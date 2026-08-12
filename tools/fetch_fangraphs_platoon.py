#!/usr/bin/env python3
"""fetch_fangraphs_platoon.py -- rebuild data/reference/fangraphs_platoon_lineups.json.

Source: FanGraphs RosterResource "Platoon Lineups", one page per team, at
``https://www.fangraphs.com/roster-resource/platoon-lineups/<slug>``. The bare
URL is the *Projected* stat set, which is what the existing reference file
records as ``stat_set``; do not append ``?statset=`` or the numbers change
meaning while the schema does not.

WHY THIS EXISTS (Ben, 2026-08-05). The platoon reference was the one input
nothing aged, and on the 1905_7g slate it was 36.9 days old. Measured against
the PIT lineup that posted that evening:

  FanGraphs (that morning)  slots 1-4 exactly right, Horwitz wrong at 5
  RotoWire (what built)     3 of 9 right, Horwitz batting LEADOFF, and he
                            was not in the game at all

Slots 1-4 carry the plate appearances a stack is bought for, so that gap is
the reason this file gets refreshed instead of aged.

ACCESS REALITY, READ BEFORE DEBUGGING A FAILURE
-----------------------------------------------
FanGraphs answers scripted requests with **HTTP 403** from at least some
non-residential IPs. It did so from the Cowork sandbox on 2026-08-05 with a
full browser User-Agent set. A 403 is the site declining automated access, and
this tool does NOT try to defeat one: no cookie replay, no proxy, no header
roulette. If you get a 403, the supported answer is ``--from-dir``.

That also revises the old project rule. ``refresh_reference_data.py`` says
"FanGraphs is manual by decision (project rule, not a technical limit)." As of
2026-08-05 it is *both*: Ben approved automated fetching, and FanGraphs may
still refuse it. This tool therefore ships two modes and treats neither as the
fallback:

  --fetch      HTTP GET each team page. Expected to work from Ben's machine.
  --from-dir   Parse pages already saved to disk. No network at all.

The parser is shared, so a page saved by hand and a page fetched over HTTP
produce byte-identical JSON.

VERIFICATION STATUS: the parser was written against the rendered table
structure of the ARI and PIT pages on 2026-08-05 and is UNVERIFIED against raw
FanGraphs HTML, because the sandbox that wrote it could not retrieve any. It
fails loudly rather than silently: a team whose two lineups do not both come
back with exactly nine slots is recorded in ``failures`` and its prior entry is
preserved. Run ``--check`` first.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

BASE_URL = "https://www.fangraphs.com/roster-resource/platoon-lineups/{slug}"
DEFAULT_REFERENCE = Path("data/reference/fangraphs_platoon_lineups.json")
DEFAULT_TIMEOUT_S = 30
DEFAULT_SLEEP_S = 2.0
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

# slug -> (full name, DK abbrev, league, division). The slug is FanGraphs'
# team-name slug and it is NOT the DK abbreviation: 'diamondbacks' not 'ARI',
# 'athletics' not 'ATH'. DK abbrevs here match mlb_engine.team_codes.
TEAMS: List[Tuple[str, str, str, str, str]] = [
    ("blue-jays",     "Toronto Blue Jays",     "TOR", "AL", "East"),
    ("orioles",       "Baltimore Orioles",     "BAL", "AL", "East"),
    ("rays",          "Tampa Bay Rays",        "TB",  "AL", "East"),
    ("red-sox",       "Boston Red Sox",        "BOS", "AL", "East"),
    ("yankees",       "New York Yankees",      "NYY", "AL", "East"),
    ("guardians",     "Cleveland Guardians",   "CLE", "AL", "Central"),
    ("royals",        "Kansas City Royals",    "KC",  "AL", "Central"),
    ("tigers",        "Detroit Tigers",        "DET", "AL", "Central"),
    ("twins",         "Minnesota Twins",       "MIN", "AL", "Central"),
    ("white-sox",     "Chicago White Sox",     "CWS", "AL", "Central"),
    ("angels",        "Los Angeles Angels",    "LAA", "AL", "West"),
    ("astros",        "Houston Astros",        "HOU", "AL", "West"),
    ("athletics",     "Athletics",             "ATH", "AL", "West"),
    ("mariners",      "Seattle Mariners",      "SEA", "AL", "West"),
    ("rangers",       "Texas Rangers",         "TEX", "AL", "West"),
    ("braves",        "Atlanta Braves",        "ATL", "NL", "East"),
    ("marlins",       "Miami Marlins",         "MIA", "NL", "East"),
    ("mets",          "New York Mets",         "NYM", "NL", "East"),
    ("nationals",     "Washington Nationals",  "WSH", "NL", "East"),
    ("phillies",      "Philadelphia Phillies", "PHI", "NL", "East"),
    ("brewers",       "Milwaukee Brewers",     "MIL", "NL", "Central"),
    ("cardinals",     "St. Louis Cardinals",   "STL", "NL", "Central"),
    ("cubs",          "Chicago Cubs",          "CHC", "NL", "Central"),
    ("pirates",       "Pittsburgh Pirates",    "PIT", "NL", "Central"),
    ("reds",          "Cincinnati Reds",       "CIN", "NL", "Central"),
    ("diamondbacks",  "Arizona Diamondbacks",  "ARI", "NL", "West"),
    ("dodgers",       "Los Angeles Dodgers",   "LAD", "NL", "West"),
    ("giants",        "San Francisco Giants",  "SF",  "NL", "West"),
    ("padres",        "San Diego Padres",      "SD",  "NL", "West"),
    ("rockies",       "Colorado Rockies",      "COL", "NL", "West"),
]

FIELDS = {
    "slot": "batting order position, 1-9",
    "position": "projected defensive position (DH included)",
    "player": "player name",
    "bats": "handedness: L=left, R=right, S=switch",
}


# --------------------------------------------------------------------------
# parsing
# --------------------------------------------------------------------------
class _TableHarvester(HTMLParser):
    """Collect every <table> as a list of rows of cell text, in document order.

    Keyed on structure, not on class names, because FanGraphs' generated class
    names are not a contract and have changed before. Heading text encountered
    between tables is recorded so a table can be attributed to the vsR or vsL
    lineup that introduces it.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: List[List[List[str]]] = []
        self.table_headings: List[str] = []
        self._heading = ""
        self._depth = 0
        self._rows: List[List[str]] = []
        self._row: List[str] = []
        self._cell: List[str] = []
        self._in_cell = False
        self._in_heading = False

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "table":
            self._depth += 1
            if self._depth == 1:
                self._rows = []
        elif tag == "tr" and self._depth:
            self._row = []
        elif tag in ("td", "th") and self._depth:
            self._in_cell = True
            self._cell = []
        elif tag in ("h1", "h2", "h3", "h4") and not self._depth:
            self._in_heading = True
            self._heading = ""

    def handle_endtag(self, tag: str) -> None:
        if tag == "table" and self._depth:
            self._depth -= 1
            if self._depth == 0:
                self.tables.append(self._rows)
                self.table_headings.append(self._heading)
                self._rows = []
        elif tag == "tr" and self._depth:
            if self._row:
                self._rows.append(self._row)
            self._row = []
        elif tag in ("td", "th") and self._depth:
            self._row.append(re.sub(r"\s+", " ", "".join(self._cell)).strip())
            self._in_cell = False
            self._cell = []
        elif tag in ("h1", "h2", "h3", "h4"):
            self._in_heading = False

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._cell.append(data)
        elif self._in_heading:
            self._heading += data


