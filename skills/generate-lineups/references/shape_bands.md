# The shape bands on a mixed entered set (R483)

Read this when a brief's `shape_bands` block names a contest under `not_carried`, when
`primary_stack_floor.by_contest` or `five_stack_quota` shows a relaxation, or before
overriding either band.

## The rule (R37(2), Ben 2026-08-28; R483, 2026-10-13)

Two construction bands, routed per contest by payout breadth and slate size, labeled
priors from ledger 3.21 and never a claim about outcomes:

- **Floor 5** (`primary_stack_min_size`): every entry in a narrow-breadth contest
  (breadth <= 0.02: WTA, one-seat satellites, solo shots, mme_gpp, single_entry_gpp)
  carries a primary stack of 5 or more. 1-2 game slates are exempt, and an unmeasurable
  slate size leaves it unavailable.
- **Quota** (`min_five_stack_share_pct`): a share of the mid-breadth contests' entries
  (breadth 0.10-0.22: large_field_gpp, portfolio_gpp, small_field_gpp, ticket satellites)
  carries a five, sized at 0.75 x the measured field share and clamped to 0.15-0.25.

**Each band binds the entries of the contests that declared it.** When every contest
declared it, the portfolio scalar carries it exactly as before R483. When the set is
mixed, the merge keeps the scalar at the least demanding value and carries the rest in
`primary_stack_min_size_by_contest` and `min_five_stack_share_pct_by_contest`:

- The floor masks only those contests' entries.
- The quota is one row over those contests' entries, pooled, at the least demanding
  share among them. A satellite's fives never count toward a GPP's quota, and a cash
  contest is touched by neither band.
- The bank is asked for fives whenever either map is present, on every door.

## The escape

A typed scalar is the answer for every entry and retires its map:

```bash
python skills/generate-lineups/scripts/build_slate.py ...     --controls-override '{"min_five_stack_share_pct": 0}'    # quota off everywhere
python skills/generate-lineups/scripts/build_slate.py ...     --controls-override '{"primary_stack_min_size": 4}'      # floor 5 off everywhere
python skills/generate-lineups/scripts/build_slate.py ...     --controls-override '{"min_five_stack_share_pct": 0.5}'  # a five on half of ALL entries
```

The `_by_contest` maps are derived, not typed: an override naming one is refused by
name at exit 4 before anything is staged, by `build_slate.py` and `late_swap.py`
alike. A late swap applies the same escape on top of the parent's recorded controls.
`--never-relax` refuses the bands too, because the allocator's ladder relaxes them.

## Relaxation (never a refusal: an S control never costs the file)

- A contest whose entries hold no compatible five in the bank is relaxed off before
  the solve, counted, and the step says whether the bank was ever asked for one.
- On a proven infeasible joint solve, the quota steps first (its own ladder: the
  share, then 0.15, then off), then the seats, then the contest floors (all off, one
  counted step), then the portfolio floor's rungs.
- A quota whose share floors to 0 entries over its contests reports `off`, not applied.

## Where to read it

- The brief's `shape_bands.application`: per band, `scope` (`portfolio`, `contests` or
  `none`), `carried_by`, `not_carried` with the reason, and `realized` (need, assigned,
  relaxations).
- `primary_stack_floor.by_contest` and `five_stack_quota` (`scope`, `contests`,
  `scope_entries`, `assigned_qualifying`, `need_met`) on the run result.
