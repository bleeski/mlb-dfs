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
import hashlib
import importlib.util
import json
import py_compile
import re
import os
import subprocess
import sys
from datetime import datetime, timezone
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
    # R128, 2026-08-16: 653 -> 657, the four that pin the brief half of the
    # within/across split -- the mirrored-satellite shape reading zero waste,
    # a within-contest duplicate still reading as the finding, the brief
    # importing the preflight's one helper rather than restating the
    # partition, and the note refusing to present the two numbers as a total.
    # R142, 2026-08-17: 657 -> 667, the ten that pin the skill-cache drift
    # check -- an in-sync copy, Cowork's JSON re-quoting of the description
    # (which would otherwise report every installed skill drifted forever), a
    # stale body, a stale trigger description, the pointer body that differs by
    # design while its description is still compared, an uninstalled repo skill,
    # an unreachable cache reporting silent rather than clean, and the wiring
    # landing in warnings and never errors. Plus two on the install-length
    # limit, which is checked against the repo alone and so still reports where
    # the cache is invisible, and one of which asserts against the live tree.
    # R143, 2026-08-17: 667 -> 676, the nine that pin the lineup-source
    # ranking -- a complete DK 1-9 sourced and stamped confirmed, a partial
    # DK side falling through, the ranking applying PER SIDE, a same-side
    # disagreement resolving to DK and being NAMED, handedness kept from a
    # feed that has it and named absent when none does, probables staying
    # SP/P against PO and PLR, one shared definition of coverage, and the
    # whole point: a fully posted slate building with no feed at all.
    # R145, 2026-08-17: 676 -> 682, the six that pin git freshness -- a clean
    # clone, unpushed commits named as the push Ben owes, commits the clone
    # never pulled (the case that makes session start's `git log` a lie), the
    # default-branch trap including the two ways it is NOT a finding, a
    # branch with no upstream staying silent rather than reporting 0/0, and
    # the wiring landing in warnings and never errors. The seventh is the
    # non-numeric degrade, which VendoredPylibsTests found by patching
    # subprocess.run out from under it.
    # R146, 2026-08-17: 683 -> 687, the four that pin the credential path
    # -- a token only in .env being found (it was there and valid the
    # whole time while find_token read os.environ alone), an explicit
    # environ still winning over it, the staleness hedge dropping once a
    # fetch has made `behind` a measurement, and the one that cannot be
    # relaxed: the token reaching git through GIT_ASKPASS only, never
    # argv, a URL, .git/config, or any printed stream. A fifth pins the
    # fallback under `python tools/sync_check.py`: the first cut imported
    # mlb_engine without REPO on sys.path, so it worked when imported and
    # no-opped in the invocation the docstring documents.
    # R147, 2026-08-17: 688 -> 698, the ten that pin a CLASSIFIED remote
    # failure. Six on the classifier itself: a proxy refusing CONNECT reading
    # as network, a scope 403 sharing that message's prefix and still reading
    # as credential, unreachable and unresolvable hosts, a rejected
    # credential, an unreadable stream claiming neither cause, and a sweep of
    # both marker lists so a misfiled marker is caught before the day it
    # decides a real failure. One that the reason a classifier returns can
    # never carry the stream it read, since git's stderr can echo a URL. One
    # that both tools classify through the single function. One that a FAILED
    # fetch no longer resets fetch_age_hours, which is what kept R145's
    # stale-contact warning from ever firing. One that the reason reaches the
    # --terse line the session-start step actually reads.
    # R127, 2026-08-17: 698 -> 716, the eighteen that pin neutral-default
    # visibility. Nine on the engine's named list: the 2026-08-15 2138_2g
    # reproduction (an arm absent from the FanGraphs file named, with its
    # reason, rather than counted), the warning carrying the player and the
    # consequence, the falsifier where the same fixture with full coverage
    # names nobody, the list being THIS BUILD'S POOL rather than the salary
    # file's unmatched rows (the crosswalk reports over the whole salary file
    # and most of those arms are unrosterable), an absent input reporting one
    # fact with a count instead of a roster of names, matched-but-sub-floor
    # carrying its own reason, the same treatment on the hitter ceiling and the
    # Base correction, and two on the per-side split including the stale-id map
    # that must leave both sides dark. Nine on the brief: signal per side
    # rather than one boolean, the disagreement warning and its falsifier,
    # a missing split reporting None rather than guessing False, the named list
    # reaching the brief, the Projection_Mode distribution and its absent case,
    # and two on the reference warnings naming the factor they feed.
    # R126, 2026-08-17: 716 -> 743, the twenty-seven that pin the dual-objective
    # frontier. Ten on apex and washout themselves: the ceiling totals summed
    # off the run's own column, a mutation that moves one Ceiling and watches
    # the total move (the numbers are readable enough to hardwire), the named
    # best entry with a stable tie-break, the measurement being over ENTRIES
    # rather than distinct lineups, the counterfactual keeping the arms, the
    # histogram covering every entry, the 2138_2g reproduction where apex and
    # retained percent are IDENTICAL and only intact entries separate the two
    # builds, an untouched game not becoming a row, the ordering putting the
    # binding game first on a fixture whose worst game is alphabetically last,
    # and the material threshold counted at exactly three bats. Five on honest
    # degrade: a missing Ceiling column reporting one fact and no list (R127's
    # boundary), a missing game column keeping apex, an unpriced rostered
    # player NAMED rather than zeroed, nothing-to-measure saying so, and the
    # wrapper that cannot kill a run. Three on labels and the note, including
    # the cross-slate comparability limit the retained percent does not have.
    # Four on the wiring: three carriers of the block (both return paths plus
    # diagnostics.json), the brief carrying it INSIDE the exposure block, and
    # the review line stating both ends, degrading loudly, and flagging a
    # short total. Five on qa_portfolio reading the artifact's block instead of
    # shadowing it with a number computed off files that carry no Ceiling: the
    # block surfaced, an absent one named rather than fallen through, its own
    # axes labelled the independent check, a short apex flagged before it is
    # compared, and the 06-03 reconciliation (16/18 vs 18/18) stated in words.
    "tests.test_core": 743,
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
    # R129 + R36 F6m(1), 2026-08-16: 182 -> 207, the twenty-five that pin the way
    # back out of a supersession -- eight on CORRUPT being its own manifest state
    # (absent is not corrupt, the quarantine holds the exact bytes, a quarantine
    # that fails refuses instead of overwriting, verify_manifest stops passing),
    # eight on promote_run (the truthful appended row, the run's final/ left
    # untouched, run-scoped by default, and four refusals), and nine on matching a
    # row to a file now that one sha256 can carry several rows.
    # R128, 2026-08-16: 207 -> 218, the eleven that pin duplicate reporting
    # having contest context -- the 2026-08-15 2138_2g shape reading zero
    # within and nine across (plus the extra entry that proves the zero was
    # computed rather than hardwired, which the first cut of that test did not
    # catch), identical satellites sharing a NAME still counting as two
    # contests, within-contest duplication as the finding, three copies being
    # one group, the two numbers refusing to sum to the flat count, a
    # single-contest file, blank contest columns degrading to the old flat
    # reading, the printed T-5 block, verify_export inheriting the split
    # through the shared advisory(), the brief agreeing on one delivered file,
    # and the rationale for why this is a split and not a filter.
    "tests.test_upload_integrity": 218,
    "tests.test_golden_replay": 9,
    "tests.test_paste_lineups": 75,
}
# The sum, not a second number to keep in step: R70 left this comment reading
# 901 while the dict already summed to 928, which is the exact staleness this
# line's own rule warns about -- the dict is the source of truth either way.
EXPECTED_TEST_COUNT = sum(EXPECTED_SUITE_COUNTS.values())  # 1000

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
    "mlb_engine/pipeline/execution_pipeline.py": 'VERSION = "v1.17"',
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


