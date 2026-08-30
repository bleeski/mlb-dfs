> **RETAINED — DO NOT DELETE ON AN INBOX SWEEP.** This fragment is not
> unconsumed; it is KEPT by design, and has been through three inbox passes
> (2026-08-16, 2026-08-27, 2026-08-29). `docs/backlog.md` names it as the SOLE
> CARRIER of the nine-family table below and of the four cautions in "Four
> things to get right on the way in," which exist nowhere else in the project.
> The inbox contract says the owning role merges and deletes consumed
> fragments; this one is exempt until ARCHIVE writes the rows into
> `data/reference/dk_contest_archetypes.csv` (Tier 4, R1c-tail) and the
> cautions land with them. Referenced from `docs/backlog.md` at R1c-tail,
> R10's step 1, R40, and R196(a).

# Ben's dated decision, 2026-08-09: add the nine ledger-3.14 satellite families to the curated archetypes table

**For ARCHIVE to execute.** Filed by DEV because the decision came in a DEV
session; `data/reference/dk_contest_archetypes.csv` is ARCHIVE's write surface,
not DEV's, so nothing here has been written.

## The decision

Ben has decided, on 2026-08-09, that the nine recurring satellite/qualifier
families in ledger section 3.14 go into the curated archetypes table with the
`ticket_count` values actually observed in the entry-history export.

This is the input R1(c) has been waiting on and the one ARCHIVE deliberately
declined to write on 2026-07-29. That refusal was correct at the time and the
reasoning still holds: a curated `ticket_count` reaches `resolve_contest_shape`
immediately, where 1 routes to `wta_ticket_satellite` and anything else takes
the ticket-line blend, which reranks lineups on contests entered that night.
That makes it a strategy change rather than an archival write, and it needed
Ben's dated decision. It now has one.

## The table, from ledger 3.14

For a satellite, the observed `Places_Paid` IS the ticket count awarded.

| target family (name substring) | sport | entries | fees | observed ticket_count | median field |
|---|---|---|---|---|---|
| `Pocket Cup` MEGA Qualifier | MLB | 2,915 | $29.15 | 1 (2,475), 5 (200), 10 (240) | 237 |
| `Knuckleball` (Midseason Best Ball $5) | MLB | 207 | $36.45 | 1 | 23 |
| `FBWC` Qualifier | MLB | 193 | $19.30 | 1 | 111 |
| `Best Ball $25 Millionaire` | MLB / GOLF | 380 / 115 | $65.45 / $31.50 | 1 (both), 5 (1 GOLF) | 149 / 118 |
| `Relay Throw` | MLB | 215 | $30.20 | 1 | 166 |
| `Fantasy Football Millionaire` | MLB | 87 | $15.60 | 1 (60), 2 (19), 5 (8) | 59 |
| `Golf Millionaire` | GOLF / MLB | 167 / 168 | $45.50 / $51.90 | 1, 4 (1 GOLF) | 118 |
| `Sand Trap` (PGA $25) | GOLF | 86 | $16.70 | 1 | 118 |
| `FGWC` Qualifier | GOLF | 8 | $3.00 | 1 | 63 |

## Four things to get right on the way in

1. **Three families are not single-valued and must not be written as if they
   were.** `Pocket Cup` has been observed at 1, 5 and 10; `Fantasy Football
   Millionaire` at 1, 2 and 5; `Best Ball $25 Millionaire` and `Golf
   Millionaire` each carry a second value on one GOLF entry. A single curated
   `ticket_count` for those families asserts something the history contradicts
   on hundreds of entries. Whatever encoding is chosen, the multi-valued case
   should resolve to the modal value with the variance recorded, or stay
   UNRESOLVED and let the contest page settle it — not silently pick one.
2. **The `SUPERSat` correction from 3.14 applies to the matching.** A
   `satellite` substring filter misses `SUPERSat` and undercounts the block by
   17 entries. Patterns written from this table inherit that gap unless the
   matcher is checked against it.
3. **Check the competing-pattern behaviour before adding nine patterns at
   once.** `posture_by_contest` already records `matched_pattern` and
   `competing_patterns`, so a new pattern that shadows an existing one is
   observable; it is much cheaper to see that on the bench than at T-10.
4. **Two GOLF-only families are in the table** (`Sand Trap`, `FGWC`). They are
   fine to curate as observed history, but they are not this engine's domain and
   should not be quoted in an MLB decision.

## Why this matters now, and what it unblocks

R40 (one-seat satellite profile routing) is currently undecidable partly because
`paid_places` is null for both of the rank-1 satellite contests it traced — in
the mined records and in `contest_library` alike. This write is what gives that
routing key real values. R40's own routing decision stays Ben's and stays
separate; do not treat this fragment as authorising it.

## Labels

Observed history from a completed export. The `ticket_count` values are observed
`Places_Paid`, not inferred. Nothing here is a win rate, a cash rate, an ROI
figure, or a probability claim, and nothing auto-applies.
