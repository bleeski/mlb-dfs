"""Offline acceptance and adversarial boundaries for the canonical engine."""

from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from fractions import Fraction
import io
import itertools
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from pydantic import ValidationError

from mlb_engine.production import optimizer, portfolio, workflow
from mlb_engine.production.contracts import Controls, EvidenceBundle, Projection
from mlb_engine.production.csvio import parse_entries, parse_salary, verify_template
from mlb_engine.production.demo import AS_OF, execute_demo, make_fixture
from mlb_engine.production.evidence import (
    FileProvider,
    UnavailableLiveProvider,
    prepare,
    validate_edge_output,
)
from mlb_engine.production.optimizer import (
    Deadline,
    LinearModel,
    candidate,
    solve_portfolio,
)
from mlb_engine.production.referee import inspect_export
from mlb_engine.production.simulation import (
    pareto_improves,
    portfolio_metrics,
    settle_scenarios,
    settle_scores,
    simulate,
)
from mlb_engine.production.state import StateStore, digest, json_bytes


@pytest.fixture
def fixture(tmp_path):
    return make_fixture(tmp_path / "input", entry_count=2)


def load(paths, controls=None):
    controls = controls or Controls(enhance=False)
    mode, players = parse_salary(paths["salary"].read_bytes())
    template = parse_entries(paths["entries"].read_bytes())
    bundle = EvidenceBundle.model_validate_json(paths["evidence"].read_bytes())
    prepared = prepare(bundle, players, controls, AS_OF, True)
    return mode, players, template, prepared


def build(paths, **kwargs):
    return workflow.run(
        **paths,
        fixture_mode=True,
        as_of=AS_OF,
        controls=kwargs.pop("controls", Controls(enhance=False)),
        **kwargs,
    )


def solve(paths, controls=None):
    controls = controls or Controls(enhance=False)
    mode, players, template, prepared = load(paths, controls)
    assignments, report = solve_portfolio(
        template.entries,
        mode,
        players,
        prepared,
        controls,
        AS_OF,
        {e.entry_id for e in template.entries},
        Deadline(30),
    )
    return assignments, report


def edit_bundle(paths, change):
    data = json.loads(paths["evidence"].read_bytes())
    change(data)
    paths["evidence"].write_bytes(json_bytes(data))


@pytest.mark.parametrize(
    "field,value",
    [
        ("mean", float("nan")),
        ("mean", float("inf")),
        ("stddev", 0),
        ("ownership", 20),
        ("ownership", -0.01),
        ("ownership", "0.2"),
        ("captain_ownership", 0.9),
        ("unvalidated_swap", "1001"),
    ],
)
def test_strict_projection_schema(fixture, field, value):
    data = json.loads(fixture["evidence"].read_bytes())["projections"][0]
    data[field] = value
    with pytest.raises(ValidationError):
        Projection.model_validate(data)


@pytest.mark.parametrize(
    "field,value",
    [
        ("enhance", "False"),
        ("max_player_exposure", 70),
        ("qa_iterations", 4),
        ("total_seconds", float("inf")),
        ("stack_min", 7),
        ("max_shared_players", -1),
        ("seed", -1),
        ("unknown_control", True),
    ],
)
def test_strict_controls(field, value):
    with pytest.raises(ValidationError):
        Controls(**{field: value})


@pytest.mark.parametrize(
    "mutation", ["duplicate", "nan_salary", "unknown_clock", "wrong_id", "empty"]
)
def test_salary_rejects_malformed_authority(fixture, mutation):
    rows = list(
        csv.reader(io.StringIO(fixture["salary"].read_bytes().decode("utf-8-sig")))
    )
    if mutation == "duplicate":
        rows.append(rows[1])
    elif mutation == "empty":
        rows = rows[:1]
    else:
        index, value = {
            "nan_salary": ("Salary", "NaN"),
            "unknown_clock": ("Game Info", "NYM@ATL TBD"),
            "wrong_id": ("Name + ID", "Wrong Person (999999)"),
        }[mutation]
        rows[1][rows[0].index(index)] = value
    out = io.StringIO()
    csv.writer(out).writerows(rows)
    with pytest.raises(ValueError):
        parse_salary(out.getvalue().encode())