_VS_RE = re.compile(r"go-?to\s+starting\s+lineup\s*vs\.?\s*([rl])", re.I)
_BATS = {"L", "R", "S", "B"}


def _rows_to_lineup(rows: List[List[str]]) -> List[Dict[str, Any]]:
    """Pull slots 1-9 out of one rendered lineup table.

    Only an integer 1-9 in the first cell is a lineup slot. 'Bench', 'IL' and
    'PL' (paternity list) live in the same table under the same header and are
    deliberately dropped: this file feeds a projected BATTING ORDER, and a
    bench bat carries no slot.
    """
    out: List[Dict[str, Any]] = []
    seen = set()
    for row in rows:
        if len(row) < 4:
            continue
        first = row[0].strip()
        if not first.isdigit():
            continue
        slot = int(first)
        if not 1 <= slot <= 9 or slot in seen:
            continue
        position, player, bats = row[1].strip(), row[2].strip(), row[3].strip().upper()
        # The name cell renders as a link; strip any trailing stat debris.
        player = re.sub(r"\s{2,}.*$", "", player).strip()
        if not player:
            continue
        if bats not in _BATS:
            bats = ""
        seen.add(slot)
        out.append({"slot": slot, "position": position, "player": player,
                    "bats": "S" if bats == "B" else bats})
    out.sort(key=lambda r: r["slot"])
    return out