def run_audit(root: Path, run_tests: bool = False,
              allow_fetch: bool = True) -> Dict[str, Any]:
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

    # Before the suite, deliberately. Both shell out, and VendoredPylibsTests
    # asserts on the LAST subprocess.run the audit made -- it is checking that
    # the suite subprocess inherited the vendored PYTHONPATH. Running git after
    # the suite made these calls the last ones and broke that test, which is
    # the test doing its job. Order is the fix; rewriting the older test to
    # accommodate a newer check would have retired a real assertion.
    fresh = git_freshness(root, allow_fetch=allow_fetch)
    checks["git_freshness"] = fresh

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

    if fresh["available"]:
        age = fresh["fetch_age_hours"]
        # Behind is the one that makes session start's `git log` read a lie, so
        # it leads. Ahead is Ben's push. A long-stale contact is said either
        # way, because it is what both numbers are worth.
        if fresh["behind"]:
            warnings.append(
                f"{fresh['behind']} commit(s) on {fresh['upstream']} are not in "
                f"this clone; `git log` at session start is missing them. Pull "
                f"before trusting it")
        if fresh["ahead"]:
            warnings.append(
                f"{fresh['ahead']} commit(s) on {fresh['branch']} are not on "
                f"{fresh['upstream']}; sessions commit and Ben pushes, so this "
                f"is a push Ben owes, and until then no clone can see them")
        # Only hedge when the fetch did NOT happen. After a successful fetch
        # `behind` is a measurement and saying it might be stale would be
        # false caution, which trains the reader to discount the real warnings.
        if not fresh["fetched"] and age is not None and age > 24 \
                and not fresh["behind"]:
            warnings.append(
                f"last contact with the remote was {age}h ago and this run "
                f"could not fetch ({fresh['fetch_reason']}), so 'behind: 0' is "
                f"only as current as that")
        if fresh["default_branch_mismatch"]:
            warnings.append(
                f"origin/HEAD is {fresh['default_branch_mismatch']} but the "
                f"work is on {fresh['branch']}; a fresh clone lands on that "
                f"default and gets its tree")

    drift = skill_cache_drift(root)
    checks["skill_cache"] = drift
    if drift["oversized"]:
        named = "; ".join(f"{d['skill']} {d['chars']}>{d['limit']}"
                          for d in drift["oversized"])
        warnings.append(
            f"skill description too long to install as written: {named}. It "
            f"gets shortened by hand at install time, which is permanent drift")
    if drift["available"] and drift["drifted"]:
        named = "; ".join(f"{d['skill']} ({', '.join(d['reasons'])})"
                          for d in drift["drifted"])
        warnings.append(
            f"installed skill snapshot behind the repo: {named}. Re-save with "
            f"save_skill(overwrite=True) from skills/<name>/SKILL.md")

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


