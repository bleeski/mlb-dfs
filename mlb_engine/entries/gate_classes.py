"""gate_classes.py -- one taxonomy for every gate and refusal the build can stop on.

R388(a), Package A of the 2026-09-22 deadline-delivery audit. Two vocabularies
answered two different questions and lived in two places, and a third question
had no home at all:

* **The governor's refusal class** (``illegal`` / ``badly_shaped`` /
  ``read_it`` / ``split``, R290(c)): what a deadline may override TODAY.
  ``CLASSIC_GATE_CLASS`` held it for the Classic gates in
  ``build_slate.py`` and ``deadline_governor.py`` kept the four strings by
  value. Both now read them here; the values are unchanged.
* **The delivery-first class** (V / S / P, ``MLB_Classic.md`` §2, R386): what
  the contract says each check IS. V is submission validity, never relaxed; S
  is a strategic preference, relaxed under deadline; P is process, recorded
  and never alone a reason to withhold a V-valid file. A check that is two of
  these is MIXED, and a MIXED check is only a container: it names its facts,
  each exactly one of V, S or P, so it can never be disabled wholesale.
* **Evidence state**: ``passed``, ``failed``, ``not_checked``, ``assumed``.
  "Not checked" and "checked and passed" are different facts (audit §3), and an
  assumed gate is a third one.

The two classes are kept side by side rather than one derived from the other,
because they disagree on purpose until Sessions 06, 09 and 13 wire the V/S/P
half into behaviour: ``lineup_gate_passed`` is READ-IT to the governor today and
MIXED V/S/P to the contract. This module changes no behaviour. The governor
still reads only the refusal class.

Lookups that answer the V/S/P question RAISE on a name this module has never
classified (``UnclassifiedGateError``), because §2 says a failure that cannot be
placed is V and a silent default is how a new gate becomes relaxable. The
governor's refusal-class lookup keeps its READ-IT default instead: it runs on a
live refusal path, where an exception is a lost file.

Pure data and stdlib only, so the skill script can import it lazily and the
engine can import it at the top.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Collection, Dict, Mapping, Optional, Tuple

# --------------------------------------------------------------------------- #
# The governor's refusal class (R290(c)). Strings are the contract with
# `build_slate.py`, which must load without the engine on its path and so keeps
# its own `REFUSAL_*` constants; `test_upload_integrity.GateTaxonomyTests` holds
# the two in step.
# --------------------------------------------------------------------------- #
REFUSAL_ILLEGAL = "illegal"
REFUSAL_BADLY_SHAPED = "badly_shaped"
REFUSAL_READ_IT = "read_it"
REFUSAL_SPLIT = "split"

# --------------------------------------------------------------------------- #
# The delivery-first class (MLB_Classic.md §2, R386).
# --------------------------------------------------------------------------- #
V = "V"
S = "S"
P = "P"
MIXED = "MIXED"
VSP = (V, S, P)

# --------------------------------------------------------------------------- #
# Evidence state.
# --------------------------------------------------------------------------- #
EVIDENCE_PASSED = "passed"
EVIDENCE_FAILED = "failed"
EVIDENCE_NOT_CHECKED = "not_checked"
EVIDENCE_ASSUMED = "assumed"
EVIDENCE_STATES = (EVIDENCE_PASSED, EVIDENCE_FAILED, EVIDENCE_NOT_CHECKED,
                   EVIDENCE_ASSUMED)


class UnclassifiedGateError(KeyError):
    """A gate or refusal name this taxonomy has never classified."""


@dataclass(frozen=True)
class Validity:
    """One check's delivery-first class, and its facts when it is MIXED."""

    klass: str
    #: ``((fact, V|S|P), ...)``, non-empty exactly when ``klass`` is MIXED.
    facts: Tuple[Tuple[str, str], ...] = ()
    #: Where the audit's treatment or the repo's own rule is stated.
    note: str = ""

    def __post_init__(self) -> None:
        if self.klass not in VSP + (MIXED,):
            raise ValueError(f"validity class {self.klass!r} is not V, S, P or MIXED")
        if self.klass == MIXED:
            if not self.facts:
                raise ValueError("a MIXED check names its facts")
            for fact, klass in self.facts:
                if klass not in VSP:
                    raise ValueError(f"fact {fact!r} is {klass!r}; a fact is "
                                     "exactly one of V, S or P")
            if len({k for _, k in self.facts}) < 2:
                raise ValueError("a MIXED check spans at least two classes; "
                                 "one class is that class")
        elif self.facts:
            raise ValueError(f"a {self.klass} check has no facts to split")

    def classes(self) -> frozenset:
        """Every V/S/P class this check can fail as."""
        if self.klass == MIXED:
            return frozenset(k for _, k in self.facts)
        return frozenset({self.klass})


