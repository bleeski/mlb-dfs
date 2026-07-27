"""
MLB Classic Optimizer — v3.18 (coverage-guaranteed candidate bank)
Framework integration: MLB Classic v2.16.0

v3.18 additions:
  - resolve_candidate_bank_size() no longer collapses large requests to a hard 40:
    the 10+ branch is ceil(requested * 2) under a raised DEFAULT_CANDIDATE_BANK_CAP,
    so a 35-entry field targets ~70 candidates instead of 40.
  - build_diverse_candidate_bank(): wraps build_candidate_lineup_bank, then
    deterministically forces additional legal lineups across every viable SP pair
    (breadth) and rotating team stacks (depth), deduped by exact player set, until
    the bank both covers the viable SP pairs and reaches the target size. This fixes
    the thin-slate collapse where the overlap-repulsion heuristic halts early and the
    bank clusters on a couple of SP pairs, which no exposure cap can repair because
    the missing diversity was never generated. Changes no projection and no MILP hard
    constraint; deterministic review input, never a win-rate, ROI, or probability claim.

v3.17 additions:
  - Runtime-neutral provenance text (no assumptions about which assistant runtime executes the solver).
  - bank_coverage_report(): one unconstrained ceiling solve compared against the
    candidate bank's best raw ceiling, so a starved bank is a visible number
    instead of a silent quality loss in the joint allocation.

Prior lineage: v3.16 (slot-lock reliability patch) on MLB Classic v2.15.0
Code lineage/base: v2.11.1
Compiled: 2026-06-11 (v3.16 slot-lock reliability patch)

v3.16 additions:
  - Exact DraftKings slot variables (P1/P2/C/1B/2B/3B/SS/OF1/OF2/OF3).
  - locked_slot_assignments hard-locks players to exact upload slots.
  - Output includes Assigned_Slot while preserving Assigned_Position.

v3.14 additions:
  - Added scipy MILP final-portfolio selection with DU/overlap, anchor, SP-pair,
    right-tail, and redundancy controls applied to the selected subset.
  - Candidate banks default to lighter bank-level constraints; final portfolio
    certification now occurs after subset selection rather than across all candidates.
  - Added candidate-by-contest-shape score matrices for heterogeneous contest grids.
  - Missing volatility tiers are UNKNOWN/neutral rather than inferred from ceiling-floor spread.
  - Small-slate SP-pair coverage defaults to weighted soft coverage; hard all-pairs
    requires an explicit override.

v3.13 additions:
  - Added capped batting-order cluster scoring for primary and secondary stacks.
  - Candidate selection now rewards connected/wraparound order clusters and penalizes bottom-only clusters without changing F1-F5 or MILP constraints.
  - Added role-elevation diagnostics for promoted hitters and top-five value.

v3.12 additions:
  - Added small-slate SP Pair Coverage Plan helpers and validation.
  - build_multi_lineup can hard-seed audited viable SP pairs before filler builds.
  - candidate-bank final selection can preserve required SP-pair coverage.

v3.11 additions:
  - Added stack-adjacency review diagnostic for candidate-bank outputs.
  - Keeps matchup micro-signals in projection notes/F4; optimizer consumes only resolved projections.

v3.10 additions:
  - Added Field_Exposure_Delta diagnostics versus projected field ownership.
  - Added stack-archetype exposure counts (5-3, 4-2-2, etc.).
  - Added right-tail volatility tier summaries and candidate scoring bonus.
  - Added contest-shape profiles for post-solve candidate selection.

v3.9 additions:
  - Added candidate-bank wrapper via build_candidate_lineup_bank().
  - Added deterministic WTA_First_Place_Proxy and Portfolio_EV_Proxy scoring.
  - Added Meta-Lineup field-pressure scoring and portfolio redundancy diagnostics.
  - Added final subset helper select_final_portfolio_from_candidate_bank().

v3.8 additions:
  - Salary suppression activation now supports SALARY_SUPPRESSION:<trigger>
    tags for metric_disconnect, role_elevation, late_news, and environment.
  - Legacy DIVERGENCE_LEVERAGE:value remains backward-compatible for one
    transition version, but new projection CSVs should use SALARY_SUPPRESSION.
  - Added deterministic wind_bearing_to_f5_label helper for translating
    meteorological wind bearings into out/in/cross using CF azimuth.
  - Chalk one-off labels updated for trigger-specific suppression tags.

v3.7 anchor exposure additions:
  - build_multi_lineup supports max_sp_exposure and max_sp_pair_repetition.
  - Anchor exposure control is separate from Diversification Units; SP pair
    remains an anchor unit and remains penalty-immune in DU retry logic.
  - build_single_lineup supports forbidden_player_combos for pair-level caps.
  - build_multi_lineup returns anchor_validation alongside du_validation.

v3.6 runtime/provenance additions:
  - scipy.optimize.milp is the sole supported MILP backend in the project runtime.
  - runtime_preflight() and optimizer_provenance_line() expose dependency/backend status.
  - All legacy alternate-backend references removed from the executable contract.

v3.4 additions preserved (Diversification Units enforcement, per Framework v2.7):
  - DU unit registry: 5 units (sp_pair, primary_stack, secondary_stack,
    game_environment, chalk_one_off). SP pair excluded from within-family
    distance (anchor unit per Framework v2.7 §4e).
  - Bucket Rules per unit (deterministic) — see compute_unit_signature.
  - Threshold table by (portfolio size class, contest mode).
  - Threshold-only relaxation order (no unit-removal mechanic).
  - Post-solve DU validation with deterministic penalty rotation:
      Retry 1 → chalk_one_off; Retry 2 → secondary_stack;
      Retry 3 → game_environment. Single-unit penalty per retry.
      Penalties always computed against the BASE shell (snapshot before
      retry loop), not against intermediate retry results.
      Primary stack and SP pair are intentionally penalty-immune.
  - Provenance Block 7th line via build_multi_lineup return dict.
  - validate_du_portfolio: post-solve and Phase-5 revalidation entry point;
    operates on precomputed signatures.
  - Modified build_multi_lineup: returns dict adds 'du_validation' and
    'du_signatures' fields. Existing 'lineups', 'failed_indices', and
    'max_overlap_base' fields preserved; lineup records gain optional
    'du_retry_count' and 'du_relaxation_idx' keys when applicable.

v3.3 additions preserved (suppression layer): see v3.3 history.
v3.1 fixes preserved (carried forward from v3.2.1 bundle).
v2 fixes preserved.
"""

import time as _time

import pandas as pd
from collections import Counter
from math import ceil

from mlb_engine.contest_shapes import (
    CONTEST_SHAPES, OBJECTIVE_CLASS_BY_SHAPE, is_ticket_line, objective_class,
)
from mlb_engine.determinism import hash_seed_report, stable_ids, stable_union

try:
    import scipy  # noqa: F401
    SCIPY_AVAILABLE = True
    SCIPY_IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover - environment-dependent
    SCIPY_AVAILABLE = False
    SCIPY_IMPORT_ERROR = str(exc)

OPTIMIZER_VERSION = 'v3.22'
LAST_SOLVER_BACKEND = None
LAST_SOLVER_STATUS = None

# ============================================================================
# v3.20 (F13) solver timeout semantics
#
# The MILP time limit was the literal 30 hardcoded at the call site, and scipy
# reports ``success=False`` when it hits that limit even when ``result.x``
# carries a feasible incumbent. The old code discarded both facts: it returned a
# bare ``None`` and the caller could not tell a clock from a proven-infeasible
# problem. It responded to the clock by climbing the overlap ladder and stepping
# DU relaxation, so a compute limit was recorded as a strategy change. CLAUDE.md
# forbids exactly that inversion: an infrastructure limit may reduce search
# effort, it may never reduce the legal player set or the construction rules.
#
# Three things change here. The limit is a named default and is threaded from
# the caller. Every solve reports a structured status through an explicit
# ``status_out`` dict rather than a module global that the next solve overwrites.
# A time-limited incumbent is verified against the constraint matrix and then
# accepted, tagged ``optimality='time_limited'``, instead of thrown away.
# ============================================================================

SOLVER_TIME_LIMIT_S = 30.0
# Below this, a solve has no useful chance and the reserve arithmetic degenerates.
MIN_SOLVER_TIME_LIMIT_S = 0.001

# scipy.optimize.milp status -> the only distinction the caller has to act on.
SCIPY_MILP_STATUS = {
    0: 'optimal',
    1: 'time_limit',
    2: 'infeasible',
    3: 'unbounded',
    4: 'other',
}

LAST_SOLVER_RESULT: dict = {}


def _new_solver_status() -> dict:
    """A fresh, fully-populated status record. Never partially filled."""
    return {
        'backend': 'scipy_milp',
        'status': 'not_run',
        'scipy_status': None,
        'message': '',
        'timed_out': False,
        'proven_infeasible': False,
        'optimality': None,
        'mip_gap': None,
        'time_limit_s': None,
        'elapsed_s': None,
        'incumbent_rejected': False,
    }


def _record_solver_status(status_out, **fields) -> dict:
    """Fill ``status_out`` in place, mirror to the module globals, return it.

    The globals are kept because older callers read them; they remain unsafe for
    anything but a single solve, which is why the structured record is passed in
    by the caller instead.
    """
    global LAST_SOLVER_BACKEND, LAST_SOLVER_STATUS, LAST_SOLVER_RESULT
    record = status_out if status_out is not None else _new_solver_status()
    for key in _new_solver_status():
        record.setdefault(key, None)
    record.update(fields)
    LAST_SOLVER_BACKEND = record.get('backend')
    LAST_SOLVER_STATUS = record.get('message') or record.get('status')
    LAST_SOLVER_RESULT = dict(record)
    return record


def resolve_solver_time_limit(time_limit_s=None, remaining_s=None):
    """The seconds one solve may take, bounded by the budget it must fit inside.

    ``remaining_s`` is what is left of the caller's wall-clock budget. Shrinking
    the per-solve limit to fit is the correct response to a tight budget: it
    reduces search effort and nothing else. Trimming the player pool to fit a
    compute limit is the response CLAUDE.md forbids, and this function exists so
    that the cheap correct lever is always available.
    """
    limit = SOLVER_TIME_LIMIT_S if time_limit_s is None else float(time_limit_s)
    if remaining_s is not None:
        limit = min(limit, float(remaining_s))
    return max(MIN_SOLVER_TIME_LIMIT_S, limit)

# ============================================================================
# v3.3 constants (unchanged)
# ============================================================================

SALARY_CAP = 50000
POSITION_SLOTS = [('P', 2), ('C', 1), ('1B', 1), ('2B', 1), ('3B', 1), ('SS', 1), ('OF', 3)]
EXACT_ROSTER_SLOTS = [('P1', 'P'), ('P2', 'P'), ('C', 'C'), ('1B', '1B'), ('2B', '2B'), ('3B', '3B'), ('SS', 'SS'), ('OF1', 'OF'), ('OF2', 'OF'), ('OF3', 'OF')]
ROSTER_SIZE = 10
MIN_GAMES = 2
MAX_HITTERS_PER_TEAM = 5
HITTER_POSITIONS = {'C', '1B', '2B', '3B', 'SS', 'OF'}
MAX_OVERLAP_CEILING = ROSTER_SIZE - 2

SUPPRESSION_TIEBREAKER_WEIGHT = 0.0003
SUPPRESSION_PER_PLAYER_CAP = 0.25
SUPPRESSION_LINEUP_CAP = 0.75
DIVERGENCE_VALUE_TAG = 'DIVERGENCE_LEVERAGE:value'

# ============================================================================
# v3.8 constants — Salary Suppression Trigger inventory
# ============================================================================

SALARY_SUPPRESSION_TAG_PREFIX = 'SALARY_SUPPRESSION:'
SALARY_SUPPRESSION_TRIGGERS = (
    'metric_disconnect',
    'role_elevation',
    'late_news',
    'environment',
)

_SUPPRESSION_TRIGGER_PRIORITY = {
    'metric_disconnect': 0,
    'role_elevation': 1,
    'late_news': 2,
    'environment': 3,
}

SUPPRESSION_ONE_OFF_LABELS = {
    'metric_disconnect': 'metric-disconnect-one-off',
    'role_elevation': 'role-elevation-one-off',
    'late_news': 'late-news-one-off',
    'environment': 'environment-one-off',
}

# ============================================================================
# v3.4 constants (Diversification Units)
# ============================================================================

DU_UNIT_NAMES = [
    'sp_pair',
    'primary_stack',
    'secondary_stack',
    'game_environment',
    'chalk_one_off',
]
DU_ANCHOR_UNITS = ['sp_pair']

# Penalty rotation (B1 round 2): retry 1 → element 0, retry 2 → element 1, etc.
# Order chosen by structural disruption (least → most).
# Primary stack and SP pair are penalty-immune.
DU_PENALTY_ROTATION = ['chalk_one_off', 'secondary_stack', 'game_environment']

MAX_DU_PENALTY_RETRIES = 3
DU_PENALTY_MAGNITUDE = 0.5

DU_THRESHOLD_TABLE = {
    ('1', 'any'): (None, None),
    ('2-3', 'gpp'): (1, None),
    ('2-3', 'wta'): (1, 1),
    ('4+', 'multi_entry_gpp'): (2, None),
    ('4+', 'wta'): (1, 2),
}

# A1 round-4 fix: sentinel for auto-derived DU threshold. The default
# behavior of build_multi_lineup must enforce DU; explicit None disables it.
_DU_AUTO = '__auto__'

DU_RELAXATION_ORDER = [
    ('across_family', 2, 1),
    ('within_family', 2, 1),
    ('across_family', 1, 0),
    ('within_family', 1, 0),
]

PRIMARY_STACK_MIN_HITTERS = 3
SECONDARY_STACK_MIN_HITTERS = 2
HIGH_TOTAL_THRESHOLD = 9.5
WIND_OUT_THRESHOLD = 10
PRECIP_LEVERAGED_THRESHOLD = 0.40

DIVERGENCE_LEVERAGE_TAG = 'DIVERGENCE_LEVERAGE:leverage'

_OWNERSHIP_PRIORITY = {'Low': 0, 'Mid': 1, 'High': 2}

# ============================================================================
# v3.12 constants — Small-slate SP Pair Coverage Plan
# ============================================================================

DEFAULT_SP_AUDIT_STATUS_COLUMN = 'Pitcher_Audit_Status'
REQUIRED_SP_AUDIT_STATUSES = ('verified_starter', 'declared_probable_sp')
OPTIONAL_SP_AUDIT_STATUSES = ('viable_bulk_or_alt_sp',)
EXCLUDED_SP_AUDIT_STATUSES = ('leverage_only_uncertain_role', 'explicit_exclude')
SP_PAIR_COVERAGE_POLICIES = (
    'hard_all_pairs',
    'soft_unique_pairs',
    'archetype_coverage',
    'disabled',
)


class StackInfeasibleError(Exception):
    """Raised when a declared stack is infeasible under salary/roster constraints."""
    pass


# ============================================================================
# v3.6 runtime / optimizer provenance helpers
# ============================================================================

def runtime_preflight():
    """Return dependency and backend availability for execution provenance.

    Runtime contract: scipy.optimize.milp is the only supported MILP backend
    for optimizer-certified MLB Classic builds, regardless of which assistant
    runtime executes the solver.
    """
    return {
        'optimizer_version': OPTIMIZER_VERSION,
        'pandas_available': True,
        'scipy_available': SCIPY_AVAILABLE,
        'scipy_import_error': SCIPY_IMPORT_ERROR,
        'supported_backend': 'scipy_milp',
        'active_backend_if_auto': 'scipy_milp' if SCIPY_AVAILABLE else None,
        'optimizer_certifiable': SCIPY_AVAILABLE,
        # F19: carried into run provenance so an archived build states whether
        # it ran with the hash seed pinned, rather than leaving it assumed.
        'hash_seed': hash_seed_report(),
    }


CORE_PROJECTION_FIELDS = (
    'Player_ID', 'Name', 'Team', 'Opponent', 'Position', 'Salary', 'Game_ID',
    'Floor', 'Ceiling', 'Excluded', 'Locked',
)
OPTIONAL_PROJECTION_FIELDS = (
    'Base_Projection', 'Ownership_Tier', 'Confidence_Tier', 'Stack_Group',
    'Batting_Order', 'Notes', 'Salary_Suppression', 'Base_Projection_MetaLineup',
    'Right_Tail_Volatility_Tier',
)

def validate_projection_schema(projections_df):
    """Validate the lean optimizer contract; optional enrichment never blocks."""
    missing = [c for c in CORE_PROJECTION_FIELDS if c not in projections_df.columns]
    ceiling_floor_errors = 0
    if not missing and len(projections_df):
        ceiling_floor_errors = int((projections_df['Ceiling'].astype(float) < projections_df['Floor'].astype(float)).sum())
    return {
        'passed': not missing and ceiling_floor_errors == 0,
        'missing_core_fields': missing,
        'available_optional_fields': [c for c in OPTIONAL_PROJECTION_FIELDS if c in projections_df.columns],
        'ceiling_below_floor_rows': ceiling_floor_errors,
        'summary': 'Lean projection schema passed' if not missing and ceiling_floor_errors == 0 else 'Lean projection schema failed',
    }


def optimizer_provenance_line():
    """Return the exact provenance line callers must surface in Phase 4."""
    preflight = runtime_preflight()
    if LAST_SOLVER_BACKEND == 'scipy_milp':
        return 'Optimizer provenance: optimizer_v3.py / scipy.optimize.milp executed successfully in this runtime.'
    if preflight['active_backend_if_auto'] == 'scipy_milp':
        return 'Optimizer provenance: scipy.optimize.milp available; no solve has executed in this process yet.'
    return 'Optimizer provenance: not optimizer certified. No supported MILP backend available in this runtime.'


def _select_solver_backend(requested='auto'):
    if requested not in ('auto', 'scipy_milp'):
        raise ValueError("solver_backend must be one of: 'auto', 'scipy_milp'")
    if not SCIPY_AVAILABLE:
        raise RuntimeError(f'scipy MILP backend unavailable: {SCIPY_IMPORT_ERROR}')
    return 'scipy_milp'


# ============================================================================
# v3.3 helpers (unchanged)
# ============================================================================

def _parse_positions(pos_string):
    """Parse DK position string (e.g., 'C/1B', 'OF', 'P') into a set."""
    if pd.isna(pos_string):
        return set()
    return set(p.strip() for p in str(pos_string).split('/'))


def _has_suppression_tag(notes_value):
    """Return True when Notes contains an MLB v3.8 salary-suppression tag.

    New projection CSVs should use SALARY_SUPPRESSION:<trigger>. The legacy
    DIVERGENCE_LEVERAGE:value tag remains supported by _compute_suppression_bonus
    for transition compatibility, but this helper intentionally checks only
    the new v3.8 prefix.
    """
    if notes_value is None or pd.isna(notes_value):
        return False
    return SALARY_SUPPRESSION_TAG_PREFIX in str(notes_value)


def _suppression_trigger(notes_value):
    """Return the highest-priority SALARY_SUPPRESSION trigger in Notes.

    If multiple tags are present defensively, framework priority order wins.
    Returns None when no new-style suppression trigger is present.
    """
    if notes_value is None or pd.isna(notes_value):
        return None
    notes = str(notes_value)
    found = [
        trigger for trigger in SALARY_SUPPRESSION_TRIGGERS
        if f'{SALARY_SUPPRESSION_TAG_PREFIX}{trigger}' in notes
    ]
    if not found:
        return None
    found.sort(key=lambda t: _SUPPRESSION_TRIGGER_PRIORITY.get(t, 99))
    return found[0]


def _compute_suppression_bonus(df):
    """Compute capped per-player suppression bonus.

    v3.8 source-of-truth activation is the dual gate:
      1. Notes contains SALARY_SUPPRESSION:<trigger>; and
      2. Salary_Suppression > 0.

    Legacy DIVERGENCE_LEVERAGE:value also activates for one transition version
    so older projection CSVs do not silently lose their tiebreaker.
    """
    bonus = {}
    if 'Salary_Suppression' not in df.columns or 'Notes' not in df.columns:
        return bonus

    for _, row in df.iterrows():
        notes = row.get('Notes', '')
        if pd.isna(notes):
            notes = ''
        notes = str(notes)
        active_tag = f'{SALARY_SUPPRESSION_TAG_PREFIX}role_elevation' in notes
        if not active_tag:
            continue
        sup = row.get('Salary_Suppression', 0)
        if pd.isna(sup):
            continue
        try:
            sup_val = float(sup)
        except (TypeError, ValueError):
            continue
        if sup_val <= 0:
            continue
        raw = sup_val * SUPPRESSION_TIEBREAKER_WEIGHT
        bonus[row['Player_ID']] = min(raw, SUPPRESSION_PER_PLAYER_CAP)

    return bonus

def _check_stack_feasibility(projections_df, stack_constraints, locked_player_ids=None):
    """Pre-flight check: can a declared stack fit under the salary cap?
    Returns None on success. Raises StackInfeasibleError on failure.
    """
    if not stack_constraints:
        return None

    if locked_player_ids:
        return None

    locked_player_ids = locked_player_ids or []

    team = stack_constraints['team']
    min_size = stack_constraints.get('min_size', 3)

    stack_eligible = projections_df[
        (projections_df['Team'] == team) &
        (projections_df['Position'].apply(
            lambda p: bool(_parse_positions(p) & HITTER_POSITIONS)
        ))
    ].copy()

    if len(stack_eligible) < min_size:
        raise StackInfeasibleError(
            f"Declared {min_size}-stack for {team} is infeasible: "
            f"only {len(stack_eligible)} eligible hitters in pool. "
            f"Revise the stack declaration."
        )

    min_stack_cost = stack_eligible.nsmallest(min_size, 'Salary')['Salary'].sum()

    remaining_slots = ROSTER_SIZE - min_size
    if remaining_slots <= 0:
        return None

    fill_eligible = projections_df[
        (projections_df['Team'] != team) &
        (~projections_df['Player_ID'].isin(locked_player_ids))
    ].copy()

    if len(fill_eligible) < remaining_slots:
        raise StackInfeasibleError(
            f"Declared {min_size}-stack for {team} is infeasible: "
            f"only {len(fill_eligible)} non-stack players available for "
            f"{remaining_slots} fill slots. Revise the stack declaration."
        )

    min_fill_cost = fill_eligible.nsmallest(remaining_slots, 'Salary')['Salary'].sum()
    min_total_cost = min_stack_cost + min_fill_cost

    if min_total_cost > SALARY_CAP:
        raise StackInfeasibleError(
            f"Declared {min_size}-stack for {team} is infeasible under "
            f"${SALARY_CAP:,} salary cap: minimum cost ${min_total_cost:,} "
            f"(stack ${min_stack_cost:,} + cheapest fill ${min_fill_cost:,}). "
            f"Revise the stack declaration (consider a smaller stack size) "
            f"or loosen locks if any are applied."
        )

    return None


