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
from typing import (Any, Dict, FrozenSet, Iterable, List, Mapping, Optional,
                    Sequence, Tuple)

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


#: R343. How many hitters from one team make an ENTRY exposed to that team for
#: ``max_team_exposure_pct``. Two, not one, and the reason is arithmetic rather
#: than taste: a DK Classic lineup holds eight hitters and at most five from one
#: team, so every entry touches at least two teams and usually four or five. At
#: a threshold of one, a team's footprint on a three-game slate is near 1.0 for
#: every team by construction, and a cap over it would bind on ordinary builds
#: while measuring nothing. Two is also what "stack ROLE" means in R343's own
#: title: a secondary stack is two or more, a lone filler bat is not a role.
#: Operators may set ``team_exposure_min_hitters`` through --controls-override.
TEAM_EXPOSURE_MIN_HITTERS = 2


def _team_exposure_min_hitters(controls: Mapping[str, Any]) -> int:
    """The threshold above, read off the controls with the engine default."""
    try:
        value = int(controls.get("team_exposure_min_hitters")
                    or TEAM_EXPOSURE_MIN_HITTERS)
    except (TypeError, ValueError):
        return TEAM_EXPOSURE_MIN_HITTERS
    return max(1, value)


def candidate_team_footprint(
    hitter_ids: Iterable[str],
    team_by_player: Mapping[str, str],
    min_hitters: int = TEAM_EXPOSURE_MIN_HITTERS,
) -> FrozenSet[str]:
    """Teams this candidate is materially exposed to, over ALL stack roles.

    R343. ``max_primary_stack_exposure_pct`` counts the PRIMARY stack only, so a
    team can reach two-thirds of the entered set through secondary stacks with
    no control binding and no line reporting it -- measured on 1310_9g, NYY in
    15 of 21 entries and 17 of 21 after the rebuild. This is the footprint that
    cap was never over: every hitter slot, whatever role the optimizer labelled
    it, and nothing about which team the candidate calls primary.

    Hitters only, deliberately, and it is a different answer from R333's game
    footprint on purpose. A rostered arm is already capped on its own axis
    (``max_pitcher_exposure_pct``) and the failure this measures is an OFFENSE
    going quiet, which an opposing starter causes and a teammate arm does not.
    R333's game cap counts every rostered player including arms, because there a
    washout is a GAME outcome and the arm is in it (Ben, 2026-09-15). Two
    definitions, each stated where it is used, neither inferred from the other.

    A player the map does not know contributes to no team. That is the safe
    direction for a CEILING: an unknown never invents an exposure, and the
    absent map is reported by the caller rather than being read as "no teams".
    """
    counts: Dict[str, int] = defaultdict(int)
    for pid in hitter_ids:
        team = str(team_by_player.get(str(pid)) or "").strip().upper()
        if team:
            counts[team] += 1
    floor = max(1, int(min_hitters))
    return frozenset(t for t, n in counts.items() if n >= floor)


#: R405, Ben 2026-09-23. The consensus cluster is the BANK's own consensus: every
#: hitter present in at least this share of the distinct lineups the
#: unconstrained search produced, most-shared first, at most twelve. It is
#: defined from the bank and not from a salary-value rank because the value rank
#: does not find it: on 1905_10g the top nine hitters by Base per $1k held 2 of
#: the nine bats the portfolio concentrated on, by Ceiling per $1k 5, and by bank
#: share 8. The cluster is cross-team, so the team, game and stack caps cannot
#: see it, and the lineups share a POOL rather than a triple, so a k-subset cap
#: misses it too (QA's worst shared triple read 4 of 34 on that build).
CONSENSUS_CLUSTER_MIN_BANK_SHARE = 0.15
CONSENSUS_CLUSTER_MAX_MEMBERS = 12
#: R405. An entry counts toward `max_consensus_cluster_share_pct` when its
#: lineup carries at least this many cluster members. Ben's k, 2026-09-23.
#: Operators may set `consensus_cluster_min_members` through --controls-override.
CONSENSUS_CLUSTER_MIN_MEMBERS = 3
#: R405(c). The `bank_job_class` a candidate carries when it was built by a
#: cluster-limited bank job. Those candidates are excluded from the cluster's
#: SOURCE: they were built to avoid the consensus, so counting them would dilute
#: the definition the limit was derived from and let the sliced, direct and
#: late-swap paths disagree about who is in it. A candidate with no class is the
#: unconstrained search.
CONSENSUS_LIMITED_JOB_CLASS = "consensus_limited"


def _consensus_cluster_min_members(controls: Mapping[str, Any]) -> int:
    """k, read off the controls with the engine default."""
    try:
        value = int(controls.get("consensus_cluster_min_members")
                    or CONSENSUS_CLUSTER_MIN_MEMBERS)
    except (TypeError, ValueError):
        return CONSENSUS_CLUSTER_MIN_MEMBERS
    return max(1, value)


def _candidate_hitter_ids(candidate: Mapping[str, Any]) -> FrozenSet[str]:
    """The candidate's hitters: its roster minus its pitchers.

    A candidate with no readable ten-slot roster contributes no hitters here
    rather than raising: this runs before the allocator's own roster read, and
    that read is where a malformed candidate is refused, with its own words.
    """
    try:
        roster = _candidate_ordered_roster(dict(candidate))
    except ValueError:
        return frozenset()
    arms = set(_candidate_pitcher_ids(dict(candidate)) or roster[:2])
    return frozenset(str(p) for p in roster if p and str(p) not in arms)


def consensus_cluster_members(
    candidates: Sequence[Mapping[str, Any]],
    *,
    min_bank_share: float = CONSENSUS_CLUSTER_MIN_BANK_SHARE,
    max_members: int = CONSENSUS_CLUSTER_MAX_MEMBERS,
) -> Dict[str, Any]:
    """R405. The bank's consensus hitters, derived from the candidates handed in.

    The share is over DISTINCT lineups (sorted-roster signatures): two candidate
    objects holding the same ten players are one lineup, and counting both would
    let a duplicated payload manufacture a consensus. The source is every
    candidate whose ``bank_job_class`` is absent -- the unconstrained search --
    and only when there is none does it fall back to every candidate, which is
    named in ``source``. Ordering is share descending, then player id, so the
    twelve-member truncation is deterministic.

    Deterministic bookkeeping over the bank this solve received. A member is a
    player the SEARCH kept choosing, not a player predicted to score; nothing
    here is a probability.
    """
    rows = [dict(c) for c in candidates]
    unconstrained = [c for c in rows if not c.get("bank_job_class")]
    source_rows = unconstrained or rows
    seen: set = set()
    counts: Counter = Counter()
    n_source = 0
    for c in source_rows:
        try:
            sig = tuple(sorted(_candidate_ordered_roster(c)))
        except ValueError:
            continue  # refused by the allocator's own roster read, not here
        if not sig or sig in seen:
            continue
        seen.add(sig)
        n_source += 1
        counts.update(_candidate_hitter_ids(c))
    threshold = float(min_bank_share)
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    members = [
        {"player_id": pid, "lineups": int(n),
         "share": round(n / n_source, 4) if n_source else 0.0}
        for pid, n in ranked
        if n_source and n / n_source + 1e-9 >= threshold
    ][:max(0, int(max_members))]
    return {
        "members": members,
        "member_ids": [m["player_id"] for m in members],
        "source_lineups": n_source,
        "source": "unconstrained_bank_jobs" if unconstrained else "all_candidates",
        "limited_candidates_excluded_from_source": len(rows) - len(unconstrained)
        if unconstrained else 0,
        "min_bank_share": threshold,
        "max_members": int(max_members),
    }


def consensus_member_count(hitter_ids: Iterable[str],
                           members: Iterable[str]) -> int:
    """How many of the cluster's members one lineup carries. Pitchers are never
    members, so a full roster may be passed."""
    member_set = {str(m) for m in members}
    return sum(1 for p in {str(x) for x in hitter_ids} if p in member_set)


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
# R294(a). How many compatible candidates the prefilter reserves per entry
# before it spends anything on coverage or score. The reasoning for 2 lives in
# `_prefilter_candidates`' own comment, beside the loop that applies it.
PREFILTER_PER_ENTRY_RESERVE = 2


