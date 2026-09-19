#!/usr/bin/env python
"""PreCompact hook: carry CLAUDE.md's `## Compaction` list across a compaction (R372).

WHY. CLAUDE.md ends with a `## Compaction` section naming what must survive:
the role and the claim held, the R-numbers in flight and their files, the last
gate line, and any instruction Ben gave this session. That is prose addressed to
a session that has already lost the context telling it to read the prose. This
hook injects the section, plus the facts it names that a hook can actually read,
at the moment the compaction runs.

WHAT IT DOES NOT DO. It cannot recover the R-numbers in flight or Ben's
instruction -- those live in the conversation, not on disk -- so it names them as
things the model must carry itself rather than pretending to supply them. A
checklist that silently drops two of its five items is worse than no checklist.

READS THE CONTRACT, NEVER RESTATES IT. The section text is read from CLAUDE.md
at run time. A copy here would be a sixteenth entry in R301's contradiction list
the first time either file moved.

Stdlib only; runs on Windows. Fails open: any error exits 0 with no output, so a
compaction is never blocked by this file.

Test by hand:
  echo '{"hook_event_name":"PreCompact","cwd":"."}' | python .claude/hooks/precompact_context.py
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


def compaction_section(root: Path) -> str:
    """CLAUDE.md's `## Compaction` section, heading included, or ''."""
    try:
        lines = (root / "CLAUDE.md").read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    out: list[str] = []
    for line in lines:
        if out and line.startswith("## "):
            break
        if line.startswith("## Compaction"):
            out.append(line)
            continue
        if out:
            out.append(line)
    return "\n".join(out).strip()


def held_claims(root: Path) -> str:
    """The claims this container holds, by name and scope.

    Container-local and invisible to other sessions (R359), which is exactly why
    it is worth carrying: nothing else in the post-compaction context says the
    session took one, and a claim it forgets it holds is a claim it never
    releases.
    """
    base = root / "claims"
    if not base.is_dir():
        return "none"
    out = []
    for d in sorted(base.iterdir()):
        owner = d / "owner.json"
        if not owner.is_file():
            continue
        try:
            data = json.loads(owner.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            out.append(d.name)
            continue
        out.append(f"{d.name} (role {data.get('role', '?')}, "
                   f"scope {data.get('scope', '?')})")
    return "; ".join(out) or "none"


def git_facts(root: Path) -> str:
    def run(*args: str) -> str:
        try:
            p = subprocess.run(["git", *args], capture_output=True, text=True,
                               timeout=5, cwd=str(root))
        except (OSError, subprocess.SubprocessError):
            return "?"
        return p.stdout.strip() if p.returncode == 0 else "?"
    branch = run("rev-parse", "--abbrev-ref", "HEAD")
    head = run("log", "-1", "--format=%h %s")
    dirty = run("status", "--porcelain")
    n = len([ln for ln in dirty.splitlines() if ln.strip()]) if dirty != "?" else "?"
    return f"branch {branch} | HEAD {head} | {n} dirty path(s)"


def main() -> int:
    try:
        json.load(sys.stdin)
    except ValueError:
        pass
    try:
        root = repo_root()
        section = compaction_section(root)
        parts = [
            "mlb-dfs: what must survive this compaction (R372, injected from "
            "CLAUDE.md at compaction time -- this is the contract's own text, "
            "not a paraphrase).",
            "",
            section or "(CLAUDE.md's `## Compaction` section could not be read.)",
            "",
            "Readable from disk right now:",
            f"  claims held: {held_claims(root)}",
            f"  git: {git_facts(root)}",
            "",
            "NOT readable from disk, so carry them yourself or they are gone: "
            "the R-numbers in flight and their files, the last gate line, and "
            "any instruction Ben gave this session. Nothing on disk records "
            "these; if they are not in the summary they do not exist.",
        ]
        sys.stdout.write(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreCompact",
                "additionalContext": "\n".join(parts),
            }
        }))
    except Exception:  # noqa: BLE001 - a compaction is never blocked by this file
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
