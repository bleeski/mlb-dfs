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
EXPECTED_TEST_COUNT = 619  # core 390 + showdown 49 + upload 115 + golden 9 + paste 56

EXPECTED_VERSION_TEXT = {
    "MLB_Classic.md": "v2.26.0",
    "mlb_engine/optimize/optimizer_v3.py": "OPTIMIZER_VERSION = 'v3.23'",
    "mlb_engine/allocate/contest_allocator.py": 'VERSION = "v1.11"',
    "mlb_engine/intake/slate_intake_manager.py": 'VERSION = "v1.10"',
    "mlb_engine/entries/dk_entries_manager.py": 'VERSION = "v1.6"',
    "mlb_engine/swap/late_swap_manager.py": 'VERSION = "v1.4"',
    "mlb_engine/pipeline/build_state_manager.py": 'VERSION = "v1.4"',
    "mlb_engine/pipeline/execution_pipeline.py": 'VERSION = "v1.15"',
    "mlb_engine/projections/projection_builder.py": 'VERSION = "v1.6"',
    "mlb_engine/projections/xwoba_base_correction.py": 'VERSION = "v1.2"',
    "mlb_engine/intake/live_data_adapters.py": 'VERSION = "v1.6"',
    "mlb_engine/optimize/tail_candidate_scanner.py": 'VERSION = "v1.0"',
    "mlb_engine/intake/platoon_order_adapter.py": 'VERSION = "v1.1"',
    "mlb_engine/optimize/bank_cache.py": 'VERSION = "v1.2"',
    "mlb_engine/determinism.py": 'VERSION = "v1.0"',
    "mlb_engine/contest_shapes.py": 'VERSION = "v1.0"',
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
    suites = [name for name in AUDITED_SUITES
              if (root / "tests" / f"{name.split('.')[-1]}.py").exists()]
    if run_tests and suites:
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
        proc = subprocess.run(
            [sys.executable, "-m", "unittest", *suites],
            cwd=str(root), text=True, capture_output=True, env=test_env,
        )
        combined = proc.stdout + "\n" + proc.stderr
        match = re.search(r"Ran\s+(\d+)\s+tests?", combined)
        runtime_count = int(match.group(1)) if match else None
        suite_ok = proc.returncode == 0
        count_ok = runtime_count == EXPECTED_TEST_COUNT
        test_result = {
            "passed": suite_ok and count_ok,
            "suite_passed": suite_ok,
            "count_matches": count_ok,
            "suites": suites,
            "returncode": proc.returncode,
            "runtime_test_count": runtime_count,
            "expected_test_count": EXPECTED_TEST_COUNT,
            "stdout_tail": proc.stdout[-2000:],
            "stderr_tail": proc.stderr[-4000:],
        }
        # Split, because CLAUDE.md tells the operator to proceed on one of these
        # and not the other: a count mismatch during a live slate is bookkeeping
        # that has not caught up, and a failing suite is not.
        if not suite_ok:
            errors.append(f"test suite FAILED (ran {runtime_count}); do not build")
        elif not count_ok:
            warnings.append(
                f"test count {runtime_count} != pinned {EXPECTED_TEST_COUNT}; the "
                f"suite passed, so this is a stale pin. Update EXPECTED_TEST_COUNT "
                f"in tools/audit.py after the slate.")
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
    test_check = result["checks"].get("tests") or {}
    test_count = test_check.get("runtime_test_count", "?")
    modules = engine_module_count(root)
    if result["passed"]:
        line = f"PASS  {result['project_version']}  {modules} modules  {test_count} tests"
        if result.get("warnings"):
            line += "  [" + "; ".join(result["warnings"][:2]) + "]"
        return line
    return "FAIL  " + ";  ".join(result["errors"])


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
