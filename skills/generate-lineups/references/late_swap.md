# Late swap

Read this when a swap fails, or when you need to drive the swap by hand instead of
through `tools/late_swap.py`.

## Why a swap and not a rebuild

Once a game starts, its players are locked. A rebuild would happily move them,
producing a file DraftKings rejects. The swap path freezes what has locked and
reoptimizes only what has not, against the file Ben already uploaded.

The parent is the delivered export: the `outputs/<date>/` file Ben uploaded, or
`runs/<run_id>/final/DKEntries.csv`, which holds the same bytes. The engine finds
the run by the file's sha256 (R268(b)), so pass the real delivered file rather than
a copy you edited. The run can be the latest promotion, an earlier one, a certified
run that never promoted, or an UNCERTIFIED build (`review_grade.md`). A file matching
no run is refused at exit 3 before any bank slice; `--allow-parent-mismatch` is for
that case alone. The swap inherits the portfolio controls its parent recorded
(R268(a)), and `--rederive-controls` re-derives them from postures and floors.

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

The swap builds one general bank, then one targeted slice per pinned entry, each
passing an `excludes` list computed from that entry's own roster. The general
bank and every targeted slice survive each other regardless of scope (R101), so
scoping decides what may move, not how big the bank is.

- **Name the entries you actually want to change, for the ordinary reason.**
  A tight `--entry-ids` limits what may move in the file.
- **Read `bank the joint solve will see: N candidates across K conditions
  bucket(s)`.** That line is printed after the targeted slices and it is the
  number the solve receives. The `candidate scoring:` line leads with the same
  number and names the only two things that can move it — duplicate rosters two
  buckets both reached, and scoring failures. `bank after the general slice:` is
  the general slice alone and says so.
- **A non-zero `superseded_jobs_dropped` means the PROJECTIONS moved** since the
  cache was written (or the cache file predates R101), and it prints with the
  projection digest that caused it.
- **A bigger `--budget` does not fix a thin bank on its own.** It buys more
  jobs, and every job's results are kept.

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

**No `--locked-teams`.** The tool derives locked teams on EVERY invocation from
the lineups feed's own clock, falling back to the salary file's `Game Info`, and
prints the clock and the source it used. The flag only ADDS to that set. If you
see `STALE --locked-teams` in the output, drop the flag. `--as-of` is the only
clock override, and it is for replaying a derivation against a fixed time.