# ============================================================================
# v3.3 build_single_lineup (unchanged)
# ============================================================================

# ============================================================================
# v3.21 (F21) the Excluded column has exactly one reading
#
# Four sites did `df[df['Excluded'] == False]`. That comparison is False for
# NaN, for None, and for the string "False", so any of those dropped the row.
# The column is only defaulted when it is absent entirely, so a projections
# override built by hand, or any CSV round-trip that leaves one cell blank,
# silently removed that player from the legal pool. It also shrank the SP-cap
# denominator, so the auto anchor caps were computed against a pool that no
# longer matched the salary file.
#
# This is the pool reduction CLAUDE.md forbids, arriving from a data condition
# instead of a compute limit, and invisible in the certified output.
#
# The reading is now: only an affirmative token excludes. Blank, missing and
# false-ish keep the player. An unrecognized token also keeps the player and is
# counted and named in the pool report, because the failure this closes is
# players disappearing, and guessing "exclude" on an ambiguous cell would
# reintroduce it in a new costume.
# ============================================================================

EXCLUDED_TRUE_TOKENS = frozenset({
    'true', 't', 'yes', 'y', '1', 'x', 'exclude', 'excluded', 'drop', 'out',
})
EXCLUDED_FALSE_TOKENS = frozenset({
    'false', 'f', 'no', 'n', '0', '', 'nan', 'none', 'null', 'na', 'n/a',
    'include', 'included', 'in', '-',
})


def excluded_flags(projections_df):
    """(boolean Series, report). The only reading of the Excluded column.

    The Series is always aligned to ``projections_df`` and always real booleans,
    so callers can filter with it directly instead of comparing to False.
    """
    report = {
        'column_present': False,
        'rows': int(len(projections_df)) if projections_df is not None else 0,
        'excluded_true': 0,
        'coerced_from_blank': 0,
        'coerced_from_text': 0,
        'unrecognized_kept': 0,
        'unrecognized_values': [],
        'note': 'only an affirmative Excluded token removes a player; blank and '
                'unrecognized cells keep the player and are counted here',
    }
    if projections_df is None or 'Excluded' not in getattr(projections_df, 'columns', []):
        return pd.Series(False, index=getattr(projections_df, 'index', None)), report

    report['column_present'] = True
    raw = projections_df['Excluded']
    flags = []
    unrecognized = []
    for value in raw:
        if isinstance(value, bool):
            flags.append(value)
            continue
        if value is None or (not isinstance(value, str) and pd.isna(value)):
            report['coerced_from_blank'] += 1
            flags.append(False)
            continue
        if isinstance(value, (int, float)):
            flags.append(bool(value))
            continue
        token = str(value).strip().lower()
        if token in EXCLUDED_TRUE_TOKENS:
            report['coerced_from_text'] += 1
            flags.append(True)
            continue
        if token in EXCLUDED_FALSE_TOKENS:
            if token in ('', 'nan', 'none', 'null', 'na', 'n/a'):
                report['coerced_from_blank'] += 1
            else:
                report['coerced_from_text'] += 1
            flags.append(False)
            continue
        report['unrecognized_kept'] += 1
        unrecognized.append(str(value))
        flags.append(False)

    series = pd.Series(flags, index=projections_df.index, dtype=bool)
    report['excluded_true'] = int(series.sum())
    report['unrecognized_values'] = sorted(set(unrecognized))[:10]
    return series, report


def coerce_excluded_column(projections_df):
    """Return a copy whose Excluded column is real booleans, plus the report."""
    if projections_df is None or not hasattr(projections_df, 'columns'):
        return projections_df, excluded_flags(projections_df)[1]
    flags, report = excluded_flags(projections_df)
    out = projections_df.copy()
    out['Excluded'] = flags if report['column_present'] else False
    return out, report


def _drop_excluded_rows(df):
    """The one place the Excluded column can remove a player from the pool."""
    if 'Excluded' not in getattr(df, 'columns', []):
        return df
    flags, _ = excluded_flags(df)
    return df[~flags]


def _prepare_single_lineup_df(
    projections_df,
    target='ceiling',
    locks=None,
    excludes=None,
    stack_constraints=None,
    skip_feasibility_check=False,
    penalized_players=None,
    apply_suppression=True,
):
    """Shared preprocessing for all single-lineup solver backends."""
    if not skip_feasibility_check:
        _check_stack_feasibility(projections_df, stack_constraints, locks)

    df = projections_df.copy()
    if excludes:
        df = df[~df['Player_ID'].isin(excludes)]
    df = _drop_excluded_rows(df)  # F21: one reading of the column, counted

    df['_pos_set'] = df['Position'].apply(_parse_positions)

    value_col = 'Ceiling' if target == 'ceiling' else 'Floor'
    if penalized_players:
        df['_obj'] = df.apply(
            lambda r: r[value_col] - penalized_players.get(r['Player_ID'], 0),
            axis=1
        )
    else:
        df['_obj'] = df[value_col]

    if apply_suppression:
        suppression_bonus = _compute_suppression_bonus(df)
    else:
        suppression_bonus = {}

    return df, suppression_bonus


def _build_lineup_output_from_selected(df, selected, suppression_bonus):
    """Build lineup output with both generic position and exact DK slot."""
    generic_by_slot = dict(EXACT_ROSTER_SLOTS)
    lineup_rows = []
    for pid, assigned_slot in selected:
        row = df[df['Player_ID'] == pid].iloc[0].to_dict()
        row['Assigned_Slot'] = assigned_slot
        row['Assigned_Position'] = generic_by_slot[assigned_slot]
        row['Suppression_Objective_Bonus'] = suppression_bonus.get(pid, 0.0)
        lineup_rows.append(row)

    slot_order = {slot: i for i, (slot, _) in enumerate(EXACT_ROSTER_SLOTS)}
    lineup_rows.sort(key=lambda row: slot_order[row['Assigned_Slot']])
    lineup_df = pd.DataFrame(lineup_rows)
    if '_pos_set' in lineup_df.columns:
        lineup_df = lineup_df.drop(columns=['_pos_set'])
    objective_value = sum(
        row['_obj'] + row['Suppression_Objective_Bonus'] for row in lineup_rows
    )
    return lineup_df, objective_value


def _build_single_lineup_scipy(
    df,
    suppression_bonus,
    locks=None,
    locked_slot_assignments=None,
    stack_constraints=None,
    bringback_constraint=None,
    overlap_reference=None,
    max_overlap=None,
    stack_core_blocklist=None,
    forbidden_player_combos=None,
    time_limit_s=None,
    status_out=None,
):
    """SciPy MILP backend with exact DraftKings slot assignment locks."""
    if not SCIPY_AVAILABLE:
        raise RuntimeError(f'scipy MILP backend unavailable: {SCIPY_IMPORT_ERROR}')

    import numpy as np
    from scipy.optimize import Bounds, LinearConstraint, milp
    from scipy.sparse import coo_matrix

    assign_keys = []
    required_by_slot = dict(EXACT_ROSTER_SLOTS)
    for _, row in df.iterrows():
        pid = row['Player_ID']
        for slot, required_pos in EXACT_ROSTER_SLOTS:
            if required_pos in row['_pos_set']:
                assign_keys.append((pid, slot))
    if not assign_keys:
        _record_solver_status(
            status_out, status='no_assignment_variables',
            message='no_assignment_variables', proven_infeasible=True,
            time_limit_s=resolve_solver_time_limit(time_limit_s),
        )
        return None, None

    assign_index = {key: idx for idx, key in enumerate(assign_keys)}
    n_assign = len(assign_keys)
    game_ids = list(df['Game_ID'].unique()) if 'Game_ID' in df.columns else []
    game_index = {gid: n_assign + i for i, gid in enumerate(game_ids)}
    n_vars = n_assign + len(game_ids)
    pid_to_var_idxs = {}
    for (pid, slot), idx in assign_index.items():
        pid_to_var_idxs.setdefault(pid, []).append(idx)
    row_by_pid = {row['Player_ID']: row for _, row in df.iterrows()}

    c = np.zeros(n_vars, dtype=float)
    for (pid, slot), idx in assign_index.items():
        row = row_by_pid[pid]
        c[idx] = -float(row['_obj'] + suppression_bonus.get(pid, 0.0))

    rows = []
    lbs = []
    ubs = []
    def add_constraint(coefs, lb, ub):
        rows.append(dict(coefs)); lbs.append(lb); ubs.append(ub)
    def add_selected_sum_constraint(pids, lb, ub):
        coefs = {}
        for pid in pids:
            for idx in pid_to_var_idxs.get(pid, []):
                coefs[idx] = coefs.get(idx, 0.0) + 1.0
        add_constraint(coefs, lb, ub)

    for pid, idxs in pid_to_var_idxs.items():
        add_constraint({idx: 1.0 for idx in idxs}, -np.inf, 1.0)
    for slot, _required_pos in EXACT_ROSTER_SLOTS:
        add_constraint({idx: 1.0 for (pid, candidate_slot), idx in assign_index.items() if candidate_slot == slot}, 1.0, 1.0)

    suppression_coefs = {idx: suppression_bonus.get(pid, 0.0) for (pid, _slot), idx in assign_index.items() if suppression_bonus.get(pid, 0.0) != 0.0}
    if suppression_coefs:
        add_constraint(suppression_coefs, -np.inf, SUPPRESSION_LINEUP_CAP)
    add_constraint({idx: float(row_by_pid[pid]['Salary']) for (pid, _slot), idx in assign_index.items()}, -np.inf, SALARY_CAP)

    for team in df['Team'].unique():
        team_hitter_pids = df[(df['Team'] == team) & (df['_pos_set'].apply(lambda pos: bool(pos & HITTER_POSITIONS) and 'P' not in pos))]['Player_ID'].tolist()
        if team_hitter_pids:
            add_selected_sum_constraint(team_hitter_pids, -np.inf, MAX_HITTERS_PER_TEAM)

    if game_ids:
        for gid in game_ids:
            g_idx = game_index[gid]
            players_in_game = df[df['Game_ID'] == gid]['Player_ID'].tolist()
            coefs = {g_idx: 1.0}
            for pid in players_in_game:
                for idx in pid_to_var_idxs.get(pid, []):
                    coefs[idx] = coefs.get(idx, 0.0) - 1.0
            add_constraint(coefs, -np.inf, 0.0)
            for pid in players_in_game:
                coefs = {g_idx: -1.0}
                for idx in pid_to_var_idxs.get(pid, []):
                    coefs[idx] = coefs.get(idx, 0.0) + 1.0
                add_constraint(coefs, -np.inf, 0.0)
        add_constraint({game_index[gid]: 1.0 for gid in game_ids}, MIN_GAMES, np.inf)

    for pid in (locks or []):
        if pid_to_var_idxs.get(pid):
            add_constraint({idx: 1.0 for idx in pid_to_var_idxs[pid]}, 1.0, 1.0)
        else:
            _record_solver_status(
                status_out, status='locked_player_unavailable',
                message=f'locked_player_unavailable:{pid}', proven_infeasible=True,
                time_limit_s=resolve_solver_time_limit(time_limit_s),
            )
            return None, None

    for slot, pid in (locked_slot_assignments or {}).items():
        slot = str(slot)
        pid = str(pid)
        if slot not in required_by_slot or (pid, slot) not in assign_index:
            _record_solver_status(
                status_out, status='locked_slot_unavailable',
                message=f'locked_slot_unavailable:{slot}:{pid}', proven_infeasible=True,
                time_limit_s=resolve_solver_time_limit(time_limit_s),
            )
            return None, None
        add_constraint({assign_index[(pid, slot)]: 1.0}, 1.0, 1.0)

    sp_pids = df[df['_pos_set'].apply(lambda pos: 'P' in pos)]['Player_ID'].tolist()
    for sp_pid in sp_pids:
        sp_row = df[df['Player_ID'] == sp_pid].iloc[0]
        opponent = sp_row['Opponent']
        opponent_hitters = df[(df['Team'] == opponent) & (df['_pos_set'].apply(lambda pos: bool(pos & HITTER_POSITIONS) and 'P' not in pos))]['Player_ID'].tolist()
        for hitter_pid in opponent_hitters:
            coefs = {}
            for idx in pid_to_var_idxs.get(sp_pid, []):
                coefs[idx] = coefs.get(idx, 0.0) + 1.0
            for idx in pid_to_var_idxs.get(hitter_pid, []):
                coefs[idx] = coefs.get(idx, 0.0) + 1.0
            if coefs:
                add_constraint(coefs, -np.inf, 1.0)

    if stack_constraints:
        team = stack_constraints['team']
        stack_pids = df[(df['Team'] == team) & (df['_pos_set'].apply(lambda pos: bool(pos & HITTER_POSITIONS) and 'P' not in pos))]['Player_ID'].tolist()
        add_selected_sum_constraint(stack_pids, stack_constraints.get('min_size', 3), stack_constraints.get('max_size', 5))
    if bringback_constraint:
        team = bringback_constraint['bringback_team']
        pids = df[(df['Team'] == team) & (df['_pos_set'].apply(lambda pos: bool(pos & HITTER_POSITIONS) and 'P' not in pos))]['Player_ID'].tolist()
        add_selected_sum_constraint(pids, bringback_constraint.get('min', 1), bringback_constraint.get('max', 2))
    if overlap_reference and max_overlap is not None:
        for reference in overlap_reference:
            pids = [pid for pid in reference if pid in pid_to_var_idxs]
            if pids:
                add_selected_sum_constraint(pids, -np.inf, max_overlap)
    if stack_core_blocklist:
        for core in stack_core_blocklist:
            pids = [pid for pid in core if pid in pid_to_var_idxs]
            if pids:
                add_selected_sum_constraint(pids, -np.inf, len(pids) - 1)
    if forbidden_player_combos:
        for combo in forbidden_player_combos:
            pids = [pid for pid in combo if pid in pid_to_var_idxs]
            if len(pids) >= 2:
                add_selected_sum_constraint(pids, -np.inf, len(pids) - 1)

    row_idx, col_idx, data = [], [], []
    for row_number, coefs in enumerate(rows):
        for col, value in coefs.items():
            if value:
                row_idx.append(row_number); col_idx.append(col); data.append(float(value))
    matrix = coo_matrix((data, (row_idx, col_idx)), shape=(len(rows), n_vars)).tocsr()
    lb_array = np.array(lbs)
    ub_array = np.array(ubs)
    effective_limit = resolve_solver_time_limit(time_limit_s)
    solve_started = _time.monotonic()
    result = milp(
        c=c, integrality=np.ones(n_vars, dtype=int),
        bounds=Bounds(np.zeros(n_vars), np.ones(n_vars)),
        constraints=LinearConstraint(matrix, lb_array, ub_array),
        options={'time_limit': effective_limit, 'disp': False},
    )
    elapsed = _time.monotonic() - solve_started
    scipy_status = getattr(result, 'status', None)
    status_name = SCIPY_MILP_STATUS.get(scipy_status, 'other')
    timed_out = status_name == 'time_limit'
    message = str(getattr(result, 'message', scipy_status))
    base_fields = dict(
        status=status_name, scipy_status=scipy_status, message=message,
        timed_out=timed_out, proven_infeasible=(status_name == 'infeasible'),
        mip_gap=getattr(result, 'mip_gap', None),
        time_limit_s=effective_limit, elapsed_s=round(elapsed, 4),
    )

    if result.x is None:
        _record_solver_status(status_out, **base_fields)
        return None, None

    # A time-limited solve reports success=False even when result.x holds a
    # feasible incumbent. Discarding it is what made a clock look like an
    # infeasible pool. Accepting it unverified would be worse, so the incumbent
    # is checked against the same constraint matrix the solver was given before
    # it is allowed anywhere near a certified export.
    x = np.asarray(result.x, dtype=float)
    rounded = np.round(x)
    integral = bool(np.max(np.abs(x - rounded)) <= 1e-5) if x.size else False
    feasible = False
    if integral:
        lhs = matrix @ rounded
        feasible = bool(
            np.all(lhs >= lb_array - 1e-6) and np.all(lhs <= ub_array + 1e-6)
        )
    if not (result.success or (timed_out and integral and feasible)):
        _record_solver_status(
            status_out,
            incumbent_rejected=bool(timed_out and not (integral and feasible)),
            **base_fields,
        )
        return None, None

    selected = [(pid, slot) for (pid, slot), idx in assign_index.items() if rounded[idx] > 0.5]
    if len(selected) != ROSTER_SIZE:
        _record_solver_status(
            status_out, incumbent_rejected=True,
            **{**base_fields, 'status': 'roster_size_mismatch'},
        )
        return None, None

    optimality = 'time_limited' if timed_out else 'optimal'
    _record_solver_status(status_out, optimality=optimality, **base_fields)
    lineup_df, objective = _build_lineup_output_from_selected(df, selected, suppression_bonus)
    if lineup_df is not None:
        try:
            lineup_df.attrs['optimality'] = optimality
            lineup_df.attrs['solver_time_limit_s'] = effective_limit
        except Exception:  # noqa: BLE001 - attrs are a diagnostic, never a gate
            pass
    return lineup_df, objective


# ============================================================================
# v3.7 build_single_lineup wrapper
# ============================================================================

def build_single_lineup(
    projections_df,
    target='ceiling',
    locks=None,
    locked_slot_assignments=None,
    excludes=None,
    stack_constraints=None,
    bringback_constraint=None,
    overlap_reference=None,
    max_overlap=None,
    stack_core_blocklist=None,
    forbidden_player_combos=None,
    penalized_players=None,
    skip_feasibility_check=False,
    apply_suppression=True,
    solver_backend='auto',
    time_limit_s=None,
    status_out=None,
):
    """Single-lineup optimizer with optional exact DK slot locks.

    ``time_limit_s`` bounds this one solve; ``None`` uses SOLVER_TIME_LIMIT_S.
    ``status_out`` is a caller-owned dict filled with the structured solver
    status (v3.20 / F13). Pass one whenever the difference between "the clock
    ran out" and "this is infeasible" changes what you do next, which is every
    caller that has a relaxation ladder.
    """
    # F19: sorted before constraint emission. These ids become one equality row
    # each, and the row order is a branch-and-bound tie-break input.
    locked_ids = stable_union(locks, (locked_slot_assignments or {}).values())
    df, suppression_bonus = _prepare_single_lineup_df(
        projections_df, target=target, locks=locked_ids, excludes=excludes,
        stack_constraints=stack_constraints, skip_feasibility_check=skip_feasibility_check,
        penalized_players=penalized_players, apply_suppression=apply_suppression,
    )
    _select_solver_backend(solver_backend)
    return _build_single_lineup_scipy(
        df, suppression_bonus, locks=locked_ids, locked_slot_assignments=locked_slot_assignments,
        stack_constraints=stack_constraints, bringback_constraint=bringback_constraint,
        overlap_reference=overlap_reference, max_overlap=max_overlap,
        stack_core_blocklist=stack_core_blocklist, forbidden_player_combos=forbidden_player_combos,
        time_limit_s=time_limit_s, status_out=status_out,
    )


# ============================================================================
# v3.4 Diversification Units: Bucket Rules
# ============================================================================

def _hitter_team_counts(lineup_df):
    """Returns dict {team: count} of non-pitcher rostered hitters by team."""
    counts = {}
    for _, row in lineup_df.iterrows():
        pos_set = _parse_positions(row['Position'])
        assigned = row.get('Assigned_Position')
        if assigned is not None and assigned in HITTER_POSITIONS:
            counts[row['Team']] = counts.get(row['Team'], 0) + 1
        elif assigned is None and (pos_set & HITTER_POSITIONS) and 'P' not in pos_set:
            counts[row['Team']] = counts.get(row['Team'], 0) + 1
    return counts


def _identify_primary_stack(lineup_df):
    """Returns team abbreviation or 'NONE' per Bucket Rule for Unit 2.
    Threshold: ≥ PRIMARY_STACK_MIN_HITTERS. Tie-break: alphabetical (A4 fix).
    """
    counts = _hitter_team_counts(lineup_df)
    eligible = [(team, c) for team, c in counts.items() if c >= PRIMARY_STACK_MIN_HITTERS]
    if not eligible:
        return 'NONE'
    eligible.sort(key=lambda x: (-x[1], x[0]))
    return eligible[0][0]


def candidate_primary_stack(lineup_df):
    """The primary stack as a payload field: a team, or "" for no stack.

    ``_identify_primary_stack`` returns the literal ``'NONE'`` because the DU
    signature needs a hashable bucket for "this lineup has no primary stack",
    and inside the signature that is correct. Outside it is a trap: the
    allocator treats any nonblank value as a team, so 'NONE' became a phantom
    stack bucket that the exposure cap then constrained, and a bank of
    stackless candidates went infeasible against a cap on a team that does not
    exist. The signature keeps its sentinel; the payload gets the empty string.
    """
    stack = _identify_primary_stack(lineup_df)
    return '' if str(stack).strip().upper() in ('', 'NONE') else str(stack)


def _identify_secondary_stack(lineup_df, primary_stack):
    """Returns team abbreviation or 'NONE' per Bucket Rule for Unit 3.
    Threshold: ≥ SECONDARY_STACK_MIN_HITTERS. Tie-break: alphabetical.
    """
    counts = _hitter_team_counts(lineup_df)
    eligible = [
        (team, c) for team, c in counts.items()
        if c >= SECONDARY_STACK_MIN_HITTERS and team != primary_stack
    ]
    if not eligible:
        return 'NONE'
    eligible.sort(key=lambda x: (-x[1], x[0]))
    return eligible[0][0]


