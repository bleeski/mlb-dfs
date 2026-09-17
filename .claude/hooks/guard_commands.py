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
  git push --force / -f             a force-push discards commits, and in a
                                    multi-session tree they may not be yours
  pip install -r requirements.txt   the unpinned resolve; use tools/env_probe.py --install
  anything naming draftkings.com    DK reads are manual, by any client
Asked (a prompt, not a block):
  git commit with no pathspec       a pathless commit sweeps other sessions' staged files

An ORDINARY `git push` is allowed (R350, Ben 2026-09-16). It was denied from
R301 until then, on CLAUDE.md's "Sessions COMMIT, Ben PUSHES" -- a convention,
never a capability limit, and docs/cowork_sync_protocol.md always said so. It
cost something on 2026-09-16: a BUILD session finished a slate, committed a
backlog fragment, and then hit this hook and the settings deny list on the push
its own harness stop-hook was asking for, with no resolution available to it
except to report the contradiction. An ordinary push is additive and revertible;
a force-push is what actually destroys work, so that is what stays denied.

Judging is per SEGMENT, not over the raw command string (R350). Every rule here
used to `search` the whole string, so a READ-ONLY `grep` whose pattern contained
a banned literal was denied -- a hook that blocks reading about a rule rather
than breaking it. Confirmed live on 2026-09-16, when a search for this file's own
push rule was refused. The command is now split on `&&`, `||`, `|`, `;` and
newlines with quote awareness, each segment's real command is resolved past env
assignments and wrappers (`timeout 130 python ...`), and a segment whose command
is a read-only text tool is exempt from the content rules. Nothing else about
matching changed: each segment is still judged by the same regexes, so no action
this hook used to deny is allowed now.

Test by hand:
  echo '{"tool_name":"Bash","tool_input":{"command":"git add -A"}}' | python .claude/hooks/guard_commands.py
"""
from __future__ import annotations

import json
import re
import shlex
import sys

# The git rules are answered from ARGV (`git_subcommand`), not from the segment
# text. R350 round two: the regexes these replaced read a banned literal inside a
# QUOTED ARGUMENT as the banned act, so the commit that shipped R350 was denied by
# its own message, which documents `git add -A` while explaining the rule. Same
# defect as the read-only `grep`, one level down.
GIT_BANNED_SUBCOMMANDS = frozenset({"checkout", "reset", "stash", "restore", "clean"})

# These two still match TEXT, deliberately. `draftkings.com` is a hard wall and
# should fail closed, so it is matched broadly and relies on the read-only
# exemption rather than on an allowlist of fetchers. The pip rule is a content
# match because `python -m pip install -r requirements.txt` puts the offending
# part in argv anyway and the regex already reads both spellings.
PIP_UNPINNED = re.compile(r"pip3?\s+install\b[^|;&\n]*-r\s+requirements\.txt\b")
DRAFTKINGS = re.compile(r"draftkings\.com", re.IGNORECASE)

# Commands that cannot change anything. A segment whose real command is one of
# these is exempt from the CONTENT rules, which is what stops a search for a
# banned literal from being mistaken for the banned act. Anything that writes
# (`tee`) or runs its argument (`sh`, `python`) is deliberately absent: a pipe
# into one of those is its own segment and gets judged on its own.
READ_ONLY_TOOLS = frozenset({
    "grep", "rg", "egrep", "fgrep", "ack", "find", "locate",
    "sed", "awk", "cat", "head", "tail", "less", "more", "nl", "strings",
    "wc", "sort", "uniq", "diff", "cut", "tr", "jq", "column", "echo", "printf",
})

# Wrappers that take another command as their argument. This list is LOAD-BEARING
# for the git rules since R350 round two: they resolve the subcommand from argv,
# so a wrapper missing from here would hide `timeout 130 git add -A` entirely.
# That is also why the deny cases in tests/test_core.py include the wrapped
# spellings -- an argv-based rule is exact about what it sees and blind to what it
# does not, where the old regex was the reverse.
COMMAND_WRAPPERS = frozenset({
    "timeout", "env", "nohup", "setsid", "sudo", "nice", "ionice", "stdbuf",
    "time", "xargs", "command", "exec",
})

ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
DURATION = re.compile(r"^\d+(\.\d+)?[smhd]?$")
FORCE_SHORT = re.compile(r"^-[a-zA-Z]*f[a-zA-Z]*$")


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


def segments(command: str) -> list[list[str]]:
    """The command's separate invocations, split quote-aware.

    Splitting on `&&`/`|`/`;` with `str.split` would reintroduce the same class
    of bug from the other side, because a separator inside a quoted argument is
    not a separator. `shlex` with `punctuation_chars` answers that correctly.

    On unbalanced quotes the whole command comes back as ONE segment rather than
    nothing, so a malformed command is still judged instead of waved through.
    """
    try:
        lex = shlex.shlex(command, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        out: list[list[str]] = []
        current: list[str] = []
        for tok in lex:
            if tok and not set(tok) - set("&|;()<>"):
                if current:
                    out.append(current)
                    current = []
                continue
            current.append(tok)
        if current:
            out.append(current)
        return out or [tokens(command)]
    except ValueError:
        return [tokens(command)]


def resolved_argv(argv: list[str]) -> list[str]:
    """The segment's argv from its ACTUAL command onward.

    Skips `VAR=value` prefixes and wrappers that take a command as their
    argument, so `PYTHONHASHSEED=0 timeout 130 git add -A` resolves to
    `['git', 'add', '-A']`. The command is returned as a bare basename, so
    `/usr/bin/git` and `git` answer alike.
    """
    i = 0
    while i < len(argv):
        tok = argv[i]
        if ASSIGNMENT.match(tok):
            i += 1
            continue
        base = tok.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        if base in COMMAND_WRAPPERS:
            i += 1
            while i < len(argv) and (argv[i].startswith("-") or DURATION.match(argv[i])):
                i += 1
            continue
        return [base] + argv[i + 1:]
    return []


def real_command(argv: list[str]) -> str:
    """The segment's actual command, or '' when it has none."""
    resolved = resolved_argv(argv)
    return resolved[0] if resolved else ""


