#!/usr/bin/env python
"""SessionStart hook: make the gate runnable before the session tries to run it.

R353, 2026-09-17. A Claude Code cloud container is built from the repo and
nothing else, so it arrives with no numpy, pandas, scipy, pytest or pydantic.
CLAUDE.md's session-start step 2 then asks for a gate that cannot run, and
`.claude/rules/engine.md` asks the session not to "fix" tests around a host
problem -- correct advice with no remedy attached. This hook is the remedy: it
probes, and installs from `requirements.lock` only when the probe says cold.

Written in Python, not bash, on purpose: this repo has three hosts
(`docs/hosts.md`) and one of them is Windows, where a `.sh` hook does not run.
Stdlib only, same as the other two hooks here.

It is a no-op unless CLAUDE_CODE_REMOTE=true. A Windows or Cowork session
manages its own interpreter (a pinned `.venv`, a vendored `.pylibs`) and must
never have a hook install into it behind the operator's back; those hosts keep
running `python tools/env_probe.py --install` by hand when they want it.

Everything it does is `python tools/env_probe.py --install`, which is the one
install command the repo documents and the one two tests pin. This hook adds no
second install path -- if it ever disagrees with the probe, the probe wins.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])
PROBE = ROOT / "tools" / "env_probe.py"
INSTALL_TIMEOUT_S = 600


def remote() -> bool:
    return os.environ.get("CLAUDE_CODE_REMOTE", "").lower() == "true"


def pin_hashseed() -> str:
    """Put PYTHONHASHSEED=0 in the session's environment. R353.

    CLAUDE.md's determinism rule says entry points pin it, and they do -- but a
    session runs plenty that is not an entry point (`python -c`, a scratch
    script, `pytest` directly), and on those the seed is whatever the container
    felt like. Setting it for the whole session costs nothing and removes a
    class of difference nobody would think to look for.
    """
    env_file = os.environ.get("CLAUDE_ENV_FILE")
    if not env_file:
        return "PYTHONHASHSEED not pinned (no CLAUDE_ENV_FILE)"
    try:
        with open(env_file, "a", encoding="utf-8") as fh:
            fh.write("export PYTHONHASHSEED=0\n")
    except OSError as exc:
        return f"PYTHONHASHSEED not pinned ({exc})"
    return "PYTHONHASHSEED=0 pinned for this session"


def run_probe(install: bool) -> tuple[int, str]:
    cmd = [sys.executable, str(PROBE)] + (["--install"] if install else [])
    try:
        out = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                             encoding="utf-8", errors="replace",
                             timeout=INSTALL_TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 2, f"env_probe did not complete: {exc}"
    return out.returncode, (out.stdout or out.stderr).strip()


def main() -> int:
    if not remote():
        return 0  # silent: this host manages its own interpreter
    if not PROBE.exists():
        sys.stdout.write(f"deps: {PROBE} missing; the gate will not run.\n")
        return 0

    code, text = run_probe(install=False)
    if code != 0:
        code, text = run_probe(install=True)

    lines = ["== deps (cloud container, R353) =="]
    lines.extend(text.splitlines()[-4:])
    if code != 0:
        # Never fail the session start over this. A blocked gate that SAYS it is
        # blocked is recoverable; a session that will not start is not.
        lines.append(
            "deps: NOT READY. `python tools/audit.py --run-tests` cannot pass "
            "here yet. Say so rather than working around it, and do not lower "
            "a suite pin to get green.")
    lines.append(pin_hashseed())
    sys.stdout.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
