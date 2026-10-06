# `--stack-sleeve`: a named secondary stack, through certification (R434, Classic only)

One entry (or a named few) carries a team YOU name as a SECONDARY stack: at least `min` of its
hitters under a different, strictly larger primary stack. It runs through the allocator, so every
portfolio cap binds it jointly and F-3 holds, and the build records it. It is an operator's
strategy preference (Ben, 2026-09-23, "what if our priors are wrong"): a construction rule, never a
prediction, an edge or a probability. It replaces hand-solving the lineup around certification
(1410_4g, entry 5267953193), which cost the caps their joint enforcement and the record its lineage.

```bash
python skills/generate-lineups/scripts/build_slate.py ... \
    --stack-sleeve '{"team": "MIA", "min": 3, "entries": 1, "contest_id": "195996455"}'
```

## Grammar

| Key | Meaning |
| :--- | :--- |
| `team` | required. The DK team code as the salary file spells it; stored upper-case. |
| `min` | 2 or 3, default 3. A secondary is STRICTLY smaller than its primary, the primary is at most 5, a roster has 8 hitter slots: 4 would need 4 + 5 = 9, 5 is the primary stack itself. |
| `entries` | whole number >= 1, default 1. |
| `role` | `"secondary"` only (default). A named PRIMARY is not built here; R422's tail seat is the engine's primary-role seat and it is ranked by the market. |
| `contest_id` | optional. Without it the seats go to the largest top-heavy contest (two or more entries, not a cash or single-entry posture), then by contest id, on the last entry ids the tail seat did not take. With it the seats go there, shape test waived. |

Exit 4 before anything is staged (`cli_value_invalid`, flag `--stack-sleeve`): not a JSON object, an
unknown key (a typo like `entires` would otherwise become a silent default), bad types, `min` outside
2 or 3, `role: "primary"`, `entries` < 1, and, when both files can be read, a team with no hitter in
the salary file, more `entries` than the entries file has rows, a `contest_id` not in it, and a
Showdown slate. A well-formed seat the slate merely cannot seat is NOT refused: it is relaxed and
counted.

## What "secondary" means

A lineup qualifies when it carries at least `min` hitters of the named team (through
`controls["player_team_by_id"]`, the map R343's team footprint reads) and its recorded primary stack
is a DIFFERENT team and STRICTLY larger. Strictly, because both primary readers break a 3-3 split
alphabetically; an unmeasured primary size never qualifies. R343's `max_team_exposure_pct` counts a
3-man secondary as footprint on both teams; `max_primary_stack_exposure_pct` counts only the primary.

## What the build does

- **Bank.** The ordinary grid builds only per-team primary jobs, so a new job family
  (`extend_bank(secondary_stack=(team, m))`, `build_sleeve_jobs`) stacks every OTHER team and carries
  exactly `m` of the named team's hitters (`bringback_constraint`). Depth-only: it counts what the
  bank already holds and builds the shortfall, at least one lineup per primary team that could carry
  it. Its own cache bucket (`sec:` in the conditions signature); a constraint on the lineup, never a
  trim of the pool.
- **Seat.** Stamped on the entry requirements after the tail seat (`stack_sleeve_team`,
  `stack_sleeve_min`) and confined through the sleeve mask like R422's tail seat.
- **Unmeetable is relaxed and counted, never a refusal.** No qualifying lineup or too few distinct
  ones: the entry falls back to the weights (`fallbacks`, `relaxations`). `classic_sleeves: false`
  (the T-15 rung): the seat is dropped by name. The joint solve proven infeasible with the seat
  active: one ladder step after the five-stack quota and before the pair seat drops it, counted
  (`stack.status: relaxed_by_ladder`). F-3 never relaxes.
- **Not carried.** The R389(b) baseline (its controls turn every sleeve off) and a late swap (it
  re-solves authorized entries with no stamps, so an authorized sleeve entry can lose the team; the
  delivery record names the entry, `extra.stack_sleeve.outcome.seated`).

## Where to read it

The brief's `exposure.classic_sleeves` (`request.stack`, `stack`, the jobs) and the `sleeves:` stderr
line (`stack MIA>=3 secondary: 1 of 1 seated`); the tracked delivery record's `extra.stack_sleeve`
(request, `team_by_entry`, outcome by entry id). V/S/P: S. No V check reads a stamp.
