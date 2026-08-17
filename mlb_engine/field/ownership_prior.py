"""ownership_prior.py — structural ownership prior for MLB Classic.

STATUS: review-only, and WIRED as of R135 (2026-08-17): `tools/ownership_pred.py`
calls both halves, and this module's VERSION is pinned in the audit's
`EXPECTED_VERSION_TEXT` beside the boundary modules. Two claims that used to
head this file were false and are corrected rather than deleted, because three
other documents copied them. It was never UNTRACKED: `git log --follow` puts it
in the v3.0.0-pre restructure commit, the repo's first, so "untracked and
unwired" was half right and the tracked half sent R135 looking for a `git add`
that was not needed. And it is not outside the audit's module count, which is
taken off the filesystem: it has always been one of the 26.

What remains true: nothing here is applied to projections, `Ownership_Tier`, or
the optimizer, and both open project slots stay reserved for the fitted model
this replaces. The fitted replacement lands once 8-15
archetype-conditioned slates of archived DK standings exist.

Nothing here is a calibrated value: every output
is an UNCALIBRATED STRUCTURAL PRIOR, labeled as such, never a win-rate, ROI,
or probability claim, and never auto-applied to projections, Ownership_Tier,
or the optimizer.

Purpose: start the predict-then-grade loop on slate one instead of waiting to
accumulate data. Each slate this emits a per-player predicted ownership share
per contest archetype from structural features that are public before lock
(salary, position scarcity, implied team total, batting order, probable-SP
status, and optionally a Base projection for value). After the slate, the
archived DK standings' actual %Drafted grades the prediction
(grade_against_actuals), and the graded errors accumulate in the calibration
ledger. The 20-31 percentage-point ownership swings observed for the same
player across contest archetypes on the same slate are encoded as
archetype-conditioned concentration (temperature): cash and single-entry
fields chase value hard (concentrated), large-field GPPs flatten, MME flattens
further. Those temperatures are the primary thing the graded errors should
eventually correct.

Accounting: a DK Classic roster is 2 P + 8 hitters, so across any contest the
pitcher pool's ownership sums to 200% and the hitter pool's to 800%. The prior
allocates those budgets with a softmax over a structural score.

Typical session flow:
    from mlb_engine.intake.slate_intake_manager import parse_dk_salary_csv
    players = parse_dk_salary_csv("DKSalaries.csv")
    pred = predict_ownership(players,
                             archetype="large_field_gpp",
                             implied_total_by_team={"NYY": 5.4, ...},
                             batting_order_by_player_id=order_map,
                             probable_sp_ids=sp_ids,
                             base_projection_by_player_id=base_map)  # optional
    # after the slate, with actuals joined from the archived standings:
    report = grade_against_actuals(pred["own_pct_by_player_id"], actual_pct)
"""
from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

VERSION = "v0.1-prior"

# Archetype-conditioned concentration and feature weights. LABELED PRIORS.
# temperature: lower = more concentrated on the top structural scores (cash
# fields pile onto value); higher = flatter (MME spreads). sp_weight scales the
# probable-SP boost; value_weight scales pts/$ when a Base map is supplied.
ARCHETYPE_PARAMS: Dict[str, Dict[str, float]] = {
    "cash":              {"temperature": 0.55, "sp_weight": 1.20, "value_weight": 1.30},
    "single_entry_gpp":  {"temperature": 0.70, "sp_weight": 1.10, "value_weight": 1.15},
    "wta_satellite":     {"temperature": 0.75, "sp_weight": 1.10, "value_weight": 1.10},
    "small_gpp":         {"temperature": 0.85, "sp_weight": 1.00, "value_weight": 1.00},
    "large_field_gpp":   {"temperature": 1.00, "sp_weight": 1.00, "value_weight": 0.90},
    "mme":               {"temperature": 1.20, "sp_weight": 0.95, "value_weight": 0.80},
}
DEFAULT_ARCHETYPE = "large_field_gpp"

HITTER_BUDGET_PCT = 800.0   # 8 hitter slots per roster
PITCHER_BUDGET_PCT = 200.0  # 2 P slots per roster

# Batting-order attention prior: earlier slots draw more ownership. Distinct
# from the engine's F2 (a scoring factor); this is a field-behavior prior.
ORDER_ATTENTION = {1: 1.15, 2: 1.12, 3: 1.12, 4: 1.10, 5: 1.02,
                   6: 0.95, 7: 0.88, 8: 0.82, 9: 0.78}
LEAGUE_MEAN_IMPLIED = 4.5   # runs; used when a team's implied total is absent


def _is_pitcher(positions: Iterable[str]) -> bool:
    return "P" in {str(p).strip().upper() for p in positions}


