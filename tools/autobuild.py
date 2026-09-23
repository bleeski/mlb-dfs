#!/usr/bin/env python3
"""Supervisor around build_slate.py. Decides the retries a human was doing by hand.

Ben, 2026-08-16: "I want you to have the freedom to use your intelligence to
override, relax and constrain to generate lineups without my intervention."

On 2026-08-16 a live build stopped twice for a human, and neither stop needed
one. The first was a pool blocker (DET listed 8 rosterable hitters because DK
never priced a called-up starter). The second was a feasibility floor the engine
itself labels ARITHMETIC, printing `remedy: raise max_shared_players to >= 7`
alongside the sentence "raising the control to the named floor removes an
impossibility and changes nothing else". The engine had already classified both.
Nothing was missing except something willing to act on the classification.

So this file is policy, not mechanism. build_slate.py stays exactly what it is:
one deterministic build that either certifies or refuses with its reasons. This
supervisor reads those reasons, decides the next move, records why, and stops on
anything it cannot classify.

WHAT IT WILL DO UNATTENDED
  - Re-run to grow the candidate bank on exit 10, until exhausted or out of time.
    Never a strategy change; the bank is search effort.
  - Apply a feasibility remedy the engine named AND classified as structural
    (STRUCTURAL_FEASIBILITY_CHECKS: shared_players_floor, sp_pair_capacity).
    Only to the value the engine named, never beyond it.
  - Override a pool blocker whose shape matches a classified-benign pattern,
    recording the classification and the evidence in the decision log.

WHAT IT WILL NOT DO, EVER
  - Touch an exposure cap. Those have no engine-named floor; raising one
    concentrates the entered set and IS a strategy change. The engine says so.
  - Reduce the legal player pool for any reason.
  - Override a pool blocker it cannot classify, including a name-crosswalk
    failure (a team matching under 5 of 9 salary hitters).
  - Skip the preflight, bypass a blank reserved row, or touch DraftKings.

This list is THIS TOOL'S remit and not the whole autonomy boundary, which is
CLAUDE.md's. R272 (2026-08-31) added a repair clause -- replacing a player who
will not play, and choosing among the mechanically legal replacements, are
autonomous -- and it governs `tools/repair_entry.py` AFTER a delivery, not the
build this supervisor runs. Nothing above is relaxed by it; the pointer is here
because "WILL NOT DO, EVER" reads as a complete boundary to anyone who lands in
this file first, and on 2026-08-29 a session asked Ben a repair question inside
a lock window that it was entitled to answer itself.

Exit: 0 certified, 3 refused with reasons, 4 bad input, 5 out of time.
Every decision lands in outputs/<date>/autobuild_decisions.json, flushed as it
is taken rather than at the end, so a killed call keeps what it had decided.

R296, 2026-09-03. Three things this docstring promised and the file could not
deliver. (d) An exit outside {0, 4, 10} fell through to the code-3 handler,
which asks the BRIEF what the engine refused for -- and a crash writes no brief,
so the log read "refused with no remedy this supervisor may take, errors=[]"
with neither the exit code nor the child's stderr recorded. (e) This was the one
engine-importing module in tools/ that never put REPO on sys.path, so
`_decision_log_date`'s import raised ModuleNotFoundError OUTSIDE `_write`'s try
block and the process died at exit 1 with the log unwritten -- on EVERY terminal
exit, on the invocation SKILL.md prints. (f) The defaults cannot fit one Cowork
call and the log was durable only at terminal exits, so the outer kill that ends
the call took every decision with it; `--call-budget-seconds` and `--resume` are
the answer to the first half and the flush is the answer to the second.
"""
from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO = Path(__file__).resolve().parents[1]

# R296(e). This file imports `mlb_engine` twice inside `_decision_log_date` and
# was the ONLY module in tools/ that imports the engine without putting REPO on
# the path (measured across tools/ and the build script: 20 importers, 19 with
# the insert, this one without). `python tools/autobuild.py` from the repo root
# puts `tools/` on sys.path[0] and NOT the cwd, so both imports raised
# ModuleNotFoundError -- the first swallowed by its own `except Exception`, the
# second unguarded, escaping `_write` before its try block and taking the whole
# process down at exit 1 with the decision log unwritten. Every terminal exit,
# on the invocation SKILL.md prints. Reproduced 2026-09-03.
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
_PYLIBS = REPO / ".pylibs"
if _PYLIBS.is_dir() and str(_PYLIBS) not in sys.path:
    sys.path.insert(0, str(_PYLIBS))

# Safe at module level only because the sys.path insert above already ran; see
# the R296(e) note there for what happens when it has not.
from mlb_engine.repo_env import call_budget_s, call_budget_source  # noqa: E402

BUILD = REPO / "skills" / "generate-lineups" / "scripts" / "build_slate.py"
ASSERTED = REPO / "tools" / "build_asserted.py"

# R296(f). CLAUDE.md pins the safe inner bash budget at 130s on Cowork. The
# defaults here (8 attempts, each up to --per-build-seconds + 90 = 110s, under a
# 12-minute wall) describe a process that CANNOT finish inside one call there,
# and until that change the decision log was flushed only at terminal exits --
# so the outer kill that ends the call took every decision with it. First bad
# moment is the first run that grows the bank once.
#
# R349, 2026-09-16: 130 is now ONE host's number rather than every host's. On a
# Claude Code container declaring a 900s ceiling the same eight attempts fit one
# call comfortably, and planning them against 130 is what turns a supervisor with
# room to work into one that stops cleanly at exit 5 for no reason. The
# resolution, its precedence and the conservative 130 floor all live in
# mlb_engine.repo_env; this stays the only place autobuild names it.
DEFAULT_CALL_BUDGET_S = call_budget_s()
DEFAULT_CALL_BUDGET_SOURCE = call_budget_source()

