"""MLB DFS engine audit v3.0 (package layout).

Ported from project_audit.py v2.2 at the Cowork migration. Kept:
version-coherence, CSV schema, venue-factor join, compile, scipy.milp,
and the full-suite run with an expected test count. Retired: the SHA-256
checksum manifest, the manifest txt, and the 26-file cap. Git history is
provenance now; the retired originals live in docs/legacy/.
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import py_compile
import re
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

VERSION = "v3.4"
PROJECT_VERSION = "v2.26.0"
LAYOUT_VERSION = "v3.0.0-pre"
# Every suite the audit gates. test_core alone left the Showdown suite and the
# golden replay outside the gate, which is how showdown_theses.py stayed
# untracked while build_slate imported it unconditionally.
AUDITED_SUITES = ("tests.test_core", "tests.test_showdown",
                  "tests.test_upload_integrity", "tests.test_golden_replay",
                  # R32: the paste is the primary lineup source, so its parser
                  # sits on the intake front door and belongs inside the gate.
                  # Its failure mode is a plausible lineup on the wrong team,
                  # which no other suite would catch.
                  "tests.test_paste_lineups")

# R62: the per-suite pin, not a comment beside a total. The total used to be
# one int with the breakdown written next to it in prose, which meant the
# breakdown could not be checked and a shortfall could not be attributed. A
# shortfall that cannot be attributed is the whole defect: on 2026-08-10 an
# off-machine run of the R101 dev cycle came back `Ran 783` against a pin of
# 792, the nine missing were tests.test_golden_replay entire, and the audit
# advised LOWERING the pin -- which would have written the golden replay out
# of the gate permanently.
EXPECTED_SUITE_COUNTS = {
    # R60, 2026-08-12: 570 -> 576, the six that pin the partial-side seeding.
    # R110, 2026-08-12: 576 -> 582, the six that pin the claim round trip.
    # R69, 2026-08-13: 582 -> 594, the twelve that pin the intake fail-open
    # trio -- nine on the salary-status coverage read and the un-ageable platoon
    # reference, three on the exclusion block/warn split.
    # R70, 2026-08-14: 594 -> 621, the twenty-seven that pin stage_slate's role
    # resolution -- eleven on ambiguity blocking, its named channel out, and the
    # resolution ORDER (a bare override resolves in the slate dir, never the
    # CWD; the first cut resolved CWD-first and re-opened R70 through R70's own
    # remedy), seven on the platoon shape check and the no-platoon note, nine on
    # the checkpoint clock read including the EST case a July fixture cannot see.
    # R99+R92+R71(a)+R119+R113+R112+R103, 2026-08-15: 621 -> 640, the
    # false-signal batch's nineteen: salary_cross_check reading one object at
    # both sites (4), bank_warnings reading keys extend_bank actually returns
    # (2), _cap_count rejecting a pct>1 units slip in both copies (2),
    # summarize_enrichment writing the value_guard key it points at plus the
    # objective_differentiation corollary (2), the Showdown cap/lock caution
    # split (1, its solve_ladder half pins in test_showdown), a proven-infeasible
    # refusal naming the bank as the limiter against feasibility.inputs plus the
    # not-exhausted flag riding every binding line (5), and a hard-pinned
    # same-game SP pair surviving the diversity filter (3).
    # R116, 2026-08-15: 640 -> 653, the thirteen that pin the candidate-reuse
    # default -- ten on the allocator (the minimum_cap arithmetic, the two-rung
    # ladder and the rung that binds nothing, the concentration reproduced on
    # the cash path, the default de-concentrating a GPP file, one non-cash entry
    # making the whole file a GPP portfolio, an operator cap winning verbatim,
    # per-signature budgeting, the infeasible default delivering instead of
    # refusing, an operator cap still refusing, and the clock never walking the
    # ladder) and three on the brief (distinct lineups off the delivered bytes,
    # DK slot order not inventing diversity, both pipeline return paths carrying
    # the block).
    "tests.test_core": 653,
    # R113's solve_ladder half, 2026-08-15: 55 -> 56, lock_relaxation_detail
    # naming the thesis and the substituted captain.
    "tests.test_showdown": 56,
    # R96, 2026-08-11: 141 -> 162, the twenty-one tests that pin the delivery
    # path. A `grew` verdict is the one case where moving a pin is correct.
    # R46 round 2, 2026-08-12: 162 -> 168, the six that pin the PARTIAL side.
    # R114 + R67, 2026-08-15: 168 -> 182, the fourteen that pin the two ways a
    # legally rostered ARM read as a contradiction -- eleven on the declared arm
    # (acknowledged not failed, the sha256-matched brief, the intersection on
    # disagreeing briefs, --declare-pitcher and its bare-id default, the refusal
    # to clear a hitter, usage errors, and verify_export answering the same) and
    # three on the bullpen game (bats-only evidences no arm, its hitters still
    # bind, a side that named an arm is untouched).
    "tests.test_upload_integrity": 182,
    "tests.test_golden_replay": 9,
    "tests.test_paste_lineups": 75,
}
# The sum, not a second number to keep in step: R70 left this comment reading
# 901 while the dict already summed to 928, which is the exact staleness this
# line's own rule warns about -- the dict is the source of truth either way.
EXPECTED_TEST_COUNT = sum(EXPECTED_SUITE_COUNTS.values())  # 975

# What a suite needs on disk beyond a tracked-files-only checkout. Named so a
# shortfall prints its remedy instead of a number: "stage this" is an action,
# "783 != 792" is a puzzle. Suites absent from this map have no precondition
# and a shortfall in them is genuinely unexplained.
SUITE_PRECONDITIONS = {
    # tests.test_paste_lineups was here until 2026-08-10. R62's deferred half
    # landed: both salary files are vendored under tests/fixtures/slates/ and
    # tracked, so the suite has no precondition beyond the checkout itself and a
    # shortfall in it is now genuinely unexplained rather than "stage the slate".
    "tests.test_golden_replay": (
        "data/archive/2026-06-03/ with the DKSalaries export and the BLANK "
        "DKEntries file (tracked in git; absent only in a partial copy of "
        "the tree, which is how it went missing on 2026-08-10)"),
}

EXPECTED_VERSION_TEXT = {
    "MLB_Classic.md": "v2.26.0",
    "mlb_engine/optimize/optimizer_v3.py": "OPTIMIZER_VERSION = 'v3.23'",
    "mlb_engine/allocate/contest_allocator.py": 'VERSION = "v1.12"',
    "mlb_engine/intake/slate_intake_manager.py": 'VERSION = "v1.10"',
    "mlb_engine/entries/dk_entries_manager.py": 'VERSION = "v1.6"',
    "mlb_engine/swap/late_swap_manager.py": 'VERSION = "v1.4"',
    "mlb_engine/pipeline/build_state_manager.py": 'VERSION = "v1.4"',
    "mlb_engine/pipeline/execution_pipeline.py": 'VERSION = "v1.16"',
    "mlb_engine/projections/projection_builder.py": 'VERSION = "v1.6"',
    "mlb_engine/projections/xwoba_base_correction.py": 'VERSION = "v1.2"',
    "mlb_engine/intake/live_data_adapters.py": 'VERSION = "v1.6"',
    "mlb_engine/optimize/tail_candidate_scanner.py": 'VERSION = "v1.0"',
    "mlb_engine/intake/platoon_order_adapter.py": 'VERSION = "v1.1"',
    "mlb_engine/optimize/bank_cache.py": 'VERSION = "v1.3"',
    "mlb_engine/determinism.py": 'VERSION = "v1.0"',
    "mlb_engine/contest_shapes.py": 'VERSION = "v1.0"',
    # R59: the team-code boundary is an ingest contract, so it is pinned
    # like the other boundary modules rather than left to R76(e).
    "mlb_engine/team_codes.py": 'VERSION = "v1.0"',
}

CSV_REQUIRED = {
    "data/reference/team_to_venue.csv": {
        "Home_Team", "Venue", "Roof_Type", "Latitude", "Longitude", "Timezone",
        "Weather_Required", "Wind_Sensitivity", "Wind_Min_Speed_MPH",
    },
    "data/reference/game_venue_overrides.csv": {
        "Game_Date", "Away_Team", "Home_Team", "Venue", "Projection_F5_Status",
        "Run_Factor_Applied", "HR_Factor_Applied", "F5_Approval_Note", "Source_URL",
        "Wind_Sensitivity", "Wind_Min_Speed_MPH",
    },
    "data/reference/f5_park_factors.csv": {
        "Venue", "Run_Factor_Applied", "HR_Factor_Applied", "Wind_Sensitivity",
    },
    "data/reference/f5_weather_adjustments.csv": {
        "Adjustment_Type", "Level", "Direction", "Hitter_Factor", "Pitcher_Factor",
        "Game_Exposure_Cap", "Exclude_Game",
    },
    "data/reference/dk_contest_archetypes.csv": {"pattern", "inferred_type", "confidence"},
}


def csv_header(path: Path) -> List[str]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return next(csv.reader(handle), [])


def check_dependencies(root: Path) -> Dict[str, Any]:
    """Import every requirement before anything else runs.

    A missing solver is not a slow build, it is no build. On 2026-07-22 scipy was
    absent in a fresh environment and surfaced at T-35 on a live slate as a bare
    'scipy.optimize.milp unavailable', with the install competing for the same
    minutes as the build. Checking first turns that into a one-line fix.

    R42(a), 2026-08-03: that "one-line fix" was itself the problem three times
    the same day -- it names `python tools/env_probe.py --install`, which
    reliably fails ENOSPC in this sandbox, while a working copy already sits
    at `<root>/.pylibs`. Check there first, same as env_probe.py does, before
    importlib ever gets a chance to fail.
    """
    import importlib

    tools_dir = Path(__file__).resolve().parent
    if str(tools_dir) not in sys.path:
        sys.path.insert(0, str(tools_dir))
    import env_probe
    vendored = env_probe.ensure_vendored_on_path(root)

    req = root / "requirements.txt"
    wanted = []
    if req.exists():
        for line in req.read_text(encoding="utf-8").splitlines():
            name = line.strip().split("==")[0].split(">=")[0].split("<")[0].strip()
            if name and not name.startswith("#"):
                wanted.append(name)
    missing = []
    for name in wanted:
        try:
            importlib.import_module(name)
        except ImportError:
            missing.append(name)
    milp_ok = True
    try:
        from scipy.optimize import milp  # noqa: F401
    except Exception:  # noqa: BLE001
        milp_ok = False
    return {
        "required": wanted,
        "missing": missing,
        "scipy_milp_available": milp_ok,
        "passed": not missing and milp_ok,
        "vendored_pylibs": str(vendored) if vendored is not None else None,
        "remedy": ("python tools/env_probe.py --install"
                   if missing or not milp_ok else None),
    }


def run_audit(root: Path, run_tests: bool = False) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []
    checks: Dict[str, Any] = {}

    deps = check_dependencies(root)
    checks["dependencies"] = deps
    if not deps["passed"]:
        detail = f"missing {deps['missing']}" if deps["missing"] else "scipy.optimize.milp unavailable"
        errors.append(f"dependencies: {detail}; run: {deps['remedy']}")

    missing = [rel for rel in EXPECTED_VERSION_TEXT if not (root / rel).exists()]
    missing += [rel for rel in CSV_REQUIRED if not (root / rel).exists()]
    if missing:
        errors.append(f"missing files: {missing}")
    checks["inventory"] = {"missing": missing}

    version_failures = []
    for rel, needle in EXPECTED_VERSION_TEXT.items():
        path = root / rel
        if path.exists() and needle not in path.read_text(encoding="utf-8"):
            version_failures.append(rel)
    if version_failures:
        errors.append(f"version text mismatch: {version_failures}")
    checks["versions"] = {"passed": not version_failures, "failures": version_failures}

    csv_failures = {}
    for rel, required in CSV_REQUIRED.items():
        path = root / rel
        if not path.exists():
            continue
        absent = sorted(required - set(csv_header(path)))
        if absent:
            csv_failures[rel] = absent
    if csv_failures:
        errors.append(f"CSV schema failures: {csv_failures}")
    checks["csv_schemas"] = {"passed": not csv_failures, "failures": csv_failures}

    venue_join_missing = []
    tv = root / "data/reference/team_to_venue.csv"
    pf = root / "data/reference/f5_park_factors.csv"
    if tv.exists() and pf.exists():
        with tv.open(newline="", encoding="utf-8-sig") as handle:
            team_venues = {row["Venue"] for row in csv.DictReader(handle)}
        with pf.open(newline="", encoding="utf-8-sig") as handle:
            factor_venues = {row["Venue"] for row in csv.DictReader(handle)}
        venue_join_missing = sorted(team_venues - factor_venues)
        if venue_join_missing:
            errors.append(f"venues missing park factors: {venue_join_missing}")
    checks["venue_factor_join"] = {"passed": not venue_join_missing, "missing": venue_join_missing}

    compile_failures = []
    py_files = sorted(
        p for d in ("mlb_engine", "tools", "tests")
        for p in (root / d).rglob("*.py")
        if "__pycache__" not in p.parts
    )
    for path in py_files:
        try:
            py_compile.compile(str(path), doraise=True)
        except Exception as exc:  # pragma: no cover
            compile_failures.append(f"{path.relative_to(root)}: {exc}")
    if compile_failures:
        errors.extend(compile_failures)
    checks["python_compile"] = {"passed": not compile_failures, "count": len(py_files), "failures": compile_failures}

    scipy_ok = importlib.util.find_spec("scipy") is not None
    if scipy_ok:
        try:
            from scipy.optimize import milp  # noqa: F401
        except Exception:
            scipy_ok = False
    if not scipy_ok:
        errors.append("scipy.optimize.milp unavailable")
    checks["scipy_milp"] = {"passed": scipy_ok}

    test_result = None
    if run_tests:
        # F19: the suite includes a determinism gate, and a gate that runs under
        # a randomized hash seed cannot tell a fixed ordering from a lucky one.
        test_env = dict(os.environ)
        test_env["PYTHONHASHSEED"] = "0"
        # R42(a): sys.path mutations in this process (check_dependencies just
        # made one, if .pylibs is in play) do not reach a subprocess -- only
        # env vars do. Without this, --run-tests could fail on import errors
        # right after --terse alone reported a clean dependency PASS.
        if deps.get("vendored_pylibs"):
            existing_pp = test_env.get("PYTHONPATH", "")
            test_env["PYTHONPATH"] = deps["vendored_pylibs"] + (
                os.pathsep + existing_pp if existing_pp else "")
        test_result = run_audited_suites(root, test_env)
        errors.extend(test_result.pop("_errors"))
        warnings.extend(test_result.pop("_warnings"))
    checks["tests"] = test_result

    debt = changelog_debt(root)
    checks["changelog"] = debt
    if debt["available"] and debt["unrecorded_commits"]:
        count = debt["unrecorded_commits"]
        warnings.append(
            f"{count} commit(s) touched the DEV write set "
            f"({', '.join(CHANGELOG_TRACKED_PATHS)}; inbox fragments exempt) since "
            f"CHANGELOG.md was last written; a change is not shipped until its "
            f"entry exists. Newest: {debt['commits'][0]}")

    return {
        "project_version": PROJECT_VERSION,
        "layout_version": LAYOUT_VERSION,
        "audit_version": VERSION,
        "passed": not errors,
        "errors": errors,
        "warnings": warnings,
        "checks": checks,
        "summary": "Audit passed" if not errors else "Audit failed",
    }


def parse_unittest_report(text: str) -> Dict[str, Any]:
    """Ran/skipped/failure counts off one suite's standard footer.

    Only the footer is parsed, deliberately. The alternative -- one combined
    run plus `-v` and per-line attribution -- reads a verbose format that has
    no stability contract, inside the tool whose whole job is to be trusted.
    The footer's two shapes ("OK (skipped=3)", "FAILED (failures=1, errors=2,
    skipped=3)") have been stable for the life of unittest.

    `skipped` is NOT the number of skipped tests, and treating it as one is
    how a shortfall gets misread. Measured on 3.10 while writing this (R62):
    a class-level `skipUnless` reports every one of its tests in BOTH `Ran`
    and `skipped`, so the count holds and coverage quietly drops; a
    `setUpClass` that raises SkipTest removes the class's tests from `Ran`
    entirely and adds exactly ONE to `skipped`, so nine lost tests read as
    "skipped=1". Only the per-suite pin can tell the difference, which is why
    EXPECTED_SUITE_COUNTS exists.
    """
    ran = re.search(r"Ran\s+(\d+)\s+tests?", text)
    out: Dict[str, Any] = {
        "ran": int(ran.group(1)) if ran else None,
        "skipped": 0, "failures": 0, "errors_count": 0,
    }
    for key, field in (("skipped", "skipped"), ("failures", "failures"),
                       ("errors", "errors_count")):
        found = re.search(rf"\b{key}=(\d+)", text)
        if found:
            out[field] = int(found.group(1))
    return out


def classify_suite(name: str, rec: Dict[str, Any]) -> Dict[str, Any]:
    """One suite's count against its pin, as a verdict rather than a delta.

    R62(b): the old advice was unconditional -- suite green plus count
    mismatch printed "this is a stale pin. Update EXPECTED_TEST_COUNT". That
    sentence is true for exactly one of the five states below, and following
    it in any of the others writes real coverage out of the gate for good.
    """
    pinned = EXPECTED_SUITE_COUNTS.get(name)
    ran = rec.get("ran")
    skipped = rec.get("skipped", 0)
    precondition = SUITE_PRECONDITIONS.get(name)
    verdict = dict(rec, suite=name, pinned=pinned, precondition=precondition)

    if not rec.get("present", True):
        verdict["state"] = "absent"
        verdict["advice"] = (
            f"{name} is in AUDITED_SUITES but tests/{name.split('.')[-1]}.py "
            f"is not on disk, so its {pinned} tests did not run and were never "
            f"counted. This is missing coverage, not a stale pin.")
        return verdict
    if ran is None or pinned is None:
        verdict["state"] = "unknown"
        verdict["advice"] = (f"{name}: no test count could be read from the "
                             f"runner output; treat the gate as not run.")
        return verdict
    if ran == pinned and skipped == 0:
        verdict["state"] = "clean"
        verdict["advice"] = None
        return verdict
    if ran == pinned and skipped:
        # skipUnless on a class: the count is intact and the coverage is not.
        verdict["state"] = "skipped_in_place"
        verdict["advice"] = (
            f"{name} ran its pinned {pinned} but {skipped} were SKIPPED, so "
            f"the count proves nothing about coverage."
            + (f" Stage {precondition} and re-run." if precondition else ""))
        return verdict
    if ran < pinned:
        # setUpClass/SkipTest: the tests never entered the count at all.
        verdict["state"] = "shortfall"
        verdict["advice"] = (
            f"{name} ran {ran} against a pinned {pinned}: {pinned - ran} "
            f"test(s) did not run"
            + (f" and {skipped} skip(s) were reported" if skipped else "")
            + f". This is LOST COVERAGE, not a stale pin -- do not lower "
              f"EXPECTED_SUITE_COUNTS to match it."
            + (f" Stage {precondition} and re-run." if precondition else ""))
        return verdict
    verdict["state"] = "grew"
    verdict["advice"] = (
        f"{name} ran {ran} against a pinned {pinned}: {ran - pinned} test(s) "
        f"were added and the pin has not caught up. This one IS a stale pin; "
        f"update EXPECTED_SUITE_COUNTS['{name}'] in tools/audit.py after the "
        f"slate.")
    return verdict


def run_audited_suites(root: Path, test_env: Dict[str, str]) -> Dict[str, Any]:
    """Every audited suite in its own subprocess, counted against its own pin.

    One subprocess per suite rather than one for all five. It costs the extra
    interpreter startups and buys three things the combined run cannot give:
    a shortfall attributable to a named suite, a `skipped` count that belongs
    to something, and numbers an operator can reconcile by hand with the exact
    command the audit ran. It also isolates the suites that assert on process
    state (import graphs, module caches), which R59 showed can pass under a
    combined run purely because an earlier suite dirtied the interpreter.
    """
    errors: List[str] = []
    warnings: List[str] = []
    results: Dict[str, Any] = {}
    stdout_tail = ""
    stderr_tail = ""
    any_failed = False

    for name in AUDITED_SUITES:
        path = root / "tests" / f"{name.split('.')[-1]}.py"
        if not path.exists():
            results[name] = classify_suite(name, {"present": False, "ran": None})
            continue
        proc = subprocess.run(
            [sys.executable, "-m", "unittest", name],
            cwd=str(root), text=True, capture_output=True, env=test_env,
        )
        combined = proc.stdout + "\n" + proc.stderr
        rec = parse_unittest_report(combined)
        rec["present"] = True
        rec["returncode"] = proc.returncode
        rec["passed"] = proc.returncode == 0
        results[name] = classify_suite(name, rec)
        if proc.returncode != 0:
            any_failed = True
            stdout_tail = proc.stdout[-2000:]
            stderr_tail = proc.stderr[-4000:]

    runtime_count = sum(r["ran"] for r in results.values()
                        if isinstance(r.get("ran"), int))
    total_skipped = sum(r.get("skipped", 0) for r in results.values())
    count_ok = runtime_count == EXPECTED_TEST_COUNT
    suite_ok = not any_failed

    # Split, because CLAUDE.md tells the operator to proceed on one of these
    # and not the other: a count mismatch during a live slate is bookkeeping
    # that has not caught up, and a failing suite is not.
    if not suite_ok:
        failed = sorted(n for n, r in results.items()
                        if r.get("present", True) and not r.get("passed"))
        errors.append(f"test suite FAILED in {', '.join(failed)} "
                      f"(ran {runtime_count}); do not build")
    else:
        for name in AUDITED_SUITES:
            advice = results.get(name, {}).get("advice")
            if advice:
                warnings.append(advice)

    return {
        "passed": suite_ok and count_ok and not total_skipped,
        "suite_passed": suite_ok,
        "count_matches": count_ok,
        "suites": [n for n, r in results.items() if r.get("present", True)],
        "suite_results": results,
        "runtime_test_count": runtime_count,
        "expected_test_count": EXPECTED_TEST_COUNT,
        "skipped_total": total_skipped,
        "stdout_tail": stdout_tail,
        "stderr_tail": stderr_tail,
        "_errors": errors,
        "_warnings": warnings,
    }


# The full DEV write set. Ben's 2026-08-01 rule: EVERY change — code or
# otherwise, CLAUDE.md included — carries a CHANGELOG.md entry in the same
# commit, so both Ben and any later session know when it changed and why.
# The two inbox dirs are exempt: fragments are inputs addressed to an owning
# role, not shipped changes; the owning role's merge commit is the change.
CHANGELOG_TRACKED_PATHS = ("mlb_engine", "tools", "tests", "skills", "docs",
                           "CLAUDE.md")
CHANGELOG_EXEMPT_PATHSPECS = (":(exclude)docs/backlog_inbox",)


def changelog_debt(root: Path) -> Dict[str, Any]:
    """Commits that changed engine code since CHANGELOG.md was last written.

    CLAUDE.md says a DEV change is not shipped until the changelog carries its
    entry. A rule that only a document states is the failure class the 07-25
    review named: documented, unenforced, and quietly false within a week. This
    is the enforcing path that sentence cites.

    It is a WARNING and never an error. It is measured against committed
    history, so it surfaces the PREVIOUS session's omission at this session's
    start, which is the honest thing it can see. It cannot know whether the
    session now running intends to write its entry.

    Degrades to silence without git, outside a work tree, or on a repo with no
    CHANGELOG.md yet. An audit that fails because of its own bookkeeping is
    worse than one that stays quiet.
    """
    out: Dict[str, Any] = {"available": False, "unrecorded_commits": 0, "commits": []}
    if not (root / "CHANGELOG.md").exists():
        return out

    def _git(*args: str) -> Optional[str]:
        try:
            done = subprocess.run(("git", "-C", str(root)) + args,
                                  capture_output=True, text=True, timeout=15)
        except (OSError, subprocess.SubprocessError):
            return None
        return done.stdout.strip() if done.returncode == 0 else None

    last_changelog = _git("log", "-1", "--format=%H", "--", "CHANGELOG.md")
    if not last_changelog:
        return out
    listed = _git("log", "--format=%h %s", f"{last_changelog}..HEAD",
                  "--", *CHANGELOG_TRACKED_PATHS, *CHANGELOG_EXEMPT_PATHSPECS)
    if listed is None:
        return out
    commits = [line for line in listed.splitlines() if line.strip()]
    out["available"] = True
    out["unrecorded_commits"] = len(commits)
    out["commits"] = commits
    return out


def engine_module_count(root: Path) -> int:
    """Counted off disk, not off a hand-kept list.

    The pinned "13 modules" was printed against 20 on the filesystem, and the pin
    was bumped in the same commit that made it necessary, so it only ever
    confirmed what the last edit had done.
    """
    return sum(1 for p in (root / "mlb_engine").rglob("*.py")
               if p.name != "__init__.py" and "__pycache__" not in p.parts)


def terse_output(result: Dict[str, Any], root: Path) -> str:
    """The session-start line CLAUDE.md pins, plus whatever is abnormal.

    R62: the clean line is byte-identical to what CLAUDE.md quotes, on
    purpose. A gate that changes its own green output every release trains
    the operator to stop reading it, and CLAUDE.md's session-start step
    quotes this string exactly. Everything added here appears only when
    there is something to say -- a skip, a shortfall, a suite off its pin --
    and the per-suite breakdown is always in the JSON output.
    """
    test_check = result["checks"].get("tests") or {}
    test_count = test_check.get("runtime_test_count", "?")
    modules = engine_module_count(root)
    if not result["passed"]:
        return "FAIL  " + ";  ".join(result["errors"])
    line = f"PASS  {result['project_version']}  {modules} modules  {test_count} tests"
    skipped = test_check.get("skipped_total", 0)
    if skipped:
        line += f"  {skipped} skipped"
    off_pin = [r for r in (test_check.get("suite_results") or {}).values()
               if r.get("state") not in (None, "clean")]
    if off_pin:
        line += "  {" + "; ".join(
            f"{r['suite'].split('.')[-1]} {r.get('ran')}/{r.get('pinned')}"
            + (f" ({r['skipped']} skipped)" if r.get("skipped") else "")
            + f" {r.get('state')}" for r in off_pin) + "}"
    if result.get("warnings"):
        line += "  [" + "; ".join(result["warnings"][:2]) + "]"
    return line


def main() -> None:
    parser = argparse.ArgumentParser(description="MLB DFS engine audit (package layout)")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--run-tests", action="store_true", help="run the full suite and verify the count")
    parser.add_argument("--terse", action="store_true", help="one-line PASS/FAIL summary")
    parser.add_argument("--output", help="write full JSON result to this path")
    args = parser.parse_args()

    result = run_audit(Path(args.root), run_tests=args.run_tests)

    if args.terse:
        print(terse_output(result, Path(args.root)))
        raise SystemExit(0 if result["passed"] else 1)

    text = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    print(text)
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
