#!/usr/bin/env python3
"""build_slate.py -- one command from uploaded DK files to a certified upload file.

Detects Classic vs Showdown from the files themselves, stages inputs, builds the
pool, decides a solve strategy that fits the execution budget, builds, certifies,
verifies, and writes a short brief.

Resumability is the point of --max-seconds. Bash calls in Cowork are killed the
moment the call returns, so an unbounded build produces no output and no
diagnostic and you cannot tell a hard slate from a hung one. This script does as
much as fits, persists the candidate bank, and exits 10 to mean "run me again".
Each rerun picks up where the last one stopped.

Exit codes:
    0   certified file written
    10  partial progress saved, run the same command again
    3   build ran but did not certify (errors printed)
    4   inputs missing or unreadable

Every number this prints is a deterministic review proxy or a labeled prior.
Nothing here is ROI, win rate, cash rate, or a probability claim. Nothing here
touches DraftKings: lineups and money move only at Ben's manual upload.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import os
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Mapping

# F19: pinned before anything else runs, because the interpreter reads
# PYTHONHASHSEED at startup and setting it later does nothing. This is the
# build that writes the file Ben uploads, so "same inputs, same file" has to be
# true here or it is not true anywhere. Solver-facing collections are sorted
# regardless; this closes the gap for anything the sorting misses.
#
# Only when run as a script. The test suite imports this module to drive its
# functions directly, and a module-level execve would replace the test runner's
# process on import.
if (__name__ == "__main__" and os.environ.get("PYTHONHASHSEED") != "0"
        and sys.executable):
    try:
        os.execve(sys.executable, [sys.executable, *sys.argv],
                  {**os.environ, "PYTHONHASHSEED": "0"})
    except OSError:
        pass  # a slate that builds on an unpinned seed beats one that does not


def _find_repo() -> Path:
    """Locate the mlb-dfs engine root.

    An installed skill lives outside the repo, so the root cannot be derived from
    __file__ alone. Order: explicit env var, then a walk up from this file (works
    when the skill is versioned inside the repo), then the usual workspace mount
    paths. Failing loudly here beats importing a half-present package later.
    """
    import os

    env = os.environ.get("MLB_DFS_ROOT")
    if env and (Path(env) / "mlb_engine").is_dir():
        return Path(env)
    for parent in Path(__file__).resolve().parents:
        if (parent / "mlb_engine").is_dir() and (parent / "CLAUDE.md").exists():
            return parent
    for guess in (
        Path.home() / "Documents" / "Claude" / "mlb-dfs",
        Path("/sessions") / "mnt" / "mlb-dfs",
    ):
        if (guess / "mlb_engine").is_dir():
            return guess
    for mount in Path("/sessions").glob("*/mnt/mlb-dfs"):
        if (mount / "mlb_engine").is_dir():
            return mount
    raise SystemExit(
        "cannot locate the mlb-dfs engine. Set MLB_DFS_ROOT to the repo root."
    )


REPO = _find_repo()
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

SALARY_CAP = 50000
CLASSIC_SLOTS = ("P", "P", "C", "1B", "2B", "3B", "SS", "OF", "OF", "OF")
MAX_HITTERS_PER_TEAM = 5
MIN_GAMES_PER_LINEUP = 2

# R98(1). Both bank budgets in this script are `max(what is left of the window,
# BANK_BUDGET_FLOOR_S)`. When the floor wins, the search is no longer bounded by
# the operator's --max-seconds; it is bounded by a constant, and the thin bank
# that follows is an infrastructure limit reaching through to shape strategy.
# CLAUDE.md permits an infrastructure limit to reduce search effort and forbids
# it changing the legal player set -- but the permission is only honest while
# the reduction is visible. On the 1910_9g build it was not: the brief recorded
# `time_budget_s: 5.0` with nothing to distinguish a deliberate five seconds
# from a window that had already run out, and the operator read a 1.8%-explored
# bank as a considered set of caps. So a floored budget announces itself, both
# on stderr and in the record.
BANK_BUDGET_FLOOR_S = 5.0

# --------------------------------------------------------------------------- #
# R290(c) commit 1, 2026-09-03. Every refusal this script can hand its caller,
# and WHAT CLASS of thing failed at it.
#
# Why this is a table and not a paragraph. The deadline governor's acceptance
# criterion is "refusal must be unreachable while entries are blank and time
# remains", which is a claim over every refusal exit in this file, and the
# post-mortem that asked for it treated them as one. They are not one. The
# post-mortem's own O3 clause draws the line correctly -- refusal is only
# correct when the file would be ILLEGAL, never when it is merely badly shaped
# -- and applied per site that line does not fall in one place. A `--deliver-by`
# that covers one exit, in front of an operator inside a lock window, reads as
# though it covers the deadline; that is this repo's named false-reassurance
# failure with a command-line switch on it.
#
# Why it is keyed on a KEY and not on a line number or a status string. Line
# numbers moved three times in three days while this item sat: the entry's own
# table, its ed10 rider and R296(h) each measured a different set. And the
# status strings do not identify a site -- `pool_blocked` is printed by two
# different refusals with opposite classifications, and `not_certified` by two
# in different contest types. The key is stamped INTO the printed payload, so
# the artifact names its own class instead of a reader inferring it (R237).
#
# The three classes, defined by what the governor may do, not by how bad the
# news is:
#   ILLEGAL       DraftKings would reject the file, or a named hard wall in
#                 CLAUDE.md forbids the override. Refusal is correct at any
#                 clock and the governor may NEVER reach it. Read `authority`
#                 to see which of the two it is; they are not the same fact and
#                 this table does not blur them.
#   BADLY-SHAPED  what failed is one of Ben's own portfolio preferences, or
#                 search effort. The file is LEGAL and merely more concentrated,
#                 or thinner, than was asked for. This is the governor's set,
#                 and it is the set CLAUDE.md means by "if the choice is a
#                 concentrated file or no file, ship the concentrated file".
#   READ-IT       the refusal reports a fact about the INPUTS or the RECORD,
#                 not about the shape of the output. No relaxation rung reaches
#                 it, an operator override already exists where one is
#                 appropriate, and pressing it is a judgment a clock cannot
#                 supply. The governor refuses too, and names the flag.
#
# Two sites are SPLIT: one exit code standing over several distinct failures
# with different classes. Those carry `klass=REFUSAL_SPLIT` and a sub-map, and
# the split is the substantive finding of this commit -- see CLASSIC_GATE_CLASS
# and VERIFY_CLASSIC_FAILURE_CLASS.
# --------------------------------------------------------------------------- #
REFUSAL_ILLEGAL = "illegal"
REFUSAL_BADLY_SHAPED = "badly_shaped"
REFUSAL_READ_IT = "read_it"
REFUSAL_SPLIT = "split"

REFUSAL_SITES = (
    {
        "key": "pool_blocked_hard",
        "exit_code": 3,
        "prints_status": "pool_blocked",
        "klass": REFUSAL_READ_IT,
        "authority": "input_identity",
        "override": "--ignore-pool-blockers",
        "why": "the pool this build would use is structurally wrong for this "
               "slate, so the file is a certified file for a DIFFERENT slate. "
               "No relaxation of any output control changes that, which is why "
               "no ladder rung reaches it. The override exists and pressing it "
               "means classifying a specific blocker benign -- the one input a "
               "clock cannot supply.",
    },
    {
        "key": "pool_blocked_crosswalk",
        "exit_code": 3,
        "prints_status": "pool_blocked",
        "klass": REFUSAL_ILLEGAL,
        "authority": "claude_md_wall",
        "override": None,
        "why": "a name-crosswalk failure. NOT a DK rule, and this table says so "
               "rather than letting the class name imply one: the authority is "
               "CLAUDE.md's hard list, which names this stop-and-ask above all "
               "others, and R133, which made --ignore-pool-blockers refuse it "
               "BY NAME instead of spending the build and losing it at the "
               "gate. The real posted lineup is in hand and a projection is "
               "being substituted for it.",
    },
    {
        "key": "bank_thin_partial",
        "exit_code": 10,
        "prints_status": "partial",
        "klass": REFUSAL_BADLY_SHAPED,
        "authority": "search_effort",
        "override": None,
        "why": "the sliced bank holds fewer than twice the entry count and the "
               "job list is not exhausted. This site is ABSENT from the R290 "
               "entry's table, which enumerated `return 3` while the class is "
               "refusal EXITS -- eleventh member, found by asking the right "
               "question (R233). It belongs to the governor for the sharpest "
               "possible reason: the remedy it prints is 'run the same command "
               "again to add a slice', which is the one remedy a deadline "
               "cannot buy, and a thin bank is search effort and never a "
               "reduction of the legal player set.",
    },
    {
        "key": "classic_not_certified",
        "exit_code": 3,
        "prints_status": "not_certified",
        "klass": REFUSAL_SPLIT,
        "authority": "see CLASSIC_GATE_CLASS",
        "override": None,
        "why": "ONE exit standing over an allocation failure, six post-export "
               "gates and the contest-identity blockers. The 1940_9g refusal is "
               "the allocation-failed member, where the allocator never passed "
               "and nothing is on disk. The gate members are the opposite case: "
               "the lineups exist and a candidate file is already written at "
               "runs/<run_id>/candidate/DO_NOT_UPLOAD_DKEntries.csv, so there "
               "is nothing left to relax and the only question is the label. "
               "Four of the six gates are DK rules, one is provenance, and one "
               "is Ben's own exposure preference; classifying the exit as a "
               "unit would have made the governor either useless or unsafe.",
    },
    {
        "key": "classic_verify_failed",
        "exit_code": 3,
        "prints_status": "brief",
        "klass": REFUSAL_SPLIT,
        "authority": "see VERIFY_CLASSIC_FAILURE_CLASS",
        "override": None,
        "why": "verify_classic on the DELIVERED file, which by this point "
               "exists and is mirrored. Six of its seven failure kinds are DK "
               "rules and refusal is right. The seventh is a blank roster cell, "
               "and that one kind covers two different facts the check cannot "
               "currently tell apart: a PARTIALLY filled row, which DK rejects, "
               "and an ALL-blank reserved row, which DK simply does not enter.",
    },
    {
        "key": "showdown_ladder_infeasible",
        "exit_code": 3,
        "prints_status": "ladder_infeasible",
        "klass": REFUSAL_BADLY_SHAPED,
        "authority": "ben_preference",
        "override": "--controls-override",
        "why": "solve_ladder left at least one thesis unsolved under the three "
               "Showdown portfolio controls. All three are Ben's own, the "
               "relaxation ORDER is already documented and counted in CLAUDE.md "
               "(overlap, then player exposure, then captain lock, then "
               "thesis), and a relaxed rung ships a legal file. This is the "
               "governor's set and the ladder already exists for it.",
    },
    {
        "key": "showdown_bank_short",
        "exit_code": 3,
        "prints_status": "bank_short",
        "klass": REFUSAL_BADLY_SHAPED,
        "authority": "search_effort",
        "override": None,
        "why": "build_showdown_bank returned fewer lineups than entries under "
               "the same three caps. Search effort against preferences, not a "
               "legality wall.",
    },
    {
        "key": "showdown_not_certified",
        "exit_code": 3,
        "prints_status": "not_certified",
        "klass": REFUSAL_ILLEGAL,
        "authority": "dk_rule",
        "override": None,
        "why": "certify_showdown failed on at least one lineup: exactly one "
               "CPT, five UTIL, no player in two slots, and a salary recomputed "
               "from the pool's own role columns under the cap. Every member is "
               "a DK rejection.",
    },
    {
        "key": "showdown_bank_short_of_reserved_rows",
        "exit_code": 3,
        "prints_status": "bank_short_of_reserved_rows",
        "klass": REFUSAL_BADLY_SHAPED,
        "authority": "ben_wall",
        "override": None,
        "why": "the bank is shorter than the reserved-row count, so rows would "
               "ship blank. Ben's guardrail blocks CERTIFICATION on a blank "
               "reserved row and R290(c) is the decision that it stops blocking "
               "DELIVERY -- thirty-seven blank entries is a washout with "
               "certainty 1.0, not a hedge against one. The site's own note "
               "already prints the governor's rung ('lower --entries-count to "
               "the number built'), which is why this is the clearest member "
               "of the badly-shaped set rather than the most doubtful.",
    },
    {
        "key": "showdown_export_failed",
        "exit_code": 3,
        "prints_status": "showdown_export_failed",
        "klass": REFUSAL_ILLEGAL,
        "authority": "dk_rule",
        "override": None,
        "why": "write_showdown_entries refused, so no DK-valid file was "
               "produced. There is nothing to deliver and nothing to relax.",
    },
    {
        "key": "showdown_template_broken",
        "exit_code": 3,
        "prints_status": "brief",
        "klass": REFUSAL_ILLEGAL,
        "authority": "dk_rule",
        "override": None,
        "why": "verify_template_preserved found a non-roster cell changed, so "
               "the file is no longer the template DK issued -- the row count, "
               "an Entry ID, a contest id or a fee. DK rejects or misattributes "
               "it and no label makes that safe.",
    },
)
REFUSAL_BY_KEY = {r["key"]: r for r in REFUSAL_SITES}

# The SPLIT half of `classic_not_certified`, one row per post-export gate, and
# it is the finding this commit exists for. `roster_legality_passed` is
# everything in dk_entries_manager's validator that is NOT an exposure or
# overlap error; `portfolio_caps_passed` is exactly the exposure and overlap
# errors (player, pitcher, primary-stack, SP-pair, per-game caps and
# max_shared_players), all of which are Ben's own numbers and every one of
# which DK accepts. So the single exit that lost 1940_9g cannot distinguish "DK
# will reject this" from "this is more concentrated than you asked for", and
# the second is the whole reason the governor exists.
CLASSIC_GATE_CLASS = {
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
# A gate this table has never classified is READ-IT, and the default is a
# safety property rather than a convenience: the governor never passes what it
# has not been told about. It should never fire --
# `test_every_workflow_gate_is_classified` asserts every name in both gate
# tuples has a row above, so a gate added to the engine without a row here
# fails the suite instead of silently becoming relaxable.
CLASSIC_GATE_CLASS_DEFAULT = (REFUSAL_READ_IT, "unclassified")


def classic_gate_class(name: str) -> tuple:
    return CLASSIC_GATE_CLASS.get(name, CLASSIC_GATE_CLASS_DEFAULT)


def refusal_class_of_failed_gates(failed_gates) -> dict:
    """Classify a Classic gate refusal, gate by gate, worst class first.

    The block is BADLY-SHAPED only when EVERY failing gate is, which is the
    conservative direction: one DK rejection among five preference misses is
    still a file DK rejects.
    """
    names = [str(n) for n in (failed_gates or [])]
    per_gate = {n: classic_gate_class(n) for n in names}
    classes = {k for k, _ in per_gate.values()}
    if not names:
        overall = REFUSAL_BADLY_SHAPED  # the allocation-failed member; no gate named
    elif REFUSAL_ILLEGAL in classes:
        overall = REFUSAL_ILLEGAL
    elif REFUSAL_READ_IT in classes:
        overall = REFUSAL_READ_IT
    else:
        overall = REFUSAL_BADLY_SHAPED
    return {
        "refusal_class": overall,
        "refusal_class_by_gate": {n: k for n, (k, _) in per_gate.items()},
        "refusal_authority_by_gate": {n: a for n, (_, a) in per_gate.items()},
    }

# The SPLIT half of `classic_verify_failed`. Keys are the `kind` tags
# verify_classic now emits beside its human-readable failure strings; the
# strings are unchanged for every existing reader.
VERIFY_CLASSIC_FAILURE_CLASS = {
    "blank_row": (REFUSAL_BADLY_SHAPED, "ben_wall"),
    "partial_row": (REFUSAL_ILLEGAL, "dk_rule"),
    "unknown_player_id": (REFUSAL_ILLEGAL, "dk_rule"),
    "over_cap": (REFUSAL_ILLEGAL, "dk_rule"),
    "duplicate_player": (REFUSAL_ILLEGAL, "dk_rule"),
    "slot_ineligible": (REFUSAL_ILLEGAL, "dk_rule"),
    "team_stack_over_max": (REFUSAL_ILLEGAL, "dk_rule"),
    "too_few_games": (REFUSAL_ILLEGAL, "dk_rule"),
}

# What this table deliberately does NOT cover, stated here rather than left to
# be discovered, because "which exits does the governor not reach" is the
# question the item makes the governor answer out loud.
#
# EXIT 4, fourteen sites (run_classic:1 through leverage_unresolved,
# run_showdown:3, main:10). Every one refuses BEFORE anything is solved: a
# missing or unreadable salary file, a feed for another slate, a flag value this
# build cannot use, a projections file that will not parse. R296(h) moved
# `supplied_feed_rejected` here from exit 3 for exactly this reason and it is
# the worked example -- nothing was solved, so there is no verdict for a
# supervisor to retry against and no shape for a ladder to relax. A deadline
# does not conjure a salary file. These stay refusals at every clock.
#
# EXIT 2 is not produced by this script; it is preflight_upload's blocked
# verdict, and SKILL.md's four-exit-code table describes that tool rather than
# this one. Named because the two vocabularies collide: exit 3 means BUILT AND
# REFUSED here and IO ERROR there.
REFUSAL_OUT_OF_SCOPE = {
    4: "refused before any solve; no verdict to retry and no shape to relax",
}


def refusal_stamp(key: str, **extra) -> dict:
    """The classification, in the refusal's own payload.

    Every refusal in this script prints JSON. Until now that JSON said WHAT
    failed and never what CLASS of thing failed, so a session under a clock had
    to infer whether it was looking at a DK rejection or at its own exposure
    cap -- and on 1940_9g it inferred wrong, cited the portfolio-level washout
    clause, and delivered nothing. The stamp is three keys and it removes the
    inference. Raises on an unknown key on purpose: a refusal site added
    without a row in REFUSAL_SITES is the N+1 this table exists to prevent, and
    `test_every_refusal_exit_is_classified` catches it before it ships.
    """
    rec = REFUSAL_BY_KEY[key]
    out = {
        "refusal": key,
        "refusal_class": rec["klass"],
        "refusal_authority": rec["authority"],
    }
    if rec.get("override"):
        out["refusal_override"] = rec["override"]
    out.update(extra)
    return out

# R98(2). Which failing feasibility checks name a floor the ENGINE derived from
# the slate, and which name a number that is merely the minimum clearing THIS
# bank. `max_shared_players` below the inherent stack-plus-pair overlap is
# arithmetically impossible: no two lineups sharing a five-man stack can overlap
# less, so raising it to that floor changes nothing about the portfolio. An
# exposure cap has no such floor, and raising one concentrates the entered set.
# The old hint called both "not a strategy or player-pool change", which is how
# 1910_9g moved three exposure caps from 0.35/0.43 to 0.56.
STRUCTURAL_FEASIBILITY_CHECKS = frozenset({"shared_players_floor", "sp_pair_capacity"})

# R167. Every control in --controls-override that is a FRACTION of the entered
# set, Classic and Showdown together. Named rather than pattern-matched on
# `_pct`: the engine also carries ownership percentages in 0-100 space, and a
# suffix rule would reject those on sight. Both contest types are listed here
# because Showdown does not pass through the engine's control merge, so this
# is the only boundary that sees a Showdown override at all.
FRACTION_CONTROL_KEYS = (
    "max_player_exposure_pct",
    "max_pitcher_exposure_pct",
    "max_primary_stack_exposure_pct",
    "min_five_stack_share_pct",
    "max_cpt_exposure_pct",
)

# R215(a). The sixth fraction control, and the reason it needs its own tuple:
# it is a mapping of game id -> fraction, so the units question is about each
# VALUE. It was in neither key set while all three `_game_cap_count` sites
# clamped, so `{"401234": 40}` for 0.40 passed this gate, passed the engine
# merge, and capped nobody in the solve or in the post-export validator, with
# no counter and no warning. `late_swap.py` steers operators to override
# exactly this control.
FRACTION_CONTROL_DICT_KEYS = (
    "max_game_exposure_pct_by_game",
)


def fraction_or_problem(value: Any) -> tuple:
    """``(coerced float, None)`` or ``(None, why it is not a fraction)``.

    The operator-facing mirror of ``contest_allocator.assert_fraction_cap``:
    same four rejections, no engine import, and it costs no seconds. A value
    of 0 or below is legal and means "not set" for a ceiling or "no quota" for
    a floor, which every posture relies on shipping.
    """
    if isinstance(value, bool):
        # bool is a subclass of int, so `True` used to coerce to 1.0 in
        # silence: a cap switched off with no name (R215(b)).
        return None, "a boolean, not a fraction"
    try:
        coerced = float(value)
    except (TypeError, ValueError):
        return None, "not a number"
    if coerced != coerced or coerced in (float("inf"), float("-inf")):
        # NaN clears every `> 1.0` test and dies later inside math.floor,
        # after the bank has spent (R215(b)).
        return None, "not a finite number"
    if coerced > 1.0:
        return None, "above 1.0"
    return coerced, None


def resolve_bank_budget(computed_s: float, *, label: str) -> tuple[float, bool]:
    """Return ``(budget_s, floored)`` and SAY SO when the floor wins (R98(1))."""
    floored = float(computed_s) < BANK_BUDGET_FLOOR_S
    budget = max(float(computed_s), BANK_BUDGET_FLOOR_S)
    if floored:
        print(
            f"BANK BUDGET FLOORED ({label}): {float(computed_s):.1f}s remained of "
            f"--max-seconds after reserve, so the {BANK_BUDGET_FLOOR_S:g}s engine "
            f"floor applies. This bank is bounded by a constant, not by the window "
            f"you asked for. If the build then refuses, grow the bank (re-run; the "
            f"build exits 10 and resumes) or raise --max-seconds -- do not relax "
            f"portfolio controls against a bank this size.",
            file=sys.stderr,
        )
    return budget, floored


def infeasibility_hint(
    feasibility: Mapping[str, Any] | None,
    bank_report: Mapping[str, Any] | None,
) -> str | None:
    """R98(2). Remedies in the order that fixes the actual problem.

    Returns None when there is nothing honest to say. Silence is correct for a
    refusal on an exhausted bank with no failing structural check: the allocator
    has already named what it proved, and inventing a remedy here would be the
    guess this item exists to remove.
    """
    parts: list[str] = []
    report = bank_report or {}
    if report.get("job_list_exhausted") is False:
        attempted = report.get("jobs_attempted")
        total = report.get("jobs_total")
        scope = ""
        if attempted is not None and total:
            scope = (f" ({int(attempted)} of {int(total)} jobs attempted, "
                     f"{float(attempted) / float(total) * 100:.1f}%)")
        floored = (" Its time budget also hit the engine floor, so the slice was "
                   "bounded by a constant." if report.get("budget_floored") else "")
        parts.append(
            f"GROW THE BANK FIRST. The job list was not exhausted{scope}, so this "
            f"refusal is about the candidates that got built, not about the slate."
            f"{floored} Re-run the SAME command: the build exits 10 and resumes into "
            f"the same cache. Relaxing a control now fits the portfolio to a partial "
            f"search and records the result as a deliberate cap."
        )
    structural: list[str] = []
    strategy: list[str] = []
    for check in ((feasibility or {}).get("checks") or []):
        if check.get("passed") is False and check.get("remedy"):
            line = f"{check.get('name')}: {check['remedy']}"
            (structural if check.get("name") in STRUCTURAL_FEASIBILITY_CHECKS
             else strategy).append(line)
    if structural:
        parts.append(
            "ARITHMETIC, not strategy -- " + "; ".join(structural)
            + ". These are structural floors of this slate; raising the control to "
            "the named floor removes an impossibility and changes nothing else."
        )
    if strategy:
        parts.append(
            "A STRATEGY DECISION -- " + "; ".join(strategy)
            + ". Exposure caps have NO engine-named floor. The value above is the "
            "minimum that clears this build, not a recommendation, and adopting it "
            "concentrates the entered set."
        )
    if not parts:
        return None
    if structural or strategy:
        parts.append("Apply control changes with --controls-override "
                     "'{\"max_shared_players\": <n>, ...}'.")
    return " ".join(parts)


# --------------------------------------------------------------------------- #
# Contest-type detection: the files already answer this, so never ask.
# --------------------------------------------------------------------------- #
def detect_contest_type(salary_csv: Path, entries_csv: Path) -> str:
    """Return 'showdown' or 'classic'.

    DK declares the roster geometry in both files: a Showdown salary file lists
    Roster Position CPT/UTIL and its entries header is CPT,UTIL x5, while Classic
    lists P/C/1B/... and P,P,C,1B,2B,3B,SS,OF,OF,OF. Reading it beats asking.
    """
    with entries_csv.open(encoding="utf-8-sig", newline="") as fh:
        header = next(csv.reader(fh), [])
    if "CPT" in header:
        return "showdown"
    with salary_csv.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            if str(row.get("Roster Position", "")).strip().upper() in ("CPT", "UTIL"):
                return "showdown"
            break
    return "classic"


def slate_date_from_salary(salary_csv: Path) -> str:
    from mlb_engine.intake.slate_intake_manager import (
        parse_dk_salary_csv, parse_game_info_datetime,
    )
    for sp in parse_dk_salary_csv(str(salary_csv)):
        parsed = parse_game_info_datetime(sp.game_info)
        if parsed is not None:
            return parsed.date().isoformat()
    # ET, not the container's calendar: a salary file we could not date at all
    # must still fall back to the day the schedule is on (R65).
    from mlb_engine.repo_env import today_et
    return today_et()


def rotowire_window(slate_date: str, today_et: str, tomorrow_et: str) -> str | None:
    """Which RotoWire page serves this slate date: "today", "tomorrow", or neither.

    Pure on purpose (R65). The bug was never in this comparison, it was in the
    two dates handed to it: they came from ``dt.date.today()``, this container's
    UTC calendar, which rolls over at 8pm ET. Splitting the decision out lets the
    window be pinned by test without a clock or a network fetch, and lets the ET
    authority be pinned separately in mlb_engine.repo_env.
    """
    if slate_date == today_et:
        return "today"
    if slate_date == tomorrow_et:
        return "tomorrow"
    return None


def feed_age_minutes(feed: dict) -> float | None:
    """Minutes since the feed was fetched, or None when it does not say.

    The feed has always carried `fetched_at` and nothing ever read it, so a
    morning file on disk beat a fresh fetch silently.
    """
    stamp = (feed or {}).get("fetched_at")
    if not stamp:
        return None
    try:
        when = dt.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    delta = dt.datetime.now(dt.timezone.utc) - when
    return round(delta.total_seconds() / 60.0, 1)


def _contest_objective_block(posture_by_contest) -> list[dict]:
    """R40: what objective each contest resolved to, and where it came from.

    One row per contest: the posture, the source that chose it, the contest
    shape, and the SCORING PROFILE that shape resolves to, weights included.
    Deterministic bookkeeping of an input, not a claim about outcomes.

    The weights are copied in rather than referenced by name on purpose. A
    profile name is only meaningful against the version of
    ``CONTEST_SHAPE_PROFILE_WEIGHTS`` that was current when the build ran, and
    the whole reason this block exists is that a build's objective had to be
    reconstructed months later from a table that had moved in between.
    """
    rows: list[dict] = []
    try:
        from mlb_engine.optimize.optimizer_v3 import resolve_contest_shape_profile
    except Exception:  # never let bookkeeping break a delivery
        resolve_contest_shape_profile = None  # type: ignore
    for cid, info in sorted((posture_by_contest or {}).items()):
        shape = info.get("contest_shape")
        row = {
            "contest_id": str(cid),
            "contest_name": info.get("contest_name"),
            "posture": info.get("posture"),
            "posture_source": info.get("posture_source") or "name_inference",
            "matched_pattern": info.get("matched_pattern"),
            "contest_shape": shape,
            "profile": None,
        }
        if shape and resolve_contest_shape_profile is not None:
            try:
                row["profile"] = resolve_contest_shape_profile(contest_shape=shape)
            except Exception as exc:  # an unknown shape is worth recording as one
                row["profile"] = {"error": str(exc)}
        rows.append(row)
    return rows


def manifest_repo_relative(path) -> str | None:
    if not path:
        return None
    from mlb_engine.entries.upload_manifest import repo_relative
    return repo_relative(path)


def manifest_sha256(path) -> str | None:
    if not path or not Path(path).exists():
        return None
    from mlb_engine.entries.upload_manifest import sha256_file
    return sha256_file(path)


def slate_tag_suffix(salary_csv: Path) -> str:
    """'_1610_1g' for the delivered filename, so same-date builds cannot collide.

    Three Showdown slates on 2026-07-25 each recorded a delivered_path of
    .../DKEntries_showdown.csv, so two briefs ended up citing a file holding
    another slate's lineups. The delivered name always carries the slate tag.
    """
    try:
        tag = str(slate_signature(Path(salary_csv)).get("tag") or "").strip()
    except Exception:
        tag = ""
    return f"_{tag}" if tag else ""


def slate_signature(salary_csv: Path) -> dict:
    """Identify the draftgroup, not just the date.

    DK runs more than one Classic draftgroup on most dates: a main slate and a
    night slate, sometimes an early one. Keying staged inputs and delivered
    artifacts by date alone means the second build of the day overwrites the
    first one's staged CSVs and its delivered DKEntries.csv. On 2026-07-24 a
    night-slate build destroyed a certified main-slate file that survived only
    because it had been copied aside by hand.

    Returns the game set and a short human-readable tag (first lock in ET plus
    game count, e.g. "1905_10g"), so a caller can both name a slate and tell two
    slates apart without trusting filenames.
    """
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
    first = min(starts) if starts else None
    tag = f"{first.strftime('%H%M')}_{len(games)}g" if first else f"{len(games)}g"
    # The contract goes in the tag. A Showdown slate is one game, so its tag
    # renders as "1915_1g", which is indistinguishable from a one-game Classic
    # draftgroup. preserve_prior_slate used that tag to rename a Showdown pair
    # aside on 2026-07-25 and the result read as Classic on disk, which is
    # exactly the confusion the tag exists to prevent.
    from mlb_engine.entries.dk_entries_manager import detect_salary_contract
    contract = detect_salary_contract(salary_csv)
    if contract == "SHOWDOWN":
        tag = f"{tag}_sd"
    return {"games": frozenset(games), "tag": tag, "contract": contract,
            "first_lock": first.isoformat() if first else None}


def _self_declared_tag(path: Path) -> str:
    """A brief names its own slate; a delivered file's sibling brief names its.

    The tag used to come from whatever was staged at the moment of the rename,
    not from the file being renamed. On 2026-07-25 that filed the certified
    10-game Classic export away as ``DKEntries_1915_1g.csv``, borrowing the tag
    of a one-game Showdown slate it had nothing to do with, and wrote the same
    brief under two names. A file that can state its own slate should be asked.
    """
    try:
        if path.suffix == ".json" and path.name.startswith("build_brief"):
            return str((json.loads(path.read_text(encoding="utf-8"))
                        .get("slate") or {}).get("tag") or "")
        if path.suffix == ".csv" and path.name.startswith("DKEntries"):
            sibling = path.with_name(
                path.name.replace("DKEntries", "build_brief").replace(".csv", ".json"))
            if sibling.exists():
                return str((json.loads(sibling.read_text(encoding="utf-8"))
                            .get("slate") or {}).get("tag") or "")
    except (OSError, ValueError):
        return ""
    return ""


def preserve_prior_slate(paths, tag: str, date: str = "") -> list:
    """Move artifacts from a different draftgroup aside instead of overwriting.

    Silent overwriting is the failure; a renamed file that is still on disk is
    recoverable, and the rename is printed so it is never a surprise.

    R96 (P6), Ben's call 2026-08-11: when the moved file is a delivery the manifest
    names, the ROW FOLLOWS THE RENAME. This used to orphan the row -- the manifest
    went on naming a path that no longer existed while the renamed file sat there
    with no row, which is R96's state reached from the far side rather than by a
    failed write. Refusing the rename was the alternative and was rejected: it
    would block a build mid-slate over bookkeeping, and preserve_prior_slate fires
    exactly when a second draftgroup is being built under time pressure. ``date``
    is optional so existing callers keep working; without it no row is touched.
    """
    from mlb_engine.entries.upload_manifest import rename_recorded_delivery
    moved = []
    for path in paths:
        path = Path(path)
        if not path.exists():
            continue
        own = _self_declared_tag(path)
        if own and own != tag:
            print(f"preserve: {path.name} declares slate {own}, not {tag}; "
                  f"filing it under its own tag", file=sys.stderr)
        dest = path.with_name(f"{path.stem}_{own or tag}{path.suffix}")
        if dest.exists() and dest.read_bytes() == path.read_bytes():
            # The tag-copy already exists with identical content, which is what
            # happens when the delivery path also writes the tagged name. Minting
            # a _1 here produced three duplicate briefs in outputs/2026-07-25/ and
            # made the directory unreadable.
            continue
        n = 1
        while dest.exists():
            dest = path.with_name(f"{path.stem}_{tag}_{n}{path.suffix}")
            n += 1
        path.rename(dest)
        moved.append(str(dest))
        print(f"preserved prior slate artifact: {path.name} -> {dest.name}",
              file=sys.stderr)
        if date:
            try:
                if rename_recorded_delivery(date, path, dest):
                    print(f"  manifest row followed the rename: {dest.name}",
                          file=sys.stderr)
            except Exception as exc:  # noqa: BLE001 - never block a build on this
                print(f"  manifest row NOT updated for {dest.name}: {exc}; the "
                      f"row still names {path.name}, which no longer exists",
                      file=sys.stderr)
    return moved


def fetch_handedness(player_ids) -> dict:
    """Map MLBAM id -> {"bat": code, "pitch": code} for the supplied players.

    The schedule hydrate returns lineup players and probable pitchers as id +
    fullName only, with no handedness on either. That left ``bat_side`` absent on
    every hitter and ``hand`` None on every probable, so BOTH inputs to the F4
    platoon prior were missing and the component was structurally dead no matter
    how well the rest of the enrichment was wired. One batched /people call
    supplies both. Failure is non-fatal: F4's team-level opposing-SP quality
    component still applies and only the platoon multiplier goes neutral.
    """
    ids = sorted({str(p) for p in player_ids if p})
    if not ids:
        return {}
    out: dict = {}
    base = "https://statsapi.mlb.com/api/v1"
    for start in range(0, len(ids), 250):  # keep the query string sane
        chunk = ",".join(ids[start:start + 250])
        url = (f"{base}/people?personIds={chunk}"
               "&fields=people,id,batSide,pitchHand,code")
        try:
            with urllib.request.urlopen(url, timeout=20) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            print(f"handedness hydrate failed ({exc}); F4 platoon component will "
                  "be neutral for this build", file=sys.stderr)
            continue
        for person in payload.get("people") or []:
            entry = {}
            for key, field in (("bat", "batSide"), ("pitch", "pitchHand")):
                code = str(((person.get(field) or {}).get("code") or "")).strip().upper()
                if code in ("L", "R", "S"):
                    entry[key] = code
            if entry:
                out[str(person.get("id"))] = entry
    return out


def fetch_lineups(date: str, dest: Path) -> dict:
    """Minimal MLB Stats API pull, used only when no feed was supplied.

    The mlb-lineups skill is the canonical fetcher and handles more edge cases;
    this exists so a missing feed degrades to a slower path instead of a dead end.
    """
    base = "https://statsapi.mlb.com/api/v1"
    url = (f"{base}/schedule?sportId=1&date={date}"
           "&hydrate=lineups,probablePitcher,team")
    with urllib.request.urlopen(url, timeout=25) as resp:
        raw = json.loads(resp.read().decode("utf-8"))
    games = []
    for day in raw.get("dates", []):
        for game in day.get("games", []):
            teams = game.get("teams", {})
            lineups = game.get("lineups") or {}

            def side(key, lineup_key):
                info = teams.get(key, {}) or {}
                team = (info.get("team") or {})
                pitcher = info.get("probablePitcher") or {}
                players = lineups.get(lineup_key) or []
                return {
                    "team_abbrev": team.get("abbreviation", ""),
                    # Same three-way derivation as tools/fetch_slate_bundle.py.
                    # Collapsing 'partial' into 'tbd' here made two writers of
                    # the same feed shape disagree about a side with one to
                    # eight hitters posted (F17).
                    "lineup_status": ("confirmed" if len(players) >= 9
                                      else "partial" if players else "tbd"),
                    "lineup": [
                        {"order": i + 1, "id": p.get("id"), "name": p.get("fullName")}
                        for i, p in enumerate(players)
                    ],
                    "probable_pitcher": ({
                        "id": pitcher.get("id"), "name": pitcher.get("fullName"),
                        "hand": ((pitcher.get("pitchHand") or {}).get("code")),
                    } if pitcher else None),
                }

            games.append({
                "game_pk": game.get("gamePk"),
                "game_date_utc": game.get("gameDate", "").replace("+00:00", "Z"),
                "status": (game.get("status") or {}).get("detailedState", ""),
                "away": side("away", "awayPlayers"),
                "home": side("home", "homePlayers"),
            })

    # Attach handedness so extract_batter_hands and extract_opposing_probables
    # have something to read. Both are inputs to the F4 platoon prior.
    wanted = []
    for game_entry in games:
        for team_side in (game_entry["away"], game_entry["home"]):
            wanted += [h.get("id") for h in team_side["lineup"]]
            probable = team_side.get("probable_pitcher") or {}
            if probable.get("id"):
                wanted.append(probable["id"])
    hand_by_id = fetch_handedness(wanted)
    for game_entry in games:
        for team_side in (game_entry["away"], game_entry["home"]):
            for hitter in team_side["lineup"]:
                code = (hand_by_id.get(str(hitter.get("id"))) or {}).get("bat")
                if code:
                    hitter["bat_side"] = code
            probable = team_side.get("probable_pitcher") or {}
            if probable and not probable.get("hand"):
                code = (hand_by_id.get(str(probable.get("id"))) or {}).get("pitch")
                if code:
                    probable["hand"] = code

    feed = {"date": date, "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "games": games}
    dest.write_text(json.dumps(feed), encoding="utf-8")
    return feed


def resolve_platoon_json(args):
    """RotoWire projected orders overlaid on the FanGraphs reference, for TBD teams.

    The MLB Stats API (and mlb.com, which renders it) only shows a lineup once the
    team officially posts it; until then the team reads TBD. RotoWire publishes a
    beat-projected order for those teams and refreshes it through the day. This
    fetches RotoWire and merges it over the manually-refreshed FanGraphs platoon
    reference, so a TBD team gets the freshest projected order available: RotoWire
    where it covers the team, FanGraphs otherwise, and top-9 AvgPointsPerGame only
    when neither does.

    The merged dict is handed to build_slate_pool as platoon_json, so
    build_projected_order applies it strictly to TBD teams (only_teams) and always
    as a projected order, never a confirmed one. A confirmed lineup posted later
    still supersedes it. Any failure returns None, which restores the engine's
    default FanGraphs-only behavior. RotoWire is a public HTTP page; this never
    touches DraftKings.
    """
    if not getattr(args, "rotowire", True):
        return None
    # ET, from ONE clock reading (R65). dt.date.today() is this container's UTC
    # calendar: after 8pm ET it rolls over, so a build for TONIGHT's slate fell
    # out of the today/tomorrow window and skipped this merge in silence, while a
    # build for TOMORROW's ET slate resolved to "today" and fetched the wrong ET
    # day's page under a fresh collected_date. Two separate today() calls could
    # also straddle midnight and yield a non-adjacent pair.
    from mlb_engine.repo_env import et_day_offsets
    today, tomorrow = et_day_offsets()
    rw_when = rotowire_window(args.date, today, tomorrow)
    if rw_when is None:
        # RotoWire only serves today and tomorrow; a backfill keeps the default.
        # Said out loud, because this branch used to be the silent one and it is
        # indistinguishable from "RotoWire had nothing" in the build log.
        print(f"rotowire: slate date {args.date} is neither today ({today}) nor "
              f"tomorrow ({tomorrow}) in ET; skipping the merge and keeping the "
              "FanGraphs reference, whose staleness rule still applies",
              file=sys.stderr)
        return None
    try:
        from tools.fetch_rotowire_lineups import fetch_rotowire_platoon
        from mlb_engine.intake.live_data_adapters import to_dk_abbrev
        from mlb_engine.intake.platoon_order_adapter import (
            DEFAULT_PLATOON_REFERENCE, load_platoon_lineups,
        )
        rw = fetch_rotowire_platoon(rw_when, collected_date=args.date)
        # Key on the DK code, not the raw abbrev: FanGraphs ships TBR/SDP/SFG where
        # RotoWire ships TB/SD/SF, so a raw-code merge would leave two entries for
        # one club and let a stale FanGraphs-only hitter survive next to RotoWire's
        # nine. Normalizing both sides lets RotoWire replace FanGraphs outright.
        by_team: dict = {}
        ref = DEFAULT_PLATOON_REFERENCE
        if not ref.is_absolute():
            ref = REPO / ref
        if ref.exists():
            for t in load_platoon_lineups(ref).get("teams") or []:
                by_team[to_dk_abbrev(t.get("abbrev", ""))] = t
        rw_n = 0
        for t in rw.get("teams") or []:
            by_team[to_dk_abbrev(t.get("abbrev", ""))] = t  # RotoWire wins
            rw_n += 1
        print(f"rotowire: merged {rw_n} projected lineups over the FanGraphs "
              "reference", file=sys.stderr)
        return {
            "source": "merged: RotoWire (fresh) over FanGraphs reference",
            "collected_date": args.date,
            "teams": list(by_team.values()),
        }
    except Exception as exc:  # never let a fallback source break the build
        print(f"rotowire fetch unavailable ({exc}); using FanGraphs reference only",
              file=sys.stderr)
        return None


# --------------------------------------------------------------------------- #
# Shared verification. The upload file is the only thing that matters, so check
# it directly rather than trusting the build report.
# --------------------------------------------------------------------------- #
def verify_classic(salary_csv: Path, entries_csv: Path) -> dict:
    """Independent DK-legality read of a delivered Classic file.

    R290(c), 2026-09-03: every failure now carries a `kind` beside its string,
    and `failures` itself is unchanged for every existing reader. Two reasons
    the kinds had to exist. The classification this file's REFUSAL_SITES table
    makes cannot be checked against free text without becoming the fragile
    substring grep R233 is filed on. And "blank slot" was ONE string over two
    different facts: a PARTIALLY filled row, which DK rejects, and an
    ALL-blank reserved row, which DK simply does not enter. Ben's guardrail
    blocks certification on the second and R290(c) is the decision that it
    stops blocking delivery, so a check that cannot tell them apart cannot
    implement either half.
    """
    with salary_csv.open(encoding="utf-8-sig", newline="") as fh:
        salary = {r["ID"]: r for r in csv.DictReader(fh)}
    failures, lineups = [], []
    kinds: list = []

    def fail(eid: str, kind: str, message: str) -> None:
        failures.append(f"{eid}: {message}")
        kinds.append({"entry_id": eid, "kind": kind, "detail": message})

    with entries_csv.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.reader(fh):
            if len(row) < 14 or not row[0].strip().isdigit():
                continue
            eid, ids = row[0].strip(), [c.strip() for c in row[4:14]]
            if any(not p for p in ids):
                filled = sum(1 for p in ids if p)
                if filled == 0:
                    fail(eid, "blank_row",
                         "blank slot (reserved row entirely blank: DK enters "
                         "nothing for it, and it blocks certification)")
                else:
                    fail(eid, "partial_row",
                         f"blank slot ({filled} of 10 filled: DK rejects a "
                         f"partially filled entry)")
                continue
            if any(p not in salary for p in ids):
                fail(eid, "unknown_player_id", "unknown player id")
                continue
            players = [salary[p] for p in ids]
            total = sum(int(p["Salary"]) for p in players)
            if total > SALARY_CAP:
                fail(eid, "over_cap", f"salary {total} over cap")
            if len(set(ids)) != 10:
                fail(eid, "duplicate_player", "duplicate player")
            bad = [i for i in range(10)
                   if CLASSIC_SLOTS[i] not in str(players[i]["Roster Position"]).split("/")]
            if bad:
                fail(eid, "slot_ineligible", f"slot ineligibility at {bad}")
            teams = {}
            for p in players[2:]:
                teams[p["TeamAbbrev"]] = teams.get(p["TeamAbbrev"], 0) + 1
            # DK Classic legality, checked here because this is the last
            # independent look at the file before Ben uploads it: at most 5
            # hitters from one team, and players from at least 2 games.
            over = [f"{t} {n}" for t, n in teams.items() if n > MAX_HITTERS_PER_TEAM]
            if over:
                fail(eid, "team_stack_over_max",
                     f"more than {MAX_HITTERS_PER_TEAM} hitters from one team "
                     f"({', '.join(sorted(over))})")
            games = {str(p.get("Game Info", "")).split(" ", 1)[0] for p in players}
            games.discard("")
            if len(games) < MIN_GAMES_PER_LINEUP:
                fail(eid, "too_few_games",
                     f"players from {len(games)} game(s), DK requires "
                     f"{MIN_GAMES_PER_LINEUP}")
            top = sorted(teams.items(), key=lambda kv: -kv[1])[:2]
            lineups.append({"entry_id": eid, "salary": total, "stack": top})
    # R290(c). The classification of THIS file's failures, so the caller does
    # not re-derive it and cannot re-derive it differently. `delivery_blocked`
    # is the honest half: it is False when every failure is a blank reserved
    # row, which is a file DK will accept for the rows that are filled.
    illegal = [k for k in kinds
               if VERIFY_CLASSIC_FAILURE_CLASS.get(
                   k["kind"], (REFUSAL_ILLEGAL, ""))[0] == REFUSAL_ILLEGAL]
    return {
        "passed": not failures,
        "failures": failures,
        "failure_kinds": kinds,
        "illegal_failures": [k["detail"] for k in illegal],
        "delivery_blocked": bool(illegal),
        "lineups": lineups,
    }


# --------------------------------------------------------------------------- #
# Projection enrichment. Everything below exists because a build that skips it
# certifies exactly as cleanly as one that does not: with no reference data the
# engine ranks players on AvgPointsPerGame times a batting-order factor and
# nothing else, and no gate anywhere in the pipeline can tell the difference.
# The enrichments themselves already exist and are tested; the only thing that
# was ever missing on this path was the wiring.
# --------------------------------------------------------------------------- #
def resolve_reference_data(args) -> dict:
    """Locate the enrichment inputs and report how fresh they are.

    Returns a dict with the three CSV paths (None when absent or when
    enrichment is disabled) plus the status block that rides into the brief.
    Missing or stale files never block a build: degraded signal beats no
    lineups at T-10. They are loud instead, in the brief and on stderr.
    """
    status: dict = {"enabled": bool(getattr(args, "enrichment", True))}
    if not status["enabled"]:
        status["note"] = ("enrichment disabled with --no-enrichment; this build "
                          "ranks on AvgPointsPerGame x batting-order factor only")
        print(f"enrichment: {status['note']}", file=sys.stderr)
        return {"savant_batting": None, "savant_pitching": None,
                "fangraphs_pitching": None, "status": status}

    try:
        from tools.refresh_reference_data import reference_status
        report = reference_status(
            Path(getattr(args, "reference_dir", None) or (REPO / "data" / "reference")),
            max_age_days=getattr(args, "reference_max_age_days", 14.0),
        )
    except Exception as exc:  # a reporting failure must never kill a build
        status["note"] = f"reference-data status unavailable ({exc}); enrichment OFF"
        print(f"enrichment: {status['note']}", file=sys.stderr)
        return {"savant_batting": None, "savant_pitching": None,
                "fangraphs_pitching": None, "status": status}

    files = report["files"]
    status.update({
        "files": {name: {"age_days": info["age_days"], "stale": info["stale"],
                         "exists": info["exists"]}
                  for name, info in files.items()},
        "warnings": list(report["warnings"]),
        "any_stale": report["any_stale"],
    })
    for warning in status["warnings"]:
        print(f"enrichment warning: {warning}", file=sys.stderr)

    def usable(name: str):
        info = files.get(name) or {}
        return info["path"] if info.get("exists") else None

    return {
        "savant_batting": usable("expected_stats_batting.csv"),
        "savant_pitching": usable("expected_stats_pitching.csv"),
        # R278: file renamed with the source swap (FanGraphs manual export ->
        # MLB StatsAPI). The KEY keeps its name because it feeds run_slate's
        # shape-based `fangraphs_pitching_csv` kwarg; that rename is filed.
        "fangraphs_pitching": usable("statsapi_season_pitching.csv"),
        "status": status,
    }


def load_odds_packet(args, salary_csv=None) -> tuple[dict, dict]:
    """Return ({game_id: odds entry}, note) for the slate, or ({}, note).

    Accepts an --odds file in every shape the project produces: a raw
    the-odds-api events list, a payload wrapping one under ``odds_raw_totals``,
    ``raw``, ``events`` or ``odds``, or the mlb-game-odds skill's DEFAULT
    ``games`` schema. Falls back to fetching when THE_ODDS_API_KEY resolves.
    The key is read from the environment or the repo ``.env``, never printed,
    and scrubbed from any error text.

    ``salary_csv`` resolves doubleheader legs (F18); omit it and the earliest
    leg wins instead of the last one parsed.

    R29(5). Two bugs stacked here and both were silent. The key was read from
    ``os.environ`` alone, which is unset in a Cowork bash call, so the auto-fetch
    reported "unset" with the real key in ``REPO/.env``. And the recognised
    wrapper keys did not include ``games``, so the skill's no-flag output fell
    through to "no recognizable events list". Either way the caller reported the
    same generic "no moneyline matched this game's teams" the absence of a
    posted market produces, and the thesis ladder allocated an even split
    against a market that had priced the game all along.
    """
    from mlb_engine.intake.live_data_adapters import (
        normalize_odds_payload, parse_the_odds_api_totals, salary_game_times,
    )
    from mlb_engine.repo_env import resolve_odds_api_key

    raw = None
    source = None
    shape = None
    path = getattr(args, "odds", None)
    if path and Path(path).exists():
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception as exc:
            return {}, {"source": str(path), "warning": f"unreadable odds file: {exc}"}
        source = str(path)
        try:
            raw, shape = normalize_odds_payload(payload)
        except ValueError as exc:
            # Shape-specific, and never the same sentence as an absent market.
            return {}, {"source": source, "matched": False,
                        "warning": f"odds file shape not recognised: {exc}"}

    if raw is None:
        key = resolve_odds_api_key()
        if not key:
            return {}, {"source": None,
                        "warning": "no --odds file and THE_ODDS_API_KEY resolves "
                                   "from neither the environment nor REPO/.env; "
                                   "F1 stays neutral for this build"}
        import urllib.parse
        query = urllib.parse.urlencode({
            "apiKey": key, "regions": "us", "markets": "totals,h2h",
            "oddsFormat": "american",
        })
        url = ("https://api.the-odds-api.com/v4/sports/baseball_mlb/odds?" + query)
        try:
            with urllib.request.urlopen(url, timeout=20) as response:
                raw = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            # Never let the key reach a log line or the brief.
            scrubbed = str(exc).replace(key, "<redacted>")
            return {}, {"source": "the-odds-api",
                        "warning": f"odds fetch failed ({scrubbed}); F1 stays neutral"}
        source = "the-odds-api"

    # F18. Two events share one AWAY@HOME key on a doubleheader date and this
    # dict was last-write-wins, so a matinee draftgroup could be priced off the
    # night game's total. The salary file is authoritative for which leg is on
    # the slate, exactly as it is for the lineups feed.
    slate_times: dict = {}
    leg_note = None
    if salary_csv:
        try:
            slate_times = salary_game_times(str(salary_csv))
        except Exception as exc:  # noqa: BLE001 - leg resolution never blocks a build
            slate_times = {}
            leg_note = f"salary start times unreadable ({exc}); kept the earliest leg"
    parsed = parse_the_odds_api_totals(raw, slate_game_times=slate_times)
    odds = parsed.get("odds_by_game_id") or {}
    with_ml = sum(1 for v in odds.values() if (v or {}).get("moneyline"))
    note = {"source": source, "games": len(odds), "games_with_moneyline": with_ml,
            "payload_shape": shape or "fetched_raw_events",
            "leg_resolution": "salary_start_time" if slate_times else "earliest_leg"}
    if raw and not odds:
        # A payload that parsed to nothing is a different fact from an absent
        # payload, and it used to reach the caller as the same message.
        note["warning"] = (
            f"the odds payload carried {len(raw)} event(s) but none mapped to a "
            f"game on this slate; check the date and the team names")
    if leg_note:
        note["leg_resolution_note"] = leg_note
    # R205. A game priced one-sided is not a game with no market, and the
    # operator sees the difference here or nowhere: both end as an even split.
    incomplete = parsed.get("moneyline_incomplete") or []
    if incomplete:
        note["moneyline_incomplete"] = incomplete
        note["warning"] = (
            f"{len(incomplete)} game(s) had a moneyline posted on one side only "
            f"and no book posted a complete two-way, so F1 splits their total "
            f"evenly: "
            + "; ".join(f"{row['game_id']} ({row['books_incomplete']})"
                        for row in incomplete))
    dropped = parsed.get("doubleheader_legs_dropped") or []
    if dropped:
        note["doubleheader_legs_dropped"] = dropped
        note["warning"] = (
            f"{len(dropped)} doubleheader odds leg(s) dropped: "
            + "; ".join(f"{d['game_id']} @ {d['start_utc']} total "
                        f"{d.get('total')} ({d['reason']})" for d in dropped))
    return odds, note


def resolve_slate_venues(pool: dict, slate_date: str) -> tuple[dict, dict]:
    """Return ({Game_ID: venue record}, report) for every game in the pool.

    One venue resolution, read by both F1 (which needs the park run factor to
    de-park the implied total) and F5 (which needs the venue, roof, azimuth and
    wind threshold). Two resolutions would be two answers to one question, and
    this project has been bitten by that before.

    F18. ``game_venue_overrides.csv`` existed with a loader and a resolver and
    was never called from the production path, so a neutral-site game silently
    took the nominal home park's factors, coordinates and roof. It is loaded
    here keyed ``(date, AWAY@HOME)``. A row whose ``Projection_F5_Status`` is
    ``manual_required`` without a ``Run_Factor_Applied`` takes a NEUTRAL 1.0
    park factor and is named in the report: an unapproved special venue is not
    a licence to reuse the wrong park's number, and guessing one is worse than
    saying we do not have it.
    """
    from mlb_engine.intake.slate_intake_manager import (
        load_f5_park_factors, load_game_venue_overrides,
        resolve_game_venue_overrides_path,
    )

    report: dict = {"games": {}, "override_games": [], "override_manual_required": [],
                    "venues_without_park_factor": [], "games_without_venue": []}
    team_to_venue = REPO / "data/reference/team_to_venue.csv"
    try:
        park_factors = load_f5_park_factors(str(REPO / "data/reference/f5_park_factors.csv"))
        venue_rows: dict = {}
        with team_to_venue.open(encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                venue_rows[str(row.get("Home_Team", "")).strip().upper()] = row
    except Exception as exc:
        report["skipped"] = f"venue reference data unreadable: {exc}"
        return {}, report

    overrides: dict = {}
    try:
        overrides_path = resolve_game_venue_overrides_path(str(team_to_venue))
        if overrides_path:
            overrides = load_game_venue_overrides(overrides_path)
            report["overrides_source"] = str(overrides_path)
    except Exception as exc:
        report["warning"] = f"game venue overrides unreadable ({exc}); home parks assumed"

    game_ids = sorted({str(row.get("Game_ID") or "")
                       for row in (pool.get("projection_rows") or [])
                       if "@" in str(row.get("Game_ID") or "")})
    by_game: dict = {}
    for game_id in game_ids:
        away, home = (part.strip().upper() for part in game_id.split("@", 1))
        override = overrides.get((str(slate_date), f"{away}@{home}"))
        if override:
            manual = (override.get("projection_f5_status") == "manual_required"
                      and override.get("run_factor_applied") in (None, ""))
            park_run = (1.0 if manual
                        else float(override.get("run_factor_applied") or 1.0))
            record = {
                "game_id": game_id, "away": away, "home": home,
                "venue": override.get("venue") or "",
                "roof_type": str(override.get("roof_type") or "unknown").strip().lower(),
                "cf_azimuth_degrees": override.get("cf_azimuth_degrees"),
                "wind_min_speed_mph": override.get("wind_min_speed_mph"),
                "park_run_factor": park_run,
                "park_factor_source": "override_manual_neutral" if manual else "override_row",
                "venue_source": "game_override",
                "manual_required": bool(manual),
                "notes": override.get("notes") or "",
            }
            report["override_games"].append(
                {"game_id": game_id, "venue": record["venue"],
                 "park_run_factor": park_run, "notes": record["notes"]})
            if manual:
                report["override_manual_required"].append(
                    {"game_id": game_id, "venue": record["venue"]})
        else:
            venue_row = venue_rows.get(home)
            if not venue_row:
                report["games_without_venue"].append(game_id)
                continue
            venue = str(venue_row.get("Venue", "")).strip()
            park = park_factors.get(venue, {})
            park_run = float(park.get("run_factor_applied") or 1.0)
            if venue not in park_factors:
                report["venues_without_park_factor"].append(venue or home)
            threshold = venue_row.get("Wind_Min_Speed_MPH")
            try:
                threshold = float(threshold) if threshold not in (None, "") else None
            except (TypeError, ValueError):
                threshold = None
            record = {
                "game_id": game_id, "away": away, "home": home, "venue": venue,
                "roof_type": str(venue_row.get("Roof_Type", "")).strip().lower(),
                "cf_azimuth_degrees": venue_row.get("CF_Azimuth_Degrees"),
                "wind_min_speed_mph": threshold,
                "park_run_factor": park_run,
                "park_factor_source": "f5_park_factors" if venue in park_factors else "missing_neutral",
                "venue_source": "home_team_default",
                "manual_required": False,
                "notes": "",
            }
        by_game[game_id] = record
        report["games"][game_id] = {
            "venue": record["venue"], "roof_type": record["roof_type"],
            "park_run_factor": record["park_run_factor"],
            "venue_source": record["venue_source"],
            "park_factor_source": record["park_factor_source"],
        }
    return by_game, report


def build_f1_map(pool: dict, odds_by_game_id: dict,
                 park_run_factor_by_game_id: dict | None = None) -> tuple[dict, dict]:
    """Return ({Player_ID: F1}, report) from the slate's posted game lines.

    Game environment is the strongest exogenous signal in MLB DFS and the market
    prices it for free. Pitchers are held at 1.0 in v1 so the opposing-team
    total is not counted twice. Labeled prior, never a run projection.

    F18. The posted total already prices the ballpark and F5 multiplies the park
    run factor again, so the park was counted twice. Park ownership is decided:
    F5 owns it, and the implied total handed to F1 is divided by the game's park
    factor first. The map comes from ``resolve_slate_venues`` so F1 and F5 read
    one venue resolution.
    """
    from mlb_engine.projections.projection_builder import build_f1_factors

    team_by_player_id = dict(pool.get("team_by_player_id") or {})
    pitcher_ids = list((pool.get("pitcher_roles") or {}).keys())
    # Pitchers are absent from team_by_player_id (it is hitters only), so add
    # them explicitly to keep the F1 map total and its report honest.
    salary_team = pool.get("team_by_player_id") or {}
    for pid in pitcher_ids:
        team_by_player_id.setdefault(str(pid), salary_team.get(str(pid), ""))
    if not odds_by_game_id:
        return {}, {"skipped": "no odds packet available", "non_neutral_f1": 0}
    return build_f1_factors(
        odds_by_game_id, team_by_player_id, pitcher_ids=pitcher_ids,
        park_run_factor_by_game_id=park_run_factor_by_game_id or None)


def build_f5_map(pool: dict, args, venues_by_game_id: dict | None = None) -> tuple[dict, dict]:
    """Return ({Player_ID: F5}, report) from park factors and tonight's weather.

    F5 is the only enrichment with a HUMAN step that cannot be automated away.
    A retractable roof's open/closed state is not in any forecast, and guessing
    it is worse than leaving it neutral: a closed roof cancels the wind
    adjustment entirely, so a wrong guess moves every hitter in that game the
    wrong way. Unresolved retractables therefore take the park factor only, and
    the game is named in a checkpoint warning for Ben to resolve by hand.

    Park factors apply on their own even with no forecast at all, which is most
    of the available signal: Coors is Coors in any weather. F18 confirmed park
    as F5's to own; F1 now de-parks the implied total so it is priced once.

    Three F18 fixes live here. The wind gate tested ``roof_type == "outdoor"``
    while the library's own ``OUTDOOR_ROOF_TYPES`` also contains ``temporary``,
    so Sutter Health Park (the ATH home, wind sensitivity HIGH, threshold 8mph,
    the most wind-sensitive park on the schedule) never took a wind adjustment.
    Delay and postponement risk were hardcoded to "none", which made both
    branches of ``compute_f5_factor`` unreachable; they are now derived from the
    forecast's precipitation probability. And the venue comes from
    ``resolve_slate_venues``, so a neutral-site override reaches production.
    """
    from mlb_engine.intake.slate_intake_manager import (
        OUTDOOR_ROOF_TYPES, compute_f5_factor, load_f5_park_factors,
        load_f5_weather_adjustments, risk_from_precip_probability,
    )
    from mlb_engine.optimize.optimizer_v3 import wind_bearing_to_f5_label

    report: dict = {"games_scored": 0, "retractable_unresolved": [],
                    "venues_without_park_factor": [], "non_neutral_f5": 0,
                    "delay_risk_by_team": {}, "override_venues": [],
                    "forecast_missing_for_venue": []}

    bundle_path = getattr(args, "bundle", None)
    weather_by_venue: dict = {}
    if bundle_path and Path(bundle_path).exists():
        try:
            bundle = json.loads(Path(bundle_path).read_text(encoding="utf-8"))
            weather_by_venue = bundle.get("weather") or {}
            report["weather_source"] = str(bundle_path)
        except Exception as exc:
            report["warning"] = f"bundle unreadable ({exc}); park factors only"
    else:
        report["weather_source"] = None

    try:
        park_factors = load_f5_park_factors(str(REPO / "data/reference/f5_park_factors.csv"))
        adjustments = load_f5_weather_adjustments(
            str(REPO / "data/reference/f5_weather_adjustments.csv"))
    except Exception as exc:
        report["skipped"] = f"F5 reference data unreadable: {exc}"
        return {}, report

    venues_by_game_id = venues_by_game_id or {}
    # Game_ID is AWAY@HOME, so the game names the venue.
    team_by_player_id = dict(pool.get("team_by_player_id") or {})
    pitcher_roles = pool.get("pitcher_roles") or {}
    game_by_team: dict = {}
    for row in (pool.get("projection_rows") or []):
        game_id = str(row.get("Game_ID") or "")
        if "@" in game_id:
            game_by_team[str(row.get("Team") or "").strip().upper()] = game_id
        if str(row.get("Player_ID")) in pitcher_roles:
            team_by_player_id.setdefault(str(row.get("Player_ID")),
                                         str(row.get("Team") or ""))

    f5_by_team: dict = {}
    for team in sorted({str(t).strip().upper() for t in team_by_player_id.values() if t}):
        record = venues_by_game_id.get(game_by_team.get(team) or "")
        if not record:
            continue
        venue = str(record.get("venue") or "").strip()
        if record.get("park_factor_source") == "missing_neutral" \
                and venue not in report["venues_without_park_factor"]:
            report["venues_without_park_factor"].append(venue or team)
        roof_type = str(record.get("roof_type") or "").strip().lower()
        forecast = (weather_by_venue.get(venue) or {})
        hours = forecast.get("hourly_window") or []
        mid = hours[len(hours) // 2] if hours else {}
        if record.get("venue_source") == "game_override":
            if venue not in report["override_venues"]:
                report["override_venues"].append(venue)
            if not hours and venue not in report["forecast_missing_for_venue"]:
                # The bundle keys weather by the nominal home venue, so a
                # neutral site has no forecast under its own name. Wind stays
                # neutral rather than borrowing another city's wind.
                report["forecast_missing_for_venue"].append(venue)

        roof_closed = roof_type == "dome"
        if roof_type == "retractable" and venue not in report["retractable_unresolved"]:
            # Never guessed. Neutral wind plus the park factor is the honest read.
            report["retractable_unresolved"].append(venue)

        wind_status = "cross"
        if hours and roof_type in OUTDOOR_ROOF_TYPES:
            wind_status = wind_bearing_to_f5_label(
                mid.get("wind_direction_deg"), record.get("cf_azimuth_degrees"))
        # Delay risk is the WORST hour in the game window, not the middle one:
        # a shower an hour after first pitch shortens the same starter's outing
        # as one at first pitch, and the middle hour cannot see it.
        precip_values = [h.get("precip_probability_pct") for h in hours
                         if h.get("precip_probability_pct") not in (None, "")]
        precip_max = max((float(v) for v in precip_values), default=None)
        delay_risk, postponement_risk = ("none", "none")
        if precip_max is not None:
            delay_risk, postponement_risk = risk_from_precip_probability(precip_max)
            report["delay_risk_by_team"][team] = {
                "precip_probability_pct_max": precip_max,
                "delay_risk": delay_risk, "postponement_risk": postponement_risk}
        weather = {
            "wind_status": wind_status,
            "wind_speed_mph": mid.get("wind_speed_mph"),
            "delay_risk": delay_risk,
            "postponement_risk": postponement_risk,
        }
        # A park factor resolved by the override path is already in the record;
        # pass it through the same table lookup compute_f5_factor uses by
        # supplying a one-row override rather than a second multiplication site.
        park_table = park_factors
        if record.get("venue_source") == "game_override" or venue not in park_factors:
            park_table = dict(park_factors)
            park_table[venue] = {"run_factor_applied": float(record.get("park_run_factor") or 1.0)}
        result = compute_f5_factor(venue, weather, park_table, adjustments,
                                   wind_threshold_mph=record.get("wind_min_speed_mph"),
                                   roof_closed=roof_closed or roof_type == "retractable")
        f5_by_team[team] = result
        report["games_scored"] += 1

    f5_by_player: dict = {}
    for pid, team in team_by_player_id.items():
        result = f5_by_team.get(str(team).strip().upper())
        if not result:
            f5_by_player[str(pid)] = 1.0
            continue
        f5_by_player[str(pid)] = float(
            result["pitcher_f5"] if str(pid) in pitcher_roles else result["hitter_f5"])

    report["non_neutral_f5"] = sum(
        1 for v in f5_by_player.values() if abs(float(v) - 1.0) > 1e-9)
    report["f5_by_team"] = {
        t: {"venue": r["components"]["venue"],
            "hitter_f5": r["hitter_f5"], "pitcher_f5": r["pitcher_f5"],
            "wind": r["components"].get("wind_row"),
            "delay": r["components"].get("delay_row"),
            "postponement": r["components"].get("postponement_row")}
        for t, r in sorted(f5_by_team.items())}
    report["game_exposure_caps"] = {
        t: r["game_exposure_cap"] for t, r in sorted(f5_by_team.items())
        if r.get("game_exposure_cap") is not None}
    report["excluded_games"] = sorted(
        t for t, r in f5_by_team.items() if r.get("exclude_game"))
    report["note"] = (
        "Deterministic F5 prior: park run factor times a wind adjustment that "
        "applies only when the roof is open (outdoor, temporary or open), "
        "direction is out/in, and speed meets the venue threshold, times a "
        "pitcher-only delay factor derived from the worst precipitation hour in "
        "the game window. Retractable roofs are never guessed. F5 owns the park; "
        "F1's implied total is de-parked so it is not counted twice. "
        "Labeled prior, never a run projection or probability claim.")
    return f5_by_player, report


def build_f4_map(pool: dict, savant_pitching_csv) -> tuple[dict, dict]:
    """Return ({Player_ID: F4}, report) for the pool's hitters, or ({}, report).

    F4 is the deterministic matchup prior: opposing-SP xwOBA-against quality
    times a platoon hand factor, PA-shrunk and clipped. The SP-quality component
    applies team-wide even when batter hands are missing, so a TBD lineup still
    receives it. It is a labeled prior, never a win-rate or probability claim.
    """
    from mlb_engine.projections.projection_builder import (
        compute_f4_factors, load_savant_expected_stats,
    )

    team_by_player_id = pool.get("team_by_player_id") or {}
    opposing = pool.get("opposing_probables") or {}
    if not team_by_player_id:
        return {}, {"skipped": "no hitters in the pool"}

    table = None
    if savant_pitching_csv:
        try:
            table = load_savant_expected_stats(savant_pitching_csv)
        except Exception as exc:
            return {}, {"skipped": f"savant pitching table unreadable: {exc}"}

    f4, report = compute_f4_factors(
        team_by_player_id, opposing, table, pool.get("batter_hands") or {},
    )
    non_neutral = sum(1 for v in f4.values() if abs(float(v) - 1.0) > 1e-9)
    report["non_neutral_f4"] = non_neutral
    if f4 and non_neutral == 0:
        # Not fatal, but it means every hitter got the neutral factor, which is
        # indistinguishable from not computing F4 at all. Say so.
        report["warning"] = (
            "F4 computed for "
            f"{len(f4)} hitters but every value is neutral 1.0; the opposing-SP "
            "quality and platoon components both found nothing to apply"
        )
    return f4, report


def pool_brief_block(report: dict, pool: dict) -> dict:
    """The brief's ``pool`` block, from the engine's own pool_report.

    R190. This block carried four keys -- teams, platoon_source, warnings,
    blockers -- and dropped two structured facts the pool_report has carried
    since R117(b) and R143. Both are the same failure shape: the brief holds
    the SYMPTOM and not the fact it joins to.

    ``opposing_probables_incomplete`` is the one that cost something. On the
    2026-08-18 1910_9g build the counts block read ``f4_platoon_applied: 0``
    against ``f4_hitters_scored: 162``, with ``signal_applied: true``,
    ``degraded: false`` and ``factors_inert: []`` -- every summary line green,
    the whole platoon term dead, and the structured list naming which
    probables arrived with no hand not present at any level of the brief. A
    reader who noticed the 0 had nowhere to go.

    ``dk_batting_order`` is R143's own record of whether the salary file
    covered the slate end to end, which is what decides whether a fetch was
    needed at all. Absent from the brief, so a session reading the brief saw
    ``null`` and could not tell a covered slate from an uncovered one -- and
    it is exactly on a fully covered slate, where DK ships no handedness, that
    the platoon term is expected to be unavailable and the reader most needs
    to see the coverage fact beside the zero.

    R291. Third instance of the same shape, and it cost an in-slate workaround.
    `excluded_column` is R289's audit surface and this block dropped it, so on
    the 2026-09-02 2138_2g build the brief carried NO `pool.excluded_column`
    key at all -- absent rather than zero, which is not the same fact and is
    the one thing a reader cannot recover. It is present unconditionally now.
    Two guesses that BUILD filed with that report are ruled out by measurement
    rather than argument: `parse_dk_salary_csv` does carry an unknown column
    into `SalaryPlayer.raw` (the R289 fixture reads 20 rows True through the
    front door), and nothing in this script rewrites the salary CSV (no
    `to_csv`, no `DictWriter`). This block was the whole of it.
    """
    return {
        "teams": len(report.get("teams") or {}),
        "platoon_source": pool.get("platoon_source"),
        "warnings": report.get("warnings") or [],
        "blockers": report.get("blockers") or [],
        "opposing_probables_incomplete": (
            report.get("opposing_probables_incomplete") or {}),
        "dk_batting_order": report.get("dk_batting_order"),
        "excluded_column": report.get("excluded_column") or {},
    }


def summarize_enrichment(reference_status: dict, enrichment: dict,
                         f4_report: dict, degraded_reason,
                         f1_report: dict | None = None,
                         f5_report: dict | None = None,
                         projections=None) -> dict:
    """Condense the enrichment record into the block the brief carries.

    The one question this has to answer at a glance is whether this build had
    signal or was APPG in a ceiling costume. ``signal_applied`` is that answer:
    it is True only when at least one factor moved at least one player off
    neutral.

    R127 added the second question that one answer could not carry. On the
    2026-08-15 2138_2g slate ``signal_applied`` was True on hitter-side signal
    while all four pitchers sat at F1 = F4 = F5 = 1.0 with the ceiling
    multiplier the only thing separating arms -- and BUILD read the single True
    and reported the build fully enriched. ``signal_applied_by_side`` is the
    per-side measurement (from the engine's own per-row count, not from the
    size of the input maps), and a DISAGREEMENT between the sides raises a
    warning, because the disagreement is the case a reader gets wrong.
    ``neutral_default`` carries the engine's named list of pool players whose
    factor took its neutral default, and ``projection_mode`` states the mode
    distribution that was previously visible only in projections.csv.
    """
    enrichment = enrichment or {}
    xwoba = enrichment.get("xwoba") or {}
    ceiling = enrichment.get("ceiling") or {}
    pitcher_ceiling = enrichment.get("pitcher_ceiling") or {}
    non_neutral_f4 = int(f4_report.get("non_neutral_f4") or 0)
    f1_report = f1_report or {}
    f5_report = f5_report or {}

    counts = {
        "xwoba_non_neutral": int(xwoba.get("non_neutral_applied") or 0),
        "xwoba_match_rate": xwoba.get("match_rate"),
        "hitter_ceiling_differentiated": int(ceiling.get("differentiated_rows") or 0),
        "pitcher_ceiling_differentiated": int(
            pitcher_ceiling.get("differentiated_rows")
            or pitcher_ceiling.get("matched") or 0),
        "f4_non_neutral": non_neutral_f4,
        "f4_hitters_scored": int(f4_report.get("hitters_scored") or 0),
        "f4_platoon_applied": int(f4_report.get("platoon_component_applied") or 0),
        "f1_non_neutral": int(f1_report.get("non_neutral_f1") or 0),
        "f1_games_priced": int(f1_report.get("games_priced") or 0),
        "f5_non_neutral": int(f5_report.get("non_neutral_f5") or 0),
        "f5_games_scored": int(f5_report.get("games_scored") or 0),
    }
    warnings = list(reference_status.get("warnings") or [])
    warnings += list(enrichment.get("warnings") or [])
    for key in ("warning", "skipped"):
        if f4_report.get(key):
            warnings.append(f"f4: {f4_report[key]}")
        if f1_report.get(key):
            warnings.append(f"f1: {f1_report[key]}")
        if f5_report.get(key):
            warnings.append(f"f5: {f5_report[key]}")
    if (f1_report.get("odds") or {}).get("warning"):
        warnings.append(f"f1: {f1_report['odds']['warning']}")
    no_ml = f1_report.get("games_without_moneyline") or []
    if no_ml:
        warnings.append(
            "f1: no moneyline for " + ", ".join(no_ml)
            + "; those totals split evenly rather than by side")
    teams_no_odds = f1_report.get("teams_without_odds") or []
    if teams_no_odds:
        warnings.append(
            "f1: no game line for " + ", ".join(teams_no_odds)
            + "; those hitters stay neutral")
    teams_without = f4_report.get("teams_without_opposing_probable") or []
    if teams_without:
        warnings.append(
            "f4: no opposing probable for " + ", ".join(sorted(teams_without))
            + "; those hitters stay neutral")
    if degraded_reason:
        warnings.append(f"DEGRADED to unenriched build: {degraded_reason}")

    # Derived from what the engine actually applied per row, not from the size of
    # the input maps. A stale-ID map is requested-but-unapplied, and the brief
    # used to report that as enrichment; an honest-looking enrichment block that
    # misreports is worse than none.
    engine_applied = {
        key: int((enrichment.get(key) or {}).get("applied_count") or 0)
        for key in ("f1", "f4", "f5")
        if isinstance(enrichment.get(key), dict)
    }
    counts.update({f"{k}_engine_applied": v for k, v in engine_applied.items()})
    requested_but_unapplied = sorted(
        key for key in ("f1", "f4", "f5")
        if isinstance(enrichment.get(key), dict)
        and int((enrichment[key] or {}).get("requested") or 0) > 0
        and int((enrichment[key] or {}).get("applied_count") or 0) == 0
    )
    for key in requested_but_unapplied:
        warnings.append(
            f"{key}: a map was supplied but reached zero rows; the ids in it do "
            f"not match this slate's pool. That factor is OFF for this build.")
    # R127(b). The per-side split, and the warning for the case the single
    # boolean got wrong. `by_side` is the engine's per-row measurement; when it
    # is absent (an older caller, or a degraded unenriched frame) the per-side
    # answer is None rather than a guess, and nothing below fabricates one.
    by_side = enrichment.get("by_side") or {}
    signal_by_side = None
    if by_side:
        signal_by_side = {
            side: bool((by_side.get(side) or {}).get("signal_applied"))
            for side in ("hitters", "pitchers")
        }
        for side, has in signal_by_side.items():
            rows = int((by_side.get(side) or {}).get("rows") or 0)
            if not has and rows:
                other = "pitchers" if side == "hitters" else "hitters"
                if signal_by_side.get(other):
                    warnings.append(
                        f"enrichment reached {other} but NOT {side}: all {rows} "
                        f"{side} in the pool sit at every factor's neutral "
                        f"default. signal_applied is true on the {other} side "
                        f"alone; read signal_applied_by_side before calling this "
                        f"build enriched.")

    # R127(a). The engine names the pool players whose factor fell back to its
    # neutral default. Surfaced here as its own brief key so the reader does not
    # have to infer it from a count, which is the failure the entry describes.
    neutral_default = enrichment.get("neutral_default") or {}

    signal = any(counts[k] for k in (
        "xwoba_non_neutral", "hitter_ceiling_differentiated",
        "pitcher_ceiling_differentiated", "f4_non_neutral", "f1_non_neutral",
        "f5_non_neutral")) and not (
        # If every factor that was requested applied to nothing, and nothing else
        # differentiated a row, there is no signal to claim.
        requested_but_unapplied and not counts["xwoba_non_neutral"]
        and not counts["hitter_ceiling_differentiated"]
        and not counts["pitcher_ceiling_differentiated"])
    # R127(b). `Projection_Mode = emergency_proxy` on every row is a fact about
    # what the build was standing on, and it was visible nowhere but
    # projections.csv. Read off the delivered frame, so it is a count and not a
    # restatement of the mode that was requested.
    projection_mode = None
    if projections is not None and getattr(projections, "empty", True) is False \
            and "Projection_Mode" in getattr(projections, "columns", []):
        modes = projections["Projection_Mode"].astype(str)
        projection_mode = {
            "rows": int(len(modes)),
            "distribution": {str(k): int(v) for k, v in
                             sorted(modes.value_counts().items())},
        }

    return {
        "signal_applied": bool(signal),
        # R127(b): the per-side answer beside the any-side one. `signal_applied`
        # keeps its meaning and its consumers; this is the field that says WHICH
        # side had signal, and None means the engine did not report it rather
        # than that both sides were dark.
        "signal_applied_by_side": signal_by_side,
        "neutral_default": neutral_default,
        "projection_mode": projection_mode,
        # R119(a), ed4 adoption, recording only. Floor is a UNIFORM 0.58 of
        # Base_Projection (projection_builder.py, no per-row path), so ranking
        # by Floor is always identical to ranking by Base_Projection; Ceiling is
        # Base_Projection times a PER-ROW Ceiling_Multiplier that only differs
        # from the uniform neutral default where enrichment (xwOBA/xISO/K-rate/
        # F1/F4/F5) actually moved it. target='floor' (cash) is therefore mean-
        # maximization on every slate, and enrichment is the only thing that can
        # make a ceiling-scored GPP/WTA build differ from it (ed4 measured
        # 25/25 identical lineups without enrichment, 4/25 with).
        # cash_and_gpp_selection_identical is that corollary of signal_applied,
        # not a lineup-by-lineup diff of an actual cash vs. GPP solve.
        "objective_differentiation": {
            "floor_basis": "Floor = Base_Projection x uniform 0.58; ranks "
                           "identically to Base_Projection on every slate",
            "ceiling_basis": "Ceiling = Base_Projection x per-row "
                             "Ceiling_Multiplier; ranks like Base_Projection "
                             "only where enrichment moved a multiplier off the "
                             "uniform neutral default",
            "cash_and_gpp_selection_identical": not bool(signal),
            "note": "target='floor' is mean-maximization on every slate (ed4, "
                    "adopted as R119); a corollary of signal_applied above, "
                    "never a probability or performance claim.",
        },
        "requested_but_unapplied": requested_but_unapplied,
        "degraded": bool(degraded_reason),
        "degraded_reason": degraded_reason,
        "reference_data": reference_status,
        # R119(c): this warning (built above from the raw enrichment dict) can
        # say "see enrichment['value_guard']" -- write the key here too, or the
        # brief's own enrichment block has no such key for the reader to see.
        "value_guard": enrichment.get("value_guard"),
        "counts": counts,
        "f4_league_mean_est_woba": f4_report.get("league_mean_est_woba"),
        "f1_odds": f1_report.get("odds"),
        "f1_league_mean_implied_total": f1_report.get("league_mean_implied_total"),
        "f1_implied_total_by_team": f1_report.get("implied_total_by_team"),
        "f5_by_team": f5_report.get("f5_by_team"),
        "f5_retractable_unresolved": f5_report.get("retractable_unresolved") or [],
        "warnings": warnings,
        "note": "Enrichment counts are deterministic labeled priors applied to the "
                "projection frame: xwOBA Base correction, xISO hitter ceilings, "
                "K-rate pitcher ceilings, the F4 opposing-SP/platoon matchup "
                "factor, F1 from Vegas implied team totals, and F5 park/weather. "
                "Implied totals are derived from the posted total and moneyline, "
                "not published by the book. signal_applied and the *_engine_applied "
                "counts come from the engine's per-row application, not from the "
                "size of the input maps. Never ROI, win rate, or a probability "
                "claim.",
    }


def salary_cross_check_note(clock: dict) -> str | None:
    """The stderr disagreement line for a clock's feed/salary cross-check, or
    None when there is nothing to report.

    R99. This used to read a DIFFERENT object than the brief's
    ``slate_clock.salary_cross_check`` field: the brief correctly reads
    ``clock.get("salary_cross_check")`` (the dict ``slate_clock`` actually
    returns, keyed ``checked``/``agrees``/... per
    ``slate_intake_manager.slate_clock``), while this stderr gate used to read
    ``pool_report.get("salary_cross_check")`` -- a key no producer in this
    codebase ever writes, so it was always None and the gate could never fire,
    on a clean slate or a genuinely disagreeing one. Both sites now read the
    same ``clock`` object, so a missing cross-check (nothing to compare, the
    common case) and an agreeing one both stay silent, and only a real
    ``agrees is False`` prints -- with the real field names the cross-check
    actually returns, not the ``first_lock_local``/``feed_first_lock_local``
    keys the old message referenced (neither exists on this dict either).
    """
    cross_check = clock.get("salary_cross_check")
    if not cross_check or cross_check.get("agrees") is not False:
        return None
    return (
        f"clock: feed-derived first lock "
        f"({cross_check.get('feed_first_lock_game_id')}) disagrees with the "
        f"authoritative salary file ({cross_check.get('salary_first_lock_game_id')} "
        f"at {cross_check.get('salary_first_lock_utc')}, drift "
        f"{cross_check.get('drift_minutes')} min); salary file adopted."
    )


# --------------------------------------------------------------------------- #
# Classic
# --------------------------------------------------------------------------- #
def run_classic(args, slate_dir: Path, salary: Path, entries: Path,
                feed: dict, deadline: float) -> tuple[int, dict]:
    from mlb_engine.intake.live_data_adapters import build_slate_pool
    from mlb_engine.optimize.bank_cache import BankCache, extend_bank, pool_signature
    # R288: the engine's own default, read rather than restated, so the brief's
    # `applied` cannot disagree with what the solver did.
    from mlb_engine.optimize.optimizer_v3 import ANTI_CORRELATION_DEFAULT_MAX
    from mlb_engine.pipeline.execution_pipeline import (
        _assemble_projection_frame, apply_leverage_ownership, run_slate,
    )

    # The stale-platoon condition prints as SOFT below, and CLAUDE.md's build
    # contract says it prints and the build ships; inheriting the engine's
    # 'block' default made lineup_gate_passed fail with no cause printed
    # (docs/backlog_inbox/2026-07-28_build_stale-platoon-block-default.md,
    # merged as R27). 'warn' makes reality match the stated contract; the
    # age still prints, and a RotoWire merge still clears it entirely.
    pool = build_slate_pool(str(salary), feed, platoon_json=resolve_platoon_json(args),
                            declared_pitchers=parse_declared_pitchers(
                                args.declare_pitcher) or None,
                            stale_platoon_policy="warn")
    report = pool["pool_report"]
    clock = pool.get("clock") or {}
    kwargs = pool["run_slate_kwargs"]

    # F8: the intake blockers landed, and then were read once, to be printed into
    # the brief. Nothing exited on them, so the 2026-07-22 failure (23 teams
    # matched 0/9, headline read certified) replayed with prettier logging.
    #
    # Tiering per the anti-paralysis doctrine: a blocker that says the pool is
    # structurally wrong for this slate is HARD, because a build on it is not a
    # worse build, it is a build of something else. A blocker about the freshness
    # of a reference file is SOFT: it degrades the build, it does not invalidate
    # it, and stopping the slate over it is the failure mode the doctrine exists
    # to prevent.
    blockers = list(report.get("blockers") or [])
    soft = [b for b in blockers if SOFT_POOL_BLOCKER_RE.search(b)]
    hard = [b for b in blockers if b not in soft]
    for b in soft:
        print(f"pool (soft): {b}", file=sys.stderr)
    if hard and not args.ignore_pool_blockers:
        for b in hard:
            print(f"POOL BLOCKER: {b}", file=sys.stderr)
        print(json.dumps({
            "status": "pool_blocked",
            **refusal_stamp("pool_blocked_hard"),
            "date": args.date,
            "blockers": hard,
            "soft_blockers": soft,
            "note": "the pool this build would use is structurally wrong for this "
                    "slate; building on it produces a certified file for a "
                    "different slate than the one being entered. Fix the input, "
                    "or pass --ignore-pool-blockers to build anyway and have the "
                    "override recorded in the brief.",
        }, indent=1))
        return 3, {}
    # R133(4). CLAUDE.md's hard list names this one "stop and ask", above all
    # others: a name-crosswalk failure means the real lineup is sitting unused
    # while a projection substitutes for it, and building anyway is a certified
    # file for a lineup nobody posted. `--ignore-pool-blockers` used to let it
    # through, spend the whole build, and then lose it at the pre-export gate.
    # It refuses HERE, by name, which is what the 2026-08-12 fragment asked for.
    unoverridable = [b for b in hard if UNOVERRIDABLE_POOL_BLOCKER_RE.search(b)]
    if unoverridable and args.ignore_pool_blockers:
        for b in unoverridable:
            print(f"POOL BLOCKER NOT OVERRIDABLE: {b}", file=sys.stderr)
        print(json.dumps({
            "status": "pool_blocked",
            **refusal_stamp("pool_blocked_crosswalk"),
            "date": args.date,
            "blockers": unoverridable,
            "other_hard_blockers": [b for b in hard if b not in unoverridable],
            "soft_blockers": soft,
            "note": "--ignore-pool-blockers does not cover a name-crosswalk "
                    "failure. CLAUDE.md's hard list calls this one stop-and-ask "
                    "above all others, because the real posted lineup is in hand "
                    "and a projection is being substituted for it. Refused here "
                    "rather than after the build, which is where the pre-export "
                    "gate used to refuse it. Fix the crosswalk (check the team "
                    "code and the name spellings against the salary file) or "
                    "exclude the team.",
        }, indent=1))
        return 3, {}
    if hard:
        for b in hard:
            print(f"POOL BLOCKER OVERRIDDEN by --ignore-pool-blockers: {b}",
                  file=sys.stderr)
        # R133(4). This flag alone never certified and never said so. The
        # pre-export gate re-derives `lineup_gate_passed` from this same pool
        # report, so an overridden blocker still fails it; CLAUDE.md's autonomy
        # section already says the two moves go together ("both together or
        # neither") and this is the tool finally saying which second move.
        if "lineup_gate_passed" not in (
                parse_assume_gates_arg(getattr(args, "assume_gates", None)) or []):
            print("NOTE: the pre-export gate re-reads this pool report "
                  "independently, so overriding the blocker here does not by "
                  "itself certify. Add --assume-gates lineup_gate_passed to "
                  "assert the gate on the same evidence (CLAUDE.md: both "
                  "together or neither); the override is recorded in "
                  "diagnostics under overridden_gates.", file=sys.stderr)

    # A salary/feed clock disagreement means two sources describe different
    # slates, so say which one this build adopted rather than picking silently.
    # R99: reads `clock`, the same object the brief's salary_cross_check field
    # reads -- `report` (pool_report) never carries this key, so the old gate
    # here could never fire.
    _cross_check_note = salary_cross_check_note(clock)
    if _cross_check_note:
        print(_cross_check_note, file=sys.stderr)

    n_entries = args.entries or count_reserved(entries)

    reference = resolve_reference_data(args)
    f4_by_player_id, f4_report = build_f4_map(pool, reference["savant_pitching"])
    if f4_report.get("warning"):
        print(f"enrichment warning: {f4_report['warning']}", file=sys.stderr)

    # One venue resolution, read by both F1 and F5 (F18). It has to run before
    # F1 because F1 divides the implied total by the park factor it returns.
    venues_by_game_id, venue_report = resolve_slate_venues(pool, args.date)
    for entry in venue_report.get("override_manual_required") or []:
        print(f"F5 VENUE: {entry['game_id']} is at {entry['venue']} by "
              "game_venue_overrides.csv, and that venue has no approved park "
              "run factor, so its park factor is NEUTRAL 1.0 for this build. "
              "Supply Run_Factor_Applied in the override row to change that.",
              file=sys.stderr)
    if venue_report.get("games_without_venue"):
        print("F5 VENUE: no venue row for "
              f"{', '.join(venue_report['games_without_venue'])}; those games "
              "take F1 without a park de-park and F5 stays neutral.",
              file=sys.stderr)

    odds_by_game_id, odds_note = load_odds_packet(args, salary_csv=salary)
    if odds_note.get("warning"):
        print(f"odds: {odds_note['warning']}", file=sys.stderr)
    f1_by_player_id, f1_report = build_f1_map(
        pool, odds_by_game_id,
        park_run_factor_by_game_id={gid: rec["park_run_factor"]
                                    for gid, rec in venues_by_game_id.items()})
    f1_report["odds"] = odds_note
    f1_report["venues"] = venue_report
    if f1_report.get("warning"):
        print(f"enrichment warning: {f1_report['warning']}", file=sys.stderr)

    f5_by_player_id, f5_report = build_f5_map(pool, args, venues_by_game_id)
    f5_report["venues"] = venue_report
    for venue in f5_report.get("retractable_unresolved") or []:
        print(f"F5 ROOF: {venue} is retractable and its open/closed state is "
              "unresolved; wind is NOT applied there. Confirm by hand if it "
              "matters to this slate.", file=sys.stderr)
    for venue in f5_report.get("forecast_missing_for_venue") or []:
        print(f"F5 WEATHER: no forecast for the override venue {venue}; wind "
              "is neutral there rather than borrowed from the nominal home "
              "park. Re-run tools/fetch_slate_bundle.py if that matters.",
              file=sys.stderr)
    for team, entry in sorted((f5_report.get("delay_risk_by_team") or {}).items()):
        if entry["delay_risk"] in {"medium", "high"} or entry["postponement_risk"] != "none":
            print(f"F5 RAIN: {team} at {entry['precip_probability_pct_max']:.0f}% "
                  f"peak precipitation; delay risk {entry['delay_risk']}, "
                  f"postponement risk {entry['postponement_risk']}.",
                  file=sys.stderr)

    # Assemble the frame WITH the enrichments. This frame is not just the timing
    # probe: on the sliced-bank path it is the frame every cached candidate is
    # built from, so enriching it here is what puts the signal in the portfolio.
    enrich_kwargs = dict(
        savant_batting_csv=reference["savant_batting"],
        savant_pitching_csv=reference["savant_pitching"],
        fangraphs_pitching_csv=reference["fangraphs_pitching"],
        f4_by_player_id=f4_by_player_id or None,
        f1_by_player_id=f1_by_player_id or None,
        f5_by_player_id=f5_by_player_id or None,
    )
    degraded_reason = None
    try:
        projections, enrichment = _assemble_projection_frame(
            str(salary), kwargs["projection_rows"], "emergency_proxy",
            enrich_kwargs["savant_batting_csv"], enrich_kwargs["savant_pitching_csv"],
            None,
            projected_order_by_player_id=kwargs.get("platoon_order_by_player_id"),
            f4_by_player_id=enrich_kwargs["f4_by_player_id"],
            f1_by_player_id=enrich_kwargs["f1_by_player_id"],
            f5_by_player_id=enrich_kwargs["f5_by_player_id"],
            fangraphs_pitching_csv=enrich_kwargs["fangraphs_pitching_csv"],
        )
    except ValueError as exc:
        # The engine's zero-match guards raise rather than build a silent no-op.
        # That is the right call at the library layer and the wrong outcome at
        # T-10, so degrade to the unenriched frame and make the reason impossible
        # to miss. A shipped build on bare APPG that SAYS it is on bare APPG is
        # honest; a killed slate is not a better answer.
        degraded_reason = str(exc)
        print(f"ENRICHMENT FAILED, building unenriched: {degraded_reason}",
              file=sys.stderr)
        enrich_kwargs = dict(savant_batting_csv=None, savant_pitching_csv=None,
                             fangraphs_pitching_csv=None, f4_by_player_id=None,
                             f1_by_player_id=None, f5_by_player_id=None)
        f4_by_player_id = {}
        f1_by_player_id = {}
        f5_by_player_id = {}
        projections, enrichment = _assemble_projection_frame(
            str(salary), kwargs["projection_rows"], "emergency_proxy", None, None, None,
            projected_order_by_player_id=kwargs.get("platoon_order_by_player_id"),
        )

    # R117(b). Computed here, where all three maps have settled (the degraded
    # path above empties them), and REPORTED beside the gates rather than here.
    # The placement is the fix: this fact lived in an enrichment warning at the
    # top of the log, which is the one place a session at T-10 does not re-read.
    factors_inert = inert_factors([
        ("F1", f1_by_player_id, f1_report),
        ("F4", f4_by_player_id, f4_report),
        ("F5", f5_by_player_id, f5_report),
    ])

    # R127. A factor that fell back to its neutral default on a DECLARED STARTER
    # changes selection, so it reaches stderr at build time and not only the
    # brief the operator reads afterwards. The engine hands back its own list
    # rather than making this re-derive it from the merged warning pile.
    for _nd_warning in ((enrichment.get("neutral_default") or {}).get("warnings") or []):
        print(f"enrichment warning: {_nd_warning}", file=sys.stderr)

    # Decide the strategy from a measurement, never from a guess. The rule that
    # matters: an infrastructure limit may reduce search effort, never the legal
    # player set, because trimming the pool is a strategy change that is invisible
    # in the certified output.
    # R246. Resolved before any bank is built, so a missing prediction file
    # costs the read and not the solve. The column goes on THIS frame for the
    # sliced path; run_slate reassembles its own and attaches it there.
    try:
        leverage, leverage_brief = resolve_leverage(
            args, salary, str(slate_signature(salary).get("tag") or ""))
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "leverage_unresolved", "date": args.date,
                              "error": str(exc)},
                         indent=1))
        return 4, {}
    # The ENGINE's own attach, not a second copy. A first cut inlined it here
    # and a mutation disabling the branch SURVIVED: with no
    # `Projected_Ownership_Pct` column the solver's reader falls back to a flat
    # 12.0 for every player, so a cumulative cap would have bound against a
    # constant and looked like it was working. Third instance of that class in
    # one session; the remedy each time is a function the tests execute.
    projections, _own_report = apply_leverage_ownership(projections, leverage)
    if _own_report.get("applied"):
        leverage_brief["players_unscored"] = _own_report["players_unscored"]
        leverage_brief["players_scored"] = _own_report["players_scored"]
        print(f"leverage: {_own_report['players_scored']} of "
              f"{_own_report['players_scored'] + _own_report['players_unscored']} "
              f"pool players carry a predicted share, from "
              f"{leverage_brief['source']}", file=sys.stderr)

    t0 = time.monotonic()
    from mlb_engine.optimize.optimizer_v3 import (
        build_single_lineup, resolve_candidate_bank_size,
    )
    build_single_lineup(projections, target="ceiling")
    single_s = time.monotonic() - t0
    remaining = deadline - time.monotonic()

    # Model the real cost, which is base bank plus SP-pair augmentation. A naive
    # per-lineup estimate ignores the augmentation and understates the total by
    # roughly the pair count, which is exactly how a build gets started that
    # cannot finish. Same model as tools/solver_probe.py.
    bank_size = resolve_candidate_bank_size(n_entries)
    game_of = {str(r.Player_ID): str(r.Game_ID) for r in projections.itertuples()}
    sps = [str(p) for p in projections[projections["Position"] == "P"]["Player_ID"]]
    cross_pairs = sum(
        1 for i in range(len(sps)) for j in range(i + 1, len(sps))
        if game_of.get(sps[i]) != game_of.get(sps[j])
    )
    growth = max(bank_size / 5.0, 1.0)
    projected_direct = (single_s * bank_size * (1 + (growth - 1) / 2)
                        + cross_pairs * single_s)

    bank_path = REPO / "runs" / f"bank_cache_{args.date}_{pool_signature(salary)}.json"
    strategy = "direct"
    bank_report = None
    candidates = None

    bank_budget_floored = False
    if projected_direct > remaining:
        strategy = "sliced_bank"
        cache = BankCache(bank_path)
        # R98(1): this is the floor the 1910_9g build actually hit. `time_budget_s`
        # in the bank report is THIS value, so the brief's `solve.bank` recorded
        # 5.0 with no way to tell it apart from a chosen budget.
        slice_budget, bank_budget_floored = resolve_bank_budget(
            remaining - 8.0, label="sliced bank")
        bank_report = extend_bank(
            cache, projections,
            time_budget_s=slice_budget,
            max_candidates=max(n_entries * 12, 60),
            # R246. This is the bank that is DELIVERED on this path: its
            # candidates go to run_slate as candidates_override, so run_slate
            # builds no bank of its own and the auto-bank passthrough never
            # runs. Both had to be wired or --leverage would be a no-op on
            # whichever path a given slate's clock happened to choose.
            leverage=leverage,
            # R288: same reason as leverage above -- the sliced bank is what most
            # builds deliver from, so a control wired only to the auto path is a
            # silent no-op on whichever path the clock happens to choose.
            max_opposing_hitters_per_sp=getattr(
                args, "max_opposing_hitters_per_sp", None),
        )
        bank_report["budget_floored"] = bank_budget_floored
        # F15: score each contest shape the reserved CSV actually contains. A
        # single wta score is a ceiling-max ranking, and the allocator's cash
        # branch then applies its floor weighting on top of it, so cash entries
        # ranked on inverted weights. The shapes are known from the entries file,
        # so there is nothing to guess.
        try:
            from mlb_engine.entries.dk_entries_manager import parse_dk_entry_rows
            from mlb_engine.pipeline.execution_pipeline import _resolve_contest_postures
            reserved_rows = parse_dk_entry_rows(str(entries))
            postures = _resolve_contest_postures(
                reserved_rows, parse_postures_arg(getattr(args, "postures", None)), None)
            slice_shapes = sorted({
                (postures.get(str(r.contest_id)) or {}).get(
                    "contest_shape", "large_field_gpp")
                for r in reserved_rows
            })
        except Exception as exc:  # noqa: BLE001 - shape scoring is a refinement
            print(f"shape resolution failed, scoring wta only: {exc}", file=sys.stderr)
            slice_shapes = None
        candidates = cache.as_candidates(
            projections, requested_n=n_entries, contest_shapes=slice_shapes)
        if len(candidates) < n_entries * 2 and not bank_report["job_list_exhausted"]:
            print(json.dumps({
                "status": "partial",
                **refusal_stamp("bank_thin_partial"),
                "date": args.date,
                "strategy": strategy,
                "candidates": len(candidates),
                "needed_at_least": n_entries * 2,
                "note": "bank still thin; run the same command again to add a slice",
            }, indent=1))
            return 10, {}

    slate_kwargs = dict(kwargs)
    postures = parse_postures_arg(getattr(args, "postures", None))
    if postures:
        slate_kwargs["contest_postures"] = postures

    # The pool report is the evidence behind the lineup gate. Without it run_slate
    # can only say "some players carry a batting order", which is not the same
    # claim.
    slate_kwargs["source_metadata"] = {
        **dict(slate_kwargs.get("source_metadata") or {}),
        "pool_report": pool.get("pool_report"),
    }

    # On the sliced path run_slate never builds the bank, so it has nothing to
    # record about how the candidates were produced and diagnostics.json would
    # say only "candidates_override". The cache's own report is the equivalent
    # evidence and belongs in the immutable run record for the same reason
    # (F11): the run record is this project's memory of what was shipped.
    if bank_report is not None:
        slate_kwargs["metadata"] = {
            **dict(slate_kwargs.get("metadata") or {}),
            "bank_diagnostics": {"source": "bank_cache", "strategy": strategy,
                                 **{k: v for k, v in bank_report.items()
                                    if k != "candidates"},
                                 "payload_report": dict(cache.last_payload_report)},
            "bank_warnings": [
                w for w in [
                    ("the job list was not exhausted; this bank is a slice, not "
                     "the full search" if not bank_report.get("job_list_exhausted")
                     else None),
                    # R92: `extend_bank` has never returned `jobs_failed` or
                    # `budget_exhausted` -- those two guards read keys only
                    # `optimizer_v3`'s unrelated augmentation report uses, so
                    # they were dead: `.get` returned None and the `if` never
                    # fired. The real keys are `jobs_raised`/`raised_by_reason`
                    # (R55(b), a defect: the solve raised and proved nothing)
                    # and `jobs_unanswered`/`unanswered_by_status` (returned no
                    # lineup and proved no infeasibility either) -- both
                    # retryable, neither the same as a dry pool.
                    (f"{bank_report.get('jobs_raised')} cache job(s) raised an "
                     f"exception instead of answering ({dict(bank_report.get('raised_by_reason') or {})})"
                     if bank_report.get("jobs_raised") else None),
                    (f"{bank_report.get('jobs_unanswered')} cache job(s) returned "
                     f"no lineup and proved no infeasibility "
                     f"({dict(bank_report.get('unanswered_by_status') or {})})"
                     if bank_report.get("jobs_unanswered") else None),
                    # F13/F15: both were previously invisible in the run record.
                    (f"{bank_report.get('jobs_timed_out')} cache jobs hit the solver "
                     f"time limit and are retryable on another slice"
                     if bank_report.get("jobs_timed_out") else None),
                    # R98(1): the reason a slice is thin belongs beside the fact
                    # that it is thin.
                    (f"the bank budget hit the {BANK_BUDGET_FLOOR_S:g}s engine "
                     f"floor, so this slice was bounded by a constant rather "
                     f"than by --max-seconds"
                     if bank_report.get("budget_floored") else None),
                    (f"{cache.last_payload_report.get('scoring_failed')} candidates "
                     f"could not be scored and allocate on raw objective"
                     if cache.last_payload_report.get("scoring_failed") else None),
                ] if w
            ],
        }

    # F4 gates that this build genuinely cannot evidence, assumed explicitly and
    # printed. A build given no odds map is a different state from a build whose
    # odds matched nothing; only the first is assumable, and the assumption is
    # recorded in diagnostics rather than papered over with a default of True.
    assumed: list[str] = []
    if not f1_by_player_id:
        assumed.append("odds_gate_passed")
    if not f5_by_player_id:
        assumed.append("weather_gate_passed")
    assumed += [g for g in parse_assume_gates_arg(getattr(args, "assume_gates", None))
                if g not in assumed]
    for gate in assumed:
        print(f"gate assumed (not checked): {gate}", file=sys.stderr)
    if assumed:
        slate_kwargs["assume_gates"] = assumed

    # Always bounded, even on the direct path. The estimate above decides
    # strategy; this makes a wrong estimate degrade to a smaller bank instead of
    # a killed process that leaves nothing behind. R98(1): and when the bound is
    # the floor rather than the remaining window, say so. On the sliced path
    # `candidates` are already in hand and run_slate never builds a bank, so this
    # value governs only the direct path -- which is why the floor that matters
    # is reported per strategy below rather than as one merged flag.
    if strategy == "direct":
        run_bank_budget, bank_budget_floored = resolve_bank_budget(
            deadline - time.monotonic() - 6.0, label="run_slate auto-bank")
    else:
        # Inert on the sliced path: candidates were handed in, so run_slate
        # builds no bank and a floor notice here would be noise about a budget
        # nothing spends.
        run_bank_budget = max(deadline - time.monotonic() - 6.0, BANK_BUDGET_FLOOR_S)

    result = run_slate(
        runs_root=str(REPO / "runs"),
        salary_csv=str(salary), entries_csv=str(entries),
        approve=True, requested_n=n_entries,
        candidates_override=candidates,
        # Same enrichment inputs the probe frame used. run_slate reassembles the
        # frame internally, so passing anything less here would build the bank on
        # enriched projections and then certify against unenriched ones.
        **enrich_kwargs,
        bank_time_budget_s=run_bank_budget,
        # R288. The allowance rides portfolio_controls, not just the bank
        # parameter, because the EXPORT validator grades the delivered file
        # against `controls` and would otherwise reject a raised build with a
        # line that reads like a DK rule. That is the fifth member of the class
        # and it is the one that made the control unusable end to end. Merged
        # under any explicit --controls-override, so an operator who sets the key
        # both ways gets their own value rather than the flag's.
        portfolio_controls_override={
            **({"max_opposing_hitters_per_sp":
                int(args.max_opposing_hitters_per_sp)}
               if getattr(args, "max_opposing_hitters_per_sp", None) is not None
               else {}),
            **(args.controls_override or {}),
        } or None,
        leverage=leverage or None,
        **slate_kwargs,
    )

    # Contest identity, one line per contest, with where it came from. The
    # objective the portfolio is built to is the single most consequential
    # inference in the build and it used to be invisible.
    for cid, info in sorted((result.get("posture_by_contest") or {}).items()):
        src = info.get("posture_source") or "name_inference"
        extra = ""
        if info.get("matched_pattern"):
            extra = f" [matched '{info['matched_pattern']}'"
            if info.get("competing_patterns"):
                extra += f", also matched {info['competing_patterns']}"
            extra += "]"
        print(f"contest {cid} {info.get('posture')} ({src}){extra}: "
              f"{info.get('contest_name')}", file=sys.stderr)

    if not result.get("passed"):
        for blocker in result.get("contest_identity_blockers") or []:
            print(f"contest identity: {blocker}", file=sys.stderr)
        # R27 (open half): when a pre-export gate fails, its cause prints
        # here, on the failing command's own output. No session should ever
        # again reproduce the pool by hand to learn why a gate failed.
        detail = gate_failure_detail(result, report)
        for name in detail.get("failed_gates") or []:
            print(f"gate {name}: {detail['gate_evidence'][name]}", file=sys.stderr)
        for blocker in detail.get("pool_blockers") or []:
            print(f"pool blocker: {blocker}", file=sys.stderr)
        # A failed joint allocation is frequently a small-slate control
        # infeasibility, not a real "no legal lineup" wall: too few games means
        # too few distinct SP pairs and team stacks to keep every portfolio
        # control (max_shared_players, exposure caps) satisfied at once for a
        # large requested_n. The engine already computes the exact structural
        # floor and a remedy per failing check (see feasibility.checks); surface
        # it here so the fix is "rerun with --controls-override" instead of a
        # from-scratch debugging session.
        feas = result.get("feasibility") or {}
        payload = {"status": "not_certified",
                   **refusal_stamp("classic_not_certified"),
                   "date": args.date,
                   "errors": result.get("errors"),
                   **detail}
        # R290(c). The split, resolved here rather than left to the reader. The
        # stamp above says SPLIT; these three keys say which way it split on
        # THIS refusal, gate by gate, so the operator sees "portfolio_caps:
        # badly_shaped" instead of inferring from a gate name whether DK would
        # have taken the file.
        payload.update(refusal_class_of_failed_gates(detail.get("failed_gates")))
        if detail.get("contest_identity_blockers") or result.get(
                "contest_identity_blockers"):
            payload["refusal_class_contest_identity"] = (
                CLASSIC_CONTEST_IDENTITY_CLASS[0])
        if not feas.get("passed", True):
            payload["feasibility"] = feas
        # R98(2). The old hint fired only on a feasibility failure and named one
        # remedy for two different kinds of control. It now fires whenever there
        # is something true to say, leads with bank growth when the job list was
        # not exhausted, and separates a structural floor from an exposure cap.
        # The counts the hint is derived from travel beside it, so a refusal can
        # be read without re-deriving them. That is R98(4) on the REFUSAL path
        # only; carrying them into the certified brief beside
        # controls_override_applied is the open half and stays in the backlog.
        # R286(b), 2026-09-01. The failing checks print FIRST, before the hint
        # and before anything else on this path, because O4 of the 1940_9g
        # post-mortem is that the answer was in the artifact the whole time and
        # the operator read `errors[]` eight times without ever printing
        # `feasibility`. SKILL.md now instructs a session to read these first;
        # printing them makes the instruction unnecessary, which is the stronger
        # form. Two lines, stderr, no JSON parsing required.
        failing_checks = [c for c in (feas.get("checks") or [])
                          if c.get("passed") is False]
        if failing_checks:
            print(f"FEASIBILITY: {len(failing_checks)} slate-level check(s) FAILED "
                  f"-- read these before errors[]:", file=sys.stderr)
            for check in failing_checks:
                print(f"  {check.get('name')}: {check.get('detail')}"
                      + (f"  REMEDY: {check.get('remedy')}"
                         if check.get("remedy") else ""), file=sys.stderr)
        else:
            print("FEASIBILITY: no slate-level check failed; the bind is the "
                  "interaction of the active controls against this bank",
                  file=sys.stderr)
        # R286(c). The clock, on the refusal, from the clock. O1 of the same
        # post-mortem: the session inferred elapsed time from turn count, decided
        # lock was two minutes away when it was twelve, and stopped building. A
        # reading printed by the refusal itself cannot be stale by more than the
        # call that produced it.
        # `clock` is the pool's own, assigned at the top of run_classic from the
        # salary file's Game Info. Read it rather than reaching into the result:
        # the result's copy is absent on some refusal paths and the salary file
        # is present on all of them.
        if clock.get("available"):
            payload["slate_clock"] = {
                "first_lock_utc": clock.get("first_lock_utc"),
                "minutes_to_deadline": clock.get("minutes_to_deadline"),
                "past_deadline": clock.get("past_deadline"),
                "buffer_minutes": clock.get("buffer_minutes"),
            }
            print(f"CLOCK: first lock {clock.get('first_lock_utc')}  minutes to the "
                  f"T-{clock.get('buffer_minutes', 5)} deadline: "
                  f"{clock.get('minutes_to_deadline')}"
                  + ("  PAST THE DEADLINE -- the best legal file is the "
                     "deliverable and certification is a bonus"
                     if clock.get("past_deadline") else ""), file=sys.stderr)
        hint = infeasibility_hint(feas, bank_report)
        if hint:
            payload["hint"] = hint
            print(f"hint: {hint}", file=sys.stderr)
        if bank_report is not None:
            payload["bank_exploration"] = {
                "jobs_attempted": bank_report.get("jobs_attempted"),
                "jobs_total": bank_report.get("jobs_total"),
                "job_list_exhausted": bank_report.get("job_list_exhausted"),
                "total_candidates": bank_report.get("total_candidates"),
                "budget_floored": bank_report.get("budget_floored"),
            }
        # R28(5): the refusal writes the brief too. This used to return an empty
        # brief, so `--brief` produced no file on the one path where the reader
        # most needs one, and a session that captured only the brief learned
        # nothing about why the build refused. The payload already carries
        # failed_gates and pool_blockers from R27; returning it as the brief is
        # the whole fix. main() prints it, so there is no second print here.
        payload["contest_type"] = "classic"
        payload["date"] = args.date
        payload["entries"] = n_entries
        payload["run_id"] = result.get("run_id")
        payload["gates"] = {
            "workflow_valid": result.get("workflow_valid"),
            "selection_certified": result.get("selection_certified"),
            "allocation_certified": result.get("allocation_certified"),
        }
        # R117(b). A refusal is read harder than a delivery, and an inert factor
        # is one candidate reason the bank had nothing to separate.
        payload["factors_inert"] = factors_inert
        print(f"factors: {format_inert_factors_line(factors_inert)}",
              file=sys.stderr)
        payload["pool_blockers_soft"] = soft
        payload["pool_blockers_overridden"] = (
            hard if (hard and args.ignore_pool_blockers) else [])
        payload["declared_pitchers"] = parse_declared_pitchers(args.declare_pitcher)
        payload["non_rosterable_arms"] = report.get("non_rosterable_arms") or []
        return 3, payload

    delivered = result.get("delivered_path") or result.get("output_path")
    checks = verify_classic(salary, Path(delivered))
    exposure = portfolio_exposure(salary, Path(delivered))
    # R116. The concentration facts join the exposure block, which is where a
    # reader already goes to ask how concentrated this portfolio is. Two
    # provenances on purpose: `distinct_lineups`/`max_lineup_repeat` above are
    # counted off the delivered file, `candidate_reuse` below is what the
    # allocator says it enforced, and `candidate_reuse_counts` is the per-
    # candidate tally it has emitted since v1.9 and nothing ever read. They
    # should agree; a brief where they do not is the interesting one.
    exposure["candidate_reuse"] = result.get("candidate_reuse")
    exposure["candidate_reuse_counts"] = result.get("candidate_reuse_counts")
    # R126. Apex and washout join the SAME block rather than opening a new
    # section, because "is this portfolio concentrated in a way the gates do not
    # catch" is the question this block already half-answered. The engine
    # computes it (it is the only place the entered set and the Ceiling column
    # are both in hand); build_slate's job is to carry it into the brief and say
    # it once out loud where the operator reads before approving.
    exposure["frontier"] = result.get("portfolio_frontier")
    print(f"frontier: {format_frontier_line(exposure['frontier'])}", file=sys.stderr)
    # R247(a). Read before approving, on the same footing as the frontier line.
    # The block itself lives inside the frontier (it is computed where the
    # entered set and the Ceiling column are both in hand); it is echoed here
    # because a degraded tail is invisible in every other line this build prints.
    print(f"degraded: "
          f"{format_degraded_line((exposure['frontier'] or {}).get('degraded_entries'))}",
          file=sys.stderr)
    print(f"factors: {format_inert_factors_line(factors_inert)}", file=sys.stderr)
    brief = {
        "status": "certified" if checks["passed"] else "verify_failed",
        "contest_type": "classic",
        "date": args.date,
        "entries": n_entries,
        "delivered_path": delivered,
        # Repo-relative and hashed. Every delivered_path recorded on 2026-07-25
        # was absolute against a session mount that no longer exists, and no
        # brief stated which bytes it was describing.
        "delivered_path_repo": manifest_repo_relative(delivered),
        "delivered_sha256": manifest_sha256(delivered),
        "upload_manifest": manifest_repo_relative(
            REPO / "outputs" / args.date / "upload_manifest.json"),
        "pool_blockers_overridden": hard if (hard and args.ignore_pool_blockers) else [],
        "pool_blockers_soft": soft,
        # R104. The operator's PLR/PO decision is an INPUT to this build, so it is
        # recorded verbatim rather than reconstructed from a terminal. The confirm
        # step behind it is a web search and deliberately lives outside the build;
        # what the build owes is a record of the answer it was given, next to the
        # arms it refused on its own.
        "declared_pitchers": parse_declared_pitchers(args.declare_pitcher),
        "non_rosterable_arms": report.get("non_rosterable_arms") or [],
        "run_id": result.get("run_id"),
        # R40. The resolved objective, per contest, recorded in the artifact
        # rather than reconstructed later. It used to print to stderr and stop
        # there, so answering "which profile scored this build" a week later
        # meant reading runs/ and cross-referencing a weights table by hand --
        # which is how R40 became archaeology for two rank-1 finishes rather
        # than a lookup. The scoring weights are included, not just the shape
        # name, because the weights are the thing that actually ranked the
        # candidates and the table they come from is versioned code.
        "contests": _contest_objective_block(result.get("posture_by_contest")),
        "gates": {
            "workflow_valid": result.get("workflow_valid"),
            "selection_certified": result.get("selection_certified"),
            "allocation_certified": result.get("allocation_certified"),
        },
        # R117(b). Beside the gates, deliberately NOT inside them: these three
        # keys are the certification vocabulary and an inert factor certifies
        # nothing and blocks nothing. It sits here because this is where a
        # reader asks "what was this build standing on", and the answer used to
        # be twelve warnings up the log.
        "factors_inert": factors_inert,
        "solve": {
            "strategy": strategy,
            "single_lineup_s": round(single_s, 2),
            # R98(1). The governing budget's floor state, named at the level a
            # reader reaches first. `bank` is None on the direct path, so a flag
            # that lived only inside it would be invisible on exactly the path
            # where run_slate builds the bank.
            "bank_budget_floored": bank_budget_floored,
            "bank": bank_report,
        },
        "slate_clock": {
            "first_lock_game_id": clock.get("first_lock_game_id"),
            "first_lock_utc": clock.get("first_lock_utc"),
            "minutes_to_deadline": clock.get("minutes_to_deadline"),
            "salary_cross_check": (clock.get("salary_cross_check") or {}).get("agrees"),
        },
        "pool": pool_brief_block(report, pool),
        "exposure": exposure,
        "verification": checks,
        "controls_override_applied": args.controls_override,
        # R246. On every Classic brief, `applied: false` when nothing was asked
        # for, so "was the ownership prior in this build" has an answer.
        "leverage": leverage_brief,
        # R288. On EVERY Classic brief, including the default, because "did this
        # build allow hitters facing its own arms" has to be answerable from the
        # artifact rather than from the absence of a key -- R237's rule, and the
        # reason R238 has three sightings. `requested: null` means the flag was
        # not passed and `applied` is the engine default the build actually ran.
        "anti_correlation": {
            "requested": getattr(args, "max_opposing_hitters_per_sp", None),
            "applied": (getattr(args, "max_opposing_hitters_per_sp", None)
                        if getattr(args, "max_opposing_hitters_per_sp", None)
                        is not None else ANTI_CORRELATION_DEFAULT_MAX),
            "unit": "hitters facing ONE rostered SP; per-lineup worst case is "
                    "twice this on Classic",
            "note": "a CONVENTION about negative correlation, not a DK rule",
        },
        "enrichment": summarize_enrichment(
            reference["status"], enrichment, f4_report, degraded_reason,
            f1_report, f5_report, projections=projections),
    }
    # R290(c). The conditional refusal stamps its own class, on the brief this
    # site already writes. Both halves matter to the governor: `delivery_blocked`
    # False means every failure is an all-blank reserved row, so the file DK
    # would take for the rows that ARE filled is sitting on disk, mirrored, and
    # this exit is the only thing standing between it and the operator.
    if not checks["passed"]:
        brief.update(refusal_stamp(
            "classic_verify_failed",
            refusal_class=(REFUSAL_ILLEGAL if checks.get("delivery_blocked")
                           else REFUSAL_BADLY_SHAPED),
            refusal_failure_kinds=sorted({k["kind"] for k in
                                          checks.get("failure_kinds") or []}),
        ))
    return (0 if checks["passed"] else 3), brief


# --------------------------------------------------------------------------- #
# Showdown
# --------------------------------------------------------------------------- #
def showdown_handedness(args, slate_dir: Path, df) -> tuple[dict, dict, dict]:
    """Return (bat_side, pitcher_hand_by_team, note) for a Showdown pool.

    The platoon component of the Base prior needs a hitter's side and the
    OPPOSING declared starter's hand. Neither is in the DK salary file, so this
    reads the lineups feed. Missing handedness is not fatal: the prior falls
    back to a flat 1.00 and the affected teams are named in the brief, which is
    the honest outcome. Silently flattening it is not, because the prior_note
    still claims a platoon factor was applied.

    R190. Both team keys are normalized through ``to_dk_abbrev``. They were not
    until 2026-08-23, and the two sides of that lookup come from different
    vocabularies: the MLB Stats API writes ``AZ``, DraftKings writes ``ARI``, so
    on the 2026-08-19 1610_1g_sd (ARI @ BOS) build the feed carried BOTH
    probable hands and the brief still reported ``platoon_unresolved_teams:
    ["ARI"]`` with ``teams_with_hand: 1``. Every BOS hitter took a flat 1.00
    against RHP Pfaadt instead of 0.94 same-handed or 1.04 opposite -- a ~10%
    relative gap between the L and R bats on that side, collapsed silently. The
    failure is one-sided by construction, which is why it reads half-clean: BOS
    resolved, ARI did not, and only the unresolved list said so. ``AZ`` is one
    of seven aliases in ``DK_ABBREV_REMAP``; the six FanGraphs spellings
    (``WSN`` ``TBR`` ``CHW`` ``KCR`` ``SDP`` ``SFG``) reach this same boundary
    from a pasted or FanGraphs-sourced feed.
    """
    from mlb_engine.intake.live_data_adapters import to_dk_abbrev
    note: dict = {"source": None, "hitters_with_side": 0, "teams_with_hand": 0}
    feed_path = Path(args.lineups) if args.lineups else slate_dir / "lineups_feed.json"
    feed = None
    if feed_path.exists():
        try:
            feed = json.loads(feed_path.read_text(encoding="utf-8"))
            note["source"] = str(feed_path)
            note["age_minutes"] = feed_age_minutes(feed)
        except Exception as exc:
            note["warning"] = f"unreadable lineups feed: {exc}"
    if feed is None:
        try:
            feed = fetch_lineups(args.date, slate_dir / "lineups_feed.json")
            note["source"] = "fetched"
        except Exception as exc:
            note["warning"] = f"lineups feed unavailable ({exc}); platoon stays flat"
            return {}, {}, note

    teams = set(df["Team"].unique()) if len(df) else set()
    bat_side: dict = {}
    hand: dict = {}
    for game in (feed.get("games") or []):
        for side in ("away", "home"):
            block = game.get(side) or {}
            # fetch_lineups writes team_abbrev; the other two are accepted so a
            # hand-rolled pre-fetch feed (the Cowork sandbox path) also works.
            abbrev = to_dk_abbrev(block.get("team_abbrev") or block.get("team")
                                  or block.get("abbrev"))
            for hitter in (block.get("lineup") or []):
                if hitter.get("bat_side") and hitter.get("name"):
                    bat_side[str(hitter["name"])] = str(hitter["bat_side"])
            pitcher = block.get("probable_pitcher") or block.get("probable") or {}
            if abbrev and pitcher.get("hand"):
                hand[str(abbrev)] = str(pitcher["hand"])
    note["hitters_with_side"] = sum(1 for n in bat_side if n in set(df["Name"]))
    note["teams_with_hand"] = len([t for t in hand if t in teams])
    # pitcher_hand is keyed by the team a hitter FACES, so invert: a hitter on
    # LAD is graded against the NYM starter's hand.
    facing = {}
    for _, row in df.iterrows():
        # DK's own column is not re-normalized, deliberately. `to_dk_abbrev`
        # maps INTO DraftKings' vocabulary, so the salary file is already the
        # target and the call would be a no-op on every real file. The
        # symmetric version was written first and SURVIVED a mutation that
        # removed it -- no fixture could tell the two apart, because none can
        # honestly carry a non-DK code in a DK column. Shipping a line no test
        # can justify is R77's class, so the fix stays one-sided, which is also
        # the shape of the defect: only the FEED speaks another vocabulary.
        opp = str(row["Opponent"])
        if opp in hand:
            facing[opp] = hand[opp]
    # Named, not silent: a DK team in this pool whose opposing hand never
    # resolved is the one-sided collapse above, and it is cheaper to read here
    # than to infer from `teams_with_hand: 1`.
    note["teams_without_hand"] = sorted(t for t in teams if t not in hand)
    return bat_side, facing, note


def resolve_leverage(args, salary: Path, slate_tag: str) -> tuple[dict, dict]:
    """(leverage mapping for run_slate/extend_bank, brief block). R246.

    R154 built two MILP constraints -- a cumulative predicted-ownership ceiling
    and a floor on low-owned hitters -- and shipped them OFF pending calibration.
    What was not intended is that no path could turn them ON: grepped at this
    head they appear only in `optimizer_v3.py` and `tests/test_core.py`. On
    1905_5g `qa_portfolio` priced all 14 delivered entries chalk-positive (+11.1
    to +46.0 pp) while Ben was asking in-slate for more leverage, and the honest
    answer was that the lever was built and not connected.

    **The input is a LABELED, UNGRADED PRIOR.** R209 measured its ORDERING as
    usable (Spearman +0.581 across 112 graded players) and said explicitly that
    its LEVEL is not -- one slate cannot size a coefficient. So this forwards
    numbers the CALLER chose, records the file they were read from, and claims
    nothing about outcomes.

    Absent prediction file with `--leverage` asked for: REFUSE, with the path
    named. Building without the input the operator asked for, while the delivered
    file looks like every other delivered file, is R242's silent-fallback shape
    on the surface where it costs the most.
    """
    if not getattr(args, "leverage", None):
        return {}, {"applied": False, "reason": "no --leverage supplied"}
    # Both imports are LOCAL, deliberately. `build_slate.py` must still load
    # with no engine on the path, so the dependency check at startup can print a
    # one-line refusal instead of an ImportError traceback -- a top-level
    # `from mlb_engine...` here failed `test_the_script_still_loads_without_the
    # _engine_on_the_path` on the first cut, and the guard was right. Importing
    # the key list rather than restating it keeps ONE definition; only the
    # import site moves.
    from mlb_engine.optimize.bank_cache import LEVERAGE_KEYS
    from tools.qa_portfolio import find_prior_file

    requested = dict(args.leverage)
    unknown = sorted(set(requested) - set(LEVERAGE_KEYS) - {"archetype"})
    if unknown:
        raise ValueError(
            f"--leverage does not take {unknown}; the keys are "
            f"{sorted(LEVERAGE_KEYS)} plus an optional 'archetype'")
    # `find_prior_file`'s own brief shape, not a second one: it reads `date` and
    # `slate.tag`, and it is the ONE resolver for this file so `qa_portfolio` and
    # the build cannot disagree about which prediction a slate has.
    path, how = find_prior_file(
        {"date": args.date, "slate": {"tag": slate_tag}},
        getattr(args, "ownership_pred", None), REPO)
    if path is None or not Path(path).exists():
        raise FileNotFoundError(
            f"--leverage needs this slate's ownership prediction and none was "
            f"found at {path or f'outputs/{args.date}/ownership_pred_{slate_tag}.json'} "
            f"({how}). Emit it with `python tools/ownership_pred.py emit` or "
            f"drop --leverage; building without it would apply a cumulative "
            f"ownership cap against a flat default for every player.")
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    archetype = str(requested.pop("archetype", "") or "").strip()
    archetypes = payload.get("archetypes") or {}
    if archetype and archetype not in archetypes:
        raise ValueError(f"archetype {archetype!r} is not in {path}; it carries "
                         f"{sorted(archetypes)}")
    if not archetype:
        # Named rather than picked from: more than one archetype in the file and
        # no choice from the operator is a question, not a race won by sort
        # order (R70's rule, and `find_prior_file`'s own).
        if len(archetypes) != 1:
            raise ValueError(
                f"{path} carries {len(archetypes)} archetypes {sorted(archetypes)}; "
                "name one with --leverage '{\"archetype\": \"large_field_gpp\", ...}'")
        archetype = next(iter(archetypes))
    own = (archetypes.get(archetype) or {}).get("own_pct_by_player_id") or {}
    if not own:
        raise ValueError(f"{path} archetype {archetype!r} carries no "
                         "own_pct_by_player_id; refusing rather than capping "
                         "against a flat default")
    leverage = {k: v for k, v in requested.items() if v is not None}
    leverage.update({"own_pct_by_player_id": {str(k): float(v)
                                              for k, v in own.items()},
                     "source": str(path)})
    return leverage, {
        "applied": True,
        "source": str(path),
        "sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
        "resolved_by": how,
        "archetype": archetype,
        "players_in_prediction": len(own),
        "constraints": {k: requested.get(k) for k in LEVERAGE_KEYS},
        "label": ("an UNGRADED prior: R209 measured its ORDERING usable "
                  "(Spearman +0.581 over 112 graded players) and its LEVEL not. "
                  "The two numbers are the operator's, forwarded unchanged. "
                  "Never an ROI, win-rate, cash-rate or probability claim."),
    }


def price_showdown_pool(df, *, use_ladder: bool, bat_side: dict, pitcher_hand: dict,
                        supplied_base: dict, supplied_read: dict):
    """The ONE place Base is finalised for a Showdown build, whichever path runs.

    R249. This exists as a function rather than as two call sites because the
    ORDER is the decision: ``apply_base_prior`` first, the supplied number last,
    so a supplied number is the prior the solver ranks on and the salary
    regression never touches it. Written as two inline call sites, that order was
    a property of the source layout and nothing executed it -- a mutation that
    supplied the number BEFORE the prior survived the whole suite, because every
    insertion-point test called the engine function directly and the wiring was
    the untested part. Now the order is a property of one function and the tests
    call it.

    ``use_ladder`` False is the fallback bank path, where no prior is computed
    and Base is raw AvgPointsPerGame. A supplied number replaces that directly;
    wiring only the ladder would make ``--projections`` a silent no-op on exactly
    the `all_healthy` slates where the pool is thinnest.
    """
    from mlb_engine.optimize import showdown_theses as theses

    priced = (theses.apply_base_prior(df, bat_side=bat_side,
                                      pitcher_hand=pitcher_hand)
              if use_ladder else df)
    if supplied_base:
        priced = theses.apply_supplied_base(priced, supplied_base, supplied_read)
    return priced


def showdown_moneyline(args, df, salary_csv=None) -> tuple[dict, dict]:
    """Return ({team: american odds}, note) for the single Showdown game.

    ``salary_csv`` matters on a doubleheader: both legs post under one
    AWAY@HOME key and a Showdown slate is one leg (F18).
    """
    try:
        odds, note = load_odds_packet(args, salary_csv=salary_csv)
    except Exception as exc:
        return {}, {"warning": f"odds unavailable ({exc}); entries split evenly"}
    teams = sorted(df["Team"].unique()) if len(df) else []
    for entry in (odds or {}).values():
        ml = (entry or {}).get("moneyline") or {}
        if all(t in ml for t in teams) and teams:
            return {t: float(ml[t]) for t in teams}, dict(note, matched=True)
    # R29(5): say WHY there is no moneyline. This one sentence used to cover a
    # missing key, an unrecognised payload shape, a parsed-but-unmatched slate
    # and a market that genuinely is not posted, and only the last of those is
    # a reason to accept an even split without investigating.
    if note.get("warning"):
        reason = f"upstream: {note['warning']}"
    elif not odds:
        reason = ("the odds payload resolved to zero games, so no market "
                  "reached this build")
    else:
        reason = (f"{len(odds)} game(s) carried odds but none had a moneyline "
                  f"for both of {teams}; check the slate's team codes")
    return {}, dict(note or {}, matched=False,
                    warning=f"no moneyline for this game ({reason}); entries "
                            f"split evenly between the two sides")


def showdown_relaxation_caution(
    cap_count,
    cap_relaxed: int,
    lock_relaxed: int,
    lock_relaxation_detail,
    share_cap,
    overlap_relaxed: int,
    both_relaxed: int,
    player_cap_count=None,
    player_relaxed: int = 0,
    cap_reassignments=None,
    player_locks_dropped=None,
    player_structurally_feasible: bool = True,
    player_structural_floor=None,
    player_cap_pct=None,
) -> str:
    """The Showdown ladder's relaxation NOTEs, one clause per counter that
    actually fired, each naming its own mechanism.

    R113. A captain-CAP relaxation (the thesis-apportionment step ran out of
    eligible captains under ``max_cpt_exposure_pct`` and fell back to any
    captain) and a captain-LOCK relaxation (the solver could not build a
    feasible lineup with the thesis's assigned captain and dropped the lock,
    substituting a different one) are different events with different
    remedies. They used to be summed into one number and reported as "captain
    cap relaxed" no matter which one fired, always pointing at
    ``captain_exposure.by_player`` -- a table that cannot show a lock
    substitution, because a lock event is not an exposure event. Each clause
    below fires only off its own counter.
    """
    notes = ""
    if cap_relaxed:
        notes += (f" NOTE: the {cap_count}-lineup captain cap relaxed on "
                  f"{cap_relaxed} slot(s) because the pool couldn't support it "
                  "without leaving a reserved row blank -- check "
                  "captain_exposure.by_player before uploading.")
    if lock_relaxed:
        detail = "; ".join(
            f"thesis {d.get('thesis', '?')}: {d.get('requested', '?')} -> {d.get('actual', '?')}"
            for d in (lock_relaxation_detail or [])
        ) or "no detail captured"
        notes += (f" NOTE: the captain LOCK relaxed on {lock_relaxed} slot(s) -- "
                  "the thesis's assigned captain could not produce a feasible "
                  f"lineup under the overlap bound, so the solver substituted a "
                  f"different one ({detail}). This is not a cap event; "
                  "captain_exposure.by_player will not show it.")
    if overlap_relaxed:
        notes += (f" NOTE: the {share_cap}-player overlap bound relaxed on "
                  f"{overlap_relaxed} slot(s); those lineups are still distinct "
                  f"but share more than {share_cap} players with an earlier one.")
    if both_relaxed:
        notes += (f" NOTE: {both_relaxed} slot(s) needed BOTH the overlap bound "
                  "and the captain lock dropped at once; those are the least "
                  "controlled lineups in the bank (R54).")
    # R153. The player-exposure cap's own clauses. Kept separate from the captain
    # ones for R113's reason: they are different mechanisms with different
    # remedies, and captain_exposure.by_player cannot show a player-cap event.
    if player_relaxed:
        notes += (f" NOTE: the {player_cap_count}-entry player exposure cap "
                  f"relaxed on {player_relaxed} slot(s), so at least one player "
                  f"sits above {player_cap_pct:.0%} of the entered set -- read "
                  "player_exposure.by_player before uploading.")
    if cap_reassignments:
        detail = "; ".join(
            f"{d.get('player', '?')} off {d.get('thesis', '?')}"
            for d in cap_reassignments)
        notes += (f" NOTE: {len(cap_reassignments)} thesis captain(s) were "
                  f"REASSIGNED because the named player was already at a cap, so "
                  f"the solver chose a different captain for that game state: "
                  f"{detail}. Nothing relaxed -- the cap held and the thesis label "
                  "is what moved.")
    if player_locks_dropped:
        detail = "; ".join(
            f"{d.get('player', '?')} off {d.get('thesis', '?')}"
            for d in player_locks_dropped)
        notes += (f" NOTE: {len(player_locks_dropped)} thesis lock(s) were dropped "
                  f"because the player was at the exposure cap: {detail}. Those "
                  "lineups are still the thesis's shape, minus that one name.")
    if not player_structurally_feasible:
        notes += (f" NOTE: the player exposure cap of {player_cap_pct:.0%} is "
                  f"below this pool's structural floor of "
                  f"{player_structural_floor:.1%} (roster size over pool size), "
                  "so it could not hold from the first slot regardless of the "
                  "solver. Widen it deliberately or accept the relaxations.")
    return notes


def showdown_excluded_block(df) -> dict:
    """What the salary file's Excluded column removes from a Showdown pool.

    R291(c). Classic has a pool report and this path has none, so the count that
    made the 1940_9g instruction auditable at T-5 had nowhere to land. It lands
    here, on the same footing: the count, the per-team split, the ids, and the
    legal pool the build actually has.

    The reading is ``optimizer_v3.excluded_flags`` -- the one reader, shared with
    Classic and with the solve that enforces it -- so this block cannot disagree
    with what the MILP did.
    """
    from mlb_engine.optimize.optimizer_v3 import excluded_flags

    flags, _ = excluded_flags(df)
    # `column_present` and the unrecognized count are facts about the FILE and
    # only the melt saw it: the frame carries an Excluded column either way now,
    # so deriving "the file had one" from the frame would read True for every
    # build. The melt records them on `attrs`.
    melt_report = dict(df.attrs.get("excluded_column_report") or {})
    excluded = df[flags] if len(df) else df
    keys = [str(k) for k in excluded.get("Player_Key", [])]
    by_team: dict = {}
    for team in (str(t) for t in excluded.get("Team", [])):
        by_team[team] = by_team.get(team, 0) + 1
    legal = df[~flags] if len(df) else df
    return {
        "column_present": bool(melt_report.get("column_present")),
        "applied": int(len(excluded)),
        "by_team": dict(sorted(by_team.items())),
        "player_keys": sorted(keys)[:50],
        "unrecognized_kept": int(melt_report.get("unrecognized_kept") or 0),
        "unrecognized_values": list(melt_report.get("unrecognized_values") or []),
        "legal_players": int(len(legal)),
        "legal_teams": sorted({str(t) for t in legal.get("Team", [])}),
        "note": "salary-file Excluded column, OR'd across a player's CPT and "
                "UTIL rows; only an affirmative token excludes "
                "(optimizer_v3.read_excluded_cell) and build_showdown_lineup is "
                "what removes the row, on every rung",
    }


def run_showdown(args, slate_dir: Path, salary: Path, entries: Path) -> tuple[int, dict]:
    from mlb_engine.optimize import showdown as sd
    from mlb_engine.optimize import showdown_theses as st

    from mlb_engine.intake.slate_intake_manager import parse_dk_salary_csv, slate_clock

    df = sd.melt_showdown_salary_csv(str(salary))
    # R291(c). Read before anything is built, so a restriction that leaves no
    # legal lineup refuses HERE with the reason, rather than surfacing as an
    # empty bank three hundred lines later. The melt's own single-team refusal
    # cannot see this: it runs on the carried pool, which is the whole point of
    # carrying rather than dropping.
    sd_excluded = showdown_excluded_block(df)
    if sd_excluded["applied"] and len(sd_excluded["legal_teams"]) < 2:
        print(json.dumps({
            "status": "showdown_excluded_column_leaves_one_team",
            "date": args.date,
            "excluded_column": sd_excluded,
            "remedy": "a DK Showdown lineup must carry both sides of the "
                      "matchup, so an Excluded column that leaves one team "
                      "cannot produce a legal entry; narrow the exclusion",
        }, indent=1))
        return 4, {}
    clock = slate_clock(players=parse_dk_salary_csv(str(salary)))
    reserved = sd.read_showdown_reserved_rows(str(entries))
    # Only blank reserved rows are fillable; a complete row is immutable, and
    # blank rows are what block certification when left unfilled.
    rows = [r for r in (reserved.get("reserved") or []) if not r.get("is_complete")]
    n_entries = min(args.entries, len(rows)) if args.entries else len(rows)
    if not n_entries:
        print(json.dumps({"status": "no_blank_reserved_entries",
                          "date": args.date}, indent=1))
        return 4, {}

    overrides = args.controls_override or {}
    cpt_cap = overrides.get("max_cpt_exposure_pct", sd.DEFAULT_MAX_CPT_EXPOSURE_PCT)
    share_cap = overrides.get("max_shared_players", sd.DEFAULT_MAX_SHARED_PLAYERS)
    # R153. The third portfolio control. Reads from the same --controls-override
    # dict as the other two, so the escape hatch is one flag rather than three.
    player_cap_pct = overrides.get("max_player_exposure_pct",
                                   sd.DEFAULT_MAX_PLAYER_EXPOSURE_PCT)
    # R239(b). The fourth, and the first that binds per contest. Same one dict.
    cpt_per_contest = overrides.get("max_cpt_per_contest",
                                    sd.DEFAULT_MAX_CPT_PER_CONTEST)

    # Handedness and the moneyline are what make the ladder more than a relabeled
    # points-max bank, so gather them before deciding the path. Both are
    # best-effort: a Showdown build must not fail because an odds endpoint is
    # down, it must say the input was missing and build anyway.
    bat_side, pitcher_hand, feed_note = showdown_handedness(args, slate_dir, df)
    moneyline, odds_note = showdown_moneyline(args, df, salary_csv=salary)

    basis = str(df["Pool_Basis"].iloc[0]) if len(df) else "empty"
    posted = int(df["Batting_Order"].notna().sum()) if len(df) else 0
    # The ladder is conditioned on batting order and declared starters. With
    # nothing posted there is no order to condition on, so the templates would be
    # labels over a pool the engine cannot actually distinguish. Fall back rather
    # than ship a thesis name that means nothing.
    use_ladder = (basis == "declared_starters" and posted >= 2 * 9)

    ladder_meta: dict = {}
    solve_diag: dict = {}
    cpt_diagnostics: dict = {}
    report: dict = {}

    # R239 seam. `rows` already carries the contest each reserved row belongs to,
    # parsed at read_showdown_reserved_rows and then dropped -- the entry-to-
    # contest fact existed here before any bank was built and nothing downstream
    # ever saw it. This vector is aligned to the SAME order used by
    # `zip(rows, bank)` below, which is what makes ladder slot j and rows[j] the
    # same entry. Passed through; nothing reads it for a decision yet.
    contest_of_entry = [r["contest_id"] for r in rows[:n_entries]]

    # R249. The supplied prior, read before either build path so a file the
    # engine cannot open costs nothing but the read. Both paths get it: the
    # ladder prices through `apply_base_prior`, the fallback bank ranks on raw
    # AvgPointsPerGame, and wiring only the ladder would make `--projections` a
    # silent no-op on exactly the `all_healthy` slates where the pool is
    # thinnest -- the R242 shape this flag's own refusal exists to avoid.
    supplied_base: dict = {}
    supplied_read: dict = {}
    if getattr(args, "projections", None):
        try:
            supplied_base, supplied_read = st.read_supplied_base(args.projections)
        except (OSError, ValueError) as exc:
            print(json.dumps({"status": "projections_unreadable", "date": args.date,
                              "projections": str(args.projections),
                              "error": str(exc)}, indent=1))
            return 4, {}

    if use_ladder:
        priced = price_showdown_pool(df, use_ladder=True, bat_side=bat_side,
                                     pitcher_hand=pitcher_hand,
                                     supplied_base=supplied_base,
                                     supplied_read=supplied_read)
        ladder_meta = st.build_thesis_ladder(priced, n_entries, moneyline=moneyline,
                                             max_cpt_exposure_pct=cpt_cap,
                                             contest_of_entry=contest_of_entry,
                                             max_cpt_per_contest=cpt_per_contest)
        theses = ladder_meta["theses"]
        solved = st.solve_ladder(priced, theses, max_shared_players=share_cap,
                                 max_player_exposure_pct=player_cap_pct,
                                 max_cpt_exposure_pct=cpt_cap,
                                 diagnostics=solve_diag,
                                 contest_of_entry=contest_of_entry,
                                 max_cpt_per_contest=cpt_per_contest)
        if any(lu is None for lu in solved):
            print(json.dumps({"status": "ladder_infeasible",
                              **refusal_stamp("showdown_ladder_infeasible"),
                              "date": args.date,
                              "unsolved": [t["name"] for t, lu in zip(theses, solved)
                                           if lu is None]}, indent=1))
            return 3, {}
        bank = list(solved)
        report = st.portfolio_report(priced, theses, solved)
        certs = [sd.certify_showdown(lineup, priced) for lineup in bank]
    else:
        # R249. Same seam through the same function, with no prior to bypass: on
        # this path Base IS raw AvgPointsPerGame, so a supplied number replaces
        # it directly and the recorded ratio is against that same column.
        df = price_showdown_pool(df, use_ladder=False, bat_side=bat_side,
                                 pitcher_hand=pitcher_hand,
                                 supplied_base=supplied_base,
                                 supplied_read=supplied_read)
        bank = sd.build_showdown_bank(df, n=n_entries, max_cpt_exposure_pct=cpt_cap,
                                      max_shared_players=share_cap,
                                      max_player_exposure_pct=player_cap_pct,
                                      diagnostics=cpt_diagnostics)
        if len(bank) < n_entries:
            print(json.dumps({"status": "bank_short",
                              **refusal_stamp("showdown_bank_short"),
                              "date": args.date,
                              "built": len(bank), "needed": n_entries}, indent=1))
            return 3, {}
        bank = bank[:n_entries]
        certs = [sd.certify_showdown(lineup, df) for lineup in bank]

    failed = [c for c in certs if not c.get("passed")]
    if failed:
        print(json.dumps({"status": "not_certified",
                          **refusal_stamp("showdown_not_certified"),
                          "date": args.date,
                          "errors": [c.get("errors") for c in failed]}, indent=1))
        return 3, {}

    # zip() silently truncates to the shorter side, so a bank short of the
    # reserved-row count left the remainder blank and shipped. Say so instead.
    if len(bank) < len(rows):
        print(json.dumps({
            "status": "bank_short_of_reserved_rows",
            **refusal_stamp("showdown_bank_short_of_reserved_rows"),
            "date": args.date,
            "reserved_blank_rows": len(rows),
            "lineups_built": len(bank),
            "shortfall": len(rows) - len(bank),
            "note": "a blank reserved row blocks certification; lower --entries-count "
                    "to the number built, or rerun to deepen the bank",
        }, indent=1))
        return 3, {}

    out_dir = REPO / "outputs" / args.date
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"DKEntries_showdown{slate_tag_suffix(salary)}.csv"
    assignments = [
        {"entry_id": row["entry_id"], "roster_ids": list(lineup["roster_ids"])}
        for row, lineup in zip(rows, bank)
    ]
    # R96(2). Was: write dest, then try to record and swallow the failure, so a
    # raising recorder left an uploadable Showdown file with no row -- one of the
    # six paths R96 enumerated, and the shape of the two unrecorded Showdown files
    # in outputs/2026-08-06/. The write now stops at the DO_NOT_UPLOAD_ staging
    # name write_showdown_entries already uses, and the name is promoted only once
    # a row names it. Everything downstream reads `delivered`, never `dest`.
    from mlb_engine.entries.upload_manifest import (
        record_delivery, stage_salary_for_delivery, unrecorded_name,
    )
    write_report = sd.write_showdown_entries(str(entries), str(dest), assignments,
                                             promote=False)
    if not write_report.get("passed"):
        print(json.dumps({"status": "showdown_export_failed",
                          **refusal_stamp("showdown_export_failed"),
                          "date": args.date,
                          "errors": write_report.get("errors")}, indent=1))
        return 3, {}
    provisional = unrecorded_name(dest)
    delivered = provisional
    manifest_error = ""
    try:
        record_delivery(
            date=args.date, delivered_file=dest, hash_source=provisional,
            contest_type="showdown",
            slate_tag=slate_tag_suffix(salary).lstrip("_"),
            contest_ids=sorted({r["contest_id"] for r in rows}),
            contest_names=sorted({r.get("contest_name", "") for r in rows}),
            # R34: was status="delivered", which is not in STATUS_VALUES and so
            # read as current everywhere that only filters out 'superseded'.
            # 'candidate' is the honest status for a review-grade Showdown file:
            # it has not been through the three certification gates, so it is a
            # candidate and preflight must not promote it past that.
            entries=len(assignments), run_id=None, status="candidate",
            certification="review_grade",
            notes="Showdown ships review-grade; it does not pass the three "
                  "certification gates. See CLAUDE.md.",
        )
        # R96(4): a Showdown slate with no staged salary can only ever be mined
        # standings_only, which is how the 2026-08-06 SD contests were lost.
        stage_salary_for_delivery(args.date, str(salary),
                                  slate_tag_suffix(salary).lstrip("_"))
        os.replace(provisional, dest)
        delivered = dest
    except Exception as exc:  # noqa: BLE001 - bookkeeping never fails a build
        manifest_error = str(exc)
        print(f"upload manifest not recorded: {exc}; the file was NOT promoted "
              f"and is at {provisional.name}, which names itself rather than "
              f"waiting for preflight to hard-fail it", file=sys.stderr)
    template = sd.verify_template_preserved(str(entries), str(delivered))

    if use_ladder:
        cap_count = ladder_meta.get("captain_cap_count")
        captain_counts = report.get("captain_exposure") or {}
        # R113. Two different mechanisms, kept separate rather than pre-summed:
        # cap_relaxed is the thesis-apportionment step running out of eligible
        # captains under the exposure cap; lock_relaxed is the SOLVER dropping
        # a thesis's assigned captain because no feasible lineup existed with
        # it locked.
        #
        # R250. They are no longer summed for the `clean` verdict, and that sum
        # was the defect. R113 split these two in the diagnostics and this line
        # re-joined them one function later, so `clean` came back FALSE on
        # `captain_relaxed_slots: 1` while realized captain exposure was 21.7%
        # under a 25% cap -- an APPORTIONMENT shortfall reported as a relaxation
        # the realized set never breached. `clean` now reads realized facts only.
        # The apportionment shortfall keeps its own name below: it is real, it is
        # worth reading, and it is not a control giving way. A `clean` flag that
        # reads false over held caps (this) while reading true over a degraded
        # tail (R247) is measuring procedure rather than the portfolio.
        cap_relaxed = ladder_meta.get("captain_cap_relaxed") or 0
        lock_relaxed = solve_diag.get("captain_lock_relaxed") or 0
        lock_relaxation_detail = list(solve_diag.get("lock_relaxation_detail") or [])
        apportionment_shortfall = cap_relaxed
        relaxed_slots = lock_relaxed
        overlap_relaxed = solve_diag.get("overlap_relaxed") or 0
        # R54(a)/(b)/(c). Both new facts, on both paths.
        both_relaxed = solve_diag.get("both_relaxed") or 0
        ignored_locks = list(solve_diag.get("ignored_locks") or [])
        max_overlap = report.get("max_pairwise_overlap")
        # R263 shadow, Ben's dated decision of 2026-08-28. Counted off the solved
        # lineups, printed beside the caps below, steers nothing.
        construction_shadow = st.construction_shadow(
            priced, report, max_cpt_exposure_pct=cpt_cap)
        # R153.
        player_counts = report.get("player_exposure") or {}
        player_cap_count = solve_diag.get("player_cap_count")
        player_relaxed = solve_diag.get("player_relaxed") or 0
        player_structural_floor = solve_diag.get("player_cap_structural_floor")
        # Not relaxations: a capped player taken off a thesis's own cpt or locks so
        # the cap could hold. Named because the thesis then built with a captain its
        # label does not imply.
        cap_reassignments = (list(solve_diag.get("player_cap_cpt_reassigned") or [])
                             + list(solve_diag.get("cpt_cap_reassigned") or [])
                             + list(solve_diag.get("contest_cpt_reassigned") or []))
        player_locks_dropped = list(solve_diag.get("player_cap_locks_dropped") or [])
        contest_cap_relaxed = solve_diag.get("contest_cap_relaxed") or 0
        # R223. The fourth counter, and the withdrawal count beside it.
        cpt_cap_relaxed = solve_diag.get("cpt_cap_relaxed") or 0
        cap_reassignments_withdrawn = solve_diag.get("cap_reassignments_withdrawn") or 0
        # R158. Compute facts from the ladder's own solves.
        solver_timeouts = solve_diag.get("solver_timeouts") or 0
        time_limited_accepted = solve_diag.get("time_limited_accepted") or 0
        solver_timeout_detail = list(solve_diag.get("solver_timeout_detail") or [])
        # R250. The apex caution, carried straight through from the ladder.
        captain_budget_inversions = list(
            solve_diag.get("captain_budget_inversions") or [])
        captain_budget_reserved = dict(
            solve_diag.get("captain_budget_reserved") or {})
        captain_budget_util_blocks = solve_diag.get("captain_budget_util_blocks") or 0
    else:
        cap_count = cpt_diagnostics.get("cap_count")
        captain_counts = cpt_diagnostics.get("captain_exposure") or {}
        relaxed_slots = cpt_diagnostics.get("relaxed_slots") or 0
        # R263: the bank path builds no per-lineup report, so the shadow has no
        # team_split to read. UNAVAILABLE with the reason, never an empty mix that
        # would print as "0% 5-1" and read as a finding.
        construction_shadow = {
            "label": "R263 CONSTRUCTION SHADOW — unavailable on this path",
            "entries_solved": len(bank),
            "steers": False,
            "unavailable_reason": (
                "the points-max bank path builds no thesis report, so no "
                "per-lineup captain or team split is recorded. The shadow "
                "requires the thesis ladder, which requires both posted batting "
                "orders"),
        }
        # R113 does not apply to this path: build_showdown_bank has one cap
        # mechanism (a rotating cpt_exclude list), no separate per-thesis lock,
        # so there is nothing to split.
        cap_relaxed = relaxed_slots
        lock_relaxed = 0
        lock_relaxation_detail = []
        # R250. This path has no apportionment step -- `build_showdown_bank`
        # rotates a cpt_exclude list and its relaxations ARE realized, so
        # `relaxed_slots` stays in `clean` here and nothing is carved out.
        apportionment_shortfall = 0
        overlap_relaxed = cpt_diagnostics.get("overlap_relaxed_slots") or 0
        both_relaxed = cpt_diagnostics.get("both_relaxed_slots") or 0
        ignored_locks = list(cpt_diagnostics.get("ignored_locks") or [])
        max_overlap = None
        # R153. build_showdown_bank keys its counts by Player_Key, not name, so
        # the names are resolved here to match the ladder path's shape.
        _name_by_key = dict(zip(df["Player_Key"], df["Name"])) if len(df) else {}
        player_counts = {_name_by_key.get(k, k): c
                         for k, c in (cpt_diagnostics.get("player_exposure") or {}).items()}
        player_cap_count = cpt_diagnostics.get("player_cap_count")
        player_relaxed = cpt_diagnostics.get("player_relaxed_slots") or 0
        # No thesis on this path, so nothing can be reassigned off one.
        cap_reassignments = []
        player_locks_dropped = []
        # R239(b). The per-contest cap is enforced in solve_ladder, which this
        # path does not use, so nothing relaxed it. Stated as 0 rather than left
        # undefined; the per_contest REPORT still runs on this path, so a breach
        # here is visible even though no control prevented it.
        contest_cap_relaxed = 0
        # R223. The portfolio captain cap relaxation lives in `solve_ladder`,
        # which this path does not use; its single cap mechanism is already
        # reported as `captain_relaxed_slots` above. Stated as 0 rather than left
        # undefined, same discipline as `contest_cap_relaxed`.
        cpt_cap_relaxed = 0
        cap_reassignments_withdrawn = 0
        # R158. The bank ladder DOES report these, and on this path they are the
        # only solver-status facts there are.
        solver_timeouts = cpt_diagnostics.get("solver_timeouts") or 0
        time_limited_accepted = cpt_diagnostics.get("time_limited_accepted") or 0
        solver_timeout_detail = []
        # R250. No thesis on this path, so no rung NAMES a captain and the
        # inversion condition cannot arise. Stated as empty rather than left
        # undefined, same discipline as `contest_cap_relaxed`.
        captain_budget_inversions = []
        captain_budget_reserved = {}
        captain_budget_util_blocks = 0
        player_structural_floor = cpt_diagnostics.get("player_cap_structural_floor")
    # R239(c). Computed on BOTH paths: the points-max bank builds no thesis
    # report, but it does build lineups, and the contest each one is entered into
    # is known either way. A slice that exists only on the ladder path would be
    # absent exactly when the operator has least other information.
    per_contest = st.per_contest_report(
        priced if use_ladder else df, bank, contest_of_entry,
        max_cpt_per_contest=overrides.get("max_cpt_per_contest",
                                          sd.DEFAULT_MAX_CPT_PER_CONTEST))

    captain_exposure = {
        key: {"count": count, "pct": round(100.0 * count / n_entries, 1)}
        for key, count in sorted(captain_counts.items(), key=lambda kv: -kv[1])
    }
    realized_cpt_pct = max((v["pct"] for v in captain_exposure.values()), default=0.0)
    player_exposure = {
        key: {"count": count, "pct": round(100.0 * count / n_entries, 1)}
        for key, count in sorted(player_counts.items(), key=lambda kv: -kv[1])
    }
    realized_player_pct = max((v["pct"] for v in player_exposure.values()), default=0.0)

    degraded_entries = showdown_degraded_entries(assignments, bank)
    print(f"degraded: {format_degraded_line(degraded_entries)}", file=sys.stderr)

    brief = {
        # Showdown ships as v0.2-review (cpt exposure cap added 2026-07-23) and
        # Phase 3 is not complete, so this path is labeled review-grade. It is
        # not the Classic certification contract.
        "status": "review_grade_build",
        "contest_type": "showdown",
        "date": args.date,
        "entries": n_entries,
        "delivered_path": str(delivered),
        "delivered_path_repo": manifest_repo_relative(delivered),
        "delivered_sha256": manifest_sha256(delivered),
        # R96(2). A brief that cited `dest` while the bytes sat under
        # DO_NOT_UPLOAD_ would send the operator to a file that does not exist.
        "manifest_recorded": not manifest_error,
        "manifest_error": manifest_error,
        "upload_manifest": manifest_repo_relative(
            REPO / "outputs" / args.date / "upload_manifest.json"),
        "showdown_module_version": sd.VERSION,
        # R249. The whole point of the item is that the operator's previous
        # workaround -- editing the APPG column of the salary file -- moved
        # captains and was recorded NOWHERE. A fix that is also invisible has
        # not closed it, so this block is present on every Showdown brief and
        # says `applied: false` when no file was supplied, rather than being
        # absent and leaving "was a projection used" unanswerable.
        "supplied_base": ((priced if use_ladder else df).attrs.get(
            "supplied_base_report") or {"applied": False, "source": None}),
        "pool": {
            "players": int(len(df)),
            "basis": (str(df["Pool_Basis"].iloc[0]) if len(df) else "empty"),
            "declared_starters": int(df["Is_Declared_Starter"].sum()) if len(df) else 0,
            "posted_hitters": int(df["Batting_Order"].notna().sum()) if len(df) else 0,
            # R291(c). Classic's `pool_report.excluded_column`, on the path that
            # had no pool report. `players` above is the CARRIED pool; read
            # `legal_players` for what the solve could actually roster.
            "excluded_column": sd_excluded,
        },
        "slate_clock": {
            "first_lock_utc": clock.get("first_lock_utc"),
            "minutes_to_deadline": clock.get("minutes_to_deadline"),
            "past_deadline": clock.get("past_deadline"),
        },
        "certification": {
            "per_lineup_passed": all(c.get("passed") for c in certs),
            "template_preserved": template.get("passed"),
            "write_report": write_report,
        },
        "captain_exposure": {
            "cap_pct": cpt_cap,
            "cap_count": cap_count,
            "realized_max_pct": realized_cpt_pct,
            "by_player": captain_exposure,
            "relaxed_slots": relaxed_slots,
            # R113. Split so a reader can tell which control actually gave way:
            # by_player can only ever show a cap event.
            "cap_relaxed_slots": cap_relaxed,
            "lock_relaxed_slots": lock_relaxed,
            "lock_relaxation_detail": lock_relaxation_detail,
        },
        # R153 (Ben, 2026-08-19). The third portfolio control, reported on the same
        # footing as the captain cap it mirrors. This is the PORTFOLIO-level
        # washout axis CLAUDE.md's dual objective names: the overlap bound stops
        # two lineups being one lineup and the captain cap stops one captain owning
        # the set, and neither of them stops one bat appearing in most entries.
        "player_exposure": {
            "cap_pct": player_cap_pct,
            "cap_count": player_cap_count,
            "realized_max_pct": realized_player_pct,
            "by_player": player_exposure,
            "relaxed_slots": player_relaxed,
            # NOT relaxations. A capped player was taken off a thesis's own captain
            # slot or locks so the cap could hold, so the thesis built with a
            # different captain than its label implies. Recorded because that is a
            # fact the reader wants, not because anything gave way.
            "cap_reassignments": cap_reassignments,
            "locks_dropped": player_locks_dropped,
            # The lowest cap that can fill this many entries from this pool by
            # counting alone. A cap_pct below it cannot hold no matter what the
            # solver does, and the engine reports that rather than widening a
            # bound Ben set (CLAUDE.md, Autonomy).
            "structural_floor_pct": (round(player_structural_floor, 4)
                                     if player_structural_floor else None),
            "structurally_feasible": (player_structural_floor is None
                                      or not player_cap_pct
                                      or player_cap_pct >= player_structural_floor),
        },
        # R263 shadow, Ben's dated decision of 2026-08-28. Sits HERE, between the
        # two exposure caps and the diversity block, because "beside the caps" is
        # where the item put it and because that is where the reader already is.
        # It steers nothing: no thesis, posture, or constraint reads this key, and
        # `steers: False` says so in the artifact rather than only in a comment.
        "construction_shadow": construction_shadow,
        # R247(a). BOTH formats. The two sightings that filed this item were
        # Showdown (1905_1g_sd, $6,100 left and proxy 38.19 against a median of
        # 54.87) and the third was Classic, so instrumenting only the Classic
        # frontier would leave the originals uninstrumented. Same function, same
        # archive-derived bars, and the Showdown contract's OWN salary cap rather
        # than Classic's assumed. Read `entries_intact_by_design` on the Classic
        # side for the other half; Showdown has no frontier to carry it.
        "degraded_entries": degraded_entries,
        "diversity": {
            "max_shared_players": share_cap,
            "max_pairwise_overlap": max_overlap,
            "overlap_relaxed_slots": overlap_relaxed,
            "all_unique_rosters": report.get("all_unique_rosters") if use_ladder else None,
        },
        # R54. The counts that decide whether the portfolio is clean. A portfolio
        # is not clean because the gates passed; it is clean when these are zero.
        # ``both_relaxed_slots`` is a subset of the other two, which each count
        # every lineup built without that control, whichever rung produced it.
        # R239(c). What was ENTERED, sliced by the contest that pays it. The
        # counters above answer "what share of the entered set", which in a
        # one-ticket satellite is the wrong denominator: the prize resolves per
        # contest. On 2026-08-28 this build printed realized_max_pct 23.8 under a
        # 0.25 cap while one 2-entry contest carried a single captain across both
        # entries.
        "per_contest": per_contest,
        "counted_relaxations": {
            "captain_relaxed_slots": relaxed_slots,
            "overlap_relaxed_slots": overlap_relaxed,
            "both_relaxed_slots": both_relaxed,
            # R153. The third control has to be in the clean verdict, or "clean"
            # keeps meaning "two of three held" and reads as all of them.
            "player_relaxed_slots": player_relaxed,
            # R54(c). Locks the solver was handed and could not enforce, because
            # the key is absent from the melted pool. Non-empty means the bank
            # was built without a player the operator asked for.
            "ignored_locks": ignored_locks,
            # R239(c). The fourth control joins the clean verdict on R153's own
            # reasoning, one level down: "clean" meaning "the portfolio controls
            # held" reads as "the portfolio is clean", and on 2026-08-28 it read
            # true on a file that violated the captain cap's own value inside two
            # contests. A breach here is NOT a relaxation (nothing gave way), so
            # it is counted separately and ANDed rather than folded into the
            # relaxation counts.
            "per_contest_cap_breaches": len(per_contest.get("over_cap") or []),
            # R239(b). The true floor gave the per-contest cap up rather than
            # leave a blank reserved row. A relaxation, so it is counted like
            # one; `contest_cpt_reassigned` beside it is NOT one and is not here.
            "contest_cap_relaxed_slots": contest_cap_relaxed,
            # R223. The PORTFOLIO captain cap giving way, which until now nothing
            # counted: the floor rung dropped it in silence, so a brief could read
            # `0 relaxations` over a breached 25% cap. Distinct from
            # `captain_relaxed_slots` above, which on the ladder path is the
            # APPORTIONMENT step (R113's split) and on the bank path is that
            # path's single cap mechanism.
            "cpt_cap_relaxed_slots": cpt_cap_relaxed,
            # R223. NOT a relaxation and deliberately outside `clean`: a
            # reassignment record withdrawn because a lower rung re-seated the
            # captain it named. It is reported so the reader knows a record was
            # removed rather than never written.
            "cap_reassignments_withdrawn": cap_reassignments_withdrawn,
            # R250. Reported, deliberately OUTSIDE `clean`. The thesis
            # apportionment ran short of eligible captains under the cap; the
            # REALIZED set never breached anything, and calling that a relaxation
            # is what made `clean` read false over caps that held.
            "captain_apportionment_shortfall": apportionment_shortfall,
            # R250. The apex condition, named rather than left to be derived by
            # crossing three tables: a player named captain by at least one rung
            # who finished at the player cap having captained zero times. His
            # whole exposure budget was spent at 1.0x and none of it at 1.5x.
            "captain_budget_inversions": captain_budget_inversions,
            "clean": (not (relaxed_slots or overlap_relaxed or both_relaxed
                           or player_relaxed or ignored_locks
                           or contest_cap_relaxed or cpt_cap_relaxed
                           or captain_budget_inversions)
                      and not (per_contest.get("over_cap") or [])),
        },
        # R158. Compute facts, deliberately NOT inside `counted_relaxations` and
        # deliberately not in `clean`. A timeout is an infrastructure limit, not a
        # control giving way, and folding it into the relaxation verdict would
        # recreate the exact conflation R158 removed from the ladder. A brief with
        # `clean: true` and `solver_timeouts` nonzero is saying the controls all
        # held and the clock ran out: raise the time limit, do not touch a control
        # and do not reduce the pool.
        # R250. The hold as planned and as it actually bound. NOT a relaxation and
        # NOT a cap breach -- nothing gave way; a player several rungs name as
        # captain was stopped from spending the last of his own exposure budget at
        # 1.0x before those rungs solved. Reported so the reader can see the
        # allocation the ladder made on purpose.
        "captain_budget": {
            "reserved": captain_budget_reserved,
            "util_blocked_slots": captain_budget_util_blocks,
            "label": "an allocation of exposure between the 1.5x and 1.0x seats, "
                     "never a change to any cap value",
        },
        "solver_compute": {
            "solver_timeouts": solver_timeouts,
            "time_limited_accepted": time_limited_accepted,
            "timeout_detail": solver_timeout_detail,
            "label": "infrastructure limits, never a strategy change",
        },
        "construction": ({
            "mode": "thesis_ladder",
            "module_version": st.VERSION,
            "win_share_basis": ladder_meta.get("win_share_basis"),
            "favorite": (ladder_meta.get("shape") or {}).get("favorite"),
            "win_share": (ladder_meta.get("shape") or {}).get("win_share"),
            "allocation": ladder_meta.get("allocation"),
            "bullpen_teams": (ladder_meta.get("shape") or {}).get("bullpen_teams"),
            "platoon_unresolved_teams": list(
                (priced.attrs.get("platoon_unresolved_teams") or [])),
            "handedness": feed_note,
            "odds": odds_note,
            "lineups": report.get("lineups"),
            "player_exposure": report.get("player_exposure"),
        } if use_ladder else {
            "mode": "points_max_bank",
            "reason": (f"pool basis is {basis!r} with {posted} posted hitters; the "
                       "thesis ladder needs both posted batting orders to "
                       "condition on, so it was not used"),
        }),
        "caution": (f"showdown.py is v{sd.VERSION} and Phase 3 is not complete. "
                    "Per-lineup checks, template preservation, the captain "
                    "exposure cap, the player exposure cap, and the roster-overlap "
                    "bound passed, but this is not the Classic three-gate "
                    "certification. Review before uploading."
                    # R113: cap and lock relaxations are named separately, each
                    # off its own counter, rather than summed into one sentence
                    # that always blamed the cap.
                    + showdown_relaxation_caution(
                        cap_count, cap_relaxed, lock_relaxed, lock_relaxation_detail,
                        share_cap, overlap_relaxed, both_relaxed,
                        player_cap_count=player_cap_count,
                        player_relaxed=player_relaxed,
                        cap_reassignments=cap_reassignments,
                        player_locks_dropped=player_locks_dropped,
                        player_structurally_feasible=(
                            player_structural_floor is None or not player_cap_pct
                            or player_cap_pct >= player_structural_floor),
                        player_structural_floor=player_structural_floor,
                        player_cap_pct=player_cap_pct,
                    )
                    # R54(c). Loudest of the four, because it is not a relaxation
                    # the solver chose: it is an instruction that did not arrive.
                    + (f" NOTE: {len(ignored_locks)} lock(s) named a player the "
                       f"melted pool does not carry and were IGNORED: "
                       f"{', '.join(ignored_locks)}. The bank was built without "
                       "them; check the key against the salary file before "
                       "uploading (R54)."
                       if ignored_locks else "")
                    + (" NOTE: no moneyline was available, so entries were split "
                       "evenly between the two sides rather than weighted to the "
                       "market."
                       if use_ladder and ladder_meta.get("win_share_basis")
                       == "even_split_no_market_input" else "")
                    # R291(c). The instruction, stated where the operator reads
                    # the build's own caveats. Without it the only trace of an
                    # accepted exclusion was a smaller pool nobody counted --
                    # the 1940_9g failure, one contest type over.
                    + (f" NOTE: the salary file excludes "
                       f"{sd_excluded['applied']} of {len(df)} melted players "
                       f"via its Excluded column "
                       f"({', '.join(f'{t}={n}' for t, n in sd_excluded['by_team'].items())}); "
                       f"this build's legal pool is "
                       f"{sd_excluded['legal_players']} and no rung can relax "
                       f"that."
                       if sd_excluded["applied"] else "")
                    + (f" NOTE: {sd_excluded['unrecognized_kept']} Excluded "
                       f"cell(s) hold values this engine does not recognize; "
                       f"those players were KEPT in the pool."
                       if sd_excluded["unrecognized_kept"] else "")),
    }
    # R290(c). ILLEGAL unconditionally: a changed non-roster cell means this is
    # no longer the template DK issued, and no label makes that enterable.
    if not template.get("passed"):
        brief.update(refusal_stamp("showdown_template_broken"))
    return (0 if template.get("passed") else 3), brief


def inert_factors(factors) -> list:
    """Which factors were computed for rows and moved NONE of them (R117(b)).

    ``factors`` is a sequence of ``(name, by_player_id_map, report)``. A factor
    is INERT when it scored at least one row and every value it produced is the
    neutral 1.0 -- which is arithmetically identical to not computing it at all,
    and is what the brief could not distinguish from a factor that applied
    evenly. A factor that scored NOTHING is absent rather than inert: that is a
    different fact with its own warnings, and folding the two together is how
    "F4 is off for this build" came to read like routine enrichment noise.

    Read the counts off the emitted MAP, not off a report key: the three factors
    do not agree on what they call their row count (``hitters_scored``,
    ``games_priced``, ``games_scored``), and a count derived from the thing the
    solver actually received cannot drift from it.
    """
    NON_NEUTRAL_KEY = {"F1": "non_neutral_f1", "F4": "non_neutral_f4",
                       "F5": "non_neutral_f5"}
    out = []
    for name, by_player, report in factors:
        rows = len(by_player or {})
        if not rows:
            continue
        key = NON_NEUTRAL_KEY.get(str(name).upper())
        non_neutral = int((report or {}).get(key) or 0) if key else 0
        if non_neutral:
            continue
        out.append({"factor": str(name).upper(), "rows_scored": rows,
                    "non_neutral": non_neutral})
    return sorted(out, key=lambda row: row["factor"])


def format_inert_factors_line(inert) -> str:
    """One review line for the inert-factor block, in the gates' own voice.

    R117(b). `f4_non_neutral: 0` of 180 hitters certified clean on 1910_10g
    while the only surface saying so was an enrichment warning at the top of the
    log. This prints where the operator reads gates, and it says what the number
    MEANS -- a factor at 1.0 everywhere ranked nothing -- because the count
    alone reads as a tally rather than as a dead input.
    """
    if not inert:
        return "none inert: every computed factor moved at least one row"
    parts = [f"{row['factor']} scored {row['rows_scored']} row(s) and moved none"
             for row in inert]
    return ("INERT " + "; ".join(parts)
            + " -- a factor at neutral 1.0 everywhere ranked nothing, which is "
              "not the same as applying evenly")


def format_frontier_line(frontier: dict | None) -> str:
    """One review line for R126's block: apex, then what binds the washout.

    A separate function because a print built inline is a print nothing can
    test, and the two facts worth reading here are the ones a session at T-10
    skips if they take a paragraph. Wording is deliberate: `retains` and
    `intact` describe the counterfactual, never a chance of anything.
    """
    if not frontier or not frontier.get("available"):
        reason = (frontier or {}).get("unavailable_reason") or "not computed"
        return f"UNAVAILABLE ({reason})"
    apex = frontier.get("apex") or {}
    parts = [
        f"apex total {apex.get('ceiling_total')} "
        f"mean {apex.get('ceiling_mean')} "
        f"best {apex.get('ceiling_best')} (entry {apex.get('best_entry_id')})"
    ]
    wash = frontier.get("washout") or {}
    if wash.get("available"):
        n = frontier.get("entries")
        # R247(c). "N/n entries untouched" is the phrase that misled on 1605_2g,
        # so the split travels with it here too. Printing the bare count and the
        # split only in the JSON would leave the misleading number as the one a
        # session at T-10 actually reads.
        intact = wash.get("entries_fully_intact_at_binding_game")
        by_design = wash.get("entries_intact_by_design_at_binding_game")
        degraded = wash.get("entries_intact_but_degraded_at_binding_game")
        ambiguous = wash.get("entries_intact_proxy_only_at_binding_game")
        untouched = f"{intact}/{n} entries untouched"
        if by_design is not None:
            split = [f"{by_design} by design"]
            if degraded:
                split.append(f"{degraded} DEGRADED -- nothing at stake, "
                             f"not a hedge")
            if ambiguous:
                split.append(f"{ambiguous} low-proxy only, which on this slate "
                             f"cannot tell a hedge from a bad build")
            untouched += " (" + "; ".join(split) + ")"
        parts.append(
            f"washout binds on {wash.get('binding_game')}: zeroing its bats "
            f"retains {wash.get('worst_ceiling_retained_pct')}% of portfolio "
            f"ceiling with {untouched}")
    else:
        parts.append(f"washout UNAVAILABLE ({wash.get('unavailable_reason')})")
    block = frontier.get("correlated_block") or {}
    if block.get("available"):
        trip = block.get("worst_triple") or {}
        parts.append(
            f"worst triple {trip.get('entries_sharing')}/{block.get('entries')} "
            f"entries, {block.get('entries_with_at_most_one_of_top_trio')}"
            f"/{block.get('entries')} carry at most one of the top trio")
    if frontier.get("unpriced_roster_players"):
        parts.append(
            f"{len(frontier['unpriced_roster_players'])} rostered player(s) "
            f"carry no Ceiling, so the totals are SHORT")
    return " | ".join(parts) + " [review proxies, not probabilities]"


def showdown_degraded_entries(assignments, bank) -> dict:
    """R247(a) on the Showdown brief: the ENTERED rows, marshalled once.

    A separate function for the same reason ``format_frontier_line`` is one --
    code built inline in ``run_showdown`` is code nothing can test without a
    solver, and the marshalling is where the mistakes live: the zip pairing
    (a flagged entry_id has to name a row in the DELIVERED file), and the cap.

    The Showdown contract's cap comes off the bank's own lineups
    (``showdown._assemble_lineup`` writes ``salary_cap`` into each), so this
    path never assumes Classic's. When the bank does not state one unanimously
    no cap is passed at all and ``field_miner.SALARY_CAP`` applies, because a
    literal here would be one more spelling of a number this repo already
    spells ten ways.
    """
    from mlb_engine.field.field_miner import degraded_entry_flags
    lineups = list(bank or [])
    rows = list(assignments or [])
    caps = {int(lu.get("salary_cap") or 0) for lu in lineups if lu.get("salary_cap")}
    kwargs = {"salary_cap": caps.pop()} if len(caps) == 1 else {}
    return degraded_entry_flags(
        [{"entry_id": a.get("entry_id"), "proxy": lu.get("proj_points"),
          "salary_used": lu.get("salary")}
         for a, lu in zip(rows, lineups)],
        **kwargs,
    )


def format_degraded_line(degraded: dict | None) -> str:
    """One review line for R247(a)'s block, printed before the operator approves.

    A separate function for the same reason `format_frontier_line` is one: a
    print built inline is a print nothing can test. The wording says REPORT out
    loud, because the one thing this must never be read as is a gate -- every
    existing counter reads clean on exactly the failure it names, so an operator
    who reads it as a blocker will conclude the build is broken when it is not.
    """
    if not degraded or not degraded.get("available"):
        reason = (degraded or {}).get("unavailable_reason") or "not computed"
        return f"UNAVAILABLE ({reason})"
    n = degraded.get("entries")
    flagged = degraded.get("flagged") or []
    bars = degraded.get("bars") or {}
    if not flagged:
        return (f"0/{n} entries flagged (bars: salary-left > "
                f"${bars.get('salary_left')}, proxy > "
                f"{bars.get('proxy_margin_pct')}% below the median "
                f"{degraded.get('median_proxy')}) [report, never a gate]")
    worst = flagged[0]
    detail = ", ".join(
        f"{d['entry_id']} (${d['salary_left']} left"
        + (f", {d['proxy_pct_below_median']}% below median" if "proxy_margin" in d["triggers"] else "")
        + ")"
        for d in flagged[:4])
    more = f" +{len(flagged) - 4} more" if len(flagged) > 4 else ""
    return (f"{len(flagged)}/{n} entries FLAGGED degraded: {detail}{more} "
            f"[worst trigger {worst['triggers']}; bars ${bars.get('salary_left')} "
            f"left / {bars.get('proxy_margin_pct')}% below median "
            f"{degraded.get('median_proxy')}; a REPORT, never a gate]")


def portfolio_exposure(salary_csv: Path, entries_csv: Path) -> dict:
    """Aggregate stack and SP-pair exposure across the delivered portfolio.

    The per-entry view alone does not answer the question worth asking, which is
    how concentrated the portfolio is. Computing it here means nobody has to
    re-join the export against the salary file by hand to write the brief.
    """
    import collections
    # R128. One implementation of the within/across split, imported rather than
    # restated, so the brief and the preflight cannot drift into disagreeing
    # about the same delivered file. Lazily, because build_slate has no other
    # module-level dependency on tools/ and a live build should not pay for one.
    from tools.preflight_upload import partition_duplicate_lineups

    with salary_csv.open(encoding="utf-8-sig", newline="") as fh:
        salary = {r["ID"]: r for r in csv.DictReader(fh)}
    primary, pitchers, pairs, n = collections.Counter(), collections.Counter(), set(), 0
    # R116. Counted off the DELIVERED bytes, on the same sorted-roster signature
    # the allocator keys its reuse rows with
    # (`contest_allocator._candidate_player_signature`), so the brief carries an
    # independent check of the cap rather than the allocator's own word for it.
    # DK writes a roster in slot order and two entries holding the same ten
    # players can differ in that order, which is why the tuple is sorted.
    rosters: collections.Counter = collections.Counter()
    contest_rows: list[tuple[str, tuple[str, ...]]] = []
    with entries_csv.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.reader(fh):
            if len(row) < 14 or not row[0].strip().isdigit():
                continue
            ids = [c.strip() for c in row[4:14]]
            if any(p not in salary for p in ids):
                continue
            n += 1
            # R128. Column 2 is the Contest ID, column 1 the name; the delivered
            # file has carried both since DK wrote it, so the brief can say
            # which duplication it found without a second input.
            contest_rows.append((row[2].strip() or row[1].strip(),
                                 tuple(sorted(ids))))
            teams = collections.Counter(salary[p]["TeamAbbrev"] for p in ids[2:])
            team, size = teams.most_common(1)[0]
            primary[f"{team} ({size})"] += 1
            for p in ids[:2]:
                pitchers[salary[p]["Name"]] += 1
            pairs.add(frozenset(ids[:2]))
            rosters[tuple(sorted(ids))] += 1
    pct = lambda c: {k: f"{v}/{n}" for k, v in c.most_common()}
    split = partition_duplicate_lineups(contest_rows)
    return {
        "lineups": n,
        "primary_stacks": pct(primary),
        "pitcher_exposure": pct(pitchers),
        "distinct_sp_pairs": len(pairs),
        "distinct_lineups": len(rosters),
        "max_lineup_repeat": max(rosters.values()) if rosters else 0,
        # R128. `max_lineup_repeat` above is contest-blind by construction and
        # stays that way: it answers "how many copies of one lineup did we
        # deliver", which is a real question. It is not the duplication
        # question, and reading it as one is how a portfolio with zero waste
        # inside any contest reads as repeating itself.
        "duplicates_within_contest": split["duplicates_within_contest"],
        "duplicates_across_contests": split["duplicates_across_contests"],
        "contests_in_file": split["contests_in_file"],
        "note": "counts across the delivered portfolio; deterministic review "
                "proxies, never ROI, win rate, or probability. "
                "duplicates_within_contest is the finding (one contest holding "
                "a lineup twice pays twice into one prize pool); "
                "duplicates_across_contests is information, since separate "
                "contests have separate prize pools. They count different "
                "objects and do not sum to a total",
    }


VALID_POSTURES = ("cash", "wta_satellite", "single_entry", "small_gpp",
                  "large_gpp", "mme")


class CliValueError(ValueError):
    """A command-line VALUE this build cannot use. R296(a).

    These parsers used to ``raise SystemExit(str)``, which exits 1. Exit 1 is
    off build_slate's documented 0/3/4/5/10 contract, so every consumer reads it
    as a crash: ``tools/autobuild.py`` logged it as "refused with no remedy",
    the SKILL's rerun-on-10 loop cannot classify it, and no brief exists to say
    what was wrong. R168(a) fixed exactly that shape for the one refusal in
    ``main()``; this is the same shape reached through a flag value.

    A ValueError rather than a SystemExit for a second reason: SystemExit is not
    an Exception, so it walked straight through ``run_classic``'s own
    ``try/except Exception`` handlers. A CliValueError raised anywhere late is
    caught there and becomes a brief. It should never be raised late, because
    ``validate_cli_values`` runs in ``main()`` before anything is staged -- but
    the fallback direction matters and this one fails toward a record.
    """


def parse_postures_arg(value: str | None) -> dict[str, str]:
    """'<id_or_name>=<posture>,...' -> {key: posture}, validated eagerly.

    A typo here would silently fall through name inference to large_gpp, which is
    the exact failure the flag exists to close, so an unknown posture is an error
    at parse time rather than a value nothing reads.
    """
    if not value:
        return {}
    out: dict[str, str] = {}
    for item in str(value).split(","):
        item = item.strip()
        if not item:
            continue
        if "=" not in item:
            raise CliValueError(f"--postures entry {item!r} is not <contest>=<posture>")
        key, posture = (x.strip() for x in item.split("=", 1))
        if posture not in VALID_POSTURES:
            raise CliValueError(
                f"--postures: unknown posture {posture!r}; valid: "
                + ", ".join(VALID_POSTURES))
        out[key] = posture
    return out


import re as _re

# SOFT pool blockers: they degrade the build and print, they do not stop it.
# Everything else from build_slate_pool is HARD. Keeping the soft list explicit
# and short means a new blocker is hard by default, which is the safe direction.
SOFT_POOL_BLOCKER_RE = _re.compile(
    r"(stale|days old|refresh|reference file|platoon file is"
    # R104. A PLR arm is a decision the operator owes, not a statement that the
    # pool is of the wrong slate: the arm is named, the remedy is named
    # (--declare-pitcher), and leaving him out is a legitimate answer. Hard would
    # stop every bullpen-game slate on a question with a defensible default.
    r"|projected long reliever)", _re.IGNORECASE)


def parse_declared_pitchers(values) -> dict:
    """``--declare-pitcher 43755567=viable_bulk_or_alt_sp`` -> {id: role}.

    R104. The engine has accepted ``declared_pitchers`` since the pool contract
    was written (``live_data_adapters.build_slate_pool``, honored at the
    declaration loop); only the CLI surface was missing, so the operator's answer
    to a PLR blocker had no way to reach the build. Bare ``<id>`` means
    ``declared_probable_sp``, the same default the engine applies.

    Deliberately not validated against a role vocabulary here: the engine owns
    the role set, and a typo'd role surfaces as a pitcher-audit gate failure
    naming the arm, which is louder than an argparse error at T-10.
    """
    out: dict = {}
    for raw in (values or []):
        text = str(raw).strip()
        if not text:
            continue
        pid, _, role = text.partition("=")
        pid = pid.strip()
        if not pid:
            raise CliValueError(f"--declare-pitcher {raw!r}: no player ID before '='")
        out[pid] = role.strip() or "declared_probable_sp"
    return out

ASSUMABLE_GATES = ("salary_gate_passed", "entry_grid_gate_passed",
                   "lineup_gate_passed", "pitcher_audit_gate_passed",
                   "weather_gate_passed", "odds_gate_passed")

# R133(4). Pool blockers `--ignore-pool-blockers` refuses to override, matched
# on the phrase both producers in `live_data_adapters` share. Kept here rather
# than in the engine because it is the FLAG's policy, not the pool's: the pool
# reports the fact and this script decides what an operator may wave through.
UNOVERRIDABLE_POOL_BLOCKER_RE = _re.compile(r"crosswalk failure", _re.I)

# The two shapes validate_upload_ready_gates emits, and nothing else.
_GATE_ERROR_RE = _re.compile(r"^(?:Missing|Failed) pre-export gate: (\w+)")


def gate_failure_detail(result: dict, pool_report: dict | None) -> dict:
    """R27 (open half): everything a failed pre-export gate can say for
    itself, collected from evidence the engine already recorded.

    The 2026-07-28 session watched lineup_gate_passed fail with no cause on
    screen and rebuilt the pool by hand to find the blocker text. The cause
    was on the result the whole time: every derived gate carries one evidence
    line (workflow_gate_evidence), and the pool report carries the blockers
    the lineup gate read. Returns {"failed_gates", "gate_evidence",
    "pool_blockers"}, each key present only when it has content, ready to
    merge into the not_certified payload.
    """
    evidence = (result or {}).get("workflow_gate_evidence") or {}
    names: list[str] = []
    for err in (result or {}).get("errors") or []:
        match = _GATE_ERROR_RE.match(str(err))
        if match and match.group(1) not in names:
            names.append(match.group(1))
    detail: dict = {}
    if names:
        detail["failed_gates"] = names
        detail["gate_evidence"] = {
            n: str(evidence.get(n) or "no evidence recorded") for n in names}
    blockers = [str(b) for b in (pool_report or {}).get("blockers") or []]
    if blockers:
        detail["pool_blockers"] = blockers
    return detail


def parse_assume_gates_arg(value: str | None) -> list[str]:
    if not value:
        return []
    out = []
    for name in str(value).split(","):
        name = name.strip()
        if not name:
            continue
        if name not in ASSUMABLE_GATES:
            raise CliValueError(f"--assume-gates: unknown gate {name!r}; valid: "
                                + ", ".join(ASSUMABLE_GATES))
        out.append(name)
    return out


# R296(a)+(b). The flags whose VALUES this build validates, and where they were
# validated before: nowhere main() could see. `--postures` was first parsed at
# the shape-scoring call AFTER the pool build, the enrichment and the bank spend
# (and again after it, unguarded); `--assume-gates` at the pool-override notice;
# `--declare-pitcher` inside the `build_slate_pool` call itself. All three
# aborted with `raise SystemExit(str)` = exit 1, past every handler, with no
# brief. On 1940_9g's shape that is a lost window: minutes of bank spent, then a
# crash, then a supervisor that cannot classify exit 1.
#
# `--controls-override` and `--leverage` are `type=json.loads`, which accepts any
# JSON -- `[1,2]`, `5`, `"x"`, `null` all parse. A non-object then reached
# `override.get(key)` (AttributeError, exit 1, pre-staging) or `dict(5)`
# (TypeError, exit 1, AFTER the pool build). `autobuild.lift_controls_override`
# already refuses non-objects; this is that rule reaching the tool it guards.
_JSON_OBJECT_FLAGS = (("controls_override", "--controls-override"),
                      ("leverage", "--leverage"))


def validate_cli_values(args) -> dict | None:
    """Every flag VALUE checked in one place, before anything is staged.

    Returns the refusal payload, or None when the values are usable. The caller
    prints it and exits 4: bad input, nothing built, nothing staged, no run
    directory. Exit 4 is what `--lineups`-unreadable and the units check already
    return for the same class of mistake, and it is on the documented contract,
    so `tools/autobuild.py` stops with "inputs missing; nothing to decide"
    instead of logging a crash as a refusal.
    """
    for attr, flag in _JSON_OBJECT_FLAGS:
        value = getattr(args, attr, None)
        if value is None or isinstance(value, dict):
            continue
        return {
            "status": "cli_value_invalid",
            "date": getattr(args, "date", None),
            "flag": flag,
            "error": (f"{flag} takes a JSON OBJECT; got "
                      f"{type(value).__name__} ({json.dumps(value)[:120]})"),
            "note": ("the value parsed as JSON but is not a dict of "
                     "name -> value, and every reader of this flag subscripts "
                     "it. Nothing was staged and no run directory was created."),
        }
    for parse, attr, flag in (
            (parse_postures_arg, "postures", "--postures"),
            (parse_assume_gates_arg, "assume_gates", "--assume-gates"),
            (parse_declared_pitchers, "declare_pitcher", "--declare-pitcher")):
        try:
            parse(getattr(args, attr, None))
        except CliValueError as exc:
            return {
                "status": "cli_value_invalid",
                "date": getattr(args, "date", None),
                "flag": flag,
                "error": str(exc),
                "note": ("checked in main() before staging, before the pool "
                         "build and before the bank. Nothing was staged and no "
                         "run directory was created."),
            }
    return None


BARE_STAGED_NAMES = {"DKSalaries.csv", "DKEntries.csv"}


def _stage(source: Path, dest: Path) -> Path:
    """Copy an uploaded file into the slate directory, writably.

    Uploads arrive on a read-only mount, so a plain copy inherits mode 500 and the
    next slate cannot overwrite it. Replace rather than write in place.

    The bare ``DKSalaries.csv`` / ``DKEntries.csv`` names are what
    ``tools/late_swap.py`` and ``tools/solver_probe.py`` read by default, and
    ``data/slates/<date>/`` is keyed on date alone. Staging Showdown data at
    those names points the deadline-critical tools at a six-slot file they will
    read as ten-slot. It happened on 2026-07-25: the staged Classic pair went
    md5-identical to its ``_showdown`` twins. Showdown always stages under a
    suffixed name.
    """
    if source.resolve() == dest.resolve():
        return dest
    if dest.name in BARE_STAGED_NAMES:
        with source.open(encoding="utf-8-sig", newline="") as fh:
            reader = csv.reader(fh)
            header = next(reader, [])
            first = next(reader, [])
        looks_showdown = (
            "CPT" in [str(c).strip().upper() for c in header]
            or any(str(c).strip().upper() in ("CPT", "UTIL") for c in first[:6])
        )
        if looks_showdown:
            raise ValueError(
                f"refusing to stage Showdown data at the bare Classic name "
                f"{dest.name}: {source} carries CPT/UTIL geometry. "
                f"tools/late_swap.py and tools/solver_probe.py default to this "
                f"name and would read it at Classic width. Stage Showdown under "
                f"a suffixed name."
            )
    if dest.exists():
        try:
            dest.unlink()
        except OSError:
            dest.chmod(0o644)
    dest.write_bytes(source.read_bytes())
    try:
        dest.chmod(0o644)
    except OSError:
        pass
    return dest


def count_reserved(entries_csv: Path) -> int:
    n = 0
    with entries_csv.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.reader(fh):
            if row and row[0].strip().isdigit():
                n += 1
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--salary", required=True)
    ap.add_argument("--entries", dest="entries_csv", required=True)
    ap.add_argument("--lineups", help="mlb-lineups feed JSON; fetched if omitted")
    ap.add_argument("--odds",
                    help="game-odds JSON (raw the-odds-api events, an "
                         "mlb-game-odds payload, or a slate_bundle). Feeds the "
                         "F1 game-environment prior. When omitted, totals are "
                         "fetched if THE_ODDS_API_KEY is set, else F1 stays 1.0.")
    ap.add_argument("--date", help="slate date; derived from the salary file if omitted")
    ap.add_argument("--no-rotowire", dest="rotowire", action="store_false",
                    help="skip the RotoWire projected-lineup fallback for TBD teams "
                         "and use only the FanGraphs reference")
    ap.set_defaults(rotowire=True)
    ap.add_argument("--entries-count", dest="entries", type=int,
                    help="override the reserved-entry count")
    ap.add_argument("--max-seconds", type=float, default=35.0,
                    help="wall clock this invocation may use before saving and "
                         "asking to be rerun")
    ap.add_argument("--brief", help="write the brief JSON here")
    ap.add_argument("--declare-pitcher", dest="declare_pitcher", action="append",
                    default=[], metavar="ID[=ROLE]",
                    help="R104. Repeatable. State that a DK player ID is a "
                         "startable arm, e.g. --declare-pitcher 43755567 or "
                         "--declare-pitcher 43755567=viable_bulk_or_alt_sp. This "
                         "is the operator's answer to a PLR (projected long "
                         "reliever) soft blocker, and the documented way past the "
                         "PO (probable opener) bar. Bare ID means "
                         "declared_probable_sp. Recorded verbatim in the brief.")
    ap.add_argument("--ignore-pool-blockers", action="store_true",
                    help="build despite a HARD pool blocker. The override is "
                         "printed and recorded in the brief. Reach for this only "
                         "when you have read the blocker and know it is wrong. "
                         "This is HALF the move: the pre-export gate re-reads "
                         "the pool report, so pair it with --assume-gates "
                         "lineup_gate_passed. A crosswalk failure is refused "
                         "outright rather than overridden.")
    ap.add_argument("--assume-gates", dest="assume_gates", default=None,
                    help="comma-separated pre-export gates to certify without "
                         "checking, for the T-5 fast path. Each one is recorded "
                         "verbatim in diagnostics.json, so the artifact states "
                         "which checks were skipped instead of implying they ran. "
                         "A gate nothing checked lands in assumed_gates; "
                         "lineup_gate_passed may also override a gate the "
                         "evidence decided FALSE and lands in overridden_gates "
                         "with the evidence it contradicts. Any other gate "
                         "against a False derivation is refused and reported in "
                         "gates_assumption_refused rather than silently doing "
                         "nothing. Valid: " + ", ".join(ASSUMABLE_GATES))
    ap.add_argument("--postures", default=None,
                    help="comma-separated <contest_id_or_name>=<posture> pairs, e.g. "
                         "'192707612=wta_satellite,192707473=cash'. Postures: cash, "
                         "wta_satellite, single_entry, small_gpp, large_gpp, mme. "
                         "These override name inference entirely. The ledger Quick "
                         "Card's standing instruction is to never trust the "
                         "inference; this flag is how to obey it. A contest whose "
                         "name matches no archetype blocks the build until it is "
                         "named here or added to the archetypes CSV.")
    ap.add_argument("--controls-override", dest="controls_override", type=json.loads,
                    default=None,
                    help="JSON dict of portfolio_controls_override, e.g. "
                         "'{\"max_shared_players\": 8}'. Use when a build fails "
                         "with a feasibility hint naming a control floor; this "
                         "raises diversity caps, it never changes the player pool. "
                         "Showdown reads all three of its controls from this same "
                         "dict: \"max_shared_players\" (default 4 of 6), "
                         "\"max_cpt_exposure_pct\" (default 0.25) for how much of "
                         "the set one captain may fill, and "
                         "\"max_player_exposure_pct\" (default 0.50) for how much "
                         "one player may fill in ANY role. Each cap count is a "
                         "floor() of pct x entries, so realized exposure never "
                         "exceeds the pct. Pass null to disable a cap.")
    ap.add_argument("--bundle",
                    help="slate_bundle.json from tools/fetch_slate_bundle.py. "
                         "Supplies the per-venue forecast for F5. Park factors "
                         "apply without it; wind does not.")
    ap.add_argument("--reference-dir", default=None,
                    help="directory holding the projection enrichment inputs "
                         "(default data/reference/)")
    ap.add_argument("--reference-max-age-days", type=float, default=14.0,
                    help="warn in the brief when an enrichment input is older "
                         "than this (default 14). Stale inputs are still used; "
                         "they are reported, not blocked.")
    ap.add_argument("--no-enrichment", dest="enrichment", action="store_false",
                    help="build on AvgPointsPerGame x batting-order factor only, "
                         "skipping the xwOBA correction, xISO and K-rate ceilings, "
                         "and the F4 matchup factor. For reproducing an old build; "
                         "not for live slates.")
    ap.set_defaults(enrichment=True)
    ap.add_argument("--past-slate-replay", action="store_true",
                    help="build a slate whose first lock has already passed "
                         "(replays and evals only; a live build never needs it)")
    # R246. R154 built two MILP leverage constraints and shipped them OFF
    # pending calibration; what was not intended is that no path could turn them
    # ON. Opt-in, defaults untouched, and the numbers are the operator's.
    ap.add_argument("--leverage", default=None, type=json.loads,
                    help="Classic only: JSON forwarding R154's leverage "
                         "constraints to the bank solve, e.g. "
                         "'{\"max_cumulative_ownership_pct\": 90, "
                         "\"min_low_owned_hitters\": 2, "
                         "\"low_owned_threshold_pct\": 10}'. Each is "
                         "independently settable because the floor has a real "
                         "infeasibility edge. Reads this slate's "
                         "outputs/<date>/ownership_pred_<tag>.json and REFUSES "
                         "with the path named when it is absent; add "
                         "\"archetype\" when that file carries more than one. "
                         "The prediction is an UNGRADED prior whose ordering is "
                         "what has been measured, never an ROI, win-rate or "
                         "probability claim.")
    # R288. The anti-correlation convention, settable. Default None means the
    # engine default (0), which is exactly what the unconditional wall enforced.
    ap.add_argument("--max-opposing-hitters-per-sp", dest="max_opposing_hitters_per_sp",
                    type=int, default=None,
                    help="Classic only: how many hitters facing ONE rostered SP "
                         "a lineup may carry. Default 0, which is the behaviour "
                         "the engine had as an unconditional constraint. PER SP, "
                         "so a Classic lineup holding two arms has a per-lineup "
                         "worst case of twice this. DraftKings does NOT prohibit "
                         "the construction -- 18.7%% of resolvable Classic entries "
                         "in this repo's archive carry one and contest 192464310's "
                         "top three all did -- so this is a CONVENTION about "
                         "negative correlation that the session may override on "
                         "judgment, recording the value and the reason in the "
                         "brief (CLAUDE.md Autonomy).")
    ap.add_argument("--ownership-pred", dest="ownership_pred", default=None,
                    help="name the ownership prediction file --leverage should "
                         "read, when the default resolution is ambiguous.")
    # R249. Showdown's only projection input. Classic reaches the whole F1-F5
    # enrichment stack through `_assemble_projection_frame`; Showdown reaches
    # AvgPointsPerGame and a salary regression, on roughly a third of entered
    # volume, and the operator's only previous lever was editing the APPG column
    # of the salary file -- which worked and which nothing recorded.
    ap.add_argument("--projections", default=None,
                    help="Showdown only: CSV of Player_ID,Base (the columns "
                         "`ownership_pred.py --base` reads) supplying the prior "
                         "the solver ranks on. A covered player's supplied "
                         "number is used AS the prior: the salary regression, "
                         "the batting-order PA factor and the platoon factor "
                         "are not applied to it. The brief records the path, "
                         "the sha256, how many players differ from APPG and the "
                         "min/median/max ratio. A labeled operator input, never "
                         "a projection this engine produced or graded.")
    ap.add_argument("--feed-max-age-minutes", type=float, default=90.0,
                    help="refetch a disk-cached lineups feed older than this "
                         "(default 90). Lineups confirm through the afternoon, so "
                         "a stale feed downgrades confirmed teams to projected "
                         "orders while better information exists.")
    args = ap.parse_args()

    # R296(a)+(b). FIRST, before the clock, before the input existence test and
    # before any import that can raise. Every one of these values used to be
    # read for the first time somewhere inside run_classic, so a typo in
    # `--postures` was worth minutes of bank and then exit 1 with no brief.
    bad_value = validate_cli_values(args)
    if bad_value is not None:
        print(json.dumps(bad_value, indent=1))
        return 4

    started = time.monotonic()
    deadline = started + args.max_seconds

    salary, entries = Path(args.salary), Path(args.entries_csv)
    if not salary.exists() or not entries.exists():
        print(json.dumps({"status": "missing_inputs", "date": args.date}, indent=1))
        return 4

    # R28(4): the front-door dependency check, before staging and before any
    # engine import that could raise on the way past. A missing solver used to
    # surface as an unhandled RuntimeError at the first solve, after staging and
    # after the whole pool build, which is the most expensive place to learn a
    # one-line fact. This is the same check tools/audit.py runs, called here so
    # the build refuses in the same second it starts.
    from tools.audit import check_dependencies
    deps = check_dependencies(REPO)
    if not deps["passed"]:
        print(json.dumps({
            "status": "missing_dependencies",
            "date": args.date,
            "missing": deps["missing"],
            "scipy_milp_available": deps["scipy_milp_available"],
            "remedy": deps["remedy"],
            "note": ("no solver, no build. Nothing was staged and no run "
                     "directory was created."),
        }, indent=1))
        return 4

    # R167. The operator-facing half of the units rule, checked in the same
    # second the build starts. `--controls-override max_pitcher_exposure_pct=45`
    # (45 typed for 0.45) used to clear the checkpoint -- which printed
    # `45 -> cap 10` as though it had checked something -- and then raise
    # uncaught after the bank had spent minutes, leaving the run at status
    # `building` with no diagnostics, at T-time. The engine boundary
    # (`_merged_controls_for_build`) now rejects it too, and this check exists
    # in addition because it is the only one that costs nothing and because
    # Showdown never passes through that boundary at all.
    #
    # R215(c). This used to float-TEST a copy and forward the raw value, which
    # is a checkpoint that lets the bad value past after saying it looked.
    # Classic re-coerced downstream at `_cap_count`; Showdown did not, so
    # `--controls-override '{"max_player_exposure_pct": "0.5"}'` raised
    # TypeError at `"0.5" >= 0.33` in brief assembly and ValueError at
    # `f"{pct:.0%}"` -- both after the full solve. The coerced float is now
    # written back, so what passed the gate is what travels.
    bad_units = []
    override = args.controls_override or {}
    for key in FRACTION_CONTROL_KEYS:
        value = override.get(key)
        if value is None:
            continue
        coerced, problem = fraction_or_problem(value)
        if problem:
            bad_units.append({"control": key, "value": value,
                              "problem": problem})
        else:
            override[key] = coerced
    # R215(a). The sixth control is dict-valued: the units question is about
    # each per-game VALUE, and the key was in no gate at all.
    for key in FRACTION_CONTROL_DICT_KEYS:
        by_game = override.get(key)
        if by_game is None:
            continue
        if not isinstance(by_game, dict):
            bad_units.append({"control": key, "value": by_game,
                              "problem": "not an object of game id -> fraction"})
            continue
        for gid, value in list(by_game.items()):
            coerced, problem = fraction_or_problem(value)
            if problem:
                bad_units.append({"control": f"{key}[{gid}]", "value": value,
                                  "problem": problem})
            else:
                by_game[gid] = coerced
    if bad_units:
        print(json.dumps({
            "status": "controls_override_bad_units",
            "date": args.date,
            "controls": bad_units,
            "note": ("these controls are FRACTIONS of the entered set, not "
                     "percentages: 0.45 for 45%. A value above 1.0 caps nobody, "
                     "and it used to reach the solve and crash there after the "
                     "bank had spent. A bool and a NaN did the same thing more "
                     "quietly: both cleared the `> 1.0` test and disabled the "
                     "cap with nothing named. 0 or below is legal and means "
                     "'not set' for a ceiling, 'no quota' for a floor. Nothing "
                     "was staged and no run directory was created."),
        }, indent=1))
        return 4

    args.date = args.date or slate_date_from_salary(salary)
    contest = detect_contest_type(salary, entries)
    signature = slate_signature(salary)

    # R249. `--projections` is a Showdown seam. On Classic the enrichment stack
    # owns the projection and a supplied Base would have to be reconciled with
    # it, which is R41/R252's question and not this flag's. Refuse rather than
    # accept-and-ignore: a flag that silently does nothing is R242's complaint,
    # and it is worse here because the operator supplied a file and would read
    # the delivered lineups as having consumed it. Before staging, deliberately.
    # R246. `--leverage` is a Classic seam. Showdown does not enter `run_slate`
    # and its bank is `build_showdown_bank`, which builds no MILP row for
    # either constraint; accepting the flag there would be the same silent
    # no-op R242 is filed on. Before staging, and symmetric with --projections.
    # R288, same shape and the same reason: the control is wired into the Classic
    # bank solve, Showdown's bank is build_showdown_bank and builds no such row,
    # so accepting the flag there would be R242's silent no-op with an operator
    # reading the delivered lineups as having honoured it.
    if (getattr(args, "max_opposing_hitters_per_sp", None) is not None
            and contest == "showdown"):
        print(json.dumps({
            "status": "anti_correlation_control_not_supported_on_showdown",
            "date": args.date,
            "max_opposing_hitters_per_sp": args.max_opposing_hitters_per_sp,
            "note": ("--max-opposing-hitters-per-sp forwards a constraint to the "
                     "Classic bank solve. Showdown does not pass through "
                     "run_slate and build_showdown_bank emits no opposing-hitter "
                     "row, so nothing would change and the brief would say "
                     "otherwise. Nothing was staged."),
        }, indent=1))
        return 4
    if getattr(args, "leverage", None) and contest == "showdown":
        print(json.dumps({
            "status": "leverage_not_supported_on_showdown",
            "date": args.date,
            "leverage": args.leverage,
            "note": ("--leverage forwards R154's constraints to the Classic "
                     "bank solve. Showdown does not pass through run_slate and "
                     "its solver builds no ownership row, so nothing would "
                     "apply it. Nothing was staged."),
        }, indent=1))
        return 4

    if getattr(args, "projections", None) and contest != "showdown":
        print(json.dumps({
            "status": "projections_not_supported_on_classic",
            "date": args.date,
            "projections": args.projections,
            "contest": contest,
            "note": ("--projections supplies the Showdown Base prior. Classic "
                     "builds its projection through the F1-F5 enrichment stack, "
                     "so a supplied Base has no defined place in it. Nothing "
                     "was staged and no run directory was created."),
        }, indent=1))
        return 4

    # R28(3): a slate whose first lock has already passed is a replay or an eval,
    # never a live build, and the build path used to say nothing at all about the
    # clock. Saying nothing is the failure: a past-lock build that certifies looks
    # exactly like a live one on disk. The flag is the whole remedy, because the
    # only legitimate callers know which they are.
    if signature.get("first_lock") and not args.past_slate_replay:
        first_lock = dt.datetime.fromisoformat(signature["first_lock"])
        now = dt.datetime.now(dt.timezone.utc)
        if first_lock <= now:
            passed_h = (now - first_lock).total_seconds() / 3600.0
            print(json.dumps({
                "status": "past_slate_locks_passed",
                "date": args.date,
                "first_lock": signature["first_lock"],
                "hours_past_first_lock": round(passed_h, 1),
                "note": ("this slate's first lock passed "
                         f"{round(passed_h, 1)}h ago, so no lineup built here can "
                         "be entered. Pass --past-slate-replay to build it anyway "
                         "(replays and evals); nothing was staged."),
            }, indent=1))
            return 4

    slate_dir = REPO / "data" / "slates" / args.date
    slate_dir.mkdir(parents=True, exist_ok=True)
    # Classic and Showdown builds for the same date used to stage to the same
    # DKSalaries.csv/DKEntries.csv filenames, so a Showdown build for a date
    # already carrying a Classic build (or vice versa) silently overwrote the
    # other's staged inputs mid-run (hit 2026-07-23: a Showdown SD@ATL stage
    # clobbered an in-flight Classic build's salary/entries CSVs). Classic
    # keeps the bare filenames CLAUDE.md documents and that late_swap.py /
    # solver_probe.py already default to; Showdown gets distinct filenames so
    # the two contest types can never collide on the same date again.
    suffix = "_showdown" if contest == "showdown" else ""
    # A REPLAY IS NOT A DELIVERY (2026-08-16). --past-slate-replay exists for
    # replays and evals, and it used to write the live delivered filename, so
    # re-running a locked slate to exercise the build overwrote the certified
    # export a human had already been handed. The run/ copy survives, but the
    # path every brief, manifest and handoff cites does not, and the same
    # filename-keyed clobber has cost this project a delivery once before from a
    # parallel session. A replay now carries its own name and can never land on
    # the delivery path.
    if getattr(args, "past_slate_replay", False):
        suffix += "_replay"
    # The contest-type suffix separates Classic from Showdown but not one Classic
    # draftgroup from another on the same date. Compare game sets and move the
    # prior draftgroup's staged inputs, brief, and delivered file aside rather
    # than overwriting them.
    prior_salary = slate_dir / f"DKSalaries{suffix}.csv"
    out_dir = REPO / "outputs" / args.date
    if prior_salary.exists():
        prior_sig = slate_signature(prior_salary)
        if prior_sig["games"] and prior_sig["games"] != signature["games"]:
            print(f"different draftgroup for {args.date}: staged "
                  f"{prior_sig['tag']}, incoming {signature['tag']}", file=sys.stderr)
            preserve_prior_slate(
                [prior_salary,
                 slate_dir / f"DKEntries{suffix}.csv",
                 out_dir / f"DKEntries{suffix}.csv",
                 out_dir / f"build_brief{suffix}.json"],
                prior_sig["tag"],
                date=args.date,
            )
    staged_salary = _stage(salary, slate_dir / f"DKSalaries{suffix}.csv")
    staged_entries = _stage(entries, slate_dir / f"DKEntries{suffix}.csv")

    feed_note = None
    if contest == "showdown":
        code, brief = run_showdown(args, slate_dir, staged_salary, staged_entries)
    else:
        feed_path = Path(args.lineups) if args.lineups else slate_dir / "lineups_feed.json"
        # R143, Ben 2026-08-17: the salary file is the first source for batting
        # order, so a slate DK has fully posted needs no paste and no fetch.
        # Measured on the network-free path, this is the difference between one
        # 25-second API call inside the build window and none at all.
        from mlb_engine.intake.live_data_adapters import dk_order_coverage
        dk_covered, dk_uncovered = dk_order_coverage(staged_salary)
        dk_covers_slate = bool(dk_covered) and not dk_uncovered and not args.lineups
        # R213. The staged feed is read HERE, before the branch chain, because
        # an unreadable one has to be ABSENT rather than fatal. A torn
        # `lineups_feed.json` is the ordinary consequence of a killed Cowork
        # call, and the unguarded `json.loads` in the branch below raised
        # JSONDecodeError past every handler: no brief, exit 1, and autobuild
        # recording "refused with no remedy this supervisor may take,
        # errors=[]" -- a crash wearing a refusal's label, which is the one
        # thing R168 was filed to stop. The guarded fetch leg at the bottom of
        # this chain already handles exactly this situation, so a cache that
        # cannot be read now falls through to it.
        staged_feed_read: dict | None = None
        staged_feed_unreadable: str | None = None
        if not dk_covers_slate and not args.lineups and feed_path.exists():
            try:
                staged_feed_read = json.loads(feed_path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                staged_feed_unreadable = f"{type(exc).__name__}: {exc}"
                print(f"staged lineups_feed.json is unreadable and is being "
                      f"treated as absent: {staged_feed_unreadable}",
                      file=sys.stderr)
        if dk_covers_slate:
            feed = {"games": []}
            feed_note = {"source": "dk_salary_starting", "fetched": False,
                         "dk_sides": len(dk_covered),
                         "note": "DK posted every side in the salary file; no "
                                 "paste and no API call were needed"}
        elif args.lineups:
            # R213. Unguarded, so a mistyped --lineups path was a raw
            # FileNotFoundError traceback: it escapes before the brief exists,
            # so the run leaves no diagnostics at all and autobuild logs it as
            # a refusal with no remedy. A feed the operator named and this
            # build cannot read is bad input, which is exit 4, and the refusal
            # names the path and the parse error rather than printing a stack.
            try:
                feed = json.loads(Path(args.lineups).read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                print(json.dumps({
                    "status": "supplied_feed_unreadable",
                    "date": args.date,
                    "feed": str(args.lineups),
                    "error": f"{type(exc).__name__}: {exc}",
                    "note": ("--lineups names a file this build cannot read or "
                             "parse. The staged feed was NOT overwritten, no run "
                             "directory was created and nothing was solved; the "
                             "salary and entries files are staged. Fix the path, "
                             "or drop the flag and let the staged feed and DK's "
                             "Starting column supply the orders."),
                }, indent=1))
                return 4
            # A supplied feed overwrote the staged one unconditionally, so a feed
            # for the wrong day or a hand-edited one destroyed the good copy and
            # left nothing to fall back to. The staged feed is the durable input;
            # it is replaced only by a feed that covers this draftgroup.
            staged_feed = slate_dir / "lineups_feed.json"
            feed_teams = {
                str((game.get(side) or {}).get("team_abbrev") or "").upper()
                for game in (feed.get("games") or []) for side in ("away", "home")
            }
            from mlb_engine.intake.slate_intake_manager import (
                parse_dk_salary_csv as _parse_salary,
            )
            slate_teams = {sp.team.upper() for sp in _parse_salary(str(salary))
                           if sp.team}
            covered = len(slate_teams & feed_teams)
            if slate_teams and covered * 2 < len(slate_teams):
                print(json.dumps({
                    "status": "supplied_feed_rejected",
                    "date": args.date,
                    "feed": str(args.lineups),
                    "slate_teams": sorted(slate_teams),
                    "covered": covered,
                    "note": "the supplied feed covers under half this draftgroup's "
                            "teams, so it is a feed for a different slate. The "
                            "staged feed was NOT overwritten. The salary and "
                            "entries files are staged; nothing was solved and no "
                            "run directory was created.",
                }, indent=1))
                # R168(a). `return 3, {}` here, in main(). run_classic and
                # run_showdown legitimately return (code, brief) tuples; main()
                # returns an int, and `raise SystemExit((3, {}))` exits 1 with a
                # stray tuple on stderr. Every documented consumer reads that as
                # a crash: autobuild's 0/3/4/5/10 contract, the SKILL's
                # rerun-on-10 loop, and build_asserted.py, which inherits main().
                # So the one refusal in this file that says "your feed is for
                # another slate" arrived looking like a bug in the build.
                #
                # R296(h). 3, not 4, and its own SIBLING thirty lines above
                # disagreed: `supplied_feed_unreadable` returns 4 for the same
                # class of fact -- the operator named a feed this build cannot
                # use. Exit 3 means BUILT AND REFUSED, which is what autobuild
                # spends attempts on: it grows the bank, reads `feasibility`,
                # applies floors. None of that can fix a feed for another slate,
                # and nothing was solved here to refuse. 4 is bad input, and 4
                # stops the supervisor with "inputs missing; nothing to decide".
                return 4
            staged_feed.write_text(json.dumps(feed), encoding="utf-8")
            feed_note = {"source": str(args.lineups), "age_minutes": feed_age_minutes(feed),
                         "draftgroup_coverage": f"{covered}/{len(slate_teams)}"}
        elif staged_feed_read is not None:
            # Lineups confirm continuously through the afternoon, so a feed left on
            # disk from the morning quietly downgrades confirmed teams to projected
            # orders at exactly the moment better information exists. Age it.
            feed = staged_feed_read
            age = feed_age_minutes(feed)
            if age is None or age > args.feed_max_age_minutes:
                try:
                    feed = fetch_lineups(args.date, feed_path)
                    feed_note = {"source": "refetched", "replaced_age_minutes": age}
                except Exception as exc:  # network failure must not kill the build
                    feed_note = {"source": str(feed_path), "age_minutes": age,
                                 "warning": f"stale feed reused; refetch failed: {exc}"}
                    print(feed_note["warning"], file=sys.stderr)
            else:
                feed_note = {"source": str(feed_path), "age_minutes": age}
        else:
            # R168(b). The refetch leg above has carried a guard for a while and
            # the platoon-side fetch gained one in the 08-18..22 work; this leg,
            # the FIRST fetch of the day, did not. No staged feed + DK's
            # `Starting` column not covering the slate + no route to statsapi
            # was a raw URLError traceback, empty stdout, no brief, exit 1 --
            # and that is the normal pre-lock morning state, not an edge case.
            # An empty feed is a degradation and not a loss: the front door
            # still fills orders from the DK salary file (R143) and from the
            # platoon reference for TBD teams.
            try:
                feed = fetch_lineups(args.date, feed_path)
                feed_note = {"source": "fetched", "age_minutes": 0.0}
            except Exception as exc:  # network failure must not kill the build
                feed = {"games": []}
                feed_note = {"status": "lineups_feed_unavailable",
                             "source": "none",
                             "warning": f"first fetch failed: {exc}",
                             "note": "building on DK's Starting column and the "
                                     "platoon reference; every side DK has not "
                                     "posted is a projection, so read "
                                     "dk_order_coverage in the pool report "
                                     "before approving"}
                print(f"lineups feed unavailable: {exc}", file=sys.stderr)
        # R213. A cache that could not be read is ABSENT, and the brief has to
        # say which absence this was: no staged feed at all and a torn one are
        # different facts, and the second one means a file on disk was
        # discarded rather than used.
        if staged_feed_unreadable and isinstance(feed_note, dict):
            feed_note["staged_feed_unreadable"] = staged_feed_unreadable
            feed_note["staged_feed_path"] = str(feed_path)
        print(f"lineups feed: {json.dumps(feed_note)}", file=sys.stderr)
        code, brief = run_classic(args, slate_dir, staged_salary, staged_entries,
                                  feed, deadline)

    if brief:
        if args.odds and Path(args.odds).exists():
            brief["odds_source"] = args.odds
        brief["elapsed_s"] = round(time.monotonic() - started, 1)
        brief["labels"] = ("deterministic review proxies and labeled priors only; "
                           "never ROI, win rate, cash rate, or probability")
        brief["slate"] = {"tag": signature["tag"], "games": len(signature["games"]),
                          "first_lock_local": signature["first_lock"]}
        if feed_note is not None:
            brief["lineups_feed"] = feed_note
        out = Path(args.brief) if args.brief else (
            REPO / "outputs" / args.date / f"build_brief{suffix}.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(brief, indent=1), encoding="utf-8")
        # A second, slate-tagged copy so evidence survives a same-date rebuild even
        # when the prior-slate preserve step did not run (same draftgroup, rerun).
        if not args.brief:
            out.with_name(f"build_brief{suffix}_{signature['tag']}.json").write_text(
                json.dumps(brief, indent=1), encoding="utf-8")
        print(json.dumps(brief, indent=1))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
