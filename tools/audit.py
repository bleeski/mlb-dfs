"""MLB DFS engine audit v3.0 (package layout).

Ported from project_audit.py v2.2 at the Cowork migration. Kept:
version-coherence, CSV schema, venue-factor join, compile, scipy.milp,
and the full-suite run with an expected test count. Retired: the SHA-256
checksum manifest, the manifest txt, and the 26-file cap. Git history is
provenance now; the retired originals live in docs/legacy/.
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import hashlib
import importlib.util
import io
import json
import py_compile
import re
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# R358, 2026-09-19. The two gate constants below were host-derived numbers
# wearing the shape of universal defaults; they resolve per host now, the way
# `tools/solver_probe.py:72` already does. `repo_env` is stdlib-only, so this
# import cannot fail for want of a dependency, and it is deliberately NOT
# guarded: a silent fallback here would reproduce the defect this file's own
# R147 comment records against `sync_check.py`, where a guarded import without
# the repo root on sys.path "worked when imported and no-opped in the
# invocation the docstring documents". `python tools/audit.py` puts `tools/`
# on sys.path, not the repo root, which is why the append is needed at all.
sys.path.append(str(Path(__file__).resolve().parents[1]))

from mlb_engine.repo_env import call_budget_s, call_budget_source  # noqa: E402

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
                  "tests.test_paste_lineups",
                  # R180(e), landed by R338 step 5. The thirteenth edition
                  # arrived with two suites this gate could not see, and one of
                  # them is the suite that pins R338's own four repairs. A gate
                  # blind to the tests that prove the change it is gating is the
                  # defect R62 is filed on, arriving through a new runner.
                  "tests.test_greenfield_regressions",
                  "tests.test_production")

# The suites above that pytest runs and `python -m unittest` cannot. Both use
# bare `assert` and pytest fixtures (`tmp_path`, `monkeypatch`), so unittest
# collects ZERO tests from them and reports `Ran 0 tests` -- an empty pass,
# which is the one shape a gate must never produce. They are run as ONE unit
# each rather than chunked by class: the split gate exists because
# `tests.test_core` needs ~89s and cannot fit a call, while these two need 0.8s
# and 5.8s measured under the pinned stack, so per-class chunking would buy
# nothing and add a second enumeration path to keep honest.
PYTEST_SUITES = frozenset({"tests.test_greenfield_regressions",
                           "tests.test_production"})

# R348. pytest's `tmp_path` / `tmp_path_factory` fixtures are rooted at
# `<system temp>/pytest-of-<user>`, and that directory is OUTSIDE this repo, is
# not this project's to create, and can be left behind by any process on the
# host. On Ben's machine one was, on 2026-09-09, owned by a principal `benja`
# cannot read: `mktemp` raised `PermissionError: [WinError 5]` at session-scoped
# fixture setup and all 131 tests in the two PYTEST_SUITES errored out. The gate
# then printed `FAIL test suite FAILED in tests.test_greenfield_regressions,
# tests.test_production (ran 2066)` -- a verdict that is correct about the gate
# and wrong about the tree, and which sends the next session hunting a code
# defect that does not exist. Both halves matter: the suites must RUN (so the
# gate is usable at all) and the redirect must be SAID (so a broken host does
# not hide behind a green line forever).
PYTEST_TEMPROOT_ENV = "PYTEST_DEBUG_TEMPROOT"
#: Short on purpose. The redirected root is a PREFIX of every `tmp_path` a test
#: builds under, and Windows still refuses a path past 260 characters: a first
#: attempt at this fix rooted the redirect under a session scratchpad 120
#: characters deep and turned the PermissionError into a FileNotFoundError on
#: `.manifest.json.<uuid>.tmp` -- a different failure that reads like a real
#: one. Anything added here is paid for by every test that writes a file.
PYTEST_TEMPROOT_PREFIX = "mlbgate_"

#: Throwaway roots ``suite_subprocess_env`` minted IN THIS PROCESS, normalised.
#:
#: R348 rider, and the defect it closes is older than R348. Both throwaway roots
#: reach a child through the ENVIRONMENT, so a child that calls
#: ``suite_subprocess_env`` inherits the parent's values rather than minting its
#: own -- and a prefix test alone cannot tell "the root I made" from "the root
#: my parent made", because they carry the same prefix by construction.
#: ``tests/test_core.py::test_run_tests_subprocess_gets_the_vendored_pythonpath``
#: is exactly that child: it calls ``run_audit(root, run_tests=True)`` IN
#: PROCESS, so since R338 repair (4) landed it has been deleting the outer
#: gate's ``MLB_DFS_ARTIFACT_ROOT`` on every ``--run-tests`` run. That went
#: unseen because ``run_audited_suites`` re-``mkdir``s a per-suite subdirectory
#: each iteration, so the isolation survived by accident; pytest's temp root has
#: no such luck, and the same deletion errored all 131 tests in the two
#: PYTEST_SUITES. The registry is the fix for both: this process deletes what
#: this process made, and nothing else.
_MINTED_ROOTS: set = set()


def _register_minted_root(path: Any) -> str:
    """Record a throwaway root this process just made, normalised for lookup."""
    key = os.path.normcase(os.path.abspath(str(path)))
    _MINTED_ROOTS.add(key)
    return key

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
    # R135 + R151, 2026-08-17: 743 -> 762, the nineteen that pin the
    # predict-then-grade loop and the name fold under it. One is R151's, on the
    # DK/feed merge: an accented feed name now matches DK's plain-ASCII spelling,
    # so the disagreement list stops reporting seven false positives on a real
    # slate and the merged row stops dropping the feed's MLBAM id and bat_side
    # (both F4 terms, R117's defect on the merge surface). Eighteen are R135's.
    # Six on the emitter: the name crosswalk the grade joins through, an absent
    # odds file named INERT with no per-player list against a partially priced
    # slate named per team (R127's boundary in both directions), side counts
    # intersected with the salary file's teams, DK-posted sides attributed to DK
    # per R143, and the roster budget accounting reported per archetype. Two on
    # determinism and the slate date coming off Game Info rather than the clock.
    # Six on the grade: per-feature buckets rather than one number, both
    # baselines with flat-12 labelled the easy one, an unmatched actual name
    # listed rather than counted, an archetype the prediction does not carry
    # refused, actuals taken from the ONE aggregation mine_contest uses on a
    # multi-slot fixture, and a blank %Drafted cell creating no key. Two on the
    # crosswalk keying on field_miner's normalizer and not the intake's, which
    # disagree on an apostrophe. One on labels, one on R107(a)'s tracked-and-
    # pinned discipline. Thirteen hand-run mutations, all thirteen caught.
    # R136, 2026-08-18: 762 -> 781, the nineteen that pin the field-facing
    # leverage panel -- three on the shape-to-archetype projection (it covers
    # the closed vocabulary exactly, a COLLAPSED projection is labelled one,
    # and an unknown shape is None rather than the default), one that checks
    # the field-mean identity against an explicit field built the long way,
    # five on conditioning (each contest reads its own archetype and the
    # fixture's archetypes carry different shares so the LABEL cannot pass for
    # the DATA, an unresolved shape reports instead of defaulting, an absent
    # archetype names what the file does carry, and R127's boundary in both
    # directions), five on the named traps (an INERT implied total, a prior
    # that priced a different salary file, the carry column counting a rank
    # because the absolute bar is inert on this prior, the read-once prose,
    # and the cross-contest comparison), three on Showdown (captain rank but
    # no Classic chalk-sum, salary left reading CPT/UTIL, an unpriced entry
    # excluded rather than guessed), and two on resolving the prediction file.
    # R117(b), 2026-08-18: 781 -> 792, the eleven that pin an inert factor
    # being nameable -- four on a NAMED opposing probable that cannot feed F4
    # (the complete case stays silent, a missing hand is one warning against the
    # OPPOSING side naming the term it kills, the twenty-arm 1910_10g shape is
    # still one warning, and reporting never filters the pool), and seven on the
    # classification (a factor that moved a row is not inert, one that moved
    # none is, one that scored NOTHING is absent rather than inert, the row
    # count comes off the emitted map because the three factors disagree on what
    # they call it, all three sort, the review line says a neutral factor ranked
    # nothing, and `factors_inert` sits BESIDE the gates while the gates dict
    # keeps exactly its three certification keys).
    # R148(a) + R152, 2026-08-18: 792 -> 809. Five are R148(a)'s, on a check
    # that could not fail: the default branch read from the REMOTE and not the
    # clone's cached origin/HEAD (the falsifier is the shape that hid it -- the
    # cache agreeing with the checked-out branch while the remote's default is
    # elsewhere), an unreadable default carrying R147's classified reason
    # instead of a null that reads as agreement, the reason never carrying
    # git's own stream, a no-network fetch not paying for a second remote call
    # while a rejected credential still does, and --no-fetch saying so.
    # Twelve are R152's, on the gate assembled across several calls: a partial
    # assembly never printing the clean line and a complete one printing it
    # byte-identically, completeness read as CLASS COVERAGE rather than a
    # matching count (both directions, including a class covered by its own
    # methods), units from another tree refused AND kept out of the numbers,
    # an age limit, a unit that never finishes named and then refused, the
    # content fingerprint ignoring bytecode and scratch, one summariser behind
    # both paths, the state words surviving the split, and the child recording
    # each unit as it lands so a killed call loses only the one in flight, and
    # a breadcrumb answered by covering its class rather than reported forever.
    # Eighteen hand-run mutations, all eighteen caught -- one of them only
    # after the FIXTURE was strengthened: pinning the stale-tree refusal alone
    # let a mutation that merged foreign records into the totals survive, since
    # the refusal fires off a separate list and never reads the counts.
    # R154, 2026-08-19: 809 -> 821, the twelve that pin leverage as two LINEAR
    # CONSTRAINTS rather than an objective term -- both controls default OFF and
    # reproduce the pre-R154 solve, the cumulative-ownership cap binding and
    # costing ceiling (a cap that costs nothing did not bind), a tighter cap
    # buying more leverage for more ceiling, the low-owned floor delivering what
    # it asks at 2/4/6/8, the floor counting BATS and never a cheap arm (DK slots
    # are P1/P2 and the obvious `slot != 'P'` filter is true for both, which
    # shipped 2 bats against a floor of 4 with every counter clean -- caught in
    # bring-up), a floor above the eight hitter slots refusing, an unreachable
    # THRESHOLD named apart from a generic infeasibility, determinism, and three
    # on the attach half: one column written and never Ownership_Tier, an
    # undecided contest shape refused rather than defaulted, and an existing
    # column left alone.
    # R190(a), 2026-08-23: 821 -> 825, the four that pin the bundle's `/people`
    # call filling BOTH halves of F4's platoon input. The schedule hydrate does
    # not return `pitchHand`, so every probable left `fetch_lineups_feed` with
    # `hand: None` -- 30 of 30 measured on 08-18 and again on 08-19 -- while
    # `bat_side` sat populated on all 270 hitters, and the only place the dead
    # term showed was `f4_platoon_applied: 0` beside `signal_applied: true`.
    # Both probables resolving, the hitter half surviving in ONE request (a
    # second call would mean a bolted-on fetch rather than a widened one), and
    # a hand that still cannot resolve being NAMED in both directions -- no id
    # to join on, and /people answering without pitchHand, which is the case a
    # helpful fixture hides. Three hand-run mutations, all three caught.
    # R159+R160+R189(2), 2026-08-23: 825 -> 841, the sixteen that pin the
    # intake-truth batch. Eleven on the degraded side (the reading that tells
    # confirmed from degraded, coverage and the merge finally answering the
    # same question, the surviving eight seeded as a PARTIAL on both the
    # in-feed and the synthesize branch, a complete source still outranking
    # eight-of-nine, the probable reaching a degraded team and a team with no
    # order at all, a shelved arm never becoming a probable, the merged
    # probable carrying a NAME, partial handedness named with its count, and
    # the pool seeding the eight while the shelved bat stays out). Three on the
    # unparseable game time (not synthesized and says why, the status map
    # surviving two malformed feed games, and the pool blocking on the CAUSE
    # rather than on "no probable"). Two on F4's id-less probable (named with
    # its reason instead of a silent 1.0, and the Savant name join recovering
    # it). Nineteen hand-run mutations, all nineteen caught -- two only after
    # the eleventh test was added, because every fixture until then handed the
    # merge an EMPTY feed and the in-feed branch was never executed at all.
    # R167+R168+R169, 2026-08-24: 841 -> 863, the lost-window batch's
    # twenty-two. Nine on the units rule now living in ONE place (five on the
    # rule itself including 1.0 staying legal and 0 not being a slip, four on
    # the override being the only surface validated and count controls being
    # left alone) plus the closure inside _feasibility_report, which no
    # assertion could reach without calling the report; three on build_slate's
    # zero-cost operator gate and its key set covering both contest types;
    # three on the exit contract as PROPERTIES (no tuple return in main(), no
    # unguarded fetch_lineups in main()) rather than as the two instances found;
    # seven on autobuild, which had none at all, driving main() with a patched
    # subprocess so the timeout, the log's date precedence, the control
    # allowlist and the passthrough order are each reached by a fixture.
    # R235, 2026-08-25: 863 -> 876, the thirteen that pin the Showdown role
    # collapse. Seven on the collapse itself (the shape guard's two clauses
    # each caught by their own file, the UTIL row being the one that survives,
    # the posted nine surviving into `dk_side_readings` as confirmed, the R75
    # ambiguity NOT being swallowed by the person key, and the key's shape);
    # four at the tool boundary (people counted rather than salary rows, the
    # crosswalk, the batting-order feature, and the contest type read off the
    # miner instead of re-derived); two on the leverage panel's captain tier,
    # which now joins a CPT id to the person and still reads a pre-R235 file.
    # R219+R220, 2026-08-27: 876 -> 884, the eight that pin the degraded-side
    # merge and its report. Five on R219 (DK's eight beating a three-hitter
    # mid-repost partial, a COMPLETE feed nine still winning and being NAMED as
    # a deferral, completeness being the order SET rather than a row count plus
    # the confirmed clause an order-less producer relies on, an operator paste
    # keeping R32's precedence at any length, and the pool warning reading the
    # resolution instead of asserting a seeding); three on R220 (all nine
    # shelved seeding nothing and firing no handedness note -- on BOTH routes,
    # since the in-feed one is where the guard lives and mutation found the
    # empty-feed fixture never reaching it; one timeless game emitting one
    # blocker rather than one per side; and a postponed timeless game being
    # excluded rather than blocked, with the off-slate blocker scope and its
    # positive control riding the last one).
    # R212, 2026-08-28: 884 -> 887, the three that pin every exit from
    # autobuild.main() flushing its decision log -- the wall-clock stop with
    # `time.monotonic` patched past the deadline, the classification-drift stop
    # (the tenth exit, which returned before `dec` existed and which the
    # backlog entry did not enumerate), and the AST property that every return
    # in main() sits immediately after a `_write`, so the next exit door added
    # fails here rather than in a post-mortem that was never written.
    # R213, 2026-08-28: 887 -> 891, the four that pin build_slate's two lineups
    # reads. Two on the supplied feed refusing at exit 4 with the path and the
    # parse error (a missing path and a torn one, since FileNotFoundError and
    # JSONDecodeError are different operator mistakes); one on a torn staged
    # cache being ABSENT and falling through to the guarded fetch leg; one
    # positive control that a readable cache is still used, without which
    # discarding every cache passes the test above. R168(b)'s AST test was
    # widened in place from `fetch_lineups` to the call SHAPE, so it now covers
    # `read_text` too and its name changed with its scope.
    # R214, 2026-08-28: 891 -> 895, the four that pin the controls merge. The
    # defect itself (a structural floor no longer erases the operator's
    # passthrough override, across attempts, with all three fields in the log
    # and at its top level); the other half, that a supervisor-owned key still
    # overwrites the operator's value, without which "merge" becomes "the
    # operator wins"; the four loud refusals (duplicate, non-JSON, non-object,
    # no value); and the `--flag=value` spelling, which argparse accepts and
    # which would otherwise arrive as a second occurrence. R169(d)'s own test
    # was rewritten in place, not added: both its halves still hold, and the
    # second is now enforced by merging rather than by ordering.
    # R215, 2026-08-28: 895 -> 902, the seven that close R167's units family.
    # Five in UnitsRuleRemainingMembersTests: NaN/inf rejected at the rule
    # (every comparison against NaN is False, so it cleared `> 1.0` and died
    # inside math.floor after the bank spent), bool rejected before the float()
    # with 1.0 and 0 kept legal as its positive control, the merge storing the
    # COERCED value, the sixth control validated per game id and its non-dict
    # spelling named, and a legal by-game dict surviving coerced (without which
    # rejecting every one of them passes the test above). Two on build_slate's
    # zero-cost gate, the only boundary Showdown reaches: the dict-valued key
    # plus the two quiet slips each naming its own problem, and the gate
    # coercing IN PLACE rather than testing a copy, read off the args
    # `run_classic` receives.
    # R205, 2026-08-28: 902 -> 911, the nine that pin cross-book consensus in
    # probability space -- the ATL@MIN straddle that filed it (with the old
    # rule's -2.0 stated so the bug stays legible), the consensus already being
    # vig-free so every consumer's second de-vig is identity, one book being its
    # own de-vigged consensus rather than its posted price, a one-sided book
    # named and excluded, a game no book priced two ways named rather than
    # invented, a NaN/inf/zero price excluded by name (R215's discipline on this
    # surface), book order not moving the answer, and the price/probability
    # round trip -- plus the one member of the class that survives on purpose,
    # the total's cross-book median, which is linear and says so.
    # R37(2)(a)+(b) + R263, 2026-08-28: 911 -> 934, the twenty-three that pin
    # Ben's two live shape bands and the quota ladder that replaced R34's hard
    # fail. Twelve on the routing (the ledger's own slate buckets, breadth <= 0.02
    # selecting EXACTLY the postures the item names by list, floor 5 binding only
    # under R34's unanimity rule so a mixed portfolio falls back to 4, the 1-2g
    # exemption that is the tranche's own counter-case, the quota reading the field
    # share monotonically and clamping to Ben's band, the share naming WHICH source
    # answered and surviving a torn rollup, the band adding the quota to postures
    # that never declared it -- load-bearing, since the mid band's whole population
    # is served by large_gpp and small_gpp -- the band never lowering a control an
    # operator set, and the R167 units gate still catching a slipped quota).
    # One is the defect a check found rather than reasoning: an UNMEASURABLE slate
    # size is a third state and is not "3g or more", and `late_swap` running
    # without a projection frame reached exactly it and printed floor 5.
    # Ten on the ladder (the rungs, an empty qualifying set relaxing OFF in ONE
    # counted step rather than refusing the delivery, a carryable quota clean, a
    # REUSE-DEPENDENT quota named and NOT relaxed -- the case R34 had no diagnostic
    # for at all, where the row is satisfiable only through candidate reuse and a
    # bare infeasibility used to arrive with no control attached to it -- absent
    # not being the same fact as relaxed, a share that floors to zero entries
    # reporting off rather than adding a vacuous row, and the quota stepping BEFORE
    # the primary-stack floor because the floor has three tranches behind it and
    # the quota is one dated decision old).
    # The last one is R116's rule generalized to a third ladder and it is where
    # this batch's own R233 moment landed: every re-entry must carry every sibling
    # ladder state. Its first cut counted the substring over the rest of the file,
    # found four calls, and flagged the fourth -- which is `allocate_entries`'
    # top-level entry into the allocator, where a private ladder kwarg would be a
    # defect and not a fix. Scoped by AST now. The class had one more member than
    # the enumeration and the test is what said so.
    # R277, 2026-08-31: 934 -> 939, the five that pin membership by FILTER as a
    # condition separate from age -- the filter warning firing on a file pulled
    # this morning (where the old code said nothing at all), the export URL
    # riding only the age condition it can actually remedy, deleting the
    # SOURCE_MEMBERSHIP_FILTER entry being what silences the warning, and
    # REQUIRED_COLUMNS finally enforced on the one file nothing fetches
    # (a good header, a missing K/9, and a non-empty file whose header cannot be
    # read at all, which is the branch a bad hand-placed download arrives on).
    # R278, 2026-08-31: 939 -> 945, the six that pin the K-rate source swap --
    # both membership tables EMPTY at this head (a claim, not an absence: the
    # qual=y entry left with the file it described), baseball innings notation
    # resolved to thirds at the emit boundary rather than carried as a float
    # that is wrong in one direction, playerPool=All carrying no filter to get
    # wrong, a truncated pagination REFUSING rather than writing a narrower
    # league, the offset loop deduping a player repeated across a page boundary,
    # and a 0 IP row leaving rather than dividing by zero.
    # R270(b), 2026-08-31: 945 -> 956, the eleven that pin the OBSERVED-FACT
    # tier -- a started game yielding the order that actually batted, a Preview
    # game reading NO order even with a block present (a pre-game boxscore is a
    # prediction and this tier holds observations), an unrecognised state
    # treated as not-started, the shared `normalize_name` join so the accented
    # spellings that cost a pass resolve, the three states being distinct with
    # `did_not_start` finding the dead bat, `unobserved` never collapsing into
    # `did_not_start` (R237's conflation through a new door), an empty side
    # block on an underway game being an UNREAD BLOCK rather than nine
    # scratches, an observed starter absent from the DK pool named rather than
    # dropped (R32's reading), a substitution appended to the order not minting
    # a tenth starter, and the boxscore URL builder going through the one leg
    # filter rather than becoming a second matcher.
    # R247(a)+(c), 2026-09-01: 956 -> 983, the twenty-seven that pin the
    # degraded-tail flag and the correlated-block line -- eight on the two bars
    # and their provenance (the salary bar IS the archive p99 and names its
    # window, the proxy bar is NOT archive-derived and says why, the two triggers
    # reachable independently, both named when both fire, the two filed sightings
    # caught and an at-cap portfolio not, a missing proxy named rather than
    # zeroed, the report-never-a-gate source check, and one function object for
    # the salary-left binner), six on the block itself (entries failing together,
    # a mutation guard on the count, entered rows rather than distinct lineups,
    # a stable tie-break, one entry reporting unavailable, names when the frame
    # carries them), six on the design axis including the finding that changed
    # it (a dead entry is not a hedge, a full-cap hedge IS design, and a
    # cap-spending low-proxy entry is NEITHER and says so, plus the three
    # buckets partitioning the count they correct), and seven on the surfaces
    # that read it (the Classic frontier surviving a frame with no Salary, both
    # build_slate lines, qa_portfolio no longer publishing the bare untouched
    # count and naming a pre-R247 brief, and the Showdown brief's own cap,
    # never-a-literal fallback, and entry_id-to-lineup pairing).
    # R165, 2026-09-01: 983 -> 993, the ten that pin the id-normalization
    # contract. Three on the normalizer itself (the vectorized and scalar
    # spellings held elementwise equal, the membership set, the copy), and
    # seven on the sites, every one of them built on an int64 frame produced by
    # a real `read_csv` reload -- an `astype(str)` fix passes trivially on a
    # frame that is already str, so the fixture IS the test. Two of the seven
    # exist because the mutation check killed the first cut of them: the
    # diverse-bank one asserted legality where the guard only changes solves
    # SPENT, and nothing anywhere handed a helper int-typed EXCLUDES.
    # R163, 2026-09-01: 993 -> 998, the five that pin the DU high-water. The
    # invariant (0 relaxed lineups cannot sit beside a non-negative high-water),
    # the solve count site A used to spend, the duplicated
    # `proven_infeasible_lineup_indices`, site B still earning its step, and a
    # source guard that the high-water is assigned in exactly one place --
    # R233 made enforceable rather than re-derived by the next reader.
    # R246, 2026-09-01: 998 -> 1016, the eighteen that pin the two leverage
    # constraints reaching a production caller for the first time. Four on the
    # engine half (the augmentation whitelist, the sliced bank's forwarding, the
    # None-omitting kwargs builder, the three-key set), four on the ownership
    # attach as a FUNCTION rather than an `if` (a disabled branch kept both the
    # call string and its position, so the only test covering it passed), five
    # on the operator surface's refusals (absent prediction file, unknown key,
    # ambiguous archetype, the recorded sha, Showdown), two on the sliced and
    # auto paths sharing ONE attach, and three on the constraints binding
    # against a real bank. The sharpest is the shared-function one: with no
    # `Projected_Ownership_Pct` column the solver's reader falls back to a flat
    # 12.0 per player, so a cumulative cap of 90 binds against 10 x 12.0 = 120
    # and reads as working while measuring nothing.
    # R286+R288+R289, 2026-09-01: 1016 -> 1039, the twenty-three that pin the
    # 09-01 no-file-at-lock batch's engine half. Nine on the refusal renderer
    # (the failing SLATE check leading errors[0], every failing check
    # enumerated, the interaction message barred while one fails and surviving
    # when none does, `passed is None` not read as a failure, the pre-R286
    # message byte-identical with no checks supplied so the frozen golden and
    # the plan leg are unmoved, the bank-growth remedy demoted, CHECKED_CONTROLS
    # disjoint from LADDER_RELAXED_CONTROLS by AST over _feasibility_report, and
    # the wiring). Six on the anti-correlation control (zero default refusing the
    # construction, a raised value shipping it, the bound exact at every rung, a
    # negative value raising rather than clamping, ONE formulation for every
    # value, and the sliced-bank reach plus the conditions-signature re-key).
    # Eight on the salary Excluded column (reaching the frame, none reaching a
    # lineup, the legal-pool warning, a blank or absent column changing nothing,
    # an unrecognized token keeping the player, the scalar and frame readings
    # being one function, the neutral shell's deliberate keep, and the bank
    # re-key). The sharpest is the byte-identical one: without it the golden
    # replay is the only thing standing between this change and a silently
    # reworded refusal on every path that supplies no feasibility inputs.
    # R291, 2026-09-02: 1040 -> 1047. The R289 acceptance test above was
    # REWRITTEN rather than added to, so its count is unchanged and its meaning
    # is not: it built the frame by hand, called `_drop_excluded_rows` directly,
    # and guarded the lineup assert with `if lineup is not None` -- on the
    # T3/T4 fixture the restricted pool is two teams whose only two arms oppose
    # every remaining hitter, so the solve returns None and the assert was
    # vacuous. It now runs `_assemble_projection_frame` and excludes one team so
    # the legal pool can solve. Six new: the frame carrying the column with the
    # pool report and the checkpoint agreeing, the digest re-keying on the
    # PRODUCTION path (the R289 test proved that on a hand-built frame while it
    # was false end to end), a file with no column hashing exactly as it did,
    # the swap refusing to revoke an operator exclusion, the swap still
    # un-excluding one it imposed itself, `extend_bank` enumerating the legal
    # pool only -- that one with the drop patched out as its own counterfactual,
    # because a job-count assertion means nothing without the number it is
    # smaller than -- and the Classic brief carrying the count zero or not,
    # which is the 09-02 BUILD fragment's own bar: on the 2138_2g build the
    # brief had NO `pool.excluded_column` key, so absent read as zero.
    # R296, 2026-09-03: 1047 -> 1075, the twenty-eight that pin the lost-window
    # doors. Twelve on flag VALUES read in main() before anything is staged
    # (three parsers that used to `raise SystemExit` past every handler, two
    # `type=json.loads` flags that accepted `[1,2]` and `5`), including the
    # positive control that a legal value still reaches the build and the
    # property test that no flag parser raises SystemExit again. Two on exit
    # codes: the two supplied-feed refusals now agree on 4, and every status
    # payload carries the slate date the supervisor's log is placed from. Nine
    # on the supervisor -- the sys.path insert that made the decision log
    # writable AT ALL (reached alone, after the first cut was masked by its own
    # fallback), the fallback that survives an unimportable engine, off-contract
    # child exits named with returncode and stderr, the per-decision flush, the
    # call budget that stops before an attempt it cannot finish, the first
    # attempt that always runs anyway, and resume. Seven on the swap, the
    # repair tool, stage_slate and the probe: three torn-input doors (two of
    # which the item did not name) and the probe timing the projected pool
    # instead of refusing a normal DK-covered slate.
    # R290(c) commit 1, 2026-09-03: 1075 -> 1095, the twenty that pin the
    # refusal classification. Twelve on the table itself -- its COMPLETENESS in
    # both directions (no refusal exit without a stamp, no row without a site,
    # eleven of them and not the eight the item filed), every row carrying a
    # class AND an authority AND its evidence, the two SPLIT sites being the two
    # with sub-maps, every workflow gate the engine enforces having a row, and
    # the finding itself: portfolio_caps is BADLY-SHAPED where roster_legality
    # and the three DK gates are ILLEGAL, one illegal gate among preference
    # misses still resolving ILLEGAL, the unclassified-gate default reached
    # alone, refusal_stamp refusing an unknown key, the crosswalk wall NOT
    # labelled a DK rule, exit 4 named out of scope, and the exit-10 site the
    # item never counted. Four on the blank-versus-partial row split, which was
    # one string over two facts with opposite classifications. Three on the
    # probe's --budget default, the retired 45-second class's ninth member,
    # asked of the parser rather than the constant. The twentieth pins the
    # table's field name: its first cut called the field `status`, which made
    # R296(e)'s payload-shape walk read eleven table rows as eleven refusal
    # payloads with no slate date.
    # R290(c) step 2, 2026-09-03: 1095 -> 1127, the thirty-two that pin the
    # deadline governor. Nineteen pure ones on the clock, the filter and the
    # ladder (every clock injected, because CLAUDE.md's own rule is read the
    # clock from the clock and a test on the wall clock cannot pin a window):
    # HH:MM and ISO parsing including a NAIVE stamp read as ET rather than UTC,
    # the window opening at T-6 and staying open PAST the lock, only
    # badly_shaped governed, a payload naming no class never governed, the
    # two-rung ladder, the open overlap value being roster size MINUS ONE so a
    # rung cannot produce an identical pair, and the label never being
    # upload_ready. Five WIRING ones that drive run_classic itself with only
    # run_slate faked -- the item's done-when executed, an ILLEGAL refusal
    # never re-solved, T-30 still refusing, rung 2's Classic boundary cited
    # against the engine source, and R288's claim re-asserted as behaviour
    # after this item's refactor broke its string pin (R300(c)). Five CLI ones
    # on --deliver-by at the front door and the supervisor's clock clamp. Three
    # on the classification defect this item's own acceptance test found: POST-
    # export gate names never reached the classifier, so four DK-rule gates
    # took the no-gate-named default.
    # R293, 2026-09-03: 1127 -> 1140, the thirteen that pin the bank's own
    # anti-correlation rung. Three on the reversed augmentation skip (no solve
    # spent on the opponent stack the rows bar, the SP-plus-own-offense stack
    # actually reached with `appended` non-zero where it was 0, and the skip
    # LIFTING when the allowance covers the stack floor so it stays a waste
    # optimization and not a wall). Four on the control reaching every rung
    # (the augmentation whitelist, the solver stamping the k it built its rows
    # under, a fresh status carrying None rather than a fabricated 0, and the
    # auto-bank reading it off portfolio_controls through run_slate itself).
    # Three on the reports (all three bank producers EXECUTED and asserted to
    # carry what their own solves ran under, the no-augmentation return still
    # carrying the key, and the call-site census that fails on an N+1 member).
    # Three on the truthful-labels half: `applied` read from the bank and
    # disagreeing with the flag, null when the rungs disagree, and an
    # unobserved build saying so instead of restating the engine default.
    # R294, 2026-09-04: 1140 -> 1154, the fourteen that pin allocator truth.
    # Six on the prefilter (the acceptance fixture asserting stack sizes
    # [4, 4] with zero relaxations and one solve, the selectable-only mechanism
    # underneath it, the per-entry reserve protecting an entry the score fill
    # would drop -- on a fixture that asserts forced_coverage_kept == 0, so it
    # cannot pass by the wrong mechanism, which is what the first cut did and
    # what three surviving mutations caught -- the emptied count firing with
    # the reserve switched off, the field present on the not-applied path, and
    # a pre-starved matrix NOT being counted against the filter). Three on the
    # slate-blocked guard (one solve
    # when a check failed, the ladders still climbing when none did, and
    # `passed is None` not being a failure -- R237's rule arriving through a new
    # door). Four on the labels (status 4 and status 3 carrying no "proven"
    # anywhere in the payload and stepping no ladder, the REACHABLE member of
    # that class -- status 0 with an unverifiable `x` -- getting the same, and
    # status 2 still saying the reserved words and still climbing). One R233
    # census: an AST walk asserting all three re-entries read both conjuncts, so
    # a fourth ladder fails here instead of stepping on a non-proof.
    # R297(d)+R304+R305, 2026-09-06: 1154 -> 1159, the five that pin
    # qa_portfolio's five members of the Classic-pitcher-token class AND the
    # premise correction that came with checking them -- the two guards that
    # make all five unreachable on a Showdown portfolio today (`lineup_players`
    # keys on Classic SLOTS; the leverage panel prints ABSENT rather than
    # computing a carry), the Classic reading unchanged at a live site, the
    # legend's denominator once the arms come out, and one predicate object
    # shared with preflight rather than restated.
    # R322, 2026-09-08: 1159 -> 1160, the one that pins the OTHER way a repo
    # path pinned in a test's own expectation table goes stale -- the guard for
    # the class, since fixing the one table (EXPECTED_CENSUS, whose untracked
    # member made this suite RED in every fresh clone and told the gate to say
    # "do not build") does not stop the third member being written next month.
    # R327+R313+R310(b)+R312 + the 1835_5g fragment, 2026-09-08: 1160 -> 1205,
    # the forty-five that pin Session 3 here; three more are in test_showdown
    # below, because R310's REPORTING end has to be driven through the
    # production `run_showdown` and a source read of build_slate.py goes green
    # on a disabled branch (R249 M1, R300(a)). Twenty-one on R327's boundary: the two
    # doors refusing duplicate ids, negative/zero/non-integer/NaN salary,
    # NaN/+-inf bounds, an inverted bound and an EMPTY frame before SciPy sees
    # any of it; `build_projections` raising on the same frames, so the rule
    # binds on the production builder and not only on a validator a caller may
    # skip; the refresh reading `Excluded` through the canonical parser for
    # every non-affirmative token INCLUDING the float NaN a CSV round trip with
    # one blank cell produces, an explicit TRUE surviving, idempotence, and the
    # inverted refreshed bound RAISING instead of being clipped to
    # Floor == Ceiling; and the `--projections` door itself refusing nan/inf/
    # negative/duplicate, which is the N+1 site the entry did not name and the
    # one door it did. Eight on R313: the blocklist survivor selectable and the
    # objective back at the unconstrained value, a full core still binding, a
    # three-member combo shrunk to two survivors no longer forbidding that
    # pair, a genuine pair still forbidden, `overlap_reference` unchanged (the
    # third `_known_pids` caller, CORRECT, tested so its omission cannot read
    # as an oversight), and the legal-player count unmoved by a core's
    # presence. Eight on R310's warning half, the two archived callups vendored
    # under tests/fixtures/showdown/ rather than read out of the gitignored
    # data/slates/ (R155's defect, R322's guard), plus the flat-pool and
    # expensive-star silences that make it a caution and not decoration. Four
    # on R312: no name `score_lineup_candidate` can emit carries the forbidden
    # vocabulary, across the closed shape set times every mode, with the
    # surviving `mode='portfolio_ev'` token named rather than silently exempt.
    # Six on the fragment's `agrees_with_request`, including the split-bank case
    # that proves the new null did not silence R293's own disagreement.
    # R326, 2026-09-09: 1205 -> 1215, the ten that pin the full-bank retry
    # before any strategy relaxation -- both feasibility witnesses (Hall via
    # the per-entry reserve, and an under-filled SP-pair bucket on the
    # DEFAULT keep_target), the search_scope record on all three report
    # paths, the happy path that must not retry, the unrestricted bank that
    # must not retry, the time limit that must not retry, and the once-only
    # bound.
    # R348, 2026-09-15: 1215 -> 1221, the six that pin the pytest-temp-root
    # probe, the redirect that never overwrites an operator pin (nor one
    # inherited from a parent that already redirected), the warning that names
    # the unusable root, the one cleanup helper that replaced three copies of
    # the same pair, and -- the rider's regression -- that a nested in-process
    # `run_audit` deletes neither of the OUTER gate's two throwaway roots.
    # R340, 2026-09-15: 1221 -> 1238, the seventeen that pin the bank stack
    # request. Nine on the derivation and the three doors it now reaches
    # (including the plan leg, which R340's own entry does not name), six on
    # telling `bank_never_asked_for_size` from `bank_asked_and_could_not`, and
    # two on merging the sliced door's two per-size reports into the one report
    # everything downstream reads.
    # R343+R333 (CC-2), 2026-09-15: 1238 -> 1274, the thirty-six that pin the
    # two washout-axis caps. Eleven on the team footprint over ALL stack roles
    # (the definition, the arm exclusion, the MILP rows, and the one assertion
    # that says the cap binds where `max_primary_stack_exposure_pct` cannot),
    # eleven on the game control being wired from a PRODUCTION writer for the
    # first time plus the scalar, the MIN merge and the F5 weather cap, nine on
    # the floors and the capacity checks that keep a default-on ceiling from
    # refusing a thin slate, and nine on the reporting surfaces -- four of those
    # nine on class members the two board entries do NOT name, found by the
    # R233 grep: the deadline governor's T-15 open-controls rung, R98(2)'s
    # strategy-versus-structural split, the untouchable-row conflict check, and
    # the vacuous-row guard that keeps an OPENED cap from moving a solve.
    # R301(2)(6), 2026-09-15: 1278 -> 1281, the three in
    # RootContractBudgetTests: the CLAUDE.md size budget, every path the
    # root contract points at exists, and the command guard hook denies the
    # contract bans. The two PASS-line prose pins now pin the shape, not
    # the count, so this move is the last one that needed a CLAUDE.md edit.
    # R349, 2026-09-16: 1281 -> 1292, the eleven that pin the host resolver --
    # two added to ProbeBudgetDefaultTests (the unknown host still gets 130, and
    # a STATED cowork host is not widened by an ambient BASH_DEFAULT_TIMEOUT_MS,
    # which the first cut got wrong), eight in HostProfileTests (the four probe
    # branches, the small-ceiling-not-floored-up case, the three-level
    # precedence, repo_root rejecting a non-repo override, and every profile
    # carrying the keys callers read), and one in BuildSlateScriptTests for the
    # engine-absent fallback -- the first cut put that import at module level and
    # reddened the sibling test that keeps this script loadable with no engine.
    # R353, 2026-09-17: 1292 -> 1294, the two in ClaimWriteSetTests that compare
    # claim.py's DEV write set against CLAUDE.md's own `- Roles.` bullet. They
    # were written because the two had drifted apart on CHANGELOG.md, so a pin
    # that restated either list here would have drifted the same way; both tests
    # read the two files instead.
    # R353 round two, 2026-09-17: 1294 -> 1295, the one that pins every
    # transitive requirement of a pinned distribution as itself pinned. CI
    # rejected the first cut for exactly that (`packaging>=20` unpinned under
    # --require-hashes) and the local gate could not see it, because Debian had
    # already put packaging on this host. The test reads installed metadata.
    # R354, 2026-09-17: 1295 -> 1302, the seven in StageSlateAttachmentIntakeTests
    # that pin the chat-attachment intake -- both roles staged and the directory
    # REPORTED, roles read from the header not the filename, two files for one
    # role blocking per R70, a second run copying nothing, an empty root reported
    # rather than raising, a missing root skipped, and ATTACHMENT_ROOTS being a
    # ranked list rather than one hardcoded path.
    # R360+R361+R362, 2026-09-18: 1302 -> 1314, the post-run retro batch's
    # twelve -- two that pin --per-build-seconds resolving from the host rather
    # than the Cowork literal 20 (R360), four that pin the deps hook keeping
    # pip's stderr and retrying the install once (R361), and six that pin the
    # session-start inbox line: fragments named, RETAINED counted apart from
    # debt, miner blocks excluded, an empty and a missing inbox both safe, and
    # the line actually reaching full() (R362).
    # R366, 2026-09-19: 1314 -> 1319, the five that pin docs/PROGRESS.md as
    # DERIVED from the board -- the drift gate itself (the committed file
    # equals what the committed board generates), status read from a row
    # rather than stored, a batch DONE only when every one of its rows is,
    # the NEXT pointer carried and a missing one named, and --check exiting
    # 2 when the board moved and the file did not.
    # R359+R356, 2026-09-19: 1319 -> 1327, the eight that pin the host
    # prose being true -- five that the claim tool says CONTAINER-LOCAL in
    # a cloud container and stays silent on the two hosts where the mutex
    # is real, that `dirt` never carries the note (it reads git, not
    # claims), and that the host resolves from a foreign working
    # directory (the sync_check import defect, one tool over); three that
    # CLAUDE.md defers every budget question to `call_budget_s()`, names
    # three hosts, and that no rule still calls `/tmp` or `rm` Cowork-only.
    # R364+R367+R368+R365, 2026-09-19: 1327 -> 1341, CC-A5's fourteen --
    # four that solver_probe refuses at the contract's exit 4 instead of
    # crashing at 1 (missing salary, no arguments, wrong geometry, and the
    # docstring promising no exit 1); six on the egress probe (every target
    # once with its client named, a raising probe reading as a status, a
    # timeout distinguished from unreachable, a 401 as reachable, no DK
    # target, and the hook printing the line); four that the retired
    # instructions are archived with banners, MANIFEST.md stays put and
    # points at its archive, MLB_Classic.md stops contradicting the bank
    # cap, and docs/hosts.md answers secrets, egress and the budget hatch.
    # R369, 2026-09-19: 1341 -> 1351, CC-A6's ten -- nine on the delivery
    # record (one delivery recorded through the real choke point and all three
    # archive-side readers answering from it with no `outputs/` tree in
    # existence; a refusal keyed by timestamp with its exit code and its note;
    # a planted key smuggled into a copied field refusing the write and naming
    # the variable without echoing its value; both of `record_delivery`'s
    # return paths mirroring, pinned by deleting the record between them; no
    # ROI, win rate or cash rate in the artifact itself; the salary tier
    # matching on CONTENT past a same-named decoy; that tier answering ahead of
    # the in-date one, pinned by running `resolve_salary_tiered`; `build_slate`'s
    # `__main__` recording the refusal its thirteen `return N, {}` sites cannot)
    # and one that `data/deliveries/` reached BUILD and ARCHIVE in CLAUDE.md and
    # tools/claim.py together. Then 1351 -> 1353, the two that pin the
    # isolation the tracked record made visible: a bare `python -m unittest`
    # got neither the gate's `MLB_DFS_ARTIFACT_ROOT` nor conftest's, so the
    # front-door tests published into the real tree (harmless while `outputs/`
    # was all they wrote, because it is gitignored), and the code sha survives
    # an isolated artifact root because it is read from the code, not from it.
    # R370 + R371, 2026-09-19: 1353 -> 1375, CC-A7's twenty-two. Twelve on the
    # outcome review: washout three-valued in both directions (an unknown curve
    # never reading as `false`, one cash beating an unknown contest), a cashed
    # contest graded end to end, a known-curve miss graded as a washout, an
    # absent standings export named rather than skipped, the planned/realized
    # exposure join through the salary sha and its unjoined fallback, the
    # emitted text grepped for every outcome-claim word, `pending` counting
    # only records with no review beside them, a re-run replacing its own
    # ledger fragment, and a sidecar never readable as a delivery. Ten on the
    # retro facts: the gate-clean-to-hand-over gap and its refusal to invent
    # one, the R363 detector against a Showdown brief plus both SKILL.md
    # constructions and the two filters that keep filenames and non-brief roots
    # out, a refusal exit against its documented table in both directions, the
    # degraded-input extraction, a missing brief stated rather than silent, a
    # defaulted control kept apart from a hand-passed one, and every section
    # rendering when all are empty.
    # R372, 2026-09-19: 1375 -> 1392, the seventeen that pin the two repo agents
    # and the four hook events as BEHAVIOUR -- the FINDINGS contract parsed from
    # a real payload (absent line -> null, never 0; last line, not a quoted
    # example; anchored so a prose mention is not the count), one jsonl per
    # session with a sanitized id, the hand-over ask firing on an uncommitted
    # R369 record and exempting the command that commits it, its refusal to
    # claim a hand-over field that does not exist, `--untracked-files=all`
    # without which the rule never fires on a fresh container, PreCompact
    # injecting CLAUDE.md's own text and naming what it cannot recover,
    # SessionEnd warning without ever blocking the exit, and all four events
    # wired to files that exist. +1 on its first LIVE firing, which arrived with
    # an empty agent_type on the PARENT transcript and recorded five hours of
    # main session as an agent's wall time: the span is now refused unless the
    # entries are the agent's.
    # +1 again: the same live firing showed the event arrives with NO agent_type
    # at all in an ordinary DEV session, so it now writes nothing rather than a
    # contentless row into a tracked directory on every session.
    # R378, 2026-09-20: 1394 -> 1396, the two that pin the findings
    # fallback -- the transcript's last SIDECHAIN assistant message answers when
    # the payload omits `last_assistant_message` (measured null on all three of
    # this hook's first real runs), the payload still wins when delivered, a
    # tool_use block is not the agent's text, neither source guesses, and a
    # PARENT transcript cannot donate its count to an unnamed agent.
    # R118 (CC-6), 2026-09-22: 1396 -> 1406, the ten that pin tools/replay_slate.py --
    # the copied tie oracle against production's own hand example, the
    # integer-hundredths guard, the CPT-row exclusion, the name-collision
    # refusal, the Showdown refusal WITH its measured reason, UNKNOWN never
    # zeroed, observed-vs-inferred seat value, the F-48 tie split on real
    # archived data, zero-mismatch self-validation, and the strangler wall.
    # R385, 2026-09-22: 1406 -> 1407, PlanStatusTests rewritten from R366's five
    # PROGRESS.md drift tests to six ROADMAP lint tests (real tree clean, a clean
    # synthetic pair, uncovered open entry, status vocabulary, NEXT target, rows
    # without an R-number and unresolvable ledger ids).
    "tests.test_core": 1407,
    # R113's solve_ladder half, 2026-08-15: 55 -> 56, lock_relaxation_detail
    # naming the thesis and the substituted captain.
    # R153, 2026-08-19: 56 -> 62, the six that pin Ben's tightened Showdown caps
    # (captain 0.33 -> 0.25, new player cap at 0.50). Two of the six are the
    # leaks the first cut shipped and the live ARI@BOS build exposed: solve_ladder
    # enforced no captain cap at all, so a lock substitution landed on top of a
    # full captain (26.3% realized under a 25% cap), and the player cap carved out
    # a thesis's own cpt and locks, so a named player reached 57.9% under a 50%
    # cap while every relaxation counter read clean. A cap enforced somewhere
    # other than where the roster spots are spent is not a cap.
    # R156, 2026-08-21: 62 -> 66, the four that pin pitchers_duel always
    # carrying both starters. The live ATL@MIL delivery shipped this thesis
    # with only Misiorowski, no Sale: the overlap bound made Sale infeasible as
    # captain, the captain-lock relaxation substituted Misiorowski, and nothing
    # else required Sale, because build_thesis_ladder's `!= cpt` filter had
    # stripped him out of `locks` precisely because he WAS the assigned
    # captain. Two tests pin the fix (both starters are unconditional
    # `hard_locks`, merged into `locks` regardless of who captains; the
    # captain is always one of the two arms, never a bat, since `cpt_ladder`
    # is now restricted to them) and two pin what the fix could have broken
    # (a solved lineup always contains both arms end to end, and the removed
    # top-band hitter locks -- infeasible on their own, measured at
    # $47,500-48,100 of the $50,000 cap before the last two roster spots --
    # never returns as an infeasible thesis across a range of entry counts).
    # R190(b)(c), 2026-08-23: 66 -> 72. Four are (b)'s, on the platoon lookup
    # that had a DK code on one side and an MLB Stats API code on the other:
    # `AZ` resolving against `ARI`, a FanGraphs alias resolving too, a team
    # needing no remap unaffected (the regression guard), and a genuinely
    # missing hand NAMED rather than folded into `teams_with_hand: 1`, which
    # could not distinguish a code mismatch from a hand the feed never had.
    # The symmetric version of the fix -- normalizing DK's own column as well
    # -- SURVIVED its mutation and was dropped rather than shipped: no honest
    # fixture can put a non-DK code in a DK column, and the defect is
    # one-sided because only the feed speaks another vocabulary.
    # R190(d), 2026-08-23: 72 -> 77, the five that pin the gate's call ceiling
    # as the HOST's to state. `--gate-budget` was already tunable and did
    # nothing on its own, because GATE_CALL_CEILING_S capped the child
    # underneath it: --gate-budget 90 still killed the child at 39s, which
    # reads exactly like a test that cannot finish, so a unit slower than the
    # ceiling accumulated two "started" records, got marked `oversized`, and
    # the gate became STRUCTURALLY unable to print its clean line. The device
    # default is unchanged for a caller who says nothing; an explicit flag beats
    # the environment; an unparseable env value falls back rather than raising,
    # because a typo must not be how the gate stops working; and the returned
    # ceiling is FLOORED above the budget, which is the defect as a property.
    # Two are (c)'s, on the brief carrying the two structured pool_report facts
    # it dropped (`opposing_probables_incomplete`, `dk_batting_order`) and
    # still producing a block when a report carries neither, since a KeyError
    # there would lose the brief on the refusal path that most needs one.
    # R167, 2026-08-24: 77 -> 79, the two that pin the Showdown caps under the
    # same units rule as the Classic ones. `exposure_cap_count` validated
    # nothing, so `25` typed for `0.25` returned a cap of 25n, capped nobody,
    # and left every relaxation counter reading clean -- R153's washout axis
    # switched off by a keystroke, invisible in the brief.
    # R263, 2026-08-28: 79 -> 91, the twelve on the shadow report and the coarse
    # weight lever that was MEASURED AND DECLINED. Eight pin the shadow: the split
    # pattern canonicalized the way `field_miner`'s `stack_pattern` already does so
    # a delivered split and a mined field share are one vocabulary, the pitcher-CPT
    # share counted off SOLVED lineups, `steers: False` present in the artifact and
    # not only in a comment, the per-player captain-cap CEILING beside the share, a
    # band the caps FORBID reported unreachable rather than missed, the three
    # verdict directions, the bands carrying their 3.21 evidence with no outcome
    # claim, and an empty report returning unmeasured rather than zeros that would
    # print as a finding.
    # Four pin the declined lever. Ben asked for a weight bump to move the
    # delivered pitcher-CPT share from ~40% toward ~50%; it was built and measured
    # over 96 apportion-and-solve checks (six moneylines x n=9..24, R156's own
    # standard on this fixture) and declined. Mean realized share 43.66% -> 44.91%,
    # mean STRUCTURAL CEILING 45.01% unchanged, builds at their ceiling 75/96 ->
    # 94/96, captain-cap relaxations 37 -> 56. The share is CAP-bound, not
    # weight-bound: with two declared arms and a per-PLAYER captain cap, the
    # reachable share is 2*floor(cap*n)/n, which never exceeds 50% and averages
    # 45.0%. So ~50% is not reachable by any weight, the old weights were already
    # at 97% of what is, and the bump buys 1.25pp by manufacturing relaxations at
    # n=16, 17 and 18 -- entry counts that had zero. The pinned
    # `test_ladder_spans_game_states_and_holds_the_captain_cap` caught it at n=18.
    # The tests pin the ceiling arithmetic, R156's 0.45 standing untouched, the
    # directional block summing to 1.00 whatever a future re-sizing does, and the
    # apportioned captain count staying under the cap the same call computed.
    # R239 seam, 2026-08-29: 91 -> 98, the seven that pin the contest partition
    # reaching the ladder and changing nothing. Three on the vector (sizes and
    # each slot's OWN contest size, a missing vector reading UNAVAILABLE rather
    # than as one contest, a short vector reported short rather than silently
    # zipped) and four on identity -- the ladder, the solved bank, every
    # diagnostic except the partition, and the captain list specifically, which
    # is the one R239(b) is about to move and therefore the one whose "unchanged
    # by the seam" reading the next stage depends on.
    # R239(c), 2026-08-29: 98 -> 114, the sixteen that pin the per-contest
    # slice and the clean verdict answering to it. Six on the slice (counts and
    # distinct captains per contest, a captain over the bar being the finding,
    # AT the cap not being over it, the cap never exceeding the contest's own
    # size, no partition reading clean=None rather than True or False, and an
    # unsolved slot not counting as an entry). Six on the Gale-Ryser
    # precondition, two of them reproducing the measured 08-28 numbers exactly
    # (infeasible at m=1 with 14 > 13 at k=3, feasible at the shipped m=2, which
    # is the evidence for the default being named rather than derived). Four on
    # qa_portfolio refusing a clean verdict without the block, and leaving
    # Classic alone.
    # R239(b), 2026-08-29: 114 -> 133, the nineteen that pin the cap binding
    # where the slot is spent. Five on the `n - 1` correction found while
    # building it (a flat cap of 2 permits a 2-entry contest to put BOTH entries
    # on one captain -- the measured 100% passing a cap written to stop it), one
    # of which pins the checker's bar equal to the builder's at every size and is
    # what caught the disagreement. Three on the solve side, driven through the
    # relaxation ladder with a mocked solver because the fixture's overlap bound
    # diversifies captains on its own: an end-to-end assertion cannot see the
    # guard, and R153's failure lives on exactly the rung it protects. Eight
    # entries, not two, because at n=2 the PORTFOLIO cap already excludes the
    # captain and the per-contest set would look necessary while doing nothing.
    # R158, 2026-08-30: 133 -> 139, the six that pin the Showdown solver-status
    # split -- a verified time-limited incumbent accepted and tagged, an
    # unverified one rejected by the constraint matrix rather than the
    # roster-shape check, the timeout latch stopping the descent on both the
    # thesis ladder and the bank ladder, the infeasibility contrast that proves
    # the latch is what stops it, and the clean-solve path unchanged.
    # R223, 2026-08-30: 139 -> 144, the five that pin the fourth counter -- the
    # floor rung carrying the portfolio captain exclusions the rung below drops,
    # the counter firing on the portfolio rung in ISOLATION (with a partition the
    # true floor also increments it, which is how the first cut passed against a
    # mutated increment), the withdrawal of a reassignment record a lower rung
    # contradicts, and the counter being present when it reads zero.
    # R250, 2026-08-30: 144 -> 151, the seven that pin the captain-budget hold --
    # the named captain reaching the captain slot at the player cap, the budget
    # MOVING from UTIL to captain rather than growing (total exposure unchanged),
    # the apex caution's exact condition, the hold shrinking as it is spent (a
    # hold that never releases strands the budget), the hold bounded by the
    # captain cap, the hold not being counted as a relaxation, and `util_excludes`
    # blocking the UTIL seat while leaving the captain seat.
    # R249, 2026-09-01: 151 -> 166, the fifteen that pin the supplied Base seam --
    # the insertion point itself (a supplied number is the prior and is not
    # regressed toward the salary fit), the property that disqualified the
    # pre-prior insertion point (supplying one player leaves every other prior
    # byte-identical), the captain move that is the item's own bar, both DK ids
    # resolving and the pitcher reach, an unmatched id named and inert, the
    # provenance the brief requires, three refusals on a named file that cannot
    # be read, the shared column contract with `ownership_pred.py --base`, the
    # truthful label, the Classic refusal landing before staging, and FOUR on
    # the wiring itself: the order applied through `price_showdown_pool` on the
    # ladder path, the fallback bank path reached, the no-file case unchanged,
    # and the brief block present on both. The wiring tests exist because the
    # first cut had none and a mutation moving the insertion point survived the
    # whole suite -- every other test called the engine function directly on an
    # already-priced frame, so nothing executed the decision.
    # R291(c), 2026-09-02: 166 -> 173, the seven that pin the Excluded column on
    # a path where `grep Excluded showdown*.py` used to return nothing. The
    # no-column fixture unchanged, the flag OR'd across the CPT and UTIL rows,
    # an excluded declared SP reaching no lineup in a five-deep bank, a lock and
    # a cpt_lock naming him REFUSED rather than overriding the pool, the brief
    # block's count and legal pool, an unrecognized token
    # keeping the player (counted per CELL, since a Showdown file has two rows
    # per person), and the one-team refusal. That last one is the test that
    # earns its place: the both-teams MILP rows are built from the LEGAL pool,
    # so an exclusion covering one side made that rule vacuously true and
    # returned a six-man one-team lineup -- the exact vacuity the melt refuses a
    # single-team FILE for, reachable through a new door.
    # R338 step 5, 2026-09-11, count UNCHANGED: the sentence above said those
    # two tests pinned the lock "landing in `ignored_locks`", and it has been
    # wrong twice over since the thirteenth edition. F14 made an operator lock
    # naming an absent player a REFUSAL before constraint assembly
    # (`showdown.py:696`), so `build_showdown_lineup` returns None with
    # `status="invalid_hard_lock"` and no lineup is built at all -- which is
    # what `R291ShowdownExcludedColumnTests.test_no_caller_instruction_can_put_
    # him_back` asserts now. And R338 repair (3) scoped that refusal to the
    # OPERATOR door, so `ignored_locks` is live again on the thesis path and is
    # no longer a field this pair of tests is about. Same seven tests, same
    # count; only the behaviour they pin moved.
    # R306, 2026-09-03: 173 -> 201, the twenty-eight that pin the Showdown
    # captain market. Four budgets (captain 100%, roster 600%, the Classic
    # 800/200 left alone, and the 6:1 identity between the two Showdown ones),
    # the OPPOSITE SIGNS on the two pitcher weights and the concentration
    # ordering that make the captain slot a different market rather than a
    # rescaling, the analytic fact that temperature cannot move the ordering,
    # three on the params tables and their import checks, four on the archetype
    # resolver (including that it CALLS contest_shape_for_card rather than
    # re-deciding a shape, and that the card fields it has to invent cannot
    # reach the answer), five on the emit -- one of which is the detector case
    # that found a defect in this item's own first cut: a CPT token beside a
    # non-CPT/UTIL token takes the collapse's early return, so the rows are
    # still one-per-ROLE and a 600% PERSON market over them re-enters R235's
    # double-count through a door R235 does not watch. Five on the captain
    # actuals and their grade, and five on the archive driver.
    # R304(d), 2026-09-06: 201 -> 206, the five that pin `declared_pitchers`
    # on the Showdown brief -- the delivered brief and the refusal payload
    # (Classic's own two sites, no more), an empty map rather than an absent key
    # when nothing was declared, the round trip back through
    # `preflight_upload.resolve_declared_pitchers`, and the scope the key does
    # NOT claim (the Showdown melt still derives its own declared starters).
    # All five drive the production `run_showdown` end to end.
    # R36 Finding 8, 2026-09-08: 206 -> 215, the nine that pin per-(event, team,
    # person) participation -- one posted side no longer erasing the other
    # side's healthy hitters, a pitcher-only declaration erasing nobody, an
    # incomplete declaration establishing nothing and labelling its side's
    # candidates, a fully posted slate being the pool it always was, R159(a)'s
    # degraded nine still deciding its side, a one-sided partial building
    # instead of hard-erroring on `len(teams) < 2`, the report accounting for
    # every person in the salary universe, a malformed side deciding nothing,
    # and the melt reading R323's shared completeness predicate rather than the
    # column a second time.
    # R310 warning half, 2026-09-08: 215 -> 219, the four that drive the
    # caution through the PRODUCTION `run_showdown` -- the field present with
    # `applied: false` on a pool that does not fire (`supplied_base`'s "absent
    # is not an answer"), the caution string RENDERING off a real report with
    # only the salary-threshold constant patched (the branch never evaluates
    # otherwise, so a NOTE that raised on a None salary would fail nowhere
    # else), and a flagged pool changing no delivered byte, which is what makes
    # it a caution and not a gate. The fourth is the one a SURVIVING mutant
    # asked for: the NOTE is suppressed when `--projections` supplied the
    # Base (the operator already replaced the prior it warns about) and the
    # FIELD is not, and that rule was correct and untested until the mutant
    # that deleted it lived. A fixture gap, not a weak mutant.
    # R358, 2026-09-19: 219 -> 224, the five that pin the gate budget and
    # ceiling as RESOLVED per host rather than the retired 28.0/39.0 --
    # an AST pin that neither is a literal again, a declaring host being
    # believed, a silent host still getting the documented 130.0 floor,
    # the MLB_DFS_CALL_BUDGET_S hatch winning, and a stated ceiling not
    # being raised to meet an unstated budget.
    # R373, 2026-09-19: 224 -> 228, the four that pin `favorite_basis` --
    # named as an alphabetical tiebreak with no market, mirroring a real
    # basis when one exists, still a tiebreak when a market prices the
    # game exactly even, and carried into the brief beside the label.
    # R347, 2026-09-20: 228 -> 235, the seven that pin the DK-declared opener
    # staying in the Showdown pool -- `declared_opener` on a decided and on an
    # undecided side, never counted as a declared starter, `openers_kept` on the
    # participation report and empty when the man was shelved or absent, and the
    # thesis ladder refusing to promote him into `starters` (which `pitchers_duel`
    # hard-locks) on an opener-only side and on a side that also has a real SP.
    # R334(a), 2026-09-20: 235 -> 245, the ten that pin the F1 implied-team-total
    # factor reaching a Showdown hitter -- the team factor and the neutral arms,
    # the favored side scored above the underdog, a total with NO moneyline
    # reading neutral on a two-team slate (correct, not a wiring failure), the
    # clip bounding the transmissible side ratio at 1.353x, the seam applying it
    # on BOTH build paths, a supplied Base still untouched by it (R249's order,
    # executable rather than a source-layout property), the no-packet no-op, the
    # prior_note reading the frame instead of asserting a chain, and the wiring
    # itself read off the source.
    # R334(c)+(d), 2026-09-20: 245 -> 257, the twelve that pin the two Showdown
    # reports -- (c) firing on the measured 2210_1g_sd arm gap and staying
    # silent inside the margin, present with a reason when it cannot run, an
    # unjoinable arm NAMED rather than scored on one side (R189(2)), and the
    # pool untouched; (d) silent on a prior that agrees, naming an inverted bat
    # with both ranks, WITHIN a side rather than across the game, the rank gap
    # exercised at two settings, the no-projections no-op, an unjoinable hitter
    # named not ranked, no supplied number changed, and both blocks on the brief.
    # R328, 2026-09-20: 257 -> 264, the seven that pin the ordering between the
    # two Showdown ownership markets -- the production pair coherent on all six
    # archetypes, a captain marginal above its roster marginal NAMED, the
    # inputs untouched (reported, never clamped), the 2dp rounding tolerance,
    # out-of-range and missing ids reported separately, R338's water-fill half
    # re-pinned so the row cannot reopen against it, and the emit block.
    # R295(a)(b)(c)(d)+F40, 2026-09-21: 264 -> 287, the twenty-three that pin
    # the ladder-truth batch -- three on the unguarded captain-lock rung (the
    # duplicate solve of rung 1, the substitution booked against a slot with no
    # lock, and the rung still firing when there IS a lock), five on the melt
    # refusing two DK persons under one name on one team (both roles, the
    # same-ID duplicate that is NOT a collision, the clean fixture, and the
    # tree-wide scan that is the evidence the fix refuses rather than re-keys),
    # five on the captain-budget hold yielding to a thesis lock plus one more
    # inside R250's own class closing its `locks: []` blind spot, four on the
    # reservation bounded by BOTH caps and released against the requesting slot,
    # and five on the degraded proxy restated off the unweighted Base.
    # R381, 2026-09-21: 287 -> 306, the nineteen that pin the captain leverage
    # sleeve (CC-5, R307 batch 1) -- eight on resolution (either role's DK id, a
    # Name|Team key and a bare name; the refusals for an unresolvable person, a
    # name two teams carry, an unknown key and the four malformed values; the
    # selector form refused AS A SELECTOR rather than as a missing ballplayer,
    # which is the one a bare assertRaises passes for the wrong reason), four on
    # apportionment (only the designated slots move, the sleeve rotates within
    # itself although the cap permits stacking, a capped designation gives way
    # to the cap and is counted, and the designation lands in `thesis["cpt"]` so
    # it mints an R250 captain reservation), four on the delivered report
    # (membership read off the DELIVERED captain, the three populations reported
    # apart, an unsolved designated slot in neither, and no sleeve as a null
    # block rather than a missing key), and three on the wiring (the JSON-object
    # door, a refusal before anything is staged, and one delivered build whose
    # brief splits the sleeve from the honest remainder).
    # R382, 2026-09-21: 306 -> 334, the twenty-eight that pin CC-5 batch 2 --
    # the captain-ownership prior reaching the build and the `prior_own_below`
    # selector on top of it. Eleven on the reader (the UTIL key space proven
    # END TO END against the real `ownership_pred` emit rather than a hand-built
    # payload, a CPT-keyed file joining and SAYING so, a prediction from another
    # slate matching nobody and refusing by name, the Classic 800/200 market
    # never used as the fallback, the archetype asked rather than picked, the
    # empty cases, the four bad values, two ids on one person, a short budget
    # reported and never rescaled, a person the prediction never scored named
    # rather than zeroed, the ids read in SORTED order so a refusal and an
    # `ids_not_in_pool` list are reproducible, and the label disclaiming each
    # banned word by name),
    # eight on the selector (coldest-first ordering, the menu not truncated to
    # the entry count, an unscored person EXCLUDED rather than read as cold,
    # the seven threshold and arity refusals, a threshold selecting nobody, an
    # explicit list still ignoring the prior, and the selected sleeve reaching
    # the ladder), and seven on the wiring (the resolve-before-the-sleeve
    # order, the payload's shape staying out of the script, the Showdown gate
    # against `is not None` because bare `--captain-prior` is not absent, the
    # brief block, the corrected `--ownership-pred` help, the exit-4 prose
    # count now counted from the AST, and TWO end-to-end runs of
    # `resolve_captain_prior` itself over a real emitted file -- R300's rule,
    # because every string pin above it would stay green on a dead branch).
    "tests.test_showdown": 334,
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
    # R133(3)+(4), 2026-08-18: 218 -> 238, the twenty that pin one thin-team bar
    # and an override that reaches the gate. Six on the pool report (eight
    # hitters no longer blocking, four blocking and naming the stack bar, five
    # being exactly where "cannot fill a stack" stops being true, the bar coming
    # off MAX_HITTERS_PER_TEAM rather than a literal, an IL PITCHER no longer
    # offered as the reason a team lacks HITTERS, and a confirmed team decided
    # once instead of twice). Four on the gate agreeing with the pool it reads
    # (a stackable short team passing, an unstackable one failing, the
    # no-thin_teams fallback classifying identically across all ten counts, and
    # an excluded team at zero not counting as thin). Seven on assumption versus
    # override (no flag still failing, the lineup gate now reaching the
    # pre-export gate, a None gate still being an assumption and not an
    # override, the other five gates refused BY NAME rather than silently
    # discarded, the override record carrying the evidence it contradicts, a
    # refusal saying which of the two reasons it was, and the payload keeping the
    # two records apart). Three on the flag half (a crosswalk failure not being
    # overridable, an ordinary thin-team blocker still being overridable -- the
    # fixture that stops the regex from meaning "refuse everything" -- and the
    # override note naming the second move).
    # R234, 2026-08-24: 238 -> 254, the sixteen on the two checks standing at
    # the money boundary. Seven pin the scoped --salary auto-resolve (a
    # Showdown file refusing the Classic snapshot the pointer names, a
    # same-geometry snapshot from another night refused by rostered id, the
    # matching snapshot still resolving, an unscoped call still resolving so
    # the guard is provably the CALLER's, a corrupt pointer and a snapshotless
    # run each naming which, and the CLI exiting 3 at the flag rather than 2 on
    # a clean file). One is the R233 enumeration: both callers in tools/ scope
    # the call and a third caller fails the test. Five pin exposure counting
    # the PERSON (the captained player at his real number and alone at the top,
    # a UTIL-only bat unmoved, the CPT distribution on its own line, Classic
    # getting no captain line, and the printed lines naming their noun). Three
    # pin person_key itself, which is what a surviving mutation asked for: one
    # name on two teams is two people, one person priced twice is one key, and
    # a lineup holding both Will Smiths is not a duplicate person.
    # R266, 2026-08-29: 254 -> 270, the sixteen that pin captains counted
    # against the contest that pays them rather than against the file. Four on
    # the arithmetic (the engine's own max(1, floor(pct * n)) on the contest's
    # own n, a units slip raising instead of disabling the check silently, the
    # local units rule agreeing with contest_allocator's, and the mirrored
    # default equalling showdown's). Seven on the finding, the load-bearing pair
    # being one captain across a 2-entry contest reading 100% while the
    # PORTFOLIO line on the same file reads clean -- which is what shipped on
    # 2026-08-28. Three on severity: WARN by default, --strict-contest-diversity
    # turning the same finding into a failure, and a clean file registering
    # neither. Two end to end, one of them pinning that the advisory is computed
    # BEFORE the report dict, because built inline a strict failure lands in
    # rep.failures after `passed` has already read it as True.
    # R239(b), 2026-08-29: 270 -> 269. R266's pct-derived bar is retired for the
    # named control it disagreed with at n=3, so the two units-rule tests and the
    # pct-mirror test go with the code they covered (the mirror was unreachable
    # once the bar changed, and a guarded copy nothing calls reads as protection
    # and is not). Two tests replace three: the bar's own arithmetic, and the
    # checker pinned equal to the builder at every size.
    # R228, 2026-08-30: 269 -> 276, the seven that pin absent evidence as a
    # refusal rather than a passing check at the promotion boundary -- five on
    # promote_run (an absent artifacts row and a row with no sha256 both refused,
    # the --force-unbound acknowledgment promoting at exit 4 with the unverified
    # bind on the manifest row, a verified promotion leaving that marker off, and
    # the dry run reporting the exit code the real run would return) and two on
    # verify_manifest's copy of the same shape, where `checked` counted a row it
    # had not checked.
    # R172, 2026-08-30: 276 -> 277, the one that pins the value guard as NOT
    # enrichment. A second test in the same class changed its assertion rather
    # than being added: it pinned the defect ("enriched" for a guard-only build),
    # which is why the count moves by one and not two.
    # R173, 2026-08-30: 277 -> 281, the four that pin a truthy pool report as not
    # a checkable one -- a metadata-only stub no longer certifies the lineup gate,
    # the fall-through names it as supplied-but-uncheckable rather than absent (in
    # both the frame branch and the None branch), a genuinely absent report still
    # says absent, and either checkable key alone is enough to use the report.
    # R176, 2026-08-30: 281 -> 297. Ten in a new GateEvidenceHonestyTests -- the
    # salary gate derived from the salary export and no longer moving with the
    # projection schema, None without one, the entry-grid evidence dropping a
    # claim about a conjunct that cannot fail, caller_asserted covering every gate
    # an assertion reaches, the constant-True forced-swap key gone from both swap
    # modes with the derived keys untouched, and a failed mirror naming its reason.
    # Six on the preflight rider: a verdict that cannot be durably recorded no
    # longer exits zero (and is acknowledgeable at 4), a stamp that CLAIMS success
    # is still read back, the read-back's own contract, the stamp's new return, and
    # a superseded row reporting the status it holds rather than the verdict.
    # R275, 2026-08-31: 297 -> 306, the nine that pin the preflight's thin-row
    # trio -- an empty contest_ids and an absent, string or boolean entries count
    # FAILING rather than skipping the cross-check each feeds, both happy paths
    # (agreeing ids, a real disagreement) held so the guards did not eat them,
    # and a row with no certification landing at review_ready with a note that
    # says the evidence was never recorded rather than quoting an empty string.
    # A tenth test moved rather than grew: the R2 clean-exit test asserted
    # `upload_ready` on a loose file carrying NO manifest, which is the reserved
    # label on zero evidence -- the assertion was inverted, not loosened, and the
    # exit-code claim it exists for is untouched.
    # R267(a) + R272, 2026-08-31: 306 -> 321, the fifteen that pin the
    # single-slot repair filter -- the one-slot search finding the answer the
    # bank structurally could not, each of the six constraints removing exactly
    # the row it is for, the opposing-SP constraint (which `verify_export`
    # caught in the hand-built 1305_12g repair) refusing rather than shipping,
    # the DEAD player not barring his own replacements, a no-legal-replacement
    # refusal carrying its census and exiting 2, a refusal OUTRANKING the
    # dry-run exit code (R176's rider in a new tool), the tool picking the mode
    # on pin count rather than the caller (R267(b)), R267(c) asserted against
    # the source because it is the whole safety argument for R272's contract
    # clause, the observed tier barring a player who has already not started,
    # the review-grade labelling, slot eligibility having ONE owner shared with
    # this file's own checker, and an AMBIGUOUS --dead name refusing rather
    # than taking the first hit (the mutation survivor: the guard existed and
    # only the zero-hit half was tested, while R75 has this repo carrying two
    # Luis Garcias).
    # R287+R288, 2026-09-01: 321 -> 332, the eleven that pin the 09-01 batch's
    # tool half. Seven on the started-game hard check (the acceptance case at a
    # pinned --as-of naming the player, before-first-pitch exiting 0, the
    # boundary MINUTE counting as started, needing no lineups feed asserted
    # against the SOURCE rather than stdout because this repo HAS a feed for the
    # fixture date, --force acknowledging it, an unparseable Game Info warning
    # rather than passing, and a bare HH:MM --as-of being Eastern and not UTC --
    # which would move the comparison four hours and pass exactly the file the
    # check exists to stop). Four on the anti-correlation demotion (warning and
    # exiting 0, the count as one portfolio-level fact, a clean file carrying no
    # block at all, and --force no longer being the price of a legal roster).
    # R292 + R300(b), 2026-09-02: 332 -> 348, the sixteen that pin the repair
    # path and its clocks. Eleven on `repair_entry` -- the `--out` artifact
    # round-tripping through the loader that wrote it (one header, one entry row,
    # the dead id gone, the non-entry remainder intact) and clearing the preflight
    # it tells you to run, a candidate whose own game is UNDERWAY being refused
    # while an `unobserved` one still falls through to the feed, the observed
    # crosswalk being handed the salary PATH rather than parsed rows (the half
    # that made the `started` branch unreachable and every rostered player on a
    # live team a false scratch), one naive `--as-of` reading identically in all
    # three sibling tools, a bare HH:MM and a Zulu stamp both surviving the
    # consolidation, and `--dead-from-feed` consuming the condition the preflight
    # hard-fails while never deriving an ARM from a posted lineup (R67's bound)
    # and refusing without a feed. Three on `verify_export` -- a started player
    # being a hard failure and not a warning when NO parent resolves, the same
    # file passing before first pitch, and a legal late swap after first pitch
    # still passing WITH a parent, which is why the check sits on that branch
    # rather than running unconditionally. Two on preflight's wall-clock branch
    # (R300(b)): the real `datetime.now` path exiting 0 at now+1h and 2 at now-1h,
    # both derived at test time so neither can rot into a fixture-clock test.
    # R297(d)+R304+R305, 2026-09-06: 348 -> 367, nineteen. Seven on the
    # pitcher-row predicate: both columns read, a Classic salary agreeing with
    # the old token on every row, a declared Showdown arm acknowledged rather
    # than failed, the two counters reconciled onto the PERSON, an undeclared
    # arm still failing, a benched BAT still failing, and the partial-side site.
    # Twelve on feed identity: the rostered game set, a feed missing one of this
    # file's games, exact-outranks-superset, the compatible feed chosen over the
    # fresher one, a wrong-contest feed REFUSED (the R300(b) rider's behaviour
    # half), two equally compatible feeds refused and both named, the sibling
    # accepted and rejected on the same test, and four on DK's own Starting
    # column standing in for a feed nobody wrote.
    # R324+R314, 2026-09-08: 367 -> 383, the sixteen that pin ONE parent-
    # transition rule in both referees, each running both production entry
    # points on one file and asserting the PAIR (R52's reason: the defect was a
    # divergence, so a test on one tool cannot see it). Five on the transition
    # itself -- a swap retaining started players in unchanged slots passing both,
    # a changed slot into and out of a started game failing both, the initial
    # build's blanket refusal, and the same build passing before first pitch;
    # three on F19's unknown clock -- refused on a changed slot, carried on an
    # unchanged one, named rather than refused on an initial build; one on an
    # empty operator lock list not clearing an unknown time; two on R314's
    # postponed exemption applying in BOTH tools and preflight naming the
    # absence of a source for it; three on the entry-identity set and contest
    # reassignment; one asserting the two tools hold the same function object
    # and neither re-implements it; and one independent oracle, written from
    # scratch here, agreeing with both tools at four clocks.
    # R323, 2026-09-08: 383 -> 394, the eleven that pin the referee's side of
    # the row-versus-person count -- a dual-role complete 1-9 covering both
    # teams, a conflicting CPT/UTIL pair and a duplicate physical-player slot
    # both refusing (including one person colliding with HIMSELF on a slot,
    # which is the only fixture that can see a person-merge), a Classic file's
    # coverage unchanged, R159(a)'s degraded side still uncovered, the caller's
    # role ids surviving the collapse, the declared probable resolving to the
    # BASE id whatever order DK numbered the roles in, and three that drive
    # `preflight_upload.main`: a posted Showdown file needing no external feed
    # and RUNNING the posted-lineup check, a benched Showdown starter failing
    # it, and the counterfactual where the row count puts it back on the
    # "no feed, no check" branch.
    "tests.test_upload_integrity": 394,
    "tests.test_golden_replay": 9,
    # R117(a), 2026-08-18: 75 -> 82, the seven that pin BOTH renders of the
    # mlb.com hand line against the same paste -- the joined render derived from
    # the bare fixture (plus the guard that the transform is not a no-op), the
    # six probables and their hands identical either way, the venue untouched,
    # the end-to-end feed byte-identical, a render neither pattern knows warning
    # and dropping the held name instead of taking the venue, the venueless
    # paste that is the only fixture able to see that drop (found by mutation),
    # and `[RL]HP` opening a line not being a handedness claim by itself.
    # R133(1), 2026-08-18: 82 -> 87, the five that pin a truthful reason on a
    # side mlb.com posted COMPLETE with one starter DK never listed -- the new
    # `dk_unrostered` cause and its reason, the genuinely-short side keeping the
    # sentence that was true (the companion fixture, without which a mutation
    # stamping every side `dk_unrostered` passes), each cause landing in its own
    # list with a blocked side in neither, and such a side still being `partial`
    # rather than `confirmed`, which is what the module docstring claimed for
    # three slates and the code has never done.
    # R236, 2026-08-28: 87 -> 98, the eleven that pin the odds paste, the second
    # source a cloud session cannot fetch -- every slate game priced per named
    # book off a constructed fixture, the payload parsing back through the
    # engine's own parser, each book's posted pair surviving beside the derived
    # consensus (the straddle, from this end), the salary file's start stamped
    # rather than the paste's silence, and six refusals: an unnamed book, an
    # unresolved team, a slate game with no priced row, two rows for one book
    # that disagree (against an exact repeat, which does not block), a price
    # inside the +/-100 gap, and a header the parser cannot read.
    "tests.test_paste_lineups": 98,
    # R338 step 5, 2026-09-11. Two pytest suites the thirteenth edition wrote
    # and this gate could not see (R180(e)). Both pins are counted off a run
    # under the pinned `requirements-production.lock` stack, not off the
    # edition's paperwork.
    # test_greenfield_regressions: 29 as the edition left it, +1 for the R338
    # step 5 grep pin (no legacy module imports `mlb_engine.production` or
    # `pydantic`), which belongs in a suite rather than only in a changelog --
    # a boundary nothing executes is a boundary that rots on the next import.
    # R374 (CC-A9), 2026-09-21: 30 -> 36. Six that pin F6's two halves --
    # four on `benchmark_engine --live` (its label may not be the synthetic
    # one, the flag exists, its replay config and its helpers agree with the
    # golden replay's) and two on the measurement finding itself: the cap does
    # not govern the bank most builds deliver from, and neither golden can move
    # when it moves. The seventh pins that --live never publishes a certified
    # delivery record into the tracked ledger, which its first cut did.
    "tests.test_greenfield_regressions": 37,
    "tests.test_production": 101,
}
# The sum, not a second number to keep in step: R70 left this comment reading
# 901 while the dict already summed to 928, which is the exact staleness this
# line's own rule warns about -- the dict is the source of truth either way.
# R180(f), 2026-08-23: and it went stale AGAIN, reading 1000 against a dict
# summing to 1221 -- the file's own staleness class, fourth instance, caught by
# the ed6 review. The number is now gone rather than corrected: a comment that
# restates a computed value has no failure mode except drifting, so there is
# nothing left here to keep in step.
EXPECTED_TEST_COUNT = sum(EXPECTED_SUITE_COUNTS.values())

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
    # R135, 2026-08-17: the structural ownership prior stops being local state.
    # It sat untracked and unwired since the July scaffolding pass while three
    # docs and the ledger named it, which is R107(a)'s shape; wiring it into the
    # predict-then-grade loop carries that discipline, so it is pinned here.
    # Still review-only and never applied to projections or Ownership_Tier.
    "mlb_engine/field/ownership_prior.py": 'VERSION = "v0.1-prior"',
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
        test_env = suite_subprocess_env(root, deps=deps)
        temproot_note = pytest_temproot_warning(test_env)
        if temproot_note:
            warnings.append(temproot_note)
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
        # R148(a), three cases and one deliberate silence. A warning that
        # fires on every run in an environment that can never satisfy it
        # trains the reader to skip warnings, so "could not read" alone is
        # recorded in the JSON and says nothing here; it speaks up only when
        # the cache it cannot confirm points somewhere else.
        if fresh["default_branch_mismatch"]:
            warnings.append(
                f"GitHub's default branch is "
                f"{fresh['default_branch_mismatch']} but the work is on "
                f"{fresh['branch']}; a fresh clone lands on that default and "
                f"gets its tree")
        elif fresh["default_branch_reason"] and fresh["origin_head_cached"] \
                and fresh["origin_head_cached"] != fresh["branch"]:
            warnings.append(
                f"GitHub's default branch could not be read "
                f"({fresh['default_branch_reason']}) and this clone's cached "
                f"origin/HEAD is {fresh['origin_head_cached']} against work on "
                f"{fresh['branch']}; the cache is not evidence about GitHub, "
                f"so confirm with `git ls-remote --symref origin HEAD` from a "
                f"machine that has the credential")
        if fresh["origin_head_cache_stale"]:
            warnings.append(
                f"this clone's origin/HEAD still reads "
                f"{fresh['origin_head_cache_stale']} while GitHub's default is "
                f"{fresh['default_branch']}; a fetch never refreshes it, so "
                f"clear it with `git remote set-head origin -a` before any "
                f"reading quotes it")

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


def parse_pytest_report(text: str) -> Dict[str, Any]:
    """The same three numbers off pytest's summary line, for PYTEST_SUITES.

    Deliberately the same shape as parse_unittest_report so classify_suite,
    summarize_suite_results and assemble_gate need no runner awareness: one
    verdict vocabulary, two footers.

    pytest's footer is a comma-separated list of `<n> <outcome>` in a banner
    (`===== 1 failed, 28 passed, 1 skipped in 0.42s =====`), and the outcomes
    present depend on what happened, so each is read independently rather than
    against one combined pattern. `ran` is the SUM, because pytest reports no
    "Ran N" of its own and a pin compared against `passed` alone would read a
    suite that failed half its tests as a clean shortfall of exactly zero.
    `errors` are kept separate from `failures` for the same reason unittest
    does: an error is usually a broken fixture and a failure an assertion, and
    collapsing them hides which.

    A suite that COLLECTED nothing returns ran=0 rather than None, and
    classify_suite then calls it a shortfall against its pin. That is the case
    this function exists for: `python -m unittest tests.test_production` prints
    `Ran 0 tests ... OK`, and the old gate would have taken that as a pass.
    """
    out: Dict[str, Any] = {"ran": None, "skipped": 0, "failures": 0,
                           "errors_count": 0}
    counts = {}
    for word in ("passed", "failed", "skipped", "error", "errors", "xfailed",
                 "xpassed", "deselected"):
        found = re.search(rf"(\d+)\s+{word}\b", text)
        if found:
            counts[word] = int(found.group(1))
    if not counts and not re.search(r"no tests ran", text):
        return out
    out["skipped"] = counts.get("skipped", 0)
    out["failures"] = counts.get("failed", 0)
    out["errors_count"] = counts.get("errors", counts.get("error", 0))
    # `deselected` tests were never run and must not be counted as coverage.
    out["ran"] = sum(counts.get(w, 0) for w in
                     ("passed", "failed", "skipped", "error", "errors",
                      "xfailed", "xpassed"))
    return out


def run_one_pytest_suite(root: Path, name: str, env: Dict[str, str],
                         timeout: Optional[float] = None) -> Dict[str, Any]:
    """One PYTEST_SUITES member, whole, in its own subprocess.

    Returns a record in `parse_unittest_report`'s shape plus `present`,
    `returncode` and `ok`, so both the single-call path and the split gate can
    record it exactly as they record a unittest unit.

    pytest's own exit codes are used rather than re-derived from the counts:
    5 is "no tests collected", which is a SHORTFALL and never a pass, and 4 is
    a usage error -- most plausibly pytest not being installed at all on a host
    running from vendored `.pylibs`. Neither may read as green, so `ok` is
    exit 0 AND a count that reached the pin's shape.
    """
    path = root / "tests" / f"{name.split('.')[-1]}.py"
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", str(path), "-q",
             "-p", "no:cacheprovider"],
            cwd=str(root), text=True, capture_output=True, env=env,
            timeout=timeout)
    except FileNotFoundError:
        return {"present": True, "ran": None, "skipped": 0, "failures": 0,
                "errors_count": 0, "returncode": 4, "ok": False,
                "runner_error": "pytest is not installed for this interpreter"}
    except subprocess.TimeoutExpired:
        return {"present": True, "ran": None, "skipped": 0, "failures": 0,
                "errors_count": 0, "returncode": 124, "ok": False,
                "runner_error": f"{name} did not finish inside the call"}
    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
    rec = parse_pytest_report(combined)
    rec["present"] = True
    rec["returncode"] = proc.returncode
    rec["ok"] = proc.returncode == 0 and bool(rec.get("ran"))
    if proc.returncode == 4:
        rec["runner_error"] = ("pytest usage error; it is in "
                               "requirements-production.lock and a host "
                               "running from vendored .pylibs may not have it")
    elif proc.returncode == 5:
        rec["runner_error"] = f"{name} collected no tests"
    rec["stdout_tail"] = (proc.stdout or "")[-2000:]
    rec["stderr_tail"] = (proc.stderr or "")[-2000:]
    return rec


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


def suite_subprocess_env(root: Path, deps: Optional[Dict[str, Any]] = None,
                         artifact_root: Optional[Path] = None) -> Dict[str, str]:
    """The environment every suite subprocess this file spawns runs under.

    One function, two callers, implemented by neither -- ``run_audit``'s
    ``--run-tests`` path and ``run_gate_chunk``'s split-gate child. R233's rule
    is why it is a function: R338 named ``audit.py:1294`` and the class had TWO
    members, and the one it did not name is the one sessions actually run.

    Three things go in it:

    * ``PYTHONHASHSEED=0`` (F19). The suite includes a determinism gate, and a
      gate under a randomized hash seed cannot tell a fixed ordering from a
      lucky one.
    * ``PYTHONPATH`` for a vendored ``.pylibs`` (R42(a)). ``sys.path`` mutations
      in this process do not reach a subprocess; only env vars do. Without it
      ``--run-tests`` could fail on import errors right after ``--terse`` alone
      reported a clean dependency PASS.
    * ``MLB_DFS_ARTIFACT_ROOT``, R338 repair (4), closing R274 on the gate path.
      ``tests/conftest.py`` redirects publication defaults away from Ben's real
      ``outputs/`` and ``runs/``, and it is a PYTEST fixture: the audit runs
      ``python -m unittest``, which never loads a ``conftest.py``, so every gate
      call wrote to the real manifests. Four archived files were changed by one
      baseline suite run on 2026-09-09
      (``docs/greenfield/2026-09-09/test_artifact_incident.json``). Setting the
      variable here reaches ``upload_manifest.REPO_ROOT`` and ``mirror_to_outputs``
      in the child under either runner, and it is what makes "a ``--gate-run``
      changes no byte under ``outputs/``" checkable rather than asserted.

    An ``MLB_DFS_ARTIFACT_ROOT`` already in the environment is respected: an
    operator pinning one is telling both runners where to write.
    """
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = "0"
    if deps is None:
        deps = check_dependencies(root)
    if deps.get("vendored_pylibs"):
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = deps["vendored_pylibs"] + (
            os.pathsep + existing if existing else "")
    if artifact_root is None and not env.get("MLB_DFS_ARTIFACT_ROOT"):
        artifact_root = Path(tempfile.mkdtemp(prefix="mlb_dfs_audit_artifacts_"))
        _register_minted_root(artifact_root)
    if artifact_root is not None:
        Path(artifact_root).mkdir(parents=True, exist_ok=True)
        env["MLB_DFS_ARTIFACT_ROOT"] = str(artifact_root)
    # R348. Only when the host's own pytest temp root is unusable, and never
    # over an operator's pin. The probe is the whole opt-out: an ordinary
    # machine returns None here and this env is byte-identical to R338's.
    if not env.get(PYTEST_TEMPROOT_ENV) and pytest_base_temp_obstruction():
        env[PYTEST_TEMPROOT_ENV] = tempfile.mkdtemp(prefix=PYTEST_TEMPROOT_PREFIX)
        _register_minted_root(env[PYTEST_TEMPROOT_ENV])
    return env


def pytest_base_temp_root() -> Path:
    """Where pytest will root `tmp_path`, computed the way pytest computes it.

    R348. Deliberately re-derived rather than imported: this module must run its
    dependency checks on a host where pytest is absent (that is a real gate
    state -- `run_one_pytest_suite` reports exit 4 for it), so importing
    `_pytest.tmpdir` to ask would make the probe fail exactly where it is most
    needed. The formula is pytest's `TempPathFactory.getbasetemp`: the system
    temp directory, then `pytest-of-<user>` with every non-word character
    stripped out of the user name, and `unknown` where there is no user at all.
    """
    try:
        import getpass
        user: Optional[str] = re.sub(r"[^\w]", "", getpass.getuser())
    except Exception:  # noqa: BLE001 - any failure means pytest's own fallback
        user = None
    return Path(tempfile.gettempdir()) / f"pytest-of-{user or 'unknown'}"


def pytest_base_temp_obstruction(root: Optional[Path] = None) -> Optional[str]:
    """One line saying why pytest cannot use its own temp root, or None.

    R348. Probed rather than assumed, and probed the way pytest uses it: an
    EXISTING directory that cannot be listed or written into is the failure
    mode, because `make_numbered_dir` both reads the siblings (to pick the next
    number) and creates a child. A root that does not exist yet is not an
    obstruction -- pytest creates it, and so would this probe's own mkdir.

    Returns None on the ordinary host, so the redirect below is opt-out by
    construction: nothing is redirected on a machine that does not need it, and
    the gate's environment stays byte-identical there.
    """
    path = Path(root) if root is not None else pytest_base_temp_root()
    if not path.exists():
        return None
    probe = path / ".mlbgate_probe"
    try:
        os.listdir(path)
        probe.mkdir(exist_ok=True)
    except OSError as exc:
        return f"{type(exc).__name__}: {exc.strerror or exc}"
    finally:
        with contextlib.suppress(OSError):
            probe.rmdir()
    return None


def _isolated_pytest_temproot(env: Dict[str, str]) -> Optional[Path]:
    """The throwaway pytest temp root this module minted, or None.

    R348, and the same rule `_isolated_artifact_root` states for the same
    reason: only a path this module created carries the prefix, so an operator
    who pinned their own ``PYTEST_DEBUG_TEMPROOT`` never has it deleted.
    """
    value = env.get(PYTEST_TEMPROOT_ENV)
    if not value:
        return None
    path = Path(value)
    return path if path.name.startswith(PYTEST_TEMPROOT_PREFIX) else None


def cleanup_isolated_roots(env: Dict[str, str]) -> None:
    """Remove every throwaway root ``suite_subprocess_env`` minted for this env.

    R348 rider. This was three identical two-line pairs against
    ``_isolated_artifact_root`` (``run_audited_suites`` and both arms of
    ``run_gate_chunk``), and adding a second throwaway root to each of them by
    hand is exactly the N-sites-and-the-class-has-N+1 shape R233 is filed on.
    One function, three callers, implemented by none of them.
    """
    for reader in (_isolated_artifact_root, _isolated_pytest_temproot):
        throwaway = reader(env)
        if throwaway is None:
            continue
        key = os.path.normcase(os.path.abspath(str(throwaway)))
        if key not in _MINTED_ROOTS:
            # Inherited from a parent process that is still using it. The prefix
            # says "a root some audit made"; only the registry says "mine".
            continue
        shutil.rmtree(throwaway, ignore_errors=True)
        _MINTED_ROOTS.discard(key)


def pytest_temproot_warning(env: Dict[str, str]) -> Optional[str]:
    """The warning a redirected pytest temp root owes the operator, or None.

    R348. A gate that silently worked around a broken host would be a gate that
    stops reporting the host. CLAUDE.md's session-start step already says a
    clean run prints the pinned line exactly and anything else APPENDS what is
    abnormal; this is one of those, and it is a warning rather than an error
    because every test really did run and really did pass.
    """
    redirected = _isolated_pytest_temproot(env)
    if redirected is None:
        return None
    return (f"pytest's own temp root {pytest_base_temp_root()} is not usable by "
            f"this user, so the two pytest suites ran under {redirected} "
            f"instead. They are the gate's only users of tmp_path; left alone, "
            f"that directory errors every test in both and the gate reads a "
            f"green tree as a failing suite. Remove it (it may need elevation) "
            f"or pin {PYTEST_TEMPROOT_ENV} yourself")


def _isolated_artifact_root(env: Dict[str, str]) -> Optional[Path]:
    """The throwaway root ``suite_subprocess_env`` minted, or None if it did not.

    Named rather than inlined so the cleanup can never delete an operator's own
    pinned ``MLB_DFS_ARTIFACT_ROOT``: only a path this module created under the
    system temp directory carries the prefix.
    """
    value = env.get("MLB_DFS_ARTIFACT_ROOT")
    if not value:
        return None
    path = Path(value)
    if path.name.startswith("mlb_dfs_audit_artifacts_"):
        return path
    return None


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
    results: Dict[str, Any] = {}
    stdout_tail = ""
    stderr_tail = ""
    # R338 repair (4). PER SUITE, matching the isolation the subprocess split
    # already buys: a suite that publishes must not be able to see, reuse or
    # clobber what the previous suite published either.
    base = test_env.get("MLB_DFS_ARTIFACT_ROOT")

    try:
        for name in AUDITED_SUITES:
            path = root / "tests" / f"{name.split('.')[-1]}.py"
            if not path.exists():
                results[name] = classify_suite(name, {"present": False, "ran": None})
                continue
            suite_env = dict(test_env)
            if base:
                per_suite = Path(base) / name.split(".")[-1]
                per_suite.mkdir(parents=True, exist_ok=True)
                suite_env["MLB_DFS_ARTIFACT_ROOT"] = str(per_suite)
            # R338 step 5. The runner is a property of the suite, not of the
            # path: both callers below pick it the same way, off PYTEST_SUITES.
            if name in PYTEST_SUITES:
                rec = run_one_pytest_suite(root, name, suite_env)
                rec["passed"] = bool(rec.pop("ok", False))
                out_tail = rec.pop("stdout_tail", "")
                err_tail = rec.pop("stderr_tail", "")
                results[name] = classify_suite(name, rec)
                if not rec["passed"]:
                    stdout_tail = out_tail
                    stderr_tail = err_tail
                continue
            proc = subprocess.run(
                [sys.executable, "-m", "unittest", name],
                cwd=str(root), text=True, capture_output=True, env=suite_env,
            )
            combined = proc.stdout + "\n" + proc.stderr
            rec = parse_unittest_report(combined)
            rec["present"] = True
            rec["returncode"] = proc.returncode
            rec["passed"] = proc.returncode == 0
            results[name] = classify_suite(name, rec)
            if proc.returncode != 0:
                stdout_tail = proc.stdout[-2000:]
                stderr_tail = proc.stderr[-4000:]
    finally:
        cleanup_isolated_roots(test_env)

    return summarize_suite_results(results, stdout_tail=stdout_tail,
                                   stderr_tail=stderr_tail)


def summarize_suite_results(results: Dict[str, Any], stdout_tail: str = "",
                            stderr_tail: str = "") -> Dict[str, Any]:
    """One verdict out of the per-suite verdicts, for either path.

    R152 extracted this from run_audited_suites so the split-run gate assembles
    its answer with the SAME function rather than a second copy of the rules.
    A copy is what the tests would then pin -- R133 landed that lesson on a
    fixture that had copied a fifteen-line gate merge, and this is the same
    shape one layer out. What lives here is the split CLAUDE.md acts on: a
    count mismatch is bookkeeping to fix after the slate, a failing suite is
    not.
    """
    errors: List[str] = []
    warnings: List[str] = []
    runtime_count = sum(r["ran"] for r in results.values()
                        if isinstance(r.get("ran"), int))
    total_skipped = sum(r.get("skipped", 0) for r in results.values())
    count_ok = runtime_count == EXPECTED_TEST_COUNT
    suite_ok = not any(r.get("present", True) and not r.get("passed")
                       for r in results.values())

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


# ---------------------------------------------------------------------------
# R152: the gate across several calls.
#
# CLAUDE.md's session-start step 2 is one command, and in a cloud Cowork
# session it cannot finish. R271(b), 2026-08-29, RETIRED the 45s figure this
# comment carried: the real `device_bash` ceiling is ~180s when the call passes
# an explicit timeout. The split survives the correction because its reason was
# never one suite -- tests.test_core alone measured 89s (84.9s of tests plus a
# 4.2s import) on 2026-08-18, and the five gated suites together do not fit 180
# either. What the correction changes is the SIZE of each slice, which is why
# CLAUDE.md now says to pass `--gate-budget 130 --gate-ceiling 165` and gets the
# whole assembly in one warm call or five cold ones, against the twenty-odd the
# defaults below force. Backgrounding it is worse than useless -- nohup and setsid both
# die when the call returns, the log comes back EMPTY, which looks exactly like
# a silent pass, and a killed audit.py leaves a zero-byte .git/index.lock that
# strands the session's commit half an hour later (R109).
#
# So the split is a supported path rather than a session improvising one:
# `--gate-run` until it says complete, then `--gate-report`. Three rules hold
# it honest.
#   1. Only a COMPLETE assembly may print the clean full-gate line. A partial
#      one prints GATE INCOMPLETE and exits 3. The pinned string is what
#      CLAUDE.md quotes and what test_the_clean_pass_line_is_the_one_CLAUDE_md_
#      quotes fixes byte for byte; a partial run printing it would be the
#      false-signal family arriving inside the gate itself.
#   2. Complete means every enumerated CLASS of every audited suite has a
#      record -- not that the counts happen to sum. A count can be reached by
#      a suite that grew while another lost coverage; a class list cannot.
#   3. Every record carries a fingerprint of the tree it ran against, and the
#      report refuses a mixed set. Chunks measured against different code are
#      not evidence about either tree.
# The verdicts themselves go through classify_suite and summarize_suite_results,
# the same two functions the single-call path uses, so the split path cannot
# drift into a second opinion about what `shortfall` means.
GATE_DIR = ".audit_gate"
GATE_UNITS_FILE = "units.jsonl"
GATE_TIMINGS_FILE = "timings.json"
# The child stops taking new classes at the deadline and the parent allows it a
# margin to finish the one in flight.
#
# 28.0 and the 39.0 below were derived from a 45s device ceiling that R271(b)
# RETIRED on 2026-08-29 (the real figure is ~180s with an explicit timeout).
# They are KEPT anyway and the reason is that a default is a floor, not a
# measurement: this value has to be safe on a host that has told us nothing,
# and every host that can do better says so through --gate-budget /
# --gate-ceiling / MLB_GATE_CEILING_S. Changing the default would be a
# behaviour change for every silent caller, measured on one host. CLAUDE.md's
# session-start command passes 130/165 explicitly and that is the supported way
# up. What is NOT kept is any comment or --help string still asserting 45.
# What the parent keeps for itself out of the call: container start, the engine
# import off a cold __pycache__, and printing the report. The child's budget is
# the rest.
GATE_BUDGET_RESERVE_S = 11.0
#: Floor, so a host declaring an absurdly small ceiling still gets a budget a
#: single test class can land inside rather than a negative number.
GATE_MIN_BUDGET_S = 20.0


def resolved_gate_budget() -> float:
    """The child's default budget on THIS host, not a constant.

    R358, 2026-09-19. This was 28.0 and the ceiling below 39.0, both derived
    from a 45s device ceiling that R271(b) RETIRED on 2026-08-29. The comment
    that kept them argued a default must be safe on a host that has told us
    nothing -- which is right, and is now `repo_env`'s job: a host that states
    nothing resolves to 130.0 there, which is CLAUDE.md's own Sandbox number
    rather than a figure measured on one machine. What changed is that a host
    which DOES say something is believed. Measured 2026-09-19 on a container
    declaring 900000ms: `--run-tests` completes in one call in about 230s, so a
    28s child budget was slicing a gate that did not need slicing.

    Both flags and the whole precedence are unchanged; only the default moved.
    """
    return max(GATE_MIN_BUDGET_S, round(call_budget_s() - GATE_BUDGET_RESERVE_S, 1))


GATE_DEFAULT_BUDGET_S = resolved_gate_budget()
GATE_DEFAULT_BUDGET_SOURCE = call_budget_source()
# The whole call, parent included: an overrun takes the parent's own report with
# it, so the parent stops the child while it can still print what landed.
#
# R190(d), 2026-08-23: 39.0 is the DEFAULT and no longer the only value.
# `--gate-budget` was already tunable and it did nothing on its own, because
# this ceiling capped the child underneath it -- raising the budget to 90 still
# killed the child at 39s, which reads exactly like a test that cannot finish.
# A unit needing more than ~39s therefore accumulated two "started" records,
# got marked `oversized`, and the gate became STRUCTURALLY unable to print its
# clean line: `DeterminismTests.test_solver_inputs_are_identical_across_hash_seeds`
# measured 11.36s when R152 landed and 36.4s on 2026-08-23 in a container whose
# own call cap is ~178s. That is R152's own lesson -- "the device VM is not a
# constant and no fixed chunk plan survives it" -- arriving at the CALL CEILING
# rather than the chunk plan, and a constant measured against one host is the
# staleness class this file keeps rediscovering. So the ceiling is now the host's
# to state: `--gate-ceiling`, or `MLB_GATE_CEILING_S`, floored at the budget plus
# a margin so a raised budget can never again be silently capped underneath.
# Nothing about the conservative device default changes; a caller that says
# nothing gets exactly the old behaviour.
GATE_CALL_CEILING_S = call_budget_s()
GATE_CEILING_ENV = "MLB_GATE_CEILING_S"


def gate_call_ceiling(explicit: "float | None" = None,
                      budget: "float | None" = None) -> float:
    """The wall-clock ceiling this host allows one --gate-run child.

    Precedence: an explicit flag, then ``MLB_GATE_CEILING_S``, then this host's
    resolved ``GATE_CALL_CEILING_S``. When a budget IS stated the result is
    floored at ``budget + GATE_UNKNOWN_RESERVE_S``, so a raised ``--gate-budget``
    cannot be capped by a lower ceiling without the caller having asked for
    that, which is the defect R190(d) fixed.

    R358, 2026-09-19: ``budget`` became ``None``-by-default rather than bound to
    ``GATE_DEFAULT_BUDGET_S``, and the floor now applies only when a budget was
    actually supplied. With the default budget host-resolved (619.0 on a
    container declaring 900000ms) the old form silently raised an explicit
    ``--gate-ceiling 150`` to 629.0 -- overriding a stated operator instruction,
    which is the opposite of what the floor is for. Both internal callers
    (``:2528``, ``:2561``) pass ``budget=`` explicitly, so the protected case is
    unchanged; what changed is that asking for the ceiling alone now answers
    about the ceiling alone.
    """
    value = explicit
    if value is None:
        raw = os.environ.get(GATE_CEILING_ENV, "").strip()
        if raw:
            try:
                value = float(raw)
            except ValueError:
                value = None
    if value is None:
        value = GATE_CALL_CEILING_S
    if budget is None:
        return float(value)  # no budget stated, so there is nothing to protect
    return max(float(value), float(budget) + GATE_UNKNOWN_RESERVE_S)
# The room an UNRECORDED class must have before it may start. A count-based
# guess is useless here -- DeterminismTests is 4 tests and 24.5s while
# PortfolioFrontierTests is 27 tests and 0.11s -- so the first pass buys its
# knowledge by running things, and the reserve bounds what that costs. It is
# deliberately not the slowest class measured: a reserve that large spends
# two thirds of every call waiting, and the downside of guessing low is only
# that the parent cuts the child off and the class is retried FIRST on the
# next call, with the whole budget to itself.
GATE_UNKNOWN_RESERVE_S = 10.0
# Records older than this are not evidence about the tree now: the fingerprint
# covers the code, nothing covers the reference data or the interpreter.
GATE_MAX_AGE_H = 6.0


def tree_fingerprint(root: Path) -> str:
    """Content hash of every .py the gate could be measuring.

    Content, never mtime: this mount hands git different mtimes for identical
    bytes (docs/cowork_sync_protocol.md), so an mtime fingerprint would refuse
    a valid split run at random. The file LIST is hashed too, so an added or
    deleted module moves it even when no surviving file changed.
    """
    parts: List[str] = []
    for folder in ("mlb_engine", "tools", "tests", "skills/generate-lineups/scripts"):
        base = root / folder
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.py")):
            if "__pycache__" in path.parts or any(
                    seg.startswith("_scratch_") for seg in path.parts):
                continue
            try:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                digest = "unreadable"
            parts.append(f"{path.relative_to(root).as_posix()}:{digest}")
    configuration = [root / "requirements.lock", root / "requirements-production.lock",
                     root / "pyproject.toml"]
    for folder in (root / "config", root / "configs", root / "schemas"):
        if folder.exists():
            configuration.extend(p for p in folder.rglob("*") if p.is_file())
    for path in sorted(configuration):
        if path.is_file():
            parts.append(f"{path.relative_to(root).as_posix()}:{hashlib.sha256(path.read_bytes()).hexdigest()}")
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:16]


def gate_units_path(root: Path) -> Path:
    return root / GATE_DIR / GATE_UNITS_FILE


def _gate_append(root: Path, record: Dict[str, Any]) -> None:
    """One JSON object per line, flushed as it lands.

    The child writes here directly rather than handing results back through
    its exit, because the call around it can be killed at any moment: a killed
    call must lose the class in flight and nothing else.
    """
    path = gate_units_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
        handle.flush()


def read_gate_units(root: Path) -> List[Dict[str, Any]]:
    """Every record on disk. A malformed line is skipped, never fatal: a call
    killed mid-write leaves a partial line and that is not a reason to lose the
    other forty."""
    path = gate_units_path(root)
    if not path.exists():
        return []
    out: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict):
            out.append(record)
    return out


def gate_reset(root: Path) -> None:
    """Truncate in place. The mount grants create and truncate but not unlink
    (R109), so `open("w")` is the delete that works here."""
    path = gate_units_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")


def _gate_timings(root: Path) -> Dict[str, float]:
    path = root / GATE_DIR / GATE_TIMINGS_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: float(v) for k, v in data.items()
            if isinstance(v, (int, float))} if isinstance(data, dict) else {}


def _gate_record_timings(root: Path, learned: Dict[str, float]) -> None:
    """Kept OUTSIDE the fingerprint, deliberately: how long a unit takes is not
    a claim about the tree's correctness, and losing it on every edit would
    make the first pass after every commit the slow one."""
    timings = _gate_timings(root)
    for key, seconds in learned.items():
        timings[key] = round(seconds, 2)
    path = root / GATE_DIR / GATE_TIMINGS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(timings, indent=1, sort_keys=True),
                    encoding="utf-8")


def assemble_gate(root: Path, fingerprint: Optional[str] = None) -> Dict[str, Any]:
    """Per-suite verdicts out of the recorded units, plus what is still owed.

    The verdicts come from classify_suite, so `shortfall`, `skipped_in_place`,
    `absent` and `grew` mean here exactly what they mean in the single-call
    path -- three of them LOST COVERAGE and only `grew` a stale pin.

    Completeness is CLASS COVERAGE and never the count. A suite whose recorded
    units happen to sum to its pin can still be missing a class, if another
    class grew by as much as the missing one held; a class list cannot be
    reached that way. The count is then checked on top, by classify_suite,
    which is where a real shortfall or a stale pin gets named.
    """
    fingerprint = fingerprint or tree_fingerprint(root)
    units = read_gate_units(root)
    stale = sorted({r.get("fingerprint") for r in units
                    if r.get("fingerprint") != fingerprint})
    mine = [r for r in units if r.get("fingerprint") == fingerprint]
    enums = {r["suite"]: r for r in mine if r.get("kind") == "enum"}

    results: Dict[str, Any] = {}
    owed: Dict[str, Any] = {}
    coverage: Dict[str, Any] = {}
    oversized: List[str] = []
    unfinished: List[str] = []
    for name in AUDITED_SUITES:
        enum = enums.get(name)
        recs = [r for r in mine if r.get("kind") == "unit"
                and r.get("suite") == name]
        recorded = {r.get("cls") for r in recs}
        oversized += [f"{name.split('.')[-1]}.{r.get('cls')}" for r in mine
                      if r.get("kind") == "oversized" and r.get("suite") == name]
        attempts = sorted(_gate_unit_attempts(units, name, fingerprint))
        if enum is None:
            owed[name] = None  # never enumerated: the suite has not started
            coverage[name] = {"ran": 0, "classes": None}
            continue
        classes = enum.get("classes") or {}
        missing = [cls for cls, methods in classes.items()
                   if cls not in recorded
                   and not all(f"{cls}.{m}" in recorded for m in methods)]
        covered = len(classes) - len(missing)
        coverage[name] = {"ran": covered, "classes": len(classes)}
        # A breadcrumb is a question, and covering the class ANSWERS it: the
        # class-level attempt that was cut off stays unmatched forever once the
        # fallback finishes the same class by method, and reporting it after
        # that is a gate carrying noise about work it has already done.
        unfinished += [f"{name.split('.')[-1]}.{unit}" for unit in attempts
                       if unit.split(".")[0] in set(missing)]
        if missing:
            owed[name] = missing
        if not enum.get("present", True):
            results[name] = classify_suite(name, {"present": False, "ran": None})
            continue
        rec = {
            "present": True,
            "ran": sum(int(r.get("ran") or 0) for r in recs),
            "skipped": sum(int(r.get("skipped") or 0) for r in recs),
            "failures": sum(int(r.get("failures") or 0) for r in recs),
            "errors_count": sum(int(r.get("errors_count") or 0) for r in recs),
        }
        rec["passed"] = all(r.get("ok") for r in recs) and not missing
        rec["returncode"] = 0 if rec["passed"] else 1
        results[name] = classify_suite(name, rec)

    ages = [r.get("ts") for r in mine if r.get("ts")]
    age_h = None
    if ages:
        try:
            oldest = min(datetime.fromisoformat(t) for t in ages)
            age_h = round((datetime.now(timezone.utc) - oldest).total_seconds()
                          / 3600.0, 1)
        except ValueError:
            age_h = None

    return {
        "fingerprint": fingerprint,
        "stale_fingerprints": stale,
        "suite_results": results,
        "owed": owed,
        "coverage": coverage,
        "complete": not owed and len(results) == len(AUDITED_SUITES),
        "age_hours": age_h,
        "unfinished_units": sorted(set(unfinished)),
        "oversized_units": sorted(set(oversized)),
    }


def _gate_unit_attempts(units: List[Dict[str, Any]], suite: str,
                        fingerprint: str) -> Dict[str, int]:
    """Units that were STARTED and never finished, counted per unit id.

    The breadcrumb is what turns "the call died" into a diagnosis. One
    unfinished attempt on a CLASS means the class is too big for a call here
    and the next run splits it into its own test methods; two on a METHOD
    means the gate cannot be run in this environment at this budget, which is
    a refusal to report and not a thing to keep retrying.
    """
    started: Dict[str, int] = {}
    finished: Dict[str, int] = {}
    for record in units:
        if record.get("suite") != suite or record.get("fingerprint") != fingerprint:
            continue
        key = record.get("cls")
        if record.get("kind") == "started":
            started[key] = started.get(key, 0) + 1
        elif record.get("kind") == "unit":
            finished[key] = finished.get(key, 0) + 1
    return {k: v - finished.get(k, 0) for k, v in started.items()
            if v - finished.get(k, 0) > 0}


def _gate_child(root: Path, suite: str, deadline: float,
                fingerprint: str) -> int:
    """Run one suite's units, one at a time, until the deadline is near.

    ONE suite per child, never two. The single-call path gives each suite its
    own subprocess because a suite that asserts on process state can pass
    purely because an earlier suite dirtied the interpreter (R59), and a child
    that mixed suites would hand that back.

    A unit is a test CLASS, so setUpClass runs once per class exactly as it
    does in `python -m unittest <suite>`. A class that has already been cut off
    once is re-run as its individual METHODS instead: that changes setUpClass
    to once per test, which is why it is the fallback and not the default.
    Measured 2026-08-18 on the device VM, and the reason the fallback exists:
    DeterminismTests did not finish in 42s, and one of its four tests
    (test_solver_inputs_are_identical_across_hash_seeds, which spawns a process
    per hash seed) took 35.8s of that by itself.
    """
    import unittest as _unittest
    sys.path.insert(0, str(root))
    units = read_gate_units(root)
    mine = [r for r in units if r.get("suite") == suite
            and r.get("fingerprint") == fingerprint]
    done = {r.get("cls") for r in mine if r.get("kind") == "unit"}
    unfinished = _gate_unit_attempts(units, suite, fingerprint)
    have_enum = any(r.get("kind") == "enum" for r in mine)

    loader = _unittest.TestLoader()
    loaded = loader.loadTestsFromName(suite)
    buckets: Dict[str, Dict[str, Any]] = {}

    def walk(node: Any) -> None:
        for item in node:
            if isinstance(item, _unittest.TestSuite):
                walk(item)
            else:
                buckets.setdefault(type(item).__name__, {})[
                    item.id().rsplit(".", 1)[-1]] = item

    walk(loaded)
    classes = {name: sorted(methods) for name, methods in sorted(buckets.items())}
    if not have_enum:
        _gate_append(root, {
            "kind": "enum", "suite": suite, "classes": classes,
            "tests": sum(len(m) for m in classes.values()), "present": True,
            "fingerprint": fingerprint,
            "ts": datetime.now(timezone.utc).isoformat()})

    # What to run, in order, as (unit id, tests). A class already carrying an
    # unfinished attempt -- or already half-recorded by method -- is expanded.
    plan: List[Any] = []
    for name, methods in classes.items():
        split = unfinished.get(name, 0) > 0 or any(
            f"{name}.{m}" in done for m in methods)
        if not split:
            if name not in done:
                plan.append((name, [buckets[name][m] for m in methods]))
            continue
        for method in methods:
            unit_id = f"{name}.{method}"
            if unit_id not in done:
                plan.append((unit_id, [buckets[name][method]]))

    timings = _gate_timings(root)
    learned: Dict[str, float] = {}
    ran_here = 0
    for unit_id, tests in plan:
        attempts = unfinished.get(unit_id, 0)
        if "." in unit_id and attempts >= 2:
            # A single test that will not finish here. Say so once, in the
            # record, and stop spending calls on it.
            if not any(r.get("kind") == "oversized" and r.get("cls") == unit_id
                       for r in mine):
                _gate_append(root, {
                    "kind": "oversized", "suite": suite, "cls": unit_id,
                    "attempts": attempts, "fingerprint": fingerprint,
                    "ts": datetime.now(timezone.utc).isoformat()})
            continue
        left = deadline - time.time()
        known = timings.get(f"{suite}.{unit_id}")
        if ran_here:
            # Never start something that will not fit. An unrecorded unit is
            # not guessed at: it gets a reserve, or it waits for the next call.
            # The first unit of a batch always runs, so the gate cannot stall.
            if known is not None:
                if known * 1.25 + 1.0 > left:
                    break
            elif left < GATE_UNKNOWN_RESERVE_S:
                break
        _gate_append(root, {
            "kind": "started", "suite": suite, "cls": unit_id,
            "fingerprint": fingerprint,
            "ts": datetime.now(timezone.utc).isoformat()})
        stream = io.StringIO()
        started_at = time.time()
        with contextlib.redirect_stdout(stream):
            result = _unittest.TextTestRunner(stream=stream, verbosity=0).run(
                _unittest.TestSuite(tests))
        seconds = time.time() - started_at
        _gate_append(root, {
            "kind": "unit", "suite": suite, "cls": unit_id,
            "ran": result.testsRun, "skipped": len(result.skipped),
            "failures": len(result.failures), "errors_count": len(result.errors),
            "ok": result.wasSuccessful(), "seconds": round(seconds, 2),
            "fingerprint": fingerprint,
            "ts": datetime.now(timezone.utc).isoformat()})
        learned[f"{suite}.{unit_id}"] = seconds
        ran_here += 1
    if learned:
        # Once per batch, not once per unit: the record that must survive a
        # killed call is the unit line above, and rewriting this file 800 times
        # over a full gate costs more than the knowledge is worth.
        _gate_record_timings(root, learned)
    return 0


def gate_run(root: Path, budget: float = GATE_DEFAULT_BUDGET_S,
             ceiling: "float | None" = None) -> Dict[str, Any]:
    """One call's worth of the gate. Run it again until it says complete."""
    started_at = time.time()
    fingerprint = tree_fingerprint(root)
    units = read_gate_units(root)
    reset = bool(units) and any(r.get("fingerprint") != fingerprint
                                for r in units)
    if reset:
        # The tree moved under a run in progress. Records from before it are
        # about other code; keeping them would let a report assemble a verdict
        # no single tree ever produced.
        gate_reset(root)

    state = assemble_gate(root, fingerprint)
    if state["complete"]:
        return {"complete": True, "reset": reset, "ran_suite": None,
                "state": state, "note": "gate complete: run --gate-report"}

    suite = next((n for n in AUDITED_SUITES if n in state["owed"]), None)
    path = root / "tests" / f"{suite.split('.')[-1]}.py"
    if not path.exists():
        # An audited suite that is not on disk is a finding, not a chunk to
        # run: classify_suite calls it `absent` and names it lost coverage.
        _gate_append(root, {
            "kind": "enum", "suite": suite, "classes": [], "tests": 0,
            "present": False, "fingerprint": fingerprint,
            "ts": datetime.now(timezone.utc).isoformat()})
        state = assemble_gate(root, fingerprint)
        return {"complete": state["complete"], "reset": reset,
                "ran_suite": suite, "state": state,
                "note": f"{suite} is not on disk"}

    # R338 repair (4). The same environment `--run-tests` builds, from the same
    # function -- this is the path that actually runs the gate, so this is the
    # call that closes R274 on it.
    env = suite_subprocess_env(root)

    # R338 step 5. A PYTEST_SUITES member is one unit and runs here, in the
    # parent, rather than in `--gate-child`: the child is a unittest loader
    # (`_unittest.TestSuite(tests)`) and has no way to hold a pytest test. It
    # still goes through `_gate_append` in the same two record shapes every
    # other suite uses, so `assemble_gate` needs no special case and
    # completeness stays class coverage -- the class here being the module, at
    # the granularity this suite is run.
    if suite in PYTEST_SUITES:
        allowed = gate_call_ceiling(ceiling, budget=budget)
        left = max(5.0, allowed - (time.time() - started_at))
        rec = run_one_pytest_suite(root, suite, env, timeout=left)
        stem = suite.split(".")[-1]
        now = datetime.now(timezone.utc).isoformat()
        _gate_append(root, {
            "kind": "enum", "suite": suite, "classes": {stem: []},
            "tests": rec.get("ran") or 0, "present": True,
            "fingerprint": fingerprint, "ts": now})
        _gate_append(root, {
            "kind": "unit", "suite": suite, "cls": stem,
            "ran": rec.get("ran") or 0, "skipped": rec.get("skipped", 0),
            "failures": rec.get("failures", 0),
            "errors_count": rec.get("errors_count", 0),
            "ok": bool(rec.get("ok")), "seconds": round(time.time() - started_at, 2),
            "fingerprint": fingerprint, "ts": now})
        cleanup_isolated_roots(env)
        state = assemble_gate(root, fingerprint)
        return {"complete": state["complete"], "reset": reset,
                "ran_suite": suite, "state": state,
                "timed_out": rec.get("returncode") == 124,
                "child_error": rec.get("runner_error"),
                "note": "gate complete: run --gate-report" if state["complete"]
                else "more units remain: run --gate-run again"}

    deadline = time.time() + budget
    # Two clocks, and they are different promises. `budget` is when the child
    # stops STARTING units; the ceiling is when the parent gives up on the one
    # in flight. Sizing the kill off the budget instead would cut off exactly
    # the units that need a whole call to themselves.
    # R190(d): the ceiling is the HOST's to state, not a constant measured
    # against one. `gate_call_ceiling` also floors it above the budget, so a
    # raised --gate-budget can never again be silently capped underneath.
    allowed = gate_call_ceiling(ceiling, budget=budget)
    ceiling = max(5.0, allowed - (time.time() - started_at))
    timed_out = False
    child = None
    try:
        child = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--gate-child",
             suite, "--gate-deadline", repr(deadline),
             "--gate-fingerprint", fingerprint],
            cwd=str(root), env=env, capture_output=True, text=True,
            timeout=ceiling)
    except subprocess.TimeoutExpired:
        timed_out = True
    finally:
        cleanup_isolated_roots(env)
    state = assemble_gate(root, fingerprint)
    # A child that died for its OWN reason (an import error, a crash) leaves no
    # unit record and no breadcrumb, and would otherwise read as "no progress".
    child_error = None
    if child is not None and child.returncode != 0:
        child_error = (child.stderr or child.stdout or "").strip()[-400:]
    return {"complete": state["complete"], "reset": reset, "ran_suite": suite,
            "state": state, "timed_out": timed_out, "child_error": child_error,
            "note": "gate complete: run --gate-report" if state["complete"]
            else "more units remain: run --gate-run again"}


