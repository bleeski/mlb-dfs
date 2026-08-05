#!/usr/bin/env python3
"""stack_shape_probe.py -- what a primary-stack floor is FEASIBLE to build, and what it COSTS.

R37 decision input, 2026-08-05. The 2026-08-04 regrade of the field-shape
analysis (ledger 3.17) asked one question before any `primary_stack_min_size`
floor could be sized: on thin slates, is our large "<=3 primary" share a
FEASIBILITY outcome (the team cap crossed with `max_shared_players` leaving no
room for a bigger stack) or a solver CHOICE? This answers it by measurement
rather than by reading the constraint set, and it answers the follow-on question
the decision actually turns on: what does forcing a floor cost against the
unconstrained optimum on the same pool?

Two probes per salary file:

1. **Feasibility.** For each team with at least five rostered hitters, solve with
   `stack_constraints={'team': T, 'min_size': N, 'max_size': 5}` for N in 3, 4, 5
   and count how many teams admit a solution. Also solve with NO stack constraint
   and report the primary-stack size the objective picks on its own, which is the
   "choice" half of the question.
2. **Cost.** The best objective reachable under each floor, against the
   unconstrained best, as a percentage. This is the price of the constraint in
   projected points on that pool.

Truthful labels. Every number this prints is a deterministic solver outcome on a
staged DraftKings salary file. None of it is ROI, a win rate, a cash rate, or a
probability claim, and it says nothing about what any shape is worth in a
contest; that evidence lives in the archive analyses and is conditioned on
archetype there. This tool measures what the ENGINE can build and what the
constraint costs, which is the half the archive cannot see.

Two caveats that belong with any number this prints:

- With no Savant CSVs supplied, Floor and Ceiling are uniform multiples of
  Base_Projection, so a ceiling-target and a floor-target solve are
  rank-identical and the two cost columns agree exactly. That is the known
  uniform-multiplier property the xISO block exists to break, not a bug here.
  Pass the enrichment CSVs to measure a variance-aware cost.
- This is single-lineup feasibility. A PORTFOLIO floor also has to satisfy
  `max_primary_stack_exposure_pct` and `max_shared_players` across N entries, and
  those can bind where one lineup does not. Use `tools/solver_probe.py` for the
  portfolio question.

Usage:
    python tools/stack_shape_probe.py --salary <DKSalaries.csv> [--salary ...]
    python tools/stack_shape_probe.py --slate-dir data/slates/2026-07-30
    python tools/stack_shape_probe.py --salary a.csv --json out.json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

VERSION = "v1.0"
FLOORS = (3, 4, 5)
MIN_HITTERS_TO_STACK = 5


def _proxy_rows(salary_csv: Path, top_sp_per_team: int = 1) -> List[Dict[str, Any]]:
    """Emergency-proxy rows off the salary file: Player_ID plus AvgPointsPerGame.

    The same shape the golden production replay builds, and the same pitcher
    filter: relievers are never probable starters, and capping arms per team
    keeps the pool from admitting two same-team starters.
    """
    from mlb_engine.intake.slate_intake_manager import parse_dk_salary_csv

    sp_by_team: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    rows: List[Dict[str, Any]] = []
    for player in parse_dk_salary_csv(str(salary_csv)):
        raw = player.raw or {}
        avg = raw.get("AvgPointsPerGame") or raw.get("Avg Points Per Game")
        try:
            base = float(avg)
        except (TypeError, ValueError):
            continue
        if base <= 0:
            continue
        row = {"Player_ID": player.player_id, "AvgPointsPerGame": base,
               "_salary": player.salary}
        position = raw.get("Position")
        if position == "SP":
            sp_by_team[player.team].append(row)
        elif position == "RP":
            continue
        else:
            rows.append(row)
    for team_rows in sp_by_team.values():
        team_rows.sort(key=lambda r: -r["_salary"])
        rows.extend(team_rows[:top_sp_per_team])
    for row in rows:
        row.pop("_salary", None)
    return rows


def _hitter_shape(lineup) -> List[int]:
    """Hitter counts per team, descending: the archive's shape family grouping."""
    hitters = lineup[lineup["Assigned_Position"] != "P"]
    return sorted(Counter(hitters["Team"]).values(), reverse=True)


def _label(counts: Sequence[int]) -> str:
    return "-".join(str(c) for c in counts)


def _stackable_teams(frame) -> List[str]:
    hitters = frame[frame["Position"].apply(
        lambda p: "P" not in str(p).split("/"))]
    return sorted(team for team, n in Counter(hitters["Team"]).items()
                  if n >= MIN_HITTERS_TO_STACK)


