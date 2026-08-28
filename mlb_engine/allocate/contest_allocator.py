"""
MLB Classic Contest Allocator
VERSION is the authoritative version constant for this module.
Framework patch: MLB Classic v2.16.0 lean joint selection/allocation
Compiled: 2026-06-11 (v1.10 reliability and game-exposure patch)

v1.12 changes (R98(2)): ``select_and_assign_entries`` accepts an advisory
``bank_report``. On a PROVEN-infeasible solve it appends ordered remedies to
``errors``: grow the bank first when ``job_list_exhausted`` is False, and only
then ``--controls-override``, with the structural-floor controls separated from
the exposure caps that have no floor. The solver's own arithmetic is unchanged
and still leads the list.

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
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

# R116. The shape vocabulary, read for one question: is this whole solve cash?
# `contest_shapes` imports nothing from the engine, so this is the acyclic
# direction the module was written for.
from mlb_engine.contest_shapes import OBJECTIVE_CLASS_BY_SHAPE

VERSION = "v1.12"

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
    feasibility_inputs: Optional[Mapping[str, Any]] = None,
) -> List[str]:
    """Name the controls that cannot be satisfied by this bank, arithmetically.

    Every check here is a counting argument on the bank as handed in, not a
    re-solve: buckets times cap has to reach the entry count or no assignment
    exists. It cannot prove infeasibility on its own (the MILP already did
    that), and it never guesses. When it finds nothing it says so, which is
    itself the useful answer: the interaction, not any single cap, is binding.

    ``feasibility_inputs`` (R112) is the slate-level capacity
    (``viable_sp_pairs``/``viable_sp_count`` from ``_slate_feasibility``),
    optional and advisory. When the bank-observed bucket count binding here is
    LOWER than what the slate itself can support, the finding names the bank
    as the true limiter in the same line -- omitting it costs nothing; a bank
    that already matches or exceeds the slate's capacity states no such claim.
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
            finding = (
                f"max_sp_pair_repetition: {buckets} distinct SP pairs x cap "
                f"{int(pair_cap)} = {buckets * int(pair_cap)} < {total} entries"
            )
            viable_pairs = (feasibility_inputs or {}).get("viable_sp_pairs")
            if viable_pairs is not None and int(viable_pairs) > buckets:
                finding += (
                    f" -- BANK-LIMITED: feasibility.inputs.viable_sp_pairs says "
                    f"the slate itself has {int(viable_pairs)} viable SP pairs; "
                    f"this bank sampled only {buckets}, so grow the bank before "
                    f"relaxing this cap"
                )
            findings.append(finding)

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
            finding = (
                f"max_pitcher_exposure_pct: {len(arms)} distinct starters x cap "
                f"{pitcher_cap} = {len(arms) * pitcher_cap} < {total * 2} pitcher slots"
            )
            viable_sps = (feasibility_inputs or {}).get("viable_sp_count")
            if viable_sps is not None and int(viable_sps) > len(arms):
                finding += (
                    f" -- BANK-LIMITED: feasibility.inputs.viable_sp_count says "
                    f"the slate itself has {int(viable_sps)} viable starters; "
                    f"this bank sampled only {len(arms)}, so grow the bank "
                    f"before relaxing this cap"
                )
            findings.append(finding)
    return findings


# R98(2). Controls that reach an ENGINE-NAMED structural floor, versus controls
# that do not have one. The distinction is the whole point: `max_shared_players`
# below the inherent overlap of a stack plus a shared SP pair is arithmetically
# impossible, so raising it to that floor changes nothing about the portfolio --
# no two lineups built on one 5-stack CAN overlap less. An exposure cap has no
# such floor. The engine can compute the minimum value that makes a given build
# feasible, but that number is a consequence of the bank it was handed, not a
# property of the slate, and adopting it concentrates the portfolio. Calling
# both "raise the cap to the named floor" is what taught the 1910_9g operator to
# move three exposure caps from 0.35/0.43 to 0.56 against a bank explored to
# 1.8%.
STRUCTURAL_FLOOR_CONTROLS = frozenset({"max_shared_players", "max_sp_pair_repetition"})
STRATEGY_CAP_CONTROLS = frozenset({
    "max_player_exposure_pct", "max_pitcher_exposure_pct",
    "max_primary_stack_exposure_pct", "max_candidate_reuse",
})

# R116, 2026-08-15. `max_candidate_reuse` sits in STRATEGY_CAP_CONTROLS above
# and the R98(2) warning does NOT generalize to it, which is the whole reason
# this default is safe to promote while the exposure defaults are not. Read the
# direction: an engine-computed floor on an EXPOSURE cap raises a ceiling, which
# lets one player, arm, or stack take more of the portfolio -- it concentrates.
# An engine-computed floor on the REUSE cap is the same arithmetic pointed the
# other way. `ceil(entries / distinct lineups)` is the SMALLEST reuse budget
# that still fits every entry, so adopting it spreads the entries across as many
# distinct lineups as the bank can supply. It de-concentrates. The number is
# still a consequence of the bank rather than a property of the slate; the
# difference is that being wrong about the bank here costs breadth the operator
# can buy back with one override, where being wrong about it there silently
# spends the portfolio on one player.
CASH_OBJECTIVE_CLASS = "cash"


def default_candidate_reuse_cap(entry_total: int, distinct_lineups: int) -> int:
    """The smallest reuse budget that still seats every entry.

    R116. This is the legacy path's `minimum_cap` arithmetic (:1062) promoted
    from a feasibility floor to the production default, keyed on DISTINCT
    LINEUPS rather than candidate objects because the reuse rows are keyed by
    signature: two candidate dicts holding the same roster share one budget.

    Feasibility is by construction, not by hope. `distinct * ceil(total /
    distinct) >= total`, so the reuse rows alone can always seat the file, and a
    round-robin deal over signatures never repeats one inside a contest whose
    entry count is at most `distinct` -- which is the per-contest uniqueness
    rule's own precondition, already diagnosed at :643. One entry returns 1, so
    the `single_entry` posture is untouched.
    """
    total = max(0, int(entry_total))
    distinct = max(1, int(distinct_lineups))
    if total <= 0:
        return 1
    return max(1, int(math.ceil(total / distinct)))


def candidate_reuse_cap_rungs(entry_total: int, distinct_lineups: int) -> List[int]:
    """The engine default's relaxation ladder, tightest first.

    R116. Two rungs and then nothing, deliberately. The all-or-nothing version
    of this fix was written first and the archived 06-03 grid falsified it
    inside one run: 18 entries against 29 distinct lineups defaults to a cap of
    1, that proved infeasible against the production exposure caps on a 4-game
    bank, and dropping straight to no cap handed back exactly the unbounded
    solve the item exists to remove. The measured portfolio there holds 11
    distinct lineups at a max repeat of 2, so rung 2 fits it and rung 1 does
    not -- the middle rung is the difference between a bounded portfolio and
    the status quo reported politely.

    Two and not `log2(n)`: every rung is a full MILP solve and the T-schedule
    prices that. Doubling means the ladder covers 1->2 and 2->4, which is the
    range the 2207_2g and 06-03 evidence both live in, and the third solve is
    the refusal-avoiding drop rather than another guess.

    A rung at or above ``entry_total`` binds nothing -- one signature could take
    every entry -- so it is dropped rather than solved as a duplicate of the
    no-cap solve that follows it.
    """
    total = max(0, int(entry_total))
    first = default_candidate_reuse_cap(total, distinct_lineups)
    rungs: List[int] = []
    for cap in (first, first * 2):
        if total and cap >= total:
            break
        if cap not in rungs:
            rungs.append(int(cap))
    return rungs


