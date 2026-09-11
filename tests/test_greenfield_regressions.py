"""Reproductions of repaired baseline defects in compatibility modules."""

from __future__ import annotations

import zipfile

import pandas as pd
import pytest

from mlb_engine.entries.dk_entries_manager import (
    _gate_bool,
    validate_dk_entries_file,
    validate_template_preservation,
)
from mlb_engine.field.ownership_prior import (
    _bounded_marginals,
    attach_predicted_ownership,
)
from mlb_engine.optimize.bank_cache import conditions_signature, projection_digest
from mlb_engine.pipeline.execution_pipeline import resolve_gate_assertions


def test_boolean_assertions_are_not_truthy_strings():
    for value in ("True", "False", "certified", 1, [True], {"passed": "True"}):
        assert not _gate_bool(value)
    assert _gate_bool(True)
    assert _gate_bool({"passed": True})


def test_supplied_gate_cannot_erase_observed_failure():
    gates, _, _, refused = resolve_gate_assertions(
        {"salary_gate_passed": False},
        {"salary_gate_passed": True},
        None,
        {"salary_gate_passed": False},
        {"salary_gate_passed": "duplicate salary ID"},
    )
    assert gates["salary_gate_passed"] is False
    assert refused[0]["gate"] == "salary_gate_passed"


def test_id_only_or_empty_entries_do_not_certify(tmp_path):
    path = tmp_path / "entries.csv"
    header = "Entry ID,Contest Name,Contest ID,Entry Fee,P,P,C,1B,2B,3B,SS,OF,OF,OF\n"
    path.write_text(
        header + "1,Example,2,$1," + ",".join(str(i) for i in range(10)) + "\n"
    )
    assert not validate_dk_entries_file(
        path, salary_player_ids=[str(i) for i in range(10)]
    )["passed"]
    path.write_text(header)
    assert not validate_dk_entries_file(path)["passed"]


def test_template_instruction_inside_roster_window_is_not_exempt(tmp_path):
    source, candidate = tmp_path / "s.csv", tmp_path / "c.csv"
    header = "Entry ID,Contest Name,Contest ID,Entry Fee,P,P,C,1B,2B,3B,SS,OF,OF,OF\n"
    raw = header + ",,,,Keep this instruction,,,,,,,,,\n"
    source.write_text(raw)
    candidate.write_text(raw.replace("Keep this instruction", "Gone"))
    assert not validate_template_preservation(source, candidate)["passed"]


@pytest.mark.parametrize(
    "column,value",
    [
        ("Team", "LAD"),
        ("Position", "OF"),
        ("Game_ID", "late"),
        ("Batting_Order", 8),
        ("Projected_Ownership_Pct", 80.0),
    ],
)
def test_cache_identity_includes_full_pool_semantics(column, value):
    frame = pd.DataFrame(
        {"Player_ID": ["1", "2"], "Ceiling": [1.0, 2.0], column: ["old", "old"]}
    )
    before = projection_digest(frame)
    changed = frame.copy()
    changed.loc[0, column] = value
    assert projection_digest(changed) != before
    assert projection_digest(frame.iloc[::-1]) == before


def test_cache_target_and_leverage_are_distinct_questions():
    frame = pd.DataFrame({"Player_ID": ["1"], "Ceiling": [1.0]})
    baseline = conditions_signature(frame)
    assert baseline != conditions_signature(frame, target="base")
    assert baseline != conditions_signature(
        frame, leverage={"min_low_owned_hitters": 2}
    )


def test_ownership_is_a_bounded_inclusion_marginal():
    result = _bounded_marginals({str(i): 10.0**i for i in range(6)}, 600)
    assert list(result.values()) == [100.0] * 6
    result = _bounded_marginals({str(i): i + 1 for i in range(20)}, 600)
    assert all(0 <= v <= 100 for v in result.values())
    assert sum(result.values()) == pytest.approx(600, abs=0.1)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, 101, True])
def test_attached_ownership_rejects_invalid_units(value):
    with pytest.raises(ValueError):
        attach_predicted_ownership(pd.DataFrame({"Player_ID": ["1"]}), {"1": value})


def test_zip_collision_is_not_idempotence(tmp_path):
    from tools.extract_inbox_zips import extract_zip

    path = tmp_path / "input.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("a/result.csv", "first")
        archive.writestr("b/result.csv", "different")
    with pytest.raises(ValueError, match="colliding"):
        extract_zip(path)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("result.csv", "first")
    [result] = extract_zip(path)
    assert extract_zip(path) == [result]
    result.write_text("different")
    with pytest.raises(ValueError, match="differs"):
        extract_zip(path)


def test_brief_parse_does_not_depend_on_key_order_or_indentation():
    from tools.autobuild import parse_brief

    raw = 'progress line\n{\n    "version": 1,\n    "status": "blocked"\n}\ntrailing progress'
    assert parse_brief(raw)["status"] == "blocked"
    assert parse_brief("no result") == {}