def gate_run_line(outcome: Dict[str, Any]) -> str:
    """Progress, never a verdict. Nothing this prints may begin with PASS."""
    state = outcome["state"]
    parts = []
    for name in AUDITED_SUITES:
        cover = state["coverage"].get(name) or {}
        total = cover.get("classes")
        parts.append(f"{name.split('.')[-1]} "
                     f"{cover.get('ran', 0)}/{'?' if total is None else total}")
    head = "GATE COMPLETE" if outcome["complete"] else "GATE PROGRESS"
    line = f"{head}  " + "; ".join(parts)
    if outcome.get("reset"):
        line += "  [tree changed since the last unit: state reset]"
    if outcome.get("timed_out"):
        line += (f"  [the call was cut off before its class finished; "
                 f"raise --gate-budget or run it alone]")
    if state["unfinished_units"]:
        line += ("  [started and never finished, split into methods on the "
                 "next call: " + ", ".join(state["unfinished_units"]) + "]")
    if state["oversized_units"]:
        line += ("  [does not finish in one call here: "
                 + ", ".join(state["oversized_units"]) + "]")
    if outcome.get("child_error"):
        line += "  [child exited non-zero: " + outcome["child_error"] + "]"
    return line + "  -> " + outcome["note"]


def gate_report(root: Path, allow_fetch: bool = True) -> Dict[str, Any]:
    """The assembled verdict, or a refusal that names what is missing.

    Returns a run_audit-shaped result when the gate is complete, so
    terse_output formats it -- one formatter for both paths, which is what
    keeps the clean line byte-identical and the abnormal decorations the same.
    """
    fingerprint = tree_fingerprint(root)
    state = assemble_gate(root, fingerprint)
    refusals: List[str] = []
    if state["stale_fingerprints"]:
        refusals.append(
            f"{len(state['stale_fingerprints'])} recorded unit(s) ran against "
            f"a different tree than the one on disk now; chunks measured "
            f"against different code are not evidence about either. Re-run "
            f"with --gate-reset")
    if state["age_hours"] is not None and state["age_hours"] > GATE_MAX_AGE_H:
        refusals.append(
            f"the oldest recorded unit is {state['age_hours']}h old (limit "
            f"{GATE_MAX_AGE_H}h); the fingerprint covers code and nothing "
            f"covers the reference data or the interpreter. Re-run with "
            f"--gate-reset")
    if not state["complete"]:
        owed = []
        for name, missing in state["owed"].items():
            short = name.split(".")[-1]
            owed.append(f"{short} not started" if missing is None
                        else f"{short} owes {len(missing)} class(es)")
        refusals.append("gate not complete: " + "; ".join(owed))
    if state["oversized_units"]:
        # The honest floor. Some environments cannot run some tests inside one
        # call, and the answer is to say which and where to run them, never to
        # report a gate that skipped them.
        refusals.append(
            "does not finish in one call at this budget: "
            + ", ".join(state["oversized_units"])
            + ". Raise --gate-budget, or run the gate in the container where "
              "the whole suite fits one process")
    if refusals:
        return {"gate_complete": False, "refusals": refusals, "state": state}

    summary = summarize_suite_results(state["suite_results"])
    result = run_audit(root, run_tests=False, allow_fetch=allow_fetch)
    result["errors"].extend(summary.pop("_errors"))
    result["warnings"].extend(summary.pop("_warnings"))
    result["checks"]["tests"] = summary
    # R348. The split gate mints its redirect inside a `--gate-run` that has
    # already exited by the time anyone reads the verdict, so the note cannot
    # ride the env the way `--run-tests`'s does. Re-PROBE instead: the
    # obstruction is a property of the host, not of the run, and a host still
    # obstructed at report time is a host whose operator still needs telling.
    if pytest_base_temp_obstruction():
        result["warnings"].append(
            f"pytest's own temp root {pytest_base_temp_root()} is not usable by "
            f"this user; --gate-run redirected the two pytest suites to a "
            f"throwaway root. Remove it (it may need elevation) or pin "
            f"{PYTEST_TEMPROOT_ENV} yourself")
    result["passed"] = not result["errors"]
    result["summary"] = "Audit passed" if result["passed"] else "Audit failed"
    result["gate_complete"] = True
    result["gate_state"] = {k: state[k] for k in
                            ("fingerprint", "age_hours", "coverage")}
    return result