def _classify_game_environment_for_game(game_meta):
    """Per-game environment classification per Bucket Rule for Unit 4.
    Roof-first per A6 fix; weather-leveraged threshold 40% per B5 fix.
    """
    venue_type = game_meta.get('venue_type', 'outdoor')
    implied_total = float(game_meta.get('implied_total', 0.0))

    if venue_type in ('dome', 'roof_closed'):
        if implied_total >= HIGH_TOTAL_THRESHOLD:
            return 'high-total'
        return 'dome'

    wind_speed = float(game_meta.get('wind_speed', 0.0))
    wind_direction = game_meta.get('wind_direction')
    precip_pct = float(game_meta.get('precip_pct', 0.0))

    weather_leveraged = (
        (wind_speed >= WIND_OUT_THRESHOLD and wind_direction == 'out')
        or precip_pct >= PRECIP_LEVERAGED_THRESHOLD
    )
    if weather_leveraged:
        return 'weather-leveraged'
    if implied_total >= HIGH_TOTAL_THRESHOLD:
        return 'high-total'
    return 'neutral'


def _modal_environment(lineup_df, slate_metadata):
    """Returns the lineup's modal game-environment label.
    Mode tie-break: highest implied total among tied games.
    """
    if slate_metadata is None or 'games' not in slate_metadata:
        return 'neutral'

    games_dict = slate_metadata['games']
    label_totals = []
    for _, row in lineup_df.iterrows():
        assigned = row.get('Assigned_Position')
        pos_set = _parse_positions(row['Position'])
        is_hitter = (assigned in HITTER_POSITIONS) if assigned is not None else (
            (pos_set & HITTER_POSITIONS) and 'P' not in pos_set
        )
        if not is_hitter:
            continue
        gid = row.get('Game_ID')
        if gid is None or pd.isna(gid):
            continue
        game_meta = games_dict.get(gid)
        if game_meta is None:
            continue
        env = game_meta.get('environment')
        if env is None:
            env = _classify_game_environment_for_game(game_meta)
        implied = float(game_meta.get('implied_total', 0.0))
        label_totals.append((env, implied))

    if not label_totals:
        return 'neutral'

    label_count = Counter(lt[0] for lt in label_totals)
    max_count = max(label_count.values())
    tied_labels = [lbl for lbl, c in label_count.items() if c == max_count]
    if len(tied_labels) == 1:
        return tied_labels[0]
    best_label = None
    best_total = -1.0
    for lbl, total in label_totals:
        if lbl in tied_labels and total > best_total:
            best_total = total
            best_label = lbl
    return best_label


def _identify_one_off_candidates(lineup_df, primary_stack, secondary_stack):
    """Returns DataFrame of non-pitcher hitters NOT in primary or secondary
    stack teams (per A5 fix).
    """
    rows = []
    for _, row in lineup_df.iterrows():
        assigned = row.get('Assigned_Position')
        pos_set = _parse_positions(row['Position'])
        is_hitter = (assigned in HITTER_POSITIONS) if assigned is not None else (
            (pos_set & HITTER_POSITIONS) and 'P' not in pos_set
        )
        if not is_hitter:
            continue
        if row['Team'] == primary_stack or row['Team'] == secondary_stack:
            continue
        rows.append(row)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def _ownership_priority(tier):
    return _OWNERSHIP_PRIORITY.get(tier, 99)


def _divergence_priority(notes_value):
    """Lower = higher priority for chalk one-off sorting.

    New-style SALARY_SUPPRESSION tags rank above legacy divergence tags because
    they represent the v3.8 source-of-truth trigger inventory.
    """
    notes = '' if notes_value is None or pd.isna(notes_value) else str(notes_value)
    trigger = _suppression_trigger(notes)
    if trigger is not None:
        return _SUPPRESSION_TRIGGER_PRIORITY.get(trigger, 99)
    if DIVERGENCE_VALUE_TAG in notes:
        return 10
    if DIVERGENCE_LEVERAGE_TAG in notes:
        return 11
    return 12


def _classify_chalk_one_off(lineup_df, primary_stack, secondary_stack):
    """Returns a deterministic Unit 5 label for the selected one-off hitter.

    v3.8 emits trigger-specific labels for SALARY_SUPPRESSION:<trigger> tags.
    Legacy divergence labels remain supported for transition compatibility.
    """
    candidates = _identify_one_off_candidates(lineup_df, primary_stack, secondary_stack)
    if len(candidates) == 0:
        return 'stack-only'

    candidates = candidates.copy()
    candidates['_own_pri'] = candidates['Ownership_Tier'].apply(_ownership_priority)
    candidates['_div_pri'] = candidates['Notes'].apply(_divergence_priority)
    candidates = candidates.sort_values(
        by=['_own_pri', '_div_pri', 'Salary', 'Player_ID'],
        ascending=[True, True, True, True]
    )

    one_off = candidates.iloc[0]
    tier = one_off['Ownership_Tier']
    notes = '' if one_off['Notes'] is None or pd.isna(one_off['Notes']) else str(one_off['Notes'])

    if tier == 'Low':
        trigger = _suppression_trigger(notes)
        if trigger is not None:
            return SUPPRESSION_ONE_OFF_LABELS.get(trigger, f'{trigger}-one-off')
        if DIVERGENCE_VALUE_TAG in notes:
            return 'value-divergence-one-off'
        if DIVERGENCE_LEVERAGE_TAG in notes:
            return 'leverage-divergence-one-off'
        return 'sub-10-pct-one-off'
    if tier == 'Mid':
        return 'mid-one-off'
    return 'high-one-off'


def wind_bearing_to_f5_label(wind_from_degrees, cf_azimuth_degrees, tolerance_degrees=45):
    """Translate meteorological wind bearing to F5 {out, in, cross} label.

    Args:
        wind_from_degrees: meteorological bearing in degrees, i.e. direction
            the wind is FROM.
        cf_azimuth_degrees: home-plate-to-center-field azimuth in degrees.
        tolerance_degrees: angular tolerance for out/in classification.

    Returns:
        'out' when wind is blowing toward center field within tolerance,
        'in' when blowing toward home plate within tolerance, otherwise 'cross'.
    """
    if wind_from_degrees is None or cf_azimuth_degrees is None:
        return 'cross'
    try:
        wind_toward = (float(wind_from_degrees) + 180.0) % 360.0
        cf_axis = float(cf_azimuth_degrees) % 360.0
        tol = float(tolerance_degrees)
    except (TypeError, ValueError):
        return 'cross'

    def angular_distance(a, b):
        return abs((a - b + 180.0) % 360.0 - 180.0)

    if angular_distance(wind_toward, cf_axis) <= tol:
        return 'out'
    if angular_distance(wind_toward, (cf_axis + 180.0) % 360.0) <= tol:
        return 'in'
    return 'cross'


def _get_sp_ids(lineup_df):
    """Returns frozenset of Player_IDs at P slot."""
    sps = []
    for _, row in lineup_df.iterrows():
        assigned = row.get('Assigned_Position')
        pos_set = _parse_positions(row['Position'])
        is_pitcher = (assigned == 'P') if assigned is not None else ('P' in pos_set)
        if is_pitcher:
            sps.append(row['Player_ID'])
    return frozenset(sps)


def _get_ordered_sp_ids(lineup_df):
    """Returns deterministic list of Player_IDs at P slot for exposure caps."""
    return sorted(_get_sp_ids(lineup_df), key=lambda pid: str(pid))


def _eligible_sp_ids_for_anchor_caps(projections_df, excludes=None):
    """Returns rosterable SP IDs after Excluded/excludes gates for auto caps."""
    df = projections_df.copy()
    if excludes:
        df = df[~df['Player_ID'].isin(excludes)]
    df = _drop_excluded_rows(df)  # F21: one reading of the column, counted
    sp_df = df[df['Position'].apply(lambda p: 'P' in _parse_positions(p))]
    return sp_df['Player_ID'].tolist()


def _normalize_sp_audit_status(value):
    """Normalize pitcher-audit status labels for v3.12 SP coverage."""
    if value is None or pd.isna(value):
        return 'unknown'
    return str(value).strip().lower().replace(' ', '_').replace('-', '_')


def resolve_viable_sp_pool(
    projections_df,
    excludes=None,
    include_optional_bulk=False,
    audit_status_col=DEFAULT_SP_AUDIT_STATUS_COLUMN,
):
    """Return audited SP IDs eligible for SP-pair coverage planning.

    Pitcher audit is source-of-truth when the audit column exists. Exact pair
    coverage uses required statuses only by default. Optional viable bulk/alt SPs
    can be included only when the caller opts in. If no audit column is present,
    the helper treats rosterable salary-row pitchers as viable but flags the
    plan as unaudited so the executor can block upload-ready export elsewhere.
    """
    df = projections_df.copy()
    if excludes:
        df = df[~df['Player_ID'].isin(excludes)]
    df = _drop_excluded_rows(df)  # F21: one reading of the column, counted
    sp_df = df[df['Position'].apply(lambda p: 'P' in _parse_positions(p))].copy()

    if audit_status_col in sp_df.columns:
        sp_df['_sp_audit_status'] = sp_df[audit_status_col].apply(_normalize_sp_audit_status)
        audit_source = audit_status_col
        audit_missing = False
    else:
        sp_df['_sp_audit_status'] = 'unknown_no_audit_column'
        audit_source = None
        audit_missing = True

    required_statuses = set(REQUIRED_SP_AUDIT_STATUSES)
    optional_statuses = set(OPTIONAL_SP_AUDIT_STATUSES)
    excluded_statuses = set(EXCLUDED_SP_AUDIT_STATUSES)

    if audit_missing:
        required_mask = sp_df['Player_ID'].notna()
        optional_mask = sp_df['Player_ID'].isna()
        excluded_mask = sp_df['Player_ID'].isna()
    else:
        required_mask = sp_df['_sp_audit_status'].isin(required_statuses)
        optional_mask = sp_df['_sp_audit_status'].isin(optional_statuses)
        excluded_mask = sp_df['_sp_audit_status'].isin(excluded_statuses)

    required_ids = sorted(sp_df[required_mask]['Player_ID'].tolist(), key=str)
    optional_ids = sorted(sp_df[optional_mask]['Player_ID'].tolist(), key=str)
    excluded_ids = sorted(sp_df[excluded_mask]['Player_ID'].tolist(), key=str)
    unknown_ids = sorted(
        sp_df[~required_mask & ~optional_mask & ~excluded_mask]['Player_ID'].tolist(),
        key=str,
    )

    viable_ids = list(required_ids)
    if include_optional_bulk:
        viable_ids = sorted(set(viable_ids) | set(optional_ids), key=str)

    return {
        'required_sp_ids': required_ids,
        'optional_sp_ids': optional_ids,
        'excluded_sp_ids': excluded_ids,
        'unknown_sp_ids': unknown_ids,
        'viable_sp_ids': viable_ids,
        'audit_source': audit_source,
        'audit_missing': audit_missing,
        'include_optional_bulk': bool(include_optional_bulk),
        'status_counts': dict(Counter(sp_df['_sp_audit_status'].tolist())),
    }


def enumerate_sp_pairs(sp_ids, projections_df=None, cross_game_only=True,
                       rank_by_ceiling=True):
    """Return deterministic 2-combinations of SP IDs, strongest first.

    Two corrections over the naive enumeration, both of which cost real slates:

    ``cross_game_only`` drops pairs of opposing starters. On a 14-game slate
    roughly 14 of the enumerated pairs are the two sides of one game, which are
    anti-correlated at the win and quality-start level. Phase 1 of the bank spent
    budgeted solves manufacturing lineups around those pairs, and
    ``_slate_feasibility`` counted them as capacity, which understates the true
    repetition floor on thin slates. ``bank_cache.extend_bank`` already excluded
    them; this makes the two subsystems agree. Pass False to enumerate every
    combination, which the pair-grid planner may legitimately want.

    ``rank_by_ceiling`` orders pairs by combined pitcher Ceiling descending when
    a projections frame is supplied. Coverage loops stop on budget exhaustion, so
    the order decides what gets covered: the previous sort was on Player_ID as a
    STRING, meaning a big-slate bank under the sandbox ceiling covered an
    alphabetical prefix and could never reach the two best arms' pairings.
    Truncation should degrade from the weak end. Ties and unranked pitchers fall
    back to the id sort, so the result stays deterministic either way.
    """
    ids = sorted(set(sp_ids or []), key=str)

    game_of = {}
    ceiling_of = {}
    if projections_df is not None and hasattr(projections_df, "itertuples"):
        for row in projections_df.itertuples():
            pid = str(getattr(row, "Player_ID", ""))
            game_of[pid] = str(getattr(row, "Game_ID", ""))
            try:
                ceiling_of[pid] = float(getattr(row, "Ceiling", 0.0) or 0.0)
            except (TypeError, ValueError):
                ceiling_of[pid] = 0.0

    pairs = []
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            if cross_game_only and game_of:
                game_a, game_b = game_of.get(str(a)), game_of.get(str(b))
                # Only drop when BOTH games are known and equal. An unknown game
                # is not evidence of a same-game pair, and silently dropping it
                # would shrink the legal pair set on incomplete data.
                if game_a and game_b and game_a == game_b:
                    continue
            pairs.append((a, b))

    if rank_by_ceiling and ceiling_of:
        pairs.sort(key=lambda pr: (
            -(ceiling_of.get(str(pr[0]), 0.0) + ceiling_of.get(str(pr[1]), 0.0)),
            str(pr[0]), str(pr[1]),
        ))
    return pairs


def _sp_pair_from_lineup(lineup_df):
    ids = _get_ordered_sp_ids(lineup_df)
    if len(ids) != 2:
        return None
    return tuple(ids)


def _sp_pair_coverage_required_usage(required_pairs):
    usage = Counter()
    for pair in required_pairs or []:
        for pid in pair:
            usage[pid] += 1
    return usage


def resolve_sp_pair_coverage_plan(
    n_lineups,
    slate_game_count=None,
    projections_df=None,
    viable_sp_ids=None,
    excludes=None,
    include_optional_bulk=False,
    audit_status_col=DEFAULT_SP_AUDIT_STATUS_COLUMN,
    mode='portfolio_ev',
    allow_four_game_hard_all_pairs=False,
    coverage_preference='weighted_soft',
    force_hard_all_pairs=False,
    soft_coverage_ratio=0.67,
):
    """Resolve small-slate SP-pair coverage policy.

    v3.14 defaults to weighted soft coverage. Exact all-pairs coverage is only
    activated by ``force_hard_all_pairs=True`` or
    ``coverage_preference='hard_all_pairs'`` when the requested lineup count can
    actually cover the grid. This avoids spending a lineup on a dominated pair
    solely for symmetry.
    """
    requested = max(1, int(n_lineups or 1))
    preference = str(coverage_preference or 'weighted_soft').strip().lower()
    if preference not in {'weighted_soft', 'hard_all_pairs', 'disabled'}:
        raise ValueError('coverage_preference must be weighted_soft, hard_all_pairs, or disabled')
    pool = None
    if viable_sp_ids is None:
        if projections_df is None:
            viable_ids = []
        else:
            pool = resolve_viable_sp_pool(
                projections_df,
                excludes=excludes,
                include_optional_bulk=include_optional_bulk,
                audit_status_col=audit_status_col,
            )
            viable_ids = pool['viable_sp_ids']
    else:
        viable_ids = sorted(set(viable_sp_ids or []), key=str)

    pairs = enumerate_sp_pairs(viable_ids)
    pair_count = len(pairs)
    game_count = int(slate_game_count) if slate_game_count is not None else None
    notes = []
    if pool and pool.get('audit_missing'):
        notes.append('pitcher_audit_column_missing; salary-row pitchers treated as viable for planning only')
    if pool and pool.get('optional_sp_ids') and not include_optional_bulk:
        notes.append('optional viable bulk/alt SPs excluded from required pair grid')

    # Transparent quality weights used only to prioritize soft coverage. They
    # do not alter pitcher projections or lineup objective values.
    sp_scores = {pid: 1.0 for pid in viable_ids}
    if projections_df is not None and len(projections_df) > 0 and 'Player_ID' in projections_df.columns:
        score_col = 'Ceiling' if 'Ceiling' in projections_df.columns else (
            'Base_Projection' if 'Base_Projection' in projections_df.columns else None
        )
        if score_col:
            raw = {}
            for pid in viable_ids:
                vals = projections_df.loc[projections_df['Player_ID'] == pid, score_col]
                if len(vals):
                    raw[pid] = max(0.0, _safe_float(vals.iloc[0], 0.0))
            if raw:
                lo, hi = min(raw.values()), max(raw.values())
                for pid in viable_ids:
                    value = raw.get(pid, lo)
                    sp_scores[pid] = 1.0 if hi <= lo else 0.25 + 0.75 * (value - lo) / (hi - lo)
    pair_priority_scores = {
        tuple(pair): round((sp_scores.get(pair[0], 1.0) + sp_scores.get(pair[1], 1.0)) / 2.0, 6)
        for pair in pairs
    }
    priority_pairs = sorted(
        pairs,
        key=lambda pair: (pair_priority_scores.get(tuple(pair), 0.0), tuple(map(str, pair))),
        reverse=True,
    )

    hard_requested = bool(force_hard_all_pairs or preference == 'hard_all_pairs')
    if preference == 'disabled' or pair_count == 0:
        policy = 'disabled'
        coverage_required = False
        target_unique_pairs = 0
    elif game_count is not None and game_count >= 5:
        policy = 'archetype_coverage'
        coverage_required = False
        target_unique_pairs = min(requested, pair_count)
        notes.append('large_slate_exact_pair_coverage_disabled')
    elif game_count == 4 and allow_four_game_hard_all_pairs and requested >= pair_count:
        policy = 'hard_all_pairs'
        coverage_required = True
        target_unique_pairs = pair_count
    elif hard_requested and requested >= pair_count and (game_count is None or game_count <= 4):
        policy = 'hard_all_pairs'
        coverage_required = True
        target_unique_pairs = pair_count
    else:
        policy = 'soft_unique_pairs'
        coverage_required = False
        feasible = min(requested, pair_count)
        target_unique_pairs = min(feasible, max(1, int(ceil(feasible * float(soft_coverage_ratio)))))
        notes.append('weighted_soft_pair_coverage_default')
        if hard_requested and requested < pair_count:
            notes.append('hard_all_pairs_requested_but_lineup_count_insufficient')
        if game_count == 4:
            notes.append('four_game_slate_defaults_to_soft_pair_coverage')
        if game_count is None:
            notes.append('slate_game_count_missing; weighted soft policy used')

    if policy not in SP_PAIR_COVERAGE_POLICIES:
        raise ValueError(f'unknown SP-pair coverage policy: {policy}')

    required_pairs = pairs if policy == 'hard_all_pairs' else []
    return {
        'policy': policy,
        'coverage_preference': preference,
        'coverage_required': bool(coverage_required),
        'n_lineups': requested,
        'slate_game_count': game_count,
        'viable_sp_count': len(viable_ids),
        'valid_pair_count': pair_count,
        'viable_sp_ids': viable_ids,
        'required_sp_pairs': required_pairs,
        'priority_sp_pairs': [tuple(pair) for pair in priority_pairs],
        'sp_pair_priority_scores': pair_priority_scores,
        'target_unique_pairs': int(target_unique_pairs),
        'soft_coverage_ratio': float(soft_coverage_ratio),
        'include_optional_bulk': bool(include_optional_bulk),
        'audit_source': None if pool is None else pool.get('audit_source'),
        'audit_missing': False if pool is None else pool.get('audit_missing'),
        'pool_summary': pool,
        'notes': notes,
        'mode': mode,
    }


def validate_sp_pair_coverage(lineup_records, coverage_plan=None):
    """Validate hard required pairs or the weighted-soft unique-pair target."""
    if not coverage_plan:
        return {
            'pass': True,
            'policy': 'disabled',
            'required_pair_count': 0,
            'covered_required_pair_count': 0,
            'missing_required_pairs': [],
            'target_unique_pairs': 0,
            'observed_unique_pair_count': 0,
            'observed_pair_counts': {},
            'summary': 'SP pair coverage: no plan supplied',
        }

    required_pairs = [tuple(sorted(pair, key=str)) for pair in coverage_plan.get('required_sp_pairs') or []]
    observed = Counter()
    for rec in lineup_records or []:
        lineup_df = rec.get('lineup') if isinstance(rec, dict) else rec
        if lineup_df is None:
            continue
        pair = _sp_pair_from_lineup(lineup_df)
        if pair is not None:
            observed[frozenset(pair)] += 1

    covered = [pair for pair in required_pairs if frozenset(pair) in observed]
    missing = [pair for pair in required_pairs if frozenset(pair) not in observed]
    target_unique = int(coverage_plan.get('target_unique_pairs') or 0)
    policy = coverage_plan.get('policy', 'disabled')
    hard_pass = len(missing) == 0
    # The target does not move. It used to shrink to min(target, lineups built),
    # so a truncated portfolio always met its own coverage target while the
    # summary went on printing the unshrunk number. A gate whose note moves its
    # own goalposts makes every automated check on `pass` useless.
    n_built = len(lineup_records or [])
    truncated_portfolio = bool(target_unique and n_built < target_unique)
    soft_pass = len(observed) >= target_unique
    passed = hard_pass if required_pairs else soft_pass
    observed_dict = {tuple(sorted(pair, key=str)): count for pair, count in observed.items()}
    summary = (
        f'SP pair coverage: policy {policy}; covered {len(covered)}/{len(required_pairs)} '
        f'required pairs; observed {len(observed)}/{target_unique} target unique pairs'
    )
    if missing:
        summary += f'; missing {len(missing)} required pair(s)'
    if not required_pairs and not soft_pass:
        summary += '; soft unique-pair target missed'
    if truncated_portfolio:
        summary += (f'; only {n_built} lineups were built against a {target_unique} '
                    f'pair target, so the target was unreachable by construction')
    return {
        'pass': bool(passed),
        'policy': policy,
        'coverage_preference': coverage_plan.get('coverage_preference'),
        'required_pair_count': len(required_pairs),
        'covered_required_pair_count': len(covered),
        'missing_required_pairs': missing,
        'covered_required_pairs': covered,
        'target_unique_pairs': target_unique,
        'lineups_built': n_built,
        'truncated_portfolio': truncated_portfolio,
        'soft_target_met': bool(soft_pass),
        'observed_unique_pair_count': len(observed),
        'observed_pair_counts': observed_dict,
        'summary': summary,
    }


