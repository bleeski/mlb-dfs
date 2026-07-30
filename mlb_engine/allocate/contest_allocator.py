"""
MLB Classic Contest Allocator
VERSION is the authoritative version constant for this module.
Framework patch: MLB Classic v2.16.0 lean joint selection/allocation
Compiled: 2026-06-11 (v1.10 reliability and game-exposure patch)

v1.10 changes: shadowed duplicate definitions removed; candidate-reuse caps are
keyed by lineup signature, not candidate object; optional per-game exposure caps
(``max_game_exposure_pct_by_game`` with ``player_game_by_id``) are encoded in the
solved model and mirrored by the export validator.

Purpose
-------
This module is a thin orchestration layer above optimizer_v3.py. It does not
build lineups, alter F1-F5 projections, weaken MILP constraints, or claim true
ROI/win-rate simulation. It helps an executor:
  1. score contest attractiveness using transparent contest-shape proxies;
  2. recommend entry counts under a slate-level buy-in budget;
  3. jointly assign an already-built global candidate bank into multiple contests;
  4. apply explicit concentrated/balanced/diversified reuse posture while forbidding same-contest duplicates;
  5. surface subset-selection process risks such as leftover allocation,
     right-tail removal, SP-family compression, material field fades, and
     single-ticket satellite classification;
  6. reconcile actual DKEntries exports against the intended assignment map;
  7. size candidate banks from unique lineup demand rather than raw reserved rows;
  8. preserve hard small-slate SP-pair coverage targets when sizing banks.

All scores are deterministic review/selection proxies. Do not label them ROI,
profitability, win rate, cash rate, Perfect%, SaberScore, or contest simulation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from collections import Counter, defaultdict
import csv
import json
import math
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

VERSION = "v1.11"

CONTEST_TYPES = {"cash", "se_gpp", "portfolio_gpp", "wta", "satellite"}
PRIORITY_MULTIPLIER = {"low": 0.80, "medium": 1.00, "high": 1.18, "must": 1.35}

SMALL_FIELD_MAX_ENTRANTS = 500
MID_FIELD_MAX_ENTRANTS = 2000
DEFAULT_RIGHT_TAIL_RETENTION_PCT = 0.0
DEFAULT_SP_COMPRESSION_WARN_DELTA = 0.20
DEFAULT_MATERIAL_FIELD_OWNERSHIP_PCT = 20.0


@dataclass(frozen=True)
class PayoutRow:
    """One payout-band row. start/end are 1-indexed finishing positions."""

    start: int
    end: int
    payout: float

    def count(self) -> int:
        return max(0, int(self.end) - int(self.start) + 1)


@dataclass
class ContestCard:
    """User-facing contest-card schema for Phase 0 allocation."""

    contest_id: str
    name: str
    contest_type: str
    field_size: int
    max_entries: int
    buy_in: float
    prize_pool: float
    payout_rows: List[PayoutRow] = field(default_factory=list)
    min_entries: int = 0
    user_max_entries: Optional[int] = None
    priority: str = "medium"
    must_enter: bool = False
    late_swap: Optional[bool] = None
    source: str = "manual"
    reserved_entries: int = 0
    metadata_confidence: str = "manual"
    decision_critical_gaps: List[str] = field(default_factory=list)
    satellite_tickets: Optional[int] = None
    ticket_value: Optional[float] = None
    allow_cross_contest_reuse: bool = True
    no_duplicates_within_contest: bool = True

    def __post_init__(self) -> None:
        self.contest_type = str(self.contest_type).strip().lower()
        if self.contest_type not in CONTEST_TYPES:
            raise ValueError(f"contest_type must be one of {sorted(CONTEST_TYPES)}")
        self.priority = str(self.priority or "medium").strip().lower()
        if self.priority not in PRIORITY_MULTIPLIER:
            self.priority = "medium"
        self.field_size = int(self.field_size)
        self.max_entries = int(self.max_entries)
        self.buy_in = float(self.buy_in)
        self.prize_pool = float(self.prize_pool)
        self.min_entries = int(self.min_entries or 0)
        if self.user_max_entries is not None:
            self.user_max_entries = int(self.user_max_entries)
        self.max_entries = max(0, self.max_entries)
        self.min_entries = max(0, min(self.min_entries, self.effective_max_entries()))

    def effective_max_entries(self) -> int:
        cap = self.max_entries
        if self.user_max_entries is not None:
            cap = min(cap, int(self.user_max_entries))
        return max(0, cap)

    @property
    def total_buyins_if_full(self) -> float:
        return self.field_size * self.buy_in

    @property
    def rake_pct(self) -> float:
        total_buyins = self.total_buyins_if_full
        if total_buyins <= 0:
            return 0.0
        return max(0.0, 100.0 * (total_buyins - self.prize_pool) / total_buyins)

    @property
    def paid_spots(self) -> int:
        if self.payout_rows:
            return sum(row.count() for row in self.payout_rows)
        if self.satellite_tickets is not None:
            return int(self.satellite_tickets)
        return 0

    @property
    def paid_spot_pct(self) -> float:
        if self.field_size <= 0:
            return 0.0
        return 100.0 * self.paid_spots / self.field_size

    @property
    def first_place_prize(self) -> float:
        if self.payout_rows:
            first_rows = [row for row in self.payout_rows if row.start <= 1 <= row.end]
            if first_rows:
                return float(first_rows[0].payout)
        return 0.0

    @property
    def first_place_share_pct(self) -> float:
        if self.prize_pool <= 0:
            return 0.0
        return 100.0 * self.first_place_prize / self.prize_pool


def parse_payout_schedule(value: Any) -> List[PayoutRow]:
    """Parse JSON/list payout rows into PayoutRow values.

    Supported JSON examples:
      [{"start":1,"end":1,"payout":75}, {"start":2,"end":3,"payout":35}]
      [[1,1,75], [2,3,35]]
    """
    if value in (None, "", []):
        return []
    if isinstance(value, str):
        value = json.loads(value)
    rows = []
    for item in value:
        if isinstance(item, dict):
            rows.append(PayoutRow(int(item["start"]), int(item["end"]), float(item["payout"])))
        else:
            start, end, payout = item
            rows.append(PayoutRow(int(start), int(end), float(payout)))
    rows.sort(key=lambda r: (r.start, r.end))
    return rows


def satellite_strategy_for_card(card: ContestCard) -> Dict[str, Any]:
    """Classify satellite payout shape before assigning lineups.

    One-ticket satellites behave like WTA-ticket contests: first-place path only.
    Multi-ticket satellites behave like ticket-line contests: optimize for the
    advancement line, not raw first. Unknown ticket counts remain a blocking
    metadata gap for lineup posture.
    """
    if card.contest_type != "satellite":
        return {"strategy": "not_satellite", "blocking_gap": False, "note": "not a satellite"}
    tickets = card.satellite_tickets
    if tickets is None and card.payout_rows:
        tickets = card.paid_spots
    if tickets == 1 or card.paid_spots == 1:
        return {"strategy": "wta_ticket", "blocking_gap": False, "ticket_count": 1, "note": "single-ticket satellite; treat as WTA-ticket"}
    if tickets is not None and int(tickets) > 1:
        return {"strategy": "ticket_line", "blocking_gap": False, "ticket_count": int(tickets), "note": "multi-ticket satellite; target ticket-line advancement"}
    return {"strategy": "unknown_ticket_structure", "blocking_gap": True, "ticket_count": None, "note": "ticket count/ticket line required"}


def contest_shape_for_card(card: ContestCard) -> str:
    """Resolve allocation-time contest shape.

    This is separate from optimizer_v3.resolve_contest_shape_profile(). It routes
    lineups into contest-specific buckets and explains the allocation. It does
    not alter MILP constraints.
    """
    if card.contest_type == "cash":
        return "cash"
    if card.contest_type == "satellite":
        sat = satellite_strategy_for_card(card)
        if sat["strategy"] == "wta_ticket":
            return "wta_ticket_satellite"
        return "satellite"
    if card.contest_type == "wta":
        if card.field_size <= SMALL_FIELD_MAX_ENTRANTS:
            return "small_wta"
        if card.field_size <= MID_FIELD_MAX_ENTRANTS:
            return "mid_wta"
        return "large_wta"
    if card.contest_type == "se_gpp" or card.effective_max_entries() <= 1:
        return "single_entry_gpp"
    if card.field_size <= SMALL_FIELD_MAX_ENTRANTS:
        return "small_field_gpp"
    if card.field_size <= MID_FIELD_MAX_ENTRANTS:
        return "mid_field_gpp"
    return "large_field_gpp"


def _top_heaviness_proxy(card: ContestCard) -> float:
    """Bounded top-heaviness proxy used for allocation score only."""
    first_share = card.first_place_share_pct / 100.0
    paid_pct = card.paid_spot_pct / 100.0
    if card.contest_type == "wta":
        return 1.0
    # More first-place share and fewer paid spots = more top-heavy.
    return max(0.0, min(1.0, 0.65 * first_share / 0.20 + 0.35 * max(0.0, 0.25 - paid_pct) / 0.25))


def contest_attractiveness_score(card: ContestCard, slate_game_count: Optional[int] = None) -> Dict[str, Any]:
    """Return transparent contest-selection proxies.

    Higher score means the contest deserves budget earlier. This is not an ROI
    projection. It intentionally rewards low rake, smaller fields, useful max
    entries, and contest fit for the MLB Classic candidate-bank workflow.
    """
    shape = contest_shape_for_card(card)
    rake_penalty = min(0.45, card.rake_pct / 100.0)
    low_rake_score = 1.0 - rake_penalty
    field_score = 1.0 / math.sqrt(max(1.0, card.field_size / 100.0))
    entry_coverage = min(0.08, card.effective_max_entries() / max(1, card.field_size)) / 0.08
    paid_pct = card.paid_spot_pct / 100.0
    payout_fit = max(0.0, min(1.0, paid_pct / 0.25)) if card.contest_type != "wta" else 0.75
    top_heavy = _top_heaviness_proxy(card)

    type_fit = {
        "cash": 0.75,
        "single_entry_gpp": 0.86,
        "small_field_gpp": 1.00,
        "mid_field_gpp": 0.90,
        "large_field_gpp": 0.74,
        "small_wta": 0.82,
        "mid_wta": 0.76,
        "large_wta": 0.66,
        "wta_ticket_satellite": 0.78,
        "satellite": 0.72,
    }.get(shape, 0.80)

    # Four-game slates make max-entry overlap/anchor discipline especially
    # valuable, but also compress ownership. Slightly favor small/mid fields.
    slate_adjust = 1.0
    if slate_game_count is not None and int(slate_game_count) <= 4:
        if shape in {"small_field_gpp", "mid_field_gpp", "small_wta"}:
            slate_adjust += 0.05
        if shape == "large_field_gpp":
            slate_adjust -= 0.05

    priority = PRIORITY_MULTIPLIER.get(card.priority, 1.0)
    if card.must_enter:
        priority = max(priority, PRIORITY_MULTIPLIER["must"])

    score = (
        42.0 * low_rake_score
        + 22.0 * field_score
        + 16.0 * entry_coverage
        + 10.0 * payout_fit
        + 10.0 * type_fit
        + 4.0 * top_heavy
    ) * priority * slate_adjust

    return {
        "contest_id": card.contest_id,
        "name": card.name,
        "contest_shape": shape,
        "allocation_score": round(score, 4),
        "rake_pct": round(card.rake_pct, 2),
        "paid_spot_pct": round(card.paid_spot_pct, 2),
        "first_place_share_pct": round(card.first_place_share_pct, 2),
        "max_entries": card.effective_max_entries(),
        "field_coverage_at_max_pct": round(100.0 * card.effective_max_entries() / max(1, card.field_size), 2),
        "type_fit_proxy": round(type_fit, 4),
        "priority_multiplier": round(priority, 4),
        "note": "allocation proxy only; not ROI or contest simulation",
    }


def recommend_entry_allocation(
    contest_cards: Sequence[ContestCard],
    total_budget: float,
    slate_game_count: Optional[int] = None,
) -> Dict[str, Any]:
    """Recommend entries per contest under a hard budget cap.

    The allocator uses a deterministic marginal-entry heuristic. It first
    satisfies min/must-enter entries, then spends remaining budget by contest
    attractiveness with a diminishing-return curve so high-quality contests can
    be maxed while lower-quality contests do not automatically consume leftovers.
    """
    budget = round(float(total_budget), 10)
    cards = list(contest_cards)
    scores = {c.contest_id: contest_attractiveness_score(c, slate_game_count) for c in cards}
    allocations = {c.contest_id: 0 for c in cards}
    spent = 0.0
    warnings: List[str] = []

    # Satisfy minimums/musts in score order, but never exceed budget.
    for c in sorted(cards, key=lambda x: scores[x.contest_id]["allocation_score"], reverse=True):
        min_entries = c.min_entries or (1 if c.must_enter else 0)
        for _ in range(min_entries):
            if allocations[c.contest_id] >= c.effective_max_entries():
                break
            if spent + c.buy_in > budget + 1e-9:
                warnings.append(f"Budget could not satisfy minimum/must-enter for {c.contest_id}")
                break
            allocations[c.contest_id] += 1
            spent += c.buy_in

    def marginal_value(card: ContestCard, next_entry_index: int) -> float:
        base = scores[card.contest_id]["allocation_score"]
        # Diminishing return is gentle for small-field max-entry contests and
        # steeper for large-field lottery allocations.
        shape = scores[card.contest_id]["contest_shape"]
        curve = 0.88 if shape in {"small_field_gpp", "mid_field_gpp", "cash", "satellite"} else 0.78
        return base * (curve ** max(0, next_entry_index - 1)) / max(card.buy_in, 0.01)

    while True:
        choices = []
        for c in cards:
            if allocations[c.contest_id] >= c.effective_max_entries():
                continue
            if spent + c.buy_in > budget + 1e-9:
                continue
            choices.append((marginal_value(c, allocations[c.contest_id] + 1), c.contest_id, c))
        if not choices:
            break
        choices.sort(reverse=True)
        _, _, chosen = choices[0]
        allocations[chosen.contest_id] += 1
        spent += chosen.buy_in

    rows = []
    for c in sorted(cards, key=lambda x: scores[x.contest_id]["allocation_score"], reverse=True):
        entry_count = allocations[c.contest_id]
        rows.append({
            **scores[c.contest_id],
            "recommended_entries": int(entry_count),
            "recommended_buy_in": round(entry_count * c.buy_in, 2),
            "enter_contest": bool(entry_count > 0),
        })
    return {
        "total_budget": round(budget, 2),
        "recommended_total_buy_in": round(spent, 2),
        "unspent_budget": round(max(0.0, budget - spent), 2),
        "allocations": allocations,
        "contest_rows": rows,
        "warnings": warnings,
        "summary": "Phase 0 allocation complete using deterministic contest-selection proxies only",
    }


def _candidate_id(candidate: Dict[str, Any], default_index: int) -> str:
    return str(candidate.get("candidate_id") or candidate.get("lineup_id") or f"L{default_index + 1:03d}")


def _candidate_player_signature(candidate: Dict[str, Any]) -> Tuple[str, ...]:
    if "player_ids" in candidate:
        return tuple(sorted(str(x) for x in candidate["player_ids"]))
    lineup = candidate.get("lineup")
    if lineup is None:
        return (_candidate_id(candidate, 0),)
    try:
        if hasattr(lineup, "iterrows"):
            return tuple(sorted(str(row.get("Player_ID")) for _, row in lineup.iterrows()))
        return tuple(sorted(str(x) for x in lineup))
    except Exception:
        return (_candidate_id(candidate, 0),)


def _candidate_shape_score(candidate: Dict[str, Any], shape: str) -> float:
    """Score candidate for contest shape using supplied tags/proxies."""
    fit_by_shape = candidate.get("contest_fit_by_shape") or {}
    if shape in fit_by_shape:
        return float(fit_by_shape[shape])
    cf = candidate.get("contest_fit") or {}
    base = float(candidate.get("contest_fit_score", cf.get("contest_fit_score", candidate.get("objective", 0.0))))
    right_tail = candidate.get("right_tail_tier") or cf.get("right_tail_tier")
    if right_tail is None:
        rt_counts = cf.get("right_tail_volatility_counts") or candidate.get("right_tail_volatility_counts") or {}
        if rt_counts.get("Eruption", 0) >= 2:
            right_tail = "Eruption"
        elif rt_counts.get("Volatile", 0) >= 2:
            right_tail = "Volatile"
        else:
            right_tail = "Stable"
    tier_bonus = {"Stable": 0.0, "Volatile": 2.0, "Eruption": 4.0}.get(str(right_tail), 0.0)
    if shape in {"large_field_gpp", "large_wta", "mid_wta", "small_wta", "wta_ticket_satellite"}:
        return base + tier_bonus
    if shape == "small_field_gpp":
        return base + 0.50 * tier_bonus
    if shape == "cash" or shape == "satellite":
        floor = float(candidate.get("floor_sum", cf.get("floor_sum", 0.0)))
        return base * 0.70 + floor * 0.30 - 0.35 * tier_bonus
    return base


def _candidate_right_tail_tier(candidate: Dict[str, Any]) -> str:
    tier = candidate.get("right_tail_tier")
    if tier:
        return str(tier)
    cf = candidate.get("contest_fit") or {}
    rt_counts = cf.get("right_tail_volatility_counts") or candidate.get("right_tail_volatility_counts") or {}
    if rt_counts.get("Eruption", 0) > 0:
        return "Eruption"
    if rt_counts.get("Volatile", 0) > 0:
        return "Volatile"
    return "Stable"


def right_tail_candidate_passes_quality_gate(candidate: Dict[str, Any]) -> bool:
    """Validate that a right-tail candidate is useful volatility, not noise.

    Explicit low-ceiling/no-first-place-path flags fail. Explicit high or extreme
    duplication risk fails unless the candidate carries an affirmative
    first_place_path override. Missing diagnostic fields remain permissive so
    older candidate-bank records do not silently disappear.
    """
    tier = _candidate_right_tail_tier(candidate)
    if tier not in {"Volatile", "Eruption"}:
        return True
    if candidate.get("first_place_path") is False or candidate.get("ceiling_story") == "none":
        return False
    dup_tier = str(candidate.get("duplication_risk_tier") or candidate.get("duplication_risk") or "").strip().lower()
    projected_dupes = candidate.get("projected_duplicate_count")
    high_dup = dup_tier in {"high", "extreme", "very_high"}
    try:
        high_dup = high_dup or (projected_dupes is not None and float(projected_dupes) >= 6)
    except (TypeError, ValueError):
        pass
    if high_dup and candidate.get("first_place_path") is not True:
        return False
    return True


def _assign_lineups_greedy_fallback(
    candidates: Sequence[Dict[str, Any]],
    contest_cards: Sequence[ContestCard],
    allocations: Dict[str, int],
    right_tail_retention_pct: float,
) -> Dict[str, Any]:
    """Legacy deterministic assignment used only if the joint MILP fails."""
    assignments = []
    warnings = ['joint_assignment_milp_failed; used_greedy_fallback']
    per_contest_selected: Dict[str, List[str]] = {}
    for card in contest_cards:
        n = int(allocations.get(card.contest_id, 0))
        shape = contest_shape_for_card(card)
        ranked = sorted(
            enumerate(candidates),
            key=lambda item: (_candidate_shape_score(item[1], shape), float(item[1].get('objective', 0.0))),
            reverse=True,
        )
        selected = []
        used_sigs = set()
        for idx, cand in ranked:
            sig = _candidate_player_signature(cand)
            if card.no_duplicates_within_contest and sig in used_sigs:
                continue
            selected.append((idx, cand)); used_sigs.add(sig)
            if len(selected) >= n:
                break
        per_contest_selected[card.contest_id] = [_candidate_id(c, idx) for idx, c in selected]
        for slot, (idx, cand) in enumerate(selected, 1):
            assignments.append({
                'contest_id': card.contest_id,
                'contest_name': card.name,
                'contest_shape': shape,
                'entry_slot': slot,
                'candidate_id': _candidate_id(cand, idx),
                'lineup_signature': '|'.join(_candidate_player_signature(cand)),
                'cross_contest_reuse_allowed': card.allow_cross_contest_reuse,
                'contest_fit_score': round(_candidate_shape_score(cand, shape), 4),
                'right_tail_tier': _candidate_right_tail_tier(cand),
            })
    reuse_counts = Counter(row['candidate_id'] for row in assignments)
    for row in assignments:
        row['reused_across_contests'] = reuse_counts[row['candidate_id']] > 1
    return {
        'assignments': assignments,
        'per_contest_selected': per_contest_selected,
        'candidate_reuse_counts': dict(reuse_counts),
        'warnings': warnings,
        'allocation_method': 'greedy_fallback',
        'allocation_certified': False,
        'passed': False,
        'summary': 'Joint assignment MILP failed; greedy fallback is diagnostic-only and must not be exported',
    }


def _candidate_pitcher_ids(candidate: Dict[str, Any]) -> Tuple[str, ...]:
    values = candidate.get("sp_ids") or (candidate.get("contest_fit") or {}).get("sp_ids") or []
    return tuple(sorted(str(x) for x in values if str(x)))


def _candidate_primary_stack(candidate: Dict[str, Any]) -> str:
    """Primary stack team, or "" when the lineup has no primary stack.

    F15: ``optimizer_v3._identify_primary_stack`` returns the literal 'NONE' as
    the DU signature's no-stack sentinel. Read here it is a truthy team name, so
    every stackless candidate landed in one phantom 'NONE' bucket and the
    primary-stack exposure cap constrained it as if a team by that name existed.
    On a bank with more stackless candidates than the cap allows, that is a
    spurious infeasibility with no binding constraint a human can find.
    """
    cf = candidate.get("contest_fit") or {}
    value = str(candidate.get("primary_stack") or cf.get("primary_stack") or "").strip().upper()
    return "" if value == "NONE" else value


def _candidate_primary_stack_size(candidate: Dict[str, Any]) -> int:
    """Hitter count on the candidate's primary stack, 0 when it has none.

    R34. Reads the ``primary_stack_size`` the optimizer now emits alongside
    ``primary_stack``. A candidate built before that field existed reports 0,
    which reads as "no five-stack" and therefore cannot satisfy a size floor.
    That is the safe direction: an unknown size never counts toward a floor it
    may not meet, so a stale bank makes the floor infeasible and visible rather
    than silently satisfied.
    """
    cf = candidate.get("contest_fit") or {}
    raw = candidate.get("primary_stack_size")
    if raw is None:
        raw = cf.get("primary_stack_size")
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return 0


# ---------------------------------------------------------------------------
# v1.11 (F13) allocator solver semantics
#
# The allocator returned one string, "entry-level joint MILP infeasible or timed
# out", for two conditions that call for opposite responses. Proven infeasible
# means a control is arithmetically impossible against this bank and the fix is
# to name it and change it. Time limit means the model was too big for the
# clock and the fix is more time, fewer candidates, or the incumbent that was
# already found. Collapsing them produced a message that pointed at neither.
# ---------------------------------------------------------------------------

# Candidates kept per requested entry before the joint MILP. The pairwise
# overlap constraints are K-squared, so an unfiltered bank of several hundred is
# where the allocator's own time limit comes from.
DEFAULT_CANDIDATE_PREFILTER_MULTIPLE = 6
MIN_CANDIDATE_PREFILTER_FLOOR = 40


def _diagnose_binding_constraints(
    entries_count: int,
    stacks: Sequence[str],
    sp_pairs: Sequence[Tuple[str, ...]],
    signatures: Sequence[Tuple[str, ...]],
    largest_contest_entries: int,
    controls: Dict[str, Any],
) -> List[str]:
    """Name the controls that cannot be satisfied by this bank, arithmetically.

    Every check here is a counting argument on the bank as handed in, not a
    re-solve: buckets times cap has to reach the entry count or no assignment
    exists. It cannot prove infeasibility on its own (the MILP already did
    that), and it never guesses. When it finds nothing it says so, which is
    itself the useful answer: the interaction, not any single cap, is binding.
    """
    findings: List[str] = []
    total = int(entries_count)

    stack_cap = _cap_count(total, controls.get("max_primary_stack_exposure_pct"))
    if stack_cap:
        buckets = len({x for x in stacks if x})
        stackless = sum(1 for x in stacks if not x)
        # Stackless candidates carry no bucket, so they are unconstrained here.
        if not stackless and buckets * stack_cap < total:
            findings.append(
                f"max_primary_stack_exposure_pct: {buckets} distinct primary stacks x "
                f"cap {stack_cap} = {buckets * stack_cap} < {total} entries"
            )

    pair_cap = controls.get("max_sp_pair_repetition")
    if pair_cap is not None:
        buckets = len(set(sp_pairs))
        if buckets * int(pair_cap) < total:
            findings.append(
                f"max_sp_pair_repetition: {buckets} distinct SP pairs x cap "
                f"{int(pair_cap)} = {buckets * int(pair_cap)} < {total} entries"
            )

    distinct_signatures = len(set(signatures))
    max_reuse = controls.get("max_candidate_reuse")
    if max_reuse is not None and distinct_signatures * int(max_reuse) < total:
        findings.append(
            f"max_candidate_reuse: {distinct_signatures} distinct lineups x cap "
            f"{int(max_reuse)} = {distinct_signatures * int(max_reuse)} < {total} entries"
        )

    if largest_contest_entries > distinct_signatures:
        findings.append(
            f"per-contest lineup uniqueness: one contest reserves "
            f"{largest_contest_entries} entries but the bank holds only "
            f"{distinct_signatures} distinct lineups"
        )

    pitcher_cap = _cap_count(total, controls.get("max_pitcher_exposure_pct"))
    if pitcher_cap:
        arms = {pid for pair in sp_pairs for pid in pair}
        # Two pitcher slots per lineup.
        if len(arms) * pitcher_cap < total * 2:
            findings.append(
                f"max_pitcher_exposure_pct: {len(arms)} distinct starters x cap "
                f"{pitcher_cap} = {len(arms) * pitcher_cap} < {total * 2} pitcher slots"
            )
    return findings


def _prefilter_candidates(
    candidates: Sequence[Dict[str, Any]],
    entries: Sequence[Dict[str, Any]],
    compatible: Sequence[Sequence[bool]],
    keep_target: int,
) -> Tuple[List[int], Dict[str, Any]]:
    """Choose which candidate indices enter the joint MILP.

    Forced coverage first: any candidate that is the only compatible option for
    some entry is kept unconditionally, because dropping it makes the problem
    infeasible outright. Then one representative per primary stack and per SP
    pair, so no exposure cap loses its bucket and starts reporting a phantom
    infeasibility. Then the best remaining by shape score until the target.
    Ordering is deterministic: score descending, candidate id ascending.
    """
    K = len(candidates)
    if K <= keep_target:
        return list(range(K)), {
            "applied": False, "candidates_in": K, "candidates_kept": K,
            "keep_target": keep_target,
        }

    best_score: Dict[int, float] = {}
    for k in range(K):
        scores = [
            _candidate_shape_score(candidates[k], str(e.get("contest_shape") or "large_wta"))
            for e in entries
        ]
        best_score[k] = max(scores) if scores else 0.0
    order = sorted(range(K), key=lambda k: (-best_score[k], _candidate_id(candidates[k], k)))

    keep: List[int] = []
    seen = set()

    def _take(k: int) -> None:
        if k not in seen:
            seen.add(k)
            keep.append(k)

    forced = 0
    for e in range(len(entries)):
        options = [k for k in range(K) if compatible[e][k]]
        if len(options) == 1:
            forced += 1
            _take(options[0])

    covered_stacks = set()
    covered_pairs = set()
    for k in order:
        stack = _candidate_primary_stack(candidates[k])
        pair = _candidate_pitcher_ids(candidates[k])
        if stack and stack not in covered_stacks:
            covered_stacks.add(stack)
            _take(k)
        if pair and pair not in covered_pairs:
            covered_pairs.add(pair)
            _take(k)

    for k in order:
        if len(keep) >= keep_target:
            break
        _take(k)

    keep.sort()
    return keep, {
        "applied": True,
        "candidates_in": K,
        "candidates_kept": len(keep),
        "keep_target": keep_target,
        "forced_coverage_kept": forced,
        "distinct_stacks_represented": len(covered_stacks),
        "distinct_sp_pairs_represented": len(covered_pairs),
        "rule": "forced-coverage candidates, then one representative per primary "
                "stack and SP pair, then best shape score; deterministic, never a "
                "win-rate or probability claim",
    }


def _cap_count(total: int, pct: Optional[float]) -> Optional[int]:
    if pct is None:
        return None
    value = float(pct)
    if value <= 0:
        return None
    return max(1, int(math.floor(total * min(1.0, value) + 1e-9)))


def assign_lineups_to_contests(
    candidates: Sequence[Dict[str, Any]],
    contest_cards: Sequence[ContestCard],
    allocations: Dict[str, int],
    right_tail_retention_pct: float = DEFAULT_RIGHT_TAIL_RETENTION_PCT,
    reuse_strategy: str = 'balanced',
    max_candidate_reuse: Optional[int] = None,
    reuse_penalty: float = 2.0,
    max_player_exposure_pct: Optional[float] = None,
    max_pitcher_exposure_pct: Optional[float] = None,
    max_primary_stack_exposure_pct: Optional[float] = None,
    max_sp_pair_repetition: Optional[int] = None,
    max_shared_players: Optional[int] = None,
) -> Dict[str, Any]:
    """Select and assign from the full bank in one SciPy MILP.

    This legacy contest-count solve is retained for compatibility; v1.9 production uses select_and_assign_entries(). Direct exposure and overlap
    constraints replace DU/right-tail machinery as the primary diversity controls.
    The legacy greedy fallback remains diagnostic-only and is never certified.
    """
    candidates = list(candidates)
    active_cards = [c for c in contest_cards if int(allocations.get(c.contest_id, 0)) > 0]
    per_contest_selected: Dict[str, List[str]] = {c.contest_id: [] for c in contest_cards}
    if not active_cards:
        return {
            'assignments': [], 'per_contest_selected': per_contest_selected,
            'candidate_reuse_counts': {}, 'warnings': [],
            'allocation_method': 'scipy_milp_joint', 'reuse_strategy': reuse_strategy,
            'selection_certified': True, 'allocation_certified': True, 'passed': True,
            'summary': 'No contest entries requested',
        }
    if not candidates:
        return {
            'assignments': [], 'per_contest_selected': per_contest_selected,
            'candidate_reuse_counts': {}, 'warnings': ['no_candidates_available'],
            'allocation_method': 'scipy_milp_joint', 'reuse_strategy': reuse_strategy,
            'selection_certified': False, 'allocation_certified': False, 'passed': False,
            'summary': 'No candidates available for requested contest entries',
        }

    strategy = str(reuse_strategy or 'balanced').strip().lower()
    if strategy not in {'concentrated', 'balanced', 'diversified'}:
        raise ValueError('reuse_strategy must be concentrated, balanced, or diversified')

    try:
        import numpy as np
        from scipy.optimize import Bounds, LinearConstraint, milp
        from scipy.sparse import coo_matrix
    except ImportError:
        fallback = _assign_lineups_greedy_fallback(candidates, contest_cards, allocations, right_tail_retention_pct)
        fallback['selection_certified'] = False
        return fallback

    card_count, cand_count = len(active_cards), len(candidates)
    x_count = card_count * cand_count
    excess_offset = x_count
    selected_offset = excess_offset + cand_count
    use_selected_vars = max_shared_players is not None
    n_vars = x_count + cand_count + (cand_count if use_selected_vars else 0)
    def x_idx(ci, ki): return ci * cand_count + ki
    def y_idx(ki): return selected_offset + ki

    c_obj = np.zeros(n_vars, dtype=float)
    raw_scores: Dict[Tuple[int, int], float] = {}
    for ci, card in enumerate(active_cards):
        shape = contest_shape_for_card(card)
        scores = [_candidate_shape_score(cand, shape) for cand in candidates]
        lo, hi = min(scores), max(scores)
        for ki, score in enumerate(scores):
            normalized = 50.0 if hi <= lo else 100.0 * (score - lo) / (hi - lo)
            raw_scores[(ci, ki)] = score
            c_obj[x_idx(ci, ki)] = -normalized
    if strategy == 'balanced':
        c_obj[excess_offset:excess_offset + cand_count] = float(reuse_penalty)
    elif strategy == 'diversified':
        c_obj[excess_offset:excess_offset + cand_count] = float(reuse_penalty) * 4.0

    rows: List[Dict[int, float]] = []
    lbs: List[float] = []
    ubs: List[float] = []
    def add(coefs, lb, ub):
        rows.append(dict(coefs)); lbs.append(lb); ubs.append(ub)

    warnings: List[str] = []
    total_requested = sum(int(allocations.get(card.contest_id, 0)) for card in active_cards)
    signatures = [_candidate_player_signature(c) for c in candidates]
    player_sets = [set(sig) for sig in signatures]
    pitcher_sets = [set(_candidate_pitcher_ids(c)) for c in candidates]
    primary_stacks = [_candidate_primary_stack(c) for c in candidates]
    sp_pairs = [tuple(sorted(pitcher_sets[i])) if len(pitcher_sets[i]) == 2 else tuple() for i in range(cand_count)]

    for ci, card in enumerate(active_cards):
        n = int(allocations.get(card.contest_id, 0))
        add({x_idx(ci, ki): 1.0 for ki in range(cand_count)}, n, n)
        if card.no_duplicates_within_contest:
            sig_groups: Dict[Tuple[str, ...], List[int]] = defaultdict(list)
            for ki, sig in enumerate(signatures):
                sig_groups[sig].append(ki)
            for idxs in sig_groups.values():
                if len(idxs) > 1:
                    add({x_idx(ci, ki): 1.0 for ki in idxs}, -np.inf, 1.0)

        if right_tail_retention_pct and right_tail_retention_pct > 0:
            shape = contest_shape_for_card(card)
            if shape in {'small_field_gpp', 'mid_field_gpp', 'large_field_gpp', 'small_wta', 'mid_wta', 'large_wta', 'wta_ticket_satellite'}:
                required_tail = max(1, math.ceil(n * right_tail_retention_pct))
                tail_idxs = [ki for ki, cand in enumerate(candidates) if _candidate_right_tail_tier(cand) in {'Volatile', 'Eruption'} and right_tail_candidate_passes_quality_gate(cand)]
                if len(tail_idxs) >= required_tail:
                    add({x_idx(ci, ki): 1.0 for ki in tail_idxs}, required_tail, np.inf)
                else:
                    warnings.append(f'{card.contest_id}: optional right-tail quota unavailable ({len(tail_idxs)}/{required_tail})')

    if max_candidate_reuse is not None:
        reuse_cap = max(1, int(max_candidate_reuse))
    elif strategy == 'concentrated':
        reuse_cap = card_count
    elif strategy == 'diversified':
        reuse_cap = 1
    else:
        reuse_cap = max(2, int(math.ceil(card_count / 2.0)))
    minimum_cap = int(math.ceil(total_requested / max(1, cand_count)))
    if reuse_cap < minimum_cap:
        warnings.append(f'reuse cap raised {reuse_cap}->{minimum_cap} for feasibility')
        reuse_cap = minimum_cap

    for ki in range(cand_count):
        usage = {x_idx(ci, ki): 1.0 for ci in range(card_count)}
        add(usage, -np.inf, reuse_cap)
        coefs = dict(usage); coefs[excess_offset + ki] = -1.0
        add(coefs, -np.inf, 1.0)
        if use_selected_vars:
            # usage <= card_count*y and y <= usage
            link = dict(usage); link[y_idx(ki)] = -float(card_count)
            add(link, -np.inf, 0.0)
            add({y_idx(ki): 1.0, **{x_idx(ci, ki): -1.0 for ci in range(card_count)}}, -np.inf, 0.0)

    # Direct portfolio exposure controls.
    player_cap = _cap_count(total_requested, max_player_exposure_pct)
    pitcher_cap = _cap_count(total_requested, max_pitcher_exposure_pct)
    stack_cap = _cap_count(total_requested, max_primary_stack_exposure_pct)
    if player_cap:
        for pid in sorted({p for s in player_sets for p in s}):
            add({x_idx(ci, ki): 1.0 for ci in range(card_count) for ki in range(cand_count) if pid in player_sets[ki]}, -np.inf, player_cap)
    if pitcher_cap:
        for pid in sorted({p for s in pitcher_sets for p in s}):
            add({x_idx(ci, ki): 1.0 for ci in range(card_count) for ki in range(cand_count) if pid in pitcher_sets[ki]}, -np.inf, pitcher_cap)
    if stack_cap:
        for team in sorted({x for x in primary_stacks if x}):
            add({x_idx(ci, ki): 1.0 for ci in range(card_count) for ki in range(cand_count) if primary_stacks[ki] == team}, -np.inf, stack_cap)
    if max_sp_pair_repetition is not None and int(max_sp_pair_repetition) > 0:
        for pair in sorted({x for x in sp_pairs if x}):
            add({x_idx(ci, ki): 1.0 for ci in range(card_count) for ki in range(cand_count) if sp_pairs[ki] == pair}, -np.inf, int(max_sp_pair_repetition))
    if use_selected_vars:
        limit = int(max_shared_players)
        for i in range(cand_count):
            for j in range(i + 1, cand_count):
                if len(player_sets[i] & player_sets[j]) > limit:
                    add({y_idx(i): 1.0, y_idx(j): 1.0}, -np.inf, 1.0)

    for ci, card in enumerate(active_cards):
        if card.allow_cross_contest_reuse:
            continue
        for other_ci in range(card_count):
            if other_ci == ci:
                continue
            for ki in range(cand_count):
                add({x_idx(ci, ki): 1.0, x_idx(other_ci, ki): 1.0}, -np.inf, 1.0)

    row_idx: List[int] = []
    col_idx: List[int] = []
    data: List[float] = []
    for r, coefs in enumerate(rows):
        for col, val in coefs.items():
            if val:
                row_idx.append(r); col_idx.append(col); data.append(float(val))
    A = coo_matrix((data, (row_idx, col_idx)), shape=(len(rows), n_vars)).tocsr()
    lower = np.zeros(n_vars)
    upper = np.ones(n_vars)
    upper[excess_offset:excess_offset + cand_count] = float(card_count)
    integrality = np.ones(n_vars, dtype=int)
    result = milp(
        c=c_obj,
        integrality=integrality,
        bounds=Bounds(lower, upper),
        constraints=LinearConstraint(A, np.array(lbs, dtype=float), np.array(ubs, dtype=float)),
        options={'time_limit': 30, 'disp': False},
    )
    solver_status = str(getattr(result, 'message', getattr(result, 'status', None)))
    if not result.success or result.x is None:
        fallback = _assign_lineups_greedy_fallback(candidates, contest_cards, allocations, right_tail_retention_pct)
        fallback['warnings'].append(f'joint_solver_status: {solver_status}')
        fallback['reuse_strategy'] = strategy
        fallback['selection_certified'] = False
        fallback['direct_constraint_failure'] = True
        return fallback

    assignments: List[Dict[str, Any]] = []
    for ci, card in enumerate(active_cards):
        chosen = [ki for ki in range(cand_count) if result.x[x_idx(ci, ki)] > 0.5]
        chosen.sort(key=lambda ki: (raw_scores[(ci, ki)], float(candidates[ki].get('objective', 0.0))), reverse=True)
        selected_ids: List[str] = []
        shape = contest_shape_for_card(card)
        for slot, ki in enumerate(chosen, 1):
            cand = candidates[ki]
            cid = _candidate_id(cand, ki)
            selected_ids.append(cid)
            assignments.append({
                'contest_id': card.contest_id,
                'contest_name': card.name,
                'contest_shape': shape,
                'entry_slot': slot,
                'candidate_id': cid,
                'lineup_signature': '|'.join(signatures[ki]),
                'cross_contest_reuse_allowed': card.allow_cross_contest_reuse,
                'contest_fit_score': round(raw_scores[(ci, ki)], 4),
                'right_tail_tier': _candidate_right_tail_tier(cand),
            })
        per_contest_selected[card.contest_id] = selected_ids

    reuse_counts = Counter(row['candidate_id'] for row in assignments)
    for row in assignments:
        row['reused_across_contests'] = reuse_counts[row['candidate_id']] > 1
    return {
        'assignments': assignments,
        'per_contest_selected': per_contest_selected,
        'candidate_reuse_counts': dict(reuse_counts),
        'warnings': warnings,
        'allocation_method': 'scipy_milp_joint_select_assign',
        'selection_certified': True,
        'allocation_certified': True,
        'passed': True,
        'allocation_solver_status': solver_status,
        'reuse_strategy': strategy,
        'max_candidate_reuse': reuse_cap,
        'direct_constraints': {
            'max_player_count': player_cap,
            'max_pitcher_count': pitcher_cap,
            'max_primary_stack_count': stack_cap,
            'max_sp_pair_repetition': max_sp_pair_repetition,
            'max_shared_players': max_shared_players,
        },
        'summary': f'Joint selection/allocation solved with {strategy} reuse posture',
    }


def sp_family_compression_audit(
    global_candidates: Sequence[Dict[str, Any]],
    selected_candidate_ids: Sequence[str],
    warn_delta: float = DEFAULT_SP_COMPRESSION_WARN_DELTA,
) -> Dict[str, Any]:
    """Compare SP exposure in global bank vs selected subset.

    Candidates can provide sp_ids=[...] or contest_fit['sp_pair']. Missing SPs
    are ignored. Emits warnings for material subset compression.
    """
    selected_set = set(str(x) for x in selected_candidate_ids)
    bank_counts: Counter = Counter()
    selected_counts: Counter = Counter()
    bank_n = 0
    selected_n = 0

    for i, cand in enumerate(global_candidates):
        cid = _candidate_id(cand, i)
        sp_ids = cand.get("sp_ids")
        if sp_ids is None:
            cf = cand.get("contest_fit") or {}
            sp_pair = cf.get("sp_pair") or cand.get("sp_pair")
            if sp_pair in (None, "", "none"):
                sp_ids = []
            elif isinstance(sp_pair, (list, tuple)):
                sp_ids = list(sp_pair)
            else:
                sp_ids = str(sp_pair).split("+") if "+" in str(sp_pair) else str(sp_pair).split("/")
        sp_ids = [str(x).strip() for x in sp_ids if str(x).strip()]
        if not sp_ids:
            continue
        bank_n += 1
        bank_counts.update(sp_ids)
        if cid in selected_set:
            selected_n += 1
            selected_counts.update(sp_ids)

    rows = []
    warnings = []
    all_sp = sorted(set(bank_counts) | set(selected_counts))
    for sp in all_sp:
        bank_pct = bank_counts[sp] / max(1, bank_n)
        sel_pct = selected_counts[sp] / max(1, selected_n)
        delta = sel_pct - bank_pct
        row = {
            "sp_id": sp,
            "bank_exposure_pct": round(100.0 * bank_pct, 2),
            "selected_exposure_pct": round(100.0 * sel_pct, 2),
            "delta_pct": round(100.0 * delta, 2),
            "bank_count": int(bank_counts[sp]),
            "selected_count": int(selected_counts[sp]),
        }
        rows.append(row)
        if bank_pct >= warn_delta and sel_pct <= max(0.0, bank_pct - warn_delta):
            warnings.append(
                f"SP compression review: {sp} appears {row['bank_exposure_pct']}% in bank but "
                f"{row['selected_exposure_pct']}% in selected subset"
            )
    return {
        "rows": rows,
        "warnings": warnings,
        "summary": f"SP family compression audit reviewed {len(rows)} SPs",
    }


def aggregate_field_exposure_by_player(field_exposure_rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Aggregate exposure diagnostics by Player_ID/name across roster positions.

    DraftKings standings/export tables can split the same hitter across eligible
    positions. Review logic must aggregate before Field_Exposure_Delta warnings
    so multi-position hitters are not undercounted.
    """
    grouped: Dict[str, Dict[str, Any]] = {}
    for row in field_exposure_rows or []:
        key = str(row.get("player_id") or row.get("Player_ID") or row.get("name") or row.get("Name") or "UNKNOWN")
        rec = grouped.setdefault(key, {
            "player_id": row.get("player_id") or row.get("Player_ID") or "",
            "name": row.get("name") or row.get("Name") or key,
            "positions": set(),
            "projected_field_ownership_pct": 0.0,
            "our_exposure_pct": 0.0,
        })
        pos = row.get("position") or row.get("Position")
        if pos:
            rec["positions"].add(str(pos))
        rec["projected_field_ownership_pct"] += float(row.get("projected_field_ownership_pct", row.get("field_ownership_pct", 0.0)) or 0.0)
        rec["our_exposure_pct"] += float(row.get("our_exposure_pct", 0.0) or 0.0)
    output = []
    for rec in grouped.values():
        out = dict(rec)
        out["positions"] = "/".join(sorted(rec["positions"]))
        output.append(out)
    output.sort(key=lambda r: (-float(r["projected_field_ownership_pct"]), str(r["name"])))
    return output