def _is_cash_only(entries: Sequence[Mapping[str, Any]]) -> bool:
    """True when every entry in this solve is ranked on the cash objective.

    R116. Cash is the one family that WANTS the same lineup behind every entry:
    the objective is a floor against a fixed cut line, so the second-best lineup
    is strictly worse in every seat and spreading across it buys variance nobody
    asked for. The de-concentration default is therefore skipped when the whole
    solve is cash, and applied whenever a single non-cash entry is present --
    the portfolio is one file and the mixed case is a GPP portfolio that happens
    to carry a cash row.
    """
    shapes = [str(e.get("contest_shape") or "").strip() for e in entries]
    if not shapes or any(not s for s in shapes):
        return False
    return all(
        OBJECTIVE_CLASS_BY_SHAPE.get(s) == CASH_OBJECTIVE_CLASS for s in shapes
    )


def _infeasibility_remedies(
    bank_report: Optional[Mapping[str, Any]],
    binding: Sequence[str],
) -> List[str]:
    """R98(2). The ordered remedies for a PROVEN-infeasible joint allocation.

    A MILP that proves infeasible against a bank whose job list was never
    exhausted has proved a fact about the candidates it was handed, not about
    the slate. Every control this module then names is binding on THAT bank, so
    relaxing one is a strategy change made to fit an infrastructure limit -- the
    move CLAUDE.md's pool rule already forbids one layer down, arriving here
    instead. So bank growth is stated FIRST and ``--controls-override`` second,
    and the two kinds of control are never presented as the same lever.

    Returns [] when there is nothing honest to add: an absent or silent
    ``bank_report`` is not evidence that the bank was complete, and this
    function never guesses which it was.
    """
    lines: List[str] = []
    exhausted = (bank_report or {}).get("job_list_exhausted")
    if exhausted is False:
        attempted = (bank_report or {}).get("jobs_attempted")
        total = (bank_report or {}).get("jobs_total")
        scope = ""
        if attempted is not None and total:
            scope = (f" ({int(attempted)} of {int(total)} jobs attempted, "
                     f"{float(attempted) / float(total) * 100:.1f}%)")
        floored = ""
        if (bank_report or {}).get("budget_floored"):
            floored = (" and its time budget bottomed out on the engine floor "
                       "rather than the requested window")
        lines.append(
            f"FIRST REMEDY, grow the bank: the job list was NOT exhausted{scope}"
            f"{floored}, so this proof is about the candidates that were built, "
            f"not about the slate. Re-run the same build command; it exits 10 and "
            f"resumes into the same cache until the job list is exhausted. Do not "
            f"relax a control against a bank that is still a slice."
        )
    named = {
        control
        for control in (STRUCTURAL_FLOOR_CONTROLS | STRATEGY_CAP_CONTROLS)
        if any(str(b).startswith(f"{control}:") for b in binding)
    }
    structural = sorted(named & STRUCTURAL_FLOOR_CONTROLS)
    strategy = sorted(named & STRATEGY_CAP_CONTROLS)
    if structural or strategy:
        parts = []
        if structural:
            parts.append(
                f"[{', '.join(structural)}] reach an engine-named structural floor, "
                f"so raising to that floor is arithmetic and changes nothing else"
            )
        if strategy:
            parts.append(
                f"[{', '.join(strategy)}] have NO engine-named floor, so any value "
                f"that clears this bank is a portfolio strategy decision and "
                f"concentrates the entered set"
            )
        label = "NEXT REMEDY" if lines else "REMEDY"
        lines.append(
            f"{label}, --controls-override, and the two kinds are not alike: "
            + "; ".join(parts) + "."
        )
    return lines


def _untouchable_cap_conflicts(
    fixed: Mapping[str, Any],
    controls: Mapping[str, Any],
    total: int,
) -> List[str]:
    """R61. Caps the rows this solve CANNOT change have already blown through.

    Decidable from the file before any MILP runs, and deliberately not reported
    as one. A solver infeasibility is a proof about the constraint system the
    solver was handed; this is a fact about rows nobody asked it to touch. No
    assignment of the authorized entries can bring a whole-file count back under
    a cap the untouchable rows already exceed, so there is nothing to prove and
    CLAUDE.md's reserved "proven infeasible: <constraint>" label does not apply.

    It is a refusal and not a relaxation. Widening a portfolio cap because the
    rows behind it happen to be frozen is a strategy change made on the
    operator's behalf, at T-minutes, invisibly -- the move R98(2) closed one
    layer up. The remedies below are ordered accordingly: change the SCOPE
    first (authorizing the offending rows makes them mutable and is not a
    strategy change at all), restate the parent build's own cap second (R29(3):
    a swap that re-derives a tighter cap than the build shipped is the common
    cause), and treat a genuinely new cap value as the strategy decision it is,
    last. Bank growth is NOT offered: the bank is irrelevant to a count the
    untouchable rows carry on their own, and naming it would be the guess
    R98(2) exists to remove.

    ``fixed_count == cap`` is NOT a conflict. It means zero headroom, which is
    an ordinary constraint the solve can satisfy by selecting none of that key.
    """
    lines: List[str] = []
    row_count = int(fixed.get("row_count") or 0)
    checks = (
        ("max_player_exposure_pct", "player", fixed.get("player_counts") or {},
         _cap_count(total, controls.get("max_player_exposure_pct"))),
        ("max_pitcher_exposure_pct", "pitcher", fixed.get("pitcher_counts") or {},
         _cap_count(total, controls.get("max_pitcher_exposure_pct"))),
        ("max_primary_stack_exposure_pct", "primary stack",
         fixed.get("primary_stack_counts") or {},
         _cap_count(total, controls.get("max_primary_stack_exposure_pct"))),
    )
    for control, noun, counts, cap in checks:
        if not cap:
            continue
        for key, count in sorted(counts.items()):
            if int(count) > int(cap):
                lines.append(
                    f"{control}: {noun} {key} already appears in {int(count)} of "
                    f"the {row_count} row(s) this solve cannot change, against a "
                    f"whole-file cap of {cap} at {total} complete rows"
                )
    pair_cap = controls.get("max_sp_pair_repetition")
    if pair_cap is not None:
        for key, count in sorted((fixed.get("sp_pair_counts") or {}).items()):
            if int(count) > int(pair_cap):
                lines.append(
                    f"max_sp_pair_repetition: SP pair {key} "
                    f"already appears in {int(count)} of the {row_count} row(s) "
                    f"this solve cannot change, against a cap of {int(pair_cap)}"
                )
    game_caps = dict(controls.get("max_game_exposure_pct_by_game") or {})
    game_counts = fixed.get("game_counts") or {}
    for gid, pct in sorted(game_caps.items()):
        cap = max(0, int(math.floor(total * min(1.0, max(0.0, float(pct))) + 1e-9)))
        count = int(game_counts.get(str(gid), 0))
        if count > cap:
            lines.append(
                f"max_game_exposure_pct_by_game: game {gid} already appears in "
                f"{count} of the {row_count} row(s) this solve cannot change, "
                f"against a whole-file cap of {cap} at {total} complete rows"
            )
    if lines:
        lines.append(
            "This is not a solver infeasibility and not a bank problem. In "
            "order: (1) authorize the rows holding the excess with --entry-ids "
            "so the solve can change them -- that is a SCOPE change and alters "
            "no strategy; (2) if the parent build itself shipped a looser cap, "
            "restate that value, because a swap re-deriving a tighter cap than "
            "the build is the common cause (R29(3)); (3) only a value neither "
            "the parent nor this slate's floors chose is a portfolio strategy "
            "decision, and it concentrates the entered set."
        )
    return lines


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


