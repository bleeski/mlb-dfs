#!/usr/bin/env python
"""PreToolUse guard for Bash and PowerShell commands in mlb-dfs (Claude Code).

Deterministic enforcement of the parts of CLAUDE.md's multi-session contract
and hard walls that a permission prefix rule cannot express (R301, 2026-09-15).
Stdlib only; runs on Windows. Reads the hook JSON on stdin, prints a
PreToolUse decision on stdout, exits 0. Anything it does not recognise is
allowed silently, so a bug here fails open, never closed.

Denied:
  git add -A / --all / .            explicit paths only (contract)
  git checkout|reset|stash|restore|clean   banned while any foreign claim is live
  git push                          sessions COMMIT, Ben PUSHES
  pip install -r requirements.txt   the unpinned resolve; use tools/env_probe.py --install
  anything naming draftkings.com    DK reads are manual, by any client
Asked (a prompt, not a block):
  git commit with no pathspec       a pathless commit sweeps other sessions' staged files

Test by hand:
  echo '{"tool_name":"Bash","tool_input":{"command":"git add -A"}}' | python .claude/hooks/guard_commands.py
"""
from __future__ import annotations

import json
import re
import shlex
import sys

GIT_BANNED = re.compile(r"(?<![\w-])git\s+(?:-C\s+\S+\s+)?(checkout|reset|stash|restore|clean)\b")
GIT_PUSH = re.compile(r"(?<![\w-])git\s+(?:-C\s+\S+\s+)?push\b")
GIT_ADD = re.compile(r"(?<![\w-])git\s+(?:-C\s+\S+\s+)?add\b([^|;&\n]*)")
GIT_COMMIT = re.compile(r"(?<![\w-])git\s+(?:-C\s+\S+\s+)?commit\b([^|;&\n]*)")
PIP_UNPINNED = re.compile(r"pip3?\s+install\b[^|;&\n]*-r\s+requirements\.txt\b")
DRAFTKINGS = re.compile(r"draftkings\.com", re.IGNORECASE)


def decision(kind: str, reason: str) -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": kind,
            "permissionDecisionReason": reason,
        }
    }


def tokens(fragment: str) -> list[str]:
    try:
        return shlex.split(fragment, posix=True)
    except ValueError:
        return fragment.split()


def judge(command: str) -> dict | None:
    if DRAFTKINGS.search(command):
        return decision("deny", "CLAUDE.md hard wall: DraftKings reads are MANUAL. Never fetch draftkings.com "
                                "by any client; Ben downloads the file and drops it in the repo.")
    if GIT_PUSH.search(command):
        return decision("deny", "CLAUDE.md: sessions COMMIT, Ben PUSHES. Leave the commit on main and say so.")
    m = GIT_BANNED.search(command)
    if m:
        return decision("deny", f"CLAUDE.md multi-session contract: no `git {m.group(1)}` while any claim you do "
                                f"not own is live. Uncommitted work of another session is the blast radius.")
    if PIP_UNPINNED.search(command):
        return decision("deny", "The unpinned resolve is barred (R7, R42): use `python tools/env_probe.py --install`, "
                                "which installs requirements-production.lock.")
    for m in GIT_ADD.finditer(command):
        for tok in tokens(m.group(1)):
            if tok in ("-A", "--all", "."):
                return decision("deny", "CLAUDE.md: `git add` by explicit path only, never -A, --all, or `.`; "
                                        "another session's dirt is in this tree.")
            if tok.startswith("-A") or tok.startswith("--all="):
                return decision("deny", "CLAUDE.md: `git add` by explicit path only.")
    for m in GIT_COMMIT.finditer(command):
        args = tokens(m.group(1))
        if any(a in ("--amend", "--allow-empty") for a in args):
            continue
        has_path = "--" in args
        skip = False
        for a in args:
            if skip:                      # the value of -m/-F/etc. is a message, not a path
                skip = False
                continue
            if a in ("-m", "-F", "--message", "--file", "--author", "--date", "-C", "-c", "--fixup", "--squash"):
                skip = True
                continue
            if a.startswith("-"):
                continue
            if "/" in a or "\\" in a or a.endswith((".py", ".md", ".json", ".csv", ".txt", ".lock", ".yaml")):
                has_path = True
        if not has_path:
            return decision("ask", "This `git commit` names no paths. A pathless commit sweeps EVERY session's staged "
                                   "files (CLAUDE.md). Pass the same explicit paths you gave `git add`, or confirm "
                                   "you mean to commit the whole index.")
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0
    if payload.get("tool_name") not in ("Bash", "PowerShell"):
        return 0
    command = str((payload.get("tool_input") or {}).get("command") or "")
    verdict = judge(command)
    if verdict is not None:
        sys.stdout.write(json.dumps(verdict))
    return 0


if __name__ == "__main__":
    sys.exit(main())
