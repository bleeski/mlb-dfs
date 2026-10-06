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
It also carries the parent build's declared pitchers (R468), read from that build's
brief and printed as `declared pitchers: ... (source)`; `--declare-pitcher ID[=ROLE]`
adds or overrides one, in `build_slate.py`'s grammar. Without them an entry holding a
declared PLR or bulk arm in a locked slot has no candidate and the whole swap refuses
(1400_4g, 2026-09-29: `+0 targeted candidates`, then `no compatible candidate`).
A declared bulk arm is projected at a bulk arm's workload in the swap exactly as in
the build (R470): the role carries the default, and any typed `:ip=N` is inherited
from the parent's `declared_pitcher_workload` and printed as `declared workload:`.
An arm declared on the swap's own command line that DK tags `PO` needs
`:evidence="..."` (R471), or the swap refuses at exit 4 before anything is swapped;
the parent's recorded notes (`declared_pitcher_evidence`) count, are printed as
`declared evidence:`, and ride the swap's manifest. Inherited declarations are not
re-judged.
The swap also refuses at exit 3 when it would remove a contest's last lineup on the
consensus SP pair its parent recorded (R469, `references/chalk_core_seat.md`);
`--accept-downgrade` takes it and the file ships review-grade.

### The swap's frame (R428): the parent's applied values, labelled

A swap ranks candidates, and compares the incumbent with the chosen lineup (the
downgrade refusal), on the projection frame it assembles. Since R428 that frame carries
what the parent run APPLIED to each player, read from the parent run's own
`final/projections.csv` (Base after the xwOBA correction and the value guard, F1, F3,
F4, F5, the Ceiling_Multiplier), and only the batting orders (F2) are the new feed's.
Neither the brief nor `runs/<id>/inputs/` records the odds packet, the Savant files or
the F1/F4/F5 maps, so there is nothing to re-read; the swap carries values, not inputs,
and says so on one line before the bank is built (also on `--dry-run`):

- `projection frame: ENRICHED by carry from run <id> (...)`: the run, its hops from the
  parent, the origin build, the frame's sha256, `carried N of M pool players`,
  `f1_games_priced` (games with a non-neutral F1 row, measured off this frame; the build's
  own count of that name is games with a usable total), `f1_non_neutral`,
  `f4_non_neutral`, `f5_non_neutral`, `ceiling_multiplier_differentiated`, and the pool
  players the parent never carried (they stay in the frame at neutral, named).
- `projection frame: UNENRICHED (<reason>)`: no parent run, no run in the chain that
  measures enriched, or another slate. The swap still runs, on AvgPointsPerGame x
  batting order only, and the entry scores below are on that model. It is never a refusal.
- `projection frame: carry REJECTED (...)`: the engine refused a carried value (a
  multiplier that breaks Ceiling >= Floor); the swap builds unenriched, exit unchanged.

