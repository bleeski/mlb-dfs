# CLAUDE.md - MLB DFS Engine (personal project)

## Context wall
This is Ben's personal DFS project. Never mix in Blue Cypress, Elastik Teams,
or Izzy context, files, or connectors. If a request seems work-related, stop
and ask.

## Truthful labels (non-negotiable)
Every diagnostic, prior, screen, plan, and scan in this project is a
deterministic review proxy or a labeled prior. Never call anything ROI,
profitability, win rate, cash rate, or a probability claim. "Upload-ready" is
reserved for a certified export where workflow_valid, selection_certified, and
allocation_certified all pass. Archived results are observed outcomes, not
graded predictions, until a model that predicted them exists.

## Authority
MLB_Classic.md governs strategy and contracts.
mlb_engine/optimize/optimizer_v3.py is the lineup source of truth;
scipy.optimize.milp only. Production builds enter at
mlb_engine/pipeline/execution_pipeline.run_slate and nowhere else.
mlb_engine/contest_shapes.py owns the contest-shape vocabulary and every
producer of a shape validates against it at import. The DKSalaries CSV is
authoritative for player IDs, salaries, teams, and eligibility; never correct
it against real-world rosters.

## Where the procedures live
This file carries the contracts and the gotchas. Each procedure lives once:
- Per-slate loop, start to upload: skills/generate-lineups/SKILL.md
- Post-slate archival: docs/cowork_archival_runbook.md
- Showdown mechanics: skills/generate-lineups/references/showdown.md
- Any tool's flags: `python tools/<tool>.py --help`
- What to build next: docs/2026-07-27_backlog_v2.md, the single live backlog.
  Do not write a new review document.

## Build contract
The steps are in SKILL.md. These five hold whatever path a build takes:
1. `live_data_adapters.build_slate_pool` is the required intake front door.
   Hitters are the confirmed nine per posted lineup plus the platoon-projected
   nine per TBD team; pitchers are feed probables plus explicit declarations.
   Every other salary row is absent, not excluded.
2. The platoon reference ages against the SLATE, not its own collected_date.
   Past 7 days with a TBD team filled from it is a pool blocker
   (`stale_platoon_policy='warn'` downgrades it;
   skills/generate-lineups/scripts/build_slate.py tiers it SOFT, so it prints
   and the build ships).
3. `run_slate(approve=False)` first, always. The checkpoint is the review:
   slate clock, pool report, postures, stack plan, caps, feasibility, and one
   Blockers line where every blocker maps to an engine action.
4. The certified artifact is runs/<run_id>/final/DKEntries.csv and it is
   immutable. outputs/<date>/ holds the mirror, returned as `delivered_path`.
5. Refinements after delivery go through `run_late_swap` with
   authorized_entry_ids, never a rebuild. A locked game admits no new players.

## Session start
1. `git status` must be clean; if not, say what is dirty before touching it.
2. `python tools/audit.py --run-tests --terse` must print
   `PASS  v2.26.0  23 modules  365 tests`. The module count comes off the
   filesystem and moves on its own; the test count is a pin. A count mismatch
   with the suite passing is a WARNING and prints in brackets on the PASS
   line: proceed, fix the pin after the slate. A failing suite blocks. The
   audit gates test_core, test_showdown, test_upload_integrity, and
   test_golden_replay.
3. `python tools/solver_probe.py --date <date> --entries <n> --budget <s>`
   before any build. Exit 3 means the bank does not fit: pass `time_budget_s`
   and accept a partial bank, or slice with `mlb_engine.optimize.bank_cache`.
4. Read the ledger Quick Card: ledger/MLB_Classic_Calibration_Ledger.md
   section 0 plus section headers. The full read is post-slate work.

Never repair audit or test infrastructure during a live slate. If version or
inventory checks fail while the suite passes in full, build and flag it.

## Hard guardrails
- Never log, echo, or write API keys. THE_ODDS_API_KEY stays in the
  environment.
