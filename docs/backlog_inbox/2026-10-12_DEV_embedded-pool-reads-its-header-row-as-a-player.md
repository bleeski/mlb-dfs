# 2026-10-12 DEV (Session 165, R499): `parse_embedded_player_pool` returns the pool's header row as a player

**Observed.** DK writes a DKEntries file's embedded player pool under a `Position` header row that sits on an entry row (row 8 of the vendored Turbo `data/archive/2026-06-03/DKEntries_2026-06-03.csv`, column 15; column 11 on the Showdown fixture). `mlb_engine/entries/dk_entries_manager.py` `parse_embedded_player_pool` (:367) finds the start column from that row and then iterates `rows[1:]`, so the header row itself is read as a player: on the vendored Turbo the first key is `'Name + ID'` with `{'position': 'Position', 'name_id': 'Name + ID', 'name': 'Name', 'id': 'Name + ID'}`. Reproduced at 696c2d7 (`tools/_scratch_r499/repro.py`, gitignored; one line: `next(iter(parse_embedded_player_pool(path).items()))`).

**Who reads it.** `grep -rn "parse_embedded_player_pool" --include=*.py mlb_engine tools skills`: DKM:663 `player_pool_count` (one high), DKM:1025 the same-draftgroup overlap check (the denominator one high, so 170/171 where 170/170 is true; the 0.90 floor is not near), `tools/results_ledger.py:1058` the name map (adds `'Name + ID' -> 'Name'`, which no real id matches). No decision has been changed by it that this session could find.

**Why filed, not fixed.** R499 reads `Game Info` by header label in `tools/day_plan.py` and does not call this function; DKM was read-only in Session 165.

**Candidate item.** Skip rows at or above the header row the start column was found on (or skip a row whose `Name + ID` cell equals the label). Test: the vendored Turbo's pool has no key equal to `'Name + ID'` and its count equals the salary file's player count. Effort XS; no engine behaviour beyond the two counts.

Nothing here is a lift, an edge, an ROI or a win rate.
