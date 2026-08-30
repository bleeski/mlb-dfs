# Two archetype rows written to `dk_contest_archetypes.csv` (slate 1605_2g, 2026-08-30); one drives inference, one does not

**Short note. The analysis lives in
`2026-08-30_BUILD_standing-data-driven-qa.md` §A and §D; this file records only
what was WRITTEN, so a DEV or ARCHIVE session merging the inbox does not have
to reconstruct it from the other fragment.**

`build_slate.py` refused at exit 3 on contest identity for two names on this
slate. Ben then supplied both real payout tables and instructed the rows be
written. They were, under a claim taken on ARCHIVE's write surface from a
BUILD session at his explicit instruction, which the multi-session contract
otherwise forbids.

## What was appended

Both rows carry the observed field size and full prize curve in `notes`, so a
later session can re-derive `payout_breadth` instead of trusting it.

- **`Micro Booster`** | `wta` | `winner_take_all` | breadth `0.021` |
  objective `wta`. Observed on `MLB 40x Micro Booster [Top 5 Win $10]`
  (194681833): 237 entrants, top 5 win $10 flat on a $0.25 entry, 6th pays
  what 237th pays. The `40x` in the title is the payout multiple, not the
  field size.
- **`Solo Shot`** | `se_gpp` | `broad_micro_gpp` | breadth `0.235` |
  objective `gpp`. Observed on `MLB $1.25K Solo Shot` (194686507): 1486
  entrants, paid to 350th, top 10 hold 43% of the pool and ranks 51-350 hold
  another 43%.

## Validation, which is the part worth reading

Re-ran `build_slate.py` with NO `--postures`:

- `Micro Booster` -> `wta_satellite (name_inference) [matched 'Micro Booster']`. **Lands.**
- `Solo Shot` -> `single_entry (name_inference) [matched 'Solo Shot']`. **Does NOT land.**

Posture inference reads `inferred_type`, not `payout_shape_default`. `se_gpp`
is the truthful value (the entry cap really is 1) and it routes to
`single_entry_gpp`, which is inside `WTA_CONSTRUCTION_SHAPES`. So the row is
correct as a DATA record and does not produce the construction the payout
curve calls for.

**Operator consequence until this is fixed: the Solo Shot family still needs
`--postures <contest_id>=small_gpp` passed by hand.** That is R196's tax,
unchanged after six sightings, and R196's own Fix line proposes the shape
value (`single_entry_gpp`) that causes it.

## Not done here

The `dk_contest_paid_places.json` companion was not touched. Both contests now
have an observed paid-place count (5 of 237, 350 of 1486) that belongs there
too if that file is still the one `--paid-places-from` reads.
