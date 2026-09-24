# Tail seats should scale with coverage, per contest (R406 follow-on)

Ben, 2026-09-24, on 1410_4g: grow the portfolio's inclusion of tail outcomes
with the number of lineups entered and shrink it with the number of games on
the slate. Comfortable outcomes at low N on big slates; lower-likelihood
outcomes as N grows and the slate shrinks.

## Premise, checked against the tree

`classic_sleeves.py` sleeve weights are a function of posture ONLY:
40/20/20/20, or 30/20/30/20 for WTA, and projection-only for cash and single
entry. Neither entries nor games enter. No sleeve is a tail sleeve. The
environment sleeve takes the TOP 2 games by implied total, which is the
opposite of a tail. Chalk-fails caps consensus bats but still maximizes the
same projection. So on 1410_4g no mechanism could have produced a MIA stack
(3.13 implied, 0.74 runs below the next team). It was hand-solved.

## Proposal

1. **Measure before building (ARCHIVE).** Split mined GPP winners by slate
   size (games) and field size, never pooled. For each cell, record the
   implied-total rank of the winners' primary-stack team: how often did it
   come from the bottom third? These are observed outcomes. They tell us
   whether a tail rule has support and at what slate sizes.
2. **The rule: coverage, not a probability.** Let S = stackable teams on the
   slate (about 2 x games). Let N_c = entries in contest c, and N = entries in
   the portfolio. Tail seats open only once the comfortable set is covered.
   Once N/S passes 1, every team gets a primary stack somewhere in the
   portfolio, and uncovered teams fill in ascending order of implied total.
   Within a contest, tail seats go only to top-heavy shapes
   (large_field_gpp, large_wta), largest field first. Cash, double-up,
   satellite and single-entry get zero, whatever N is.
3. **Implement as sleeve weights = f(N_c, N, S, contest_shape)** plus a
   `tail` sleeve that seats bottom-implied stacks. Define tails by the
   MARKET's implied totals, not by the ownership prior. The market is the
   best-calibrated input we have; the ownership prior's first grade had a
   mean signed error of -10.44.

Truthful labels: this is a deterministic coverage rule over labeled priors.
It carries no claim about how often a tail wins.
