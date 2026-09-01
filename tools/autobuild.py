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
Every decision lands in outputs/<date>/autobuild_decisions.json.
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
BUILD = REPO / "skills" / "generate-lineups" / "scripts" / "build_slate.py"
ASSERTED = REPO / "tools" / "build_asserted.py"

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


class Decisions:
    def __init__(self) -> None:
        self.log: List[Dict[str, Any]] = []
        # R214. Three fields, because one cannot answer "what did the operator
        # ask for" and "what ran" at the same time -- and the old single dict
        # answered neither honestly, since it recorded the floors that landed
        # and never the override they displaced.
        self.user_controls: Dict[str, Any] = {}
        self.derived_controls: Dict[str, Any] = {}

    @property
    def effective_controls(self) -> Dict[str, Any]:
        """What actually reaches build_slate. Supervisor-owned keys win."""
        return {**self.user_controls, **self.derived_controls}

    def controls_block(self) -> Dict[str, Any]:
        return {"user_controls": dict(self.user_controls),
                "derived_controls": dict(self.derived_controls),
                "effective_controls": dict(self.effective_controls)}

    def add(self, attempt: int, action: str, why: str, **extra: Any) -> None:
        rec = {"attempt": attempt, "action": action, "why": why,
               "utc": datetime.now(timezone.utc).isoformat(), **extra}
        self.log.append(rec)
        print(f"[autobuild {attempt}] {action}: {why}", file=sys.stderr)


def parse_brief(stdout: str) -> Dict[str, Any]:
    i = stdout.find('{\n "status"')
    if i < 0:
        i = stdout.find('{"status"')
    if i < 0:
        return {}
    try:
        return json.loads(stdout[i:])
    except Exception:  # noqa: BLE001
        try:
            return json.loads(stdout[i:stdout.rfind("}") + 1])
        except Exception:  # noqa: BLE001
            return {}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--salary", required=True)
    ap.add_argument("--entries", required=True)
    ap.add_argument("--lineups")
    ap.add_argument("--odds")
    ap.add_argument("--postures")
    ap.add_argument("--max-attempts", type=int, default=8)
    ap.add_argument("--per-build-seconds", type=int, default=20)
    ap.add_argument("--stop-after-minutes", type=float, default=12.0,
                    help="wall clock for the whole supervised run")
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
    dec.user_controls = dict(user_controls)
    if user_controls:
        dec.add(0, "operator_controls",
                "read from --passthrough and merged UNDER the supervisor's own "
                "keys; R169(d)'s 'supervisor-owned flags win' holds per key "
                "rather than by dropping the operator's whole dict",
                **dec.controls_block())

    deadline = time.monotonic() + a.stop_after_minutes * 60.0
    ignore_pool = False
    last_brief: Dict[str, Any] = {}

    for attempt in range(1, a.max_attempts + 1):
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
                          ("--postures", a.postures)):
            if val:
                cmd += [flag, val]
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
        code = proc.returncode

        if code == 0:
            dec.add(attempt, "certified",
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
    return 0 if any(d["action"] == "certified" for d in dec.log) else 3


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
    from mlb_engine.repo_env import today_et
    return today_et()


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
