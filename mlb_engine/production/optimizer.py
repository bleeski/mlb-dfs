"""Sparse exact lineup constraints and a fully checked HiGHS boundary."""

from __future__ import annotations

import math
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix

from mlb_engine.optimize.roster_contracts import get_contract
from .contracts import Candidate, Controls, Entry, Player
from .evidence import Prepared


class BudgetExpired(RuntimeError):
    pass


class Deadline:
    def __init__(self, seconds: float):
        if not math.isfinite(seconds) or seconds <= 0:
            raise ValueError("positive finite time budget required")
        self.started = time.monotonic()
        self.end = self.started + seconds

    def remaining(self, reserve: float = 0.0) -> float:
        value = self.end - time.monotonic() - reserve
        if value <= 0:
            raise BudgetExpired("shared build deadline reached")
        return value


@dataclass
class Solve:
    x: np.ndarray | None
    report: dict


class LinearModel:
    def __init__(self):
        self.cost: list[float] = []
        self.upper: list[float] = []
        self.integral: list[int] = []
        self.rows: list[dict[int, float]] = []
        self.lower_rows: list[float] = []
        self.upper_rows: list[float] = []
        self.names: list[str] = []

    def variable(self, reward=0.0, upper=1.0, integral=True) -> int:
        if not math.isfinite(reward) or not math.isfinite(upper) or upper < 0:
            raise ValueError("invalid solver objective or bound")
        index = len(self.cost)
        self.cost.append(-float(reward))
        self.upper.append(float(upper))
        self.integral.append(int(integral))
        return index

    def add(
        self, name: str, coefficients: dict[int, float], lower=-np.inf, upper=np.inf
    ):
        if math.isnan(lower) or math.isnan(upper) or lower > upper:
            raise ValueError("invalid constraint bounds")
        if any(not math.isfinite(v) for v in coefficients.values()):
            raise ValueError("nonfinite constraint coefficient")
        self.names.append(name)
        self.rows.append({k: float(v) for k, v in coefficients.items() if v})
        self.lower_rows.append(float(lower))
        self.upper_rows.append(float(upper))

    def solve(self, deadline: Deadline, seconds: float) -> Solve:
        remaining = min(seconds, deadline.remaining())
        ri, ci, values = [], [], []
        for r, row in enumerate(self.rows):
            for c, value in row.items():
                ri.append(r)
                ci.append(c)
                values.append(value)
        matrix = coo_matrix(
            (values, (ri, ci)), shape=(len(self.rows), len(self.cost))
        ).tocsc()
        lb, ub = np.asarray(self.lower_rows), np.asarray(self.upper_rows)
        started = time.perf_counter()
        report = {
            "backend": "scipy_highs",
            "variables": len(self.cost),
            "constraints": len(self.rows),
            "nonzeros": matrix.nnz,
            "time_limit_seconds": remaining,
            "relaxations_applied": [],
        }
        if not self.cost:
            report.update(status="EMPTY_MODEL", proven_infeasible=False)
            return Solve(None, report)
        result = milp(
            c=np.asarray(self.cost),
            integrality=np.asarray(self.integral),
            bounds=Bounds(np.zeros(len(self.cost)), np.asarray(self.upper)),
            constraints=LinearConstraint(matrix, lb, ub),
            options={
                "time_limit": min(remaining, deadline.remaining()),
                "mip_rel_gap": 0.0,
                "disp": False,
            },
        )
        code = int(result.status)
        report.update(
            status={
                0: "OPTIMAL",
                1: "LIMIT",
                2: "INFEASIBLE",
                3: "UNBOUNDED",
                4: "ERROR",
            }.get(code, "ERROR"),
            scipy_status=code,
            proven_infeasible=code == 2,
            elapsed_seconds=time.perf_counter() - started,
            mip_gap=_finite_or_none(getattr(result, "mip_gap", None)),
            mip_node_count=_finite_or_none(getattr(result, "mip_node_count", None)),
            incumbent_valid=False,
        )
        x = getattr(result, "x", None)
        # Even "success" must pass integrality, variable bounds and every row.
        if code not in {0, 1} or x is None:
            return Solve(None, report)
        x = np.asarray(x, dtype=float)
        if x.shape != (len(self.cost),) or not np.isfinite(x).all():
            return Solve(None, report)
        integers = np.asarray(self.integral, dtype=bool)
        if np.any(np.abs(x[integers] - np.rint(x[integers])) > 1e-6):
            return Solve(None, report)
        x[integers] = np.rint(x[integers])
        lhs = matrix @ x
        if (
            np.any(x < -1e-7)
            or np.any(x > np.asarray(self.upper) + 1e-7)
            or np.any(lhs < lb - 1e-6)
            or np.any(lhs > ub + 1e-6)
        ):
            return Solve(None, report)
        report["incumbent_valid"] = True
        if code == 1:
            report["status"] = "FEASIBLE_LIMIT"
        return Solve(x, report)

    def diagnostic_relaxation(self, deadline: Deadline) -> dict:
        """Minimum named policy-row slack; diagnostic only, never an export."""
        diag = LinearModel()
        diag.cost = [0.0] * len(self.cost)
        diag.upper, diag.integral = list(self.upper), list(self.integral)
        slack_names = {}
        for name, row, lower, upper in zip(
            self.names, self.rows, self.lower_rows, self.upper_rows
        ):
            coefficients = dict(row)
            relaxable = name.startswith(
                ("exposure:", "overlap:", "stack:", "salary_floor:")
            )
            if relaxable:
                scale = 50000.0 if name.startswith("salary_floor:") else 1.0
                if math.isfinite(upper):
                    s = diag.variable(reward=-1 / scale, upper=1e7, integral=False)
                    coefficients[s] = -1
                    slack_names[s] = name + ":upper"
                if math.isfinite(lower):
                    s = diag.variable(reward=-1 / scale, upper=1e7, integral=False)
                    coefficients[s] = 1
                    slack_names[s] = name + ":lower"
            diag.add(name, coefficients, lower, upper)
        solved = diag.solve(deadline, min(3.0, deadline.remaining()))
        proposed = (
            {
                name: float(solved.x[s])
                for s, name in slack_names.items()
                if solved.x[s] > 1e-6
            }
            if solved.x is not None
            else {}
        )
        return {
            "applied": False,
            "scope": "this exact model only",
            "solver": solved.report,
            "minimum_policy_slack": proposed,
            "action": "review named controls or correct input evidence; no bounds were changed",
        }