def gate_report_line(result: Dict[str, Any], root: Path) -> str:
    """A refusal never wears the clean line's clothes: it starts with GATE
    INCOMPLETE, which no reader and no test can mistake for PASS."""
    if not result.get("gate_complete"):
        return "GATE INCOMPLETE  " + ";  ".join(result["refusals"])
    return terse_output(result, root)


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
# this is checked at the source instead of only reported downstream. That skill
# has since been shortened to 993 (it rode R142's commit, 189de4f, unremarked),
# so 1073 is the history and not a current reading -- re-measure before citing
# it, which is this check's whole point.
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
def _sync_check():
    """`sync_check` as a module, imported from BESIDE this file.

    Not from the audited root, which is what the three copies of this import
    used to do. The classifier and the token resolver are properties of this
    tool, not of the tree being audited, so pointing them at `root` made every
    audit of anything other than this repo report "sync_check unavailable" --
    including every temp-repo fixture, where it hid the difference between a
    classified failure and no classifier at all.
    """
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import sync_check  # type: ignore
        return sync_check
    except Exception:
        return None


def _credentialed_git_env(root: Path) -> Dict[str, Any]:
    """An environment that hands git a token through GIT_ASKPASS and nothing else.

    R148(a) extracted this out of ``_try_git_fetch`` so the fetch and the
    default-branch read share ONE credential path rather than two copies of it.
    A copy is what the tests would then pin (R133's lesson, one layer out), and
    the rule this carries is the one rule that cannot be relaxed: the token
    reaches git through GIT_ASKPASS and an env var and NEVER through argv, a
    remote URL, ``.git/config``, or any stream this process prints.

    Returns ``env: None`` with a named ``reason`` when no credential is
    reachable; a caller that does not need one (a path remote, a public repo)
    may still run git with its own environment.
    """
    out: Dict[str, Any] = {"env": None, "credential": None, "reason": None}
    sync = _sync_check()
    if sync is None:
        out["reason"] = "sync_check unavailable"
        return out
    try:
        name, token = sync.find_token()
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
    except OSError:
        out["reason"] = "askpass could not be written"
        return out
    env = dict(os.environ)
    env.update({"AUDIT_GIT_TOKEN": token, "GIT_ASKPASS": str(askpass),
                "GIT_TERMINAL_PROMPT": "0"})
    out.update(env=env, credential=name)
    return out


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
    sync = _sync_check()
    if sync is None:
        out["reason"] = "sync_check unavailable"
        return out
    classify_git_failure = sync.classify_git_failure
    cred = _credentialed_git_env(root)
    if cred["env"] is None:
        out["reason"] = cred["reason"]
        return out

    try:
        done = subprocess.run(["git", "fetch", "--quiet", "origin"],
                              cwd=str(root), capture_output=True, text=True,
                              timeout=timeout, env=cred["env"])
        if done.returncode == 0:
            out.update(fetched=True, credential=cred["credential"])
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