def _m(*facts: Tuple[str, str], note: str = "") -> Validity:
    return Validity(MIXED, tuple(facts), note)


# --------------------------------------------------------------------------- #
# The governor's Classic gate table, moved verbatim from build_slate.py (R290(c)
# commit 1). Keys are exactly dk_entries_manager's PRE_EXPORT_GATES and
# POST_EXPORT_GATES; `test_every_workflow_gate_is_classified` pins that.
# --------------------------------------------------------------------------- #
# The SPLIT half of `classic_not_certified`, one row per post-export gate.
# `roster_legality_passed` is everything in dk_entries_manager's validator that
# is NOT an exposure or overlap error; `portfolio_caps_passed` is exactly the
# exposure and overlap errors (player, pitcher, primary-stack, SP-pair, per-game
# caps and max_shared_players), all of which are Ben's own numbers and every one
# of which DK accepts. So the single exit that lost 1940_9g cannot distinguish
# "DK will reject this" from "this is more concentrated than you asked for", and
# the second is the whole reason the governor exists.
CLASSIC_GATE_CLASS: Dict[str, Tuple[str, str]] = {
    # Pre-export, the nine in dk_entries_manager.PRE_EXPORT_GATES. Seven of
    # them are READ-IT for one reason: each reports that an INPUT is wrong or
    # absent -- the salary file's shape, the entry grid, who is starting, a
    # weather or odds feed, the projection schema. A relaxation ladder relaxes
    # OUTPUT controls; there is no rung that fixes an input, so the governor
    # would be pressing past a fact rather than loosening a preference.
    "salary_gate_passed": (REFUSAL_READ_IT, "input_identity"),
    "entry_grid_gate_passed": (REFUSAL_READ_IT, "input_identity"),
    "lineup_gate_passed": (REFUSAL_READ_IT, "input_identity"),
    "pitcher_audit_gate_passed": (REFUSAL_READ_IT, "input_identity"),
    "weather_gate_passed": (REFUSAL_READ_IT, "input_identity"),
    "odds_gate_passed": (REFUSAL_READ_IT, "input_identity"),
    "projection_schema_gate_passed": (REFUSAL_READ_IT, "input_identity"),
    "optimizer_gate_passed": (REFUSAL_READ_IT, "provenance"),
    # The allocator's own verdict on the selection it made under the portfolio
    # controls, so it is the same family as an outright allocation failure and
    # it relaxes the same way.
    "selection_certified": (REFUSAL_BADLY_SHAPED, "ben_preference"),
    # Post-export, the six in dk_entries_manager.POST_EXPORT_GATES.
    "template_preservation_passed": (REFUSAL_ILLEGAL, "dk_rule"),
    "entry_reconciliation_passed": (REFUSAL_ILLEGAL, "dk_rule"),
    "roster_legality_passed": (REFUSAL_ILLEGAL, "dk_rule"),
    "locked_immutability_passed": (REFUSAL_ILLEGAL, "dk_rule"),
    # Not a DK rule and not a preference: the file may be perfectly legal while
    # the record that binds a sha256 to it is broken. Delivering a file whose
    # hash does not bind is what the money-boundary items forbid, and every
    # brief states a sha256 Ben checks at upload, so this refuses -- but it
    # refuses because the RECORD failed, which is a different sentence from
    # "the lineups are wrong" and an operator under a clock needs the
    # difference.
    "export_hash_binding_passed": (REFUSAL_READ_IT, "provenance"),
    "portfolio_caps_passed": (REFUSAL_BADLY_SHAPED, "ben_preference"),
}
CLASSIC_ALLOCATION_FAILED_CLASS = (REFUSAL_BADLY_SHAPED, "ben_preference")
CLASSIC_CONTEST_IDENTITY_CLASS = (REFUSAL_READ_IT, "input_identity")
# A gate the table above has never classified is READ-IT, and the default is a
# safety property rather than a convenience: the governor never passes what it
# has not been told about. It is not a default that can never fire, as the
# comment it replaced said: R388(a) measured three names that CAN reach it.
# `validate_upload_ready_gates` fails `allocation_certified` and
# `allocation_method` by those names, and a forbidden caller assertion as
# `caller_assertion:<gate>`, which `build_slate._GATE_ERROR_RE` (`\w+`) reads as
# `caller_assertion`. On the `run_slate` path the two allocation names do not
# arrive in practice: every allocator record with `allocation_certified` False
# also has `passed` False, and `execute_portfolio` blocks on that before the
# gate check. All three refuse at every clock, the conservative direction, and
# their V/S/P classes are in GATE_VALIDITY below.
CLASSIC_GATE_CLASS_DEFAULT = (REFUSAL_READ_IT, "unclassified")