def _finite_or_none(value):
    return float(value) if value is not None and math.isfinite(float(value)) else None


def count_cap(fraction: float, n: int) -> int:
    return math.floor(fraction * n + 1e-9)


def signature(roster: tuple[str, ...], mode: str) -> tuple[str, ...]:
    return (
        (roster[0], *sorted(roster[1:]))
        if mode == "SHOWDOWN"
        else tuple(sorted(roster))
    )


def candidate(
    roster: tuple[str, ...], mode: str, players: dict[str, Player], prepared: Prepared
) -> Candidate:
    projections = {x.player_id: x.mean for x in prepared.bundle.projections}
    selected = [players[pid] for pid in roster]
    counts = Counter(
        p.team for p in selected if mode == "SHOWDOWN" or "P" not in p.positions
    )
    primary = min(counts, key=lambda t: (-counts[t], t)) if counts else ""
    return Candidate(
        roster,
        signature(roster, mode),
        frozenset(p.person_id for p in selected),
        frozenset(p.person_id for p in selected if "P" in p.positions),
        frozenset(p.team for p in selected),
        frozenset(p.game_id for p in selected),
        selected[0].person_id if mode == "SHOWDOWN" else None,
        sum(
            projections.get(p.person_id, 0.0)
            * (1.5 if mode == "SHOWDOWN" and i == 0 else 1.0)
            for i, p in enumerate(selected)
        ),
        primary,
    )


def fixed_slots(
    entry: Entry,
    players: dict[str, Player],
    prepared: Prepared,
    now: datetime,
    mutable: bool,
) -> dict[int, str]:
    games = {g.game_id: g for g in prepared.bundle.games}
    fixed = {}
    for i, pid in enumerate(entry.roster):
        if not pid:
            continue
        if pid not in players:
            raise ValueError("parent entry contains an ID outside the salary pool")
        p = players[pid]
        locked = now >= p.start or games[p.game_id].state in {"in_progress", "final"}
        if not mutable or locked:
            fixed[i] = pid
    return fixed


def _combine(expressions):
    result = defaultdict(float)
    for expression in expressions:
        for k, v in expression.items():
            result[k] += v
    return dict(result)


