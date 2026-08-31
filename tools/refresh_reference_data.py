#!/usr/bin/env python3
"""refresh_reference_data.py — keep the projection enrichment inputs fresh.

The engine's three season-rate enrichment inputs live in ``data/reference/``:

  * ``expected_stats_batting.csv``  — Baseball Savant expected statistics
    (batter). Feeds the xwOBA Base correction and the xISO hitter ceiling.
  * ``expected_stats_pitching.csv`` — Baseball Savant expected statistics
    (pitcher). Feeds the same correction on the pitcher side AND the opposing-SP
    quality component of the deterministic F4 matchup factor.
  * ``statsapi_season_pitching.csv`` — MLB StatsAPI season pitching, every
    pitcher (``playerPool=All``). Feeds the K-rate pitcher ceiling.

These are season-long rates, so a weekly refresh is plenty. What they are NOT is
optional: a build whose reference files are missing or months old silently
degrades to ranking players on AvgPointsPerGame, which certifies exactly as
cleanly as a build on real signal. That is the whole reason this script and the
staleness stamp exist — the freshness of these files is not observable anywhere
else in the pipeline.

All three are fetched over HTTP, validated before anything is overwritten, and
stamped with the fetch time. **Nothing here is manual any more (R278).** The
K-rate input used to be a hand-run FanGraphs export, which is why it was the one
file that reliably went stale — 45.2 days old against a 14-day limit on the day
it was replaced — and why its ``qual=y`` URL silently held the file to 211 arms
against Savant's 831. MLB StatsAPI answers the same question with no
qualification filter, no membership gate, and no human in the loop.

Nothing here is a projection, an edge, or a probability claim. These are
published observed season rates; every factor derived from them downstream is a
labeled deterministic prior.

Usage:
  python tools/refresh_reference_data.py                # fetch Savant, report all
  python tools/refresh_reference_data.py --check        # report only, fetch nothing
  python tools/refresh_reference_data.py --year 2026
  python tools/refresh_reference_data.py --max-age-days 14
  python tools/refresh_reference_data.py --json
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

VERSION = "1.0.0"

REPO = Path(__file__).resolve().parents[1]
REFERENCE_DIR = REPO / "data" / "reference"
MANIFEST_NAME = "reference_manifest.json"

# Past this age the enrichment inputs are treated as stale: the build still runs,
# but it says so loudly in the brief rather than pretending it had signal.
DEFAULT_MAX_AGE_DAYS = 14

TIMEOUT = 25.0
USER_AGENT = "mlb-dfs-engine/refresh_reference_data"

SAVANT_EXPECTED = (
    "https://baseballsavant.mlb.com/leaderboard/expected_statistics"
    "?type={kind}&year={year}&position=&team=&filterType=bip&min={min_pa}&csv=true"
)

# Savant's default `min=q` restricts the export to QUALIFIED players: 255 batters
# in 2026 against 602 at min=1. That default was silently costing more than half
# the enrichment coverage, because a DK slate is full of part-time and recently
# called-up hitters who never qualify. Pulling the long tail is safe here: the
# engine PA-shrinks every rate toward 1.0 and returns exactly 1.0 below
# XWOBA_PA_MIN, so a thin sample contributes proportionally little and a very
# thin one contributes nothing. What it cannot do is shrink a row it never saw.
DEFAULT_MIN_PA = "1"

# R278. The K-rate side moved off FanGraphs entirely. The old source was a
# MANUAL export whose URL carried `qual=y`, which is why the file held 211 arms
# against Savant's 831 and why every non-qualified starter took the neutral
# multiplier all season (R277). Widening that export was the filed fix and it was
# NOT taken: the one-click CSV is a FanGraphs membership feature, the data behind
# it is free to read but the export is the gated thing, and rebuilding it by
# automation is doing the gated thing by another route.
#
# MLB StatsAPI answers the same question with no gate and no membership. It is
# already a dependency of this repo (tools/fetch_slate_bundle.py reads the
# schedule and people endpoints from the same host), `playerPool=All` has no
# qualification filter to get wrong, and it carries two fields the FanGraphs
# export never did: a REAL batters-faced count, replacing the IP x 4.25 proxy at
# exactly the sample sizes where the proxy was worst, and the MLBAM id, which is
# the key `expected_stats_pitching.csv` is already joined on.
#
# Three sources agree on the population: StatsAPI 834, FanGraphs at qual=0 832,
# Savant at min=1 831. Rank agreement between StatsAPI and the FanGraphs file was
# measured at Spearman 0.980 over the 40 highest-IP arms, implying a maximum
# multiplier move of 0.045 -- under the 0.05 bar, and that residual still
# contains an unknown date gap, so the true source disagreement is smaller.
STATSAPI_PITCHING = (
    "https://statsapi.mlb.com/api/v1/stats"
    "?stats=season&group=pitching&season={year}&playerPool=All&sportId=1"
    "&limit={limit}&offset={offset}"
)
STATSAPI_PAGE_SIZE = 250
STATSAPI_MAX_ROWS = 5000

# Emitted column order. `Name` keeps the existing DK name crosswalk working
# unchanged; `MLBAM_ID` is carried so the join can move off names later without
# another fetch change.
STATSAPI_COLUMNS = ["Name", "MLBAM_ID", "Team", "G", "GS", "IP", "TBF", "SO", "K/9"]

# Columns each file must actually contain for the enrichment it feeds to work.
# Checked before anything is written, so a redirect to an HTML error page or a
# silently-changed export cannot overwrite a good file with garbage.
REQUIRED_COLUMNS: Dict[str, List[str]] = {
    "expected_stats_batting.csv": ["player_id", "pa", "woba", "est_woba"],
    "expected_stats_pitching.csv": ["player_id", "pa", "woba", "est_woba"],
    "statsapi_season_pitching.csv": ["Name", "IP", "K/9", "GS", "TBF"],
}

SAVANT_TARGETS = {
    "expected_stats_batting.csv": "batter",
    "expected_stats_pitching.csv": "pitcher",
}

STATSAPI_TARGETS = {
    "statsapi_season_pitching.csv": STATSAPI_PITCHING,
}

# R278. Empty, and that is the change. This held the FanGraphs pitching export,
# the last reference input a human had to fetch by hand -- which is why it was
# 45.2 days old against a 14-day limit on the day it was replaced. Nothing is
# manual now. Kept as a table rather than deleted because `reference_status`
# still branches on it and a future manual source would go here.
MANUAL_TARGETS: Dict[str, str] = {}

# R127(b). What each CSV actually FEEDS, in the words of the thing it moves.
# The stale warning used to read "season rates are drifting", which names a
# property of the file and nothing about the build: on 2026-08-15 it led BUILD
# to report that a 30-day-old file had not touched the build, when it feeds the
# pitcher K-rate ceiling and is exactly what would have caught the arm that
# kept the neutral multiplier and took 9 of 19 lineups. TRACKED_JSON already
# carried a `feeds` string; the CSVs did not.
CSV_FEEDS: Dict[str, str] = {
    "expected_stats_batting.csv":
        "the xwOBA Base correction and the xISO hitter ceiling multipliers",
    "expected_stats_pitching.csv":
        "the xwOBA Base correction on pitcher rows and the F4 opposing-SP quality term",
    "statsapi_season_pitching.csv":
        "the K-rate pitcher ceiling multipliers, the only factor that separates arms "
        "in a ceiling-scored build",
}

# R277. MEMBERSHIP, not age. Which players a reference file lists is set by the
# filter its export carries, and a pull made this morning is exactly as
# incomplete as a month-old one when both were pulled through the same filter.
# That fact used to ride the STALENESS branch below, where it printed the export
# URL as the remedy -- and re-exporting the same URL returns the same roster, so
# the remedy reproduced the condition it was offered for. On 2026-08-15 and again
# on 2026-08-16 an arm's absence was read as staleness on exactly that warning.
# An entry here says: this file's source drops players by rule, and here is the
# rule. No entry means the pull is unfiltered. DELETING an entry is part of
# widening the pull it describes, which is what makes this table go stale loudly.
#
# R278: EMPTY, one day later, and by that mechanism working as designed. The
# single entry described `fangraphs_season_pitching.csv`'s `qual=y`; the source
# moved to MLB StatsAPI with `playerPool=All`, there is no qualification filter
# left to declare, and the entry left with the file it described rather than
# surviving to describe a filter nothing carries. An empty table here is a claim:
# no reference pull currently drops players by rule.
SOURCE_MEMBERSHIP_FILTER: Dict[str, str] = {}

FANGRAPHS_ROSTER_RESOURCE_URL = (
    "https://www.fangraphs.com/roster-resource/depth-charts"
)

# F17. JSON reference inputs this tool reports on but never fetches. The platoon
# file is manual by decision and it was the one reference nothing aged: it is
# absent from REQUIRED_COLUMNS, absent from the manifest, and the only staleness
# measurement anywhere compared it to its own collected_date, which is the one
# date it cannot be stale against. Age comes from the payload's own
# ``collected_date`` rather than mtime, because a checkout or a copy resets
# mtime and would report a month-old file as fresh.
TRACKED_JSON: Dict[str, Dict[str, Any]] = {
    "fangraphs_platoon_lineups.json": {
        "source": FANGRAPHS_ROSTER_RESOURCE_URL,
        "max_age_days": 7,
        "date_key": "collected_date",
        "feeds": "the TBD-team projected batting order in build_slate_pool",
    },
}


# --------------------------------------------------------------------------- #
# Stamp handling
# --------------------------------------------------------------------------- #
def _now() -> datetime:
    return datetime.now(timezone.utc)


def load_manifest(reference_dir: Path = REFERENCE_DIR) -> Dict[str, Any]:
    path = Path(reference_dir) / MANIFEST_NAME
    if not path.exists():
        return {}
    try:
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _write_manifest(manifest: Dict[str, Any], reference_dir: Path) -> None:
    path = Path(reference_dir) / MANIFEST_NAME
    manifest["manifest_version"] = VERSION
    manifest["note"] = (
        "Fetched-date stamps for the projection enrichment inputs. Written by "
        "tools/refresh_reference_data.py; read by the build to decide whether the "
        "enrichment inputs are fresh enough to trust. Files with no entry here "
        "fall back to filesystem mtime, which is a floor on their true age."
    )
    with path.open("w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=1, sort_keys=True)
        fh.write("\n")


def _stamp(manifest: Dict[str, Any], name: str, source: str, rows: int,
           reference_dir: Path) -> None:
    files = manifest.setdefault("files", {})
    files[name] = {
        "fetched_at": _now().isoformat(),
        "source": source,
        "rows": rows,
    }
    _write_manifest(manifest, reference_dir)


# --------------------------------------------------------------------------- #
# Status reporting. This is the part build_slate.py consumes.
# --------------------------------------------------------------------------- #
def _age_days(stamp: Optional[str], path: Path) -> Optional[float]:
    """Age in days, preferring the recorded fetch time over filesystem mtime.

    mtime is only a floor on true age (a copy or a checkout resets it), so it is
    used solely as a fallback for files that predate the manifest.
    """
    when: Optional[datetime] = None
    if stamp:
        try:
            when = datetime.fromisoformat(str(stamp))
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
        except ValueError:
            when = None
    if when is None:
        if not path.exists():
            return None
        when = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return (_now() - when).total_seconds() / 86400.0


def _json_payload_age_days(path: Path, date_key: str) -> Optional[float]:
    """Age in days from a date stamped inside the JSON payload itself.

    Filesystem mtime is not usable here: a git checkout or a copy resets it, and
    this file's whole failure mode is reading as fresh when it is not.
    """
    if not path.exists():
        return None
    try:
        with path.open(encoding="utf-8") as fh:
            payload = json.load(fh)
        stamp = str((payload or {}).get(date_key) or "")[:10]
        y, m, d = (int(x) for x in stamp.split("-"))
    except (OSError, ValueError, json.JSONDecodeError, AttributeError, TypeError):
        return None
    stamped = datetime(y, m, d, tzinfo=timezone.utc)
    return (_now() - stamped).total_seconds() / 86400.0


def _header_columns(path: Path) -> Optional[List[str]]:
    """First CSV row as a stripped column list, or None if it cannot be read.

    R277. ``REQUIRED_COLUMNS`` is enforced by ``_validate`` on the FETCH path
    only, so the one file nobody fetches -- the manual FanGraphs export -- was
    the one file whose column list nothing ever checked. That entry read as a
    guard and was decoration, and it matters most exactly when the manual export
    changes shape under a hand re-pull.
    """
    try:
        with path.open(encoding="utf-8-sig", newline="") as fh:
            row = next(csv.reader(fh), None)
    except (OSError, UnicodeDecodeError, csv.Error, StopIteration):
        return None
    if row is None:
        return None
    return [c.strip().strip('"') for c in row]


def reference_status(reference_dir: Path = REFERENCE_DIR,
                     max_age_days: float = DEFAULT_MAX_AGE_DAYS) -> Dict[str, Any]:
    """Report presence, age, and staleness for every enrichment input.

    Returns ``{"files": {name: {...}}, "usable": bool, "warnings": [...]}``.
    ``usable`` means every file exists; stale files are still usable and still
    passed to the build, because degraded signal beats no signal — but the
    warnings ride into the brief so the operator sees it.

    R277. A CSV entry carries three INDEPENDENT conditions, because they have
    three different causes and three different remedies, and collapsing them is
    what let an arm absent by qualification be reported as staleness twice:

      * ``stale`` — age. Remedy: a fresh pull.
      * ``membership_filtered`` — the export's own filter drops players by rule
        (``SOURCE_MEMBERSHIP_FILTER``). Age-independent; a fresh pull through
        the same filter returns the same roster. Remedy: widen the pull.
      * ``missing_columns`` — the file is the wrong shape for what it feeds.
        Remedy: re-export, and check the export type.
    """
    reference_dir = Path(reference_dir)
    manifest_files = (load_manifest(reference_dir).get("files") or {})
    out: Dict[str, Any] = {"files": {}, "warnings": [], "max_age_days": max_age_days}
    for name in REQUIRED_COLUMNS:
        path = reference_dir / name
        stamped = (manifest_files.get(name) or {}).get("fetched_at")
        age = _age_days(stamped, path)
        exists = path.exists() and path.stat().st_size > 0
        stale = bool(exists and age is not None and age > max_age_days)
        out["files"][name] = {
            "path": str(path),
            "exists": exists,
            "age_days": round(age, 1) if age is not None else None,
            "age_basis": "fetched_at" if stamped else "mtime",
            "stale": stale,
            "manual": name in MANUAL_TARGETS,
        }
        if not exists:
            out["warnings"].append(
                f"{name}: missing from data/reference/; it feeds "
                f"{CSV_FEEDS.get(name, 'projection enrichment')}, which is OFF "
                f"for this build. Run tools/refresh_reference_data.py"
                + (f" or export it manually from {MANUAL_TARGETS[name]}"
                   if name in MANUAL_TARGETS else "")
            )
        elif stale:
            how = (f"export it manually from {MANUAL_TARGETS[name]}"
                   if name in MANUAL_TARGETS
                   else "run tools/refresh_reference_data.py")
            # R277. This branch keeps only the incompleteness AGE causes -- a
            # player who arrived after the pull -- because that is the half a
            # fresh pull actually reaches. Absence by the export's own filter is
            # a different cause with a different remedy and is reported below,
            # whatever this file's age.
            out["warnings"].append(
                f"{name}: {out['files'][name]['age_days']} days old "
                f"(limit {max_age_days}); it feeds "
                f"{CSV_FEEDS.get(name, 'projection enrichment')}. Age costs "
                f"MEMBERSHIP as well as accuracy: a player who debuted or was "
                f"called up after the pull is absent, takes the neutral default, "
                f"and is named in enrichment['neutral_default']. "
                f"{how[0].upper()}{how[1:]}"
            )
        # Membership by FILTER, reported whether the file is fresh or stale,
        # because its cause is the export URL and not the clock.
        membership = SOURCE_MEMBERSHIP_FILTER.get(name)
        out["files"][name]["membership_filtered"] = bool(exists and membership)
        if exists and membership:
            out["warnings"].append(
                f"{name}: INCOMPLETE BY FILTER, independent of age -- "
                f"{membership}. It feeds "
                f"{CSV_FEEDS.get(name, 'projection enrichment')}; every player "
                f"it omits is named in enrichment['neutral_default']."
            )
        # REQUIRED_COLUMNS enforced on a file this tool did not fetch.
        if exists:
            header = _header_columns(path)
            if header is None:
                missing_cols = list(REQUIRED_COLUMNS[name])
                out["warnings"].append(
                    f"{name}: header unreadable, so none of "
                    f"{', '.join(REQUIRED_COLUMNS[name])} could be confirmed; it "
                    f"feeds {CSV_FEEDS.get(name, 'projection enrichment')}"
                )
            else:
                missing_cols = [c for c in REQUIRED_COLUMNS[name] if c not in header]
                if missing_cols:
                    out["warnings"].append(
                        f"{name}: missing required column(s) "
                        f"{', '.join(missing_cols)} (header carries "
                        f"{len(header)}); it feeds "
                        f"{CSV_FEEDS.get(name, 'projection enrichment')}, which "
                        f"will fail or silently neutralize on this file"
                    )
            out["files"][name]["missing_columns"] = missing_cols
    for name, spec in TRACKED_JSON.items():
        path = reference_dir / name
        limit = float(spec.get("max_age_days") or max_age_days)
        exists = path.exists() and path.stat().st_size > 0
        age = _json_payload_age_days(path, str(spec.get("date_key") or "collected_date"))
        stale = bool(exists and age is not None and age > limit)
        out["files"][name] = {
            "path": str(path),
            "exists": exists,
            "age_days": round(age, 1) if age is not None else None,
            "age_basis": spec.get("date_key") or "collected_date",
            "stale": stale,
            "manual": True,
            "max_age_days": limit,
        }
        if not exists:
            out["warnings"].append(
                f"{name}: missing from data/reference/; {spec.get('feeds')} has no "
                f"source. Rebuild it from {spec.get('source')}"
            )
        elif age is None:
            out["warnings"].append(
                f"{name}: no {spec.get('date_key')} in the payload, so its age is "
                f"unknown; it cannot be aged against a slate"
            )
        elif stale:
            out["warnings"].append(
                f"{name}: {out['files'][name]['age_days']} days old "
                f"(limit {limit}); it feeds {spec.get('feeds')}. Rebuild it from "
                f"{spec.get('source')}"
            )
    out["usable"] = all(f["exists"] for f in out["files"].values())
    out["any_stale"] = any(f["stale"] for f in out["files"].values())
    return out


# --------------------------------------------------------------------------- #
# Fetch
# --------------------------------------------------------------------------- #
def _validate(text: str, name: str) -> int:
    """Return the row count, or raise ValueError if the payload is not the file
    we asked for. Validate BEFORE overwriting: an HTML error page that lands on
    top of a good CSV costs a slate, and it does so silently."""
    reader = csv.DictReader(io.StringIO(text))
    header = [h.strip().strip('"') for h in (reader.fieldnames or [])]
    missing = [c for c in REQUIRED_COLUMNS[name] if c not in header]
    if missing:
        raise ValueError(
            f"payload is not the expected {name}: missing column(s) "
            f"{', '.join(missing)} (got {len(header)} columns)"
        )
    rows = sum(1 for _ in reader)
    if rows < 50:
        raise ValueError(f"payload has only {rows} data rows; refusing to overwrite")
    return rows


def fetch_savant(kind: str, year: int, min_pa: str = DEFAULT_MIN_PA) -> str:
    url = SAVANT_EXPECTED.format(kind=kind, year=year, min_pa=min_pa)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return response.read().decode("utf-8-sig")


def innings_to_float(value: Any) -> Optional[float]:
    """Baseball innings notation to a true decimal: ``.1`` is a THIRD, not a tenth.

    R278. Both FanGraphs and MLB StatsAPI write 148 and one third as ``148.1``,
    so ``float("148.1")`` is wrong by up to 0.23 innings and always in the same
    direction. The old path never noticed because the only consumer of IP was the
    ``IP * K_RATE_TBF_PER_IP`` batters-faced PROXY, where a 0.2% error hid inside
    a 4.25 fudge factor. This emitter resolves the thirds once, at the boundary,
    so no downstream reader has to know the convention -- and the file also
    carries a REAL ``TBF``, so nothing has to use the proxy at all.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if "." not in text:
        try:
            return float(text)
        except ValueError:
            return None
    whole, frac = text.split(".", 1)
    try:
        base = float(whole)
    except ValueError:
        return None
    return base + {"0": 0.0, "1": 1.0 / 3.0, "2": 2.0 / 3.0}.get(frac[:1], 0.0)