def git_subcommand(argv: list[str]) -> tuple[str, list[str]]:
    """``(subcommand, its arguments)`` for a git segment, ``('', [])`` otherwise.

    R350 round two. The git rules used to regex the segment TEXT, which reads a
    banned literal inside a quoted argument as the banned act: the commit that
    shipped this change was itself denied, because its message documents
    `git add -A` while explaining the rule. That is the same defect as the
    read-only `grep`, one level down, and rewording the message would have left
    it in place for the next person to describe a rule.

    Answering from argv instead is exact. It is only safe because
    ``resolved_argv`` already walks past wrappers -- an ``argv[0] == 'git'``
    test alone would let ``timeout 130 git add -A`` through, which is why the
    first cut kept the regexes.
    """
    rest = resolved_argv(argv)
    if not rest or rest[0] != "git":
        return "", []
    i = 1
    while i < len(rest):                 # git's own options, before the subcommand
        if rest[i] in ("-C", "-c", "--git-dir", "--work-tree", "--namespace") and i + 1 < len(rest):
            i += 2
            continue
        if rest[i].startswith("-"):
            i += 1
            continue
        return rest[i], rest[i + 1:]
    return "", []


def forced_push(argv: list[str]) -> bool:
    """Whether this segment's push carries a force flag.

    Token-wise rather than by regex, so `--follow-tags` is not mistaken for
    `--force` and a combined short flag like `-fu` is still caught.
    """
    for tok in argv:
        if tok.startswith("--force"):
            return True
        if FORCE_SHORT.match(tok):
            return True
    return False