def _page_updated(html: str) -> Optional[str]:
    m = re.search(r"Updated:\s*(\d{1,2})/(\d{1,2})/(\d{4})", html)
    if m:
        mo, dy, yr = (int(x) for x in m.groups())
        return f"{yr:04d}-{mo:02d}-{dy:02d}"
    m = re.search(r"Updated:\s*[A-Za-z]+,\s*([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})", html)
    if m:
        try:
            return datetime.strptime(" ".join(m.groups()), "%B %d %Y").date().isoformat()
        except ValueError:
            return None
    return None


def parse_page(html: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Optional[str]]:
    """Return (vs_RHP, vs_LHP, page_updated) for one team page."""
    h = _TableHarvester()
    h.feed(html)

    vs_r: List[Dict[str, Any]] = []
    vs_l: List[Dict[str, Any]] = []
    current = ""
    for heading, rows in zip(h.table_headings, h.tables):
        m = _VS_RE.search(heading or "")
        if m:
            current = m.group(1).upper()
        lineup = _rows_to_lineup(rows)
        if len(lineup) != 9:
            continue
        # FanGraphs renders each lineup table twice (packed view duplicates the
        # block). First complete one per side wins; the duplicate is identical.
        if current == "R" and not vs_r:
            vs_r = lineup
        elif current == "L" and not vs_l:
            vs_l = lineup

    # Fallback for a page whose headings did not survive: two complete 9-slot
    # tables in document order are vsR then vsL, which is FanGraphs' order.
    if not vs_r or not vs_l:
        complete = []
        for rows in h.tables:
            lu = _rows_to_lineup(rows)
            if len(lu) == 9 and (not complete or lu != complete[-1]):
                complete.append(lu)
        if len(complete) >= 2:
            vs_r = vs_r or complete[0]
            vs_l = vs_l or complete[1]

    return vs_r, vs_l, _page_updated(html)


# --------------------------------------------------------------------------
# fetching
# --------------------------------------------------------------------------
class FetchRefused(RuntimeError):
    """FanGraphs declined the scripted request (403). Not retried, not worked around."""


