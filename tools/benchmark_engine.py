"""Reproducible offline comparisons; timings are measurements, not EV claims."""

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


def measure(fn, repetitions=5):
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
        "python_peak_bytes": peak,
        "memory_note": "tracemalloc excludes native solver/BLAS allocation",
    }


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
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    results = {
        "environment": runtime_identity(),
        "label": "offline synthetic workload; no live model/economic inference",
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
