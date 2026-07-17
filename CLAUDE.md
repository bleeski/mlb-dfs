# CLAUDE.md - MLB DFS Engine (personal project)

## Context wall
This is Ben's personal DFS project. Never mix in Blue Cypress, Elastik
Teams, or Izzy context, files, or connectors. If a request seems
work-related, stop and ask.

## Communication contract
Lead with the point. Complete sentences. No em dashes, no flattery, no
padding, no sign-offs. Recommend rather than enumerate options. Push back
when the data does not support a direction. Bias toward shipping; surface
blockers only when a real decision is needed.

## Truthful labels (non-negotiable)
Every diagnostic, prior, screen, plan, and scan in this project is a
deterministic review proxy or a labeled prior. Never call anything ROI,
profitability, win rate, cash rate, or a probability claim. "Upload-ready"
is reserved for a certified export where workflow_valid,
selection_certified, and allocation_certified all pass. Archived results
are observed outcomes, not graded predictions, until a model that
predicted them exists.

## Authority
MLB_Classic.md governs strategy and contracts.
mlb_engine/optimize/optimizer_v3.py is the lineup source of truth;
scipy.optimize.milp only. Production builds enter at
mlb_engine/pipeline/execution_pipeline.run_slate and nowhere else. The
DKSalaries CSV is authoritative for player IDs, salaries, teams, and
eligibility; never correct it against real-world rosters.

Note: the package restructure is executed in this seed. The layout is
v3.0.0-pre with engine v2.26.0 behavior unchanged; every module VERSION
constant is intact.

## Session start
1. `git status` must be clean; if not, say what is dirty before touching it.
2. `python tools/audit.py --run-tests --terse` must print
   `PASS  v2.26.0  12 modules  119 tests`. The quick form of the suite
   alone is `python -m unittest tests.test_core`.
3. Read the ledger Quick Card: ledger/MLB_Classic_Calibration_Ledger.md
   section 0 plus section headers only. The full read is post-slate work.
Never repair audit or test infrastructure during a live slate. If version
or inventory checks fail while the test suite passes in full, proceed with
the build and flag the failure for post-slate repair.

## Per-slate loop
Inputs live in data/slates/<date>/: slate_bundle.json, the platoon JSON,
the DKSalaries CSV, and the DKEntries reserved-entries CSV.
1. live_data_adapters.build_slate_pool(salary_csv, lineups_feed,
   platoon_json, declared_pitchers) is the required intake front door.
   Hitters: the confirmed nine per posted lineup plus the platoon-projected
   nine per TBD team. Pitchers: feed probables plus explicit declarations.
   Every other salary row is absent, not excluded.
2. run_slate(approve=False). Review the checkpoint: slate clock, pool
   report, postures, stack plan, caps, feasibility, and a single Blockers
   line where every blocker maps to an engine action.
3. run_slate(approve=True). The certified DKEntries file and build report
   go to outputs/<date>/.
4. Ben uploads to DraftKings by hand. Refinements after delivery go
   through run_late_swap with authorized_entry_ids, never a rebuild.
T-schedule: at T-20 skip optional steps. At T-10 approve on posture
defaults and auto-floors. At T-5 present the best certified file
immediately with zero diagnostic narration.

## Hard guardrails
- Never log, echo, or write API keys. THE_ODDS_API_KEY stays in the
  environment.
- Never automate authenticated DraftKings actions. No scripted standings
  pulls, no scripted uploads, no browser sessions holding Ben's login.
  Money moves only at Ben's manual upload.
- Blank reserved entry rows block certification. Never bypass.
- Ledger edits are in place; the archive is append-only, newest first;
  never drop an invariant section.
- Deliverables land in outputs/<date>/ with exact paths stated.
- Ceiling below Floor is a hard error, never silently repaired.

## Scheduled task sessions
Each scheduled run is its own session. Read this file and the ledger
Quick Card first. Stay file-scoped: no browser, no DraftKings, no
destructive git operations. Commit with a descriptive message when a task
changes tracked files.

## Post-slate
For each standings CSV in data/standings/inbox/: run
`python -m mlb_engine.field.field_miner` with --registry and --emit-ledger, run the
verification checklist (utf-8-sig read, salary join rate investigated,
ownership recompute within 1.5 points of %Drafted, duplication table
present, contest JSON complete), append the emitted block to the ledger
archive, update the registry, move files to data/archive/<date>/, commit.
Ownership and outcome counts are conditioned on contest archetype and
field size, never pooled across them.

## Showdown (active after Phase 3)
Roster contracts live in mlb_engine/optimize/roster_contracts.py. Classic
and Showdown are two contracts on one solver. Showdown archetypes never
pool with Classic in the ledger or the ownership work.
