---
paths:
  - "skills/**"
---
# skills/ (the BUILD procedure; loads when you open one)

- `skills/generate-lineups/SKILL.md` is the per-slate procedure and a Cowork BUILD session reads it whole (about 80KB today; R301(3) wants it at 150 lines plus `references/`). Put new reference material in `references/` and point at it; do not grow the body.
- Prose in it is pinned by tests: `PreflightContractDocumentationTests` (`tests/test_upload_integrity.py`) wants the four exit codes, "acknowledged", and the `--force` waiver wording; `test_docs_instruct_the_probe_not_raw_pip` wants `tools/env_probe.py --install` present and `pip install -r requirements.txt` absent. Run both after any edit.
- `skills/generate-lineups/scripts/build_slate.py` is the script door: one `approve=True` call, no plan leg first (R63, R98), and `REFUSAL_SITES` is the refusal table every exit reads from.
- The repo `skills/` folder is not a skill registry. Cowork reaches this file through an account-level router skill (`mlb-generate-lineups`) that reads CLAUDE.md and then this file; the repo copy is the one under CHANGELOG discipline, so edit here and never fork the text into the router.
- Two SKILL.md paragraphs cite "CLAUDE.md's `## Sandbox`" for the 130s number and "CLAUDE.md's T-15 rung"; both sections still exist in CLAUDE.md by those names. Keep them resolving when you edit either file.
