# The Quick Card's R37(2)(a) reading goes stale with R483 (shape bands per contest)

DEV, 2026-10-13, Session 152 (R483). Filing rather than editing, because the
ledger is ARCHIVE's to reconcile in place.

## The line

The Quick Card's R37(2) note, under FIRST, reads:

> It is 5 on a portfolio whose every contest resolves `payout_breadth <= 0.02`
> ... on a slate of 3+ games, and 4 otherwise -- including on any MIXED entered
> set, because R34's floor merge takes the least demanding declared value and
> one broad-payout contest retires the floor for the whole portfolio. ... the
> brief's `shape_bands` block is what says which and why;
> `floor_5_binds_portfolio` is the one-line answer.

## What changed (CHANGELOG 2026-10-13, R483)

- **Floor.** On a mixed entered set the floor of 5 now binds the entries of the
  narrow-breadth contests alone (`primary_stack_min_size_by_contest`). The
  portfolio floor stays 4.
- **Quota.** The same holds for the mid-breadth quota. It binds over the mid
  contests' entries only (`min_five_stack_share_pct_by_contest`), pooled, at
  the least demanding share among them.
- **The one-line answer.** `floor_5_binds_portfolio` still means what it says,
  but it is no longer the answer to "which floor did this build run". The
  answer is `shape_bands.application` in the build brief (and on
  `checkpoint_plan.shape_bands`). Its `floor_5` and `quota` entries each carry
  `scope` (`portfolio`, `contests` or `none`), `carried_by`, `not_carried`
  and `realized`.
- **The brief block.** A Classic build brief carries a `shape_bands` key only
  from this commit on. Briefs before it have none, which the 2026-09-15
  fragment found.

## What to reconcile

- **The Quick Card.** Replace "including on any MIXED entered set ... retires the
  floor for the whole portfolio" with the per-contest rule, and point at
  `shape_bands.application`.
- **Archived briefs.** A mixed-set build before 2026-10-13 ran with neither
  band. Read it as "floor 4, no quota" whatever its contests declared.
- **Grading.** A grade that splits by shape band should condition on
  `scope`. A narrow contest in a mixed file carried floor 5 after this date and
  not before.
