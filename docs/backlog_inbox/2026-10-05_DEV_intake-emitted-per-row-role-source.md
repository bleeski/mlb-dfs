# `build_slate_pool` knows how each hitter got into the pool and returns only a per-team status: emit the per-row source (beside R482)

Filed 2026-10-05 by DEV (Session 43, R342(c)). S; found while recording the build's pool in the brief.

**What is missing.** `pool.members.role_source` (R342(c)) can only say `confirmed_lineup`, `platoon_projected`, `declared_pitcher`, `probable_sp` or `unknown`, because those are the only per-row facts `build_slate_pool` hands back (`confirmed_hitter_ids`, `platoon_order_by_player_id`, `pitcher_roles`, the pool report's `declared_arm_workload`). A posted-partial seed (`live_data_adapters.py:2237-2243`) and an APPG-fallback hitter (`:2275-2281`) both come out of `_pool_row(..., batting_order=None)` with no Notes tag, so both read `unknown`, and a posted seed that also holds a platoon slot reads `platoon_projected`. The only record of which fill a side took is the per-team `teams[team]["status"]` (seven values, `:2248-2288`), which the brief now copies verbatim; `status_by_player_id` (`:2209`), which knows each posted starter, is not returned.

**Fix.** Return a per-row `role_source_by_player_id` from `build_slate_pool` (additive: the confirmed lineup, a DK-posted slot, a posted partial seed, a platoon slot, the APPG fallback, a probable arm, a declared arm), and have `pool_members_record` read it instead of deriving from four facts. No pool row changes; only a new key in the return.

**Pairs with R482 (Session 151), which edits the same function.** R482 will name every partial-side fill (`pool.partial_side_fills`) after D-11; this is the same record taken per player, so do it in that session rather than opening `build_slate_pool` twice. Trigger otherwise: the first pool-aware grade shows `unknown` is a large share of the hitters on TBD-heavy slates.

**Evidence.** On the vendored frozen 2026-07-29 salary file (fully DK-posted) `unknown` is 0 of 60; on the posted-lineup test pool with no platoon reference the TBD side's nine are `unknown` (9 of 40).
