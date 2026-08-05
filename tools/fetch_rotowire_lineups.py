#!/usr/bin/env python3
"""fetch_rotowire_lineups.py

MLB Classic engine tool. VERSION = "v1.0".

Fetches RotoWire's MLB Daily Lineups page over HTTP and emits a projected-order
file in the SAME schema the engine already consumes for the FanGraphs platoon
fallback (data/reference/fangraphs_platoon_lineups.json). Because the schema
matches, the output drops straight into
mlb_engine.intake.platoon_order_adapter.build_projected_order and, through it,
into live_data_adapters.build_slate_pool as `platoon_json`, with no change to any
certified engine module.

Why this exists: the MLB Stats API (and mlb.com, which renders the same API)
only shows a lineup once the team officially posts it. Any team that has not
posted reads TBD. RotoWire publishes a beat-projected "Expected Lineup" for those
teams and often confirms slightly ahead of the API. This tool fills the TBD gap
with a fresher projected order than the periodically-refreshed FanGraphs file.

Truthful labels (non-negotiable): every row here is a projected order, a labeled
prior. It is consumed ONLY through build_projected_order, which never marks these
teams confirmed, so a real posted lineup always supersedes it via
projection_builder.refresh_confirmed_lineups. Nothing here is an ROI, win-rate,
cash-rate, or probability claim. The per-team `status` field records whether
RotoWire labeled the lineup confirmed or expected at fetch time; it is metadata
for review, not a certification.

RotoWire uses its own player IDs, not MLB or DraftKings IDs. This file carries
only clean full names (from each row's title attribute); the DraftKings Player_ID
crosswalk happens downstream in build_projected_order against the authoritative
DKSalaries CSV, exactly as it does for the FanGraphs file.

This is not DraftKings. It is a public HTTP page, fetched the same way the engine
fetches the MLB Stats API and the-odds-api. It never touches draftkings.com.

Usage:
    python tools/fetch_rotowire_lineups.py [--date today|tomorrow] [--out PATH]

Importable:
    from tools.fetch_rotowire_lineups import fetch_rotowire_platoon
    platoon = fetch_rotowire_platoon(date="today")   # -> FanGraphs-schema dict
"""

from __future__ import annotations

import argparse
import datetime as dt
import html as _html
import json
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

VERSION = "v1.1"

BASE_URL = "https://www.rotowire.com/baseball/daily-lineups.php"
DEFAULT_TIMEOUT_S = 30

# R65 parse floor. This parser is regex over live third-party HTML, so a layout
# change surfaces as an EMPTY parse rather than an error, and an empty
# platoon file merges zero lineups while looking exactly like a successful
# fetch. Two collapse signals are checked, and neither of them can fire on
# legitimately thin data:
#
#   * zero game containers found on a page with real bytes in it. The game
#     containers exist whether or not lineups have posted, so this is regex
#     drift and nothing else.
#   * zero teams carrying a parsed batting order, when games WERE found.
#     Nothing to merge; writing that file records a no-op as data.
#
# What is deliberately NOT the floor is an absolute team count. The filed fix
# asked for >=24 teams; that number is a FULL slate with every lineup posted
# (the real page carries 30 on a 15-game day), and it refuses correct parses
# routinely: build_slate runs hours before lock, when most teams have not
# posted yet, and a light 9-game day is 18 teams even once they all have.
# A floor that fails closed on good data would just be turned off. ``min_teams``
# is the knob for a caller that genuinely knows the page should be full.
MIN_PAGE_BYTES = 2000
DEFAULT_MIN_TEAMS = 1


class RotoWireParseFloor(RuntimeError):
    """The page parsed to less than the caller demanded. Never write this."""
_UA = "Mozilla/5.0 (compatible; mlb-dfs-engine/1.0; +local)"

# Repo root on sys.path so the engine's canonical team-code normalizer can be
# reused rather than re-implemented (keeps ARI/AZ, TB/TBR, SD/SDP consistent with
# the salary join). Falls back to identity only if the engine is unavailable.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
try:
    from mlb_engine.intake.live_data_adapters import to_dk_abbrev as _to_dk_abbrev
except Exception:  # pragma: no cover - engine should always be importable in-repo
    def _to_dk_abbrev(code: str) -> str:
        return str(code or "").strip().upper()


# --------------------------------------------------------------------------- #
# Fetch
# --------------------------------------------------------------------------- #
def fetch_html(date: str = "today", *, timeout: int = DEFAULT_TIMEOUT_S) -> str:
    """Return the raw RotoWire daily-lineups HTML. date is 'today' or 'tomorrow'."""
    url = BASE_URL + ("?date=tomorrow" if str(date).lower() == "tomorrow" else "")
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