def _resolve_anchor_cap(cap_value, cap_kind, n_lineups, eligible_sp_count):
    """Resolve SP exposure or SP-pair repetition cap.

    cap_value may be None, an integer, or 'auto'. Auto is MLB small-slate
    policy, but callers may use it explicitly on any slate.
    """
    if cap_value is None:
        return None
    if isinstance(cap_value, str):
        if cap_value != 'auto':
            raise ValueError("anchor exposure caps must be None, an int, or 'auto'")
        if cap_kind == 'sp':
            if eligible_sp_count <= 0:
                return None
            avg_slots = ceil((2 * n_lineups) / eligible_sp_count)
            return max(avg_slots, min(ceil(0.60 * n_lineups), ceil(1.25 * avg_slots)))
        if cap_kind == 'pair':
            return max(2, ceil(n_lineups / 3))
        raise ValueError("cap_kind must be 'sp' or 'pair'")
    cap = int(cap_value)
    if cap < 0:
        raise ValueError('anchor exposure caps must be non-negative')
    return cap


def _anchor_validation_dict(sp_usage, sp_pair_usage, max_sp_cap, max_pair_cap):
    """Return machine-readable anchor exposure validation/provenance."""
    observed_max_sp = max(sp_usage.values()) if sp_usage else 0
    observed_max_pair = max(sp_pair_usage.values()) if sp_pair_usage else 0

    sp_pass = True if max_sp_cap is None else observed_max_sp <= max_sp_cap
    pair_pass = True if max_pair_cap is None else observed_max_pair <= max_pair_cap
    passed = sp_pass and pair_pass

    if max_sp_cap is None and max_pair_cap is None:
        summary = (
            f'Anchor exposure: no caps active; observed max SP {observed_max_sp}, '
            f'observed max SP pair {observed_max_pair}'
        )
    else:
        summary = (
            f'Anchor exposure: max SP cap {max_sp_cap}, max SP-pair cap {max_pair_cap}; '
            f'observed max SP {observed_max_sp}, observed max SP pair {observed_max_pair}; '
            f"{'passed' if passed else 'failed'}"
        )

    return {
        'pass': passed,
        'sp_exposure_counts': dict(sp_usage),
        'sp_pair_counts': dict(sp_pair_usage),
        'max_sp_exposure': max_sp_cap,
        'max_sp_pair_repetition': max_pair_cap,
        'relaxation_applied': None,
        'summary': summary,
    }


def compute_unit_signature(lineup_df, slate_metadata):
    """Returns dict {unit_name: bucket_label}. Deterministic; order-invariant."""
    primary = _identify_primary_stack(lineup_df)
    secondary = _identify_secondary_stack(lineup_df, primary)
    return {
        'sp_pair': _get_sp_ids(lineup_df),
        'primary_stack': primary,
        'secondary_stack': secondary,
        'game_environment': _modal_environment(lineup_df, slate_metadata),
        'chalk_one_off': _classify_chalk_one_off(lineup_df, primary, secondary),
    }


def matched_units(sig_a, sig_b, exclude_anchor=False):
    """Returns list of unit names where sig_a[u] == sig_b[u]."""
    units = DU_UNIT_NAMES
    if exclude_anchor:
        units = [u for u in units if u not in DU_ANCHOR_UNITS]
    return [u for u in units if sig_a.get(u) == sig_b.get(u)]


def du_distance(sig_a, sig_b, exclude_anchor=False):
    """Returns count of units where signatures differ."""
    units = DU_UNIT_NAMES
    if exclude_anchor:
        units = [u for u in units if u not in DU_ANCHOR_UNITS]
    return sum(1 for u in units if sig_a.get(u) != sig_b.get(u))


# ============================================================================
# v3.4 DU enforcement
# ============================================================================

def _get_family_index(lineup_index, scenario_families):
    """Returns the family index for a given lineup_index per family['count']."""
    if scenario_families is None or lineup_index is None:
        return None
    cumulative = 0
    for fi, family in enumerate(scenario_families):
        cumulative += family['count']
        if lineup_index < cumulative:
            return fi
    return len(scenario_families) - 1


def check_du_against_priors(
    current_sig, prior_signatures, within_min, across_min,
    scenario_families=None, current_lineup_index=None,
):
    """Returns list of violation records (A3 round-4 fix structure).

    Each record carries lineup_i and lineup_j (with lineup_i < lineup_j by
    convention) plus signature_i and signature_j. The Phase 5 dispatch
    caller derives affected_lineup_indices from the union of {lineup_i,
    lineup_j} across the violation list.
    """
    violations = []
    cur_family = _get_family_index(current_lineup_index, scenario_families)

    # In incremental check, the new lineup is always at a higher index than
    # any prior. If current_lineup_index is None, fall back to the position
    # the new lineup would occupy: len(prior_signatures).
    cur_idx = current_lineup_index if current_lineup_index is not None \
        else len(prior_signatures)

    for prior_idx, prior_sig in enumerate(prior_signatures):
        prior_family = _get_family_index(prior_idx, scenario_families)

        if scenario_families is None:
            same_family = True
        else:
            same_family = (cur_family == prior_family)

        # Convention: lineup_i < lineup_j. In incremental check,
        # prior_idx < cur_idx, so lineup_i = prior_idx, lineup_j = cur_idx.
        lineup_i = min(prior_idx, cur_idx)
        lineup_j = max(prior_idx, cur_idx)
        signature_i = prior_sig if lineup_i == prior_idx else current_sig
        signature_j = current_sig if lineup_j == cur_idx else prior_sig

        if same_family:
            if within_min is None or within_min <= 0:
                continue
            distance = du_distance(current_sig, prior_sig, exclude_anchor=True)
            if distance < within_min:
                violations.append({
                    'lineup_i': lineup_i,
                    'lineup_j': lineup_j,
                    'axis': 'within_family',
                    'threshold': within_min,
                    'distance': distance,
                    'signature_i': signature_i,
                    'signature_j': signature_j,
                    'matched_units': matched_units(current_sig, prior_sig, exclude_anchor=True),
                })
        else:
            if across_min is None or across_min <= 0:
                continue
            distance = du_distance(current_sig, prior_sig, exclude_anchor=False)
            if distance < across_min:
                violations.append({
                    'lineup_i': lineup_i,
                    'lineup_j': lineup_j,
                    'axis': 'across_family',
                    'threshold': across_min,
                    'distance': distance,
                    'signature_i': signature_i,
                    'signature_j': signature_j,
                    'matched_units': matched_units(current_sig, prior_sig, exclude_anchor=False),
                })

    return violations

def pick_penalty_target(violations, retry_index):
    """Returns DU_PENALTY_ROTATION[retry_index - 1] or None if out of range."""
    if retry_index < 1 or retry_index > len(DU_PENALTY_ROTATION):
        return None
    return DU_PENALTY_ROTATION[retry_index - 1]


def _bucket_drivers(target_unit, lineup_df, slate_metadata):
    """Returns list of player_ids that are bucket drivers for target_unit."""
    if target_unit == 'sp_pair':
        return list(_get_sp_ids(lineup_df))
    if target_unit == 'primary_stack':
        primary = _identify_primary_stack(lineup_df)
        if primary == 'NONE':
            return []
        return _team_hitter_ids(lineup_df, primary)
    if target_unit == 'secondary_stack':
        primary = _identify_primary_stack(lineup_df)
        secondary = _identify_secondary_stack(lineup_df, primary)
        if secondary == 'NONE':
            return []
        return _team_hitter_ids(lineup_df, secondary)
    if target_unit == 'game_environment':
        modal_env = _modal_environment(lineup_df, slate_metadata)
        if slate_metadata is None or 'games' not in slate_metadata:
            return []
        games_dict = slate_metadata['games']
        drivers = []
        for _, row in lineup_df.iterrows():
            assigned = row.get('Assigned_Position')
            pos_set = _parse_positions(row['Position'])
            is_hitter = (assigned in HITTER_POSITIONS) if assigned is not None else (
                (pos_set & HITTER_POSITIONS) and 'P' not in pos_set
            )
            if not is_hitter:
                continue
            gid = row.get('Game_ID')
            if gid is None or pd.isna(gid):
                continue
            game_meta = games_dict.get(gid)
            if game_meta is None:
                continue
            env = game_meta.get('environment') or _classify_game_environment_for_game(game_meta)
            if env == modal_env:
                drivers.append(row['Player_ID'])
        return drivers
    if target_unit == 'chalk_one_off':
        primary = _identify_primary_stack(lineup_df)
        secondary = _identify_secondary_stack(lineup_df, primary)
        candidates = _identify_one_off_candidates(lineup_df, primary, secondary)
        if len(candidates) == 0:
            return []
        candidates = candidates.copy()
        candidates['_own_pri'] = candidates['Ownership_Tier'].apply(_ownership_priority)
        candidates['_div_pri'] = candidates['Notes'].apply(_divergence_priority)
        candidates = candidates.sort_values(
            by=['_own_pri', '_div_pri', 'Salary', 'Player_ID'],
            ascending=[True, True, True, True]
        )
        return [candidates.iloc[0]['Player_ID']]
    return []


def _team_hitter_ids(lineup_df, team):
    """Helper: Player_IDs for a given team's non-pitcher rostered hitters."""
    ids = []
    for _, row in lineup_df.iterrows():
        if row['Team'] != team:
            continue
        assigned = row.get('Assigned_Position')
        pos_set = _parse_positions(row['Position'])
        is_hitter = (assigned in HITTER_POSITIONS) if assigned is not None else (
            (pos_set & HITTER_POSITIONS) and 'P' not in pos_set
        )
        if is_hitter:
            ids.append(row['Player_ID'])
    return ids


def du_penalty_dict_for_target(
    target_unit, violations, lineup_df, projections_df, slate_metadata,
):
    """Returns {player_id: penalty_value} for bucket drivers of target_unit
    where target_unit appears in matched_units of at least one violation.
    Returns {} if lineup_df is None/empty or target doesn't match.
    """
    if lineup_df is None or len(lineup_df) == 0:
        return {}
    target_matches = any(target_unit in v.get('matched_units', []) for v in violations)
    if not target_matches:
        return {}
    drivers = _bucket_drivers(target_unit, lineup_df, slate_metadata)
    penalty = {}
    for pid in drivers:
        ceiling_series = projections_df.loc[
            projections_df['Player_ID'] == pid, 'Ceiling'
        ]
        if len(ceiling_series) == 0:
            continue
        penalty[pid] = DU_PENALTY_MAGNITUDE * float(ceiling_series.values[0])
    return penalty


def validate_du_portfolio(
    du_signatures, mode, threshold_table_row, scenario_families=None,
):
    """Post-solve validation operating on precomputed signatures.

    threshold_table_row is a (within_family_min, across_family_min) tuple.

    Returns dict with: pass, pairwise_distances, within_family_violations,
    across_family_violations, relaxation_applied (caller-filled).

    Violation records carry lineup_i and lineup_j with lineup_i < lineup_j
    by convention (A3 round-4 fix). Phase 5 dispatch derives affected
    lineup indices from the union of {lineup_i, lineup_j} across the
    violation list.
    """
    within_min, across_min = threshold_table_row
    pairwise = []
    within_violations = []
    across_violations = []

    n = len(du_signatures)
    for i in range(n):
        cur_family = _get_family_index(i, scenario_families) if scenario_families else None
        for j in range(i + 1, n):
            prior_family = _get_family_index(j, scenario_families) if scenario_families else None

            if scenario_families is None:
                same_family = True
            else:
                same_family = (cur_family == prior_family)

            if same_family:
                d = du_distance(du_signatures[i], du_signatures[j], exclude_anchor=True)
                pairwise.append((i, j, d))
                if within_min is not None and within_min > 0 and d < within_min:
                    within_violations.append({
                        'lineup_i': i,
                        'lineup_j': j,
                        'axis': 'within_family',
                        'threshold': within_min,
                        'distance': d,
                        'signature_i': du_signatures[i],
                        'signature_j': du_signatures[j],
                        'matched_units': matched_units(
                            du_signatures[i], du_signatures[j], exclude_anchor=True
                        ),
                    })
            else:
                d = du_distance(du_signatures[i], du_signatures[j], exclude_anchor=False)
                pairwise.append((i, j, d))
                if across_min is not None and across_min > 0 and d < across_min:
                    across_violations.append({
                        'lineup_i': i,
                        'lineup_j': j,
                        'axis': 'across_family',
                        'threshold': across_min,
                        'distance': d,
                        'signature_i': du_signatures[i],
                        'signature_j': du_signatures[j],
                        'matched_units': matched_units(
                            du_signatures[i], du_signatures[j], exclude_anchor=False
                        ),
                    })

    return {
        'pass': len(within_violations) == 0 and len(across_violations) == 0,
        'pairwise_distances': pairwise,
        'within_family_violations': within_violations,
        'across_family_violations': across_violations,
        'relaxation_applied': None,
    }

def _compute_relaxed_thresholds(base_within, base_across, relaxation_idx):
    """Apply DU_RELAXATION_ORDER steps 0..relaxation_idx (inclusive).
    relaxation_idx == -1 means no relaxation; returns base.
    """
    within = base_within
    across = base_across
    if relaxation_idx < 0:
        return within, across
    for step_idx in range(relaxation_idx + 1):
        if step_idx >= len(DU_RELAXATION_ORDER):
            break
        axis, frm, to = DU_RELAXATION_ORDER[step_idx]
        if axis == 'within_family' and within is not None and within == frm:
            within = to if to > 0 else None
        elif axis == 'across_family' and across is not None and across == frm:
            across = to if to > 0 else None
    return within, across


def _relaxation_summary(base_within, base_across, relaxation_idx):
    """Human-readable summary of relaxation steps actually applied."""
    if relaxation_idx < 0:
        return None
    parts = []
    cur_within = base_within
    cur_across = base_across
    for step_idx in range(min(relaxation_idx + 1, len(DU_RELAXATION_ORDER))):
        axis, frm, to = DU_RELAXATION_ORDER[step_idx]
        if axis == 'within_family' and cur_within is not None and cur_within == frm:
            parts.append(f'{axis} {frm}->{to}')
            cur_within = to if to > 0 else None
        elif axis == 'across_family' and cur_across is not None and cur_across == frm:
            parts.append(f'{axis} {frm}->{to}')
            cur_across = to if to > 0 else None
    if not parts:
        return None
    return ', '.join(parts)


# ============================================================================
# v3.7 build_multi_lineup
# ============================================================================

def _resolve_du_threshold_row(n_lineups, mode, explicit):
    """Resolve the active DU threshold row from inputs (A1 round-4 fix).

    Parameters:
      n_lineups: portfolio size for size_class derivation.
      mode: 'cash' | 'gpp' | 'portfolio_ev' | 'wta' (Framework v2.7 modes).
      explicit: one of:
        - _DU_AUTO (sentinel, the default): auto-derive from (n_lineups, mode)
          via DU_THRESHOLD_TABLE.
        - None: explicit disable. Returns None to signal "DU off."
        - A 2-tuple (within, across): caller-provided override.

    Returns: tuple (within, across) or None.
      Returning (None, None) means "the table prescribes no enforcement at
      this size/mode" (e.g., n=1). Returning None means "explicit caller
      disable." build_multi_lineup treats both as "DU disabled" in the
      du_enforced check; the distinction is preserved here so a caller can
      tell which path was taken if needed.
    """
    if explicit is None:
        return None
    if explicit != _DU_AUTO:
        return tuple(explicit)

    if n_lineups <= 1:
        size_class = '1'
    elif n_lineups <= 3:
        size_class = '2-3'
    else:
        size_class = '4+'

    if size_class == '1':
        mode_key = 'any'
    elif mode == 'wta':
        mode_key = 'wta'
    elif mode in ('portfolio_ev', 'gpp', 'multi_entry_gpp'):
        mode_key = 'gpp' if size_class == '2-3' else 'multi_entry_gpp'
    elif mode == 'cash':
        mode_key = 'any'
    else:
        mode_key = 'gpp' if size_class == '2-3' else 'multi_entry_gpp'

    return DU_THRESHOLD_TABLE.get((size_class, mode_key), (None, None))


