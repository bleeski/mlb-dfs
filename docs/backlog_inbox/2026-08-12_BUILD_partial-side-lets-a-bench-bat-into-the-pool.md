# 2026-08-12 BUILD: a PARTIAL side put a non-playing bench bat into 6 of 18 certified entries

Slate `1840_3g` (CLE@DET, PIT@MIA, CHC@WSH), 18-entry apex Classic. First build
certified all three gates and carried Eduardo Valencia (43812994, DET, C, $4500,
APPG 9.07) in 6 of 18 entries. Valencia is not in tonight's posted DET lineup.
Dillon Dingler is. Nothing in the three gates or in `preflight_upload` catches it,
because DK lists Valencia as active: he is rosterable, just not playing.

Rebuilt with him excluded at intake and redelivered; that file is the record
(sha256 `df7cd44e...`, run `20260812T221445Z_fd09a632`). The superseded one is
sha256 `fadcd669...`, run `20260812T215414Z_ef7fa730`. Four findings, in the order
they bite.

## 1. `lineups_from_paste.py` calls a complete lineup "partial"

The operator paste held all nine DET slots. The ninth, Corey Julks, has no DK
salary row. The tool reported:

    "team": "DET", "hitters_posted": 8, "reason": "mlb.com posted a partial lineup"

That reason is false. mlb.com posted a complete lineup; DK did not roster one of
its players. The tool already distinguishes these two facts one field away, in
`unrostered_starters`, and its own policy text says absent-from-DK "is reported
per name and never fatal on its own." Then it collapses both into
`lineup_status: partial` anyway, and R60's TBD routing does the rest.

Suggest a third status, or at minimum a truthful `reason` when
`hitters_posted + len(unrostered_starters) == 9`, so a downstream reader can tell
"nine posted, eight rosterable" from "eight posted, one still to come."

## 2. Being PARTIAL costs the side its posted batting order, then invents a hitter

DET routed through the TBD path, which is R60 working as written: posted hitters
stay `Projected_Starter` and F2 comes from the platoon reference, not the posted
slot. Two consequences on this slate:

- F2 was wrong for every DET hitter. Engine order vs posted order: McGonigle 1st
  (posted 3rd, F2 1.10), Torres 2nd (posted 1st, 1.08), Dingler 3rd (posted 2nd,
  1.07), Lee 6th (posted 4th, 1.00), Malgeri 9th (posted **6th**, 0.91). Slot 4
  empty. Spread is only 1.10-0.91, so each miss is small, but every one of them
  was avoidable from information the build already had in hand.
- The TBD path seeded a ninth DET hitter from `fangraphs_platoon_lineups.json`
  (7.9 days old, past its 7-day limit, warned and shipped per R27). It picked the
  highest-APPG DET bat available, which is exactly the bench catcher. He is
  cheaper than Dingler ($4500 vs $5600) and higher APPG (9.07 vs 8.63), so the
  optimizer took him in a third of the portfolio. This is the failure mode
  CLAUDE.md already describes in words; R60's guard stops a bench bat from
  *displacing* a posted starter from the pool, but here nothing was displaced.
  The bench bat was *added* as the ninth fill and then won the C slot on value.

The seeded ninth hitter is a labeled prior standing in for an unknown. It should
not be selectable at the same weight as an observed posted starter, or a partial
side should seed no ninth hitter at all.

## 3. A confirmed side with eight rosterable hitters cannot certify

Marking DET `confirmed` with its 8 rosterable posted starters is the fix that
solves 1 and 2 together: no invented ninth, and F2 stamped from real slots. The
intake accepts it (`is_confirmed` reads `lineup_status` only, no count check).
Certification does not:

    POOL BLOCKER: DET: 8/9 hitters after dropping [15 IL arms/bats];
    the team cannot fill a stack

"Cannot fill a stack" is false. DK caps a stack at 5 hitters and DET has 8. And
CLAUDE.md's stated bar is "a team matching fewer than 5 of 9 salary hitters is a
blocker, not a warning" — 8 clears it. The blocker appears to fire on `< 9`. Note
the message also lists IL *pitchers* (Flaherty, Olson, Verlander, River Ryan,
Jake Miller) as reasons a team is short of nine *hitters*, which makes it read
worse than it is.

## 4. Neither documented override gets past it

Both escape hatches were tried and both failed:

- `--ignore-pool-blockers` let the build proceed, recorded the override in the
  brief, and then the pre-export gate independently re-read the same pool report
  and failed: `gate lineup_gate_passed: pool report: 1 blockers, 1 team(s) under
  nine hitters (DET)`.
- `--assume-gates lineup_gate_passed` did not suppress it either. Same error:
  `Failed pre-export gate: lineup_gate_passed`.

A flag documented as "build anyway and have the override recorded" that a later
gate re-blocks on the identical fact is a flag that does not do what it says. If
the intent is that this blocker is never overridable, `--ignore-pool-blockers`
should refuse it by name up front instead of spending the build.

Also worth noting, since it changed the shape of the fix: with DET confirmed the
feasible set narrowed and the engine named two structural floors in sequence,
`max_sp_pair_repetition >= 3` (8 distinct pairs x 2 < 18 entries) and then
`max_shared_players >= 7`. Both hints were exact and arithmetic, and that part of
the system worked well.

## What shipped tonight instead

`skills/generate-lineups-workspace/build_apex.py` gained `--exclude-ids`, a
comma-separated intake drop for a player DK lists as active who is absent from
the posted lineups. It is an eligibility correction from the operator's own
paste, never a compute shortcut, and it prints to stderr and lands in the brief's
pool warnings. Untracked driver, outside the audited engine, so no engine path
was touched during the slate.

Result of the rebuild, same posture and same controls, only Valencia removed:
10 distinct SP pairs (was 9), 10 primary-stack shapes (was 7), top stack exposure
22% (was 28%), 14 unique lineups of 18 (was 11), all three gates genuinely
passed, no overrides and no assumed gates.

That flag treats the symptom. 1 through 4 are the disease and they are DEV's.