def test_entries_empty_duplicate_and_partial(fixture):
    raw = fixture["entries"].read_bytes()
    with pytest.raises(ValueError):
        parse_entries(raw.splitlines(keepends=True)[0])
    with pytest.raises(ValueError):
        parse_entries(raw.replace(b"90001", b"90000"))
    template = parse_entries(raw)
    partial = raw.replace(b"$1.00,", b"$1.00,1001,", 1)
    fixture["entries"].write_bytes(partial)
    assert build(fixture)["status"] == "blocked"
    assert len(template.entries) == 2


def test_exact_csv_bytes_and_unauthorized_cells(fixture):
    # Multiline quoted names, BOM, CRLF, escaped quotes and instruction cells.
    raw = fixture["entries"].read_bytes().replace(b"example", b"line one\r\nline two")
    fixture["entries"].write_bytes(raw)
    assignments, report = solve(fixture)
    assert report["incumbent_valid"]
    template = parse_entries(raw)
    exported = template.render(assignments, set(assignments))
    assert exported.startswith(b"\xef\xbb\xbf")
    assert exported.count(b"\r\n") == raw.count(b"\r\n")
    assert b"line one\r\nline two" in exported
    assert exported.splitlines(keepends=True)[-1] == raw.splitlines(keepends=True)[-1]
    verify_template(template, exported, set(assignments))
    for tampered in (
        exported.replace(b"keep exactly", b"changed", 1),
        exported.replace(b"$1.00", b"$2.00", 1),
        exported.replace(b"Do not edit", b"Edited"),
    ):
        with pytest.raises(ValueError):
            verify_template(template, tampered, set(assignments))
    with pytest.raises(ValueError):
        template.render(assignments, set())


@pytest.mark.parametrize(
    "status", ["confirmed_out", "bench", "unknown", "projected_starter"]
)
def test_probable_pitcher_gate(fixture, status):
    edit_bundle(fixture, lambda d: d["players"][0].update(status=status))
    _, _, _, prepared = load(fixture)
    assert "1001" not in prepared.eligible


def test_confirmed_and_projected_hitter_rules(fixture):
    edit_bundle(fixture, lambda d: d["players"][1].update(status="projected_starter"))
    assert "1002" in load(fixture)[3].eligible
    assert (
        "1002" not in load(fixture, Controls(allow_projected_hitters=False))[3].eligible
    )
    # A short order must never claim confirmation.
    edit_bundle(fixture, lambda d: d["games"][0]["lineups"][0]["ordered_ids"].pop())
    with pytest.raises(ValidationError):
        load(fixture)


@pytest.mark.parametrize(
    "what",
    [
        "expired",
        "future",
        "date",
        "wrong_team",
        "wrong_player",
        "missing_projection",
        "unknown_weather",
    ],
)
def test_evidence_fail_closed(fixture, what):
    def change(data):
        if what == "expired":
            data["sources"][0]["expires_at"] = AS_OF.isoformat()
        elif what == "future":
            data["sources"][0]["observed_at"] = (
                AS_OF + timedelta(minutes=1)
            ).isoformat()
        elif what == "date":
            data["games"][0]["start"] = "2040-07-02T22:00:00+00:00"
        elif what == "wrong_team":
            data["players"][0]["team"] = "LAD"
        elif what == "wrong_player":
            data["players"][0]["player_id"] = "999999"
        elif what == "missing_projection":
            data["projections"].pop()
        else:
            data["games"][0]["weather"] = "unknown"

    edit_bundle(fixture, change)
    result = build(fixture)
    assert result["status"] == "blocked"
    assert result["RELEASE_DECISION"] == "DO_NOT_UPLOAD"
    assert not list(fixture["output"].glob("safe/**/*.csv"))


@pytest.mark.parametrize(
    "state,weather",
    [
        ("postponed", "clear"),
        ("cancelled", "clear"),
        ("scheduled", "high"),
        ("scheduled", "medium"),
    ],
)
def test_weather_and_postponement_never_relax_legality(fixture, state, weather):
    edit_bundle(fixture, lambda d: d["games"][0].update(state=state, weather=weather))
    result = build(fixture)
    assert result["status"] == "blocked"  # Classic requires both remaining games.
    assert result["solver"]["proven_infeasible"]
    assert result["solver"]["diagnostic_relaxation"]["applied"] is False


