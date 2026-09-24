# Late swap re-ranks open slots on an unenriched projection (R272, R386)

Slate 2026-09-23 1905_10g, 20:55 ET. Ben asked for a swap once every lineup had
posted. Seven of ten games were locked, and 81 of 320 slots were open, across
LAA@ATH, SD@LAD and HOU@SEA. None of those 81 slots held a player absent from
the posted lineups, so a swap would have been pure refinement.

`tools/late_swap.py:739` builds the swap's projection frame as
`_assemble_projection_frame(salary, rows, "emergency_proxy", None, None, None, ...)`:
no Savant batting or pitching file, and no F1, F4 or F5 maps. So the swap ranks
candidates, and compares incumbent to chosen, on AvgPointsPerGame x
batting-order only. The parent build used all six enrichment factors plus the
odds paste (`f1_games_priced` 10, `f4_platoon_applied` 153). The docstring at
`late_swap.py:99` says a swap "does not re-derive weather, odds, or a pitcher
audit". In fact it drops the whole enrichment stack.

Consequence: a swap's "improvement" is measured against a weaker model than the
one that built the file. The swap was not run, and Ben was told why. Tonight it
would have been worst for LAA@ATH, which is 29 of the 81 open slots in the
slate's highest-total open game (9.5). Without F1, the swap cannot see that total.

Proposed for DEV: the swap reuses the parent run's enrichment inputs (the odds
packet, Savant files and F4/F5 maps recorded in the parent brief), refreshing
only the batting orders from the new feed. It prints the factor counts the way
the build's brief does, so an unenriched swap is visible rather than silent.
