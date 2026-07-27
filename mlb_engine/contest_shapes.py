"""contest_shapes.py -- one canonical contest-shape vocabulary.

R1a. The shape name is the only thing that tells the engine what a lineup is
being ranked FOR. It was spelled in four places that did not agree.

``optimizer_v3.CONTEST_SHAPE_PROFILE_WEIGHTS`` owned twelve profile keys.
``contest_allocator.contest_shape_for_card`` produced ten of them.
``execution_pipeline._posture_to_shape`` produced six, one of which
(``mme_top_heavy``) was not a profile key at all and raised on the direct path.
And the satellite-family names never reached any of them: ``normalize_posture``
folded ``inferred_type='satellite'`` and ``payout_shape_default='ticket_line'``
into the ``wta_satellite`` posture, which mapped to ``large_wta``, so the
``satellite`` profile (mode family ``ticket_line``, 0.58/0.42 ceiling/floor)
could not be reached from a production build and the floor-aware allocation
branch that already existed for it was dead code.

This module is the vocabulary. It holds no weights and imports nothing from the
engine, so every layer can validate against it without a cycle:

- ``CONTEST_SHAPES`` is the closed set. ``optimizer_v3`` asserts its profile
  table covers it exactly at import.
- ``OBJECTIVE_CLASS_BY_SHAPE`` says what each shape is ranked for. It is the
  contract the profile table's ``mode_family`` is checked against at import, and
  it is what R1c's ``objective_class`` CSV column will be validated against.
- ``WTA_CONSTRUCTION_SHAPES`` is a separate axis on purpose. Which MILP
  construction mode a shape builds in is not the same question as what its
  candidates are ranked for, and R1 changes only the second. Satellites are
  listed here because they build in ``wta`` mode today, and moving them would
  silently move the DU threshold row (``optimizer_v3._resolve_du_threshold_row``
  keys on mode). Construction and caps are R5's decision, not this module's.

Nothing here is a probability or an ROI claim. A shape is a label for an
objective; the scores it selects are deterministic review proxies.
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

VERSION = "v1.0"

# The closed set of contest shapes. Order is stable for deterministic messages.
CONTEST_SHAPES: Tuple[str, ...] = (
    "cash",
    "single_entry_gpp",
    "small_field_gpp",
    "mid_field_gpp",
    "large_field_gpp",
    "portfolio_gpp",
    "mme_gpp",
    "small_wta",
    "mid_wta",
    "large_wta",
    "wta_ticket_satellite",
    "satellite",
)

CONTEST_SHAPE_SET = frozenset(CONTEST_SHAPES)

# What each shape is ranked for. Mirrors the ``mode_family`` on each profile in
# ``optimizer_v3.CONTEST_SHAPE_PROFILE_WEIGHTS``; that agreement is asserted at
# import there, so the two can never drift apart silently again.
OBJECTIVE_CLASS_BY_SHAPE: Dict[str, str] = {
    "cash": "cash",
    "single_entry_gpp": "gpp",
    "small_field_gpp": "gpp",
    "mid_field_gpp": "gpp",
    "large_field_gpp": "gpp",
    "portfolio_gpp": "gpp",
    "mme_gpp": "gpp",
    "small_wta": "wta",
    "mid_wta": "wta",
    "large_wta": "wta",
    "wta_ticket_satellite": "wta",
    # A multi-ticket satellite pays for clearing a cut line, not for finishing
    # first. That is its own objective and it is the one most of the portfolio
    # is actually entered into.
    "satellite": "ticket_line",
}

OBJECTIVE_CLASSES: Tuple[str, ...] = ("cash", "gpp", "wta", "ticket_line")

# Shapes whose bank is CONSTRUCTED in MILP mode 'wta'. Deliberately broader than
# the ``wta`` objective class: a satellite is ranked on a ticket-line blend but
# still built from the WTA construction row, which is what it did before R1a.
# Widening or narrowing this set moves DU thresholds and is a strategy change.
WTA_CONSTRUCTION_SHAPES = frozenset({
    "small_wta", "mid_wta", "large_wta", "wta_ticket_satellite",
    "satellite", "single_entry_gpp",
})

# Satellite-family tokens as they appear in ``inferred_type`` and
# ``payout_shape_default`` on the curated archetype CSV and DEFAULT_ARCHETYPES.
SATELLITE_TYPE_TOKENS = frozenset({"satellite"})
SATELLITE_PAYOUT_TOKENS = frozenset({"ticket_line", "ticket_satellite"})


def is_contest_shape(shape: object) -> bool:
    return str(shape or "").strip().lower() in CONTEST_SHAPE_SET


def validate_shape(shape: object, where: str = "contest_shape") -> str:
    """Return the normalized shape or raise naming the caller.

    Used at import by every producer of a shape, so a new mapping entry that
    invents a name fails on load rather than on the one contest that uses it.
    """
    key = str(shape or "").strip().lower()
    if key not in CONTEST_SHAPE_SET:
        raise ValueError(
            f"{where}: '{shape}' is not a canonical contest shape; "
            f"valid shapes are {', '.join(sorted(CONTEST_SHAPES))}"
        )
    return key


def objective_class(shape: object, default: Optional[str] = None) -> str:
    """The objective a shape is ranked for. Raises on an unknown shape unless a
    default is supplied, because guessing an objective is the R1 defect."""
    key = str(shape or "").strip().lower()
    if key in OBJECTIVE_CLASS_BY_SHAPE:
        return OBJECTIVE_CLASS_BY_SHAPE[key]
    if default is not None:
        return default
    return validate_shape(shape, "objective_class")


def is_ticket_line(shape: object) -> bool:
    """True for shapes ranked on clearing a cut line rather than on first place."""
    return objective_class(shape, default="") == "ticket_line"


def builds_in_wta_mode(shape: object) -> bool:
    return str(shape or "").strip().lower() in WTA_CONSTRUCTION_SHAPES


def satellite_shape_for(ticket_count: Optional[int]) -> str:
    """Route a satellite by ticket structure.

    One ticket is a first-place path and takes the WTA-ticket profile. More than
    one is a cut line and takes the ticket-line profile. Unknown is the common
    case on a DK name alone, and it resolves to the ticket-line profile because
    multi-ticket qualifiers are the majority of the satellite field and because
    the blend degrades more gracefully than pure ceiling if the guess is wrong.
    ``infer_contest_archetype`` already reports ``ticket_count`` as a
    decision-critical gap, so the assumption is visible at the checkpoint.
    """
    if ticket_count is not None:
        try:
            if int(ticket_count) == 1:
                return "wta_ticket_satellite"
        except (TypeError, ValueError):
            pass
    return "satellite"
