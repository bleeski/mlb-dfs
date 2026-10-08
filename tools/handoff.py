#!/usr/bin/env python3
"""handoff.py -- what a session does after its dev PR merges (R491).

`/ship` ends at the merge, and a cloud container is reclaimed when the session
ends, so everything that should follow a merge was left to whoever remembered:
stale branches piled up on GitHub and on Ben's disk, "is my disk in sync?" had
no answer a cloud session could give (it cannot see his disk), and the next
chunk of work was a prompt Ben wrote by hand. `/handoff` is the procedure; this
is its three deterministic parts, each a subcommand so a session prints them
rather than composing them from memory.

  branches    classify every branch against origin/main; with --apply delete
              ONLY the class that loses nothing.
  powershell  the copy/paste block that brings Ben's Windows clone level with
              GitHub and proves it.
  prompt      the next-session prompt, from the roadmap's NEXT row: what to do,
              how much effort, how to verify, and the plan-mode / advisor
              protocol Ben asked for (2026-10-08).

WHAT `branches` MAY DELETE. DELETE is one class: the branch tip is an ancestor of
origin/main reached through a merge, so every commit on it is already on main and
nothing is lost. GitHub
already deletes a merged PR's branch (`delete_branch_on_merge`), so on a healthy
repo this class is nearly empty and mostly means Ben's local branches whose
upstream is gone. Everything else is reported, never deleted:

  KEEP-CHECKED-OUT  a branch checked out in this or another worktree.
  KEEP-ON-MAIN      the tip sits on main's own first-parent line: a branch with no
                    commits of its own yet, or a fast-forward merge. A cloud
                    session pushes its branch before its first commit (R359: the
                    pushed branch is the mutex), and that branch is an ancestor of
                    main too, so ancestry alone would delete a live session's
                    branch. A PR merge commit's second parent is never on this line.
  KEEP-CITED        unmerged, and docs/ROADMAP.md, docs/backlog.md or
                    CHANGELOG.md names it by branch or tip sha. Measured
                    2026-10-08: all three stale remote branches were cited, one
                    as the base the next R379 session starts from ("never
                    landed"), one as "merging it is Ben's". An age-based sweep
                    would have deleted unlanded work the roadmap depends on.
  ASK               unmerged and uncited: unique commits exist, so whether they
                    are extraneous is a fact only Ben has. The report prints the
                    delete command AND the one that restores it.

`branches` never runs `git branch -D` on anything it has not just re-verified as
an ancestor of origin/main, which is the whole of what `-d` checks; it uses `-D`
only because `-d` tests the CURRENT branch rather than origin/main, so it
refuses a branch that is merged. It never force-pushes.

Exit codes, matching claim.py and sync_check.py:
  0  nothing waits on Ben
  2  `branches` found an ASK branch
  3  usage or IO error

Usage:
    python tools/handoff.py branches [--fetch] [--apply] [--json]
    python tools/handoff.py powershell --merge-sha <sha> [--repo-path PATH]
    python tools/handoff.py prompt [--session NN] [--merge-sha <sha>] [--note TEXT]
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
import plan_status  # noqa: E402  (split_row, ROW and NEXT: one parser for the roadmap)

BASE_REF = "origin/main"
#: Where the register and the roadmap name a branch. A branch cited here is part
#: of the plan, not litter.
CITED_IN = ("docs/ROADMAP.md", "docs/backlog.md", "CHANGELOG.md")
#: Ben's clone (docs/cowork_sync_protocol.md); overridable with --repo-path.
WINDOWS_REPO = r"C:\Users\benja\Documents\Claude\mlb-dfs"
PROTECTED = frozenset({"main", "HEAD"})

CLASS_ORDER = ("DELETE", "KEEP-CHECKED-OUT", "KEEP-ON-MAIN", "KEEP-CITED", "ASK")


def git(root: Path, *args: str, timeout: int = 60) -> tuple[int, str, str]:
    proc = subprocess.run(["git", *args], cwd=str(root), capture_output=True,
                          text=True, encoding="utf-8", errors="replace",
                          timeout=timeout)
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


# --------------------------------------------------------------------------
# branches
# --------------------------------------------------------------------------

_REF_FORMAT = ("%(refname)%09%(objectname)%09%(upstream:track)%09"
               "%(committerdate:short)%09%(authorname)%09%(subject)")


def is_ancestor(root: Path, sha: str, base: str = BASE_REF) -> bool:
    return git(root, "merge-base", "--is-ancestor", sha, base)[0] == 0


def checked_out_branches(root: Path) -> tuple[dict[str, str], list[str]]:
    """(branch name -> worktree path, every worktree path except this root)."""
    code, out, _ = git(root, "worktree", "list", "--porcelain")
    if code != 0:
        return {}, []
    branches: dict[str, str] = {}
    paths: list[str] = []
    here = str(root.resolve()).replace("\\", "/").lower()
    path = ""
    for line in out.splitlines():
        if line.startswith("worktree "):
            path = line[len("worktree "):]
            if path.replace("\\", "/").lower() != here:
                paths.append(path)
        elif line.startswith("branch refs/heads/"):
            branches[line[len("branch refs/heads/"):]] = path
    return branches, paths


def citations(root: Path, name: str, sha: str, base: str = BASE_REF) -> list[str]:
    """Which of CITED_IN name this branch or its tip sha, read from `base`."""
    code, out, _ = git(root, "grep", "-l", "-F", "-e", name, "-e", sha[:7],
                       base, "--", *CITED_IN)
    if code != 0:
        return []
    return sorted(line.split(":", 1)[1] for line in out.splitlines() if ":" in line)


def unique_paths(root: Path, sha: str, base: str = BASE_REF) -> tuple[int, int] | None:
    """(paths the branch changed that still differ from base, paths it changed).

    Informational. It can prove a branch is NOT redundant, never that it is: a
    path main also edited differs without the branch's change being lost.
    """
    code, merge_base, _ = git(root, "merge-base", base, sha)
    if code != 0 or not merge_base:
        return None
    own = set(git(root, "diff", "--name-only", merge_base, sha)[1].splitlines())
    drift = set(git(root, "diff", "--name-only", base, sha)[1].splitlines())
    return len(own & drift), len(own)


def classify(row: dict) -> str:
    """The class for one branch row. Pure, so it is testable without a repo."""
    if row["checked_out"]:
        return "KEEP-CHECKED-OUT"
    if row["merged"]:
        return "KEEP-ON-MAIN" if row.get("on_main_line") else "DELETE"
    if row["cited_in"]:
        return "KEEP-CITED"
    return "ASK"


def collect_branches(root: Path = REPO, base: str = BASE_REF) -> dict:
    code, out, err = git(root, "for-each-ref", f"--format={_REF_FORMAT}",
                         "refs/heads", "refs/remotes/origin")
    if code != 0:
        raise OSError(f"git for-each-ref failed: {err.splitlines()[0] if err else code}")
    in_use, other_worktrees = checked_out_branches(root)
    # One call each, not one per branch. A failed call leaves the set empty, which
    # reads every branch as unmerged: the safe direction.
    merged_refs = set(git(root, "for-each-ref", "--merged", base,
                          "--format=%(refname)")[1].splitlines())
    main_line = set(git(root, "rev-list", "--first-parent", base)[1].split())
    rows: list[dict] = []
    for line in out.splitlines():
        ref, sha, track, date, author, subject = (line.split("\t", 5) + [""] * 6)[:6]
        if ref.startswith("refs/heads/"):
            where, name = "local", ref[len("refs/heads/"):]
        elif ref.startswith("refs/remotes/origin/"):
            where, name = "remote", ref[len("refs/remotes/origin/"):]
        else:
            continue
        if name in PROTECTED:
            continue
        merged = ref in merged_refs
        behind = ahead = None
        code, counts, _ = git(root, "rev-list", "--left-right", "--count",
                              f"{base}...{sha}")
        if code == 0 and len(counts.split()) == 2:
            behind, ahead = (int(x) for x in counts.split())
        row = {
            "where": where, "name": name, "sha": sha, "date": date,
            "author": author, "subject": subject,
            "upstream_gone": track == "[gone]",
            "merged": merged, "on_main_line": merged and sha in main_line,
            "ahead": ahead, "behind": behind,
            "checked_out": where == "local" and name in in_use,
            "cited_in": [] if merged else citations(root, name, sha, base),
            "unique_paths": None if merged else unique_paths(root, sha, base),
        }
        row["class"] = classify(row)
        rows.append(row)
    rows.sort(key=lambda r: (CLASS_ORDER.index(r["class"]), r["where"], r["name"]))
    return {"base": base, "rows": rows, "other_worktrees": other_worktrees}


def apply_deletions(root: Path, rows: list[dict], base: str = BASE_REF) -> list[str]:
    """Delete the DELETE class, re-verifying each tip against base first."""
    log: list[str] = []
    for row in rows:
        if row["class"] != "DELETE":
            continue
        label = f"{row['where']} {row['name']} ({row['sha'][:7]})"
        if not is_ancestor(root, row["sha"], base):
            log.append(f"skipped  {label}: no longer an ancestor of {base}")
            continue
        if row["where"] == "local":
            code, tip, _ = git(root, "rev-parse", "--verify", "-q",
                               f"refs/heads/{row['name']}")
            if code != 0 or tip != row["sha"]:
                log.append(f"skipped  {label}: the branch moved or is gone since the report")
                continue
            code, _, err = git(root, "branch", "-D", row["name"])
            log.append(f"deleted  {label}" if code == 0 else
                       f"refused  {label}: {err.splitlines()[0] if err else code}")
            continue
        code, out, _ = git(root, "ls-remote", "--heads", "origin", row["name"])
        tip = next((ln.split()[0] for ln in out.splitlines()
                    if ln.split()[1:] == [f"refs/heads/{row['name']}"]), None)
        if code != 0 or tip is None:
            log.append(f"skipped  {label}: not readable on origin (already gone?)")
        elif tip != row["sha"]:
            log.append(f"skipped  {label}: origin's tip moved to {tip[:7]} since the fetch")
        else:
            code, _, _ = git(root, "push", "origin", "--delete", row["name"], timeout=120)
            log.append(f"deleted  {label}" if code == 0 else
                       f"refused  {label}: the push was rejected (rc {code})")
    return log


def render_branches(report: dict) -> list[str]:
    rows = report["rows"]
    lines: list[str] = []
    for row in rows:
        lines.append(f"{row['class']:<17} {row['where']:<6} {row['name']}")
        detail = f"last commit {row['date']} by {row['author']}"
        if row["ahead"] is not None:
            detail = (f"{row['ahead']} ahead, {row['behind']} behind {report['base']}; "
                      + detail)
        lines.append(f"{'':<25}{detail}")
        if row["upstream_gone"]:
            lines.append(f"{'':<25}its upstream is gone")
        if row["unique_paths"]:
            n, total = row["unique_paths"]
            lines.append(f"{'':<25}{n} of {total} changed paths still differ from main")
        if row["class"] == "KEEP-ON-MAIN":
            lines.append(f"{'':<25}tip is on main's own line (no commits of its own, or a "
                         "fast-forward merge); left in case a session just took it")
        if row["class"] == "KEEP-CITED":
            lines.append(f"{'':<25}do not delete; named in {', '.join(row['cited_in'])}")
        if row["class"] == "ASK":
            if row["where"] == "remote":
                drop = f"git push origin --delete {row['name']}"
                back = f"git push origin {row['sha']}:refs/heads/{row['name']}"
            else:
                drop = f"git branch -D {row['name']}"
                back = f"git branch {row['name']} {row['sha']}"
            lines.append(f"{'':<25}Ben's call. delete: {drop}   restore: {back}")
    counts = {c: sum(1 for r in rows if r["class"] == c) for c in CLASS_ORDER}
    lines.append("branches: " + ", ".join(f"{n} {c}" for c, n in counts.items()))
    if report["other_worktrees"]:
        lines.append("other worktrees, never touched: "
                     + "; ".join(report["other_worktrees"]))
    return lines


# --------------------------------------------------------------------------
# powershell
# --------------------------------------------------------------------------

_SHA = re.compile(r"^[0-9a-f]{4,40}$")


def powershell_block(merge_sha: str, repo_path: str = WINDOWS_REPO) -> str:
    """The block that levels Ben's clone with GitHub, and says whether it did.

    Self-contained on purpose: Ben's checkout is the thing that is behind, so
    nothing here may need a file from the repo. It refuses a dirty tree rather
    than working around one, only fast-forwards, and deletes with `-d`, which git
    refuses for anything unmerged.
    """
    sha = merge_sha.strip().lower()
    if not _SHA.match(sha):
        raise ValueError(f"not a commit sha: {merge_sha!r}")
    path = repo_path.replace("'", "''")
    return "\n".join([
        f"$repo = '{path}'",
        "if (-not (Test-Path -LiteralPath (Join-Path $repo '.git'))) {",
        "  Write-Host \"STOP: no git folder at $repo, so nothing was run\"",
        "} else {",
        "  Set-Location -LiteralPath $repo",
        "  git fetch --prune origin",
        "  if ($LASTEXITCODE -ne 0) {",
        "    Write-Host 'STOP: the fetch failed, so nothing was changed'",
        "  } elseif (git status --porcelain --untracked-files=no) {",
        "    Write-Host 'STOP: uncommitted changes to tracked files, so nothing was changed. Commit or set them aside.'",
        "    git status -sb",
        "  } else {",
        "    if ((git branch --show-current) -ne 'main') { git switch main }",
        "    git merge --ff-only origin/main",
        "    git for-each-ref --format='%(refname:short) %(upstream:track)' refs/heads | ForEach-Object {",
        "      $n, $t = $_ -split ' ', 2",
        "      if ($t -eq '[gone]') { git branch -d $n }",
        "    }",
        f"    git merge-base --is-ancestor {sha} main",
        "    $holds = ($LASTEXITCODE -eq 0)",
        "    $level = ((git rev-parse main) -eq (git rev-parse origin/main))",
        "    git status -sb",
        "    git branch -vv",
        f"    if ($holds -and $level) {{ Write-Host 'IN SYNC: main equals origin/main and holds {sha}' }}"
        f" else {{ Write-Host 'NOT IN SYNC: read the lines above' }}",
        "  }",
        "}",
    ])


# --------------------------------------------------------------------------
# prompt
# --------------------------------------------------------------------------

_KEY_LINE = re.compile(r"^\s*-\s+`([A-Z][A-Z0-9]{0,5})`\s*=\s*`([^`]+)`", re.M)
_CORE = re.compile(r"optimizer_v3|contest_allocator|execution_pipeline")
_EFFORT_RANK = {"XS": 0, "S": 1, "M": 2, "L": 3, "XL": 4}
_LEVEL_FOR_RANK = ("medium", "medium", "high", "xhigh", "xhigh")
_LEVELS = ("low", "medium", "high", "xhigh", "max")


def path_keys(roadmap: str) -> dict[str, str]:
    return dict(_KEY_LINE.findall(roadmap))


def expand_keys(cell: str, keys: dict[str, str]) -> str:
    return re.sub(r"`([A-Z][A-Z0-9]{0,5})`",
                  lambda m: f"`{keys[m.group(1)]}` ({m.group(1)})" if m.group(1) in keys
                  else m.group(0), cell)


def reasoning_level(effort: str | None, packaging: str, files: str) -> tuple[str, str]:
    """(level, why). A floor of `high` for Standalone rows and the three
    solver-core files, mirroring dev-session section 2's plan-mode trigger."""
    level, why = "high", "the row states no size"
    if effort:
        ranks = [_EFFORT_RANK[t] for t in effort.upper().split("-") if t in _EFFORT_RANK]
        if ranks:
            level, why = _LEVEL_FOR_RANK[max(ranks)], f"effort {effort}"
    floor = []
    if packaging.strip() == "Standalone":
        floor.append("a Standalone row, high blast radius")
    if _CORE.search(files):
        floor.append("it touches the optimizer, allocator or execution pipeline")
    if floor and _LEVELS.index(level) < _LEVELS.index("high"):
        level, why = "high", why + "; raised because " + " and ".join(floor)
    elif floor:
        why += "; " + " and ".join(floor)
    return level, why


