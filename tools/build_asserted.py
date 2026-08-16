#!/usr/bin/env python3
"""build_slate.py with caller-asserted workflow gates. Same build, recorded assertion.

Why this exists, 2026-08-16. `--assume-gates` fills a gate that is UNDETERMINED;
execution_pipeline only honours it where `gates.get(name) is None`. That is
deliberate and correct: a gate that actively evaluated False has evidence behind
it, and letting a flag erase evidence would make the artifact lie.

But there is a real case it leaves no room for. `lineup_gate_passed` derives from
the pool report, so a pool blocker a human has read and classified as benign
still fails the gate forever. On 2026-08-16 that was DET listing 8 rosterable
hitters because DK never priced a called-up starter: true, verified, and
harmless, since DK owns eligibility and an unpriced player is unrosterable by
anyone. The build was correct and could not certify.

`run_slate` already has the right instrument. Caller-supplied `workflow_gates`
override derived values and land in `caller_asserted_gates` in the artifact, so
the file states that a human asserted the gate rather than implying the check
ran. This wrapper supplies them and changes nothing else: same pool, same
postures, same bank cache, same certification path.

Use it when you have READ the blocker and know what it is. It is not a way past
a gate you have not investigated, and every assertion is written into the
delivered artifact where a later reader will see it.

    python tools/build_asserted.py --assert-gate lineup_gate_passed \
        --salary DKSalaries.csv --entries DKEntries.csv [...build_slate args]
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
_PYLIBS = REPO / ".pylibs"
if _PYLIBS.is_dir():
    sys.path.insert(0, str(_PYLIBS))

BUILD = REPO / "skills" / "generate-lineups" / "scripts" / "build_slate.py"

VALID_GATES = {
    "salary_gate_passed", "entry_grid_gate_passed", "lineup_gate_passed",
    "pitcher_audit_gate_passed", "weather_gate_passed", "odds_gate_passed",
}


def main() -> int:
    argv = sys.argv[1:]
    asserted: dict[str, bool] = {}
    passthrough: list[str] = []
    i = 0
    while i < len(argv):
        if argv[i] == "--assert-gate":
            if i + 1 >= len(argv):
                print("build_asserted: --assert-gate needs a gate name", file=sys.stderr)
                return 4
            name = argv[i + 1]
            if name not in VALID_GATES:
                print(f"build_asserted: unknown gate {name!r}; valid: "
                      f"{sorted(VALID_GATES)}", file=sys.stderr)
                return 4
            asserted[name] = True
            i += 2
            continue
        passthrough.append(argv[i])
        i += 1

    if not asserted:
        print("build_asserted: no --assert-gate given; use build_slate.py directly",
              file=sys.stderr)
        return 4

    import mlb_engine.pipeline.execution_pipeline as ep

    original = ep.run_slate

    def run_slate_asserting(*args, **kwargs):
        supplied = dict(kwargs.get("workflow_gates") or {})
        for name, value in asserted.items():
            supplied.setdefault(name, value)
        kwargs["workflow_gates"] = supplied
        print(f"caller-asserted gates: {sorted(asserted)} "
              f"(recorded in the artifact, not silently defaulted)", file=sys.stderr)
        return original(*args, **kwargs)

    ep.run_slate = run_slate_asserting

    spec = importlib.util.spec_from_file_location("build_slate_mod", BUILD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    sys.argv = ["build_slate.py"] + passthrough
    return mod.main()


if __name__ == "__main__":
    raise SystemExit(main())
