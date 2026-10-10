# 2026-10-10 DEV (Session 29, R68): three more raw `row[4:14]` roster readers in `build_slate.py` read a "Name (ID)" cell as a player id they cannot match

**Observed.** R68(a) closed `tools/late_swap._load_entry_rosters`, which kept `row[4:14]` raw, by routing it through `parse_dk_entry_rows` (one definition of a roster cell). `grep -rnE "\[4:1[0-9]\]" tools mlb_engine skills` finds the same raw read in `skills/generate-lineups/scripts/build_slate.py` at `:2508` (`verify_classic`: a false `unknown player id` failure; repro `['4711612346: unknown player id']`), `:8245` (`portfolio_exposure`: the row is silently dropped; `lineups: 1` from a file of 2) and `:8174` (`leverage_realized`: counted under `entries_unresolved`, so at least named). Measured by the R68 premise agent on hand-written cells in a scratch file.

**Why it is filed and not fixed in Session 29.** Each reads a file the engine wrote, and a hand-written or repaired cell reaches them only through a completed row a build preserves (R448), so none is reachable with such cells today. The item named `late_swap.py`; fixing `build_slate.py` is a different file's surface. `dk_entries_manager.py:790,793` compares raw bytes to raw bytes on purpose (to prove rows were preserved) and `production/csvio.py:307` already normalizes.

**Candidate item.** Route the three through `parse_dk_entry_rows` (or `normalize_player_id` per cell) and add one test per reader with a `Name (ID)` cell. XS. P3 until a repaired file is built on rather than swapped.

Nothing here is a lift, an edge, an ROI or a win rate.
