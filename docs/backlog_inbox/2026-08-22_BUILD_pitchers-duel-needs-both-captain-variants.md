# Pitchers-duel thesis needs both captain variants, not just both rosters

Raised by a BUILD session, slate 2026-08-22 tag `1335_1g_sd` (TOR @ NYY
Showdown, 19 entries). Create-only fragment; the owning role merges and
deletes it.

## Ben's rule (2026-08-22)

> When we think of a "pitchers duel" game thesis for showdown we need to
> include both pitchers, and if we have enough lineup slots in our portfolio
> we should have at least 2: one where each P is captain and the other is
> UTIL. We can have more if it makes sense, but two lineups (one with each as
> captain and the other as util) should be the minimum.

## What already works, what doesn't

`duel()` in `mlb_engine/optimize/showdown_theses.py` (~line 282, added R156
2026-08-21) already hard-locks both starters into every `pitchers_duel`
lineup regardless of who captains it (`hard_locks = list(both_sp)`, never
filtered by `cpt`, survives every rung of `solve_ladder`'s relaxation
ladder). So "both pitchers rostered" is solid today. Confirmed on tonight's
delivered entry 5226658789: captain Ryan Weathers, Dylan Cease at UTIL.

What's missing is the SECOND lineup with the captain flipped. Two separate
gaps, both in `build_thesis_ladder` (same file, ~line 415):

**1. No allocation floor.** `pitchers_duel` is one row among 13 templates,
weighted 0.45 within the 18% `NEUTRAL_SHARE` slice and apportioned by
`_largest_remainder` same as everything else. Tonight it landed on exactly 1
slot out of 19 entries. R156's own comment already flags this: "A single
slot cannot hedge which arm ends up captaining... whether this template
clears a second slot at a given n still depends on how its share lands
against the other ten." Nothing forces a second slot when both starters are
live, no matter how large the portfolio.

**2. Repeated occurrences of the same thesis don't rotate captains.** Even if
`pitchers_duel` DID land 2 slots, the captain picked for each occurrence
comes from this loop (~line 462):

```python
cpt = None
for cand in built.get("cpt_ladder") or []:
    if cap is None or cpt_counts.get(cand, 0) < cap:
        cpt = cand
        break
```

This only skips a candidate once he's AT THE GLOBAL EXPOSURE CAP (4 of 19
tonight, 25%). It has no memory of "already used as captain for THIS
thesis id", so a second `pitchers_duel` occurrence would walk the same
2-element `cpt_ladder = list(both_sp)`, find the first starter still under
cap (true after just one use), and pick him AGAIN. Two occurrences of the
same template only ever get a different roster today because
`solve_ladder`'s overlap bound (`max_shared_players`) forces different
filler hitters -- the `(variant 2, ... captain)` naming at line 481 proves
the mechanism can produce a same-captain variant, since it labels whatever
captain the loop actually picked, not a guaranteed-different one. Tonight's
own delivered ladder shows this on a directional template: entry 1
("TOR win big - starter carries it") and entry 14
("TOR win big - starter carries it (variant 2, Dylan Cease captain)") both
captained Dylan Cease -- the "variant" was entirely in the four supporting
hitters.

Net effect confirmed live tonight: with only 1 slot, `pitchers_duel`
captained whichever starter sorts first in `shape["teams"]` (Ryan Weathers,
NYY < TOR) -- a team-name-ordering artifact, not a scored choice. Getting a
Cease-captain / Weathers-UTIL lineup into the portfolio took a manual
post-hoc solve (`build_showdown_lineup` with `cpt_lock=Cease,
locks=[Weathers]`, hand-patched into entry 5226658792) because nothing in
the ladder would have produced it on its own even at higher `n_entries`.

## Suggested fix, two parts matching the two gaps

**Allocation floor.** After `counts = _largest_remainder(weights,
n_entries)`, if the `pitchers_duel` spec is live (`duel()` returned
non-None, i.e. both starters declared) and the portfolio can afford it
without zeroing out other templates that would otherwise get a slot, raise
`counts[pitchers_duel_idx]` to at least 2, borrowing the marginal slot from
wherever the remainder apportionment ranked lowest. "Can afford it" needs a
real threshold -- Ben's own phrasing ("if we have enough lineup slots") says
this is conditional, not absolute; a 1-entry Solo Shot contest obviously
keeps today's single-slot behavior. Where that line sits is DEV's call, not
dictated here.

**Per-thesis captain rotation.** Give the captain-selection loop a second
piece of state alongside the existing global `cpt_counts`: which captains
have already been used for THIS thesis id. On the first occurrence, walk
`cpt_ladder` as today. On the second (and later) occurrence of the SAME
template id, skip any candidate already captained for that id (in addition
to the existing cap check) before falling back to allowing a repeat. For
`pitchers_duel` specifically, with a 2-element `cpt_ladder`, this
deterministically gives occurrence 1 the first starter and occurrence 2 the
second -- exactly Ben's "one where each P is captain and the other is UTIL."

Note this second piece is a general mechanism, not `pitchers_duel`-specific,
and would also change today's directional-template behavior (entry 1 /
entry 14 above would stop sharing a captain). That's a larger behavior
change than Ben asked for here -- worth a separate call on whether to scope
the fix to `pitchers_duel` alone (e.g. a per-template flag) or apply it
everywhere. Flagging the choice, not making it.

## Worked example from tonight, for a test fixture

TOR @ NYY, Dylan Cease (TOR) vs Ryan Weathers (NYY), 19-entry portfolio,
25%/4-count captain cap. Minimum-viable `pitchers_duel` allocation of 2 should
produce:

- Occurrence 1: captain Ryan Weathers, UTIL Dylan Cease + 4 cheapest-fitting
  bats under the salary left after both arms (as delivered: Kirk, Bateman,
  Cameron, Guerrero Jr., $49,300).
- Occurrence 2: captain Dylan Cease, UTIL Ryan Weathers + best remaining
  legal 4 (as hand-solved tonight: Okamoto, Clement, Bateman, Cameron,
  $49,900, proxy 82.25 vs occurrence 1's 72.47 -- Cease-captain scores higher
  as a standalone proxy since his Base far exceeds Weathers', so today's
  team-order-driven single pick undersells the thesis's own ceiling case
  about as often as it sells it short).