def build_multi_lineup(
    projections_df,
    n_lineups,
    mode='portfolio_ev',
    target='ceiling',
    overlap_preset='typical',
    scenario_families=None,
    du_threshold_row=None,
    slate_metadata=None,
    max_sp_exposure=None,
    max_sp_pair_repetition=None,
    sp_pair_coverage_plan=None,
    enforce_wta_stack_core_uniqueness=True,
    time_budget_s=None,
    solver_time_limit_s=None,
    **single_lineup_kwargs
):
    """Multi-lineup wrapper with v3.4 DU enforcement and v3.7 anchor caps.

    v3.20 (F13) separates the clock from the pool. A solve that hits the time
    limit no longer climbs the overlap ladder, no longer steps DU relaxation,
    and no longer contributes its cost to the per-lineup budget reserve. It is
    recorded in ``failed_indices`` and named in ``solver_report`` as a timeout,
    and the loop moves to the next lineup. Relaxing a construction rule because
    the machine was slow is a strategy change that is invisible in the certified
    output, which is the exact inversion CLAUDE.md forbids.

    v3.19 ``time_budget_s`` bounds the wall-clock spent generating lineups.
    Default None preserves prior behavior exactly (unbounded). When set, the
    per-lineup loop stops before starting a lineup it cannot afford and returns
    what it has under ``budget``, so a caller running inside a hard execution
    ceiling gets a short bank plus a diagnostic instead of being killed with no
    output. Cost grows superlinearly in n_lineups because each lineup carries
    overlap constraints against all priors (measured on a 159-row pool: n=5
    3.2s, n=8 7.6s, n=10 12.2s), so an unbounded call is not safe to assume
    finishes inside a fixed budget.

    Per Framework v2.7: post-solve DU validation with deterministic
    penalty rotation; threshold-only relaxation; B1 round-3 fix
    (orthogonal pivots from snapshotted base shell).

    v3.7 anchor exposure controls are separate from DU. max_sp_exposure
    caps individual SP usage; max_sp_pair_repetition caps repeated SP pairs.
    Both accept None, int, or 'auto'.

    v3.12 SP-pair coverage can hard-seed audited viable SP pairs for small
    slates by passing sp_pair_coverage_plan from resolve_sp_pair_coverage_plan().

    DU enforcement defaults to AUTO (A1 round-4 fix): the threshold row
    is resolved from (n_lineups, mode) via DU_THRESHOLD_TABLE unless the
    caller overrides. Explicit du_threshold_row=None disables enforcement.

    Returns dict:
      lineups, failed_indices, max_overlap_base (v3.3 contract preserved)
      du_validation: dict with pass/relaxation_applied/pairwise_summary
      du_signatures: list of signature dicts (one per produced lineup)
      anchor_validation: dict with SP exposure and SP-pair cap provenance
      sp_pair_coverage_validation: dict with required pair coverage provenance
    """
    overlap_pct = {'conservative': 0.60, 'typical': 0.45, 'aggressive': 0.30}[overlap_preset]
    max_overlap_base = max(2, int(ROSTER_SIZE * overlap_pct))

    lineups = []
    stack_cores = []
    prior_lineup_ids = []
    failed_indices = []
    prior_signatures = []
    du_relaxation_high_water = -1

    # A1 round-4 fix: resolve DU threshold via auto-derivation unless
    # explicitly overridden or disabled.
    resolved_row = _resolve_du_threshold_row(n_lineups, mode, du_threshold_row)
    du_enforced = resolved_row is not None and any(t is not None for t in resolved_row)
    base_within, base_across = resolved_row if du_enforced else (None, None)

    base_excludes_for_caps = single_lineup_kwargs.get('excludes') or []
    eligible_sp_count = len(_eligible_sp_ids_for_anchor_caps(
        projections_df, excludes=base_excludes_for_caps
    ))
    active_sp_cap = _resolve_anchor_cap(
        max_sp_exposure, 'sp', n_lineups, eligible_sp_count
    )
    active_pair_cap = _resolve_anchor_cap(
        max_sp_pair_repetition, 'pair', n_lineups, eligible_sp_count
    )

    # v3.12 hard SP-pair coverage: seed required audited pairs before filler
    # lineups. Pair coverage takes precedence over auto anchor caps; otherwise
    # an SP exposure cap below (viable_sp_count - 1) would make exact coverage
    # impossible by construction.
    coverage_plan = sp_pair_coverage_plan or None
    required_sp_pairs = []
    seed_sp_pairs = []
    coverage_cap_notes = []
    if coverage_plan and coverage_plan.get('policy') == 'hard_all_pairs':
        required_sp_pairs = [tuple(sorted(pair, key=str)) for pair in coverage_plan.get('required_sp_pairs') or []]
        seed_sp_pairs = list(required_sp_pairs)
        if len(required_sp_pairs) > n_lineups:
            raise ValueError('hard_all_pairs SP coverage requires n_lineups >= required pair count')
        required_usage = _sp_pair_coverage_required_usage(required_sp_pairs)
        if active_sp_cap is not None and required_usage:
            min_required_sp_cap = max(required_usage.values())
            if active_sp_cap < min_required_sp_cap:
                coverage_cap_notes.append(
                    f'max_sp_exposure raised from {active_sp_cap} to {min_required_sp_cap} for required SP-pair coverage'
                )
                active_sp_cap = min_required_sp_cap
        if active_pair_cap is not None and active_pair_cap < 1:
            coverage_cap_notes.append('max_sp_pair_repetition raised from 0 to 1 for required SP-pair coverage')
            active_pair_cap = 1
    elif coverage_plan and coverage_plan.get('policy') == 'soft_unique_pairs':
        target_unique = min(
            int(coverage_plan.get('target_unique_pairs') or 0),
            n_lineups,
        )
        seed_sp_pairs = [
            tuple(sorted(pair, key=str))
            for pair in (coverage_plan.get('priority_sp_pairs') or [])[:target_unique]
        ]

    sp_usage = Counter()
    sp_pair_usage = Counter()

    budget_started = _time.monotonic()
    budget_s = None if time_budget_s is None else float(time_budget_s)
    budget_report = {
        'time_budget_s': budget_s,
        'exhausted': False,
        'lineups_requested': int(n_lineups),
        'lineups_built': 0,
        'elapsed_s': 0.0,
    }
    per_lineup_cost = None

    # F13 bookkeeping. Kept separate from failed_indices because "the pool could
    # not produce a legal lineup" and "the solver ran out of seconds" call for
    # opposite responses, and the old single None told the caller neither.
    timed_out_indices = []
    time_limited_accepted = 0
    proven_infeasible_indices = []
    solver_timeouts = 0

    def _solve(**solve_kwargs):
        """One solve, bounded by what is left of the budget, with its status.

        Shrinking the per-solve limit to the remaining budget reduces search
        effort. It never touches the legal player set, so it is the lever that
        is allowed here.
        """
        status = _new_solver_status()
        remaining = None
        if budget_s is not None:
            remaining = budget_s - (_time.monotonic() - budget_started)
        solve_kwargs.setdefault(
            'time_limit_s', resolve_solver_time_limit(solver_time_limit_s, remaining)
        )
        solve_kwargs['status_out'] = status
        df_out, obj_out = build_single_lineup(
            projections_df, target=target, **solve_kwargs
        )
        return df_out, obj_out, status

    for i in range(n_lineups):
        if budget_s is not None:
            elapsed = _time.monotonic() - budget_started
            # Stop before starting a lineup the budget cannot cover. Each lineup
            # costs at least as much as the running average because overlap
            # constraints accumulate, so the average is a floor, not an estimate.
            projected = elapsed + (per_lineup_cost or 0.0)
            if elapsed >= budget_s or (per_lineup_cost is not None and projected > budget_s):
                budget_report['exhausted'] = True
                break
        lineup_started = _time.monotonic()
        accepted = None  # A1 round-2 fix
        relaxation_idx = -1

        while accepted is None:
            iteration_kwargs = dict(single_lineup_kwargs)

            # F19: every merge below used to be list(set(...)), so the order of
            # the locks and excludes handed to the solver came out of a
            # hash-randomized set. Those lists become MILP constraint rows, and
            # row order breaks ties in branch and bound. stable_union sorts once
            # and the ordering stops depending on which process is running.
            if i < len(seed_sp_pairs):
                iteration_kwargs['locks'] = stable_union(
                    iteration_kwargs.get('locks'), seed_sp_pairs[i])

            if mode == 'wta' and scenario_families:
                family = _select_family_for_lineup(i, scenario_families)
                iteration_kwargs['stack_constraints'] = {
                    'team': family['team'],
                    'min_size': family.get('min_size', 4),
                    'max_size': family.get('max_size', 5),
                }
                iteration_kwargs['locks'] = stable_union(
                    iteration_kwargs.get('locks'), [family['anchor']])

            if mode == 'wta' and enforce_wta_stack_core_uniqueness and stack_cores:
                iteration_kwargs['stack_core_blocklist'] = [
                    sorted(core, key=str) for core in stack_cores
                ]

            if active_sp_cap is not None:
                capped_sps = {str(pid) for pid, count in sp_usage.items()
                              if count >= active_sp_cap}
                if i < len(seed_sp_pairs):
                    capped_sps -= {str(x) for x in seed_sp_pairs[i]}
                if capped_sps:
                    iteration_kwargs['excludes'] = stable_union(
                        iteration_kwargs.get('excludes'), capped_sps)

            if active_pair_cap is not None:
                # sp_pair_usage is keyed by frozenset, so tuple(pair) unpacked in
                # hash order. Sorting inside the tuple and across the list makes
                # the emitted combo rows identical run to run.
                capped_pairs = sorted(
                    (tuple(sorted(pair, key=str)) for pair, count in sp_pair_usage.items()
                     if count >= active_pair_cap),
                    key=lambda combo: tuple(str(x) for x in combo),
                )
                if capped_pairs:
                    iteration_kwargs['forbidden_player_combos'] = list(
                        iteration_kwargs.get('forbidden_player_combos') or []
                    ) + capped_pairs

            if du_enforced:
                active_within, active_across = _compute_relaxed_thresholds(
                    base_within, base_across, relaxation_idx
                )
            else:
                active_within, active_across = None, None

            # Inner overlap-feasibility loop (existing v3.3 logic)
            lineup_df, obj = None, None
            current_overlap = max_overlap_base
            relaxed_overlap_used = None
            lineup_timed_out = False
            solve_status = _new_solver_status()

            while current_overlap <= MAX_OVERLAP_CEILING:
                attempt_kwargs = dict(iteration_kwargs)
                if prior_lineup_ids:
                    attempt_kwargs['overlap_reference'] = prior_lineup_ids
                    attempt_kwargs['max_overlap'] = current_overlap

                try:
                    lineup_df, obj, solve_status = _solve(**attempt_kwargs)
                except StackInfeasibleError:
                    raise

                if solve_status.get('timed_out'):
                    solver_timeouts += 1
                if lineup_df is not None:
                    if solve_status.get('optimality') == 'time_limited':
                        time_limited_accepted += 1
                    if current_overlap > max_overlap_base:
                        relaxed_overlap_used = current_overlap
                    break

                # F13: the overlap ladder answers "this pool cannot make a lineup
                # this distinct from the priors". It does not answer "the solver
                # ran out of seconds", and climbing it on a timeout records a
                # loosened diversity rule the operator never chose.
                if solve_status.get('timed_out'):
                    lineup_timed_out = True
                    break

                if not prior_lineup_ids:
                    break

                current_overlap += 1

            if lineup_df is None:
                if lineup_timed_out:
                    timed_out_indices.append(i)
                    failed_indices.append(i)
                    break
                if solve_status.get('proven_infeasible'):
                    proven_infeasible_indices.append(i)
                if du_enforced and relaxation_idx + 1 < len(DU_RELAXATION_ORDER):
                    relaxation_idx += 1
                    du_relaxation_high_water = max(du_relaxation_high_water, relaxation_idx)
                    continue
                failed_indices.append(i)
                break

            if not du_enforced:
                accepted = {
                    'lineup_df': lineup_df,
                    'objective': obj,
                    'sig': None,
                    'retry_count': 0,
                    'relaxation_idx': -1,
                    'relaxed_overlap': relaxed_overlap_used,
                    'optimality': solve_status.get('optimality'),
                }
                break

            sig = compute_unit_signature(lineup_df, slate_metadata)
            violations = check_du_against_priors(
                sig, prior_signatures, active_within, active_across,
                scenario_families=scenario_families,
                current_lineup_index=i,
            )

            if not violations:
                accepted = {
                    'lineup_df': lineup_df,
                    'objective': obj,
                    'sig': sig,
                    'retry_count': 0,
                    'relaxation_idx': relaxation_idx,
                    'relaxed_overlap': relaxed_overlap_used,
                    'optimality': solve_status.get('optimality'),
                }
                break

            # B1 round-3 fix: snapshot BASE shell. Retries test orthogonal
            # pivots from this base, NOT cumulative pivots.
            base_lineup_df = lineup_df
            base_violations = violations

            for retry in range(1, MAX_DU_PENALTY_RETRIES + 1):
                target_unit = pick_penalty_target(base_violations, retry)
                if target_unit is None:
                    break

                penalty_dict = du_penalty_dict_for_target(
                    target_unit, base_violations, base_lineup_df,
                    projections_df, slate_metadata,
                )

                attempt_kwargs = dict(iteration_kwargs)
                if prior_lineup_ids:
                    attempt_kwargs['overlap_reference'] = prior_lineup_ids
                    attempt_kwargs['max_overlap'] = current_overlap
                attempt_kwargs['penalized_players'] = penalty_dict

                try:
                    retry_lineup_df, retry_obj, retry_status = _solve(**attempt_kwargs)
                except StackInfeasibleError:
                    raise

                if retry_status.get('timed_out'):
                    solver_timeouts += 1
                    if retry_lineup_df is None:
                        # Burning the remaining penalty retries against a clock
                        # accomplishes nothing and then hands the loop a
                        # relaxation step it did not earn.
                        lineup_timed_out = True
                        break

                if retry_lineup_df is None:
                    continue
                if retry_status.get('optimality') == 'time_limited':
                    time_limited_accepted += 1

                retry_sig = compute_unit_signature(retry_lineup_df, slate_metadata)
                retry_violations = check_du_against_priors(
                    retry_sig, prior_signatures, active_within, active_across,
                    scenario_families=scenario_families,
                    current_lineup_index=i,
                )

                if not retry_violations:
                    accepted = {
                        'lineup_df': retry_lineup_df,
                        'objective': retry_obj,
                        'sig': retry_sig,
                        'retry_count': retry,
                        'relaxation_idx': relaxation_idx,
                        'relaxed_overlap': relaxed_overlap_used,
                        'optimality': retry_status.get('optimality'),
                    }
                    break

            if accepted is not None:
                break

            # Step relaxation. F13: not on a timeout. A DU threshold is a
            # strategy control, and stepping it because the solver ran long
            # writes a relaxation into the run record that no one decided.
            if lineup_timed_out:
                timed_out_indices.append(i)
                failed_indices.append(i)
                break
            if relaxation_idx + 1 < len(DU_RELAXATION_ORDER):
                relaxation_idx += 1
                du_relaxation_high_water = max(du_relaxation_high_water, relaxation_idx)
                continue
            failed_indices.append(i)
            break

        if accepted is not None:
            record = {
                'lineup': accepted['lineup_df'],
                'objective': accepted['objective'],
                'lineup_id': i + 1,
            }
            if accepted.get('relaxed_overlap') is not None:
                record['relaxed_overlap'] = accepted['relaxed_overlap']
            if accepted.get('optimality') == 'time_limited':
                record['optimality'] = 'time_limited'
            if du_enforced:
                if accepted['retry_count'] > 0:
                    record['du_retry_count'] = accepted['retry_count']
                if accepted['relaxation_idx'] >= 0:
                    record['du_relaxation_idx'] = accepted['relaxation_idx']
            lineups.append(record)
            cost = _time.monotonic() - lineup_started
            # F13: only a lineup that actually solved tells you what the next one
            # costs. Folding a timed-out solve in sets the reserve to the time
            # limit, and the loop then refuses to start any lineup with less than
            # a full time limit left, which is how one slow solve ended the bank.
            if accepted.get('optimality') != 'time_limited':
                per_lineup_cost = cost if per_lineup_cost is None else max(per_lineup_cost, cost)
            prior_lineup_ids.append(accepted['lineup_df']['Player_ID'].tolist())

            accepted_sp_ids = _get_ordered_sp_ids(accepted['lineup_df'])
            for sp_id in accepted_sp_ids:
                sp_usage[sp_id] += 1
            if len(accepted_sp_ids) == 2:
                sp_pair_usage[frozenset(accepted_sp_ids)] += 1

            if du_enforced:
                prior_signatures.append(accepted['sig'])

            if mode == 'wta' and iteration_kwargs.get('stack_constraints'):
                stack_team = iteration_kwargs['stack_constraints']['team']
                core = frozenset(
                    accepted['lineup_df'][
                        accepted['lineup_df']['Team'] == stack_team
                    ]['Player_ID'].tolist()
                )
                stack_cores.append(core)

    # Final DU validation. A2 round-4 fix: validate against the final
    # active relaxed thresholds, not the base thresholds, so an accepted
    # relaxed build does not report pass=False.
    if du_enforced and prior_signatures:
        active_within, active_across = _compute_relaxed_thresholds(
            base_within, base_across, du_relaxation_high_water
        )
        validation = validate_du_portfolio(
            prior_signatures, mode,
            (active_within, active_across),
            scenario_families=scenario_families,
        )
        relaxation_summary = _relaxation_summary(
            base_within, base_across, du_relaxation_high_water
        )
        if relaxation_summary is not None:
            validation['relaxation_applied'] = relaxation_summary

        n = len(prior_signatures)
        total_pairs = n * (n - 1) // 2
        if validation['pass']:
            min_thresholds = []
            if active_within is not None:
                min_thresholds.append(active_within)
            if active_across is not None:
                min_thresholds.append(active_across)
            min_threshold = max(min_thresholds) if min_thresholds else 0
            if relaxation_summary is not None:
                validation['pairwise_summary'] = (
                    f'RELAXED: {relaxation_summary}; '
                    f'{total_pairs} of {total_pairs} lineup pairs cleared '
                    f'{min_threshold}-unit minimum under relaxation'
                )
            else:
                validation['pairwise_summary'] = (
                    f'{total_pairs} of {total_pairs} lineup pairs cleared '
                    f'{min_threshold}-unit minimum'
                )
        else:
            cleared = total_pairs - len(validation['within_family_violations']) \
                - len(validation['across_family_violations'])
            validation['pairwise_summary'] = (
                f'{cleared} of {total_pairs} lineup pairs cleared threshold; '
                f'{len(validation["within_family_violations"])} within-family + '
                f'{len(validation["across_family_violations"])} across-family violations'
            )
    else:
        validation = {
            'pass': True,
            'pairwise_distances': [],
            'within_family_violations': [],
            'across_family_violations': [],
            'relaxation_applied': None,
            'pairwise_summary': None,
        }

    anchor_validation = _anchor_validation_dict(
        sp_usage, sp_pair_usage, active_sp_cap, active_pair_cap
    )
    if coverage_cap_notes:
        anchor_validation['relaxation_applied'] = '; '.join(coverage_cap_notes)
        anchor_validation['summary'] += '; ' + '; '.join(coverage_cap_notes)

    sp_pair_coverage_validation = validate_sp_pair_coverage(lineups, coverage_plan)

    budget_report['lineups_built'] = len(lineups)
    budget_report['elapsed_s'] = round(_time.monotonic() - budget_started, 3)

    # A portfolio is not clean because the gates passed; it is clean when the
    # relaxation counts are zero. These were computed per lineup and then lived
    # only inside individual records, so the run record could not answer "what
    # did the engine give up to produce this", which is exactly the fact
    # post-slate review needs.
    relaxations = {
        'overlap_relaxed_lineups': sum(1 for r in lineups if 'relaxed_overlap' in r),
        'du_relaxed_lineups': sum(1 for r in lineups if 'du_relaxation_idx' in r),
        'du_retry_lineups': sum(1 for r in lineups if r.get('du_retry_count')),
        'du_relaxation_high_water': du_relaxation_high_water,
        'coverage_cap_notes': list(coverage_cap_notes),
        'failed_lineup_count': len(failed_indices),
        'requested': int(n_lineups),
        'built': len(lineups),
        # F13: a timeout is a compute fact, not a relaxation. It is counted here
        # so the run record can say "the clock, not the pool" without the reader
        # having to infer it from a bare failed index.
        'timed_out_lineup_count': len(timed_out_indices),
        'time_limited_lineups': sum(1 for r in lineups if r.get('optimality') == 'time_limited'),
    }
    relaxations['clean'] = not (
        relaxations['overlap_relaxed_lineups']
        or relaxations['du_relaxed_lineups']
        or relaxations['coverage_cap_notes']
        or relaxations['failed_lineup_count']
    )
    warnings = []
    if relaxations['overlap_relaxed_lineups']:
        warnings.append(
            f"overlap cap relaxed on {relaxations['overlap_relaxed_lineups']} of "
            f"{len(lineups)} lineups")
    if relaxations['du_relaxed_lineups']:
        warnings.append(
            f"DU thresholds relaxed on {relaxations['du_relaxed_lineups']} lineups "
            f"(high water step {du_relaxation_high_water})")
    for note in coverage_cap_notes:
        warnings.append(f"coverage cap: {note}")
    if failed_indices:
        warnings.append(
            f"{len(failed_indices)} of {n_lineups} requested lineups were not built "
            f"(indices {failed_indices[:10]})")
    if timed_out_indices:
        warnings.append(
            f"{len(timed_out_indices)} lineups hit the {resolve_solver_time_limit(solver_time_limit_s)}s "
            f"solver time limit and were skipped without relaxing any control "
            f"(indices {timed_out_indices[:10]}); this is the clock, not the pool")
    if relaxations['time_limited_lineups']:
        warnings.append(
            f"{relaxations['time_limited_lineups']} lineups were accepted from a "
            f"time-limited incumbent (feasible and verified, not proven optimal)")
    relaxations['warnings'] = warnings

    solver_report = {
        'time_limit_s': resolve_solver_time_limit(solver_time_limit_s),
        'solver_timeouts': solver_timeouts,
        'timed_out_lineup_indices': list(timed_out_indices),
        'time_limited_accepted': time_limited_accepted,
        'proven_infeasible_lineup_indices': list(proven_infeasible_indices),
        'relaxation_on_timeout': False,
        'note': 'a solver time limit never steps the overlap ladder or the DU '
                'relaxation order; deterministic bookkeeping, never a claim',
    }

    return {
        'lineups': lineups,
        'failed_indices': failed_indices,
        'max_overlap_base': max_overlap_base,
        'du_validation': validation,
        'du_signatures': list(prior_signatures),
        'anchor_validation': anchor_validation,
        'sp_pair_coverage_plan': coverage_plan,
        'sp_pair_coverage_validation': sp_pair_coverage_validation,
        'budget': budget_report,
        'relaxations': relaxations,
        'solver_report': solver_report,
    }

# ============================================================================
# v3.10 candidate-bank / contest-fit proxy + review diagnostics layer
# ============================================================================

DEFAULT_CANDIDATE_BANK_CAP = 150
DEFAULT_OWNERSHIP_PCT_BY_TIER = {'Low': 5.0, 'Mid': 12.0, 'High': 25.0}
COMMON_SALARY_BAND_THRESHOLD = 49800
RIGHT_TAIL_TIERS = ('Stable', 'Volatile', 'Eruption', 'Unknown')
DEFAULT_EXPOSURE_DELTA_TOP_N = 20

# v3.13 batting-order clustering is a bounded post-solve selection proxy.
# It never changes F1-F5 projections or MILP feasibility.
BATTING_ORDER_CLUSTER_PER_LINEUP_CAP = 1.25
BATTING_ORDER_CLUSTER_FLOOR = -0.50
SECONDARY_STACK_CLUSTER_WEIGHT = 0.50
BATTING_ORDER_CLUSTER_BASE_BONUS = {
    'WRAPAROUND_STRONG': 0.85,
    'STRONG': 0.80,
    'CONNECTED': 0.40,
    'SCATTERED': 0.00,
    'BOTTOM_ORDER_HEAVY': -0.35,
    'UNKNOWN': 0.00,
    'NONE': 0.00,
}

CONTEST_SHAPE_PROFILE_WEIGHTS = {
    'small_wta': {
        'mode_family': 'wta', 'ceiling_weight': 1.00, 'floor_weight': 0.00,
        'stack_bonus_weight': 1.00, 'batting_order_cluster_weight': 1.00, 'leverage_bonus_weight': 0.75,
        'salary_uniqueness_weight': 0.55, 'right_tail_weight': 0.45,
        'field_pressure_weight': 0.70,
    },
    'mid_wta': {
        'mode_family': 'wta', 'ceiling_weight': 1.00, 'floor_weight': 0.00,
        'stack_bonus_weight': 1.05, 'batting_order_cluster_weight': 1.00, 'leverage_bonus_weight': 0.95,
        'salary_uniqueness_weight': 0.75, 'right_tail_weight': 0.70,
        'field_pressure_weight': 0.90,
    },
    'large_wta': {
        'mode_family': 'wta', 'ceiling_weight': 1.00, 'floor_weight': 0.00,
        'stack_bonus_weight': 1.10, 'batting_order_cluster_weight': 1.00, 'leverage_bonus_weight': 1.20,
        'salary_uniqueness_weight': 1.00, 'right_tail_weight': 1.00,
        'field_pressure_weight': 1.15,
    },
    'single_entry_gpp': {
        'mode_family': 'gpp', 'ceiling_weight': 0.78, 'floor_weight': 0.22,
        'stack_bonus_weight': 0.55, 'batting_order_cluster_weight': 0.75, 'leverage_bonus_weight': 0.30,
        'salary_uniqueness_weight': 0.25, 'right_tail_weight': 0.25,
        'field_pressure_weight': 0.45,
    },
    'portfolio_gpp': {
        'mode_family': 'gpp', 'ceiling_weight': 0.72, 'floor_weight': 0.28,
        'stack_bonus_weight': 0.50, 'batting_order_cluster_weight': 0.75, 'leverage_bonus_weight': 0.35,
        'salary_uniqueness_weight': 0.35, 'right_tail_weight': 0.35,
        'field_pressure_weight': 0.55,
    },
    'mme_gpp': {
        'mode_family': 'gpp', 'ceiling_weight': 0.70, 'floor_weight': 0.30,
        'stack_bonus_weight': 0.50, 'batting_order_cluster_weight': 0.75, 'leverage_bonus_weight': 0.50,
        'salary_uniqueness_weight': 0.55, 'right_tail_weight': 0.45,
        'field_pressure_weight': 0.75,
    },
    'small_field_gpp': {
        'mode_family': 'gpp', 'ceiling_weight': 0.80, 'floor_weight': 0.20,
        'stack_bonus_weight': 0.60, 'batting_order_cluster_weight': 0.80, 'leverage_bonus_weight': 0.30,
        'salary_uniqueness_weight': 0.25, 'right_tail_weight': 0.20,
        'field_pressure_weight': 0.40,
    },
    'mid_field_gpp': {
        'mode_family': 'gpp', 'ceiling_weight': 0.76, 'floor_weight': 0.24,
        'stack_bonus_weight': 0.62, 'batting_order_cluster_weight': 0.80, 'leverage_bonus_weight': 0.42,
        'salary_uniqueness_weight': 0.38, 'right_tail_weight': 0.32,
        'field_pressure_weight': 0.58,
    },
    'large_field_gpp': {
        'mode_family': 'gpp', 'ceiling_weight': 0.72, 'floor_weight': 0.28,
        'stack_bonus_weight': 0.68, 'batting_order_cluster_weight': 0.80, 'leverage_bonus_weight': 0.58,
        'salary_uniqueness_weight': 0.62, 'right_tail_weight': 0.50,
        'field_pressure_weight': 0.82,
    },
    'wta_ticket_satellite': {
        'mode_family': 'wta', 'ceiling_weight': 1.00, 'floor_weight': 0.00,
        'stack_bonus_weight': 1.00, 'batting_order_cluster_weight': 1.00, 'leverage_bonus_weight': 0.85,
        'salary_uniqueness_weight': 0.65, 'right_tail_weight': 0.55,
        'field_pressure_weight': 0.80,
    },
    'cash': {
        'mode_family': 'cash', 'ceiling_weight': 0.30, 'floor_weight': 0.70,
        'stack_bonus_weight': 0.10, 'batting_order_cluster_weight': 0.20, 'leverage_bonus_weight': 0.00,
        'salary_uniqueness_weight': 0.00, 'right_tail_weight': 0.00,
        'field_pressure_weight': 0.10,
    },
    'satellite': {
        'mode_family': 'ticket_line', 'ceiling_weight': 0.58, 'floor_weight': 0.42,
        'stack_bonus_weight': 0.35, 'batting_order_cluster_weight': 0.55, 'leverage_bonus_weight': 0.15,
        'salary_uniqueness_weight': 0.10, 'right_tail_weight': 0.10,
        'field_pressure_weight': 0.25,
    },
}


