"""Reproducible offline comparisons; timings are measurements, not EV claims.

Two modes, and they do not share a label because they do not measure the same
thing. The default mode drives ``mlb_engine.production.*`` against a synthetic
fixture. ``--live`` drives the real lineup path -- ``execution_pipeline.run_slate``,
the one production front door -- against the vendored 2026-06-03 archive slate,
so ``SYNTHETIC_LABEL``'s "offline synthetic workload" would be false of it.
R374 / CC-A9: until this flag existed the path that actually builds slates had
no timing baseline at all.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
from pathlib import Path
import statistics
import sys
import time
import tracemalloc

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SYNTHETIC_LABEL = "offline synthetic workload; no live model/economic inference"
# Every clause here is load-bearing and each one is false of the other mode.
# "no network intake" is the one a reader is most likely to assume away: the
# replay synthesizes projections from the salary file's own AvgPointsPerGame in
# emergency_proxy mode, so live_data_adapters.build_slate_pool -- the real
# intake front door -- is never reached. "Live" here means the real optimizer
# and the real front door, not a live data feed.
LIVE_LABEL = (
    "live lineup path: execution_pipeline.run_slate against the vendored "
    "2026-06-03 archive slate; real MILP, emergency_proxy projections off the "
    "salary CSV's AvgPointsPerGame, no network intake. Timings are deterministic "
    "review proxies on ONE slate (n=1) and are host-dependent; never ROI, edge, "
    "a win rate, or a probability"
)
LIVE_SLATE_DATE = "2026-06-03"
# Mirrors tests/test_golden_replay.py's replay configuration so this baseline
# times the same shape the golden gate already pins for correctness. A test
# asserts the two stay equal rather than trusting the comment.
LIVE_REQUESTED_N = 8
LIVE_TOP_SP_PER_TEAM = 2
LIVE_LOOSE_CONTROLS = {
    "max_player_exposure_pct": 1.0,
    "max_pitcher_exposure_pct": 1.0,
    "max_primary_stack_exposure_pct": 1.0,
    "max_team_exposure_pct": 1.0,
    # R405: opened, as in the golden's LOOSE_CONTROLS (R374 pins the two equal).
    "max_consensus_cluster_share_pct": 1.0,
    "max_sp_pair_repetition": 50,
    "max_shared_players": 9,
    "max_candidate_reuse": 20,
}
LIVE_ASSUMED_GATES = ["odds_gate_passed", "weather_gate_passed",
                      "pitcher_audit_gate_passed", "lineup_gate_passed"]


def measure(fn, repetitions=5, warmup=True):
    """Time ``fn`` then trace it, in separate runs.

    The two are separated deliberately: tracemalloc inflates wall time, so a
    single combined run would report a timing no one could compare. ``warmup``
    is skipped on the live path, where one extra full build costs a minute and
    buys a cache effect this baseline does not want to hide.
    """
    if warmup:
        fn()
    times = []
    for _ in range(repetitions):
        start = time.perf_counter()
        fn()
        times.append(time.perf_counter() - start)
    tracemalloc.start()
    fn()
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {
        "median_seconds": statistics.median(times),
        "samples_seconds": times,
        "repetitions": repetitions,
        "warmup": warmup,
        "python_peak_bytes": peak,
        "memory_note": "tracemalloc excludes native solver/BLAS allocation",
    }


ENTRIES_HEADER_PREFIX = ["Entry ID", "Contest Name", "Contest ID", "Entry Fee"]


def live_inputs(archive_dir):
    """Content-sniff the archive dir for the DK salary export and DKEntries file.

    Sniffed rather than matched on filename, and against the real parsers'
    own validation, so a renamed archive file does not silently benchmark
    nothing. Returns (salary_csv, entries_csv); either may be None.
    """
    from mlb_engine.intake.slate_intake_manager import validate_salary_schema

    salary_csv = entries_csv = None
    for path in sorted(Path(archive_dir).glob("*.csv")):
        with path.open(newline="", encoding="utf-8-sig") as handle:
            header = next(csv.reader(handle), [])
        if not header:
            continue
        if [c.strip() for c in header[:4]] == ENTRIES_HEADER_PREFIX:
            entries_csv = path
            continue
        if validate_salary_schema(str(path)).get("passed"):
            salary_csv = path
    return salary_csv, entries_csv


def live_projection_rows(salary_csv):
    """Per-player emergency-proxy rows: Player_ID + Base off AvgPointsPerGame.

    Pitchers are capped at the top LIVE_TOP_SP_PER_TEAM by salary per team.
    That cap is load-bearing, not cosmetic: the raw salary file lists every
    SP-eligible arm on each active roster, and build_diverse_candidate_bank
    enumerates every viable SP PAIR, an O(n^2) cost in distinct SPs. Benchmarking
    the unfiltered file would time a shape no real build ever solves, because
    the real filter is live_data_adapters.build_slate_pool with declared_pitchers,
    which an archived slate has no feed for.
    """
    from collections import defaultdict
    from mlb_engine.intake.slate_intake_manager import parse_dk_salary_csv

    sp_by_team = defaultdict(list)
    rows = []
    for player in parse_dk_salary_csv(str(salary_csv)):
        avg = player.raw.get("AvgPointsPerGame") or player.raw.get("Avg Points Per Game")
        try:
            base = float(avg)
        except (TypeError, ValueError):
            continue
        if base <= 0:
            continue
        row = {"Player_ID": player.player_id, "Base": base, "_salary": player.salary}
        position = player.raw.get("Position")
        if position == "SP":
            sp_by_team[player.team].append(row)
        elif position == "RP":
            continue  # never a probable starter; excluded like real production
        else:
            rows.append(row)
    for team_rows in sp_by_team.values():
        team_rows.sort(key=lambda r: -r["_salary"])
        rows.extend(team_rows[:LIVE_TOP_SP_PER_TEAM])
    for row in rows:
        row.pop("_salary", None)
    return rows


def run_live(output_dir):
    """Time the real lineup path end to end against the vendored archive slate.

    Runs under a redirected ``MLB_DFS_ARTIFACT_ROOT``. A certified build writes
    a `kind: "delivery"` record into `data/deliveries/<date>/`, and a benchmark
    that leaves those behind publishes six fake certified deliveries of an
    ARCHIVED slate into the tracked ledger, where `awaiting_standings`,
    `field_miner` and `outcome_review` would all read them as real. The gate
    (`tools/audit.py`, R338 repair 4) and `tests/conftest.py` redirect the same
    variable for the same reason; `delivery_record._artifact_root` reads it at
    CALL time, so setting it here reaches the writer.
    """
    import os
    import tempfile
    from mlb_engine.pipeline.execution_pipeline import (
        _assemble_projection_frame, run_slate,
    )
    from mlb_engine.production.workflow import runtime_identity

    with tempfile.TemporaryDirectory() as artifact_root:
        previous = os.environ.get("MLB_DFS_ARTIFACT_ROOT")
        os.environ["MLB_DFS_ARTIFACT_ROOT"] = artifact_root
        try:
            import mlb_engine.entries.upload_manifest as _um
            previous_repo_root = _um.REPO_ROOT
            _um.REPO_ROOT = Path(artifact_root)
            try:
                return _run_live_inner(output_dir)
            finally:
                _um.REPO_ROOT = previous_repo_root
        finally:
            if previous is None:
                os.environ.pop("MLB_DFS_ARTIFACT_ROOT", None)
            else:
                os.environ["MLB_DFS_ARTIFACT_ROOT"] = previous


def _run_live_inner(output_dir):
    import tempfile
    from mlb_engine.pipeline.execution_pipeline import (
        _assemble_projection_frame, run_slate,
    )
    from mlb_engine.production.workflow import runtime_identity

    archive = ROOT / "data" / "archive" / LIVE_SLATE_DATE
    salary_csv, entries_csv = live_inputs(archive)
    if salary_csv is None or entries_csv is None:
        raise SystemExit(
            f"--live needs the vendored slate: data/archive/{LIVE_SLATE_DATE}/ must "
            "carry a DK salary export and a blank DKEntries reserved-entries CSV. "
            f"Found: {sorted(p.name for p in archive.iterdir()) if archive.exists() else 'the directory does not exist'}"
        )

    results = {
        "environment": runtime_identity(),
        "label": LIVE_LABEL,
        "mode": "live",
        "slate_date": LIVE_SLATE_DATE,
        "requested_n": LIVE_REQUESTED_N,
        "inputs": {"salary_csv": salary_csv.name, "entries_csv": entries_csv.name},
        "llm_calls": 0, "llm_tokens": 0, "network_calls": 0,
    }

    projection_rows = live_projection_rows(salary_csv)
    results["projection_row_count"] = len(projection_rows)
    results["projection_frame_assembly"] = measure(
        lambda: _assemble_projection_frame(
            salary_csv, projection_rows, "emergency_proxy", None, None, None
        ),
        repetitions=3,
    )
    frame, _meta = _assemble_projection_frame(
        salary_csv, projection_rows, "emergency_proxy", None, None, None
    )
    results["projection_frame_shape"] = list(frame.shape)

    def _slate(approve):
        def run():
            with tempfile.TemporaryDirectory() as tmp:
                return run_slate(
                    runs_root=Path(tmp) / "runs",
                    salary_csv=salary_csv,
                    entries_csv=entries_csv,
                    projection_rows=projection_rows,
                    projection_mode="emergency_proxy",
                    requested_n=LIVE_REQUESTED_N,
                    portfolio_controls_override=LIVE_LOOSE_CONTROLS,
                    approve=approve,
                    assume_gates=LIVE_ASSUMED_GATES,
                )
        return run

    # One repetition and no warmup: a full certified build is the expensive unit
    # here, and measure() already runs it twice (once timed, once traced).
    results["plan_pass_approve_false"] = measure(_slate(False), repetitions=1, warmup=False)
    results["certified_build_approve_true"] = measure(_slate(True), repetitions=1, warmup=False)

    # What that build actually produced, so a timing is never read without the
    # shape it was a timing OF.
    with tempfile.TemporaryDirectory() as tmp:
        built = _slate(True)()
    results["build_outcome"] = {
        "passed": bool(built.get("passed")),
        "workflow_valid": bool(built.get("workflow_valid")),
        "selection_certified": bool(built.get("selection_certified")),
        "allocation_certified": bool(built.get("allocation_certified")),
        # The bank block lands under "candidate_bank" on the run_slate return
        # (execution_pipeline.py:5430); "bank_diagnostics" is the run-directory
        # holder, not a key on this dict, and reading it returns all-None
        # silently -- a timing with no shape attached.
        "candidate_bank": {
            k: (built.get("candidate_bank") or {}).get(k)
            for k in ("source", "candidate_count", "requested_n", "mode")
        },
        "bank_coverage": built.get("bank_coverage"),
        "portfolio_frontier": built.get("portfolio_frontier"),
    }
    return results


def main():
    from mlb_engine.production.contracts import Controls, EvidenceBundle
    from mlb_engine.production.csvio import parse_entries, parse_salary
    from mlb_engine.production.demo import AS_OF, execute_demo, make_fixture
    from mlb_engine.production.evidence import prepare
    from mlb_engine.production.optimizer import Deadline, solve_portfolio
    from mlb_engine.production.simulation import simulate
    from mlb_engine.production.workflow import runtime_identity
    from mlb_engine.optimize.bank_cache import projection_digest
    import pandas as pd

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument(
        "--live", action="store_true",
        help="benchmark the REAL lineup path (execution_pipeline.run_slate) against "
             f"the vendored data/archive/{LIVE_SLATE_DATE}/ slate instead of the "
             "synthetic production workload. Emits LIVE_LABEL, never SYNTHETIC_LABEL.",
    )
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)

    if args.live:
        results = run_live(args.output)
        (args.output / "benchmarks.json").write_text(
            json.dumps(results, indent=2, allow_nan=False, default=str), encoding="utf-8"
        )
        print(json.dumps({
            "mode": "live",
            "status": "certified" if results["build_outcome"]["passed"] else "refused",
            "result": str((args.output / "benchmarks.json").resolve()),
        }))
        return

    results = {
        "environment": runtime_identity(),
        "label": SYNTHETIC_LABEL,
        "mode": "synthetic",
    }
    paths = make_fixture(args.output / "inputs", entry_count=3)
    raw = paths["salary"].read_bytes()
    results["csv_reader"] = measure(
        lambda: list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
    )
    results["pandas_read_csv"] = measure(
        lambda: pd.read_csv(io.BytesIO(raw), dtype=str)
    )
    results["strict_salary_ingestion"] = measure(lambda: parse_salary(raw))
    results["input_size_bytes"] = len(raw)
    frame = pd.DataFrame(
        {
            "Player_ID": [str(i) for i in range(500)],
            "Team": ["A"] * 500,
            "Position": ["OF"] * 500,
            "Base": [10.0] * 500,
            "Ceiling": [20.0] * 500,
            "Floor": [2.0] * 500,
            "Salary": [4000] * 500,
            "Excluded": [False] * 500,
        }
    )
    results["complete_projection_digest_500_rows"] = measure(
        lambda: projection_digest(frame), 30
    )
    controls = Controls(
        enhance=False, total_seconds=20.0, per_solve_seconds=8.0, simulations=2048
    )
    mode, players = parse_salary(raw)
    template = parse_entries(paths["entries"].read_bytes())
    bundle = EvidenceBundle.model_validate_json(paths["evidence"].read_bytes())
    prepared = prepare(bundle, players, controls, AS_OF, True)
    reports = []

    def solve():
        rosters, report = solve_portfolio(
            template.entries,
            mode,
            players,
            prepared,
            controls,
            AS_OF,
            {e.entry_id for e in template.entries},
            Deadline(20),
        )
        reports.append({**report, "entry_count": len(rosters)})

    results["joint_baseline_3_entries_40_players"] = measure(solve)
    results["joint_solver_reports"] = reports
    results["correlated_simulation_2048x40"] = measure(
        lambda: simulate(players, prepared, controls)
    )
    start = time.perf_counter()
    demo = execute_demo(args.output / "complete_demo")
    results["end_to_end_demo_seconds"] = time.perf_counter() - start
    results["end_to_end_demo_status"] = demo["status"]
    results["baseline_solver_seconds"] = demo["baseline"]["baseline_solve_seconds"]
    results["late_swap_seconds"] = demo["late_swap"]["elapsed_seconds"]
    results["enhancement_decisions"] = (
        demo["baseline"].get("review", {}).get("decisions", [])
    )
    results["raw_inputs_unchanged"] = demo["raw_inputs_unchanged"]
    results["llm_calls"] = results["llm_tokens"] = results["network_calls"] = 0
    (args.output / "benchmarks.json").write_text(
        json.dumps(results, indent=2, allow_nan=False), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "status": demo["status"],
                "result": str((args.output / "benchmarks.json").resolve()),
            }
        )
    )


if __name__ == "__main__":
    main()