def material_field_exposure_warnings(
    field_exposure_delta_rows: Sequence[Dict[str, Any]],
    material_field_ownership_pct: float = DEFAULT_MATERIAL_FIELD_OWNERSHIP_PCT,
) -> List[str]:
    """Convert Field_Exposure_Delta rows into blocking review warnings."""
    warnings = []
    for row in aggregate_field_exposure_by_player(field_exposure_delta_rows):
        field_own = float(row.get("projected_field_ownership_pct", 0.0))
        our_exp = float(row.get("our_exposure_pct", 0.0))
        name = row.get("name") or row.get("player_id")
        if field_own >= material_field_ownership_pct and our_exp <= max(0.0, field_own - 20.0):
            warnings.append(
                f"Material field-divergence review: {name} projected {field_own:.1f}% field ownership, "
                f"selected portfolio {our_exp:.1f}%. Intentional fade or selection artifact?"
            )
    return warnings


def cheap_high_total_stack_quota(
    team_rows: Sequence[Dict[str, Any]],
    implied_total_gap: float = 0.40,
    salary_discount_pct: float = 8.0,
) -> Dict[str, Any]:
    """Identify cheap teams near the slate's top implied total for bank quotas.

    Inputs should contain team, implied_total, and avg_hitter_salary or
    median_hitter_salary. Output is a deterministic candidate-bank quota aid,
    not a projection or contest simulation.
    """
    rows = [dict(r) for r in team_rows or []]
    if not rows:
        return {"teams": [], "summary": "No team environment rows supplied"}
    max_total = max(float(r.get("implied_total", 0.0) or 0.0) for r in rows)
    salaries = [float(r.get("avg_hitter_salary", r.get("median_hitter_salary", 0.0)) or 0.0) for r in rows]
    avg_salary = sum(salaries) / max(1, len([x for x in salaries if x > 0])) if any(x > 0 for x in salaries) else 0.0
    candidates = []
    for r in rows:
        team = str(r.get("team") or r.get("Team") or "")
        total = float(r.get("implied_total", 0.0) or 0.0)
        sal = float(r.get("avg_hitter_salary", r.get("median_hitter_salary", 0.0)) or 0.0)
        near_top = total >= max_total - float(implied_total_gap)
        discount = 100.0 * (avg_salary - sal) / avg_salary if avg_salary > 0 and sal > 0 else 0.0
        if team and near_top and discount >= float(salary_discount_pct):
            candidates.append({
                "team": team,
                "implied_total": round(total, 2),
                "salary_discount_pct": round(discount, 2),
                "recommended_bank_quota": "force_stack_or_mini_stack_exposure",
            })
    return {
        "teams": candidates,
        "summary": f"Cheap high-total quota review found {len(candidates)} team(s)",
    }