@pytest.mark.parametrize(
    "relative", ["../secret.txt", "C:\\secret.txt", "/secret.txt", ".env"]
)
def test_source_path_confinement(fixture, relative):
    edit_bundle(fixture, lambda d: d["sources"][0].update(artifact=relative))
    with pytest.raises((ValueError, FileNotFoundError)):
        FileProvider(fixture["evidence"]).read()


def test_source_hash_and_unavailable_connector(fixture):
    (fixture["evidence"].parent / "source.json").write_bytes(b"changed")
    assert build(fixture)["status"] == "blocked"
    with pytest.raises(RuntimeError, match="LIVE_PROVIDER_UNAVAILABLE"):
        UnavailableLiveProvider().read()


def test_classic_full_run_and_independent_geometry(fixture):
    hashes = {k: digest(v.read_bytes()) for k, v in fixture.items() if k != "output"}
    result = build(fixture)
    assert result["status"] == "validated_export", result
    assert all(
        result[k] is True
        for k in (
            "FILE_VALID",
            "workflow_valid",
            "selection_certified",
            "allocation_certified",
        )
    )
    assert result["economic_certification"] is False
    assert result["MODEL_STATUS"] == "PRIOR_ONLY"
    _, players = parse_salary(fixture["salary"].read_bytes())
    after = parse_entries(Path(result["export"]).read_bytes())
    assert [e.entry_id for e in after.entries] == ["90000", "90001"]
    for e in after.entries:
        selected = [players[p] for p in e.roster]
        assert len(set(e.roster)) == 10
        assert sum(p.salary for p in selected) <= 50000
        assert all(
            pos in player.positions
            for pos, player in zip(
                ("P", "P", "C", "1B", "2B", "3B", "SS", "OF", "OF", "OF"), selected
            )
        )
        assert len({p.game_id for p in selected}) >= 2
        assert not any(p.opponent == h.team for p in selected[:2] for h in selected[2:])
    assert hashes == {k: digest(fixture[k].read_bytes()) for k in hashes}
    assert (
        Path(result["safe_export"]).read_bytes() == Path(result["export"]).read_bytes()
    )


def test_showdown_exact_oracle_and_captain_roles(tmp_path):
    paths = make_fixture(tmp_path / "sd", "SHOWDOWN", 1)
    mode, players, template, prepared = load(paths)
    assignments, report = solve(paths)
    assert report["status"] == "OPTIMAL"
    actual = candidate(assignments["90000"], mode, players, prepared)
    # Exhaustive role-aware oracle on the ten highest means; equal salary is not
    # assumed. Twenty-player pool remains small enough for exhaustive 6-person search.
    means = {p.player_id: p.mean for p in prepared.bundle.projections}
    best = -float("inf")
    util = [p for p in players.values() if p.role == "UTIL"]
    for cpt in (p for p in players.values() if p.role == "CPT"):
        eligible = [p for p in util if p.person_id != cpt.person_id]
        for others in itertools.combinations(eligible, 5):
            selected = [cpt, *others]
            if (
                sum(p.salary for p in selected) <= 50000
                and len({p.team for p in selected}) == 2
            ):
                best = max(
                    best,
                    1.5 * means[cpt.person_id]
                    + sum(means[p.person_id] for p in others),
                )
    assert actual.mean == pytest.approx(best)
    assert len(actual.people) == 6 and actual.captain is not None
    result = build(paths)
    assert result["status"] == "validated_export"
    scores = simulate(players, prepared, Controls(simulations=128))
    roster = assignments["90000"]
    expected = sum(
        scores.scores[:, scores.person_ids.index(players[p].person_id)]
        * (1.5 if i == 0 else 1)
        for i, p in enumerate(roster)
    )
    np.testing.assert_allclose(
        scores.lineup_scores([roster], mode, players)[:, 0], expected
    )


