#!/usr/bin/env python3
"""tools/stage_slate.py -- Phase 1 intake wiring (migration guide, Phase 1).

Make ``data/slates/<date>/`` sufficient input for a build in one command.

Given a date, this loads the four staged artifacts from that folder --
``slate_bundle.json`` (the mlb-lineups-shaped feed plus DK/FD totals plus
per-venue weather, produced by ``tools/fetch_slate_bundle.py``), the platoon
JSON, the DKSalaries CSV, and the DKEntries reserved-entries CSV -- runs the
confirmed-pool intake front door
(``live_data_adapters.build_slate_pool``), computes the deterministic F4
matchup prior via ``compute_f4_factors`` over
``extract_opposing_probables``/``extract_batter_hands``, parses the odds packet
via ``parse_the_odds_api_totals``, and assembles the exact ``run_slate`` kwargs.

The acceptance bar (migration guide, Phase 1): one command stages tonight's
slate and ``run_slate(approve=False)`` returns a clean checkpoint with no file
pasted or uploaded by hand. Manual lineups-feed construction stays documented in
CLAUDE.md as the fallback path, nothing more.

The DKSalaries CSV stays authoritative for Player_ID, salary, team, and
eligibility (CLAUDE.md "Authority"); this tool never corrects it against
real-world rosters. Everything here is deterministic intake bookkeeping and
labeled priors -- never a projection edge, ROI, win-rate, or probability claim.

Usage:
  python tools/stage_slate.py [--date YYYY-MM-DD] [--slates-dir data/slates]
                              [--reference-dir data/reference]
                              [--runs-root runs] [--no-enrich]
                              [--checkpoint] [--json]

  --checkpoint  after staging, call run_slate(approve=False) and print the
                slate clock, the pool report, and the single Blockers line.
  --json        print a compact JSON summary of the assembled kwargs
                (ids and counts, never full projection rows).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

ENTRIES_HEADER_PREFIX = ["Entry ID", "Contest Name", "Contest ID", "Entry Fee"]


def _today_et() -> str:
    # ET without a tz-database dependency: UTC-4 (EDT) covers the MLB season,
    # matching tools/fetch_slate_bundle.py._today_et.
    return (datetime.now(timezone.utc) - timedelta(hours=4)).strftime("%Y-%m-%d")


def _read_header(path: Path) -> List[str]:
    import csv
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return next(csv.reader(handle), [])


def _find_salary_and_entries(slate_dir: Path) -> Tuple[Optional[Path], Optional[Path]]:
    """Content-sniff the slate dir for the DK salary export and the DKEntries
    reserved-entries file, independent of filename convention -- the same
    discipline tests/test_golden_replay.py uses: the entries file by its exact
    4-column header, the salary file by validate_salary_schema.
    """
    from mlb_engine.intake.slate_intake_manager import validate_salary_schema

    salary_csv: Optional[Path] = None
    entries_csv: Optional[Path] = None
    for path in sorted(slate_dir.glob("*.csv")):
        header = _read_header(path)
        if not header:
            continue
        if [c.strip() for c in header[:4]] == ENTRIES_HEADER_PREFIX:
            entries_csv = path
            continue
        try:
            if validate_salary_schema(str(path)).get("passed"):
                salary_csv = path
        except Exception:
            continue
    return salary_csv, entries_csv


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _find_bundle_and_platoon(
    slate_dir: Path,
) -> Tuple[Optional[Path], Optional[Path], Optional[Path]]:
    """Resolve the three JSON artifacts. Prefer conventional names, then sniff.

    - bundle: ``slate_bundle.json`` if present, else any *.json carrying a
      ``bundle_version`` or ``lineups`` key.
    - platoon: any ``*platoon*.json``, else the remaining non-bundle,
      non-declared JSON.
    - declared_pitchers: ``declared_pitchers.json`` if present (optional; the
      feed's own probables are used when it is absent).
    """
    jsons = sorted(slate_dir.glob("*.json"))
    declared = next((p for p in jsons if p.name == "declared_pitchers.json"), None)

    bundle = next((p for p in jsons if p.name == "slate_bundle.json"), None)
    if bundle is None:
        for p in jsons:
            if p in (declared,):
                continue
            try:
                obj = _load_json(p)
            except Exception:
                continue
            if isinstance(obj, Mapping) and ("bundle_version" in obj or "lineups" in obj):
                bundle = p
                break

    platoon = next((p for p in jsons if "platoon" in p.name.lower()), None)
    if platoon is None:
        for p in jsons:
            if p in (bundle, declared):
                continue
            platoon = p
            break
    return bundle, platoon, declared


def stage_slate(
    date: str,
    slates_dir: str | Path = REPO_ROOT / "data" / "slates",
    reference_dir: str | Path = REPO_ROOT / "data" / "reference",
    runs_root: Optional[str | Path] = REPO_ROOT / "runs",
    enrich: bool = True,
    declared_pitchers: Optional[Mapping[str, str]] = None,
) -> Dict[str, Any]:
    """Stage ``data/slates/<date>/`` into ready-to-splat ``run_slate`` kwargs.

    Returns a dict with ``run_slate_kwargs`` (splat straight into
    ``run_slate``), plus the ``odds_packet``, ``pool_report``, ``clock``,
    ``f4_report``, ``weather``, resolved ``sources``, and ``warnings`` for the
    checkpoint and the morning brief. Deterministic bookkeeping only.
    """
    from mlb_engine.intake.live_data_adapters import (
        build_slate_pool, parse_the_odds_api_totals, salary_game_times,
    )
    from mlb_engine.projections.projection_builder import (
        compute_f4_factors, load_savant_expected_stats,
    )

    slate_dir = Path(slates_dir) / date
    if not slate_dir.exists():
        raise FileNotFoundError(f"slate folder does not exist: {slate_dir}")

    warnings: List[str] = []

    salary_csv, entries_csv = _find_salary_and_entries(slate_dir)
    if salary_csv is None:
        raise FileNotFoundError(
            f"no DKSalaries CSV found in {slate_dir} (a DraftKings salary export "
            f"with Position/Name+ID/Salary/TeamAbbrev columns). Download it from "
            f"DraftKings and drop it in that folder."
        )
    if entries_csv is None:
        raise FileNotFoundError(
            f"no DKEntries reserved-entries CSV found in {slate_dir} (header must "
            f"start 'Entry ID,Contest Name,Contest ID,Entry Fee'). Download it from "
            f"DraftKings and drop it in that folder."
        )

    bundle_path, platoon_path, declared_path = _find_bundle_and_platoon(slate_dir)
    if bundle_path is None:
        raise FileNotFoundError(
            f"no slate_bundle.json found in {slate_dir}. Run "
            f"`python tools/fetch_slate_bundle.py --date {date} "
            f"--out {slate_dir}/slate_bundle.json` first."
        )
    bundle = _load_json(bundle_path)
    lineups_feed = bundle.get("lineups")
    if not lineups_feed or not (lineups_feed.get("games")):
        raise ValueError(
            f"{bundle_path.name} has no usable lineups feed (bundle['lineups']['games'] "
            f"is empty). The MLB Stats API fetch in fetch_slate_bundle.py may have failed; "
            f"see bundle['warnings']: {bundle.get('warnings')}"
        )
    for w in bundle.get("warnings") or []:
        warnings.append(f"bundle: {w}")

    platoon_json: Optional[Any] = None
    if platoon_path is not None:
        try:
            platoon_json = _load_json(platoon_path)
        except Exception as exc:
            warnings.append(f"platoon JSON unreadable ({platoon_path.name}): {exc}")
    else:
        warnings.append(
            "no platoon JSON found; TBD-lineup teams will fall back to top-9 "
            "AvgPointsPerGame with a warning"
        )

    if declared_pitchers is None and declared_path is not None:
        try:
            declared_pitchers = _load_json(declared_path)
        except Exception as exc:
            warnings.append(f"declared_pitchers.json unreadable: {exc}")

    # THE intake front door (CLAUDE.md per-slate loop step 1).
    pool = build_slate_pool(
        salary_csv=str(salary_csv),
        lineups_feed=lineups_feed,
        platoon_json=platoon_json,
        declared_pitchers=declared_pitchers,
    )

    reference = Path(reference_dir)
    savant_batting = reference / "expected_stats_batting.csv"
    savant_pitching = reference / "expected_stats_pitching.csv"
    fangraphs_pitching = reference / "fangraphs_season_pitching.csv"

    # F4 deterministic matchup prior: opposing-SP contact quality (Savant
    # pitching frame) times the platoon hand factor. Neutral (1.0) where an
    # opposing probable or its Savant row is missing; still a labeled prior.
    pitching_table = None
    if savant_pitching.exists():
        try:
            pitching_table = load_savant_expected_stats(savant_pitching)
        except Exception as exc:
            warnings.append(f"savant pitching frame unreadable; F4 quality neutral: {exc}")
    f4_by_player_id, f4_report = compute_f4_factors(
        pool["team_by_player_id"],
        pool["opposing_probables"],
        pitching_table,
        pool["batter_hands"],
    )

    # Odds packet: parsed for the checkpoint and the brief. Not a run_slate
    # input in the current engine (the odds gate is static; only the opt-in
    # tail scanner consumes game environment), so it rides alongside the kwargs.
    odds_raw = bundle.get("odds_raw_totals")
    odds_packet: Dict[str, Any]
    if odds_raw:
        try:
            # F18: the salary file resolves which doubleheader leg is on this
            # slate, for odds exactly as for the lineups feed.
            odds_packet = parse_the_odds_api_totals(
                odds_raw, fetched_at=bundle.get("fetched_at"),
                slate_game_times=salary_game_times(str(salary_csv)))
            for leg in odds_packet.get("doubleheader_legs_dropped") or []:
                warnings.append(
                    f"odds doubleheader leg dropped: {leg['game_id']} @ "
                    f"{leg['start_utc']} total {leg.get('total')} ({leg['reason']})")
        except Exception as exc:
            odds_packet = {"odds_by_game_id": {}, "warning": f"odds parse failed: {exc}"}
            warnings.append(f"odds packet parse failed: {exc}")
    else:
        odds_packet = {"odds_by_game_id": {}, "note": "no odds in bundle (skipped or fetch failed)"}

    # Assemble the exact run_slate kwargs: pool kwargs + salary/entries + the
    # F4 map + the reference enrichments (each only if the file is present).
    kwargs: Dict[str, Any] = dict(pool["run_slate_kwargs"])
    kwargs["salary_csv"] = str(salary_csv)
    kwargs["entries_csv"] = str(entries_csv)
    kwargs["projection_mode"] = "emergency_proxy"
    kwargs["f4_by_player_id"] = f4_by_player_id or None
    if runs_root is not None:
        kwargs["runs_root"] = str(runs_root)
    if enrich:
        if savant_batting.exists():
            kwargs["savant_batting_csv"] = str(savant_batting)
        if savant_pitching.exists():
            kwargs["savant_pitching_csv"] = str(savant_pitching)
        if fangraphs_pitching.exists():
            kwargs["fangraphs_pitching_csv"] = str(fangraphs_pitching)

    pool_report = pool["pool_report"]
    for b in pool_report.get("blockers") or []:
        warnings.append(f"pool blocker: {b}")

    return {
        "date": date,
        "run_slate_kwargs": kwargs,
        "odds_packet": odds_packet,
        "pool_report": pool_report,
        "clock": pool.get("clock"),
        "f4_report": f4_report,
        "weather": bundle.get("weather"),
        "sources": {
            "slate_dir": str(slate_dir),
            "salary_csv": salary_csv.name,
            "entries_csv": entries_csv.name,
            "slate_bundle": bundle_path.name,
            "platoon_json": platoon_path.name if platoon_path else None,
            "declared_pitchers": declared_path.name if declared_path else None,
        },
        "warnings": warnings,
    }


def _kwargs_summary(kwargs: Mapping[str, Any]) -> Dict[str, Any]:
    """Compact, ID-and-count view of the assembled kwargs. Never dumps rows."""
    rows = kwargs.get("projection_rows") or []
    return {
        "salary_csv": kwargs.get("salary_csv"),
        "entries_csv": kwargs.get("entries_csv"),
        "projection_mode": kwargs.get("projection_mode"),
        "projection_rows": len(rows),
        "confirmed_hitter_ids": len(kwargs.get("confirmed_hitter_ids") or []),
        "confirmed_teams": list(kwargs.get("confirmed_teams") or []),
        "pitcher_roles": len(kwargs.get("pitcher_roles") or {}),
        "platoon_order_by_player_id": len(kwargs.get("platoon_order_by_player_id") or {}),
        "f4_by_player_id": len(kwargs.get("f4_by_player_id") or {}),
        "enrichments": [
            k for k in ("savant_batting_csv", "savant_pitching_csv", "fangraphs_pitching_csv")
            if kwargs.get(k)
        ],
    }


def _print_staging(staged: Mapping[str, Any]) -> None:
    src = staged["sources"]
    summary = _kwargs_summary(staged["run_slate_kwargs"])
    pr = staged["pool_report"]
    print(f"staged {staged['date']} from {src['slate_dir']}")
    print(f"  salary={src['salary_csv']}  entries={src['entries_csv']}  "
          f"bundle={src['slate_bundle']}  platoon={src['platoon_json']}")
    print(f"  pool: {pr['kept']} kept / {pr['dropped']} dropped of {pr['salary_rows_total']} "
          f"salary rows ({pr['hitters_kept']} hitters, {pr['pitchers_kept']} pitchers)")
    print(f"  kwargs: {summary['projection_rows']} rows, "
          f"{summary['confirmed_hitter_ids']} confirmed hitters, "
          f"{summary['pitcher_roles']} arms, "
          f"{summary['platoon_order_by_player_id']} platoon slots, "
          f"F4 on {summary['f4_by_player_id']} hitters")
    print(f"  odds: {len(staged['odds_packet'].get('odds_by_game_id') or {})} games; "
          f"enrichments: {summary['enrichments'] or 'none'}")
    blockers = pr.get("blockers") or []
    print(f"  Blockers: {'; '.join(blockers) if blockers else 'none'}")
    if staged["warnings"]:
        print("  warnings:")
        for w in staged["warnings"]:
            print(f"    - {w}")


def _run_checkpoint(kwargs: Mapping[str, Any]) -> int:
    from mlb_engine.pipeline.execution_pipeline import run_slate

    plan = run_slate(approve=False, **kwargs)
    ck = plan.get("checkpoint") or {}
    clock = ck.get("slate_clock") or {}
    print("--- run_slate(approve=False) checkpoint ---")
    print(f"  passed={plan.get('passed')}  status={plan.get('status')}")
    if plan.get("errors"):
        print(f"  errors: {plan['errors']}")
    if clock:
        print(f"  slate_clock: first_lock={clock.get('first_lock_et') or clock.get('first_lock')} "
              f"deadline={clock.get('delivery_deadline_et') or clock.get('deadline')} "
              f"minutes_remaining={clock.get('minutes_remaining')}")
    feas = ck.get("feasibility") or {}
    binding = feas.get("binding_constraints") or []
    ck_warnings = ck.get("warnings") or []
    blockers = [w for w in ck_warnings if "blocker" in str(w).lower()] or binding
    print(f"  Blockers: {'; '.join(str(b) for b in blockers) if blockers else 'none'}")
    return 0 if plan.get("passed") else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Stage data/slates/<date>/ into run_slate kwargs")
    parser.add_argument("--date", default=_today_et(), help="ET slate date YYYY-MM-DD (default: today ET)")
    parser.add_argument("--slates-dir", default=str(REPO_ROOT / "data" / "slates"))
    parser.add_argument("--reference-dir", default=str(REPO_ROOT / "data" / "reference"))
    parser.add_argument("--runs-root", default=str(REPO_ROOT / "runs"))
    parser.add_argument("--no-enrich", action="store_true",
                        help="skip the Savant/FanGraphs enrichment CSVs")
    parser.add_argument("--checkpoint", action="store_true",
                        help="after staging, run run_slate(approve=False) and print the checkpoint")
    parser.add_argument("--json", action="store_true",
                        help="print a compact JSON summary of the assembled kwargs")
    args = parser.parse_args()

    try:
        staged = stage_slate(
            date=args.date,
            slates_dir=args.slates_dir,
            reference_dir=args.reference_dir,
            runs_root=args.runs_root,
            enrich=not args.no_enrich,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"stage_slate: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps({
            "date": staged["date"],
            "kwargs_summary": _kwargs_summary(staged["run_slate_kwargs"]),
            "sources": staged["sources"],
            "odds_games": len(staged["odds_packet"].get("odds_by_game_id") or {}),
            "warnings": staged["warnings"],
        }, indent=2))
    else:
        _print_staging(staged)

    if args.checkpoint:
        return _run_checkpoint(staged["run_slate_kwargs"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