def fetch_page(slug: str, *, timeout: int = DEFAULT_TIMEOUT_S) -> str:
    req = urllib.request.Request(BASE_URL.format(slug=slug), headers={"User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403, 429):
            raise FetchRefused(
                f"FanGraphs returned HTTP {exc.code} for {slug}. That is the site "
                f"declining automated access, and this tool does not attempt to "
                f"bypass it. Save the pages by hand and re-run with --from-dir."
            ) from exc
        raise


def _read_saved(directory: Path, slug: str) -> Optional[str]:
    for name in (f"{slug}.html", f"{slug}.htm", f"{slug}.txt"):
        p = directory / name
        if p.exists():
            return p.read_text(encoding="utf-8", errors="replace")
    return None


# --------------------------------------------------------------------------
# build
# --------------------------------------------------------------------------
def build(*, from_dir: Optional[Path], slate_date: Optional[str],
          timeout: int, sleep_s: float, only: Optional[List[str]]) -> Dict[str, Any]:
    teams: List[Dict[str, Any]] = []
    failures: List[Dict[str, str]] = []
    wanted = {a.upper() for a in only} if only else None

    for slug, name, abbrev, league, division in TEAMS:
        if wanted and abbrev.upper() not in wanted:
            continue
        try:
            html = _read_saved(from_dir, slug) if from_dir else fetch_page(slug, timeout=timeout)
            if html is None:
                failures.append({"team": abbrev, "slug": slug,
                                 "error": f"no saved page in {from_dir}"})
                continue
            vs_r, vs_l, updated = parse_page(html)
            if len(vs_r) != 9 or len(vs_l) != 9:
                failures.append({
                    "team": abbrev, "slug": slug,
                    "error": f"parsed vsR={len(vs_r)} vsL={len(vs_l)} slots, expected 9 and 9",
                })
                continue
            teams.append({
                "team": name, "slug": slug, "abbrev": abbrev,
                "league": league, "division": division,
                "page_updated": updated,
                "vs_RHP": vs_r, "vs_LHP": vs_l,
            })
        except FetchRefused:
            raise
        except Exception as exc:  # noqa: BLE001 - one bad team must not lose 29 good ones
            failures.append({"team": abbrev, "slug": slug, "error": f"{type(exc).__name__}: {exc}"})
        if not from_dir and sleep_s:
            time.sleep(sleep_s)

    return {
        "source": "FanGraphs RosterResource - Platoon Lineups",
        "url_pattern": "https://www.fangraphs.com/roster-resource/platoon-lineups/{slug}",
        "stat_set": "Projected",
        "view_mode": "Both (Packed)",
        "lineup_label": "Go-To Starting Lineup",
        "collected_date": slate_date or date.today().isoformat(),
        "collected_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "description": ("Projected batting order (slots 1-9) vs RHP and vs LHP for all 30 MLB "
                        "teams. Bench, IL and PL rows are excluded by design."),
        "fields": FIELDS,
        "team_count": len(teams),
        "teams": teams,
        "failures": failures,
    }


def merge_preserving(new: Dict[str, Any], existing_path: Path) -> Dict[str, Any]:
    """Keep the prior entry for any team this run failed, so a partial run never
    shrinks the file. A preserved team is marked so its age is not overstated."""
    if not existing_path.exists():
        return new
    try:
        old = json.loads(existing_path.read_text(encoding="utf-8"))
    except Exception:
        return new
    have = {t["abbrev"] for t in new["teams"]}
    carried = []
    for t in old.get("teams", []):
        if t.get("abbrev") not in have:
            t = dict(t)
            t["carried_forward_from"] = old.get("collected_date")
            carried.append(t)
    if carried:
        new["teams"] = sorted(new["teams"] + carried, key=lambda t: t["abbrev"])
        new["team_count"] = len(new["teams"])
        new["carried_forward"] = [t["abbrev"] for t in carried]
    return new


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--fetch", action="store_true",
                     help="GET each team page over HTTP (expect 403 off a residential IP)")
    src.add_argument("--from-dir", type=Path,
                     help="parse pages already saved here as <slug>.html; no network")
    ap.add_argument("--out", type=Path, default=DEFAULT_REFERENCE)
    ap.add_argument("--slate-date", help="value for collected_date; defaults to today")
    ap.add_argument("--only", help="comma-separated DK abbrevs, e.g. ARI,SD,DET")
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_S)
    ap.add_argument("--sleep", type=float, default=DEFAULT_SLEEP_S,
                    help="seconds between page fetches; be polite, default 2.0")
    ap.add_argument("--check", action="store_true",
                    help="parse and report, write nothing")
    ap.add_argument("--json", action="store_true", help="machine-readable report")
    args = ap.parse_args(argv)

    if not args.fetch and not args.from_dir:
        ap.error("choose --fetch or --from-dir")

    only = [s.strip() for s in args.only.split(",")] if args.only else None
    try:
        data = build(from_dir=args.from_dir, slate_date=args.slate_date,
                     timeout=args.timeout, sleep_s=args.sleep, only=only)
    except FetchRefused as exc:
        print(f"REFUSED  {exc}", file=sys.stderr)
        return 4

    ok, bad = data["team_count"], len(data["failures"])
    if not args.check:
        data = merge_preserving(data, args.out)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n",
                            encoding="utf-8")

    if args.json:
        print(json.dumps({"parsed": ok, "failed": bad,
                          "failures": data["failures"],
                          "written": None if args.check else str(args.out)}, indent=1))
    else:
        verb = "parsed" if args.check else "wrote"
        print(f"{verb} {ok} team(s), {bad} failure(s)"
              + ("" if args.check else f" -> {args.out}"))
        for f in data["failures"]:
            print(f"  FAIL {f['team']}: {f['error']}", file=sys.stderr)
        if data.get("carried_forward"):
            print(f"  carried forward from the prior file: "
                  f"{', '.join(data['carried_forward'])}", file=sys.stderr)

    return 0 if bad == 0 else 3


if __name__ == "__main__":
    raise SystemExit(main())
