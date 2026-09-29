# late_swap.py cannot carry declared pitchers (BUILD, 2026-09-29 1400_4g)

The build declared three bulk arms (`--declare-pitcher`): Painter 44321370, Fedde 44321115, Imai 44321357.
`tools/late_swap.py` has no `--declare-pitcher`, so its intake re-surfaces them as PLR blockers and leaves
them out of the pool. At the 16:03 ET window:

- The two entries with Painter locked (5268244944, 5268245048) got `+0 targeted candidates` and
  `no compatible candidate`, because their pinned arm is not in the swap's pool.
- Scoping `--entry-ids` to the 7 other entries still failed: the joint MILP was proven infeasible under the
  inherited and the re-derived caps. The re-certification spans every entry, and the Imai entry's only
  roster-compatible arm is absent too.

Effect: no engine swap was possible for any entry of a slate built on declared arms. Proposal for DEV:
`late_swap.py --declare-pitcher`, defaulting to the parent brief's `declared_pitchers` (R268(a) already
inherits the parent's controls the same way). Refusal records: `data/deliveries/2026-09-29/untagged_20260929T2003*.json`.
