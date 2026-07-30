# Fragment: the portfolio has no primary-stack SIZE control

Session: ARCHIVE, 2026-07-30, after mining A-027 and A-028 (37 contests).
For: DEV, whose `docs/` and `mlb_engine/` are. Full working in
`ledger/2026-07-30_field_shape_analysis.md`.

## The observation

Across 53 Classic contests with at least 40 parsed entries (43,045 field
entries), one construction has a within-contest top-decile lift whose bootstrap
interval excludes zero on the upside:

    5-2-1   +3.1pp  [+1.2, +5.1]   field share 25.1%   our share 0.0%

It holds in every slice tested: satellites +3.4 [+1.1, +5.8], non-satellite GPP
+1.6 [+0.1, +3.1], fields <=150 +3.3, 151-500 +4.1, >500 +1.5.

Paired inside contests where we had entries, our 5-stack share is 6.5% against
the same contests' field at 44.2% and their winners at 52.2%. We stacked 5 less
than the field in 63 of 69 contests.

The one 5-stack shape we DO build is 5-3, at 16.0% of our Classic entries, and
it is the member of the 5-stack family with no measurable lift (-0.1pp,
interval spanning zero).

The engine is right about the downside. "3 or fewer primary" is reliably bad
(-2.8pp, [-4.1, -1.5]) and we build it 6.4% against a field at 28.0%.

## Why it happens (this is the part worth arguing about)

Not a bug. `MAX_HITTERS_PER_TEAM = 5` permits the shape.
`PRIMARY_STACK_MIN_HITTERS = 3` only *identifies* a primary stack at 3+.
There is no constraint that targets primary stack **size** anywhere in the
solve. The only stack control in `STRATEGY_DEFAULTS` is
`max_primary_stack_exposure_pct` (0.35 on `wta_satellite`), which caps how many
entries share a primary stack **team**.

The objective is projected points. Correlation is not in it. The fifth bat of a
stack projects below the best available isolated bat, so a mean-maximizing MILP
declines it every time, and the 35% team cap then spreads the portfolio, which
mechanically yields 4-2-1-1 and 4-3-1. Our top shape is 4-2-1-1 at 32.1%
against a field at 7.2%.

## What I am NOT claiming

- Not that we underperform. Our finish is indistinguishable from the field
  median in every archetype (all bootstrap intervals contain 50.0), and our
  top-decile rate is 11.8% against a 10.0% base.
- Not that a mix change is worth +3.73pp. That number is arithmetic applying
  the archive's observed lifts to a different mix. It assumes the lift survives
  us building the shape at volume, and portfolio caps are exactly the thing
  that could break it. A 35% primary-stack exposure cap and a mandated 5-man
  primary stack fight each other on a short slate.
- Not that the salary gap is separate. Our Classic median salary left is $100
  against a field at $200 and winners at $300, but a 5-2-1 costs differently
  than a 4-2-1-1, so this may be the shape gap in another coordinate.

## Suggested shape of the work, for DEV to accept or reject

A `primary_stack_min_size` posture parameter, defaulting to today's behaviour
(no floor), that a posture can raise to 5 for some share of the bank. The
interaction to think about first is feasibility: a 5-man floor plus the 35%
team cap plus `max_shared_players` on a 3-game slate may have no solution, and
the relaxation ladder currently has no rung for it. Whatever lands should count
its relaxations like Showdown does, because a portfolio is not clean because
the gates passed.

Worth deciding before building: whether the target is the shape (5-2-1
specifically) or the size (any 5-stack). The archive says the shape, since 5-3
carries no lift, but that distinction rests on 53 contests.

## Separately, a small one

`tools/net_to_date.py` prints an inconsistent TOTAL. Per-date rows sum
`fees_total` over all rows (line 109); the TOTAL line sums over `graded`, which
requires both a fee and winnings (line 86). The date column now sums to $64.21
while TOTAL prints $51.46. The date rows are the correct ones. Fragment:
`docs/backlog_inbox/2026-07-30_archive_net-to-date-total.md`.
