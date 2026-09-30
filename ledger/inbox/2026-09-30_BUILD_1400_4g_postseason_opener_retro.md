# 2026-09-29 1400_4g postseason Wild Card G1 (4 games, staggered 2/5/8/10 PM ET): BUILD retro fragment

Observed outcomes, conditioned on archetype: Opener 196052739 (large_field_gpp, 11,764 entries, 4 ours) and
Pocket Cup 195970831 (mini-MAX satellite, 5,251 entries, 5 ours). Entered file: certified run 0efaf97e
(sha256 52d158c3), plus 3 hand late-swap changes at 19:43 ET (Schlittler->Tolle x2, Rice->Rutschman).
Result: 0 of 9 cashed. Opener best 104.9 (cash line 120.5, winner 211.8); Pocket best 113.35 (cash line 120.8, 10th 181.8).

## What won (final FPTS, %Drafted from DK standings)
- Winners in both contests: Schlittler (57%, 36.45) + King (16%, 33.35) + SD bats (Tatis 11% 28, Machado 14% 25, France)
  + Ben Rice (2%, 44: the one sub-10% top-5 scorer, ledger 3.17's pattern). Ben Rice was in all 10 of the Opener's top 10.
- Sale (67%) scored 22.05. Fading him was not what hurt us.
- The lowest-total game (CHC@SD 7.0, Petco) carried the winning stack. The highest-total game (CWS@HOU 8.5, two bullpens) did not.
- Declared bulk/PLR arms scored 0 in every slot we held (Painter x2, Imai x1, Fedde x1). Luzardo (DK PO, confirmed opener,
  K line 2.5) went long enough for 17.65.

## Our decisions, graded against outcomes (observed, not predictions)
1. **8 PM hand swaps: net harmful.** Opener 5269344580 kept as built (Schlittler + Rice) scores 160.8
   (rank ~209, about $45) against 96.25 actual. Pocket 5268245030 kept (Schlittler) scores 122.5 (cashes) against 98.95.
   The swap logic was "entries behind the leaders must fade the leaders' SP2". The entries were not live for 1st either way;
   the fade cut ceiling on cash-viable entries, and Rice->Rutschman was a correlation tweak that dropped the slate's top scorer.
2. **Luzardo override (pre-lock):** caught by the K-prop check and reversed before upload (backlog fragment 2026-09-29_BUILD_po-token...).
3. **Leverage build (cap 60), rejected pre-lock:** moved arms to Sale+Schlittler x2. Schlittler was right; Sale neutral.
4. **Bulk arms:** 4 P slots on PLR arms returned 0. Their projections came from season APPG (starter-era for Imai).

## Candidate rules (for the ledger owner to weigh, not applied)
- A late swap that REDUCES an entry's projection for leverage needs a live path to the target payout for THAT entry.
  Otherwise hold projection (cash equity is real in a 2,766-deep payout).
- Never drop a confirmed top-3 hitter for a correlation fit in a late swap.
- Postseason PLR/bulk arms: treat as near-zero floor; do not roster in a P slot without a named workload (IP) source.
- Tooling: late_swap cannot carry declared arms (backlog fragment 2026-09-29_BUILD_late-swap-drops-declared-arms.md),
  so the 5 PM and 8 PM windows ran by hand, outside the engine's projection discipline.

## Ben's follow-up (2026-09-30): a chalk-core seat per contest
The certified file held exactly one Sale + Schlittler lineup (Pocket 5268245030); the Opener held none, and the 8 PM
swap removed the Pocket one. Proposal: every contest with 2+ entries seats at least one lineup on the projection's
consensus SP pair, differentiated through its bats. The field's winning cores here were chalk arms (Schlittler 57%)
paired with a mid-owned second arm (King 16%) and low-owned bats (Rice 2%). The engine already has a `projection`
sleeve; the ask is that `distinct_sp_pairs` / pitcher caps never leave a contest with zero consensus-pair entries,
and that a late swap never removes the last one.