def test_hard_exposure_overlap_and_stack_controls(fixture):
    controls = Controls(
        enhance=False,
        max_player_exposure=0.5,
        max_pitcher_exposure=0.5,
        max_shared_players=0,
    )
    result = build(fixture, controls=controls)
    assert result["status"] == "validated_export", result
    assert max(result["player_counts"].values()) == 1
    assert result["max_shared_players"] == 0
    assignments, _ = solve(
        fixture,
        Controls(
            enhance=False,
            stack_team="NYM",
            stack_min=5,
            stack_max=5,
            bringback_min=1,
            max_opposing_hitters_per_sp=8,
        ),
    )
    assert assignments
    _, players, _, _ = load(fixture)
    for roster in assignments.values():
        assert sum(players[pid].team == "NYM" for pid in roster[2:]) == 5
        assert sum(players[pid].team == "ATL" for pid in roster[2:]) >= 1
    result = build(fixture, controls=Controls(enhance=False, max_player_exposure=0.0))
    assert result["status"] == "blocked"
    assert result["solver"]["proven_infeasible"] is True
    assert result["solver"]["relaxations_applied"] == []


@pytest.mark.parametrize(
    "status,x,accepted,infeasible",
    [
        (0, [1.0], True, False),
        (1, [1.0], True, False),
        (1, None, False, False),
        (2, None, False, True),
        (3, None, False, False),
        (4, [1.0], False, False),
        (0, [0.6], False, False),
        (0, [float("nan")], False, False),
        (0, [0.0], False, False),
        (0, [2.0], False, False),
        (0, [1.0, 0.0], False, False),
    ],
)
def test_solver_status_and_incumbent_boundary(
    monkeypatch, status, x, accepted, infeasible
):
    monkeypatch.setattr(
        optimizer, "milp", lambda **kw: SimpleNamespace(status=status, x=x, mip_gap=0)
    )
    model = LinearModel()
    v = model.variable(1)
    model.add("required", {v: 1}, 1, 1)
    result = model.solve(Deadline(2), 1)
    assert (result.x is not None) == accepted
    assert result.report["proven_infeasible"] == infeasible


def test_no_manual_swap_and_three_iteration_bound(fixture, monkeypatch):
    mode, players, template, prepared = load(fixture)
    assignments, _ = solve(fixture)
    scenarios = simulate(players, prepared, Controls(simulations=128))
    calls = []

    def fake_allocate(*args):
        calls.append(args[-1].copy())
        return assignments, {"incumbent_valid": True}

    monkeypatch.setattr(portfolio, "allocate_candidates", fake_allocate)
    counter = iter(range(100))

    def metric(*args):
        i = next(counter)
        return {
            "contest_ceiling": float(i),
            "portfolio_safety": float(i),
            "ceiling_definition": "test",
            "safety_definition": "test",
        }

    monkeypatch.setattr(portfolio, "portfolio_metrics", metric)
    _, review = portfolio.enhance(
        assignments,
        template.entries,
        mode,
        players,
        prepared,
        Controls(max_candidates_per_entry=1),
        AS_OF,
        set(assignments),
        scenarios,
        scenarios,
        Deadline(10),
        lambda x: {"FILE_VALID": True},
    )
    assert len(calls) == 3 and review["iterations"] == 3
    assert all(d["accepted"] for d in review["decisions"])


@pytest.mark.parametrize(
    "after,expected",
    [
        ((2, 1), True),
        ((1, 2), True),
        ((1, 1), False),
        ((3, 0), False),
        ((0, 3), False),
        ((float("nan"), 2), False),
    ],
)
def test_pareto_never_trades_away_one_requirement(after, expected):
    before = {
        "contest_ceiling": 1,
        "portfolio_safety": 1,
        "ceiling_definition": "x",
        "safety_definition": "y",
    }
    proposed = dict(before, contest_ceiling=after[0], portfolio_safety=after[1])
    assert bool(pareto_improves(before, proposed)) == expected


def test_simulation_reproducibility_and_payout_ties(fixture):
    mode, players, template, prepared = load(fixture)
    c = Controls(simulations=128)
    a, b = simulate(players, prepared, c), simulate(players, prepared, c)
    np.testing.assert_array_equal(a.scores, b.scores)
    assert not a.scores.flags.writeable
    assert not np.array_equal(a.scores, simulate(players, prepared, c, seed=7).scores)
    assert settle_scores([100, 100, 90, 100], [1000, 500, 100, 0]) == [
        Fraction(1600, 3),
        Fraction(1600, 3),
        0,
        Fraction(1600, 3),
    ]
    rng = np.random.default_rng(55)
    scores = rng.integers(0, 5, size=(50, 9)).astype(float)
    curve = [1000, 500, 200, 100, 0, 0, 0, 0, 0]
    payouts, first = settle_scenarios(scores[:, :3], scores[:, 3:], curve)
    for i, row in enumerate(scores):
        expected = settle_scores(row.tolist(), curve)
        np.testing.assert_allclose(payouts[i], [float(v) for v in expected[:3]])
        assert first[i].tolist() == [v == max(row) for v in row[:3]]
        assert sum(expected) == sum(curve)


