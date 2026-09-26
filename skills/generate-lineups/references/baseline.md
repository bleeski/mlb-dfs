# The baseline: a legal file before the build's own construction (R389(b), R389(c))

Classic first; Showdown's differences are the last section.

**What lands.** `run_classic` publishes a baseline before it reads reference data, odds, weather or venues.
- **Where it sits.** Directly after the pool-blocker refusals and the `--leverage` check, so every earlier refusal still refuses first and exit 4 still means "before any solve".
- **The frame.** The core (`mlb_engine/pipeline/baseline.py`) builds entry-mapped lineups on the unenriched frame and covers every reserved row. The build's `--max-opposing-hitters-per-sp` reaches every solve.
- **Allocation.** `run_slate` allocates and exports them, with every portfolio cap opened to the deadline rung's value. A `--never-relax` control stays held, and F-3 (no lineup twice in one contest) always holds.
- **The file.** `outputs/<date>/DKEntries_<tag>_BASELINE_<run_id>.csv`, labelled `review_grade_baseline`. It is never certified and never upload-ready: odds and weather are assumed by construction, and every cap was opened before any refusal. Preflight says `review_ready`, exit 0, and gives that reason. Upload stays Ben's call.

**It is checked on its exact bytes before it is presented.** Three checks must all pass:
- `verify_classic` re-reads the file;
- the engine's post-export V gates must pass on those bytes (essential-valid);
- the bytes must re-hash to the run's `final/DKEntries.csv`.

Then a brief bound to its sha256 is written beside it, `build_brief_<tag>_BASELINE_<run_id>.json`, carrying `declared_pitchers`. Preflight and `verify_export` read declared arms only through such a brief. The `FILE` line then prints before any research narrative.

**Its own manifest lineage.** The row carries `lineage: baseline`.
- **Nothing crosses lineages.** Supersession, the same-bytes merge and the UNCERTIFIED backstop stay inside one lineage. So the enhanced file, recorded later, supersedes nothing Ben may already hold, and both files pass preflight on their own bytes.
- **A rerun.** One that rebuilds identical bytes (an autobuild retry, a resume) reuses the live baseline row and file.
  - A rerun whose baseline bytes changed, because the pool or the controls did, supersedes the earlier baseline inside its lineage, and so does any late swap of it. That holds even when the rerun's enhanced solve then refuses, just as a new enhanced file supersedes the old one.
- **`promote_run.py --canonical`** refuses a baseline run, because that name is the enhanced file's.
- **A late swap** records in its parent's lineage, supersedes that parent, and retires every other lineage's live row for the slate (`retired_by`). After a swap only the swapped file is live.
- **Re-promotion.** `promote_run.py` keeps the baseline label and lineage.
- **The row's `strategy_state`** reads `relaxed`, with `controls_opened` counting every cap the baseline moved. A cap the operator already typed at its open value did not move. A deadline-governed enhanced row counts its rung's moves the same way.

**Which file is current.** The last `FILE` line printed is the current file, and the brief's `baseline.current` says the same.

| outcome of the enhanced build | current file | exit |
|---|---|---|
| certified or deadline-labelled | the enhanced file | 0 (7 on a later failure) |
| refused, including an UNCERTIFIED file | the baseline, re-presented after the UNCERTIFIED line | 3 |
| sliced bank thin, resumable | the baseline, re-presented | 10 |
| an enhanced file that fails its independent re-read (`verify_failed`) | the baseline, re-presented; the brief's `delivered_*` are null and the failed file is under `verify_failed_path` (R461) | 3 |
| no baseline, an UNCERTIFIED file held, then a re-solve crashes (R459) | the UNCERTIFIED file | 7 |
| a crash after the baseline and before an enhanced file is presented (research, the enhanced solve) | the baseline | 7 |
| a crash after an enhanced file was presented (the brief, a report) | the enhanced file | 7 |

