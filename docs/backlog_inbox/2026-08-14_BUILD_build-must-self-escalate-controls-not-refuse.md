# build_slate must self-escalate controls and deliver, not refuse and wait

Filed by BUILD, 2026-08-14, from the 2138_4g late slate.
Priority: this is the highest-value change on the board. It cost a delivery tonight.

## What happened

4-game night slate, 8 entries across 6 contests. Every input was clean: 8 of 8
teams confirmed 9-for-9 off the salary `Starting` column, 8 declared SPs,
handedness patched in, feed age under 3 minutes, zero pool blockers, zero bank
flooring, all five enrichment signals live (F4 72, F1 72, F5 72 non-neutral).

The build refused five consecutive times over 20 minutes, from T-15 to T-8, and
delivered nothing. Ben had to intervene at T-8 and tell me to override whatever
was needed. One more run with every control opened at once certified in 37
seconds on the first try, all three gates green, preflight exit 0.

Logs, in order: `outputs/2026-08-14/_build_late.log`, `_late2`, `_late3`,
`_late4`, `_late5` (all refusals), then `_lateA.log` (certified).

| Attempt | Controls changed | Result |
|---|---|---|
| 1 | defaults | infeasible, named `shared_players_floor` |
| 2 | max_shared_players 6 to 7 | infeasible, no control named |
| 3 | + max_player_exposure_pct 0.35 to 0.38 | infeasible, no control named |
| 4 | + max_sp_pair_repetition 2 to 3 | infeasible, no control named |
| 5 | + max_primary_stack_exposure_pct 0.35 to 0.5 | infeasible, no control named |
| A | all five opened to their limits at once | **certified, 37s** |

## The arithmetic the engine should have found itself

On 4 games there are 8 teams and 8 viable SPs. With 8 entries,
`floor(0.35 * 8) = 2` caps every player, pitchers included, at 2 appearances.
Pitcher demand is 8 entries x 2 = 16 slots. Capacity is 8 SPs x 2 = 16. That is
exactly zero slack before the no-SP-against-your-own-stack rule removes any
pair. Run 1's own `player_exposure_floor` check reported this and marked it
PASSED, because it passed at equality: "cap 2 vs structural floor 2".

A check that passes at exactly its floor is a check that is about to fail in
interaction. The engine had the number and drew the wrong conclusion from it.

## Why the current behavior is wrong

The refusal says: "no single control is arithmetically binding against this
bank, so the interaction of the active controls is", lists the active controls,
and stops. It names the problem class and offers no remedy, which leaves the
operator to guess a search order under a lock clock. Incremental relaxation is
the wrong order and it failed four times; the interaction only clears when the
binding set opens together.

The deeper problem is the default. `exit 3` treats "did not certify under the
default controls" as the terminal state. On a small slate the default controls
are not a strategy preference, they are arithmetically unsatisfiable, and
refusing is the engine choosing no portfolio over a concentrated one. The
asymmetry runs the other way: a concentrated portfolio delivered before lock is
worth much more than a well-shaped one delivered after it. Small slates are
exactly when the defaults break and exactly when the clock is shortest.

## Proposed change

When the entry-level joint MILP proves infeasible and no single control is
named binding, `build_slate.py` escalates on its own and delivers. No operator
round trip.

1. Compute the structural floors already available in the feasibility block
   (pitcher demand vs capacity, stack demand, overlap floor) and open every
   control that sits at or below its floor in ONE step, not incrementally.
2. If still infeasible, run the full-open ladder: `max_shared_players` to
   roster size, all exposure caps to 1.0, `max_sp_pair_repetition` to the entry
   count. Solve.
3. Deliver the first certified portfolio and report the ladder rung reached.
4. Only refuse when the full-open set is still infeasible, because at that
   point it is genuinely not a controls problem and the operator needs to know
   that specifically.

Suggested surface: escalation is the DEFAULT for a build under a live clock,
with `--no-auto-escalate` for the deliberate case. If a flag is wanted the
other way, default it on anyway; the failure tonight was the default, not the
absence of an option.

A cheap version of this that captures most of the value: when a small slate is
detected (games <= 5, or viable_sp_count x per-player cap <= pitcher slots),
select small-slate control defaults at strategy-selection time so the
infeasibility never occurs.

## Truthful labels are preserved, not weakened

Escalation reports MORE, not less. Every rung is counted and named in the brief
with its before and after value, the delivered portfolio carries the
concentration statistics that result, and the three gates mean exactly what
they mean today. Tonight's delivered file was certified on the same gates as
any other. What changed was the control set, and the brief should say so in one
line the operator reads at a glance.

The concentration must be surfaced loudly, because it is real. Tonight's
delivery: three players at 100%, two at 87.5%, and an overlap histogram of
`{4:6, 5:7, 10:15}` where 15 pairs shared all ten players. The brief should
state that as the headline risk with a swap direction, which is what the
operator actually acts on, instead of making him find it in the preflight tail.

## Acceptance test

Replay `data/slates/2026-08-14/DKSalaries.csv` + `DKEntries.csv` for the
2138_4g draftgroup (8 entries, 5 wta_satellite + 1 mme) with default controls.

Expected: exit 0, certified, on the FIRST invocation, with a brief that lists
the escalation rung, every control opened with its before and after value, and
the resulting concentration as a named risk. Today that same command exits 3.

## Related

- Postures were never cleared as a factor. Attempt A kept the original
  5 wta_satellite + 1 mme postures, so the WTA construction shapes were not the
  binder. Worth confirming that separately, but it is not the cause here.
- No bank cache file was written by any of tonight's six runs, and every run
  finished in about 33s against a 130s budget. Possibly related to
  `2026-08-13_BUILD_bank-cache-freezes-at-first-slice.md`, filed separately.
- `2026-08-14_BUILD_floored-bank-hint-names-the-wrong-remedy.md` is the same
  underlying defect in a different place: a hint that names a remedy the
  operator cannot act on usefully.
