"""Canonical MLB Classic execution pipeline (MLB Classic v2.26.0).
VERSION is the authoritative version constant for this module.

Initial builds and late swaps share one immutable, hash-bound production path.
The exact final DKEntries file is re-read to derive all post-export gates.

v1.17 changes (R126):
- ``compute_portfolio_frontier`` measures both ends of the stated dual
  objective over the ENTERED set, off the run's own ``Ceiling`` column: apex
  (portfolio ceiling total, mean, best single entry) and washout (per game,
  zero that game's hitters, keep the arms, report the percent of portfolio
  ceiling retained plus a histogram over entries of bats drawn from it). The
  block reaches ``diagnostics.json`` and BOTH success return paths as
  ``portfolio_frontier``. A counterfactual over data already in hand, so it
  costs no solve; wrapped so it can never block a run.

v1.16 changes (R98(2)):
- ``run_initial_build`` passes its merged ``bank_diagnostics`` to
  ``select_and_assign_entries`` as ``bank_report``. A proven-infeasible joint
  allocation against a bank whose ``job_list_exhausted`` is False now returns
  ordered remedies naming bank growth first. The plan path is deliberately NOT
  threaded: ``_plan_joint_allocation`` already returns ``unchecked`` and never
  solves when its own plan bank did not exhaust its job list, so a report there
  would describe a bank that never reached the solver.

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
import math
import shutil
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple

import pandas as pd

from mlb_engine.pipeline.build_state_manager import (
    create_run, promote_run, read_pointer_sha256, register_artifact,
    sha256_file, snapshot_run_inputs, update_run_certification,
)
from mlb_engine.allocate.contest_allocator import (
    CONSENSUS_CLUSTER_MIN_MEMBERS,
    TEAM_EXPOSURE_MIN_HITTERS, assert_fraction_cap, select_and_assign_entries,
)
from mlb_engine.contest_shapes import (
    SATELLITE_PAYOUT_TOKENS, SATELLITE_TYPE_TOKENS, WTA_CONSTRUCTION_SHAPES,
    satellite_shape_for, validate_shape,
)
from mlb_engine.entries.dk_entries_manager import (
    derive_workflow_certification, fixed_portfolio_exposure,
    reconcile_entries_against_assignments,
    validate_dk_entries_file, validate_template_preservation,
    validate_upload_ready_gates, write_candidate_from_template,
)
from mlb_engine.swap.late_swap_manager import (
    PlayerLineupStatus, build_entry_requirements, late_swap_certification,
    load_latest_valid_parent_run, validate_late_swap_delta,
)

VERSION = "v1.17"

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
    # R112: the slate-level capacity _slate_feasibility already computed at the
    # checkpoint, threaded through so a proven-infeasible refusal can name the
    # bank as the limiter when the slate itself supports more than the bank
    # sampled. Advisory; omitting it costs nothing.
    feasibility_inputs: Optional[Mapping[str, Any]] = None,
    # R286: the checkpoint's already-computed feasibility VERDICTS, so a
    # proven-infeasible refusal leads with the slate-level check that failed
    # instead of with a count over the bank. Advisory; omitting it restores the
    # pre-R286 message exactly.
    feasibility_checks: Optional[Sequence[Mapping[str, Any]]] = None,
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

    # R61: on a late swap the solve is handed a SUBSET of the file's complete
    # rows, and the export validator grades all of them. Hand the allocator what
    # the rows it cannot touch already hold so both ends resolve the same caps
    # against the same denominator.
    #
    # Late swap only, deliberately. On an initial build from a reserved template
    # the authorized set and the complete-row set are the same set, so there is
    # nothing to offset and passing None keeps the build byte-identical (the R28
    # precedent). `preserve_completed=True` below means an initial build CAN in
    # principle carry completed rows outside the requirements; that case is
    # filed as R61-tail rather than changed silently here.
    fixed_exposure = None
    if mode == "late_swap":
        fixed_exposure = fixed_portfolio_exposure(
            entries_csv,
            [str(req["entry_id"]) for req in entry_requirements],
            salary_csv_path=salary_csv,
            # R343 + R61. The offset has to be counted at the SAME threshold the
            # cap is enforced at, or the untouched rows are subtracted from a
            # cap they were never measured against.
            team_exposure_min_hitters=controls.get("team_exposure_min_hitters"),
        )
    # R98(2): the bank record travels with the candidates it produced. The
    # allocator can prove infeasibility against a bank; it cannot see whether
    # that bank was a completed search or a slice, and that difference decides
    # whether the honest remedy is another slice or a control change.
    allocation = select_and_assign_entries(
        candidates, entry_requirements, controls, bank_report=bank_diagnostics,
        fixed_exposure=fixed_exposure, feasibility_inputs=feasibility_inputs,
        feasibility_checks=feasibility_checks)
    if not allocation.get("passed"):
        diagnostics = {
            "run_id": run["run_id"], "mode": mode, "allocation": allocation,
            "diagnostic_source_file": "", "diagnostic_source_sha256": "",
            "workflow_valid": False,
        }
        return _blocked_result(run, allocation.get("errors", ["allocation failed"]), diagnostics)

    bank_coverage = _bank_coverage(projections, candidates) if compute_bank_coverage else None

    assignments = allocation["assignments"]
    # R126. Both ends of the stated objective, over the set that is actually
    # being entered rather than over the bank. Computed here because this is the
    # first point where the entered set exists and the projections are still in
    # hand; a caller writing the brief would otherwise have to re-join the export
    # against projections.csv, which is exactly what BUILD did by hand.
    portfolio_frontier = _portfolio_frontier(projections, assignments)
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
        # R126. In the immutable run record, beside bank_coverage, because "how
        # concentrated was the set we entered" is a question asked weeks later
        # and the answer has to survive without the projections frame.
        "portfolio_frontier": portfolio_frontier,
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
            # R116. Rides beside bank_coverage for the same reason it does: the
            # fact lives in diagnostics.json, and a caller writing a brief should
            # not have to re-open the run directory to state how many distinct
            # lineups it just delivered and what capped them.
            "candidate_reuse": allocation.get("candidate_reuse"),
            "candidate_reuse_counts": allocation.get("candidate_reuse_counts"),
            # R298(a). The allocator's other two ladders, beside the first, so
            # `manifest_strategy_state` can read all three off the result. The
            # allocator emits each only when its control was requested.
            "primary_stack_floor": allocation.get("primary_stack_floor"),
            "five_stack_quota": allocation.get("five_stack_quota"),
            # R126, same reasoning, and the same requirement that BOTH return
            # paths carry it: a late swap that lost the block would report a
            # refined portfolio with no concentration facts at all.
            "portfolio_frontier": portfolio_frontier,
            # R405. The allocator's consensus-cluster block, on both return
            # paths for R126's reason.
            "consensus_cluster": allocation.get("consensus_cluster"),
            # R406, the same.
            "classic_sleeves": allocation.get("classic_sleeves"),
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
        # R116, see the deferred branch above.
        "candidate_reuse": allocation.get("candidate_reuse"),
        "candidate_reuse_counts": allocation.get("candidate_reuse_counts"),
        # R298(a), see the deferred branch above.
        "primary_stack_floor": allocation.get("primary_stack_floor"),
        "five_stack_quota": allocation.get("five_stack_quota"),
        # R126, see the deferred branch above.
        "portfolio_frontier": portfolio_frontier,
        # R405, see the deferred branch above.
        "consensus_cluster": allocation.get("consensus_cluster"),
        # R406, the same.
        "classic_sleeves": allocation.get("classic_sleeves"),
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
#
# R37 stage 1, Ben's dated decision of 2026-08-09: `primary_stack_min_size` is 4
# on EVERY posture, cash included. It is the one construction number here with
# an archive behind it rather than a principle, and it is stated once so the six
# copies below are not read as six separate opinions. Three independent tranches
# put the `<=3-primary` family negative -- -2.8pp [-3.8,-1.8] combined over the
# first two, -9.8pp [-18.0,-1.6] on the third -- while our own share of that
# family climbed 7.0% -> 21.5% -> 26.3%. The 2026-08-05 feasibility probe
# (`tools/stack_shape_probe.py`) priced the floor at 0.00-0.76% of the
# unconstrained objective across slates from 3 to 8 games and found a 5-primary
# lineup feasible on 100% of stackable teams at every width, so the constraint
# is close to free and the family it removes is the one the archive is firmest
# about. Those are observed outcomes and deterministic review proxies; none of
# it is a win rate, a cash rate, or a probability claim.
#
# What is deliberately NOT here, per the same decision: the floor of 5 on
# narrow-breadth postures waits for one measured tranche, the 4-2-x secondary
# cap is deferred and sized separately after this lands, no contrarian push is
# added on top, and the salary-left gap is left alone.

# R343, 2026-09-15. `max_team_exposure_pct` caps a team's footprint over EVERY
# hitter slot, whatever stack role the optimizer labelled it, where
# `max_primary_stack_exposure_pct` counts the primary stack alone. Measured on
# 1310_9g (9 games, 21 entries): NYY in 15 of 21 entries and 17 of 21 after the
# rebuild, entirely through SECONDARY stacks, with no control binding and no
# line in the brief reporting it.
#
# How these five numbers were chosen, because "posture-sized like the other
# caps" is a shape and not a value. Each sits about 0.20 above that posture's
# `max_primary_stack_exposure_pct`, which is the smallest gap that leaves the
# primary cap as the binding one on an ordinary build -- a team's footprint is
# a superset of its primary-stack share by construction, so a value at or near
# the primary cap would be a second primary cap wearing a different name and
# would bind on builds that have nothing wrong with them.
#
# Arithmetic safety, stated rather than assumed. A DK Classic lineup holds eight
# hitters and at most five from one team, so every entry footprints at least two
# teams and some team must take ceil(2E / T) of E entries on a slate with T
# stackable teams. At 0.55 that needs T >= 4, which is two games. A one-game
# Classic slate (T = 2) floors arithmetically at 1.0, and
# `floor_team_exposure_pct` raises the cap to exactly that rather than letting a
# posture default refuse a slate it cannot fit -- the same mechanism that has
# carried `max_primary_stack_exposure_pct` through thin slates since v1.9.
#
# Truthful labels: these are deterministic portfolio-shape controls on the
# washout half of Ben's dual objective. Nothing here is a win rate, a cash rate,
# or a probability, and no archive number prices a team footprint -- the value
# is a decorrelation preference, and Ben's to move.
MAX_TEAM_EXPOSURE_NOTE = "R343: team footprint over all hitter slots, any role"

# R405, Ben's decisions of 2026-09-23. `max_consensus_cluster_share_pct` caps the
# share of entries whose lineup carries k = 3 or more members of the BANK's
# consensus cluster (every hitter in 15% or more of the distinct lineups the
# unconstrained search built, most-shared first, at most twelve). 0.50 on
# `wta_satellite`, `large_gpp`, `small_gpp` and `mme`; 1.0 on `single_entry`;
# `cash` declares no controls. MIN wins across a mixed entered set. On 1905_10g
# that is at most 17 of 34 lineups at 3+ of the ten, against 27 delivered.
#
# It needs lineups below k to choose from, and the ordinary bank holds almost
# none (6 of 408 on 1905_10g, 0 of 30 on the vendored 2026-06-03 slate), so it
# ships with cluster-limited bank jobs on every door
# (`resolve_consensus_limited_request`). A decorrelation preference over the
# washout half of the dual objective: nothing here is a win rate, a cash rate or
# a probability, and the value is Ben's to move.
MAX_CONSENSUS_CLUSTER_NOTE = ("R405: entries at k+ of the bank's consensus "
                              "hitters, capped per posture")

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
            "primary_stack_min_size": 4, "max_team_exposure_pct": 1.0,
            # R405: off at one entry, and MIN-merged, so it loosens nobody.
            "max_consensus_cluster_share_pct": 1.0,
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
            # R343, 2026-09-15. See MAX_TEAM_EXPOSURE_NOTE below for how these
            # five numbers were chosen and what they are not.
            "max_team_exposure_pct": 0.55,
            # R405, 2026-09-23. See MAX_CONSENSUS_CLUSTER_NOTE below.
            "max_consensus_cluster_share_pct": 0.50,
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
            "primary_stack_min_size": 4,
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
            "max_shared_players": 6, "primary_stack_min_size": 4,
            "max_team_exposure_pct": 0.75,
            "max_consensus_cluster_share_pct": 0.50,  # R405
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
            "max_shared_players": 6, "primary_stack_min_size": 4,
            "max_team_exposure_pct": 0.70,
            "max_consensus_cluster_share_pct": 0.50,  # R405
        },
        "note": "top-heavy field rewards a tight five-stack plus a secondary",
    },
    "mme": {
        "construction": "multi_wide",
        "objective": "ceiling",
        "entry_count_policy": "scale_to_bank_coverage",
        # R37, 2026-08-09. Was "five_three_with_diversification". The archive
        # contradicts the 5-3 half of that string in every slice measured: 5-3
        # is at-share on both the win line and the top decile, and the mini-MAX
        # slice this posture serves prefers the lone five (5-1-1-1, +3.6pp
        # [+1.4,+5.6] over 73,343 entries). The string was never read as a
        # constraint -- only _STACK_SIZE_BY_PLAN reads it, for the size 5, which
        # is unchanged -- so this is a label correction with no behavioural
        # effect, which is exactly why it was worth doing before it got wired to
        # something. The new name commits to the floor and stays silent about a
        # secondary size, because the secondary is R37's deferred half.
        "stack_plan": "tight_5_with_diversification",
        "decorrelation": "high",
        "controls": {
            "max_player_exposure_pct": 0.35, "max_pitcher_exposure_pct": 0.50,
            "max_primary_stack_exposure_pct": 0.45, "max_sp_pair_repetition": 3,
            "max_shared_players": 6, "primary_stack_min_size": 4,
            "max_team_exposure_pct": 0.65,
            "max_consensus_cluster_share_pct": 0.50,  # R405
        },
        "note": "wider exposure and higher decorrelation; deployed count scales with bank coverage",
    },
    "cash": {
        "construction": "not_recommended",
        "objective": "floor",
        "entry_count_policy": "none",
        "stack_plan": "none",
        "decorrelation": "none",
        "controls": {"primary_stack_min_size": 4},
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

# R133(4). Gates an explicit assumption may promote against a DERIVED FALSE, as
# opposed to against a None. Deliberately one entry, and deliberately not a
# knob: CLAUDE.md's autonomy section authorizes exactly one such assertion --
# "override a pool blocker whose shape you have classified benign, and assert
# `lineup_gate_passed` on that same evidence. Both together or neither" -- and
# every other gate on the list reads a fact the operator cannot have better
# evidence about than the file does. A salary schema failure is not a judgement
# call, so assuming past it would be a way to certify a broken CSV.
OVERRIDABLE_GATES = ("lineup_gate_passed",)


def caller_asserted_gates(supplied: Mapping[str, Any],
                          gates: Mapping[str, Any]) -> List[str]:
    """Which gate values in the final set came from the caller rather than evidence.

    F4 made this "only the gates a caller actually supplied"; the label had named
    six gates nobody had asserted.

    R176(b), 2026-08-30. It then filtered to ``PRE_EXPORT_GATE_NAMES``, the six
    DERIVED names, while ``run_slate`` merges ``{**gate_defaults, **supplied}`` and
    ``gate_defaults`` also carries ``projection_schema_gate_passed`` and
    ``optimizer_gate_passed``. A caller supplying either had it win the merge
    silently and never appear in ``caller_asserted_gates`` -- an unchecked
    assertion with no recorded escape hatch. Same class as a fabricated evidence
    string, with the falsehood in what the artifact OMITS.

    Derived from the merge RESULT, not from a list of names. A fourth hand-kept
    tuple is how R167 and R159 both went wrong, and the two that already exist
    disagree: ``dk_entries_manager.PRE_EXPORT_GATES`` holds nine, including
    ``selection_certified``, a certification this pipeline derives and no caller
    may assert. ``set(gates)`` is definitionally every name an assertion can
    reach, and it cannot drift from the merge it reads.

    Extracted from ``run_slate`` for the same reason ``resolve_gate_assertions``
    was: a test over a copy of the logic pins the copy.
    """
    return sorted(set(supplied or {}) & set(gates or {}))


def resolve_gate_assertions(
    gate_defaults: Mapping[str, Any],
    supplied: Mapping[str, Any],
    assume_gates: Optional[Sequence[str]],
    derived_gates: Mapping[str, Any],
    gate_evidence: Mapping[str, str],
) -> Tuple[Dict[str, Any], List[str], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Apply ``assume_gates`` and say which of three things each request was.

    Extracted from ``run_slate`` for R133(4) so a test can exercise the real
    merge. The first cut of that test reimplemented these fifteen lines and
    passed against two mutations of the lines it claimed to pin -- a test over a
    copy of the logic pins the copy.

    Returns ``(gates, assumed, overridden, refused)``.

    - ASSUMED: the evidence said nothing (None), so the caller supplies it. The
      T-5 fast path, unchanged since F4.
    - OVERRIDDEN: the evidence said False and the caller has read it and
      disagrees. Only ``OVERRIDABLE_GATES`` may be, and the record carries the
      evidence string being contradicted rather than just the gate name.
    - REFUSED: neither. Reported rather than silently discarded, which is what
      cost the 2026-08-12 build two runs at T-10.
    """
    requested = {str(x) for x in (assume_gates or [])} & set(derived_gates)
    assumed = sorted(n for n in requested if gate_defaults.get(n) is None)
    overridden = sorted(n for n in requested
                        if n in OVERRIDABLE_GATES
                        and gate_defaults.get(n) is False)
    refused = sorted(requested - set(assumed) - set(overridden))
    gates = {**gate_defaults, **dict(supplied or {})}
    supplied_refusals = []
    for name, value in (supplied or {}).items():
        if gate_defaults.get(name) is False and value is not False:
            gates[name] = False
            supplied_refusals.append({"gate": name, "derived": False,
                                      "reason": "supplied value cannot bypass an observed failure",
                                      "evidence": gate_evidence.get(name, "")})
    for name in assumed + overridden:
        if gates.get(name) is None or name in overridden:
            gates[name] = True
    gates = {k: v for k, v in gates.items() if v is not None}
    overridden_records = [
        {"gate": name, "derived": False,
         "evidence_contradicted": gate_evidence.get(name, "")}
        for name in overridden
    ]
    refused_records = [
        {"gate": name, "derived": gate_defaults.get(name),
         "reason": ("already decided True by the evidence; nothing to assume"
                    if gate_defaults.get(name) is True else
                    f"derived False and not in OVERRIDABLE_GATES "
                    f"({', '.join(sorted(OVERRIDABLE_GATES))}); the fix is the "
                    f"input, not the flag"),
         "evidence": gate_evidence.get(name, "")}
        for name in refused
    ]
    return gates, assumed, overridden_records, refused_records + supplied_refusals


def _applied(block: Any) -> Optional[bool]:
    """True when an enrichment map reached rows, False when it reached none.

    None when no map was requested at all: a build that was never given odds is
    a different state from a build given odds that matched nothing, and only the
    second is a failure.
    """
    if not isinstance(block, Mapping):
        return None
    if "requested" in block:
        requested = int(block.get("requested") or 0)
        if requested <= 0:
            return None
        return int(block.get("applied_count") or 0) > 0
    # R64(b): only f1/f4/f5 and projected_order carry requested/applied_count.
    # The other blocks report their own shapes -- xwoba an explicit `applied`
    # flag over considered/matched, ceiling and pitcher_ceiling matched/unmatched,
    # value_guard an `applied` flag with clipped_count -- so requiring `requested`
    # returned None for every one of them, and `manifest_projection_tier`
    # recorded a fully Savant-enriched build as projection_tier="proxy".
    #
    # R172, 2026-08-30: this comment said "the SAVANT-FED blocks" and then listed
    # value_guard among them, which is how an internal Base cap ended up in the
    # tier's key list and made every default build read "enriched". The guard is
    # not Savant-fed and reaches no external source; `_applied` still reads its
    # shape, because the weather and odds gates use this helper too, but
    # `manifest_projection_tier` no longer asks it.
    if "applied" in block:
        applied = bool(block.get("applied"))
        if not applied:
            return False
        # An `applied: True` block that matched nothing reached no rows.
        if "matched" in block:
            return int(block.get("matched") or 0) > 0
        return True
    if "matched" in block:
        if not (int(block.get("matched") or 0) + int(block.get("unmatched") or 0)):
            return None
        return int(block.get("matched") or 0) > 0
    return None


def validate_salary_export(salary_csv: Any) -> Dict[str, Any]:
    """Structural check of the DKSalaries CSV itself. R176(a), 2026-08-30.

    ``salary_gate_passed`` used to read ``validate_projection_schema(projections)``
    -- the same value as ``projection_schema_gate_passed``, one check wearing two
    gate names -- while its evidence string said "salary CSV schema validation".
    Nothing had validated the salary CSV. On the ``projections_override`` path the
    salary file was never even opened by this leg, and the gate still said it had
    been checked.

    The check is deliberately structural and generous: the export parses, and it
    carries at least one player row with an id and a positive salary. Anything the
    engine can already build a pool from passes. A stricter bar would be inventing
    a new refusal on the certified path under cover of fixing a label, and the
    DKSalaries CSV is authoritative by contract -- this says whether it READ, not
    whether its contents are right.
    """
    from mlb_engine.intake.slate_intake_manager import parse_dk_salary_csv

    try:
        rows = list(parse_dk_salary_csv(str(salary_csv)))
    except Exception as exc:  # noqa: BLE001 - any parse failure is the finding
        return {"passed": False, "rows": 0, "usable": 0,
                "summary": f"DKSalaries export at {salary_csv} did not parse ({exc})"}
    usable = sum(
        1 for sp in rows
        if str(getattr(sp, "player_id", "") or "").strip()
        and float(getattr(sp, "salary", 0) or 0) > 0
    )
    if not usable:
        return {"passed": False, "rows": len(rows), "usable": 0,
                "summary": f"DKSalaries export parsed {len(rows)} row(s) and none "
                           f"carries both a player id and a positive salary"}
    return {"passed": True, "rows": len(rows), "usable": usable,
            "summary": f"DKSalaries export parsed; {usable} of {len(rows)} row(s) "
                       f"carry a player id and a positive salary"}