def _player_record(p: Any) -> Dict[str, Any]:
    """Accept slate_intake_manager player objects or plain dicts."""
    if isinstance(p, Mapping):
        return {"id": str(p.get("player_id") or p.get("Player_ID") or p.get("id")),
                "name": str(p.get("name") or p.get("Name") or ""),
                "team": str(p.get("team") or p.get("Team") or "").strip().upper(),
                "salary": float(p.get("salary") or p.get("Salary") or 0.0),
                "positions": [t for t in str(p.get("positions") or p.get("Position") or "").replace("/", ",").split(",") if t]
                             if not isinstance(p.get("positions"), (list, tuple)) else list(p.get("positions"))}
    return {"id": str(getattr(p, "player_id")), "name": str(getattr(p, "name", "")),
            "team": str(getattr(p, "team", "")).strip().upper(),
            "salary": float(getattr(p, "salary", 0.0)),
            "positions": list(getattr(p, "positions", []))}


def _softmax_shares(scores: Dict[str, float], temperature: float) -> Dict[str, float]:
    if not scores:
        return {}
    t = max(float(temperature), 1e-6)
    peak = max(scores.values())
    exps = {k: math.exp((v - peak) / t) for k, v in scores.items()}
    total = sum(exps.values()) or 1.0
    return {k: v / total for k, v in exps.items()}


def predict_ownership(
    salary_players: Iterable[Any],
    archetype: str = DEFAULT_ARCHETYPE,
    implied_total_by_team: Optional[Mapping[str, float]] = None,
    batting_order_by_player_id: Optional[Mapping[str, int]] = None,
    probable_sp_ids: Optional[Iterable[str]] = None,
    base_projection_by_player_id: Optional[Mapping[str, float]] = None,
    archetype_params: Optional[Mapping[str, Mapping[str, float]]] = None,
) -> Dict[str, Any]:
    """Return the structural ownership prior for one contest archetype.

    Output dict:
      own_pct_by_player_id  — predicted %Drafted per player (hitters sum ~800,
                              pitchers ~200)
      tier_by_player_id     — High / Mid / Low by within-pool percentile
                              (top 15% High, bottom 40% Low), the ONLY field
                              ever eligible to feed Ownership_Tier, and only on
                              explicit operator opt-in
      archetype, params, note — provenance and the truthful label

    Structural score per player (before the softmax):
      salary percentile within the P/hitter pool
      + implied-total tilt (hitters; team implied over league mean)
      + batting-order attention prior (hitters with a known/projected slot)
      + probable-SP boost (pitchers; the field concentrates on named starters)
      + optional value tilt (pts/$ percentile when a Base map is supplied)
    """
    params_table = dict(ARCHETYPE_PARAMS)
    if archetype_params:
        params_table.update({k: dict(v) for k, v in archetype_params.items()})
    params = params_table.get(str(archetype), params_table[DEFAULT_ARCHETYPE])

    implied = {str(k).strip().upper(): float(v) for k, v in (implied_total_by_team or {}).items()}
    orders = {str(k): int(v) for k, v in (batting_order_by_player_id or {}).items()}
    sp_set = {str(x) for x in (probable_sp_ids or [])}
    bases = {str(k): float(v) for k, v in (base_projection_by_player_id or {}).items()}

    records = [_player_record(p) for p in salary_players]
    pitchers = [r for r in records if _is_pitcher(r["positions"])]
    hitters = [r for r in records if not _is_pitcher(r["positions"])]

    def _pool_scores(pool: List[Dict[str, Any]], is_pitcher_pool: bool) -> Dict[str, float]:
        if not pool:
            return {}
        salaries = sorted(r["salary"] for r in pool)
        n = len(salaries)

        def pct_of(value: float, ordered: List[float]) -> float:
            below = sum(1 for s in ordered if s < value)
            equal = sum(1 for s in ordered if s == value)
            return (below + 0.5 * equal) / max(len(ordered), 1)

        value_pool: List[Tuple[str, float]] = []
        for r in pool:
            base = bases.get(r["id"])
            if base is not None and r["salary"] > 0:
                value_pool.append((r["id"], base / (r["salary"] / 1000.0)))
        value_sorted = sorted(v for _, v in value_pool)
        value_pct = {pid: pct_of(v, value_sorted) for pid, v in value_pool}

        scores: Dict[str, float] = {}
        for r in pool:
            score = pct_of(r["salary"], salaries)  # salary as the baseline attention proxy
            if is_pitcher_pool:
                if r["id"] in sp_set:
                    score += 0.60 * params["sp_weight"]
                else:
                    score -= 0.80  # non-probable arms draw near-zero classic ownership
            else:
                team_implied = implied.get(r["team"], LEAGUE_MEAN_IMPLIED)
                score += 0.35 * (team_implied - LEAGUE_MEAN_IMPLIED)
                slot = orders.get(r["id"])
                if slot is not None:
                    score += ORDER_ATTENTION.get(int(slot), 0.90) - 1.0
                else:
                    score -= 0.15  # no known slot: the field discounts TBD bats
            if r["id"] in value_pct:
                score += params["value_weight"] * (value_pct[r["id"]] - 0.5)
            scores[r["id"]] = score
        return scores

    hitter_shares = _softmax_shares(_pool_scores(hitters, False), params["temperature"])
    pitcher_shares = _softmax_shares(_pool_scores(pitchers, True), params["temperature"])

    own: Dict[str, float] = {}
    own.update({pid: round(share * HITTER_BUDGET_PCT, 2) for pid, share in hitter_shares.items()})
    own.update({pid: round(share * PITCHER_BUDGET_PCT, 2) for pid, share in pitcher_shares.items()})

    def _tiers(shares: Mapping[str, float]) -> Dict[str, str]:
        if not shares:
            return {}
        ordered = sorted(shares.items(), key=lambda kv: kv[1], reverse=True)
        n = len(ordered)
        out: Dict[str, str] = {}
        for rank, (pid, _) in enumerate(ordered):
            frac = rank / max(n - 1, 1)
            out[pid] = "High" if frac <= 0.15 else ("Low" if frac >= 0.60 else "Mid")
        return out

    tiers = {**_tiers(hitter_shares), **_tiers(pitcher_shares)}
    return {
        "own_pct_by_player_id": own,
        "tier_by_player_id": tiers,
        "archetype": str(archetype),
        "params": dict(params),
        "prior_version": VERSION,
        "note": (
            "UNCALIBRATED STRUCTURAL PRIOR. Predicted %Drafted from salary, implied "
            "totals, batting order, probable-SP status, and optional value; archetype-"
            "conditioned concentration encodes the observed cross-archetype ownership "
            "swings. Never a win-rate, ROI, or probability claim; never auto-applied "
            "to projections, Ownership_Tier, or the optimizer. Grade every slate "
            "against archived DK standings and reconcile errors into the calibration "
            "ledger; the fitted replacement takes a tracked project slot."
        ),
    }