def write_master_assignment_csv(assignments: Sequence[Dict[str, Any]], path: str) -> str:
    """Write master lineup assignment map."""
    fieldnames = [
        "contest_id", "contest_name", "contest_shape", "entry_slot", "candidate_id",
        "contest_fit_score", "right_tail_tier", "reused_across_contests",
        "cross_contest_reuse_allowed", "lineup_signature",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in assignments:
            writer.writerow({k: row.get(k, "") for k in fieldnames})
    return path


# ---------------------------------------------------------------------------
# v1.2-v1.5 Runtime-Aware Candidate Bank Governor
# ---------------------------------------------------------------------------

def _default_candidate_bank_target(requested_lineups: int) -> int:
    requested = max(1, int(requested_lineups or 1))
    if requested == 1:
        return 8
    if requested <= 3:
        return 12
    if requested <= 9:
        return max(12, requested + 6)
    return min(40, int(math.ceil(1.5 * requested)))


def resolve_candidate_bank_plan(
    requested_lineups: int,
    contest_entry_counts: Optional[Sequence[int]] = None,
    contest_shapes: Optional[Sequence[str]] = None,
    cross_contest_reuse: bool = True,
    slate_game_count: Optional[int] = None,
    eligible_sp_count: Optional[int] = None,
    sp_pair_coverage_pair_count: Optional[int] = None,
    sp_pair_coverage_policy: Optional[str] = None,
    has_locks_or_tbd: bool = False,
    near_lock: bool = False,
    runtime_context: str = "chatgpt",
    pilot_candidates_requested: Optional[int] = None,
    pilot_candidates_built: Optional[int] = None,
    pilot_failed_indices: Optional[Sequence[int]] = None,
    pilot_elapsed_seconds: Optional[float] = None,
    max_candidate_reuse: Optional[int] = 3,
) -> Dict[str, Any]:
    """Return a runtime-aware candidate-bank plan for GPP/WTA builds.

    v1.4 change: in Reserved Entry Grid Mode with cross-contest reuse, the bank
    is sized from unique lineup demand (largest same-contest block + shape/tail
    buffers), not from total reserved rows. This keeps a 34-entry sheet with a
    20-entry largest contest from becoming an automatic 80-candidate run.

    v1.5 change: when optimizer_v3 resolves hard_all_pairs SP-pair coverage,
    the bank target may not be reduced below the required pair count.
    """
    requested = max(1, int(requested_lineups or 1))
    entry_counts = [int(x) for x in (contest_entry_counts or []) if int(x) > 0]
    largest_same_contest_block = max(entry_counts, default=requested)
    shapes = sorted({str(x) for x in (contest_shapes or []) if str(x)})
    shape_buffer = max(3, len(shapes)) if shapes else 3
    required_unique_for_reuse = int(math.ceil(requested / max(1, int(max_candidate_reuse or requested))))
    right_tail_buffer = 0

    raw_default_target = _default_candidate_bank_target(requested)
    if entry_counts and cross_contest_reuse:
        unique_need = max(largest_same_contest_block, required_unique_for_reuse) + shape_buffer
        # Compact default from unique demand. Keep enough optionality for
        # contest-shape selection without blindly tripling raw entry count.
        default_target = min(raw_default_target, max(unique_need + 8, int(math.ceil(unique_need * 1.25))))
        bank_sizing_basis = "reserved_grid_unique_lineup_demand"
    else:
        unique_need = max(requested + 4, 12)
        default_target = raw_default_target
        bank_sizing_basis = "requested_final_lineup_count"

    sp_pair_count = int(sp_pair_coverage_pair_count or 0)
    sp_policy = str(sp_pair_coverage_policy or "").lower()
    if sp_policy == "hard_all_pairs" and sp_pair_count > 0:
        unique_need = max(unique_need, sp_pair_count)
        default_target = max(default_target, sp_pair_count)
        bank_sizing_basis += "+sp_pair_coverage_floor"

    runtime = str(runtime_context or "chatgpt").lower()
    runtime_cap = 40 if runtime == "chatgpt" else 80
    risk_reasons: List[str] = []
    if default_target > runtime_cap:
        risk_reasons.append("default_bank_target_exceeds_runtime_cap")
    if slate_game_count is not None and int(slate_game_count) <= 3:
        risk_reasons.append("small_slate")
        runtime_cap = min(runtime_cap, 32)
    if sp_policy == "hard_all_pairs" and sp_pair_count > 0:
        risk_reasons.append("hard_sp_pair_coverage")
        runtime_cap = max(runtime_cap, min(40 if runtime == "chatgpt" else 80, sp_pair_count))
    if eligible_sp_count is not None and int(eligible_sp_count) <= 5:
        risk_reasons.append("compressed_sp_pool")
        runtime_cap = min(runtime_cap, 32)
    if has_locks_or_tbd:
        risk_reasons.append("locks_or_tbd_narrow_pool")
        runtime_cap = min(runtime_cap, 32)
    if near_lock:
        risk_reasons.append("near_lock")
        runtime_cap = min(runtime_cap, 24)

    pilot_failed = len(list(pilot_failed_indices or []))
    if pilot_candidates_requested is not None and pilot_candidates_built is not None:
        if int(pilot_candidates_built) < int(pilot_candidates_requested) or pilot_failed:
            risk_reasons.append("pilot_incomplete")
            runtime_cap = min(runtime_cap, max(12, largest_same_contest_block + 6))
    if pilot_elapsed_seconds is not None and float(pilot_elapsed_seconds) >= 30.0:
        risk_reasons.append("pilot_slow")
        runtime_cap = min(runtime_cap, max(12, largest_same_contest_block + 8))

    actual_target = min(default_target, runtime_cap)
    actual_target = max(min(unique_need, runtime_cap), actual_target)
    if near_lock:
        actual_target = min(actual_target, max(12, largest_same_contest_block + 4))

    if actual_target >= raw_default_target:
        fallback_tier = "A_full_review"
    elif actual_target >= max(20, largest_same_contest_block * 2):
        fallback_tier = "B_compact_review"
    elif actual_target >= max(12, largest_same_contest_block + 4):
        fallback_tier = "C_minimum_viable_review"
    else:
        fallback_tier = "D_direct_certified_build"

    reduced = actual_target < raw_default_target
    pilot_required = bool(actual_target > 24 and runtime == "chatgpt")
    reason = ",".join(dict.fromkeys(risk_reasons)) if risk_reasons else ("unique_demand_compaction" if reduced else "full_target")
    return {
        "candidate_bank_reduced": bool(reduced),
        "requested_lineups": requested,
        "largest_same_contest_block": int(largest_same_contest_block),
        "raw_default_bank_target": int(raw_default_target),
        "default_bank_target": int(default_target),
        "actual_bank_target": int(actual_target),
        "unique_lineup_need": int(unique_need),
        "bank_sizing_basis": bank_sizing_basis,
        "sp_pair_coverage_policy": sp_policy or None,
        "sp_pair_coverage_pair_count": int(sp_pair_count),
        "runtime_context": runtime,
        "runtime_cap": int(runtime_cap),
        "fallback_tier": fallback_tier,
        "reason": reason,
        "pilot_required": pilot_required,
        "pilot_candidate_target": 5 if pilot_required else None,
        "pilot_summary": {
            "requested": pilot_candidates_requested,
            "built": pilot_candidates_built,
            "failed_indices": list(pilot_failed_indices or []),
            "elapsed_seconds": pilot_elapsed_seconds,
        },
        "note": "candidate-bank sizing proxy only; does not change optimizer hard constraints or claim ROI",
    }

# ---------------------------------------------------------------------------
# v1.1 Reserved Entry Grid helpers
# ---------------------------------------------------------------------------


def resolve_phase0_mode(
    reserved_grid_summary: Optional[Dict[str, Any]] = None,
    total_budget: Optional[float] = None,
    choosing_contests: bool = False,
) -> str:
    """Use lean reserved-entry execution unless contest selection is requested."""
    has_reserved = bool((reserved_grid_summary or {}).get('contests'))
    if has_reserved and total_budget is None and not choosing_contests:
        return 'reserved_entry_execution'
    return 'contest_selection'


def reserved_grid_action(summary: Dict[str, Any], total_budget_remaining: Optional[float] = None) -> Dict[str, Any]:
    """Recommend a keep/reduce/add/need-info action from a DKEntries contest summary.

    This is a fast Phase 0 triage helper for already-reserved entries. It does
    not claim ROI/profitability. It uses contest archetype, reserved entries,
    entry fee, and missing-field gaps to produce an operator-facing action.
    """
    contest_type = str(summary.get("inferred_type") or summary.get("contest_type") or "unknown").lower()
    reserved_entries = int(summary.get("reserved_entries") or 0)
    entry_fee = float(summary.get("entry_fee") or summary.get("buy_in") or 0.0)
    gaps = list(summary.get("decision_critical_gaps") or [])
    name = str(summary.get("contest_name") or summary.get("name") or "UNKNOWN")
    action = "keep_reserved"
    priority = "medium"
    rationale = []

    if contest_type == "satellite":
        action = "need_ticket_details"
        priority = "unknown_until_ticket_structure"
        rationale.append("Satellite/ticket contests require ticket count, ticket line, and ticket value before EV-style allocation.")
    elif contest_type == "cash":
        action = "use_reserved_if_floor_edge"
        priority = "medium"
        rationale.append("Cash contests require confirmed roles and low assumption risk; do not force if slate is volatile/TBD-heavy.")
    elif contest_type == "se_gpp":
        action = "use_best_single_lineup"
        priority = "medium_high"
        rationale.append("Single-entry GPP receives one best contest-fit lineup from full global candidate bank.")
    elif contest_type == "wta":
        action = "use_only_validated_right_tail"
        priority = "conditional"
        rationale.append("WTA requires a coherent first-place path; direct exposure and overlap caps create portfolio breadth.")
    elif contest_type == "portfolio_gpp":
        action = "keep_reserved_consider_add_if_available"
        priority = "high" if reserved_entries >= 2 else "medium"
        rationale.append("Portfolio GPP can reuse strongest global lineups across contests while avoiding same-contest duplicates.")
    else:
        action = "triage_unknown"
        priority = "unknown"
        rationale.append("Contest type not reliably inferred; ask only for decision-critical missing fields.")

    if total_budget_remaining is not None and entry_fee > 0 and total_budget_remaining < entry_fee and action.startswith("keep"):
        action = "budget_limited_review"
        rationale.append("Budget remaining is below one additional entry fee; do not add more entries without user approval.")

    if gaps:
        rationale.append("Missing fields: " + ", ".join(gaps))

    return {
        "contest_id": summary.get("contest_id"),
        "contest_name": name,
        "reserved_entries": reserved_entries,
        "entry_fee": entry_fee,
        "inferred_type": contest_type,
        "action": action,
        "priority": priority,
        "decision_critical_gaps": gaps,
        "rationale": " ".join(rationale),
    }


def recommend_reserved_grid_actions(
    reserved_grid_summary: Dict[str, Any],
    total_budget: Optional[float] = None,
    declared_contest_type: Optional[str] = None,
) -> Dict[str, Any]:
    """Produce fast Phase 0 actions for all contests parsed from DKEntries.csv."""
    contests = list(reserved_grid_summary.get("contests") or [])
    reserved_buy_in = float(reserved_grid_summary.get("reserved_total_buy_in") or 0.0)
    budget_remaining = None if total_budget is None else max(0.0, float(total_budget) - reserved_buy_in)
    normalized = []
    for contest in contests:
        row = dict(contest)
        if declared_contest_type:
            row['inferred_type'] = str(declared_contest_type).lower()
            row['decision_critical_gaps'] = []
        normalized.append(row)
    actions = [reserved_grid_action(c, budget_remaining) for c in normalized]
    blocking_gaps = []
    for a in actions:
        if a["action"] in {"need_ticket_details", "triage_unknown"}:
            blocking_gaps.extend({"contest_id": a["contest_id"], "contest_name": a["contest_name"], "gap": g} for g in a["decision_critical_gaps"])
    return {
        "reserved_total_buy_in": reserved_buy_in,
        "total_budget": total_budget,
        "budget_remaining": budget_remaining,
        "actions": actions,
        "blocking_gaps": blocking_gaps,
        "phase0_mode": resolve_phase0_mode(reserved_grid_summary, total_budget=total_budget),
        "summary": f"Reserved Entry Grid Mode: {len(contests)} contest(s), reserved buy-in ${reserved_buy_in:.2f}",
    }


def contest_cards_from_reserved_grid(
    reserved_grid_summary: Dict[str, Any],
    fallback_field_size: int = 0,
    fallback_prize_pool: float = 0.0,
    declared_contest_type: Optional[str] = None,
) -> List[ContestCard]:
    """Convert parsed DKEntries contest summaries into minimal ContestCards.

    These cards are usable for assignment/export orchestration. Allocation scores
    that depend on field size/prize pool remain low-confidence until the user or
    visible contest data provides those fields.
    """
    cards: List[ContestCard] = []
    for summary in reserved_grid_summary.get("contests", []):
        ctype = str(declared_contest_type or summary.get("inferred_type") or "portfolio_gpp").lower()
        if ctype not in CONTEST_TYPES:
            ctype = "portfolio_gpp"
        reserved_entries = int(summary.get("reserved_entries") or 0)
        max_entries = int(summary.get("inferred_max_entries") or reserved_entries or 1)
        cards.append(ContestCard(
            contest_id=str(summary.get("contest_id")),
            name=str(summary.get("contest_name")),
            contest_type=ctype,
            field_size=int(summary.get("field_size") or fallback_field_size or max(reserved_entries, 1)),
            max_entries=max_entries,
            buy_in=float(summary.get("entry_fee") or 0.0),
            prize_pool=float(summary.get("prize_pool") or fallback_prize_pool or 0.0),
            min_entries=reserved_entries,
            user_max_entries=reserved_entries,
            priority="medium",
            source="dk_entries",
            reserved_entries=reserved_entries,
            metadata_confidence=str(summary.get("inference_confidence") or "inferred"),
            decision_critical_gaps=[] if declared_contest_type else list(summary.get("decision_critical_gaps") or []),
            ticket_value=summary.get("inferred_ticket_value"),
        ))
    return cards

# ---------------------------------------------------------------------------
# v1.9 Entry-level joint selection and assignment
# ---------------------------------------------------------------------------

ENTRY_ROSTER_SLOTS = ("P1", "P2", "C", "1B", "2B", "3B", "SS", "OF1", "OF2", "OF3")


def _candidate_ordered_roster(candidate: Dict[str, Any]) -> Tuple[str, ...]:
    """Return the candidate's exact ten-slot roster when available."""
    raw = candidate.get("roster_slot_ids") or candidate.get("slot_assignments")
    if isinstance(raw, dict):
        roster = tuple(str(raw.get(slot, "")).strip() for slot in ENTRY_ROSTER_SLOTS)
    elif raw is not None:
        roster = tuple(str(x).strip() for x in raw)
    elif candidate.get("lineup_ids") is not None:
        roster = tuple(str(x).strip() for x in candidate["lineup_ids"])
    elif candidate.get("roster_ids") is not None:
        roster = tuple(str(x).strip() for x in candidate["roster_ids"])
    elif candidate.get("player_ids") is not None:
        roster = tuple(str(x).strip() for x in candidate["player_ids"])
    else:
        lineup = candidate.get("lineup") or candidate.get("lineup_df")
        if hasattr(lineup, "iterrows"):
            slot_map: Dict[str, str] = {}
            position_buckets: Dict[str, List[str]] = defaultdict(list)
            for _, row in lineup.iterrows():
                pid = str(row.get("Player_ID") or "").strip()
                exact = str(row.get("Assigned_Slot") or "").strip()
                pos = str(row.get("Assigned_Position") or "").strip()
                if exact:
                    slot_map[exact] = pid
                elif pos:
                    position_buckets[pos].append(pid)
            if slot_map:
                roster = tuple(slot_map.get(slot, "") for slot in ENTRY_ROSTER_SLOTS)
            else:
                roster = (
                    *(position_buckets.get("P", [])[:2]),
                    *(position_buckets.get("C", [])[:1]),
                    *(position_buckets.get("1B", [])[:1]),
                    *(position_buckets.get("2B", [])[:1]),
                    *(position_buckets.get("3B", [])[:1]),
                    *(position_buckets.get("SS", [])[:1]),
                    *(position_buckets.get("OF", [])[:3]),
                )
        else:
            roster = tuple()
    if len(roster) != 10 or not all(roster):
        raise ValueError(f"candidate {_candidate_id(candidate, 0)} lacks an ordered ten-slot roster")
    return roster


def _entry_candidate_compatible(candidate: Dict[str, Any], requirement: Dict[str, Any]) -> bool:
    cid = str(candidate.get("candidate_id") or candidate.get("lineup_id") or "")
    allowed = requirement.get("allowed_candidate_ids")
    if allowed is not None and cid not in {str(x) for x in allowed}:
        return False
    roster = _candidate_ordered_roster(candidate)
    locked = requirement.get("locked_slot_assignments") or {}
    for slot, pid in locked.items():
        if slot not in ENTRY_ROSTER_SLOTS or roster[ENTRY_ROSTER_SLOTS.index(slot)] != str(pid):
            return False
    required_players = {str(x) for x in requirement.get("locked_player_ids", [])}
    if not required_players.issubset(set(roster)):
        return False
    excluded_players = {str(x) for x in requirement.get("excluded_player_ids", [])}
    if excluded_players.intersection(roster):
        return False
    excluded_new_teams = {str(x).upper() for x in requirement.get("excluded_new_teams", [])}
    team_by_player = {str(k): str(v).upper() for k, v in (requirement.get("player_team_by_id") or {}).items()}
    if excluded_new_teams:
        for pid in roster:
            if team_by_player.get(pid) in excluded_new_teams and pid not in required_players:
                return False
    return True


def select_and_assign_entries(
    candidates: Sequence[Dict[str, Any]],
    entry_requirements: Sequence[Dict[str, Any]],
    portfolio_controls: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Select one candidate for every exact Entry ID in a single SciPy MILP.

    This is the v2.15 production allocation contract. Entry-level locks and
    candidate compatibility are enforced before solve; no leftover allocation
    step exists.
    """
    candidates = list(candidates)
    entries = [dict(x) for x in entry_requirements]
    controls = dict(portfolio_controls or {})
    if not entries:
        return {
            "passed": True, "assignments": [], "selection_certified": True,
            "allocation_certified": True, "allocation_method": "scipy_milp_entry_level",
            "summary": "No entries requested",
        }
    if not candidates:
        return {
            "passed": False, "assignments": [], "selection_certified": False,
            "allocation_certified": False, "allocation_method": "scipy_milp_entry_level",
            "errors": ["no candidates available"],
        }
    entry_ids = [str(e.get("entry_id") or "") for e in entries]
    if any(not x for x in entry_ids) or len(set(entry_ids)) != len(entry_ids):
        raise ValueError("entry requirements must have unique nonblank entry_id values")

    try:
        import numpy as np
        from scipy.optimize import Bounds, LinearConstraint, milp
        from scipy.sparse import coo_matrix
    except ImportError as exc:  # pragma: no cover
        return {
            "passed": False, "assignments": [], "selection_certified": False,
            "allocation_certified": False, "allocation_method": "unavailable",
            "errors": [str(exc)],
        }

    # F15: excluded_new_teams silently passed every candidate when the team map
    # was missing, while the sibling game-exposure check below fails closed on
    # the same class of missing input. A late-swap entry whose locked game admits
    # no new players is the exact case where failing open puts an illegal lineup
    # in a certified file.
    team_map_errors: List[str] = []
    for e, entry in enumerate(entries):
        if not entry.get("excluded_new_teams"):
            continue
        team_map = {str(k) for k in (entry.get("player_team_by_id") or {})}
        if not team_map:
            team_map_errors.append(
                f"Entry ID {entry_ids[e]} sets excluded_new_teams without "
                f"player_team_by_id; the exclusion cannot be enforced"
            )
    if team_map_errors:
        return {
            "passed": False, "assignments": [], "selection_certified": False,
            "allocation_certified": False, "allocation_method": "scipy_milp_entry_level",
            "errors": team_map_errors,
        }

    E = len(entries)
    all_rosters = [_candidate_ordered_roster(c) for c in candidates]
    full_compatible = [
        [_entry_candidate_compatible(candidates[k], entries[e]) for k in range(len(candidates))]
        for e in range(E)
    ]
    incompatible_entries = [entry_ids[e] for e in range(E) if not any(full_compatible[e])]
    if incompatible_entries:
        return {
            "passed": False, "assignments": [], "selection_certified": False,
            "allocation_certified": False, "allocation_method": "scipy_milp_entry_level",
            "errors": [f"no compatible candidate for Entry ID {x}" for x in incompatible_entries],
        }

    # F13: the pairwise overlap block is K-squared. An unfiltered bank is what
    # pushes this solve into its own time limit, and a time limit here used to
    # read as "infeasible". Prefiltering reduces search effort; it never touches
    # the legal player set, and forced-coverage candidates are kept outright.
    keep_target = max(
        int(controls.get("candidate_prefilter_target")
            or E * DEFAULT_CANDIDATE_PREFILTER_MULTIPLE),
        MIN_CANDIDATE_PREFILTER_FLOOR,
    )
    kept_idx, prefilter_report = _prefilter_candidates(
        candidates, entries, full_compatible, keep_target
    )
    if prefilter_report["applied"]:
        candidates = [candidates[k] for k in kept_idx]
        all_rosters = [all_rosters[k] for k in kept_idx]

    K = len(candidates)
    rosters = all_rosters
    player_sets = [set(r) for r in rosters]
    signatures = [tuple(sorted(r)) for r in rosters]
    pitcher_sets = [set(_candidate_pitcher_ids(c) or rosters[i][:2]) for i, c in enumerate(candidates)]
    sp_pairs = [tuple(sorted(x)) for x in pitcher_sets]
    stacks = [_candidate_primary_stack(c) for c in candidates]
    stack_sizes = [_candidate_primary_stack_size(c) for c in candidates]  # R34
    candidate_ids = [_candidate_id(c, i) for i, c in enumerate(candidates)]
    compatible = [[full_compatible[e][k] for k in kept_idx] for e in range(E)]

    x_count = E * K
    use_y = controls.get("max_shared_players") is not None
    y_offset = x_count
    n_vars = x_count + (K if use_y else 0)
    def x_idx(e: int, k: int) -> int: return e * K + k
    def y_idx(k: int) -> int: return y_offset + k

    objective = np.zeros(n_vars, dtype=float)
    raw_scores: Dict[Tuple[int, int], float] = {}
    for e, entry in enumerate(entries):
        shape = str(entry.get("contest_shape") or "large_wta")
        scores = [_candidate_shape_score(c, shape) for c in candidates]
        lo, hi = min(scores), max(scores)
        for k, score in enumerate(scores):
            raw_scores[(e, k)] = score
            normalized = 50.0 if hi <= lo else 100.0 * (score - lo) / (hi - lo)
            objective[x_idx(e, k)] = -normalized
    reuse_penalty = float(controls.get("reuse_penalty", 2.0))
    if use_y:
        objective[y_offset:] = reuse_penalty * 0.01

    rows: List[Dict[int, float]] = []
    lbs: List[float] = []
    ubs: List[float] = []
    def add(coefs: Dict[int, float], lb: float, ub: float) -> None:
        rows.append(coefs); lbs.append(lb); ubs.append(ub)

    for e in range(E):
        add({x_idx(e, k): 1.0 for k in range(K)}, 1.0, 1.0)

    by_contest_entries: Dict[str, List[int]] = defaultdict(list)
    for e, entry in enumerate(entries):
        by_contest_entries[str(entry.get("contest_id") or "")].append(e)
    sig_groups: Dict[Tuple[str, ...], List[int]] = defaultdict(list)
    for k, sig in enumerate(signatures):
        sig_groups[sig].append(k)
    for contest_id, entry_idxs in by_contest_entries.items():
        if not contest_id:
            continue
        for group in sig_groups.values():
            add({x_idx(e, k): 1.0 for e in entry_idxs for k in group}, -np.inf, 1.0)

    total = E
    max_reuse = controls.get("max_candidate_reuse")
    if max_reuse is not None:
        # Keyed by signature: duplicate candidate objects with identical rosters
        # share one reuse budget instead of each receiving their own.
        for group in sig_groups.values():
            add({x_idx(e, k): 1.0 for e in range(E) for k in group}, -np.inf, int(max_reuse))

    player_cap = _cap_count(total, controls.get("max_player_exposure_pct"))
    pitcher_cap = _cap_count(total, controls.get("max_pitcher_exposure_pct"))
    stack_cap = _cap_count(total, controls.get("max_primary_stack_exposure_pct"))
    pair_cap = controls.get("max_sp_pair_repetition")
    if player_cap:
        for pid in sorted(set().union(*player_sets)):
            add({x_idx(e, k): 1.0 for e in range(E) for k in range(K) if pid in player_sets[k]}, -np.inf, player_cap)
    if pitcher_cap:
        for pid in sorted(set().union(*pitcher_sets)):
            add({x_idx(e, k): 1.0 for e in range(E) for k in range(K) if pid in pitcher_sets[k]}, -np.inf, pitcher_cap)
    if stack_cap:
        for team in sorted({x for x in stacks if x}):
            add({x_idx(e, k): 1.0 for e in range(E) for k in range(K) if stacks[k] == team}, -np.inf, stack_cap)
    if pair_cap is not None:
        for pair in sorted(set(sp_pairs)):
            add({x_idx(e, k): 1.0 for e in range(E) for k in range(K) if sp_pairs[k] == pair}, -np.inf, int(pair_cap))

    # R34: primary-stack SIZE floor. Every other control here is a ceiling, so
    # this is the first row in the joint solve with a lower bound, and the
    # asymmetry matters: a ceiling can always be met by selecting less, a floor
    # cannot be met by selecting at all if the bank has too few qualifying
    # candidates. _slate_feasibility floors the share before it reaches here,
    # and the relaxation ladder owns what happens when it still does not fit.
    five_share = controls.get("min_five_stack_share_pct")
    if five_share:
        min_size = int(controls.get("five_stack_min_size") or 5)
        need = int(math.floor(E * min(1.0, max(0.0, float(five_share))) + 1e-9))
        qualifying = [k for k in range(K) if stack_sizes[k] >= min_size]
        if need > 0:
            if not qualifying:
                return {
                    "passed": False, "assignments": [], "selection_certified": False,
                    "allocation_certified": False,
                    "allocation_method": "scipy_milp_entry_level",
                    "errors": [
                        f"min_five_stack_share_pct {five_share} requires {need} of {E} "
                        f"entries at primary stack size >= {min_size}, and the bank "
                        f"contains 0 such candidates. Raise bank_stack_min_size on the "
                        f"bank build or lower the share; never trim the pool to fit."
                    ],
                }
            add({x_idx(e, k): 1.0 for e in range(E) for k in qualifying}, float(need), np.inf)

    game_caps = dict(controls.get("max_game_exposure_pct_by_game") or {})
    if game_caps:
        game_by_player = {str(k): str(v) for k, v in (controls.get("player_game_by_id") or {}).items()}
        if not game_by_player:
            return {
                "passed": False, "assignments": [], "selection_certified": False,
                "allocation_certified": False, "allocation_method": "scipy_milp_entry_level",
                "errors": ["max_game_exposure_pct_by_game requires controls['player_game_by_id']"],
            }
        candidates_in_game: Dict[str, List[int]] = defaultdict(list)
        for k, pset in enumerate(player_sets):
            for gid in {game_by_player.get(pid) for pid in pset}:
                if gid:
                    candidates_in_game[gid].append(k)
        for gid, pct in sorted(game_caps.items()):
            cap = max(0, int(math.floor(E * min(1.0, max(0.0, float(pct))) + 1e-9)))
            members = candidates_in_game.get(str(gid), [])
            if members:
                add({x_idx(e, k): 1.0 for e in range(E) for k in members}, -np.inf, float(cap))

    if use_y:
        for k in range(K):
            usage = {x_idx(e, k): 1.0 for e in range(E)}
            add({**usage, y_idx(k): -float(E)}, -np.inf, 0.0)
            add({y_idx(k): 1.0, **{x_idx(e, k): -1.0 for e in range(E)}}, -np.inf, 0.0)
        limit = int(controls["max_shared_players"])
        for i in range(K):
            for j in range(i + 1, K):
                if signatures[i] != signatures[j] and len(player_sets[i] & player_sets[j]) > limit:
                    add({y_idx(i): 1.0, y_idx(j): 1.0}, -np.inf, 1.0)

    row_idx: List[int] = []
    col_idx: List[int] = []
    data: List[float] = []
    for r, coefs in enumerate(rows):
        for col, value in coefs.items():
            if value:
                row_idx.append(r); col_idx.append(col); data.append(float(value))
    matrix = coo_matrix((data, (row_idx, col_idx)), shape=(len(rows), n_vars)).tocsr()
    lower = np.zeros(n_vars)
    upper = np.ones(n_vars)
    for e in range(E):
        for k in range(K):
            if not compatible[e][k]:
                upper[x_idx(e, k)] = 0.0
    lb_array = np.array(lbs)
    ub_array = np.array(ubs)
    time_limit_s = float(controls.get("time_limit", 30))
    result = milp(
        c=objective,
        integrality=np.ones(n_vars, dtype=int),
        bounds=Bounds(lower, upper),
        constraints=LinearConstraint(matrix, lb_array, ub_array),
        options={"time_limit": time_limit_s, "disp": False},
    )
    solver_status = str(getattr(result, "message", getattr(result, "status", "unknown")))
    scipy_status = getattr(result, "status", None)
    timed_out = scipy_status == 1
    mip_gap = getattr(result, "mip_gap", None)
    largest_contest = max(
        (len(v) for v in by_contest_entries.values()), default=0
    )
    solver_report = {
        "scipy_status": scipy_status,
        "status": {0: "optimal", 1: "time_limit", 2: "infeasible",
                   3: "unbounded"}.get(scipy_status, "other"),
        "message": solver_status,
        "time_limit_s": time_limit_s,
        "mip_gap": mip_gap,
        "optimality": None,
        "candidate_prefilter": prefilter_report,
    }

    incumbent = None
    if result.x is not None:
        x = np.asarray(result.x, dtype=float)
        rounded = np.round(x)
        if x.size and float(np.max(np.abs(x - rounded))) <= 1e-5:
            lhs = matrix @ rounded
            within_bounds = bool(
                np.all(rounded >= lower - 1e-6) and np.all(rounded <= upper + 1e-6)
            )
            if within_bounds and np.all(lhs >= lb_array - 1e-6) and np.all(lhs <= ub_array + 1e-6):
                incumbent = rounded

    if incumbent is None:
        if timed_out:
            gap = "unknown" if mip_gap is None else f"{float(mip_gap):.4f}"
            errors = [
                f"entry-level joint MILP hit the {time_limit_s}s time limit at gap "
                f"{gap} with no feasible incumbent; this is the clock, not a proven "
                f"infeasibility. Raise controls['time_limit'] or lower "
                f"controls['candidate_prefilter_target'] "
                f"({prefilter_report['candidates_in']} candidates in, "
                f"{prefilter_report['candidates_kept']} solved)"
            ]
        else:
            binding = _diagnose_binding_constraints(
                E, stacks, sp_pairs, signatures, largest_contest, controls
            )
            if binding:
                errors = [f"entry-level joint MILP proven infeasible: {b}" for b in binding]
            else:
                errors = [
                    "entry-level joint MILP proven infeasible: no single control is "
                    "arithmetically binding against this bank, so the interaction of "
                    "the active controls is. Active: "
                    + ", ".join(
                        f"{k}={controls.get(k)}" for k in sorted((
                            "max_player_exposure_pct", "max_pitcher_exposure_pct",
                            "max_primary_stack_exposure_pct", "max_sp_pair_repetition",
                            "max_shared_players", "max_candidate_reuse",
                        )) if controls.get(k) is not None
                    )
                ]
        solver_report["binding_constraints"] = (
            [] if timed_out else _diagnose_binding_constraints(
                E, stacks, sp_pairs, signatures, largest_contest, controls)
        )
        return {
            "passed": False, "assignments": [], "selection_certified": False,
            "allocation_certified": False, "allocation_method": "scipy_milp_entry_level",
            "allocation_solver_status": solver_status,
            "allocation_solver_report": solver_report,
            "errors": errors,
        }

    # A time-limited incumbent satisfies every constraint in the matrix; it is
    # simply not proven optimal. Verified above, accepted here, and named in the
    # result so "time_limited" is never inferred from silence.
    solver_report["optimality"] = "time_limited" if timed_out else "optimal"

    assignments: List[Dict[str, Any]] = []
    for e, entry in enumerate(entries):
        chosen = [k for k in range(K) if incumbent[x_idx(e, k)] > 0.5]
        if len(chosen) != 1:
            return {
                "passed": False, "assignments": [], "selection_certified": False,
                "allocation_certified": False, "allocation_method": "scipy_milp_entry_level",
                "allocation_solver_status": solver_status,
                "allocation_solver_report": solver_report,
                "errors": [f"Entry ID {entry_ids[e]} resolved to {len(chosen)} candidates"],
            }
        k = chosen[0]
        assignments.append({
            "entry_id": entry_ids[e],
            "contest_id": str(entry.get("contest_id") or ""),
            "contest_name": str(entry.get("contest_name") or ""),
            "contest_shape": str(entry.get("contest_shape") or ""),
            "candidate_id": candidate_ids[k],
            "lineup_ids": list(rosters[k]),
            "roster_slot_ids": {slot: pid for slot, pid in zip(ENTRY_ROSTER_SLOTS, rosters[k])},
            "lineup_signature": "|".join(signatures[k]),
            "contest_fit_score": round(raw_scores[(e, k)], 4),
            "primary_stack": stacks[k],
            "primary_stack_size": stack_sizes[k],  # R34
            "sp_ids": list(sp_pairs[k]),
        })
    reuse_counts = Counter(a["candidate_id"] for a in assignments)
    for assignment in assignments:
        assignment["reused_across_contests"] = reuse_counts[assignment["candidate_id"]] > 1
    return {
        "passed": True,
        "assignments": assignments,
        "selection_certified": True,
        "allocation_certified": True,
        "allocation_method": "scipy_milp_entry_level",
        "allocation_solver_status": solver_status,
        "allocation_solver_report": solver_report,
        "allocation_optimality": solver_report["optimality"],
        "warnings": (
            [f"allocation accepted from a time-limited incumbent at gap "
             f"{'unknown' if mip_gap is None else format(float(mip_gap), '.4f')}; "
             f"every constraint verified, optimality not proven"]
            if timed_out else []
        ) + (
            [f"candidate prefilter kept {prefilter_report['candidates_kept']} of "
             f"{prefilter_report['candidates_in']} candidates before the joint MILP"]
            if prefilter_report.get("applied") else []
        ),
        "candidate_reuse_counts": dict(reuse_counts),
        "direct_constraints": {
            "max_player_count": player_cap,
            "max_pitcher_count": pitcher_cap,
            "max_primary_stack_count": stack_cap,
            "max_sp_pair_repetition": pair_cap,
            "max_shared_players": controls.get("max_shared_players"),
            "max_game_exposure_pct_by_game": game_caps or None,
        },
        "summary": f"Entry-level joint MILP assigned {E} exact Entry IDs",
    }


def select_and_assign_portfolio(
    candidates: Sequence[Dict[str, Any]],
    contest_cards: Sequence[ContestCard],
    allocations: Dict[str, int],
    reuse_strategy: str = "balanced",
    **overrides: Any,
) -> Dict[str, Any]:
    """Backward-compatible wrapper over the entry-level MILP."""
    requirements: List[Dict[str, Any]] = []
    total = sum(max(0, int(v)) for v in allocations.values())
    shapes = []
    for card in contest_cards:
        count = max(0, int(allocations.get(card.contest_id, 0)))
        shape = contest_shape_for_card(card)
        if count:
            shapes.append(shape)
        for slot in range(1, count + 1):
            requirements.append({
                "entry_id": f"{card.contest_id}:{slot}",
                "contest_id": card.contest_id,
                "contest_name": card.name,
                "contest_shape": shape,
            })
    controls: Dict[str, Any] = {"reuse_strategy": reuse_strategy}
    tournament = bool(shapes) and all(x not in {"cash", "satellite"} for x in shapes)
    if tournament and total >= 4:
        controls.update({
            "max_player_exposure_pct": 0.45,
            "max_pitcher_exposure_pct": 0.43,
            "max_primary_stack_exposure_pct": 0.35,
            "max_sp_pair_repetition": max(2, int(math.ceil(total * 0.12))),
            "max_shared_players": 5 if total >= 8 else 6,
        })
    controls.update(overrides)
    # Legacy argument is descriptive only in the entry-level implementation.
    controls.pop("right_tail_retention_pct", None)
    return select_and_assign_entries(candidates, requirements, controls)


def reconcile_entries_against_assignments(
    intended_assignments: Sequence[Dict[str, Any]],
    actual_entry_rows: Any,
) -> Dict[str, Any]:
    """Canonical reconciliation delegated to dk_entries_manager.

    ``actual_entry_rows`` must be a DKEntries file path in v1.9. Generic
    DictReader rows are rejected because repeated P/OF headers are unsafe.
    """
    from mlb_engine.entries.dk_entries_manager import reconcile_entries_against_assignments as _reconcile
    if not isinstance(actual_entry_rows, (str, bytes)):
        try:
            from pathlib import Path
            if not isinstance(actual_entry_rows, Path):
                return {
                    "passed": False,
                    "errors": ["actual_entry_rows must be a DKEntries path; generic row dictionaries are unsupported"],
                    "rows": [],
                }
        except Exception:  # pragma: no cover
            pass
    return _reconcile(intended_assignments, actual_entry_rows)
