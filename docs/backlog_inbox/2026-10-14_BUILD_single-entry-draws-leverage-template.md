# Positional deal put both bottom-order leverage templates in single-entry contests, second occurrence

Filed by BUILD, 2026-10-14, NLCS G3 MIL@LAD Showdown (2000_1g_sd).

## What happened
`thesis_deal` (side_balanced) dealt `favorite_bottom_order` (Will Smith CPT) to the $5K Solo Shot and `underdog_bottom_order`
(Cooper Pratt CPT, .572 OPS vs LHP) to the $2K Daily Dollar [Single Entry], and both $300 Dime Time entries realized LAD 4-2
(`favorite_win_close` + `pitchers_duel`, which the deal counts as neutral). Delivered instead: the same 17 lineups permuted by
hand (Solo Shot <-> $100 Dime slot, Daily Dollar <-> $300 Dime slot), sha256 0fc959426dfd, preflight exit 0.

## Prior occurrence
2026-10-06 2130_1g_sd: the same hand swap (Solo Shot took a mainstream lineup, the Pratt-CPT bottom-order lineup went to Dime
Time), record `data/deliveries/2026-10-06/2130_1g_sd_norun_b9638868fe13.json`.

## For DEV
The backlog declined shape-conditioned dealing for want of a measurement (see the R239(a) landing line in `docs/backlog.md`).
This is two sessions making the same manual call, which is the evidence that line asked for, though not an outcome
measurement. Two smaller asks: (1) a realized `pitchers_duel` row whose team split is 4-2 should count toward that side in the
deal, not neutral; (2) a named operator permutation (`--deal-override` or similar) so the record carries the swap instead of a
hand assembly.
