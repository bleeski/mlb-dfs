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

Exit: 0 certified, 3 refused with reasons, 4 bad input, 5 out of time.
Every decision lands in outputs/<date>/autobuild_decisions.json.
"""
from __future__ import annotations

import argparse
import json
import re
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


class Decisions:
    def __init__(self) -> None:
        self.log: List[Dict[str, Any]] = []

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
                    help="extra args forwarded to build_slate verbatim")
    a = ap.parse_args()

    drift = assert_classification_in_sync()
    if drift:
        print(f"autobuild: {drift}", file=sys.stderr)
        return 4

    deadline = time.monotonic() + a.stop_after_minutes * 60.0
    dec = Decisions()
    controls: Dict[str, Any] = {}
    ignore_pool = False
    last_brief: Dict[str, Any] = {}

    for attempt in range(1, a.max_attempts + 1):
        if time.monotonic() > deadline:
            dec.add(attempt, "stop", "supervised wall clock spent")
            return 5

        entry = str(ASSERTED) if ignore_pool else str(BUILD)
        cmd = [sys.executable, "-u", entry]
        if ignore_pool:
            cmd += ["--assert-gate", GATE_IMPLIED_BY_POOL_OVERRIDE]
        cmd += ["--salary", a.salary, "--entries", a.entries,
                "--max-seconds", str(a.per_build_seconds)]
        for flag, val in (("--lineups", a.lineups), ("--odds", a.odds),
                          ("--postures", a.postures)):
            if val:
                cmd += [flag, val]
        if controls:
            cmd += ["--controls-override", json.dumps(controls)]
        if ignore_pool:
            cmd += ["--ignore-pool-blockers"]
        if a.passthrough:
            cmd += a.passthrough.split()

        proc = subprocess.run(cmd, capture_output=True, text=True,
                              cwd=str(REPO), timeout=a.per_build_seconds + 90)
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
            _write(dec, brief)
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
                _write(dec, brief)
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
                _write(dec, brief)
                return 3
            m = CONTROL_FLOOR_RE.search(c["remedy"])
            if not m:
                dec.add(attempt, "stop", "structural remedy not machine-readable",
                        remedy=c["remedy"])
                _write(dec, brief)
                return 3
            applied[m.group(1)] = int(m.group(2))
        if applied and applied != {k: controls.get(k) for k in applied}:
            controls.update(applied)
            dec.add(attempt, "apply_structural_floor",
                    "engine classified these ARITHMETIC: raising to the named "
                    "floor removes an impossibility and changes nothing else",
                    controls=dict(controls))
            continue

        dec.add(attempt, "stop", "refused with no remedy this supervisor may take",
                errors=(brief.get("errors") or [])[:2])
        _write(dec, brief)
        return 3

    _write(dec, last_brief)
    return 0 if any(d["action"] == "certified" for d in dec.log) else 3


def _write(dec: Decisions, brief: Dict[str, Any]) -> None:
    date = (brief or {}).get("date") or datetime.now().strftime("%Y-%m-%d")
    out = REPO / "outputs" / str(date)
    try:
        out.mkdir(parents=True, exist_ok=True)
        (out / "autobuild_decisions.json").write_text(
            json.dumps({"decisions": dec.log,
                        "labels": "deterministic review proxies and labeled priors "
                                  "only; never ROI, win rate, cash rate, or "
                                  "probability"}, indent=1),
            encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        print(f"autobuild: could not write decision log: {exc}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
