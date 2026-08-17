#!/usr/bin/env python3
"""sync_check.py -- the three-way sync state as one command (R102).

Three locations, two filesystems. Ben's Windows folder and the Cowork mount
are the SAME files and cannot drift; the cloud container is separate, empty at
session start and discarded at session end. GitHub is the only thing all three
can agree on, so it is the reference point this tool measures against.

What each caller can actually see:

  on the mount     no network, and the repo has never fetched. `origin/main` is
                   a remote-tracking ref that only moves when Ben pushes from
                   Windows, so comparing it to `main` answers "does my disk
                   carry commits GitHub does not", and nothing else. It cannot
                   answer "has GitHub moved ahead of me".
  in the container GH_PAT (or GH_TOKEN) reaches the private repo, so
                   `git ls-remote` gives GitHub's TRUE head and both questions
                   are answerable.

Ambiguity is reported as ambiguity. A tool that prints "in sync" when it only
checked a stale local ref is worse than one that says it could not tell.

The mount lies about modification times, so `git status --porcelain` lists
files as ` M` whose content is identical to HEAD (see the stat-dirt note in
CLAUDE.md's multi-session contract). Every path this tool calls dirty is
confirmed against `git diff HEAD --name-only`, which compares content. Stat
noise is counted and named, never reported as drift.

Exit codes, matching claim.py and preflight:
  0  in sync, or the only difference is stat noise
  2  drift: unpushed commits, real uncommitted content, or remote ahead
  3  usage or IO error

Usage:
    python tools/sync_check.py
    python tools/sync_check.py --json
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

TOKEN_ENV_VARS = ("GH_PAT", "GH_TOKEN", "GITHUB_TOKEN")

# A token shorter than this is a placeholder, not a credential. The container
# ships GH_TOKEN/GITHUB_TOKEN set to 14-character stubs, and treating those as
# real produces an auth failure that reads like a network problem.
MIN_TOKEN_LEN = 20


def _git(root: Path, *args: str, timeout: int = 60) -> tuple[int, str]:
    proc = subprocess.run(["git", *args], cwd=str(root), capture_output=True,
                          text=True, timeout=timeout)
    return proc.returncode, proc.stdout.strip()


def _read_ref(root: Path, relpath: str) -> str | None:
    """Read a ref from the filesystem rather than via git.

    Deliberate: reading .git/refs directly takes no index.lock, and on this
    mount git cannot unlink the lock it leaves, so every avoided git call is
    one less lock to clean up.
    """
    direct = Path(root) / ".git" / relpath
    try:
        value = direct.read_text(encoding="utf-8").strip()
        return value or None
    except OSError:
        pass
    packed = Path(root) / ".git" / "packed-refs"
    try:
        for line in packed.read_text(encoding="utf-8").splitlines():
            if line.startswith("#") or not line.strip():
                continue
            parts = line.split()
            if len(parts) == 2 and parts[1] == relpath:
                return parts[0]
    except OSError:
        pass
    return None


def find_token(environ=None) -> tuple[str | None, str | None]:
    """Return (env var name, token) for the first real-looking credential.

    Never returns the value to a caller that prints; callers use the NAME.
    """
    env = os.environ if environ is None else environ
    for name in TOKEN_ENV_VARS:
        value = env.get(name) or ""
        if len(value) >= MIN_TOKEN_LEN:
            return name, value
    # R146. The environment is not the only place a secret lives here. A
    # fine-grained PAT sat in REPO/.env under GH_PAT from before 2026-08-17
    # while this function read os.environ alone, so every run reported "no
    # usable token" and GitHub's head went unmeasured against a credential
    # that was present and valid. Same shape as THE_ODDS_API_KEY, which
    # repo_env already resolves from .env for exactly this reason; an explicit
    # `environ` still wins, so a caller can override.
    if environ is None:
        # Run as `python tools/sync_check.py`, sys.path[0] is tools/ and the
        # repo root is absent, so the import fails and the fallback silently
        # no-ops in the exact invocation the docstring documents. Put REPO on
        # the path first. Found by running the script rather than the function.
        if str(REPO) not in sys.path:
            sys.path.insert(0, str(REPO))
        try:
            from mlb_engine.repo_env import resolve_secret
        except ImportError:
            return None, None
        for name in TOKEN_ENV_VARS:
            value = resolve_secret(name) or ""
            if len(value) >= MIN_TOKEN_LEN:
                return name, value
    return None, None


# R147, 2026-08-17: a git remote call that fails is not evidence of a bad
# credential. Both this tool and tools/audit.py hard-coded "check the token
# scope" for ANY non-zero return, so a cloud Cowork session's device VM -- which
# has no outbound network at all, and whose proxy answers CONNECT with 403 even
# for a public repo needing no credential -- reported a working fine-grained PAT
# as the problem. The remedy that message names is regenerating a token that was
# never broken.
#
# git's stderr can echo the remote URL, so it is classified here and never
# surfaced. The return value is one of three fixed strings.
GIT_FAIL_NETWORK = "no network reachable from this environment"
GIT_FAIL_CREDENTIAL = "credential rejected: check the token scope or expiry"
GIT_FAIL_UNKNOWN = "git refused and the reason did not classify"

# The two lists are kept DISJOINT in what they can match, which is the property
# that matters; testing network first is only a backstop for the day one of them
# grows a marker the other already covers. What actually keeps them disjoint is
# the exclusion noted below: a proxy refusing CONNECT reports "Received HTTP code
# 403 from proxy after CONNECT" and a scope failure reports "The requested URL
# returned error: 403", so both carry a 403 and only the tail separates them.
# Every marker is matched against a lowercased stderr.
_GIT_NETWORK_MARKERS = (
    "could not resolve host",
    "temporary failure in name resolution",
    "network is unreachable",
    "no route to host",
    "connection refused",
    "connection timed out",
    "operation timed out",
    "failed to connect to",
    "from proxy",
    "after connect",
    "proxy connect",
    "ssl",
    "gnutls",
)
# Deliberately NOT a network marker, and this is the one that nearly shipped:
# "unable to access" is git's generic prefix for BOTH failures. Adding it here
# would classify every credential failure as a network failure and re-open this
# defect pointing the other way, which is why the two sample messages in
# tests.test_core.GitFreshnessTests share that prefix on purpose.
_GIT_CREDENTIAL_MARKERS = (
    "authentication failed",
    "invalid username or password",
    "could not read username",
    "could not read password",
    "terminal prompts disabled",
    "repository not found",
    "permission denied",
    "403 forbidden",
    "401 unauthorized",
    "returned error: 401",
    "returned error: 403",
    "access denied",
    "support for password authentication was removed",
)


def classify_git_failure(stderr: str) -> str:
    """Name what stopped a git remote call, without echoing git's own stream.

    Three buckets, because three different things are owed: reach the network,
    fix the credential, or look at it by hand. An empty or unrecognized stderr
    classifies as unknown rather than as either of the other two, since naming
    the wrong cause is the defect this function exists to close.
    """
    text = str(stderr or "").lower()
    if any(marker in text for marker in _GIT_NETWORK_MARKERS):
        return GIT_FAIL_NETWORK
    if any(marker in text for marker in _GIT_CREDENTIAL_MARKERS):
        return GIT_FAIL_CREDENTIAL
    return GIT_FAIL_UNKNOWN


def classify_dirt(porcelain: str, changed_names: str) -> dict:
    """Split `git status --porcelain` into real content changes and stat noise.

    `changed_names` is `git diff HEAD --name-only`: content, not mtime, and it
    is the AUTHORITY here. porcelain is consulted for two things only, the
    untracked list and which paths are mtime-only noise.

    The direction matters and the first cut had it backwards. Deriving
    modifications from porcelain and subtracting the diff means a path the
    mount's porcelain misses is reported by neither bucket, so it vanishes:
    observed 2026-08-10, seconds after a write-back, when this mount served a
    stale stat for a CHANGELOG.md that `git diff HEAD` scored at +51 lines. A
    sync tool that under-reports drift is worse than no tool, so content wins
    and porcelain only ever ADDS context.
    """
    real = {line.strip() for line in changed_names.splitlines() if line.strip()}
    tracked_dirty: list[str] = []
    untracked: list[str] = []
    for line in porcelain.splitlines():
        if len(line) < 4:
            continue
        code, path = line[:2], line[3:].strip().strip('"')
        if " -> " in path:
            path = path.split(" -> ", 1)[1].strip().strip('"')
        path = path.replace("\\", "/")
        if code == "??":
            untracked.append(path)
        else:
            tracked_dirty.append(path)
    return {
        "real_modified": sorted(real),
        "stat_noise": sorted(p for p in tracked_dirty if p not in real),
        "untracked": sorted(untracked),
    }


def collect(root: Path = REPO, environ=None, probe_remote: bool = True) -> dict:
    """Gather the full state. Pure enough to test: git and env are the only IO."""
    state: dict = {"repo": str(root), "errors": []}

    state["local_head"] = _read_ref(root, "refs/heads/main")
    state["origin_ref"] = _read_ref(root, "refs/remotes/origin/main")
    state["ever_fetched"] = (Path(root) / ".git" / "FETCH_HEAD").exists()

    code, porcelain = _git(root, "status", "--porcelain")
    if code != 0:
        state["errors"].append("git status failed")
        porcelain = ""
    code, names = _git(root, "diff", "HEAD", "--name-only")
    if code != 0:
        state["errors"].append("git diff HEAD failed")
        names = ""
    state["dirt"] = classify_dirt(porcelain, names)

    ahead = behind = None
    if state["local_head"] and state["origin_ref"]:
        code, out = _git(root, "rev-list", "--left-right", "--count",
                         "refs/heads/main...refs/remotes/origin/main")
        if code == 0 and len(out.split()) == 2:
            ahead, behind = (int(x) for x in out.split())
    state["ahead_of_origin_ref"] = ahead
    state["behind_origin_ref"] = behind

    token_name, token = find_token(environ)
    state["token_env_var"] = token_name
    state["remote_head"] = None
    state["remote_reachable"] = False
    if probe_remote and token:
        code, url = _git(root, "config", "--get", "remote.origin.url")
        if code == 0 and url:
            askpass = Path(root) / ".git" / "sync_check_askpass"
            try:
                askpass.write_text(
                    '#!/bin/sh\ncase "$1" in *[Uu]sername*) echo '
                    'x-access-token;; *) echo "$SYNC_CHECK_TOKEN";; esac\n',
                    encoding="utf-8")
                askpass.chmod(0o700)
                env = dict(os.environ)
                env.update({"SYNC_CHECK_TOKEN": token,
                            "GIT_ASKPASS": str(askpass),
                            "GIT_TERMINAL_PROMPT": "0"})
                proc = subprocess.run(
                    ["git", "ls-remote", url, "refs/heads/main"],
                    cwd=str(root), capture_output=True, text=True,
                    timeout=60, env=env)
                if proc.returncode == 0 and proc.stdout.split():
                    state["remote_head"] = proc.stdout.split()[0]
                    state["remote_reachable"] = True
                else:
                    # R147: say which of the three it is. Never echo proc.stderr
                    # itself; it can carry the remote URL.
                    state["errors"].append(
                        "ls-remote failed: " + classify_git_failure(proc.stderr))
            except (OSError, subprocess.SubprocessError):
                state["errors"].append("ls-remote could not run")
    return state


def verdict(state: dict) -> tuple[int, list[str]]:
    """Turn the state into an exit code and the lines a human should read."""
    lines: list[str] = []
    drift = False

    head = (state.get("local_head") or "?")[:7]
    ref = (state.get("origin_ref") or "?")[:7]
    lines.append(f"disk      main {head}")

    remote = state.get("remote_head")
    if state.get("remote_reachable") and remote:
        lines.append(f"GitHub    main {remote[:7]}  (measured via {state['token_env_var']})")
        if remote != state.get("local_head"):
            drift = True
            ahead = state.get("ahead_of_origin_ref")
            if ahead:
                lines.append(f"DRIFT     disk is {ahead} commit(s) ahead of GitHub; push from Windows")
            else:
                lines.append("DRIFT     disk and GitHub differ; fetch from Windows before writing")
        else:
            lines.append("ok        disk and GitHub agree")
    else:
        lines.append(f"GitHub    unmeasured; local origin/main ref says {ref}")
        if not state.get("token_env_var"):
            lines.append("          no usable token in GH_PAT/GH_TOKEN/GITHUB_TOKEN, "
                         "so GitHub's true head was not read")
        if not state.get("ever_fetched"):
            lines.append("          this repo has never fetched, so origin/main only "
                         "moves when Ben pushes; it cannot show GitHub moving ahead")
        ahead = state.get("ahead_of_origin_ref")
        if ahead:
            drift = True
            lines.append(f"DRIFT     {ahead} commit(s) on disk are not on GitHub; push from Windows")

    dirt = state.get("dirt") or {}
    real, noise = dirt.get("real_modified", []), dirt.get("stat_noise", [])
    if real:
        drift = True
        lines.append(f"DRIFT     {len(real)} file(s) with uncommitted content:")
        lines.extend(f"            {p}" for p in real[:12])
        if len(real) > 12:
            lines.append(f"            ... and {len(real) - 12} more")
    else:
        lines.append("ok        no uncommitted content")
    if noise:
        lines.append(f"note      {len(noise)} path(s) are mount stat noise, not changes; "
                     f"git status lists them, git diff HEAD does not")
    if dirt.get("untracked"):
        lines.append(f"note      {len(dirt['untracked'])} untracked path(s); "
                     f"not drift on their own")

    for err in state.get("errors", []):
        lines.append(f"ERROR     {err}")
    return (2 if drift else 0), lines


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="report the three-way sync state")
    ap.add_argument("--root", type=Path, default=REPO, help=argparse.SUPPRESS)
    ap.add_argument("--json", action="store_true", dest="as_json",
                    help="emit the raw state; the token VALUE is never included")
    ap.add_argument("--no-remote", action="store_true",
                    help="skip the GitHub probe even when a token is present")
    args = ap.parse_args(argv)
    try:
        state = collect(args.root, probe_remote=not args.no_remote)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"ERROR  {exc}", file=sys.stderr)
        return 3
    code, lines = verdict(state)
    if args.as_json:
        print(json.dumps(state, indent=1, sort_keys=True))
        return code
    for line in lines:
        print(line)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