A parent that is not this file's lineage (`--allow-parent-mismatch` resolves the latest
promoted run) lends its frame only when its salary snapshot has this swap's player-ID
pool (`pool_signature`); a swap of a swap walks the manifests' `parent_run_id` and takes
the root-most run whose frame measures enriched and verifies (an intermediate swap's frame
holds the root's values only for its own pool). The record is on the swap run's manifest
(`metadata.projection_carry`) and the delivery record's `projection_tier` is `enriched`
only when the carry moved a cell off neutral. A deterministic review proxy of the
parent's values, not a re-derivation and not fresher than the parent. The entry scores
now move with the parent's model: an incumbent seated for its market total or platoon
edge is no longer "improved" into an APPG-max roster with the refusal silent.

### `--standings` (R472): the standings at the decision

`--standings <contest-standings-<id>.csv|.zip>` (repeat for several contests;
`--paid-places N` for one file or `<contest_id>=N,...`; `--target-rank k`, default 1)
reads a DK standings export Ben downloaded, by explicit path, read-only, and prints
per contest the points at #1, #10 and #100, the cash line, the %Drafted of started
players, and each leader's open-pitcher inference, then per authorized entry a
verdict: `live_for_target` (current points plus the projected Ceiling of every
unstarted slot reaches the target rank's points), `cash_viable`, `out`, or `unknown`
with the reason. Review proxies, never a prediction: Ceiling is a model prior from the
parent run's `final/projections.csv`, and the live export's TimeRemaining and
hidden-slot format are UNVERIFIED (0 of 516,804 archived rows are nonzero), so
TimeRemaining is printed raw and feeds nothing. Rule: never lower a `cash_viable`
entry's projection for leverage.

What it changes: an entry that is `live_for_target` while still BEHIND the target, in
a `gpp` or `wta` contest, whose CHOSEN lineup still reaches the target, is exempt from
the downgrade refusal above (and nothing else: not the consensus-pair guard, not any
V check, which all run before it). The file still ships review-grade
(`review_grade_downgrade_accepted`); it is reported as `exempted by standings`, never
as accepted by the flag, and the record counts it as
`relaxations.downgrades_exempted_by_standings`. `--accept-downgrade` subsumes it. An
absent `--standings` path or a typo'd flag is exit 4; a file that exists but cannot be
used prints `STANDINGS NOT USED: <reason>` and the refusal is exactly what it is
without the flag. `--dry-run` checks the `--standings` flags but returns before the
verdicts are read; read them without a swap with `python tools/standings_read.py
--help` (the standalone reader).

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

## Exit codes and the file in hand (R414)

The swap presents the file (`FILE <path> sha256=... label=... coverage=...`)
before any narrative, the moment it is written and its label is known, the same
contract Session 08 gave `build_slate.py`. Codes:

- **0** — delivered clean: promoted, recorded, staged, and the swap's own run of
  the preflight on those bytes exited 0 with verdict `upload_ready` (R174; see
  below). A `review_ready` verdict also exits 0, and prints as such.
- **4** — a required input is missing: the salary file, the parent, or an
  explicit `--lineups` path that does not exist. A missing DEFAULT
  `lineups_feed.json` is NOT this when DK's `Starting` column covers every side
  (R404): the swap builds its feed from the salary file, prints
  `DK's Starting column covers all N side(s)`, and goes on. One uncovered side
  brings the exit 4 back, naming the side.
- **5** — delivered, and the swap's own preflight run REFUSED the bytes (or could
  not run). The file is written, recorded and on disk; the `REFEREE FAILED` lines
  say which check failed. It is not upload-ready. Repair the failure
  (`tools/repair_entry.py` for a dead or locked player) and run the preflight
  again; nothing is withdrawn, and nothing was uploaded.
- **3** — refused: a downgrade without `--accept-downgrade` (and not exempted by
  `--standings`, R472), or a promotion
  another session's race beat (the file sits at its `DO_NOT_UPLOAD_` name,
  withdrawn, not delivered).
- **7** — delivered a prior valid artifact after a LATER failure: a raising
  promotion, a raising `record_delivery`, or anything else after the file was
  presented. The file above is the deliverable, under its own label (the
  downgrade label when `--accept-downgrade` was taken); nothing was silently
  swallowed into a clean exit 0 with the file stuck under `DO_NOT_UPLOAD_`.
  `deliver_swap` is the whole tail (present, promote, record, ship) in one
  function precisely so each of these later-failure branches is a small,
  direct test rather than a full swap.

A refused promotion (3) is not the same fact as a raising one (7): the first
means "another session already delivered from this run," never a later failure
of a real delivery, so the file is deliberately withdrawn rather than delivered
under a bad label.

## After a swap

The swap runs `preflight_upload.py` on the file it just wrote, in process, with
`--salary`, `--parent` and `--expect-sha256` (and `--feed` when a feed file was
read), and prints `referee: preflight_upload exit 0 ... verdict <verdict>` before
it prints the upload line. Only `verdict upload_ready` means upload-ready;
preflight also exits 0 for `review_ready`, which is what a downgrade taken with
`--accept-downgrade` (or exempted by `--standings`) or a review-grade parent produces, and the line says so. Exit 5 is the swap saying it has no such verdict. Also
run `verify_export.py` below, because CLAUDE.md's two-referee clause is about two
tools. Verify before handing it over. `preflight_upload.py` auto-resolves `--parent`
from the manifest's supersession chain when it is omitted (R450), the same
mechanism `verify_export.py` already used, but the swap's own printed command
already names it, so nothing needs to be typed under a clock:

```bash
python tools/preflight_upload.py --entries <swapped file> --salary <DKSalaries.csv> \
  --parent <parent file> --expect-sha256 <sha>
python tools/verify_export.py --salary <DKSalaries.csv> \
  --entries <swapped file> --parent <parent file>
```

That confirms locked slots held and no new player arrived from a locked game,
which is precisely what DK will reject if you got it wrong.

**No `--locked-teams`.** The tool derives locked teams on EVERY invocation from
the salary file's `Game Info` clock, unioned with the lineups feed's own clock,
and prints the clock and the source it used. A feed can only ADD to that set. The
one thing it can remove is a game it reports postponed, and only when the feed's
date for that game is the salary file's date for it (R325): a feed dated to
another day is named `IGNORED` and the salary clock decides. `preflight_upload.py`
and `verify_export.py` share this derivation and both accept the flag. The flag only ADDS to that set. If you
see `STALE --locked-teams` in the output, drop the flag. `--as-of` is the only
clock override, and it is for replaying a derivation against a fixed time.