# R142. Cowork installs a skill as a SNAPSHOT of its SKILL.md, not a live read
# of the repo, and nothing warns when the two diverge. Measured 2026-08-16: the
# installed `generate-lineups` was 85 commits and 351 lines behind the repo,
# missing the autobuild path, the paste intake, the preflight exit codes and the
# Showdown thesis ladder, and its trigger still called Showdown certified.
#
# The installed BODY is now a pointer at the repo file (see the sentinel below),
# so a body diff is expected there and is not drift. What a pointer cannot carry
# is the TRIGGER DESCRIPTION: that lives in the save_skill argument, is what
# routes a prompt to the skill at all, and is invisible to a session that only
# reads the repo. So the description is compared always, the body only for a
# cached copy that still claims to be a full copy.
POINTER_SENTINEL = "skill-cache: pointer"
SKILL_CACHE_ENV = "MLB_SKILL_CACHE_DIR"
# Cowork refuses a description past this, so a repo skill written longer than it
# CANNOT be installed as written and someone shortens it by hand at install
# time. That is drift the moment it is created and it never converges: found
# 2026-08-17 on mlb-standings-pull-checklist at 1073 characters, which is why
# this is checked at the source instead of only reported downstream.
SKILL_DESCRIPTION_LIMIT = 1024


