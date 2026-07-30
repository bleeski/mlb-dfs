"""Canonical MLB Classic execution pipeline (MLB Classic v2.26.0).
VERSION is the authoritative version constant for this module.

Initial builds and late swaps share one immutable, hash-bound production path.
The exact final DKEntries file is re-read to derive all post-export gates.

v1.15 changes (R28):
- ``run_slate(approve=False)`` gains a plan-mode joint-allocation verdict.
  ``_plan_joint_allocation`` builds a bank through the sliced path into a
  TEMPORARY cache (never the shared per-slate cache) and solves the same
  ``select_and_assign_entries`` MILP the build solves, then reports
  ``would_certify``, ``proven_infeasible`` carrying the build's exact error
  text, or ``unchecked`` naming the budget it ran out of. It never reports
  silence, which was the defect: ``_slate_feasibility``'s auto-floors are
  POOL-keyed and cannot see an interaction that lives in the BANK, so the
  checkpoint passed plans the build then proved jointly infeasible.
  ``plan_solve_budget_s`` sets the budget (default ``PLAN_SOLVE_BUDGET_S``);
  0 disables the solve and says so. approve=False still creates no run
  directory and writes nothing outside the temporary cache; approve=True is
  unchanged.
- The verdict names its own exactness. With ``candidates_override`` the plan
  solves the build's own candidates and ``exact_for_this_build`` is True; on
  the auto-bank path the plan's sliced bank is not the build's
  ``build_diverse_candidate_bank`` bank and the summary says so.
- An allocator time limit at plan time is reported as ``unchecked``, never as
  ``proven_infeasible``: that distinction is the allocator's own contract and
  collapsing it would be the mislabel the item exists to remove.

v1.9 changes:
- Percentage exposure caps join the feasibility floors. ``_slate_feasibility``
  now derives the minimum feasible ``max_player_exposure_pct``,
  ``max_pitcher_exposure_pct``, and ``max_primary_stack_exposure_pct`` from the
  entry count, the viable SP count, and the stackable-team count (a pitcher cap
  must admit ceil(2*entries/viable_SPs) appearances for some arm, a stack cap
  ceil(entries/stackable_teams) for some team), and ``run_slate`` floors the
  tightest-merged pct caps to those values before the explicit override, which
  still wins. This retires the last recurring manual relaxation (ledger 3.3).
- Floors now apply only to keys already present after the posture merge. The
  v1.8 behavior of inserting an absent repetition key at its floor value could
  ADD a cap where no posture set one; a floor may only relax, never restrict.
- ``run_slate`` surfaces the slate clock (``slate_intake_manager.slate_clock``)
  on the checkpoint and the result: first lock, the T-minus-5 delivery deadline,
  and minutes remaining, with a warning when the deadline is inside 15 minutes
  or already past. Deterministic bookkeeping, never a guarantee.
- ``_feasibility_report`` gains pct-cap capacity checks that name the exact
  required cap value when a resolved pct cannot cover the field; advisory,
  never a hard block.

v1.8 changes:
- Feasibility-aware control resolution. ``_merged_controls_for_build`` accepts
  ``feasibility_floors`` and raises the tightest-merged ``max_sp_pair_repetition``
  and ``max_shared_players`` to a slate-feasible minimum BEFORE explicit overrides,
  so a mixed portfolio no longer inherits a cap of 1 from a single-entry posture or
  a shared-players cap of 6 that is infeasible against a repeating five-stack. The
  floors are derived by ``_slate_feasibility`` from the viable SP-pair count, entry
  count, and stack size; an explicit override always wins over the floor.
- Pre-solve feasibility assertion on the checkpoint. ``run_slate`` injects
  ``checkpoint["feasibility"]`` (via ``_feasibility_report``) naming the exact
  binding constraint and the required cap value when the resolved controls cannot
  cover the field, and appends those to the checkpoint warnings. Structural and
  bank-free, so it runs at ``approve=False`` before the expensive solve.
- ``run_slate`` builds the candidate bank through
  ``optimizer_v3.build_diverse_candidate_bank`` so the auto-bank path carries
  guaranteed SP-pair and stack coverage instead of collapsing on thin slates.
  All of the above are deterministic review inputs, never ROI, win-rate, or
  probability claims.

v1.6 changes:
- FIXED the silent xwOBA no-op: ``_assemble_projection_frame`` now joins the
  Base correction through ``xwoba_base_correction.build_dk_keyed_corrections``
  (the DK-keyed name crosswalk) instead of the MLBAM-keyed map whose ids never
  intersect the slate's DraftKings ids. The match report is surfaced under
  ``projection_enrichment["xwoba"]``; a zero-match on a pool of at least
  ``XWOBA_WIRING_MIN_POOL`` raises as a wiring failure, and a sub-50% match
  rate warns. Supplying CSVs without AvgPointsPerGame values also warns instead
  of silently skipping.
- Codified the value-sanity guard (previously a manual protocol step): hitter
  Base is capped at the slate 90th-percentile hitter pts/$1k times 1.08 before
  F1-F5, opt-out via ``apply_value_sanity_guard=False``, clips tagged in Notes
  and reported.
- Per-player Ceiling multipliers from expected ISO join through
  ``build_dk_keyed_ceiling_multipliers`` when the batting CSV is supplied and
  flow into ``build_projections`` via the ``Ceiling_Multiplier`` column.
- v1.7: per-pitcher Ceiling multipliers from a FanGraphs K-rate input join
  through ``build_dk_keyed_pitcher_ceiling_multipliers`` when
  ``fangraphs_pitching_csv`` is supplied and fill the same
  ``Ceiling_Multiplier`` column for pitcher rows, closing the "hitters only
  until a K-rate input exists" gap; surfaced under
  ``projection_enrichment["pitcher_ceiling"]`` with the same zero-match
  wiring guard.
- Deterministic F4: ``run_slate`` gains ``f4_by_player_id``, a map built
  upstream by ``projection_builder.compute_f4_factors`` and applied to rows
  lacking an explicit F4; explicit factors always win.
- ``_assemble_projection_frame`` now returns ``(projections, enrichment)`` and
  ``run_slate`` surfaces ``projection_enrichment`` in the checkpoint payload
  and the approved result, with enrichment warnings appended to the checkpoint
  warnings. All enrichments are deterministic labeled priors or review inputs,
  never ROI, win-rate, or probability claims.

v1.2 changes:
- Added ``run_slate``, the single front door. It takes raw slate inputs (salary
  CSV, entries template, per-player projection rows or a prebuilt frame, contest
  postures), assembles an optimizer-ready projection frame, builds the candidate
  bank, derives entry requirements, maps each contest to a strategy default, and
  emits a one-screen pre-build checkpoint. With ``approve=False`` it stops before
  the expensive bank/allocation so a construction error is caught in seconds.
  With ``approve=True`` it runs the existing certified ``execute_portfolio`` path.
- Added ``STRATEGY_DEFAULTS`` keyed on contest posture. These are principled
  priors, not empirically tuned values; there is not enough accumulated slate
  data to calibrate them, so they are labeled priors and never called win rates.
- Added the assembly conformance step (DK slot-token coercion, explicit
  ``Ownership_Tier`` default, ``Stack_Group`` default) so the frame drops into
  the optimizer without per-slate hand fixing.
- Added a lighter ``light_satellite`` path that skips the bank-coverage solve.
  It deliberately keeps the immutable run directory, the final-export re-read,
  and the blank-reserved-row block, because those are the guardrail that stops a
  broken upload; only the optional diagnostics are trimmed.
- The integration contract for these inputs lives in
  ``MLB_Classic_Integration_Contract.md`` (untracked companion doc).

v1.1 changes:
- Gate-blocked runs are marked ``status='blocked'`` so a crashed run and a
  blocked run are distinguishable in the manifest.
- ``run_late_swap`` accepts ``authorized_entry_ids`` (only those Entry IDs are
  mutable) and ``missing_status_policy`` (unknown lock state fails closed).
- ``validate_only`` late swaps receive a real Run ID, input snapshot, and a
  registered requirements artifact, with certification hardcoded False.
- The parent's promoted export hash and the current DKEntries hash are recorded
  in run metadata so the parent linkage is checkable, not just a label.
- Optional confirmed-lineup refresh routes through the shared projection
  builder when confirmed orders are supplied.
- A bank-coverage diagnostic (one unconstrained ceiling solve vs the best bank
  candidate) is recorded in diagnostics; it never blocks a run.
"""
from __future__ import annotations

import csv
import json
import shutil
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, MutableMapping, Optional, Sequence

import pandas as pd

from mlb_engine.pipeline.build_state_manager import (
    create_run, promote_run, read_pointer_sha256, register_artifact,
    sha256_file, snapshot_run_inputs, update_run_certification,
)
from mlb_engine.allocate.contest_allocator import select_and_assign_entries
from mlb_engine.contest_shapes import (
    SATELLITE_PAYOUT_TOKENS, SATELLITE_TYPE_TOKENS, WTA_CONSTRUCTION_SHAPES,
    satellite_shape_for, validate_shape,
)
from mlb_engine.entries.dk_entries_manager import (
    derive_workflow_certification, reconcile_entries_against_assignments,
    validate_dk_entries_file, validate_template_preservation,
    validate_upload_ready_gates, write_candidate_from_template,
)
from mlb_engine.swap.late_swap_manager import (
    PlayerLineupStatus, build_entry_requirements, late_swap_certification,
    load_latest_valid_parent_run, validate_late_swap_delta,
)

VERSION = "v1.15"