# R349 moved the CALL budget off 130; the per-attempt SEARCH budget stayed at a
# literal 20 and kept the Cowork ceiling alive one level down. 20 was chosen so
# that "8 x 110s under a 12-minute wall" would fit the ~130s Cowork bash
# ceiling (see --call-budget-seconds below). On a host resolving 630s that hands
# each attempt 20s of --max-seconds, from which build_slate derives its bank
# budget as `deadline - now - 6.0` -- about 14s to build a candidate bank, on a
# host that can afford 600. The bank TARGET is unchanged by this
# (resolve_candidate_bank_size is entry-derived, 2n capped at 150); what a
# bigger budget buys is REACHING that target in one call instead of slicing it
# across exit-10 resumes, and each extra slice costs a call on a live slate.
#
# The divisor keeps the old behaviour where the old constraint still applies:
# 130/6 = 21 on Cowork and on an unrecognised host, 105 on a 630s container.
PER_BUILD_FLOOR_S = 20
PER_BUILD_BUDGET_DIVISOR = 6


def default_per_build_seconds(budget: Optional[float] = None) -> int:
    """Seconds of SEARCH one attempt gets, derived from this host's call budget.

    Mirrors ``build_slate.default_max_seconds``: resolved from the host rather
    than pinned, so a container with room to work uses it. ``budget`` is for
    tests, which must not depend on the ambient environment.
    """
    resolved = DEFAULT_CALL_BUDGET_S if budget is None else float(budget)
    return max(PER_BUILD_FLOOR_S, int(resolved / PER_BUILD_BUDGET_DIVISOR))

# build_slate.py's documented exit vocabulary. Anything else is a crash wearing
# a refusal's label; see the off-contract branch in main().
BUILD_SLATE_CONTRACT_CODES = (0, 3, 4, 5, 10)

# lineup_gate_passed derives from the pool report, so overriding a benign pool
# blocker is not enough on its own: the gate keeps reading the same finding and
# --assume-gates cannot clear an evidenced False. The two decisions share one
# piece of evidence, so they are taken together or not at all.
GATE_IMPLIED_BY_POOL_OVERRIDE = "lineup_gate_passed"

# Mirrors build_slate.STRUCTURAL_FEASIBILITY_CHECKS. Kept as a literal so this
# file does not import the build script, and asserted against it at runtime.
STRUCTURAL_CHECKS = {"shared_players_floor", "sp_pair_capacity"}

# R169(c). The check name being structural was the only thing validated, and
# then whatever control the remedy SENTENCE named got applied. Those are two
# different facts. A remedy is free text assembled by _feasibility_report, and
# the supervisor's whole warrant is that the engine classified this control
# arithmetic -- a sentence under a structural check's name that says "raise
# max_player_exposure_pct" would have moved an exposure cap, which this file's
# own docstring lists under WHAT IT WILL NOT DO, EVER. So the pairing is
# explicit: a structural check may move the one control it is about.
STRUCTURAL_CONTROL_BY_CHECK = {
    "shared_players_floor": "max_shared_players",
    "sp_pair_capacity": "max_sp_pair_repetition",
}

CONTROL_FLOOR_RE = re.compile(r"raise\s+(\w+)\s+to\s*>=\s*(\d+)")


def assert_classification_in_sync() -> Optional[str]:
    """The whole policy rests on the engine's own arithmetic/strategy split.

    If build_slate's frozenset ever grows an entry this file does not know about,
    the supervisor would either refuse a remedy it should take or, far worse,
    take one it should not. Read it off the source rather than trusting a copy.
    """
    try:
        src = BUILD.read_text(encoding="utf-8")
    except OSError as exc:
        return f"cannot read build_slate.py to verify classification: {exc}"
    m = re.search(r"STRUCTURAL_FEASIBILITY_CHECKS\s*=\s*frozenset\(\{([^}]*)\}\)", src)
    if not m:
        return "STRUCTURAL_FEASIBILITY_CHECKS not found in build_slate.py"
    live = set(re.findall(r'"([^"]+)"', m.group(1)))
    if live != STRUCTURAL_CHECKS:
        return (f"classification drift: build_slate says {sorted(live)}, this "
                f"supervisor says {sorted(STRUCTURAL_CHECKS)}. Refusing to act on "
                f"a stale arithmetic/strategy split.")
    # R169(c): the pairing has to cover the split, or a structural check would
    # arrive with no control this file is willing to name for it.
    unpaired = STRUCTURAL_CHECKS - set(STRUCTURAL_CONTROL_BY_CHECK)
    if unpaired:
        return (f"structural checks {sorted(unpaired)} have no control paired in "
                f"STRUCTURAL_CONTROL_BY_CHECK; refusing to apply a remedy whose "
                f"target this supervisor cannot vouch for.")
    return None


def classify_pool_blocker(text: str) -> Optional[str]:
    """Return a benign classification, or None meaning 'a human decides'."""
    low = text.lower()
    m = re.search(r"(\d+)/9 hitters", low)
    if m:
        matched = int(m.group(1))
        if matched >= 5:
            return ("unpriced_or_absent_starter: DK owns eligibility, so a posted "
                    "starter DK never priced is unrosterable anyway; the remaining "
                    f"{matched} are confirmed and stackable")
        return None  # under 5 of 9 is a crosswalk failure, per SKILL.md
    if "no rosterable starter" in low:
        return ("no_rosterable_arm: the team's arms are simply not selectable, "
                "which removes options without corrupting the pool")
    return None