def classic_gate_class(name: str) -> Tuple[str, str]:
    """The governor's (refusal class, authority) for one Classic gate name."""
    return CLASSIC_GATE_CLASS.get(str(name), CLASSIC_GATE_CLASS_DEFAULT)


# --------------------------------------------------------------------------- #
# The delivery-first class of every gate the certification path can name:
# dk_entries_manager's PRE_EXPORT_GATES and POST_EXPORT_GATES, every name in
# FORBIDDEN_CALLER_ASSERTIONS, the two allocation gates
# `validate_upload_ready_gates` adds, and `caller_assertion`, the name a
# forbidden assertion fails under. Classes are the audit's (§3,
# `docs/2026-09-22_deadline_delivery_qa.md`); where it names two classes the
# check is MIXED and split into the facts its "required treatment" column
# separates. Where the audit leaves a fact unplaced, §2's rule applies: it is V.
# --------------------------------------------------------------------------- #
GATE_VALIDITY: Dict[str, Validity] = {
    # -- pre-export ------------------------------------------------------ #
    "salary_gate_passed": Validity(
        V, note="real player IDs, official salary and eligibility, the correct "
                "slate and a parseable authority"),
    "entry_grid_gate_passed": Validity(
        V, note="Entry IDs, contest mapping, geometry, row accounting and "
                "authorization"),
    "lineup_gate_passed": _m(
        ("player_identity_or_known_unavailability", V),
        ("missing_confirmation_or_stale_reference", P),
        ("team_cannot_fill_a_preferred_stack", S),
        note="missing confirmation is not a scratch"),
    "pitcher_audit_gate_passed": _m(
        ("pitcher_identity_and_participation_evidence", V),
        ("missing_preferred_role_label", P),
        note="a missing role label is not a platform rule; never manufacture a "
             "declaration"),
    "weather_gate_passed": _m(
        ("known_postponement_or_lock_effect", V),
        ("missing_optional_forecast", P),
        ("material_risk_cap", S)),
    "odds_gate_passed": Validity(
        P, note="missing or unmatched market evidence never blocks a legal "
                "export; record unavailable, never an invented market"),
    "projection_schema_gate_passed": _m(
        ("corrupt_ids_salaries_or_eligibility", V),
        ("missing_or_bad_statistical_estimates", P),
        note="bad model values are repaired or omitted, never fabricated"),
    "optimizer_gate_passed": Validity(
        P, note="scipy availability and provenance are not platform validity; "
                "a permitted fallback's output is still V-validated by the "
                "post-export gates"),
    "selection_certified": _m(
        ("requested_strategy_satisfied", S),
        ("selection_record", P),
        note="validity of the selected rosters is roster_legality_passed's, "
             "not this gate's"),
    "allocation_certified": _m(
        ("entry_assignment_correctness", V),
        ("global_portfolio_optimality", P),
        ("preferred_allocation_quality", S)),
    "allocation_method": Validity(
        P, note="the scipy joint-MILP allowlist is an architecture rule, not a "
                "submission rule; a fallback needs an honest method label and "
                "independent validation"),
    # -- post-export ----------------------------------------------------- #
    "template_preservation_passed": Validity(
        V, note="identity, file structure and non-authorized cells; a partial "
                "output never truncates or corrupts the operator's template"),
    "entry_reconciliation_passed": Validity(
        V, note="each delivered entry carries its intended roster"),
    "roster_legality_passed": _m(
        ("platform_roster_rules", V),
        ("non_platform_anti_correlation", S),
        ("completeness_accounting", P),
        ("distinct_lineups_per_contest", S),
        note="distinct lineups per contest is F-3: an S control with operator "
             "never-relax authority, kept under every deadline"),
    "locked_immutability_passed": Validity(
        V, note="genuinely locked slots and unauthorized selections; no "
                "deadline override"),
    "export_hash_binding_passed": _m(
        ("delivered_byte_identity", V),
        ("redundant_record_plumbing", P),
        note="a broken auxiliary record is reconstructed, never an invented "
             "hash or stale bytes"),
    "portfolio_caps_passed": Validity(
        S, note="player, pitcher, stack, SP-pair, game and team caps and "
                "overlap"),
    # -- aggregates a caller may never assert (FORBIDDEN_CALLER_ASSERTIONS) - #
    "workflow_valid": _m(
        ("no_fabricated_validation", V),
        ("aggregate_record", P),
        note="derived by dk_entries_manager, never supplied; its members carry "
             "their own classes"),
    "dk_export_gate_passed": _m(
        ("no_fabricated_validation", V),
        ("aggregate_record", P),
        note="derived, never supplied"),
    "post_export_gate_passed": _m(
        ("no_fabricated_validation", V),
        ("aggregate_record", P),
        note="derived, never supplied"),
    "caller_assertion": Validity(
        V, note="a caller asserted a gate only this module derives; "
                "fabricated validation is refused at every clock"),
}