def assert_fraction_cap(pct: Any, *, key: Optional[str] = None) -> float:
    """The units rule for a fractional exposure control, in ONE place.

    Returns the value as a float, or raises ``ValueError`` when it is above
    1.0. A value of 0 or below is returned unchanged; callers read that as
    "not set" (a ceiling) or "no quota" (a floor), and neither reading is a
    units slip.

    R167. R71(a) made "both ``_cap_count`` copies" raise instead of clamping,
    and there was a third copy: ``execution_pipeline._feasibility_report``'s
    local one still did ``min(1.0, value)``. So a units slip
    (``max_pitcher_exposure_pct=45``) cleared the checkpoint -- which PRINTED
    ``45 -> cap 10`` as though it had checked something -- and then raised
    uncaught inside ``execute_portfolio``, after the bank had spent minutes,
    leaving the run at status ``building`` with no diagnostics. A rule enforced
    in two of three places is exactly the disagreement it exists to prevent,
    so the rule lives here and the copies call it.

    ``dk_entries_manager._cap_count`` deliberately keeps its own
    implementation: it is the post-export validator, and
    ``test_cap_count_arithmetic_is_floor_and_both_copies_agree`` measures the
    solve side against it. Collapsing that pair into one function would make
    the comparison tautological and retire real coverage.

    R215(b). Two values used to clear this gate and disable a cap anyway, which
    is verbatim the harm the paragraphs above name -- the lost-window class
    arriving THROUGH the checkpoint built to stop it.

    ``float("nan") > 1.0`` is False, so a NaN passed every boundary and died
    later inside ``math.floor(total * value)`` with an unnamed ValueError,
    after the bank had spent. Infinity passes the same way and floors to a cap
    nobody is under.

    ``bool`` is a subclass of ``int``, so ``assert_fraction_cap(True)``
    returned 1.0 in silence: a cap switched off with no name, which is the one
    outcome this function exists to prevent. It is rejected before the
    ``float()`` rather than after, because after it is indistinguishable from
    a legitimate 1.0 (R157's rescue sanity check ships exactly that value).
    """
    named = f"{key} " if key else ""
    if isinstance(pct, bool):
        raise ValueError(
            f"exposure cap {named}{pct!r} is a bool, not a fraction; bool is a "
            f"subclass of int, so this used to coerce to {float(pct)} and "
            f"disable the cap without naming it. Pass the fraction you mean "
            f"(0.45 for 45%), or 0 for 'not set'."
        )
    value = float(pct)
    if not math.isfinite(value):
        raise ValueError(
            f"exposure cap {named}{value!r} is not a finite number; it cleared "
            f"the `> 1.0` test (every comparison against NaN is False) and "
            f"then raised inside math.floor after the bank had spent"
        )
    if value > 1.0:
        raise ValueError(
            f"exposure cap {named}{value!r} is > 1.0; caps are fractions of the "
            f"requested count (0.45 for 45%), not percentages -- a bare 45 "
            f"used to silently disable this cap"
        )
    return value


def _cap_count(total: int, pct: Optional[float]) -> Optional[int]:
    """Resolve a fractional exposure cap (e.g. 0.45) to a count.

    R71(a). This used to clamp ``pct > 1`` to 1.0 rather than reject it, which
    silently DISABLES the cap on a plain units slip: ``max_player_exposure_pct:
    45`` (45 typed for 0.45) clamped to 1.0 and capped nobody. Every legitimate
    cap in this codebase is a fraction in (0, 1]; a value above 1 is not a
    looser cap someone meant, it is the same mistake every time, so it raises
    here instead of the mirrored ``dk_entries_manager._cap_count`` disagreeing
    silently with what the solver actually enforced.

    R167: the units half of that rule moved to ``assert_fraction_cap`` so the
    checkpoint enforces the identical rule this solve does.
    """
    if pct is None:
        return None
    value = assert_fraction_cap(pct)
    if value <= 0:
        return None
    return max(1, int(math.floor(total * value + 1e-9)))


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
            if pid in required_players:
                continue
            team = team_by_player.get(pid)
            # R72(i): fail closed on an UNMAPPED pid. `team_by_player.get(pid)`
            # returns None for a player the map does not cover and
            # `None in excluded_new_teams` is False, so this test used to pass
            # every uncovered player through -- per-player fail-open, while F15's
            # sibling guard below fails closed on the same class of missing input
            # and only when the map is empty ENTIRELY. Partial coverage is the
            # real case: a game missing from the lineups feed leaves its
            # platoon-filled players with no PlayerLineupStatus, hence absent from
            # player_team_by_id, and its team absent from locked_teams. Once a
            # game has locked, "I cannot tell which team this player is on" must
            # not resolve to "admit him".
            if team is None or team in excluded_new_teams:
                return False
    return True


def uncovered_locked_team_players(
    candidates: Sequence[Dict[str, Any]],
    requirement: Dict[str, Any],
) -> List[str]:
    """Roster pids this entry's team map cannot classify, once a game has locked.

    R72(i)'s other half. With the fail-closed test above, an uncovered pid drops
    its candidate silently, and a starved entry would surface as the generic "no
    compatible candidate for Entry ID X" -- which reads as a strategy dead end
    rather than the missing input it is. This names the cause.
    """
    if not requirement.get("excluded_new_teams"):
        return []
    team_by_player = {str(k) for k in (requirement.get("player_team_by_id") or {})}
    required = {str(x) for x in requirement.get("locked_player_ids", [])}
    uncovered = {
        pid
        for candidate in candidates
        for pid in _candidate_ordered_roster(candidate)
        if pid and pid not in team_by_player and pid not in required
    }
    return sorted(uncovered)


# R37 stage 1. The lowest rung the primary-stack floor ladder will step to
# before it switches off entirely. It is optimizer_v3.PRIMARY_STACK_MIN_HITTERS
# by value and not by import, because this module is deliberately not coupled to
# the optimizer at runtime. Below 3 the bucket rule stops reporting a primary
# stack at all, so a "floor of 2" would be a floor on a quantity that is always
# 0 -- it would exclude every candidate while appearing to be the loosest
# setting on the ladder.
PRIMARY_STACK_FLOOR_MIN_RUNG = 3