def _skill_frontmatter(text: str) -> Dict[str, str]:
    """name/description out of a SKILL.md, tolerating both quoting styles.

    The repo writes `description: Build a ...` bare; Cowork rewrites it
    `description: "Build a ..."` with JSON escaping. Comparing the raw lines
    reports drift on every skill forever, which is worse than not checking.
    """
    out: Dict[str, str] = {}
    if not text.startswith("---"):
        return out
    end = text.find("\n---", 3)
    if end == -1:
        return out
    for line in text[3:end].splitlines():
        if ":" not in line or line.startswith((" ", "\t", "#")):
            continue
        key, _, value = line.partition(":")
        value = value.strip()
        if len(value) > 1 and value[0] == '"' and value[-1] == '"':
            try:
                value = json.loads(value)
            except ValueError:
                value = value[1:-1]
        out[key.strip()] = value
    return out


def _skill_body(text: str) -> str:
    if not text.startswith("---"):
        return text
    end = text.find("\n---", 3)
    return text if end == -1 else text[end + 4:].lstrip("\n")


def skill_cache_dir(root: Path) -> Optional[Path]:
    """The installed-skill cache, or None when it is not reachable.

    In a Cowork sandbox the mount holds the repo and `.claude/skills/` as
    siblings. From Ben's own PowerShell the cache lives under an AppData path
    keyed by session GUIDs and is not derivable from the repo, so the check
    goes quiet rather than guessing at a path or reporting a false clean.
    """
    override = os.environ.get(SKILL_CACHE_ENV)
    if override:
        path = Path(override)
        return path if path.is_dir() else None
    # resolve() first: run_audit is called with a relative root in tests and by
    # hand, and Path('.').parent is Path('.'), which silently looks like "no
    # cache" instead of looking one level up from the repo.
    candidate = root.resolve().parent / ".claude" / "skills"
    return candidate if candidate.is_dir() else None


def skill_cache_drift(root: Path) -> Dict[str, Any]:
    """Installed skill snapshots that no longer match the repo they came from.

    WARNING only, and silent when it cannot see the cache. Modeled on
    changelog_debt: an audit that fails on its own bookkeeping is worse than one
    that stays quiet. Reports per skill so the message names what to re-save.
    """
    out: Dict[str, Any] = {"available": False, "checked": 0, "drifted": [],
                           "oversized": []}
    # The length check reads only the repo, so it runs even where the cache is
    # unreachable: a description too long to install is a defect in the repo.
    for repo_skill in sorted((root / "skills").glob("*/SKILL.md")):
        try:
            desc = _skill_frontmatter(
                repo_skill.read_text(encoding="utf-8")).get("description", "")
        except OSError:
            continue
        if len(desc) > SKILL_DESCRIPTION_LIMIT:
            out["oversized"].append({"skill": repo_skill.parent.name,
                                     "chars": len(desc),
                                     "limit": SKILL_DESCRIPTION_LIMIT})

    cache = skill_cache_dir(root)
    if cache is None:
        return out
    out["available"] = True
    out["cache_dir"] = str(cache)

    for repo_skill in sorted((root / "skills").glob("*/SKILL.md")):
        name = repo_skill.parent.name
        cached = cache / name / "SKILL.md"
        if not cached.is_file():
            continue  # not installed; not this check's business
        try:
            cached_text = cached.read_text(encoding="utf-8")
            repo_text = repo_skill.read_text(encoding="utf-8")
        except OSError:
            continue
        out["checked"] += 1

        reasons: List[str] = []
        cached_desc = _skill_frontmatter(cached_text).get("description", "")
        repo_desc = _skill_frontmatter(repo_text).get("description", "")
        if cached_desc != repo_desc:
            reasons.append("trigger description")

        cached_body = _skill_body(cached_text)
        if POINTER_SENTINEL not in cached_body:
            digest = lambda s: hashlib.sha256(  # noqa: E731
                s.strip().encode("utf-8")).hexdigest()
            if digest(cached_body) != digest(_skill_body(repo_text)):
                reasons.append("body")
        if reasons:
            out["drifted"].append({"skill": name, "reasons": reasons})
    return out


