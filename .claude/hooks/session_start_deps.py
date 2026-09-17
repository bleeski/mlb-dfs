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


def venv_python() -> Path:
    """`<repo>/.venv`'s interpreter. Mirrors `env_probe.venv_python`.

    Duplicated rather than imported because this hook runs before anything has
    put the repo on `sys.path`, and a hook that fails to import is a session
    that starts with no dependencies and no explanation.
    """
    if sys.platform == "win32":
        return ROOT / ".venv" / "Scripts" / "python.exe"
    return ROOT / ".venv" / "bin" / "python"


def remote() -> bool:
    return os.environ.get("CLAUDE_CODE_REMOTE", "").lower() == "true"


def export_env(lines: list) -> str:
    """Append `export` lines to the session's environment file. R353.

    `PYTHONHASHSEED=0`: CLAUDE.md's determinism rule says entry points pin it,
    and they do -- but a session runs plenty that is not an entry point
    (`python -c`, a scratch script, `pytest` directly).

    The PATH entry is load-bearing, not a convenience. The deps live in
    `<repo>/.venv` and the container's `python3` is the system one, so without
    this every command the session runs would miss them and the gate would fail
    for a reason that looks like a code defect.
    """
    env_file = os.environ.get("CLAUDE_ENV_FILE")
    if not env_file:
        return "environment not pinned (no CLAUDE_ENV_FILE)"
    try:
        with open(env_file, "a", encoding="utf-8") as fh:
            for line in lines:
                fh.write(line + "\n")
    except OSError as exc:
        return f"environment not pinned ({exc})"
    return "pinned: " + ", ".join(l.replace("export ", "") for l in lines)


def run_probe(argv: list, python: Path) -> tuple:
    try:
        out = subprocess.run([str(python), str(PROBE), *argv], cwd=ROOT,
                             capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=INSTALL_TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 2, f"env_probe did not complete: {exc}"
    return out.returncode, (out.stdout or out.stderr).strip()


def main() -> int:
    if not remote():
        return 0  # silent: this host manages its own interpreter
    if not PROBE.exists():
        sys.stdout.write(f"deps: {PROBE} missing; the gate will not run.\n")
        return 0

    venv = venv_python()
    if venv.exists():
        # Probe THROUGH the venv. Probing with the system interpreter would
        # report cold every time, because the deps are deliberately not there.
        code, text = run_probe([], venv)
        if code != 0:
            code, text = run_probe(["--install", "--venv"], Path(sys.executable))
    else:
        code, text = run_probe(["--install", "--venv"], Path(sys.executable))

    lines = ["== deps (cloud container, R353) =="]
    lines.extend(text.splitlines()[-4:])

    exports = ["export PYTHONHASHSEED=0"]
    if venv.exists():
        exports.append(f'export VIRTUAL_ENV="{venv.parent.parent}"')
        exports.append(f'export PATH="{venv.parent}:$PATH"')
    else:
        lines.append(f"deps: {venv} absent after the install step; commands will "
                     f"run against the system interpreter.")

    if code != 0:
        # Never fail the session start over this. A blocked gate that SAYS it is
        # blocked is recoverable; a session that will not start is not.
        lines.append(
            "deps: NOT READY. `python tools/audit.py --run-tests` cannot pass "
            "here yet. Say so rather than working around it, and do not lower "
            "a suite pin to get green.")
    lines.append(export_env(exports))
    sys.stdout.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
