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
  --entries <swapped file> --parent <parent file> --locked-teams PIT,NYY
```

That confirms locked slots held and no new player arrived from a locked game,
which is precisely what DK will reject if you got it wrong.