def _add_lineup(
    model: LinearModel,
    entry: Entry,
    mode: str,
    players: dict[str, Player],
    prepared: Prepared,
    controls: Controls,
    now: datetime,
    mutable: bool,
    rewards: dict[str, float] | None = None,
    forbidden: list[Candidate] | None = None,
):
    slots = get_contract(mode).slots
    fixed = fixed_slots(entry, players, prepared, now, mutable)
    means = {p.player_id: p.mean for p in prepared.bundle.projections}
    games = {g.game_id: g for g in prepared.bundle.games}
    assignments, by_person, by_id = {}, defaultdict(dict), defaultdict(dict)
    for s, slot in enumerate(slots):
        for pid, p in sorted(players.items()):
            slot_ok = p.role == slot if mode == "SHOWDOWN" else slot in p.positions
            if not slot_ok:
                continue
            locked = now >= p.start or games[p.game_id].state in {
                "in_progress",
                "final",
            }
            if s in fixed:
                available = fixed[s] == pid
            else:
                available = mutable and pid in prepared.eligible and not locked
            if not available:
                continue
            points = (rewards or means).get(p.person_id, 0.0)
            idx = model.variable(reward=points * (1.5 if slot == "CPT" else 1.0))
            assignments[(s, pid)] = idx
            by_person[p.person_id][idx] = 1.0
            by_id[pid][idx] = 1.0
        model.add(
            f"slot:{entry.entry_id}:{s}",
            {v: 1 for (j, _), v in assignments.items() if j == s},
            1,
            1,
        )
    for person, expression in by_person.items():
        model.add(f"person:{entry.entry_id}:{person}", expression, upper=1)
    salary = {v: players[pid].salary for (_, pid), v in assignments.items()}
    model.add(f"salary_cap:{entry.entry_id}", salary, upper=50000)
    if controls.salary_floor:
        model.add(f"salary_floor:{entry.entry_id}", salary, lower=controls.salary_floor)
    hitters_by_team = defaultdict(dict)
    for (s, pid), idx in assignments.items():
        if mode == "SHOWDOWN" or "P" not in players[pid].positions:
            hitters_by_team[players[pid].team][idx] = 1
    if mode == "CLASSIC":
        for team, expression in hitters_by_team.items():
            model.add(f"team_limit:{entry.entry_id}:{team}", expression, upper=5)
        used_games = []
        for gid in sorted({p.game_id for p in players.values()}):
            expression = {
                v: 1
                for (_, pid), v in assignments.items()
                if players[pid].game_id == gid
            }
            flag = model.variable()
            used_games.append(flag)
            model.add("game_used_lower", {**expression, flag: -1}, lower=0)
            model.add("game_used_upper", {**expression, flag: -10}, upper=0)
        model.add(f"two_games:{entry.entry_id}", {v: 1 for v in used_games}, lower=2)
    else:
        for team in sorted({p.team for p in players.values()}):
            expression = {
                v: 1 for (_, pid), v in assignments.items() if players[pid].team == team
            }
            model.add(f"both_teams:{entry.entry_id}:{team}", expression, lower=1)
    # The same per-pitcher policy also applies when a pitcher occupies CPT/UTIL.
    for person in sorted(by_person):
        p = next(p for p in players.values() if p.person_id == person)
        if "P" not in p.positions:
            continue
        facing = {
            v: 1
            for (_, pid), v in assignments.items()
            if "P" not in players[pid].positions
            and players[pid].team == p.opponent
            and players[pid].game_id == p.game_id
        }
        n = len(slots)
        expression = _combine(
            [facing, {k: n * v for k, v in by_person[person].items()}]
        )
        allowance = controls.max_opposing_hitters_per_sp
        if allowance is None:
            allowance = 0 if mode == "CLASSIC" else n
        model.add(
            f"opposing_pitcher:{entry.entry_id}:{person}",
            expression,
            upper=n + allowance,
        )
    if controls.stack_team:
        expression = hitters_by_team.get(controls.stack_team, {})
        model.add(
            f"stack:{entry.entry_id}",
            expression,
            controls.stack_min,
            controls.stack_max,
        )
        if controls.bringback_min:
            opponents = {
                p.opponent for p in players.values() if p.team == controls.stack_team
            }
            if len(opponents) != 1:
                raise ValueError("stack team has ambiguous opponent")
            model.add(
                f"stack:bringback:{entry.entry_id}",
                hitters_by_team.get(next(iter(opponents)), {}),
                lower=controls.bringback_min,
            )
    for old in forbidden or []:
        model.add(
            "distinct_candidate",
            _combine(by_id.get(pid, {}) for pid in old.signature),
            upper=len(slots) - 1,
        )
    if controls.primary_stack_min_size:
        indicators = []
        for expression in hitters_by_team.values():
            flag = model.variable()
            indicators.append(flag)
            model.add(
                "stack:primary_minimum",
                {**expression, flag: -controls.primary_stack_min_size},
                lower=0,
            )
        model.add("stack:has_primary", {v: 1 for v in indicators}, lower=1)
    # Ordered symmetry for interchangeable UNLOCKED slots removes permutations.
    ranks = {pid: i + 1 for i, pid in enumerate(sorted(players))}
    for s in range(len(slots) - 1):
        t = s + 1
        if slots[s] == slots[t] and s not in fixed and t not in fixed:
            expr = {
                v: ranks[pid] * (1 if j == s else -1)
                for (j, pid), v in assignments.items()
                if j in {s, t}
            }
            model.add("slot_symmetry", expr, upper=-1)
    return assignments, dict(by_person)