def statsapi_rows_to_csv(splits: List[Dict[str, Any]]) -> str:
    """Render StatsAPI pitching splits as the season pitching CSV the engine reads.

    One row per pitcher with a positive IP. ``K/9`` is computed here as
    ``9 * SO / IP`` off the official counting stats rather than taken from the
    API's own pre-rounded ``strikeoutsPer9Inn``, so the rank the multiplier
    consumes is not decided by a two-decimal string. ``IP`` is a true decimal
    (see ``innings_to_float``), NOT the ``.1``-is-a-third notation the FanGraphs
    export used, and that is a deliberate semantic change carried by the rename.
    """
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(STATSAPI_COLUMNS)
    seen: set = set()
    for split in splits:
        stat = split.get("stat") or {}
        player = split.get("player") or {}
        innings = innings_to_float(stat.get("inningsPitched"))
        strikeouts = stat.get("strikeOuts")
        if not innings or innings <= 0 or strikeouts is None:
            continue
        pid = str(player.get("id") or "").strip()
        if pid in seen:
            continue
        seen.add(pid)
        team = ((split.get("team") or {}).get("abbreviation")
                or (split.get("team") or {}).get("name") or "")
        writer.writerow([
            player.get("fullName") or "",
            pid,
            team,
            stat.get("gamesPlayed") or 0,
            stat.get("gamesStarted") or 0,
            f"{innings:.4f}",
            stat.get("battersFaced") if stat.get("battersFaced") is not None else "",
            strikeouts,
            f"{9.0 * float(strikeouts) / innings:.4f}",
        ])
    return out.getvalue()