def _assert_profiles_match_canonical_shapes():
    """R1a: the profile table and the canonical vocabulary agree, at import.

    Before this, three modules each carried their own spelling of the shape set
    and one of them (execution_pipeline) emitted a name that was not a profile
    key. A table that disagrees with the vocabulary now fails on load instead of
    on the one contest that routes to the missing key.
    """
    profile_keys = set(CONTEST_SHAPE_PROFILE_WEIGHTS)
    canonical = set(CONTEST_SHAPES)
    if profile_keys != canonical:
        missing = ', '.join(sorted(canonical - profile_keys)) or 'none'
        extra = ', '.join(sorted(profile_keys - canonical)) or 'none'
        raise RuntimeError(
            'CONTEST_SHAPE_PROFILE_WEIGHTS does not match contest_shapes.CONTEST_SHAPES; '
            f'missing profiles: {missing}; profiles with no canonical shape: {extra}'
        )
    for key, profile in sorted(CONTEST_SHAPE_PROFILE_WEIGHTS.items()):
        declared = OBJECTIVE_CLASS_BY_SHAPE[key]
        if profile['mode_family'] != declared:
            raise RuntimeError(
                f"contest shape '{key}': profile mode_family "
                f"'{profile['mode_family']}' contradicts objective class '{declared}'"
            )


_assert_profiles_match_canonical_shapes()


def resolve_candidate_bank_size(requested_n, explicit=None, cap=DEFAULT_CANDIDATE_BANK_CAP):
    """Resolve default candidate-bank size for post-solve contest-fit evaluation.

    This is intentionally a wrapper-layer helper. It does not change MILP hard
    constraints or claim true ROI simulation. The bank size follows the v3.18 spec:
      - 1 requested lineup  -> 8 candidates
      - 2-3 requested       -> 12 candidates
      - 4-9 requested       -> max(12, requested + 6)
      - 10+ requested       -> ceil(requested * 2), capped

    v3.18 note: the 10+ branch previously collapsed to a hard 40, which starved
    large fields of SP-pair diversity and forced a hand-built candidates_override
    every session. It now scales with the request under the raised cap.
    """
    if explicit is not None:
        value = int(explicit)
        if value < int(requested_n):
            raise ValueError('candidate_bank_size must be >= requested_n')
        return min(value, int(cap)) if cap is not None else value

    requested = int(requested_n)
    if requested <= 1:
        value = 8
    elif requested <= 3:
        value = 12
    elif requested <= 9:
        value = max(12, requested + 6)
    else:
        value = int(ceil(requested * 2))
    return min(value, int(cap)) if cap is not None else value


def _lineup_player_ids(lineup_df):
    return [row['Player_ID'] for _, row in lineup_df.iterrows()]


def _safe_float(value, default=0.0):
    if value is None or pd.isna(value):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _ownership_pct_for_row(row):
    if 'Projected_Ownership_Pct' in row.index:
        val = row.get('Projected_Ownership_Pct')
        if val is not None and not pd.isna(val):
            return _safe_float(val, 0.0)
    return DEFAULT_OWNERSHIP_PCT_BY_TIER.get(row.get('Ownership_Tier', 'Mid'), 12.0)


def _lineup_projected_ownership_sum(lineup_df):
    return sum(_ownership_pct_for_row(row) for _, row in lineup_df.iterrows())


def _salary_band_duplication_penalty(salary_used):
    return 1.0 if float(salary_used) >= COMMON_SALARY_BAND_THRESHOLD else 0.0


def _suppression_trigger_count(lineup_df):
    if 'Notes' not in lineup_df.columns:
        return 0
    return sum(1 for _, row in lineup_df.iterrows() if _suppression_trigger(row.get('Notes')) is not None)


def _low_owned_hitter_count(lineup_df):
    count = 0
    for _, row in lineup_df.iterrows():
        assigned = row.get('Assigned_Position')
        pos_set = _parse_positions(row.get('Position'))
        is_hitter = (assigned in HITTER_POSITIONS) if assigned is not None else (
            bool(pos_set & HITTER_POSITIONS) and 'P' not in pos_set
        )
        if is_hitter and row.get('Ownership_Tier') == 'Low':
            count += 1
    return count


def _lineup_stack_archetype(lineup_df):
    """Return hitter-count structure such as '5-3', '4-2-2', or '3-2-1-1-1'.

    This is a post-solve diagnostic, not a hard stack rule. It helps the
    executor review whether the final portfolio is concentrated in one lineup
    construction shape.
    """
    counts = sorted(_hitter_team_counts(lineup_df).values(), reverse=True)
    if not counts:
        return 'none'
    return '-'.join(str(int(c)) for c in counts if int(c) > 0)


def _extract_batting_order_slot(row):
    """Read a projected/confirmed batting-order slot if the projection CSV has one.

    Accepted column names intentionally cover common projection-builder exports.
    Missing or unparsable slots return None; stack-adjacency review then becomes
    UNKNOWN rather than blocking the optimizer.
    """
    for col in ('Batting_Order', 'BattingOrder', 'Lineup_Slot', 'LineupSlot', 'Order', 'Batting_Slot'):
        if col in row.index:
            raw = row.get(col)
            if raw is None or pd.isna(raw):
                continue
            try:
                slot = int(float(raw))
            except (TypeError, ValueError):
                continue
            if 1 <= slot <= 9:
                return slot
    return None


def _has_consecutive_run(slots, min_run=3):
    """Return True when stack slots include a normal or wraparound run."""
    slot_set = set(int(s) for s in slots)
    if len(slot_set) < min_run:
        return False
    for start in range(1, 10):
        run = [((start + offset - 1) % 9) + 1 for offset in range(min_run)]
        if all(slot in slot_set for slot in run):
            return True
    return False


def _longest_circular_batting_order_run(slots):
    """Return the longest selected run on the circular 1..9 batting order."""
    slot_set = set(int(s) for s in slots)
    if not slot_set:
        return 0
    longest = 0
    for start in range(1, 10):
        run = 0
        for offset in range(9):
            slot = ((start + offset - 1) % 9) + 1
            if slot not in slot_set:
                break
            run += 1
        longest = max(longest, run)
    return min(longest, len(slot_set))


def _team_batting_order_cluster(lineup_df, team, minimum_hitter_count):
    """Classify one stack team's confirmed batting-order connectivity.

    Partial/missing order data is UNKNOWN and receives no selection adjustment.
    This prevents the optimizer from guessing order quality before lineups post.
    """
    if team in (None, 'NONE'):
        return {'team': 'NONE', 'slots': [], 'tier': 'NONE', 'base_bonus': 0.0}

    team_rows = []
    for _, row in lineup_df.iterrows():
        assigned = row.get('Assigned_Position')
        pos_set = _parse_positions(row.get('Position'))
        is_hitter = (assigned in HITTER_POSITIONS) if assigned is not None else (
            bool(pos_set & HITTER_POSITIONS) and 'P' not in pos_set
        )
        if is_hitter and row.get('Team') == team:
            team_rows.append(row)

    if len(team_rows) < int(minimum_hitter_count):
        return {'team': team, 'slots': [], 'tier': 'NONE', 'base_bonus': 0.0}

    slots = [_extract_batting_order_slot(row) for row in team_rows]
    if any(slot is None for slot in slots):
        return {'team': team, 'slots': sorted(s for s in slots if s is not None), 'tier': 'UNKNOWN', 'base_bonus': 0.0}

    unique_slots = sorted(set(slots))
    if len(unique_slots) != len(team_rows):
        return {'team': team, 'slots': unique_slots, 'tier': 'UNKNOWN', 'base_bonus': 0.0}

    # Explicitly penalize bottom-only / bottom-heavy stacks that do not connect
    # back to slots 1-2. A wraparound such as 8-9-1-2 is handled below.
    if (set(unique_slots) <= {7, 8, 9}) or (
        len(unique_slots) >= 4 and min(unique_slots) >= 5 and not set(unique_slots) & {1, 2}
    ):
        tier = 'BOTTOM_ORDER_HEAVY'
    else:
        longest_run = _longest_circular_batting_order_run(unique_slots)
        adjacent_pairs = sum(
            1 for slot in unique_slots
            if (((slot % 9) + 1) in set(unique_slots))
        )
        wraps = 9 in unique_slots and 1 in unique_slots
        if len(unique_slots) >= 3 and longest_run >= 3:
            tier = 'WRAPAROUND_STRONG' if wraps else 'STRONG'
        elif longest_run >= 2 and adjacent_pairs >= max(1, len(unique_slots) - 2):
            tier = 'CONNECTED'
        else:
            tier = 'SCATTERED'

    return {
        'team': team,
        'slots': unique_slots,
        'tier': tier,
        'base_bonus': BATTING_ORDER_CLUSTER_BASE_BONUS[tier],
    }


def _row_has_role_elevation(row):
    """Return True when resolved or audit trigger data contains role_elevation."""
    if _suppression_trigger(row.get('Notes')) == 'role_elevation':
        return True
    raw = row.get('Triggers_Fired_All') if 'Triggers_Fired_All' in row.index else None
    return raw is not None and not pd.isna(raw) and 'role_elevation' in str(raw).lower()


def _role_elevation_diagnostics(lineup_df):
    promoted = 0
    promoted_top_five = 0
    for _, row in lineup_df.iterrows():
        assigned = row.get('Assigned_Position')
        pos_set = _parse_positions(row.get('Position'))
        is_hitter = (assigned in HITTER_POSITIONS) if assigned is not None else (
            bool(pos_set & HITTER_POSITIONS) and 'P' not in pos_set
        )
        if not is_hitter or not _row_has_role_elevation(row):
            continue
        promoted += 1
        slot = _extract_batting_order_slot(row)
        if slot is not None and slot <= 5:
            promoted_top_five += 1
    return {
        'promoted_hitter_count': promoted,
        'promoted_top_five_value_count': promoted_top_five,
    }


def _lineup_batting_order_cluster_summary(lineup_df):
    """Return bounded primary/secondary batting-order cluster diagnostics."""
    primary = _identify_primary_stack(lineup_df)
    secondary = _identify_secondary_stack(lineup_df, primary)
    primary_cluster = _team_batting_order_cluster(
        lineup_df, primary, PRIMARY_STACK_MIN_HITTERS
    )
    secondary_cluster = _team_batting_order_cluster(
        lineup_df, secondary, SECONDARY_STACK_MIN_HITTERS
    )
    raw_bonus = (
        primary_cluster['base_bonus']
        + SECONDARY_STACK_CLUSTER_WEIGHT * secondary_cluster['base_bonus']
    )
    bonus = max(
        BATTING_ORDER_CLUSTER_FLOOR,
        min(BATTING_ORDER_CLUSTER_PER_LINEUP_CAP, raw_bonus),
    )
    if primary_cluster['tier'] == 'UNKNOWN' and secondary_cluster['tier'] in ('UNKNOWN', 'NONE'):
        overall = 'UNKNOWN'
    elif bonus >= 1.0:
        overall = 'ELITE'
    elif bonus >= 0.70:
        overall = 'STRONG'
    elif bonus > 0:
        overall = 'CONNECTED'
    elif bonus < 0:
        overall = 'BOTTOM_ORDER_PENALTY'
    else:
        overall = 'NEUTRAL'
    return {
        'primary_stack_slots': primary_cluster['slots'],
        'secondary_stack_slots': secondary_cluster['slots'],
        'primary_batting_order_cluster_tier': primary_cluster['tier'],
        'secondary_batting_order_cluster_tier': secondary_cluster['tier'],
        'batting_order_cluster_tier': overall,
        'batting_order_cluster_bonus': bonus,
    }


def _lineup_stack_adjacency_tag(lineup_df):
    """Backward-compatible primary-stack adjacency diagnostic."""
    tier = _lineup_batting_order_cluster_summary(lineup_df)[
        'primary_batting_order_cluster_tier'
    ]
    mapping = {
        'NONE': 'STACK_ADJACENCY_NONE',
        'UNKNOWN': 'STACK_ADJACENCY_UNKNOWN',
        'BOTTOM_ORDER_HEAVY': 'BOTTOM_ORDER_STACK',
        'WRAPAROUND_STRONG': 'WRAPAROUND_STACK',
        'STRONG': 'STACK_ADJACENCY_STRONG',
        'CONNECTED': 'STACK_ADJACENCY_WEAK',
        'SCATTERED': 'STACK_ADJACENCY_WEAK',
    }
    return mapping[tier]

def _canonical_right_tail_tier(value):
    if value is None or pd.isna(value):
        return None
    raw = str(value).strip().lower().replace('_', ' ').replace('-', ' ')
    mapping = {
        'stable': 'Stable',
        'low': 'Stable',
        'floor': 'Stable',
        'volatile': 'Volatile',
        'medium': 'Volatile',
        'mid': 'Volatile',
        'eruption': 'Eruption',
        'high': 'Eruption',
        'ceiling': 'Eruption',
    }
    return mapping.get(raw)


def _row_right_tail_volatility_tier(row):
    """Return an explicit Stable / Volatile / Eruption tier or Unknown.

    v3.14 removes the ceiling-minus-floor fallback. A wide projection interval
    can represent uncertainty or weak data rather than useful tournament
    volatility, so missing tier data is neutral in candidate scoring.
    """
    for col in ('Ceiling_Volatility_Tier', 'Right_Tail_Volatility_Tier', 'Volatility_Tier'):
        if col in row.index:
            tier = _canonical_right_tail_tier(row.get(col))
            if tier is not None:
                return tier
    return 'Unknown'


def _lineup_right_tail_volatility_summary(lineup_df):
    counts = Counter()
    for _, row in lineup_df.iterrows():
        counts[_row_right_tail_volatility_tier(row)] += 1
    # Small, bounded candidate-selection bump for lineups with a clear path to
    # a right-tail outcome. This is a contest-fit proxy only.
    bonus = 0.60 * counts.get('Eruption', 0) + 0.25 * counts.get('Volatile', 0)
    return {
        'tier_counts': {tier: counts.get(tier, 0) for tier in RIGHT_TAIL_TIERS},
        'right_tail_bonus': bonus,
    }


def resolve_contest_shape_profile(mode='wta', requested_n=1, contest_shape=None):
    """Resolve the post-solve candidate-selection profile.

    Contest shape profiles adjust only the transparent proxy score used to rank
    already-valid candidates. They do not change MILP constraints or produce
    simulated ROI / win-rate estimates.
    """
    if contest_shape is not None:
        key = str(contest_shape).strip().lower()
        if key not in CONTEST_SHAPE_PROFILE_WEIGHTS:
            valid = ', '.join(sorted(CONTEST_SHAPE_PROFILE_WEIGHTS.keys()))
            raise ValueError(f'contest_shape must be one of: {valid}')
    else:
        requested = int(requested_n or 1)
        mode_key = str(mode or '').lower()
        if mode_key == 'wta':
            if requested <= 3:
                key = 'small_wta'
            elif requested <= 9:
                key = 'mid_wta'
            else:
                key = 'large_wta'
        else:
            if requested <= 1:
                key = 'single_entry_gpp'
            elif requested >= 10:
                key = 'mme_gpp'
            else:
                key = 'portfolio_gpp'
    profile = dict(CONTEST_SHAPE_PROFILE_WEIGHTS[key])
    profile['contest_shape'] = key
    return profile


def field_exposure_delta_report(lineup_records, projections_df=None, top_n=DEFAULT_EXPOSURE_DELTA_TOP_N):
    """Compare our final/candidate exposure to projected field ownership.

    Rows use proxy labels only. The report is meant for review: identifying
    overweight stands, field-neutral chalk, underweights, and intentional fades.
    """
    n_lineups = len(lineup_records or [])
    selected_counts = Counter()
    row_lookup = {}

    for record in lineup_records or []:
        lineup_df = record['lineup']
        for _, row in lineup_df.iterrows():
            pid = row['Player_ID']
            selected_counts[pid] += 1
            row_lookup.setdefault(pid, row)

    if projections_df is not None and len(projections_df) > 0:
        for _, row in projections_df.iterrows():
            pid = row.get('Player_ID')
            if pid is not None and not pd.isna(pid):
                row_lookup.setdefault(pid, row)

    candidate_pids = set(selected_counts.keys())
    if projections_df is not None and len(projections_df) > 0:
        chalk_rows = []
        for _, row in projections_df.iterrows():
            own = _ownership_pct_for_row(row)
            if own >= 10.0:
                chalk_rows.append((own, row.get('Player_ID')))
        chalk_rows.sort(reverse=True)
        candidate_pids.update(pid for _, pid in chalk_rows[:top_n] if pid is not None)

    rows = []
    for pid in candidate_pids:
        row = row_lookup.get(pid)
        if row is None:
            continue
        count = selected_counts.get(pid, 0)
        our_exposure = 100.0 * count / n_lineups if n_lineups else 0.0
        field_own = _ownership_pct_for_row(row)
        delta = our_exposure - field_own
        if count == 0 and field_own >= 20.0:
            intent = 'intentional fade / review'
        elif count == 0 and field_own >= 10.0:
            intent = 'underweight fade'
        elif delta >= 20.0:
            intent = 'overweight stand'
        elif delta >= 8.0:
            intent = 'positive leverage'
        elif delta <= -12.0:
            intent = 'underweight'
        elif abs(delta) <= 8.0:
            intent = 'field-neutral'
        else:
            intent = 'slight overweight' if delta > 0 else 'slight underweight'
        rows.append({
            'player_id': pid,
            'name': row.get('Name'),
            'team': row.get('Team'),
            'position': row.get('Position'),
            'our_exposure_pct': round(our_exposure, 2),
            'projected_field_ownership_pct': round(field_own, 2),
            'exposure_delta_pct': round(delta, 2),
            'lineup_count': int(count),
            'intent': intent,
        })

    rows.sort(key=lambda r: (abs(r['exposure_delta_pct']), r['projected_field_ownership_pct']), reverse=True)
    rows = rows[:int(top_n)]
    return {
        'n_lineups': n_lineups,
        'top_n': int(top_n),
        'rows': rows,
        'summary': f'Field exposure delta: {len(rows)} players reviewed against projected field ownership',
    }


def _lineup_stack_correlation_bonus(lineup_df):
    counts = _hitter_team_counts(lineup_df)
    if not counts:
        return 0.0
    max_stack = max(counts.values())
    secondary = sorted(counts.values(), reverse=True)[1] if len(counts) > 1 else 0
    bonus = 0.0
    if max_stack >= 5:
        bonus += 2.0
    elif max_stack == 4:
        bonus += 1.5
    elif max_stack == 3:
        bonus += 1.0
    if secondary >= 3:
        bonus += 0.75
    elif secondary == 2:
        bonus += 0.50
    return bonus


def compute_field_pressure_score(lineup_df, meta_lineup_ids=None):
    """Deterministic proxy for how much a lineup resembles the projected field.

    This is not ownership ROI. It is a transparent pressure score used by the
    candidate-selection layer to penalize duplicate-prone constructions.
    """
    player_ids = set(_lineup_player_ids(lineup_df))
    meta_ids = set(meta_lineup_ids or [])
    meta_overlap = len(player_ids & meta_ids)
    ownership_total = _lineup_projected_ownership_sum(lineup_df)
    salary_used = float(lineup_df['Salary'].sum()) if 'Salary' in lineup_df.columns else 0.0
    primary = _identify_primary_stack(lineup_df)
    counts = _hitter_team_counts(lineup_df)
    primary_count = counts.get(primary, 0) if primary != 'NONE' else 0
    high_owned_one_offs = 0
    if 'Ownership_Tier' in lineup_df.columns:
        for _, row in lineup_df.iterrows():
            assigned = row.get('Assigned_Position')
            pos_set = _parse_positions(row.get('Position'))
            is_hitter = (assigned in HITTER_POSITIONS) if assigned is not None else (
                bool(pos_set & HITTER_POSITIONS) and 'P' not in pos_set
            )
            if is_hitter and row.get('Team') != primary and row.get('Ownership_Tier') == 'High':
                high_owned_one_offs += 1

    return {
        'meta_lineup_overlap': meta_overlap,
        'ownership_sum_pct': ownership_total,
        'salary_band_penalty': _salary_band_duplication_penalty(salary_used),
        'primary_stack_size': primary_count,
        'high_owned_one_offs': high_owned_one_offs,
        'field_pressure_score': (
            0.70 * meta_overlap
            + 0.035 * ownership_total
            + 0.75 * _salary_band_duplication_penalty(salary_used)
            + 0.40 * high_owned_one_offs
            + (0.35 if primary_count >= 5 else 0.0)
        ),
    }