def solve_portfolio(
    entries: tuple[Entry, ...],
    mode: str,
    players: dict[str, Player],
    prepared: Prepared,
    controls: Controls,
    now: datetime,
    mutable_ids: set[str],
    deadline: Deadline,
) -> tuple[dict, dict]:
    """Baseline MILP over the complete eligible salary universe, including fixed rows."""
    model = LinearModel()
    mappings, person_maps = [], []
    for entry in entries:
        deadline.remaining()
        mapping, people = _add_lineup(
            model,
            entry,
            mode,
            players,
            prepared,
            controls,
            now,
            entry.entry_id in mutable_ids,
        )
        mappings.append(mapping)
        person_maps.append(people)
    n = len(entries)
    canonical = {p.person_id: p for p in players.values()}
    for person, player in sorted(canonical.items()):
        expr = _combine(m.get(person, {}) for m in person_maps)
        cap = controls.max_player_exposure
        if "P" in player.positions:
            cap = min(cap, controls.max_pitcher_exposure)
        model.add(f"exposure:player:{person}", expr, upper=count_cap(cap, n))
        if mode == "SHOWDOWN":
            cpt = {
                v: 1
                for m in mappings
                for (s, pid), v in m.items()
                if s == 0 and players[pid].person_id == person
            }
            model.add(
                f"exposure:captain:{person}",
                cpt,
                upper=count_cap(controls.max_captain_exposure, n),
            )
    for kind, limits in (
        ("team", controls.max_team_exposure),
        ("game", prepared.game_caps),
    ):
        for key, cap in sorted(limits.items()):
            flags = []
            for mapping in mappings:
                expr = {
                    v: 1
                    for (_, pid), v in mapping.items()
                    if (players[pid].team if kind == "team" else players[pid].game_id)
                    == key
                }
                flag = model.variable()
                flags.append(flag)
                model.add("presence_lower", {**expr, flag: -1}, lower=0)
                model.add(
                    "presence_upper",
                    {**expr, flag: -len(get_contract(mode).slots)},
                    upper=0,
                )
            model.add(
                f"exposure:{kind}:{key}", {v: 1 for v in flags}, upper=count_cap(cap, n)
            )
    if controls.max_primary_stack_exposure < 1 or controls.primary_stack_min_size:
        primary_flags = defaultdict(dict)
        team_names = sorted({p.team for p in players.values()})
        big_m = len(get_contract(mode).slots) + 1
        for entry, mapping in zip(entries, mappings):
            counts = {
                team: {
                    v: 1
                    for (_, pid), v in mapping.items()
                    if players[pid].team == team
                    and (mode == "SHOWDOWN" or "P" not in players[pid].positions)
                }
                for team in team_names
            }
            flags = {team: model.variable() for team in team_names}
            model.add("one_primary_stack", {v: 1 for v in flags.values()}, 1, 1)
            for team, flag in flags.items():
                primary_flags[team][flag] = 1
                model.add(
                    "stack:primary_size",
                    _combine([counts[team], {flag: -controls.primary_stack_min_size}]),
                    lower=0,
                )
                for other in team_names:
                    if other == team:
                        continue
                    # Lexicographically first team wins a size tie, matching final QA.
                    minimum = 1 if other < team else 0
                    expression = _combine(
                        [
                            counts[team],
                            {k: -v for k, v in counts[other].items()},
                            {flag: -big_m},
                        ]
                    )
                    model.add(
                        "primary_stack_tiebreak", expression, lower=minimum - big_m
                    )
        for team, expression in primary_flags.items():
            model.add(
                "exposure:primary_stack:" + team,
                expression,
                upper=count_cap(controls.max_primary_stack_exposure, n),
            )
    if controls.max_sp_pair_repetition is not None and mode == "CLASSIC":
        from itertools import combinations

        pitcher_ids = sorted(pid for pid, p in canonical.items() if "P" in p.positions)
        for a, b in combinations(pitcher_ids, 2):
            flags = []
            for people in person_maps:
                if a not in people or b not in people:
                    continue
                flag = model.variable(integral=False)
                flags.append(flag)
                model.add(
                    "sp_pair_present",
                    _combine([people[a], people[b], {flag: -1}]),
                    upper=1,
                )
            model.add(
                f"exposure:sp_pair:{a}:{b}",
                {v: 1 for v in flags},
                upper=controls.max_sp_pair_repetition,
            )
    for a, entry in enumerate(entries):
        deadline.remaining()
        for b in range(a + 1, n):
            same_contest = entry.contest_id == entries[b].contest_id
            limit = controls.max_shared_players
            if limit is not None:
                shared = []
                for person in sorted(person_maps[a].keys() & person_maps[b].keys()):
                    z = model.variable(integral=False)
                    shared.append(z)
                    expr = _combine(
                        [person_maps[a][person], person_maps[b][person], {z: -1}]
                    )
                    model.add("shared_person", expr, upper=1)
                model.add(
                    f"overlap:{entry.entry_id}:{entries[b].entry_id}",
                    {v: 1 for v in shared},
                    upper=limit,
                )
            if same_contest:
                # Role-ID equality for Showdown, person equality for Classic.
                both = []
                for pid in sorted(players):
                    ma = {v: 1 for (_, p), v in mappings[a].items() if p == pid}
                    mb = {v: 1 for (_, p), v in mappings[b].items() if p == pid}
                    if not ma or not mb:
                        continue
                    z = model.variable(integral=False)
                    both.append(z)
                    model.add("same_role_player", _combine([ma, mb, {z: -1}]), upper=1)
                model.add(
                    "contest_unique",
                    {v: 1 for v in both},
                    upper=get_contract(mode).roster_size - 1,
                )
    solved = model.solve(
        deadline, min(controls.per_solve_seconds, deadline.remaining(2))
    )
    solved.report["search_scope"] = "full_eligible_salary_universe"
    if solved.x is None:
        if solved.report.get("proven_infeasible"):
            try:
                solved.report["diagnostic_relaxation"] = model.diagnostic_relaxation(
                    deadline
                )
            except BudgetExpired:
                solved.report["diagnostic_relaxation"] = {
                    "applied": False,
                    "state": "BUDGET_EXPIRED",
                }
        return {}, solved.report
    output = {}
    for entry, mapping in zip(entries, mappings):
        selected = {s: pid for (s, pid), v in mapping.items() if solved.x[v] > 0.5}
        output[entry.entry_id] = tuple(
            selected[s] for s in range(get_contract(mode).roster_size)
        )
    return output, solved.report


def generate_candidates(
    entry: Entry,
    mode: str,
    players: dict[str, Player],
    prepared: Prepared,
    controls: Controls,
    now: datetime,
    mutable: bool,
    initial: Candidate,
    rewards: list[dict[str, float]],
    deadline: Deadline,
) -> tuple[list[Candidate], list[dict]]:
    bank, reports = [initial], []
    if not mutable:
        return bank, reports
    for values in rewards[: controls.max_candidates_per_entry - 1]:
        deadline.remaining(3)
        model = LinearModel()
        mapping, _ = _add_lineup(
            model, entry, mode, players, prepared, controls, now, mutable, values, bank
        )
        solved = model.solve(
            deadline, min(controls.per_solve_seconds, deadline.remaining(3))
        )
        reports.append(solved.report)
        if solved.x is None:
            # A numerical error is never a reason to relax a strategy constraint.
            break
        selected = {s: pid for (s, pid), v in mapping.items() if solved.x[v] > 0.5}
        roster = tuple(selected[s] for s in range(get_contract(mode).roster_size))
        bank.append(candidate(roster, mode, players, prepared))
    return bank, reports
