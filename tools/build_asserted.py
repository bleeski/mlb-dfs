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

R490(ii), 2026-10-07. That paragraph's remedy stopped working on 2026-09-11.
R133(4) made `--assume-gates lineup_gate_passed` the one sanctioned override
of a DERIVED False (`execution_pipeline.OVERRIDABLE_GATES`), and R338 then
refused every caller-supplied `workflow_gates` value against a derived False
("supplied value cannot bypass an observed failure"). This wrapper still
supplied `workflow_gates`, so every pool override it carried failed the gate
it asserted (1600_4g: `caller_asserted_gates` held the gate and
`overridden_gates` was empty). `lineup_gate_passed` now rides build_slate's own
`--assume-gates`, which reaches the deadline baseline and the main build alike
and is recorded as `overridden_gates` with the evidence it contradicts. Any
other gate still goes through `workflow_gates`, where it fills an undetermined
gate and is refused, on the record, against a derived False. Nothing else
changes: same pool, same postures, same bank cache, same certification path.

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


# R490(ii). The gate R133(4) lets an explicit assumption promote against a
# derived False (`execution_pipeline.OVERRIDABLE_GATES`), so it rides that
# channel, build_slate's own `--assume-gates`, and not `workflow_gates`.
ASSUME_CHANNEL_GATE = "lineup_gate_passed"


def with_assumed_gate(argv: list[str], gate: str) -> list[str]:
    """``argv`` with ``gate`` in its one ``--assume-gates`` value.

    build_slate reads the flag as one comma list and argparse keeps the LAST
    occurrence, so a second flag appended here would drop the operator's own.
    Every occurrence (either spelling) is lifted out, the value build_slate
    would have read is kept, the gate is added to it, and one flag goes back.
    """
    out: list[str] = []
    names: list[str] = []
    i = 0
    while i < len(argv):
        token = argv[i]
        if token == "--assume-gates":
            # A trailing flag with no value names nothing; it is not kept as a token.
            value = argv[i + 1] if i + 1 < len(argv) else ""
            names, i = [n.strip() for n in value.split(",") if n.strip()], i + 2
        elif token.startswith("--assume-gates="):
            names = [n.strip() for n in token.split("=", 1)[1].split(",") if n.strip()]
            i += 1
        else:
            out.append(token)
            i += 1
    return out + ["--assume-gates", ",".join(names + [gate] if gate not in names
                                             else names)]


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

    # R490(ii). The overridable gate goes through build_slate's --assume-gates.
    if asserted.pop(ASSUME_CHANNEL_GATE, False):
        passthrough = with_assumed_gate(passthrough, ASSUME_CHANNEL_GATE)
        print(f"caller-asserted gate {ASSUME_CHANNEL_GATE} -> build_slate "
              f"--assume-gates (R133(4)); recorded as overridden_gates with the "
              f"evidence it contradicts", file=sys.stderr)

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

    if asserted:
        ep.run_slate = run_slate_asserting

    spec = importlib.util.spec_from_file_location("build_slate_mod", BUILD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    sys.argv = ["build_slate.py"] + passthrough
    # R393(b). The same exit door `python build_slate.py` uses, not bare
    # `main()`: autobuild runs THIS file as its child once it overrides pool
    # blockers, and `main()` alone skipped both the refusal record (R369) and
    # the guard that presents a written file after a later exception (exit 7).
    return mod._main_recording_refusals()


if __name__ == "__main__":
    raise SystemExit(main())