def score_lineup_candidate(
    lineup_df,
    projections_df=None,
    mode='wta',
    slate_metadata=None,
    meta_lineup_ids=None,
    du_signature=None,
    candidate_id=None,
    requested_n=1,
    contest_shape=None,
):
    """Score a legal lineup with four decision-relevant components.

    v3.16 deliberately keeps descriptive diagnostics in the return payload, but
    only ceiling/floor, stack correlation, duplication pressure, and joint-MILP
    diversity affect selection. Marginal diversity is applied by the allocator.
    """
    salary_used = float(lineup_df['Salary'].sum()) if 'Salary' in lineup_df.columns else 0.0
    ceiling = float(lineup_df['Ceiling'].sum()) if 'Ceiling' in lineup_df.columns else 0.0
    floor = float(lineup_df['Floor'].sum()) if 'Floor' in lineup_df.columns else 0.0
    signature = du_signature or compute_unit_signature(lineup_df, slate_metadata)
    field = compute_field_pressure_score(lineup_df, meta_lineup_ids=meta_lineup_ids)
    stack_bonus = _lineup_stack_correlation_bonus(lineup_df)
    batting_order_cluster = _lineup_batting_order_cluster_summary(lineup_df)
    profile = resolve_contest_shape_profile(mode=mode, requested_n=requested_n, contest_shape=contest_shape)

    stack_archetype = _lineup_stack_archetype(lineup_df)
    stack_adjacency_tag = _lineup_stack_adjacency_tag(lineup_df)
    role_elevation = _role_elevation_diagnostics(lineup_df)
    right_tail = _lineup_right_tail_volatility_summary(lineup_df)
    low_owned_hitters = _low_owned_hitter_count(lineup_df)
    suppression_count = _suppression_trigger_count(lineup_df)
    salary_uniqueness_bonus = 0.40 if salary_used <= 49200 else 0.0

    if profile['mode_family'] == 'cash':
        projection_component = profile['ceiling_weight'] * ceiling + profile['floor_weight'] * floor
    else:
        projection_component = ceiling
    correlation_component = (
        profile['stack_bonus_weight'] * stack_bonus
        + profile['batting_order_cluster_weight'] * batting_order_cluster['batting_order_cluster_bonus']
    )
    has_duplication_signal = bool(meta_lineup_ids) or field['ownership_sum_pct'] > 0
    duplication_component = profile['salary_uniqueness_weight'] * salary_uniqueness_bonus
    if has_duplication_signal:
        duplication_component -= profile['field_pressure_weight'] * field['field_pressure_score']
    marginal_portfolio_diversity_component = 0.0  # applied jointly, never guessed per lineup
    contest_fit = projection_component + correlation_component + duplication_component

    metric_name = 'WTA_First_Place_Proxy' if mode == 'wta' else 'Portfolio_EV_Proxy'
    return {
        'candidate_id': candidate_id,
        'salary_used': salary_used,
        'ceiling_sum': ceiling,
        'floor_sum': floor,
        'raw_objective_proxy': ceiling,
        'contest_shape_profile': profile['contest_shape'],
        'contest_shape_weights': profile,
        'primary_stack': signature.get('primary_stack'),
        'secondary_stack': signature.get('secondary_stack'),
        'game_environment': signature.get('game_environment'),
        'chalk_one_off': signature.get('chalk_one_off'),
        'sp_pair': signature.get('sp_pair'),
        'score_components': {
            'projection': projection_component,
            'stack_correlation': correlation_component,
            'duplication_adjustment': duplication_component,
            'marginal_portfolio_diversity': marginal_portfolio_diversity_component,
        },
        'stack_correlation_bonus': stack_bonus,
        'stack_archetype': stack_archetype,
        'stack_adjacency_tag': stack_adjacency_tag,
        **batting_order_cluster,
        **role_elevation,
        'right_tail_volatility_counts': right_tail['tier_counts'],
        'right_tail_bonus': right_tail['right_tail_bonus'],
        'low_owned_hitter_count': low_owned_hitters,
        'suppression_trigger_count': suppression_count,
        'salary_uniqueness_bonus': salary_uniqueness_bonus,
        'meta_lineup_overlap': field['meta_lineup_overlap'],
        'ownership_sum_pct': field['ownership_sum_pct'],
        'duplication_risk_proxy': field['field_pressure_score'] if has_duplication_signal else None,
        metric_name: contest_fit,
        'contest_fit_metric': metric_name,
        'contest_fit_score': contest_fit,
    }



def portfolio_redundancy_report(lineup_records, du_signatures=None):
    """Identify the highest-redundancy pair in a lineup set.

    Proxy score = shared player count + matching DU-axis count. This is a
    diagnostic only; it does not override DU validation or anchor validation.
    """
    if lineup_records is None or len(lineup_records) < 2:
        return {
            'highest_redundancy_pair': None,
            'highest_redundancy_score': 0,
            'summary': 'Portfolio redundancy: fewer than 2 lineups',
        }
    best = None
    best_score = None
    for i in range(len(lineup_records)):
        ids_i = set(_lineup_player_ids(lineup_records[i]['lineup']))
        for j in range(i + 1, len(lineup_records)):
            ids_j = set(_lineup_player_ids(lineup_records[j]['lineup']))
            shared = len(ids_i & ids_j)
            matched = []
            if du_signatures and i < len(du_signatures) and j < len(du_signatures):
                matched = matched_units(du_signatures[i], du_signatures[j], exclude_anchor=False)
            score = shared + len(matched)
            if best_score is None or score > best_score:
                best_score = score
                best = {
                    'lineup_i': i,
                    'lineup_j': j,
                    'lineup_i_id': lineup_records[i].get('lineup_id', i + 1),
                    'lineup_j_id': lineup_records[j].get('lineup_id', j + 1),
                    'shared_player_count': shared,
                    'matched_du_units': matched,
                    'redundancy_score': score,
                }
    return {
        'highest_redundancy_pair': best,
        'highest_redundancy_score': best_score or 0,
        'summary': (
            f"Portfolio redundancy: highest pair L{best['lineup_i_id']}-L{best['lineup_j_id']} "
            f"with {best['shared_player_count']} shared players and "
            f"{len(best['matched_du_units'])} matched DU units"
            if best is not None else 'Portfolio redundancy: unavailable'
        ),
    }


def _portfolio_exposure_summary(lineup_records, projections_df=None):
    player_counts = Counter()
    sp_counts = Counter()
    primary_stack_counts = Counter()
    secondary_stack_counts = Counter()
    stack_archetype_counts = Counter()
    salary_bands = Counter()
    right_tail_tier_counts = Counter()

    for record in lineup_records or []:
        lineup_df = record['lineup']
        for pid in _lineup_player_ids(lineup_df):
            player_counts[pid] += 1
        for sp_id in _get_ordered_sp_ids(lineup_df):
            sp_counts[sp_id] += 1
        primary = _identify_primary_stack(lineup_df)
        primary_stack_counts[primary] += 1
        secondary_stack_counts[_identify_secondary_stack(lineup_df, primary)] += 1
        stack_archetype_counts[_lineup_stack_archetype(lineup_df)] += 1
        rt = _lineup_right_tail_volatility_summary(lineup_df)
        for tier, count in rt['tier_counts'].items():
            right_tail_tier_counts[tier] += count
        salary = float(lineup_df['Salary'].sum()) if 'Salary' in lineup_df.columns else 0.0
        if salary >= 49800:
            band = '49800-50000'
        elif salary >= 49200:
            band = '49200-49799'
        elif salary >= 48500:
            band = '48500-49199'
        else:
            band = '<48500'
        salary_bands[band] += 1
    return {
        'player_counts': dict(player_counts),
        'sp_counts': dict(sp_counts),
        'primary_stack_counts': dict(primary_stack_counts),
        'secondary_stack_counts': dict(secondary_stack_counts),
        'stack_archetype_counts': dict(stack_archetype_counts),
        'salary_band_counts': dict(salary_bands),
        'right_tail_tier_counts': {tier: right_tail_tier_counts.get(tier, 0) for tier in RIGHT_TAIL_TIERS},
        'field_exposure_delta': field_exposure_delta_report(
            lineup_records, projections_df=projections_df
        ),
    }

def _mode_for_contest_shape(shape, fallback_mode='portfolio_ev'):
    shape = str(shape or '').lower()
    if shape in {'small_wta', 'mid_wta', 'large_wta', 'wta_ticket_satellite'}:
        return 'wta'
    if shape == 'cash':
        return 'cash'
    return fallback_mode if fallback_mode != 'wta' else 'portfolio_ev'


def build_candidate_lineup_bank(
    projections_df,
    requested_n,
    candidate_bank_size=None,
    mode='wta',
    target='ceiling',
    overlap_preset='typical',
    scenario_families=None,
    du_threshold_row=None,
    slate_metadata=None,
    max_sp_exposure=None,
    max_sp_pair_repetition=None,
    sp_pair_coverage_plan=None,
    meta_lineup_ids=None,
    contest_shape=None,
    contest_shapes=None,
    bank_constraint_scope='selection',
    time_budget_s=None,
    solver_time_limit_s=None,
    **single_lineup_kwargs
):
    """Generate and score a candidate bank through the certified MILP path.

    ``bank_constraint_scope='selection'`` is the v3.14 default. It keeps DK
    roster constraints and pairwise lineup overlap during candidate generation,
    but defers DU/anchor portfolio constraints to the final selection MILP.
    ``'bank'`` preserves the legacy behavior of enforcing those controls across
    every candidate in the oversized bank.
    """
    bank_size = resolve_candidate_bank_size(requested_n, candidate_bank_size)
    scope = str(bank_constraint_scope or 'selection').lower()
    if scope not in {'selection', 'bank'}:
        raise ValueError("bank_constraint_scope must be 'selection' or 'bank'")

    bank_du = None if scope == 'selection' else du_threshold_row
    bank_sp_cap = None if scope == 'selection' else max_sp_exposure
    bank_pair_cap = None if scope == 'selection' else max_sp_pair_repetition
    result = build_multi_lineup(
        projections_df,
        n_lineups=bank_size,
        mode=mode,
        target=target,
        overlap_preset=overlap_preset,
        scenario_families=scenario_families,
        du_threshold_row=bank_du,
        slate_metadata=slate_metadata,
        max_sp_exposure=bank_sp_cap,
        max_sp_pair_repetition=bank_pair_cap,
        sp_pair_coverage_plan=sp_pair_coverage_plan,
        enforce_wta_stack_core_uniqueness=(scope == 'bank'),
        time_budget_s=time_budget_s,
        solver_time_limit_s=solver_time_limit_s,
        **single_lineup_kwargs,
    )

    if meta_lineup_ids is None:
        try:
            meta_lineup_ids = run_meta_lineup(projections_df)
        except Exception:
            meta_lineup_ids = []

    requested_shapes = []
    for shape in list(contest_shapes or []) + ([contest_shape] if contest_shape else []):
        key = str(shape).strip().lower()
        if key and key not in requested_shapes:
            requested_shapes.append(key)
    if not requested_shapes:
        requested_shapes = [resolve_contest_shape_profile(
            mode=mode, requested_n=requested_n, contest_shape=contest_shape
        )['contest_shape']]
    primary_shape = str(contest_shape).strip().lower() if contest_shape else requested_shapes[0]

    scored = []
    for idx, record in enumerate(result['lineups']):
        sig = result['du_signatures'][idx] if idx < len(result.get('du_signatures', [])) else None
        if sig is None:
            sig = compute_unit_signature(record['lineup'], slate_metadata)
        base_score = score_lineup_candidate(
            record['lineup'], projections_df=projections_df, mode=_mode_for_contest_shape(primary_shape, mode),
            slate_metadata=slate_metadata, meta_lineup_ids=meta_lineup_ids,
            du_signature=sig, candidate_id=idx + 1, requested_n=requested_n,
            contest_shape=primary_shape,
        )
        fit_by_shape = {}
        for shape in requested_shapes:
            shape_score = score_lineup_candidate(
                record['lineup'], projections_df=projections_df,
                mode=_mode_for_contest_shape(shape, mode),
                slate_metadata=slate_metadata, meta_lineup_ids=meta_lineup_ids,
                du_signature=sig, candidate_id=idx + 1, requested_n=requested_n,
                contest_shape=shape,
            )
            fit_by_shape[shape] = shape_score['contest_fit_score']
        enriched = dict(record)
        enriched['candidate_id'] = idx + 1
        enriched['contest_fit'] = base_score
        enriched['contest_fit_by_shape'] = fit_by_shape
        enriched['player_ids'] = _lineup_player_ids(record['lineup'])
        enriched['sp_ids'] = _get_ordered_sp_ids(record['lineup'])
        # F15: the allocator's primary-stack exposure cap reads this field. It
        # was never emitted, so the cap added zero MILP rows and the stack
        # concentration it exists to prevent was only discovered at the export
        # gate, after the whole build had been spent.
        enriched['primary_stack'] = candidate_primary_stack(record['lineup'])
        enriched['du_signature'] = sig
        scored.append(enriched)

    result['requested_n'] = int(requested_n)
    result['candidate_bank_size_requested'] = bank_size
    result['candidate_lineups'] = scored
    result['du_signatures'] = [rec['du_signature'] for rec in scored]
    result['candidate_scores'] = [r['contest_fit'] for r in scored]
    result['contest_shapes_scored'] = requested_shapes
    result['contest_shape_profile'] = resolve_contest_shape_profile(
        mode=mode, requested_n=requested_n, contest_shape=primary_shape
    )
    result['portfolio_redundancy_report'] = portfolio_redundancy_report(
        result['lineups'], result.get('du_signatures', [])
    )
    result['exposure_summary'] = _portfolio_exposure_summary(
        result['lineups'], projections_df=projections_df
    )
    result['mode'] = mode
    result['overlap_preset'] = overlap_preset
    result['scenario_families'] = scenario_families
    result['selection_du_threshold_row'] = du_threshold_row
    result['selection_max_sp_exposure'] = max_sp_exposure
    result['selection_max_sp_pair_repetition'] = max_sp_pair_repetition
    result['bank_constraint_scope'] = scope
    result['bank_constraints_deferred_to_selection'] = scope == 'selection'
    return result


def _stackable_teams_by_strength(projections_df, min_hitters=4, top_k=5):
    """Deterministic list of hitter teams that can anchor a stack, strongest first.

    Strength is the sum of the team's top-``top_k`` hitter Ceiling values (falling
    back to hitter count when no Ceiling column is present). Teams with fewer than
    ``min_hitters`` rostered hitters cannot anchor a 4-5 man stack and are dropped.
    Ties break alphabetically on team so the order is stable across runs.
    """
    if not hasattr(projections_df, 'columns') or 'Team' not in projections_df.columns:
        return []
    df = projections_df
    df = _drop_excluded_rows(df)  # F21: one reading of the column, counted
    hitters = df[df['Position'].apply(lambda p: 'P' not in _parse_positions(p))]
    has_ceiling = 'Ceiling' in hitters.columns
    strengths = []
    for team, grp in hitters.groupby('Team'):
        if len(grp) < min_hitters:
            continue
        if has_ceiling:
            ceils = sorted(
                pd.to_numeric(grp['Ceiling'], errors='coerce').fillna(0.0).tolist(),
                reverse=True,
            )
            strength = float(sum(ceils[:top_k]))
        else:
            strength = float(len(grp))
        strengths.append((strength, str(team)))
    strengths.sort(key=lambda t: (-t[0], t[1]))
    return [team for _, team in strengths]


def build_diverse_candidate_bank(
    projections_df,
    requested_n,
    candidate_bank_size=None,
    mode='wta',
    target='ceiling',
    coverage_target=None,
    max_sp_pair_repetition=None,
    time_budget_s=None,
    solver_time_limit_s=None,
    **bank_kwargs
):
    """Coverage-guaranteed wrapper over build_candidate_lineup_bank (v3.18).

    build_candidate_lineup_bank spreads its bank with overlap-repulsion and stack-
    core uniqueness. On thin slates that heuristic saturates: the generator halts
    once it cannot place a lineup distinct enough from the priors, so the bank can
    collapse well below requested_n and cluster on a couple of SP pairs. An allocator
    then cannot cover the entry field no matter how the exposure caps are set,
    because the missing diversity was never generated.

    This wrapper builds the base bank, then deterministically forces additional legal
    lineups across every viable SP pair (breadth first) and rotating team stacks
    (depth), deduped by exact player set, until the bank both covers the viable SP
    pairs and reaches the target size. It changes no projection and no MILP hard
    constraint; it only guarantees the candidate pool the selection MILP draws from is
    diverse enough to be feasible. Deterministic review input, never a win-rate, ROI,
    or probability claim.
    """
    _budget_started = _time.monotonic()
    _budget_s = None if time_budget_s is None else float(time_budget_s)

    def _budget_left():
        if _budget_s is None:
            return None
        return _budget_s - (_time.monotonic() - _budget_started)

    bank = build_candidate_lineup_bank(
        projections_df, requested_n=requested_n,
        candidate_bank_size=candidate_bank_size, mode=mode, target=target,
        max_sp_pair_repetition=max_sp_pair_repetition,
        time_budget_s=_budget_s, solver_time_limit_s=solver_time_limit_s,
        **bank_kwargs,
    )

    slate_metadata = bank_kwargs.get('slate_metadata')
    passthrough_keys = {
        'excludes', 'locks', 'penalized_players', 'apply_suppression',
        'solver_backend', 'skip_feasibility_check', 'bringback_constraint',
    }
    single_lineup_kwargs = {k: v for k, v in bank_kwargs.items() if k in passthrough_keys}

    eligible_sps = _eligible_sp_ids_for_anchor_caps(
        projections_df, excludes=single_lineup_kwargs.get('excludes')
    )
    # Cross-game only and ceiling-ranked: Phase 1 below stops on budget
    # exhaustion, so this order decides which pairings a truncated bank covers.
    viable_pairs = enumerate_sp_pairs(eligible_sps, projections_df)
    stack_teams = _stackable_teams_by_strength(projections_df)

    base_count = len(bank.get('candidate_lineups') or [])
    target_size = int(coverage_target or bank.get('candidate_bank_size_requested') or requested_n)
    n_pairs = len(viable_pairs)

    augmentation = {
        'attempted': False,
        'appended': 0,
        'base_candidate_count': base_count,
        'final_candidate_count': base_count,
        'viable_sp_pair_count': n_pairs,
        'stackable_team_count': len(stack_teams),
        'target_size': target_size,
        'distinct_sp_pairs': None,
        'time_budget_s': _budget_s,
        'budget_exhausted': False,
        'base_bank_budget': (bank.get('budget') or {}),
        'note': '',
    }

    if n_pairs < 1 or not stack_teams:
        augmentation['note'] = 'no augmentation: insufficient viable SP pairs or stackable teams'
        bank['diversity_augmentation'] = augmentation
        return bank

    augmentation['attempted'] = True

    existing = list(bank.get('lineups') or [])
    existing_sigs = list(bank.get('du_signatures') or [])
    scored = list(bank.get('candidate_lineups') or [])
    seen = set()
    pair_counts = Counter()
    for rec in existing:
        ldf = rec.get('lineup')
        if ldf is None:
            continue
        seen.add(frozenset(_lineup_player_ids(ldf)))
        pr = _sp_pair_from_lineup(ldf)
        if pr is not None:
            pair_counts[tuple(sorted(pr, key=str))] += 1

    requested_shapes = list(bank.get('contest_shapes_scored') or [])
    if not requested_shapes:
        requested_shapes = [resolve_contest_shape_profile(
            mode=mode, requested_n=requested_n
        )['contest_shape']]
    primary_shape = requested_shapes[0]
    try:
        meta_lineup_ids = run_meta_lineup(projections_df)
    except Exception:
        meta_lineup_ids = []

    next_candidate_id = 1 + max([int(r.get('candidate_id') or 0) for r in scored] + [0])
    team_of_cache = {}

    def _teams_of_pair(pair):
        key = tuple(pair)
        if key in team_of_cache:
            return team_of_cache[key]
        teams = set()
        for pid in pair:
            row = projections_df[projections_df['Player_ID'] == pid]
            if len(row):
                teams.add(str(row.iloc[0].get('Team')))
        team_of_cache[key] = teams
        return teams

    attempts = {'n': 0}
    max_attempts = target_size * 4 + 60
    # Worst observed single augmentation solve, used as the reserve so the loop
    # stops before starting a solve it cannot finish rather than being killed.
    # F13: only completed solves feed it. A timed-out solve costs exactly the
    # time limit, so folding it in set the reserve to the limit and every later
    # round then read as unaffordable: one slow solve ended the whole pass. The
    # per-solve limit is instead shrunk to what is left, which reduces search
    # effort and never touches the legal player set.
    aug_cost = {'max': 0.0}
    aug_timeouts = {'n': 0, 'accepted_time_limited': 0}

    def _budget_exhausted():
        left = _budget_left()
        if left is None:
            return False
        return left <= max(aug_cost['max'], MIN_SOLVER_TIME_LIMIT_S)

    def _try_accept(pair, team):
        nonlocal next_candidate_id
        attempts['n'] += 1
        kwargs = dict(single_lineup_kwargs)
        kwargs['locks'] = stable_union(kwargs.get('locks'), pair)  # F19
        kwargs['stack_constraints'] = {'team': team, 'min_size': 4, 'max_size': 5}
        kwargs['time_limit_s'] = resolve_solver_time_limit(
            solver_time_limit_s, _budget_left()
        )
        status = _new_solver_status()
        kwargs['status_out'] = status
        _attempt_started = _time.monotonic()
        try:
            ldf, obj = build_single_lineup(projections_df, target=target, **kwargs)
        except Exception:
            aug_cost['max'] = max(aug_cost['max'], _time.monotonic() - _attempt_started)
            return False
        if status.get('timed_out'):
            aug_timeouts['n'] += 1
        else:
            aug_cost['max'] = max(aug_cost['max'], _time.monotonic() - _attempt_started)
        if ldf is None:
            return False
        if status.get('optimality') == 'time_limited':
            aug_timeouts['accepted_time_limited'] += 1
        ids = frozenset(_lineup_player_ids(ldf))
        if ids in seen:
            return False
        seen.add(ids)
        sig = compute_unit_signature(ldf, slate_metadata)
        record = {
            'lineup': ldf, 'objective': obj, 'lineup_id': len(existing) + 1,
            'source': 'diversity_augmentation',
        }
        base_score = score_lineup_candidate(
            ldf, projections_df=projections_df,
            mode=_mode_for_contest_shape(primary_shape, mode),
            slate_metadata=slate_metadata, meta_lineup_ids=meta_lineup_ids,
            du_signature=sig, candidate_id=next_candidate_id, requested_n=requested_n,
            contest_shape=primary_shape,
        )
        fit_by_shape = {}
        for shape in requested_shapes:
            shape_score = score_lineup_candidate(
                ldf, projections_df=projections_df,
                mode=_mode_for_contest_shape(shape, mode),
                slate_metadata=slate_metadata, meta_lineup_ids=meta_lineup_ids,
                du_signature=sig, candidate_id=next_candidate_id, requested_n=requested_n,
                contest_shape=shape,
            )
            fit_by_shape[shape] = shape_score['contest_fit_score']
        enriched = dict(record)
        enriched['candidate_id'] = next_candidate_id
        enriched['contest_fit'] = base_score
        enriched['contest_fit_by_shape'] = fit_by_shape
        enriched['player_ids'] = _lineup_player_ids(ldf)
        enriched['sp_ids'] = _get_ordered_sp_ids(ldf)
        enriched['primary_stack'] = candidate_primary_stack(ldf)  # F15
        enriched['du_signature'] = sig
        existing.append(record)
        existing_sigs.append(sig)
        scored.append(enriched)
        pr = _sp_pair_from_lineup(ldf)
        if pr is not None:
            pair_counts[tuple(sorted(pr, key=str))] += 1
        next_candidate_id += 1
        return True

    # Phase 1 (breadth): ensure every viable SP pair has at least one lineup.
    for p_idx, pair in enumerate(viable_pairs):
        if attempts['n'] >= max_attempts or _budget_exhausted():
            break
        if pair_counts.get(tuple(sorted(pair, key=str)), 0) >= 1:
            continue
        excluded_teams = _teams_of_pair(pair)
        for offset in range(len(stack_teams)):
            team = stack_teams[(p_idx + offset) % len(stack_teams)]
            if team in excluded_teams:
                continue
            if _try_accept(pair, team):
                break
            if attempts['n'] >= max_attempts:
                break

    # Phase 2 (depth): cycle (pair, rotating stack) until target size or exhausted.
    round_idx = 1
    max_rounds = len(stack_teams) + 2
    while (len(existing) < target_size and round_idx <= max_rounds
           and attempts['n'] < max_attempts and not _budget_exhausted()):
        progress = False
        for p_idx, pair in enumerate(viable_pairs):
            if len(existing) >= target_size or attempts['n'] >= max_attempts:
                break
            excluded_teams = _teams_of_pair(pair)
            team = stack_teams[(p_idx + round_idx) % len(stack_teams)]
            if team in excluded_teams:
                team = next((t for t in stack_teams if t not in excluded_teams), None)
                if team is None:
                    continue
            if _try_accept(pair, team):
                progress = True
        round_idx += 1
        if not progress:
            break

    bank['lineups'] = existing
    bank['du_signatures'] = existing_sigs
    bank['candidate_lineups'] = scored
    bank['candidate_scores'] = [r['contest_fit'] for r in scored]
    try:
        bank['portfolio_redundancy_report'] = portfolio_redundancy_report(existing, existing_sigs)
    except Exception:
        pass
    try:
        bank['exposure_summary'] = _portfolio_exposure_summary(existing, projections_df=projections_df)
    except Exception:
        pass

    augmentation['appended'] = len(scored) - base_count
    augmentation['budget_exhausted'] = bool(_budget_exhausted())
    augmentation['elapsed_s'] = round(_time.monotonic() - _budget_started, 3)
    augmentation['final_candidate_count'] = len(scored)
    augmentation['distinct_sp_pairs'] = len([k for k, v in pair_counts.items() if v > 0])
    augmentation['attempts'] = attempts['n']
    augmentation['solver_timeouts'] = aug_timeouts['n']
    augmentation['time_limited_accepted'] = aug_timeouts['accepted_time_limited']
    augmentation['base_bank_solver_report'] = bank.get('solver_report')
    # Built from observed state. The note used to assert "forced coverage across
    # N pairs" unconditionally, including when budget exhaustion no-opped both
    # phases and the pass appended nothing at all, so the run record claimed work
    # that never happened.
    if augmentation['appended'] <= 0:
        reason = ("the compute budget was exhausted before it ran"
                  if augmentation['budget_exhausted']
                  else "no candidate it produced improved coverage")
        augmentation['note'] = (
            f"coverage augmentation appended nothing: {reason}. The bank covers "
            f"{augmentation['distinct_sp_pairs']} of {n_pairs} viable SP pairs; "
            f"coverage across the remaining pairs was NOT forced."
        )
    else:
        augmentation['note'] = (
            f"appended {augmentation['appended']} candidates over "
            f"{attempts['n']} attempts, forcing coverage toward {n_pairs} viable "
            f"SP pairs and {len(stack_teams)} stackable teams; the bank now "
            f"covers {augmentation['distinct_sp_pairs']} pairs"
            + (". The compute budget was exhausted before the pass completed."
               if augmentation['budget_exhausted'] else ".")
        )
    bank['diversity_augmentation'] = augmentation
    return bank


