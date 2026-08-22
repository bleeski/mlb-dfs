# Teach autobuild.py the R157 exposure-cap rescue

Filed by a DEV session, claim `engine_claude-autonomy_2026-08-22`, alongside
the CLAUDE.md edit that delegates this decision (R157, CHANGELOG same date).
This fragment is the code half that edit explicitly did not do.

`tools/autobuild.py`'s docstring lists exposure caps under "WHAT IT WILL NOT
DO, EVER". CLAUDE.md's Autonomy section now permits loosening
`max_pitcher_exposure_pct` / `max_player_exposure_pct` /
`max_primary_stack_exposure_pct` when both `STRUCTURAL_FEASIBILITY_CHECKS`
remedies are already at their named values and the joint MILP's error names
no single control as binding -- only the interaction. autobuild.py's own
retry loop still stops at that error today, because it only classifies the
two structural checks (`shared_players_floor`, `sp_pair_capacity`), never the
exposure caps.

Two things a fix needs, not one:

1. **Detect the shape.** The error string to match is `"no single control is
   arithmetically binding against this bank, so the interaction of the active
   controls is"`, paired with confirmation that `sp_pair_capacity` and
   `shared_players_floor` both already passed (i.e. this isn't a case where a
   structural remedy is still available and should be tried first).
2. **Re-derive the target, never hardcode 0.55.** The 1335_3g precedent
   confirmed feasibility with all three caps at 1.0, then settled on 0.55 --
   but that number came from 1335_3g's own structural floors (`player_exposure_floor`
   etc. in the feasibility report, all 3-of-9 on a 9-entry/6-pitcher/3-game
   slate), not from a general rule. A bigger slate or a thinner pitcher pool
   floors differently. The supervisor needs to read those floors off the
   feasibility report the same way it already reads `STRUCTURAL_FEASIBILITY_CHECKS`
   remedies, not carry a constant.

Until this lands, the rescue is manual: confirm fully open (1.0) via
`--controls-override`, read the floors back from the feasibility report, set
a delivered target above them with real headroom, rebuild, record before/after
values in the report. That is what the 1335_3g build session did by hand.