def test_conditional_payouts_not_calibrated_ev(fixture):
    assignments, _ = solve(fixture)
    edit_bundle(
        fixture,
        lambda d: d["contests"][0].update(
            field_size=3,
            payouts_cents=[300, 0, 0],
            field_rosters=[list(next(iter(assignments.values())))],
            source_id="fixture",
        ),
    )
    mode, players, template, prepared = load(fixture)
    metrics = portfolio_metrics(
        assignments,
        template.entries,
        mode,
        players,
        prepared,
        simulate(players, prepared, Controls(simulations=128)),
    )
    assert metrics["payout_state"] == "CONDITIONAL_ON_SUPPLIED_FIELD_AND_PRIOR"
    assert metrics["label"] == "UNCALIBRATED_CORRELATED_PRIOR"
    assert 0 <= metrics["conditional_washout"] <= 1
    assert metrics["conditional_washout"] + metrics["conditional_any_cash"] == 1


@pytest.mark.parametrize("z,blocked", [(1.5, False), (1.5001, True), (-1.5001, True)])
def test_market_sigma_discrepancy(fixture, z, blocked):
    def change(d):
        d["markets"] = [
            {
                "game_id": d["games"][0]["game_id"],
                "source_id": "fixture",
                "model_total": 8 + z * np.sqrt(100 / 99),
                "market_total": 8.0,
                "residual_stddev": float(np.sqrt(100 / 99)),
                "residual_sample_size": 100,
                "residual_model_id": "held-out-residual-v1",
                "residual_fitted_before": "2040-06-01T00:00:00Z",
                "decimal_odds": [1.9, 1.9],
                "residual_source_id": "fixture",
                "residual_observations": [
                    {
                        "event_id": str(i),
                        "prediction": 9.0 if i % 2 else 7.0,
                        "outcome": 8.0,
                        "predicted_at": "2040-05-01T00:00:00Z",
                        "settled_at": "2040-05-02T00:00:00Z",
                    }
                    for i in range(100)
                ],
            }
        ]

    edit_bundle(fixture, change)
    if blocked:
        assert build(fixture)["status"] == "blocked"
    else:
        check = load(fixture)[3].market_checks[0]
        assert check["fair_probabilities"] == [0.5, 0.5]
        assert check["z"] == pytest.approx(1.5)


def test_sigma_not_fabricated_without_residuals(fixture):
    edit_bundle(
        fixture,
        lambda d: d.update(
            markets=[
                {
                    "game_id": d["games"][0]["game_id"],
                    "source_id": "fixture",
                    "model_total": 100.0,
                    "market_total": 8.0,
                }
            ]
        ),
    )
    assert load(fixture)[3].market_checks[0]["z"] is None
    assert load(fixture)[3].market_checks[0]["state"] == "UNAVAILABLE"


@pytest.mark.parametrize(
    "patch",
    [
        {"confidence": "ambiguous"},
        {"player_id": "999999"},
        {"source_id": "invented"},
        {"lineup": ["1001"]},
        {"proposed_player_cap": "0.1"},
    ],
)
def test_llm_invalid_outputs_rejected(fixture, patch):
    _, players, _, prepared = load(fixture)
    output = dict(
        source_id="fixture",
        player_id="1001",
        status="confirmed_out",
        confidence="confirmed",
        rationale="Verified fact",
    )
    output.update(patch)
    with pytest.raises(ValueError):
        validate_edge_output(json.dumps(output), prepared.bundle, players)


def test_llm_proposals_do_not_mutate_lineups(fixture):
    raw = json.dumps(
        dict(
            source_id="fixture",
            player_id="1001",
            status="confirmed_out",
            confidence="confirmed",
            rationale="Proposal only",
        )
    )
    first = build(fixture)
    second = build(fixture, edge_output=raw)
    assert first["export_sha256"] == second["export_sha256"]
    assert second["llm_calls"] == 0