def probe_salary_file(salary_csv: Path, target: str = "ceiling",
                      savant_batting: Optional[str] = None,
                      savant_pitching: Optional[str] = None) -> Dict[str, Any]:
    from mlb_engine.optimize import optimizer_v3 as opt
    from mlb_engine.pipeline import execution_pipeline as epi

    frame, _enrichment = epi._assemble_projection_frame(
        str(salary_csv), _proxy_rows(salary_csv), "emergency_proxy",
        savant_batting, savant_pitching, None)
    teams = _stackable_teams(frame)
    result: Dict[str, Any] = {
        "salary_csv": salary_csv.name,
        "target": target,
        "pool_rows": int(len(frame)),
        "games": int(frame["Game_ID"].nunique()),
        "teams_stackable": len(teams),
        "enriched": bool(savant_batting or savant_pitching),
        "floors": {},
        "note": "deterministic solver outcomes; never an ROI, win-rate or "
                "probability claim",
    }

    free, free_obj = opt.build_single_lineup(frame, target=target)
    if free is None:
        result["unconstrained"] = None
        return result
    free_shape = _hitter_shape(free)
    result["unconstrained"] = {
        "objective": round(float(free_obj), 4),
        "shape": _label(free_shape),
        "primary_size": int(free_shape[0]) if free_shape else None,
    }

    for floor in FLOORS:
        feasible, shapes, best_obj, best_shape = 0, [], None, None
        for team in teams:
            lineup, objective = opt.build_single_lineup(
                frame, target=target,
                stack_constraints={"team": team, "min_size": floor, "max_size": 5})
            if lineup is None:
                continue
            feasible += 1
            shape = _label(_hitter_shape(lineup))
            shapes.append(shape)
            if best_obj is None or objective > best_obj:
                best_obj, best_shape = float(objective), shape
        cost = (None if best_obj is None
                else round(100.0 * (float(free_obj) - best_obj) / float(free_obj), 4))
        result["floors"][str(floor)] = {
            "teams_feasible": feasible,
            "teams_considered": len(teams),
            "shape_counts": dict(Counter(shapes)),
            "best_objective": None if best_obj is None else round(best_obj, 4),
            "cost_pct_vs_unconstrained": cost,
            "best_shape": best_shape,
        }
    return result


def _print_report(results: List[Dict[str, Any]]) -> None:
    print(f"stack_shape_probe {VERSION}: primary-stack floor feasibility and cost")
    print("=" * 86)
    for r in results:
        free = r.get("unconstrained")
        print(f"\n{r['salary_csv']}  target={r['target']}  pool={r['pool_rows']} rows  "
              f"{r['games']} games  {r['teams_stackable']} teams with "
              f">={MIN_HITTERS_TO_STACK} hitters"
              + ("" if r["enriched"] else "  [uniform Floor/Ceiling multipliers]"))
        if free is None:
            print("  unconstrained solve: INFEASIBLE; nothing below is meaningful")
            continue
        print(f"  unconstrained: primary={free['primary_size']} "
              f"shape={free['shape']} objective={free['objective']:.2f}")
        for floor in FLOORS:
            block = r["floors"].get(str(floor)) or {}
            if not block.get("teams_feasible"):
                print(f"  floor {floor}: 0/{block.get('teams_considered', 0)} teams feasible")
                continue
            top = ", ".join(f"{s} x{n}" for s, n in
                            sorted(block["shape_counts"].items(),
                                   key=lambda kv: (-kv[1], kv[0]))[:4])
            print(f"  floor {floor}: {block['teams_feasible']}/{block['teams_considered']} "
                  f"teams feasible   cost {block['cost_pct_vs_unconstrained']:.2f}%   "
                  f"best {block['best_shape']}   shapes: {top}")
    print()
    print("Feasibility is per single lineup. A portfolio floor must also satisfy")
    print("max_primary_stack_exposure_pct and max_shared_players; see solver_probe.py.")


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--salary", action="append", default=[],
                    help="a DKSalaries.csv; repeatable")
    ap.add_argument("--slate-dir", action="append", default=[],
                    help="a data/slates/<date> directory; every Classic "
                         "DKSalaries*.csv in it is probed. Repeatable.")
    ap.add_argument("--target", default="ceiling", choices=["ceiling", "floor"],
                    help="solver objective (default ceiling)")
    ap.add_argument("--savant-batting", help="optional expected-stats batting CSV, "
                                             "for a variance-aware cost")
    ap.add_argument("--savant-pitching", help="optional expected-stats pitching CSV")
    ap.add_argument("--json", help="also write the full result here")
    args = ap.parse_args(argv)

    paths: List[Path] = [Path(p) for p in args.salary]
    for directory in args.slate_dir:
        for candidate in sorted(Path(directory).glob("DKSalaries*.csv")):
            if "showdown" in candidate.name.lower():
                continue
            paths.append(candidate)
    if not paths:
        print("nothing to probe: pass --salary or --slate-dir", file=sys.stderr)
        return 2

    results: List[Dict[str, Any]] = []
    for path in paths:
        if not path.exists():
            print(f"ERROR  missing salary file: {path}", file=sys.stderr)
            return 3
        results.append(probe_salary_file(
            path, target=args.target,
            savant_batting=args.savant_batting,
            savant_pitching=args.savant_pitching))

    _print_report(results)
    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
