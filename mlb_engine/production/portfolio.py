"""Candidate allocation and at most three re-solved, measured Pareto proposals."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime

import numpy as np

from .contracts import Candidate, Controls, Entry, Player
from .evidence import Prepared
from .optimizer import Deadline, LinearModel, candidate, count_cap, generate_candidates
from .simulation import Scenarios, pareto_improves, portfolio_metrics, settle_scenarios


def allocate_candidates(
    banks: dict[str, list[Candidate]],
    entries: tuple[Entry, ...],
    controls: Controls,
    game_caps: dict[str, float],
    utilities: dict[tuple[str, tuple[str, ...]], float],
    deadline: Deadline,
    extra_caps: dict[str, int] | None = None,
):
    model = LinearModel()
    options = []
    for entry in entries:
        for c in banks[entry.entry_id]:
            idx = model.variable(reward=utilities[(entry.entry_id, c.signature)])
            options.append((idx, entry, c))
        model.add(
            "one_candidate:" + entry.entry_id,
            {v: 1 for v, e, _ in options if e.entry_id == entry.entry_id},
            1,
            1,
        )
    n = len(entries)
    for kind, fraction in (
        ("people", controls.max_player_exposure),
        ("pitchers", controls.max_pitcher_exposure),
    ):
        members = sorted(set().union(*(getattr(c, kind) for _, _, c in options)))
        for member in members:
            cap = count_cap(fraction, n)
            if kind == "people" and member in (extra_caps or {}):
                cap = min(cap, extra_caps[member])
            model.add(
                f"exposure:{kind}:{member}",
                {v: 1 for v, _, c in options if member in getattr(c, kind)},
                upper=cap,
            )
    for member in sorted({c.captain for _, _, c in options if c.captain}):
        model.add(
            f"exposure:captain:{member}",
            {v: 1 for v, _, c in options if c.captain == member},
            upper=count_cap(controls.max_captain_exposure, n),
        )
    for team in sorted({c.primary_stack for _, _, c in options}):
        model.add(
            "exposure:primary_stack:" + team,
            {v: 1 for v, _, c in options if c.primary_stack == team},
            upper=count_cap(controls.max_primary_stack_exposure, n),
        )
    if controls.max_sp_pair_repetition is not None:
        pairs = {
            c.pitchers
            for _, _, c in options
            if len(c.pitchers) == 2 and c.captain is None
        }
        for pair in pairs:
            model.add(
                "exposure:sp_pair:" + "/".join(sorted(pair)),
                {
                    v: 1
                    for v, _, c in options
                    if c.pitchers == pair and c.captain is None
                },
                upper=controls.max_sp_pair_repetition,
            )
    for kind, limits in (("teams", controls.max_team_exposure), ("games", game_caps)):
        for member, fraction in limits.items():
            model.add(
                f"exposure:{kind}:{member}",
                {v: 1 for v, _, c in options if member in getattr(c, kind)},
                upper=count_cap(fraction, n),
            )
    unique = defaultdict(dict)
    for v, entry, c in options:
        unique[(entry.contest_id, c.signature)][v] = 1
    for key, expression in unique.items():
        model.add("contest_unique:" + key[0], expression, upper=1)
    if controls.max_shared_players is not None:
        for i, (v, entry, c) in enumerate(options):
            if i % 64 == 0:
                deadline.remaining()
            for w, other, d in options[i + 1 :]:
                if (
                    entry.entry_id != other.entry_id
                    and len(c.people & d.people) > controls.max_shared_players
                ):
                    model.add(
                        f"overlap:{entry.entry_id}:{other.entry_id}",
                        {v: 1, w: 1},
                        upper=1,
                    )
    solved = model.solve(
        deadline, min(controls.per_solve_seconds, deadline.remaining(3))
    )
    solved.report["search_scope"] = "complete_generated_bank"
    solved.report["global_lineup_optimality_claimed"] = False
    if solved.x is None:
        return {}, solved.report
    return {
        entry.entry_id: c.roster for v, entry, c in options if solved.x[v] > 0.5
    }, solved.report


def enhance(
    baseline: dict[str, tuple[str, ...]],
    entries: tuple[Entry, ...],
    mode: str,
    players: dict[str, Player],
    prepared: Prepared,
    controls: Controls,
    now: datetime,
    mutable_ids: set[str],
    scenarios: Scenarios,
    holdout: Scenarios,
    deadline: Deadline,
    validate,
) -> tuple[dict, dict]:
    """QA proposes constraints or allocation objectives; only solvers alter rosters."""
    banks, search_reports = {}, []
    # Deterministic scenario directions expose correlated upside without excluding
    # players or pretending an independent sum of individual ceilings is a quantile.
    indices = np.linspace(
        0, len(scenarios.scores) - 1, controls.max_candidates_per_entry, dtype=int
    )
    directions = [
        dict(zip(scenarios.person_ids, scenarios.scores[i].tolist())) for i in indices
    ]
    for entry in entries:
        initial = candidate(baseline[entry.entry_id], mode, players, prepared)
        bank, reports = generate_candidates(
            entry,
            mode,
            players,
            prepared,
            controls,
            now,
            entry.entry_id in mutable_ids,
            initial,
            directions,
            deadline,
        )
        banks[entry.entry_id] = bank
        search_reports.extend(reports)
    specs = {x.contest_id: x for x in prepared.bundle.contests}
    if any(e.contest_id not in specs for e in entries):
        raise ValueError(
            "ENHANCEMENT_UNAVAILABLE: an unknown contest needs its objective identified"
        )
    utilities = {}
    baseline_scores = scenarios.lineup_scores(
        [baseline[e.entry_id] for e in entries], mode, players
    )
    field_scores = {}
    for entry in entries:
        bank = banks[entry.entry_id]
        values = scenarios.lineup_scores([c.roster for c in bank], mode, players)
        shape = (
            specs[entry.contest_id].shape if entry.contest_id in specs else "large_gpp"
        )
        q = {
            "cash": 0.1,
            "small_gpp": 0.9,
            "single_entry_gpp": 0.9,
            "small_field_gpp": 0.9,
            "mid_field_gpp": 0.97,
            "satellite": 0.5,
        }.get(shape, 0.99)
        spec = specs.get(entry.contest_id)
        opponents = None
        if spec is not None and spec.field_rosters is not None:
            if entry.contest_id not in field_scores:
                field_scores[entry.contest_id] = scenarios.lineup_scores(
                    spec.field_rosters, mode, players
                )
            other_columns = [
                i
                for i, e in enumerate(entries)
                if e.contest_id == entry.contest_id and e.entry_id != entry.entry_id
            ]
            opponents = np.concatenate(
                [field_scores[entry.contest_id], baseline_scores[:, other_columns]],
                axis=1,
            )
        for j, c in enumerate(bank):
            deadline.remaining(3)
            utility = (
                float(
                    settle_scenarios(
                        values[:, j : j + 1], opponents, spec.payouts_cents
                    )[0].mean()
                )
                if opponents is not None
                else float(np.quantile(values[:, j], q))
            )
            utilities[(entry.entry_id, c.signature)] = utility
    current = dict(baseline)
    decisions = []
    before = portfolio_metrics(current, entries, mode, players, prepared, scenarios)
    before_holdout = portfolio_metrics(
        current, entries, mode, players, prepared, holdout
    )
    extra_caps = {}
    for iteration in range(controls.qa_iterations):
        deadline.remaining(3)
        if iteration:
            counts = Counter(
                players[pid].person_id for roster in current.values() for pid in roster
            )
            person, count = min(counts.items(), key=lambda kv: (-kv[1], kv[0]))
            if count <= 1:
                break
            extra_caps[person] = count - 1
        proposal, solver_report = allocate_candidates(
            banks,
            entries,
            controls,
            prepared.game_caps,
            utilities,
            deadline,
            extra_caps,
        )
        record = {
            "iteration": iteration + 1,
            "proposed_player_count_caps": dict(extra_caps),
            "solver": solver_report,
            "accepted": False,
        }
        decisions.append(record)
        if not proposal:
            record["reason"] = "no verified solution to the proposed constraints"
            break
        validation = validate(proposal)
        if validation["FILE_VALID"] is not True:
            record["reason"] = "independent final-byte validation refused the proposal"
            record["errors"] = validation["errors"]
            break
        after = portfolio_metrics(proposal, entries, mode, players, prepared, scenarios)
        after_holdout = portfolio_metrics(
            proposal, entries, mode, players, prepared, holdout
        )
        record.update(
            before=before,
            after=after,
            before_holdout=before_holdout,
            after_holdout=after_holdout,
            delta_contest_ceiling=after["contest_ceiling"] - before["contest_ceiling"],
            delta_portfolio_safety=after["portfolio_safety"]
            - before["portfolio_safety"],
        )
        if not (
            pareto_improves(before, after)
            and pareto_improves(before_holdout, after_holdout)
        ):
            record["reason"] = (
                "no strict Pareto improvement on both construction and held-out draws"
            )
            break
        record.update(
            accepted=True,
            reason="both metric deltas nonnegative and at least one positive on each draw set",
        )
        current, before, before_holdout = proposal, after, after_holdout
    return current, {
        "candidate_count": sum(map(len, banks.values())),
        "search": search_reports,
        "decisions": decisions,
        "iterations": len(decisions),
        "maximum_iterations": 3,
        "metrics": before,
        "holdout_metrics": before_holdout,
        "objective": "conditional payout against supplied opponents and incumbent siblings when complete; otherwise contest-specific score quantile. Final Pareto decisions settle the joint portfolio.",
        "economic_improvement_proven": False,
    }
