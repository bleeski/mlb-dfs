"""The baseline-first, deterministic ingestion-to-export production workflow."""

from __future__ import annotations

import importlib.metadata
import json
import platform
import time
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from . import VERSION
from .contracts import ContestSpec, Controls, EvidenceBundle, infer_shape
from .csvio import inspect_embedded_pool, parse_entries, parse_salary
from .evidence import (
    FileProvider,
    aware,
    freshness_deadline,
    prepare,
    read_bounded,
    validate_edge_output,
)
from .optimizer import BudgetExpired, Deadline, solve_portfolio
from .portfolio import enhance
from .referee import inspect_export
from .simulation import leverage_report, portfolio_metrics, simulate
from .state import StateStore, atomic_write, digest, json_bytes

PINS = {"numpy": "2.2.6", "pandas": "2.3.3", "scipy": "1.15.3", "pydantic": "2.12.5"}


def runtime_identity() -> dict:
    versions = {name: importlib.metadata.version(name) for name in PINS}
    if versions != PINS:
        raise RuntimeError(
            "RUNTIME_MISMATCH: run tools/bootstrap_engine.py to install the verified dependencies"
        )
    source_root = Path(__file__).parent
    code = b"".join(
        p.name.encode() + p.read_bytes() for p in sorted(source_root.glob("*.py"))
    )
    roster = source_root.parent / "optimize" / "roster_contracts.py"
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "dependencies": versions,
        "engine_version": VERSION,
        "code_sha256": digest(code + roster.read_bytes()),
    }


