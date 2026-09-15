# EVERY fragment in this directory as of 2026-08-22 is ALREADY MERGED. Do not merge again.

Written by ARCHIVE, 2026-08-22, holding the `ledger` and `inbox` claims (both
now released). **The merge is done; only the deletion is outstanding**, and the
deletion is outstanding for one reason: the Cowork shell died partway through
close-out and this mount refuses `rm`, so the files could not be moved out.

R23 exists so a ledger block cannot be pasted twice. Deleting a consumed
fragment is how that is enforced, and that step did not run. **This file is the
substitute enforcement. Read it before touching anything in this directory.**

## What was merged, and where it went

| fragments | merged into |
|---|---|
| 108 × `<date>_miner_<contest_id>.md` (2026-08-08 … 2026-08-13) | ledger `A-038` … `A-043`, one `#### Full-field decomposition` block each |
| `2026-08-13_BUILD_1507_3g_sp_pair_floor.md` | ledger `A-038`, demoted to a `#### BUILD note` |
| `2026-08-13_BUILD_1507_3g_crossgame_override.md` | ledger `A-038`, demoted to a `#### BUILD note` |
| `2026-08-15_DEV_audit_macro_fits_this_sandbox.md` | ledger Quick Card item 1 — **the surviving half only** ("a killed macro is not a red gate"). The other half is superseded by R152 and the merge says so explicitly. |
| `2026-08-22_BUILD_wsh-platoon-refresh-build-scoped-only.md` | ledger Quick Card item 4a |

That is every file that was in this directory. If you are reading this and the
directory still holds `*_miner_*.md` files, they are the consumed ones, not new
ones.

## The sweep that still has to run

From the repo root, holding the `inbox` claim:

    mkdir -p _to_delete/ledger_inbox_2026-08-22
    mv ledger/inbox/*_miner_*.md                                    _to_delete/ledger_inbox_2026-08-22/
    mv ledger/inbox/2026-08-13_BUILD_1507_3g_sp_pair_floor.md        _to_delete/ledger_inbox_2026-08-22/
    mv ledger/inbox/2026-08-13_BUILD_1507_3g_crossgame_override.md   _to_delete/ledger_inbox_2026-08-22/
    mv ledger/inbox/2026-08-15_DEV_audit_macro_fits_this_sandbox.md  _to_delete/ledger_inbox_2026-08-22/
    mv ledger/inbox/2026-08-22_BUILD_wsh-platoon-refresh-build-scoped-only.md _to_delete/ledger_inbox_2026-08-22/
    mv ledger/inbox/_CONSUMED_2026-08-22_DO_NOT_REMERGE.md           _to_delete/ledger_inbox_2026-08-22/

`mv`, not `rm`: this mount grants create and truncate but not unlink (R109).
Delete this marker last, and only once the rest are gone.

## Also outstanding from the same interruption

`tools/_scratch_archive0822/` is the run-scoped driver directory for this pass
(`mine_driver.py`, `tranche.py`, `build_ledger_entries.py`, `state.json`,
`cidmap.json`, `consumed.json`). It is gitignored at any depth so it does not
show as dirt, but CLAUDE.md is explicit that a scratch patch outliving its slate
is a hazard rather than clutter. Sweep it the same way:

    mv tools/_scratch_archive0822 _to_delete/

Nothing in it was ever imported by a build. `mine_driver.py` monkeypatches
`field_miner.default_salary_candidates` with a memo for speed and verifies the
memo against an uncached call before use; it changed no result and it must not
be reused on a later pass without re-reading that comment.