def test_late_scratch_locked_slots_and_parent_compare(tmp_path):
    result = execute_demo(tmp_path / "demo")
    assert result["status"] == "verified", result
    root = tmp_path / "demo"
    before = parse_entries((root / "parent.csv").read_bytes())
    after = parse_entries(Path(result["late_swap"]["safe_export"]).read_bytes())
    _, players = parse_salary((root / "DKSalaries.csv").read_bytes())
    for old, new in zip(before.entries, after.entries):
        assert old.entry_id == new.entry_id
        for i, pid in enumerate(old.roster):
            if players[pid].start.hour == 22:
                assert new.roster[i] == pid
        assert result["scratch_id"] not in new.roster
    stale = workflow.run(
        root / "DKSalaries.csv",
        root / "parent.csv",
        root / "scratch_evidence.json",
        root / "store",
        parent=root / "parent.csv",
        authorized_entry_ids={e.entry_id for e in before.entries},
        controls=Controls(enhance=False),
        fixture_mode=True,
        as_of=datetime(2040, 7, 1, 22, 30, tzinfo=timezone.utc),
    )
    assert (
        stale["status"] == "blocked"
        and "current committed export" in stale["errors"][0]
    )


def test_preserved_rows_count_against_exposure(fixture):
    first = build(fixture)
    fixture["entries"].write_bytes(Path(first["export"]).read_bytes())
    result = build(fixture, controls=Controls(enhance=False, max_player_exposure=0.0))
    assert result["status"] == "blocked"
    assert Path(first["safe_export"]).read_bytes() == fixture["entries"].read_bytes()


def test_safe_export_recovery_idempotence_and_failure(fixture):
    first = build(fixture)
    safe = Path(first["safe_export"])
    payload, mtime = safe.read_bytes(), safe.stat().st_mtime_ns
    store = StateStore(fixture["output"])
    store.recover_safe(first["scope"])
    assert safe.stat().st_mtime_ns == mtime
    second = build(fixture)
    assert second["export_sha256"] == first["export_sha256"]
    assert safe.stat().st_mtime_ns == mtime
    safe.write_bytes(b"interrupted mirror")
    store.recover_safe(first["scope"])
    assert safe.read_bytes() == payload
    edit_bundle(fixture, lambda d: d["sources"][0].update(expires_at=AS_OF.isoformat()))
    assert build(fixture)["status"] == "blocked"
    assert safe.read_bytes() == payload


def test_empty_or_forged_certificates_and_manifest_escape(fixture):
    store = StateStore(fixture["output"])
    run, manifest = store.create_run({}, {})
    with pytest.raises(ValueError, match="no frozen inputs"):
        store.verify_bundle(run.name)
    result = build(fixture)
    run = Path(result["manifest"]).parent
    original = json.loads(Path(result["manifest"]).read_bytes())
    manifest = json.loads(json.dumps(original))
    manifest["artifacts"]["final/DKEntries.csv"]["path"] = "../escape.csv"
    store.save_manifest(run, manifest)
    with pytest.raises(ValueError, match="escapes"):
        store.verify_bundle(run.name)
    store.save_manifest(run, original)
    # Re-hash a forged illegal roster and its alleged certificate; actual legality
    # must still be rederived instead of trusting every hash and True flag.
    raw = (run / "final/DKEntries.csv").read_bytes().replace(b"1001", b"9999")
    (run / "final/DKEntries.csv").write_bytes(raw)
    original["artifacts"]["final/DKEntries.csv"]["sha256"] = digest(raw)
    diagnostics = json.loads((run / "final/diagnostics.json").read_bytes())
    diagnostics["export_sha256"] = digest(raw)
    (run / "final/diagnostics.json").write_bytes(json_bytes(diagnostics))
    original["artifacts"]["final/diagnostics.json"]["sha256"] = digest(
        json_bytes(diagnostics)
    )
    store.save_manifest(run, original)
    with pytest.raises(ValueError):
        store.verify_bundle(run.name)


def test_publication_compare_and_swap(fixture):
    result = build(fixture)
    store = StateStore(fixture["output"])
    manifest = json.loads(Path(result["manifest"]).read_bytes())
    with pytest.raises(RuntimeError, match="PARENT_CONFLICT"):
        store.publish(result["scope"], None, Path(result["manifest"]).parent, manifest)