# --- v1.6 projection-enrichment constants -----------------------------------
# XWOBA_WIRING_MIN_POOL: a supplied xwOBA correction that matches ZERO players
# on a pool at least this large is a wiring failure and raises; below it (toy
# fixtures) a zero-match only warns through the report. XWOBA_LOW_MATCH_RATE_WARN
# surfaces a degraded (but nonzero) crosswalk. VALUE_GUARD_* codify the manual
# hitter Base value-sanity protocol: cap at the slate 90th-percentile hitter
# pts/$1k times the headroom, before F1-F5. All deterministic, never claims.
XWOBA_WIRING_MIN_POOL = 10
XWOBA_LOW_MATCH_RATE_WARN = 0.50
VALUE_GUARD_PCTL = 0.90
VALUE_GUARD_HEADROOM = 1.08


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _write_assignments(path: Path, assignments: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "entry_id", "contest_id", "contest_name", "contest_shape", "candidate_id",
        "lineup_signature", "contest_fit_score", "primary_stack", "sp_ids",
        "lineup_ids", "reused_across_contests",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in assignments:
            values = dict(row)
            values["sp_ids"] = "/".join(str(x) for x in row.get("sp_ids", []))
            values["lineup_ids"] = "/".join(str(x) for x in row.get("lineup_ids", []))
            writer.writerow({field: values.get(field, "") for field in fields})


def _materialize_projections(projections: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(projections, pd.DataFrame):
        projections.to_csv(path, index=False)
    elif isinstance(projections, (str, Path)):
        shutil.copy2(projections, path)
    else:
        pd.DataFrame(list(projections)).to_csv(path, index=False)


def _bank_coverage(projections: Any, candidates: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Diagnostic only: never raises, never blocks."""
    try:
        if not isinstance(projections, pd.DataFrame):
            return {"passed": None, "note": "bank coverage requires a projections DataFrame"}
        from mlb_engine.optimize.optimizer_v3 import bank_coverage_report
        report = dict(bank_coverage_report(projections, candidates) or {})
        try:
            report["game_script_coverage"] = compute_game_script_coverage(projections, candidates)
        except Exception:
            pass
        return report
    except Exception as exc:  # noqa: BLE001 - diagnostic must not block the run
        return {"passed": None, "note": f"bank coverage diagnostic unavailable: {exc}"}


def _json_safe(value: Any) -> Any:
    """Drop anything that will not serialise, keeping the rest.

    bank_diag carries DataFrames under 'lineups'. The counts and validations
    beside them are the reviewable part and must reach disk; a single
    unserialisable key must not take the whole record with it.
    """
    if isinstance(value, Mapping):
        return {
            ("|".join(sorted(str(x) for x in k))
             if isinstance(k, (tuple, frozenset, set)) else str(k)): _json_safe(v)
            for k, v in value.items() if k != "lineups"
        }
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (set, frozenset)):
        return sorted(str(v) for v in value)
    return str(value)


def _blocked_result(run: Dict[str, Any], errors: Sequence[str], diagnostics: Dict[str, Any]) -> Dict[str, Any]:
    run_dir = Path(run["run_dir"])
    diagnostic_path = run_dir / "final" / "diagnostics.json"
    # Blocked-run diagnostics used to omit status, blockers and errors, and to
    # carry empty hash-binding fields, so verify_run_bundle reported a false
    # "missing export hash binding" on a run that had been correctly blocked. A
    # correctly blocked run is not a tampered one, and the record has to say
    # which it is.
    diagnostics = {
        **diagnostics,
        "status": "blocked",
        "pipeline_version": VERSION,
        "errors": list(errors),
        "blockers": list(errors),
        "export_declared": False,
        "hash_binding_applicable": False,
        "hash_binding_note": "no export was declared for this run; hash binding "
                             "does not apply and its absence is not a defect",
    }
    _write_json(diagnostic_path, diagnostics)
    register_artifact(run_dir, diagnostic_path, "diagnostics")
    update_run_certification(
        run_dir,
        {"workflow_valid": False, "selection_certified": False, "allocation_certified": False},
        errors=list(errors),
        warnings=diagnostics.get("warnings", []),
        status="blocked",
    )
    return {
        "passed": False, "run_id": run["run_id"], "run_dir": str(run_dir),
        "errors": list(errors), "diagnostics_path": str(diagnostic_path),
        "workflow_valid": False,
    }


def execute_portfolio(
    *,
    runs_root: str | Path,
    mode: str,
    salary_csv: str | Path,
    entries_csv: str | Path,
    projections: Any,
    candidates: Sequence[Dict[str, Any]],
    entry_requirements: Sequence[Dict[str, Any]],
    workflow_gates: Mapping[str, Any],
    portfolio_controls: Optional[Mapping[str, Any]] = None,
    confirmed_hitter_ids: Optional[Iterable[str]] = None,
    confirmed_teams: Optional[Iterable[str]] = None,
    pitcher_roles: Optional[Mapping[str, str]] = None,
    excluded_player_ids: Optional[Iterable[str]] = None,
    parent_run_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    additional_input_paths: Optional[Sequence[str | Path]] = None,
    compute_bank_coverage: bool = True,
    # F11. Explicit rather than smuggled through ``metadata``: metadata goes into
    # the run manifest, and these carry frozenset-keyed pair counts that a
    # manifest cannot serialise. They belong in diagnostics.json only.
    bank_diagnostics: Optional[Mapping[str, Any]] = None,
    bank_warnings: Optional[Sequence[str]] = None,
    # R29(2): hold the promotion until the caller has decided the run is a
    # delivery. See :func:`promote_deferred_run`.
    defer_promotion: bool = False,
) -> Dict[str, Any]:
    """Execute the canonical entry-level portfolio workflow."""
    controls = dict(portfolio_controls or {})
    run = create_run(runs_root, mode, parent_run_id=parent_run_id, metadata={"pipeline_version": VERSION, **(metadata or {})})
    # R20(c): the compare half of promotion's compare-and-swap, captured the
    # moment this run begins. If another session promotes while this run is
    # building, promotion below refuses instead of silently overwriting.
    pointer_sha_at_create = read_pointer_sha256(runs_root)
    run_dir = Path(run["run_dir"])
    input_paths = [salary_csv, entries_csv, *(additional_input_paths or [])]
    snapshot_run_inputs(run_dir, input_paths)

    projection_path = run_dir / "final" / "projections.csv"
    _materialize_projections(projections, projection_path)
    register_artifact(run_dir, projection_path, "projections")

    allocation = select_and_assign_entries(candidates, entry_requirements, controls)
    if not allocation.get("passed"):
        diagnostics = {
            "run_id": run["run_id"], "mode": mode, "allocation": allocation,
            "diagnostic_source_file": "", "diagnostic_source_sha256": "",
            "workflow_valid": False,
        }
        return _blocked_result(run, allocation.get("errors", ["allocation failed"]), diagnostics)

    bank_coverage = _bank_coverage(projections, candidates) if compute_bank_coverage else None

    assignments = allocation["assignments"]
    assignment_path = run_dir / "final" / "assignments.csv"
    _write_assignments(assignment_path, assignments)
    assignment_record = register_artifact(run_dir, assignment_path, "assignments")

    pre_gate_values = dict(workflow_gates)
    pre_gate_values.update({
        "selection_certified": allocation.get("selection_certified"),
        "allocation_required": True,
        "allocation_certified": allocation.get("allocation_certified"),
        "allocation_method": allocation.get("allocation_method"),
    })
    pre = validate_upload_ready_gates(pre_gate_values, allocation_required=True)

    candidate_path = run_dir / "candidate" / "DO_NOT_UPLOAD_DKEntries.csv"
    write_result = write_candidate_from_template(entries_csv, assignments, candidate_path, preserve_completed=(mode != "late_swap"))
    if not write_result["passed"]:
        diagnostics = {
            "run_id": run["run_id"], "mode": mode, "allocation": allocation,
            "pre_export": pre, "candidate_write": write_result,
            "bank_coverage": bank_coverage,
            "diagnostic_source_file": "", "diagnostic_source_sha256": "",
            "workflow_valid": False,
        }
        return _blocked_result(run, write_result["errors"], diagnostics)
    register_artifact(run_dir, candidate_path, "candidate_export")

    mutable_ids = [str(req["entry_id"]) for req in entry_requirements]
    locked_slots = {
        str(req["entry_id"]): dict(req.get("locked_slot_assignments") or {})
        for req in entry_requirements if req.get("locked_slot_assignments")
    }
    template = validate_template_preservation(entries_csv, candidate_path, mutable_entry_ids=mutable_ids if mode == "late_swap" else None)
    reconciliation = reconcile_entries_against_assignments(assignments, candidate_path)
    candidate_validation = validate_dk_entries_file(
        candidate_path,
        salary_csv_path=salary_csv,
        confirmed_hitter_ids=confirmed_hitter_ids,
        confirmed_teams=confirmed_teams,
        pitcher_roles=pitcher_roles,
        excluded_player_ids=excluded_player_ids,
        locked_slot_assignments=locked_slots,
        portfolio_controls=controls,
        require_all_reserved_filled=True,
    )
    if mode == "late_swap":
        delta = validate_late_swap_delta(entries_csv, candidate_path, mutable_entry_ids=mutable_ids)
    else:
        delta = {"passed": True, "errors": [], "changed_entry_ids": mutable_ids}

    early_errors = pre["errors"] + template["errors"] + reconciliation["errors"] + candidate_validation["errors"] + delta["errors"]
    if early_errors:
        diagnostics = {
            "run_id": run["run_id"], "mode": mode, "allocation": allocation,
            "pre_export": pre, "template_preservation": template,
            "entry_reconciliation": reconciliation, "candidate_validation": candidate_validation,
            "late_swap_delta": delta,
            "bank_coverage": bank_coverage,
            "diagnostic_source_file": str(candidate_path.relative_to(run_dir)),
            "diagnostic_source_sha256": sha256_file(candidate_path),
            "assignment_sha256": assignment_record["sha256"],
            "workflow_valid": False,
        }
        return _blocked_result(run, early_errors, diagnostics)

    final_export = run_dir / "final" / "DKEntries.csv"
    shutil.copy2(candidate_path, final_export)
    final_hash = sha256_file(final_export)
    candidate_hash = sha256_file(candidate_path)
    final_validation = validate_dk_entries_file(
        final_export,
        salary_csv_path=salary_csv,
        confirmed_hitter_ids=confirmed_hitter_ids,
        confirmed_teams=confirmed_teams,
        pitcher_roles=pitcher_roles,
        excluded_player_ids=excluded_player_ids,
        locked_slot_assignments=locked_slots,
        portfolio_controls=controls,
        require_all_reserved_filled=True,
    )
    final_reconciliation = reconcile_entries_against_assignments(assignments, final_export)
    post = {
        "template_preservation_passed": template["passed"],
        "entry_reconciliation_passed": final_reconciliation["passed"],
        "roster_legality_passed": final_validation["roster_legality_passed"],
        "portfolio_caps_passed": final_validation["portfolio_caps_passed"],
        "locked_immutability_passed": final_validation["locked_immutability_passed"] and delta["passed"],
        "export_hash_binding_passed": candidate_hash == final_hash,
    }
    certification = derive_workflow_certification(pre, post, allocation_required=True)
    diagnostics = {
        "run_id": run["run_id"],
        "parent_run_id": parent_run_id,
        "mode": mode,
        "pipeline_version": VERSION,
        "allocation": allocation,
        "pre_export": pre,
        "post_export": post,
        "template_preservation": template,
        "entry_reconciliation": final_reconciliation,
        "final_export_validation": final_validation,
        "late_swap_delta": delta,
        "bank_coverage": bank_coverage,
        "diagnostic_source_file": str(final_export.relative_to(run_dir)),
        "diagnostic_source_sha256": final_hash,
        "assignment_sha256": assignment_record["sha256"],
        # F4: what the pre-export gates were built from, recorded in the immutable
        # run record. "Upload-ready" is defined as all three gates passing, so the
        # artifact has to say which of its inputs were checked, which were
        # asserted by the caller, and which were assumed without checking.
        "workflow_gate_evidence": dict((metadata or {}).get("workflow_gate_evidence") or {}),
        "assumed_gates": list((metadata or {}).get("assumed_gates") or []),
        "caller_asserted_gates": list((metadata or {}).get("caller_asserted_gates") or []),
        # F11: what the build actually did. build_multi_lineup returns relaxation
        # counts, DU and anchor validation, and failed_indices; none of it was
        # written down, so the immutable run record could not answer "what did the
        # engine give up to produce this file". Relaxations are exactly the facts
        # post-slate review needs, and a portfolio is clean when they are zero,
        # not when the gates pass.
        "bank_diagnostics": _json_safe(bank_diagnostics),
        "warnings": list(bank_warnings or []),
        "status": "certified" if certification.get("workflow_valid") else "blocked",
        "export_declared": True,
        "hash_binding_applicable": True,
        **certification,
    }
    diagnostic_path = run_dir / "final" / "diagnostics.json"
    _write_json(diagnostic_path, diagnostics)
    register_artifact(run_dir, final_export, "dk_export")
    register_artifact(run_dir, diagnostic_path, "diagnostics")
    update_run_certification(
        run_dir, certification, errors=[],
        warnings=final_validation.get("warnings", []),
        status=None if certification["workflow_valid"] else "blocked",
    )
    if not certification["workflow_valid"]:
        return {
            "passed": False, "run_id": run["run_id"], "run_dir": str(run_dir),
            "errors": [f"failed post-export gate: {x}" for x in certification["failed_post_export_gates"]],
            "diagnostics_path": str(diagnostic_path), "workflow_valid": False,
        }
    if defer_promotion:
        # R29(2): certification and delivery are two different facts, and the
        # pointer is a claim about delivery. A caller that can still refuse the
        # file after this point (late_swap.py's downgrade check) must promote
        # afterwards, or the pointer names a run nothing was mirrored from and
        # the next swap dies on a parent mismatch that reads like a
        # multi-session collision. The run stays mutable and valid.
        return {
            "passed": True,
            "run_id": run["run_id"],
            "run_dir": str(run_dir),
            "output_path": str(final_export),
            "assignments_path": str(assignment_path),
            "projections_path": str(projection_path),
            "diagnostics_path": str(diagnostic_path),
            "bank_coverage": bank_coverage,
            "workflow_valid": True,
            "selection_certified": certification["selection_certified"],
            "allocation_certified": certification["allocation_certified"],
            "errors": [],
            "promotion_deferred": True,
            "promoted": False,
            "pointer_sha_at_create": pointer_sha_at_create,
        }
    promotion = promote_run(run_dir, expected_pointer_sha256=pointer_sha_at_create)
    return {
        "passed": bool(promotion["passed"]),
        "run_id": run["run_id"],
        "run_dir": str(run_dir),
        "output_path": str(final_export) if promotion["passed"] else None,
        "assignments_path": str(assignment_path),
        "projections_path": str(projection_path),
        "diagnostics_path": str(diagnostic_path),
        "bank_coverage": bank_coverage,
        "workflow_valid": bool(promotion["passed"]),
        "selection_certified": certification["selection_certified"],
        "allocation_certified": certification["allocation_certified"],
        "errors": promotion.get("errors", []),
    }


def promote_deferred_run(result: MutableMapping[str, Any]) -> Dict[str, Any]:
    """Complete a promotion held back by ``defer_promotion=True``.

    R29(2). Call this only once the run's file is a delivery, which for
    ``late_swap.py`` means after the accept-downgrade decision resolves and the
    mirror to ``outputs/`` has been written. It carries the compare half of
    R20(c)'s compare-and-swap forward from run creation, so a session that
    promoted while this one was deciding still produces a loud refusal rather
    than a lost update.

    ``result`` is updated in place so a caller that already returned it keeps
    one dict as the record. A result that was never deferred is returned
    unchanged, which makes this safe to call unconditionally.
    """
    if not result.get("promotion_deferred"):
        return dict(result)
    promotion = promote_run(
        result["run_dir"],
        expected_pointer_sha256=result.get("pointer_sha_at_create"),
    )
    result["promoted"] = bool(promotion["passed"])
    result["promotion_deferred"] = False
    if not promotion["passed"]:
        # The file stays where it is and stays certified. What failed is the
        # claim that it is the latest delivery, and that is the caller's to
        # report; a refusal here never rewrites the artifact.
        result["errors"] = list(result.get("errors") or []) + list(
            promotion.get("errors") or [])
        result["pointer_conflict"] = bool(promotion.get("pointer_conflict"))
        # `passed` and `workflow_valid` mean the same thing here as on the inline
        # path, where a refused promotion sets both False. A caller that reads
        # the idiomatic `if not result["passed"]` must not read a pointer
        # conflict as success just because this run deferred.
        result["passed"] = False
        result["workflow_valid"] = False
    return dict(result)


def run_initial_build(**kwargs: Any) -> Dict[str, Any]:
    kwargs["mode"] = "initial_build"
    return execute_portfolio(**kwargs)


def _parent_export_sha256(parent: Mapping[str, Any]) -> str:
    for record in (parent.get("manifest", {}).get("artifacts", {}) or {}).values():
        if record.get("role") == "dk_export":
            return str(record.get("sha256") or "")
    return ""


def _assert_parent_lineage(lineage: Mapping[str, Any],
                           allow_parent_mismatch: bool) -> None:
    """R20(c): a swap that does not descend from the promoted export blocks.

    The swap resolves its parent through the latest-run pointer at call time.
    A session that promoted between this file's delivery and this swap makes
    the pointer name a different portfolio, and refining the wrong parent was
    previously recorded in lineage metadata and allowed to proceed. It blocks
    now; ``allow_parent_mismatch=True`` is the reviewed override, and the
    mismatch stays on the record either way.
    """
    if lineage.get("current_matches_parent_export"):
        return
    if allow_parent_mismatch:
        return
    raise ValueError(
        "late swap parent mismatch: the entries file does not hash to the "
        "promoted run's export, so the latest promotion is not the portfolio "
        "this file came from (another session may have promoted since "
        "delivery). Re-resolve the parent, or pass allow_parent_mismatch=True "
        "after reviewing the lineage")


def run_late_swap(
    *,
    runs_root: str | Path,
    current_entries_csv: str | Path,
    status_by_player_id: Mapping[str, PlayerLineupStatus],
    as_of: Any,
    late_swap_mode: str = "reoptimize",
    contest_shapes: Optional[Mapping[str, str]] = None,
    authorized_entry_ids: Optional[Iterable[str]] = None,
    missing_status_policy: str = "error",
    confirmed_order_by_player_id: Optional[Mapping[str, int]] = None,
    starter_player_ids: Optional[Iterable[str]] = None,
    confirmed_teams: Optional[Iterable[str]] = None,
    allow_parent_mismatch: bool = False,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Execute a late swap against the verified latest promoted parent run.

    ``authorized_entry_ids`` restricts mutability to exactly those Entry IDs.
    None means every reserved Entry ID in the file is explicitly authorized.
    ``missing_status_policy='error'`` (default) blocks the swap when any
    rostered player's lock state is unknown; ``'treat_as_locked'`` freezes
    those slots instead. There is no fail-open option.

    When ``confirmed_order_by_player_id`` is provided and ``projections`` is a
    DataFrame, confirmed lineups are refreshed through the shared projection
    builder (spec section 11 step 5) before the joint solve.
    """
    parent = load_latest_valid_parent_run(runs_root)
    parent_id = parent["manifest"]["run_id"]
    parent_export_hash = _parent_export_sha256(parent)
    current_hash = sha256_file(current_entries_csv)
    lineage_metadata = {
        "parent_export_sha256": parent_export_hash,
        "current_entries_sha256": current_hash,
        "current_matches_parent_export": bool(parent_export_hash) and parent_export_hash == current_hash,
    }
    _assert_parent_lineage(lineage_metadata, allow_parent_mismatch)

    requirements = build_entry_requirements(
        current_entries_csv, status_by_player_id, as_of, contest_shapes,
        mode=late_swap_mode,
        authorized_entry_ids=authorized_entry_ids,
        missing_status_policy=missing_status_policy,
    )

    if late_swap_mode == "validate_only":
        run = create_run(
            runs_root, "validate_only", parent_run_id=parent_id,
            metadata={"pipeline_version": VERSION, **lineage_metadata},
        )
        run_dir = Path(run["run_dir"])
        snapshot_run_inputs(run_dir, [current_entries_csv])
        certification = late_swap_certification("validate_only")
        requirements_path = run_dir / "final" / "late_swap_requirements.json"
        _write_json(requirements_path, {
            "run_id": run["run_id"],
            "parent_run_id": parent_id,
            "mode": "validate_only",
            "entry_requirements": requirements,
            **lineage_metadata,
            **certification,
        })
        register_artifact(run_dir, requirements_path, "late_swap_requirements")
        update_run_certification(
            run_dir,
            {"workflow_valid": False,
             "selection_certified": False,
             "allocation_certified": False},
            errors=[], warnings=[], status="diagnostic",
        )
        return {
            "passed": True,
            "run_id": run["run_id"],
            "run_dir": str(run_dir),
            "parent_run_id": parent_id,
            "entry_requirements": requirements,
            "requirements_path": str(requirements_path),
            **lineage_metadata,
            **certification,
        }

    projections = kwargs.get("projections")
    if confirmed_order_by_player_id is not None and isinstance(projections, pd.DataFrame):
        from mlb_engine.projections.projection_builder import refresh_confirmed_lineups
        refreshed, refresh_delta = refresh_confirmed_lineups(
            projections, confirmed_order_by_player_id,
            starter_player_ids=starter_player_ids,
            confirmed_teams=confirmed_teams,
        )
        kwargs["projections"] = refreshed
        kwargs.setdefault("metadata", {})["confirmed_refresh_row_count"] = int(len(refresh_delta))

    kwargs.update({
        "runs_root": runs_root,
        "mode": "late_swap",
        "entries_csv": current_entries_csv,
        "entry_requirements": requirements,
        "parent_run_id": parent_id,
    })
    if confirmed_teams is not None:
        kwargs["confirmed_teams"] = confirmed_teams
    kwargs["metadata"] = {**lineage_metadata, **(kwargs.get("metadata") or {})}
    result = execute_portfolio(**kwargs)
    result.update(late_swap_certification("reoptimize", result))
    result.update(lineage_metadata)
    return result


# ============================================================================
# v1.2 front door: strategy defaults, pre-build checkpoint, run_slate
# ============================================================================
#
# STRATEGY_DEFAULTS are PRINCIPLED PRIORS, not empirically tuned values. There
# is not enough accumulated slate data to calibrate construction numbers, so
# these are starting points keyed on contest posture and are never to be called
# win rates or ROI. Override any field per slate via portfolio_controls_override.

STRATEGY_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "single_entry": {
        "construction": "single",
        "objective": "ceiling",
        "entry_count_policy": "one",
        "stack_plan": "tight_consecutive_1_5",
        "decorrelation": "none",
        "controls": {
            "max_player_exposure_pct": 1.0, "max_pitcher_exposure_pct": 1.0,
            "max_primary_stack_exposure_pct": 1.0, "max_sp_pair_repetition": 1,
        },
        "note": "one max-ceiling lineup; no decorrelation needed at one entry",
    },
    "wta_satellite": {
        "construction": "multi_small",
        "objective": "ceiling",
        "entry_count_policy": "scale_to_bank_coverage",
        "stack_plan": "tight_consecutive_1_5",
        "decorrelation": "moderate",
        # R5, dated decision 2026-07-27, ledger 3.11. Was 0.60 / 0.70 / 0.60 /
        # 2 / 7. These are MLB_Classic section 8's numbers, adopted for the whole
        # posture rather than split into a separate satellite row: at more than
        # one entry a true WTA also wants live independent shots, so the loose
        # half of the old row was defending a case that does not hold. The
        # WTA-versus-cut-line objective difference is carried at the shape level
        # by resolve_contest_shape, not here. SP-pair stays 2, which is tighter
        # than section 8's ~12%-of-entries rule above 16 entries and equal to it
        # below.
        "controls": {
            "max_player_exposure_pct": 0.45, "max_pitcher_exposure_pct": 0.43,
            "max_primary_stack_exposure_pct": 0.35, "max_sp_pair_repetition": 2,
            "max_shared_players": 5,
            # R34, 2026-07-30. Ships at 0.0, which is today's behaviour exactly.
            # The archive (138 contests, 43,045 Classic field entries) shows
            # 5-2-1 is the only shape whose within-contest top-decile lift
            # excludes zero, +3.1pp [+1.2, +5.1], and that we built 0.0% of it
            # against a field at 25.1%. That is an observed outcome and a
            # deterministic descriptive statistic, never a win rate or an ROI
            # claim, and it does not license turning this on by itself. Raise it
            # deliberately per slate via portfolio_controls_override and read
            # the relaxation counts in the brief.
            "min_five_stack_share_pct": 0.0,
            "five_stack_min_size": 5,
        },
        "note": "cut-line and first-place objectives both want independent "
                "shots; section 8 caps, floored up by _slate_feasibility when "
                "a thin slate cannot carry them; five-stack quota off by "
                "default (R34)",
    },
    "small_gpp": {
        "construction": "multi",
        "objective": "ceiling",
        "entry_count_policy": "scale_to_bank_coverage",
        "stack_plan": "tight_4_or_5",
        "decorrelation": "moderate",
        "controls": {
            "max_player_exposure_pct": 0.50, "max_pitcher_exposure_pct": 0.60,
            "max_primary_stack_exposure_pct": 0.55, "max_sp_pair_repetition": 2,
            "max_shared_players": 6,
        },
        "note": "tight consecutive stacks; cover viable SP pairs only on deep slates",
    },
    "large_gpp": {
        "construction": "multi",
        "objective": "ceiling",
        "entry_count_policy": "scale_to_bank_coverage",
        "stack_plan": "tight_5_plus_secondary",
        "decorrelation": "high",
        "controls": {
            "max_player_exposure_pct": 0.40, "max_pitcher_exposure_pct": 0.55,
            "max_primary_stack_exposure_pct": 0.50, "max_sp_pair_repetition": 3,
            "max_shared_players": 6,
        },
        "note": "top-heavy field rewards a tight five-stack plus a secondary",
    },
    "mme": {
        "construction": "multi_wide",
        "objective": "ceiling",
        "entry_count_policy": "scale_to_bank_coverage",
        "stack_plan": "five_three_with_diversification",
        "decorrelation": "high",
        "controls": {
            "max_player_exposure_pct": 0.35, "max_pitcher_exposure_pct": 0.50,
            "max_primary_stack_exposure_pct": 0.45, "max_sp_pair_repetition": 3,
            "max_shared_players": 6,
        },
        "note": "wider exposure and higher decorrelation; deployed count scales with bank coverage",
    },
    "cash": {
        "construction": "not_recommended",
        "objective": "floor",
        "entry_count_policy": "none",
        "stack_plan": "none",
        "decorrelation": "none",
        "controls": {},
        "note": "cash and double-up are a weak architectural fit for this engine; flag and confirm before building",
    },
}

# DK MLB Classic roster-slot tokens the optimizer expects.
_DK_POSITION_MAP = {
    "SP": "P", "RP": "P", "P": "P",
    "LF": "OF", "CF": "OF", "RF": "OF", "OF": "OF",
    "C": "C", "1B": "1B", "2B": "2B", "3B": "3B", "SS": "SS",
}


def _coerce_dk_positions(position: Any) -> str:
    """Coerce a salary-file position string to DK slot tokens (SP/RP->P, LF/CF/RF->OF)."""
    tokens = [t.strip().upper() for t in str(position or "").split("/") if t.strip()]
    out: list[str] = []
    for token in tokens:
        out.append(_DK_POSITION_MAP.get(token, token))
    seen: list[str] = []
    for token in out:
        if token not in seen:
            seen.append(token)
    return "/".join(seen)


def normalize_posture(
    inferred_type: Optional[str],
    payout_shape_default: Optional[str] = None,
    max_entries: Optional[int] = None,
) -> str:
    """Map an inferred contest archetype to a STRATEGY_DEFAULTS posture key."""
    itype = str(inferred_type or "").strip().lower()
    shape = str(payout_shape_default or "").strip().lower()
    if itype == "cash" or shape == "flat_cash":
        return "cash"
    if itype in ("wta", "satellite") or shape in ("winner_take_all", "ticket_line"):
        return "wta_satellite"
    if itype == "se_gpp" or shape == "single_entry_gpp" or max_entries == 1:
        return "single_entry"
    if shape == "mme_top_heavy" or (max_entries is not None and max_entries >= 100):
        return "mme"
    if shape in ("limited_entry_gpp",) or (max_entries is not None and max_entries <= 20):
        return "small_gpp"
    if shape == "broad_micro_gpp":
        return "large_gpp"
    return "large_gpp"


def _resolve_contest_postures(
    entry_rows: Sequence[Any],
    contest_postures: Optional[Mapping[str, Any]],
    archetypes_path: Optional[str],
) -> Dict[str, Dict[str, Any]]:
    """Resolve a posture and contest shape for each distinct contest in the entries file."""
    from mlb_engine.entries.dk_entries_manager import infer_contest_archetype, load_archetypes

    archetypes = load_archetypes(archetypes_path)
    postures = dict(contest_postures or {})
    resolved: Dict[str, Dict[str, Any]] = {}
    for row in entry_rows:
        cid = str(getattr(row, "contest_id", "") or "")
        cname = str(getattr(row, "contest_name", "") or "")
        fee = float(getattr(row, "entry_fee", 0.0) or 0.0)
        if cid in resolved:
            continue
        override = postures.get(cid) if cid in postures else postures.get(cname)
        if isinstance(override, str):
            posture = override
            inferred = {"inferred_type": override, "payout_shape_default": None, "inferred_max_entries": None}
            source = "operator_supplied"
        elif isinstance(override, Mapping):
            inferred = dict(override)
            posture = str(inferred.get("posture") or normalize_posture(
                inferred.get("inferred_type"), inferred.get("payout_shape_default"),
                inferred.get("inferred_max_entries"),
            ))
            source = "operator_supplied"
        else:
            inferred = infer_contest_archetype(cname, fee, archetypes)
            posture = normalize_posture(
                inferred.get("inferred_type"), inferred.get("payout_shape_default"),
                inferred.get("inferred_max_entries"),
            )
            source = ("name_inference"
                      if inferred.get("inferred_type") not in (None, "", "unknown")
                      else "unresolved")
        shape = resolve_contest_shape(posture, inferred)
        resolved[cid] = {
            "contest_id": cid, "contest_name": cname, "posture": posture,
            "contest_shape": shape, "inferred": inferred,
            # Where this posture came from. The build is entitled to route a
            # contest on a labelled prior; it is not entitled to route one
            # silently, and the difference between "the operator said cash" and
            # "the name matched nothing so it fell through to large_gpp" is the
            # whole of F3.
            "posture_source": source,
            "matched_pattern": inferred.get("matched_pattern"),
            "competing_patterns": list(inferred.get("competing_patterns") or []),
        }
    return resolved


PRE_EXPORT_GATE_NAMES = (
    "salary_gate_passed", "entry_grid_gate_passed", "lineup_gate_passed",
    "pitcher_audit_gate_passed", "weather_gate_passed", "odds_gate_passed",
)


def _applied(block: Any) -> Optional[bool]:
    """True when an enrichment map reached rows, False when it reached none.

    None when no map was requested at all: a build that was never given odds is
    a different state from a build given odds that matched nothing, and only the
    second is a failure.
    """
    if not isinstance(block, Mapping):
        return None
    requested = int(block.get("requested") or 0)
    if requested <= 0:
        return None
    return int(block.get("applied_count") or 0) > 0


def _derive_workflow_gates(
    *,
    schema: Mapping[str, Any],
    entry_requirements: Sequence[Mapping[str, Any]],
    posture_by_contest: Mapping[str, Mapping[str, Any]],
    projected_order: Mapping[str, Any],
    pitcher_roles: Optional[Mapping[str, str]],
    projection_enrichment: Mapping[str, Any],
    pool_report: Optional[Mapping[str, Any]] = None,
) -> Tuple[Dict[str, Optional[bool]], Dict[str, str]]:
    """Derive the six pre-export gates from evidence already on hand.

    A gate is True only when something checkable says so, False when something
    checkable says otherwise, and None when nothing does. None is not a pass:
    ``validate_upload_ready_gates`` reports it as a missing gate and blocks. The
    caller can assume any of them explicitly via ``assume_gates``, which is
    recorded, and that is the only way one of these reaches True unchecked.
    """
    gates: Dict[str, Optional[bool]] = {}
    why: Dict[str, str] = {}

    gates["salary_gate_passed"] = bool(schema.get("passed"))
    why["salary_gate_passed"] = f"salary CSV schema validation: {schema.get('summary')}"

    reserved = list(entry_requirements or [])
    grid_ok = bool(reserved) and all(
        str(r.get("contest_id") or "").strip() for r in reserved
    )
    gates["entry_grid_gate_passed"] = grid_ok
    why["entry_grid_gate_passed"] = (
        f"{len(reserved)} reserved entries parsed across "
        f"{len(posture_by_contest)} contests, every row carrying a contest id"
        if grid_ok else
        f"{len(reserved)} reserved entries parsed; the grid is empty or a row "
        f"carries no contest id"
    )

    report = dict(pool_report or {})
    if report:
        thin = sorted(
            team for team, rec in (report.get("teams") or {}).items()
            if str(rec.get("status")) not in ("excluded_postponed", "excluded_no_order_data")
            and int(rec.get("hitters") or 0) < 9
        )
        gates["lineup_gate_passed"] = not report.get("blockers") and not thin
        why["lineup_gate_passed"] = (
            f"pool report: {len(report.get('blockers') or [])} blockers, "
            f"{len(thin)} team(s) under nine hitters"
            + (f" ({', '.join(thin)})" if thin else "")
        )
    elif projected_order:
        gates["lineup_gate_passed"] = True
        why["lineup_gate_passed"] = (
            f"{len(projected_order)} players carry a batting order; no pool "
            f"report was supplied, so team completeness is unverified"
        )
    else:
        gates["lineup_gate_passed"] = None
        why["lineup_gate_passed"] = (
            "no pool report and no batting orders; nothing states that the "
            "lineups behind this build were reviewed"
        )

    roles = dict(pitcher_roles or {})
    if roles:
        bad = sorted(pid for pid, role in roles.items()
                     if str(role) not in ALLOWED_PITCHER_ROLES_FOR_GATE)
        gates["pitcher_audit_gate_passed"] = not bad
        why["pitcher_audit_gate_passed"] = (
            f"{len(roles)} declared arms, all in the allowed role set"
            if not bad else f"arms with a role outside the allowed set: {bad}"
        )
    else:
        gates["pitcher_audit_gate_passed"] = None
        why["pitcher_audit_gate_passed"] = (
            "no pitcher_roles supplied; nothing states which arms were audited")

    enrichment = dict(projection_enrichment or {})
    gates["weather_gate_passed"] = _applied(enrichment.get("f5"))
    why["weather_gate_passed"] = _enrichment_note("F5 park/weather", enrichment.get("f5"))
    gates["odds_gate_passed"] = _applied(enrichment.get("f1"))
    why["odds_gate_passed"] = _enrichment_note("F1 implied team total", enrichment.get("f1"))
    return gates, why


ALLOWED_PITCHER_ROLES_FOR_GATE = frozenset(
    {"verified_starter", "declared_probable_sp", "viable_bulk_or_alt_sp"})


def _enrichment_note(label: str, block: Any) -> str:
    if not isinstance(block, Mapping) or int(block.get("requested") or 0) <= 0:
        return f"{label}: no map supplied for this build"
    return (f"{label}: {block.get('applied_count')} of {block.get('requested')} "
            f"requested rows enriched")


def unresolved_contest_blockers(resolved: Mapping[str, Mapping[str, Any]]) -> List[str]:
    """One blocker per reserved contest whose identity nothing established.

    ``normalize_posture`` ends in an unconditional ``return "large_gpp"``, so an
    unrecognised name does not fail, it becomes a large-field GPP build. On a
    portfolio that is almost entirely satellites and qualifiers that is the
    wrong objective, applied invisibly. Route it or name it.
    """
    out: List[str] = []
    for cid, rec in sorted(resolved.items()):
        if rec.get("posture_source") != "unresolved":
            continue
        out.append(
            f"contest {cid} '{rec.get('contest_name')}' matched no archetype; "
            f"it would build as {rec.get('posture')} by fallback, not by "
            f"identification. Supply the real posture via contest_postures "
            f"(build_slate.py --postures {cid}=<posture>) or add the pattern to "
            f"data/reference/dk_contest_archetypes.csv."
        )
    return out


_POSTURE_TO_SHAPE = {
    "single_entry": "single_entry_gpp",
    "wta_satellite": "large_wta",
    "small_gpp": "small_field_gpp",
    "large_gpp": "large_field_gpp",
    # R1a: was "mme_top_heavy", which is a payout_shape_default token and not a
    # profile key, so resolve_contest_shape_profile raised on it and every
    # 150-Max contest died on the direct path. The MME profile is "mme_gpp".
    "mme": "mme_gpp",
    "cash": "cash",
}
_POSTURE_TO_SHAPE_FALLBACK = "large_field_gpp"

# Validated at import, so a mapping entry that invents a shape name fails on
# load rather than on the single contest that routes to it.
for _shape in list(_POSTURE_TO_SHAPE.values()) + [_POSTURE_TO_SHAPE_FALLBACK]:
    validate_shape(_shape, "execution_pipeline._POSTURE_TO_SHAPE")
del _shape


def _posture_to_shape(posture: str) -> str:
    return _POSTURE_TO_SHAPE.get(posture, _POSTURE_TO_SHAPE_FALLBACK)


def resolve_contest_shape(posture: str, inferred: Optional[Mapping[str, Any]] = None) -> str:
    """Resolve the shape a contest's candidates are RANKED for.

    R1a. The posture is a caps key and it is lossy: ``wta_satellite`` covers a
    winner-take-all and a multi-ticket qualifier, which are different objectives.
    Routing through the posture alone flattened every satellite to ``large_wta``,
    a pure-ceiling profile, on a portfolio that is almost entirely satellites and
    qualifiers. The contest's own identity is on hand in ``inferred``, so use it.

    An explicit ``contest_shape`` in ``inferred`` still wins: an operator who
    names the shape has said something the inference cannot.

    The posture is deliberately NOT split here. Adding a ``satellite`` posture
    means adding a caps row, and the caps divergence between STRATEGY_DEFAULTS
    and MLB_Classic section 8 is an open dated decision (backlog R5). This
    changes what candidates are ranked for and changes no cap.
    """
    info = dict(inferred or {})
    explicit = str(info.get("contest_shape") or "").strip().lower()
    if explicit:
        return validate_shape(explicit, "contest_shape override")

    itype = str(info.get("inferred_type") or "").strip().lower()
    payout = str(info.get("payout_shape_default") or "").strip().lower()
    if itype in SATELLITE_TYPE_TOKENS or payout in SATELLITE_PAYOUT_TOKENS:
        return satellite_shape_for(info.get("ticket_count"))
    return _posture_to_shape(posture)


# ----------------------------------------------------------------------------
# v1.3: game-script fill-depth planning. Deterministic review proxies that size
# per-contest game-script coverage from entry count and payout breadth, so the
# marginal lineup in a high-volume contest can be routed to a new game script (a
# deliberate contrarian play) rather than another permutation of the chalk. None
# of these are win-rate, ROI, or expected-value claims; they are construction
# priors and are surfaced for human review at the checkpoint.
# ----------------------------------------------------------------------------

# Fraction of a contest field that wins a prize-equivalent. Higher = broader
# payout (many independent winners), which rewards spreading lineups across game
# scripts. Lower = top-heavy (one or few winners), which rewards concentrating on
# the highest-ceiling script. Priors; tunable via the payout_breadth column in
# dk_contest_archetypes.csv.
PAYOUT_BREADTH_BY_SHAPE: Dict[str, float] = {
    "winner_take_all": 0.002,
    "single_entry_gpp": 0.01,
    "mme_top_heavy": 0.02,
    "large_field_gpp": 0.12,
    "limited_entry_gpp": 0.10,
    "small_field_gpp": 0.18,
    "broad_micro_gpp": 0.15,
    "portfolio_gpp": 0.15,
    "ticket_line": 0.22,
    "large_wta": 0.02,
    "cash": 0.45,
    "flat_cash": 0.45,
    # R1a: the fallback leg of _resolve_payout_breadth reads a contest_shape, so
    # every canonical shape needs a row or a satellite silently takes the
    # 0.12 global default instead of a satellite's breadth. Values mirror the
    # payout_shape_default token each shape corresponds to: satellite is a cut
    # line (ticket_line 0.22), a one-ticket satellite pays one spot
    # (winner_take_all 0.002), mme_gpp is the mme_top_heavy row.
    "satellite": 0.22,
    "wta_ticket_satellite": 0.002,
    "small_wta": 0.002,
    "mid_wta": 0.002,
    "mme_gpp": 0.02,
    "mid_field_gpp": 0.15,
    "ticket_satellite": 0.22,
}
_DEFAULT_PAYOUT_BREADTH = 0.12
_PRIMARY_CEILING_RATIO = 0.75   # scripts within this ratio of the top are "primary"
_MAX_PRIMARY_SCRIPTS = 2


def _payout_breadth_by_shape_from_csv(archetypes_path: Optional[str]) -> Dict[str, float]:
    """Read the optional payout_breadth column from the archetype CSV, aggregated
    by payout_shape_default. Falls back to the in-code priors for any shape absent
    from the file, and when no file is supplied."""
    breadth = dict(PAYOUT_BREADTH_BY_SHAPE)
    if not archetypes_path:
        return breadth
    try:
        import csv as _csv
        p = Path(archetypes_path)
        if not p.exists():
            return breadth
        with p.open(newline="", encoding="utf-8-sig") as fh:
            for row in _csv.DictReader(fh):
                shape = str(row.get("payout_shape_default") or "").strip()
                raw = row.get("payout_breadth")
                if shape and raw not in (None, ""):
                    try:
                        breadth[shape] = float(raw)
                    except (TypeError, ValueError):
                        continue
    except Exception:
        return dict(PAYOUT_BREADTH_BY_SHAPE)
    return breadth


def _resolve_payout_breadth(posture_info: Mapping[str, Any], breadth_by_shape: Mapping[str, float]) -> float:
    """Resolve a contest's payout breadth from its inferred payout_shape_default,
    falling back to its contest_shape and then a global default."""
    shape = str((posture_info.get("inferred") or {}).get("payout_shape_default") or "").strip()
    if shape in breadth_by_shape:
        return float(breadth_by_shape[shape])
    cshape = str(posture_info.get("contest_shape") or "").strip()
    if cshape in breadth_by_shape:
        return float(breadth_by_shape[cshape])
    return float(_DEFAULT_PAYOUT_BREADTH)


def _script_saturation(payout_breadth: float, posture: str = "") -> int:
    """Lineups one game script can productively absorb in a contest before the
    marginal correlated lineup adds little. Inverse to payout breadth: broad
    multi-winner payouts spread across scripts (low saturation -> deeper fill);
    top-heavy single-winner payouts concentrate (high saturation -> shallow fill).
    Cash is special-cased to a high value: it wants one repeated high-floor build,
    not script spread."""
    if posture == "cash":
        return 9
    b = max(0.0, min(float(payout_breadth), 0.25))
    s = round(8.0 - 5.0 * (b / 0.25))
    return int(max(3, min(8, s)))


def rank_game_scripts(projections: Any) -> List[Dict[str, Any]]:
    """Rank team stacks by top-5 hitter ceiling (the stacking unit), descending.
    Returns a list of {script, game, stack_ceiling, ceiling_ratio}. Pitchers are
    excluded from a stack's ceiling. Defensive: returns [] when the frame lacks a
    usable team or ceiling column."""
    try:
        if not hasattr(projections, "columns"):
            return []
        cols = set(projections.columns)
        team_col = next((c for c in ("Stack_Group", "TeamAbbrev", "Team") if c in cols), None)
        ceil_col = "Ceiling" if "Ceiling" in cols else None
        if team_col is None or ceil_col is None:
            return []
        pos_col = next((c for c in ("Position", "Assigned_Position", "Roster_Position") if c in cols), None)
        game_col = next((c for c in ("Game_ID", "GameId", "Game") if c in cols), None)
        ceilings: Dict[str, list] = {}
        games: Dict[str, str] = {}
        for _, r in projections.iterrows():
            team = str(r.get(team_col) or "").strip()
            if not team:
                continue
            if pos_col is not None:
                toks = {t.strip().upper() for t in str(r.get(pos_col) or "").split("/")}
                if toks & {"P", "SP", "RP"}:
                    continue
            try:
                c = float(r.get(ceil_col))
            except (TypeError, ValueError):
                continue
            ceilings.setdefault(team, []).append(c)
            if game_col is not None and team not in games:
                g = str(r.get(game_col) or "").strip()
                if g:
                    games[team] = g
        ranked: List[Dict[str, Any]] = []
        for team, vals in ceilings.items():
            top5 = sum(sorted(vals, reverse=True)[:5])
            ranked.append({"script": team, "game": games.get(team, ""), "stack_ceiling": round(top5, 2)})
        ranked.sort(key=lambda d: d["stack_ceiling"], reverse=True)
        top = ranked[0]["stack_ceiling"] if ranked else 0.0
        for d in ranked:
            d["ceiling_ratio"] = round(d["stack_ceiling"] / top, 3) if top else 0.0
        return ranked
    except Exception:
        return []


def compute_contest_fill_depth(
    n_entries: int,
    payout_breadth: float,
    posture: str = "",
    n_viable_scripts: Optional[int] = None,
) -> Dict[str, Any]:
    """How many distinct game scripts a contest's entries should cover. Review
    proxy: ceil(entries / per-script saturation), capped by the entry count and by
    the number of viable scripts. Single-entry -> 1. High-volume broad-payout ->
    deep (the case where a lower-ceiling contrarian lineup earns a slot)."""
    n = max(0, int(n_entries))
    S = _script_saturation(payout_breadth, posture)
    if n <= 0:
        depth = 0
    else:
        import math as _math
        depth = max(1, _math.ceil(n / S))
        depth = min(depth, n)
    if n_viable_scripts is not None and n > 0:
        depth = min(depth, max(1, int(n_viable_scripts)))
    return {
        "entry_count": n,
        "payout_breadth": round(float(payout_breadth), 4),
        "lineups_per_script_prior": S,
        "fill_depth": int(depth),
    }


def build_fill_depth_plan(
    contest_rows: Sequence[Mapping[str, Any]],
    posture_by_contest: Mapping[str, Mapping[str, Any]],
    game_script_ranking: Optional[Sequence[Mapping[str, Any]]] = None,
    scanner_flagged_games: Optional[Sequence[str]] = None,
    archetypes_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Per-contest fill-depth determination: how many game scripts to cover and
    how many of those slots are contrarian (below the primary ceiling tier). This
    is the engine making the call that previously required a manual prompt: in a
    high-volume contest the deeper slots fall to lower-ceiling scripts, so a
    contrarian lineup is warranted. Deterministic review proxy; never a win-rate,
    ROI, or EV claim."""
    breadth_by_shape = _payout_breadth_by_shape_from_csv(archetypes_path)
    ranking = [dict(d) for d in (game_script_ranking or [])]
    n_viable = len(ranking) or None
    flagged_raw = [str(g).strip().upper() for g in (scanner_flagged_games or []) if str(g).strip()]
    top_ceiling = ranking[0]["stack_ceiling"] if ranking else 0.0
    primary_scripts: List[str] = []
    for d in ranking:
        if len(primary_scripts) >= _MAX_PRIMARY_SCRIPTS:
            break
        if top_ceiling and d.get("stack_ceiling", 0.0) >= _PRIMARY_CEILING_RATIO * top_ceiling:
            primary_scripts.append(d["script"])
    if not primary_scripts and ranking:
        primary_scripts = [ranking[0]["script"]]
    primary_set = set(primary_scripts)

    def _is_flagged(entry: Mapping[str, Any]) -> bool:
        team = str(entry.get("script") or "").strip().upper()
        game = str(entry.get("game") or "").strip().upper()
        if not flagged_raw:
            return False
        if game and game in flagged_raw:
            return True
        return any(team and team in g for g in flagged_raw)

    contests: List[Dict[str, Any]] = []
    for cid, info in posture_by_contest.items():
        posture = info.get("posture", "")
        n_entries = sum(1 for r in contest_rows if str(r.get("contest_id") or "") == cid)
        breadth = _resolve_payout_breadth(info, breadth_by_shape)
        depth_info = compute_contest_fill_depth(n_entries, breadth, posture, n_viable)
        depth = depth_info["fill_depth"]
        covered_entries = ranking[:depth] if ranking else []
        covered_primary = [d["script"] for d in covered_entries if d["script"] in primary_set]
        contrarian_entries = [d for d in covered_entries if d["script"] not in primary_set]
        contrarian_scripts = [d["script"] for d in contrarian_entries]
        flagged_contrarian = [d["script"] for d in contrarian_entries if _is_flagged(d)]
        contests.append({
            "contest_id": cid,
            "contest_name": info.get("contest_name", ""),
            "posture": posture,
            "entry_count": n_entries,
            "payout_breadth": depth_info["payout_breadth"],
            "lineups_per_script_prior": depth_info["lineups_per_script_prior"],
            "fill_depth": depth,
            "primary_scripts_covered": covered_primary,
            "contrarian_slots": len(contrarian_scripts),
            "contrarian_scripts_recommended": contrarian_scripts,
            "scanner_flagged_contrarian_scripts": flagged_contrarian,
        })
    return {
        "label": "FILL-DEPTH PLAN — review proxy; per-contest game-script coverage from entry count and payout breadth",
        "calibrated": False,
        "is_review_proxy": True,
        "primary_ceiling_ratio_threshold": _PRIMARY_CEILING_RATIO,
        "primary_scripts": primary_scripts,
        "game_script_ranking": ranking,
        "contests": contests,
    }


def _candidate_id(c: Mapping[str, Any], idx: int) -> str:
    return str(c.get("candidate_id") or c.get("lineup_id") or f"L{idx + 1:03d}")


def _candidate_primary_stack_label(c: Mapping[str, Any]) -> str:
    fit = c.get("contest_fit") if isinstance(c.get("contest_fit"), Mapping) else {}
    return str(c.get("primary_stack") or (fit or {}).get("primary_stack") or "").strip()


def _candidate_objective(c: Mapping[str, Any]) -> float:
    fit = c.get("contest_fit") if isinstance(c.get("contest_fit"), Mapping) else {}
    for key in ("objective", "ceiling", "ceiling_sum"):
        v = c.get(key)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
    v = (fit or {}).get("contest_fit_score")
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def emit_contest_routing(
    fill_depth_plan: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
    entry_requirements: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Translate a fill-depth plan into per-entry allowed_candidate_ids that route
    the highest-ceiling lineup to a single-entry contest and reserve covered
    (primary + contrarian) scripts for higher-volume contests. This automates the
    ceiling-to-prize hand-routing the allocator will not do on its own, because it
    normalizes ceiling per entry and weights entries equally. Deterministic; falls
    back to NO restriction for any contest where it would orphan an entry."""
    objs: Dict[str, float] = {}
    stacks: Dict[str, str] = {}
    for i, c in enumerate(candidates):
        cid = _candidate_id(c, i)
        objs[cid] = _candidate_objective(c)
        stacks[cid] = _candidate_primary_stack_label(c)
    top_id = max(objs, key=objs.get) if objs else None
    plan_by_contest = {str(c.get("contest_id")): c for c in fill_depth_plan.get("contests", [])}
    by_contest: Dict[str, list] = {}
    for req in entry_requirements:
        by_contest.setdefault(str(req.get("contest_id") or ""), []).append(req)
    routing: Dict[str, list] = {}
    warnings: List[str] = []
    for cid, reqs in by_contest.items():
        plan = plan_by_contest.get(cid)
        if not plan:
            continue
        posture = plan.get("posture", "")
        if posture == "single_entry" and top_id is not None:
            allowed = [top_id]
        else:
            covered = set(plan.get("primary_scripts_covered", [])) | set(plan.get("contrarian_scripts_recommended", []))
            if not covered:
                continue
            allowed = [cid_ for cid_, s in stacks.items() if s and s in covered]
        if len(allowed) < len(reqs):
            warnings.append(
                f"routing skipped for contest {cid}: {len(allowed)} eligible candidates < {len(reqs)} entries"
            )
            continue
        for req in reqs:
            routing[str(req.get("entry_id"))] = list(allowed)
    return {"allowed_candidate_ids_by_entry": routing, "warnings": warnings}


def compute_game_script_coverage(projections: Any, candidates: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """How many distinct game scripts (team stacks) the candidate set covers
    relative to the viable scripts on the slate. A composition governor for the
    marginal lineup: low coverage means add a new script, not another chalk
    permutation. Derives a candidate's stack from its roster when the candidate
    lacks a primary_stack label. Review proxy, never a win-rate claim; wrapped so
    it never raises."""
    try:
        ranking = rank_game_scripts(projections)
        viable = [d["script"] for d in ranking]
        team_by_player: Dict[str, str] = {}
        pitcher_ids: set = set()
        if hasattr(projections, "columns"):
            cols = set(projections.columns)
            team_col = next((c for c in ("Stack_Group", "TeamAbbrev", "Team") if c in cols), None)
            pos_col = next((c for c in ("Position", "Assigned_Position", "Roster_Position") if c in cols), None)
            if team_col is not None and "Player_ID" in cols:
                for _, r in projections.iterrows():
                    pid = str(r.get("Player_ID") or "").strip()
                    if not pid:
                        continue
                    team_by_player[pid] = str(r.get(team_col) or "").strip()
                    if pos_col is not None:
                        toks = {t.strip().upper() for t in str(r.get(pos_col) or "").split("/")}
                        if toks & {"P", "SP", "RP"}:
                            pitcher_ids.add(pid)
        covered: List[str] = []
        for i, c in enumerate(candidates):
            label = _candidate_primary_stack_label(c)
            if not label and team_by_player:
                tally: Dict[str, int] = {}
                for pid in (c.get("player_ids") or []):
                    spid = str(pid).strip()
                    if spid in pitcher_ids:
                        continue
                    team = team_by_player.get(spid, "")
                    if team:
                        tally[team] = tally.get(team, 0) + 1
                if tally:
                    label = max(sorted(tally), key=tally.get)
            if label and label not in covered:
                covered.append(label)
        return {
            "scripts_covered": covered,
            "n_scripts_covered": len(covered),
            "n_viable_scripts": len(viable),
            "uncovered_viable_scripts": [s for s in viable if s not in covered],
            "is_review_proxy": True,
        }
    except Exception:
        return {}


def build_checkpoint_plan(
    contest_rows: Sequence[Mapping[str, Any]],
    posture_by_contest: Mapping[str, Mapping[str, Any]],
    bank_coverage: Optional[Mapping[str, Any]] = None,
    projections: Any = None,
    scanner_flagged_games: Optional[Sequence[str]] = None,
    archetypes_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Build the one-screen pre-build plan for human approval. Review proxy only."""
    counts: Dict[str, int] = {}
    contests: list[Dict[str, Any]] = []
    warnings: list[str] = []
    for cid, info in posture_by_contest.items():
        posture = info["posture"]
        n_entries = sum(1 for r in contest_rows if str(r.get("contest_id") or "") == cid)
        counts[cid] = n_entries
        default = STRATEGY_DEFAULTS.get(posture, STRATEGY_DEFAULTS["large_gpp"])
        if posture == "cash":
            warnings.append(f"contest {cid} ({info['contest_name']}) is cash/double-up: weak fit, confirm before building")
        contests.append({
            "contest_id": cid,
            "contest_name": info["contest_name"],
            "posture": posture,
            "contest_shape": info["contest_shape"],
            "construction": default["construction"],
            "objective": default["objective"],
            "stack_plan": default["stack_plan"],
            "decorrelation": default["decorrelation"],
            "entry_count": n_entries,
            "entry_count_policy": default["entry_count_policy"],
            "exposure_caps": dict(default["controls"]),
            "note": default["note"],
        })
    total_entries = sum(counts.values())
    postures_present = sorted({c["posture"] for c in contests})
    dominant = max(counts, key=counts.get) if counts else None
    dominant_posture = posture_by_contest.get(dominant, {}).get("posture") if dominant else None
    fill_depth_plan = None
    try:
        ranking = rank_game_scripts(projections) if projections is not None else []
        fill_depth_plan = build_fill_depth_plan(
            contest_rows, posture_by_contest, game_script_ranking=ranking,
            scanner_flagged_games=scanner_flagged_games, archetypes_path=archetypes_path,
        )
    except Exception:
        fill_depth_plan = None
    contested = contested_slot_audit(projections) if projections is not None else {
        "contested_slots": [], "top_n": 14, "is_review_proxy": True}
    if contested.get("contested_slots"):
        crowded = ", ".join(
            f"{c.get('displaceable_name')} ({c.get('slot')})" for c in contested["contested_slots"])
        warnings.append(
            "contested high-ceiling slots, build positional-variant coverage or they enter zero "
            "candidates: " + crowded)
    return {
        "label": "PRE-BUILD CHECKPOINT — review proxy; approve before the expensive build",
        "calibrated": False,
        "defaults_are_priors": True,
        "total_entries": total_entries,
        "distinct_contests": len(contests),
        "postures_present": postures_present,
        "dominant_posture": dominant_posture,
        "pitcher_spread": (
            "single thin-slate ace: do not donate seats to weak SP pairs"
            if dominant_posture in ("wta_satellite", "single_entry")
            else "cover viable SP pairs in proportion to slate depth"
        ),
        "contests": contests,
        "bank_coverage": dict(bank_coverage) if bank_coverage else None,
        "fill_depth_plan": fill_depth_plan,
        "contested_slot_audit": contested,
        "warnings": warnings,
    }


# --- v1.10 waterfall (posture_allocator) checkpoint integration --------------
# The waterfall/tier policy lives in mlb_engine.allocate.posture_allocator, a
# REVIEW-ONLY companion deliberately OUTSIDE the audited engine (ledger 3.9).
# run_slate consumes its already-computed result as inert data: it never imports
# or runs the allocator, and nothing here auto-applies to the certified build.
# The derived coverage target is a DETERMINISTIC review input that, when a waterfall
# is supplied, drives build_diverse_candidate_bank's coverage_target on approve=True
# (the auto-bank path); with no waterfall the bank call is unchanged. None of these
# values is a win-rate, cash-rate, ROI, or probability claim, and nothing auto-applies
# without the operator approving the checkpoint that displays it.

_WATERFALL_LABEL = (
    "bankroll policy priors and deterministic shape classification; "
    "not win rate, cash rate, ROI, or probability; review-only, nothing auto-applies"
)


def _tier_entry_counts(
    waterfall: Mapping[str, Any],
    entry_requirements: Sequence[Mapping[str, Any]],
) -> Dict[str, int]:
    """Entries per tier, joining allocator rows (contest_id -> tier) to reserved entries."""
    tier_by_contest = {
        str(r.get("contest_id")): str(r.get("tier"))
        for r in (waterfall.get("rows") or [])
        if r.get("contest_id")
    }
    counts: Dict[str, int] = {}
    for req in entry_requirements:
        tier = tier_by_contest.get(str(req.get("contest_id") or ""))
        if tier is None:
            continue
        counts[tier] = counts.get(tier, 0) + 1
    return counts


def derive_coverage_target(
    waterfall: Mapping[str, Any],
    entry_requirements: Sequence[Mapping[str, Any]],
    feasibility_inputs: Optional[Mapping[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Map the tiers present + entry counts + slate SP-pair capacity to a single
    candidate-bank coverage target and SP-pair-spread demand.

    Tier A wants a distinct decorrelated lineup per entry with SP-pair spread scaled
    to entries (ledger 3.5); Tier F tolerates a shared chalk core (a primary plus one
    variant); Tier V takes distinct near-best lineups under the concentration rule.
    One slate builds one bank, so the effective target is the demand summed across
    resolved tiers, floored to the Tier A SP-pair spread.

    Deterministic review input shown in the approve=False checkpoint; on approve=True
    with a waterfall supplied it drives build_diverse_candidate_bank's coverage_target
    (auto-bank path). Never a probability claim. Returns None when no tier can be
    resolved (no menu, or every matched contest is UNRESOLVED)."""
    counts = _tier_entry_counts(waterfall, entry_requirements)
    a = counts.get("A", 0)
    f = counts.get("F", 0)
    v = counts.get("V", 0)
    if a + f + v <= 0:
        return None
    viable_pairs = None
    if feasibility_inputs and feasibility_inputs.get("available"):
        viable_pairs = feasibility_inputs.get("viable_sp_pairs")

    notes: list[str] = []
    sp_pair_spread_demand: Optional[int] = None
    a_distinct = a
    if a:
        if viable_pairs:
            sp_pair_spread_demand = max(min(a, int(viable_pairs)), min(3, int(viable_pairs)))
        else:
            sp_pair_spread_demand = max(a, 3)
        a_distinct = max(a, sp_pair_spread_demand)
        notes.append(
            f"Tier A ({a} entries): {a_distinct} distinct decorrelated lineups spanning "
            f"{sp_pair_spread_demand} SP pairs (ledger 3.5); structural duplication screen "
            f"(exact-set dedup + SP breadth) on every candidate")
    f_distinct = min(f, 2) if f else 0
    if f:
        notes.append(
            f"Tier F ({f} entries): {f_distinct} top-script highest-median core(s); shared "
            f"chalk core tolerated, no forced SP-pair spread")
    v_distinct = v
    if v:
        notes.append(
            f"Tier V ({v} entries): up to {v_distinct} distinct near-best lineups under the "
            f"concentration rule")

    coverage_target = max(a_distinct + f_distinct + v_distinct, sp_pair_spread_demand or 0, 1)
    return {
        "coverage_target": int(coverage_target),
        "sp_pair_spread_demand": sp_pair_spread_demand,
        "tier_entry_counts": dict(counts),
        "resolved_entry_count": a + f + v,
        "total_entry_count": len(list(entry_requirements)),
        "viable_sp_pairs": (int(viable_pairs) if viable_pairs is not None else None),
        "applies": True,
        "notes": notes,
        "label": "deterministic review input; drives candidate-bank coverage_target on "
                 "approve=True (auto-bank path), shown here for review before it applies",
    }


def build_waterfall_block(
    waterfall: Optional[Mapping[str, Any]],
    entry_requirements: Sequence[Mapping[str, Any]],
    feasibility_inputs: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Render posture_allocator output as a first-class checkpoint block plus a
    display-only coverage target. Review proxy; nothing auto-applies."""
    if not waterfall:
        return {
            "available": False,
            "label": _WATERFALL_LABEL,
            "note": "no waterfall/contest menu supplied; tier policy unavailable, "
                    "checkpoint uses posture defaults. Supply a contest menu (paid_places "
                    "and field_size per contest) to enable tier policy.",
        }
    counts = _tier_entry_counts(waterfall, entry_requirements)
    unresolved = counts.get("UNRESOLVED", 0)
    coverage = derive_coverage_target(waterfall, entry_requirements, feasibility_inputs)
    return {
        "available": True,
        "label": waterfall.get("label") or _WATERFALL_LABEL,
        "allocator_version": waterfall.get("version"),
        "tiers": [
            {
                "contest_id": r.get("contest_id"), "name": r.get("name"),
                "tier": r.get("tier"), "breadth": r.get("breadth"),
                "posture": r.get("posture"), "my_entries": r.get("my_entries"),
                "tier_reason": r.get("tier_reason"),
                "resolution": r.get("resolution"), "confidence": r.get("confidence"),
            }
            for r in (waterfall.get("rows") or [])
        ],
        "tier_entry_counts": dict(counts),
        "unresolved_entries": unresolved,
        "fees_by_tier": waterfall.get("fees_by_tier"),
        "fee_shares": waterfall.get("fee_shares"),
        "policy": waterfall.get("policy"),
        "policy_checks": list(waterfall.get("policy_checks") or []),
        "family_notes": list(waterfall.get("family_notes") or []),
        "warnings": list(waterfall.get("warnings") or []),
        "coverage_target": coverage,
        "contest_postures_suggested": waterfall.get("contest_postures"),
    }


def _merged_controls_for_build(
    posture_by_contest: Mapping[str, Mapping[str, Any]],
    override: Optional[Mapping[str, Any]],
    feasibility_floors: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Merge strategy-default controls across contests (tightest cap wins), floor to
    feasibility, then apply overrides.

    ``feasibility_floors`` raises the tightest-merged repetition caps to a slate-
    feasible minimum. Floors are applied AFTER the min-merge and BEFORE the explicit
    override, so an explicit override always wins over a floor. Default None keeps the
    pre-v1.8 behavior unchanged.
    """
    merged: Dict[str, Any] = {}
    pct_keys = ("max_player_exposure_pct", "max_pitcher_exposure_pct", "max_primary_stack_exposure_pct")
    rep_keys = ("max_sp_pair_repetition", "max_shared_players")
    # R34. Floor keys merge by MIN like the ceilings, but for the opposite
    # reason. A ceiling merges to the tightest because one portfolio must
    # satisfy every contest's ceiling. A floor merges to the LEAST demanding
    # because the same portfolio must be legal for the contest that never asked
    # for the floor, and forcing a 5-stack quota onto a posture that did not
    # request it is a strategy change for that contest, made invisibly.
    floor_keys = ("min_five_stack_share_pct",)
    for info in posture_by_contest.values():
        controls = STRATEGY_DEFAULTS.get(info["posture"], STRATEGY_DEFAULTS["large_gpp"])["controls"]
        for key in pct_keys:
            if key in controls:
                merged[key] = min(merged.get(key, 1.0), float(controls[key]))
        for key in rep_keys:
            if key in controls:
                merged[key] = min(merged.get(key, controls[key]), int(controls[key]))
        for key in ("five_stack_min_size",):
            if key in controls:
                merged[key] = min(merged.get(key, controls[key]), int(controls[key]))
    # R34, the floor merge, done after the ceiling loop because it needs to know
    # whether EVERY posture declared it. Silence is not zero-with-an-opinion, it
    # is no opinion, and a portfolio that serves a silent contest must not carry
    # a quota that contest never asked for. So one silent posture retires the
    # floor for the whole merge; among postures that do declare it, the least
    # demanding wins for the same reason.
    for key in floor_keys:
        declared = [
            STRATEGY_DEFAULTS.get(i["posture"], STRATEGY_DEFAULTS["large_gpp"])["controls"]
            for i in posture_by_contest.values()
        ]
        vals = [float(c[key] or 0.0) for c in declared if key in c]
        if not vals:
            continue          # nobody asked: the key stays absent entirely
        merged[key] = min(vals) if len(vals) == len(declared) else 0.0

    for key, floor_val in (feasibility_floors or {}).items():
        if floor_val is None or key not in merged:
            # v1.9: a floor may only relax an existing cap, never add one.
            continue
        if key in floor_keys:
            # R34: relaxing a LOWER bound means lowering it. Applying the
            # ceiling rule here would raise the quota on exactly the thin slate
            # that could not carry it, which is the failure inverted.
            merged[key] = max(0.0, min(float(merged[key]), float(floor_val)))
        elif key in pct_keys:
            merged[key] = min(1.0, max(float(merged[key]), float(floor_val)))
        else:
            merged[key] = max(int(merged[key]), int(floor_val))
    merged.update(dict(override or {}))
    return merged


def feasibility_floors_from(feasibility_inputs: Mapping[str, Any]) -> Dict[str, Any]:
    """``_slate_feasibility`` output -> the ``feasibility_floors`` mapping.

    v1.9: pct exposure caps join the repetition floors, retiring the last
    recurring manual relaxation (ledger 3.3). Applied only to keys the posture
    merge produced; an explicit override still wins.

    R29(3), second pass: extracted from ``run_slate`` so ``late_swap.py`` can
    apply the SAME floors the build applied. Without this the swap re-derived the
    UNFLOORED caps, which on a thin slate are tighter than the ones the build
    shipped, and the untouched entries violated them -- the identical failure
    R29(3) set out to close, arriving through the automatic path instead of the
    operator's. One implementation, because two would diverge and the weaker one
    would report success.
    """
    floors: Dict[str, Any] = {}
    if not feasibility_inputs.get("available"):
        return floors
    if feasibility_inputs.get("floor_sp_pair_repetition"):
        floors["max_sp_pair_repetition"] = feasibility_inputs["floor_sp_pair_repetition"]
    if feasibility_inputs.get("floor_shared_players"):
        floors["max_shared_players"] = feasibility_inputs["floor_shared_players"]
    for floor_key, control_key in (
        ("floor_player_exposure_pct", "max_player_exposure_pct"),
        ("floor_pitcher_exposure_pct", "max_pitcher_exposure_pct"),
        ("floor_stack_exposure_pct", "max_primary_stack_exposure_pct"),
    ):
        if feasibility_inputs.get(floor_key):
            floors[control_key] = feasibility_inputs[floor_key]
    # R34: the preventive rung for the five-stack quota. A slate with few
    # stackable teams cannot carry both a 5-stack quota and the primary-stack
    # EXPOSURE cap that limits how many entries may share one team, because the
    # quota needs qualifying entries and the cap forbids them piling onto one
    # team. The two multiply: with S stackable teams and an exposure cap c, at
    # most S * c of the bank can be five-stacks. Cap the quota there rather than
    # letting the joint MILP discover it as a bare infeasibility.
    stackable = feasibility_inputs.get("stackable_team_count")
    if stackable:
        exposure = float(feasibility_inputs.get("floor_stack_exposure_pct") or 0.0) or 0.35
        ceiling = max(0.0, min(1.0, float(stackable) * exposure))
        floors["min_five_stack_share_pct"] = ceiling
    return floors


# Stack-size the pipeline can force per posture, used only to floor decorrelation
# controls to a feasible minimum. These mirror the stack_plan sizes in
# STRATEGY_DEFAULTS and are never win-rate or ROI claims.
_STACK_SIZE_BY_PLAN: Dict[str, int] = {
    "tight_consecutive_1_5": 5,
    "tight_5_plus_secondary": 5,
    "five_three_with_diversification": 5,
    "tight_4_or_5": 5,
    "tight_consecutive_1_4": 4,
}


def _exclusion_block(
    projections: Any,
    excluded_player_ids: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """What the exclusion set actually removes from this pool.

    F15: ``excluded_player_ids`` used to reach validation and feasibility but
    not the bank build. Now that it does, the checkpoint has to show the effect
    before the solve, because an exclusion is the one input where a typo is
    silent: a wrong ID excludes nobody, the build proceeds around a player who
    should be gone, and the export gate finds it with no time to rebuild.
    """
    from mlb_engine.optimize.optimizer_v3 import excluded_flags

    ids = [str(x) for x in (excluded_player_ids or [])]
    block: Dict[str, Any] = {
        "requested": ids,
        "requested_count": len(ids),
        "matched_player_ids": [],
        "unmatched_player_ids": [],
        "excluded_column": {},
        "blockers": [],
        "note": "excludes are applied to the bank build and to every solve; "
                "deterministic bookkeeping, never a claim",
    }

    # F21: the Excluded column is the other way a player leaves the legal pool,
    # and it used to do it silently on a blank cell. Its counts belong next to
    # the explicit exclusion set, in the block the operator already reads.
    try:
        _, column_report = excluded_flags(projections)
        block["excluded_column"] = column_report
        if column_report.get("unrecognized_kept"):
            block["blockers"].append(
                f"{column_report['unrecognized_kept']} Excluded cell(s) hold values "
                f"this engine does not recognize "
                f"({column_report['unrecognized_values'][:5]}); those players were "
                f"KEPT in the pool. Fix the cells or drop the players explicitly"
            )
    except Exception:  # noqa: BLE001 - never block the checkpoint on a frame quirk
        block["excluded_column"] = {"note": "Excluded column not readable from this frame"}

    if not ids:
        return block
    try:
        pool = {str(p) for p in projections["Player_ID"]}
    except Exception:  # noqa: BLE001 - never block the checkpoint on a frame quirk
        block["note"] = "exclusion effect not computable from this frame"
        return block
    matched = [x for x in ids if x in pool]
    unmatched = [x for x in ids if x not in pool]
    block["matched_player_ids"] = matched
    block["unmatched_player_ids"] = unmatched
    if unmatched:
        block["blockers"].append(
            f"{len(unmatched)} excluded player id(s) are absent from the pool "
            f"({unmatched[:5]}); an exclusion that matches nobody removes nobody"
        )
    return block


def _slate_feasibility(
    posture_by_contest: Mapping[str, Mapping[str, Any]],
    entry_requirements: Sequence[Mapping[str, Any]],
    projections: Any,
    excluded_player_ids: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Cheap, pre-solve structural feasibility inputs for the checkpoint.

    Derives the slate's viable SP-pair capacity and stack size from the frame and the
    minimum feasible ``max_sp_pair_repetition`` and ``max_shared_players`` so the
    merged controls can be floored to a feasible value instead of the tightest posture
    default. Fully defensive: any error degrades to ``available=False`` and never blocks
    the checkpoint. Deterministic; touches no projection value.
    """
    from math import ceil as _ceil
    info: Dict[str, Any] = {
        "viable_sp_count": None, "viable_sp_pairs": None, "entries": None,
        "largest_contest_entries": None, "max_stack_size": None,
        "floor_sp_pair_repetition": None, "floor_shared_players": None,
        "stackable_team_count": None,
        "floor_pitcher_exposure_count": None, "floor_pitcher_exposure_pct": None,
        "floor_stack_exposure_count": None, "floor_stack_exposure_pct": None,
        "floor_player_exposure_count": None, "floor_player_exposure_pct": None,
        "available": False, "note": "",
    }
    try:
        entries = len(list(entry_requirements or []))
        info["entries"] = entries
        by_contest: Dict[str, int] = {}
        for r in (entry_requirements or []):
            cid = str(r.get("contest_id"))
            by_contest[cid] = by_contest.get(cid, 0) + 1
        info["largest_contest_entries"] = max(by_contest.values()) if by_contest else 0

        from mlb_engine.optimize.optimizer_v3 import (
            _eligible_sp_ids_for_anchor_caps, enumerate_sp_pairs,
            _stackable_teams_by_strength,
        )
        sps = _eligible_sp_ids_for_anchor_caps(projections, excludes=list(excluded_player_ids or []))
        n_sps = len({str(s) for s in sps})
        info["viable_sp_count"] = n_sps
        # Cross-game only: two opposing starters are anti-correlated, so
        # counting them as capacity understates the true repetition floor.
        n_pairs = len(enumerate_sp_pairs(sps, projections))
        info["viable_sp_pairs"] = n_pairs
        n_stackable = len(_stackable_teams_by_strength(projections))
        info["stackable_team_count"] = n_stackable

        stack_sizes = []
        for meta in (posture_by_contest or {}).values():
            plan = STRATEGY_DEFAULTS.get(meta.get("posture"), {}).get("stack_plan")
            if plan in _STACK_SIZE_BY_PLAN:
                stack_sizes.append(_STACK_SIZE_BY_PLAN[plan])
        max_stack = max(stack_sizes) if stack_sizes else 5
        info["max_stack_size"] = max_stack

        floor_rep = int(_ceil(entries / n_pairs)) if (entries > 1 and n_pairs >= 1) else 1
        info["floor_sp_pair_repetition"] = floor_rep
        if entries > 1:
            inherent = max_stack + (2 if floor_rep >= 2 else 0)
            info["floor_shared_players"] = min(9, inherent + 1)
        else:
            info["floor_shared_players"] = None

        # v1.9 pct exposure floors. Some arm must take ceil(2E / viable SPs)
        # pitcher slots and some team ceil(E / stackable teams) primary stacks,
        # so any pct whose _cap_count lands below that is structurally
        # infeasible. Player cap covers both pitchers and stacked hitters.
        if entries > 1:
            if n_sps >= 1:
                pc = int(_ceil((2 * entries) / n_sps))
                info["floor_pitcher_exposure_count"] = pc
                info["floor_pitcher_exposure_pct"] = min(1.0, pc / entries)
            if n_stackable >= 1:
                sc = int(_ceil(entries / n_stackable))
                info["floor_stack_exposure_count"] = sc
                info["floor_stack_exposure_pct"] = min(1.0, sc / entries)
            pl = max(info["floor_pitcher_exposure_count"] or 1,
                     info["floor_stack_exposure_count"] or 1)
            info["floor_player_exposure_count"] = pl
            info["floor_player_exposure_pct"] = min(1.0, pl / entries)

        info["available"] = True
    except Exception as exc:  # defensive: never block the checkpoint on this
        info["note"] = f"feasibility inputs unavailable: {exc}"
    return info


def _feasibility_report(feas: Mapping[str, Any], controls: Mapping[str, Any]) -> Dict[str, Any]:
    """Advisory pre-solve feasibility of the resolved controls against the slate.

    Never a hard block: it names the exact binding constraint and required cap value
    so an infeasible build is a one-read fix instead of a rediscovery under the clock.
    ``passed`` is None when the structural inputs were unavailable.
    """
    from math import ceil as _ceil
    report: Dict[str, Any] = {"passed": True, "checks": [], "binding_constraints": []}
    if not feas.get("available"):
        report["passed"] = None
        report["checks"].append({
            "name": "feasibility_inputs", "passed": None,
            "detail": feas.get("note") or "structural feasibility inputs unavailable",
        })
        return report

    entries = feas.get("entries") or 0
    n_pairs = feas.get("viable_sp_pairs")
    max_stack = feas.get("max_stack_size") or 5
    rep = controls.get("max_sp_pair_repetition")
    shared = controls.get("max_shared_players")

    if entries > 1 and rep is not None and n_pairs is not None:
        capacity = int(n_pairs) * int(rep)
        ok = capacity >= entries
        detail = f"{n_pairs} viable SP pairs x cap {rep} = {capacity} lineup-slots vs {entries} entries"
        remedy = None
        if not ok:
            need_cap = int(_ceil(entries / n_pairs)) if n_pairs else None
            need_pairs = int(_ceil(entries / int(rep))) if rep else None
            remedy = (f"raise max_sp_pair_repetition to >= {need_cap}, or widen the viable "
                      f"SP set to >= {need_pairs} pairs (have {n_pairs})")
            report["binding_constraints"].append(f"SP-pair capacity infeasible: {detail}; {remedy}")
            report["passed"] = False
        report["checks"].append({"name": "sp_pair_capacity", "passed": ok, "detail": detail, "remedy": remedy})

    if entries > 1 and shared is not None:
        inherent = int(max_stack) + (2 if (rep or 1) >= 2 else 0)
        ok = int(shared) >= inherent
        detail = (f"max_shared_players {shared} vs inherent overlap floor {inherent} "
                  f"({max_stack}-stack" + (" + shared SP pair" if (rep or 1) >= 2 else "") + ")")
        remedy = None
        if not ok:
            remedy = f"raise max_shared_players to >= {inherent}"
            report["binding_constraints"].append(f"max_shared_players below inherent floor: {detail}; {remedy}")
            report["passed"] = False
        report["checks"].append({"name": "shared_players_floor", "passed": ok, "detail": detail, "remedy": remedy})

    # v1.9 pct-cap capacity checks, mirroring the allocator's _cap_count.
    def _cap_count_local(pct: Any) -> Optional[int]:
        if pct is None:
            return None
        value = float(pct)
        if value <= 0:
            return None
        from math import floor as _floor
        return max(1, int(_floor(entries * min(1.0, value) + 1e-9)))

    if entries > 1:
        n_sps = feas.get("viable_sp_count")
        n_stackable = feas.get("stackable_team_count")
        pct_specs = (
            ("max_pitcher_exposure_pct", "pitcher_exposure_capacity", n_sps,
             2 * entries, "viable SPs", "pitcher slots"),
            ("max_primary_stack_exposure_pct", "stack_exposure_capacity", n_stackable,
             entries, "stackable teams", "entries"),
        )
        for key, check_name, n_units, demand, unit_label, demand_label in pct_specs:
            pct = controls.get(key)
            if pct is None or not n_units:
                continue
            cap = _cap_count_local(pct)
            if cap is None:
                continue
            capacity = cap * int(n_units)
            ok = capacity >= demand
            detail = (f"{key} {pct} -> cap {cap} x {n_units} {unit_label} = "
                      f"{capacity} vs {demand} {demand_label}")
            remedy = None
            if not ok:
                need = int(_ceil(demand / int(n_units)))
                remedy = f"raise {key} to >= {min(1.0, need / entries):.3f} (cap {need})"
                report["binding_constraints"].append(f"{check_name} infeasible: {detail}; {remedy}")
                report["passed"] = False
            report["checks"].append({"name": check_name, "passed": ok, "detail": detail, "remedy": remedy})

        player_pct = controls.get("max_player_exposure_pct")
        floor_player = feas.get("floor_player_exposure_count")
        if player_pct is not None and floor_player:
            cap = _cap_count_local(player_pct)
            if cap is not None:
                ok = cap >= int(floor_player)
                detail = (f"max_player_exposure_pct {player_pct} -> cap {cap} vs "
                          f"structural floor {floor_player} (max of pitcher and stack demand)")
                remedy = None
                if not ok:
                    remedy = (f"raise max_player_exposure_pct to >= "
                              f"{min(1.0, int(floor_player) / entries):.3f} (cap {floor_player})")
                    report["binding_constraints"].append(f"player_exposure_floor infeasible: {detail}; {remedy}")
                    report["passed"] = False
                report["checks"].append({"name": "player_exposure_floor", "passed": ok,
                                         "detail": detail, "remedy": remedy})

    largest = feas.get("largest_contest_entries") or 0
    report["checks"].append({
        "name": "same_contest_unique_capacity", "passed": True,
        "detail": (f"largest single contest needs {largest} distinct lineups; the auto-bank "
                   f"targets >= requested_n, which is >= total entries"),
    })
    return report


# Default plan-solve budget in seconds. Sized against the evidence in R28: the
# sliced path exhausts a two-game pool's 64 (SP pair, stack team) jobs in about
# a second, and a full slate's job list is roughly an order of magnitude larger.
# The budget is stated in the verdict either way, because "unchecked" is only
# honest when the reader can see what it was unchecked against.
PLAN_SOLVE_BUDGET_S = 25.0


def _plan_joint_allocation(
    projections: Any,
    entry_requirements: Sequence[Mapping[str, Any]],
    controls: Mapping[str, Any],
    *,
    budget_s: float,
    candidates_override: Optional[Sequence[Mapping[str, Any]]] = None,
    excluded_player_ids: Optional[Sequence[str]] = None,
    requested_n: Optional[int] = None,
    contest_shapes: Optional[Sequence[str]] = None,
    solver_time_limit_s: Optional[float] = None,
) -> Dict[str, Any]:
    """Solve the build's joint allocation at approve=False and report the verdict.

    R28(1). ``_slate_feasibility``'s auto-floors are POOL-keyed, so they cannot
    see an interaction that lives in the BANK. The archived 06-03 grid is the
    proof: the floors visibly fired, the checkpoint passed the plan, and the
    approve=True build then returned "no single control is arithmetically
    binding against this bank, so the interaction of the active controls is".
    Pool arithmetic can never predict that, so the checkpoint stops trying to
    and solves the same MILP the build solves instead.

    The verdict is one of three, and one of them is always emitted:

    ``would_certify``    the joint allocation solved on this bank. This is the
                         allocation leg only (``selection_certified`` and
                         ``allocation_certified``); ``workflow_valid`` is
                         derived post-export from the written file and is not
                         evaluated here. Never a claim about the slate.
    ``proven_infeasible``the allocator refused, carrying the exact error text
                         the build would raise.
    ``unchecked``        the budget did not cover the work, naming the budget.

    Silence is not on the list, which is the whole point of the item.

    The bank is built through the sliced path into a TEMPORARY cache, never the
    shared per-slate cache: this solve is speculative, its conditions signature
    is the plan's, and writing it where a build would read it would let a plan
    seed a build's bank. When ``candidates_override`` is supplied the plan
    solves the build's own candidates and the verdict is exact; on the auto-bank
    path the plan's sliced bank is not the build's ``build_diverse_candidate_bank``
    bank, and the verdict says so rather than implying an identity it does not
    have.

    Deterministic and side-effect free: no run directory, no shared-cache write.
    """
    verdict: Dict[str, Any] = {
        "available": False,
        "verdict": "unchecked",
        "budget_s": float(budget_s),
        "bank_source": None,
        "candidate_count": None,
        "errors": [],
        "summary": "",
        "exact_for_this_build": None,
    }
    entries = [dict(e) for e in (entry_requirements or [])]
    if not entries:
        verdict.update({
            "available": True, "verdict": "would_certify", "bank_source": "none",
            "candidate_count": 0, "exact_for_this_build": True,
            "summary": "no entries requested; the joint allocation is trivially satisfiable",
        })
        return verdict
    if budget_s <= 0:
        verdict["summary"] = (
            f"unchecked: plan solve disabled (budget {float(budget_s):g}s). The bank "
            f"interaction stays unchecked until approve=True."
        )
        return verdict

    try:
        import tempfile as _tempfile
        from pathlib import Path as _Path

        started = time.monotonic()
        if candidates_override is not None:
            candidates = [dict(c) for c in candidates_override]
            verdict["bank_source"] = "candidates_override"
            verdict["exact_for_this_build"] = True
            bank_note = "the build's own candidates"
        else:
            from mlb_engine.optimize.bank_cache import BankCache, extend_bank

            excl = [str(x) for x in (excluded_player_ids or [])]
            bank_projections = projections
            if excl and hasattr(projections, "columns"):
                bank_projections = projections.copy()
                if "Excluded" not in bank_projections.columns:
                    bank_projections["Excluded"] = False
                mask = bank_projections["Player_ID"].astype(str).isin(set(excl))
                bank_projections.loc[mask, "Excluded"] = True
            with _tempfile.TemporaryDirectory(prefix="plan_bank_") as tmp:
                cache = BankCache(_Path(tmp) / "plan_bank.json")
                report = extend_bank(
                    cache, bank_projections, time_budget_s=float(budget_s),
                    excludes=excl or None, solver_time_limit_s=solver_time_limit_s,
                )
                if not report.get("job_list_exhausted"):
                    built = len(cache.candidates)
                    verdict["bank_source"] = "sliced_plan_bank"
                    verdict["candidate_count"] = built
                    verdict["summary"] = (
                        f"unchecked: budget exceeded. The sliced plan bank did not exhaust "
                        f"its job list inside {float(budget_s):g}s ({built} candidates built); "
                        f"solving a partial bank would report an infeasibility that is the "
                        f"clock, not the controls. Raise the plan budget or accept that the "
                        f"bank interaction is unchecked until approve=True."
                    )
                    return verdict
                candidates = cache.as_candidates(
                    bank_projections,
                    requested_n=int(requested_n or max(len(entries), 1)),
                    contest_shapes=list(contest_shapes) if contest_shapes else None,
                )
            verdict["bank_source"] = "sliced_plan_bank"
            verdict["exact_for_this_build"] = False
            bank_note = (
                "a sliced plan bank, which is not the build's "
                "build_diverse_candidate_bank bank"
            )

        verdict["candidate_count"] = len(candidates)
        allocation = select_and_assign_entries(candidates, entries, dict(controls))
        elapsed = time.monotonic() - started
        verdict["elapsed_s"] = round(elapsed, 2)
        solver_report = allocation.get("allocation_solver_report") or {}
        verdict["allocation_solver_report"] = solver_report

        if allocation.get("passed"):
            verdict.update({
                "available": True, "verdict": "would_certify",
                "summary": (
                    f"would certify: the joint allocation solved on {bank_note} "
                    f"({len(candidates)} candidates, {len(entries)} entries) under the "
                    f"resolved controls. Allocation leg only; workflow_valid is derived "
                    f"post-export and is not evaluated in plan mode."
                ),
            })
            return verdict

        errors = [str(e) for e in (allocation.get("errors") or [])]
        # A time limit inside the allocator is the clock, not the controls, and
        # the allocator already says so in its own words. Reporting it as
        # proven-infeasible would be the exact mislabel this item exists to kill.
        timed_out = str(solver_report.get("status") or "") == "time_limit"
        if timed_out:
            verdict["errors"] = errors
            verdict["summary"] = (
                f"unchecked: budget exceeded. The joint MILP hit its own time limit on "
                f"{bank_note}; this is the clock, not a proven infeasibility."
            )
            return verdict
        verdict.update({
            "available": True, "verdict": "proven_infeasible", "errors": errors,
            "summary": (
                f"proven infeasible at plan time on {bank_note}: "
                + (errors[0] if errors else "the allocator refused without an error line")
            ),
        })
        return verdict
    except Exception as exc:  # noqa: BLE001 - the checkpoint may never block on this
        verdict["errors"] = [f"{type(exc).__name__}: {exc}"]
        verdict["summary"] = (
            f"unchecked: the plan solve raised {type(exc).__name__}: {exc}. The bank "
            f"interaction stays unchecked until approve=True."
        )
        return verdict


def _assemble_projection_frame(
    salary_csv: str | Path,
    projection_rows: Any,
    projection_mode: str,
    savant_batting_csv: Optional[str | Path],
    savant_pitching_csv: Optional[str | Path],
    source_metadata: Optional[Mapping[str, Any]],
    projected_order_by_player_id: Optional[Mapping[str, int]] = None,
    f4_by_player_id: Optional[Mapping[str, float]] = None,
    f1_by_player_id: Optional[Mapping[str, float]] = None,
    f5_by_player_id: Optional[Mapping[str, float]] = None,
    apply_value_sanity_guard: bool = True,
    fangraphs_pitching_csv: Optional[str | Path] = None,
) -> "tuple[pd.DataFrame, Dict[str, Any]]":
    """Join per-player projection rows to the authoritative salary file and build an
    optimizer-ready frame. Returns ``(projections, enrichment)``.

    Salary is authoritative for Team/Salary/Game_ID/Opponent; Position comes from
    the salary roster slot unless explicitly overridden, then is coerced to DK slot
    tokens. Missing factors default to 1.0 and are surfaced via Notes.

    ``projected_order_by_player_id`` is the TBD-lineup fallback hook: for any row
    whose Player_ID is in the map AND that carries no Batting_Order, Batting_Order is
    set to the projected slot and F2 is set to ``batting_order_factor(slot)`` BEFORE
    ``build_projections`` runs, so the slot flows into Base_Projection, Floor, and
    Ceiling. Rows that already carry a Batting_Order are left untouched, so a
    confirmed or explicit order always wins. The map is built upstream by
    ``platoon_order_adapter.build_projected_order`` and is a projected order only;
    it never sets confirmed_teams. Rows enriched this way are tagged in Notes.

    ``f4_by_player_id`` is the deterministic matchup hook (v1.6): a
    ``{Player_ID: F4}`` map built upstream by
    ``projection_builder.compute_f4_factors``. It is applied only to rows that do
    NOT carry an explicit F4, so a hand-supplied factor always wins, and applied
    rows are tagged in Notes. It is a labeled deterministic prior, never a
    win-rate or probability claim.

    When ``savant_batting_csv``/``savant_pitching_csv`` are supplied, the xwOBA
    Base correction is joined through the DK-keyed name crosswalk
    (``xwoba_base_correction.build_dk_keyed_corrections``), never through the raw
    MLBAM-keyed map, and the match report is returned in ``enrichment["xwoba"]``.
    A supplied correction that matches ZERO players on a real pool is a wiring
    failure, not a data condition, and raises rather than silently building on
    uncorrected Bases. The batting CSV additionally drives per-player Ceiling
    multipliers from expected ISO (``enrichment["ceiling"]``).

    ``apply_value_sanity_guard`` (default True) codifies the previously manual
    protocol step: hitter Base is capped at the slate's 90th-percentile hitter
    points-per-$1k times 1.08 BEFORE F1-F5, so a small-sample min-salary bat
    cannot dominate every candidate. Clips are tagged in Notes and reported in
    ``enrichment["value_guard"]``. Pitchers are never capped.

    ``fangraphs_pitching_csv`` (v1.7) supplies the K-rate input the pitcher
    ceiling gap waited on: per-pitcher Ceiling multipliers join through
    ``xwoba_base_correction.build_dk_keyed_pitcher_ceiling_multipliers`` and
    fill the same per-row ``Ceiling_Multiplier`` column for pitcher rows,
    independent of the Savant CSVs. Applied rows are tagged in Notes and the
    match report is returned in ``enrichment["pitcher_ceiling"]``. A supplied
    file that matches ZERO pitchers on a real pool raises as a wiring error,
    mirroring the xwOBA guard; omit the file to build with uniform pitcher
    ceilings on purpose. Deterministic labeled prior, never a probability
    claim.
    """
    from mlb_engine.intake.slate_intake_manager import parse_dk_salary_csv
    from mlb_engine.projections.projection_builder import (
        build_projections, apply_xwoba_correction, batting_order_factor,
    )
    from mlb_engine.projections.xwoba_base_correction import (
        build_dk_keyed_corrections, build_dk_keyed_ceiling_multipliers,
        build_dk_keyed_pitcher_ceiling_multipliers,
    )

    projected_order = {str(k): int(v) for k, v in (projected_order_by_player_id or {}).items()}
    f4_map = {str(k): float(v) for k, v in (f4_by_player_id or {}).items()}
    f1_map = {str(k): float(v) for k, v in (f1_by_player_id or {}).items()}
    f5_map = {str(k): float(v) for k, v in (f5_by_player_id or {}).items()}

    players = {str(p.player_id): p for p in parse_dk_salary_csv(str(salary_csv))}
    rows = list(projection_rows or [])
    if not rows:
        raise ValueError("projection_rows is empty; supply per-player rows or projections_override")

    enrichment: Dict[str, Any] = {
        "xwoba": None, "ceiling": None, "value_guard": None, "pitcher_ceiling": None,
        "f4": {"requested": len(f4_map), "applied_count": 0, "applied_player_ids": [],
               "note": "deterministic F4 prior applied to rows lacking an explicit F4"
                       if f4_map else "no F4 map supplied"},
        "f1": {"requested": len(f1_map), "applied_count": 0, "applied_player_ids": [],
               "note": "deterministic F1 game-environment prior applied to rows "
                       "lacking an explicit F1" if f1_map else "no F1 map supplied"},
        "f5": {"requested": len(f5_map), "applied_count": 0, "applied_player_ids": [],
               "note": "deterministic F5 park/weather prior applied to rows "
                       "lacking an explicit F5" if f5_map else "no F5 map supplied"},
        "warnings": [],
    }

    assembled: list[Dict[str, Any]] = []
    for raw in rows:
        r = dict(raw)
        pid = str(r.get("Player_ID") or r.get("player_id") or "").strip()
        sp = players.get(pid)
        if sp is None:
            continue  # not on the salary file -> unrosterable (spec: salary is authoritative)
        position = r.get("Position") or "/".join(sp.positions)
        notes = str(r.get("Notes") or "")
        if (r.get("F4") in (None, "")) and pid in f4_map:
            r["F4"] = f4_map[pid]
            enrichment["f4"]["applied_count"] += 1
            enrichment["f4"]["applied_player_ids"].append(pid)
            notes = (notes + f"; f4_matchup: deterministic prior {f4_map[pid]:.3f}").lstrip("; ")
        # Same contract as F4: an explicitly supplied F1 always wins, applied
        # rows are tagged, and the map is a labeled prior built upstream from
        # posted prices. Never a run projection or a probability claim.
        if (r.get("F1") in (None, "")) and pid in f1_map:
            r["F1"] = f1_map[pid]
            enrichment["f1"]["applied_count"] += 1
            enrichment["f1"]["applied_player_ids"].append(pid)
            notes = (notes + f"; f1_environment: deterministic prior {f1_map[pid]:.3f}").lstrip("; ")
        if (r.get("F5") in (None, "")) and pid in f5_map:
            r["F5"] = f5_map[pid]
            enrichment["f5"]["applied_count"] += 1
            enrichment["f5"]["applied_player_ids"].append(pid)
            notes = (notes + f"; f5_park_weather: deterministic prior {f5_map[pid]:.3f}").lstrip("; ")
        for fcol in ("F1", "F2", "F3", "F4", "F5"):
            if fcol not in r or r.get(fcol) in (None, ""):
                r[fcol] = 1.0
                notes = (notes + f"; {fcol}=1.0 default").lstrip("; ")
        bo_val = r.get("Batting_Order")
        has_order = bo_val not in (None, "") and str(bo_val).strip() != ""
        slot = projected_order.get(pid)
        if slot is not None and not has_order:
            bo_val = int(slot)
            r["F2"] = batting_order_factor(int(slot))
            notes = (notes + "; platoon_order: F2 from projected batting order").lstrip("; ")
        base = r.get("Base")
        if base in (None, "") and "AvgPointsPerGame" in r:
            base = r["AvgPointsPerGame"]
        if base in (None, ""):
            raise ValueError(f"row for Player_ID {pid} missing Base/AvgPointsPerGame")
        assembled.append({
            "Player_ID": pid,
            "Name": r.get("Name") or sp.name,
            "Team": sp.team,
            "Opponent": r.get("Opponent") or sp.opponent,
            "Position": _coerce_dk_positions(position),
            "Salary": float(sp.salary),
            "Game_ID": r.get("Game_ID") or sp.game_id or sp.game_info,
            "Base": float(base),
            "F1": float(r["F1"]), "F2": float(r["F2"]), "F3": float(r["F3"]),
            "F4": float(r["F4"]), "F5": float(r["F5"]),
            "Batting_Order": bo_val,
            "Stack_Group": r.get("Stack_Group") or sp.team,
            "Ownership_Tier": r.get("Ownership_Tier") or "Mid",
            "AvgPointsPerGame": r.get("AvgPointsPerGame"),
            "Notes": notes,
        })

    frame = pd.DataFrame(assembled)

    # --- xwOBA Base correction through the DK-keyed crosswalk (v1.6 fix) ----
    # The pre-v1.6 path applied the MLBAM-keyed map to a DK-keyed frame; the id
    # universes never intersect, so every correction silently fell back to 1.0.
    # The DK-keyed helper is the only sanctioned join, the match report is
    # surfaced, and a zero-match on a real pool is a hard wiring error because
    # the caller can always omit the CSVs to build uncorrected on purpose.
    if savant_batting_csv or savant_pitching_csv:
        corrections, match_report = build_dk_keyed_corrections(
            str(salary_csv),
            batting_csv=str(savant_batting_csv) if savant_batting_csv else None,
            pitching_csv=str(savant_pitching_csv) if savant_pitching_csv else None,
        )
        xwoba_summary = {
            "applied": False,
            "considered": match_report.get("considered", 0),
            "matched": match_report.get("matched", 0),
            "unmatched": match_report.get("unmatched", 0),
            "match_rate": match_report.get("match_rate", 0.0),
            "neutral_1p0": match_report.get("neutral_1p0", 0),
            "name_collisions_batter": match_report.get("name_collisions_batter", {}),
            "name_collisions_pitcher": match_report.get("name_collisions_pitcher", {}),
            "unmatched_rows": match_report.get("unmatched_rows", []),
        }
        if xwoba_summary["considered"] >= XWOBA_WIRING_MIN_POOL and xwoba_summary["matched"] == 0:
            raise ValueError(
                "xwOBA wiring failure: expected-stats CSV(s) were supplied but the "
                f"DK-keyed crosswalk matched 0 of {xwoba_summary['considered']} salary "
                "players. Building on uncorrected Bases while claiming a correction is "
                "the silent no-op this guard exists to block; verify the CSVs or omit "
                "them to build uncorrected on purpose."
            )
        if "AvgPointsPerGame" in frame.columns and frame["AvgPointsPerGame"].notna().any():
            frame, _xwoba_audit = apply_xwoba_correction(
                frame, corrections, base_in="AvgPointsPerGame", base_out="Base")
            xwoba_summary["applied"] = True
            non_neutral = _xwoba_audit[abs(_xwoba_audit["xwoba_correction"] - 1.0) > 1e-9]
            xwoba_summary["non_neutral_applied"] = int(len(non_neutral))
            if xwoba_summary["match_rate"] < XWOBA_LOW_MATCH_RATE_WARN:
                enrichment["warnings"].append(
                    f"xwOBA match rate {xwoba_summary['match_rate']:.0%} is below "
                    f"{XWOBA_LOW_MATCH_RATE_WARN:.0%}; unmatched players build on uncorrected Bases"
                )
        else:
            enrichment["warnings"].append(
                "Savant CSV(s) supplied but no AvgPointsPerGame values present; xwOBA "
                "correction NOT applied and Bases are as supplied"
            )
        enrichment["xwoba"] = xwoba_summary

        # Per-player Ceiling multipliers from expected ISO (batting CSV only).
        if savant_batting_csv:
            ceiling_mults, ceiling_report = build_dk_keyed_ceiling_multipliers(
                str(salary_csv), str(savant_batting_csv))
            frame["Ceiling_Multiplier"] = frame["Player_ID"].astype(str).map(
                lambda p: ceiling_mults.get(p))
            differentiated = frame["Ceiling_Multiplier"].notna().sum()
            for idx in frame.index[frame["Ceiling_Multiplier"].notna()]:
                mult = float(frame.at[idx, "Ceiling_Multiplier"])
                frame.at[idx, "Notes"] = (
                    str(frame.at[idx, "Notes"]) + f"; xiso_ceiling: {mult:.2f}").lstrip("; ")
            enrichment["ceiling"] = {
                "matched": ceiling_report.get("matched", 0),
                "unmatched": ceiling_report.get("unmatched", 0),
                "match_rate": ceiling_report.get("match_rate", 0.0),
                "differentiated_rows": int(differentiated),
                "note": "Per-player Ceiling multipliers from expected ISO; unmatched rows "
                        "take the uniform neutral. Deterministic prior, never a probability claim.",
            }

    # --- Per-pitcher Ceiling multipliers from a K-rate input (v1.7) ----------
    # Closes the "hitters only until a K-rate input exists" gap: the FanGraphs
    # season pitching CSV is a per-slate data input on the same footing as the
    # Savant CSVs. Pitcher rows fill the same Ceiling_Multiplier column the
    # xISO block uses for hitters, so build_projections consumes one path.
    # Independent of the Savant CSVs; a supplied file matching zero pitchers on
    # a real pool is a wiring failure, mirroring the xwOBA guard.
    if fangraphs_pitching_csv:
        pitcher_mults, pitcher_report = build_dk_keyed_pitcher_ceiling_multipliers(
            str(salary_csv), str(fangraphs_pitching_csv))
        if (pitcher_report.get("considered_pitchers", 0) >= XWOBA_WIRING_MIN_POOL
                and pitcher_report.get("matched", 0) == 0):
            raise ValueError(
                "pitcher K-rate ceiling wiring failure: a FanGraphs pitching CSV was "
                f"supplied but the DK-keyed crosswalk matched 0 of "
                f"{pitcher_report['considered_pitchers']} salary pitchers. Building on "
                "uniform pitcher ceilings while claiming differentiation is the silent "
                "no-op this guard exists to block; verify the CSV or omit it to build "
                "with uniform pitcher ceilings on purpose."
            )
        if "Ceiling_Multiplier" not in frame.columns:
            frame["Ceiling_Multiplier"] = None
        applied_pitchers = 0
        for idx in frame.index:
            pid = str(frame.at[idx, "Player_ID"])
            if pid in pitcher_mults:
                mult = float(pitcher_mults[pid])
                frame.at[idx, "Ceiling_Multiplier"] = mult
                frame.at[idx, "Notes"] = (
                    str(frame.at[idx, "Notes"]) + f"; k_rate_ceiling: {mult:.2f}").lstrip("; ")
                applied_pitchers += 1
        enrichment["pitcher_ceiling"] = {
            "matched": pitcher_report.get("matched", 0),
            "unmatched": pitcher_report.get("unmatched", 0),
            "match_rate": pitcher_report.get("match_rate", 0.0),
            "differentiated_rows": int(applied_pitchers),
            "rate_column": pitcher_report.get("rate_column"),
            "name_collisions": pitcher_report.get("name_collisions", {}),
            "unmatched_rows": pitcher_report.get("unmatched_rows", []),
            "note": "Per-pitcher Ceiling multipliers from a FanGraphs K-rate input; "
                    "unmatched, non-starter, or sub-floor pitchers take the uniform "
                    "neutral. Deterministic prior, never a probability claim.",
        }

    # --- Value-sanity guard, codified (v1.6) ---------------------------------
    # Previously a manual protocol step, the same silent-failure class as the
    # xwOBA join. Hitter Base is capped at the slate's 90th-percentile hitter
    # pts/$1k times VALUE_GUARD_HEADROOM before F1-F5; pitchers are untouched.
    if apply_value_sanity_guard and len(frame):
        hitter_mask = ~frame["Position"].astype(str).str.split("/").apply(
            lambda toks: "P" in [t.strip() for t in toks])
        clipped: list[Dict[str, Any]] = []
        p90 = None
        if bool(hitter_mask.any()):
            per_k = frame.loc[hitter_mask, "Base"].astype(float) / (
                frame.loc[hitter_mask, "Salary"].astype(float) / 1000.0)
            p90 = float(per_k.quantile(VALUE_GUARD_PCTL))
            cap_per_k = p90 * VALUE_GUARD_HEADROOM
            for idx in frame.index[hitter_mask]:
                salary_k = float(frame.at[idx, "Salary"]) / 1000.0
                raw_base = float(frame.at[idx, "Base"])
                cap_base = cap_per_k * salary_k
                if raw_base > cap_base + 1e-9:
                    frame.at[idx, "Base"] = cap_base
                    frame.at[idx, "Notes"] = (
                        str(frame.at[idx, "Notes"]) +
                        f"; value_guard: Base capped {raw_base:.2f}->{cap_base:.2f}").lstrip("; ")
                    clipped.append({
                        "Player_ID": str(frame.at[idx, "Player_ID"]),
                        "Name": str(frame.at[idx, "Name"]),
                        "raw_base": raw_base, "capped_base": cap_base,
                    })
        enrichment["value_guard"] = {
            "applied": True, "percentile": VALUE_GUARD_PCTL,
            "headroom": VALUE_GUARD_HEADROOM, "p90_pts_per_k": p90,
            "clipped_count": len(clipped), "clipped": clipped,
            "note": "Hitter Base capped at the slate 90th-percentile hitter pts/$1k x 1.08 "
                    "before F1-F5; pitchers never capped. Codified from the manual protocol.",
        }
        if clipped:
            enrichment["warnings"].append(
                f"value_guard clipped {len(clipped)} hitter Base value(s); see enrichment['value_guard']")
    else:
        enrichment["value_guard"] = {"applied": False,
                                     "note": "value-sanity guard opted out for this build"}

    projections, _audit = build_projections(frame, mode=projection_mode, source_metadata=source_metadata)
    if "Ownership_Tier" not in projections.columns:
        projections["Ownership_Tier"] = "Mid"
    return projections, enrichment


def _bank_records_to_candidates(candidate_lineups: Sequence[Mapping[str, Any]]) -> list[Dict[str, Any]]:
    """Pass optimizer bank records to the allocator, pinning exact DK slots when present."""
    out: list[Dict[str, Any]] = []
    for rec in candidate_lineups:
        c = dict(rec)
        lineup = rec.get("lineup")
        if hasattr(lineup, "iterrows") and "Assigned_Slot" in getattr(lineup, "columns", []):
            slot_map = {
                str(row.get("Assigned_Slot") or "").strip(): str(row.get("Player_ID") or "").strip()
                for _, row in lineup.iterrows()
                if str(row.get("Assigned_Slot") or "").strip()
            }
            if slot_map:
                c["roster_slot_ids"] = slot_map
        out.append(c)
    return out


# ---------------------------------------------------------------------------
# v2.21.0 bank-diversification guardrail
#
# A high-ceiling hitter who loses a roster slot to a comparable, more flexible
# hitter (e.g. a pure-3B bat behind a 1B/3B bat of equal-or-higher ceiling) is
# never generated into the candidate bank, so no exposure cap can place them.
# These helpers surface that risk at the pre-build checkpoint
# (contested_slot_audit), catch it at build time across any bank-construction
# path (audit_bank_player_coverage), and provide the tool to cover it
# (generate_positional_variant_candidates). All three are deterministic review
# proxies, never win-rate, ROI, or probability claims.
# ---------------------------------------------------------------------------

HITTER_SLOTS = ("C", "1B", "2B", "3B", "SS", "OF")


def _eligible_hitter_slots(position: Any) -> set:
    """DK hitter slot tokens a player is eligible for, parsed from Position."""
    if position is None:
        return set()
    toks = {t.strip().upper() for t in str(position).replace(",", "/").split("/") if t.strip()}
    return {t for t in toks if t in HITTER_SLOTS}


def _hitter_ceiling_table(projections: Any) -> "pd.DataFrame":
    cols = getattr(projections, "columns", [])
    if not hasattr(projections, "columns") or "Ceiling" not in cols or "Position" not in cols:
        return pd.DataFrame(columns=["Player_ID", "Name", "Team", "Position", "Ceiling"])
    df = projections.copy()
    pos = df["Position"].astype(str).str.upper()
    hitters = df[~pos.str.contains("P", na=False)].copy()
    hitters["Ceiling"] = pd.to_numeric(hitters["Ceiling"], errors="coerce").fillna(0.0)
    return hitters.sort_values("Ceiling", ascending=False)


def contested_slot_audit(projections: Any, top_n: int = 14) -> Dict[str, Any]:
    """Flag top-ceiling hitters who can be crowded out of the candidate bank.

    A contested slot is a single-position hitter inside the top ``top_n`` by
    ceiling whose only slot is also covered by a multi-eligible hitter with a
    ceiling at least as high. The flexible hitter can satisfy that slot while
    occupying another, so a ceiling-maximizing optimizer never rosters the
    single-position hitter and they enter zero candidates unless a deliberate
    variant is built. Deterministic review proxy, never a win-rate claim.
    """
    hitters = _hitter_ceiling_table(projections)
    if hitters.empty:
        return {"contested_slots": [], "top_n": top_n, "is_review_proxy": True}
    top = hitters.head(top_n)
    recs: List[Dict[str, Any]] = []
    for _, s in top.iterrows():
        s_slots = _eligible_hitter_slots(s["Position"])
        if len(s_slots) != 1:
            continue  # only single-position hitters can be fully crowded out
        slot = next(iter(s_slots))
        coverers = []
        for _, f in top.iterrows():
            if str(f["Player_ID"]) == str(s["Player_ID"]):
                continue
            f_slots = _eligible_hitter_slots(f["Position"])
            if slot in f_slots and len(f_slots) > 1 and float(f["Ceiling"]) >= float(s["Ceiling"]):
                coverers.append({"player_id": str(f["Player_ID"]), "name": f.get("Name"),
                                 "position": f.get("Position"), "ceiling": round(float(f["Ceiling"]), 2)})
        if coverers:
            recs.append({
                "slot": slot,
                "displaceable_player_id": str(s["Player_ID"]),
                "displaceable_name": s.get("Name"),
                "displaceable_team": s.get("Team"),
                "displaceable_ceiling": round(float(s["Ceiling"]), 2),
                "covered_by": coverers,
                "recommendation": ("build a positional-variant candidate locking this player "
                                   "so the bank carries the slot both ways"),
            })
    return {"contested_slots": recs, "top_n": top_n, "is_review_proxy": True,
            "note": "deterministic review proxy; flags ceiling crowd-out risk, never a win-rate claim"}


def _candidate_player_id_set(cand: Mapping[str, Any]) -> set:
    if cand.get("player_ids"):
        return {str(x) for x in cand["player_ids"]}
    rs = cand.get("roster_slot_ids")
    if isinstance(rs, Mapping):
        return {str(v) for v in rs.values() if str(v)}
    lu = cand.get("lineup")
    if hasattr(lu, "iterrows"):
        return {str(r.get("Player_ID")) for _, r in lu.iterrows()}
    return set()


def audit_bank_player_coverage(candidates: Sequence[Mapping[str, Any]], projections: Any,
                               top_n: int = 14) -> Dict[str, Any]:
    """Flag top-ceiling hitters absent from every candidate in the bank.

    Path-agnostic safety net: whatever built the bank (manual override or the
    auto bank builder), if a hitter inside the top ``top_n`` by ceiling appears
    in zero candidates, no exposure control can ever place them. Deterministic
    review proxy, never a win-rate claim.
    """
    cands = list(candidates or [])
    hitters = _hitter_ceiling_table(projections)
    if hitters.empty:
        return {"passed": True, "absent_players": [], "top_n": top_n,
                "candidate_count": len(cands), "is_review_proxy": True}
    covered: set = set()
    for c in cands:
        covered |= _candidate_player_id_set(c)
    absent = []
    for _, s in hitters.head(top_n).iterrows():
        if str(s["Player_ID"]) not in covered:
            absent.append({"player_id": str(s["Player_ID"]), "name": s.get("Name"),
                           "team": s.get("Team"), "position": s.get("Position"),
                           "ceiling": round(float(s["Ceiling"]), 2)})
    return {"passed": not absent, "absent_players": absent, "top_n": top_n,
            "candidate_count": len(cands), "is_review_proxy": True,
            "note": "top-ceiling hitters in zero candidates cannot be placed by any exposure cap"}


def _lineup_to_variant_candidate(lu: "pd.DataFrame", candidate_id: str,
                                 sp_ids: Optional[Sequence[str]] = None,
                                 primary_stack: Optional[str] = None) -> Dict[str, Any]:
    slot_ids = {str(r["Assigned_Slot"]): str(r["Player_ID"]) for _, r in lu.iterrows()
                if str(r.get("Assigned_Slot") or "").strip()}
    pids = sorted(str(p) for p in lu["Player_ID"])
    ceil = float(pd.to_numeric(lu["Ceiling"], errors="coerce").fillna(0.0).sum()) if "Ceiling" in lu.columns else 0.0
    floor = float(pd.to_numeric(lu["Floor"], errors="coerce").fillna(0.0).sum()) if "Floor" in lu.columns else 0.0
    if sp_ids is None:
        sp_ids = [slot_ids.get("P1"), slot_ids.get("P2")]
    if primary_stack is None and "Team" in lu.columns and "Assigned_Slot" in lu.columns:
        hit = lu[~lu["Assigned_Slot"].astype(str).isin(["P1", "P2"])]
        if not hit.empty:
            primary_stack = str(hit["Team"].value_counts().idxmax())
    return {"candidate_id": candidate_id, "roster_slot_ids": slot_ids, "player_ids": pids,
            "sp_ids": [str(x) for x in (sp_ids or []) if x], "primary_stack": primary_stack,
            "ceiling_sum": round(ceil, 3), "floor_sum": round(floor, 3), "variant_focus": True}


def generate_positional_variant_candidates(projections: Any, focus_player_id: str,
                                           variant_specs: Sequence[Mapping[str, Any]],
                                           *, builder: Any = None,
                                           id_prefix: str = "VAR") -> List[Dict[str, Any]]:
    """Build forced-lock candidates that include ``focus_player_id``.

    The tool to cover a slot flagged by ``contested_slot_audit``. Each spec is a
    dict of optimizer arguments (``locks``, ``stack_constraints``,
    ``bringback_constraint``, ``target``, optional ``sp_ids``/``primary_stack``);
    ``focus_player_id`` is appended to each spec's locks. ``builder`` defaults to
    ``optimizer_v3.build_single_lineup`` and is injectable for testing. Specs
    that come back infeasible are skipped. Deterministic review proxy.
    """
    if builder is None:
        from mlb_engine.optimize.optimizer_v3 import build_single_lineup as builder  # type: ignore
    out: List[Dict[str, Any]] = []
    for i, spec in enumerate(variant_specs):
        locks = [str(x) for x in spec.get("locks", [])] + [str(focus_player_id)]
        try:
            lu, _obj = builder(
                projections, target=spec.get("target", "ceiling"), locks=locks,
                stack_constraints=spec.get("stack_constraints"),
                bringback_constraint=spec.get("bringback_constraint"),
            )
        except Exception:
            lu = None
        if lu is None:
            continue
        out.append(_lineup_to_variant_candidate(
            lu, f"{id_prefix}-{i + 1}", spec.get("sp_ids"), spec.get("primary_stack")))
    return out


def run_slate(
    *,
    runs_root: str | Path,
    salary_csv: str | Path,
    entries_csv: str | Path,
    contest_postures: Optional[Mapping[str, Any]] = None,
    waterfall: Optional[Mapping[str, Any]] = None,
    projection_rows: Any = None,
    projection_mode: str = "emergency_proxy",
    projections_override: Any = None,
    candidates_override: Optional[Sequence[Dict[str, Any]]] = None,
    savant_batting_csv: Optional[str | Path] = None,
    savant_pitching_csv: Optional[str | Path] = None,
    fangraphs_pitching_csv: Optional[str | Path] = None,
    platoon_order_by_player_id: Optional[Mapping[str, int]] = None,
    f4_by_player_id: Optional[Mapping[str, float]] = None,
    f1_by_player_id: Optional[Mapping[str, float]] = None,
    f5_by_player_id: Optional[Mapping[str, float]] = None,
    apply_value_sanity_guard: bool = True,
    confirmed_hitter_ids: Optional[Iterable[str]] = None,
    confirmed_teams: Optional[Iterable[str]] = None,
    pitcher_roles: Optional[Mapping[str, str]] = None,
    excluded_player_ids: Optional[Iterable[str]] = None,
    portfolio_controls_override: Optional[Mapping[str, Any]] = None,
    workflow_gates: Optional[Mapping[str, Any]] = None,
    assume_gates: Optional[Sequence[str]] = None,
    requested_n: Optional[int] = None,
    archetypes_path: Optional[str] = None,
    approve: bool = False,
    light_satellite: bool = False,
    apply_script_routing: bool = False,
    scanner_flagged_games: Optional[Sequence[str]] = None,
    source_metadata: Optional[Mapping[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    bank_time_budget_s: Optional[float] = None,
    solver_time_limit_s: Optional[float] = None,
    plan_solve_budget_s: Optional[float] = None,
) -> Dict[str, Any]:
    """Single front door: raw slate inputs -> certified DKEntries file plus diagnostics.

    With ``approve=False`` (default) this assembles the projection frame, derives
    entry requirements and contest postures, and returns the pre-build checkpoint
    plan WITHOUT building the candidate bank or running the allocation, so a
    construction error is caught before the expensive solve. With ``approve=True``
    it builds the bank (unless ``candidates_override`` is supplied) and runs the
    existing certified ``execute_portfolio`` path. ``light_satellite`` skips only
    the optional bank-coverage solve; the run directory, final-export re-read, and
    blank-reserved-row block are always retained.

    STRATEGY_DEFAULTS feeding the checkpoint and controls are principled priors,
    not calibrated values, and are never to be read as win rates or ROI.

    ``waterfall`` is the optional, already-computed result of
    ``mlb_engine.allocate.posture_allocator.allocate`` (a review-only companion
    OUTSIDE the audited engine, ledger 3.9). When supplied it is rendered as a
    first-class checkpoint block with a derived candidate-bank coverage target
    that, on approve=True, drives build_diverse_candidate_bank (auto-bank path).
    It is inert data: run_slate never imports or runs the allocator, and the
    coverage target only applies through the checkpoint the operator approves.

    ``solver_time_limit_s`` bounds each individual MILP solve (v3.20 / F13).
    A solve that hits it is recorded as a timeout and never triggers a
    relaxation ladder, because a compute limit is not a strategy decision.
    """
    from mlb_engine.entries.dk_entries_manager import parse_dk_entry_rows
    from mlb_engine.optimize.optimizer_v3 import (
        build_candidate_lineup_bank, build_diverse_candidate_bank,
        runtime_preflight, validate_projection_schema,
    )

    # Pulled out of ``metadata`` before it reaches create_run: metadata is
    # serialised into the run manifest, and these carry pair counts keyed on
    # frozensets that json cannot encode as keys.
    metadata = dict(metadata or {})
    caller_bank_diagnostics = metadata.pop("bank_diagnostics", None)
    caller_bank_warnings = metadata.pop("bank_warnings", None)

    entry_rows = parse_dk_entry_rows(str(entries_csv))
    reserved = [r for r in entry_rows]
    posture_by_contest = _resolve_contest_postures(reserved, contest_postures, archetypes_path)
    contest_identity_blockers = unresolved_contest_blockers(posture_by_contest)

    if projections_override is not None:
        projections = projections_override.copy() if hasattr(projections_override, "copy") else projections_override
        if hasattr(projections, "columns") and "Ownership_Tier" not in projections.columns:
            projections["Ownership_Tier"] = "Mid"
        projection_enrichment: Dict[str, Any] = {
            "xwoba": None, "ceiling": None, "value_guard": None, "f4": None,
            "f1": None, "f5": None, "pitcher_ceiling": None,
            "warnings": [],
            "note": "projections_override path; assembly enrichments (xwOBA, ceiling, "
                    "pitcher ceiling, value guard, F4 map) are not applied to a "
                    "prebuilt frame",
        }
    else:
        projections, projection_enrichment = _assemble_projection_frame(
            salary_csv, projection_rows, projection_mode,
            savant_batting_csv, savant_pitching_csv, source_metadata,
            projected_order_by_player_id=platoon_order_by_player_id,
            f4_by_player_id=f4_by_player_id,
            f1_by_player_id=f1_by_player_id,
            f5_by_player_id=f5_by_player_id,
            apply_value_sanity_guard=apply_value_sanity_guard,
            fangraphs_pitching_csv=fangraphs_pitching_csv,
        )

    projected_order_applied: list[str] = []
    if platoon_order_by_player_id and hasattr(projections, "columns") and "Notes" in projections.columns:
        mask = projections["Notes"].astype(str).str.contains("platoon_order", na=False)
        projected_order_applied = [str(p) for p in projections.loc[mask, "Player_ID"].tolist()]
    projected_order = {
        "requested": len(dict(platoon_order_by_player_id or {})),
        "applied_count": len(projected_order_applied),
        "applied_player_ids": projected_order_applied,
        "note": "Projected batting order applied as Batting_Order + F2 to rows that "
                "lacked an order; projected only, never confirmed_teams. Applies on the "
                "projection_rows path, not when projections_override is supplied."
                if platoon_order_by_player_id else "no projected order supplied",
    }

    schema = validate_projection_schema(projections)
    preflight = runtime_preflight()

    entry_requirements = [
        {
            "entry_id": str(r.entry_id),
            "contest_id": str(r.contest_id),
            "contest_name": r.contest_name,
            "contest_shape": posture_by_contest.get(str(r.contest_id), {}).get("contest_shape", "large_field_gpp"),
        }
        for r in reserved
    ]

    checkpoint = build_checkpoint_plan(
        entry_requirements, posture_by_contest, bank_coverage=None,
        projections=projections, scanner_flagged_games=scanner_flagged_games,
        archetypes_path=archetypes_path,
    )
    enrichment_warnings = list(projection_enrichment.get("warnings") or [])
    if enrichment_warnings:
        existing = list(checkpoint.get("warnings") or [])
        checkpoint["warnings"] = existing + [f"projection_enrichment: {w}" for w in enrichment_warnings]
    fill_depth_plan = checkpoint.get("fill_depth_plan")

    # v1.8 feasibility-aware control resolution. Floor the tightest-merged repetition
    # caps to a slate-feasible minimum before applying the explicit override, so a
    # mixed portfolio does not inherit an infeasible cap; the explicit override still
    # wins. Then assert feasibility of the resolved controls on the checkpoint.
    feasibility_inputs = _slate_feasibility(
        posture_by_contest, entry_requirements, projections, excluded_player_ids
    )
    merged_default = _merged_controls_for_build(posture_by_contest, None)
    floors = feasibility_floors_from(feasibility_inputs)
    controls = _merged_controls_for_build(
        posture_by_contest, portfolio_controls_override, feasibility_floors=floors
    )

    override_keys = set(dict(portfolio_controls_override or {}).keys())
    controls_feasibility: Dict[str, Any] = {"floors_applied": {}, "notes": []}
    for key, floor_val in floors.items():
        base = merged_default.get(key)
        final = controls.get(key)
        if base is None or final is None:
            continue
        if key in override_keys:
            controls_feasibility["notes"].append(
                f"{key}: explicit override {final} used (feasibility floor was {floor_val}, "
                f"merged default {base})"
            )
        elif float(final) > float(base):
            controls_feasibility["floors_applied"][key] = {
                "from_merged_default": base, "raised_to": final, "reason": "feasibility floor",
            }

    # F15: the exclusion set now reaches the bank build, so the checkpoint says
    # so before the build rather than after. An exclusion that names nobody in
    # the pool is a blocker at approve=False: it means the ID is wrong, and
    # discovering that at the export gate costs the whole build.
    exclusion_block = _exclusion_block(projections, excluded_player_ids)
    checkpoint["exclusions"] = exclusion_block
    if exclusion_block.get("blockers"):
        existing = list(checkpoint.get("warnings") or [])
        checkpoint["warnings"] = existing + [
            f"exclusions: {b}" for b in exclusion_block["blockers"]
        ]

    feasibility_report = _feasibility_report(feasibility_inputs, controls)
    checkpoint["feasibility"] = {
        **feasibility_report,
        "inputs": feasibility_inputs,
        "controls_feasibility": controls_feasibility,
    }
    binding = feasibility_report.get("binding_constraints") or []
    if binding:
        existing = list(checkpoint.get("warnings") or [])
        checkpoint["warnings"] = existing + [f"feasibility: {b}" for b in binding]

    # v1.10 waterfall tier policy as a first-class checkpoint block. Review-only:
    # the supplied ``waterfall`` is inert data from the posture_allocator companion
    # (never imported here). The derived coverage target is shown here and, on
    # approve=True with a waterfall supplied, drives build_diverse_candidate_bank
    # (below). Uses the feasibility inputs computed above for viable SP-pair capacity.
    checkpoint["waterfall"] = build_waterfall_block(
        waterfall, entry_requirements, feasibility_inputs
    )
    wf_block = checkpoint["waterfall"]
    if wf_block.get("available"):
        wf_flags = list(wf_block.get("policy_checks") or []) + list(wf_block.get("warnings") or [])
        if wf_flags:
            existing = list(checkpoint.get("warnings") or [])
            checkpoint["warnings"] = existing + [f"waterfall: {w}" for w in wf_flags]

    # v1.9 slate clock: first lock and the T-minus-5 delivery deadline, visible
    # at every checkpoint so the session budgets from the deadline instead of
    # discovering it. Deterministic bookkeeping, never a guarantee.
    try:
        from mlb_engine.intake.slate_intake_manager import slate_clock as _slate_clock
        clock = _slate_clock(salary_csv=str(salary_csv))
    except Exception as exc:
        clock = {"available": False, "note": f"slate clock unavailable: {exc}"}
    checkpoint["slate_clock"] = clock
    if clock.get("available"):
        mins = clock.get("minutes_to_deadline")
        clock_warnings = list(checkpoint.get("warnings") or [])
        if clock.get("past_deadline"):
            clock_warnings.append(
                f"slate_clock: past the T-{clock.get('buffer_minutes', 5)} delivery deadline "
                f"({clock.get('deadline_utc')}); ship the best certified file immediately"
            )
        elif mins is not None and mins < 15:
            clock_warnings.append(
                f"slate_clock: {mins} minutes to the T-{clock.get('buffer_minutes', 5)} "
                f"delivery deadline; skip all optional steps"
            )
        checkpoint["warnings"] = clock_warnings

    # F4: six of the eight pre-export gates used to default to True with a static
    # "caller_asserted" label, and no production caller ever supplied
    # ``workflow_gates``. validate_upload_ready_gates only fails a gate that is
    # present-and-falsy or absent, so the axis always passed and ``workflow_valid``
    # was computed from constants. "Upload-ready" is defined as all three gates
    # passing; if six inputs to that definition are literals, the label carries no
    # information, which is how a 23-team 0/9 build read certified on 07-22.
    #
    # Each of the six is now derived from work this function has already done, or
    # left None. None means missing, and missing blocks.
    derived_gates, gate_evidence = _derive_workflow_gates(
        schema=schema,
        entry_requirements=entry_requirements,
        posture_by_contest=posture_by_contest,
        projected_order=projected_order,
        pitcher_roles=pitcher_roles,
        projection_enrichment=projection_enrichment,
        pool_report=(source_metadata or {}).get("pool_report"),
    )
    gate_defaults = {
        **derived_gates,
        "projection_schema_gate_passed": bool(schema.get("passed")),
        "optimizer_gate_passed": bool(preflight.get("optimizer_certifiable")),
    }
    supplied = dict(workflow_gates or {})
    # The T-5 fast path. An assumed gate certifies, and the assumption is written
    # verbatim into the artifact, so the file states which checks were skipped
    # rather than implying they ran.
    assumed = sorted({str(x) for x in (assume_gates or [])} & set(derived_gates))
    gates = {**gate_defaults, **supplied}
    for name in assumed:
        if gates.get(name) is None:
            gates[name] = True
    gates = {k: v for k, v in gates.items() if v is not None}
    # Only the gates a caller actually supplied are caller-asserted. The label
    # used to name six gates nobody had asserted.
    caller_asserted = sorted(set(supplied) & set(PRE_EXPORT_GATE_NAMES))

    base_payload = {
        "checkpoint_plan": checkpoint,
        "projection_schema": schema,
        "optimizer_preflight": preflight,
        "entry_requirements": entry_requirements,
        "posture_by_contest": posture_by_contest,
        "merged_controls": controls,
        "controls_feasibility": controls_feasibility,
        "feasibility": checkpoint["feasibility"],
        "exclusions": exclusion_block,
        "slate_clock": clock,
        "waterfall": checkpoint.get("waterfall"),
        "caller_asserted_gates": caller_asserted,
        "workflow_gate_evidence": gate_evidence,
        "assumed_gates": assumed,
        "contest_identity_blockers": contest_identity_blockers,
        "strategy_defaults_are_priors": True,
        "projected_order": projected_order,
        "projection_enrichment": projection_enrichment,
        "light_satellite": bool(light_satellite),
    }

    if not schema.get("passed"):
        return {"passed": False, "status": "blocked", "approved": bool(approve),
                "errors": [f"projection schema failed: {schema}"], **base_payload}

    # Wrong-contest identity is a HARD gate: it is decidable from disk in under a
    # second, it changes the objective the whole portfolio is built to, and it is
    # invisible in the certified output. It has no override, because the fix is a
    # single flag on the same command and takes less time than an override would.
    if approve and contest_identity_blockers:
        return {"passed": False, "status": "blocked", "approved": True,
                "errors": contest_identity_blockers, **base_payload}

    if not approve:
        # R28(1): the plan-mode joint-allocation verdict. Everything above this
        # line is pool arithmetic, and pool arithmetic provably cannot see an
        # interaction that lives in the bank, so the checkpoint solves the same
        # MILP the build will solve and reports what it found. Placed after the
        # schema gate so a blocked plan never pays for a solve, and inside the
        # not-approve branch so approve=True is byte-identical to pre-v1.15.
        shape_counts_plan: Dict[str, int] = {}
        for req in entry_requirements:
            shape_counts_plan[req["contest_shape"]] = shape_counts_plan.get(req["contest_shape"], 0) + 1
        joint = _plan_joint_allocation(
            projections, entry_requirements, controls,
            budget_s=(PLAN_SOLVE_BUDGET_S if plan_solve_budget_s is None
                      else float(plan_solve_budget_s)),
            candidates_override=candidates_override,
            excluded_player_ids=[str(x) for x in (excluded_player_ids or [])],
            requested_n=int(requested_n or max(len(entry_requirements), 1)),
            contest_shapes=sorted(shape_counts_plan) or None,
            solver_time_limit_s=solver_time_limit_s,
        )
        checkpoint["joint_allocation"] = joint
        if joint.get("verdict") != "would_certify":
            existing = list(checkpoint.get("warnings") or [])
            checkpoint["warnings"] = existing + [f"joint_allocation: {joint['summary']}"]
        # A plan that predicts refusal still returns passed=True: this is the
        # review checkpoint, not a gate, and its job is to say what the build
        # would do, not to pre-empt the operator's decision to run it.
        return {"passed": True, "status": "plan_pending_approval", "approved": False,
                "joint_allocation": joint,
                "note": "review the checkpoint_plan and re-run with approve=True to build", **base_payload}

    if candidates_override is not None:
        candidates = list(candidates_override)
        bank_diag: Dict[str, Any] = {"source": "candidates_override", "candidate_count": len(candidates)}
    else:
        shape_counts: Dict[str, int] = {}
        for req in entry_requirements:
            shape_counts[req["contest_shape"]] = shape_counts.get(req["contest_shape"], 0) + 1
        dominant_shape = max(shape_counts, key=shape_counts.get) if shape_counts else "large_field_gpp"
        # R1a: construction mode is a separate axis from the ranking objective,
        # and R1 moves only the second. A satellite now resolves to the
        # `satellite` shape instead of `large_wta`; reading that off a literal
        # tuple would have flipped it from wta to gpp construction, which moves
        # the DU threshold row (_resolve_du_threshold_row keys on mode) as a
        # side effect of a scoring fix. WTA_CONSTRUCTION_SHAPES holds the
        # satellite family, so the bank is built exactly as it was.
        mode = "wta" if dominant_shape in WTA_CONSTRUCTION_SHAPES else "gpp"
        n = int(requested_n or max(len(entry_requirements), 1))
        # v1.10: when a waterfall is supplied, the tier-derived coverage target from the
        # checkpoint (exactly the value displayed for review) drives the bank's
        # coverage_target on this auto-bank path. With no waterfall it stays None and the
        # call is byte-identical to pre-v1.10. Deterministic review input, never a claim.
        wf_block = checkpoint.get("waterfall") or {}
        wf_cov = wf_block.get("coverage_target") if wf_block.get("available") else None
        wf_coverage_target = (
            int(wf_cov["coverage_target"]) if wf_cov and wf_cov.get("coverage_target") else None
        )
        # F15: excluded_player_ids reached validation and the feasibility block
        # but never the bank build. At T-10 that spends the entire remaining
        # budget generating lineups around a player who should have been
        # dropped, and the mistake surfaces only at the export gate with no time
        # left to rebuild. Excludes go in two ways because the optimizer honors
        # both and they cover different paths: the ``Excluded`` column is read by
        # _prepare_single_lineup_df on every solve including the augmentation
        # pass, and the ``excludes`` kwarg is read by the anchor-cap and
        # stackable-team helpers that size the bank.
        bank_excludes = [str(x) for x in (excluded_player_ids or [])]
        bank_projections = projections
        if bank_excludes and hasattr(projections, "columns"):
            bank_projections = projections.copy()
            if "Excluded" not in bank_projections.columns:
                bank_projections["Excluded"] = False
            mask = bank_projections["Player_ID"].astype(str).isin(set(bank_excludes))
            bank_projections.loc[mask, "Excluded"] = True
        bank = build_diverse_candidate_bank(
            bank_projections, requested_n=n, mode=mode, target="ceiling",
            contest_shapes=sorted(shape_counts) or None,
            max_sp_pair_repetition=controls.get("max_sp_pair_repetition"),
            coverage_target=wf_coverage_target,
            time_budget_s=bank_time_budget_s,
            solver_time_limit_s=solver_time_limit_s,
            excludes=bank_excludes or None,
        )
        candidates = _bank_records_to_candidates(bank.get("candidate_lineups") or [])
        bank_diag = {
            "source": "build_diverse_candidate_bank", "mode": mode, "requested_n": n,
            "candidate_count": len(candidates),
            "excluded_player_ids_applied": bank_excludes,
            "solver_report": bank.get("solver_report"),
            "waterfall_coverage_target": wf_coverage_target,
            "contest_shape_profile": bank.get("contest_shape_profile"),
            "diversity_augmentation": bank.get("diversity_augmentation"),
            # F11: the facts post-slate review needs, carried from the solver
            # rather than discarded at this boundary.
            "relaxations": bank.get("relaxations"),
            "failed_indices": list(bank.get("failed_indices") or []),
            "du_validation": bank.get("du_validation"),
            "anchor_validation": bank.get("anchor_validation"),
            "sp_pair_coverage_validation": bank.get("sp_pair_coverage_validation"),
            "budget": bank.get("budget"),
        }

    if apply_script_routing and fill_depth_plan is not None:
        routing = emit_contest_routing(fill_depth_plan, candidates, entry_requirements)
        allowed_map = routing.get("allowed_candidate_ids_by_entry") or {}
        for req in entry_requirements:
            ids = allowed_map.get(str(req.get("entry_id")))
            if ids:
                req["allowed_candidate_ids"] = list(ids)
        script_routing = {"applied": True, **routing}
    else:
        script_routing = {"applied": False, "allowed_candidate_ids_by_entry": {}, "warnings": []}

    bank_player_coverage = audit_bank_player_coverage(candidates, projections)

    result = run_initial_build(
        runs_root=runs_root, salary_csv=salary_csv, entries_csv=entries_csv,
        projections=projections, candidates=candidates,
        entry_requirements=entry_requirements, workflow_gates=gates,
        portfolio_controls=controls,
        confirmed_hitter_ids=confirmed_hitter_ids, confirmed_teams=confirmed_teams,
        pitcher_roles=pitcher_roles, excluded_player_ids=excluded_player_ids,
        metadata={**(metadata or {}), "front_door": "run_slate",
                  "front_door_version": VERSION,
                  "workflow_gate_evidence": gate_evidence,
                  "assumed_gates": assumed,
                  "caller_asserted_gates": caller_asserted,
                  },
        # When candidates were handed in, run_slate did not build the bank and
        # has nothing to say about how they were produced. The caller does, so
        # the caller's record wins rather than being overwritten with the word
        # "candidates_override".
        bank_diagnostics={
            **dict(caller_bank_diagnostics or {}),
            **{k: v for k, v in (bank_diag or {}).items()
               if candidates_override is None or k == "candidate_count"},
        },
        bank_warnings=(
            list(caller_bank_warnings or [])
            + list(((bank_diag or {}).get("relaxations") or {}).get("warnings") or [])),
        compute_bank_coverage=not light_satellite,
    )
    result.update({
        "approved": True,
        "checkpoint_plan": checkpoint,
        "projection_schema": schema,
        "posture_by_contest": posture_by_contest,
        "merged_controls": controls,
        "controls_feasibility": controls_feasibility,
        "feasibility": checkpoint["feasibility"],
        "exclusions": exclusion_block,
        "slate_clock": clock,
        "candidate_bank": bank_diag,
        "bank_player_coverage": bank_player_coverage,
        "script_routing": script_routing,
        "fill_depth_plan": fill_depth_plan,
        "projected_order": projected_order,
        "projection_enrichment": projection_enrichment,
        "caller_asserted_gates": caller_asserted,
        "workflow_gate_evidence": gate_evidence,
        "assumed_gates": assumed,
        "contest_identity_blockers": contest_identity_blockers,
        "strategy_defaults_are_priors": True,
        "light_satellite": bool(light_satellite),
    })
    result["delivered_path"] = mirror_to_outputs(result, salary_csv)
    # Repo-relative alongside the absolute path: every recorded delivered_path in
    # outputs/2026-07-25/ pointed at a session mount that no longer exists.
    if result.get("delivered_path"):
        try:
            from mlb_engine.entries.upload_manifest import repo_relative, sha256_file
            result["delivered_path_repo"] = repo_relative(result["delivered_path"])
            result["delivered_sha256"] = sha256_file(result["delivered_path"])
        except Exception:  # noqa: BLE001
            pass
    return result


def mirror_to_outputs(result: Mapping[str, Any], salary_csv: Any) -> Optional[str]:
    """Copy a promoted export to outputs/<date>/ and return the path.

    CLAUDE.md states deliverables land in outputs/<date>/ with exact paths, but the
    engine only ever wrote runs/<run_id>/final/, so every slate ended with a manual
    copy. The run directory stays immutable and stays the source for the
    post-export gate re-read; this is a mirror, never the certified artifact.
    """
    output_path = result.get("output_path")
    if not output_path or not result.get("passed"):
        return None
    try:
        from mlb_engine.intake.slate_intake_manager import (
            parse_dk_salary_csv, parse_game_info_datetime,
        )

        slate_date = None
        for sp in parse_dk_salary_csv(str(salary_csv)):
            parsed = parse_game_info_datetime(sp.game_info)
            if parsed is not None:
                slate_date = parsed.date().isoformat()
                break
        if slate_date is None:
            return None
        source = Path(output_path)
        dest_dir = Path(__file__).resolve().parents[2] / "outputs" / slate_date
        dest_dir.mkdir(parents=True, exist_ok=True)
        # The delivered name carries the slate tag. DK runs several draftgroups on
        # most dates and this mirror wrote one name per contest type, so the
        # second build of the day silently replaced the first one's delivered
        # file while both briefs went on citing the same path.
        tag = _slate_tag(salary_csv)
        stem = source.stem
        dest = dest_dir / (f"{stem}_{tag}{source.suffix}" if tag and not stem.endswith(tag)
                           else source.name)
        dest.write_bytes(source.read_bytes())
        recorded = _record_upload_manifest(slate_date, dest, result, tag)
        # R3(a). Generation stays fail-open, because bookkeeping must never break
        # a certified build. What was wrong was that it also failed SILENT: a
        # file could land in outputs/ with no manifest row and nothing said so,
        # which re-opens exactly the "which file do I upload" hole the manifest
        # was built to close. Say it, loudly, and carry the flag on the payload.
        if isinstance(result, dict):
            result["manifest_recorded"] = bool(recorded)
        if not recorded:
            print(f"MANIFEST NOT RECORDED  {dest} was delivered with no manifest "
                  f"row. Preflight will hard-fail it; re-run the build or pass "
                  f"--no-manifest deliberately.")
        return str(dest)
    except Exception:  # noqa: BLE001 - a mirror must never fail a certified build
        if isinstance(result, dict):
            result.setdefault("manifest_recorded", False)
        return None


def _slate_tag(salary_csv: Any) -> str:
    """'1605_4g': first lock in ET plus game count. Identifies the draftgroup."""
    try:
        from mlb_engine.intake.slate_intake_manager import (
            parse_dk_salary_csv, parse_game_info_datetime,
        )
        games, starts = set(), []
        for sp in parse_dk_salary_csv(str(salary_csv)):
            info = getattr(sp, "game_info", "") or ""
            gid = str(getattr(sp, "game_id", "") or info.split(" ", 1)[0] or "").strip()
            if gid:
                games.add(gid)
            parsed = parse_game_info_datetime(info)
            if parsed is not None:
                starts.append(parsed)
        if not starts or not games:
            return ""
        return f"{min(starts).strftime('%H%M')}_{len(games)}g"
    except Exception:  # noqa: BLE001
        return ""


def manifest_projection_tier(result: Mapping[str, Any]) -> str:
    """'enriched' when any enrichment map actually reached rows, else 'proxy'.

    R3(c). The backlog specified deriving this from ``enrichment.signal_applied``;
    no such key exists on this tree. The enrichment blocks each carry
    ``requested`` and ``applied_count``, and ``_applied`` is already the helper
    that reads them, so the tier is derived from those instead. A build whose
    projections were handed in prebuilt has no enrichment at all and is 'proxy'.
    """
    enrichment = result.get("projection_enrichment") or {}
    for key in ("xwoba", "ceiling", "value_guard", "f4", "f1", "f5", "pitcher_ceiling"):
        if _applied(enrichment.get(key)):
            return "enriched"
    return "proxy"


def manifest_strategy_state(result: Mapping[str, Any]) -> Dict[str, Any]:
    """'clean' only when nothing was relaxed to make the portfolio fit.

    R3(c). A relaxed portfolio and a clean one are different artifacts and the
    difference lived in prose in the brief. It belongs on the record.
    """
    relaxations = ((result.get("bank_diagnostics") or {}).get("relaxations") or {})
    counts = {k: v for k, v in relaxations.items()
              if isinstance(v, int) and k != "note" and v}
    warnings = list(relaxations.get("warnings") or [])
    state = "relaxed" if (counts or warnings) else "clean"
    return {"state": state, "counts": counts, "warnings": warnings[:10]}


def _record_upload_manifest(slate_date: str, dest: Path, result: Mapping[str, Any],
                            tag: str) -> bool:
    """One manifest record per delivery, so T-5 never has to guess which file.

    Returns whether the record was written. The caller says so out loud when it
    was not; see mirror_to_outputs.
    """
    try:
        from mlb_engine.entries.upload_manifest import record_delivery

        contests = (result.get("posture_by_contest") or {})
        # Counted off the delivered file, not off an upstream plan: the count
        # preflight cross-checks has to be a fact about these bytes, because
        # catching a truncated write is exactly what it is for.
        from mlb_engine.entries.dk_entries_manager import parse_dk_entry_rows
        entries_in_file = len(parse_dk_entry_rows(dest))
        record_delivery(
            date=slate_date,
            delivered_file=dest,
            contest_type="classic",
            slate_tag=tag,
            contest_ids=sorted(contests),
            contest_names=sorted(
                str(v.get("contest_name") or "") for v in contests.values()),
            entries=entries_in_file,
            run_id=result.get("run_id"),
            status="candidate",
            certification="certified" if result.get("workflow_valid") else "not_certified",
            projection_tier=manifest_projection_tier(result),
            strategy_state=manifest_strategy_state(result),
        )
        return True
    except Exception:  # noqa: BLE001 - bookkeeping must never fail a certified build
        return False