# R145. CLAUDE.md's session start reads `git log` to learn what moved. That
# read is only as current as the clone, and a stale `git log` looks EXACTLY like
# a current one: there is no "you are twelve days behind" line in its output.
# Nothing here can fetch -- this sandbox has no credential for a private repo
# and `git fetch` dies on "could not read Username" -- so the honest move is not
# to guarantee freshness but to make the uncertainty visible. Three facts, all
# readable offline, all warnings.
def _try_git_fetch(root: Path, timeout: int = 20) -> Dict[str, Any]:
    """Update the remote-tracking refs, if a credential is reachable.

    R146. Without this, ``behind`` is measured against a ref that moves only
    when Ben pushes, so a clone reports ``behind: 0`` when it means "I cannot
    know". With it, ``behind`` is a measurement.

    The token is passed to git through GIT_ASKPASS and an env var and NEVER
    lands in argv, in ``.git/config``, in a remote URL, or in any output --
    same discipline as tools/sync_check.py, and the reason a token-in-the-URL
    remote is not used. Bounded and non-fatal: a build at T-20 must not hang or
    die on a network call, so a failure here is reported as "not fetched" and
    the stale-ref reading is used, honestly labelled.
    """
    out: Dict[str, Any] = {"fetched": False, "reason": None}
    try:
        sys.path.insert(0, str(root / "tools"))
        from sync_check import classify_git_failure, find_token  # type: ignore
    except Exception:
        out["reason"] = "sync_check unavailable"
        return out
    try:
        name, token = find_token()
    except Exception:
        name, token = None, None
    if not token:
        out["reason"] = "no credential in env or .env"
        return out

    askpass = root / ".git" / "audit_askpass"
    try:
        askpass.write_text(
            '#!/bin/sh\ncase "$1" in *[Uu]sername*) echo x-access-token;; '
            '*) echo "$AUDIT_GIT_TOKEN";; esac\n', encoding="utf-8")
        askpass.chmod(0o700)
        env = dict(os.environ)
        env.update({"AUDIT_GIT_TOKEN": token, "GIT_ASKPASS": str(askpass),
                    "GIT_TERMINAL_PROMPT": "0"})
        done = subprocess.run(["git", "fetch", "--quiet", "origin"],
                              cwd=str(root), capture_output=True, text=True,
                              timeout=timeout, env=env)
        if done.returncode == 0:
            out.update(fetched=True, credential=name)
        else:
            # stderr can echo a URL; never surface it, and never the token.
            # R147: it is CLASSIFIED instead. This line read "check the token
            # scope or expiry" for every failure, so a sandbox with no network
            # at all blamed a PAT that was present, in scope and working.
            out["reason"] = "fetch failed: " + classify_git_failure(done.stderr)
    except subprocess.TimeoutExpired:
        out["reason"] = f"fetch exceeded {timeout}s"
    except (OSError, subprocess.SubprocessError):
        out["reason"] = "fetch could not run"
    return out