def test_enhancement_failure_keeps_baseline(fixture, monkeypatch):
    monkeypatch.setattr(
        workflow,
        "simulate",
        lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("fixture simulation failure")
        ),
    )
    result = build(fixture, controls=Controls(enhance=True))
    assert result["status"] == "validated_export"
    assert result["baseline_preserved"]
    assert (
        Path(result["safe_export"]).read_bytes() == Path(result["export"]).read_bytes()
    )


def test_referee_rejects_illegal_export_even_if_solver_claims_success(fixture):
    mode, players, template, prepared = load(fixture)
    assignments, _ = solve(fixture)
    eid = next(iter(assignments))
    bad = dict(assignments)
    bad[eid] = (bad[eid][2], *bad[eid][1:])
    check = inspect_export(
        template,
        template.render(bad, set(bad)),
        players,
        prepared,
        Controls(),
        AS_OF,
        set(bad),
    )
    assert not check["FILE_VALID"]
    assert any("positional violation" in x for x in check["errors"])


def test_primary_stack_and_pitcher_pair_constraints(fixture):
    controls = Controls(
        enhance=False,
        primary_stack_min_size=4,
        max_primary_stack_exposure=0.5,
        max_sp_pair_repetition=1,
    )
    result = build(fixture, controls=controls)
    assert result["status"] == "validated_export", result
    assert max(result["primary_stack_counts"].values()) == 1
    assert max(result["sp_pair_counts"].values()) == 1


def test_showdown_caps_include_role_equivalence(tmp_path):
    paths = make_fixture(tmp_path / "sd_caps", "SHOWDOWN", 3)
    result = build(
        paths,
        controls=Controls(
            enhance=False,
            max_captain_exposure=0.5,
            max_player_exposure=0.7,
            max_shared_players=4,
        ),
    )
    assert result["status"] == "validated_export", result
    assert max(result["captain_counts"].values()) == 1
    assert max(result["player_counts"].values()) <= 2
    assert result["max_shared_players"] <= 4


def test_wrong_embedded_draftgroup_blocks(fixture):
    from mlb_engine.production.csvio import inspect_embedded_pool

    raw = fixture["entries"].read_bytes()
    lines = raw.decode("utf-8-sig").splitlines()
    lines[0] += ",Position,Name + ID,Name,ID"
    lines[1] += ",P,Alien (999999),Alien,999999"
    template = parse_entries(("\r\n".join(lines) + "\r\n").encode())
    _, players = parse_salary(fixture["salary"].read_bytes())
    with pytest.raises(ValueError, match="different draftgroups"):
        inspect_embedded_pool(template, players)


def test_simulation_missing_moments_preserves_legal_baseline(fixture):
    edit_bundle(fixture, lambda d: d["projections"][0].update(stddev=None))
    result = build(fixture, controls=Controls(enhance=True))
    assert result["status"] == "validated_export"
    assert "SIMULATION_UNAVAILABLE" in result["enhancement_status"]


def test_fixture_cannot_masquerade_as_live(fixture):
    result = workflow.run(**fixture, controls=Controls(enhance=False))
    assert result["status"] == "blocked"
    with pytest.raises(ValueError, match="artificial clock"):
        workflow.run(**fixture, as_of=AS_OF)


def test_naive_lock_clock_refused(fixture):
    with pytest.raises(ValueError, match="timezone-aware"):
        workflow.run(**fixture, fixture_mode=True, as_of=AS_OF.replace(tzinfo=None))


def test_unexpected_exception_records_failure(fixture, monkeypatch):
    monkeypatch.setattr(
        workflow,
        "solve_portfolio",
        lambda *a, **k: (_ for _ in ()).throw(ArithmeticError("fixture")),
    )
    result = build(fixture)
    assert result["status"] == "blocked"
    assert Path(result["manifest"]).exists()
    assert json.loads(Path(result["manifest"]).read_bytes())["status"] == "blocked"


@pytest.mark.parametrize("curve", [[100, -1], [0, 100], [100.0, 0], [True, 0]])
def test_invalid_payout_units_rejected(curve):
    with pytest.raises(ValueError):
        settle_scenarios(np.array([[1]]), np.array([[1]]), curve)


def test_source_policy_cannot_be_bypassed_with_long_declared_expiry(fixture):
    result = workflow.run(
        **fixture,
        controls=Controls(enhance=False),
        fixture_mode=True,
        as_of=AS_OF + timedelta(minutes=31),
    )
    assert result["status"] == "blocked"
    assert "STALE_SOURCE_POLICY" in result["errors"][0]