def fetch_statsapi_pitching(year: int, page_size: int = STATSAPI_PAGE_SIZE,
                            opener=None) -> str:
    """Fetch every pitcher's season line from MLB StatsAPI and render it as CSV.

    R278. This replaces a MANUAL FanGraphs export whose URL carried ``qual=y``.
    ``playerPool=All`` is the whole point: there is no qualification filter to
    get wrong, so the coverage defect cannot come back through a parameter.
    Paginated because the response is capped server-side; the loop stops when a
    page returns nothing or ``totalSplits`` is covered, and it REFUSES a short
    read rather than writing a partial league, since a partial league is exactly
    the condition this change exists to remove.
    """
    fetch = opener or _read_url
    collected: List[Dict[str, Any]] = []
    total: Optional[int] = None
    offset = 0
    while True:
        url = STATSAPI_PITCHING.format(year=year, limit=page_size, offset=offset)
        payload = json.loads(fetch(url))
        blocks = payload.get("stats") or []
        splits = (blocks[0].get("splits") or []) if blocks else []
        if total is None and blocks:
            total = blocks[0].get("totalSplits")
        if not splits:
            break
        collected.extend(splits)
        offset += len(splits)
        if total is not None and offset >= int(total):
            break
        if offset > STATSAPI_MAX_ROWS:
            raise ValueError(
                f"StatsAPI pagination exceeded {STATSAPI_MAX_ROWS} rows; refusing "
                "to loop"
            )
    if total is not None and len(collected) < int(total):
        raise ValueError(
            f"StatsAPI returned {len(collected)} of {total} pitcher rows; refusing "
            "to overwrite with a partial league"
        )
    return statsapi_rows_to_csv(collected)