def _candidate_selection_score(record, contest_shape=None):
    if contest_shape:
        by_shape = record.get('contest_fit_by_shape') or {}
        if contest_shape in by_shape:
            return float(by_shape[contest_shape])
    return float(record.get('contest_fit', {}).get(
        'contest_fit_score', record.get('objective', float('-inf'))
    ))


def _candidate_explicit_right_tail(record):
    counts = record.get('contest_fit', {}).get('right_tail_volatility_counts') or {}
    return counts.get('Eruption', 0) > 0 or counts.get('Volatile', 0) > 0


def _selection_pairwise_incompatible(rec_a, rec_b, sig_a, sig_b, max_overlap, within_min):
    ids_a = set(_lineup_player_ids(rec_a['lineup']))
    ids_b = set(_lineup_player_ids(rec_b['lineup']))
    if max_overlap is not None and len(ids_a & ids_b) > max_overlap:
        return True
    if within_min is not None and within_min > 0 and sig_a is not None and sig_b is not None:
        if du_distance(sig_a, sig_b, exclude_anchor=True) < within_min:
            return True
    return False


def _solve_candidate_subset_milp(
    candidates,
    signatures,
    requested,
    contest_shape,
    max_overlap,
    within_min,
    max_sp_cap,
    max_pair_cap,
    coverage_plan,
    right_tail_target,
    redundancy_penalty_weight,
):
    """Solve one final-subset MILP attempt and return selected indices/status."""
    if not SCIPY_AVAILABLE:
        raise RuntimeError(f'scipy MILP backend unavailable: {SCIPY_IMPORT_ERROR}')
    import numpy as np
    from scipy.optimize import Bounds, LinearConstraint, milp
    from scipy.sparse import coo_matrix

    n = len(candidates)
    if requested > n:
        return None, 'insufficient_candidates'

    sp_pairs = [_sp_pair_from_lineup(rec['lineup']) for rec in candidates]
    observed_pairs = sorted({tuple(pair) for pair in sp_pairs if pair is not None}, key=str)
    pair_to_candidates = {
        pair: [i for i, candidate_pair in enumerate(sp_pairs) if candidate_pair is not None and frozenset(candidate_pair) == frozenset(pair)]
        for pair in observed_pairs
    }

    # Pairwise soft redundancy variables. Hard-incompatible pairs are excluded
    # through x_i + x_j <= 1 and do not receive a soft variable.
    soft_pairs = []
    hard_pairs = []
    for i in range(n):
        ids_i = set(_lineup_player_ids(candidates[i]['lineup']))
        for j in range(i + 1, n):
            if _selection_pairwise_incompatible(
                candidates[i], candidates[j], signatures[i], signatures[j], max_overlap, within_min
            ):
                hard_pairs.append((i, j))
                continue
            shared = len(ids_i & set(_lineup_player_ids(candidates[j]['lineup'])))
            matched = 0
            if signatures[i] is not None and signatures[j] is not None:
                matched = len(matched_units(signatures[i], signatures[j], exclude_anchor=False))
            redundancy = shared + 0.5 * matched
            if redundancy > 0:
                soft_pairs.append((i, j, redundancy))

    x_offset = 0
    y_offset = n
    a_offset = y_offset + len(soft_pairs)
    n_vars = n + len(soft_pairs) + len(observed_pairs)
    c = np.zeros(n_vars, dtype=float)
    for i, rec in enumerate(candidates):
        c[x_offset + i] = -_candidate_selection_score(rec, contest_shape)
    for k, (_, _, redundancy) in enumerate(soft_pairs):
        c[y_offset + k] = float(redundancy_penalty_weight) * float(redundancy)

    priority_scores = coverage_plan.get('sp_pair_priority_scores', {}) if coverage_plan else {}
    for p_idx, pair in enumerate(observed_pairs):
        priority = priority_scores.get(tuple(pair), priority_scores.get(tuple(sorted(pair, key=str)), 0.0))
        c[a_offset + p_idx] = -0.25 * float(priority or 0.0)

    rows, lbs, ubs = [], [], []
    def add(coefs, lb, ub):
        rows.append(dict(coefs)); lbs.append(lb); ubs.append(ub)

    add({i: 1.0 for i in range(n)}, requested, requested)

    # Duplicate player signatures cannot both enter the selected portfolio.
    signature_groups = {}
    for i, rec in enumerate(candidates):
        key = tuple(sorted(map(str, _lineup_player_ids(rec['lineup']))))
        signature_groups.setdefault(key, []).append(i)
    for idxs in signature_groups.values():
        if len(idxs) > 1:
            add({i: 1.0 for i in idxs}, -np.inf, 1.0)

    for i, j in hard_pairs:
        add({i: 1.0, j: 1.0}, -np.inf, 1.0)

    # Anchor exposure constraints apply to the selected subset.
    sp_to_candidates = {}
    for i, rec in enumerate(candidates):
        for sp_id in _get_ordered_sp_ids(rec['lineup']):
            sp_to_candidates.setdefault(sp_id, []).append(i)
    if max_sp_cap is not None:
        for idxs in sp_to_candidates.values():
            add({i: 1.0 for i in idxs}, -np.inf, max_sp_cap)
    if max_pair_cap is not None:
        for idxs in pair_to_candidates.values():
            add({i: 1.0 for i in idxs}, -np.inf, max_pair_cap)

    # SP-pair activation variables support hard exact coverage and weighted
    # soft unique-pair breadth without treating every pair as equally valuable.
    for p_idx, pair in enumerate(observed_pairs):
        a = a_offset + p_idx
        idxs = pair_to_candidates[pair]
        coefs = {a: 1.0}
        for i in idxs:
            coefs[i] = coefs.get(i, 0.0) - 1.0
        add(coefs, -np.inf, 0.0)  # a_pair <= selected lineups using pair

    if coverage_plan:
        required_pairs = [tuple(sorted(pair, key=str)) for pair in coverage_plan.get('required_sp_pairs') or []]
        for pair in required_pairs:
            idxs = [i for i, cp in enumerate(sp_pairs) if cp is not None and frozenset(cp) == frozenset(pair)]
            if not idxs:
                return None, f'missing_required_pair:{pair}'
            add({i: 1.0 for i in idxs}, 1.0, np.inf)
        target_unique = int(coverage_plan.get('target_unique_pairs') or 0)
        target_unique = min(target_unique, requested, len(observed_pairs))
        if target_unique > 0 and observed_pairs:
            add({a_offset + p_idx: 1.0 for p_idx in range(len(observed_pairs))}, target_unique, np.inf)

    if right_tail_target > 0:
        tail_idxs = [i for i, rec in enumerate(candidates) if _candidate_explicit_right_tail(rec)]
        if len(tail_idxs) < right_tail_target:
            return None, 'insufficient_explicit_right_tail_candidates'
        add({i: 1.0 for i in tail_idxs}, right_tail_target, np.inf)

    # Linearize y_ij = x_i AND x_j for redundancy penalties.
    for k, (i, j, _) in enumerate(soft_pairs):
        y = y_offset + k
        add({y: 1.0, i: -1.0}, -np.inf, 0.0)
        add({y: 1.0, j: -1.0}, -np.inf, 0.0)
        add({y: 1.0, i: -1.0, j: -1.0}, -1.0, np.inf)

    row_idx, col_idx, data = [], [], []
    for r, coefs in enumerate(rows):
        for col, val in coefs.items():
            if val:
                row_idx.append(r); col_idx.append(col); data.append(float(val))
    A = coo_matrix((data, (row_idx, col_idx)), shape=(len(rows), n_vars)).tocsr()
    result = milp(
        c=c,
        integrality=np.ones(n_vars, dtype=int),
        bounds=Bounds(np.zeros(n_vars), np.ones(n_vars)),
        constraints=LinearConstraint(A, np.array(lbs, dtype=float), np.array(ubs, dtype=float)),
        options={'time_limit': 30, 'disp': False},
    )
    status = str(getattr(result, 'message', getattr(result, 'status', None)))
    if not result.success or result.x is None:
        return None, status
    selected = [i for i in range(n) if result.x[i] > 0.5]
    if len(selected) != requested:
        return None, f'solver_selected_{len(selected)}_of_{requested}'
    return selected, status


def select_final_portfolio_from_candidate_bank(
    candidate_bank_result,
    requested_n=None,
    preserve_sp_pair_coverage=True,
    selection_contest_shape=None,
    mode=None,
    overlap_preset=None,
    du_threshold_row=None,
    max_sp_exposure=None,
    max_sp_pair_repetition=None,
    right_tail_min_pct=0.0,
    redundancy_penalty_weight=0.12,
):
    """Select the final portfolio with a second-stage scipy MILP.

    The selected subset—not the oversized candidate bank—is certified against
    overlap, DU, anchor exposure, SP-pair breadth, explicit right-tail quota,
    and same-lineup duplication controls. Threshold-only DU and overlap
    relaxation follows the existing optimizer policy when the strict model is
    infeasible.
    """
    requested = int(requested_n or candidate_bank_result.get('requested_n') or 1)
    candidates = list(candidate_bank_result.get('candidate_lineups') or [])
    selection_shape = str(selection_contest_shape or '').strip().lower() or None
    mode = mode or candidate_bank_result.get('mode') or 'portfolio_ev'
    overlap_preset = overlap_preset or candidate_bank_result.get('overlap_preset') or 'typical'
    coverage_plan = candidate_bank_result.get('sp_pair_coverage_plan') if preserve_sp_pair_coverage else None

    signatures = []
    bank_sigs = candidate_bank_result.get('du_signatures') or []
    for idx, rec in enumerate(candidates):
        signatures.append(
            bank_sigs[idx] if idx < len(bank_sigs) and bank_sigs[idx] is not None
            else compute_unit_signature(rec['lineup'], None)
        )

    eligible_sp_count = len({sp for rec in candidates for sp in _get_ordered_sp_ids(rec['lineup'])})
    sp_setting = max_sp_exposure if max_sp_exposure is not None else candidate_bank_result.get('selection_max_sp_exposure')
    pair_setting = max_sp_pair_repetition if max_sp_pair_repetition is not None else candidate_bank_result.get('selection_max_sp_pair_repetition')
    active_sp_cap = _resolve_anchor_cap(sp_setting, 'sp', requested, eligible_sp_count)
    active_pair_cap = _resolve_anchor_cap(pair_setting, 'pair', requested, eligible_sp_count)

    resolved_du = _resolve_du_threshold_row(
        requested, mode,
        candidate_bank_result.get('selection_du_threshold_row', _DU_AUTO) if du_threshold_row == _DU_AUTO else du_threshold_row,
    )
    base_within = resolved_du[0] if resolved_du else None
    base_overlap = max(2, int(ROSTER_SIZE * {'conservative': 0.60, 'typical': 0.45, 'aggressive': 0.30}[overlap_preset]))

    tournament_shape = selection_shape in {
        'small_wta', 'mid_wta', 'large_wta', 'wta_ticket_satellite',
        'small_field_gpp', 'mid_field_gpp', 'large_field_gpp',
        'single_entry_gpp', 'portfolio_gpp', 'mme_gpp',
    } or (selection_shape is None and str(mode).lower() in {'wta', 'portfolio_ev', 'gpp'})
    if right_tail_min_pct == 'auto':
        tail_pct = 0.20 if tournament_shape and 8 <= requested <= 12 else 0.0
    else:
        tail_pct = max(0.0, float(right_tail_min_pct or 0.0))
    right_tail_target = int(ceil(requested * tail_pct)) if tail_pct > 0 else 0

    selected_indices = None
    solver_status = None
    applied_relaxation = None
    used_within = base_within
    used_overlap = base_overlap
    relaxation_steps = [-1] + list(range(len(DU_RELAXATION_ORDER)))
    for relaxation_idx in relaxation_steps:
        within, _ = _compute_relaxed_thresholds(base_within, None, relaxation_idx)
        for overlap in range(base_overlap, MAX_OVERLAP_CEILING + 1):
            selected_indices, solver_status = _solve_candidate_subset_milp(
                candidates, signatures, requested, selection_shape, overlap, within,
                active_sp_cap, active_pair_cap, coverage_plan, right_tail_target,
                redundancy_penalty_weight,
            )
            if selected_indices is not None:
                used_within = within
                used_overlap = overlap
                du_note = _relaxation_summary(base_within, None, relaxation_idx)
                overlap_note = f'max_overlap {base_overlap}->{overlap}' if overlap > base_overlap else None
                applied_relaxation = '; '.join(x for x in (du_note, overlap_note) if x) or None
                break
        if selected_indices is not None:
            break

    if selected_indices is None:
        return {
            'lineups': [],
            'selected_candidate_ids': [],
            'requested_n': requested,
            'candidate_count': len(candidates),
            'selection_method': 'scipy_milp',
            'selection_certified': False,
            'selection_solver_status': solver_status,
            'selection_failure_reason': solver_status or 'infeasible_final_selection',
            'sp_pair_coverage_plan': coverage_plan,
        }

    selected = [candidates[i] for i in selected_indices]
    final_signatures = [signatures[i] for i in selected_indices]
    du_validation = validate_du_portfolio(final_signatures, mode, (used_within, None))
    du_validation['relaxation_applied'] = applied_relaxation
    sp_usage = Counter()
    pair_usage = Counter()
    for rec in selected:
        sps = _get_ordered_sp_ids(rec['lineup'])
        sp_usage.update(sps)
        if len(sps) == 2:
            pair_usage[frozenset(sps)] += 1
    anchor_validation = _anchor_validation_dict(
        sp_usage, pair_usage, active_sp_cap, active_pair_cap
    )
    pair_validation = validate_sp_pair_coverage(selected, coverage_plan)

    max_observed_overlap = 0
    for i in range(len(selected)):
        ids_i = set(_lineup_player_ids(selected[i]['lineup']))
        for j in range(i + 1, len(selected)):
            max_observed_overlap = max(
                max_observed_overlap,
                len(ids_i & set(_lineup_player_ids(selected[j]['lineup'])))
            )
    overlap_validation = {
        'pass': max_observed_overlap <= used_overlap,
        'max_overlap_allowed': used_overlap,
        'max_overlap_observed': max_observed_overlap,
    }
    certified = bool(
        len(selected) == requested
        and du_validation.get('pass')
        and anchor_validation.get('pass')
        and pair_validation.get('pass')
        and overlap_validation.get('pass')
    )
    return {
        'lineups': selected,
        'selected_candidate_ids': [rec['candidate_id'] for rec in selected],
        'requested_n': requested,
        'candidate_count': len(candidates),
        'du_signatures': final_signatures,
        'du_validation': du_validation,
        'anchor_validation': anchor_validation,
        'overlap_validation': overlap_validation,
        'portfolio_redundancy_report': portfolio_redundancy_report(selected, final_signatures),
        'exposure_summary': _portfolio_exposure_summary(selected),
        'contest_shape_profile': candidate_bank_result.get('contest_shape_profile'),
        'sp_pair_coverage_plan': coverage_plan,
        'sp_pair_coverage_validation': pair_validation,
        'selection_method': 'scipy_milp',
        'selection_certified': certified,
        'selection_solver_status': solver_status,
        'selection_contest_shape': selection_shape,
        'selection_relaxation_applied': applied_relaxation,
        'right_tail_target': right_tail_target,
        'right_tail_selected': sum(1 for rec in selected if _candidate_explicit_right_tail(rec)),
        'bank_constraint_scope': candidate_bank_result.get('bank_constraint_scope'),
    }


def _select_family_for_lineup(lineup_index, scenario_families):
    cumulative = 0
    for family in scenario_families:
        cumulative += family['count']
        if lineup_index < cumulative:
            return family
    return scenario_families[-1]


def run_meta_lineup(projections_df):
    """Optional structural consensus build used only for duplication review.

    Base_Projection_MetaLineup is no longer a required schema field. When it is
    absent, fall back to Base_Projection and then Ceiling.
    """
    source_col = next((c for c in ('Base_Projection_MetaLineup', 'Base_Projection', 'Ceiling') if c in projections_df.columns), None)
    if source_col is None:
        return []

    meta_df = projections_df.copy()
    meta_df['Floor'] = meta_df[source_col]
    meta_df['Ceiling'] = meta_df[source_col]
    lineup, obj = build_single_lineup(
        meta_df, target='ceiling', apply_suppression=False
    )
    return lineup['Player_ID'].tolist() if lineup is not None else []


def apply_meta_lineup_penalties(projections_df, meta_lineup_ids, divergence_target):
    penalty_magnitude = 3.0 * divergence_target
    return {pid: penalty_magnitude for pid in meta_lineup_ids}


# ============================================================================
# v3.17 bank coverage diagnostic
# ============================================================================

def bank_coverage_report(projections_df, candidates, locks=None, excludes=None):
    """Report how far the candidate bank's best raw ceiling sits below the slate optimum.

    The two-stage design (bank, then joint assignment) fails silently when the
    bank lacks strong candidates: the joint MILP returns a feasible, certified,
    mediocre portfolio. This diagnostic runs ONE unconstrained ceiling solve and
    compares it against the best candidate ceiling sum, making bank starvation a
    visible number. It is a review diagnostic only; it never alters constraints,
    certification, or projections, and a failure here never blocks a run.
    """
    report = {
        'passed': None,
        'optimal_ceiling_sum': None,
        'best_candidate_ceiling_sum': None,
        'best_candidate_id': None,
        'gap_points': None,
        'gap_pct': None,
        'candidate_count': len(list(candidates or [])),
        'note': 'gap_points = unconstrained slate ceiling optimum minus best bank candidate ceiling sum',
    }
    candidates = list(candidates or [])
    if projections_df is None or not len(candidates):
        report['note'] = 'insufficient inputs for bank coverage diagnostic'
        return report
    try:
        ceiling_by_pid = {
            str(row['Player_ID']): float(row['Ceiling'])
            for _, row in projections_df.iterrows()
        }
        best_sum, best_id = None, None
        for idx, candidate in enumerate(candidates):
            ids = candidate.get('player_ids') or candidate.get('lineup_ids') or []
            ids = [str(x) for x in ids]
            if len(ids) != 10 or any(pid not in ceiling_by_pid for pid in ids):
                continue
            total = sum(ceiling_by_pid[pid] for pid in ids)
            if best_sum is None or total > best_sum:
                best_sum = total
                best_id = str(candidate.get('candidate_id') or candidate.get('lineup_id') or f'L{idx + 1:03d}')
        lineup_df, _objective = build_single_lineup(
            projections_df, target='ceiling', locks=list(locks or []),
            excludes=list(excludes or []), apply_suppression=False,
        )
        if lineup_df is None or best_sum is None:
            report['note'] = 'coverage solve or candidate scan unavailable; diagnostic skipped'
            return report
        optimal = float(lineup_df['Ceiling'].astype(float).sum())
        gap = optimal - best_sum
        report.update({
            'passed': True,
            'optimal_ceiling_sum': round(optimal, 4),
            'best_candidate_ceiling_sum': round(best_sum, 4),
            'best_candidate_id': best_id,
            'gap_points': round(gap, 4),
            'gap_pct': round(100.0 * gap / optimal, 4) if optimal else None,
        })
    except Exception as exc:  # diagnostic only; never block the pipeline
        report['note'] = f'bank coverage diagnostic failed: {exc}'
    return report