- DraftKings reads are MANUAL. Claude-in-Chrome is blocked from
  draftkings.com and scripted DK access violates DK terms; never attempt to
  bypass either, by curl, requests, or any alternate fetch. Ben downloads
  completed-contest standings himself (one click on
  exportfullstandingscsv/<contest_id> while logged in) into
  data/standings/inbox/. Claude automates everything downstream and may emit
  the export URLs from the contest IDs in Ben's files, but never fetches DK.
- The money-and-entry wall is absolute: never automate a DraftKings action
  that enters a contest or moves money. No uploads, no entry submission or
  edits, no deposits or withdrawals. Lineups and money move only at Ben's
  manual action. Never store DK credentials or cookies.
- **Before any upload, run the preflight.** One command, two files, no engine
  import, no network, under two seconds:
  `python tools/preflight_upload.py --entries <delivered.csv> --salary <salary.csv>`
  Exit 0 clean, 2 hard failure, 3 IO error, 4 acknowledged (`--force` prints
  the failures and exits 4, never 0). This sentence is the pre-upload rule;
  nothing else is.
- Never trim the player pool to fit a compute limit. An infrastructure limit
  may reduce search effort; it may never reduce the legal player set, because
  that is a strategy change and it is invisible in the certified output. A
  timeout is recorded in `solver_report`, never climbs the overlap ladder,
  never steps DU relaxation, and never enters `attempted` in the bank cache. A
  time-limited incumbent is verified against the constraint matrix and then
  accepted, tagged `optimality='time_limited'`. The allocator says "time limit
  at gap X" or "proven infeasible: <constraint>", never both.
- The Excluded column has one reading, in `optimizer_v3.excluded_flags`. Only
  an affirmative token removes a player; blank, NaN, "False" and unrecognized
  cells keep them. Never compare the column to False directly. A player
  leaving the pool on a blank cell is the forbidden pool reduction arriving as
  a data condition.
- Determinism: every set reaching the solver is sorted first
  (`mlb_engine.determinism.stable_union`) and entry points pin
  `PYTHONHASHSEED=0`. Never write `list(set(player_ids))`.
- Blank reserved entry rows block certification. Never bypass.
- The standings inbox is FLAT. Do not sort it into per-contest-type folders:
  the miner reads Classic vs Showdown off the lineup cells, and a folder is a
  second copy of that fact that can disagree with the first.
- Ledger edits are in place; the archive is append-only, newest first; never
  drop an invariant section. Ownership and outcome counts are conditioned on
  contest archetype and field size, never pooled across them.
- Deliverables land in outputs/<date>/ with exact paths stated.
- Ceiling below Floor is a hard error, never silently repaired.

## T-schedule
At T-20 skip optional steps. At T-10 approve on posture defaults and
auto-floors. At T-5 present the best certified file immediately with zero
diagnostic narration.

## Showdown
Showdown ships **review-grade**, not certified. It does not pass through
workflow_valid / selection_certified / allocation_certified; `run_slate` is
the Classic front door and Showdown does not enter it. Say "review-grade
build", never "upload-ready", and run the preflight on every deliverable.
`run_late_swap` cannot refine a Showdown delivery, because there is no
promoted run to refine. Bringing Showdown under the three gates is open
backlog, not a decision left implicit.

Two portfolio controls are enforced in the solver, not in review, and relaxed
only in the stated order and counted: no two lineups share more than
max_shared_players (4 of 6, counting
the player and not the role), and no captain exceeds max_cpt_exposure_pct
(0.33, a floor() of pct * n, which is why it is not 0.35). Both relax before
they truncate, in the order overlap then captain lock then thesis, because a
short bank leaves a blank reserved row and a blank row blocks certification.
Every relaxation is counted in the brief. A portfolio is not clean because the
gates passed; it is clean when the relaxation counts are zero.

## Scheduled task sessions
Each scheduled run is its own session. Read this file and the ledger Quick
Card first. Stay file-scoped: no DraftKings fetching, no destructive git
operations. A scheduled task may process standings CSVs Ben has already
dropped in the inbox and remind him which contests still need a manual pull.
Commit with a descriptive message when a task changes tracked files.
