# Late swap

Read this when a swap fails, or when you need to drive the swap by hand instead of
through `tools/late_swap.py`.

## Why a swap and not a rebuild

Once a game starts, its players are locked. A rebuild would happily move them,
producing a file DraftKings rejects. The swap path freezes what has locked and
reoptimizes only what has not, against the file Ben already uploaded.

The parent is the delivered export, normally `runs/<run_id>/final/DKEntries.csv`.
The engine verifies the parent hash, so pass the real delivered file rather than a
copy you edited.

## The command

```bash
python tools/late_swap.py --date <date> \
  --parent-entries runs/<run_id>/final/DKEntries.csv \
  --budget 30 [--entry-ids 123,456] [--dry-run]
```

`--dry-run` reports each entry's pinned slots and how many candidates exist,
without swapping. Good first move when you are unsure how much room there is.

`--entry-ids` restricts mutability to exactly those entries. Omitting it
authorizes every reserved entry in the file.

## Scope `--entry-ids` to the entries you mean, not to protect the bank

**This section changed on 2026-08-10 (R101). Scoping is now a scope choice.**
It used to be a bank-preservation workaround, and if you learned the habit from
the older version of this page, the reason you learned it is gone.

The mechanism, as dated history. The swap builds one general bank, then one
targeted slice per pinned entry, and each targeted slice passes an `excludes`
list computed from *that entry's own* roster. Until R101 the exclude set was
part of one `bank_cache` conditions signature, and `extend_bank` opened by
calling `drop_stale_jobs`, which discarded every stored candidate built under a
different signature — so each targeted slice threw away the candidates the
previous slices built, the general bank included. Across nine runs on 2026-08-03
the cache reached 1,007 candidates while the joint solve was handed 8, 9 or 10
of them; scoped to the 2 entries that needed a change, which happened to share
one exclude set so nothing was discarded between them, it was handed 90
(R47, measured 2026-08-08 against `outputs/2026-08-03/_swap1..9.log`).

What holds now:

- **Name the entries you actually want to change, for the ordinary reason.**
  A tight `--entry-ids` limits what may move in the file. It is no longer buying
  you a bigger bank; the general bank and every targeted slice survive each
  other regardless of scope.
- **Read `bank the joint solve will see: N candidates across K conditions
  bucket(s)`.** That line is printed after the targeted slices and it is the
  number the solve receives. The `candidate scoring:` line leads with the same
  number and names the only two things that can move it — duplicate rosters two
  buckets both reached, and scoring failures. `bank after the general slice:` is
  the general slice alone and says so.
- **`superseded_jobs_dropped` now means one thing.** A non-zero value is the
  PROJECTIONS having moved since the cache was written (or a cache file older
  than R101), and it prints with the projection digest that caused it. It can no
  longer mean a sibling slice quietly deleted your bank.
- **A bigger `--budget` still does not fix a thin bank on its own.** It buys
  more jobs, which is now worth buying, since nothing throws the results away.

## The two rules that explain most failures

**A locked slot cannot move.** The player who is already playing stays in the exact
DK slot he occupies.

**A locked game admits no new players at all.** This is the one that surprises
people. If PIT@NYY has started, an entry may keep the Yankees it already has, but
it cannot add a *different* Yankee into an open slot. The requirement carries this
as `excluded_new_teams`.

The subtlety: "no new player from a locked game" means the entry's *own current
players* are still allowed. If you build the exclusion list without exempting the
entry's current roster, you exclude that entry's own pinned players and every
solve goes infeasible. The requirement dict does not carry the roster, so it has
to come from the parent CSV.

## Candidate generation for pinned entries

A general bank covers entries with nothing locked. Entries with pins need
candidates built against those exact pins, or the allocator reports "no compatible
candidate". `mlb_engine/optimize/bank_cache.extend_bank` takes
`locked_slot_assignments` and `excludes` for this.

Three constraints it handles that are easy to miss:

**Dedupe on the ordered ten-slot roster, never the player set.** Late swap pins
players to exact slots, so the same ten players in a different slot order is a
genuinely different candidate. A player-set frozenset throws away the variant the
allocator needs.

**A pinned pitcher constrains the SP pair space.** If P1 is pinned, every pair
excluding that pitcher is infeasible. Enumerating them burns the budget on
guaranteed failures, so the pair space is narrowed to the pins up front.

**Both pitcher slots pinned to the SAME GAME yields zero candidates, at any
budget.** `extend_bank` builds its job list from `usable_pairs`, which drops any
pair whose two pitchers share a `Game_ID`. Each job then passes its pair as
`locks` *on top of* the entry's `locked_slot_assignments`, so a job whose pair is
not the pinned pair needs four pitchers in two slots and is infeasible. If the
pinned pair itself is not in `usable_pairs`, every job is infeasible and the
slice reports `+0 targeted candidates` (R47; reproduced on entry 5207638174,
both P slots pinned to the locked STL@NYY game). Entries with one P pinned are
fine, because pairs containing that pitcher survive the same-game filter. Until
this is fixed, exclude such an entry from the swap rather than growing the bank.

**Enough pinned hitter slots makes a stack impossible.** A Classic roster has 8
hitter slots. Pin 5 and only 3 are free, so a 4-man stack cannot fit and no budget
will help. `extend_bank` relaxes `stack_min` to the room actually available and
reports it as `stack_min_relaxed_to`.

## Driving it by hand

```python
from mlb_engine.intake.live_data_adapters import build_status_map_from_lineups_feed
from mlb_engine.swap.late_swap_manager import build_entry_requirements
from mlb_engine.pipeline.execution_pipeline import run_late_swap

status = build_status_map_from_lineups_feed(feed, salary_csv)   # feed first
requirements = build_entry_requirements(
    parent_entries_csv, status["status_by_player_id"], now, None,
    mode="reoptimize", missing_status_policy="treat_as_locked",
)
```

`run_late_swap` needs `projections` (a DataFrame from
`_assemble_projection_frame`), `candidates` (with `roster_slot_ids` in
`ENTRY_ROSTER_SLOTS` order), `workflow_gates`, and `portfolio_controls`. There is
no fail-open policy: `missing_status_policy` is either `error` (block) or
`treat_as_locked` (freeze). Use `treat_as_locked` when a player's lock state
cannot be resolved.

## After a swap

Verify before handing it over:

```bash
python tools/verify_export.py --salary <DKSalaries.csv> \
  --entries <swapped file> --parent <parent file>
```

That confirms locked slots held and no new player arrived from a locked game,
which is precisely what DK will reject if you got it wrong.

**No `--locked-teams`.** This example passed `--locked-teams PIT,NYY` until
2026-09-06, against SKILL.md's explicit "do not pass `--locked-teams` at all" —
the two instructions have contradicted each other at the money boundary, and
this one was wrong. The tool derives locked teams on EVERY invocation from the
lineups feed's own clock, falling back to the salary file's `Game Info`, and
prints the clock and the source it used. The flag only ADDS to that set and can
no longer replace it, so a hand-typed list is a list that goes stale while you
are still using it: on 2026-07-29 a list passed at 7:23 PM ET was still in use
at 8:02 with three games locked underneath it, `verify_export.py` printed PASS,
and DraftKings rejected 7 of 16 entries. If you see `STALE --locked-teams` in
the output, drop the flag. `--as-of` is the only clock override, and it is for
replaying a derivation against a fixed time.
