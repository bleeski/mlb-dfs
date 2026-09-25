---
name: land
description: Landing checklist for a DEV change in mlb-dfs: gate, CHANGELOG entry in the same commit, roadmap row and NEXT, register migration, explicit-path add and commit, claim release. Run it before every commit of engine, tool, test, skill, or docs work.
---

# Land a DEV change

Every step prints evidence. Show the output, not a summary of it.

1. **Gate on the real tree.** `python tools/audit.py --run-tests --terse` prints `PASS  v2.26.0  <N> modules  <N> tests` with nothing appended. If a pin moved, the `EXPECTED_SUITE_COUNTS` comment in `tools/audit.py` says `R###, date: old -> new, the N that pin X`. If a golden histogram moved, you re-froze it on purpose and the entry says so. `python tools/solver_probe.py --date <recent slate date>` still says FITS when the change touched the bank, the allocator, or the optimizer. Then, when the diff touches `mlb_engine/`, `tools/`, `tests/`, `.claude/hooks/` or a `scripts/` file, run `/code-review` on it and fix every finding you would block the merge for; the CHANGELOG entry names any you declined and why. No human reviews the PR before the merge, so this pass is the only review it gets.
2. **CHANGELOG.md entry**, newest first, under `## <date> — <title with the R-numbers>`: `**Scope.**` naming every file touched (docs, skills, `.claude/`, CLAUDE.md included), what was wrong, what shipped, declined parts with reasons, the R233 grep for any "now lives in one place" claim with its hit list, and the gate line. The completed backlog entry's text migrates here.
3. **docs/ROADMAP.md and the register**: the row's Status reads `Complete <date>` (a batched block only when every item landed; a partial landing rewrites the row to its remainder); **NEXT** advances; append a Progress Ledger row and backfill the previous row's SHA; the register entry in `docs/backlog.md` collapses to a CLOSED stub or is rewritten to its open remainder. Splice by anchor (see `.claude/rules/board.md`); never rewrite the register. `python tools/plan_status.py --check` exits 0.
4. **Pins that read prose.** `python -m pytest tests/test_core.py -k "ChangelogDebt or AuditSkipHonesty or ClaimTool or EnvLock or SkillCacheDrift or RootContractBudget" -q` and, if `skills/` changed, `python -m pytest tests/test_upload_integrity.py -k PreflightContractDocumentation -q`.
5. **Dirt check.** `python tools/claim.py dirt --role DEV` shows only your paths inside the write set. Foreign `BLOCK` lines mean another session's work is in the tree: do not add its paths and do not commit pathless.
6. **Commit by explicit path**, the same list to both commands:
   `git add <paths>` then `git commit -F <msgfile> -- <paths>` (or `-m`). Subject at most 100 characters carrying the R-numbers; body: one sentence on what moved and why, and the CHANGELOG entry title. Verify with `git show --stat HEAD` that only your paths landed.
7. **Release**: `python tools/claim.py release engine` (add `--date <date>` if the claim was minted on an earlier UTC day). Sweep `tools/_scratch_<tag>/`.
8. **Ship it.** Run `/ship`: push the branch, open the PR against `.github/pull_request_template.md`, drive the `gate` check to green, merge. The push, the PR and the merge are the session's (R350, R353). `main` is never committed to directly, and a force-push is refused.