def primary_stack_floor_rungs(requested: int) -> List[Optional[int]]:
    """The relaxation ladder for a requested primary-stack floor, tightest first.

    ``4 -> [4, 3, None]``. The final ``None`` is the floor switched off, which
    is the truncation-avoiding rung: Showdown relaxes its overlap and captain
    controls before it returns a short bank, for the reason CLAUDE.md states --
    a short bank leaves a blank reserved row and a blank row blocks
    certification. A primary-stack floor that cannot be met has the same two
    outcomes available to it, and the same one is worse.
    """
    top = int(requested)
    if top < PRIMARY_STACK_FLOOR_MIN_RUNG:
        return [None]
    return [n for n in range(top, PRIMARY_STACK_FLOOR_MIN_RUNG - 1, -1)] + [None]


def _resolve_primary_stack_floor(
    candidates: Sequence[Dict[str, Any]],
    full_compatible: Sequence[Sequence[bool]],
    entry_ids: Sequence[str],
    controls: Mapping[str, Any],
    floor_state: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Pick the tightest primary-stack floor this bank can actually carry.

    R37 stage 1, Ben's dated decision of 2026-08-09, accepting DEV's 2026-08-05
    floor-first recommendation. Three tranches of archived contests put
    ``<=3-primary`` negative every time (-2.8pp [-3.8,-1.8] combined, then
    -9.8pp [-18.0,-1.6] on the third), while our own share of that family rose
    7.0% -> 21.5% -> 26.3%. The 2026-08-05 feasibility probe found a 5-primary
    lineup feasible on 100% of stackable teams at every slate width probed and
    a floor of 4 costing 0.00-0.76% of the unconstrained objective, so the floor
    is cheap and the family it removes is the one the archive is firmest about.
    Deterministic construction control and an observed-outcome rationale; never
    a win rate, a probability, or an ROI claim.

    Two things this deliberately is NOT.

    It is not the pool trimming CLAUDE.md forbids. That rule is about reducing
    the legal PLAYER set to fit a COMPUTE limit, invisibly. This reduces the
    candidate set to fit a stated STRATEGY, it is decided before the solve
    rather than discovered during it, and every rung it lands on is named in the
    result. The same distinction the fixed-exposure blocking above already
    draws.

    It is not a hard gate. The ladder steps down one rung at a time and counts
    each step, exactly as the Showdown controls do, because a floor that
    refuses is a floor that leaves a blank reserved row.

    The check at each rung is a NECESSARY condition, not a sufficient one:
    every entry must retain at least one compatible candidate. A rung that
    passes it can still be infeasible against the exposure caps, and that case
    is handled where it becomes visible -- the caller re-enters with the next
    rung after the MILP PROVES infeasibility, never after a timeout.
    """
    state = dict(floor_state or {})
    requested = controls.get("primary_stack_min_size")
    report: Dict[str, Any] = {
        "requested": None,
        "applied": None,
        "status": "not_requested",
        "relaxations": int(state.get("relaxations") or 0),
        "relaxation_steps": list(state.get("relaxation_steps") or []),
        "candidates_in": len(candidates),
        "candidates_eligible": len(candidates),
        "excluded_candidate_idx": [],
        "size_histogram": {},
        "note": "deterministic construction control; observed-outcome rationale, "
                "never a win rate, cash rate, or ROI claim",
    }
    if requested is None:
        return report
    try:
        requested = int(requested)
    except (TypeError, ValueError):
        report["status"] = "unreadable"
        report["requested"] = controls.get("primary_stack_min_size")
        return report
    report["requested"] = requested
    if requested < PRIMARY_STACK_FLOOR_MIN_RUNG:
        # 0 is what the floor merge writes when one posture in the portfolio
        # never declared the control, and it means no opinion rather than a
        # floor of zero. Distinct from `relaxed_off`, which is a floor that was
        # asked for and could not be carried.
        report["status"] = "off"
        return report

    sizes = [_candidate_primary_stack_size(c) for c in candidates]
    histogram: Dict[str, int] = {}
    for size in sizes:
        key = str(int(size))
        histogram[key] = histogram.get(key, 0) + 1
    report["size_histogram"] = dict(sorted(histogram.items(), key=lambda kv: int(kv[0])))

    # The bank cannot be read, so it is not enforced against. A Classic bank in
    # which NOT ONE candidate has three hitters on any team is not a bank of
    # stackless lineups, it is a bank whose primary_stack_size field never got
    # written -- which is precisely what bank_cache.as_candidates did before
    # R37. Excluding every candidate on the strength of a missing field is the
    # worst available reading, so this says so instead.
    if candidates and not any(int(s) > 0 for s in sizes):
        report["status"] = "unmeasurable"
        report["note"] = (
            "no candidate in this bank reports a primary_stack_size, so the floor "
            "was NOT enforced. A bank of genuinely stackless lineups is not a "
            "realistic Classic bank; the likelier reading is that the candidate "
            "payloads omit the field. Fix the producer rather than lowering the "
            "floor"
        )
        return report

    rungs = primary_stack_floor_rungs(requested)
    start = int(state.get("rung_index") or 0)
    entry_count = len(entry_ids)
    for idx in range(start, len(rungs)):
        rung = rungs[idx]
        report["rung_index"] = idx
        if rung is None:
            report["applied"] = None
            report["status"] = "relaxed_off"
            report["candidates_eligible"] = len(candidates)
            report["excluded_candidate_idx"] = []
            return report
        eligible = [k for k, size in enumerate(sizes) if int(size) >= rung]
        eligible_set = set(eligible)
        starved = [
            entry_ids[e]
            for e in range(entry_count)
            if not any(full_compatible[e][k] for k in eligible_set)
        ]
        if starved:
            report["relaxations"] += 1
            report["relaxation_steps"].append({
                "from": rung,
                "to": rungs[idx + 1],
                "reason": (
                    f"{len(starved)} entry/entries retain no compatible candidate at "
                    f"primary stack size >= {rung} "
                    f"(first: {', '.join(starved[:3])}"
                    f"{' ...' if len(starved) > 3 else ''})"
                ),
                "trigger": "entry_starved_before_solve",
            })
            continue
        report["applied"] = rung
        report["status"] = "applied" if rung == requested else "applied_relaxed"
        report["candidates_eligible"] = len(eligible)
        report["excluded_candidate_idx"] = [k for k in range(len(candidates))
                                            if k not in eligible_set]
        return report
    return report


def select_and_assign_entries(
    candidates: Sequence[Dict[str, Any]],
    entry_requirements: Sequence[Dict[str, Any]],
    portfolio_controls: Optional[Dict[str, Any]] = None,
    *,
    bank_report: Optional[Mapping[str, Any]] = None,
    fixed_exposure: Optional[Mapping[str, Any]] = None,
    feasibility_inputs: Optional[Mapping[str, Any]] = None,
    _floor_state: Optional[Mapping[str, Any]] = None,
    _reuse_state: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Select one candidate for every exact Entry ID in a single SciPy MILP.

    This is the v2.15 production allocation contract. Entry-level locks and
    candidate compatibility are enforced before solve; no leftover allocation
    step exists.

    ``bank_report`` (R98(2), v1.12) is the caller's bank-construction record --
    ``bank_cache.extend_bank``'s return, or the merged ``bank_diagnostics`` the
    pipeline assembles. It is advisory and read on ONE path only: when the MILP
    proves infeasible, ``job_list_exhausted is False`` means this refusal is a
    fact about a partial search, and the remedy the caller is told to reach for
    changes accordingly. Omitting it costs nothing and asserts nothing; the
    allocator never infers a complete bank from a missing report.

    ``fixed_exposure`` (R61, v1.13) is
    :func:`dk_entries_manager.fixed_portfolio_exposure`'s return: what the rows
    this solve cannot touch already hold. Supplying it makes this solve the
    whole-file problem the export validator is going to grade -- the denominator
    widens by ``row_count``, every cap row loses the count already fixed, the
    untouchable signatures are pre-seeded into the same-contest duplicate rule,
    and a candidate overlapping an untouchable roster past
    ``max_shared_players`` is not selectable. Seven controls shared that
    asymmetry, not the one the item was filed on.

    It defaults to ABSENT and absent means byte-identical to v1.12 on every
    path: ``total`` stays ``E``, no bound moves and no row is added. The initial
    build is deliberately left alone (the R28 precedent), because on a build
    from a blank template the authorized set and the complete-row set are the
    same set and there is nothing to offset.

    ``controls['primary_stack_min_size']`` (R37 stage 1, v1.14) is the smallest
    primary stack a selected candidate may carry. It is the first LOWER bound
    among the per-candidate controls, it relaxes one rung at a time and counts
    every step (see :func:`_resolve_primary_stack_floor`), and it is reported
    under ``primary_stack_floor``. Absent means absent: no candidate is
    excluded and the result carries no floor block.

    ``feasibility_inputs`` (R112) is ``_slate_feasibility``'s return: the
    slate's viable SP count/pairs, independent of what this bank happened to
    sample. Advisory and read on the same proven-infeasible path as
    ``bank_report``: it lets a binding-constraint finding name the bank as the
    limiter when the slate itself could support more than this bank sampled.
    Omitting it costs nothing.

    ``controls['max_candidate_reuse']`` (R116, v1.15) is how many entries may
    share one lineup SIGNATURE across the whole file. Absent, it now DEFAULTS to
    :func:`default_candidate_reuse_cap` rather than to no row at all, on every
    portfolio that is not entirely cash. An explicit value still wins verbatim,
    including an explicit value looser than the default, and the result names
    which of the two it used under ``candidate_reuse.cap_source``.

    ``_floor_state`` and ``_reuse_state`` are private. They carry the ladder
    position, the relaxation record, and the dropped-default flag across the
    re-entries this function makes into itself after the MILP PROVES the
    corresponding control infeasible. Never pass either from outside.
    """
    candidates = list(candidates)
    # Kept whole for the floor re-entry below: `candidates` is rebound by the
    # prefilter, and re-entering with a prefiltered bank would relax the floor
    # against a bank that is not the one the caller handed us.
    _all_candidates = list(candidates)
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

    # R61. The whole-file problem, when the caller has told us what the rest of
    # the file holds. `total` is the denominator every exposure cap resolves
    # against, and it has to be the same number the export validator uses or a
    # legal swap dies at the gate closest to lock.
    fixed = dict(fixed_exposure or {})
    fixed_rows = max(0, int(fixed.get("row_count") or 0))
    total = E + fixed_rows
    # ONE gate. Every offset below reads these four dicts, and they stay empty
    # unless there is at least one untouchable row -- because `row_count` and the
    # counts are derived from the same rows by `fixed_portfolio_exposure`, so
    # counts arriving with a row_count of 0 are a contradiction, and the only
    # honest reading of "no untouchable rows" is that nothing is fixed. Reading
    # the counts on their own let a stray dict silently spend headroom while the
    # conflict check above was skipped: an invisible cap change, which is the
    # defect this whole item exists to remove.
    fixed_players: Dict[str, int] = {}
    fixed_pitchers: Dict[str, int] = {}
    fixed_stacks: Dict[str, int] = {}
    fixed_pairs: Dict[str, int] = {}
    if fixed_rows:
        fixed_players = {str(k): int(v) for k, v in (fixed.get("player_counts") or {}).items()}
        fixed_pitchers = {str(k): int(v) for k, v in (fixed.get("pitcher_counts") or {}).items()}
        fixed_stacks = {str(k): int(v) for k, v in (fixed.get("primary_stack_counts") or {}).items()}
        fixed_pairs = {str(k): int(v) for k, v in (fixed.get("sp_pair_counts") or {}).items()}
        conflicts = _untouchable_cap_conflicts(fixed, controls, total)
        if conflicts:
            return {
                "passed": False, "assignments": [], "selection_certified": False,
                "allocation_certified": False,
                "allocation_method": "scipy_milp_entry_level",
                "refusal": "untouchable_rows_exceed_cap",
                "errors": conflicts,
                "fixed_exposure_rows": fixed_rows,
            }

    all_rosters = [_candidate_ordered_roster(c) for c in candidates]
    full_compatible = [
        [_entry_candidate_compatible(candidates[k], entries[e]) for k in range(len(candidates))]
        for e in range(E)
    ]
    incompatible_entries = [entry_ids[e] for e in range(E) if not any(full_compatible[e])]
    if incompatible_entries:
        # R72(i): say WHY where the cause is a missing input rather than a
        # strategy dead end. An entry whose game has locked and whose team map
        # does not cover the bank's players now starves by design (fail closed),
        # and without this the operator reads it as "the bank admits nothing".
        errors = []
        for e in range(E):
            if any(full_compatible[e]):
                continue
            message = f"no compatible candidate for Entry ID {entry_ids[e]}"
            uncovered = uncovered_locked_team_players(candidates, entries[e])
            if uncovered:
                message += (
                    f"; {len(uncovered)} bank player(s) are absent from this "
                    f"entry's player_team_by_id while excluded_new_teams is set "
                    f"({', '.join(uncovered[:8])}"
                    f"{' ...' if len(uncovered) > 8 else ''}), so their locked-game "
                    f"membership is undecidable and they are excluded rather than "
                    f"admitted. Refresh the lineups feed so every game is covered"
                )
            errors.append(message)
        return {
            "passed": False, "assignments": [], "selection_certified": False,
            "allocation_certified": False, "allocation_method": "scipy_milp_entry_level",
            "errors": errors,
        }

    # R61. Two of the seven asymmetries are not caps and cannot be offset by
    # arithmetic: the same-contest duplicate rule and max_shared_players are
    # PAIRWISE, and the pairs the solve never formed are the ones crossing into
    # the untouchable rows. A candidate that duplicates an untouched row of its
    # own contest, or overlaps one past the limit, is unselectable here for the
    # same reason the validator will reject it there. This enforces a control the
    # export gate already enforces; it is not the pool trimming CLAUDE.md
    # forbids, which is a reduction made to fit a COMPUTE limit and invisible in
    # the output. Every exclusion below is named in `fixed_exposure_report`.
    fixed_blocked_overlap: List[int] = []
    fixed_blocked_signature: List[Tuple[str, int]] = []
    if fixed_rows:
        candidate_sigs = [tuple(sorted(r)) for r in all_rosters]
        untouchable = [tuple(str(p) for p in r) for r in (fixed.get("rosters") or [])]
        untouchable_sigs = [tuple(sorted(r)) for r in untouchable]
        overlap_limit = controls.get("max_shared_players")
        if overlap_limit is not None and untouchable:
            limit = int(overlap_limit)
            u_sets = [set(r) for r in untouchable]
            for k in range(len(candidates)):
                k_set = set(all_rosters[k])
                for u_idx, u_set in enumerate(u_sets):
                    # Same exemption the validator applies: an identical roster
                    # is approved reuse of one candidate, not an overlap.
                    if candidate_sigs[k] == untouchable_sigs[u_idx]:
                        continue
                    if len(k_set & u_set) > limit:
                        fixed_blocked_overlap.append(k)
                        for e in range(E):
                            full_compatible[e][k] = False
                        break
        taken = {
            str(cid): {tuple(sorted(str(p) for p in sig)) for sig in sigs}
            for cid, sigs in (fixed.get("signatures_by_contest") or {}).items()
        }
        if taken:
            for e, entry in enumerate(entries):
                occupied = taken.get(str(entry.get("contest_id") or ""))
                if not occupied:
                    continue
                for k in range(len(candidates)):
                    if full_compatible[e][k] and candidate_sigs[k] in occupied:
                        full_compatible[e][k] = False
                        fixed_blocked_signature.append((entry_ids[e], k))
        starved = [entry_ids[e] for e in range(E) if not any(full_compatible[e])]
        if starved:
            return {
                "passed": False, "assignments": [], "selection_certified": False,
                "allocation_certified": False,
                "allocation_method": "scipy_milp_entry_level",
                "refusal": "untouchable_rows_starve_entry",
                "errors": [
                    f"Entry ID {eid}: every compatible candidate is ruled out by "
                    f"the {fixed_rows} row(s) this solve cannot change -- either "
                    f"it duplicates one of their rosters in the same contest, or "
                    f"it shares more than max_shared_players="
                    f"{controls.get('max_shared_players')} with one of them. This "
                    f"is a portfolio control against the untouchable rows, NOT "
                    f"this entry's pins and not a thin bank. Grow the bank only "
                    f"if you want more DISTINCT shapes; authorizing the "
                    f"conflicting rows with --entry-ids removes the conflict "
                    f"outright."
                    for eid in starved
                ],
                "fixed_exposure_rows": fixed_rows,
            }

    # R37 stage 1. The primary-stack floor is applied HERE: after entry
    # compatibility and the untouchable-row blocking, so the starvation check
    # sees the real compatible set, and before the prefilter, so the prefilter
    # spends its keep-target on candidates that can actually be selected rather
    # than discarding eligible ones in favour of ineligible ones.
    floor_report = _resolve_primary_stack_floor(
        candidates, full_compatible, entry_ids, controls, _floor_state
    )
    if floor_report.get("applied") is not None:
        for k in floor_report["excluded_candidate_idx"]:
            for e in range(E):
                full_compatible[e][k] = False

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
    # R36 F11: the joint objective carries NO reuse term. Every nonzero
    # coefficient is an x term and every x term is a negated shape score in
    # [-100, 0]; the y block stays at 0.0. The removed
    # `objective[y_offset:] = reuse_penalty * 0.01` put a POSITIVE cost on each
    # DISTINCT used candidate under minimization, so it rewarded concentration,
    # the opposite of the parameter's name. It was also redundant: `use_y` is
    # true only when `max_shared_players` is set, so the soft nudge was live
    # only where the hard overlap cap already enforced diversity. y_k exists to
    # carry the overlap rows (:1721-1730) and nothing else. Diversity is
    # governed by max_shared_players and max_candidate_reuse alone.
    control_warnings: List[str] = []
    if "reuse_penalty" in controls:
        # Not fatal, and deliberately not an error dict: the checkpoint reports
        # an allocator refusal as `proven_infeasible`, and a dead control key is
        # not an infeasible constraint system. Naming it here keeps it out of
        # silence without mislabeling it. `reuse_penalty` survives only as the
        # correctly-signed excess-variable coefficient on the legacy
        # `assign_lineups_to_contests` path (:797-800), where it is a function
        # parameter and not a controls key.
        control_warnings.append(
            "reuse_penalty was supplied and is IGNORED: it is not a "
            "joint-allocator control. The term it used to set rewarded reuse "
            "rather than penalising it (R36 Finding 11) and is removed. "
            "Overlap diversity is set by max_shared_players and "
            "max_candidate_reuse."
        )

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

    # R61: `total` is E plus the untouchable complete rows, set above. It was
    # `total = E` here, which is the file's denominator only when the solve was
    # handed every complete row -- true on an initial build, false on every
    # scoped or partly-locked swap.
    #
    # R116, 2026-08-15. Until this landed the production MILP added NO reuse row
    # unless an operator typed the control, `STRATEGY_DEFAULTS` set it on no
    # posture, and nothing outside tests passed one -- so the solver legitimately
    # spent the whole file on its few best candidates. The first certified
    # 2207_2g build put 4 distinct lineups across 11 apex entries; the rebuild
    # with the cap at 2 delivered 7 distinct for 0.98% of aggregate fit. The
    # default below is that rebuild's number, derived rather than typed.
    #
    # `cap_source` is the honesty half. An operator value is used verbatim and
    # never recomputed, an engine value is labelled as engine-computed wherever
    # it is reported, and only an engine value is droppable by the relaxation
    # below -- an operator who typed a cap gets a refusal naming it, not a
    # quietly widened portfolio.
    distinct_lineup_count = len(sig_groups)
    reuse_cap_source = "operator" if controls.get("max_candidate_reuse") is not None else None
    reuse_cap_skipped: Optional[str] = None
    reuse_rungs = candidate_reuse_cap_rungs(total, distinct_lineup_count)
    reuse_rung_index = int((_reuse_state or {}).get("rung_index") or 0)
    if reuse_cap_source is None:
        if _is_cash_only(entries):
            reuse_cap_skipped = "cash_only_portfolio"
        elif reuse_rung_index >= len(reuse_rungs):
            # Off the end of the ladder: every rung was proven infeasible and
            # the solve runs unbounded, which is pre-R116 behaviour reached
            # deliberately and counted rather than by never having tried.
            reuse_cap_skipped = "engine_default_exhausted"
        else:
            controls["max_candidate_reuse"] = reuse_rungs[reuse_rung_index]
            reuse_cap_source = "engine_default"
    max_reuse = controls.get("max_candidate_reuse")
    if max_reuse is not None:
        # Keyed by signature: duplicate candidate objects with identical rosters
        # share one reuse budget instead of each receiving their own.
        for group in sig_groups.values():
            add({x_idx(e, k): 1.0 for e in range(E) for k in group}, -np.inf, int(max_reuse))
    # Known before the solve, so it rides the REFUSAL as well as the delivery.
    # A refusal that does not state which reuse cap was active, and how many
    # rungs the engine already spent getting there, reads as a fact about the
    # slate when it is a fact about the engine's own last guess.
    reuse_state_report: Dict[str, Any] = {
        "entries": E,
        "entry_denominator": total,
        "distinct_lineups_available": distinct_lineup_count,
        "cap_applied": int(max_reuse) if max_reuse is not None else None,
        "cap_source": reuse_cap_source or "none",
        "cap_skipped_reason": reuse_cap_skipped,
        "engine_default_rungs": list(reuse_rungs),
        "relaxations": len(list((_reuse_state or {}).get("relaxation_steps") or [])),
        "relaxation_steps": list((_reuse_state or {}).get("relaxation_steps") or []),
    }

    # R61: headroom, not the raw cap. A key already sitting in the untouchable
    # rows spends the cap before this solve chooses anything, and
    # _untouchable_cap_conflicts has already refused the case where it has
    # overspent it, so every value here is >= 0 by construction. The four dicts
    # are empty unless offsets were supplied, so this is a no-op without them.
    def headroom(cap: int, already: int) -> float:
        return float(max(0, int(cap) - int(already)))

    player_cap = _cap_count(total, controls.get("max_player_exposure_pct"))
    pitcher_cap = _cap_count(total, controls.get("max_pitcher_exposure_pct"))
    stack_cap = _cap_count(total, controls.get("max_primary_stack_exposure_pct"))
    pair_cap = controls.get("max_sp_pair_repetition")
    if player_cap:
        for pid in sorted(set().union(*player_sets)):
            add({x_idx(e, k): 1.0 for e in range(E) for k in range(K) if pid in player_sets[k]},
                -np.inf, headroom(player_cap, fixed_players.get(pid, 0)))
    if pitcher_cap:
        for pid in sorted(set().union(*pitcher_sets)):
            add({x_idx(e, k): 1.0 for e in range(E) for k in range(K) if pid in pitcher_sets[k]},
                -np.inf, headroom(pitcher_cap, fixed_pitchers.get(pid, 0)))
    if stack_cap:
        for team in sorted({x for x in stacks if x}):
            add({x_idx(e, k): 1.0 for e in range(E) for k in range(K) if stacks[k] == team},
                -np.inf, headroom(stack_cap, fixed_stacks.get(team, 0)))
    if pair_cap is not None:
        for pair in sorted(set(sp_pairs)):
            add({x_idx(e, k): 1.0 for e in range(E) for k in range(K) if sp_pairs[k] == pair},
                -np.inf, headroom(int(pair_cap), fixed_pairs.get("/".join(pair), 0)))

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
        fixed_games = ({str(k): int(v) for k, v in (fixed.get("game_counts") or {}).items()}
                       if fixed_rows else {})
        for gid, pct in sorted(game_caps.items()):
            # R61: `total`, not E, and minus what the untouchable rows hold. This
            # cap floors at 0 rather than 1 (_game_cap_count's contract: an
            # explicit pct of 0 means zero), so headroom() is the same shape.
            cap = max(0, int(math.floor(total * min(1.0, max(0.0, float(pct))) + 1e-9)))
            members = candidates_in_game.get(str(gid), [])
            if members:
                add({x_idx(e, k): 1.0 for e in range(E) for k in members},
                    -np.inf, headroom(cap, fixed_games.get(str(gid), 0)))

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
                E, stacks, sp_pairs, signatures, largest_contest, controls,
                feasibility_inputs=feasibility_inputs,
            )
            # R112 rider (2026-08-14). This flag rides EVERY finding line below,
            # not only a remedy trailing the whole list: two separate blocked
            # runs against the same still-slicing bank (20260813T162123Z /
            # 162422Z) each showed a different bank-observed count as if it
            # were a fresh diagnosis of the SLATE, and a reader who only sees
            # errors[0] (the T-5 "present with zero diagnostic narration" case)
            # would never reach the trailing remedy that explains why.
            bank_flag = (
                " [BANK JOB LIST NOT EXHAUSTED -- see remedies below before "
                "relaxing any control]"
                if (bank_report or {}).get("job_list_exhausted") is False else ""
            )
            if binding:
                errors = [f"entry-level joint MILP proven infeasible: {b}{bank_flag}"
                          for b in binding]
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
                    ) + bank_flag
                ]
            # R98(2). Appended, never substituted: the arithmetic above is what
            # the solver proved and it stays first among the facts. What follows
            # is what to DO about it, and the order matters more than the words
            # -- on 1910_9g both lines above were true and the operator still
            # reached for the wrong lever, because nothing said the bank was
            # 1.8% explored.
            errors = errors + _infeasibility_remedies(bank_report, binding)

        # R116. The engine's own default goes FIRST, before the floor ladder
        # steps and before the refusal is written. The ordering is the point: a
        # primary-stack floor is a strategy control Ben decided on archive
        # evidence, and the reuse cap here is a number this function computed
        # thirty lines ago from the bank it happened to be handed. Relaxing the
        # engine's guess before anyone's decision is the only order that keeps
        # "the default de-concentrates" from turning into "the default cost you
        # the delivery". The same two rules the floor ladder follows apply: never
        # on a timeout, and the step is COUNTED, never silent.
        if (not timed_out) and reuse_cap_source == "engine_default":
            next_rung = (reuse_rungs[reuse_rung_index + 1]
                         if reuse_rung_index + 1 < len(reuse_rungs) else None)
            return select_and_assign_entries(
                _all_candidates, entry_requirements, portfolio_controls,
                bank_report=bank_report, fixed_exposure=fixed_exposure,
                feasibility_inputs=feasibility_inputs,
                _floor_state=_floor_state,
                _reuse_state={
                    "rung_index": reuse_rung_index + 1,
                    "relaxation_steps": list((_reuse_state or {}).get("relaxation_steps") or []) + [{
                        "from": int(max_reuse) if max_reuse is not None else None,
                        "to": next_rung,
                        "reason": (
                            "entry-level joint MILP proven infeasible with the "
                            "ENGINE-DEFAULTED candidate-reuse cap active; the "
                            "engine's own default steps before any control the "
                            "operator or a posture chose"
                        ),
                        "trigger": "proven_infeasible_with_engine_default_reuse_cap",
                    }],
                },
            )

        # R37. The one re-entry. A PROVEN infeasibility with the floor active is
        # the case the ladder exists for, and relaxing beats refusing because a
        # refusal here leaves every reserved row blank. Never on a timeout: the
        # rule that a compute limit may not move a strategy control is the same
        # rule that stops a slow solve from quietly buying a looser portfolio,
        # and it is the rule the DU ladder already follows two modules over.
        if (not timed_out) and floor_report.get("applied") is not None:
            ladder = primary_stack_floor_rungs(int(floor_report["requested"]))
            rung_idx = int(floor_report.get("rung_index") or 0)
            if rung_idx + 1 < len(ladder):
                stepped = list(floor_report.get("relaxation_steps") or [])
                stepped.append({
                    "from": floor_report["applied"],
                    "to": ladder[rung_idx + 1],
                    "reason": (
                        "entry-level joint MILP proven infeasible with the primary-"
                        "stack floor active; the floor is one of the controls whose "
                        "interaction the solver could not satisfy"
                    ),
                    "trigger": "proven_infeasible_with_floor",
                })
                return select_and_assign_entries(
                    _all_candidates, entry_requirements, portfolio_controls,
                    bank_report=bank_report, fixed_exposure=fixed_exposure,
                    feasibility_inputs=feasibility_inputs,
                    # R116: the reuse state rides the floor's re-entry too, or a
                    # ladder step would silently re-add the default this solve
                    # already proved infeasible and buy an extra round trip per
                    # rung.
                    _reuse_state=_reuse_state,
                    _floor_state={
                        "rung_index": rung_idx + 1,
                        "relaxations": int(floor_report.get("relaxations") or 0) + 1,
                        "relaxation_steps": stepped,
                    },
                )

        solver_report["binding_constraints"] = (
            [] if timed_out else _diagnose_binding_constraints(
                E, stacks, sp_pairs, signatures, largest_contest, controls,
                feasibility_inputs=feasibility_inputs)
        )
        return {
            "passed": False, "assignments": [], "selection_certified": False,
            "allocation_certified": False, "allocation_method": "scipy_milp_entry_level",
            "allocation_solver_status": solver_status,
            "allocation_solver_report": solver_report,
            "errors": errors,
            "candidate_reuse": dict(reuse_state_report),
            **({"primary_stack_floor": floor_report}
               if floor_report.get("status") != "not_requested" else {}),
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
    # R116. What the DELIVERED set actually holds, counted off the assignments
    # rather than asserted from the constraint, on the R37 precedent. The cap is
    # a claim about the output, so the output is where it gets checked.
    # `distinct_lineups` is counted on the SIGNATURE, not the candidate id: two
    # candidate objects carrying the same nine hitters and two arms are one
    # lineup to DraftKings and to the field, and counting ids would report a
    # diversified portfolio that duplicates on upload.
    assigned_signatures = Counter(a["lineup_signature"] for a in assignments)
    reuse_block: Dict[str, Any] = {"candidate_reuse": {
        **reuse_state_report,
        "distinct_lineups": len(assigned_signatures),
        "max_signature_repeat": max(assigned_signatures.values()) if assigned_signatures else 0,
    }}
    reuse_warnings: List[str] = []
    if reuse_block["candidate_reuse"]["relaxations"]:
        _n_distinct = len(assigned_signatures)
        reuse_warnings.append(
            f"max_candidate_reuse: the engine-computed default relaxed "
            f"{reuse_block['candidate_reuse']['relaxations']} time(s) after the joint "
            f"MILP proved it infeasible against this bank, landing on "
            f"{reuse_block['candidate_reuse']['cap_applied'] if max_reuse is not None else 'no cap'}"
            f". The delivered set holds {_n_distinct} distinct lineup"
            f"{'' if _n_distinct == 1 else 's'} across {E} entries, with one lineup used "
            f"{max(assigned_signatures.values())} time(s). A portfolio is not clean "
            f"because the gates passed; it is clean when the relaxation counts are zero"
        )
    # R61. Added to the result ONLY when offsets were supplied, so a build that
    # passes no `fixed_exposure` gets a result dict with exactly the v1.12 keys.
    # That is what makes "byte-identical when absent" checkable rather than
    # asserted, and it is why test_golden_replay's frozen payloads did not move.
    fixed_report: Dict[str, Any] = {}
    if fixed_rows:
        fixed_report = {"fixed_exposure_report": {
            "untouchable_row_count": fixed_rows,
            "solve_entry_count": E,
            "entry_denominator": total,
            "caps_resolved_against": total,
            "candidates_blocked_by_untouchable_overlap":
                sorted({candidate_ids[k] for k in set(fixed_blocked_overlap)
                        if k < len(candidate_ids)}),
            "entry_candidate_pairs_blocked_by_untouchable_signature":
                len(fixed_blocked_signature),
            "headroom_reduced_keys": {
                "max_player_exposure_pct": sorted(
                    pid for pid in fixed_players
                    if player_cap and fixed_players[pid] > 0),
                "max_pitcher_exposure_pct": sorted(
                    pid for pid in fixed_pitchers
                    if pitcher_cap and fixed_pitchers[pid] > 0),
                "max_primary_stack_exposure_pct": sorted(
                    team for team in fixed_stacks
                    if stack_cap and fixed_stacks[team] > 0),
                "max_sp_pair_repetition": sorted(
                    pair for pair in fixed_pairs
                    if pair_cap is not None and fixed_pairs[pair] > 0),
            },
        }}
    # R37. What the delivered set actually holds, counted from the assignments
    # rather than asserted from the constraint. The floor is a claim about the
    # output, so the output is where it gets checked; `below_requested` is 0 on
    # a clean portfolio and nonzero exactly when the ladder stepped.
    floor_block: Dict[str, Any] = {}
    if floor_report.get("status") != "not_requested":
        assigned_sizes = [int(a.get("primary_stack_size") or 0) for a in assignments]
        requested_floor = floor_report.get("requested")
        floor_block = {"primary_stack_floor": {
            **{k: v for k, v in floor_report.items()
               if k not in ("excluded_candidate_idx",)},
            "candidates_excluded": len(floor_report.get("excluded_candidate_idx") or []),
            "assigned_size_histogram": dict(sorted(
                Counter(str(s) for s in assigned_sizes).items(),
                key=lambda kv: int(kv[0]),
            )),
            "assigned_below_requested": (
                sum(1 for s in assigned_sizes if s < int(requested_floor))
                if isinstance(requested_floor, int) else None
            ),
        }}

    floor_warnings: List[str] = []
    _fr = floor_block.get("primary_stack_floor") if floor_block else None
    if _fr:
        if _fr.get("relaxations"):
            floor_warnings.append(
                f"primary_stack_min_size relaxed {_fr['relaxations']} time(s): "
                f"requested {_fr['requested']}, applied "
                f"{_fr['applied'] if _fr['applied'] is not None else 'none'}. "
                f"A portfolio is not clean because the gates passed; it is clean "
                f"when the relaxation counts are zero"
            )
        if _fr.get("status") == "unmeasurable":
            floor_warnings.append(
                "primary_stack_min_size was requested but NOT enforced: no candidate "
                "in this bank reports a primary_stack_size. The producer of these "
                "payloads is the thing to fix"
            )

    return {
        **fixed_report,
        **floor_block,
        **reuse_block,
        "passed": True,
        "assignments": assignments,
        "selection_certified": True,
        "allocation_certified": True,
        "allocation_method": "scipy_milp_entry_level",
        "allocation_solver_status": solver_status,
        "allocation_solver_report": solver_report,
        "allocation_optimality": solver_report["optimality"],
        "warnings": control_warnings + floor_warnings + reuse_warnings + (
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
            # R116: the resolved value, default included. This block is what a
            # reader consults to answer "what actually constrained this solve",
            # and the one control that could now be set by the engine rather
            # than the caller was the one control missing from it.
            "max_candidate_reuse": int(max_reuse) if max_reuse is not None else None,
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