def _fetch_reason_is_network(root: Path, reason: Optional[str]) -> bool:
    """Did the fetch fail because nothing outbound works from here?

    R147 classifies a failure into three; only the network one makes a SECOND
    remote call pointless. A rejected credential is not the same fact: a path
    remote and a public repo both answer ls-remote without one.
    """
    sync = _sync_check()
    if sync is None:
        return False
    return bool(reason) and sync.GIT_FAIL_NETWORK in reason


def _read_remote_default_branch(root: Path, timeout: int = 15) -> Dict[str, Any]:
    """GitHub's OWN default branch, which only ``ls-remote --symref`` can read.

    R148(a). ``origin/HEAD`` in a clone is a cache written by the last
    ``clone`` or ``set-head`` and a fetch never refreshes it, so a check
    against it returns the same answer whatever GitHub does -- it agreed with
    the local ref through the entire week the documents were wrong, and it
    would be equally silent if the default moved again tomorrow. This is the
    one call that asks the remote.

    Read-only by choice: ``git remote set-head -a`` would answer the same
    question by WRITING the cache, which hides the reading inside a side
    effect and leaves the audit having modified the repo it is auditing.

    Same credential discipline as the fetch, through the shared helper. The
    reason on failure is R147's three-way classification and never git's own
    stream, which can echo a URL.
    """
    out: Dict[str, Any] = {"branch": None, "reason": None}
    sync = _sync_check()
    classify_git_failure = (sync.classify_git_failure if sync is not None
                            else lambda stream: "sync_check unavailable")
    cred = _credentialed_git_env(root)
    env = cred["env"] or dict(os.environ, GIT_TERMINAL_PROMPT="0")
    try:
        done = subprocess.run(
            ["git", "ls-remote", "--symref", "origin", "HEAD"],
            cwd=str(root), capture_output=True, text=True, timeout=timeout,
            env=env)
    except subprocess.TimeoutExpired:
        out["reason"] = f"ls-remote exceeded {timeout}s"
        return out
    except (OSError, subprocess.SubprocessError):
        out["reason"] = "ls-remote could not run"
        return out
    if done.returncode != 0:
        out["reason"] = "ls-remote failed: " + classify_git_failure(done.stderr)
        return out
    found = re.search(r"^ref:\s+refs/heads/(\S+)\s+HEAD$", done.stdout, re.M)
    if not found:
        # A remote that answers without a symref line has no default to read
        # (an empty repo, or a HEAD pointing outside refs/heads). Silent, not
        # clean: the caller must not read a missing branch as agreement.
        out["reason"] = "the remote answered with no symbolic HEAD"
        return out
    out["branch"] = found.group(1)
    return out


