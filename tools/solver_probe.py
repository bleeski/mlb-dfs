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
    python tools/solver_probe.py --date 2026-07-22 [--entries 10] [--budget 130]
    python tools/solver_probe.py --salary path/to/DKSalaries.csv --lineups feed.json

The default budget is RESOLVED for this host (R349), not a constant: an explicit
--budget, then MLB_DFS_CALL_BUDGET_S, then the host's own declared bash ceiling
discounted for container start and the engine import, then its profile, then
130s for a host that has stated nothing. 130 is Cowork's inner bash budget
(CLAUDE.md, Sandbox) and it stays the conservative floor. It was 43.0 until 2026-09-03 -- the
ninth and last live member of the retired 45-second ceiling R271 swept out of
five other files, deliberately left in place there because changing it changes
this probe's VERDICT rather than a doc string. R290(c) is the item about
refusals an operator reads under a clock, and that is exactly what this one was:
against 43 the probe answered EXCEEDS, exit 3, for banks that fit the real
window with 87 seconds to spare, and it sent a session slicing a bank that
never needed slicing. A verdict measured against a ceiling that no longer
exists is not conservative, it is wrong. Pass --budget to measure against a
different window; the report and the printed line both name the number used and
where it came from.

Exit codes:
    0  projected build fits the budget
    3  projected build exceeds the budget (use time_budget_s or bank_cache slices)
    4  inputs missing, unreadable, or the wrong geometry for this probe

There is no exit 1: every refusal carries one of the codes above
(R364). CLAUDE.md's session-start step 3 mandates this tool before any
build, so a traceback here is a refusal a session cannot classify.

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
from mlb_engine.repo_env import call_budget_s, call_budget_source  # noqa: E402

# The one number, named once -- and since R349 (2026-09-16) RESOLVED once rather
# than hardcoded once. It was 130.0, CLAUDE.md's Cowork inner bash budget, which
# is right on Cowork and wrong by a factor of five on a Claude Code container
# that declares a 900s ceiling. The lesson of 43.0 was not "pin the number", it
# was "never let a verdict quote a ceiling that does not exist here", and a
# constant cannot satisfy that on three hosts.
#
# `mlb_engine.repo_env.call_budget_s` holds the precedence and the host probe;
# 130.0 survives there as the profile for a host that has told us nothing. Do
# not re-derive either value per call.
DEFAULT_BUDGET_S = call_budget_s()
DEFAULT_BUDGET_SOURCE = call_budget_source()


class ProbeInputError(Exception):
    """An input this probe cannot use, carrying the contract's exit code.

    R364, 2026-09-19. Every refusal here used to be a bare ``SystemExit`` or an
    unhandled ``FileNotFoundError``, so the tool exited 1 -- with a traceback in
    the missing-file case -- while its own docstring and CLAUDE.md's
    session-start step 3 document 0/3/4. This repo's own phrase for that is "a
    crash wearing a refusal's label", and it lands at the moment a BUILD session
    is orienting under a slate clock.
    """

    def __init__(self, message: str, code: int = 4):
        super().__init__(message)
        self.code = code


