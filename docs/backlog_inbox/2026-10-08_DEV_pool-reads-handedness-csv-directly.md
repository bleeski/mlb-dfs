# 2026-10-08 DEV (Session 33): let `build_slate_pool` read `data/reference/handedness.csv` for a DK-covered Classic slate

**Context.** R332 shipped `tools/handedness_feed.py`: it builds the DK-only feed through `dk_starting_only_feed` and stamps `bat_side` and each probable's `hand` from `data/reference/handedness.csv` (per-row stamp and source). A DK-covered Classic slate still needs that step before `build_slate.py --lineups`, and a session that forgets it builds with F4's platoon half neutral (named, never silent: `f4_handedness_unavailable`).

**The cheaper route, not built.** `build_slate_pool` could read the CSV itself, under the feed's hands, the way R442 now merges the platoon reference's `bats` for TBD sides (`pool_report["handedness"]` already reports `from_feed` and `from_platoon_reference`; a third source `from_handedness_cache` would sit beside them). No feed step, no new door.

**Why it was left.** It adds a second writer of a posted hitter's hand beside the feed's, on the surface R442 had just made explicit, and it changes what a confirmed side with no feed hands means (today: named as without a hand; then: filled from a cache whose rows may be old). That is a precedence decision (feed over cache over reference, with the cache's per-row stamp reaching the report) and it deserves its own test class, not a rider.

**Cost estimate.** S. `build_slate_pool` reads the CSV through `tools/handedness_feed.read_handedness` (or a copy moved under `mlb_engine/`: the tool imports `live_data_adapters`, so the engine importing the tool is a layering inversion), merges under both existing sources, reports the rows' ages, and `from_handedness_cache` joins the `handedness` block.
