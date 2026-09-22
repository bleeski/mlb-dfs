# MANIFEST

The Cowork migration seed this file used to hold was retired on 2026-09-19
(R368) and now lives at `docs/legacy/MANIFEST_cowork_seed_2026-07-16.md`. It
pinned a 119-test v2.26.0 tree and told the reader to open the folder in Cowork;
the tree is past 2,100 tests and Cowork is legacy.

This file stays in place rather than moving because it is named in the DEV write
set in two places (`CLAUDE.md`'s Roles bullet and `tools/claim.py`'s
`WRITE_SETS`), and `ClaimWriteSetTests` compares the two.

Where the current answers live:

| Need | Read |
|---|---|
| The contract, and what a session may write | `CLAUDE.md` |
| Which host you are on, and what it can do | `docs/hosts.md` |
| What to build next | `docs/ROADMAP.md` (the NEXT line), then the R-entry in `docs/backlog.md` |
| What changed and why | `CHANGELOG.md`, by R-number |
| Per-slate build procedure | `skills/generate-lineups/SKILL.md` |
| Layout and module inventory | `python tools/audit.py --terse` |
