"""Explicit, uncalibrated correlated priors and exact contest settlement.

The simulation is conditional on supplied moments, configured factor loadings and
the supplied opponent field. It is not an empirically calibrated win probability.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

import numpy as np

from .contracts import Controls, Entry, Player
from .evidence import Prepared


@dataclass(frozen=True)
class Scenarios:
    person_ids: tuple[str, ...]
    scores: np.ndarray
    label: str = "UNCALIBRATED_CORRELATED_PRIOR"

    def lineup_scores(self, rosters, mode, players):
        index = {pid: i for i, pid in enumerate(self.person_ids)}
        weights = np.zeros((len(rosters), len(index)), dtype=np.float64)
        for row, roster in enumerate(rosters):
            for slot, pid in enumerate(roster):
                weights[row, index[players[pid].person_id]] += (
                    1.5 if mode == "SHOWDOWN" and slot == 0 else 1.0
                )
        return self.scores @ weights.T


def simulate(
    players: dict[str, Player],
    prepared: Prepared,
    controls: Controls,
    seed: int | None = None,
) -> Scenarios:
    canonical = {p.person_id: p for p in players.values()}
    ids = tuple(sorted(canonical))
    projections = {p.player_id: p for p in prepared.bundle.projections}
    missing = [
        pid for pid in ids if pid not in projections or projections[pid].stddev is None
    ]
    if missing:
        raise ValueError(
            "SIMULATION_UNAVAILABLE: explicit means and standard deviations required for every physical player"
        )
    teams = sorted({p.team for p in canonical.values()})
    games = sorted({p.game_id for p in canonical.values()})
    ti, gi = ({t: i for i, t in enumerate(teams)}, {g: i for i, g in enumerate(games)})
    rng = np.random.Generator(np.random.PCG64(controls.seed if seed is None else seed))
    tdraw = rng.standard_normal((controls.simulations, len(teams)))
    gdraw = rng.standard_normal((controls.simulations, len(games)))
    residual = rng.standard_normal((controls.simulations, len(ids)))
    scores = np.empty_like(residual)
    for j, pid in enumerate(ids):
        player, projection = canonical[pid], projections[pid]
        pitcher = "P" in player.positions
        loading = (
            -controls.opposing_pitcher_loading if pitcher else controls.team_loading
        )
        team = player.opponent if pitcher else player.team
        # A salary pool can omit the opponent's players on a tiny fixture.
        if team not in ti:
            raise ValueError("simulation requires both teams in each game")
        game_loading = -controls.game_loading if pitcher else controls.game_loading
        noise = np.sqrt(1 - loading**2 - game_loading**2)
        latent = (
            loading * tdraw[:, ti[team]]
            + game_loading * gdraw[:, gi[player.game_id]]
            + noise * residual[:, j]
        )
        mean, sd = projection.mean, projection.stddev
        if pitcher:
            scores[:, j] = mean + sd * latent
        elif mean == 0:
            raise ValueError(
                "a nonnegative hitter with mean zero cannot have positive variance"
            )
        else:
            # Moment-matched lognormal: no clipping or silent distortion of means.
            variance = np.log1p((sd / mean) ** 2)
            scores[:, j] = np.exp(
                np.log(mean) - variance / 2 + np.sqrt(variance) * latent
            )
    if not np.isfinite(scores).all():
        raise ValueError("simulation overflow")
    scores.setflags(write=False)
    return Scenarios(ids, scores)


def settle_scores(scores: list[float], payouts_cents: list[int]) -> list[Fraction]:
    """Exact tie oracle: every duplicated entry occupies and shares a paid rank."""
    if len(scores) != len(payouts_cents) or not scores or not np.isfinite(scores).all():
        raise ValueError("finite scores and one payout per field entry required")
    if any(type(p) is not int or p < 0 for p in payouts_cents):
        raise ValueError("payouts must be nonnegative integer cents")
    if any(a < b for a, b in zip(payouts_cents, payouts_cents[1:])):
        raise ValueError("payout curve must be nonincreasing")
    order = sorted(range(len(scores)), key=lambda i: (-scores[i], i))
    output = [Fraction(0) for _ in scores]
    rank = 0
    while rank < len(order):
        end = rank + 1
        while end < len(order) and scores[order[end]] == scores[order[rank]]:
            end += 1
        prize = Fraction(sum(payouts_cents[rank:end]), end - rank)
        for index in order[rank:end]:
            output[index] = prize
        rank = end
    return output


def settle_scenarios(own: np.ndarray, field: np.ndarray, payouts_cents: list[int]):
    if own.ndim != 2 or field.ndim != 2 or own.shape[0] != field.shape[0]:
        raise ValueError("incompatible contest scenario matrices")
    if own.shape[1] + field.shape[1] != len(payouts_cents):
        raise ValueError(
            "opponent field size plus own entries must equal total field size"
        )
    if not np.isfinite(own).all() or not np.isfinite(field).all():
        raise ValueError("nonfinite contest scores")
    if not len(payouts_cents) or any(
        type(x) is not int or x < 0 for x in payouts_cents
    ):
        raise ValueError("payouts require nonnegative integer cents")
    if any(a < b for a, b in zip(payouts_cents, payouts_cents[1:])):
        raise ValueError("payout curve must be nonincreasing")
    prefix = np.r_[0.0, np.cumsum(np.asarray(payouts_cents, dtype=np.float64))]
    payout, first = (
        np.zeros(own.shape, dtype=np.float64),
        np.zeros_like(own, dtype=bool),
    )
    for j in range(own.shape[1]):
        value = own[:, j : j + 1]
        higher = (field > value).sum(axis=1) + (own > value).sum(axis=1)
        ties = (field == value).sum(axis=1) + (own == value).sum(axis=1)
        payout[:, j] = (prefix[higher + ties] - prefix[higher]) / ties
        first[:, j] = higher == 0
    return payout, first


def portfolio_metrics(
    assignments: dict[str, tuple[str, ...]],
    entries: tuple[Entry, ...],
    mode: str,
    players: dict[str, Player],
    prepared: Prepared,
    scenarios: Scenarios,
) -> dict:
    points = scenarios.lineup_scores(
        [assignments[e.entry_id] for e in entries], mode, players
    )
    total = points.sum(axis=1)
    result = {
        "label": scenarios.label,
        "contest_ceiling": float(np.quantile(points.max(axis=1), 0.99)),
        "portfolio_safety": float(np.quantile(total, 0.1)),
        "ceiling_definition": "p99 of the portfolio's best lineup score",
        "safety_definition": "p10 of aggregate portfolio score",
        "payout_state": "UNAVAILABLE",
        "scenario_count": len(total),
        "mean_score": float(points.mean()),
        "p99_best_score": float(np.quantile(points.max(axis=1), 0.99)),
        "p10_total_score": float(np.quantile(total, 0.1)),
        "portfolio_score_variance": float(np.var(total)),
    }
    specs = {c.contest_id: c for c in prepared.bundle.contests}
    gross = np.zeros(scenarios.scores.shape[0])
    any_first = np.zeros(scenarios.scores.shape[0], dtype=bool)
    covered = True
    for cid in sorted({e.contest_id for e in entries}):
        spec = specs.get(cid)
        if spec is None or spec.payouts_cents is None or spec.field_rosters is None:
            covered = False
            break
        columns = [j for j, entry in enumerate(entries) if entry.contest_id == cid]
        field = scenarios.lineup_scores(spec.field_rosters, mode, players)
        payouts, first = settle_scenarios(points[:, columns], field, spec.payouts_cents)
        gross += payouts.sum(axis=1)
        any_first |= first.any(axis=1)
    if covered:
        fees = sum(e.fee_cents for e in entries)
        result.update(
            payout_state="CONDITIONAL_ON_SUPPLIED_FIELD_AND_PRIOR",
            expected_gross_cents=float(gross.mean()),
            expected_net_cents=float(gross.mean() - fees),
            conditional_any_first=float(any_first.mean()),
            conditional_any_cash=float((gross > 0).mean()),
            conditional_washout=float((gross == 0).mean()),
            conditional_cash_floor=float((gross >= fees).mean()),
            contest_ceiling=float(gross.mean()),
            portfolio_safety=float((gross >= fees).mean()),
            ceiling_definition="conditional expected payout under this contest's complete prize curve",
            safety_definition="conditional probability of recovering aggregate entry fees",
        )
        if any(specs[e.contest_id].payout_kind == "ticket_face_value" for e in entries):
            result["payout_units"] = (
                "cash plus nominal ticket face value, not realizable cash"
            )
            result["expected_prize_value_cents"] = result.pop("expected_gross_cents")
            result["expected_value_less_fees_cents"] = result.pop("expected_net_cents")
            result["conditional_any_prize"] = result.pop("conditional_any_cash")
            result["conditional_value_floor"] = result.pop("conditional_cash_floor")
            result["ceiling_definition"] = (
                "conditional expected cash plus nominal ticket face value"
            )
            result["safety_definition"] = (
                "conditional probability prize face value covers entry fees; not a cash floor"
            )
        else:
            result["payout_units"] = "cash_cents"
    return result


def leverage_report(
    scenarios: Scenarios, players: dict[str, Player], prepared: Prepared
):
    """Common role-pool p90 threshold; a player's own p90 makes the event tautological."""
    canonical = {p.person_id: p for p in players.values()}
    predictions = {p.player_id: p for p in prepared.bundle.projections}
    rows = []
    for role in ("P", "H"):
        indexes = [
            j
            for j, pid in enumerate(scenarios.person_ids)
            if ("P" in canonical[pid].positions) == (role == "P")
        ]
        if not indexes:
            continue
        threshold = float(np.quantile(scenarios.scores[:, indexes], 0.9))
        for j in indexes:
            pid = scenarios.person_ids[j]
            own = predictions[pid].ownership
            probability = float((scenarios.scores[:, j] >= threshold).mean())
            rows.append(
                {
                    "player_id": pid,
                    "role": role,
                    "threshold": threshold,
                    "conditional_tail_probability": probability,
                    "ownership": own,
                    "leverage_delta": None if own is None else probability - own,
                    "label": scenarios.label,
                }
            )
    return rows


def pareto_improves(before: dict, after: dict, tolerance=1e-9) -> bool:
    if (
        before["ceiling_definition"] != after["ceiling_definition"]
        or before["safety_definition"] != after["safety_definition"]
    ):
        return False
    delta = [after[k] - before[k] for k in ("contest_ceiling", "portfolio_safety")]
    return (
        all(np.isfinite(delta))
        and all(x >= -tolerance for x in delta)
        and any(x > tolerance for x in delta)
    )
