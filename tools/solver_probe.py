#!/usr/bin/env python3
"""solver_probe.py -- how long will this slate's bank actually take?

Run this at session start, before any build. It times one lineup and a short
multi-lineup run on the real pool, extrapolates to the bank the slate needs, and
compares that to the execution budget available.

Why: on 2026-07-22 the bank build was killed four times inside a ~43s per-call
ceiling before anyone knew how long it needed. Fifteen minutes went into
discovering the wall empirically, at T-30 on a live slate, and one of the
workarounds attempted along the way trimmed the legal player pool -- a strategy
change bought to relieve an infrastructure limit that had been misdiagnosed. This
probe answers the question in about ten seconds.

Usage:
    python tools/solver_probe.py --date 2026-07-22 [--entries 10] [--budget 43]
    python tools/solver_probe.py --salary path/to/DKSalaries.csv --lineups feed.json

Exit codes:
    0  projected build fits the budget
    3  projected build exceeds the budget (use time_budget_s or bank_cache slices)
    4  inputs missing

Timings are measurements of this machine on this pool. They are deterministic
review inputs, never an ROI, win-rate, or probability claim.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from mlb_engine.intake.live_data_adapters import build_slate_pool  # noqa: E402
from mlb_engine.optimize.optimizer_v3 import (  # noqa: E402
    build_multi_lineup, build_single_lineup, resolve_candidate_bank_size,
)
from mlb_engine.pipeline.execution_pipeline import _assemble_projection_frame  # noqa: E402


def _resolve_inputs(args) -> tuple[Path, Path]:
    if args.salary and args.lineups:
        return Path(args.salary), Path(args.lineups)
    if not args.date:
        raise SystemExit("need --date, or both --salary and --lineups")
    slate = REPO / "data" / "slates" / args.date
    salary = Path(args.salary) if args.salary else slate / "DKSalaries.csv"
    feed = Path(args.lineups) if args.lineups else slate / "lineups_feed.json"
    # The default name is date-keyed and shared, so it can hold a Showdown file
    # left by another build for the same date. This probe reports whether the
    # bank fits the execution budget; timing a six-slot pool as a ten-slot one
    # answers a question nobody asked.
    from mlb_engine.entries.dk_entries_manager import detect_salary_contract
    contract = detect_salary_contract(salary)
    if contract != "CLASSIC":
        raise SystemExit(
            f"{salary} carries {contract} geometry; solver_probe times the Classic "
            f"solver. Pass --salary with the Classic file for this date."
        )
    return salary, feed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--date", help="slate date, reads data/slates/<date>/")
    ap.add_argument("--salary", help="DKSalaries.csv path")
    ap.add_argument("--lineups", help="mlb-lineups feed JSON path")
    ap.add_argument("--entries", type=int, default=10, help="entries to build for")
    ap.add_argument("--budget", type=float, default=43.0,
                    help="seconds of compute available per call (default 43)")
    ap.add_argument("--json", action="store_true", help="emit JSON only")
    args = ap.parse_args()

    salary, feed_path = _resolve_inputs(args)
    if not salary.exists() or not feed_path.exists():
        print(f"missing inputs: salary={salary.exists()} lineups={feed_path.exists()}",
              file=sys.stderr)
        return 4

    pool = build_slate_pool(str(salary), json.loads(feed_path.read_text(encoding="utf-8")))
    kwargs = pool["run_slate_kwargs"]
    projections, _ = _assemble_projection_frame(
        str(salary), kwargs["projection_rows"], "emergency_proxy", None, None, None,
        projected_order_by_player_id=kwargs.get("platoon_order_by_player_id"),
    )

    n_players = len(projections)
    n_sp = int((projections["Position"] == "P").sum())
    bank_size = resolve_candidate_bank_size(args.entries)

    t0 = time.monotonic()
    build_single_lineup(projections, target="ceiling")
    single_s = time.monotonic() - t0

    probe_n = 5
    t0 = time.monotonic()
    # R15, 2026-07-27: du_threshold_row=None matches production. The default is
    # _DU_AUTO, which enforces DU, and production reaches build_multi_lineup
    # through build_candidate_lineup_bank under bank_constraint_scope=
    # 'selection', which passes None. The probe was measuring a strictly harder
    # solve than the build it estimates, so its timing ran long and exit 3
    # could fire on a constraint the build never applies.
    multi = build_multi_lineup(projections, n_lineups=probe_n, mode="wta", target="ceiling",
                               du_threshold_row=None)
    multi_s = time.monotonic() - t0
    built = len(multi["lineups"])

    # Cost per lineup grows with the number of priors, because each new lineup
    # carries overlap constraints against all of them. Scale the observed
    # per-lineup average by the ratio of bank size to probe size rather than
    # assuming it stays flat; that underestimates rather than overestimates.
    per_lineup = multi_s / max(built, 1)
    growth = max(bank_size / max(probe_n, 1), 1.0)
    base_bank_s = per_lineup * bank_size * (1 + (growth - 1) / 2)

    cross_game_pairs = 0
    game_of = {str(r.Player_ID): str(r.Game_ID) for r in projections.itertuples()}
    sps = [str(p) for p in projections[projections["Position"] == "P"]["Player_ID"]]
    for i in range(len(sps)):
        for j in range(i + 1, len(sps)):
            if game_of.get(sps[i]) != game_of.get(sps[j]):
                cross_game_pairs += 1
    augmentation_s = cross_game_pairs * single_s
    projected_s = base_bank_s + augmentation_s
    fits = projected_s <= args.budget

    report = {
        "pool_players": n_players,
        "viable_sp": n_sp,
        "cross_game_sp_pairs": cross_game_pairs,
        "entries": args.entries,
        "bank_size": bank_size,
        "single_lineup_s": round(single_s, 2),
        "multi_lineup_probe": {"n": probe_n, "built": built, "seconds": round(multi_s, 2)},
        "projected_base_bank_s": round(base_bank_s, 1),
        "projected_augmentation_s": round(augmentation_s, 1),
        "projected_total_s": round(projected_s, 1),
        "budget_s": args.budget,
        "fits_budget": fits,
        "slices_needed": max(1, int(projected_s / args.budget) + (0 if fits else 1)),
        "note": "measured on this pool and machine; deterministic review input, "
                "never an ROI, win-rate, or probability claim",
    }

    if args.json:
        print(json.dumps(report, indent=1))
    else:
        print(f"pool {n_players} players, {n_sp} SP, {cross_game_pairs} cross-game pairs")
        print(f"one lineup {single_s:.2f}s | {probe_n}-lineup probe {multi_s:.2f}s "
              f"({built} built)")
        print(f"projected: base bank {base_bank_s:.0f}s + augmentation "
              f"{augmentation_s:.0f}s = {projected_s:.0f}s")
        print(f"budget {args.budget:.0f}s -> {'FITS' if fits else 'EXCEEDS'}")
        if not fits:
            print(f"\nrun_slate will not finish in one call. Either:")
            print(f"  - pass time_budget_s={args.budget:.0f} and accept a partial bank, or")
            print(f"  - build across ~{report['slices_needed']} slices with "
                  f"mlb_engine.optimize.bank_cache, then pass candidates_override")
            print("Do NOT trim the player pool to fit; that changes strategy, not effort.")
    return 0 if fits else 3


if __name__ == "__main__":
    raise SystemExit(main())