def lift_controls_override(tokens: List[str]) -> tuple:
    """Pull an operator's ``--controls-override`` out of the passthrough tokens.

    R214. ``controls`` started empty and gained only the supervisor's own
    structural floors, and the whole dict was appended AFTER the passthrough by
    R169(d)'s deliberate design -- so argparse's last-wins DROPPED the
    operator's dict rather than losing to it key by key. Attempt 1 honoured a
    passthrough R157 rescue (``{"max_player_exposure_pct": 0.55}``); the first
    structural floor erased it for every later attempt, and the decision log
    recorded the floors landing and said nothing about what left.

    R169(d)'s intent -- supervisor-owned flags win -- is right and is kept. It
    is now enforced per KEY, which is what it meant.

    Returns ``(tokens without the flag, the operator's controls, error)``. A
    duplicate or malformed occurrence is an error and never a guess: argparse
    would silently keep the last of two, which is the same silence this item
    exists to remove.
    """
    rest: List[str] = []
    found: List[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok == "--controls-override":
            if i + 1 >= len(tokens):
                return tokens, {}, ("--controls-override in --passthrough has no "
                                    "value after it")
            found.append(tokens[i + 1])
            i += 2
            continue
        if tok.startswith("--controls-override="):
            found.append(tok.split("=", 1)[1])
            i += 1
            continue
        rest.append(tok)
        i += 1
    if not found:
        return rest, {}, None
    if len(found) > 1:
        return rest, {}, (
            f"--passthrough carries {len(found)} --controls-override "
            f"occurrences ({found}); argparse would keep only the last and say "
            f"nothing, so this supervisor refuses rather than choosing for you")
    try:
        parsed = json.loads(found[0])
    except ValueError as exc:
        return rest, {}, (f"--controls-override in --passthrough is not JSON "
                          f"({exc}); the value was {found[0]!r}")
    if not isinstance(parsed, dict):
        return rest, {}, (f"--controls-override in --passthrough parsed to a "
                          f"{type(parsed).__name__}, not an object of "
                          f"control -> value")
    return rest, parsed, None


def lift_never_relax(tokens: List[str]) -> tuple:
    """Pull every ``--never-relax`` out of the passthrough tokens.

    R388(b). For R214's reason: this supervisor applies structural floors of
    its own, so a never-relax it cannot see is one it can break. Every
    occurrence is lifted (the flag repeats, so none is dropped) and the names
    are forwarded once, merged with the supervisor's own flag. Returns
    ``(tokens without the flag, names, error)``.
    """
    rest: List[str] = []
    names: List[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok == "--never-relax":
            if i + 1 >= len(tokens):
                return tokens, [], ("--never-relax in --passthrough has no value "
                                    "after it")
            names.append(tokens[i + 1])
            i += 2
            continue
        if tok.startswith("--never-relax="):
            names.append(tok.split("=", 1)[1])
            i += 1
            continue
        rest.append(tok)
        i += 1
    return rest, names, None


def never_relax_names(chunks: Optional[List[str]]) -> List[str]:
    """The comma-separated, repeatable flag's values as one sorted list."""
    out = set()
    for chunk in chunks or []:
        out.update(p.strip() for p in str(chunk).split(",") if p.strip())
    return sorted(out)


class Decisions:
    def __init__(self) -> None:
        self.log: List[Dict[str, Any]] = []
        # R214. Three fields, because one cannot answer "what did the operator
        # ask for" and "what ran" at the same time -- and the old single dict
        # answered neither honestly, since it recorded the floors that landed
        # and never the override they displaced.
        self.user_controls: Dict[str, Any] = {}
        self.derived_controls: Dict[str, Any] = {}
        # R388(b). The operator's never-relax. A derived floor never lands on
        # one of these, and `effective_controls` enforces it a second time.
        self.never_relax: List[str] = []
        # R296(f). The log was durable only at terminal exits, so an outer kill
        # -- the Cowork call ceiling, a Ctrl-C, the sandbox dying -- lost every
        # decision taken up to that point. R212 and R169(a) each fixed one
        # non-flushing RETURN; the class is not the returns, it is that a
        # decision existed in memory only. Every `add` now flushes through this
        # writer, so the log on disk is never behind the decisions taken.
        self._writer: Optional[Any] = None

    def attach_writer(self, writer) -> None:
        self._writer = writer

    @property
    def effective_controls(self) -> Dict[str, Any]:
        """What actually reaches build_slate. Supervisor-owned keys win, except
        on a never-relax control, where no derived value lands (R388(b))."""
        held = set(self.never_relax)
        return {**self.user_controls,
                **{k: v for k, v in self.derived_controls.items() if k not in held}}

    def controls_block(self) -> Dict[str, Any]:
        return {"user_controls": dict(self.user_controls),
                "derived_controls": dict(self.derived_controls),
                "effective_controls": dict(self.effective_controls),
                "never_relax": list(self.never_relax)}

    def add(self, attempt: int, action: str, why: str, **extra: Any) -> None:
        rec = {"attempt": attempt, "action": action, "why": why,
               "utc": datetime.now(timezone.utc).isoformat(), **extra}
        self.log.append(rec)
        print(f"[autobuild {attempt}] {action}: {why}", file=sys.stderr)
        if self._writer is not None:
            self._writer()


def parse_brief(stdout: str) -> Dict[str, Any]:
    decoder = json.JSONDecoder()
    found = []
    offset = 0
    while offset < len(stdout):
        start = stdout.find("{", offset)
        if start < 0:
            break
        try:
            value, end = decoder.raw_decode(stdout, start)
        except ValueError:
            offset = start + 1
            continue
        if isinstance(value, dict) and isinstance(value.get("status"), str):
            found.append(value)
        offset = end
    return found[-1] if found else {}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--salary", required=True)
    ap.add_argument("--entries", required=True)
    ap.add_argument("--lineups")
    ap.add_argument("--odds")
    ap.add_argument("--postures")
    ap.add_argument("--max-attempts", type=int, default=8)
    ap.add_argument("--per-build-seconds", type=int,
                    default=default_per_build_seconds(),
                    help=f"seconds of SEARCH one attempt gets, forwarded to "
                         f"build_slate as --max-seconds and therefore the input "
                         f"to its bank budget (default "
                         f"{default_per_build_seconds()}, this host's call "
                         f"budget / {PER_BUILD_BUDGET_DIVISOR}, floored at "
                         f"{PER_BUILD_FLOOR_S}). Raising it makes attempts "
                         f"deeper and fewer: the subprocess wall is this + 90s, "
                         f"so fewer fit one call, and --call-budget-seconds "
                         f"stops cleanly at exit 5 before one that cannot "
                         f"finish. --resume then restores the attempt count and "
                         f"the derived floors, so a thin bank costs a call "
                         f"rather than a truncated solve.")
    ap.add_argument("--stop-after-minutes", type=float, default=12.0,
                    help="wall clock for the whole supervised run")
    # R296(f). Two clocks, because they answer different questions.
    # --stop-after-minutes is the SLATE's budget: how long this supervisor may
    # keep working before the window is gone. --call-budget-seconds is THIS
    # PROCESS's budget: how long the caller's shell will let it live. They were
    # the same number implicitly and the implicit answer was wrong, because the
    # defaults (8 x 110s under a 12-minute wall) cannot fit the ~130s Cowork
    # bash ceiling CLAUDE.md pins. The supervisor now stops CLEANLY before an
    # attempt that cannot finish, and --resume picks it back up in the next
    # call instead of restarting from attempt 1 with the derived floors lost.
    ap.add_argument("--call-budget-seconds", type=float,
                    default=DEFAULT_CALL_BUDGET_S,
                    help=f"wall clock for THIS process, distinct from the slate "
                         f"budget (default {DEFAULT_CALL_BUDGET_S:.0f}, resolved "
                         f"for this host -- {DEFAULT_CALL_BUDGET_SOURCE}). When "
                         f"the next attempt cannot finish inside it, the run "
                         f"stops at exit 5 with resumable=true; re-invoke with "
                         f"--resume. 0 disables the check.")
    # R290(c) step 2. The THIRD clock, and it is the AUTHORITY over the other
    # two rather than a third answer to "how long do we have". The distinction
    # is what each one is a fact about:
    #   --deliver-by          an ABSOLUTE time, and an EXTERNAL fact: when the
    #                         slate locks. Nothing here can move it.
    #   --stop-after-minutes  a RELATIVE budget: how long this supervisor may
    #                         keep trying. A choice, and it may not outlive the
    #                         lock, so it is CLAMPED to the deliver-by time and
    #                         the clamp is recorded.
    #   --call-budget-seconds a RELATIVE budget: how long THIS process may live
    #                         before checkpointing for --resume. Untouched: it
    #                         is about the shell, not the slate, and a call
    #                         killed at 130s is killed whatever the lock says.
    # Forwarded to build_slate so the engine-side governor fires on the refusal
    # itself. Passing it here and not forwarding would be a supervisor that
    # knows the deadline while the thing doing the work does not.
    ap.add_argument("--deliver-by", dest="deliver_by", default=None,
                    help="an ISO timestamp or HH:MM ET. Clamps "
                         "--stop-after-minutes so the supervisor cannot outlive "
                         "the lock, and is forwarded to build_slate, whose "
                         "governor turns a badly_shaped refusal into a "
                         "review_grade_deadline_build from T-6.")
    # R388(b). Forwarded to build_slate, which validates the names and holds
    # them at the governor's rung and the pipeline's floors, and read here too,
    # because this supervisor applies structural floors of its own.
    ap.add_argument("--never-relax", dest="never_relax", action="append",
                    default=None, metavar="CONTROL[,CONTROL...]",
                    help="controls that must never be relaxed, comma-separated "
                         "or repeated. Forwarded to build_slate (which refuses "
                         "a name it cannot hold, at exit 4). This supervisor "
                         "never applies a structural floor to one: it stops "
                         "and names the control instead, because raising it "
                         "is Ben's call. A --never-relax inside --passthrough "
                         "is lifted out and merged with this flag.")
    ap.add_argument("--resume", action="store_true",
                    help="continue the run recorded in "
                         "outputs/<date>/autobuild_decisions.json: attempt "
                         "numbering, the derived structural floors, and whether "
                         "pool blockers were already overridden. Without it a "
                         "second call re-derives every floor from attempt 1 and "
                         "spends the window twice.")
    ap.add_argument("--passthrough", default="",
                    help="extra args forwarded to build_slate. Split with shlex, "
                         "so quote a JSON argument the way you would in a shell: "
                         "--passthrough \"--controls-override '{\\\"max_shared_"
                         "players\\\": 9}'\". Supervisor-owned flags are appended "
                         "AFTER these, so a flag named in both is the "
                         "supervisor's, not yours (R169(d)): the decision log "
                         "has to describe the command that ran. A "
                         "--controls-override here is the exception and is "
                         "MERGED rather than displaced (R214): your keys are "
                         "kept, and only the keys this supervisor owns -- the "
                         "structural floors it applies -- overwrite yours. Two "
                         "occurrences, or one that is not a JSON object, is a "
                         "refusal rather than a guess.")
    a = ap.parse_args()

    # R212. `dec` is constructed before the first thing that can return, so
    # every exit from main() has a log to flush. The drift stop below is a
    # decision like any other -- "refusing to act on a stale arithmetic /
    # strategy split" -- and it used to reach stderr and nothing else, against
    # this file's own docstring promise that every decision lands in
    # outputs/<date>/autobuild_decisions.json.
    dec = Decisions()

    # R296(f). The writer hook, wired before the first `add`. `state` carries the
    # latest brief by reference so the flush always writes the current one
    # without threading it through every call site (which is how R212's and
    # R169(a)'s siblings got missed in the first place).
    state: Dict[str, Any] = {"brief": {}}
    dec.attach_writer(lambda: _write(dec, state["brief"], salary=a.salary))

    a._resumed_attempts = 0
    a._resumed_ignore_pool = False
    if a.resume:
        resumed = _resume_state(dec, a.salary)
        if resumed["attempts_done"]:
            a._resumed_attempts = resumed["attempts_done"]
            a._resumed_ignore_pool = resumed["ignore_pool"]
            dec.add(0, "resumed",
                    f"continuing a run recorded in {resumed['path']}: "
                    f"{resumed['attempts_done']} attempts already made, "
                    f"pool blockers {'already' if resumed['ignore_pool'] else 'not'} "
                    f"overridden",
                    **dec.controls_block())

    drift = assert_classification_in_sync()
    if drift:
        print(f"autobuild: {drift}", file=sys.stderr)
        dec.add(0, "stop", drift)
        _write(dec, {}, salary=a.salary)
        return 4

    # R214. Tokenized once, and an operator's --controls-override is lifted out
    # here so exactly ONE reaches build_slate: the merge, not two occurrences
    # for argparse to silently resolve.
    passthrough_tokens = shlex.split(a.passthrough) if a.passthrough else []
    passthrough_tokens, user_controls, controls_error = lift_controls_override(
        passthrough_tokens)
    if controls_error:
        print(f"autobuild: {controls_error}", file=sys.stderr)
        dec.add(0, "stop", controls_error)
        _write(dec, {}, salary=a.salary)
        return 4
    passthrough_tokens, passthrough_never_relax, never_relax_error = (
        lift_never_relax(passthrough_tokens))
    if never_relax_error:
        print(f"autobuild: {never_relax_error}", file=sys.stderr)
        dec.add(0, "stop", never_relax_error)
        _write(dec, {}, salary=a.salary)
        return 4
    dec.never_relax = never_relax_names(
        list(getattr(a, "never_relax", None) or []) + passthrough_never_relax)
    if dec.never_relax:
        dec.add(0, "operator_never_relax",
                "forwarded to build_slate once, merged from this flag and "
                "--passthrough; no structural floor this supervisor applies "
                "lands on one of these controls",
                never_relax=list(dec.never_relax))
    dec.user_controls = dict(user_controls)
    if user_controls:
        dec.add(0, "operator_controls",
                "read from --passthrough and merged UNDER the supervisor's own "
                "keys; R169(d)'s 'supervisor-owned flags win' holds per key "
                "rather than by dropping the operator's whole dict",
                **dec.controls_block())

    started = time.monotonic()
    # R290(c) step 2. One authority, two subordinate budgets. The slate budget
    # is CLAMPED here rather than compared later, so every downstream read of
    # `deadline` already respects the lock and there is no second place where
    # the two could disagree.
    stop_after_minutes = float(a.stop_after_minutes)
    if getattr(a, "deliver_by", None):
        from mlb_engine.pipeline import deadline_governor as _dg
        try:
            deliver_by_utc, tz_source = _dg.parse_deliver_by(a.deliver_by)
        except ValueError as exc:
            dec.add(0, "stop", f"--deliver-by is unparseable: {exc}",
                    remedy="pass an ISO timestamp or HH:MM ET")
            _write(dec, {}, salary=a.salary)
            return 4
        minutes_to_lock = (deliver_by_utc - datetime.now(
            timezone.utc)).total_seconds() / 60.0
        if minutes_to_lock < stop_after_minutes:
            dec.add(0, "clock_clamped",
                    f"--stop-after-minutes {stop_after_minutes:.1f} outlives "
                    f"--deliver-by ({minutes_to_lock:.1f} min to lock), so the "
                    f"slate budget is clamped to the lock. --deliver-by is an "
                    f"external fact and the other two clocks are budgets; a "
                    f"budget that outlives the lock is spending time the slate "
                    f"does not have",
                    deliver_by_utc=deliver_by_utc.isoformat().replace(
                        "+00:00", "Z"),
                    deadline_tz_source=tz_source,
                    stop_after_minutes_requested=stop_after_minutes,
                    stop_after_minutes_applied=round(max(minutes_to_lock, 0.0), 2),
                    call_budget_seconds=a.call_budget_seconds,
                    call_budget_note="unchanged: it is a fact about this shell, "
                                     "not about the slate")
            stop_after_minutes = max(minutes_to_lock, 0.0)
    deadline = started + stop_after_minutes * 60.0
    call_deadline = (started + a.call_budget_seconds
                     if a.call_budget_seconds and a.call_budget_seconds > 0
                     else None)
    ignore_pool = bool(getattr(a, "_resumed_ignore_pool", False))
    attempts_done = int(getattr(a, "_resumed_attempts", 0))
    last_brief: Dict[str, Any] = {}

    for attempt in range(attempts_done + 1, a.max_attempts + 1):
        # R296(f). Checked BEFORE the attempt, not after: an attempt started
        # with 20 seconds of call budget left is killed from outside, which is
        # the one exit that leaves no record of itself. Stopping cleanly costs
        # one attempt and keeps the log, the floors and the resume point.
        build_timeout = a.per_build_seconds + 90
        # The FIRST attempt of a call always runs. A supervisor that refuses to
        # try because the budget is tight is the process preventing the lineup,
        # which is the failure this whole file is filed against; being killed
        # after one honest attempt is strictly better than delivering nothing
        # and calling it prudence. The guard exists to stop the SECOND and later
        # attempts from being cut off mid-build with the log unflushed.
        first_attempt_of_this_call = attempt == attempts_done + 1
        if (call_deadline is not None and not first_attempt_of_this_call
                and time.monotonic() + build_timeout > call_deadline):
            remaining_slate = max(0.0, deadline - time.monotonic())
            dec.add(attempt, "stop",
                    f"this call's budget ({a.call_budget_seconds:.0f}s) cannot "
                    f"hold another {build_timeout}s attempt; stopping with the "
                    f"log intact rather than being killed mid-build",
                    resumable=True,
                    attempts_made=attempt - 1,
                    slate_seconds_remaining=round(remaining_slate, 1),
                    remedy="re-invoke the same command with --resume",
                    **dec.controls_block())
            _write(dec, last_brief, salary=a.salary)
            return 5

        if time.monotonic() > deadline:
            # R212. This was the one return in main() that did not flush, so
            # the run that spent its entire window -- precisely the run whose
            # post-mortem anyone needs -- filed no decision log at all.
            # R169(a) fixed the identical defect on the TimeoutExpired path
            # eight lines below, three days earlier, and did not enumerate the
            # sibling. Reachable by construction on defaults: eight attempts at
            # up to per_build_seconds + 90 each, against a twelve-minute wall
            # clock. CLAUDE.md's Autonomy section rests on this log being the
            # record of every decision; on this path there was no record.
            dec.add(attempt, "stop", "supervised wall clock spent",
                    attempts_made=attempt - 1,
                    stop_after_minutes=a.stop_after_minutes)
            _write(dec, last_brief, salary=a.salary)
            return 5

        entry = str(ASSERTED) if ignore_pool else str(BUILD)
        cmd = [sys.executable, "-u", entry]
        # R169(d). The passthrough goes FIRST, and it is split with shlex.
        #
        # Order: argparse takes the LAST occurrence of a repeated flag, and the
        # passthrough used to be appended after --controls-override, so an
        # operator's own --controls-override silently outranked the structural
        # floors this supervisor had just applied -- while the decision log
        # recorded that they landed. The log has to describe the command that
        # ran. Supervisor-owned flags therefore come last and win.
        #
        # shlex: `.split()` broke on exactly the argument most worth passing
        # through, a quoted JSON dict, turning
        # `--controls-override {"max_shared_players": 7}` into three tokens and
        # a parse error the operator reads as a build failure.
        #
        # R214. The operator's own --controls-override is no longer among these
        # tokens; it was lifted out above and merged into the single occurrence
        # emitted below. Last-wins dropped the operator's ENTIRE dict, which is
        # not what "supervisor-owned flags win" meant.
        if passthrough_tokens:
            cmd += passthrough_tokens
        if ignore_pool:
            cmd += ["--assert-gate", GATE_IMPLIED_BY_POOL_OVERRIDE]
        cmd += ["--salary", a.salary, "--entries", a.entries,
                "--max-seconds", str(a.per_build_seconds)]
        for flag, val in (("--lineups", a.lineups), ("--odds", a.odds),
                          ("--postures", a.postures),
                          # R290(c) step 2. Forwarded, not merely consumed. A
                          # supervisor that knows the lock while the thing doing
                          # the work does not is the two-readers-one-fact shape
                          # this repo keeps paying for, and the governor that
                          # matters is the one on the refusal itself.
                          ("--deliver-by", getattr(a, "deliver_by", None))):
            if val:
                cmd += [flag, val]
        if dec.never_relax:
            cmd += ["--never-relax", ",".join(dec.never_relax)]
        effective = dec.effective_controls
        if effective:
            cmd += ["--controls-override", json.dumps(effective)]
        if ignore_pool:
            cmd += ["--ignore-pool-blockers"]

        # R169(a). The timeout had no handler. The bank budget floors make an
        # overshoot past --per-build-seconds possible BY CONSTRUCTION
        # (resolve_bank_budget floors the budget at a constant regardless of the
        # window asked for), so this fires on real runs, and when it fired
        # `_write` never ran: the entire decision log was lost and the process
        # exited 1, off the 0/3/4/5/10 contract -- on exactly the run whose
        # post-mortem needed it. A timeout is out-of-time, which is 5.
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  cwd=str(REPO), timeout=a.per_build_seconds + 90)
        except subprocess.TimeoutExpired as exc:
            dec.add(attempt, "build_timed_out",
                    f"build_slate exceeded {a.per_build_seconds + 90}s of wall "
                    f"clock and was killed; no brief was produced, so there is "
                    f"nothing to classify and nothing to retry against",
                    timeout_s=a.per_build_seconds + 90,
                    per_build_seconds=a.per_build_seconds,
                    **dec.controls_block())
            _write(dec, last_brief, salary=a.salary)
            return 5
        brief = parse_brief(proc.stdout) or parse_brief(proc.stderr)
        last_brief = brief or last_brief
        state["brief"] = last_brief
        code = proc.returncode

        # R296(d). Anything outside build_slate's documented vocabulary fell
        # through to the code-3 handler below, which asks the brief what the
        # engine refused for -- and on a crash there is no brief, so the log
        # read "refused with no remedy this supervisor may take, errors=[]".
        # That sentence appears in outputs/2026-09-01/_ab1.err and it is a
        # CRASH WEARING A REFUSAL'S LABEL, the exact thing R168 was filed to
        # stop, reached one file downstream of where R168 fixed it. Worse, the
        # two facts that identify the crash -- the exit code and what the child
        # printed -- were recorded nowhere, so the artifact that should explain
        # the stop cannot even name it. Named, with both facts, before any
        # classification is attempted.
        if code not in BUILD_SLATE_CONTRACT_CODES:
            dec.add(attempt, "stop",
                    f"{Path(entry).name} exited {code}, outside its documented "
                    f"{list(BUILD_SLATE_CONTRACT_CODES)} contract. That is a "
                    f"crash, not a refusal: there is no verdict to classify and "
                    f"no remedy this supervisor may take. The child's stderr "
                    f"tail is recorded below.",
                    returncode=code,
                    stderr=(proc.stderr or "")[-2000:],
                    brief_parsed=bool(brief))
            _write(dec, last_brief, salary=a.salary)
            return 3

        if code == 0:
            if not brief or not brief.get("delivered_path") or not brief.get("delivered_sha256"):
                dec.add(attempt, "stop", "exit zero without a structured, hash-bound delivery is not certification")
                _write(dec, brief, salary=a.salary)
                return 3
            dec.add(attempt, "delivered",
                    f"sha256={brief.get('delivered_sha256', '?')[:12]}",
                    delivered=brief.get("delivered_path"))
            break

        if code == 4:
            dec.add(attempt, "stop", "inputs missing; nothing to decide")
            _write(dec, brief, salary=a.salary)
            return 4

        if code == 10:
            dec.add(attempt, "grow_bank",
                    "job list not exhausted; search effort, not strategy",
                    jobs=(brief.get("solve", {}) or {}).get("bank", {}).get("jobs_attempted"))
            continue

        # code 3: built but refused, or blocked before building.
        status = brief.get("status")
        if status == "pool_blocked" and not ignore_pool:
            blockers = brief.get("blockers") or []
            verdicts = {b: classify_pool_blocker(b) for b in blockers}
            unclassified = [b for b, v in verdicts.items() if not v]
            if unclassified:
                dec.add(attempt, "stop",
                        "pool blocker outside the benign classification; a human "
                        "decides this one", unclassified=unclassified)
                _write(dec, brief, salary=a.salary)
                return 3
            ignore_pool = True
            dec.add(attempt, "override_pool_blockers",
                    "every blocker matched a benign classification; asserting "
                    f"{GATE_IMPLIED_BY_POOL_OVERRIDE} on the same evidence, since "
                    "that gate derives from the pool report and would otherwise "
                    "keep failing on findings already classified",
                    classifications=verdicts,
                    gate_asserted=GATE_IMPLIED_BY_POOL_OVERRIDE)
            continue

        # A refusal. Grow the bank before touching any control.
        bank = (brief.get("solve", {}) or {}).get("bank", {}) or {}
        if bank.get("job_list_exhausted") is False:
            dec.add(attempt, "grow_bank",
                    "refusal against a partial bank; the engine's first remedy is "
                    "always to grow it, never to relax a control",
                    jobs_attempted=bank.get("jobs_attempted"),
                    jobs_total=bank.get("jobs_total"))
            continue

        checks = ((brief.get("feasibility") or {}).get("checks")) or []
        applied = {}
        for c in checks:
            if c.get("passed") is not False or not c.get("remedy"):
                continue
            if c.get("name") not in STRUCTURAL_CHECKS:
                dec.add(attempt, "stop",
                        f"failing check '{c.get('name')}' is a STRATEGY control "
                        f"with no engine-named floor; not mine to move",
                        remedy=c.get("remedy"))
                _write(dec, brief, salary=a.salary)
                return 3
            m = CONTROL_FLOOR_RE.search(c["remedy"])
            if not m:
                dec.add(attempt, "stop", "structural remedy not machine-readable",
                        remedy=c["remedy"])
                _write(dec, brief, salary=a.salary)
                return 3
            control, floor_to = m.group(1), int(m.group(2))
            if control in dec.never_relax:
                # R388(b). The floor is arithmetic, and the operator's word
                # outranks it: raising a never-relax control is Ben's call,
                # so this names it and stops rather than retrying forever.
                dec.add(attempt, "stop",
                        f"structural check '{c['name']}' needs {control} raised "
                        f"to >= {floor_to}, and {control} is --never-relax; "
                        f"the operator's never-relax holds, so a human decides "
                        f"whether to lift it",
                        remedy=c["remedy"], never_relax=list(dec.never_relax))
                _write(dec, brief, salary=a.salary)
                return 3
            expected = STRUCTURAL_CONTROL_BY_CHECK[c["name"]]
            if control != expected:
                dec.add(attempt, "stop",
                        f"structural check '{c['name']}' named control "
                        f"'{control}', which is not the control that check is "
                        f"about ('{expected}'); the classification covers the "
                        f"check, not any control a remedy sentence happens to "
                        f"name, so a human decides this one",
                        remedy=c["remedy"])
                _write(dec, brief, salary=a.salary)
                return 3
            applied[control] = floor_to
        if applied and applied != {k: dec.derived_controls.get(k) for k in applied}:
            dec.derived_controls.update(applied)
            # R214. Three fields rather than one. `controls=` used to print the
            # supervisor's floors and call that the answer, so an operator's
            # override that had just been dropped left no trace anywhere.
            dec.add(attempt, "apply_structural_floor",
                    "engine classified these ARITHMETIC: raising to the named "
                    "floor removes an impossibility and changes nothing else",
                    **dec.controls_block())
            continue

        dec.add(attempt, "stop", "refused with no remedy this supervisor may take",
                errors=(brief.get("errors") or [])[:2])
        _write(dec, brief, salary=a.salary)
        return 3

    _write(dec, last_brief, salary=a.salary)
    return 0 if bool(dec.log) and dec.log[-1]["action"] == "delivered" else 3


def _resume_state(dec: "Decisions", salary: Optional[str]) -> Dict[str, Any]:
    """R296(f). Read back the decision log this run is continuing.

    Restores the three things a second call would otherwise re-derive at the
    cost of the window: how many attempts were already spent, the structural
    floors already applied, and whether pool blockers were already overridden.
    The floors are the expensive one -- each was paid for with a full build.

    Never fatal. A missing or unreadable log means "nothing to resume", which is
    exactly the fresh-run state, and refusing to start because a resume file is
    torn would be the process preventing the lineup.
    """
    out: Dict[str, Any] = {"attempts_done": 0, "ignore_pool": False, "path": None}
    date = _decision_log_date({}, salary)
    path = REPO / "outputs" / str(date) / "autobuild_decisions.json"
    out["path"] = str(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return out
    records = payload.get("decisions") or []
    if not isinstance(records, list) or not records:
        return out
    attempts = [int(r.get("attempt") or 0) for r in records
                if isinstance(r, dict) and isinstance(r.get("attempt"), int)]
    out["attempts_done"] = max(attempts) if attempts else 0
    out["ignore_pool"] = any(
        isinstance(r, dict) and r.get("action") == "override_pool_blockers"
        for r in records)
    derived = ((payload.get("controls") or {}).get("derived_controls") or {})
    if isinstance(derived, dict):
        dec.derived_controls.update(derived)
    # The prior log is the run's history, so keep it rather than starting a new
    # file: the flush rewrites the whole document and a resumed run that dropped
    # the earlier attempts would make the artifact say the floors appeared from
    # nowhere.
    dec.log.extend(r for r in records if isinstance(r, dict))
    return out


def _decision_log_date(brief: Dict[str, Any], salary: Optional[str] = None) -> str:
    """Which outputs/<date>/ this decision log belongs in.

    R169(b). The old fallback was ``datetime.now()``, the container's calendar,
    which is UTC: after 8pm ET every pre-brief stop filed its decision log under
    TOMORROW's date, so the one artifact explaining why a build never happened
    landed in a directory nobody was looking in. The R65/R95 class.

    Three sources, in the order of how much they know. The brief's own ``date``
    is the build's answer and wins. The salary file is the same authority
    build_slate itself dates a slate from, and it is available on every stop,
    including the ones that produce no brief at all. ``today_et`` is last and is
    the schedule's calendar, never the container's.
    """
    date = (brief or {}).get("date")
    if date:
        return str(date)
    if salary:
        try:
            from mlb_engine.intake.slate_intake_manager import (
                parse_dk_salary_csv, parse_game_info_datetime,
            )
            for sp in parse_dk_salary_csv(str(salary)):
                parsed = parse_game_info_datetime(sp.game_info)
                if parsed is not None:
                    return parsed.date().isoformat()
        except Exception:  # noqa: BLE001 - an undatable salary file is not fatal
            pass
    # R296(e). Guarded, and the guard is not belt-and-braces. This import ran
    # OUTSIDE `_write`'s try block, so when it raised -- which it did on every
    # invocation, see the sys.path note at the top of this file -- the whole
    # process died at exit 1 and the decision log this function exists to place
    # was never written at all. The path insert is the fix; this is the promise
    # that no future import failure can cost the log again.
    #
    # The fallback is ET, never `date.today()`: R169(b) is on record that the
    # container's calendar is UTC, so after 8pm ET every pre-brief stop filed
    # its log under TOMORROW. If zoneinfo cannot answer either, the date is
    # LABELLED rather than guessed, so a reader never mistakes a fallback for
    # the schedule's answer.
    try:
        from mlb_engine.repo_env import today_et
        return today_et()
    except Exception as exc:  # noqa: BLE001
        print(f"autobuild: repo_env unavailable ({type(exc).__name__}); dating "
              f"this decision log from zoneinfo", file=sys.stderr)
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    except Exception as exc:  # noqa: BLE001
        print(f"autobuild: no ET clock available ({type(exc).__name__}); this "
              f"decision log is filed under a UTC-dated fallback directory and "
              f"the date is NOT the schedule's", file=sys.stderr)
        return f"_undated_utc_{datetime.now(timezone.utc).date().isoformat()}"


def _write(dec: Decisions, brief: Dict[str, Any],
           salary: Optional[str] = None) -> None:
    date = _decision_log_date(brief or {}, salary)
    out = REPO / "outputs" / str(date)
    try:
        out.mkdir(parents=True, exist_ok=True)
        (out / "autobuild_decisions.json").write_text(
            json.dumps({"decisions": dec.log,
                        # R214. The run's controls as three facts, at the top
                        # level, so a post-mortem does not have to reconstruct
                        # "what did the operator ask for" from the records.
                        "controls": dec.controls_block(),
                        "labels": "deterministic review proxies and labeled priors "
                                  "only; never ROI, win rate, cash rate, or "
                                  "probability"}, indent=1),
            encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        print(f"autobuild: could not write decision log: {exc}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