# --------------------------------------------------------------------------- #
# Parse
# --------------------------------------------------------------------------- #
# One game container. RotoWire ships a hidden template with the same outer class,
# so blocks that carry no visitor list are skipped downstream.
_GAME_SPLIT = re.compile(r'<div class="lineup is-mlb')
_ABBR = re.compile(r'lineup__abbr[^>]*>\s*([A-Za-z0-9]{2,3})\s*<')
_VISIT_ANCHOR = 'lineup__list is-visit'
_HOME_ANCHOR = 'lineup__list is-home'
# pos, full name (title attr), bats -- in batting-order sequence.
_PLAYER = re.compile(
    r'lineup__pos">\s*(?P<pos>[A-Z0-9]{1,3})\s*</div>\s*'
    r'<a[^>]*title="(?P<name>[^"]+)"[^>]*>.*?</a>\s*'
    r'<span class="lineup__bats">\s*(?P<bats>[A-Za-z]{1,2})\s*</span>',
    re.S,
)


def _status_of(chunk: str) -> str:
    if "lineup__status is-confirmed" in chunk:
        return "confirmed"
    if "lineup__status is-expected" in chunk:
        return "expected"
    return "unknown"


def _players_from(chunk: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for slot, m in enumerate(_PLAYER.finditer(chunk), start=1):
        rows.append({
            "slot": slot,
            "position": m.group("pos").strip(),
            "player": _html.unescape(m.group("name").strip()),
            "bats": m.group("bats").strip().upper(),
        })
    return rows


def parse_lineups(page_html: str, *,
                  report: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Parse the page into per-team dicts: abbrev, status, and the 9-row order.

    Pass a ``report`` dict to receive the structural counts the parse floor
    reads: ``page_bytes``, ``blocks`` (raw splits), ``games`` (blocks carrying
    both a visitor and a home list), ``teams_with_order``, and
    ``teams_without_order`` (a game container whose lineup has not posted yet,
    which is normal and not a failure).
    """
    teams: List[Dict[str, Any]] = []
    parts = _GAME_SPLIT.split(page_html)
    games = 0
    no_order = 0
    for block in parts[1:]:  # parts[0] is everything before the first game
        vi = block.find(_VISIT_ANCHOR)
        hi = block.find(_HOME_ANCHOR)
        if vi == -1 or hi == -1:
            continue  # template / non-game block
        games += 1
        abbrs = _ABBR.findall(block[:vi] or block[:2000])
        if len(abbrs) < 2:
            # Abbrevs can trail the anchor in some layouts; widen the search.
            abbrs = _ABBR.findall(block[:hi + 400])
        if len(abbrs) < 2:
            continue
        visit_abbr, home_abbr = abbrs[0], abbrs[1]
        visit_chunk = block[vi:hi]
        home_chunk = block[hi:]
        for abbr, chunk in ((visit_abbr, visit_chunk), (home_abbr, home_chunk)):
            players = _players_from(chunk)
            if not players:
                no_order += 1
                continue
            teams.append({
                "abbrev": _to_dk_abbrev(abbr),
                "raw_abbrev": abbr,
                "status": _status_of(chunk),
                "players": players,
            })
    if report is not None:
        report.update({
            "page_bytes": len(page_html or ""),
            "blocks": max(0, len(parts) - 1),
            "games": games,
            "teams_with_order": len(teams),
            "teams_without_order": no_order,
        })
    return teams


# --------------------------------------------------------------------------- #
# Emit FanGraphs-compatible platoon schema
# --------------------------------------------------------------------------- #
def to_platoon_schema(teams: List[Dict[str, Any]], collected_date: str) -> Dict[str, Any]:
    """Wrap parsed teams in the schema build_projected_order expects.

    RotoWire posts one lineup per team for tonight's specific matchup, already
    accounting for the opposing starter's hand. There is no separate vs_RHP /
    vs_LHP split, so both views carry the identical tonight order; the engine's
    handedness view selection then becomes a harmless no-op.
    """
    out_teams: List[Dict[str, Any]] = []
    for t in teams:
        rows = [
            {"slot": p["slot"], "position": p["position"],
             "player": p["player"], "bats": p["bats"]}
            for p in t["players"]
        ]
        out_teams.append({
            "abbrev": t["abbrev"],
            "status": t["status"],
            "page_updated": collected_date,
            "vs_RHP": rows,
            "vs_LHP": list(rows),
        })
    return {
        "source": "RotoWire - MLB Daily Lineups",
        "url": BASE_URL,
        "tool_version": VERSION,
        "stat_set": "Projected/Confirmed (as posted at fetch time)",
        "lineup_label": "RotoWire tonight order",
        "collected_date": collected_date,
        "description": (
            "Projected batting order (slots 1-9) for tonight, one lineup per team. "
            "vs_RHP and vs_LHP hold the same order because RotoWire posts a single "
            "matchup-specific lineup. 'status' is confirmed or expected as RotoWire "
            "labeled it. Consumed only through build_projected_order as a projected "
            "order; a real posted lineup supersedes it. Not a probability claim."
        ),
        "fields": {
            "slot": "batting order position, 1-9",
            "position": "listed defensive position (DH included)",
            "player": "player full name (RotoWire title attribute)",
            "bats": "handedness: L=left, R=right, S=switch",
        },
        "team_count": len(out_teams),
        "teams": out_teams,
    }


def check_parse_floor(report: Dict[str, Any], min_teams: int = DEFAULT_MIN_TEAMS) -> None:
    """Raise RotoWireParseFloor when the parse collapsed. Returns None when it did not.

    See MIN_PAGE_BYTES / DEFAULT_MIN_TEAMS for why the two signals are these two
    and not an absolute team count (R65).
    """
    page_bytes = int(report.get("page_bytes") or 0)
    games = int(report.get("games") or 0)
    with_order = int(report.get("teams_with_order") or 0)
    if page_bytes >= MIN_PAGE_BYTES and games == 0:
        raise RotoWireParseFloor(
            f"parsed 0 game containers from {page_bytes} bytes of HTML "
            f"({report.get('blocks', 0)} raw blocks): the page layout moved and "
            "the lineup regexes no longer match. Refusing to emit an empty "
            "platoon file that would read as a successful fetch."
        )
    if with_order < min_teams:
        raise RotoWireParseFloor(
            f"parsed {with_order} team lineups (floor {min_teams}) from {games} "
            f"games; {report.get('teams_without_order', 0)} game containers had no "
            "posted order. Refusing to emit a platoon file with nothing to merge."
        )


def fetch_rotowire_platoon(date: str = "today", *,
                           timeout: int = DEFAULT_TIMEOUT_S,
                           collected_date: Optional[str] = None,
                           min_teams: int = DEFAULT_MIN_TEAMS,
                           parse_report: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Fetch + parse + wrap in one call. Returns the FanGraphs-schema dict.

    Raises RotoWireParseFloor when the parse collapsed, rather than returning a
    zero-team document (R65). ``collected_date`` defaults to today in ET, not to
    the container's calendar, because the date being stamped is a slate date.
    """
    page = fetch_html(date, timeout=timeout)
    report: Dict[str, Any] = {} if parse_report is None else parse_report
    teams = parse_lineups(page, report=report)
    check_parse_floor(report, min_teams=min_teams)
    from mlb_engine.repo_env import today_et
    cd = collected_date or today_et()
    out = to_platoon_schema(teams, cd)
    out["parse_report"] = dict(report)
    return out


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Fetch RotoWire MLB projected lineups.")
    ap.add_argument("--date", default="today", choices=["today", "tomorrow"],
                    help="RotoWire only serves today and tomorrow.")
    ap.add_argument("--out", help="Write the platoon-schema JSON here.")
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_S)
    ap.add_argument("--min-teams", type=int, default=DEFAULT_MIN_TEAMS,
                    dest="min_teams",
                    help="refuse to emit fewer than this many parsed lineups "
                         "(exit 2, nothing written). Raise it when you know the "
                         "page should be full; the default only catches collapse.")
    args = ap.parse_args(argv)

    try:
        data = fetch_rotowire_platoon(args.date, timeout=args.timeout,
                                      min_teams=args.min_teams)
    except RotoWireParseFloor as exc:
        # Exit 2 and write NOTHING: an empty platoon file on disk is worse than
        # no file, because the next build merges it and reports success (R65).
        print(f"PARSE FLOOR: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"ERROR fetching RotoWire: {exc}", file=sys.stderr)
        return 1

    teams = data["teams"]
    conf = sum(1 for t in teams if t["status"] == "confirmed")
    exp = sum(1 for t in teams if t["status"] == "expected")
    unk = sum(1 for t in teams if t["status"] == "unknown")
    pr = data.get("parse_report") or {}
    print(f"RotoWire {args.date}: {len(teams)} teams "
          f"({conf} confirmed, {exp} expected, {unk} unknown) "
          f"from {pr.get('games', '?')} games, "
          f"{pr.get('teams_without_order', '?')} without a posted order")
    for t in teams:
        n = len(t["vs_RHP"])
        flag = "" if n == 9 else f"  <-- {n}/9 rows"
        print(f"  {t['abbrev']:<4} {t['status']:<9} {n} hitters{flag}")

    if args.out:
        Path(args.out).write_text(json.dumps(data, indent=2, ensure_ascii=False),
                                  encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(json.dumps(data, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