def test_fingerprint_covers_skill_entrypoint_and_configuration(tmp_path):
    from tools.audit import tree_fingerprint

    path = tmp_path / "skills/generate-lineups/scripts/build_slate.py"
    path.parent.mkdir(parents=True)
    path.write_text("pass\n")
    before = tree_fingerprint(tmp_path)
    path.write_text("raise RuntimeError\n")
    assert tree_fingerprint(tmp_path) != before
    before = tree_fingerprint(tmp_path)
    (tmp_path / "requirements-production.lock").write_text("scipy==1.15.3\n")
    assert tree_fingerprint(tmp_path) != before


def test_cache_invalidation_survives_a_stale_writer(tmp_path):
    """F11: a PROVEN invalidation must not be resurrected by the save union.

    The proof is the projection digest, and R338 repair (1) is why this test
    supplies one. Retiring on a bare ``drop_stale_jobs(sig)`` erased a sibling
    session's bucket instead -- the R55/R130 incident, pinned in the opposite
    direction by ``BankCacheMergeOnSaveTests
    .test_a_purge_no_longer_erases_the_other_sessions_work_on_disk``, which is
    the same shape minus the digest. Both must pass; the digest is what
    separates them.
    """
    from mlb_engine.optimize.bank_cache import BankCache

    path = tmp_path / "bank.json"
    first = BankCache(path)
    first.register_conditions("old", "digest-v1")
    first.add([str(i) for i in range(10)], 1, job="pair|team||old")
    first.attempted.add("pair|team||old")
    first.save()
    stale_writer = BankCache(path)
    first.register_conditions("new", "digest-v2")
    first.drop_stale_jobs("new", projection_digest="digest-v2")
    first.save()
    stale_writer.save()
    loaded = BankCache(path)
    assert loaded.candidates == [] and not loaded.attempted


def test_empty_legacy_certification_cannot_promote(tmp_path):
    from mlb_engine.pipeline.build_state_manager import (
        create_run,
        update_run_certification,
        promote_run,
        verify_run_bundle,
    )

    result = create_run(tmp_path, "initial_build")
    update_run_certification(
        result["run_dir"],
        dict(workflow_valid=True, selection_certified=True, allocation_certified=True),
    )
    assert not verify_run_bundle(result["run_dir"])["passed"]
    assert not promote_run(result["run_dir"])["passed"]


def test_ambiguous_name_collision_has_no_highest_pa_winner():
    from mlb_engine.projections.xwoba_base_correction import _build_name_to_mlbam

    table = pd.DataFrame(
        {
            "player_id": ["1", "2"],
            "last_name, first_name": ["Doe, John", "Doe Jr., John"],
            "pa": [1, 500],
        }
    )
    names, collisions = _build_name_to_mlbam(table, {"1": 1.1, "2": 0.9})
    assert not names and collisions


def test_project_runtime_cannot_be_shadowed_by_foreign_vendored_wheels(
    tmp_path, monkeypatch
):
    import sys
    from tools.env_probe import ensure_vendored_on_path

    foreign = tmp_path / ".pylibs"
    foreign.mkdir()
    (foreign / "scipy.py").write_text("raise RuntimeError('wrong ABI')")
    monkeypatch.setattr(sys, "prefix", str(tmp_path / ".venv"))
    before = sys.path.copy()
    assert ensure_vendored_on_path(tmp_path) is None
    assert sys.path == before


def test_standings_duplicates_keep_captain_but_ignore_util_order(tmp_path):
    import csv
    from mlb_engine.field.field_miner import parse_standings_export, mine_contest

    path = tmp_path / "standings.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["Rank", "EntryId", "EntryName", "TimeRemaining", "Points", "Lineup"]
        )
        for i, lineup in enumerate(
            [
                "CPT Alpha UTIL Bravo UTIL Charlie UTIL Delta UTIL Echo UTIL Foxtrot",
                "CPT Bravo UTIL Alpha UTIL Charlie UTIL Delta UTIL Echo UTIL Foxtrot",
                "CPT Alpha UTIL Foxtrot UTIL Echo UTIL Delta UTIL Charlie UTIL Bravo",
            ]
        ):
            writer.writerow([i + 1, str(100 + i), "user", "0", 100 - i, lineup])
    result = mine_contest(parse_standings_export(str(path)))
    assert result["duplication"]["distinct_lineups"] == 2
    assert result["duplication"]["winner_copies"] == 2
    assert result["duplication"]["entries_in_duplicated_lineups"] == 2


def test_incomplete_weather_arrays_are_unavailable(monkeypatch):
    from tools import fetch_slate_bundle as fetch

    monkeypatch.setattr(
        fetch,
        "_get_json",
        lambda _: {"hourly": {"time": ["2040-07-01T23:00"], "temperature_2m": []}},
    )
    warnings = []
    result = fetch.fetch_weather(
        {
            "games": [
                {"venue": "park", "game_pk": 1, "game_date_utc": "2040-07-01T23:00:00Z"}
            ]
        },
        {
            "park": dict(
                roof_type="open",
                wind_sensitivity="normal",
                wind_min_speed_mph=10,
                lat=1,
                lon=1,
            )
        },
        warnings,
    )
    assert result == {}
    assert any("incomplete hourly arrays" in warning for warning in warnings)


