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
   `PASS  v2.26.0  13 modules  180 tests`. The quick form of the suite
   alone is `python -m unittest tests.test_core`. The audit checks
   dependencies first and names the install command, because a missing
   solver is not a slow build, it is no build.
3. `python tools/solver_probe.py --date <date> --entries <n> --budget <s>`
   before any build. It times one lineup and a short multi-lineup run on
   the real pool and says whether the bank fits the execution budget. Exit
   3 means it does not: pass `time_budget_s` and accept a partial bank, or
   build across slices with `mlb_engine.optimize.bank_cache`. Never trim
   the player pool to fit a compute limit. An infrastructure limit may
   reduce search effort; it may never reduce the legal player set, because
   that is a strategy change and it is invisible in the certified output.
4. Read the ledger Quick Card: ledger/MLB_Classic_Calibration_Ledger.md
   section 0 plus section headers only. The full read is post-slate work.
Never repair audit or test infrastructure during a live slate. If version
or inventory checks fail while the test suite passes in full, proceed with
the build and flag the failure for post-slate repair.

## Per-slate loop
Inputs live in data/slates/<date>/: slate_bundle.json, the lineups feed,
the DKSalaries CSV, and the DKEntries reserved-entries CSV. The platoon
fallback is no longer a per-slate drop: build_slate_pool loads
data/reference/fangraphs_platoon_lineups.json by default, so a TBD team
keeps a projected batting order instead of being guessed at by top-9
AvgPointsPerGame or dropped from the slate. Refresh that reference from
FanGraphs RosterResource periodically; the pool report names any team the
file covers but cannot fill, and flags stale per-team pages.
1. live_data_adapters.build_slate_pool(salary_csv, lineups_feed,
   platoon_json, declared_pitchers) is the required intake front door.
   Hitters: the confirmed nine per posted lineup plus the platoon-projected
   nine per TBD team. Pitchers: feed probables plus explicit declarations.
   Every other salary row is absent, not excluded.
2. run_slate(approve=False). Review the checkpoint: slate clock, pool
   report, postures, stack plan, caps, feasibility, and a single Blockers
   line where every blocker maps to an engine action.
3. run_slate(approve=True). The certified artifact is
   runs/<run_id>/final/DKEntries.csv and stays immutable; the engine
   mirrors it to outputs/<date>/ and returns that as `delivered_path`.
4. Ben uploads to DraftKings by hand. Refinements after delivery go
   through run_late_swap with authorized_entry_ids, never a rebuild.
   `python tools/late_swap.py --date <date> --parent-entries <csv>` wraps
   that path, including the excluded-new-teams rule (a locked game admits
   no new players) and the pinned-slot candidate generation it requires.
   Verify any file before upload with `python tools/verify_export.py`.
T-schedule: at T-20 skip optional steps. At T-10 approve on posture
defaults and auto-floors. At T-5 present the best certified file
immediately with zero diagnostic narration.

## Hard guardrails
- Never log, echo, or write API keys. THE_ODDS_API_KEY stays in the
  environment.
- DraftKings reads are MANUAL. Claude-in-Chrome is blocked from
  draftkings.com by platform safety restrictions, and scripted DK access
  violates DK terms; Claude never attempts to bypass either (no curl, no
  requests, no alternate fetch). Ben downloads completed-contest standings
  himself (one click on exportfullstandingscsv/<contest_id> while logged in)
  and drops them in data/standings/inbox/. Claude automates everything
  downstream (field_miner, grading, ledger archive) and may emit the exact
  export URLs from the contest IDs in Ben's files and remind Ben to pull, but
  never fetches DraftKings itself.
- The money-and-entry wall is absolute: never automate a DraftKings action
  that enters a contest or moves money. No lineup uploads, no entry submission
  or edits, no deposits or withdrawals. Lineups and money move only at Ben's
  manual action. Never store DK credentials or cookies.
- Blank reserved entry rows block certification. Never bypass.
- Ledger edits are in place; the archive is append-only, newest first;
  never drop an invariant section.
- Deliverables land in outputs/<date>/ with exact paths stated.
- Ceiling below Floor is a hard error, never silently repaired.

## Scheduled task sessions
Each scheduled run is its own session. Read this file and the ledger
Quick Card first. Stay file-scoped: no DraftKings fetching (the platform
blocks it and it is barred anyway), no destructive git operations. A
scheduled task may process standings CSVs Ben has already dropped in the
inbox and remind him which contests still need a manual pull. Commit with a
descriptive message when a task changes tracked files.

## Post-slate
The inbox is FLAT. Do not sort it into per-contest-type folders: the miner
reads Classic vs Showdown off the lineup cells, and a folder is a second
copy of that fact that can disagree with the first.

For each standings CSV in data/standings/inbox/: run
`python -m mlb_engine.field.field_miner` with --auto-salary, --registry and
--emit-ledger, run the verification checklist (utf-8-sig read, salary join
rate investigated, ownership recompute within 1.5 points of %Drafted,
duplication table present, contest JSON complete), append the emitted block
to the ledger archive, update the registry, move files to
data/archive/<date>/, commit. Ownership and outcome counts are conditioned
on contest archetype and field size, never pooled across them.

--auto-salary scores every salary CSV on disk against the contest's own
lineups and picks the one that fits, or declines to the standings_only tier
rather than joining the wrong slate. Join rate alone is not enough: one date
carries several draftgroups and a small one can sit entirely inside a larger
one, so the resolver also requires the field to have drafted nearly every
team in the candidate file. Identical copies of one slate are one answer;
two files that differ in content and fit equally well are reported as
ambiguous and need an explicit --salary.

The structural gate is hard and fail-closed: a zero parse, an unparsed share
over 20%, or a standings/salary contest-type mismatch all block archiving.
Never archive downstream of a PARSE FAILURE or WRONG SALARY FILE note.

## Showdown (active after Phase 3)
Roster contracts live in mlb_engine/optimize/roster_contracts.py. Classic
and Showdown are two contracts on one solver. Showdown archetypes never
pool with Classic in the ledger or the ownership work.