# --------------------------------------------------------------------------- #
# The delivery-first class of every `build_slate.REFUSAL_SITES` key. The site
# keeps its `klass` and `authority`; this is the contract's answer beside them.
# `classic_not_certified` is split by the gates that failed, so its facts point
# at GATE_VALIDITY rather than restating it; `classic_verify_failed` is split
# by `verify_classic`'s failure kinds (`build_slate.VERIFY_CLASSIC_FAILURE_CLASS`).
# --------------------------------------------------------------------------- #
REFUSAL_SITE_VALIDITY: Dict[str, Validity] = {
    "pool_blocked_hard": _m(
        ("slate_identity", V),
        ("pool_size", S),
        ("evidence_completeness", P),
        note="classify the individual blocker; salvage unaffected entries"),
    "pool_blocked_crosswalk": _m(
        ("authoritative_identity", V),
        ("under_five_name_wall", P),
        note="the under-five wall is a repository rule, not a demonstrated DK "
             "rule; its authority stays claude_md_wall, so it remains Ben's at "
             "any clock (CLAUDE.md Autonomy)"),
    "bank_thin_partial": Validity(
        S, note="candidate count and pair coverage are bank targets, which §2 "
                "lists as S; not proof that no usable entry exists"),
    "classic_not_certified": _m(
        ("contest_identity", V),
        ("allocation_failed", S),
        ("failed_gate", V),
        note="split by the gates that failed: each carries its own "
             "GATE_VALIDITY class, and `failed_gate` is the unplaced default, "
             "V by §2"),
    # Every verify kind is V, `blank_row` included: F-2 says DK takes a
    # partial file only with the unresolved rows REMOVED, and a blank row is
    # not that form. The governor still classes `blank_row` BADLY-SHAPED
    # (`VERIFY_CLASSIC_FAILURE_CLASS`) because its rung 2 delivers blank rows;
    # dropping them and reporting the coverage is R401 (Session 22).
    "classic_verify_failed": Validity(
        V, note="partial row, unknown player id, over cap, duplicate player, "
                "slot ineligible, team stack over max, too few games, and a "
                "blank row (F-2)"),
    "showdown_ladder_infeasible": Validity(
        S, note="a thesis shortfall under Ben's three Showdown controls is not "
                "legal impossibility"),
    "showdown_bank_short": Validity(
        S, note="search effort against preferences"),
    "showdown_not_certified": Validity(
        V, note="captain and UTIL roles, person uniqueness, salary and team "
                "requirements"),
    "showdown_bank_short_of_reserved_rows": _m(
        ("bank_short_of_rows", S),
        ("blank_reserved_row", V),
        note="the rows the bank fills are deliverable; a blank row is not the "
             "partial form (F-2)"),
    "showdown_export_failed": Validity(
        V, note="no DK-valid file was produced"),
    "showdown_template_broken": Validity(
        V, note="a non-roster cell changed, so the file is no longer the "
                "template DK issued"),
}


