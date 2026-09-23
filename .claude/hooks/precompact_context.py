#!/usr/bin/env python
"""PreCompact hook: carry CLAUDE.md's `## Compaction` list across a compaction (R372).

WHY. CLAUDE.md ends with a `## Compaction` section naming what must survive:
the role and the claim held, the R-numbers in flight and their files, the last
gate line, and any instruction Ben gave this session. That is prose addressed to
a session that has already lost the context telling it to read the prose. This
hook injects the section, plus the facts it names that a hook can actually read,
at the moment the compaction runs.

WHAT IT DOES NOT DO. It cannot recover the R-numbers in flight or Ben's
instruction from the conversation, so it names them as things the model must
carry itself rather than pretending to supply them. A checklist that silently
drops two of its five items is worse than no checklist.

THE TASK FILE (R409). What it cannot recover from the conversation it CAN read
from `claims/<claim>/TASKS.md`, the list CLAUDE.md's `## Compaction` tells a
session to keep as it goes. Each HELD claim's file is injected verbatim, capped
at `TASKS_MAX_CHARS`. A file older than its claim's `taken_utc` was written by an
earlier holder of the same name (release-then-retake) and is named, not
injected. A released claim is neither listed nor read: `claim.py release` stamps
`released_utc` and leaves the directory, so on a long-lived tree most claim
directories are released ones.

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
from datetime import datetime, timezone
from pathlib import Path

TASKS_FILE = "TASKS.md"
TASKS_MAX_CHARS = 6000


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


def _held(root: Path) -> list[tuple[Path, dict]]:
    """(directory, owner) for every claim not stamped `released_utc`.

    An unreadable owner.json counts as held with an empty owner, matching
    `claim.py`'s own default that a half-written claim is not free.
    """
    base = root / "claims"
    if not base.is_dir():
        return []
    out = []
    for d in sorted(base.iterdir()):
        owner = d / "owner.json"
        if not owner.is_file():
            continue
        try:
            data = json.loads(owner.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        if data.get("released_utc"):
            continue
        out.append((d, data))
    return out


def held_claims(root: Path) -> str:
    """The claims this container holds, by name and scope.

    Container-local and invisible to other sessions (R359), which is exactly why
    it is worth carrying: nothing else in the post-compaction context says the
    session took one, and a claim it forgets it holds is a claim it never
    releases.
    """
    out = []
    for d, data in _held(root):
        if not data:
            out.append(d.name)
            continue
        out.append(f"{d.name} (role {data.get('role', '?')}, "
                   f"scope {data.get('scope', '?')})")
    return "; ".join(out) or "none"


def _taken(data: dict) -> datetime | None:
    try:
        return datetime.strptime(str(data.get("taken_utc")), "%Y-%m-%dT%H:%M:%SZ"
                                 ).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def task_files(root: Path) -> list[str]:
    """Each held claim's TASKS.md, verbatim and capped, or why it was left out."""
    blocks = []
    for d, data in _held(root):
        path = d / TASKS_FILE
        if not path.is_file():
            continue
        rel = f"claims/{d.name}/{TASKS_FILE}"
        try:
            mtime = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
            text = path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            blocks.append(f"{rel}: unreadable")
            continue
        taken = _taken(data)
        if taken is not None and mtime < taken:
            blocks.append(
                f"{rel}: last written {mtime:%Y-%m-%dT%H:%M:%SZ}, before this "
                f"claim was taken at {data.get('taken_utc')}, so it is an earlier "
                f"holder's list and is not injected.")
            continue
        if len(text) > TASKS_MAX_CHARS:
            text = (text[:TASKS_MAX_CHARS] + f"\n[truncated at {TASKS_MAX_CHARS} "
                    f"of {len(text)} characters; read {rel} for the rest]")
        blocks.append(f"--- {rel} ---\n{text}\n--- end {rel} ---")
    return blocks


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
        tasks = task_files(root)
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
        ]
        if tasks:
            parts += [
                "The session's own task list, from each held claim's "
                f"{TASKS_FILE} (R409; verbatim, one per held claim in this "
                "checkout, and yours is the claim you took):",
                *tasks,
                "",
                "NOT readable from disk unless the list above has it: the "
                "R-numbers in flight and their files, the last gate line, and "
                "any instruction Ben gave this session. If it is in neither the "
                "list nor the summary, it does not exist; add it to the file.",
            ]
        else:
            parts.append(
                "NOT readable from disk, so carry them yourself or they are "
                "gone: the R-numbers in flight and their files, the last gate "
                "line, and any instruction Ben gave this session. No held claim "
                f"has a {TASKS_FILE}, so nothing on disk records these; start "
                "one in your claim's directory now.")
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
