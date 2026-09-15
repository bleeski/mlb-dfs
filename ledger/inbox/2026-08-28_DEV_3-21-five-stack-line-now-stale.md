# 3.21's five-stack sentence went stale the same day it was written

DEV, 2026-08-28, on a `ledger` claim scoped to the Quick Card pin line ONLY.
Filing rather than editing, because section 3.21 is calibration content and that
is ARCHIVE's to reconcile in place.

## The line

Section 3.21, under **Classic — stack shapes**, ends:

> `min_five_stack_share_pct` ships 0.0 in every posture; nothing in the build
> asks for a five-man primary.

Both halves were true when written and the second half is now false.

## What changed

Ben's dated go-live decision of 2026-08-28 took R37(2)(a) and R37(2)(b) live
against this very section as the measured tranche. Shipped the same day
(CHANGELOG.md carries the `Decided` entry and the shipped entry):

- `primary_stack_min_size = 5` on a portfolio whose every contest resolves
  `payout_breadth <= 0.02`, on slates of 3+ games. 1-2g exempt, on this
  section's own counter-case (5-3 +16.5pp, 4-4 +12.0, 5-2-1 flat at +1.4).
- `min_five_stack_share_pct` derived as 0.75x the measured five-stack field
  share for the slate-size bucket, clamped to 15-25%, on breadth 0.10-0.22.
  At this section's measured 25.7% on 5g+ that is 19.3%.

The first half of the sentence is still literally true and should stay: the
POSTURE dict in `execution_pipeline.STRATEGY_DEFAULTS` does still ship 0.0
everywhere. The quota is added at the control MERGE, per contest, keyed on
breadth and slate size, because a posture is blind to both axes this file's own
conditioning rule requires. A test pins the posture default at 0.0 precisely so
that stays true.

Suggested reconciliation, ARCHIVE's wording to choose:

> `min_five_stack_share_pct` ships 0.0 in every POSTURE and is now supplied at
> the control merge per contest, on Ben's dated decision of 2026-08-28 (R37(2),
> keyed on this section's own measurements). This gap is what that decision
> closed.

## Two things this section is now the upstream source for

1. **Its measured field shares are a live engine input.** The 1-2g / 3-4g /
   5-6g / 7g+ five-stack shares are mirrored in
   `execution_pipeline.FIVE_STACK_FIELD_SHARE_MEASURED`, stamped
   `FIVE_STACK_FIELD_SHARE_MEASURED_AS_OF = "2026-08-28"`, and every brief names
   `source: ledger_measured` when they answer. If a later mine moves those
   shares, the engine's fallback is stale and says so but does not know it. The
   intended fix is the rollup below, not an engine edit.

2. **The rollup this section implies does not exist yet.** The quota prefers
   `data/reference/stack_shape_field_shares.json`, schema
   `{"computed_at": <iso>, "five_stack_share_by_slate_bucket": {"1-2g": f,
   "3-4g": f, "5-6g": f, "7g+": f}}`. Nothing produces it.
   `field_miner.mine_contest` writes the per-entry `stack_pattern` string, but
   its `construction` block carries only `max_stack_histogram` -- the scalar
   primary size, not the partition -- so the shares have only ever been computed
   by a throwaway in `tools/_scratch_archive0822/`. Filed as R37(2)(c)'s open
   remainder and flagged there as ARCHIVE's, since `data/reference/` is
   ARCHIVE's write set. Note the registration trap recorded in that entry: a new
   reference file must reach `refresh_reference_data.py`'s `TRACKED_JSON`, not
   just `reference_manifest.json`, or nothing will ever age it -- the same hole
   that let `fangraphs_platoon_lineups.json` drift unmeasured.

## Also for this file's Showdown half

3.21 reports our SD pitcher-CPT share at 40% against winners at 65.5%. A bound
worth carrying into any future reading of that gap: on a slate with two declared
arms, pitcher-CPT share cannot exceed `2 * floor(cpt_cap * n) / n`, because the
captain cap is per PLAYER. At the shipped 0.25 cap that is 42.1% at n=19, 36.4%
at n=11, 50.0% at n=20, and it averages 45.0% over n=9..24. So the 65.5% winner
share is not a reachable target for our portfolio under the current cap, and the
root doc's proposed 48-52% band sits above the maximum at most entry counts. The
delivered share is now printed beside that ceiling on every Showdown brief
(`construction_shadow.pitcher_cpt_ceiling_pct`), which is the number to grade
against over Ben's ~12 conditioned slates. Nothing here is a probability claim;
the ceiling is arithmetic and the shares are observed.