def git_freshness(root: Path, allow_fetch: bool = True) -> Dict[str, Any]:
    """How far the clone is from the last remote state it actually saw.

    ``ahead`` needs a push (Ben's action, per docs/cowork_sync_protocol.md);
    ``behind`` needs a pull (the session's). ``fetch_age_hours`` is what both
    numbers are worth: measured against the remote-tracking ref, which moves
    only on fetch or push, so a long-stale fetch means ``behind: 0`` proves
    nothing. ``default_branch_mismatch`` catches the trap that a fresh clone
    lands on ``origin/HEAD`` -- still ``master`` here, stale since 2026-08-04.

    Silent without git, without a remote, or on a branch with no upstream.
    """
    out: Dict[str, Any] = {"available": False, "ahead": 0, "behind": 0,
                           "fetch_age_hours": None, "branch": None,
                           "default_branch_mismatch": None,
                           "fetched": False, "fetch_reason": None}
    if allow_fetch:
        attempt = _try_git_fetch(root)
        out["fetched"] = attempt["fetched"]
        out["fetch_reason"] = attempt["reason"]

    def _git(*args: str) -> Optional[str]:
        try:
            done = subprocess.run(("git", "-C", str(root)) + args,
                                  capture_output=True, text=True, timeout=15)
        except (OSError, subprocess.SubprocessError):
            return None
        return done.stdout.strip() if done.returncode == 0 else None

    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    if not branch or branch == "HEAD":
        return out
    out["branch"] = branch
    upstream = _git("rev-parse", "--abbrev-ref", f"{branch}@{{upstream}}")
    if not upstream:
        return out
    ahead = _git("rev-list", "--count", f"{upstream}..{branch}")
    behind = _git("rev-list", "--count", f"{branch}..{upstream}")
    # Anything that is not a bare count means this was not git answering --
    # a patched subprocess.run in a test, a wrapper on PATH, a git that
    # printed advice. Degrade to silent; an audit that raises on its own
    # bookkeeping is worse than one that says nothing, and `available: False`
    # already means "not measured" rather than "clean".
    if not (ahead or "").strip().isdigit() or not (behind or "").strip().isdigit():
        return out
    out.update(available=True, upstream=upstream,
               ahead=int(ahead.strip()), behind=int(behind.strip()))

    # The remote-tracking ref moves on fetch OR push, and .git/FETCH_HEAD is
    # touched by fetch alone. Either one is evidence of contact; take the newer.
    #
    # R147: a FAILED fetch touches FETCH_HEAD too, and truncates it to zero
    # bytes. So R146's fetch attempt was resetting fetch_age_hours to 0.0 on
    # every failure, and the one number R145 built to say what `behind: 0` is
    # WORTH was itself reporting contact that never happened -- which also kept
    # the stale-contact warning below (age > 24) from ever firing on a clone
    # that cannot reach the remote at all. A zero-byte FETCH_HEAD is not
    # contact: a fetch that reaches the remote writes a line per ref even when
    # everything is already up to date.
    newest = 0.0
    for rel in ("FETCH_HEAD", f"refs/remotes/{upstream}"):
        path = root / ".git" / rel
        try:
            stat_result = path.stat()
        except OSError:
            continue
        if rel == "FETCH_HEAD" and stat_result.st_size == 0:
            continue
        newest = max(newest, stat_result.st_mtime)
    if newest:
        out["fetch_age_hours"] = round(
            (datetime.now(timezone.utc).timestamp() - newest) / 3600.0, 1)

    head_ref = _git("rev-parse", "--abbrev-ref", "origin/HEAD")
    # An origin/HEAD that is not a proper symbolic ref abbreviates to the
    # literal "origin/HEAD", whose tail is "HEAD" and matches no branch name.
    # Reporting that as a mismatch would warn on every clone that simply never
    # had one set, which is noise, not a finding.
    if head_ref in (None, "", "origin/HEAD", "HEAD"):
        head_ref = None
    if head_ref and head_ref.split("/")[-1] != branch:
        # Not an error: it is legitimate to work off the default branch. It IS
        # worth saying, because a fresh clone lands on origin/HEAD and gets that
        # branch's tree, which here is weeks behind the branch the work is on.
        out["default_branch_mismatch"] = head_ref
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
    parser.add_argument("--no-fetch", action="store_true",
                        help="skip the git fetch that makes 'behind' a "
                             "measurement; the stale-ref reading is used and "
                             "labelled as such")
    args = parser.parse_args()

    result = run_audit(Path(args.root), run_tests=args.run_tests,
                       allow_fetch=not args.no_fetch)

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
