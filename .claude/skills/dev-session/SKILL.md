---
name: dev-session
description: Start a DEV session on the mlb-dfs engine in Claude Code: read the session-start facts, take the engine claim, run the gate, pull the NEXT session block from docs/ROADMAP.md and its R-entries from the register, and work it to a landing. Use when Ben says "work on the next session" (in the roadmap or the backlog), names a Session NN block or an R-number to build, or asks for any engine, tool, test, skill, or docs change in this repo.
argument-hint: [Session NN or R-number, optional]
---

# DEV session

You are DEV. CLAUDE.md is the contract and it has already loaded; this skill is the procedure. The SessionStart hook has printed HEAD, held claims, dirt, the git log, the NEXT pointer, and any git locks; if it did not, run step 1 by hand.

**Done means** the item's verification command passes, the gate prints its PASS line, the CHANGELOG entry and the roadmap row land in the same commit, and the PR merges on a green `gate`. Between here and there, stop only for a fact only Ben has, the nod §2 requires, or `/land` and `/ship`, which Ben types because their frontmatter bars the model from invoking them. A status note rides in the same message as the next action.

## 1. Orient (no writes yet)

1. Read the hook output. Classify every dirty path against the DEV write set with `python tools/claim.py dirt --role DEV`. `BLOCK` lines are another session's uncommitted work inside your write set: stop and tell Ben whose it is (the held claim's `owner.json` names the scope). A HELD claim from an earlier UTC day with hours-old dirt and no live session is a dead session: finish its commit first, by explicit path, using its CHANGELOG entry as the message, then `release` its claim before taking yours. Never redo its work and never restore, checkout, or reset around it.
2. Take the claim: `python tools/claim.py take engine --role DEV --scope "<Session NN or R-numbers>"`. If `engine` for today is held, a scoped `engine_<slug>` blocks nobody (the mutex is nominal), so say so and commit early. Then start `claims/<claim>/TASKS.md` and keep it current: Ben's instructions this session, each R-number in flight with the files it touches, and the last gate line. Tick items as they land and add what you find. The PreCompact hook re-injects it, so it is the one list that survives a compaction.
3. Gate: `python tools/audit.py --run-tests --terse`. Expect `PASS  v2.26.0  <N> modules  <N> tests` with nothing appended (`docs/hosts.md` has how long it takes on this host; the Bash timeout is raised in `.claude/settings.json`). A bracketed warning is about the host (see `CLAUDE.local.md`); a failing suite blocks; `grew` means a stale pin, everything else off-pin is lost coverage.
4. Read the hook's `inbox:` line. Fragments in `docs/backlog_inbox/` are addressed to DEV and are the documented way every other role hands you a row; merge the ones your item touches into `docs/backlog.md` under an R-number, add or edit the `docs/ROADMAP.md` row that schedules it (the linter fails on an open entry no row names), and retire them per `.claude/rules/board.md`. Verify each premise with grep before acting on it. They are not on the NEXT path and a committed fragment is invisible to `git status`, which is how three sat unmerged from 2026-08-09 and eighteen ledger fragments from 2026-08-13. A `+N retained` count is by design, not debt.
5. Find the work. `$ARGUMENTS` names it, or the NEXT line does: `grep -n "^\*\*NEXT:\*\*" docs/ROADMAP.md` gives the block; `grep -n "| \*\*Session <NN>\*\*" docs/ROADMAP.md` gives the row (scope, target files, verification command, prerequisites); `grep -n "^### R<num>\." docs/backlog.md` gives each entry. Read the row and the entries in full and nothing else of the board. Read the CHANGELOG entry for every R-number the row's `Was` or the entries cite (`grep -n "^## .*R<num>" CHANGELOG.md`).
6. Check each premise. Hand every filed entry's text and the paths it names to its own `dfs-premise` agent, all of them in one message when the block has several. Before you build on a report, re-run its sharpest grep yourself; a verdict you have not reproduced is the agent's opinion.

## 2. Plan before code

Write the plan as a short list Ben could read: what is wrong (verified against the tree, not the entry), which files, which tests, what the gate line and golden histogram should look like after. For an M item or anything touching `optimizer_v3.py`, `contest_allocator.py`, or `execution_pipeline.py`, use plan mode and get Ben's nod before editing. Reproduce first: the filed diagnosis has been wrong about the mechanism more often than right (see `.claude/rules/engine.md`).

## 3. Implement

- Surgical changes; match the surrounding style; touch only what the item names.
- One R-number at a time inside a batch; each gets its own tests, run with `python -m pytest tests/test_core.py -k <Class> -q` or `python -m unittest tests.test_core.<Class>` while iterating. Do not run the full gate per edit.
- Mutation-check each new test (revert the fix, expect red, restore).
- Move the per-suite pin in `tools/audit.py` with a one-line comment; re-freeze a golden baseline only deliberately and record the histogram before and after.
- Keep the list of every file touched in `TASKS.md`; the CHANGELOG scope line, `git add` and `git commit` all need it.

## 4. Land

Run `/land`. It is the checklist: full gate, CHANGELOG entry in the same commit, roadmap row Complete, NEXT advanced and ledger row, register migration, explicit-path add and commit, subject at most 100 characters, release the claim, then `/ship` (R353 made the push, the PR and the merge the session's).

End the session's last message in this order: what is blocked on Ben (a question, a declined part that needs his call, a `/land` or `/ship` to type), then what changed (the PR or merge sha and the gate line), then what you found and filed.

## Gotchas that have each cost a session

- `git commit` without pathspecs commits every session's staged files, not yours. Pass paths to both `git add` and `git commit`.
- A scoped `engine_<slug>` claim beside a held `engine_<date>` blocks nobody, and a concurrent session's restore has wiped uncommitted edits silently (2026-08-11). Commit in small batches. A surprising `substring not found` on a string you know you changed means your edit was reverted, not that the test is wrong.
- The board's entry for an item is a hypothesis about the mechanism. `grep` the tree for the control it says is missing before building one; R333 was a dead control, not a missing one, and 2 of 3 fragments filed on 2026-09-09 had a false premise.
- Partial landings are normal: land the buildable parts, rewrite the entry to the remainder, record declines with reasons in the CHANGELOG.
- `TZ=... date`, `nohup` and `setsid` are bash idioms, not Cowork habits: they work in a cloud container, where `/tmp` also persists across calls and `rm` works (measured 2026-09-17, re-measured 2026-09-19). On Ben's Windows machine use `python` and `Get-Date` instead. Prefer a `python` entry point either way, so the same command works on both.
- Auto memory is on. Save corrections Ben gives you and non-derivable project facts there; CLAUDE.md stays the team-facing contract and is not a diary.
