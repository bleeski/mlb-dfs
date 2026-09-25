---
paths:
  - "skills/**"
---
# skills/ (the BUILD procedure; loads when you open one)

- `skills/generate-lineups/SKILL.md` is the per-slate procedure and a BUILD session reads it whole, often inside a lock window, so every line costs every build. R301(3)'s target is 150 lines plus `references/`, measured by `wc -l`. Put new reference material in `references/` and point at it; do not grow the body.
- Prose in it is pinned by tests: `PreflightContractDocumentationTests` (`tests/test_upload_integrity.py`) wants the four exit codes, "acknowledged", and the `--force` waiver wording; `test_docs_instruct_the_probe_not_raw_pip` wants `tools/env_probe.py --install` present and `pip install -r requirements.txt` absent. Run both after any edit.
- `skills/generate-lineups/scripts/build_slate.py` is the script door: one `approve=True` call, no plan leg first (R63, R98; the baseline's own approved call is EP `run_baseline`'s, R389(b)), and `REFUSAL_SITES` is the refusal table every exit reads from.
- The repo `skills/` folder is not a skill registry. Cowork reaches this file through an account-level router skill (`mlb-generate-lineups`) that reads CLAUDE.md and then this file; the repo copy is the one under CHANGELOG discipline, so edit here and never fork the text into the router.
- SKILL.md cites "CLAUDE.md's T-15 rung", and that rung exists in CLAUDE.md by that name; keep it resolving when you edit either file. Per-host budgets are resolved by `mlb_engine.repo_env.call_budget_s()`, with the prose in `docs/hosts.md` (R354).