def git_freshness(root: Path, allow_fetch: bool = True) -> Dict[str, Any]:
    """How far the clone is from the last remote state it actually saw.

    ``ahead`` needs a push (Ben's action, per docs/cowork_sync_protocol.md);
    ``behind`` needs a pull (the session's). ``fetch_age_hours`` is what both
    numbers are worth: measured against the remote-tracking ref, which moves
    only on fetch or push, so a long-stale fetch means ``behind: 0`` proves
    nothing.

    ``default_branch_mismatch`` is GitHub's own default when it differs from
    the checked-out branch, and R148(a) is the reason it is worth this much
    prose. It used to compare the branch against this clone's cached
    ``origin/HEAD`` -- a copy of the default from whenever ``set-head`` last
    ran, which no fetch refreshes -- so it returned ``null`` whether or not
    GitHub agreed, and a null read as agreement. That is a check that cannot
    fail. It now reads the remote through ``ls-remote --symref`` and reports
    which source answered:

      - ``default_branch_source: "remote"`` -- asked GitHub. A null mismatch
        here means checked and agrees.
      - ``default_branch_source: None`` with ``default_branch_reason`` set --
        NOT read, in R147's three-way form (no network / rejected credential /
        unknown). A null mismatch here means nothing at all. The device VM of a
        cloud Cowork session lives here permanently.

    The reading that closed R111(b) is also the shape a citation should take
    here. From Ben's Windows machine on 2026-08-18:
    ``git ls-remote --symref origin HEAD`` -> ``ref: refs/heads/main  HEAD``,
    and ``git fetch --prune`` -> ``- [deleted] (none) -> origin/master``. The
    same command returned ``master`` on 2026-08-11 and both readings were true
    when taken, which is why the command and its output are the citation and
    the person who ran it is not.

    ``origin_head_cached`` is the local cache kept beside it, and
    ``origin_head_cache_stale`` names it when the remote disagrees: a fresh
    clone follows GitHub, but ``git clone`` from a stale cache is not the
    failure -- reading that cache AS GitHub is, and that is what this
    separates.

    Silent without git, without a remote, or on a branch with no upstream.
    """
    out: Dict[str, Any] = {"available": False, "ahead": 0, "behind": 0,
                           "fetch_age_hours": None, "branch": None,
                           "default_branch": None,
                           "default_branch_source": None,
                           "default_branch_reason": None,
                           "default_branch_mismatch": None,
                           "origin_head_cached": None,
                           "origin_head_cache_stale": None,
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
    out["origin_head_cached"] = head_ref.split("/")[-1] if head_ref else None

    # R148(a): ask the remote, and when that cannot happen say so by name. The
    # second call is skipped only when the fetch already proved there is no
    # network -- a rejected credential is not proof, since a path remote and a
    # public repo both answer without one.
    if not allow_fetch:
        out["default_branch_reason"] = (
            "--no-fetch: GitHub's default branch was not read")
    elif not out["fetched"] and _fetch_reason_is_network(
            root, out["fetch_reason"]):
        out["default_branch_reason"] = out["fetch_reason"]
    else:
        read = _read_remote_default_branch(root)
        out["default_branch"] = read["branch"]
        out["default_branch_reason"] = read["reason"]

    if out["default_branch"]:
        out["default_branch_source"] = "remote"
        out["default_branch_reason"] = None
        if out["default_branch"] != branch:
            # Not an error: it is legitimate to work off the default branch. It
            # IS worth saying, because a fresh clone lands on GitHub's default
            # and gets that branch's tree.
            out["default_branch_mismatch"] = out["default_branch"]
        if out["origin_head_cached"] \
                and out["origin_head_cached"] != out["default_branch"]:
            out["origin_head_cache_stale"] = out["origin_head_cached"]
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
    # R152: the same gate across several calls, for a caller whose per-call
    # ceiling cannot hold --run-tests. R358, 2026-09-19: that caller is now the
    # exception rather than the assumption. Measured on a container declaring
    # 900000ms, `--run-tests` completes in one call in about 230s and CI runs it
    # in one step; the split path is for Cowork's ~130s inner budget and for any
    # host that states a small ceiling. Both defaults below are resolved from
    # `repo_env.call_budget_s()`, so the split happens where it is needed and
    # not where it is not.
    parser.add_argument("--gate-run", action="store_true",
                        help="run as much of the gate as fits one call, "
                             "recording per-class results; repeat until it "
                             "says complete. Exit 0 complete, 3 more remains")
    parser.add_argument("--gate-report", action="store_true",
                        help="assemble the recorded units into one verdict. "
                             "Exit 0 pass, 1 fail, 3 incomplete or refused")
    parser.add_argument("--gate-reset", action="store_true",
                        help="drop the recorded units and start the gate over")
    parser.add_argument("--gate-budget", type=float,
                        default=GATE_DEFAULT_BUDGET_S,
                        help="seconds of testing one --gate-run may start "
                             f"(default {GATE_DEFAULT_BUDGET_S:.0f} on this "
                             f"host: {GATE_DEFAULT_BUDGET_SOURCE}, less a "
                             f"{GATE_BUDGET_RESERVE_S:.0f}s parent reserve). "
                             "Lower it to assemble the gate across more, "
                             "smaller calls")
    parser.add_argument("--gate-ceiling", type=float, default=None,
                        help="seconds of wall clock one --gate-run child may "
                             f"use (default {GATE_CALL_CEILING_S:.0f} on this "
                             "host, resolved from its own declared ceiling; "
                             "also read from "
                             f"{GATE_CEILING_ENV}). Raise it on a host with a "
                             "longer call cap: a unit slower than the ceiling "
                             "can never land, and the gate then cannot print "
                             "its clean line at all")
    parser.add_argument("--gate-child", nargs=1, help=argparse.SUPPRESS)
    parser.add_argument("--gate-deadline", help=argparse.SUPPRESS)
    parser.add_argument("--gate-fingerprint", help=argparse.SUPPRESS)
    args = parser.parse_args()
    root = Path(args.root)

    if args.gate_child:
        raise SystemExit(_gate_child(root, args.gate_child[0],
                                     float(args.gate_deadline),
                                     args.gate_fingerprint))
    if args.gate_reset:
        gate_reset(root)
        print("gate state reset")
        if not (args.gate_run or args.gate_report):
            raise SystemExit(0)
    if args.gate_run:
        outcome = gate_run(root, budget=args.gate_budget,
                           ceiling=args.gate_ceiling)
        print(gate_run_line(outcome))
        raise SystemExit(0 if outcome["complete"] else 3)
    if args.gate_report:
        assembled = gate_report(root, allow_fetch=not args.no_fetch)
        if args.terse or not args.output:
            print(gate_report_line(assembled, root))
        else:
            print(json.dumps(assembled, indent=2, sort_keys=True))
        if not assembled.get("gate_complete"):
            raise SystemExit(3)
        raise SystemExit(0 if assembled["passed"] else 1)

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