def next_session(roadmap: str) -> str | None:
    for line in roadmap.splitlines():
        m = plan_status.NEXT.match(line)
        if m:
            return m.group(1)
    return None


def session_cells(roadmap: str, session: str) -> list[str] | None:
    for line in roadmap.splitlines():
        m = plan_status.ROW.match(line)
        if m and m.group(1) == session:
            cells = plan_status.split_row(line)
            return cells if len(cells) == 8 else None
    return None


def fence(body: str) -> str:
    longest = max((len(m) for m in re.findall(r"`+", body)), default=0)
    mark = "`" * max(3, longest + 1)
    return f"{mark}text\n{body}\n{mark}"


def build_prompt(roadmap: str, session: str | None = None, *, base: str = "",
                 merged: str = "", notes: list[str] | None = None) -> dict:
    """The next-session prompt for `session` (default: the NEXT row).

    Three things are answered from the row itself, because that is where the
    roadmap already keeps them: WHAT is the Work Unit cell, EFFORT is its rank
    line, VERIFY is its Verification cell. Nothing here is composed from memory,
    so a row that is thin produces a thin prompt that SAYS it is thin.
    """
    session = session or next_session(roadmap)
    if session is None:
        raise ValueError("the roadmap has no **NEXT:** line")
    cells = session_cells(roadmap, session)
    if cells is None:
        raise ValueError(f"Session {session} is not a well-formed row of the roadmap")
    _, packaging, scope, source, gate_class, files, verify, status = cells
    keys = path_keys(roadmap)
    parts = [p.strip() for p in scope.split("<br>")]
    title = parts[0].rstrip(".")
    sizing = next((p for p in parts if p.startswith("**Rank")), "")
    needs = next((p for p in parts if p.startswith("Needs")), "")
    body = [p for p in parts[1:] if p and p != needs and not p.startswith("**Rank")]
    effort = re.search(r"effort ([A-Z]{1,2}(?:-[A-Z]{1,2})?)\b", sizing)
    effort = effort.group(1) if effort else None
    breakpoint_ = re.search(r"breakpoint: (.*?)(?:\. Why here:|\.?$)", sizing)
    sizing_line = re.sub(r"\*\*|\s*Why here:.*$", "", sizing).strip()
    files_text = expand_keys(files, keys)
    level, level_why = reasoning_level(effort, packaging, files_text)
    needs_ben = sorted(set(re.findall(r"\bD-\d+\b", needs)))
    warnings: list[str] = []
    if not re.match(r"^(Pending|In Progress)$", status):
        warnings.append(f"Session {session} is {status!r}, not open work")
    if needs_ben:
        warnings.append("Session %s needs a decision from Ben: %s" % (session, ", ".join(needs_ben)))
    if not sizing:
        warnings.append(f"Session {session} states no rank line, so the effort section is a default")
    if not verify:
        warnings.append(f"Session {session} states no verification command")

    headline = title if len(title) <= 110 else title[:107].rstrip() + "..."
    out = [f"/plan Session {session}: {headline}", ""]
    out.append("You are DEV on the mlb-dfs engine. Start in plan mode and stay there: no edits, "
               "no engine claim and no gate run until I approve the plan. If /plan did not "
               "switch modes, treat this session as read-only until I say go.")
    if base:
        out.append(f"Base: {base}. Run `git fetch origin` first; "
                   + (f"{merged}. " if merged else "")
                   + "CLAUDE.md is the contract and /dev-session is the procedure.")
    out += ["", "## 1. What to do",
            f"docs/ROADMAP.md row Session {session} ({packaging}; {gate_class}; source: {source}).",
            f"{title}."]
    out += body
    if needs:
        out.append(needs)
    if needs_ben:
        out.append(f"That is a decision only I can make ({', '.join(needs_ben)}, in the roadmap's "
                   "'Decide these first'): ask me for it before planning around it.")
    out.append(f"Files: {files_text}.")
    out.append("Check each premise against the tree before planning on it, and reproduce before "
               "fixing: the filed diagnosis has been wrong about the mechanism more often than "
               "right (.claude/rules/engine.md).")
    for note in notes or []:
        out.append(f"Carry-over from the last session: {note}")
    out += ["", "## 2. How much effort",
            (sizing_line or "The row states no size.") ,
            f"Reasoning effort: {level} ({level_why}). Set the session's effort control to match "
            "if you want it enforced; this line is guidance, not a setting.",
            "If the context window runs hot, stop at the "
            + (f"row's breakpoint ({breakpoint_.group(1)})" if breakpoint_ and breakpoint_.group(1)
               else "row's named breakpoint")
            + ": land that part with /land and /ship and say what remains, rather than "
            "half-landing all of it.",
            "Stop only for a fact only I have (CLAUDE.md, Autonomy); otherwise keep going and "
            "put the status note in the same message as the next action.",
            "", "## 3. How to verify",
            f"- The row's verification, verbatim (UT, GOLD, PROBE, LINT and GATE are defined under "
            f"'Commands' in docs/ROADMAP.md): {verify or 'NONE STATED: say so in the plan and propose one'}",
            "- `python tools/plan_status.py --check` exits 0, and `python tools/audit.py --run-tests "
            "--terse` prints `PASS  <version>  <N> modules  <N> tests` with nothing appended "
            "(docs/hosts.md has its time on this host; the PR's `gate` check is the merge authority "
            "wherever the local gate is red for host reasons).",
            "- Every new test is mutation-checked: revert the fix, expect red, restore.",
            "- Merge only on a green `gate`, then run /handoff.",
            "- End with: what is blocked on me, what changed (PR or merge sha and the gate line), "
            "then what you found and filed.",
            "", "## Advisor",
            "1. Before you present the plan: draft it (what is wrong, verified against the tree; "
            "the files; the tests; the gate line and golden histogram you expect), call the "
            "advisor (/advisor) on the draft, fold its answer in or say why you disagree, and "
            "only then present it with ExitPlanMode.",
            "2. After I approve it: call the advisor again before the first edit if the approach "
            "is not settled, whenever you are stuck or a result does not fit, and once more "
            "before you declare done (commit the work first so it survives the call)."]
    return {"session": session, "prompt": "\n".join(out), "reasoning_effort": level,
            "needs_ben": needs_ben, "warnings": warnings}


