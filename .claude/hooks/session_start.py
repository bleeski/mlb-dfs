#!/usr/bin/env python
"""SessionStart hook for mlb-dfs (Claude Code). Stdlib only; runs on Windows.

Prints, as plain text that Claude Code adds to context, the facts CLAUDE.md's
session-start step 1 asks every session to gather: HEAD and its distance from
origin, held claims, dirt classified by write set, a truncated git log, the
backlog's NEXT pointer, and any git lock files. About 300 tokens, replacing the
two shell calls and the read of a 63KB status note that used to do this job
(R301, 2026-09-15).

`--compact` prints the short form used after context compaction.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])
SUBJECT_WIDTH = 96
LOG_LINES = 12
DIRT_LINES = 14
INBOX_NAMES = 6


def git(*args: str) -> str:
    try:
        out = subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:  # git missing or hung
        return f"<git unavailable: {exc}>"
    return (out.stdout or out.stderr).rstrip()


def held_claims() -> list[str]:
    rows: list[str] = []
    today = time.strftime("%Y-%m-%d", time.gmtime())
    claims = ROOT / "claims"
    if not claims.is_dir():
        return ["claims/ missing"]
    released = 0
    for owner in sorted(claims.glob("*/owner.json")):
        try:
            data = json.loads(owner.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            rows.append(f"{owner.parent.name}: unreadable owner.json")
            continue
        if data.get("released_utc"):
            released += 1
            continue
        taken = str(data.get("taken_utc") or "")
        stale = "" if taken.startswith(today) else "  STALE (Ben arbitrates)"
        rows.append(
            f"HELD {owner.parent.name}  role={data.get('role')}  "
            f"scope={data.get('scope') or '-'}  taken={taken}{stale}"
        )
    if not rows:
        rows.append(f"none held ({released} released)")
    return rows


def dirt() -> list[str]:
    porcelain = git("status", "--porcelain")
    if not porcelain or porcelain.startswith("<git"):
        return [porcelain or "clean"]
    lines = porcelain.splitlines()
    staged = sum(1 for l in lines if l[:1] not in (" ", "?"))
    unstaged = sum(1 for l in lines if l[1:2] == "M" or l[1:2] == "D")
    untracked = sum(1 for l in lines if l.startswith("??"))
    head = [f"{len(lines)} paths: {staged} staged, {unstaged} unstaged, {untracked} untracked"]
    shown = [l for l in lines if not l.startswith("??")][:DIRT_LINES]
    more = len(lines) - len(shown)
    return head + ["  " + l for l in shown] + ([f"  ... {more} more (untracked mostly)"] if more > 0 else [])


def next_pointer() -> str:
    backlog = ROOT / "docs" / "backlog.md"
    try:
        with backlog.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.startswith("## Execution roadmap") and "NEXT:" in line:
                    return line.strip()[:320]
    except OSError:
        return "docs/backlog.md unreadable"
    return "no `## Execution roadmap ... NEXT:` heading found in docs/backlog.md"


def pending_fragments() -> str:
    """Inbox fragments waiting for their owning role to merge them.

    CLAUDE.md tells every non-owning role to drop a fragment in
    `docs/backlog_inbox/` or `ledger/inbox/` rather than edit the board or the
    ledger. Nothing surfaced them: not this hook, not `/dev-session`, and a
    COMMITTED fragment is invisible to `git status`, so the write end of that
    contract worked and the read end did not. Three backlog fragments were
    sitting unmerged on 2026-09-18, the oldest filed 2026-08-09.

    `ledger/inbox/` is ~355 machine-emitted `*_miner_*.md` decomposition blocks
    that ARCHIVE consumes in bulk from its runbook; those are not news and are
    excluded. A fragment whose first lines carry the RETAINED banner is kept BY
    DESIGN and is counted separately, so the line does not read as debt every
    session.
    """
    parts = []
    for label, rel, pattern in (("backlog", "docs/backlog_inbox", "*.md"),
                                ("ledger", "ledger/inbox", "*.md")):
        directory = ROOT / rel
        try:
            names = sorted(p.name for p in directory.glob(pattern))
        except OSError:
            continue
        if label == "ledger":
            names = [n for n in names if "_miner_" not in n]
        names = [n for n in names if not n.startswith("_")]
        if not names:
            continue
        retained = []
        fresh = []
        for name in names:
            try:
                head = (directory / name).read_text(encoding="utf-8",
                                                    errors="replace")[:400]
            except OSError:
                head = ""
            (retained if "RETAINED" in head else fresh).append(name)
        chunk = f"{label} {len(fresh)}"
        if fresh:
            chunk += " (" + ", ".join(fresh[:INBOX_NAMES]) + ")"
        if retained:
            chunk += f" +{len(retained)} retained"
        parts.append(chunk)
    return "; ".join(parts) if parts else "none"


def locks() -> str:
    hits = []
    now = time.time()
    for p in (ROOT / ".git").glob("*.lock"):
        try:
            hits.append(f"{p.name} (age {int(now - p.stat().st_mtime)}s)")
        except OSError:
            hits.append(p.name)
    return ", ".join(hits) if hits else "none"


def ahead_behind() -> str:
    out = git("rev-list", "--left-right", "--count", "HEAD...origin/main")
    if out.startswith("<git") or "fatal" in out or not out.strip():
        return "origin/main unknown here (audit measures it)"
    ahead, behind = out.split()
    return f"ahead {ahead} / behind {behind} of origin/main (as last fetched)"


def full() -> str:
    stamp = time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime())
    lock_state = locks()  # read before any git call of our own can leave one
    head = git("log", "-1", "--format=%h %<(72,trunc)%s")
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    parts = [
        f"== mlb-dfs session start ({stamp}, hook) ==",
        f"HEAD {head}  [{branch}]  {ahead_behind()}",
        "claims: " + "; ".join(held_claims()),
        "dirt (classify against your write set before touching anything):",
        *["  " + l for l in dirt()],
        f"git log, subjects truncated at {SUBJECT_WIDTH}:",
        *["  " + l for l in git("log", f"--format=%h %<({SUBJECT_WIDTH},trunc)%s", f"-{LOG_LINES}").splitlines()],
        "backlog: " + next_pointer(),
        "inbox (fragments awaiting their owning role): " + pending_fragments(),
        "git locks: " + lock_state,
        "next: take your role's claim (python tools/claim.py take engine --role DEV --scope \"...\"), "
        "then python tools/audit.py --run-tests --terse. DEV: /dev-session.",
    ]
    return "\n".join(parts)


def compact() -> str:
    return "\n".join([
        "== mlb-dfs, after compaction ==",
        "claims: " + "; ".join(held_claims()),
        "backlog: " + next_pointer(),
        "Re-read CLAUDE.md's Hard walls and Roles, claims, and git before the next write. "
        "Explicit-path git add and commit; CHANGELOG entry in the same commit; "
        "then /ship (branch, push, PR, merge on green). Force-push is refused.",
    ])


def main() -> int:
    text = compact() if "--compact" in sys.argv[1:] else full()
    # Plain text on stdout is added to Claude's context; never emit JSON here.
    sys.stdout.write(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