def _diagnose_binding_constraints(
    entries_count: int,
    stacks: Sequence[str],
    sp_pairs: Sequence[Tuple[str, ...]],
    signatures: Sequence[Tuple[str, ...]],
    largest_contest_entries: int,
    controls: Dict[str, Any],
    feasibility_inputs: Optional[Mapping[str, Any]] = None,
    team_exposure: Optional[Mapping[str, Any]] = None,
    game_exposure: Optional[Mapping[str, Any]] = None,
    consensus_cluster: Optional[Mapping[str, Any]] = None,
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

    # R343 / R333. The two washout-axis caps, in the same counting form. Both
    # are only reachable once their id map is wired, so a `map_status` of
    # `unknown` produces no finding at all rather than a finding computed over
    # an empty bucket set -- "asked and could not answer" is not "nothing is
    # binding", and R333's whole defect was a control whose absence read as the
    # bank's fault.
    team = dict(team_exposure or {})
    if team.get("map_status") == "wired" and team.get("count"):
        buckets = len(team.get("teams_capped") or [])
        cap = int(team["count"])
        per_entry = int(team.get("min_teams_per_candidate") or 0)
        if buckets and per_entry and buckets * cap < total * per_entry:
            findings.append(
                f"max_team_exposure_pct: {buckets} distinct teams x cap {cap} = "
                f"{buckets * cap} < {total * per_entry} team slots "
                f"({total} entries x {per_entry} teams each, at "
                f"{team.get('min_hitters_per_entry')}+ hitters per team)"
            )
    game = dict(game_exposure or {})
    if game.get("map_status") == "wired" and game.get("all_games_capped"):
        capped = list(game.get("games_capped") or [])
        capacity = sum(int(x.get("count") or 0) for x in capped)
        per_entry = int(game.get("min_games_per_candidate") or 0)
        if capped and per_entry and capacity < total * per_entry:
            findings.append(
                f"max_game_exposure_pct_by_game: {len(capped)} capped games "
                f"summing to {capacity} entry-slots < {total * per_entry} "
                f"({total} entries x {per_entry} games each)"
            )
    # R405. The consensus-cluster cap in the same counting form: at most
    # `headroom` entries may take a lineup carrying k or more cluster members,
    # so at least E - headroom need one carrying fewer, and the bank has to
    # hold enough of those. The count is over DISTINCT low-cluster lineups times
    # the reuse cap, the same capacity the reuse rows allow. When the bank holds
    # too few, the refusal says BANK-LIMITED and names the bank jobs that exist
    # to supply them (R405(c)), because relaxing the cap to fit a bank that was
    # never asked for the shape is R98(2)'s strategy-change-to-fit-a-search.
    cluster = dict(consensus_cluster or {})
    if cluster.get("row_added"):
        need = max(0, total - int(cluster.get("headroom") or 0))
        low_distinct = int(cluster.get("solved_distinct_below_k") or 0)
        reuse = controls.get("max_candidate_reuse")
        capacity = low_distinct * (int(reuse) if reuse is not None else need)
        if need and capacity < need:
            findings.append(
                f"max_consensus_cluster_share_pct: at most "
                f"{int(cluster.get('headroom') or 0)} entries may carry "
                f"{cluster.get('min_members_k')}+ of the "
                f"{len(cluster.get('members') or [])}-member consensus cluster, "
                f"so {need} need a lineup carrying fewer; the solved bank holds "
                f"{low_distinct} such distinct lineup(s) "
                f"({cluster.get('bank_candidates_below_k')} of "
                f"{cluster.get('bank_candidates')} in the bank handed in) -- "
                f"BANK-LIMITED: grow the cluster-limited bank jobs (R405(c)) "
                f"before relaxing this cap"
            )
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
    # R343. Same class as the three above it and for the same reason: the
    # engine can compute the minimum value that makes a GIVEN build feasible
    # (`floor_team_exposure_pct`), but that number is a consequence of the bank
    # it was handed, and adopting it concentrates the portfolio. It is not a
    # structural floor in R98(2)'s sense, so `late_swap` must not steer an
    # operator to raise it as though it were arithmetic.
    "max_team_exposure_pct",
    # R405. Same class and same reason: what the cluster cap can carry is a
    # property of the BANK (how many low-cluster lineups it holds), never an
    # arithmetic floor of the slate.
    "max_consensus_cluster_share_pct",
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


# R286, 2026-09-01. The infeasibility message is rendered in ONE place and it
# leads with the SLATE-level check that failed, never with a bank-level finding
# about a control whose slate check passed.
#
# The 1940_9g cost, and the shape is worth stating because neither half was
# lying. `_diagnose_binding_constraints` above is a counting argument on the BANK
# as handed in: 12 sampled SP pairs x cap 2 = 24 < 37 entries, true. The
# checkpoint's `sp_pair_capacity` check is the same arithmetic on the SLATE: 113
# viable pairs x cap 2 = 226 >= 37, also true. So `errors[0]` named
# `max_sp_pair_repetition` on four consecutive builds while the ONE failing
# check, `shared_players_floor`, carried its own arithmetic remedy ("raise
# max_shared_players to >= 7") and never appeared in `errors[]` at all. The
# operator escalated the sampled cap 1 -> 2 -> 10 and grew the bank twice,
# because that is what errors[0] and the FIRST REMEDY line together told him to
# do, and no amount of bank growth can clear a slate floor.
#
# Two orderings follow from that and both are load-bearing:
#   1. A failing slate check is PRIOR to every bank finding. It is an
#      impossibility of the slate, so it survives any bank; a bank finding is a
#      fact about candidates that another slice can change.
#   2. "no single control is arithmetically binding ... the interaction is" may
#      only be said when no slate check failed. In `_b7` it was said with
#      `shared_players_floor` failing, which is the same defect wearing the
#      reassuring message instead of the misleading one. That case is why this
#      guard is not just a reordering.
#
# Checks arrive already computed by their one owner, `_feasibility_report`; this
# function reads `passed` and `remedy` and computes no floor of its own, so there
# is no second implementation of the arithmetic to drift (R167's class).
SLATE_LEVEL_PREFIX = "SLATE-LEVEL structural check"
BANK_LEVEL_PREFIX = "BANK-LEVEL count against the candidates handed in"

# R286. Threading a verdict computed at the checkpoint into a function that
# re-enters itself with RELAXED controls is only safe while the relaxations touch
# nothing the verdict was computed from. These two sets say which is which as
# data, and `test_checkpoint_verdicts_cannot_go_stale_across_a_ladder_re_entry`
# asserts they stay disjoint -- so a fourth ladder that ever relaxes
# `max_shared_players` or an exposure cap fails a test here instead of silently
# reporting a stale check as the bind. The alternative was recomputing the floors
# in this module, which is the duplicate-arithmetic failure R167 is filed on.
CHECKED_CONTROLS = frozenset({
    "max_sp_pair_repetition", "max_shared_players",
    "max_pitcher_exposure_pct", "max_primary_stack_exposure_pct",
    "max_player_exposure_pct",
    # R343 / R333, 2026-09-15. Both new washout-axis ceilings are CHECKED and
    # neither is ladder-relaxed, and that pairing is the item's one deliberate
    # departure from what its board entries asked for. They asked for the caps
    # to be "relaxable in the standard order after player exposure" -- but the
    # order they name is R153's SHOWDOWN ladder, and on Classic there is no
    # player-exposure rung to come after: `LADDER_RELAXED_CONTROLS` holds three
    # LOWER bounds and the engine's own reuse default, and every exposure
    # CEILING is handled instead by the structural floor merge
    # (`feasibility_floors_from`), which raises an arithmetically impossible cap
    # to a feasible value BEFORE the solve. So the faithful reading of "handled
    # after player exposure" is "handled the way player exposure is handled",
    # and these two are. Putting them in both sets would also fail the
    # disjointness assert directly above, which exists because a ladder that
    # moves a control a threaded verdict was computed from makes that verdict
    # stale.
    "max_team_exposure_pct", "max_game_exposure_pct",
    # R405. A ceiling handled the way the other ceilings are (checked, floored
    # before the solve, relaxed under deadline by the T-15 rung), and so NOT a
    # ladder control: the disjointness assert above holds with it here.
    "max_consensus_cluster_share_pct",
})
LADDER_RELAXED_CONTROLS = frozenset({
    "max_candidate_reuse", "five_stack_share_quota", "primary_stack_min_size",
})


def failing_feasibility_checks(
    feasibility_checks: Optional[Sequence[Mapping[str, Any]]],
) -> List[Mapping[str, Any]]:
    """The checks whose ``passed`` is exactly False, in the order given.

    ``passed is None`` means the structural inputs were unavailable and is NOT a
    failure -- conflating "not checked" with "checked and failed" is R237's rule,
    and here it would invent a slate impossibility out of a missing input and
    send the operator to raise a control that was never binding.
    """
    out: List[Mapping[str, Any]] = []
    for check in (feasibility_checks or []):
        if not isinstance(check, Mapping):
            continue
        if check.get("passed") is False:
            out.append(check)
    return out


#: The controls the interaction message names as ACTIVE, and the ones R207's
#: probe drops one at a time. One tuple, so the sentence and the probe cannot
#: name different sets. R343 / R333 added the team and game caps and R405 the
#: cluster cap, each because a washout-axis cap missing from the list made the
#: sentence false on exactly the builds it binds.
INTERACTION_CONTROLS: Tuple[str, ...] = tuple(sorted((
    "max_player_exposure_pct", "max_pitcher_exposure_pct",
    "max_primary_stack_exposure_pct", "max_sp_pair_repetition",
    "max_shared_players", "max_candidate_reuse",
    "max_team_exposure_pct", "max_game_exposure_pct",
    "max_consensus_cluster_share_pct",
)))
#: The integer caps among them; every other one is a fraction of the entered set
#: resolved by `_cap_count`.
INTERACTION_COUNT_CONTROLS = frozenset({
    "max_sp_pair_repetition", "max_shared_players", "max_candidate_reuse"})


def compose_infeasibility_errors(
    binding: Sequence[str],
    controls: Mapping[str, Any],
    bank_flag: str,
    feasibility_checks: Optional[Sequence[Mapping[str, Any]]] = None,
) -> List[str]:
    """The one renderer for a PROVEN-infeasible joint allocation.

    Order: every failing slate-level check first, each naming itself and its own
    remedy; then every bank-level finding, labelled as such; then, only when no
    slate check failed AND no bank finding was made, the interaction message.

    With no ``feasibility_checks`` supplied this returns exactly what the two
    inline branches it replaced returned, byte for byte, which is what keeps the
    plan-time leg (`_plan_joint_allocation`, which passes no feasibility inputs)
    and the frozen golden replay unmoved.
    """
    failing = failing_feasibility_checks(feasibility_checks)
    lines: List[str] = []
    for check in failing:
        name = str(check.get("name") or "unnamed_check")
        detail = str(check.get("detail") or "").strip()
        remedy = str(check.get("remedy") or "").strip()
        text = f"entry-level joint MILP proven infeasible: {SLATE_LEVEL_PREFIX} {name}"
        if detail:
            text += f": {detail}"
        if remedy:
            text += f" -- REMEDY: {remedy}"
        text += (". This is arithmetic about the SLATE, so no bank growth and no "
                 "further search can clear it; fix this before reading anything "
                 "below.")
        lines.append(text)
    if binding:
        label = f"{BANK_LEVEL_PREFIX}, " if failing else ""
        lines.extend(
            f"entry-level joint MILP proven infeasible: {label}{b}{bank_flag}"
            for b in binding
        )
    elif not failing:
        lines.append(
            "entry-level joint MILP proven infeasible: no single control is "
            "arithmetically binding against this bank, so the interaction of "
            "the active controls is. Active: "
            + ", ".join(
                f"{k}={controls.get(k)}" for k in INTERACTION_CONTROLS
                if controls.get(k) is not None
            ) + bank_flag
        )
    return lines


def _infeasibility_remedies(
    bank_report: Optional[Mapping[str, Any]],
    binding: Sequence[str],
    feasibility_checks: Optional[Sequence[Mapping[str, Any]]] = None,
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

    R286. ``feasibility_checks`` outranks the bank-growth remedy when one of them
    FAILED. Bank growth is the right first move against a bank-limited count and
    it is the wrong move against a slate floor: on 1940_9g the operator grew the
    bank twice on this line's instruction while `shared_players_floor` was
    failing, which no bank can fix. So a failing slate check demotes the growth
    line and says why, rather than the growth line being deleted -- the bank may
    still be a slice, and that is still true and still worth knowing second.
    """
    lines: List[str] = []
    slate_failed = bool(failing_feasibility_checks(feasibility_checks))
    if slate_failed:
        lines.append(
            "FIRST REMEDY, raise the control the failing SLATE-LEVEL check names "
            "above: it is arithmetic about this slate and neither a bigger bank "
            "nor a looser cap elsewhere can satisfy it. Everything below is "
            "secondary and none of it clears that check."
        )
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
        bank_label = "NEXT REMEDY" if slate_failed else "FIRST REMEDY"
        # R415. A bank that stopped at its candidate cap does not grow on a
        # re-run: the next slice breaks before its first job. Say which lever.
        cap = (bank_report or {}).get("bank_cap") or {}
        if (bank_report or {}).get("bank_stop_reason") == "candidate_cap":
            lever = (
                f"It stopped at its {cap.get('value')}-candidate cap "
                f"({cap.get('source') or 'cap'}), so re-running the same command "
                f"adds nothing: raise --bank-max-candidates."
            )
        else:
            lever = ("Re-run the same build command; it exits 10 and resumes into "
                     "the same cache until the job list is exhausted.")
        lines.append(
            f"{bank_label}, grow the bank: the job list was NOT exhausted{scope}"
            f"{floored}, so this proof is about the candidates that were built, "
            f"not about the slate. {lever} Do not "
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
        # R343. The fourth, and it is not optional: `headroom()` clamps a
        # negative at 0, so without this check a late swap whose untouchable
        # rows have ALREADY overspent the team cap gets a silent zero-headroom
        # row instead of the refusal every sibling cap produces. The docstring
        # above says these are decidable from the file before any MILP runs;
        # that was true of three of the four.
        ("max_team_exposure_pct", "team footprint",
         fixed.get("team_counts") or {},
         _cap_count(total, controls.get("max_team_exposure_pct"))),
        # R405. The fifth, for R343's reason: `headroom()` clamps a negative at
        # 0, so without it untouchable rows that already overspend the cluster
        # cap would get a silent zero-headroom row instead of this refusal. The
        # count is taken by `select_and_assign_entries` against the cluster it
        # derived from the bank, because the cluster is a property of the bank
        # and `fixed_portfolio_exposure` never sees one.
        ("max_consensus_cluster_share_pct", "consensus-cluster lineup",
         fixed.get("consensus_cluster_counts") or {},
         _cap_count(total, controls.get("max_consensus_cluster_share_pct"))),
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


def _resolve_classic_sleeves(
    candidates: Sequence[Dict[str, Any]],
    entries: Sequence[Dict[str, Any]],
    full_compatible: List[List[bool]],
    controls: Mapping[str, Any],
    rosters: Sequence[Tuple[str, ...]],
) -> Dict[str, Any]:
    """R406. Apportion entries to sleeves and confine each through the mask.

    Applied only when the bank actually carries sleeve-built candidates (a
    ``bank_sleeve`` tag): a bank that never built a sleeve is not a sleeve
    shortfall, so it reports ``no_sleeve_bank`` and changes nothing -- R340's
    never-asked versus asked-and-could-not. Each entry's declared weights come
    from its own posture and shape (`classic_sleeves.contest_sleeve_weights`),
    and the joint MILP and every cap stay in force across all sleeves, because
    the only change is which candidates an entry may take.

    Every fallback is counted: a sleeve with no candidate, a (contest, sleeve)
    with fewer distinct compatible lineups than entries (its excess entries go
    to ``projection``), and an entry left with nothing compatible in its sleeve
    (unmasked). Mutates ``full_compatible`` in place.
    """
    from mlb_engine.optimize import classic_sleeves as cs
    if controls.get("classic_sleeves") is False:
        return {"status": "off", "relaxations": 0}
    cand_sleeves = [set(cs.candidate_sleeves(c)) for c in candidates]
    if all(x == {cs.SLEEVE_PROJECTION} for x in cand_sleeves):
        return {"status": "no_sleeve_bank", "relaxations": 0}
    E, K = len(entries), len(candidates)
    weights: Dict[str, Dict[str, float]] = {}
    for entry in entries:
        cid = str(entry.get("contest_id") or "")
        weights.setdefault(cid, cs.contest_sleeve_weights(
            entry.get("posture"), entry.get("contest_shape")))
    available = sorted(set().union(*cand_sleeves))
    plan = cs.apportion_entries(entries, weights, available=available)
    sleeve_of = dict(plan["sleeve_by_entry"])
    fallbacks = list(plan["fallbacks"])
    ids = [str(e.get("entry_id") or "") for e in entries]
    # A (contest, sleeve) needs as many distinct compatible lineups as entries,
    # or the same-contest duplicate rule cannot seat it.
    by_group: Dict[Tuple[str, str], List[int]] = defaultdict(list)
    for e, entry in enumerate(entries):
        by_group[(str(entry.get("contest_id") or ""), sleeve_of.get(ids[e], cs.SLEEVE_PROJECTION))].append(e)
    for (cid, sleeve), members in sorted(by_group.items()):
        if sleeve == cs.SLEEVE_PROJECTION:
            continue
        distinct = {tuple(sorted(rosters[k])) for e in members for k in range(K)
                    if full_compatible[e][k] and sleeve in cand_sleeves[k]}
        if len(distinct) < len(members):
            excess = sorted(members, key=lambda e: ids[e])[len(distinct):]
            for e in excess:
                sleeve_of[ids[e]] = cs.SLEEVE_PROJECTION
            fallbacks.append({"contest_id": cid, "sleeve": sleeve, "entries": len(excess),
                              "reason": f"{len(distinct)} distinct compatible lineup(s) "
                                        f"for {len(members)} entries"})
    unmasked: List[str] = []
    for e in range(E):
        want = sleeve_of.get(ids[e], cs.SLEEVE_PROJECTION)
        masked = [full_compatible[e][k] and want in cand_sleeves[k] for k in range(K)]
        if any(masked):
            full_compatible[e] = masked
        elif any(full_compatible[e]):
            unmasked.append(ids[e])
    if unmasked:
        fallbacks.append({"sleeve": "any", "entries": len(unmasked),
                          "entry_ids": unmasked,
                          "reason": "no compatible candidate in the entry's sleeve; "
                                    "left unmasked"})
    entries_by_sleeve: Dict[str, Dict[str, int]] = {}
    for e, entry in enumerate(entries):
        cid = str(entry.get("contest_id") or "")
        bucket = entries_by_sleeve.setdefault(cid, {x: 0 for x in cs.SLEEVES})
        bucket[sleeve_of.get(ids[e], cs.SLEEVE_PROJECTION)] += 1
    return {
        "status": "applied",
        "weights_by_contest": weights,
        "entries_by_sleeve": entries_by_sleeve,
        "candidates_by_sleeve": dict(sorted(Counter(
            s for members in cand_sleeves for s in members).items())),
        "sleeve_by_entry": dict(sorted(sleeve_of.items())),
        "fallbacks": fallbacks,
        "relaxations": sum(int(f.get("entries") or 0) for f in fallbacks),
        "unmasked_entries": unmasked,
        "_cand_sleeves": cand_sleeves,
    }


def _prefilter_candidates(
    candidates: Sequence[Dict[str, Any]],
    entries: Sequence[Dict[str, Any]],
    compatible: Sequence[Sequence[bool]],
    keep_target: int,
    *,
    reserve: Optional[Any] = None,
) -> Tuple[List[int], Dict[str, Any]]:
    """Choose which candidate indices enter the joint MILP.

    Only SELECTABLE candidates are eligible for a keep slot: a candidate no
    entry is compatible with cannot be assigned to anything, so spending a slot
    on it reduces what the MILP may choose from without reducing anything the
    MILP could have used. Forced coverage first: any candidate that is the only
    compatible option for some entry is kept unconditionally, because dropping
    it makes the problem infeasible outright. Then a per-entry reservation, so
    no entry can leave this function with an empty option set. Then one
    representative per primary stack and per SP pair, so no exposure cap loses
    its bucket and starts reporting a phantom infeasibility. Then the best
    remaining by shape score until the target. Ordering is deterministic: score
    descending, candidate id ascending, and every list is built by ascending
    index rather than from a set.

    R294(a), 2026-09-04. The three loops below used to iterate ``range(K)`` and
    ``order`` over ALL candidates with no compatibility test, and the primary-
    stack floor at the call site marks its excluded candidates incompatible for
    every entry BEFORE this runs. So on a bank whose ineligible candidates score
    highest -- exactly what a floor of 4 against a bank of high-scoring 3-stacks
    produces -- the score-ordered fill spent the entire keep target on
    candidates the MILP was forbidden to select, handed it no eligible option,
    and the infeasibility that followed was attributed to the bank by the reuse
    and floor ladders, each step counted as a relaxation. That is a SEARCH-EFFORT
    filter moving ``primary_stack_min_size``, a strategy control, invisibly:
    the shape CLAUDE.md's pool rule forbids. Measured at HEAD on the 60-candidate
    fixture in ``PrefilterCompatibilityTests``: 3 MILP calls, floor relaxed 4->3,
    assigned stack sizes [3, 3], with 10 eligible size-4 candidates sitting in
    the full bank untouched.
    """
    K = len(candidates)
    E = len(entries)
    if K <= keep_target:
        return list(range(K)), {
            "applied": False, "candidates_in": K, "candidates_kept": K,
            "keep_target": keep_target, "entries_emptied_by_prefilter": 0,
            "entries_emptied_ids": [],
        }

    # Ascending k and no set, so this is deterministic by construction
    # (`stable_union` is for merging sets; there is no set here to merge).
    selectable = [k for k in range(K) if any(compatible[e][k] for e in range(E))]

    def _score_order(indices: Sequence[int]) -> List[int]:
        best: Dict[int, float] = {}
        for k in indices:
            scores = [
                _candidate_shape_score(
                    candidates[k], str(e.get("contest_shape") or "large_wta"))
                for e in entries
            ]
            best[k] = max(scores) if scores else 0.0
        return sorted(indices, key=lambda k: (-best[k], _candidate_id(candidates[k], k)))

    if not selectable:
        # Every entry was already starved before this function ran, which is a
        # fact about the compatibility matrix and not something a keep-slot
        # choice can repair. Preserve the old score-ordered behaviour so the
        # caller's own diagnosis sees the bank it used to see, and report zero
        # emptied entries, because this function emptied none of them.
        order = _score_order(list(range(K)))
        keep = sorted(order[:keep_target])
        return keep, {
            "applied": True, "candidates_in": K, "candidates_kept": len(keep),
            "keep_target": keep_target, "forced_coverage_kept": 0,
            "selectable_in": 0,
            "distinct_stacks_represented": 0, "distinct_sp_pairs_represented": 0,
            "entries_emptied_by_prefilter": 0, "entries_emptied_ids": [],
            "rule": "no candidate is compatible with any entry; the keep set is "
                    "score-ordered and the starvation predates this filter",
        }

    order = _score_order(selectable)

    keep: List[int] = []
    seen = set()

    def _take(k: int) -> None:
        if k not in seen:
            seen.add(k)
            keep.append(k)

    forced = 0
    for e in range(E):
        options = [k for k in range(K) if compatible[e][k]]
        if len(options) == 1:
            forced += 1
            _take(options[0])

    # The anti-starvation floor. Two is the reservation and the reason it is not
    # larger: once the coverage and fill loops below iterate `order` -- which is
    # now selectable-only -- the whole keep target is spent on candidates the
    # MILP may actually select, so VOLUME is already guaranteed and a bigger N
    # would only displace higher-scored eligible candidates with lower-scored
    # ones. What N=2 buys that the fill cannot is the guarantee itself: an entry
    # whose compatible set is small and low-scored keeps an option even when
    # every slot would otherwise go to another entry's better ones, and a second
    # option so the same-contest duplicate rule has somewhere to go. It may push
    # `keep` past `keep_target` on a wide entry list; keeping MORE candidates
    # never starves an entry and never reduces the legal set, so that direction
    # is the safe one and `candidates_kept` reports it honestly.
    for e in range(E):
        taken_for_entry = 0
        for k in order:
            if taken_for_entry >= PREFILTER_PER_ENTRY_RESERVE:
                break
            if compatible[e][k]:
                _take(k)
                taken_for_entry += 1

    # R405. A ceiling over a CLASS of candidates needs the class's complement
    # in the keep set, or the row proves infeasible against a bank that held
    # the answer -- the consensus-cluster cap limits entries carrying k or more
    # cluster members, and the candidates that satisfy it score lower by
    # construction (they avoid the search's consensus), so a score-ordered fill
    # is exactly the fill that drops them. The caller sizes the reserve to what
    # the cap needs and passes nothing when the cap cannot bind, so a solve
    # without it keeps the same set it always kept.
    # R406: `reserve` may also be a MAPPING of name -> (indices, want), one per
    # class that needs its complement kept (R405's low-cluster candidates, each
    # sleeve's own), each reported under its own name. A single pair is R405's
    # shape and reads exactly as it did.
    if reserve and isinstance(reserve, tuple):
        reserves = {"consensus_low_cluster": reserve}
    else:
        reserves = dict(reserve or {})
    reserved_by_name: Dict[str, int] = {}
    for name in sorted(reserves):
        reserve_idx, reserve_want = reserves[name]
        reserve_set = {int(k) for k in reserve_idx}
        want = max(0, int(reserve_want))
        kept_here = 0
        for k in order:
            if kept_here >= want:
                break
            if k in reserve_set:
                _take(k)
                kept_here += 1
        reserved_by_name[name] = kept_here

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
    # An entry that HAD a compatible option in the full bank and has none in the
    # keep set was emptied by this function. After the reservation above that
    # should be unreachable; it is reported rather than asserted because a
    # pool-membership fact that is invisible in the artifact is the failure mode
    # CLAUDE.md's guardrail is written against, and the next reader can check the
    # count instead of re-deriving it.
    emptied = [
        str(entries[e].get("entry_id") or e)
        for e in range(E)
        if any(compatible[e][k] for k in range(K))
        and not any(compatible[e][k] for k in keep)
    ]
    return keep, {
        "applied": True,
        "candidates_in": K,
        "candidates_kept": len(keep),
        "keep_target": keep_target,
        "forced_coverage_kept": forced,
        "selectable_in": len(selectable),
        "per_entry_reserve": PREFILTER_PER_ENTRY_RESERVE,
        **{f"{name}_kept": kept for name, kept in sorted(reserved_by_name.items())},
        "distinct_stacks_represented": len(covered_stacks),
        "distinct_sp_pairs_represented": len(covered_pairs),
        "entries_emptied_by_prefilter": len(emptied),
        "entries_emptied_ids": emptied,
        "rule": "selectable candidates only, then forced coverage, then the "
                "per-entry reserve, then one representative per primary stack "
                "and SP pair, then best shape score; deterministic, never a "
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


# The bottom rung of the quota ladder above zero. R37(2)(b) sizes the live band
# at 0.15-0.25, so 0.15 is the loosest share the decision actually asked for;
# below it the honest step is off, not an unsized fraction nobody chose.
FIVE_STACK_QUOTA_MIN_RUNG = 0.15


def five_stack_quota_rungs(requested_share: float) -> List[Optional[float]]:
    """The relaxation ladder for the five-stack SHARE quota, tightest first.

    R37(2)(b), Ben's dated decision of 2026-08-28. ``0.20 -> [0.20, 0.15, None]``:
    the requested share, then the bottom of the sized band, then the quota
    switched off. The final ``None`` is the truncation-avoiding rung, for the
    reason ``primary_stack_floor_rungs`` states in full -- a control that
    REFUSES leaves a blank reserved row, and a blank row blocks certification.

    This ladder is the reconciliation the backlog item asked for. R34 shipped
    the quota as a MILP row that HARD FAILS, while R37 stage 1 shipped the
    primary-stack floor as a ladder that relaxes and counts. Two lower bounds on
    the same quantity with opposite failure modes is not a state to ship, and
    the item names which one wins: the counted relaxation.
    """
    try:
        top = float(requested_share)
    except (TypeError, ValueError):
        return [None]
    if not (top > 0.0):
        return [None]
    rungs: List[Optional[float]] = [top]
    if top > FIVE_STACK_QUOTA_MIN_RUNG:
        rungs.append(FIVE_STACK_QUOTA_MIN_RUNG)
    rungs.append(None)
    return rungs


def bank_stack_size_verdict(
    bank_report: Optional[Mapping[str, Any]],
    min_size: int,
) -> Dict[str, Any]:
    """Was the bank ever ASKED for a primary stack of ``min_size``?

    R340 fix (2). Without this the floor report and the quota report have one
    vocabulary for two different facts: a bank that was asked and could not
    produce the shape (a real fact about the pool or the clock) and a bank that
    was never asked (a control with no wire). The first is evidence; the second
    is a defect, and for a year it wore the first one's clothes.

    Three values, and the third is not a hedge. ``bank_asked_and_could_not`` and
    ``bank_never_asked_for_size`` both require a bank report that RECORDS what it
    asked for; a caller that passes no report, or an older report from before
    this record existed, gets ``unknown`` and the reader is told the question
    could not be answered rather than being given the likelier answer.
    """
    report = dict(bank_report or {})
    request = report.get("stack_request")
    if not isinstance(request, Mapping):
        return {"status": "unknown", "requested_sizes": None,
                "note": "this bank report records no stack request, so whether "
                        "the bank was asked for this size cannot be read off it"}
    sizes = request.get("sizes")
    try:
        asked = [int(x) for x in (sizes or [])]
    except (TypeError, ValueError):
        asked = []
    if not asked:
        return {"status": "unknown", "requested_sizes": None,
                "note": "the stack request carries no sizes"}
    if max(asked) >= int(min_size):
        return {"status": "bank_asked_and_could_not", "requested_sizes": asked,
                "note": f"the bank WAS asked for a primary stack of "
                        f"{max(asked)} and did not produce one that qualifies "
                        f"at >= {int(min_size)}; this is a fact about the pool "
                        f"or the search budget, not an unwired control"}
    return {"status": "bank_never_asked_for_size", "requested_sizes": asked,
            "note": f"the bank was asked for {asked} and never for "
                    f">= {int(min_size)}, so no candidate could have qualified. "
                    f"This is a wiring fact, not a thin pool (R340)"}


def _resolve_five_stack_quota(
    stack_sizes: Sequence[int],
    n_entries: int,
    controls: Mapping[str, Any],
    quota_state: Optional[Mapping[str, Any]] = None,
    bank_report: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Resolve the five-stack share quota to a need count this bank can carry.

    R37(2)(b). Returns the report block AND the ``need`` the MILP row should
    enforce. Three statuses matter and they are deliberately distinct:

    ``not_requested`` -- the share is 0.0 or absent. Every posture shipped 0.0
    until this date, so this is still the common case, and it is NOT the same
    fact as a quota that was asked for and could not be carried.

    ``relaxed_off`` -- asked for, and NO candidate in the bank reports a primary
    stack at or above ``five_stack_min_size``. That is arithmetically binding
    without consulting the solver: a lower bound of ``need`` over an empty
    column set cannot be met. R34 returned ``passed: False`` here. It now steps
    the ladder and counts, because the alternative is a refusal that delivers
    nothing.

    ``applied`` / ``applied_relaxed`` -- enforced at the rung named.

    One case R34 did not have a diagnostic for at all, and this does: when SOME
    candidates qualify but fewer than ``need`` distinct ones exist, the row is
    satisfiable only through candidate REUSE, so whether it fits is the joint
    MILP's answer and not arithmetic. That is not relaxed here. It is NAMED in
    ``reuse_dependent``, so a proven infeasibility downstream arrives with the
    quota already identified as a probable binder instead of as a bare
    infeasibility with no control attached to it.
    """
    state = dict(quota_state or {})
    verdict = bank_stack_size_verdict(
        bank_report, int(controls.get("five_stack_min_size") or 5))
    requested = controls.get("min_five_stack_share_pct")
    E = max(0, int(n_entries))
    report: Dict[str, Any] = {
        "requested_share": None,
        "applied_share": None,
        "status": "not_requested",
        "min_size": int(controls.get("five_stack_min_size") or 5),
        "requested_need": 0,
        "applied_need": 0,
        "qualifying_candidates": 0,
        "reuse_dependent": False,
        "relaxations": int(state.get("relaxations") or 0),
        "relaxation_steps": list(state.get("relaxation_steps") or []),
        "rung_index": int(state.get("rung_index") or 0),
        # R340 fix (2). "No candidate qualifies" has two causes that used to
        # share one sentence, and they call for opposite responses: a bank that
        # was ASKED and could not is a fact about the pool or the clock, and a
        # bank that was NEVER asked is a control with no wire.
        "bank_stack_request": verdict,
        "note": "deterministic construction control sized off a MEASURED field "
                "share; observed-outcome rationale, never a win rate, cash "
                "rate, or ROI claim",
    }
    if not requested:
        return report
    ladder = five_stack_quota_rungs(requested)
    rung_idx = min(report["rung_index"], len(ladder) - 1)
    report["rung_index"] = rung_idx
    report["requested_share"] = assert_fraction_cap(
        requested, key="min_five_stack_share_pct")
    applied = ladder[rung_idx]
    if applied is None:
        report["status"] = "relaxed_off" if report["relaxations"] else "off"
        return report
    min_size = report["min_size"]
    qualifying = [k for k, size in enumerate(stack_sizes) if int(size) >= min_size]
    report["qualifying_candidates"] = len(qualifying)
    report["requested_need"] = int(math.floor(E * report["requested_share"] + 1e-9))
    need = int(math.floor(E * float(applied) + 1e-9))
    if need <= 0:
        report["applied_share"] = float(applied)
        report["status"] = "off"
        report["note"] = (
            f"quota share {applied} over {E} entries floors to a need of 0 "
            f"entries, so the row would bind nothing. Reported off rather than "
            f"added as a vacuous constraint. " + report["note"])
        return report
    if not qualifying:
        # Arithmetically binding: a lower bound over an empty column set. Step
        # STRAIGHT to off rather than walking the ladder, because the bind is the
        # candidate set and not the share -- lowering 0.20 to 0.15 does not make
        # a candidate qualify, and counting that as a relaxation would inflate
        # the number the brief teaches Ben to read as "how much gave way". One
        # bind, one counted step.
        stepped = list(report["relaxation_steps"])
        stepped.append({
            "from": float(applied),
            "to": None,
            "reason": (
                f"min_five_stack_share_pct {applied} requires {need} of {E} "
                f"entries at primary stack size >= {min_size}, and the bank "
                f"contains 0 such candidates. {verdict['note']}. Lowering the "
                f"share cannot help. Never trim the pool to fit"),
            # R340 fix (2). Was always `no_qualifying_candidate_in_bank`, which
            # reads as a bank that came up short. Where the report says what the
            # bank was asked for, the trigger says which of the two it was.
            "trigger": (verdict["status"] if verdict["status"] != "unknown"
                        else "no_qualifying_candidate_in_bank"),
        })
        report["relaxations"] = int(report["relaxations"]) + 1
        report["relaxation_steps"] = stepped
        report["rung_index"] = len(ladder) - 1
        report["status"] = "relaxed_off"
        report["applied_share"] = None
        report["applied_need"] = 0
        return report
    report["applied_share"] = float(applied)
    report["applied_need"] = need
    report["reuse_dependent"] = len(qualifying) < need
    report["status"] = "applied_relaxed" if report["relaxations"] else "applied"
    return report


def _resolve_primary_stack_floor(
    candidates: Sequence[Dict[str, Any]],
    full_compatible: Sequence[Sequence[bool]],
    entry_ids: Sequence[str],
    controls: Mapping[str, Any],
    floor_state: Optional[Mapping[str, Any]] = None,
    bank_report: Optional[Mapping[str, Any]] = None,
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
        # R340 fix (2). Same distinction the quota report carries, for the same
        # reason: a floor that relaxes because the bank holds nothing at that
        # size is reporting a bank that was ASKED and could not, or one that was
        # never asked. Only the second is a defect, and it used to be invisible.
        "bank_stack_request": bank_stack_size_verdict(
            bank_report, int(controls.get("primary_stack_min_size") or 0) or 5),
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


def fraction_for_count(count: int, total: int, places: int = 4) -> float:
    """The smallest fraction, at ``places`` decimals, that `_cap_count`
    resolves to at least ``count`` entries of ``total``.

    ``round(count / total, places)`` rounds DOWN about half the time, and a
    rounded-down pct enforces the count below the one it was meant to name
    (9 entries, count 4: 0.4444 enforces 3). So this rounds up and then checks
    against `_cap_count`'s own floor, the rule the solve enforces. Capped at
    1.0, which is the cap switched off.
    """
    if total <= 0 or count >= total:
        return 1.0
    scale = 10 ** places
    value = math.ceil(count / float(total) * scale - 1e-6) / scale
    while value < 1.0 and math.floor(total * value + 1e-9) < count:
        value = round(value + 1.0 / scale, places)
    return min(1.0, round(value, places))


def interaction_step(key: str, value: Any, total: int) -> Dict[str, Any]:
    """R207. The smallest move of one control that changes what it enforces.

    A fraction cap binds as ``_cap_count(total, pct)`` entries, so the smallest
    useful raise is the smallest pct at which that count goes up by one
    (`fraction_for_count`, rounded UP so the step enforces the count it names);
    any value between the two enforces the same count. An integer cap
    goes up by one. A step that reaches 1.0 is the cap switched off.
    """
    if key in INTERACTION_COUNT_CONTROLS:
        count = int(value)
        return {"from": value, "to": count + 1, "count_from": count,
                "count_to": count + 1}
    count = _cap_count(total, value)
    if count is None:
        return {"from": value, "to": None, "count_from": None, "count_to": None}
    return {"from": value, "to": fraction_for_count(count + 1, total, 4),
            "count_from": count, "count_to": min(total, count + 1)}


def _probe_verdict(result: Mapping[str, Any]) -> Optional[bool]:
    """True when a probe solve found an allocation, False when it PROVED none
    exists, None when it did neither (a time limit or an unverifiable status):
    "undecided" is not "infeasible" (R294(c))."""
    if result.get("passed"):
        return True
    report = result.get("allocation_solver_report") or {}
    return False if report.get("scipy_status") == 2 else None


#: What the probe drops as one row when per-game caps bind: the scalar's
#: expansion, an operator's per-game values and F5 weather caps all land in one
#: dict, merged by MIN, and the solve enforces the dict. Dropping any of them
#: alone would need the merge's inputs, which the allocator does not have.
PER_GAME_SCOPE = ("every per-game cap: the max_game_exposure_pct scalar's "
                  "expansion, operator per-game values and F5 weather caps, "
                  "merged by MIN")


def _interaction_probe(
    resolve: Any,
    controls: Mapping[str, Any],
    total: int,
    budget_s: float,
    not_after: Optional[float] = None,
) -> Dict[str, Any]:
    """R207. Which ONE active control, dropped alone, restores feasibility.

    The interaction message names the active set and nothing else, so on
    1240_6g finding the one cap that mattered (``max_player_exposure_pct`` 0.4
    -> 0.5, ``floor(pct * n)`` 2 -> 3) took four full builds. This re-solves the
    same model once per active control with that control ALONE dropped, and for
    each whose removal restores feasibility, once more at its smallest step
    (`interaction_step`), so the refusal can carry the number. ``resolve`` is a
    closure over the refused solve's own bank, entries and ladder states, run in
    probe mode: no ladder, no retry, no recursion. Nothing here reaches
    ``errors[]``.

    Bounded by ``budget_s`` of wall clock across every solve, each solve's own
    time limit clamped to what remains; a control the budget did not reach reads
    ``not_probed``. ``not_after`` is an absolute ``time.monotonic()`` bound
    the caller computed from its own deadline and the governor's window, so a
    budget sized before a long solve cannot run past either. The per-game caps
    are one row (`PER_GAME_SCOPE`): the scalar when it is set, the dict when
    only the dict is, and never a step, since the dict is what the solve
    enforces. Truthful labels: a restored solve is feasibility of a MILP
    against this bank, never a claim about outcomes.
    """
    import time as _time
    started = _time.monotonic()
    rows: List[Dict[str, Any]] = []
    solves = 0

    def _left() -> float:
        left = float(budget_s) - (_time.monotonic() - started)
        if not_after is not None:
            left = min(left, float(not_after) - _time.monotonic())
        return left

    def _run(trial: Dict[str, Any]) -> Optional[bool]:
        nonlocal solves
        limit = float(trial.get("time_limit", controls.get("time_limit", 30)))
        trial["time_limit"] = max(0.5, min(limit, _left()))
        solves += 1
        return _probe_verdict(resolve(trial))

    probe_keys = [k for k in INTERACTION_CONTROLS if controls.get(k) is not None]
    if ("max_game_exposure_pct" not in probe_keys
            and controls.get("max_game_exposure_pct_by_game")):
        probe_keys.append("max_game_exposure_pct_by_game")
    for key in probe_keys:
        value = controls.get(key)
        row: Dict[str, Any] = {"control": key, "value": value}
        if key in ("max_game_exposure_pct", "max_game_exposure_pct_by_game"):
            row["scope"] = PER_GAME_SCOPE
        if _left() <= 0.5:
            row["status"] = "not_probed"
            rows.append(row)
            continue
        dropped = dict(controls)
        dropped[key] = None
        if key in ("max_game_exposure_pct", "max_game_exposure_pct_by_game"):
            dropped["max_game_exposure_pct"] = None
            dropped["max_game_exposure_pct_by_game"] = None
        row["alone_restores"] = _run(dropped)
        row["status"] = "probed"
        if row["alone_restores"] is True:
            if key in ("max_game_exposure_pct", "max_game_exposure_pct_by_game"):
                step = {"from": value, "to": None, "count_from": None,
                        "count_to": None, "restores": None,
                        "note": ("no single step: dropping the per-game caps "
                                 "restores feasibility, and which of their "
                                 "writers binds is not separable here")}
                row["step"] = step
                rows.append(row)
                continue
            step = interaction_step(key, value, total)
            if step["to"] is None:
                step["restores"] = None
                step["note"] = "not re-solved: the control resolves to no count"
            elif _left() <= 0.5:
                step["restores"] = None
                step["note"] = "not re-solved: the probe budget was spent"
            else:
                stepped = dict(controls)
                stepped[key] = step["to"]
                step["restores"] = _run(stepped)
            row["step"] = step
        rows.append(row)
    return {
        "ran": True,
        "budget_s": float(budget_s),
        "elapsed_s": round(_time.monotonic() - started, 3),
        "solves": solves,
        "controls": rows,
        "restoring": [r["control"] for r in rows if r.get("alone_restores") is True],
        "note": ("each active control dropped ALONE against the refused solve's "
                 "own bank; alone_restores is True (feasible), False (proven "
                 "infeasible) or None (undecided within its time limit). A step "
                 "is the smallest move that changes what the control enforces. "
                 "Feasibility of a MILP, never a probability"),
    }


def select_and_assign_entries(
    candidates: Sequence[Dict[str, Any]],
    entry_requirements: Sequence[Dict[str, Any]],
    portfolio_controls: Optional[Dict[str, Any]] = None,
    *,
    bank_report: Optional[Mapping[str, Any]] = None,
    fixed_exposure: Optional[Mapping[str, Any]] = None,
    feasibility_inputs: Optional[Mapping[str, Any]] = None,
    feasibility_checks: Optional[Sequence[Mapping[str, Any]]] = None,
    _floor_state: Optional[Mapping[str, Any]] = None,
    _reuse_state: Optional[Mapping[str, Any]] = None,
    _quota_state: Optional[Mapping[str, Any]] = None,
    _search_state: Optional[Mapping[str, Any]] = None,
    interaction_probe_budget_s: Optional[float] = None,
    interaction_probe_not_after: Optional[float] = None,
    _probe: bool = False,
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

    ``feasibility_checks`` (R286) is ``_feasibility_report(...)["checks"]`` -- the
    checkpoint's already-computed verdicts, not a second implementation of the
    arithmetic. Read on the proven-infeasible path only, where a check whose
    ``passed`` is False is a SLATE impossibility and therefore prior to every
    count this module can take over a bank. Omitting it returns the pre-R286
    message byte for byte. The allocator's three relaxation ladders
    (``max_candidate_reuse``, the five-stack quota, the primary-stack floor) move
    no control any of these checks reads, so a checkpoint verdict cannot go stale
    across a re-entry; ``CHECKED_CONTROLS`` and ``LADDER_RELAXED_CONTROLS`` state
    that as data and a test asserts they stay disjoint.

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

    ``_search_state`` is private and is R326's. It carries one fact -- that the
    restricted bank was already proven infeasible and this re-entry is the
    FULL-bank retry -- so the retry happens once and never recurses. Never
    pass it from outside. ``allocation_solver_report.search_scope`` says which
    bank the certificate covers, ``restricted`` or ``full``.

    ``interaction_probe_budget_s`` (R207) arms `_interaction_probe` on the one
    refusal it answers: PROVEN infeasible, every ladder spent, no failing slate
    check and no bank-level finding, which is when ``errors[]`` can only say
    "the interaction of the active controls is", and not on a partial bank,
    whose first remedy is to grow it. The refusal then carries
    ``interaction_probe``. ``interaction_probe_not_after`` is an absolute
    ``time.monotonic()`` bound on it. None (the default) runs nothing, so every
    caller that does not pass a budget is byte-identical. ``_probe`` is
    private: the probe's own solves, which skip every ladder and retry and
    never probe again.
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

    # R294(b), 2026-09-04. A slate-level check that has already FAILED cannot be
    # cleared by any rung the three ladders below climb. R286 established that
    # `CHECKED_CONTROLS` and `LADDER_RELAXED_CONTROLS` are disjoint and asserts
    # it in a test, so the controls those ladders relax are, by construction,
    # not the controls a failing check is about. Re-entering therefore re-solves
    # the same slate impossibility and arrives at the same refusal, having spent
    # the operator's window: measured 5 solves on a 9-entry fixture with a
    # failing `shared_players_floor`, against 1 with this guard, and the
    # arithmetic ceiling is 8 (1 initial + reuse 2 + quota 2 + floor 3 rungs).
    # The refusal itself is unchanged -- `compose_infeasibility_errors` already
    # leads with the failing check and its remedy; what changes is that it
    # arrives at the first solve instead of the fifth.
    slate_blocked = bool(failing_feasibility_checks(feasibility_checks))

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

    # R405. The consensus cluster, derived HERE from the candidate set this
    # solve received and before the prefilter narrows it, so the sliced, direct
    # and late-swap paths all answer "who is the consensus" from one function
    # over the bank they actually hand in. The untouchable rows' count is taken
    # now because the conflict check below runs before any candidate is scored.
    cluster = consensus_cluster_members(_all_candidates)
    cluster_members = list(cluster["member_ids"])
    cluster_k = _consensus_cluster_min_members(controls)
    fixed_cluster_high = 0
    if fixed_rows and cluster_members:
        fixed_cluster_high = sum(
            1 for r in (fixed.get("rosters") or [])
            if consensus_member_count(r, cluster_members) >= cluster_k)
        fixed["consensus_cluster_counts"] = (
            {f"at {cluster_k}+ members": fixed_cluster_high}
            if fixed_cluster_high else {})
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

    # R406. The sleeves' mask, applied before the floor and the prefilter so
    # both see the compatible set each entry's world allows.
    sleeve_report = _resolve_classic_sleeves(
        candidates, entries, full_compatible, controls, all_rosters)

    # R37 stage 1. The primary-stack floor is applied HERE: after entry
    # compatibility and the untouchable-row blocking, so the starvation check
    # sees the real compatible set, and before the prefilter, so the prefilter
    # spends its keep-target on candidates that can actually be selected rather
    # than discarding eligible ones in favour of ineligible ones.
    floor_report = _resolve_primary_stack_floor(
        candidates, full_compatible, entry_ids, controls, _floor_state,
        bank_report=bank_report,
    )
    if floor_report.get("applied") is not None:
        for k in floor_report["excluded_candidate_idx"]:
            for e in range(E):
                full_compatible[e][k] = False

    # F13: the pairwise overlap block is K-squared. An unfiltered bank is what
    # pushes this solve into its own time limit, and a time limit here used to
    # read as "infeasible". Prefiltering reduces search effort; it never touches
    # the legal player set, and forced-coverage candidates are kept outright.
    # R326. The full-bank retry sets the keep target to the whole bank, so
    # `_prefilter_candidates` takes its `K <= keep_target` early return and the
    # MILP sees every candidate. Expressed as a keep target rather than by
    # skipping the call, so the retry's `prefilter_report` is a real report from
    # the same helper and `search_scope` below derives from it rather than from
    # a second flag that could disagree with it.
    _full_bank_retry = bool((_search_state or {}).get("full_bank"))
    keep_target = (
        len(candidates) if _full_bank_retry else max(
            int(controls.get("candidate_prefilter_target")
                or E * DEFAULT_CANDIDATE_PREFILTER_MULTIPLE),
            MIN_CANDIDATE_PREFILTER_FLOOR,
        )
    )
    # R405. Resolved before the prefilter, because the prefilter has to keep
    # the candidates this cap needs (see the reserve in `_prefilter_candidates`).
    # `cluster_bound` is the headroom the row will carry; a bound at or above E
    # cannot bind, adds no row, and reserves nothing, which is what keeps a cap
    # opened to 1.0 byte-identical to no cap at all.
    bank_member_counts = [
        consensus_member_count(_candidate_hitter_ids(c), cluster_members)
        for c in candidates]
    cluster_pct = controls.get("max_consensus_cluster_share_pct")
    cluster_cap = _cap_count(total, cluster_pct)
    cluster_bound: Optional[int] = None
    cluster_reserve: Optional[Tuple[List[int], int]] = None
    if cluster_cap and cluster_members:
        cluster_bound = max(0, int(cluster_cap) - int(fixed_cluster_high))
        if cluster_bound < E:
            low_idx = [k for k, n in enumerate(bank_member_counts) if n < cluster_k]
            cluster_reserve = (low_idx, min(len(low_idx), 2 * (E - cluster_bound)))
    # R406: each sleeve keeps twice its entries' worth of its own candidates,
    # for R405's reason -- a sleeve's lineups can score below the projection's,
    # and a score-ordered fill would drop exactly them.
    prefilter_reserves: Dict[str, Tuple[List[int], int]] = {}
    if cluster_reserve is not None:
        prefilter_reserves["consensus_low_cluster"] = cluster_reserve
    if sleeve_report.get("status") == "applied":
        _cs = sleeve_report["_cand_sleeves"]
        _entries_per_sleeve = Counter(sleeve_report["sleeve_by_entry"].values())
        for _sleeve, _n in sorted(_entries_per_sleeve.items()):
            if _sleeve == "projection" or not _n:
                continue
            _idx = [k for k in range(len(candidates)) if _sleeve in _cs[k]]
            prefilter_reserves[f"sleeve_{_sleeve}"] = (_idx, min(len(_idx), 2 * _n))
    kept_idx, prefilter_report = _prefilter_candidates(
        candidates, entries, full_compatible, keep_target,
        reserve=prefilter_reserves or None,
    )
    if prefilter_report["applied"]:
        candidates = [candidates[k] for k in kept_idx]
        all_rosters = [all_rosters[k] for k in kept_idx]
    # R294(a). The sentence above this call ("spends its keep-target on
    # candidates that can actually be selected") described an intent the code
    # did not implement until 2026-09-04; it is now true, and this warning is
    # what says so when it is not. An emptied entry is a pool reduction in
    # effect, so it is surfaced rather than left inside a report field -- but it
    # WARNS and does not refuse, because a starved entry makes a badly shaped
    # file and not an illegal one, and CLAUDE.md reserves refusal for illegal.
    prefilter_warnings: List[str] = []
    if prefilter_report.get("entries_emptied_by_prefilter"):
        prefilter_warnings.append(
            f"candidate prefilter left "
            f"{prefilter_report['entries_emptied_by_prefilter']} entry(ies) with "
            f"no compatible candidate that had one in the full bank "
            f"({', '.join(prefilter_report.get('entries_emptied_ids') or [])}); "
            f"any infeasibility below is this filter's, NOT the bank's and NOT "
            f"a strategy control's. Raise controls['candidate_prefilter_target']"
        )

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
    #
    # R37(2)(b), 2026-08-28. This used to HARD FAIL when no candidate qualified,
    # which is the failure mode the backlog item told us to retire: R37 stage 1's
    # floor one screen up relaxes and counts, and two lower bounds on the same
    # quantity with opposite failure modes is not a state to ship. The resolution
    # now runs through `_resolve_five_stack_quota`, which steps the ladder, counts
    # the step, and reports the rung it landed on. A quota that cannot be carried
    # costs a named relaxation; it no longer costs the delivery.
    quota_report = _resolve_five_stack_quota(stack_sizes, E, controls,
                                             quota_state=_quota_state,
                                             bank_report=bank_report)
    if quota_report.get("applied_need"):
        qualifying = [k for k in range(K)
                      if stack_sizes[k] >= int(quota_report["min_size"])]
        add({x_idx(e, k): 1.0 for e in range(E) for k in qualifying},
            float(quota_report["applied_need"]), np.inf)

    game_caps = dict(controls.get("max_game_exposure_pct_by_game") or {})
    game_by_player = {str(k): str(v)
                      for k, v in (controls.get("player_game_by_id") or {}).items()}
    game_cap_report: Dict[str, Any] = {
        "requested": {str(k): float(v) for k, v in sorted(game_caps.items())} or None,
        # R333. Three values, never a bool, and the third is the one that
        # matters: `unknown` says the map was absent so the question could not
        # be answered, which for a year was reported as an ERROR on the one
        # control `late_swap.py` steers an operator to. `bank_stack_size_verdict`
        # is the shape being copied (R340 fix 2).
        "map_status": ("not_requested" if not game_caps
                       else ("wired" if game_by_player else "unknown")),
        "games_capped": [], "counts": "roster_footprint",
        "min_games_per_candidate": None, "all_games_capped": None,
    }
    if game_caps:
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
        game_cap_report["min_games_per_candidate"] = min(
            (len({game_by_player.get(pid) for pid in pset} - {None, ""})
             for pset in player_sets), default=0)
        # The counting argument below is only valid when no game is exempt: an
        # uncapped game is an unconstrained bucket and capacity cannot be summed
        # over the capped ones alone.
        game_cap_report["all_games_capped"] = bool(candidates_in_game) and all(
            str(g) in {str(x) for x in game_caps} for g in candidates_in_game)
        for gid, pct in sorted(game_caps.items()):
            # R61: `total`, not E, and minus what the untouchable rows hold. This
            # cap floors at 0 rather than 1 (_game_cap_count's contract: an
            # explicit pct of 0 means zero), so headroom() is the same shape.
            cap = max(0, int(math.floor(total * min(1.0, max(0.0, float(pct))) + 1e-9)))
            members = candidates_in_game.get(str(gid), [])
            if members:
                game_cap_report["games_capped"].append(
                    {"game_id": str(gid), "pct": float(pct), "count": cap,
                     "candidates_in_game": len(members)})
                add({x_idx(e, k): 1.0 for e in range(E) for k in members},
                    -np.inf, headroom(cap, fixed_games.get(str(gid), 0)))

    # R343. The team footprint cap, over EVERY hitter slot rather than over the
    # primary stack alone. Same row shape as the game cap one screen up and the
    # same three-value wiring verdict, because the two defects are one defect:
    # a correlated-failure axis with a control that cannot reach it. What
    # differs is what an entry has to hold to be counted -- see
    # `candidate_team_footprint`, which states both definitions in one place.
    team_pct = controls.get("max_team_exposure_pct")
    team_by_player = {str(k): str(v)
                      for k, v in (controls.get("player_team_by_id") or {}).items()}
    team_min_hitters = _team_exposure_min_hitters(controls)
    team_cap = _cap_count(total, team_pct)
    team_cap_report: Dict[str, Any] = {
        "requested_pct": float(team_pct) if team_pct is not None else None,
        "count": team_cap,
        "min_hitters_per_entry": team_min_hitters,
        "map_status": ("not_requested" if not team_cap
                       else ("wired" if team_by_player else "unknown")),
        "teams_capped": [], "counts": "hitter_slots",
        "min_teams_per_candidate": None,
    }
    if team_cap and team_by_player:
        footprints = [candidate_team_footprint(
            player_sets[k] - pitcher_sets[k], team_by_player, team_min_hitters)
            for k in range(K)]
        candidates_on_team: Dict[str, List[int]] = defaultdict(list)
        for k, teams_k in enumerate(footprints):
            for team in teams_k:
                candidates_on_team[team].append(k)
        fixed_teams = ({str(k): int(v) for k, v in (fixed.get("team_counts") or {}).items()}
                       if fixed_rows else {})
        team_cap_report["min_teams_per_candidate"] = min(
            (len(f) for f in footprints), default=0)
        for team in sorted(candidates_on_team):
            members = candidates_on_team[team]
            bound = headroom(team_cap, fixed_teams.get(team, 0))
            # A row that CANNOT bind does not enter the matrix. Each entry takes
            # exactly one candidate, so this sum is at most E whatever the bank
            # holds, and a bound at or above E is vacuous: the feasible set is
            # identical with or without the row. Skipping it is not an
            # optimisation, it is what keeps a cap OPENED to 1.0 from moving a
            # solve it does not constrain -- measured on the golden replay,
            # where adding eight vacuous rows left `exposure_summary` and
            # `sp_pair_distribution` byte-identical and still moved 15 of 18
            # entry-to-lineup assignments through scipy's branch order. A
            # baseline that shuffles for no semantic reason is a baseline that
            # has stopped reporting construction drift.
            #
            # Deliberately NOT retrofitted to the three sibling ceilings above:
            # the same guard there would be correct and would move the frozen
            # baseline for a reason that has nothing to do with this item. Filed
            # rather than smuggled in.
            team_cap_report["teams_capped"].append(
                {"team": team, "count": team_cap,
                 "candidates_on_team": len(members),
                 "row_added": bool(bound < E)})
            if bound < E:
                add({x_idx(e, k): 1.0 for e in range(E) for k in members},
                    -np.inf, bound)
    elif team_cap and not team_by_player:
        # NOT a refusal, and the asymmetry with the game cap above is deliberate.
        # `max_game_exposure_pct_by_game` is never a posture default: it is set
        # by an operator who typed it (or the scalar it expands from) or by an
        # F5 material-weather cap, which the pipeline merges in by MIN
        # (R388(b) corrected "only ever an operator"). Each is an explicit
        # instruction about this slate, so a missing map means one cannot be
        # honoured and silence would be the R289 failure. This cap ships as a
        # POSTURE DEFAULT on every Classic build, so refusing here would turn a
        # caller that never passed a team map -- the legacy wrapper, a test, an
        # older door -- into a dead build. It is recorded as `unknown` and the
        # brief says the cap did not bind, which is the honest reading of "asked
        # and could not answer" rather than a cap silently reported as held.
        pass

    # R405. The consensus-cluster cap, in R343's shape: `total` denominator,
    # headroom for untouchable rows, the vacuous row skipped, the binding
    # diagnosis named. It caps how many ENTRIES take a lineup carrying k or more
    # of the bank's consensus hitters, which is the concentration the person,
    # team, game and stack caps cannot see: on 1905_10g nine hitters sat at the
    # 0.35 person cap and filled 36% of hitter slots, every lineup carried 2 of
    # them and 27 of 34 carried 3 or more, while the brief read 15 distinct
    # primary stacks and a 29% max team footprint. S class under R386.
    member_counts = [bank_member_counts[k] for k in kept_idx]
    cluster_high = [k for k in range(K) if member_counts[k] >= cluster_k]
    cluster_row_added = False
    if cluster_bound is not None and cluster_bound < E:
        add({x_idx(e, k): 1.0 for e in range(E) for k in cluster_high},
            -np.inf, float(cluster_bound))
        cluster_row_added = True
    cluster_report: Dict[str, Any] = {
        **{k: v for k, v in cluster.items() if k != "member_ids"},
        "min_members_k": cluster_k,
        "requested_pct": float(cluster_pct) if cluster_pct is not None else None,
        "count": cluster_cap,
        "status": ("not_requested" if not cluster_cap
                   else "no_cluster" if not cluster_members
                   else "applied" if cluster_row_added else "vacuous"),
        "row_added": cluster_row_added,
        "headroom": cluster_bound,
        "bank_candidates": len(bank_member_counts),
        "bank_candidates_below_k": sum(1 for n in bank_member_counts if n < cluster_k),
        "solved_candidates_below_k": sum(1 for n in member_counts if n < cluster_k),
        "solved_distinct_below_k": len({signatures[k] for k in range(K)
                                        if member_counts[k] < cluster_k}),
        **({"fixed_rows_at_k_or_more": fixed_cluster_high} if fixed_rows else {}),
        "note": "the bank's consensus hitters (share of the distinct lineups the "
                "unconstrained search built); deterministic review proxy, never "
                "a probability",
    }

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
    # R294(c), 2026-09-04. "Proven infeasible" is the label CLAUDE.md reserves
    # and it means scipy status 2, nothing else. This used to be the `else` of
    # `if timed_out`, so EVERY no-incumbent outcome that was not the clock got
    # the reserved word: status 3 (unbounded), status 4 (numerical trouble), and
    # -- the reachable one -- status 0 with an `x` that fails the integrality,
    # bounds or constraint verification twenty lines below, which is a solution
    # this module declined to trust rather than a proof that none exists. Two
    # readings measured 2026-09-04 rather than assumed, because a read has been
    # wrong on this board repeatedly. Status 3 is UNREACHABLE through this call
    # site: `Bounds(lower, upper)` is built from zeros and ones with the
    # incompatible entries clamped to 0.0, so every variable is bounded and a
    # bounded MILP cannot be unbounded (scipy 1.15.3 returns 3 only for a
    # genuinely unbounded variable, confirmed directly). Status 4 was NOT
    # produced in a probe of degenerate coefficient ranges, NaN in the matrix
    # and a zero time limit, so it is not claimed as a field sighting here. The
    # label is corrected anyway: the third state is the one status 0 reaches,
    # and it is exactly as cheap to be right about all three.
    proven_infeasible = scipy_status == 2
    mip_gap = getattr(result, "mip_gap", None)
    largest_contest = max(
        (len(v) for v in by_contest_entries.values()), default=0
    )
    solver_report = {
        "scipy_status": scipy_status,
        "status": {0: "optimal", 1: "time_limit", 2: "infeasible",
                   3: "unbounded", 4: "numerical_or_other"}.get(scipy_status, "other"),
        "message": solver_status,
        "time_limit_s": time_limit_s,
        "mip_gap": mip_gap,
        "optimality": None,
        "candidate_prefilter": prefilter_report,
        # R326. Which bank this certificate covers. Derived from the
        # prefilter's own `applied`, so it cannot disagree with it: a
        # restricted solve is one the prefilter actually restricted.
        "search_scope": "restricted" if prefilter_report["applied"] else "full",
        "full_bank_retry": (
            {
                "triggered": True,
                "trigger": "restricted_bank_proven_infeasible",
                "restricted_candidates_kept": (
                    (_search_state or {}).get("restricted_candidates_kept")),
                "restricted_candidates_in": (
                    (_search_state or {}).get("restricted_candidates_in")),
            }
            if _full_bank_retry else {"triggered": False}
        ),
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
        # R207: the interaction case is a proven infeasibility whose `binding`
        # below comes back empty, so it needs a value on every branch.
        binding: List[str] = []
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
        elif not proven_infeasible:
            # R294(c). The third state, which had no words of its own and took
            # the reserved ones. Nothing is diagnosed, no control is named, and
            # no ladder steps: naming a binding constraint here would assert a
            # diagnosis this solve did not make, and stepping a ladder would
            # relax a strategy control against a non-proof -- the same shape as
            # relaxing one against an unexhausted bank, which R98(2) already
            # forbids one branch over.
            errors = [
                f"entry-level joint MILP returned solver status {scipy_status} "
                f"({solver_report['status']}) with no verifiable incumbent. This "
                f"is NEITHER an infeasibility proof NOR the clock: nothing about "
                f"this slate, this bank or any control has been established, so "
                f"no relaxation ladder steps and no control is named as binding. "
                f"Solver message: {solver_status}. Re-run; if it repeats, the "
                f"model or the solver build is the subject, not a portfolio "
                f"control."
            ]
        else:
            binding = _diagnose_binding_constraints(
                E, stacks, sp_pairs, signatures, largest_contest, controls,
                feasibility_inputs=feasibility_inputs,
                # R405. Passed to THIS call, the one that writes `errors`, and
                # not only to the report call below: a refusal whose first line
                # cannot say BANK-LIMITED sends the operator to the cap instead
                # of the bank. The two R343/R333 reports stay on the report call
                # alone, as they shipped.
                consensus_cluster=cluster_report,
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
            # R286. One renderer, and the failing SLATE check leads it. Before
            # this call the two branches lived inline here and neither could see
            # `feasibility.checks`, so `errors[0]` was composed entirely from a
            # count over the bank while the checkpoint's own failing check sat
            # in the same brief with its remedy attached.
            errors = compose_infeasibility_errors(
                binding, controls, bank_flag,
                feasibility_checks=feasibility_checks,
            )
            # R98(2). Appended, never substituted: the arithmetic above is what
            # the solver proved and it stays first among the facts. What follows
            # is what to DO about it, and the order matters more than the words
            # -- on 1910_9g both lines above were true and the operator still
            # reached for the wrong lever, because nothing said the bank was
            # 1.8% explored.
            errors = errors + _infeasibility_remedies(
                bank_report, binding, feasibility_checks=feasibility_checks)

        # R326, 2026-09-09. The full-bank retry goes before EVERY rung below.
        # The prefilter reserves two compatible candidates per entry, which is
        # not Hall's condition, and its stack/SP-pair coverage loop keeps ONE
        # representative per bucket, which stops a bucket being EMPTY but not
        # its being under-filled against a repetition cap. So a restricted bank
        # can be infeasible while the bank the caller handed in is feasible, and
        # every rung below would then relax a STRATEGY control -- the reuse cap,
        # the five-stack quota, the primary-stack floor -- to pay for a search
        # filter's omission. Measured at the parent commit on a 440-candidate /
        # 49-entry default-path witness (no `candidate_prefilter_target` set,
        # keep_target = max(6E, 40) = 294): 3 MILP calls, candidate_reuse
        # relaxed twice, zero entries reported emptied, and errors[0] read "no
        # single control is arithmetically binding against this bank, so the
        # interaction of the active controls is" -- the exact diagnostic
        # CLAUDE.md's R157 clause licenses an operator to answer by OPENING
        # exposure caps. The same bank at keep_target = K: 1 call, 49 distinct
        # assignments, zero relaxations.
        #
        # Guarded on `proven_infeasible` like every rung below, and for the same
        # reason read the other way: a TIME LIMIT means the model was already too
        # big for the clock, and re-solving on a larger bank is the wrong
        # direction. `_search_state` makes this fire once, so a full bank that is
        # genuinely infeasible descends the rungs on the next pass instead of
        # recursing.
        if (proven_infeasible and (not slate_blocked) and not _probe
                and prefilter_report["applied"]
                and not _full_bank_retry):
            return select_and_assign_entries(
                _all_candidates, entry_requirements, portfolio_controls,
                bank_report=bank_report, fixed_exposure=fixed_exposure,
                feasibility_inputs=feasibility_inputs,
                feasibility_checks=feasibility_checks,
                interaction_probe_budget_s=interaction_probe_budget_s,
                interaction_probe_not_after=interaction_probe_not_after,
                # Every sibling state rides this re-entry, same rule as R116 and
                # R37(2)(b): the retry widens the SEARCH and must not silently
                # reset a ladder position the earlier passes paid for.
                _floor_state=_floor_state,
                _reuse_state=_reuse_state,
                _quota_state=_quota_state,
                _search_state={
                    "full_bank": True,
                    "restricted_candidates_kept": prefilter_report["candidates_kept"],
                    "restricted_candidates_in": prefilter_report["candidates_in"],
                },
            )

        # R116. The engine's own default goes FIRST, before the floor ladder
        # steps and before the refusal is written. The ordering is the point: a
        # primary-stack floor is a strategy control Ben decided on archive
        # evidence, and the reuse cap here is a number this function computed
        # thirty lines ago from the bank it happened to be handed. Relaxing the
        # engine's guess before anyone's decision is the only order that keeps
        # "the default de-concentrates" from turning into "the default cost you
        # the delivery". The same two rules the floor ladder follows apply: never
        # on a proven infeasibility only, and the step is COUNTED, never silent.
        # R294(b)(c). `proven_infeasible` replaces `not timed_out` on all three
        # guards: the ladders exist for a PROVEN infeasibility, and status 3, 4
        # and the unverifiable-incumbent case are none of the three. `not
        # slate_blocked` is (b): see the computation at the top of this function.
        if (proven_infeasible and (not slate_blocked) and not _probe
                and reuse_cap_source == "engine_default"):
            next_rung = (reuse_rungs[reuse_rung_index + 1]
                         if reuse_rung_index + 1 < len(reuse_rungs) else None)
            return select_and_assign_entries(
                _all_candidates, entry_requirements, portfolio_controls,
                bank_report=bank_report, fixed_exposure=fixed_exposure,
                feasibility_inputs=feasibility_inputs,
                feasibility_checks=feasibility_checks,
                interaction_probe_budget_s=interaction_probe_budget_s,
                interaction_probe_not_after=interaction_probe_not_after,
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
                # R37(2)(b), R116's rule applied to the third ladder: sibling
                # state rides every re-entry, or a step silently re-adds a
                # control this solve already proved infeasible and buys an extra
                # round trip per rung.
                _quota_state=_quota_state,
                # R326: and the search scope's, for the same reason.
                _search_state=_search_state,
            )

        # R37(2)(b), 2026-08-28. The five-stack quota steps BEFORE the
        # primary-stack floor, and the ordering is a judgment worth stating
        # rather than leaving to source order. Both are lower bounds sized off
        # the archive, so neither is the engine's own guess the way the reuse cap
        # above is; what separates them is the weight of evidence. The floor of 4
        # has three independent tranches behind it and put `<=3-primary` negative
        # every time. The quota is one dated decision old, sized off a field
        # share whose LIFT has moved in three directions across three tranches,
        # which is the reason the item made it read the share instead. Relax the
        # newer, thinner-evidenced control first. Only on a PROVEN infeasibility
        # (R294(c) widened this from "never on a timeout"), for the
        # reason the floor's own comment gives.
        if (proven_infeasible and (not slate_blocked) and not _probe
                and quota_report.get("applied_need")):
            q_ladder = five_stack_quota_rungs(quota_report["requested_share"])
            q_idx = int(quota_report.get("rung_index") or 0)
            if q_idx + 1 < len(q_ladder):
                q_stepped = list(quota_report.get("relaxation_steps") or [])
                q_stepped.append({
                    "from": quota_report["applied_share"],
                    "to": q_ladder[q_idx + 1],
                    "reason": (
                        "entry-level joint MILP proven infeasible with the "
                        "five-stack share quota active; the quota is one of the "
                        "controls whose interaction the solver could not satisfy"
                        + (", and it was already flagged reuse_dependent -- "
                           "fewer distinct qualifying candidates than the need"
                           if quota_report.get("reuse_dependent") else "")),
                    "trigger": "proven_infeasible_with_five_stack_quota",
                })
                return select_and_assign_entries(
                    _all_candidates, entry_requirements, portfolio_controls,
                    bank_report=bank_report, fixed_exposure=fixed_exposure,
                    feasibility_inputs=feasibility_inputs,
                    feasibility_checks=feasibility_checks,
                    interaction_probe_budget_s=interaction_probe_budget_s,
                    interaction_probe_not_after=interaction_probe_not_after,
                    _floor_state=_floor_state,
                    _reuse_state=_reuse_state,
                    _quota_state={
                        "rung_index": q_idx + 1,
                        "relaxations": int(quota_report.get("relaxations") or 0) + 1,
                        "relaxation_steps": q_stepped,
                    },
                    # R326: and the search scope's, for the same reason.
                    _search_state=_search_state,
                )

        # R37. The one re-entry. A PROVEN infeasibility with the floor active is
        # the case the ladder exists for, and relaxing beats refusing because a
        # refusal here leaves every reserved row blank. Only on a PROVEN
        # infeasibility (R294(c) widened this from "never on a timeout"): the
        # rule that a compute limit may not move a strategy control is the same
        # rule that stops a slow solve from quietly buying a looser portfolio,
        # and it is the rule the DU ladder already follows two modules over.
        if (proven_infeasible and (not slate_blocked) and not _probe
                and floor_report.get("applied") is not None):
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
                    feasibility_checks=feasibility_checks,
                    interaction_probe_budget_s=interaction_probe_budget_s,
                    interaction_probe_not_after=interaction_probe_not_after,
                    # R116: the reuse state rides the floor's re-entry too, or a
                    # ladder step would silently re-add the default this solve
                    # already proved infeasible and buy an extra round trip per
                    # rung.
                    _reuse_state=_reuse_state,
                    # R37(2)(b): and the quota's state, for the same reason.
                    _quota_state=_quota_state,
                    _floor_state={
                        "rung_index": rung_idx + 1,
                        "relaxations": int(floor_report.get("relaxations") or 0) + 1,
                        "relaxation_steps": stepped,
                    },
                    # R326: and the search scope's, for the same reason.
                    _search_state=_search_state,
                )

        # R294(c). Only a PROVEN infeasibility has binding constraints to name.
        # This read `[] if timed_out else ...`, so a status-3/4 or unverifiable
        # result published a binding-constraint list -- a diagnosis of a solve
        # that diagnosed nothing, in the field an operator reads first.
        solver_report["binding_constraints"] = (
            _diagnose_binding_constraints(
                E, stacks, sp_pairs, signatures, largest_contest, controls,
                feasibility_inputs=feasibility_inputs,
                team_exposure=team_cap_report, game_exposure=game_cap_report,
                consensus_cluster=cluster_report)
            if proven_infeasible else []
        )
        # R207. The interaction case, and only it: proven infeasible, every
        # ladder spent (this is the refusal they all fall through to), no
        # failing slate check and no bank-level finding. `errors` is written
        # above and not touched; the probe is a new key beside it.
        probe_block = None
        if (interaction_probe_budget_s is not None and not _probe
                and proven_infeasible and not slate_blocked and not binding
                # A partial bank's first remedy is to grow it (R98(2)); a
                # probe there is a number the next slice will change.
                and (bank_report or {}).get("job_list_exhausted") is not False):
            exhausted_reuse = {"rung_index": len(reuse_rungs)}

            def _resolve(trial: Dict[str, Any]) -> Dict[str, Any]:
                # The refused model, rebuilt: the same bank and entries, the
                # enforced controls and the same ladder states. At this refusal
                # the reuse ladder has always re-entered past its end first, so
                # an engine default is never in `controls`; an operator's cap
                # is, and dropping it also moves the ladder past its end, or an
                # engine default would re-enter where the probe removed it.
                return select_and_assign_entries(
                    _all_candidates, entry_requirements, trial,
                    bank_report=bank_report, fixed_exposure=fixed_exposure,
                    feasibility_inputs=feasibility_inputs,
                    feasibility_checks=feasibility_checks,
                    _floor_state=_floor_state, _quota_state=_quota_state,
                    _reuse_state=(exhausted_reuse
                                  if trial.get("max_candidate_reuse") is None
                                  else _reuse_state),
                    _search_state={"full_bank": True}, _probe=True)

            probe_block = _interaction_probe(
                _resolve, controls, total, float(interaction_probe_budget_s),
                not_after=interaction_probe_not_after)
        return {
            "passed": False, "assignments": [], "selection_certified": False,
            "allocation_certified": False, "allocation_method": "scipy_milp_entry_level",
            "allocation_solver_status": solver_status,
            "allocation_solver_report": solver_report,
            **({"interaction_probe": probe_block} if probe_block is not None else {}),
            "errors": errors,
            "candidate_reuse": dict(reuse_state_report),
            # R405. Known before the solve, so it rides the refusal: a refusal
            # on this cap is read against the bank's low-cluster count.
            "consensus_cluster": dict(cluster_report),
            # R406. And the sleeves' apportionment, for the same reason.
            "classic_sleeves": {k: v for k, v in sleeve_report.items()
                                if not k.startswith("_")},
            # R294(a). The refusal path is where an emptied entry matters most,
            # and it is the one path that carried no `warnings` key at all, so
            # the count lived only inside `solver_report.candidate_prefilter`
            # where a reader under a clock does not go. Emitted only when there
            # is something to say, so every other refusal is byte-identical.
            **({"warnings": list(prefilter_warnings)} if prefilter_warnings else {}),
            **({"primary_stack_floor": floor_report}
               if floor_report.get("status") != "not_requested" else {}),
            **({"five_stack_quota": quota_report}
               if quota_report.get("status") != "not_requested" else {}),
        }

    # A time-limited incumbent satisfies every constraint in the matrix; it is
    # simply not proven optimal. Verified above, accepted here, and named in the
    # result so "time_limited" is never inferred from silence.
    # R294(c). The success path had the same two words for three states. An
    # incumbent that verified against the constraint matrix under a status this
    # module cannot interpret is accepted -- the verification is what makes it
    # safe, and refusing a verified roster would be the blank-reserved-row
    # outcome CLAUDE.md calls the maximum washout -- but it is not "optimal",
    # which is a claim about the solve and not about the roster.
    solver_report["optimality"] = (
        "time_limited" if timed_out
        else "optimal" if scipy_status == 0
        else "accepted_unproven_status"
    )

    assignments: List[Dict[str, Any]] = []
    chosen_k: List[int] = []  # R405: the solved-bank index behind each assignment
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
        chosen_k.append(k)
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

    # R37(2)(b). The same discipline for the quota: it is a claim about the
    # delivered set, so it is counted off the assignments. `assigned_qualifying`
    # is what the file actually carries at or above `five_stack_min_size`, and it
    # is the number to read against `applied_need` -- the constraint is a lower
    # bound, so the solver may exceed it, and reading the request instead of the
    # realization is the mistake R153 named one module over.
    quota_block: Dict[str, Any] = {}
    if quota_report.get("status") != "not_requested":
        _min_size = int(quota_report.get("min_size") or 5)
        assigned_q = sum(1 for a in assignments
                         if int(a.get("primary_stack_size") or 0) >= _min_size)
        quota_block = {"five_stack_quota": {
            **dict(quota_report),
            "assigned_qualifying": assigned_q,
            "assigned_qualifying_share": (
                round(assigned_q / len(assignments), 4) if assignments else 0.0),
            "need_met": (assigned_q >= int(quota_report.get("applied_need") or 0)),
        }}

    # R405. What the DELIVERED set carries, counted off the assignments on the
    # R37 precedent: the cap is a claim about the output. `objective_median` is
    # the price of the protection in the build's own objective units, bank and
    # delivered side by side -- on 1905_10g the low-cluster candidates had a
    # median objective of 133.0 against the bank's 138.6. A median of a
    # deterministic objective, never a probability or an expected value.
    def _objective(c: Mapping[str, Any]) -> Optional[float]:
        for key in ("objective", "proj_points"):
            try:
                if c.get(key) is not None:
                    return float(c.get(key))
            except (TypeError, ValueError):
                continue
        return None

    def _median(values: Sequence[Optional[float]]) -> Optional[float]:
        vals = sorted(v for v in values if v is not None)
        if not vals:
            return None
        mid = len(vals) // 2
        return round(vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2, 3)

    delivered_counts = [member_counts[k] for k in chosen_k]
    delivered_high = sum(1 for n in delivered_counts if n >= cluster_k)
    cluster_block: Dict[str, Any] = {"consensus_cluster": {
        **cluster_report,
        "delivered_member_count_histogram": {
            str(n): c for n, c in sorted(Counter(delivered_counts).items())},
        "delivered_at_k_or_more": delivered_high,
        "delivered_share_at_k_or_more": (
            round(delivered_high / len(assignments), 4) if assignments else 0.0),
        "objective_median": {
            "bank": _median([_objective(c) for c in _all_candidates]),
            "bank_below_k": _median([
                _objective(c) for c, n in zip(_all_candidates, bank_member_counts)
                if n < cluster_k]),
            "delivered_below_k": _median([
                _objective(candidates[k]) for k in chosen_k
                if member_counts[k] < cluster_k]),
            "delivered_at_k_or_more": _median([
                _objective(candidates[k]) for k in chosen_k
                if member_counts[k] >= cluster_k]),
        },
    }}

    # R406. Each sleeve's delivered shape, as review proxies: the apex end
    # (mean and best contest-fit of its delivered lineups) and the washout end
    # (its most-rostered player's share and its share at k+ of R405's cluster).
    sleeve_block: Dict[str, Any] = {}
    if sleeve_report.get("status") in ("applied", "off", "no_sleeve_bank"):
        public = {k: v for k, v in sleeve_report.items() if not k.startswith("_")}
        if sleeve_report.get("status") == "applied":
            by_sleeve: Dict[str, List[int]] = defaultdict(list)
            sleeve_of = sleeve_report.get("sleeve_by_entry") or {}
            for e, k in enumerate(chosen_k):
                by_sleeve[sleeve_of.get(entry_ids[e], "projection")].append(e)
            delivered: Dict[str, Any] = {}
            for sleeve, members in sorted(by_sleeve.items()):
                fits = [raw_scores[(e, chosen_k[e])] for e in members]
                players = Counter(p for e in members for p in rosters[chosen_k[e]])
                high = sum(1 for e in members if member_counts[chosen_k[e]] >= cluster_k)
                delivered[sleeve] = {
                    "entries": len(members),
                    "apex_mean_fit": round(sum(fits) / len(fits), 4) if fits else None,
                    "apex_best_fit": round(max(fits), 4) if fits else None,
                    "washout_max_player_share": (
                        round(max(players.values()) / len(members), 4) if players else None),
                    "at_k_or_more_cluster": high,
                }
            public["delivered"] = delivered
        public["note"] = ("deterministic constructions over labeled priors; review "
                          "proxies, never a probability or an edge")
        sleeve_block = {"classic_sleeves": public}

    floor_warnings: List[str] = []
    _qr = quota_block.get("five_stack_quota") if quota_block else None
    if _qr:
        if _qr.get("relaxations"):
            floor_warnings.append(
                f"min_five_stack_share_pct relaxed {_qr['relaxations']} time(s): "
                f"requested {_qr['requested_share']}, applied "
                f"{_qr['applied_share'] if _qr['applied_share'] is not None else 'none'}. "
                f"A portfolio is not clean because the gates passed; it is clean "
                f"when the relaxation counts are zero"
            )
        if _qr.get("reuse_dependent"):
            floor_warnings.append(
                f"min_five_stack_share_pct is satisfiable only through candidate "
                f"REUSE on this bank: {_qr['qualifying_candidates']} distinct "
                f"candidate(s) at primary stack size >= {_qr['min_size']} against a "
                f"need of {_qr['applied_need']}. The quota held here, and it is the "
                f"first control to suspect if a later solve on this bank proves "
                f"infeasible"
            )
    # R340 fix (2). The brief says WHICH of the two a missing size was, on
    # either report that carries the verdict. `bank_never_asked_for_size` is a
    # defect in the wiring and reads as one; `bank_asked_and_could_not` is a
    # fact about the pool or the clock and reads as one. Reported for both
    # reports from one loop so the two can never drift apart.
    for _label, _rep in (("min_five_stack_share_pct", _qr),
                         ("primary_stack_min_size",
                          (floor_block or {}).get("primary_stack_floor"))):
        _verdict = (_rep or {}).get("bank_stack_request") or {}
        if _verdict.get("status") == "bank_never_asked_for_size":
            floor_warnings.append(
                f"{_label} found no qualifying candidate because the BANK WAS "
                f"NEVER ASKED for that stack size (asked for "
                f"{_verdict.get('requested_sizes')}). That is a wiring fact, "
                f"not a thin pool: the control filtered a bank that could not "
                f"contain what it was filtering for (R340)")
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
        **quota_block,
        **reuse_block,
        **cluster_block,
        **sleeve_block,
        "passed": True,
        "assignments": assignments,
        "selection_certified": True,
        "allocation_certified": True,
        "allocation_method": "scipy_milp_entry_level",
        "allocation_solver_status": solver_status,
        "allocation_solver_report": solver_report,
        "allocation_optimality": solver_report["optimality"],
        "warnings": control_warnings + floor_warnings + reuse_warnings
        + prefilter_warnings + (
            [f"allocation accepted from a time-limited incumbent at gap "
             f"{'unknown' if mip_gap is None else format(float(mip_gap), '.4f')}; "
             f"every constraint verified, optimality not proven"]
            if timed_out else []
        ) + (
            [f"allocation accepted from an incumbent returned under solver "
             f"status {scipy_status} ({solver_report['status']}), which is "
             f"neither optimal nor the clock; every constraint in the matrix was "
             f"verified against this roster, and nothing beyond that is claimed"]
            if solver_report["optimality"] == "accepted_unproven_status" else []
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
            # R343. The resolved COUNT, beside the four that were already here.
            # A reader consulting this block to answer "what actually
            # constrained this solve" got no answer about the team footprint at
            # all, which is the same gap R116 closed for the reuse cap.
            "max_team_count": team_cap,
            # R405. The resolved count, for the same reason.
            "max_consensus_cluster_count": cluster_cap,
        },
        # R333 / R343. Both washout-axis caps report whether they were WIRED,
        # not just what was asked for: `unknown` means the id map was absent, so
        # the cap did not bind and nothing here should be read as though it did.
        "game_exposure": game_cap_report,
        "team_exposure": team_cap_report,
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