def read_roadmap(root: Path, ref: str) -> tuple[str, str]:
    code, out, _ = git(root, "show", f"{ref}:docs/ROADMAP.md")
    if code == 0:
        return out, ref
    return (root / "docs" / "ROADMAP.md").read_text(encoding="utf-8"), "the working tree"


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass
    ap = argparse.ArgumentParser(description="the close-out after a dev PR merges")
    ap.add_argument("--root", type=Path, default=REPO, help=argparse.SUPPRESS)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("branches", help="classify branches; --apply deletes only the merged class")
    b.add_argument("--fetch", action="store_true", help="git fetch --prune origin first")
    b.add_argument("--apply", action="store_true", help="delete the DELETE class")
    b.add_argument("--json", action="store_true", dest="as_json")
    p = sub.add_parser("powershell", help="the block that levels Ben's clone with GitHub")
    p.add_argument("--merge-sha", required=True)
    p.add_argument("--repo-path", default=WINDOWS_REPO)
    q = sub.add_parser("prompt", help="the next-session prompt")
    q.add_argument("--session", help="Session NN; default the roadmap's NEXT row")
    q.add_argument("--merge-sha", default="", help="the PR merge just landed")
    q.add_argument("--note", action="append", default=[], help="a carry-over line; repeatable")
    q.add_argument("--ref", default=BASE_REF, help="read the roadmap from this ref")
    args = ap.parse_args(argv)
    root = args.root
    try:
        if args.cmd == "powershell":
            print(powershell_block(args.merge_sha, args.repo_path))
            return 0
        if args.cmd == "branches":
            if args.fetch and git(root, "fetch", "--prune", "origin", timeout=120)[0] != 0:
                print("ERROR  git fetch failed; classification would read stale refs",
                      file=sys.stderr)
                return 3
            report = collect_branches(root)
            log = apply_deletions(root, report["rows"]) if args.apply else []
            if args.as_json:
                print(json.dumps({**report, "applied": log}, indent=1, sort_keys=True))
            else:
                print("\n".join(render_branches(report)))
                print("\n".join(log))
            return 2 if any(r["class"] == "ASK" for r in report["rows"]) else 0
        roadmap, label = read_roadmap(root, args.ref)
        sha = git(root, "rev-parse", "--short", args.ref)[1] if label == args.ref else ""
        merged = ""
        if args.merge_sha:
            holds = is_ancestor(root, args.merge_sha, args.ref)
            merged = (f"merge {args.merge_sha[:7]} is on it" if holds else
                      f"merge {args.merge_sha[:7]} is NOT on it yet, so fetch before trusting this prompt")
        result = build_prompt(
            roadmap, args.session.replace("Session", "").strip() if args.session else None,
            base=f"{label} @ {sha}" if sha else f"{label} (no {args.ref} here)",
            merged=merged, notes=args.note)
        if label != args.ref:
            result["warnings"].append(
                f"{args.ref} is unreadable here, so NEXT came from the working tree, "
                "which may be stale: fetch and rerun")
        for warning in result["warnings"]:
            print(f"WARNING  {warning}", file=sys.stderr)
        print(fence(result["prompt"]))
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"ERROR  {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