def test_monitor_repeats_are_idempotent_and_stale_sources_preserve_parent(fixture):
    from mlb_engine.production.monitor import tick

    result = build(fixture)
    safe = Path(result["safe_export"])
    original = safe.read_bytes()
    token, updated = tick(
        fixture["salary"],
        fixture["evidence"],
        fixture["output"],
        result["scope"],
        {"90000", "90001"},
        controls=Controls(enhance=False),
        fixture_mode=True,
        as_of=AS_OF,
    )
    assert updated["status"] == "validated_export", updated
    token2, unchanged = tick(
        fixture["salary"],
        fixture["evidence"],
        fixture["output"],
        result["scope"],
        {"90000", "90001"},
        token,
        Controls(enhance=False),
        fixture_mode=True,
        as_of=AS_OF,
    )
    assert token2 == token and unchanged["status"] == "unchanged"
    _, expired = tick(
        fixture["salary"],
        fixture["evidence"],
        fixture["output"],
        result["scope"],
        {"90000", "90001"},
        token,
        Controls(enhance=False),
        fixture_mode=True,
        as_of=AS_OF + timedelta(minutes=31),
    )
    assert expired["status"] == "blocked" and safe.read_bytes() == original


def test_input_sheets_and_freeze_need_facts_not_programming(fixture, tmp_path):
    from mlb_engine.production.intake import create_intake, freeze_intake, write_table

    root = tmp_path / "packet"
    create_intake(fixture["salary"], fixture["entries"], root)
    assert (root / "DKSalaries.csv").read_bytes() == fixture["salary"].read_bytes()
    with pytest.raises(ValueError):
        freeze_intake(root)
    data = json.loads(fixture["evidence"].read_bytes())
    (root / "source.json").write_bytes(
        (fixture["evidence"].parent / "source.json").read_bytes()
    )
    for name in ("sources", "games", "players", "projections", "contests"):
        rows = data[name]
        columns = next(
            csv.reader(
                io.StringIO((root / (name + ".csv")).read_bytes().decode("utf-8-sig"))
            )
        )
        write_table(
            root / (name + ".csv"),
            columns,
            [
                {k: (r.get(k) if r.get(k) is not None else "") for k in columns}
                for r in rows
            ],
        )
    result = freeze_intake(root)
    assert result["status"] == "evidence_frozen"
    again = freeze_intake(root)
    assert again["evidence"] == result["evidence"]
    assert (
        EvidenceBundle.model_validate_json(
            Path(result["evidence"]).read_bytes()
        ).fixture
        is False
    )
    # Freezing fictional future data cannot certify it at the real execution clock.
    assert (
        workflow.run(
            root / "DKSalaries.csv",
            root / "DKEntries.csv",
            result["evidence"],
            root / "store",
        )["status"]
        == "blocked"
    )


def test_owned_full_pool_must_reconcile_slot_budgets(fixture):
    edit_bundle(fixture, lambda d: d["projections"][0].update(ownership=0.99))
    assert "roster-slot budgets" in build(fixture)["errors"][0]


def test_residual_sigma_assertion_alone_is_unavailable(fixture):
    edit_bundle(
        fixture,
        lambda d: d.update(
            markets=[
                {
                    "game_id": d["games"][0]["game_id"],
                    "source_id": "fixture",
                    "model_total": 20.0,
                    "market_total": 8.0,
                    "residual_stddev": 1.0,
                    "residual_sample_size": 500,
                    "residual_model_id": "asserted",
                    "residual_fitted_before": "2040-06-01T00:00:00Z",
                }
            ]
        ),
    )
    assert load(fixture)[3].market_checks[0]["z"] is None


def test_contest_title_inference_and_unknown_fallback(fixture):
    from mlb_engine.production.contracts import infer_shape

    assert infer_shape("Single Entry Satellite") == "satellite"
    assert infer_shape("$2 Double Up") == "cash"
    assert infer_shape("Winner Take All") == "wta"
    assert infer_shape("mystery product") is None
    edit_bundle(fixture, lambda d: d.update(contests=[]))
    result = build(fixture)
    assert result["contest_profiles"][0]["shape"] == "large_gpp"
