---
name: handoff
description: Close out after an mlb-dfs dev PR merges: level this checkout and Ben's clone with GitHub, delete only the branches that lose nothing, and write the next-session prompt (plan mode, the advisor, what to do, how much effort, how to verify). /ship runs it after every merge; run it by hand when Ben merged a PR himself, or when he says "hand off", "next prompt", "clean up branches" or "sync my disk".
---

# Hand off after a merge

`/ship` ends at the merge. A cloud container is reclaimed when the session ends and cannot see Ben's disk, so whatever should follow a merge is done here, in this message, or it is not done (R491). Each part is a subcommand of `tools/handoff.py`: print its output, do not compose it from memory.

## 1. Level this checkout with GitHub

```
git fetch --prune origin
git status --porcelain --untracked-files=no   # must print nothing before the next line
git switch main                               # you are still on the merged branch
git merge --ff-only origin/main
python tools/sync_check.py                    # exit 0
```

If the status line prints anything, do not switch: `git switch` carries uncommitted edits onto `main`. Say so and go on to part 2, which reads refs only.

## 2. Branches

```
python tools/handoff.py branches --fetch --apply
```

It deletes ONE class: a branch whose tip is already an ancestor of `origin/main`, so nothing on it is lost. Everything else is reported and left. `KEEP-ON-MAIN` means the tip is on `main`'s own line: a branch with no commits of its own yet, which a session may have just taken (R359's pushed branch is its mutex), so ancestry alone must not delete it. `KEEP-CITED` means the roadmap, the register or the CHANGELOG names the branch or its tip sha (measured 2026-10-08: all three stale remote branches were, one as the base the next R379 session starts from). `ASK` means unique commits nothing names. Exit 2 means an `ASK` row exists. The report prints the delete command and the command that restores it; lead your message with them and let Ben decide. Never delete a branch by hand, never sweep by age, and leave other worktrees alone. GitHub already deletes a merged PR's branch (`delete_branch_on_merge`), so on a healthy repo this part finds little.

## 3. Ben's clone

You cannot see his disk from a cloud container, so give him the block, tagged `powershell`:

```
python tools/handoff.py powershell --merge-sha <the merge sha>
```

It fetches and prunes, fast-forwards `main` (it stops on a dirty tree and changes nothing), deletes only local branches whose upstream is gone and which `git branch -d` accepts, and ends in `IN SYNC` or `NOT IN SYNC`. On Ben's Windows machine the checkout is his disk: run those lines yourself in PowerShell, quote the last line, and print no block.

## 4. The next-session prompt

```
python tools/handoff.py prompt --merge-sha <the merge sha> --note "<what this session found or filed that bears on the next row>"
```

It reads **NEXT** from `origin/main` after the fetch, so `/land` having advanced it is what makes this the right row. Its three answers come from the row: WHAT is the Work Unit cell, EFFORT is the rank line plus a reasoning level (`high` at least for a Standalone row or the optimizer, allocator or execution pipeline), VERIFY is the Verification cell plus the gate. Check them before you hand it over. A `WARNING` on stderr (the row needs a decision only Ben has, is not open work, states no size or no verification) goes first in your message, and `--session NN` picks another row. Add a `--note` for anything the next session would otherwise rediscover. Do not edit the prompt's plan-mode and advisor protocol: starting in `/plan`, the advisor on the draft before it is presented, and the advisor again after approval is Ben's rule (2026-10-08). The prompt is already inside a fence; paste it as it is.

## The message

In this order: what waits on Ben (an `ASK` or `KEEP-CITED` branch with its commands, a decision the next row needs), then the merge sha with the gate line and the sync evidence, then the PowerShell block if you printed one, then the prompt last, so the last thing on the screen is the thing he copies.