def _resolve_inputs(args) -> tuple[Path, Path]:
    if args.salary and args.lineups:
        salary, feed = Path(args.salary), Path(args.lineups)
    else:
        if not args.date:
            raise ProbeInputError("need --date, or both --salary and --lineups")
        slate = REPO / "data" / "slates" / args.date
        salary = Path(args.salary) if args.salary else slate / "DKSalaries.csv"
        feed = Path(args.lineups) if args.lineups else slate / "lineups_feed.json"

    # EXISTENCE BEFORE GEOMETRY, and the order is the fix (R364). It ran the
    # other way round: `detect_salary_contract` opens the path unguarded
    # (`dk_entries_manager.py:280-289`), so a slate directory holding
    # `DKSalaries_showdown.csv` but no canonical `DKSalaries.csv` -- an ordinary
    # state -- raised FileNotFoundError out of a helper, exit 1, traceback.
    if not salary.exists():
        raise ProbeInputError(f"missing input: salary file {salary} does not exist")

    # The default name is date-keyed and shared, so it can hold a Showdown file
    # left by another build for the same date. This probe reports whether the
    # bank fits the execution budget; timing a six-slot pool as a ten-slot one
    # answers a question nobody asked.
    from mlb_engine.entries.dk_entries_manager import detect_salary_contract
    contract = detect_salary_contract(salary)
    if contract != "CLASSIC":
        raise ProbeInputError(
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
    # R290(c) rider, 2026-09-03. See the module docstring: 43.0 was the retired
    # 45-second ceiling's ninth member and it moved this tool's verdict, which
    # is why R271 left it and why this item is the right place to decide it.
    ap.add_argument("--budget", type=float, default=DEFAULT_BUDGET_S,
                    help=f"seconds of compute available per call "
                         f"(default {DEFAULT_BUDGET_S:.0f}, resolved for this "
                         f"host -- {DEFAULT_BUDGET_SOURCE})")
    ap.add_argument("--json", action="store_true", help="emit JSON only")
    args = ap.parse_args()

    try:
        salary, feed_path = _resolve_inputs(args)
    except ProbeInputError as exc:
        print(str(exc), file=sys.stderr)
        return exc.code

    # R296(g). This refused at exit 4 -- "missing inputs" -- whenever the feed
    # was absent, which since R143 is the NORMAL state of a fully DK-covered
    # slate: DK publishes the batting order in the salary file's `Starting`
    # column, `build_slate.py` makes no API call at all, and nothing writes
    # `data/slates/<date>/lineups_feed.json`. CLAUDE.md's session-start step 3
    # mandates this probe before any build, so the mandated step refused on the
    # ordinary case and the step is skipped in practice.
    #
    # An absent feed is not missing input here. `build_slate_pool` takes
    # `{"games": []}` and falls through to the platoon projection, which is what
    # the probe is timing anyway: this instrument answers "does the bank fit the
    # budget", and the answer moves with the pool SIZE, not with which nine bats
    # per team are confirmed. Say which pool was timed rather than implying a
    # confirmed one.
    feed: dict = {"games": []}
    feed_source = "absent"
    if feed_path.exists():
        try:
            feed = json.loads(feed_path.read_text(encoding="utf-8"))
            feed_source = str(feed_path)
        except (OSError, ValueError) as exc:
            feed = {"games": []}
            feed_source = f"unreadable ({type(exc).__name__})"
    if feed_source != str(feed_path):
        print(f"lineups feed {feed_source}: timing the platoon-projected pool. "
              f"On a DK-covered slate this is the normal state (R143) and the "
              f"timing still answers whether the bank fits the budget; pass "
              f"--lineups to time a confirmed pool instead.", file=sys.stderr)

    pool = build_slate_pool(str(salary), feed)
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
    # R405(c). The cluster-limited jobs every multi-entry posture now asks for:
    # at least (1 - pct) x E x 2 lineups, each one solve, at the loosest posture
    # default below 1.0 (0.50 on every multi-entry posture today). Counted
    # rather than left out, because a probe that omits a phase the build runs
    # says FITS about a different build.
    from mlb_engine.pipeline.execution_pipeline import (
        STRATEGY_DEFAULTS, resolve_consensus_limited_request)
    _cluster_pcts = [v["controls"].get("max_consensus_cluster_share_pct")
                     for v in STRATEGY_DEFAULTS.values()]
    _cluster_pcts = [float(x) for x in _cluster_pcts if x is not None and float(x) < 1.0]
    consensus_request = resolve_consensus_limited_request(
        {"max_consensus_cluster_share_pct": max(_cluster_pcts)} if _cluster_pcts else {},
        args.entries)
    consensus_limited_s = int(consensus_request["min_candidates"] or 0) * single_s
    # R406. The three non-projection sleeves each ask for twice the entries
    # they seat, at the default multi-entry weights (40/20/20/20); one solve
    # per lineup, like the term above.
    from mlb_engine.optimize.classic_sleeves import DEFAULT_WEIGHTS, largest_remainder
    _seats = largest_remainder(int(args.entries), DEFAULT_WEIGHTS) if args.entries > 1 else {}
    sleeve_lineups = sum(2 * n for s, n in _seats.items() if s != "projection")
    sleeves_s = sleeve_lineups * single_s
    projected_s = base_bank_s + augmentation_s + consensus_limited_s + sleeves_s
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
        "projected_consensus_limited_s": round(consensus_limited_s, 1),
        "consensus_limited_min_candidates": consensus_request["min_candidates"],
        "projected_sleeves_s": round(sleeves_s, 1),
        "sleeve_lineups": sleeve_lineups,
        "projected_total_s": round(projected_s, 1),
        "budget_s": args.budget,
        # R290(c) rider. A verdict states the ceiling it was measured against
        # and where that number came from, so the next reader of an EXCEEDS can
        # tell a real overrun from a stale constant.
        "budget_source": (DEFAULT_BUDGET_SOURCE
                          if args.budget == DEFAULT_BUDGET_S
                          else "--budget, supplied by the caller"),
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
              f"{augmentation_s:.0f}s + consensus-limited "
              f"{consensus_limited_s:.0f}s ({consensus_request['min_candidates']} "
              f"lineups, R405) + sleeves {sleeves_s:.0f}s ({sleeve_lineups} lineups, "
              f"R406) = {projected_s:.0f}s")
        print(f"budget {args.budget:.0f}s ({report['budget_source']}) -> "
              f"{'FITS' if fits else 'EXCEEDS'}")
        if not fits:
            print(f"\nrun_slate will not finish in one call. Either:")
            print(f"  - pass time_budget_s={args.budget:.0f} and accept a partial bank, or")
            print(f"  - build across ~{report['slices_needed']} slices with "
                  f"mlb_engine.optimize.bank_cache, then pass candidates_override")
            print("Do NOT trim the player pool to fit; that changes strategy, not effort.")
    return 0 if fits else 3


if __name__ == "__main__":
    raise SystemExit(main())