def _base_name(name: str) -> str:
    text = str(name)
    return "caller_assertion" if text.startswith("caller_assertion") else text


def gate_validity(name: str) -> Validity:
    """The V/S/P class of one gate name. Raises on a name never classified."""
    key = _base_name(name)
    try:
        return GATE_VALIDITY[key]
    except KeyError:
        raise UnclassifiedGateError(
            f"gate {name!r} has no V/S/P class in mlb_engine/entries/"
            "gate_classes.py; a check that cannot be placed is V "
            "(MLB_Classic.md §2), so classify it before anything reads it"
        ) from None


def refusal_site_validity(key: str) -> Validity:
    """The V/S/P class of one refusal site. Raises on a key never classified."""
    try:
        return REFUSAL_SITE_VALIDITY[str(key)]
    except KeyError:
        raise UnclassifiedGateError(
            f"refusal site {key!r} has no V/S/P class in mlb_engine/entries/"
            "gate_classes.py; classify it beside its REFUSAL_SITES row"
        ) from None


def evidence_state(values: Mapping[str, Any], name: str,
                   assumed: Collection[str] = ()) -> str:
    """One gate's evidence state from a workflow-gate mapping.

    ``assumed`` is the operator's ``--assume-gates`` list: a gate named there
    is ``assumed`` whatever value it carries, because an assumption is neither
    a check nor its absence. A name absent from ``values`` was not checked. A
    present value passes only when it is literally ``True``, or a mapping whose
    ``passed`` is, the same identity rule ``dk_entries_manager._gate_bool``
    applies, so "1 means yes" cannot come back through this door.
    """
    if name in set(assumed or ()):
        return EVIDENCE_ASSUMED
    if name not in values:
        return EVIDENCE_NOT_CHECKED
    value = values[name]
    if isinstance(value, Mapping):
        value = value.get("passed")
    return EVIDENCE_PASSED if value is True else EVIDENCE_FAILED


def describe(name: str, kind: str = "gate") -> Dict[str, Any]:
    """A JSON-ready row for one gate or refusal site, both classes side by side."""
    validity = gate_validity(name) if kind == "gate" else refusal_site_validity(name)
    out: Dict[str, Any] = {"name": str(name), "validity": validity.klass}
    if validity.facts:
        out["facts"] = {fact: klass for fact, klass in validity.facts}
    if validity.note:
        out["note"] = validity.note
    if kind == "gate" and _base_name(name) in CLASSIC_GATE_CLASS:
        refusal, authority = CLASSIC_GATE_CLASS[_base_name(name)]
        out["refusal_class"], out["authority"] = refusal, authority
    return out
