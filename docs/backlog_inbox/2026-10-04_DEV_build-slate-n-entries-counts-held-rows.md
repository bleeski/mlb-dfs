# 2026-10-04 DEV (Session 124, R448): `build_slate` sizes the bank, the SP-pair need and the thin-bank floor on every reserved row, held ones included

**Observed.** `skills/generate-lineups/scripts/build_slate.py:3773`: `n_entries = args.entries or count_reserved(entries)`, and `count_reserved` (`:8278`) counts every row whose first cell is a digit, complete rows included. After R448 a template's complete rows are left in the file and never filled, but `n_entries` still feeds `resolve_candidate_bank_size` (`:3968`), `resolve_bank_cap` (`:4079`), `sp_pairs_needed` (`:4277`), `requested_n` (`:4262`, `:4266`, `:4557`), the thin-bank test `len(candidates) < n_entries * 2` (`:4278`, `needed_at_least: n_entries * 2` at `:4347`) and the brief's `entries` (`:4891`, `:5012`). On the vendored 18-row template with one row held, the real `run_classic` door builds and certifies (verified in the Session 124 tests), so the over-ask is harmless at that size.

**Not reproduced.** The effect that would matter is a refusal: a template where Ben entered many lineups by hand (say 30 of 38 rows) sizes the bank and the thin-bank floor for 38 entries when the build fills 8, so a slate with a thin bank could refuse BANK-THIN for rows it never needed. That is reasoned from the lines above, not run.

**Candidate item.** Count the rows the build FILLS (blank and partial) for Classic, as `baseline.initial_build_requirements` does, and keep the whole-file count for the brief's `entries`; `--entries` stays an explicit override. Showdown's own reserved read (`:5950`) already drops complete rows. Test: a `run_classic` build on a template with most rows complete asserts the bank target and the floor use the filled count.

Nothing here is a lift, an edge, an ROI or a win rate.