def grade_against_actuals(
    predicted_pct: Mapping[str, float],
    actual_pct: Mapping[str, float],
) -> Dict[str, Any]:
    """Grade one archetype's prediction against archived actual %Drafted.

    Joins on DK Player_ID over the intersection (players absent from the
    standings export are excluded and counted). Reports MAE, mean signed error
    (positive = prior over-predicts), Spearman rank correlation (computed
    directly, no scipy dependency), and the ten largest misses both ways. The
    grade is bookkeeping for the ledger, not a model-quality claim on its own;
    per the ledger discipline a single slate never moves a prior.
    """
    keys = sorted(set(map(str, predicted_pct)) & set(map(str, actual_pct)))
    if not keys:
        return {"joined": 0, "note": "no overlapping Player_IDs; check the standings join"}
    pred = [float(predicted_pct[k]) for k in keys]
    act = [float(actual_pct[k]) for k in keys]
    errors = [p - a for p, a in zip(pred, act)]
    mae = sum(abs(e) for e in errors) / len(errors)
    signed = sum(errors) / len(errors)

    def _ranks(values: List[float]) -> List[float]:
        order = sorted(range(len(values)), key=lambda i: values[i])
        ranks = [0.0] * len(values)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                ranks[order[k]] = avg
            i = j + 1
        return ranks

    rp, ra = _ranks(pred), _ranks(act)
    mean_rp = sum(rp) / len(rp)
    mean_ra = sum(ra) / len(ra)
    cov = sum((x - mean_rp) * (y - mean_ra) for x, y in zip(rp, ra))
    var_p = math.sqrt(sum((x - mean_rp) ** 2 for x in rp))
    var_a = math.sqrt(sum((y - mean_ra) ** 2 for y in ra))
    spearman = cov / (var_p * var_a) if var_p and var_a else None

    ranked = sorted(zip(keys, errors), key=lambda kv: kv[1])
    return {
        "joined": len(keys),
        "unjoined_predicted": len(set(map(str, predicted_pct)) - set(keys)),
        "mae_pct_points": round(mae, 2),
        "mean_signed_error_pct_points": round(signed, 2),
        "spearman_rank_corr": round(spearman, 3) if spearman is not None else None,
        "largest_under_predictions": [{"Player_ID": k, "error": round(e, 2)} for k, e in ranked[:10]],
        "largest_over_predictions": [{"Player_ID": k, "error": round(e, 2)} for k, e in ranked[-10:][::-1]],
        "note": "Grade is ledger bookkeeping; one slate never moves a prior. Condition on contest archetype and field size, never pooled.",
    }