def _read_url(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return response.read().decode("utf-8")


def refresh(reference_dir: Path = REFERENCE_DIR, year: Optional[int] = None,
            targets: Optional[List[str]] = None,
            min_pa: str = DEFAULT_MIN_PA) -> Dict[str, Any]:
    """Fetch the Savant files. Each fetch fails independently; a failure leaves
    the existing file untouched and is reported."""
    reference_dir = Path(reference_dir)
    reference_dir.mkdir(parents=True, exist_ok=True)
    year = year or _now().year
    manifest = load_manifest(reference_dir)
    result: Dict[str, Any] = {"fetched": [], "failed": [], "skipped": []}

    for name, kind in SAVANT_TARGETS.items():
        if targets and name not in targets:
            result["skipped"].append(name)
            continue
        try:
            text = fetch_savant(kind, year, min_pa=min_pa)
            rows = _validate(text, name)
        except (urllib.error.URLError, ValueError, TimeoutError, OSError) as exc:
            result["failed"].append({"file": name, "error": str(exc)})
            continue
        (reference_dir / name).write_text(text, encoding="utf-8")
        _stamp(manifest, name,
               f"baseballsavant expected_statistics {kind} {year} min={min_pa}",
               rows, reference_dir)
        result["fetched"].append({"file": name, "rows": rows, "year": year})

    # R278. The K-rate input, fetched rather than hand-exported. Same
    # fail-independently discipline as Savant: validate before overwriting, and a
    # failure leaves the existing file alone and is reported.
    for name in STATSAPI_TARGETS:
        if targets and name not in targets:
            result["skipped"].append(name)
            continue
        try:
            text = fetch_statsapi_pitching(year)
            rows = _validate(text, name)
        except (urllib.error.URLError, ValueError, TimeoutError, OSError,
                json.JSONDecodeError, KeyError) as exc:
            result["failed"].append({"file": name, "error": str(exc)})
            continue
        (reference_dir / name).write_text(text, encoding="utf-8")
        _stamp(manifest, name,
               f"mlb statsapi season pitching {year} playerPool=All",
               rows, reference_dir)
        result["fetched"].append({"file": name, "rows": rows, "year": year})

    for name in MANUAL_TARGETS:
        result["skipped"].append(name)
    return result


# --------------------------------------------------------------------------- #
def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true",
                        help="report status only; fetch nothing")
    parser.add_argument("--year", type=int, default=None,
                        help="Savant season (default: current year)")
    parser.add_argument("--min-pa", default=DEFAULT_MIN_PA,
                        help="Savant minimum-PA filter; 'q' for qualified only "
                             f"(default {DEFAULT_MIN_PA}, which pulls the long tail "
                             "and lets the engine's PA shrinkage do the filtering)")
    parser.add_argument("--max-age-days", type=float, default=DEFAULT_MAX_AGE_DAYS)
    parser.add_argument("--reference-dir", default=str(REFERENCE_DIR))
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    reference_dir = Path(args.reference_dir)
    payload: Dict[str, Any] = {"version": VERSION}
    if not args.check:
        payload["refresh"] = refresh(reference_dir, year=args.year, min_pa=args.min_pa)
    payload["status"] = reference_status(reference_dir, max_age_days=args.max_age_days)

    if args.json:
        print(json.dumps(payload, indent=1))
    else:
        refreshed = payload.get("refresh") or {}
        for item in refreshed.get("fetched", []):
            print(f"fetched  {item['file']}  {item['rows']} rows  ({item['year']})")
        for item in refreshed.get("failed", []):
            print(f"FAILED   {item['file']}: {item['error']}", file=sys.stderr)
        for name, info in sorted(payload["status"]["files"].items()):
            age = "missing" if not info["exists"] else f"{info['age_days']}d"
            flag = "STALE" if info["stale"] else ("MISSING" if not info["exists"] else "ok")
            manual = " (manual)" if info["manual"] else ""
            print(f"{flag:8} {name:32} {age}{manual}")
        for warning in payload["status"]["warnings"]:
            print(f"warning: {warning}", file=sys.stderr)

    failed = bool((payload.get("refresh") or {}).get("failed"))
    if not payload["status"]["usable"]:
        return 2
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
