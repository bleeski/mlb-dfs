# 2026-10-10 BUILD (2000_1g_sd): a late `pitchers_duel` slot ships without a starter when other templates fill his player cap first

**Observed.** On the ALDS G5 ladder (37 entries, player cap 18), `solve_ladder` solved the third duel slot after Gavin Williams had reached 18 in other templates. `player_exposure.cap_reassignments` and `.locks_dropped` named him, and the slot shipped as "Pitchers duel - both starters" with one starter, then on a retune with neither. `counted_relaxations.clean` stayed true, which is correct by R153's rules (the cap held), but the delivered row no longer matches its label.

**Mechanism (read).** R250's captain hold reserves player-cap budget for a captain rung only (`captain_demand`), so a `hard_locks` arm who is NOT that slot's captain has no reservation, and slot order (the R239 deal) decides whether the duel still gets him.

**Candidate item.** Extend the hold to `hard_locks`: count each template's hard-locked arms into the reservation the same way captain demand is counted, so a duel slot keeps both arms or the brief names the shortfall before the solve. Effort S. The session worked around it by taking the opposing starter out of three directional scripts and cutting the duel to the two-entry floor.

Nothing here is a lift, an edge, an ROI or a win rate.
