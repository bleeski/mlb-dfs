# Fragment: R10's gate may be the wrong shape, and R13 has less surface than it looks

Session: ARCHIVE, 2026-07-29, second half of the satellite audit.
For: DEV and Ben. Two items, both framing rather than code. Neither is urgent
and neither should be built to before Ben rules on the first.

## 1. R10's gate assumes breadth the portfolio does not have (decision, before code)

R10 gates on "roughly eight archetype-conditioned slates." Measured against the
now-backfilled archive, that gate reads as failure: 76 contests in 15 distinct
(paid_places, field-bucket) cells, with 58 in one cell (`paid_places == 1`,
satellite) and every other cell holding 1 to 3.

My first pass called that a badly shaped archive. On reflection that is probably
wrong. The archive is **faithful**: MLB satellites are 4,201 of 4,879 MLB entries,
so an archive that is 63/76 satellite is an accurate sample of what Ben actually
plays. The deep cell is the cell that matters.

R10's own justification agrees: "field behavior is the one commercial capability
that materially changes satellite results (clearing the cut line unduplicated is
the whole game)." If that sentence is true, then a gate demanding archetype
*breadth* is measuring the wrong thing, and R10 may be closer to openable than the
cell count suggests, scoped to the satellite archetype alone.

The question for Ben, not for me: **should R10's gate be re-scoped to "N slates in
the satellite archetype" rather than "N archetype-conditioned slates" generally?**
If no, R10 stays shut until the contest mix changes, and that is a portfolio
decision rather than a modeling one. Do not start fitting priors until this is
settled, because the answer changes what "per archetype" means in the fit.

**The count this note asked for was run before the session closed** (ledger 3.15,
updated here in place): the `paid_places == 1` cell holds **77 contests across 12
distinct slate dates with 286 of Ben's own entries.** Contest depth and slate depth
are not the same and I was right to insist on the distinction, but both clear the
bar: R10 asks for roughly eight and the cell has twelve. So the re-scope question is
no longer "is there enough depth", it is only "is payout shape the right conditioning
variable." If yes, R10 is unblocked today.

**R10 is also orthogonal to the parked satellite question, which I had wrong
earlier.** It was carried as gated behind R13. It is not. Reducing duplication on a
one-paid WTA satellite at a 118-median field does not require knowing whether the
satellite leg is +EV on cash after promotions, and R10's own justification already
says clearing the cut line unduplicated is the mechanism for exactly these contests.
That makes R10 the only major board item waiting on no parked measurement and no open
decision. `own_lineups_duplicated_by_field` is populated for all 97 mined contests,
so the grading substrate exists.

Carry forward the two limits: "archetype" is undefined at this depth (8 contest
families, 25 distinct field sizes from 15 to 297), and meeting the slate count is not
meeting R10's bar, which is beating flat-12 before any production column flips.

## 2. The satellite leg is parked as PARTIALLY MEASURED; do not grade R13 on it

Ledger 3.14, corrected 2026-07-29. The entry-history export carries only
`Entry_Fee`, `Winnings_Non_Ticket`, and `Winnings_Ticket`. A third channel exists
and the export cannot see it: DraftKings promotional benefits tied to ticket
acquisition and to contest-entry volume. Ben's correction, and it plausibly runs
opposite to the cash result, because a $0.01 satellite is the cheapest available
unit of "contest entered" and any promotion keying on entry or ticket counts is
served far better by 4,201 penny satellites than by 678 dollar contests.

Ben's call on 2026-07-29: **leave it unmeasured.** No promotional record gets
pulled for now. Consequences to respect:

- The satellite leg's -$244.45 is a cash-only figure. It is not the result of the
  strategy and must never be quoted as one.
- Any earlier reading of mine that "the satellites are the loss" is withdrawn.
- **R13 therefore has almost no decidable surface left.** The satellite block is
  86% of MLB entries and is now explicitly ungraded, and the remaining
  non-satellite line is 678 entries at $301.01 fees against $247.15 cash, which is
  a small sample of observed outcomes and is not evidence of an edge in either
  direction. R13 should stay open, and the next thing that moves it is graded
  non-satellite slates accumulating, not another pass over this export.
- The $175 of unresolved ticket face is **held inventory, not a loss.** Several of
  those Best Ball contests have not commenced (NFL from September 2026, NBA from
  October). Re-export the entry history after they settle and it resolves in the
  record. Nobody needs to chase it before then.

## What is ready and waiting on Ben, unchanged from the earlier fragment

The nine recurring satellite families with observed `ticket_count` values are in
ledger 3.14, ready to become `dk_contest_archetypes.csv` rows. I did not write
them because `ticket_count` reaches `resolve_contest_shape` and reranks lineups.
Given that the satellite volume is now explicitly an open question rather than
something to cut, this input is more likely to matter than it looked this morning:
if the satellites are staying, routing them to the right objective is exactly the
work that pays. Still Ben's dated decision.
