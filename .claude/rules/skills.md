---
paths:
  - "skills/**"
---
# skills/ (the BUILD procedure; loads when you open one)

- `skills/generate-lineups/SKILL.md` is the per-slate procedure and a BUILD session reads it whole (R301(3) wants it at 150 lines plus `references/`. R354 took it from 1,371 to 1,358 by moving 147 lines of host mechanics into `docs/hosts.md`; seven commits then grew it back to 1,586 by 2026-09-23, and R410 cut it to 1,578, by `wc -l`; R388(b)'s two-line pointer to `references/never_relax.md` makes it 1,580, R393(b)'s exit-7 clause 1,581, and R389(b)'s two-line pointer to `references/baseline.md` 1,583). Put new reference material in `references/` and point at it; do not grow the body.
- Prose in it is pinned by tests: `PreflightContractDocumentationTests` (`tests/test_upload_integrity.py`) wants the four exit codes, "acknowledged", and the `--force` waiver wording; `test_docs_instruct_the_probe_not_raw_pip` wants `tools/env_probe.py --install` present and `pip install -r requirements.txt` absent. Run both after any edit.
- `skills/generate-lineups/scripts/build_slate.py` is the script door: one `approve=True` call, no plan leg first (R63, R98; the baseline's own approved call is EP `run_baseline`'s, R389(b)), and `REFUSAL_SITES` is the refusal table every exit reads from.
- The repo `skills/` folder is not a skill registry. Cowork reaches this file through an account-level router skill (`mlb-generate-lineups`) that reads CLAUDE.md and then this file; the repo copy is the one under CHANGELOG discipline, so edit here and never fork the text into the router.
- SKILL.md no longer cites "CLAUDE.md's `## Sandbox`" at all (R354): the 130s number was Cowork's, and per-host budgets are now resolved by `mlb_engine.repo_env.call_budget_s()` with the prose in `docs/hosts.md`. It still cites "CLAUDE.md's T-15 rung", and that section exists in CLAUDE.md by that name -- keep it resolving when you edit either file.
