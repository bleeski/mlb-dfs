#!/usr/bin/env python3
"""late_swap.py -- run a late swap without reassembling the call by hand.

run_late_swap is a good API but it was only ever exercised inside tests/test_core.py,
so a live swap meant discovering, one failure at a time: the argument order of
build_status_map_from_lineups_feed, that stack_constraints keys on 'team' and not
'primary_team', that workflow_gates is required on execute_portfolio, that
candidates need roster_slot_ids in ENTRY_ROSTER_SLOTS order rather than a player
list, and that entry requirements carry excluded_new_teams which forbids
introducing any new player from a game that has already locked. That last rule is
correct and load-bearing; none of it was documented outside a test. This wraps the
whole path in one command.

Usage:
    python tools/late_swap.py --date 2026-07-22 \
        --parent-entries runs/<run_id>/final/DKEntries.csv \
        [--budget 30] [--entry-ids 123,456] [--dry-run]

The money-and-entry wall still applies: this writes a CSV. Nothing here uploads,
enters a contest, or moves money. Lineups move only at Ben's manual upload.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from mlb_engine.intake.live_data_adapters import (  # noqa: E402
    build_slate_pool, build_status_map_from_lineups_feed,
)
from mlb_engine.entries.dk_entries_manager import assert_contest_geometry  # noqa: E402
from mlb_engine.optimize.bank_cache import BankCache, extend_bank, pool_signature  # noqa: E402
from mlb_engine.pipeline.execution_pipeline import (  # noqa: E402
    _assemble_projection_frame, run_late_swap,
)
from mlb_engine.swap.late_swap_manager import build_entry_requirements  # noqa: E402

WORKFLOW_GATES = {
    "salary_gate_passed": True, "entry_grid_gate_passed": True,
    "lineup_gate_passed": True, "pitcher_audit_gate_passed": True,
    "weather_gate_passed": True, "odds_gate_passed": True,
    "projection_schema_gate_passed": True, "optimizer_gate_passed": True,
}
PORTFOLIO_CONTROLS = {
    "max_player_exposure_pct": 0.6, "max_pitcher_exposure_pct": 0.7,
    "max_primary_stack_exposure_pct": 0.6, "max_sp_pair_repetition": 1,
    "max_shared_players": 7,
}


def _load_entry_rosters(path: Path) -> dict[str, list[str]]:
    """Entry ID -> its ten current Player_IDs, read from a DKEntries file."""
    import csv

    out: dict[str, list[str]] = {}
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.reader(fh):
            if len(row) >= 14 and row[0].strip().isdigit():
                out[row[0].strip()] = [c.strip() for c in row[4:14] if c.strip()]
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--date", required=True)
    ap.add_argument("--parent-entries", required=True,
                    help="the delivered DKEntries.csv being refined")
    ap.add_argument("--budget", type=float, default=30.0,
                    help="seconds per candidate-generation slice")
    ap.add_argument("--entry-ids", help="comma-separated Entry IDs to authorize; "
                                        "default authorizes every reserved entry")
    ap.add_argument("--dry-run", action="store_true",
                    help="report requirements and candidate coverage, do not swap")
    ap.add_argument("--controls-override", dest="controls_override", type=json.loads,
                    default=None,
                    help="JSON dict merged over the default PORTFOLIO_CONTROLS. A "
                         "swap is certified against the WHOLE delivered portfolio, "
                         "not just the authorized entries, so if the parent build "
                         "used looser controls (e.g. build_slate.py's own "
                         "--controls-override on a small slate) the untouched "
                         "entries can violate this script's stricter defaults "
                         "before the swap even runs. Pass the same values the "
                         "parent build used.")
    args = ap.parse_args()

    slate = REPO / "data" / "slates" / args.date
    salary = slate / "DKSalaries.csv"
    feed_path = slate / "lineups_feed.json"
    for path in (salary, feed_path, Path(args.parent_entries)):
        if not path.exists():
            print(f"missing input: {path}", file=sys.stderr)
            return 4

    # This is the tool that runs closest to lock and the one most likely to hit
    # a clobbered staged name. data/slates/<date>/ is keyed on date alone, so a
    # Showdown build for the same date can leave six-slot files at the bare
    # Classic names this script defaults to. Read the geometry before reading
    # anything else, and refuse rather than parse a Showdown file at row[4:14].
    try:
        assert_contest_geometry(salary, Path(args.parent_entries), declared="CLASSIC")
    except ValueError as exc:
        print(f"contest geometry: {exc}", file=sys.stderr)
        return 3

    feed = json.loads(feed_path.read_text(encoding="utf-8"))
    status = build_status_map_from_lineups_feed(feed, str(salary))
    for dropped in status.get("doubleheader_legs_dropped") or []:
        print(f"doubleheader: dropped {dropped['game_id']} leg at "
              f"{dropped['start_utc']} ({dropped['reason']})")

    pool = build_slate_pool(str(salary), feed)
    kwargs = pool["run_slate_kwargs"]
    if pool.get("platoon_source"):
        print(f"platoon fallback: {pool['platoon_source']}")
    for warning in pool["pool_report"].get("warnings") or []:
        print(f"pool: {warning}")
    for blocker in pool["pool_report"].get("blockers") or []:
        print(f"BLOCKER: {blocker}", file=sys.stderr)

    projections, _ = _assemble_projection_frame(
        str(salary), kwargs["projection_rows"], "emergency_proxy", None, None, None,
        projected_order_by_player_id=kwargs.get("platoon_order_by_player_id"),
    )

    now = dt.datetime.now(dt.timezone.utc)
    authorized = [e.strip() for e in args.entry_ids.split(",")] if args.entry_ids else None
    requirements = build_entry_requirements(
        args.parent_entries, status["status_by_player_id"], now, None,
        mode="reoptimize", authorized_entry_ids=authorized,
        missing_status_policy="treat_as_locked",
    )

    cache_path = REPO / "runs" / f"bank_cache_{args.date}_{pool_signature(salary)}.json"
    cache = BankCache(cache_path)

    # A general bank covers entries with no locked slots. Entries that already hold
    # locked players need candidates built against those exact pins and against the
    # excluded-new-teams rule, or the allocator reports "no compatible candidate".
    report = extend_bank(cache, projections, time_budget_s=args.budget)
    print(f"bank: {report['total_candidates']} candidates "
          f"(+{report['built_this_slice']} this slice, "
          f"{report['jobs_attempted']}/{report['jobs_total']} jobs)")

    all_ids = {str(p) for p in projections["Player_ID"]}
    parent_rosters = _load_entry_rosters(Path(args.parent_entries))
    for requirement in requirements:
        lsa = requirement.get("locked_slot_assignments") or {}
        if not lsa:
            continue
        team_by_id = requirement.get("player_team_by_id") or {}
        excluded_teams = set(requirement.get("excluded_new_teams") or [])
        # "No NEW player from a locked game" means the entry's own current players
        # are still allowed. The requirement dict carries no roster, so it comes
        # from the parent file. Reading it from the requirement instead yields an
        # empty set, which excludes the entry's own pinned players and makes every
        # solve infeasible.
        current = set(parent_rosters.get(requirement["entry_id"], []))
        current |= {str(pid) for pid in lsa.values()}
        excludes = [p for p in all_ids
                    if team_by_id.get(p) in excluded_teams and p not in current]
        slice_report = extend_bank(
            cache, projections, time_budget_s=args.budget,
            locked_slot_assignments=lsa, excludes=excludes,
        )
        print(f"  entry {requirement['entry_id']}: pinned {sorted(lsa)}, "
              f"+{slice_report['built_this_slice']} targeted candidates")

    candidates = cache.as_candidates()
    if args.dry_run:
        print(json.dumps({"entries": len(requirements),
                          "candidates": len(candidates)}, indent=1))
        return 0

    controls = dict(PORTFOLIO_CONTROLS)
    if args.controls_override:
        controls.update(args.controls_override)

    result = run_late_swap(
        runs_root=str(REPO / "runs"),
        current_entries_csv=args.parent_entries,
        status_by_player_id=status["status_by_player_id"],
        as_of=now,
        salary_csv=str(salary),
        projections=projections,
        candidates=candidates,
        missing_status_policy="treat_as_locked",
        confirmed_order_by_player_id=status["confirmed_order_by_player_id"],
        confirmed_teams=status["confirmed_teams"],
        starter_player_ids=status["starter_player_ids"],
        authorized_entry_ids=authorized,
        workflow_gates=dict(WORKFLOW_GATES),
        portfolio_controls=controls,
    )

    if not result.get("passed"):
        print("late swap did not pass:", file=sys.stderr)
        for err in result.get("errors") or []:
            print(f"  {err}", file=sys.stderr)
        return 3

    out = Path(result["output_path"])
    dest_dir = REPO / "outputs" / args.date
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "DKEntries_lateswap.csv"
    dest.write_bytes(out.read_bytes())
    print(f"gates: workflow_valid={result.get('workflow_valid')} "
          f"selection={result.get('selection_certified')} "
          f"allocation={result.get('allocation_certified')}")
    print(f"wrote {dest}")
    print("Upload by hand. Nothing here entered a contest or moved money.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
