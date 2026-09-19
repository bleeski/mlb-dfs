#!/usr/bin/env python
"""SessionEnd hook: warn when this container is about to take work with it (R372).

WHY. A Claude Code cloud container is EPHEMERAL and everything uncommitted dies
with the session (CLAUDE.md's `## Hosts`). `outputs/` and `runs/` are gitignored,
so a build that never pushed leaves nothing behind at all, and a DEV session that
never pushed leaves its R-numbers unshipped. The rule is prose in CLAUDE.md; this
says it at the one moment it still matters.

BEST-EFFORT, DELIBERATELY. A container reclaim may not fire SessionEnd at all, so
this is a second line and never the first. Do not let the existence of this hook
be a reason to push later.

NEVER BLOCKS. `SessionEnd` can block termination with exit 2 and this never does:
a session that cannot end is worse than a session that ended noisily. It also
keeps well inside the event's shared 1.5s budget -- three short git calls, each
capped at 3 seconds, and any failure exits silently.

Test by hand:
  echo '{"hook_event_name":"SessionEnd","cwd":"."}' | python .claude/hooks/session_end_push.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def repo_root() -> Path:
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env and Path(env).is_dir():
        return Path(env)
    return Path(__file__).resolve().parents[2]


def git(root: Path, *args: str) -> str | None:
    try:
        p = subprocess.run(["git", *args], capture_output=True, text=True,
                           timeout=3, cwd=str(root))
    except (OSError, subprocess.SubprocessError):
        return None
    return p.stdout.strip() if p.returncode == 0 else None


def main() -> int:
    try:
        json.load(sys.stdin)
    except ValueError:
        pass
    try:
        root = repo_root()
        if git(root, "rev-parse", "--git-dir") is None:
            return 0                      # not a git repo; nothing to say
        # `git branch --show-current`, not `rev-parse --abbrev-ref HEAD`: on an
        # UNBORN HEAD (a repo with no commits) rev-parse exits non-zero, and the
        # first cut returned right there -- losing the uncommitted-work warning
        # as well, on the one tree where every file in it is unsaved. Caught by
        # its own test, 2026-09-19.
        branch = git(root, "branch", "--show-current") or ""
        warnings: list[str] = []

        # Unpushed commits. `@{u}` fails when the branch has no upstream, which
        # is itself the loudest case: a branch that was never pushed at all.
        ahead = git(root, "rev-list", "--count", "@{u}..HEAD")
        if ahead is None:
            if branch and branch != "main":
                warnings.append(
                    f"branch `{branch}` has NO UPSTREAM -- nothing on it has "
                    f"ever been pushed. `git push -u origin {branch}`.")
        elif ahead.isdigit() and int(ahead) > 0:
            warnings.append(
                f"{ahead} commit(s) on `{branch}` are not pushed. "
                f"`git push -u origin {branch}`.")

        dirty = git(root, "status", "--porcelain")
        if dirty:
            n = len([ln for ln in dirty.splitlines() if ln.strip()])
            warnings.append(f"{n} uncommitted path(s) in the tree.")

        if not warnings:
            return 0
        sys.stdout.write(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "SessionEnd",
                "systemMessage": (
                    "mlb-dfs (R372): this container is EPHEMERAL and everything "
                    "uncommitted dies with it. " + " ".join(warnings) +
                    " If a slate is in flight, Ben having the file comes first; "
                    "the repo housekeeping is still yours to finish."),
            }
        }))
    except Exception:  # noqa: BLE001 - a session is never blocked from ending
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