def _derive_workflow_gates(
    *,
    schema: Mapping[str, Any],
    entry_requirements: Sequence[Mapping[str, Any]],
    posture_by_contest: Mapping[str, Mapping[str, Any]],
    projected_order: Mapping[str, Any],
    pitcher_roles: Optional[Mapping[str, str]],
    projection_enrichment: Mapping[str, Any],
    pool_report: Optional[Mapping[str, Any]] = None,
    order_by_team: Optional[Mapping[str, int]] = None,
    salary_schema: Optional[Mapping[str, Any]] = None,
) -> Tuple[Dict[str, Optional[bool]], Dict[str, str]]:
    """Derive the six pre-export gates from evidence already on hand.

    A gate is True only when something checkable says so, False when something
    checkable says otherwise, and None when nothing does. None is not a pass:
    ``validate_upload_ready_gates`` reports it as a missing gate and blocks.

    **R133(4) correction, 2026-08-18.** This paragraph used to end "the caller
    can assume any of them explicitly via ``assume_gates``", and the code has
    never done that: ``run_slate`` promoted a gate only where the derived value
    was None, so an assumption against a derived FALSE was discarded -- while
    still being written into ``assumed_gates`` in the artifact, which is a
    record of an assumption that had no effect. An operator following
    CLAUDE.md's own instruction ("override a pool blocker whose shape you have
    classified benign, and assert ``lineup_gate_passed`` on that same evidence.
    Both together or neither") got a blocked build from doing exactly what the
    contract says. ``lineup_gate_passed`` is now overridable against a derived
    False and lands in ``overridden_gates`` beside the evidence it contradicts;
    every other gate keeps None-only semantics, because that gate is the only
    one the contract authorizes asserting on operator evidence.
    """
    gates: Dict[str, Optional[bool]] = {}
    why: Dict[str, str] = {}

    # R176(a), 2026-08-30. This read `bool(schema.get("passed"))` -- the PROJECTION
    # schema, the identical value `projection_schema_gate_passed` carries two lines
    # below -- under an evidence string that said "salary CSV schema validation".
    # One check wearing two gate names, and the second name describing work nobody
    # had done: on the `projections_override` path this leg never opened the salary
    # file at all. The gate is now derived from the salary export itself, and says
    # None when no such check was supplied rather than borrowing another gate's
    # verdict.
    if salary_schema is None:
        gates["salary_gate_passed"] = None
        why["salary_gate_passed"] = (
            "no salary export check was supplied; nothing states that the "
            "DKSalaries CSV behind this build was read")
    else:
        gates["salary_gate_passed"] = bool(salary_schema.get("passed"))
        why["salary_gate_passed"] = str(salary_schema.get("summary") or "")

    reserved = list(entry_requirements or [])
    # R176(a), second half. The old second conjunct was `all(contest_id for row)`,
    # and it cannot fail: `parse_dk_entry_rows` skips any row whose contest id is
    # not all digits, so a row without one never reaches here. Verified at this
    # head at dk_entries_manager.py:303-305 rather than taken from the item. A
    # conjunct that cannot fail is not a check, and evidence saying "every row
    # carrying a contest id" claims one happened. Rather than invent a check, the
    # evidence now states the fact and where it comes from.
    grid_ok = bool(reserved)
    gates["entry_grid_gate_passed"] = grid_ok
    why["entry_grid_gate_passed"] = (
        f"{len(reserved)} reserved entries parsed across "
        f"{len(posture_by_contest)} contests; the parser admits only all-digit "
        f"contest ids, so every row here carries one by construction"
        if grid_ok else
        "no reserved entries parsed; the entry grid is empty"
    )

    report = dict(pool_report or {})
    # R173, 2026-08-30. This branch was guarded by `if report:` -- a truthiness test
    # standing in for a content check, which is the R53/R177/F16 shape. A pool
    # report carrying only metadata (`{"generated_at": ..., "note": ...}`) is
    # truthy, so `report.get("blockers")` returned None and `report.get("teams")`
    # returned {}: the gate certified True and wrote "0 blockers, 0 team(s) under 5
    # hitters" into the immutable diagnostics, evidence for a check that had nothing
    # to check. `pool_report=None` correctly None-blocked, so the WEAKER input
    # certified and the absent one blocked. Latent on the sanctioned path
    # (build_slate passes a real report), live on the engine-API leg and on any
    # upstream key drift, which is the 07-22 "certified with 0/9 posted" class.
    #
    # `teams` and `blockers` are the two keys this branch actually reads, so they
    # are what "checkable" means here; naming any other key would be a third
    # definition of the pool report's shape.
    checkable = "teams" in report or "blockers" in report
    supplied_uncheckable = bool(report) and not checkable
    if checkable:
        # R133(3): this was the THIRD reader of "how short is too short" and it
        # held the strictest bar of the three -- any team under nine failed the
        # gate, while the pool report's own confirmed path called 5 through 8 a
        # warning. One fact, two verdicts, and the gate's verdict won silently.
        # The bar is now MAX_HITTERS_PER_TEAM, the count that fills a maximum DK
        # stack, and the pool report computes it once under `thin_teams`. The
        # fallback recomputes it at the same bar for a report that predates the
        # key or was assembled by hand; it is not a second definition, and the
        # two are pinned equal by test.
        from mlb_engine.optimize.optimizer_v3 import MAX_HITTERS_PER_TEAM

        live = {
            team: rec for team, rec in (report.get("teams") or {}).items()
            if str(rec.get("status")) not in ("excluded_postponed",
                                              "excluded_no_order_data")
        }
        split = report.get("thin_teams") or {}
        if "cannot_fill_a_stack" in split:
            thin = sorted(str(t) for t in split.get("cannot_fill_a_stack") or [])
            short = sorted(str(t) for t in split.get("short_of_nine") or [])
        else:
            thin = sorted(t for t, rec in live.items()
                          if int(rec.get("hitters") or 0) < MAX_HITTERS_PER_TEAM)
            short = sorted(t for t, rec in live.items()
                           if MAX_HITTERS_PER_TEAM <= int(rec.get("hitters") or 0) < 9)
        gates["lineup_gate_passed"] = not report.get("blockers") and not thin
        why["lineup_gate_passed"] = (
            f"pool report: {len(report.get('blockers') or [])} blockers, "
            f"{len(thin)} team(s) under {MAX_HITTERS_PER_TEAM} hitters and so "
            f"unable to fill a stack"
            + (f" ({', '.join(thin)})" if thin else "")
            + f"; {len(short)} short of nine but stackable"
            + (f" ({', '.join(short)})" if short else "")
        )
    elif order_by_team:
        # R53: this branch read `elif projected_order:` -- and `projected_order` is
        # the four-key SUMMARY dict run_slate always builds, truthy even at
        # `requested: 0, applied_count: 0`. So every pool-report-absent call
        # certified lineup_gate_passed=True and wrote the evidence string
        # "4 players carry a batting order" (the len of a dict's KEYS) into the
        # immutable diagnostics, while the designed None-blocks branch below was
        # unreachable. That is the F4 class -- the 07-22 "certified with 0/9
        # lineups posted" incident -- reopened on the API leg of the sanctioned
        # front door. The evidence is now per-team counts off the assembled frame,
        # so an empty frame falls through to None and blocks.
        partial = sorted(t for t, n in order_by_team.items() if 0 < n < 9)
        gates["lineup_gate_passed"] = not partial
        covered = ", ".join(f"{t} {n}" for t, n in sorted(order_by_team.items()))
        why["lineup_gate_passed"] = (
            # R173: "no pool report supplied" would itself be false for a report
            # that arrived and carried nothing readable. Two different upstream
            # states, and the record says which one it was in.
            (f"a pool report was supplied but carries neither 'teams' nor "
             f"'blockers', so nothing in it is checkable; batting orders on the "
             f"assembled frame by team: {covered}"
             if supplied_uncheckable else
             f"no pool report supplied; batting orders on the assembled frame by "
             f"team: {covered}")
            + (f". Under nine: {', '.join(partial)}" if partial else "")
            + ". A team absent here carries no order at all and cannot be "
              "distinguished from one excluded on purpose without a pool report"
        )
    else:
        gates["lineup_gate_passed"] = None
        why["lineup_gate_passed"] = (
            "a pool report was supplied but carries neither 'teams' nor "
            "'blockers', and there are no batting orders either; nothing here "
            "states that the lineups behind this build were reviewed"
            if supplied_uncheckable else
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


def batting_orders_by_team(projections: Any) -> Dict[str, int]:
    """Per-team count of rows carrying a batting order, off the assembled frame.

    R53. The lineup gate's pool-report-absent branch needs evidence it can be
    wrong about. `projected_order`, the summary dict it used to read, is truthy on
    every build and its len() is the number of its own keys, so the gate could
    only ever pass and its evidence string was a fabrication. This is countable,
    per team, and empty when the frame holds no orders at all -- which is what
    lets the gate fall through to None and block.

    Pitchers carry no batting order and are absent by construction. A team with
    zero ordered rows does not appear: without a pool report there is nothing here
    that distinguishes "excluded on purpose" from "missing", and the gate says so
    rather than guessing.
    """
    out: Dict[str, int] = {}
    if projections is None or not hasattr(projections, "columns"):
        return out
    if "Batting_Order" not in projections.columns or "Team" not in projections.columns:
        return out
    for team, order in zip(projections["Team"].tolist(),
                           projections["Batting_Order"].tolist()):
        if order is None or str(order).strip() in ("", "None", "nan"):
            continue
        try:
            if int(float(order)) <= 0:
                continue
        except (TypeError, ValueError):
            continue
        key = str(team).upper()
        out[key] = out.get(key, 0) + 1
    return dict(sorted(out.items()))


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

# ---------------------------------------------------------------------------
# R37(2)(a) and (b): the two live bands, Ben's dated decision of 2026-08-28.
# ---------------------------------------------------------------------------
#
# Evidence: ledger 3.21, the 610-contest greenfield standings mine, which is the
# ONE measured tranche R37(2)(a)'s gate waited on. Stage 1's floor-4 portfolio is
# archived and graded across 2026-08-09 -> 08-27, so the two effects are
# separable exactly as Ben's 2026-08-09 decision required.
#
# What the tranche says, and every number here is an observed cohort share or a
# deterministic review proxy over one, never a win rate or a probability:
#   - The top-1%+win cohort's 5-2-1 lift held in BOTH halves on 3g+ slates
#     (+13.1/+16.6pp on 5-6g, +12.9/+13.1 on 7g+, pooled estimator). The root
#     doc's slate-clustered estimate of the same effect is +3.84pp and fails its
#     permutation gate, so the joint label is STABLE DIRECTIONAL, not replicated.
#   - Mean primary-stack size runs 4.36-4.63 in top cohorts against a field at
#     4.00-4.23, on every slate size.
#   - 1-2g slates are the counter-case and they are why the floor is
#     slate-size-conditioned rather than global: there the cohort favors 5-3
#     (+16.5pp) and 4-4 (+12.0) with 5-2-1 FLAT (+1.4).
#   - Our own delivered mix on 5g+ slates ran 5-2-1 at 0.4% against a field at
#     25.7% and a top cohort near 40%. That is the largest observed
#     portfolio-vs-cohort gap in either format.
#
# BREADTH <= 0.02 is the routing, and it is exactly the set the item names. Read
# PAYOUT_BREADTH_BY_SHAPE above: winner_take_all 0.002, wta_ticket_satellite /
# small_wta / mid_wta 0.002, single_entry_gpp 0.01, mme_top_heavy / mme_gpp /
# large_wta 0.02 sit at or under the threshold, and the next shape up is
# limited_entry_gpp at 0.10. So "WTA, one-seat satellites, solo shots,
# mme_gpp/mini-MAX, single_entry_gpp" and "breadth <= 0.02" pick out the same
# contests, and the threshold is the definition rather than a second list that
# can drift from the first.
NARROW_BREADTH_MAX = 0.02
NARROW_BREADTH_PRIMARY_STACK_FLOOR = 5

# 1-2 game slates are EXEMPT and stay at the stage-1 floor of 4. This is not
# caution about a thin slate's feasibility; it is the tranche's own counter-case.
MIN_SLATE_GAMES_FOR_NARROW_FLOOR = 3

# R37(2)(b): the middle breadth band, inclusive at both ends. large_field_gpp
# (0.12), limited_entry_gpp (0.10), broad_micro_gpp / portfolio_gpp /
# mid_field_gpp (0.15), small_field_gpp (0.18), ticket_line / satellite /
# ticket_satellite (0.22). Part of the payout there sits at a cut line where
# shape does not separate, so the quota buys top-end exposure on a SHARE of
# entries rather than on all of them.
MID_BREADTH_RANGE = (0.10, 0.22)

# The band Ben sized. The quota lands inside it; it is never set outside it.
MID_BREADTH_QUOTA_BAND = (0.15, 0.25)

# How the quota reads the field. `MID_BREADTH_QUOTA_SHARE_RATIO` is the fraction
# of the shape's CURRENT field share we ask for, clamped into the band above.
#
# This is the item's build requirement, carried by Ben's decision and worth
# restating because it is the whole reason the quota is not a constant: the LIFT
# has moved OPPOSITE to 5-2-1's field share in all three prior tranches (+3.1pp
# on a 25.1% share, +0.2pp on 29.7%, +13.6pp on 21.6%), and 3.21 adds a fourth
# point with a strong val-half lift on a ~26% share. Four points in three
# directions is a record-only pattern, not a law. So the quota reads the SHARE,
# which is measurable and stable, and never the lift, which is neither.
#
# Below 1.0 on purpose: at a 25.7% field share the quota asks for 19%, which
# moves us off 0.4% without asking the portfolio to out-concentrate the field on
# shape. R37(2)'s standing constraint is "no contrarian push", and its mirror
# holds too -- nothing in the tranche licenses going PAST the field.
MID_BREADTH_QUOTA_SHARE_RATIO = 0.75

# The field share of the five-or-larger primary stack, by slate-size bucket, as
# MEASURED in ledger 3.21 over the 610-contest corpus (2026-06-03 -> 08-27).
#
# This is a dated FALLBACK, not the intended source. `read_five_stack_field_share`
# prefers a rollup emitted from the archive, so the share can be refreshed
# without an engine edit; these values answer only when no rollup is on disk, and
# whichever source answered is NAMED in the report. That naming is the point:
# R145-R148 cost this project real time by presenting a cached reading as a live
# one, and a share that nothing on this disk can re-read goes stale silently and
# confidently.
FIVE_STACK_FIELD_SHARE_MEASURED = {
    "1-2g": 0.155,
    "3-4g": 0.212,
    "5-6g": 0.257,
    "7g+": 0.257,
}
FIVE_STACK_FIELD_SHARE_MEASURED_AS_OF = "2026-08-28"
FIVE_STACK_FIELD_SHARE_MEASURED_SOURCE = (
    "ledger 3.21, 610-contest greenfield standings mine, 2026-06-03..2026-08-27")

# Where a refreshed rollup is read from when one exists. ARCHIVE owns this path
# (`data/reference/` is ARCHIVE's write set); the engine only READS it.
#
# NOTHING PRODUCES THIS FILE YET, and that is stated here rather than implied by
# a forward reference to a tool that does not exist. `field_miner.mine_contest`
# writes the per-entry `stack_pattern` string but aggregates only
# `max_stack_histogram` -- the scalar primary size, not the partition -- so the
# shares have only ever been computed by a throwaway under `tools/_scratch_*`.
# The producer is filed as R37(2)(c)'s open remainder and it is ARCHIVE's work.
# Until it exists every build reads `ledger_measured` and SAYS so, which is the
# whole point of `read_five_stack_field_share` naming its source.
#
# Resolved against the REPO ROOT, not the process CWD. A bare relative path here
# would resolve against wherever the caller happened to start, so the rollup
# would be invisible to any build not launched from the repo root -- and it would
# be invisible SILENTLY, falling back to the dated values with `ledger_measured`
# in the report, which is the one failure mode this three-source design exists to
# prevent. `upload_manifest` and `repo_env` both anchor the same way.
FIVE_STACK_FIELD_SHARE_PATH = (
    Path(__file__).resolve().parents[2]
    / "data" / "reference" / "stack_shape_field_shares.json")


def slate_game_count(projections: Any) -> Optional[int]:
    """Distinct games in the pool, or ``None`` when the frame cannot say.

    R37(2)(a). The floor is slate-size-conditioned, so the count is an INPUT to a
    strategy control and not a cosmetic. It is read off the projection frame's
    game column, which descends from the DKSalaries `Game Info` field, and that
    file is this project's authority on what is on the slate.

    ``None`` rather than a guess when no game column exists: an unmeasurable
    slate size leaves both bands unavailable, which the callers treat as "do not
    apply", never as "apply the default bucket". A frame with a team column but
    no game column would otherwise take whichever bucket 0 or 1 falls in and
    silently exempt or bind the whole portfolio.
    """
    try:
        if not hasattr(projections, "columns"):
            return None
        cols = set(projections.columns)
        col = next((c for c in ("Game_ID", "GameId", "Game") if c in cols), None)
        if col is None:
            return None
        vals = {str(v).strip() for v in projections[col].tolist() if str(v).strip()}
        return len(vals) or None
    except Exception:
        return None


def slate_size_bucket(game_count: Optional[int]) -> Optional[str]:
    """Slate-size bucket, matching ledger 3.21's own conditioning exactly.

    3.21 reports every shape finding by this bucketing, and the buckets are the
    reason R37(2)(a) is conditioned at all -- 1-2g is where the 5-2-1 lift goes
    flat and 5-3/4-4 take over. Returning the same names the ledger prints keeps
    a reader from having to reconcile two bucketings.
    """
    if game_count is None:
        return None
    try:
        n = int(game_count)
    except (TypeError, ValueError):
        return None
    if n <= 0:
        return None
    if n <= 2:
        return "1-2g"
    if n <= 4:
        return "3-4g"
    if n <= 6:
        return "5-6g"
    return "7g+"


def read_five_stack_field_share(
    game_count: Optional[int],
    rollup_path: Optional[str] = None,
) -> Dict[str, Any]:
    """The five-stack field share for this slate size, and WHICH source answered.

    R37(2)(b). Three outcomes, and the third is the one that matters most:

    ``archive_rollup`` -- a rollup exists on disk and carries this bucket. This
    is the live read and the intended path.

    ``ledger_measured`` -- no rollup, so the dated 3.21 measurement answers. The
    report carries ``as_of`` so nobody reads it as current.

    ``unavailable`` -- no share for this bucket from either source, which happens
    when the slate size cannot be determined. The quota is then OFF. It is not
    guessed and it is not silently zero-with-an-opinion: an unmeasurable input
    makes a control unavailable, the same distinction `f4_handedness_unavailable`
    draws one layer down.
    """
    bucket = slate_size_bucket(game_count)
    out: Dict[str, Any] = {
        "bucket": bucket,
        "share": None,
        "source": "unavailable",
        "as_of": None,
        "source_detail": None,
    }
    if bucket is None:
        out["source_detail"] = (
            "slate game count unavailable, so no slate-size bucket could be "
            "resolved and the quota is unavailable rather than defaulted")
        return out
    path = Path(rollup_path or FIVE_STACK_FIELD_SHARE_PATH)
    try:
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            shares = (payload or {}).get("five_stack_share_by_slate_bucket") or {}
            raw = shares.get(bucket)
            if raw is not None:
                share = float(raw)
                if 0.0 <= share <= 1.0:
                    out.update({
                        "share": share,
                        "source": "archive_rollup",
                        "as_of": (payload or {}).get("computed_at"),
                        "source_detail": str(path),
                    })
                    return out
    except Exception as exc:      # a torn or unreadable rollup falls through
        out["source_detail"] = f"rollup at {path} unreadable ({exc}); fell back"
    measured = FIVE_STACK_FIELD_SHARE_MEASURED.get(bucket)
    if measured is None:
        return out
    out.update({
        "share": float(measured),
        "source": "ledger_measured",
        "as_of": FIVE_STACK_FIELD_SHARE_MEASURED_AS_OF,
        "source_detail": (out["source_detail"] + "; " if out["source_detail"]
                          else "") + FIVE_STACK_FIELD_SHARE_MEASURED_SOURCE,
    })
    return out


def five_stack_quota_from_field_share(field_share: Optional[float]) -> Optional[float]:
    """The quota share to request, read off the field share and clamped to the band.

    R37(2)(b). ``None`` in, ``None`` out: an unmeasurable field share leaves the
    quota unavailable rather than defaulted to a band edge, which would be the
    pinned constant the item forbids wearing a measurement's clothes.
    """
    if field_share is None:
        return None
    try:
        share = float(field_share)
    except (TypeError, ValueError):
        return None
    if not (share > 0.0):
        return None
    lo, hi = MID_BREADTH_QUOTA_BAND
    return round(min(hi, max(lo, MID_BREADTH_QUOTA_SHARE_RATIO * share)), 4)


def resolve_shape_bands(
    posture_by_contest: Mapping[str, Mapping[str, Any]],
    game_count: Optional[int] = None,
    archetypes_path: Optional[str] = None,
    rollup_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Per-contest R37(2) band routing, and the portfolio-wide floors it implies.

    R37(2)(a)+(b), Ben's dated decision of 2026-08-28. Returns the per-contest
    rows AND the two floor values the control merge should treat as DECLARED for
    each contest, so the merge's existing rules do the rest unchanged.

    That last part is deliberate and it is the safety property worth naming.
    R34's floor merge takes the LEAST demanding declared value and retires the
    floor entirely if any posture is silent, because ONE portfolio serves every
    contest and forcing a narrow-breadth contest's floor onto a broad-payout one
    is a strategy change for that contest made invisibly. Routing per contest and
    then merging by that rule means a mixed entered set lands back on the stage-1
    floor of 4 automatically. Floor 5 binds only when EVERY contest in the set is
    narrow-breadth; the quota binds only when every contest is mid-breadth. That
    is the conservative direction and it is not a coincidence -- it is the reason
    the routing goes here rather than into a posture default.
    """
    breadth_by_shape = _payout_breadth_by_shape_from_csv(archetypes_path)
    bucket = slate_size_bucket(game_count)
    slate_exempt = bucket == "1-2g"
    # An UNKNOWN slate size is a third state and it is not "3g or more". The
    # floor is slate-size-conditioned by Ben's decision, so a bucket that could
    # not be resolved leaves it unavailable rather than applied -- the same
    # direction the quota already takes when the field share cannot be read.
    #
    # Caught by check rather than by reasoning, and worth recording as the
    # R145-class failure it is: `slate_exempt` was first written
    # `bool(bucket) and bucket == "1-2g"`, which is False for an unknown bucket,
    # so `narrow and not slate_exempt` bound floor 5 on a narrow portfolio whose
    # game count nothing had measured. `late_swap` reaches exactly that state
    # whenever it runs without a projection frame, and it printed
    # `primary_stack_min_size: 5` there while this function's own docstring said
    # the bands were inert.
    floor_available = bucket is not None and not slate_exempt
    field = read_five_stack_field_share(game_count, rollup_path=rollup_path)
    quota_share = five_stack_quota_from_field_share(field.get("share"))
    lo, hi = MID_BREADTH_RANGE
    rows: List[Dict[str, Any]] = []
    for cid, info in posture_by_contest.items():
        breadth = _resolve_payout_breadth(info, breadth_by_shape)
        narrow = breadth <= NARROW_BREADTH_MAX
        mid = lo <= breadth <= hi
        floor = NARROW_BREADTH_PRIMARY_STACK_FLOOR if (narrow and floor_available) else None
        rows.append({
            "contest_id": cid,
            "contest_name": info.get("contest_name", ""),
            "posture": info.get("posture", ""),
            "payout_breadth": round(float(breadth), 4),
            "band": "narrow" if narrow else ("mid" if mid else "broad"),
            "primary_stack_min_size_declared": floor,
            "min_five_stack_share_pct_declared": quota_share if mid else None,
            "slate_size_exempt": bool(narrow and slate_exempt),
            "floor_unavailable_reason": (
                None if (floor is not None or not narrow)
                else ("1-2g slate: the tranche's own counter-case, where the "
                      "cohort favors 5-3 and 4-4 and the 5-2-1 lift is flat"
                      if slate_exempt else
                      "slate game count unmeasurable, so the size condition "
                      "cannot be evaluated and the floor is unavailable")),
        })
    narrow_rows = [r for r in rows if r["band"] == "narrow"]
    mid_rows = [r for r in rows if r["band"] == "mid"]
    return {
        "label": "R37(2) SHAPE BANDS — Ben's dated decision of 2026-08-28; "
                 "observed cohort shares and deterministic review proxies, never "
                 "a win rate, cash rate, or probability claim",
        "evidence": "ledger 3.21 (610 contests, 2026-06-03..2026-08-27)",
        "slate_games": game_count,
        "slate_size_bucket": bucket,
        "narrow_breadth_max": NARROW_BREADTH_MAX,
        "mid_breadth_range": list(MID_BREADTH_RANGE),
        "quota_band": list(MID_BREADTH_QUOTA_BAND),
        "quota_share_ratio": MID_BREADTH_QUOTA_SHARE_RATIO,
        "five_stack_field_share": field,
        "quota_share_resolved": quota_share,
        "slate_size_exempts_narrow_floor": slate_exempt,
        "narrow_floor_available": floor_available,
        "contests": rows,
        "narrow_breadth_contests": len(narrow_rows),
        "mid_breadth_contests": len(mid_rows),
        # What the merge will actually do, stated here so the checkpoint does not
        # require re-deriving R34's unanimity rule by hand.
        "floor_5_binds_portfolio": bool(rows) and all(
            r["primary_stack_min_size_declared"] == NARROW_BREADTH_PRIMARY_STACK_FLOOR
            for r in rows),
        "quota_binds_portfolio": bool(rows) and quota_share is not None and all(
            r["min_five_stack_share_pct_declared"] is not None for r in rows),
    }


#: The stack floor BOTH bank builders default to, named once here so the
#: derivation below cannot drift from them silently. R340: the defaults live in
#: `optimizer_v3.build_diverse_candidate_bank(bank_stack_min_size=4)` and
#: `bank_cache.extend_bank(stack_min=4)`, and a test pins all three equal.
BANK_DEFAULT_STACK_MIN = 4

#: How much of a budgeted slice the five-stack request may take, and how much it
#: must leave behind. R340: a bank with no five-stacks is the defect; a bank with
#: no four-stacks is a DIFFERENT defect, because the four is what fills the
#: contests that never asked for the floor (R34's merge rule) and what keeps a
#: thin slice from leaving a blank reserved row, which blocks certification.
#: Neither size is ever starved, whatever the quota says.
BANK_FIVE_STACK_BUDGET_MIN_SHARE = 0.25
BANK_FIVE_STACK_BUDGET_MAX_SHARE = 0.75


def resolve_bank_stack_request(
    controls: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    """What to ASK the candidate bank for, derived from the merged controls.

    R340, and the defect is that this function did not exist. R37(2)(a)'s
    ``primary_stack_min_size`` floor and (b)'s ``min_five_stack_share_pct`` quota
    shipped 2026-08-28 as allocator FILTERS over a bank, and no caller anywhere
    passed a stack size to either bank builder -- so both controls filtered a
    bank that is never asked for a five-stack. Measured on 1907_8g (2026-09-14,
    38 entries): ``BANK PRIMARY STACK SIZE DIST: {4: 107}``, 107 of 107
    candidates a four-stack, quota 0.60 -> zero five-stacks, and the quota
    reported ``relaxed_off / no_qualifying_candidate_in_bank``, which reads as a
    bank that came up short rather than as a control with no wire.

    The derivation is the SAME breadth routing the floor and the quota already
    use, so a five-stack request reaches the bank on exactly the contests they
    target and on no others. It reads the MERGED controls rather than the bands
    directly, which matters: R34's floor merge already applied unanimity (floor 5
    binds only when EVERY contest is narrow-breadth, the quota only when every
    contest is mid-breadth) and reading the bands again here would be a second
    copy of that rule that can disagree with the first.

    ``sizes`` is what a builder with ONE size per call (``extend_bank``) asks
    for, in priority order, and it holds BOTH sizes whenever a five is wanted --
    "a slate mixing both breadths asks the bank for both sizes". The auto-bank
    door needs only ``bank_stack_min_size``, because there the base bank supplies
    the fours and only the forced-augmentation pass reads the floor, so one value
    already produces the mix.

    Truthful labels: this chooses what to SEARCH for. It is not a claim that a
    five-stack scores better, and nothing here relaxes a control or reduces a
    player pool.
    """
    merged = dict(controls or {})
    try:
        floor = int(merged.get("primary_stack_min_size") or 0)
    except (TypeError, ValueError):
        floor = 0
    try:
        quota = float(merged.get("min_five_stack_share_pct") or 0.0)
    except (TypeError, ValueError):
        quota = 0.0
    try:
        five_size = int(merged.get("five_stack_min_size") or
                        NARROW_BREADTH_PRIMARY_STACK_FLOOR)
    except (TypeError, ValueError):
        five_size = NARROW_BREADTH_PRIMARY_STACK_FLOOR

    if floor >= five_size:
        # Every contest in the entered set asked for the floor, so every
        # delivered lineup needs one. The bank is still asked for fours as well:
        # see BANK_FIVE_STACK_BUDGET_MIN_SHARE.
        target = 1.0
        reason = (f"primary_stack_min_size {floor} >= five_stack_min_size "
                  f"{five_size}: every entry needs a stack of {five_size}")
    elif quota > 0.0:
        target = quota
        reason = (f"min_five_stack_share_pct {quota} over stacks of "
                  f"{five_size}: that share of the entered set needs one")
    else:
        target = 0.0
        reason = ("neither primary_stack_min_size nor min_five_stack_share_pct "
                  "asks for a stack above the bank default")

    wants_five = target > 0.0
    return {
        "primary_floor": floor or None,
        "quota_share": quota or None,
        "five_min_size": five_size,
        "five_share_target": target,
        "wants_five": wants_five,
        # The auto door's single value. The sliced door's list.
        "bank_stack_min_size": five_size if wants_five else BANK_DEFAULT_STACK_MIN,
        "sizes": ([five_size, BANK_DEFAULT_STACK_MIN] if wants_five
                  else [BANK_DEFAULT_STACK_MIN]),
        "reason": reason,
        "note": "deterministic search-effort routing derived from the same "
                "breadth bands R37(2)(a) and (b) already apply; never a win "
                "rate, cash rate, or probability claim",
    }



#: R405(c). The consensus-limited bank jobs' share of a budgeted bank, clamped
#: like the five-stack request's (R340) so neither bucket is ever starved: the
#: ordinary bucket is what DEFINES the cluster and what fills every entry the cap
#: does not touch, and the limited bucket is what lets the cap bind at all.
BANK_CONSENSUS_LIMITED_MIN_SHARE = 0.25
BANK_CONSENSUS_LIMITED_MAX_SHARE = 0.50


def resolve_consensus_limited_request(
    controls: Optional[Mapping[str, Any]],
    entries: int,
    total_max: Optional[int] = None,
) -> Dict[str, Any]:
    """What to ask the bank for so the consensus-cluster cap has something to bind.

    R405(c), one derivation for all three bank doors (the sliced build door,
    the direct auto-bank door, and the plan leg, which has to solve the build's
    own MILP -- R340's lesson about the door the entry did not name). Reads the
    MERGED controls. The cap limits entries carrying k or more of the bank's
    consensus hitters, and the ordinary bank holds almost nothing below k: on
    1905_10g 6 of 408 candidates, on the vendored 2026-06-03 slate 0 of 30. So a
    cap below 1.0 asks for jobs solved under ``max_selected_from=(cluster, k-1)``
    and sizes them to cover it: at least ``(1 - pct) x E x 2`` candidates.

    Search effort, never a pool reduction: the limit applies to the reserved
    jobs only, every player stays legal in every job, and m = k - 1 >= 1 is
    enforced by the solver wrapper. Not a claim that a low-consensus lineup
    scores better.
    """
    from mlb_engine.allocate.contest_allocator import (
        CONSENSUS_CLUSTER_MAX_MEMBERS, CONSENSUS_CLUSTER_MIN_BANK_SHARE,
        _consensus_cluster_min_members,
    )
    merged = dict(controls or {})
    try:
        pct = merged.get("max_consensus_cluster_share_pct")
        pct = None if pct is None else float(pct)
    except (TypeError, ValueError):
        pct = None
    k = _consensus_cluster_min_members(merged)
    n = max(0, int(entries or 0))
    active = pct is not None and 0.0 < pct < 1.0 and n > 1 and k >= 2
    need = int(math.ceil((1.0 - pct) * n * 2)) if active else 0
    share = None
    limited_max = None
    if active and total_max:
        share = min(BANK_CONSENSUS_LIMITED_MAX_SHARE,
                    max(BANK_CONSENSUS_LIMITED_MIN_SHARE, need / max(1, int(total_max))))
        limited_max = max(need, int(int(total_max) * share))
    return {
        "active": bool(active),
        "requested_pct": pct,
        "min_members_k": k,
        "m": (k - 1) if active else None,
        "min_candidates": need,
        "budget_share": share,
        "max_candidates": limited_max,
        "min_bank_share": CONSENSUS_CLUSTER_MIN_BANK_SHARE,
        "max_members": CONSENSUS_CLUSTER_MAX_MEMBERS,
        "reason": ("max_consensus_cluster_share_pct below 1.0: the cap needs "
                   "lineups carrying fewer than k cluster members, and the "
                   "ordinary bank holds almost none" if active else
                   "no consensus-cluster cap below 1.0 in the merged controls"),
        "note": "deterministic search-effort routing; never a win rate, cash "
                "rate, or probability claim",
    }


def build_consensus_limited_jobs(
    cache: Any,
    projections: Any,
    request: Mapping[str, Any],
    *,
    max_opposing_hitters_per_sp: Optional[int] = None,
    **extend_kwargs: Any,
) -> Dict[str, Any]:
    """R405(c). Derive the cluster from the cache's ORDINARY bucket, then extend
    the bank with cluster-limited jobs in their own conditions bucket.

    One function for the sliced build door and the plan leg, so the two cannot
    disagree about the cluster or the job size. ``extend_kwargs`` is the
    caller's own ``extend_bank`` arguments (budget, max_candidates, leverage,
    anti-correlation, stack size), passed through unchanged apart from the two
    this function owns.
    """
    from mlb_engine.allocate.contest_allocator import (
        CONSENSUS_LIMITED_JOB_CLASS, consensus_cluster_members,
    )
    from mlb_engine.optimize.bank_cache import extend_bank

    cluster = consensus_cluster_members(
        cache.as_candidates(None, requested_n=1),
        min_bank_share=float(request.get("min_bank_share")),
        max_members=int(request.get("max_members")))
    members = list(cluster["member_ids"])
    m = int(request.get("m") or 0)
    if not request.get("active") or len(members) <= m:
        return {"attempted": False, "cluster_members": members,
                "reason": ("not requested" if not request.get("active") else
                           f"the ordinary bank's cluster has {len(members)} "
                           f"member(s), at most m = {m}, so no lineup can exceed it")}
    report = extend_bank(
        cache, projections, max_selected_from=(members, m),
        job_class=CONSENSUS_LIMITED_JOB_CLASS,
        # R288/R293: named, not splatted, so the solve-producer census can see
        # that this call forwards the anti-correlation allowance.
        max_opposing_hitters_per_sp=max_opposing_hitters_per_sp,
        **extend_kwargs)
    return {"attempted": True, "cluster_members": members, "m": m,
            "cluster_source_lineups": cluster["source_lineups"],
            "report": report}


#: R406. The three non-projection sleeves' combined share of a budgeted bank.
#: The projection world still gets most of the search: it seats the largest
#: sleeve, defines R405's cluster, and fills every entry a sleeve cannot.
BANK_SLEEVE_BUDGET_SHARE = 0.30


def resolve_sleeve_bank_request(
    entry_requirements: Sequence[Mapping[str, Any]],
    controls: Optional[Mapping[str, Any]],
    projections: Any = None,
    *,
    implied_total_by_team: Optional[Mapping[str, float]] = None,
) -> Dict[str, Any]:
    """R406. What to ask the bank for so each sleeve can seat its entries.

    One derivation for every door. Weights come from `classic_sleeves` (Ben's
    40/20/20/20 and the WTA tilt), the entry counts from the reserved file, and
    each non-projection sleeve is asked for twice the entries it will seat. The
    environment sleeve's games are ranked by the implied totals F1 priced, else
    by the static park run factor F5 itself reads. ``classic_sleeves: False`` in
    the merged controls (an override, the loose golden) turns it off.
    """
    from mlb_engine.optimize import classic_sleeves as cs
    enabled = (controls or {}).get("classic_sleeves", True) is not False
    counts: Dict[str, int] = {}
    weights: Dict[str, Dict[str, float]] = {}
    for req in entry_requirements or []:
        cid = str(req.get("contest_id") or "")
        counts[cid] = counts.get(cid, 0) + 1
        # The allocator's own source for the same weights (each entry's
        # posture and shape), so the bank is asked for what the mask will seat.
        weights.setdefault(cid, cs.contest_sleeve_weights(
            req.get("posture"), req.get("contest_shape")))
    expected = cs.expected_entries_by_sleeve(weights, counts)
    teams_by_game: Dict[str, List[str]] = {}
    if projections is not None and hasattr(projections, "columns") \
            and "Game_ID" in projections.columns:
        for gid, team in zip(projections["Game_ID"].astype(str),
                             projections["Team"].astype(str)):
            if gid and gid.lower() not in ("nan", "none", ""):
                bucket = teams_by_game.setdefault(gid, [])
                if team not in bucket:
                    bucket.append(team)
    environment = cs.rank_environment_games(
        sorted(teams_by_game), implied_total_by_team=implied_total_by_team,
        park_run_factor_by_game=cs.static_park_run_factor_by_game(sorted(teams_by_game)),
        teams_by_game={g: sorted(t) for g, t in teams_by_game.items()})
    sleeves = {s: {"expected_entries": n, "min_candidates": 2 * n}
               for s, n in expected.items() if s != cs.SLEEVE_PROJECTION and n > 0}
    dropped: Dict[str, str] = {}
    if not environment.get("games"):
        if sleeves.pop(cs.SLEEVE_ENVIRONMENT, None):
            dropped[cs.SLEEVE_ENVIRONMENT] = "no game could be ranked (no odds, no park factor)"
    elif set(environment["games"]) >= set(teams_by_game):
        # The top games ARE the slate (a two-game slate): the sleeve would be
        # the projection's own job grid, not a distinct world.
        if sleeves.pop(cs.SLEEVE_ENVIRONMENT, None):
            dropped[cs.SLEEVE_ENVIRONMENT] = (
                f"the top {len(environment['games'])} games are the whole slate, "
                f"so the sleeve would repeat the projection's job grid")
    return {
        "active": bool(enabled and sleeves),
        "enabled": enabled,
        "weights_by_contest": weights,
        "expected_entries": expected,
        "sleeves": sleeves,
        "dropped": dropped,
        "environment": environment,
        "note": ("deterministic constructions over labeled priors; a sleeve that "
                 "does well in a replay is supported in the shapes replayed, never "
                 "a probability or an edge"),
    }


def build_sleeve_jobs(
    cache: Any,
    projections: Any,
    request: Mapping[str, Any],
    *,
    consensus_members: Sequence[str],
    time_budget_s: float,
    salary_cache: Any = None,
    max_opposing_hitters_per_sp: Optional[int] = None,
    **extend_kwargs: Any,
) -> Dict[str, Any]:
    """R406. Extend the bank with each active sleeve's jobs, in its own bucket.

    * ``chalk_fails``: the projection frame, at most one of R405's cluster
      (``consensus_members``, derived by the caller from its ORDINARY bank);
    * ``environment``: the projection frame, stack jobs only for the chosen
      games' teams (every player stays legal as a filler);
    * ``salary_only``: the salary-only COPY of the frame, in ``salary_cache``
      (a separate file: a different frame is a different projection digest,
      and sharing a cache would purge the ordinary bucket).

    Each call stops at the sleeve's own candidate need; the budget is split
    evenly across the sleeves still to run. Search effort only.
    """
    from mlb_engine.optimize import classic_sleeves as cs
    from mlb_engine.optimize.bank_cache import extend_bank
    import time as _t
    started = _t.monotonic()
    report: Dict[str, Any] = {}
    if not request.get("active"):
        return {"attempted": False, "reason": "sleeves not requested"}
    order = [s for s in cs.SLEEVES if s in (request.get("sleeves") or {})]
    for idx, sleeve in enumerate(order):
        need = int(request["sleeves"][sleeve]["min_candidates"])
        left = float(time_budget_s) - (_t.monotonic() - started)
        budget = max(1.0, left / max(1, len(order) - idx))
        common = dict(extend_kwargs, time_budget_s=budget,
                      job_class=cs.SLEEVE_JOB_CLASS[sleeve])
        if sleeve == cs.SLEEVE_CHALK_FAILS:
            members = list(consensus_members)
            if len(members) <= cs.CHALK_FAILS_MAX_MEMBERS:
                report[sleeve] = {"attempted": False,
                                  "reason": "the consensus cluster is too small to limit"}
                continue
            rep = extend_bank(cache, projections,
                              max_selected_from=(members, cs.CHALK_FAILS_MAX_MEMBERS),
                              max_candidates=len(cache) + need,
                              max_opposing_hitters_per_sp=max_opposing_hitters_per_sp,
                              **common)
        elif sleeve == cs.SLEEVE_ENVIRONMENT:
            teams = list((request.get("environment") or {}).get("teams") or [])
            # The sleeve seats on projection lineups stacking these teams, so
            # the jobs are only DEPTH: when the bank already holds enough such
            # lineups, re-solving the restricted grid (a new bucket, no cache
            # hits) would return the same lineups and spend the budget.
            held = _stacked_on_teams(cache, projections, teams)
            if held >= need:
                report[sleeve] = {"attempted": False, "need": need, "already_held": held,
                                  "reason": "the bank already holds enough lineups "
                                            "stacking the chosen games"}
                continue
            rep = extend_bank(cache, projections, stack_teams=teams,
                              max_candidates=len(cache) + need,
                              max_opposing_hitters_per_sp=max_opposing_hitters_per_sp,
                              **common)
        else:
            if salary_cache is None:
                report[sleeve] = {"attempted": False, "reason": "no salary-only cache"}
                continue
            frame, transform = cs.salary_only_frame(projections)
            rep = extend_bank(salary_cache, frame,
                              max_candidates=len(salary_cache) + need,
                              max_opposing_hitters_per_sp=max_opposing_hitters_per_sp,
                              **common)
            rep = {**rep, "transform": transform}
        report[sleeve] = {"attempted": True, "need": need,
                          "built": rep.get("built_this_slice"),
                          "job_list_exhausted": rep.get("job_list_exhausted"),
                          "conditions_signature": rep.get("conditions_signature"),
                          **({"transform": rep["transform"]} if "transform" in rep else {})}
    return {"attempted": True, "sleeves": report,
            "elapsed_s": round(_t.monotonic() - started, 3)}



def _stacked_on_teams(cache: Any, projections: Any, teams: Sequence[str],
                      min_size: int = 4) -> int:
    """How many cached lineups carry ``min_size`` or more hitters from one of
    ``teams`` -- the environment sleeve's membership, counted cheaply off the
    rosters and the frame's team column."""
    wanted = {str(t).upper() for t in teams}
    if not wanted or projections is None or not hasattr(projections, "columns"):
        return 0
    team_of = dict(zip(projections["Player_ID"].astype(str),
                       projections["Team"].astype(str).str.upper()))
    held = 0
    for entry in cache.candidates:
        counts = Counter(team_of.get(str(p)) for p in list(entry.get("roster") or [])[2:])
        if any(counts.get(t, 0) >= min_size for t in wanted):
            held += 1
    return held

def sleeve_candidates(
    cache: Any,
    salary_cache: Any,
    projections: Any,
    *,
    requested_n: int,
    contest_shapes: Optional[Sequence[str]] = None,
    base: Optional[Sequence[Mapping[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """R406. The sleeve-built candidates, each tagged with its world, scored in
    its OWN world (the salary-only lineups on the salary-only frame), with ids
    that cannot collide with the ordinary bank's. ``base`` is the ordinary list
    already served; rosters it holds are not served twice."""
    from mlb_engine.optimize import classic_sleeves as cs
    seen = {tuple(str(p) for p in (c.get("roster_slot_ids") or c.get("player_ids") or []))
            for c in (base or [])}
    out: List[Dict[str, Any]] = []
    sources = []
    if salary_cache is not None and len(salary_cache):
        frame, _ = cs.salary_only_frame(projections)
        sources.append(("sal", salary_cache.as_candidates(
            frame, requested_n=requested_n, contest_shapes=contest_shapes)))
    for prefix, rows in sources:
        for c in rows:
            roster = tuple(str(p) for p in (c.get("roster_slot_ids") or []))
            if roster in seen:
                continue
            seen.add(roster)
            c = dict(c)
            c["candidate_id"] = c["lineup_id"] = f"{prefix}{c['candidate_id']}"
            out.append(c)
    return cs.tag_sleeves(out)


def _direct_door_sleeves(
    candidates: Sequence[Mapping[str, Any]],
    projections: Any,
    request: Mapping[str, Any],
    *,
    requested_n: int,
    contest_shapes: Optional[Sequence[str]],
    time_budget_s: float,
    **extend_kwargs: Any,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """R406. The direct door's sleeve jobs in throwaway caches, appended to its
    in-memory candidates with ids that cannot collide and rosters that are not
    served twice."""
    import tempfile as _tf
    from mlb_engine.allocate.contest_allocator import (
        _candidate_ordered_roster, consensus_cluster_members)
    from mlb_engine.optimize.bank_cache import BankCache
    from mlb_engine.optimize.classic_sleeves import environment_teams_of, tag_sleeves
    env_teams = environment_teams_of(request)
    out = tag_sleeves([dict(c) for c in candidates], env_teams)
    seen = set()
    for c in out:
        try:
            seen.add(tuple(sorted(_candidate_ordered_roster(c))))
        except ValueError:
            continue
    leverage = extend_kwargs.pop("leverage", None)
    with _tf.TemporaryDirectory(prefix="sleeve_bank_") as tmp:
        cache = BankCache(Path(tmp) / "sleeves.json")
        salary = BankCache(Path(tmp) / "salary_only.json")
        jobs = build_sleeve_jobs(
            cache, projections, request,
            consensus_members=consensus_cluster_members(out)["member_ids"],
            time_budget_s=time_budget_s, salary_cache=salary,
            leverage=leverage, **extend_kwargs)
        extra = tag_sleeves(cache.as_candidates(
            projections, requested_n=requested_n, contest_shapes=contest_shapes), env_teams)
        for c in extra:
            c["candidate_id"] = c["lineup_id"] = f"slv{c['candidate_id']}"
        extra += sleeve_candidates(cache, salary, projections, requested_n=requested_n,
                                   contest_shapes=contest_shapes, base=extra)
    added = 0
    for c in extra:
        sig = tuple(sorted(str(p) for p in (c.get("roster_slot_ids") or [])))
        if sig in seen:
            continue
        seen.add(sig)
        out.append(c)
        added += 1
    jobs = {**jobs, "candidates_added": added}
    return out, jobs

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


# R126. A lineup is only materially exposed to a game it draws real bats from.
# The same threshold qa_portfolio uses for its own axes, kept identical on
# purpose so a reader comparing the two reports is comparing the same object.
FRONTIER_MATERIAL_BATS = 3


def _correlated_block_report(
    rosters: Sequence[Tuple[str, Sequence[str]]],
    name_of: Optional[Mapping[str, str]] = None,
) -> Dict[str, Any]:
    """R247(c) axis one: the worst k-subset and the top-trio spread.

    The washout objective binds at the PORTFOLIO level -- correlated failure
    ACROSS entries, per CLAUDE.md's dual-objective note -- and no counter
    reported it. `max_shared_players` bounds one PAIR of lineups, the exposure
    caps bound one PERSON across the set, and neither answers "how many entries
    die together": a block of three players in seven of twenty-three entries is
    seven entries that fail as one, with every pairwise bound and every
    exposure cap clean. The fragment's measured example is worst triple 7 of 23
    and 11 of 23 carrying at most one of the top trio.

    Counted off each entry's OWN subsets, which is exact: a k-subset shared by
    m entries is counted m times and never missed, because every entry
    containing it enumerates it. 45 pairs and 120 triples per 10-slot entry.

    Deterministic review proxy. A count of entries, never a probability that
    they fail.
    """
    import itertools
    rows = [(str(eid), sorted({str(p).strip() for p in ids if str(p).strip()}))
            for eid, ids in (rosters or [])]
    rows = [(eid, ids) for eid, ids in rows if ids]
    n = len(rows)
    out: Dict[str, Any] = {
        "available": False, "unavailable_reason": None, "entries": n,
        "is_review_proxy": True,
    }
    if n < 2:
        out["unavailable_reason"] = (
            "a correlated block is a property of two or more entries; this "
            f"portfolio has {n}")
        return out

    def label(pid: str) -> str:
        nm = (name_of or {}).get(pid) or ""
        return f"{nm} ({pid})" if nm else pid

    exposure: Counter = Counter()
    for _eid, ids in rows:
        exposure.update(ids)
    worst: Dict[str, Any] = {}
    for k in (2, 3):
        counts: Counter = Counter()
        for _eid, ids in rows:
            if len(ids) >= k:
                counts.update(itertools.combinations(ids, k))
        if not counts:
            continue
        # Tie-break on the player ids so the named block does not move run to
        # run: identical-count blocks are routine on a small slate.
        block, cnt = max(counts.items(), key=lambda kv: (kv[1], tuple(kv[0])))
        worst[f"worst_{'pair' if k == 2 else 'triple'}"] = {
            "players": [label(p) for p in block],
            "player_ids": list(block),
            "entries_sharing": cnt,
            "entries_sharing_pct": round(100.0 * cnt / n, 1),
        }
    out.update(worst)

    # The top trio by exposure, tie-broken on the id. "At most one of the top
    # trio" is the spread half of the same fact: the worst block says how many
    # entries die together, this says how many are clear of the concentration.
    trio = [p for p, _c in sorted(exposure.items(), key=lambda kv: (-kv[1], kv[0]))[:3]]
    at_most_one = sum(1 for _eid, ids in rows if len(set(ids) & set(trio)) <= 1)
    out["available"] = True
    out["top_trio"] = [label(p) for p in trio]
    out["top_trio_exposure"] = [[label(p), exposure[p]] for p in trio]
    out["entries_with_at_most_one_of_top_trio"] = at_most_one
    out["entries_with_at_most_one_of_top_trio_pct"] = round(100.0 * at_most_one / n, 1)
    out["distinct_rostered_players"] = len(exposure)
    out["note"] = (
        "correlated failure across ENTRIES, which is where the washout "
        "objective binds; deterministic review proxies, never a probability "
        "that a block fails. entries_sharing counts ENTERED rows, so two "
        "entries holding one lineup count twice -- they die together and pay "
        "twice. A report, never a gate")
    return out


def compute_portfolio_frontier(
    projections: Any, assignments: Sequence[Mapping[str, Any]]
) -> Dict[str, Any]:
    """Both ends of Ben's dual objective over the ENTERED set, off ``Ceiling``.

    R126. Ben named the objective on 2026-08-15 -- "dually optimize apex
    lineups with preventing a total washout across the portfolio" -- and until
    now neither term existed anywhere in the engine, the brief, or the skill.
    BUILD hand-rolled both in a scratch script to choose among five variants of
    the 2138_2g slate, which means the numbers that decided a delivery were not
    reproducible run to run and not comparable across slates. Computing them
    here makes them an artifact of the run instead of a chat message.

    APEX is the portfolio's ceiling total, its mean per entry, and its best
    single entry, summed off this run's own ``Ceiling`` column.

    WASHOUT is a per-game counterfactual: zero that game's HITTERS, keep the
    arms, and report the percent of portfolio ceiling retained, plus a
    histogram over entries of how many bats each draws from that game. The arms
    are kept deliberately -- an arm in a game that goes badly for hitters is
    the one roster spot that may benefit from it -- and the histogram is the
    part that earned its place, because on 2138_2g it was the only thing
    separating two builds that passed identical gates: the rejected build drew
    4-5 bats from one game in EVERY entry, the delivered build ranged from 0 to
    8 across the same nineteen.

    Measured over the ENTERED set, one row per entry rather than per distinct
    lineup. Two entries holding the same lineup die together, and correlated
    failure across ENTRIES is what the washout objective binds on (CLAUDE.md's
    dual-objective note says so, and it is why this is not a floor metric).

    A counterfactual over data already in hand: no solve, no network, nothing
    that can delay a build. Deterministic review proxies throughout. ``Ceiling``
    is a projection input, not an observed outcome, so nothing here is a
    probability, a win rate, a cash rate, or a payout estimate.
    """
    n = len(assignments or [])
    out: Dict[str, Any] = {
        "entries": n,
        "available": False,
        "unavailable_reason": None,
        "is_review_proxy": True,
    }
    if not n:
        out["unavailable_reason"] = "no assignments to measure"
        return out
    if not hasattr(projections, "columns"):
        out["unavailable_reason"] = "the frontier requires a projections DataFrame"
        return out
    cols = set(projections.columns)
    if "Player_ID" not in cols or "Ceiling" not in cols:
        # R127's boundary, applied deliberately: a missing INPUT is one fact
        # about the build, not one fact per player, so it reports a reason and
        # no list. The alternative -- a zero-valued apex block -- reads as a
        # portfolio with no ceiling, which is the failure R127 exists to stop.
        out["unavailable_reason"] = (
            "this run's projections carry no Ceiling column, so no ceiling "
            "proxy exists for it")
        return out

    game_col = next((c for c in ("Game_ID", "GameId", "Game") if c in cols), None)
    pos_col = next((c for c in ("Position", "Assigned_Position", "Roster_Position")
                    if c in cols), None)
    ceiling: Dict[str, float] = {}
    game_of: Dict[str, str] = {}
    salary_of: Dict[str, float] = {}
    name_of: Dict[str, str] = {}
    pitchers: set = set()
    for _, r in projections.iterrows():
        pid = str(r.get("Player_ID") or "").strip()
        if not pid:
            continue
        # R247(a). Salary and Name are read on the same pass and are BOTH
        # optional: a frame without Salary loses the salary-left trigger and
        # keeps the proxy one, which is why the two triggers sit beside each
        # other in `degraded_entry_flags` rather than one inside the other.
        if "Salary" in cols:
            try:
                salary_of[pid] = float(r.get("Salary"))
            except (TypeError, ValueError):
                pass
        if "Name" in cols:
            name_of[pid] = str(r.get("Name") or "").strip()
        # Classification first, ceiling second. An unparseable Ceiling must not
        # also cost the row its game and its position: a player who fell out of
        # `ceiling` while staying out of `pitchers` would be counted as a bat in
        # whatever game key an empty cell produced.
        if game_col is not None:
            game_of[pid] = str(r.get(game_col) or "").strip()
        if pos_col is not None:
            toks = {t.strip().upper() for t in str(r.get(pos_col) or "").split("/")}
            if toks & {"P", "SP", "RP"}:
                pitchers.add(pid)
        try:
            ceiling[pid] = float(r.get("Ceiling"))
        except (TypeError, ValueError):
            continue
    # `sp_ids` is the assignment's own statement of which two ids are arms,
    # which beats inferring it from a Position token; the Position read above is
    # the fallback for a frame whose assignments predate that field.
    for a in assignments:
        for pid in (a.get("sp_ids") or []):
            pitchers.add(str(pid).strip())

    rosters: List[Tuple[str, List[str]]] = []
    unpriced: set = set()
    for a in assignments:
        ids = [str(x).strip() for x in (a.get("lineup_ids") or []) if str(x).strip()]
        rosters.append((str(a.get("entry_id") or ""), ids))
        unpriced.update(p for p in ids if p not in ceiling)

    totals = [(sum(ceiling.get(p, 0.0) for p in ids), eid) for eid, ids in rosters]
    ceiling_total = sum(t for t, _ in totals)
    # Tie-break on the entry id so a slate of identical-ceiling entries names
    # the same one every run. Ceilings here come off a uniform multiplier over a
    # small set of base values, so exact ties are routine (determinism.py).
    best = max(totals)
    worst = min(totals)
    out["available"] = True
    out["apex"] = {
        "ceiling_total": round(ceiling_total, 2),
        "ceiling_mean": round(ceiling_total / n, 2),
        "ceiling_best": round(best[0], 2),
        "best_entry_id": best[1],
        "ceiling_worst": round(worst[0], 2),
        "worst_entry_id": worst[1],
    }
    # R247(a). The degraded-tail flag, on the ENTERED set, beside the apex block
    # a reader has already reached. The bars and their provenance come from
    # `field_miner`, which owns the "at the cap" vocabulary and the salary-left
    # bins the archive is described in; restating either here is how the two
    # start disagreeing about one dollar amount.
    # Lazily, the way `slate_intake_manager` already imports this module's
    # `normalize_name`: it is the established shape for taking a definition from
    # field_miner rather than restating it, and it keeps a review-only module off
    # the engine's load-time import graph.
    from mlb_engine.field.field_miner import degraded_entry_flags
    proxy_by_entry = {eid: total for total, eid in totals}
    out["degraded_entries"] = degraded_entry_flags([
        {
            "entry_id": eid,
            "proxy": proxy_by_entry.get(eid),
            "salary_used": (sum(salary_of[p] for p in ids if p in salary_of)
                            if salary_of and all(p in salary_of for p in ids)
                            else None),
        }
        for eid, ids in rosters
    ])
    # R247(c) axis one: the worst k-subset and the top trio. Counted by walking
    # each ENTRY's own C(10,k) subsets rather than every k-subset of the rostered
    # pool, which is both exact and cheap -- 45 pairs and 120 triples per entry
    # against C(100,3) = 161,700 triples for a 100-player pool.
    out["correlated_block"] = _correlated_block_report(rosters, name_of)
    out["roster_players"] = sum(len(ids) for _, ids in rosters)
    out["unpriced_roster_players"] = sorted(unpriced)
    if unpriced:
        out["unpriced_note"] = (
            f"{len(unpriced)} rostered player(s) carry no Ceiling in this run's "
            "projections, so every total here is SHORT by their ceiling. Named "
            "rather than zeroed, because a silent zero reads as a low-ceiling "
            "portfolio instead of a missing join")

    if game_col is None:
        out["washout"] = {
            "available": False,
            "unavailable_reason": (
                "this run's projections carry no game column, so the per-game "
                "counterfactual cannot be built"),
        }
        out["note"] = _FRONTIER_NOTE
        return out

    by_game: List[Dict[str, Any]] = []
    # Only games the portfolio draws a BAT from. A game nobody is exposed to
    # retains 100% with every entry intact, which is arithmetic rather than a
    # finding, and it would dilute the ordering below.
    touched = sorted({game_of.get(p, "") for _, ids in rosters for p in ids
                      if p not in pitchers and game_of.get(p, "")})
    # R247(c) axis two. `entries_fully_intact` cannot tell a designed hedge from
    # an entry that had nothing at stake anywhere, and on 1605_2g it scored the
    # defect as protection: the weaker of two builds showed "2 of 7 entries
    # untouched" against the stronger one's 1 of 7, and its second untouched
    # entry WAS the $10,300-salary-left lineup. It survived a zeroed BAL@ATH
    # because it was cheap and weak, not because it avoided that game on purpose.
    #
    # THREE buckets, not two, and the third is the whole lesson of this cut. The
    # first version keyed "degraded" on R247(a) flagging an entry AT ALL, and its
    # own test caught the consequence: on a slate whose binding game is also the
    # highest-ceiling game -- which is the common case, since the binding game
    # binds by carrying the most portfolio ceiling -- an entry that sits that
    # game out scores below the portfolio median BY CONSTRUCTION. So the proxy
    # trigger fires on every real hedge, and keying on it inverted the very
    # judgement R247(c) exists to make. Money UNSPENT is what separates a dead
    # entry from a hedge (the 1605_2g lineup had $10,300 of it), so the degraded
    # bucket keys on the SALARY trigger; an entry flagged on proxy alone is
    # genuinely ambiguous and gets its own name rather than a forced answer,
    # which is R237's rule and R270(b)'s three-valued return on a third surface.
    deg_block = out.get("degraded_entries") or {}
    dead_ids = set(deg_block.get("flagged_on_salary_entry_ids") or [])
    proxy_only_ids = set(deg_block.get("flagged_on_proxy_only_entry_ids") or [])
    for g in touched:
        bats: List[int] = []
        retained = 0.0
        intact_ids: List[str] = []
        for _eid, ids in rosters:
            drawn = 0
            for p in ids:
                if p not in pitchers and game_of.get(p, "") == g:
                    drawn += 1
                    continue  # zeroed: this is the counterfactual
                retained += ceiling.get(p, 0.0)
            bats.append(drawn)
            if drawn == 0:
                intact_ids.append(str(_eid))
        hist: Dict[int, int] = {}
        for k in bats:
            hist[k] = hist.get(k, 0) + 1
        intact_dead = sorted(e for e in intact_ids if e in dead_ids)
        intact_proxy_only = sorted(e for e in intact_ids if e in proxy_only_ids)
        by_game.append({
            "game": g,
            "ceiling_retained_pct": (round(100.0 * retained / ceiling_total, 1)
                                     if ceiling_total else None),
            "entries_fully_intact": hist.get(0, 0),
            # The split, per game, on the same footing as the count it corrects.
            # The three partition it: a hedge, an entry with nothing at stake,
            # and one this measure cannot tell apart.
            "entries_intact_by_design": (len(intact_ids) - len(intact_dead)
                                         - len(intact_proxy_only)),
            "entries_intact_but_degraded": len(intact_dead),
            "entries_intact_proxy_only": len(intact_proxy_only),
            "intact_but_degraded_entry_ids": intact_dead,
            "intact_proxy_only_entry_ids": intact_proxy_only,
            "entries_materially_exposed": sum(
                1 for k in bats if k >= FRONTIER_MATERIAL_BATS),
            "max_bats_in_one_entry": max(bats),
            "bats_histogram": [[k, hist[k]] for k in sorted(hist)],
        })
    # Worst first, then the game id, so the binding game is by_game[0] and the
    # ordering does not move between runs on a tie.
    by_game.sort(key=lambda d: (d["ceiling_retained_pct"]
                                if d["ceiling_retained_pct"] is not None else 0.0,
                                d["game"]))
    binding = by_game[0] if by_game else None
    out["washout"] = {
        "available": bool(by_game),
        "games_measured": len(by_game),
        "by_game": by_game,
        "binding_game": binding["game"] if binding else None,
        "worst_ceiling_retained_pct": (binding["ceiling_retained_pct"]
                                      if binding else None),
        "entries_fully_intact_at_binding_game": (binding["entries_fully_intact"]
                                                 if binding else None),
        # R247(c). The number above is the one that misled on 1605_2g, so its
        # split travels beside it at the top level and not only inside by_game.
        "entries_intact_by_design_at_binding_game": (
            binding["entries_intact_by_design"] if binding else None),
        "entries_intact_but_degraded_at_binding_game": (
            binding["entries_intact_but_degraded"] if binding else None),
        "entries_intact_proxy_only_at_binding_game": (
            binding["entries_intact_proxy_only"] if binding else None),
        "note": (
            "each row zeroes that game's HITTERS and keeps every arm, so "
            "ceiling_retained_pct is bounded below by the arms plus the other "
            "games' bats and it FALLS as the slate shrinks: a 2-game slate "
            "cannot retain what a 10-game slate does and the two numbers are "
            "NOT comparable across slates. entries_fully_intact is comparable, "
            "and it is the number that separated the two 2138_2g builds -- a "
            "portfolio where every entry draws bats from the binding game has "
            "nothing left when that game goes cold, whatever its retained "
            "percent. R247(c): read entries_intact_by_design, not "
            "entries_fully_intact. An entry with money UNSPENT that is 'intact' "
            "here survived by having nothing at stake, which is a cost counted "
            "as protection. entries_intact_proxy_only is neither answer and says "
            "so: on a slate whose binding game carries the most ceiling, sitting "
            "that game out costs proxy by construction, so a low proxy alone "
            "cannot distinguish a hedge from a badly built entry"),
    }
    out["note"] = _FRONTIER_NOTE
    return out


_FRONTIER_NOTE = (
    "apex and washout are deterministic review proxies over the entered set, "
    "computed off this run's own Ceiling column. Ceiling is a projection input, "
    "not an observed outcome, so neither is a probability, a win rate, a cash "
    "rate, or a payout estimate. The two move together by construction: "
    "concentration raises apex and raises washout exposure on the same axis, so "
    "a build chooses a point on that frontier rather than maximizing both"
)


def _portfolio_frontier(
    projections: Any, assignments: Sequence[Mapping[str, Any]]
) -> Dict[str, Any]:
    """Diagnostic only: never raises, never blocks (the `_bank_coverage` rule)."""
    try:
        return compute_portfolio_frontier(projections, assignments)
    except Exception as exc:  # noqa: BLE001 - a review proxy must not kill a run
        return {"available": False,
                "unavailable_reason": f"frontier diagnostic unavailable: {exc}",
                "is_review_proxy": True}


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


def derive_roster_id_maps(projections: Any) -> Dict[str, Any]:
    """player id -> team and player id -> game, read off the projection frame.

    R333, and the defect is that this function did not exist. The game-exposure
    control has been complete in the allocator since R61 and in the post-export
    validator since R215, ``late_swap.py:214`` names it as THE binding control
    on a ``game G exposure N>M`` refusal, and no production caller anywhere ever
    wrote ``controls['player_game_by_id']`` -- so an operator who did exactly
    what the swap tool steers them to do got ``passed: False`` and
    ``max_game_exposure_pct_by_game requires controls['player_game_by_id']``.
    The only writers repo-wide were two lines of ``tests/test_core.py`` handing
    the map in by hand, which is why the gap never showed.

    R343's team footprint needs the same shape from the same frame, so both maps
    are derived here, once, and threaded to every door through the control merge
    rather than assembled per caller. That is CC-1's lesson applied: R340 found
    THREE production doors where its entry named two, and a second derivation
    would be the copy that disagrees.

    Defensive by construction. A frame without ``Game_ID`` or ``TeamAbbrev``
    yields an empty map for that axis and the consumers report ``unknown``,
    which is a stated absence. It never raises and never invents an id.
    """
    out: Dict[str, Any] = {
        "player_team_by_id": {}, "player_game_by_id": {},
        "teams": [], "games": [], "note": "",
    }
    try:
        import pandas as _pd  # noqa: F401
        frame = projections
        if not hasattr(frame, "columns"):
            out["note"] = "projections is not a frame; no id maps derived"
            return out
        cols = {str(c) for c in frame.columns}
        id_col = "Player_ID" if "Player_ID" in cols else None
        if id_col is None:
            out["note"] = "frame carries no Player_ID column"
            return out
        team_col = "TeamAbbrev" if "TeamAbbrev" in cols else (
            "Team" if "Team" in cols else None)
        game_col = "Game_ID" if "Game_ID" in cols else None
        for _, row in frame.iterrows():
            pid = str(row[id_col]).strip()
            if not pid:
                continue
            if team_col:
                team = str(row[team_col] or "").strip().upper()
                if team:
                    out["player_team_by_id"][pid] = team
            if game_col:
                gid = str(row[game_col] or "").strip()
                if gid and gid.lower() not in {"nan", "none"}:
                    out["player_game_by_id"][pid] = gid
        out["teams"] = sorted(set(out["player_team_by_id"].values()))
        out["games"] = sorted(set(out["player_game_by_id"].values()))
        if not game_col:
            out["note"] = "frame carries no Game_ID column"
    except Exception as exc:  # defensive: an id map never blocks a build
        out["note"] = f"id maps unavailable: {exc}"
    return out


def resolve_game_exposure_request(
    controls: Optional[Mapping[str, Any]],
    games: Sequence[str],
    weather_game_caps: Optional[Mapping[str, float]] = None,
) -> Dict[str, Any]:
    """The per-game cap dict the allocator enforces, from the three sources.

    R333 fix (2) and (3). Three writers, one reader, merged by MIN because every
    one of them is a CEILING and a portfolio has to satisfy all of them:

    ``max_game_exposure_pct`` -- the slate-wide scalar this item adds, which
    expands to every game id in the frame. Until it existed the only shape was a
    per-game dict an operator had to type, which is why the control had no
    posture default, no place in the relaxation vocabulary, and no mention in
    SKILL.md (grep, 0 hits). Ships ABSENT: R333's own fix says default OFF until
    Ben sets one, and the expansion is recorded either way so the default's
    absence is visible rather than merely true.

    ``max_game_exposure_pct_by_game`` -- the operator's explicit per-game dict,
    unchanged, and it wins where it is tighter.

    ``weather_game_caps`` -- the F5 material-weather cap (0.25 on medium
    postponement risk). It was computed and then dropped: ``build_slate``'s F5
    report has carried ``game_exposure_caps`` since the factor shipped and
    nothing read it into a control, R197's shape exactly. One warning about it,
    which cost this item a re-read rather than a guess: the F5 report keys that
    dict by TEAM while ``slate_intake_manager.material_weather_adjustments``
    keys its own by GAME ID, two different keyings under one name. The caller
    resolves teams to game ids before handing them here; this function takes
    game ids only.

    Truthful labels: a cap is search and portfolio shape, never a probability
    that a game is washed out.
    """
    merged = dict(controls or {})
    explicit = {str(k): float(v)
                for k, v in (merged.get("max_game_exposure_pct_by_game") or {}).items()}
    weather = {str(k): float(v) for k, v in (weather_game_caps or {}).items()}
    try:
        scalar = merged.get("max_game_exposure_pct")
        scalar = float(scalar) if scalar is not None else None
    except (TypeError, ValueError):
        scalar = None
    if scalar is not None and scalar <= 0:
        scalar = None

    per_game: Dict[str, float] = {}
    if scalar is not None:
        for gid in sorted({str(g) for g in games if str(g)}):
            per_game[gid] = scalar
    for gid, pct in sorted(explicit.items()):
        per_game[gid] = min(per_game[gid], pct) if gid in per_game else pct
    weather_applied: List[Dict[str, Any]] = []
    for gid, pct in sorted(weather.items()):
        before = per_game.get(gid)
        after = pct if before is None else min(before, pct)
        if before is None or after < before:
            weather_applied.append(
                {"game_id": gid, "from": before, "to": after,
                 "reason": "F5 material weather (postponement risk)"})
        per_game[gid] = after

    return {
        "scalar_pct": scalar,
        "scalar_expanded_to": sorted(per_game) if scalar is not None else [],
        "explicit_by_game": explicit or None,
        "weather_game_caps_applied": weather_applied,
        "per_game": per_game,
        "games_known": sorted({str(g) for g in games if str(g)}),
        "counts": "roster_footprint",
        "note": ("R150, decided 2026-09-15 (Ben): the count is every rostered "
                 "player in the game, arms included, because a washout is a "
                 "game outcome and the arm is in it. The allocator's rows have "
                 "always counted this way; the decision makes it load-bearing "
                 "rather than silent."),
    }


#: The two id maps the merge stamps into the controls for the allocator. They
#: are inputs to a constraint, not controls an operator reads, and a slate's
#: worth of them is several hundred rows -- so every REPORTING surface publishes
#: their size instead of their contents. `controls_for_report` is the one place
#: that redaction happens; the allocator always receives the whole thing.
CONTROL_ID_MAP_KEYS = ("player_team_by_id", "player_game_by_id")



# R407, Ben's decisions of 2026-09-23. Caps that scale with input confidence.
# 1905_10g built with no odds (`f1_games_priced: 0`), no handedness
# (`f4_platoon_applied: 0`), Savant data 23 days old and, on the first build,
# 12 of 20 sides from a 48.9-day-old platoon file. The brief recorded each fact
# and the build concentrated exactly as it would on a clean night: nothing read
# a degradation back into the controls. Two tiers from four facts, each fact the
# one the brief already prints: DEGRADED is exactly one, SEVERE two or more.
# A deterministic schedule over labeled inputs, never a probability that the
# projection is wrong.
INPUT_CONFIDENCE_TIGHTENING: Dict[str, Dict[str, float]] = {
    "degraded": {"max_player_exposure_pct": 0.05,
                 "max_consensus_cluster_share_pct": 0.10},
    "severe": {"max_player_exposure_pct": 0.10,
               "max_consensus_cluster_share_pct": 0.20},
}
INPUT_CONFIDENCE_FACTS = ("no_odds_priced", "stale_platoon_reference",
                          "stale_savant_expected_stats", "no_handedness")
#: The provenance a tightened value carries. R407 wrote the word first; since
#: R388(b) it lives in `gate_classes.CONTROL_PROVENANCES` with the other six.
from mlb_engine.entries.gate_classes import (  # noqa: E402
    PROV_CONFIDENCE_DERIVED as CONFIDENCE_DERIVED,
    PROV_ENGINE_DEFAULT as _PROV_ENGINE_DEFAULT,
)


def resolve_input_confidence(facts: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """R407. The tier, from the four facts the brief already carries.

    ``facts`` is what `build_slate.input_confidence_facts` read off the brief's
    own enrichment block, reference status and pool report -- one reader of
    each fact, not a second derivation. ``None`` means the caller supplied none
    (a direct `run_slate` caller: a test, the golden replay), and the tier is
    ``not_assessed``, which tightens nothing and says so. A fact whose input is
    absent is ``unknown``, never fired: an absent measurement is not a bad one.
    """
    if facts is None:
        return {"assessed": False, "tier": "not_assessed", "fired": [],
                "facts": {}, "note": "no input-confidence facts supplied by the "
                                     "caller; nothing was tightened"}
    from mlb_engine.intake.live_data_adapters import PLATOON_AGE_BLOCK_DAYS
    f = dict(facts)

    def _fact(value_known: bool, fired: bool, value: Any, rule: str) -> Dict[str, Any]:
        return {"state": ("fired" if fired else "clear") if value_known else "unknown",
                "value": value, "rule": rule}

    priced = f.get("f1_games_priced")
    platoon_age = f.get("platoon_age_days")
    platoon_sides = list(f.get("platoon_dependent_teams") or [])
    savant = dict(f.get("savant_expected_stats") or {})
    f4_applied = f.get("f4_platoon_applied")
    hitters = f.get("hitters_in_pool")
    table = {
        "no_odds_priced": _fact(
            priced is not None, priced is not None and int(priced) == 0,
            priced, "enrichment.counts.f1_games_priced == 0"),
        "stale_platoon_reference": _fact(
            platoon_age is not None or not platoon_sides,
            platoon_age is not None and bool(platoon_sides)
            and int(platoon_age) > PLATOON_AGE_BLOCK_DAYS,
            {"age_days": platoon_age, "sides": platoon_sides},
            f"a side the pool used came from a platoon reference older than "
            f"{PLATOON_AGE_BLOCK_DAYS} days (R27's check)"),
        "stale_savant_expected_stats": _fact(
            bool(savant), any(bool(v.get("stale")) for v in savant.values()),
            {k: v.get("age_days") for k, v in sorted(savant.items())},
            "an expected_stats file past the enrichment age warning's own "
            "threshold (reference_status `stale`)"),
        "no_handedness": _fact(
            f4_applied is not None and hitters is not None,
            f4_applied is not None and hitters is not None
            and int(hitters) > 0 and int(f4_applied) == 0,
            {"f4_platoon_applied": f4_applied, "hitters_in_pool": hitters},
            "enrichment.counts.f4_platoon_applied == 0 with hitters in the pool"),
    }
    fired = [name for name in INPUT_CONFIDENCE_FACTS if table[name]["state"] == "fired"]
    tier = "severe" if len(fired) >= 2 else "degraded" if len(fired) == 1 else "clean"
    return {"assessed": True, "tier": tier, "fired": fired, "facts": table,
            "note": "a deterministic tier over the brief's own degradation facts; "
                    "never a probability that the projection is wrong"}


def apply_input_confidence(
    controls: Mapping[str, Any],
    confidence: Mapping[str, Any],
    *,
    floors: Optional[Mapping[str, Any]] = None,
    override_keys: Iterable[str] = (),
    relax: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """R407. Tighten the two caps by the tier's schedule, and say what moved.

    Floors win (``max(tightened, floor)``), so the tightening can never push a
    cap below what the slate can carry, and the result never exceeds the cap it
    started from (R388(b)): a never-relax cap already below its floor stays put. An explicit override of either key wins
    over the tightening. A cap already at 1.0 is OFF and stays off: tightening
    it would switch on a control no posture asked for. ``relax`` names why the
    tightening is not applied this solve -- ``deadline_t30`` (R386: inside T-30
    it is the FIRST thing relaxed) or ``proven_infeasible`` (the first thing
    relaxed on a refused joint MILP) -- and the block still records the before
    and the would-be after, so the relaxation is counted rather than silent.
    """
    out = dict(controls)
    tier = str(confidence.get("tier") or "not_assessed")
    schedule = INPUT_CONFIDENCE_TIGHTENING.get(tier) or {}
    overrides = {str(k) for k in override_keys}
    changes: Dict[str, Any] = {}
    for key, delta in sorted(schedule.items()):
        before = out.get(key)
        if before is None:
            changes[key] = {"before": None, "after": None, "delta": delta,
                            "source": "not_declared"}
            continue
        if key in overrides:
            changes[key] = {"before": before, "after": before, "delta": delta,
                            "source": "operator_override"}
            continue
        if float(before) >= 1.0:
            changes[key] = {"before": before, "after": before, "delta": delta,
                            "source": "off_stays_off"}
            continue
        floor_val = (floors or {}).get(key)
        target = round(float(before) - float(delta), 4)
        # R388(b). Capped at `before`: a tightening never loosens. A cap held
        # below its feasibility floor by `--never-relax` would otherwise come
        # back AT the floor, the exact move the never-relax blocked. For every
        # other cap `before` is already at or above its floor after the merge,
        # so the cap changes nothing there.
        after = round(min(float(before),
                          max(target, float(floor_val) if floor_val else 0.0)), 4)
        if after <= 0.0:
            after = float(before)
        entry = {"before": before, "after": after, "delta": delta,
                 "floor": floor_val, "source": CONFIDENCE_DERIVED,
                 "floor_won": bool(floor_val) and after > target}
        if relax:
            entry = {**entry, "after": before, "would_be": after,
                     "source": f"relaxed_{relax}"}
        else:
            out[key] = after
        changes[key] = entry
    applied = any(v.get("source") == CONFIDENCE_DERIVED for v in changes.values())
    block = {**dict(confidence), "changes": changes, "applied": applied,
             "relaxed": relax, "provenance": CONFIDENCE_DERIVED if applied else None}
    return out, block

def _control_provenance_block(
    controls: Mapping[str, Any],
    provenance: Mapping[str, Any],
    input_confidence: Mapping[str, Any],
    never_relax: Iterable[str],
    control_moves: Optional[Sequence[Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    """R388(b). One row per resolved control: its value and its provenance.

    ``provenance`` is what `_merged_controls_for_build` wrote as each layer
    landed. Two layers run after it and are applied here, in order:

    * R407's tightening: a cap the tier moved is `confidence_derived`, unless
      the operator named it never-relax, which outranks every source. That is
      true of the value because `apply_input_confidence` caps its result at
      the value it started from, so a tightening never loosens a held cap,
      even one held below its feasibility floor.
    * The deadline governor's ``control_moves``: its opened values arrive as an
      override, so without this the row would read `operator_relaxable` for a
      number no operator typed. A moved row keeps the provenance the control
      had BEFORE the move, the authority the rung relaxed, and says what moved
      it under ``relaxed``. A control the rung added where none was set had no
      provenance to keep; its value is the governor's fixed engine table, so
      it reads `engine_default`.

    F-3's distinct lineups per contest has a row on every build although it is
    no key in the controls dict: the allocator enforces it unconditionally and
    the validator fails `roster_legality_passed` on a breach.
    """
    from mlb_engine.entries import gate_classes as _gc  # noqa: PLC0415
    holding = {str(k) for k in (never_relax or ())}
    prov = {k: (dict(v) if isinstance(v, Mapping) else v)
            for k, v in (provenance or {}).items()}
    for key, change in sorted(((input_confidence or {}).get("changes") or {}).items()):
        if (isinstance(change, Mapping) and change.get("source") == CONFIDENCE_DERIVED
                and key not in holding and key in prov):
            prov[key] = _gc.PROV_CONFIDENCE_DERIVED
    moved: Dict[str, Any] = {}
    for move in control_moves or ():
        key = str(move.get("control") or "")
        if not key or key not in controls:
            continue
        prov[key] = move.get("provenance") or _gc.PROV_ENGINE_DEFAULT
        moved[key] = {"from": move.get("before"), "to": move.get("after"),
                      "by": move.get("by"), "reason": move.get("reason")}
    by_control: Dict[str, Any] = {}
    for key in sorted(prov):
        row = {"value": controls.get(key), "provenance": prov[key]}
        if key in moved:
            row["relaxed"] = moved[key]
        by_control[key] = row
    for fact in sorted(_gc.FACT_AUTHORITY):
        by_control.setdefault(fact, {
            "value": True, "provenance": _gc.FACT_AUTHORITY[fact],
            "enforced_by": "the allocator's one-per-signature-per-contest row "
                           "and roster_legality_passed (F-3)"})
    return {
        "by_control": by_control,
        "never_relax": sorted(holding),
        "moved": sorted(moved),
        "vocabulary": list(_gc.CONTROL_PROVENANCES),
        "note": ("where each control's value came from, and whether it may "
                 "relax: every provenance but operator_never_relax may. A typed "
                 "--controls-override value is operator_relaxable; only "
                 "--never-relax (or F-3) holds a control under a deadline"),
    }


def controls_for_report(controls: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """The merged controls as a reader should see them: maps summarised.

    R333 / R343. `merged_controls` is published in the checkpoint and in the
    approved result and read by an operator under a clock. Dropping two
    few-hundred-entry dictionaries into it would bury the six numbers that block
    actually exists to show, and R290(c)'s lesson is precisely about what a
    refusal reads like at T-5. The summary keeps the fact that the map was
    WIRED, which is the only thing about it a reader needs here.
    """
    out = dict(controls or {})
    for key in CONTROL_ID_MAP_KEYS:
        value = out.get(key)
        if isinstance(value, Mapping):
            out[key] = {"wired": True, "players_mapped": len(value),
                        "distinct_values": len({str(v) for v in value.values()})}
    return out


def _merged_controls_for_build(
    posture_by_contest: Mapping[str, Mapping[str, Any]],
    override: Optional[Mapping[str, Any]],
    feasibility_floors: Optional[Mapping[str, Any]] = None,
    shape_bands: Optional[Mapping[str, Any]] = None,
    roster_id_maps: Optional[Mapping[str, Any]] = None,
    weather_game_caps: Optional[Mapping[str, float]] = None,
    *,
    never_relax: Iterable[str] = (),
    provenance_out: Optional[MutableMapping[str, Any]] = None,
    override_provenance: Optional[Mapping[str, str]] = None,
) -> Dict[str, Any]:
    """Merge strategy-default controls across contests (tightest cap wins), floor to
    feasibility, then apply overrides.

    ``feasibility_floors`` raises the tightest-merged repetition caps to a slate-
    feasible minimum. Floors are applied AFTER the min-merge and BEFORE the explicit
    override, so an explicit override always wins over a floor. Default None keeps the
    pre-v1.8 behavior unchanged.

    R388(b). ``never_relax`` names controls a feasibility floor may not raise:
    a floor only ever relaxes a cap, and the operator's `--never-relax` is the
    word that it holds, the same way a typed override already beats a floor. A
    typed override alone is NOT that word, so without the flag nothing here
    changes. ``provenance_out``, when given, is filled with each resolved
    control's provenance (`gate_classes.CONTROL_PROVENANCES`), written layer by
    layer as each value lands so the record and the dict cannot disagree: the
    posture merge, a floor that moved a value, the override, the per-game caps
    (a per-game dict of its own, since weather and the operator both write it),
    and never-relax last, because it outranks every other source. The id maps
    are data, not controls, and carry none. ``override_provenance`` names the
    provenance of override keys that are NOT the operator's: `run_slate` passes
    the deadline rung's moves through it, so a game the opened scalar expands
    into is labelled with the scalar rather than as typed. None of the three
    arguments changes a value except ``never_relax``; every caller that passes
    none gets the dict it got before.
    """
    from mlb_engine.entries import gate_classes as _gc  # noqa: PLC0415
    holding = {str(k) for k in (never_relax or ())}
    prov: Dict[str, Any] = {}
    merged: Dict[str, Any] = {}
    # R343 adds the seventh fraction control and the fourth ceiling that merges
    # to the tightest across contests. It belongs with the other three and not
    # in a set of its own: one portfolio has to satisfy every contest's team
    # ceiling exactly as it satisfies every contest's player ceiling.
    # R405 adds the fifth ceiling. A cluster cap merges by MIN for the same
    # reason: one portfolio has to satisfy every contest's cluster ceiling, and
    # `single_entry` at 1.0 is no opinion that loosens nobody. Its k merges as
    # an integer MIN beside the repetition caps, and a LOWER k is the tighter
    # reading (more lineups count toward the cap), which is the direction MIN
    # takes.
    pct_keys = ("max_player_exposure_pct", "max_pitcher_exposure_pct",
                "max_primary_stack_exposure_pct", "max_team_exposure_pct",
                "max_consensus_cluster_share_pct")
    rep_keys = ("max_sp_pair_repetition", "max_shared_players",
                "consensus_cluster_min_members")
    # R167. The override is the ONLY unvalidated way a control reaches the
    # build: postures and feasibility floors are engine-authored, an override
    # is typed by an operator, and `--controls-override
    # max_pitcher_exposure_pct=45` used to travel all the way to the solve
    # before anything objected. Validate it HERE, the one boundary both the
    # build (run_slate) and the swap (late_swap) pass through, and validate it
    # with the same function the solve enforces so the two cannot disagree.
    #
    # `min_five_stack_share_pct` is included because it is the same units
    # question about a FLOOR: 50 typed for 0.50 is one quota nobody can meet
    # rather than one cap nobody is under. Ownership percentages elsewhere in
    # the engine live in 0-100 space and are deliberately NOT in this set;
    # the four keys named here are the fraction-valued controls the merge
    # itself produces.
    #
    # R215(a). `max_game_exposure_pct_by_game` is the sixth fraction control
    # and was in neither key set, here or in build_slate's gate, while all
    # three `_game_cap_count` sites still clamped with `min(1.0, max(0.0, ...))`.
    # So a per-game units slip (`{"401234": 40}` for 0.40) passed the zero-cost
    # gate, passed this merge, and capped nobody in the solve AND in the
    # post-export validator, with no counter and no warning. R167 kept that
    # clamp on the reasoning that the solve and the validator agree; agreement
    # does not answer SILENT DISABLE, and `late_swap.py` steers operators to
    # override exactly this control. It is dict-valued, so each VALUE is routed
    # through the same rule.
    #
    # R215(c). This validated a copy and then stored the RAW value below, which
    # is a checkpoint that lets the bad value past after saying it looked.
    # Classic re-coerced at `_cap_count` and Showdown did not, so a string
    # `"0.5"` raised TypeError at `"0.5" >= 0.33` in brief assembly and
    # ValueError at `f"{pct:.0%}"` -- both after the full solve. The coerced
    # float is what gets stored.
    #
    # R333 adds `max_game_exposure_pct`, the slate-wide scalar. It is a fraction
    # of the entered set like its five siblings, so it routes through the same
    # units rule; the per-game dict beside it keeps routing each VALUE.
    _fraction_control_keys = pct_keys + ("min_five_stack_share_pct",
                                         "max_game_exposure_pct")
    _fraction_control_dict_keys = ("max_game_exposure_pct_by_game",)
    coerced_override: Dict[str, Any] = dict(override or {})
    for key, value in list(coerced_override.items()):
        if value is None:
            continue
        if key in _fraction_control_keys:
            coerced_override[key] = assert_fraction_cap(value, key=key)
        elif key in _fraction_control_dict_keys:
            if not isinstance(value, Mapping):
                raise ValueError(
                    f"{key} must be an object of game id -> fraction, not "
                    f"{type(value).__name__}")
            coerced_override[key] = {
                gid: assert_fraction_cap(v, key=f"{key}[{gid}]")
                for gid, v in dict(value).items()}
    # R34. Floor keys merge by MIN like the ceilings, but for the opposite
    # reason. A ceiling merges to the tightest because one portfolio must
    # satisfy every contest's ceiling. A floor merges to the LEAST demanding
    # because the same portfolio must be legal for the contest that never asked
    # for the floor, and forcing a 5-stack quota onto a posture that did not
    # request it is a strategy change for that contest, made invisibly.
    # R37 adds `primary_stack_min_size` to the same rule for the same reason.
    # Every posture declares it today, so the unanimity branch below returns 4
    # and the merge is a no-op; the rule still has to hold, because a posture
    # that stops declaring it must retire the floor for the whole portfolio
    # rather than inherit one it never asked for.
    #
    # R37(2)(a)+(b), Ben's dated decision of 2026-08-28. The two live bands enter
    # HERE, as a per-contest DECLARED value layered over the posture default, so
    # every rule below runs on them unchanged. Nothing about the merge changes;
    # what changes is what a contest declares.
    #
    # Why not a posture default, which is where every other construction number
    # in this module lives: the bands are conditioned on PAYOUT BREADTH and SLATE
    # SIZE, and a posture is neither. `wta_satellite` covers a 0.002-breadth
    # one-seat ticket and a 0.22-breadth cut-line satellite alike -- the ledger's
    # own conditioning rule is family x field size x slate size, never pooled,
    # and a posture-keyed default would pool exactly the axis 3.21 says decides
    # the answer. `_resolve_payout_breadth` already resolves breadth per contest,
    # which is what R37(2)(a) meant by "the routing exists".
    _band_floors: Dict[str, Dict[str, Any]] = {}
    for _row in ((shape_bands or {}).get("contests") or []):
        _band_floors[str(_row.get("contest_id"))] = _row
    floor_keys = ("min_five_stack_share_pct", "primary_stack_min_size")

    def _declared_controls(info: Mapping[str, Any], cid: str) -> Dict[str, Any]:
        """A contest's declared controls: its posture default, then its band."""
        base = dict(STRATEGY_DEFAULTS.get(
            info["posture"], STRATEGY_DEFAULTS["large_gpp"])["controls"])
        row = _band_floors.get(str(cid))
        if not row:
            return base
        band_floor = row.get("primary_stack_min_size_declared")
        if band_floor is not None and "primary_stack_min_size" in base:
            # A band may only RAISE the floor, never lower one a posture set.
            base["primary_stack_min_size"] = max(
                int(base["primary_stack_min_size"]), int(band_floor))
        band_quota = row.get("min_five_stack_share_pct_declared")
        if band_quota is not None:
            # Same direction for the quota: a band raises a floor the posture
            # ships at 0.0, and never lowers one already asked for.
            #
            # It also ADDS the key where the posture never had it, and that is
            # load-bearing rather than incidental. Only `wta_satellite` carries
            # `min_five_stack_share_pct` today, while the mid-breadth band's
            # actual population -- large_field_gpp at 0.12, portfolio_gpp and
            # mid_field_gpp at 0.15, small_field_gpp at 0.18 -- is served by
            # `large_gpp` and `small_gpp`, which never declared it. Gating the
            # band on the posture having spoken first would have made (b) live in
            # name and inert on every contest it was sized for. Under R34's rule
            # silence is no opinion, and the band IS an opinion: Ben's, dated,
            # keyed on the axis the ledger conditions on.
            base["min_five_stack_share_pct"] = max(
                float(base.get("min_five_stack_share_pct") or 0.0), float(band_quota))
            base.setdefault("five_stack_min_size", 5)
        return base

    for cid, info in posture_by_contest.items():
        controls = _declared_controls(info, cid)
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
    declared = [_declared_controls(i, cid) for cid, i in posture_by_contest.items()]
    for key in floor_keys:
        vals = [float(c[key] or 0.0) for c in declared if key in c]
        if not vals:
            continue          # nobody asked: the key stays absent entirely
        merged[key] = min(vals) if len(vals) == len(declared) else 0.0
        # R37: a stack SIZE is a count of hitters, and it reaches the brief and
        # the allocator's report as it is written here. `min` over floats would
        # print a floor of 4.0 hitters.
        if key == "primary_stack_min_size":
            merged[key] = int(merged[key])

    # R388(b). Everything so far is what the contests' postures (and their
    # shape bands, a declared value layered over the posture) asked for. The
    # one exception is the stack size a band's quota adds by `setdefault`: no
    # posture declared it, so the number is the engine's.
    for key in merged:
        prov[key] = _gc.PROV_POSTURE_DEFAULT
    if "five_stack_min_size" in merged and not any(
            "five_stack_min_size" in STRATEGY_DEFAULTS.get(
                i["posture"], STRATEGY_DEFAULTS["large_gpp"])["controls"]
            for i in posture_by_contest.values()):
        prov["five_stack_min_size"] = _gc.PROV_ENGINE_DEFAULT

    for key, floor_val in (feasibility_floors or {}).items():
        if floor_val is None or key not in merged:
            # v1.9: a floor may only relax an existing cap, never add one.
            continue
        if key in holding:
            # R388(b): a floor relaxes, and this control is never relaxed.
            continue
        before_floor = merged[key]
        if key in floor_keys:
            # R34: relaxing a LOWER bound means lowering it. Applying the
            # ceiling rule here would raise the quota on exactly the thin slate
            # that could not carry it, which is the failure inverted.
            merged[key] = max(0.0, min(float(merged[key]), float(floor_val)))
        elif key in pct_keys:
            merged[key] = min(1.0, max(float(merged[key]), float(floor_val)))
        else:
            merged[key] = max(int(merged[key]), int(floor_val))
        if merged[key] != before_floor:
            prov[key] = _gc.PROV_DERIVED_FLOOR
    # R215(c). The COERCED override, not the raw one: validating a copy and
    # storing the original is a gate that looks and then lets the value past.
    merged.update(coerced_override)
    # R388(b): a typed cap alone is relaxable (audit §2).
    for key in coerced_override:
        prov[key] = (override_provenance or {}).get(key) or _gc.PROV_OPERATOR_RELAXABLE
    # Never-relax reaches the game scalar before the per-game expansion reads
    # its provenance, so every game the held scalar sets reads held too.
    if "max_game_exposure_pct" in holding and "max_game_exposure_pct" in merged:
        prov["max_game_exposure_pct"] = _gc.PROV_OPERATOR_NEVER_RELAX

    # R333 / R343. The id maps and the resolved per-game caps land HERE, after
    # the override, because this is the one boundary every production door
    # passes through: `run_slate` (the build), `_plan_joint_allocation` (the
    # plan leg, which inherits these controls and must solve the SAME MILP the
    # build will -- the door R340's entry did not name and its own grep found),
    # and `late_swap.py`. Threading them from each caller instead would be the
    # second copy R34's merge rule already taught this file not to keep.
    maps = dict(roster_id_maps or {})
    if maps.get("player_team_by_id"):
        merged["player_team_by_id"] = dict(maps["player_team_by_id"])
    if maps.get("player_game_by_id"):
        merged["player_game_by_id"] = dict(maps["player_game_by_id"])
    game_request = resolve_game_exposure_request(
        merged, list(maps.get("games") or []), weather_game_caps=weather_game_caps)
    if game_request["per_game"]:
        merged["max_game_exposure_pct_by_game"] = dict(game_request["per_game"])
        # R388(b). Per game, because three writers share the dict: the scalar's
        # expansion carries the scalar's provenance, a typed per-game value
        # that is at or under it the operator's, and a weather cap that
        # tightened it `weather_derived`. Read off the request record, which is
        # the same pure function's account of the same merge.
        explicit_prov = prov.get("max_game_exposure_pct_by_game",
                                 _gc.PROV_OPERATOR_RELAXABLE)
        scalar = game_request["scalar_pct"]
        explicit = game_request["explicit_by_game"] or {}
        weathered = {str(w["game_id"]) for w in game_request["weather_game_caps_applied"]}
        by_game: Dict[str, str] = {}
        for gid in game_request["per_game"]:
            source = prov.get("max_game_exposure_pct") if scalar is not None else None
            if gid in explicit and (scalar is None or explicit[gid] <= scalar):
                source = explicit_prov
            if gid in weathered:
                source = _gc.PROV_WEATHER_DERIVED
            by_game[gid] = source or _gc.PROV_ENGINE_DEFAULT
        prov["max_game_exposure_pct_by_game"] = by_game
    for key in holding:
        if key == "max_game_exposure_pct_by_game" and isinstance(prov.get(key), dict):
            prov[key] = {gid: _gc.PROV_OPERATOR_NEVER_RELAX for gid in prov[key]}
        elif key in merged:
            prov[key] = _gc.PROV_OPERATOR_NEVER_RELAX
    if provenance_out is not None:
        provenance_out.clear()
        provenance_out.update(prov)
    # The request record itself is deliberately NOT stashed in the controls.
    # `resolve_game_exposure_request` is a pure function of the merged controls,
    # the game list and the weather caps, so a reporting caller re-derives it
    # from the same three inputs and cannot disagree with this one -- which is
    # the CC-1 shape (one derivation function called at each door) rather than a
    # value carried around in a bag that other readers then have to ignore.
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
        # R343 / R333. Both new ceilings join the v1.9 rule unchanged: a floor
        # may only relax a cap the merge already produced, never add one. That
        # is why `max_game_exposure_pct_by_game` is absent here -- it is
        # dict-valued and ships OFF, and the scalar below is what a floor can
        # reach. Its writers are the operator and the F5 weather cap (R388(b)
        # corrected "until an operator sets one"), and both land in
        # `resolve_game_exposure_request`, after the floors, so a floor never
        # loosens either.
        ("floor_team_exposure_pct", "max_team_exposure_pct"),
        ("floor_game_exposure_pct", "max_game_exposure_pct"),
        # R405. Only the ARITHMETIC half of the cluster cap's feasibility lives
        # here; the rest is bank-dependent and is the allocator's diagnosis.
        ("floor_consensus_cluster_share_pct", "max_consensus_cluster_share_pct"),
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
    "tight_5_with_diversification": 5,   # R37: mme's corrected label, same size
    # R37 retired this name from STRATEGY_DEFAULTS but not from this map. The
    # lookup is fed by archived build records and stored specs as well as by
    # today's postures, and a plan string this map does not know drops silently
    # out of the max-stack computation. Keeping the old key costs one line and
    # keeps a replayed 2026-07 record resolving to the size it resolved to then.
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

    R69(c) splits the two findings this block used to pool under one key, because
    they are not the same kind of fact and the shared label made both of them
    lies. ``blockers`` now holds ONLY the unmatched-exclusion finding, which is
    an operator-supplied identifier that resolves to nothing -- decidable from
    disk, fixed by correcting the same argument, and hard-gated on approve=True
    at the call site exactly like contest identity. ``warnings`` holds the
    Excluded-column finding, which is a data condition in a supplied frame whose
    remedy is a file edit: keeping unrecognized cells is the DOCUMENTED reading
    of that column, so reporting it as a blocker described behaviour working as
    specified.
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
        "warnings": [],
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
            block["warnings"].append(
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
        "game_count": None,
        "floor_team_exposure_count": None, "floor_team_exposure_pct": None,
        "floor_game_exposure_count": None, "floor_game_exposure_pct": None,
        "legal_hitter_count": None, "floor_consensus_cluster_share_pct": None,
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
        # R333. The game denominator, from the same derivation the control merge
        # uses, so the floor and the cap are counted over one game list.
        n_games = len(derive_roster_id_maps(projections)["games"])
        info["game_count"] = n_games or None

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

            # R343. The team FOOTPRINT floor, the same counting argument as the
            # pitcher floor one screen up and for the same reason. A DK Classic
            # lineup holds eight hitters and at most MAX_HITTERS_PER_TEAM from
            # one team, so every entry footprints at least
            # ceil(8 / MAX_HITTERS_PER_TEAM) = 2 teams and some team must take
            # ceil(2E / T) of E entries. Below that value the posture default is
            # arithmetically impossible and the cap is floored UP to it, which is
            # what keeps a one-game Classic slate (T = 2, floor 1.0) from being
            # refused by a control that ships on by default.
            #
            # `stackable_team_count` is the denominator and it is the
            # CONSERVATIVE choice: a team too weak to be stackable can still
            # supply two filler bats, so the true denominator is at least this,
            # the true floor is at most this, and erring here loosens a ceiling
            # rather than tightening one.
            if n_stackable >= 1:
                from mlb_engine.optimize.optimizer_v3 import MAX_HITTERS_PER_TEAM
                per_entry = int(_ceil(8 / max(1, int(MAX_HITTERS_PER_TEAM))))
                tc = int(_ceil((per_entry * entries) / n_stackable))
                info["floor_team_exposure_count"] = tc
                info["floor_team_exposure_pct"] = min(1.0, tc / entries)

            # R333. Every entry touches at least one game -- a DK Classic roster
            # of ten CAN come from a single game -- so the game floor is
            # ceil(E / G), a much looser bound than the team one and usually
            # inert. It exists so a slate-wide scalar cannot be set to a value
            # no portfolio could meet.
            if n_games >= 1:
                gc = int(_ceil(entries / n_games))
                info["floor_game_exposure_count"] = gc
                info["floor_game_exposure_pct"] = min(1.0, gc / entries)

            # R405. The consensus-cluster cap's ARITHMETIC half, and the only
            # half a pool can decide: the cluster itself is defined from the
            # bank, which does not exist yet. A lineup holds eight hitters, so
            # it can carry fewer than k of a cluster of C only if the legal pool
            # has at least 8 - (k - 1) hitters OUTSIDE the cluster. Taken at the
            # largest cluster the definition allows (C = 12) and the engine's k,
            # a pool smaller than that forces every lineup to k or more and the
            # cap floors to 1.0, inert, the way R343's team floor makes a
            # one-game slate inert. The worst-case C errs toward LOOSENING the
            # ceiling. Everything bank-shaped is `_diagnose_binding_constraints`'.
            # Its own guard: a frame this count cannot read must not take the
            # other floors in this block down with it.
            try:
                from mlb_engine.allocate.contest_allocator import (
                    CONSENSUS_CLUSTER_MAX_MEMBERS, CONSENSUS_CLUSTER_MIN_MEMBERS)
                from mlb_engine.optimize.optimizer_v3 import _drop_excluded_rows
                _legal = _drop_excluded_rows(projections)
                _excl = {str(x) for x in (excluded_player_ids or [])}
                n_hitters = int(sum(
                    1 for pos, pid in zip(_legal["Position"], _legal["Player_ID"])
                    if str(pos) != "P" and str(pid) not in _excl))
                info["legal_hitter_count"] = n_hitters
                if (n_hitters - CONSENSUS_CLUSTER_MAX_MEMBERS
                        < 8 - (CONSENSUS_CLUSTER_MIN_MEMBERS - 1)):
                    info["floor_consensus_cluster_share_pct"] = 1.0
            except Exception:  # noqa: BLE001 - advisory, never blocks
                info["legal_hitter_count"] = None

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
    #
    # R167: "mirroring" was aspirational. This copy clamped `pct > 1` where
    # both production copies raise, so the checkpoint printed `45 -> cap 10`
    # and reported the check PASSED against a control the solver would refuse.
    # It now calls the same units rule. In practice
    # `_merged_controls_for_build` has already rejected an override this bad,
    # so reaching the raise here means a control arrived from somewhere that
    # bypassed the merge -- worth a hard failure rather than a clamp that
    # invents a plausible number.
    def _cap_count_local(pct: Any) -> Optional[int]:
        if pct is None:
            return None
        value = assert_fraction_cap(pct)
        if value <= 0:
            return None
        from math import floor as _floor
        return max(1, int(_floor(entries * value + 1e-9)))

    if entries > 1:
        n_sps = feas.get("viable_sp_count")
        n_stackable = feas.get("stackable_team_count")
        # R343 / R333, the two washout-axis ceilings, in the same counting form
        # and for the same reason: an arithmetically impossible cap is a
        # one-read fix here and a bare infeasibility at the solve. Their demand
        # terms differ and the difference is the whole content of each check --
        # an entry footprints at least two TEAMS (eight hitters, five per team
        # maximum) and at least one GAME (a ten-man roster can legally come from
        # one), so the team check is the binding one and the game check is
        # usually inert.
        n_games = feas.get("game_count")
        _team_per_entry = 2
        pct_specs = (
            ("max_pitcher_exposure_pct", "pitcher_exposure_capacity", n_sps,
             2 * entries, "viable SPs", "pitcher slots"),
            ("max_primary_stack_exposure_pct", "stack_exposure_capacity", n_stackable,
             entries, "stackable teams", "entries"),
            ("max_team_exposure_pct", "team_exposure_capacity", n_stackable,
             _team_per_entry * entries, "stackable teams", "team footprint slots"),
            ("max_game_exposure_pct", "game_exposure_capacity", n_games,
             entries, "games", "entries"),
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

        # R405. The arithmetic half only (see `_slate_feasibility`): the check
        # fails when the legal pool cannot seat a lineup below k members of a
        # full-size cluster and the cap was nonetheless held below the entered
        # set, which only an explicit override can do once the floor applied.
        cluster_pct = controls.get("max_consensus_cluster_share_pct")
        n_hitters = feas.get("legal_hitter_count")
        if cluster_pct is not None and n_hitters is not None:
            cap = _cap_count_local(cluster_pct)
            if cap is not None:
                from mlb_engine.allocate.contest_allocator import (
                    CONSENSUS_CLUSTER_MAX_MEMBERS, CONSENSUS_CLUSTER_MIN_MEMBERS)
                forced = feas.get("floor_consensus_cluster_share_pct") is not None
                ok = not (forced and cap < entries)
                detail = (f"max_consensus_cluster_share_pct {cluster_pct} -> cap {cap} "
                          f"of {entries}; the legal pool holds {n_hitters} hitters, "
                          f"and a lineup can carry fewer than "
                          f"{CONSENSUS_CLUSTER_MIN_MEMBERS} of a "
                          f"{CONSENSUS_CLUSTER_MAX_MEMBERS}-member cluster only "
                          f"with >= {8 - (CONSENSUS_CLUSTER_MIN_MEMBERS - 1)} "
                          f"hitters outside it")
                remedy = None
                if not ok:
                    remedy = "raise max_consensus_cluster_share_pct to >= 1.000"
                    report["binding_constraints"].append(
                        f"consensus_cluster_capacity infeasible: {detail}; {remedy}")
                    report["passed"] = False
                report["checks"].append({"name": "consensus_cluster_capacity",
                                         "passed": ok, "detail": detail,
                                         "remedy": remedy})

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
            _plan_stack_request = resolve_bank_stack_request(controls)
            with _tempfile.TemporaryDirectory(prefix="plan_bank_") as tmp:
                cache = BankCache(_Path(tmp) / "plan_bank.json")
                report = extend_bank(
                    cache, bank_projections, time_budget_s=float(budget_s),
                    excludes=excl or None, solver_time_limit_s=solver_time_limit_s,
                    # R293, found by this item's own AST enumeration rather than
                    # named in the entry. The plan leg's whole job is to solve
                    # THE SAME MILP the build will solve (R28, R63): a verdict
                    # produced under a different constraint matrix is a verdict
                    # about a different question, and `would_certify` is exactly
                    # the kind of label CLAUDE.md's truthful-labels rule covers.
                    max_opposing_hitters_per_sp=controls.get(
                        "max_opposing_hitters_per_sp"),
                    # R340, and this site is NOT one of the two the item names --
                    # it is the third, found by re-running its own grep. The
                    # comment directly above says this leg's whole job is to
                    # solve THE SAME MILP the build will solve, and after R340
                    # wires the two build doors that stops being true here: the
                    # build would ask its bank for a five-stack and the plan leg
                    # would keep asking for four, so `would_certify` would be a
                    # verdict about a different question. Same derivation, same
                    # merged controls.
                    stack_min=_plan_stack_request["bank_stack_min_size"],
                )
                # R405(c), the third door for R340's reason: the build's bank
                # carries cluster-limited jobs whenever the cap is below 1.0, so
                # a plan bank without them would prove the cap infeasible
                # against a question the build never asks. Same derivation, same
                # merged controls, the budget that is left; and the same rule as
                # the ordinary call below -- a limited bucket that did not
                # exhaust leaves the verdict unchecked rather than wrong.
                _plan_consensus = resolve_consensus_limited_request(
                    controls, len(entries))
                if _plan_consensus["active"] and report.get("job_list_exhausted"):
                    _left = float(budget_s) - (time.monotonic() - started)
                    _limited = build_consensus_limited_jobs(
                        cache, bank_projections, _plan_consensus,
                        time_budget_s=max(1.0, _left),
                        excludes=excl or None,
                        solver_time_limit_s=solver_time_limit_s,
                        max_opposing_hitters_per_sp=controls.get(
                            "max_opposing_hitters_per_sp"),
                        stack_min=_plan_stack_request["bank_stack_min_size"],
                    )
                    verdict["consensus_limited_jobs"] = {
                        k: v for k, v in _limited.items() if k != "report"}
                    if _limited.get("report") is not None:
                        report = {**report, "job_list_exhausted": bool(
                            _limited["report"].get("job_list_exhausted"))}
                # R406, the plan leg's sleeves, for the same reason: the build's
                # bank carries them and the mask seats entries on them, so a plan
                # bank without them would solve a different MILP. Same helper,
                # same request, a sibling cache for the salary-only frame.
                _plan_sleeves = resolve_sleeve_bank_request(
                    entries, controls, bank_projections)
                _plan_salary_cache = None
                if _plan_sleeves["active"] and report.get("job_list_exhausted"):
                    from mlb_engine.allocate.contest_allocator import (
                        consensus_cluster_members)
                    _plan_salary_cache = BankCache(_Path(tmp) / "plan_bank_salary.json")
                    _left = float(budget_s) - (time.monotonic() - started)
                    verdict["classic_sleeves_jobs"] = build_sleeve_jobs(
                        cache, bank_projections, _plan_sleeves,
                        consensus_members=consensus_cluster_members(
                            cache.as_candidates(None))["member_ids"],
                        time_budget_s=max(1.0, _left), salary_cache=_plan_salary_cache,
                        excludes=excl or None, solver_time_limit_s=solver_time_limit_s,
                        max_opposing_hitters_per_sp=controls.get(
                            "max_opposing_hitters_per_sp"),
                        stack_min=_plan_stack_request["bank_stack_min_size"])
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
                from mlb_engine.optimize.classic_sleeves import (
                    environment_teams_of, tag_sleeves)
                candidates = tag_sleeves(cache.as_candidates(
                    bank_projections,
                    requested_n=int(requested_n or max(len(entries), 1)),
                    contest_shapes=list(contest_shapes) if contest_shapes else None,
                ), environment_teams_of(_plan_sleeves))
                if _plan_salary_cache is not None:
                    candidates += sleeve_candidates(
                        cache, _plan_salary_cache, bank_projections,
                        requested_n=int(requested_n or max(len(entries), 1)),
                        contest_shapes=list(contest_shapes) if contest_shapes else None,
                        base=candidates)
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


def _is_blank(value: Any) -> bool:
    """True for None, empty/whitespace strings, and float NaN.

    A projections CSV read with ``pandas`` turns a blank cell into NaN, so
    ``value in (None, "")`` is not the same question as "did the caller supply
    this" (R57).
    """
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


# --------------------------------------------------------------------------- #
# Neutral-default visibility (R127)
# --------------------------------------------------------------------------- #
# A factor that falls back to its neutral default is INDISTINGUISHABLE in the
# output from a factor that ran and found nothing to move. That is not a
# reporting nicety: on 2026-08-15 an arm absent from the FanGraphs season
# pitching file kept the neutral 1.42 ceiling multiplier, outranked a better
# strikeout arm that was in the file, and took 9 of 19 lineups. The only signal
# was `pitcher_ceiling_differentiated: 3` against 4 rostered arms -- a number
# that named no player, no reason, and no consequence.
#
# Two rules hold this block honest. Names are drawn from THIS BUILD'S POOL, not
# the salary file: per the build contract the frame's pitcher rows are feed
# probables plus explicit declarations, so a pitcher named here is a declared
# starter and the miss can change selection. And a factor whose INPUT IS ABSENT
# reports as one fact with a count, never as a list -- "the file is missing" is
# one fact about the build, not N facts about N players, and listing the pool
# under it buries the case where the factor ran and skipped somebody.
NEUTRAL_TOLERANCE = 1e-9

NEUTRAL_DEFAULT_NOTE = (
    "Players in THIS BUILD'S POOL whose factor took its neutral default rather "
    "than a value the factor computed for them. A neutral default is "
    "indistinguishable in the output from a factor that ran and found nothing "
    "to move, so the players are named rather than counted. Where the factor's "
    "input file was absent entirely the block reports `applied: false` with a "
    "count and no list, because that is one fact about the build rather than "
    "one fact per player. Deterministic record of what the engine did; never a "
    "probability, ROI, or win-rate claim. F1, F4 and F5 are deliberately absent "
    "here: they are per-GAME and per-TEAM factors that already name the teams "
    "they could not price, and expanding those to one line per hitter restates "
    "a single fact N times."
)


def _pitcher_mask(frame) -> "pd.Series":
    """True for rows whose DK position tokens include P, matching the value guard."""
    return frame["Position"].astype(str).str.split("/").apply(
        lambda toks: "P" in [t.strip() for t in toks])


def _neutral_default_block(frame, mask, at_neutral_ids, reason_by_id,
                           factor: str, neutral: float, applied: bool,
                           unavailable_reason: str | None) -> "Dict[str, Any]":
    """One factor's neutral-default record over the pool rows ``mask`` selects."""
    in_pool = int(mask.sum())
    if not applied:
        return {
            "factor": factor,
            "neutral": neutral,
            "applied": False,
            "in_pool": in_pool,
            "at_neutral": in_pool,
            "unavailable_reason": unavailable_reason,
            "players": [],
        }
    players: list[Dict[str, Any]] = []
    for idx in frame.index[mask]:
        pid = str(frame.at[idx, "Player_ID"])
        if pid not in at_neutral_ids:
            continue
        players.append({
            "player_id": pid,
            "name": str(frame.at[idx, "Name"]),
            "team": str(frame.at[idx, "Team"]) if "Team" in frame.columns else "",
            "position": str(frame.at[idx, "Position"]),
            "reason": reason_by_id.get(pid, "unknown"),
        })
    players.sort(key=lambda p: (p["reason"], p["name"], p["player_id"]))
    return {
        "factor": factor,
        "neutral": neutral,
        "applied": True,
        "in_pool": in_pool,
        "at_neutral": len(players),
        "unavailable_reason": None,
        "players": players,
    }


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

    Two records are assembled last, after every factor block has run (R127).
    ``enrichment["neutral_default"]`` NAMES the pool players whose factor took
    its neutral default instead of a value computed for them, per factor and
    with a reason each, because a neutral default is indistinguishable in the
    output from a factor that ran and found nothing to move. The names come
    from the FRAME, not the salary file: the frame's pitcher rows are feed
    probables plus explicit declarations, so a pitcher listed there is a
    declared starter whose neutral ceiling can change selection, and that case
    also raises a warning. A factor whose input file was absent entirely
    reports ``applied: false`` with a count and no list -- that is one fact
    about the build rather than one fact per player.
    ``enrichment["by_side"]`` counts, per side and per row, what any factor
    actually moved off neutral. One boolean over both sides reported
    enrichment on a slate where every pitcher sat at F1 = F4 = F5 = 1.0 and the
    ceiling multiplier was the only thing separating arms.
    """
    from mlb_engine.intake.slate_intake_manager import parse_dk_salary_csv
    from mlb_engine.projections.projection_builder import (
        build_projections, apply_xwoba_correction, batting_order_factor,
        XISO_CEILING_NEUTRAL,
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

    # R127. Per-factor bookkeeping for the neutral-default report assembled at
    # the end. Declared here so the report can be built whether or not each
    # factor's input file was supplied -- an absent input is a state to report,
    # not a reason for the key to go missing.
    xwoba_non_neutral_ids: set[str] = set()
    xwoba_neutral_reasons: Dict[str, str] = {}
    hitter_ceiling_reasons: Dict[str, str] = {}
    hitter_ceiling_neutral_ids: set[str] = set()
    pitcher_ceiling_reasons: Dict[str, str] = {}
    pitcher_ceiling_neutral_ids: set[str] = set()

    assembled: list[Dict[str, Any]] = []
    # Parallel to ``assembled``: True where Base was derived from
    # AvgPointsPerGame, False where the caller supplied Base explicitly.
    base_sources: list[bool] = []
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
        # Base source, recorded because the xwOBA correction downstream must not
        # overwrite an operator-supplied Base (R57). A blank cell in a
        # projections_override CSV arrives as NaN, not "", so NaN counts as
        # absent here: treating it as supplied both skips the APPG fallback that
        # exists for exactly that row and would leave a NaN Base for
        # validate_projection_factors to reject.
        base = r.get("Base")
        if _is_blank(base):
            base = None
        base_from_appg = False
        if base is None and not _is_blank(r.get("AvgPointsPerGame")):
            base = r["AvgPointsPerGame"]
            base_from_appg = True
        if base is None:
            raise ValueError(f"row for Player_ID {pid} missing Base/AvgPointsPerGame")
        base_sources.append(base_from_appg)
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
            # R291, 2026-09-02. The operator exclusion, CARRIED into the frame
            # the optimizer actually solves. R289 made `_pool_row` read the
            # salary file's Excluded column and made the pool report count it,
            # and this dict -- a fixed key set built fresh per row -- then
            # dropped the column on the way out. Every Classic build passes
            # through here (`run_slate`; both `build_slate.py` routes), so a
            # frame with an all-False column is what the bank, the digest, the
            # checkpoint and the certified file all saw, while the pool report
            # and its warning told the operator the pool was smaller.
            #
            # Measured at b4ad0f7 on the R289 fixture (Excluded=TRUE on T3/T4):
            # pool rows True 20 / pool_report.applied 20 / frame True 0 / T3+T4
            # rows still in the frame 20, and the checkpoint's
            # `exclusions.excluded_column.excluded_true` read 0 in the same
            # brief as the report's 20.
            #
            # No token rule is re-derived here. `_pool_row` already applied
            # `optimizer_v3.read_excluded_cell`, which is the one reading, and
            # `optimizer_v3._drop_excluded_rows` is still the one site that
            # removes a row from the pool.
            "Excluded": bool(r.get("Excluded", False)),
            "Excluded_Source": r.get("Excluded_Source") or "absent_or_blank",
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
            # The correction restates Base from APPG, so it may only touch rows
            # whose Base CAME from APPG. A row where the operator supplied Base
            # keeps it, and a row with no APPG keeps it too rather than taking a
            # NaN (R57). The mask is the pre-correction source, captured above;
            # after this call Base carries no record of where it came from.
            frame, _xwoba_audit = apply_xwoba_correction(
                frame, corrections, base_in="AvgPointsPerGame", base_out="Base",
                apply_mask=base_sources)
            xwoba_summary["applied"] = True
            applied_rows = _xwoba_audit[_xwoba_audit["applied"]]
            non_neutral = applied_rows[abs(applied_rows["xwoba_correction"] - 1.0) > 1e-9]
            xwoba_summary["non_neutral_applied"] = int(len(non_neutral))
            xwoba_non_neutral_ids = {
                str(p).strip() for p in non_neutral["Player_ID"].astype(str)}
            # R127. Three distinct ways a row keeps an uncorrected Base, and they
            # are not the same finding: an operator-supplied Base was DELIBERATELY
            # left alone (R57), where an absent Savant row is a coverage hole.
            for _rec in _xwoba_audit.to_dict("records"):
                _pid = str(_rec.get("Player_ID") or "").strip()
                if _pid in xwoba_non_neutral_ids:
                    continue
                if not bool(_rec.get("matched")):
                    xwoba_neutral_reasons[_pid] = "absent_from_expected_stats_csv"
                elif not bool(_rec.get("applied")):
                    xwoba_neutral_reasons[_pid] = "operator_supplied_base_not_corrected"
                else:
                    xwoba_neutral_reasons[_pid] = "matched_but_sample_too_thin_to_move"
            xwoba_summary["rows_corrected"] = int(_xwoba_audit["applied"].sum())
            xwoba_summary["rows_skipped_operator_base"] = int(
                len(_xwoba_audit) - int(_xwoba_audit["applied"].sum()))
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
            # R127. Two ways a pool hitter ends at the uniform neutral: no row in
            # the Savant export at all, or a row whose sample was too thin to
            # move off it. They are different data conditions and different
            # remedies, so they are different reasons.
            _xiso_neutral = float(XISO_CEILING_NEUTRAL)
            for idx in frame.index:
                pid = str(frame.at[idx, "Player_ID"])
                mult = ceiling_mults.get(pid)
                if mult is None:
                    hitter_ceiling_neutral_ids.add(pid)
                    hitter_ceiling_reasons[pid] = "absent_from_expected_stats_batting"
                elif abs(float(mult) - _xiso_neutral) < NEUTRAL_TOLERANCE:
                    hitter_ceiling_neutral_ids.add(pid)
                    hitter_ceiling_reasons[pid] = "matched_but_sample_too_thin_to_move"
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
        # R127. `unmatched_rows` is computed over the whole salary file, so it
        # cannot be the list the operator reads: most of those arms are not in
        # this build's pool. The reasons are keyed by id here and resolved
        # against the frame at the end, which is what makes the emitted list the
        # DECLARED starters and nobody else.
        _unmatched_ids = {str(r.get("id")) for r in (pitcher_report.get("unmatched_rows") or [])}
        _k_neutral = float(XISO_CEILING_NEUTRAL)
        for idx in frame.index:
            pid = str(frame.at[idx, "Player_ID"])
            if pid in pitcher_mults:
                mult = float(pitcher_mults[pid])
                frame.at[idx, "Ceiling_Multiplier"] = mult
                frame.at[idx, "Notes"] = (
                    str(frame.at[idx, "Notes"]) + f"; k_rate_ceiling: {mult:.2f}").lstrip("; ")
                applied_pitchers += 1
                if abs(mult - _k_neutral) < NEUTRAL_TOLERANCE:
                    pitcher_ceiling_neutral_ids.add(pid)
                    pitcher_ceiling_reasons[pid] = (
                        "matched_but_sub_floor_sample_or_non_starter")
            else:
                pitcher_ceiling_neutral_ids.add(pid)
                pitcher_ceiling_reasons[pid] = (
                    # R278. Named for the CONDITION, not the vendor: the K-rate
                    # source moved from a FanGraphs export to MLB StatsAPI and
                    # this reason string outlived the provider it named once
                    # already.
                    "absent_from_season_pitching" if pid in _unmatched_ids
                    else "not_in_salary_file_pitcher_crosswalk")
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

    # --- Neutral-default report and the per-side signal split (R127) ---------
    # Assembled last, so it sees every factor block's outcome. Everything below
    # is measured off the frame the solver is about to receive, never off the
    # size of an input map: a stale-id map is requested-but-unapplied, and the
    # brief used to read that as enrichment.
    pitchers = _pitcher_mask(frame)
    hitters = ~pitchers
    neutral_default = {
        "pitcher_ceiling": _neutral_default_block(
            frame, pitchers, pitcher_ceiling_neutral_ids, pitcher_ceiling_reasons,
            factor="Ceiling_Multiplier (K-rate)", neutral=float(XISO_CEILING_NEUTRAL),
            applied=bool(fangraphs_pitching_csv),
            unavailable_reason="no_fangraphs_pitching_csv_supplied"),
        "hitter_ceiling": _neutral_default_block(
            frame, hitters, hitter_ceiling_neutral_ids, hitter_ceiling_reasons,
            factor="Ceiling_Multiplier (xISO)", neutral=float(XISO_CEILING_NEUTRAL),
            applied=bool(savant_batting_csv),
            unavailable_reason="no_savant_batting_csv_supplied"),
        "xwoba_base": _neutral_default_block(
            frame, pd.Series(True, index=frame.index),
            set(xwoba_neutral_reasons), xwoba_neutral_reasons,
            factor="Base xwOBA correction", neutral=1.0,
            applied=bool(savant_batting_csv or savant_pitching_csv),
            unavailable_reason="no_savant_expected_stats_csv_supplied"),
        "note": NEUTRAL_DEFAULT_NOTE,
    }
    enrichment["neutral_default"] = neutral_default

    # The pitcher warning is the one that changes SELECTION. Every pitcher row in
    # the frame is a feed probable or an explicit declaration (build contract
    # step 1), so a name here is a declared starter the operator can act on --
    # which is exactly the condition the entry names for raising this.
    _pc = neutral_default["pitcher_ceiling"]
    _nd_warnings: list[str] = []
    if _pc["applied"] and _pc["players"]:
        _named = ", ".join(
            f"{p['name']} [{p['reason']}]" for p in _pc["players"][:8])
        _more = "" if len(_pc["players"]) <= 8 else f", +{len(_pc['players']) - 8} more"
        _nd_warnings.append(
            f"pitcher_ceiling: {_pc['at_neutral']} of {_pc['in_pool']} declared "
            f"starter(s) kept the neutral {_pc['neutral']:.2f} ceiling multiplier "
            f"({_named}{_more}). An unmeasured arm therefore ranks level with a "
            "measured average one, which can change selection. See "
            "enrichment['neutral_default']."
        )
    elif not _pc["applied"] and _pc["in_pool"]:
        _nd_warnings.append(
            f"pitcher_ceiling: no FanGraphs pitching CSV supplied, so all "
            f"{_pc['in_pool']} declared starter(s) carry the uniform neutral "
            f"{_pc['neutral']:.2f} ceiling and ceiling-scored builds cannot "
            "separate arms."
        )
    # Carried in two places on purpose: `enrichment["warnings"]` is what the
    # brief merges, and this list is what a caller echoes to stderr without
    # string-matching the merged pile to find its own warnings back.
    neutral_default["warnings"] = list(_nd_warnings)
    enrichment["warnings"].extend(_nd_warnings)

    # (b) One boolean covering two sides answered for the side with signal and
    # spoke for the side without. The split is measured per side off the frame.
    def _side_moved(mask) -> Dict[str, Any]:
        idx = {str(frame.at[i, "Player_ID"]) for i in frame.index[mask]}
        mult = pd.to_numeric(frame["Ceiling_Multiplier"], errors="coerce") \
            if "Ceiling_Multiplier" in frame.columns else None
        ceiling_moved = 0
        if mult is not None:
            moved = mask & mult.notna() & (
                (mult - float(XISO_CEILING_NEUTRAL)).abs() > NEUTRAL_TOLERANCE)
            ceiling_moved = int(moved.sum())
        factors_moved = 0
        for fcol in ("F1", "F3", "F4", "F5"):
            if fcol not in frame.columns:
                continue
            vals = pd.to_numeric(frame[fcol], errors="coerce")
            factors_moved += int((mask & vals.notna()
                                  & ((vals - 1.0).abs() > NEUTRAL_TOLERANCE)).sum())
        base_moved = len(idx & xwoba_non_neutral_ids)
        return {
            "rows": int(mask.sum()),
            "ceiling_multiplier_moved": ceiling_moved,
            "factor_cells_moved": factors_moved,
            "base_corrected": base_moved,
            "signal_applied": bool(ceiling_moved or factors_moved or base_moved),
        }

    enrichment["by_side"] = {
        "hitters": _side_moved(hitters),
        "pitchers": _side_moved(pitchers),
        "note": "Counted per row off the assembled frame, not off the size of the "
                "input maps. `signal_applied` per side is true only where some "
                "factor moved at least one row of that side off its neutral. One "
                "boolean over both sides reported enrichment on a slate where "
                "every pitcher sat at F1=F4=F5=1.0 (R127).",
    }

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


def apply_leverage_ownership(projections, leverage):
    """(frame, report). R246's ownership attach, as a function rather than as an
    `if` inside `run_slate`.

    It is separate because a test has to be able to EXECUTE it. Written inline,
    a mutation that disabled the branch survived the whole suite: the only test
    covering it read the source for the call and its position, and a disabled
    `if` keeps both. That is the same shape as R249's M1 one commit earlier, and
    the same remedy -- the decision moves into a function the tests call.

    The call SITE stays source-enforced (it must precede
    `validate_projection_schema`, because everything after that reads the
    frame), because position is a property of the layout and not of any
    function's return value.
    """
    if not (leverage or {}).get("own_pct_by_player_id"):
        return projections, {"applied": False, "reason": "no leverage supplied"}
    from mlb_engine.field.ownership_prior import attach_predicted_ownership
    return attach_predicted_ownership(
        projections, leverage["own_pct_by_player_id"],
        source=(leverage or {}).get("source"), overwrite=True,
    )


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
    # R333 fix (3). The F5 material-weather game cap, game-id keyed. Optional
    # because the factor is computed in `build_slate`, outside this module: the
    # caller that HAS the F5 report hands it in rather than this module
    # recomputing weather. Absent means no weather cap, which is today's
    # behaviour and every existing caller's.
    weather_game_caps: Optional[Mapping[str, float]] = None,
    leverage: Optional[Mapping[str, Any]] = None,
    input_confidence_facts: Optional[Mapping[str, Any]] = None,
    input_confidence_relax: Optional[str] = None,
    sleeve_implied_total_by_team: Optional[Mapping[str, float]] = None,
    # R388(e). The label the manifest records for this build's delivery, when
    # the CALLER knows something the gates cannot: build_slate's deadline
    # governor opened controls to get here, so the file is review-grade however
    # the gates read. It can only lower the label; see the guard below.
    certification_label: Optional[str] = None,
    # R388(b). Control authority. `never_relax_controls` is the operator's
    # `--never-relax`: a feasibility floor does not raise those controls, and
    # the result says each one is `operator_never_relax`. `control_moves` is
    # the deadline governor's rung record (`DeadlineGovernor.take_rung`'s
    # `moves`) on a governed re-solve: the opened values still arrive through
    # `portfolio_controls_override`, and this is how the record tells them
    # from the operator's own. Both default to nothing, which is every
    # existing caller's build exactly.
    never_relax_controls: Iterable[str] = (),
    control_moves: Optional[Sequence[Mapping[str, Any]]] = None,
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
    # R388(e). Refused before any work: a caller-supplied label that is not a
    # review-grade one would let a caller write `certified` (or anything
    # preflight might read as it) over gates that said otherwise.
    if certification_label is not None and not str(
            certification_label).startswith("review_grade"):
        raise ValueError(
            f"certification_label={certification_label!r}: only a review_grade* "
            f"label may be passed; certification comes from the gates")
    # R388(b). Refused before any work too: a misspelled never-relax holds
    # nothing and says nothing. The same resolver build_slate's flag uses, so
    # the two doors accept the same names; F-3 is in the set on every build.
    from mlb_engine.pipeline import deadline_governor as _dg  # noqa: PLC0415
    never_relax = _dg.resolve_never_relax(never_relax_controls)

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

    # R246. The leverage constraints read `Projected_Ownership_Pct` off this
    # frame, and `run_slate` REASSEMBLES the frame rather than taking the
    # caller's, so attaching the column upstream would reach the sliced bank and
    # not this one. Applied here, once, before anything reads the frame; the
    # three solver keys travel separately to the bank build below.
    projections, leverage_report = apply_leverage_ownership(projections, leverage)

    schema = validate_projection_schema(projections)
    preflight = runtime_preflight()

    entry_requirements = [
        {
            "entry_id": str(r.entry_id),
            "contest_id": str(r.contest_id),
            "contest_name": r.contest_name,
            "contest_shape": posture_by_contest.get(str(r.contest_id), {}).get("contest_shape", "large_field_gpp"),
            # R406. The allocator reads each entry's sleeve weights off its own
            # posture and shape (the WTA tilt keys on `wta_satellite`).
            "posture": posture_by_contest.get(str(r.contest_id), {}).get("posture"),
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
    # R37(2)(a)+(b), Ben's dated decision of 2026-08-28. Resolved once and passed
    # to BOTH merges, so `merged_default` and `controls` are the same portfolio's
    # defaults and the floors-applied diff below compares like with like. Passing
    # the bands to one and not the other would have reported every band floor as
    # a feasibility floor.
    shape_bands = resolve_shape_bands(
        posture_by_contest,
        game_count=slate_game_count(projections),
        archetypes_path=archetypes_path,
    )
    checkpoint["shape_bands"] = shape_bands
    # R333 / R343. Derived once from the frame and handed to BOTH merges, the
    # same rule `shape_bands` follows two lines up: passing the maps to one and
    # not the other would report every wired control as an override.
    roster_id_maps = derive_roster_id_maps(projections)
    merged_default = _merged_controls_for_build(
        posture_by_contest, None, shape_bands=shape_bands,
        roster_id_maps=roster_id_maps, weather_game_caps=weather_game_caps)
    floors = feasibility_floors_from(feasibility_inputs)
    provenance: Dict[str, Any] = {}
    # R388(b). A rung-opened key arrives in the override; its provenance is the
    # one it had before the move (or the governor's engine table where nothing
    # was set), never the operator's.
    moved_provenance = {
        str(m.get("control")): (m.get("provenance") or _PROV_ENGINE_DEFAULT)
        for m in (control_moves or ()) if m.get("control")}
    controls = _merged_controls_for_build(
        posture_by_contest, portfolio_controls_override, feasibility_floors=floors,
        shape_bands=shape_bands, roster_id_maps=roster_id_maps,
        weather_game_caps=weather_game_caps,
        never_relax=never_relax, provenance_out=provenance,
        override_provenance=moved_provenance,
    )
    # Re-derived from the merged controls rather than carried out of the merge:
    # same pure function, same three inputs, so the record and the enforced dict
    # cannot disagree (CC-1's pattern).
    game_exposure_request = resolve_game_exposure_request(
        controls, list(roster_id_maps.get("games") or []),
        weather_game_caps=weather_game_caps)

    override_keys = set(dict(portfolio_controls_override or {}).keys())
    # R407. The confidence tier, where the controls are resolved and before the
    # floor record below reads them: the tightening is floored by the same
    # `floors` the merge just applied, loses to an explicit override, and is
    # recorded with its before and after on the checkpoint and the result.
    input_confidence = resolve_input_confidence(input_confidence_facts)
    controls, input_confidence = apply_input_confidence(
        controls, input_confidence, floors=floors, override_keys=override_keys,
        relax=input_confidence_relax)
    control_provenance = _control_provenance_block(
        controls, provenance, input_confidence, never_relax, control_moves)
    moved_keys = set(control_provenance["moved"])
    controls_feasibility: Dict[str, Any] = {"floors_applied": {}, "notes": []}
    for key, floor_val in floors.items():
        base = merged_default.get(key)
        final = controls.get(key)
        if base is None or final is None:
            continue
        if key in moved_keys:
            # R388(b). The governor's value arrives as an override and used to
            # be reported as one; the record says whose it is.
            controls_feasibility["notes"].append(
                f"{key}: deadline governor opened to {final} (feasibility floor "
                f"was {floor_val}, merged default {base})"
            )
        elif key in override_keys:
            controls_feasibility["notes"].append(
                f"{key}: explicit override {final} used (feasibility floor was {floor_val}, "
                f"merged default {base})"
            )
        elif key in never_relax and float(floor_val) > float(base):
            controls_feasibility["notes"].append(
                f"{key}: never-relax held {final} (feasibility floor was "
                f"{floor_val}, merged default {base})"
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
    # R69(c): both findings still reach the plan-mode report, and reach it with
    # the same text as before. What changed is that only one of them is called a
    # blocker, and that one now blocks.
    exclusion_notices = list(exclusion_block.get("blockers") or []) + list(
        exclusion_block.get("warnings") or [])
    if exclusion_notices:
        existing = list(checkpoint.get("warnings") or [])
        checkpoint["warnings"] = existing + [
            f"exclusions: {b}" for b in exclusion_notices
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
        order_by_team=batting_orders_by_team(projections),
        # R176(a): the salary gate reads the salary file now. Computed here rather
        # than inside the gate function so the projections_override path -- which
        # never otherwise opens it -- checks the same bytes as every other path.
        salary_schema=validate_salary_export(salary_csv),
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
    #
    # R133(4). Two facts wear one name here and they are not the same claim.
    # ASSUMING a gate nothing checked is a statement about missing evidence.
    # OVERRIDING a gate the evidence decided False is a statement that the
    # operator has read that evidence and disagrees. The loop below used to
    # promote only the first and DROP the second on the floor -- while still
    # listing it in `assumed_gates`, so the artifact recorded an assumption that
    # changed nothing. An operator doing what CLAUDE.md's autonomy section
    # instructs, overriding a pool blocker and asserting `lineup_gate_passed` on
    # the same evidence, got a blocked build for it.
    #
    # `lineup_gate_passed` is the only gate an override reaches, because it is
    # the only one the contract authorizes asserting on operator evidence, and
    # the override is recorded SEPARATELY with the evidence it contradicts. A
    # reader of the artifact can then tell "nobody checked" from "the check said
    # no and was overruled", which is the whole point of the labels rule.
    gates, assumed, overridden_gates, gates_assumption_refused = resolve_gate_assertions(
        gate_defaults, supplied, assume_gates, derived_gates, gate_evidence)
    caller_asserted = caller_asserted_gates(supplied, gates)

    base_payload = {
        "checkpoint_plan": checkpoint,
        "projection_schema": schema,
        "optimizer_preflight": preflight,
        "entry_requirements": entry_requirements,
        "posture_by_contest": posture_by_contest,
        "merged_controls": controls_for_report(controls),
        # R333 / R343. The washout-axis controls, on every Classic build
        # including the ones that set neither, so the ABSENCE of a game cap is
        # visible rather than merely true -- R333's fix asks for exactly this.
        "game_exposure_request": game_exposure_request,
        "team_exposure": {
            "max_team_exposure_pct": controls.get("max_team_exposure_pct"),
            "min_hitters_per_entry": controls.get(
                "team_exposure_min_hitters", TEAM_EXPOSURE_MIN_HITTERS),
            "counts": "hitter_slots",
            "map_wired": bool(controls.get("player_team_by_id")),
            "note": MAX_TEAM_EXPOSURE_NOTE,
        },
        # R407. The tier, the facts that set it, and each control's before and
        # after, on the checkpoint and on the approved result alike.
        "input_confidence": input_confidence,
        # R388(b). Every resolved control's value and provenance, the
        # never-relax set, and what a deadline rung moved.
        "control_provenance": control_provenance,
        # R405. The cap as requested, before the bank defines the cluster; the
        # realized block is the allocator's `consensus_cluster`.
        "consensus_cluster_request": {
            "max_consensus_cluster_share_pct": controls.get(
                "max_consensus_cluster_share_pct"),
            "min_members_k": controls.get(
                "consensus_cluster_min_members", CONSENSUS_CLUSTER_MIN_MEMBERS),
            "note": MAX_CONSENSUS_CLUSTER_NOTE,
        },
        "controls_feasibility": controls_feasibility,
        "feasibility": checkpoint["feasibility"],
        "exclusions": exclusion_block,
        "slate_clock": clock,
        "waterfall": checkpoint.get("waterfall"),
        "caller_asserted_gates": caller_asserted,
        "workflow_gate_evidence": gate_evidence,
        "assumed_gates": assumed,
        # R133(4). Kept apart from `assumed_gates` on purpose: one says nothing
        # checked, the other says the check said no.
        "overridden_gates": overridden_gates,
        "gates_assumption_refused": gates_assumption_refused,
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

    # R69(c). An exclusion that matches nobody is the same shape of failure as
    # wrong-contest identity, and it gets the same treatment. The docstring at
    # ``_exclusion_block`` has said since F15 that this is "a blocker at
    # approve=False", but the code only ever appended to warnings, so approve=True
    # sailed past a typo'd ID and built a portfolio around a player the operator
    # had asked to remove. It is decidable from disk in under a second, it is
    # invisible in the certified output, and the remedy is correcting one
    # argument on the same command -- which is the whole test the identity gate
    # above is justified by. No override, for the same reason: an override would
    # cost more than the fix.
    #
    # Scoped to ids the operator TYPED. The Excluded column's unrecognized cells
    # stay a warning: keeping those players is the documented reading of that
    # column, and its remedy is a file edit, not a flag.
    unmatched_exclusions = list(exclusion_block.get("unmatched_player_ids") or [])
    if approve and unmatched_exclusions:
        return {"passed": False, "status": "blocked", "approved": True,
                "errors": [
                    f"{len(unmatched_exclusions)} excluded player id(s) match no "
                    f"row in this pool of {len(projections)}: "
                    f"{unmatched_exclusions[:10]}. An exclusion that matches "
                    f"nobody removes nobody, so this build would roster a player "
                    f"you asked to drop. Correct the id(s) or drop the exclusion"
                ], **base_payload}

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
        # R246. The auto-bank path's half of the leverage passthrough. These
        # cross into `build_candidate_lineup_bank` -> `build_multi_lineup` AND
        # into the forced-augmentation pass, because the same three keys are on
        # `build_diverse_candidate_bank`'s `passthrough_keys` whitelist. The
        # OTHER production bank -- `build_slate.py`'s sliced `extend_bank`,
        # which arrives here as `candidates_override` and never reaches this
        # branch -- carries them through `bank_cache._leverage_kwargs`.
        from mlb_engine.optimize.bank_cache import _leverage_kwargs
        bank_stack_request = resolve_bank_stack_request(controls)
        # R405(c). The direct door's half of the cluster-limited jobs: the same
        # derivation the sliced door and the plan leg call, over the same
        # merged controls, so the cap never binds against a bank that was never
        # asked for what it needs (R246's lesson about the path the clock picks).
        consensus_request = resolve_consensus_limited_request(
            controls, len(entry_requirements))
        bank = build_diverse_candidate_bank(
            bank_projections, requested_n=n, mode=mode, target="ceiling",
            contest_shapes=sorted(shape_counts) or None,
            max_sp_pair_repetition=controls.get("max_sp_pair_repetition"),
            coverage_target=wf_coverage_target,
            time_budget_s=bank_time_budget_s,
            solver_time_limit_s=solver_time_limit_s,
            excludes=bank_excludes or None,
            # R293. R288's sixth member. `controls` has carried this key since
            # R288 wired it through portfolio_controls, and this call -- the
            # ONLY bank the direct strategy builds -- never read it, so a build
            # at `--max-opposing-hitters-per-sp 3` solved its entire bank at 0
            # whenever the clock chose direct over sliced. The sliced path was
            # wired at `build_slate.py`'s `extend_bank` call and the auto path
            # was not, which is R153's "on every rung" one rung short again.
            max_opposing_hitters_per_sp=controls.get("max_opposing_hitters_per_sp"),
            # R340. The two arguments that decide whether this bank can CONTAIN
            # the shape R37(2)(a)'s floor and (b)'s quota filter for. Neither was
            # ever passed by any caller, so both controls filtered a bank of
            # four-stacks and reported as if they were working. Derived from the
            # merged controls, which already carry R34's unanimity rule, so a
            # five is requested on exactly the contests the floor and the quota
            # target. On THIS door one value is enough for the mix: the base
            # bank supplies the fours and only the forced-augmentation pass
            # reads the floor.
            bank_stack_min_size=bank_stack_request["bank_stack_min_size"],
            bank_secondary_size=controls.get("bank_secondary_size") or 0,
            consensus_limited_jobs=consensus_request,
            **_leverage_kwargs(leverage),
        )
        candidates = _bank_records_to_candidates(bank.get("candidate_lineups") or [])
        # R406. The direct door's sleeves, through the SAME helper the sliced
        # door and the plan leg call, in throwaway caches: the direct bank is
        # in memory, so its sleeves are too. The cluster chalk-fails limits
        # against is derived from this door's own unconstrained candidates.
        sleeve_request = resolve_sleeve_bank_request(
            entry_requirements, controls, bank_projections,
            implied_total_by_team=sleeve_implied_total_by_team)
        sleeve_jobs: Dict[str, Any] = {"attempted": False,
                                       "reason": "sleeves not requested"}
        if sleeve_request["active"]:
            candidates, sleeve_jobs = _direct_door_sleeves(
                candidates, bank_projections, sleeve_request,
                requested_n=n, contest_shapes=sorted(shape_counts) or None,
                time_budget_s=(max(10.0, BANK_SLEEVE_BUDGET_SHARE * float(bank_time_budget_s))
                               if bank_time_budget_s else 60.0),
                excludes=bank_excludes or None,
                solver_time_limit_s=solver_time_limit_s,
                max_opposing_hitters_per_sp=controls.get("max_opposing_hitters_per_sp"),
                leverage=leverage)
        bank_diag = {
            "source": "build_diverse_candidate_bank", "mode": mode, "requested_n": n,
            # R406. What the sleeves were asked for and what they built.
            "classic_sleeves_request": sleeve_request,
            "classic_sleeves_jobs": sleeve_jobs,
            # R340. What this bank was ASKED for, carried to the allocator so a
            # floor or quota that finds nothing can say whether the bank was
            # asked and could not, or was never asked at all.
            "stack_request": bank_stack_request,
            # R405(c), same reason.
            "consensus_limited_request": consensus_request,
            "candidate_count": len(candidates),
            "excluded_player_ids_applied": bank_excludes,
            "solver_report": bank.get("solver_report"),
            "waterfall_coverage_target": wf_coverage_target,
            "contest_shape_profile": bank.get("contest_shape_profile"),
            "diversity_augmentation": bank.get("diversity_augmentation"),
            # R293. Carried to the boundary so `build_slate.py` can write the
            # brief's `anti_correlation.applied` from the SOLVES rather than
            # from the flag that requested them.
            "anti_correlation": bank.get("anti_correlation"),
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
        # R112: the checkpoint's own feasibility inputs, so a proven-infeasible
        # refusal from this build can name the bank as the limiter.
        feasibility_inputs=feasibility_inputs,
        # R286: and its own feasibility VERDICTS, so the refusal leads with the
        # slate-level check that failed. The checkpoint computed these ~350 lines
        # above and, until this argument existed, printed them into the brief
        # while the allocator refused without ever seeing them.
        feasibility_checks=list(feasibility_report.get("checks") or []),
        metadata={**(metadata or {}), "front_door": "run_slate",
                  "front_door_version": VERSION,
                  "workflow_gate_evidence": gate_evidence,
                  "assumed_gates": assumed,
                  "overridden_gates": overridden_gates,
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
        # R388(e). Only when a caller passed one, so an ungoverned result keeps
        # exactly its old keys.
        **({"certification_label": str(certification_label)}
           if certification_label else {}),
        "merged_controls": controls_for_report(controls),
        # R333 / R343. The washout-axis controls, on every Classic build
        # including the ones that set neither, so the ABSENCE of a game cap is
        # visible rather than merely true -- R333's fix asks for exactly this.
        "game_exposure_request": game_exposure_request,
        "team_exposure": {
            "max_team_exposure_pct": controls.get("max_team_exposure_pct"),
            "min_hitters_per_entry": controls.get(
                "team_exposure_min_hitters", TEAM_EXPOSURE_MIN_HITTERS),
            "counts": "hitter_slots",
            "map_wired": bool(controls.get("player_team_by_id")),
            "note": MAX_TEAM_EXPOSURE_NOTE,
        },
        # R407. The tier, the facts that set it, and each control's before and
        # after, on the checkpoint and on the approved result alike.
        "input_confidence": input_confidence,
        # R388(b). Every resolved control's value and provenance, the
        # never-relax set, and what a deadline rung moved.
        "control_provenance": control_provenance,
        # R405. The cap as requested, before the bank defines the cluster; the
        # realized block is the allocator's `consensus_cluster`.
        "consensus_cluster_request": {
            "max_consensus_cluster_share_pct": controls.get(
                "max_consensus_cluster_share_pct"),
            "min_members_k": controls.get(
                "consensus_cluster_min_members", CONSENSUS_CLUSTER_MIN_MEMBERS),
            "note": MAX_CONSENSUS_CLUSTER_NOTE,
        },
        "controls_feasibility": controls_feasibility,
        "feasibility": checkpoint["feasibility"],
        "exclusions": exclusion_block,
        "slate_clock": clock,
        # R246. Present on every approved build, `applied: false` when no
        # leverage was asked for, so "was the ownership prior in this build"
        # has an answer rather than an absence.
        "leverage": {
            **leverage_report,
            "constraints": {k: (leverage or {}).get(k)
                            for k in ("max_cumulative_ownership_pct",
                                      "min_low_owned_hitters",
                                      "low_owned_threshold_pct")},
        },
        "candidate_bank": bank_diag,
        "bank_player_coverage": bank_player_coverage,
        "script_routing": script_routing,
        "fill_depth_plan": fill_depth_plan,
        "projected_order": projected_order,
        "projection_enrichment": projection_enrichment,
        "caller_asserted_gates": caller_asserted,
        "workflow_gate_evidence": gate_evidence,
        "assumed_gates": assumed,
        "overridden_gates": overridden_gates,
        "gates_assumption_refused": gates_assumption_refused,
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
        except Exception as exc:  # noqa: BLE001
            # R176(d). `pass` dropped the one fact the multi-session contract says
            # every brief must state: "Every brief states the delivered file's
            # sha256, and Ben checks it at upload before entering anything." A
            # missing sha that nothing explains is indistinguishable from a brief
            # that simply did not carry the field.
            result["delivered_sha256_error"] = f"{type(exc).__name__}: {exc}"
            print(f"DELIVERED SHA NOT COMPUTED  {type(exc).__name__}: {exc}; the "
                  f"brief cannot state the sha256 Ben checks at upload",
                  file=sys.stderr)
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
        from mlb_engine.entries.upload_manifest import REPO_ROOT as artifact_root
        dest_dir = artifact_root / "outputs" / slate_date
        dest_dir.mkdir(parents=True, exist_ok=True)
        # The delivered name carries the slate tag. DK runs several draftgroups on
        # most dates and this mirror wrote one name per contest type, so the
        # second build of the day silently replaced the first one's delivered
        # file while both briefs went on citing the same path.
        tag = _slate_tag(salary_csv)
        stem = source.stem
        dest = dest_dir / (f"{stem}_{tag}{source.suffix}" if tag and not stem.endswith(tag)
                           else source.name)
        # R96(2). Was: write dest, then try to record, and on failure print
        # loudly and leave the file wearing its uploadable name. R3(a) had
        # already made that failure loud; what it could not fix is that the
        # ARTIFACT stayed silent, so anything reading the directory later --
        # ARCHIVE, awaiting_standings, the next session -- saw a normal delivery.
        # The order is now write-provisional, record, promote, so an unrecorded
        # file is named DO_NOT_UPLOAD_* and says so without being asked.
        outcome = _deliver_mirror(slate_date, dest, source, result, tag, salary_csv)
        if isinstance(result, dict):
            result["manifest_recorded"] = bool(outcome["recorded"])
            result["staged_salary"] = outcome.get("staged_salary")
        if outcome["error"]:
            print(f"MANIFEST NOT RECORDED  {outcome['error']}")
        return str(outcome["path"])
    except Exception as exc:  # noqa: BLE001 - a mirror must never fail a certified build
        # R176(d), 2026-08-30. This swallowed the reason. `delivered_path` came
        # back None, the brief carried no delivery and no explanation, and the
        # multi-session contract requires every brief to state the delivered
        # file's sha256 -- which cannot be stated about a delivery nobody can see
        # failed. The build still must not fail on a mirror, so the exception is
        # still caught; it is now NAMED on the record and said out loud once.
        if isinstance(result, dict):
            result.setdefault("manifest_recorded", False)
            result["mirror_error"] = f"{type(exc).__name__}: {exc}"
        print(f"MIRROR FAILED  {type(exc).__name__}: {exc}; the export stays in "
              f"runs/<run_id>/final/ and nothing was delivered to outputs/",
              file=sys.stderr)
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

    R172, 2026-08-30. ``value_guard`` was in this list and is not enrichment. It is
    an internal Base cap: hitter Base clipped at the slate's own 90th-percentile
    pts/$1k times 1.08, computed from the salary file and the build's own
    projections, reaching no external source at all. It is applied by default, and
    its block reads ``applied: True`` whether it clipped anything or not, so EVERY
    default assembled build wrote ``projection_tier: "enriched"`` onto a permanent,
    money-adjacent record, including a build with zero external data, which is the
    exact case this field exists to distinguish. Dropping the key is the fix rather
    than demanding richer evidence from it: no evidence the guard could produce
    would make an internal cap into enrichment.
    """
    enrichment = result.get("projection_enrichment") or {}
    for key in ("xwoba", "ceiling", "f4", "f1", "f5", "pitcher_ceiling"):
        if _applied(enrichment.get(key)):
            return "enriched"
    return "proxy"


def manifest_strategy_state(result: Mapping[str, Any]) -> Dict[str, Any]:
    """'clean' only when nothing was relaxed to make the portfolio fit.

    R3(c). A relaxed portfolio and a clean one are different artifacts and the
    difference lived in prose in the brief. It belongs on the record.

    R64(a). This read one key, ``bank_diagnostics["relaxations"]``, which is real
    on the self-built-bank path and absent on the production sliced one:
    ``run_slate`` strips ``bank_diag`` to ``candidate_count`` when
    ``candidates_override`` is supplied (the caller's record wins) and
    build_slate's own ``bank_diagnostics`` carries no ``relaxations`` key at all.
    Missing evidence therefore read as ``"clean"`` -- and CLAUDE.md's "a portfolio
    is clean when the relaxation counts are zero" is read at T-5 off exactly this
    field. A record that structurally cannot say "relaxed" destroys the evidence
    the rule depends on.

    Two changes. The union of the places relaxations are actually recorded is
    read: both diagnostics holders, the ``relaxations`` block inside each, and the
    top-level ``*relax*`` counters Showdown keeps there instead (R54's
    ``relaxed_slots`` / ``overlap_relaxed_slots``). And absence of evidence is now
    ``"unknown"``, not ``"clean"``: this function cannot certify a portfolio it has
    no report for. ``bank_warnings`` -- where the sliced path's failed cache jobs
    and slice-not-full-search notes land -- travels on the record as evidence
    without driving the verdict, because reduced search effort is not a relaxed
    control and conflating them would trade one false label for another.
    """
    counts: Dict[str, int] = {}
    relax_warnings: List[str] = []
    saw_evidence = False
    for holder_key in ("bank_diagnostics", "candidate_bank"):
        holder = result.get(holder_key)
        if not isinstance(holder, Mapping):
            continue
        block = holder.get("relaxations")
        if isinstance(block, Mapping):
            saw_evidence = True
            for key, value in block.items():
                if key in ("note", "warnings") or isinstance(value, bool):
                    continue
                if isinstance(value, int) and value:
                    counts[key] = max(counts.get(key, 0), value)
            relax_warnings.extend(str(w) for w in (block.get("warnings") or []))
        showdown = {k: v for k, v in holder.items()
                    if isinstance(v, int) and not isinstance(v, bool)
                    and "relax" in k.lower()}
        if showdown:
            saw_evidence = True
            for key, value in showdown.items():
                if value:
                    counts[key] = max(counts.get(key, 0), value)
    # R298(a). The allocator's three ladders -- max_candidate_reuse, the
    # primary-stack floor and the five-stack quota -- each count their own
    # relaxations, and this read none of them, so a Classic row read `unknown`
    # with reuse, floor and quota all relaxed. `execute_portfolio` returns the
    # three blocks on the result; a block present is evidence the ladder ran.
    for ladder in ("candidate_reuse", "primary_stack_floor", "five_stack_quota"):
        block = result.get(ladder)
        if not isinstance(block, Mapping):
            continue
        saw_evidence = True
        steps = block.get("relaxations")
        if isinstance(steps, int) and not isinstance(steps, bool) and steps:
            counts[ladder] = max(counts.get(ladder, 0), steps)
    seen: set = set()
    relax_warnings = [w for w in relax_warnings if not (w in seen or seen.add(w))]
    if counts or relax_warnings:
        state = "relaxed"
    elif saw_evidence:
        state = "clean"
    else:
        state = "unknown"
    return {
        "state": state,
        "counts": counts,
        "warnings": relax_warnings[:10],
        "evidence": "recorded" if saw_evidence else "absent",
        "bank_warnings": [str(w) for w in (result.get("bank_warnings") or [])][:10],
    }


def _deliver_mirror(slate_date: str, dest: Path, source: Path,
                    result: Mapping[str, Any], tag: str,
                    salary_csv: Any) -> Dict[str, Any]:
    """Mirror the promoted export through the R96(2) record-or-self-label door.

    One manifest record per delivery, so T-5 never has to guess which file, and
    the salary export staged beside it so the contest stays mineable (R96(4)).
    The caller says the error out loud; see mirror_to_outputs.
    """
    from mlb_engine.entries.upload_manifest import deliver

    contests = (result.get("posture_by_contest") or {})

    def _write(provisional: Path) -> None:
        provisional.write_bytes(source.read_bytes())

    def _entries_in(path: Path) -> int:
        # Counted off the delivered file, not off an upstream plan: the count
        # preflight cross-checks has to be a fact about these bytes, because
        # catching a truncated write is exactly what it is for.
        from mlb_engine.entries.dk_entries_manager import parse_dk_entry_rows
        return len(parse_dk_entry_rows(path))

    return deliver(
        date=slate_date,
        dest=dest,
        write=_write,
        salary_csv=salary_csv,
        contest_type="classic",
        slate_tag=tag,
        contest_ids=sorted(contests),
        contest_names=sorted(
            str(v.get("contest_name") or "") for v in contests.values()),
        entries=_entries_in(source),
        run_id=result.get("run_id"),
        status="candidate",
        certification=manifest_certification(result),
        projection_tier=manifest_projection_tier(result),
        strategy_state=manifest_strategy_state(result),
        # R377. The controls the build solved under, after any deadline opening
        # and R407's tier: `run_slate` sets this before it calls the mirror.
        controls=result.get("merged_controls"),
    )


def manifest_certification(result: Mapping[str, Any]) -> str:
    """The label the manifest records for a Classic delivery.

    R388(e). This was `certified` whenever `workflow_valid`, so a deadline-
    governed retry was recorded certified and preflight stamped it
    `upload_ready` while the brief said review-grade. A caller's review-grade
    label wins over a passing gate; a failing gate wins over any label.
    """
    if not result.get("workflow_valid"):
        return "not_certified"
    return str(result.get("certification_label") or "certified")
