#!/usr/bin/env python3
"""refresh_reference_data.py — keep the projection enrichment inputs fresh.

The engine's three season-rate enrichment inputs live in ``data/reference/``:

  * ``expected_stats_batting.csv``  — Baseball Savant expected statistics
    (batter). Feeds the xwOBA Base correction and the xISO hitter ceiling.
  * ``expected_stats_pitching.csv`` — Baseball Savant expected statistics
    (pitcher). Feeds the same correction on the pitcher side AND the opposing-SP
    quality component of the deterministic F4 matchup factor.
  * ``fangraphs_season_pitching.csv`` — FanGraphs season pitching leaderboard.
    Feeds the K-rate pitcher ceiling.

These are season-long rates, so a weekly refresh is plenty. What they are NOT is
optional: a build whose reference files are missing or months old silently
degrades to ranking players on AvgPointsPerGame, which certifies exactly as
cleanly as a build on real signal. That is the whole reason this script and the
staleness stamp exist — the freshness of these files is not observable anywhere
else in the pipeline.

Two sources, two policies, deliberately:

  * **Savant is fetched over HTTP.** The leaderboard exports a CSV on a public
    URL; this script pulls it, validates the shape before overwriting anything,
    and stamps the fetch time.
  * **FanGraphs is manual by decision** (project rule, not a technical limit).
    This script never fetches it. It reports the file's age and prints the export
    URL so Ben can pull it by hand when it goes stale.

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

FANGRAPHS_PITCHING_URL = (
    "https://www.fangraphs.com/leaders/major-league"
    "?pos=all&stats=pit&lg=all&qual=y&type=8"
)

# Columns each file must actually contain for the enrichment it feeds to work.
# Checked before anything is written, so a redirect to an HTML error page or a
# silently-changed export cannot overwrite a good file with garbage.
REQUIRED_COLUMNS: Dict[str, List[str]] = {
    "expected_stats_batting.csv": ["player_id", "pa", "woba", "est_woba"],
    "expected_stats_pitching.csv": ["player_id", "pa", "woba", "est_woba"],
    "fangraphs_season_pitching.csv": ["Name", "IP", "K/9"],
}

SAVANT_TARGETS = {
    "expected_stats_batting.csv": "batter",
    "expected_stats_pitching.csv": "pitcher",
}

MANUAL_TARGETS = {
    "fangraphs_season_pitching.csv": FANGRAPHS_PITCHING_URL,
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


def reference_status(reference_dir: Path = REFERENCE_DIR,
                     max_age_days: float = DEFAULT_MAX_AGE_DAYS) -> Dict[str, Any]:
    """Report presence, age, and staleness for every enrichment input.

    Returns ``{"files": {name: {...}}, "usable": bool, "warnings": [...]}``.
    ``usable`` means every file exists; stale files are still usable and still
    passed to the build, because degraded signal beats no signal — but the
    warnings ride into the brief so the operator sees it.
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
                f"{name}: missing from data/reference/; the enrichment it feeds is "
                f"OFF for this build. Run tools/refresh_reference_data.py"
                + (f" or export it manually from {MANUAL_TARGETS[name]}"
                   if name in MANUAL_TARGETS else "")
            )
        elif stale:
            how = (f"export it manually from {MANUAL_TARGETS[name]}"
                   if name in MANUAL_TARGETS
                   else "run tools/refresh_reference_data.py")
            out["warnings"].append(
                f"{name}: {out['files'][name]['age_days']} days old "
                f"(limit {max_age_days}); season rates are drifting, {how}"
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