def test_provider_response_size_and_secret_errors_are_bounded(monkeypatch):
    import io
    import urllib.error
    from tools import fetch_slate_bundle as fetch

    class Oversized(io.BytesIO):
        def read(self, size=-1):
            assert size == 32 * 1024 * 1024 + 1
            return b"x" * size

    monkeypatch.setattr(fetch.urllib.request, "urlopen", lambda *a, **k: Oversized())
    with pytest.raises(RuntimeError, match="exceeds 32 MiB"):
        fetch._get_json("https://example.invalid")

    def unavailable(*args, **kwargs):
        raise urllib.error.HTTPError(
            "https://example.invalid",
            403,
            "denied",
            {},
            io.BytesIO(b"test-secret " * 100),
        )

    monkeypatch.setattr(fetch.urllib.request, "urlopen", unavailable)
    with pytest.raises(RuntimeError) as exc:
        fetch._get_json("https://example.invalid?key=test-secret", secret="test-secret")
    assert "test-secret" not in str(exc.value)
    assert len(str(exc.value)) < 400


def test_manifest_stamp_failure_updates_json_passed_flag(tmp_path, monkeypatch, capsys):
    from tests.test_upload_integrity import PreflightManifestBindingTests

    case = PreflightManifestBindingTests()
    case.setUp()
    try:
        case._write_manifest()
        module, _ = case._preflight_in_process()
        from tests.test_upload_integrity import FIXTURE_AS_OF_BEFORE_FIRST_PITCH

        argv = [
            "--entries",
            str(case.entries),
            "--salary",
            str(case.salary),
            "--as-of",
            FIXTURE_AS_OF_BEFORE_FIRST_PITCH,
            "--json",
        ]
        monkeypatch.setattr(
            module,
            "stamp_manifest_status",
            lambda *a, **k: dict(
                stamped=False, status=None, reason="test write failure"
            ),
        )
        code = module.main(argv)
        import json

        report = json.loads(capsys.readouterr().out)
        assert code == 2 and report["passed"] is False and report["failures"]
    finally:
        case.tearDown()
        case.doCleanups()


def test_legacy_naive_source_clock_is_not_assumed_utc():
    from mlb_engine.intake.live_data_adapters import _parse_utc

    with pytest.raises(ValueError, match="timezone"):
        _parse_utc("2040-07-01T12:00:00")
    assert _parse_utc("2040-07-01T12:00:00Z").utcoffset().total_seconds() == 0


def test_unclassified_showdown_failure_cannot_relax(monkeypatch):
    from mlb_engine.optimize import showdown_theses as theses
    from tests.test_showdown import _synth

    calls = []

    def failure(**kwargs):
        calls.append(kwargs)
        kwargs["status_out"].update(status=4, proven_infeasible=False)
        return None

    monkeypatch.setattr(theses, "build_showdown_lineup", failure)
    diagnostics = {}
    result = theses.solve_ladder(
        _synth(),
        [
            dict(
                template="t", name="t", why="", cpt=None, locks=[], excludes=[], mult={}
            )
        ],
        diagnostics=diagnostics,
        time_limit=1,
    )
    assert result == [None] and len(calls) == 1
    assert len(diagnostics["solver_failures"]) == 1 and diagnostics["infeasible"] == 0


def test_no_legacy_module_imports_the_production_package_or_pydantic():
    """R338 step 5's grep pin, as a test rather than a line in a changelog.

    R302 stage 0 lands `mlb_engine/production/` as a STRANGLER: it may read the
    legacy engine's inputs, and nothing in the legacy engine may depend on it.
    The whole argument for committing an unproven 5,698-line package beside a
    live build path is that the live path cannot reach it, so the moment one
    legacy module imports it the package stops being isolated and becomes an
    undeclared dependency of tonight's build. `pydantic` rides along for the
    same reason: the backlog accepts it SCOPED to this package, and a scope
    nothing enforces is a preference.

    A grep in a changelog entry records what was true on the day it was
    written. This runs on every gate.
    """
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    # The four tools the edition added are the package's own front door and are
    # exempt by construction; every other tool is legacy.
    package_tools = {"dfs.py", "verify_engine.py", "bootstrap_engine.py",
                     "benchmark_engine.py"}
    pattern = re.compile(r"^\s*(?:from|import)\s+.*\b(mlb_engine\.production|pydantic)\b",
                         re.MULTILINE)

    scanned = []
    offenders = []
    for path in sorted(root.glob("mlb_engine/**/*.py")) + sorted(root.glob("tools/*.py")):
        rel = path.relative_to(root).as_posix()
        if rel.startswith("mlb_engine/production/") or path.name in package_tools:
            continue
        scanned.append(rel)
        text = path.read_text(encoding="utf-8")
        for match in pattern.finditer(text):
            line = text[:match.start()].count("\n") + 1
            offenders.append(f"{rel}:{line} {match.group(0).strip()}")

    assert scanned, "the scan found no legacy modules, so it proved nothing"
    assert offenders == [], "\n".join(offenders)