def error_text(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return json.dumps(
            exc.errors(include_input=False, include_context=False, include_url=False)
        )
    return f"{type(exc).__name__}: {exc}"


def run(
    salary: str | Path,
    entries: str | Path,
    evidence: str | Path,
    output: str | Path,
    *,
    controls: Controls | None = None,
    authorized_entry_ids: set[str] | None = None,
    parent: str | Path | None = None,
    fixture_mode: bool = False,
    as_of: datetime | None = None,
    edge_output: str | None = None,
) -> dict:
    started = time.perf_counter()
    controls = controls or Controls()
    # Revalidate even a model made with Pydantic's unsafe model_construct/copy API.
    controls = Controls.model_validate_json(controls.model_dump_json())
    if as_of is not None and not fixture_mode:
        raise ValueError(
            "an artificial clock is only available for labeled offline fixtures"
        )
    if fixture_mode and as_of is None:
        raise ValueError("offline fixture execution requires its explicit clock")

    def clock():
        return aware(as_of) if fixture_mode else datetime.now(timezone.utc)

    now = clock()
    deadline = Deadline(controls.total_seconds)
    root = Path(output).resolve()
    source_paths = {
        "salary": Path(salary).resolve(),
        "entries": Path(entries).resolve(),
        "evidence": Path(evidence).resolve(),
    }
    if any(
        path.is_relative_to(root) and not path.is_relative_to(root / "runs")
        for path in source_paths.values()
    ):
        raise ValueError(
            "raw inputs must be outside output; an immutable prior run export is allowed"
        )
    store = StateStore(root)
    run_dir, manifest, baseline_result = None, None, None
    inputs = {}
    try:
        environment = runtime_identity()
        inputs["salary"] = read_bounded(source_paths["salary"])
        inputs["entries"] = read_bounded(source_paths["entries"])
        inputs["evidence"], artifacts = FileProvider(source_paths["evidence"]).read()
        inputs.update({"source:" + k: v for k, v in artifacts.items()})
        inputs["controls"] = json_bytes(controls.model_dump(mode="json"))
        if parent is not None:
            inputs["parent"] = read_bounded(Path(parent))
        if edge_output is not None:
            inputs["edge_output"] = edge_output.encode()
        run_dir, manifest = store.create_run(
            inputs,
            {
                "environment": environment,
                "as_of": now.isoformat(),
                "fixture": fixture_mode,
                "source_paths": {k: str(v) for k, v in source_paths.items()},
            },
        )
        # Only captured bytes are consumed below this point.
        mode, players = parse_salary(inputs["salary"])
        template = parse_entries(inputs["entries"])
        if template.mode != mode:
            raise ValueError("salary and entry contest formats disagree")
        manifest["metadata"]["embedded_pool"] = inspect_embedded_pool(template, players)
        bundle = EvidenceBundle.model_validate_json(inputs["evidence"])
        explicit_contests = {c.contest_id: c for c in bundle.contests}
        inferred = {}
        for entry in template.entries:
            shape = infer_shape(entry.name)
            if entry.contest_id not in explicit_contests and shape:
                inferred[entry.contest_id] = shape
                explicit_contests[entry.contest_id] = ContestSpec(
                    contest_id=entry.contest_id, shape=shape
                )
        bundle = bundle.model_copy(
            update={"contests": list(explicit_contests.values())}
        )
        manifest["metadata"]["title_inferred_contests"] = inferred
        prepared = prepare(bundle, players, controls, now, fixture_mode)
        if edge_output is not None:
            proposal = validate_edge_output(edge_output, bundle, players)
            manifest["metadata"]["edge_proposal"] = proposal.model_dump(mode="json")
            # It is recorded only; it cannot alter authoritative participation facts.
        known_ids = {e.entry_id for e in template.entries}
        if authorized_entry_ids is None:
            if parent is not None:
                raise ValueError("late swap requires explicit authorized Entry IDs")
            mutable = {e.entry_id for e in template.entries if not any(e.roster)}
            if any(any(e.roster) and not all(e.roster) for e in template.entries):
                raise ValueError(
                    "partial prefilled entries require explicit late-swap authorization"
                )
        else:
            mutable = set(authorized_entry_ids)
            if not mutable or mutable - known_ids:
                raise ValueError(
                    "late-swap authorization is empty or contains unknown Entry IDs"
                )
            if inputs.get("parent") != inputs["entries"]:
                raise ValueError(
                    "late swap must start from the exact verified parent export"
                )
        scope = digest(
            json_bytes(
                {
                    "platform": "DraftKings",
                    "sport": "MLB",
                    "mode": mode,
                    "salary_ids": sorted(players),
                    "game_ids": sorted({p.game_id for p in players.values()}),
                    "entries": sorted(
                        (e.entry_id, e.contest_id, e.fee_cents)
                        for e in template.entries
                    ),
                }
            )
        )
        previous = store.current(scope)
        if authorized_entry_ids is not None:
            if previous is None:
                raise ValueError(
                    "no verified parent in this output store; build or import the parent first"
                )
            current_safe = store.recover_safe(scope)
            if current_safe.read_bytes() != inputs["parent"]:
                raise ValueError("parent is not the current committed export")
        manifest["metadata"].update(
            scope=scope,
            mode=mode,
            mutable_entry_ids=sorted(mutable),
            parent_run_id=previous,
        )
        specs = {c.contest_id: c for c in bundle.contests}
        if set(specs) - {e.contest_id for e in template.entries}:
            raise ValueError("contest metadata is outside the entries template")
        # Validate supplied opponent lineups independently, as part of the model
        # input. They need the platform geometry, not our portfolio preferences.
        if any(c.field_rosters is not None for c in bundle.contests):
            _validate_fields(bundle, players, mode, template)
        manifest["metadata"]["market_checks"] = list(prepared.market_checks)
        stage = time.perf_counter()
        assignments, solver = solve_portfolio(
            template.entries, mode, players, prepared, controls, now, mutable, deadline
        )
        solve_seconds = time.perf_counter() - stage
        if not assignments:
            manifest["solver"] = solver
            raise RuntimeError(
                "NO_VERIFIED_BASELINE: inspect solver and diagnostic relaxation in manifest.json"
            )

        def validate(values):
            when = clock()
            current_prepared = prepare(bundle, players, controls, when, fixture_mode)
            raw = template.render(values, mutable)
            result = inspect_export(
                template, raw, players, current_prepared, controls, when, mutable
            )
            result["valid_as_of"] = when.isoformat()
            boundaries = [freshness_deadline(bundle, controls)]
            boundaries.extend(p.start for p in players.values() if p.start > when)
            result["recheck_at"] = min(boundaries).isoformat()
            return result

        baseline_result = _finish(
            store,
            run_dir,
            manifest,
            scope,
            previous,
            template,
            assignments,
            validate(assignments),
            solver,
            prepared,
            inputs,
            fixture_mode,
            {
                "baseline_solve_seconds": solve_seconds,
                "elapsed_seconds": time.perf_counter() - started,
            },
        )
        if not controls.enhance or controls.qa_iterations == 0:
            return _current_readiness(baseline_result, clock())
        try:
            deadline.remaining(5)
            scenarios = simulate(players, prepared, controls)
            holdout = simulate(
                players, prepared, controls, seed=(controls.seed + 1) % 2**32
            )
            baseline_metrics = portfolio_metrics(
                assignments, template.entries, mode, players, prepared, scenarios
            )
            final, review = enhance(
                assignments,
                template.entries,
                mode,
                players,
                prepared,
                controls,
                now,
                mutable,
                scenarios,
                holdout,
                deadline,
                validate,
            )
            review["baseline_metrics"] = baseline_metrics
            review["leverage"] = leverage_report(scenarios, players, prepared)
            review["simulation_label"] = scenarios.label
            if final != assignments:
                next_dir, next_manifest = store.create_run(
                    inputs,
                    {
                        **manifest["metadata"],
                        "parent_run_id": run_dir.name,
                        "phase": "enhancement",
                        "review": review,
                    },
                )
                final_result = _finish(
                    store,
                    next_dir,
                    next_manifest,
                    scope,
                    run_dir.name,
                    template,
                    final,
                    validate(final),
                    {
                        "incumbent_valid": True,
                        "status": "PARETO_RESOLVED",
                        "search_scope": "generated_bank",
                        "relaxations_applied": [],
                    },
                    prepared,
                    inputs,
                    fixture_mode,
                    {"elapsed_seconds": time.perf_counter() - started},
                )
                final_result["review"] = review
                final_result["baseline_export"] = baseline_result["export"]
                baseline_result = final_result
            else:
                baseline_result["review"] = review
            # Review is a separate artifact; the promoted baseline remains immutable.
            atomic_write(
                root / "reviews" / (baseline_result["run_id"] + ".json"),
                json_bytes(review),
            )
        except (BudgetExpired, ValueError, RuntimeError) as exc:
            baseline_result["enhancement_status"] = error_text(exc)
            baseline_result["baseline_preserved"] = True
        baseline_result["elapsed_seconds"] = time.perf_counter() - started
        return _current_readiness(baseline_result, clock())
    except Exception as exc:
        if baseline_result is not None:
            baseline_result.update(
                enhancement_status=error_text(exc), baseline_preserved=True
            )
            return _current_readiness(baseline_result, clock())
        failure = {
            "schema_version": 1,
            "status": "blocked",
            "FILE_VALID": False,
            "workflow_valid": False,
            "selection_certified": False,
            "allocation_certified": False,
            "EVIDENCE_STATE": "UNVERIFIED",
            "MODEL_STATUS": "PRIOR_ONLY",
            "RELEASE_DECISION": "DO_NOT_UPLOAD",
            "errors": [error_text(exc)],
            "elapsed_seconds": time.perf_counter() - started,
        }
        if run_dir is not None:
            manifest.update(status="blocked", failure=failure)
            store.save_manifest(run_dir, manifest)
            failure["manifest"] = str(run_dir / "manifest.json")
            failure["solver"] = manifest.get("solver")
        # Failure records are unique; concurrent slates cannot truncate one another.
        import uuid

        atomic_write(
            root / "failures" / (uuid.uuid4().hex + ".json"), json_bytes(failure)
        )
        return failure


def _current_readiness(result: dict, now: datetime) -> dict:
    if now >= datetime.fromisoformat(result["recheck_at"]):
        result.update(
            RELEASE_DECISION="DO_NOT_UPLOAD",
            current_readiness="RECHECK_REQUIRED",
            workflow_valid=False,
            baseline_preserved=True,
        )
    else:
        result["current_readiness"] = "VALID_AT_RECORDED_TIME"
    return result


def _finish(
    store,
    run_dir,
    manifest,
    scope,
    previous,
    template,
    assignments,
    validation,
    solver,
    prepared,
    inputs,
    fixture,
    timings,
):
    if (
        validation["FILE_VALID"] is not True
        or solver.get("incumbent_valid") is not True
    ):
        raise ValueError("FINAL_REFEREE_REFUSED: " + "; ".join(validation["errors"]))
    raw = template.render(assignments, set(manifest["metadata"]["mutable_entry_ids"]))
    # Reparse exact final bytes before they can receive any certificate.
    reparsed = parse_entries(raw)
    if {e.entry_id: e.roster for e in reparsed.entries} != assignments:
        raise ValueError("export/assignment reconciliation failed")
    assignment_raw = json_bytes(assignments)
    diagnostics = {
        **validation,
        **timings,
        "schema_version": 1,
        "run_id": run_dir.name,
        "workflow_valid": True,
        "selection_certified": True,
        "allocation_certified": True,
        "EVIDENCE_STATE": "OFFLINE_FIXTURE" if fixture else "CURRENT",
        "MODEL_STATUS": "PRIOR_ONLY",
        "economic_certification": False,
        "RELEASE_DECISION": "FIXTURE_DO_NOT_UPLOAD"
        if fixture
        else "MANUAL_REVIEW_REQUIRED",
        "export_sha256": digest(raw),
        "assignment_sha256": digest(assignment_raw),
        "solver": solver,
        "source_hashes": {k: digest(v) for k, v in sorted(inputs.items())},
        "valid_as_of": validation["valid_as_of"],
        "source_expiry": min(s.expires_at for s in prepared.bundle.sources).isoformat(),
        "llm_calls": 0,
        "network_calls": 0,
        "llm_tokens": 0,
        "contest_profiles": [
            c.model_dump(mode="json") | {"field_rosters": None}
            for c in prepared.bundle.contests
        ],
    }
    store.artifact(run_dir, manifest, "final/DKEntries.csv", raw)
    store.artifact(run_dir, manifest, "final/assignments.json", assignment_raw)
    store.artifact(run_dir, manifest, "final/diagnostics.json", json_bytes(diagnostics))
    manifest.update(
        status="verified",
        certification={
            k: diagnostics[k]
            for k in (
                "FILE_VALID",
                "workflow_valid",
                "selection_certified",
                "allocation_certified",
            )
        },
    )
    safe = store.publish(scope, previous, run_dir, manifest)
    if digest(safe.read_bytes()) != digest(raw):
        raise ValueError("safe export readback differs from the committed export")
    return {
        **diagnostics,
        "status": "validated_export",
        "export": str(run_dir / "final/DKEntries.csv"),
        "safe_export": str(safe),
        "scope": scope,
        "manifest": str(run_dir / "manifest.json"),
    }


def _validate_fields(bundle, players, mode, template):
    """Validate every opponent roster; duplicates are legal opponents and retained."""
    from collections import Counter
    from mlb_engine.optimize.roster_contracts import get_contract

    slots = get_contract(mode).slots
    for contest in bundle.contests:
        if contest.field_rosters is None:
            continue
        own_count = sum(e.contest_id == contest.contest_id for e in template.entries)
        if len(contest.field_rosters) + own_count != contest.field_size:
            raise ValueError(
                "opponent field must exclude our entries and match total field size"
            )
        for roster in contest.field_rosters:
            if len(roster) != len(slots) or any(pid not in players for pid in roster):
                raise ValueError(
                    "field roster geometry or salary membership is invalid"
                )
            selected = [players[pid] for pid in roster]
            if len({p.person_id for p in selected}) != len(slots):
                raise ValueError("field lineup duplicates a physical player")
            if sum(p.salary for p in selected) > 50000:
                raise ValueError("field lineup exceeds salary cap")
            if any(
                (p.role != s if mode == "SHOWDOWN" else s not in p.positions)
                for s, p in zip(slots, selected)
            ):
                raise ValueError("field lineup position is illegal")
            if mode == "CLASSIC":
                counts = Counter(p.team for p in selected if "P" not in p.positions)
                if (
                    max(counts.values(), default=0) > 5
                    or len({p.game_id for p in selected}) < 2
                ):
                    raise ValueError("field lineup game/team rule violation")
            elif len({p.team for p in selected}) != 2:
                raise ValueError("Showdown field lineup must represent both teams")