def judge(command: str) -> dict | None:
    """The verdict for a whole command, or None to allow it silently.

    Signature is unchanged (R350) so the pinned test's helper and this file's
    own hand-test both still work; what moved inside is that each rule is now
    applied per SEGMENT instead of to the raw string.
    """
    for argv in segments(command):
        if not argv:
            continue
        if real_command(argv) in READ_ONLY_TOOLS:
            continue
        # shlex.join, never " ".join: the rules below re-tokenize their own
        # captures, so a segment rebuilt without quotes changes meaning. Measured
        # -- `git commit -m "R301: lean CLAUDE.md"` rejoined bare becomes
        # `... -m R301: lean CLAUDE.md`, whose re-tokenization finds `CLAUDE.md`
        # sitting loose and reads a commit MESSAGE as a pathspec, so the pathless
        # commit stopped asking. Caught by the pinned test it was meant to keep.
        verdict = judge_segment(shlex.join(argv), argv)
        if verdict is not None:
            return verdict
    return None


def judge_segment(command: str, argv: list[str]) -> dict | None:
    if DRAFTKINGS.search(command):
        return decision("deny", "CLAUDE.md hard wall: DraftKings reads are MANUAL. Never fetch draftkings.com "
                                "by any client; Ben downloads the file and drops it in the repo.")
    sub, args = git_subcommand(argv)
    if sub == "push" and forced_push(args):
        return decision("deny", "A force-push discards commits, and in this tree they may not be yours "
                                "(CLAUDE.md's multi-session contract). An ordinary `git push` is allowed; "
                                "re-run without --force / --force-with-lease / -f.")
    if sub in GIT_BANNED_SUBCOMMANDS:
        return decision("deny", f"CLAUDE.md multi-session contract: no `git {sub}` while any claim you do "
                                f"not own is live. Uncommitted work of another session is the blast radius.")
    if sub == "add":
        for tok in args:
            if tok in ("-A", "--all", "."):
                return decision("deny", "CLAUDE.md: `git add` by explicit path only, never -A, --all, or `.`; "
                                        "another session's dirt is in this tree.")
            if tok.startswith("-A") or tok.startswith("--all="):
                return decision("deny", "CLAUDE.md: `git add` by explicit path only.")
    if sub == "commit":
        verdict = judge_commit(args)
        if verdict is not None:
            return verdict
    if PIP_UNPINNED.search(command):
        return decision("deny", "The unpinned resolve is barred (R7, R42): use `python tools/env_probe.py --install`, "
                                "which installs requirements.lock (`LOCK_NAME` in that file). This message named "
                                "requirements-production.lock until R350 and that was simply wrong -- two locks "
                                "with overlapping names, and the probe installs the OTHER one.")
    return None


# Arguments whose VALUE is the next token and is never a pathspec. `-m` is the
# one that matters: a commit message is not a path, and treating it as one is how
# the pathless-commit prompt goes quiet.
COMMIT_VALUE_FLAGS = frozenset({
    "-m", "-F", "--message", "--file", "--author", "--date", "-C", "-c",
    "--fixup", "--squash",
})
PATHY_SUFFIXES = (".py", ".md", ".json", ".csv", ".txt", ".lock", ".yaml")


def judge_commit(args: list[str]) -> dict | None:
    """`ask` when a `git commit` names no pathspec, else None.

    Lifted out of the old `GIT_COMMIT.finditer` loop unchanged in behaviour; what
    changed is the input. It reads the subcommand's real argv rather than a regex
    capture, so a path-looking token inside a quoted MESSAGE is no longer mistaken
    for a pathspec -- the bug `shlex.join` patched from the other side, now gone
    at the source.
    """
    if any(a in ("--amend", "--allow-empty") for a in args):
        return None
    has_path = "--" in args
    skip = False
    for a in args:
        if skip:                          # the value of -m/-F/etc. is a message
            skip = False
            continue
        if a in COMMIT_VALUE_FLAGS:
            skip = True
            continue
        if a.startswith("-"):
            continue
        if "/" in a or "\\" in a or a.endswith(PATHY_SUFFIXES):
            has_path = True
    if has_path:
        return None
    return decision("ask", "This `git commit` names no paths. A pathless commit sweeps EVERY session's staged "
                           "files (CLAUDE.md). Pass the same explicit paths you gave `git add`, or confirm "
                           "you mean to commit the whole index.")


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