- **Why the baseline outranks an UNCERTIFIED file.** It passed its own gates, and a gates-failed file never outranks a gates-passing one (R388(d)).
- **An earlier build's live row.** When an earlier build's enhanced file for the slate passed its gates and its row is still live, it is named under `baseline.live_delivery` and printed under the baseline's line. Only a row recorded before this call's baseline counts, never this call's own.
  - The baseline stays this call's current file, because it was built on this call's inputs.
  - When the inputs changed (lineups posted, a scratch), the baseline is the one to upload. When they did not, the earlier file is better shaped.
- **Exits 3 and 10 keep their meaning**, so autobuild still grows the bank or resumes. The refusal record names the delivered baseline.

**When there is no baseline.** Each case is a named record under `baseline.status`, and the build runs exactly as before:
- `short`: the core could not cover every row inside its window, a quarter of the time left at the call. F-2's removed-rows form is Session 22.
- `refused`: the allocator refused. For example, a `--never-relax` cap the covering set cannot meet.
- `not_presented`: the re-read, the essential check or the label failed.
- `error`: anything raised.

An S/P-only baseline refusal is never published; the enhanced build keeps its own UNCERTIFIED path (`references/review_grade.md`).

**What it costs.** Measured on the cloud container:
- 06-03 (2 games, 18 rows): 0.4s for the core and 0.13s to allocate.
- 06-28 blanked (11 games, 38 rows): 3.7s and 0.8s.

The build's deadline is not moved, so enhancement keeps everything the baseline did not spend. The timing probe (`single_s`) still runs on the enriched frame: the core's probe time is 2-4x slower and would misjudge the bank's cost.

## Showdown (R389(c))

**What lands.** `run_showdown` publishes a baseline after pricing the pool and before the thesis ladder.
- **Where it sits.** After every exit-4 refusal (the Excluded column, unreadable `--projections`, the captain prior and sleeve), so exit 4 still means "before any solve".
- **The solve.** `build_showdown_bank` on the ladder's own priced frame: one points-max lineup per incomplete reserved row, thesis-free, at the build's `max_shared_players`, `max_cpt_exposure_pct` and `max_player_exposure_pct`. Those are relaxed per slot under R153's order and counted in `baseline.relaxations`. The per-contest captain cap is the ladder's control, so `baseline.per_contest` reports it and no row lists it as held. A `--captain-sleeve` does not reach it, and when the baseline is current the build says so.
- **F-3.** The template's complete rows are forbidden to the bank (`complete_row_player_keys`), so no baseline lineup repeats one in its contest.
- **The window** is a quarter of the time left. The bank stops early when its first lineup's time says the rest will not fit, and a short bank is `short`, with no file.
- **The points-max path** builds no baseline (`not_needed`): its own bank is the same construction on the same frame. The exception is `--entries-count` below the reserved rows. There the build refuses the rows it would leave blank, and the baseline covers every row.

**The file.** `outputs/<date>/DKEntries_showdown_<tag>_BASELINE_<sha12>.csv`, review-grade like every Showdown file, in the `baseline` lineage. Every lineup passes `certify_showdown`. The template check and row coverage run on the staged bytes before any manifest row is recorded. The same bytes on a rerun reuse the row and the name; new bytes are a new file that supersedes inside the lineage. Preflight says `review_ready`, exit 0. The brief beside it is `build_brief_showdown_<tag>_BASELINE_<sha12>.json`.

**Which file is current.**

| outcome of the thesis ladder | current file | exit |
|---|---|---|
| a file that passed its checks and recorded its row | the ladder's file | 0 |
| a refusal (infeasible, not certified, short of rows, export failed, template broken) | the baseline, re-presented | 3 |
| a crash anywhere after the baseline | the baseline | 7 |
| a file whose own manifest row failed, beside a recorded baseline | the baseline; the ladder's `DO_NOT_UPLOAD_` copy is named, not presented | 7 |

**What it costs**, measured on the cloud container on the MIN@CHC fixture:
- 21 rows: 0.9s.
- 150 rows: 48.3s for the baseline, 59.9s for the whole build.
- At Cowork's 100s budget the window is 25s, so a 150-row baseline stops after its first lineup, as `short` (0.2s spent).
