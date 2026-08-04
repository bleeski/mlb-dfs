# Fragment: R37's decision input changed — do not confirm the 5-2-1 target off the 07-30 numbers

Session: ARCHIVE, 2026-08-04. For: DEV, and for Ben before the R37 decision. Working:
`ledger/2026-08-04_field_shape_ownership_analysis.md` and ledger 3.17, from the A-030..A-034 mine
(94 contests; the archive's entry count roughly doubled).

R37 is queued as "Ben confirms the target (the 5-2-1 family, per the evidence), then bank-job +
posture-parameter work." The evidence moved:

1. **The 5-2-1 lift decayed while the field crowded in.** 07-30 tranche: +3.1pp [+1.2,+5.1] on
   25.1% field share. New 32-contest tranche: +0.2pp [-2.1,+2.5] on 29.7% share. Combined 116
   contests: +2.0pp [+0.6,+3.5]. Win-line concentration did NOT repeat (31.2% of new-tranche wins
   on 39.1% share; ledger 3.16 line downgraded to open).
2. **The repeatable result is the downside.** "3 or fewer primary" is negative in both tranches and
   every conditioned slice (combined -2.8pp [-3.8,-1.8]; promoted provisional -> firm as an observed
   field pattern). 4-2-x — 35.5% of our new-tranche Classic entries — turned negative with the
   interval excluding zero (-2.2pp [-3.6,-0.8]).
3. **Our thin-slate drift makes the floor the payoff.** Our <=3-primary share tripled to 21.5% in
   the new tranche while our 5-stack share stayed at 10.8% against a field at 47.7%. R37's
   feasibility bullet (5-man floor on a 3-game slate) now has a live diagnostic sub-question: how
   much of that 21.5% is thin-slate structure vs solver choice. Answer it before sizing the floor.
4. **Slice detail for the target decision:** solo shots (WTA family): 5-2-1 still over-wins
   (36.4% of 11 wins on 21.5% share) and 5-stacks take 64% of wins. mini-MAX (5 contests, 73,343
   entries): 5-1-1-1 is the strongest shape (+3.6pp [+1.4,+5.6]). Satellites: +2.0pp [+0.2,+3.9].
5. **The no-contrarian-push constraint strengthens.** Winners run chalk-positive cumulative
   ownership in Classic satellites (+4.9 pts vs field), solo shots (+9.5), and single-entry GPPs
   (+8.6); sub-field only in supersatellites (-13.2). Differentiation that pays: one or two sub-10%
   pieces inside a chalk-positive lineup (winner carries >=1 in 51% of contests vs 13% field base),
   not global contrarianism. Winners take the chalk SP pair at its field share (24% vs 20.7%).
6. **Record updates R37's prose cites:** "0 seats in 234 own entries" is stale — the first two
   rank-1 finishes are on the books (192892126 rank 1/53, A-034; 192973047 rank 1/23, A-032; both
   $0.25 Classic satellites). Satellite-family record now 535 entries, 19 top-3, 2 rank-1.

Suggested reframe for the R37 decision line: the fuller archive argues FLOOR-FIRST — eliminate the
confirmed-negative families (<=3 primary, shrink 4-2-x) via a `primary_stack_min_size` posture
parameter and stack_min=4 as the true floor, with the 5-family push (5-2-1 / 5-1-1-1 bank jobs) as
the second, smaller half, sized per posture: 5-1-1-1 for mini-MAX/large-field, 5-2-1 for WTA solo
shots. The +3.73pp mix arithmetic in the 07-30 doc no longer holds at face value.

Related merges: R40 gains two live cases (which profile built the two rank-1 satellite winners?);
R10's starting priors extend (Showdown own-dup now 27/109 vs Classic 4/93; dup share 27.2% median
in 151-500 Showdown fields, 53.4% above 500). R30(a)'s priority argument strengthens: none of the
94 new contests carries a paid line, so the two rank-1s cannot be graded as seats and the cash-line
finding stays ungradeable until a fresh entry-history export lands.
