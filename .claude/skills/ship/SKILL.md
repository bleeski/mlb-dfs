---
name: ship
description: Take a landed mlb-dfs commit the rest of the way: branch, push, open the PR, drive the gate check to green, merge, report the sha. Run it after /land, or when Ben asks to ship, push, open a PR, or get a change merged.
disable-model-invocation: true
---

# Ship a landed change

`/land` ends with a commit on a branch. This is everything after it. R353,
2026-09-17: before this, sessions stopped at the commit and Ben pushed, which
does not work when the session is a cloud container that will be reclaimed and
Ben is on a phone.

Every step prints evidence. Show the output, not a summary of it.

## 0. Before you start

`/land` must have passed: gate green on the real tree, CHANGELOG entry in the
same commit, backlog row migrated, commit made by explicit path. If it has not,
stop and run `/land`. Shipping an unlanded commit is how the changelog and the
tree drift apart.

## 1. The branch

One session, one branch, one PR. Name it for the work, not the session:
`claude/<r-numbers>-<slug>`. If the harness already put you on a branch, use it;
never rename someone else's.

```
git rev-parse --abbrev-ref HEAD      # confirm you are NOT on main
git log --oneline origin/main..HEAD  # exactly the commits you mean to ship
```

If that second command prints a commit you did not write this session, stop and
say whose it is. Do not ship it and do not rebase it away.

## 2. Push

```
git push -u origin <branch>
```

Retry a network failure up to four times, backing off 2s, 4s, 8s, 16s. A
force-push is refused by both the settings deny list and the command guard, and
that refusal is correct: it discards commits that in this tree may not be yours.
If a push is rejected as non-fast-forward, **merge** `origin/main` in and resolve
it; never force.

## 3. Open the PR

Fill `.github/pull_request_template.md`, section by section. It mirrors the
CHANGELOG entry deliberately, so most of it is already written: paste the gate
line in full, including the bracketed host warnings, which describe the host and
not the tree (R348). Title is the commit subject: at most 100 characters,
carrying the R-numbers.

Then subscribe to the PR so its CI and review events reach you.

## 4. Drive the gate to green

The `gate` check runs `python tools/audit.py --run-tests --terse` on a clean
ubuntu / cp311 checkout. It is the same gate you ran locally, on a host that
shares none of your host's facts, which is the point.

- **Red because of your change** — fix it and push again. Each push supersedes
  the run in flight.
- **Red on a suite your diff does not touch** — check whether `main` is red too
  before calling it yours.
- **Never** skip, disable, or quarantine a test to get green; never lower a pin
  in `EXPECTED_SUITE_COUNTS` to meet a shortfall. `grew` is a stale pin and is
  the one legitimate pin move; `shortfall`, `skipped_in_place` and `absent` are
  lost coverage (CLAUDE.md, session start step 2).
- **"Flake"** is not a root cause. Re-run a job at most once, and only when it
  died before any test body ran.

Expect five skips: no vendored `.pylibs/scipy`, no `.env`, two unstaged
2026-08-16 salary fixtures, no Classic salary file for the Showdown case. All
five are absent optional files, on every host including CI. A sixth is a finding.

## 5. Merge

Once `gate` is green and there is no conflict, merge it and delete the branch.
Then say, in one line: the merge sha, the gate line, and what Ben would notice.

## 6. If you cannot finish

A cloud container is reclaimed when the session ends, so an unpushed commit is a
lost commit. If you have to stop, push the branch first, even mid-work, and say
what is unfinished. A pushed branch with a red gate is recoverable; a reclaimed
container is not.

## What stays Ben's

Nothing about DraftKings moves here. No uploads, no entries, no deposits, no
stored credentials, no scripted DK access by any client. Shipping code to GitHub
and moving money on DK are different things and only the first is delegated.
