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
- What's missing from the standings inbox: skills/mlb-standings-pull-checklist/SKILL.md,
  which wraps `python tools/awaiting_standings.py scan`. Regenerated, never
  hand-maintained.
- Showdown mechanics: skills/generate-lineups/references/showdown.md
- Any tool's flags: `python tools/<tool>.py --help`
- What to build next: docs/2026-07-27_backlog_v2.md, the single live backlog.
  OPEN work only; its "What do we tackle next" section is the answer every
  session gives to that question. Do not write a new review document.
- What already changed and why: CHANGELOG.md, newest first, DEV writes it.
  One entry per shipped change with its rationale, keyed to its R-number, and
  the scope is EVERY change in the DEV write set — engine, tools, tests,
  skills, docs, this file. A completed backlog item's entry MIGRATES from the
  backlog into the changelog in the completing commit (Ben, 2026-08-01);
  history from before that date sits under "Imported record" at the bottom.
  Slate outcomes go to the ledger and per-build records to that run's brief;
  neither goes here.

## Build contract
The steps are in SKILL.md. These five hold whatever path a build takes:
1. `live_data_adapters.build_slate_pool` is the required intake front door.
   Hitters are the confirmed nine per posted lineup plus the platoon-projected
   nine per TBD team; pitchers are feed probables plus explicit declarations.
   Every other salary row is absent, not excluded.
   **A lineup Ben pastes is the primary source and is never re-fetched (R32).**
   `tools/lineups_from_paste.py` turns an mlb.com/starting-lineups paste into an
   ordinary `lineups_feed.json` tagged `source: operator_paste` per side; the
   API feed is fallback for uncovered sides only, via `--merge-feed`. A pasted
   name that is AMBIGUOUS or UNMATCHED is a blocker and NO feed is written,
   because a half-resolved lineup arrives downstream looking like a posted
   partial. A name that resolves but is ABSENT FROM THE DK POOL is a different
   fact and is not fatal on its own: DK owns eligibility, so a starter DK did
   not list is unrosterable anyway and the slot is named in
   `unrostered_starters`. In bulk it does block, because it stops being N facts
   and becomes one: past half of one posted side, or `SLATE_ABSENT_BLOCK_RATIO`
   of the paste with at least `SLATE_ABSENT_BLOCK_FLOOR`, the paste and the
   salary file are not the same slate (R32 round 2). A `1. TBD` line and a bare
   `TBD` in a probable's place are POSITIONAL FACTS, each holding an empty slot
   so the counts match; blocks and pitchers attach at a count of 0 or exactly 2
   and are otherwise refused, never guessed. DK's `Starting` column (SP/P) is a
   first-class probable source, and the paste wins where both name someone.
   A fully pasted slate reads no platoon reference, so item 2's staleness rule
   has nothing to gate.
2. The platoon reference ages against the SLATE, not its own collected_date.
   Past 7 days with a TBD team filled from it is a pool blocker at the
   engine default (`stale_platoon_policy='block'`); build_slate.py and
   late_swap.py pass `'warn'`, so it prints and the build ships (R27). A
   fresh RotoWire merge (no `--no-rotowire`) clears the age entirely.
3. `run_slate(approve=False)` first, always. The checkpoint is the review:
   slate clock, pool report, postures, stack plan, caps, feasibility, and one
   Blockers line where every blocker maps to an engine action.
4. The certified artifact is runs/<run_id>/final/DKEntries.csv and it is
   immutable. outputs/<date>/ holds the mirror, returned as `delivered_path`.
5. Refinements after delivery go through `run_late_swap` with
   authorized_entry_ids, never a rebuild. A locked game admits no new players.

## Session start
1. `git status`: apply the foreign-dirt rule in the multi-session contract
   below. Say what is dirty, and whose it is where a claim names an owner,
   before touching anything.
2. `python tools/audit.py --run-tests --terse` must print
   `PASS  v2.26.0  26 modules  684 tests`. The module count comes off the
   filesystem and moves on its own; the test count is a pin. A count mismatch
   with the suite passing is a WARNING and prints in brackets on the PASS
   line: proceed, fix the pin after the slate. A failing suite blocks. The
   audit gates test_core, test_showdown, test_upload_integrity,
   test_golden_replay, and test_paste_lineups.
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
  timeout is recorded in `solver_report`, never climbs the overlap ladder, and
  never enters `attempted` in the bank cache. A time-limited incumbent is
  verified against the constraint matrix and then
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

## Multi-session contract (v1.1)
Cowork sessions sharing this folder have no coordination: no locks, no
messages, no registry. This file and the filesystem are the only channels.
Every session follows this section before its first write.

Roles; Ben's first message assigns one:
- BUILD, one slate: writes runs/, outputs/<its date>/,
  data/slates/<its date>/, and its own bank cache. Nothing else.
- ARCHIVE: writes ledger/, data/archive/, data/standings/,
  data/reference/. Runs only outside live build windows.
- DEV: writes mlb_engine/, tools/, tests/, docs/, skills/. Never edits
  engine paths while any slate beacon is lit: builds re-import modules
  between steps, so a mid-slate edit changes a running build. A DEV change
  is not shipped until CHANGELOG.md carries its entry, in the same commit
  as the change — and "change" means the whole write set, docs and this
  file included, not code alone. Enforced by `audit.changelog_debt`, which
  warns at the next session's start when commits touching the DEV write
  set (inbox fragments exempt) outrun the changelog; it cannot see the
  session now running, so the discipline is still yours and the warning is
  only the backstop.
Unassigned: building lineups is always permitted, claims present or not;
light the beacon and go. Ledger, inbox, engine, and contract surfaces
still need their role and its mutex; outside a build, when in doubt, ask
Ben.

Claims are live session state in claims/, gitignored except .gitkeep.
Take with plain mkdir (atomic, fails when held):
`mkdir claims/<resource>_<utc-date>`, then write owner.json (role, scope,
taken_utc). Two kinds. Engine, ledger, and inbox are MUTEXES: a failed
mkdir means held, read owner.json and stop; never delete or take over
another session's claim. Slate claims are BEACONS: BUILD lights one
before staging (`python tools/claim.py take slate_<date>_<tag> --role
BUILD --beacon`) so DEV can see that builds are live, and a beacon
another session already lit means a parallel build, which never stops a
build. Yesterday's claims are stale by definition; a stale claim today is
Ben's to arbitrate. Release by writing a RELEASED file inside your own
claim. Re-read claims/ immediately before writing any contended surface,
not only at session start. ARCHIVE claims ledger and inbox before mining;
DEV claims engine before touching code.

Git under multiple sessions: classify dirty paths against your write set.
Foreign dirt inside it blocks and names the owner; foreign dirt elsewhere
is reported and left alone. `git add` by explicit path only, never `-A`.
While any claim you do not own is live: no checkout, reset, stash,
restore, or clean.

One writer per contended file. Only ARCHIVE edits the ledger; only DEV
edits the backlog and this file, and contract changes happen only with no
other session live. Everyone else records by dropping a fragment in
ledger/inbox/ or docs/backlog_inbox/ (create-only for every role, one
note per file, named <date>_<role>_<slug>.md); the owning role merges and
deletes consumed fragments.

Builds never block builds, the same slate included: Entry IDs are fixed
by the DK template, so two certified files for one contest are
alternatives, not a union, and the manifest's supersession plus the
sha256 in every brief name the delivery. One ban survives, because it is
structural: never split one entry bank across sessions by Entry ID
ranges. Portfolio caps are properties of the whole entered set and
certification is per run, so a stitched union passed no gate. Every
brief states the delivered file's sha256; Ben checks it at upload before
entering anything.

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
max_shared_players (4 of 6, counting the player and not the role), and no
captain exceeds max_cpt_exposure_pct
(0.33, a floor() of pct * n, which is why it is not 0.35). Both relax before
they truncate, in the order overlap then captain lock then thesis, because a
short bank leaves a blank reserved row and a blank row blocks certification.
Every relaxation is counted in the brief. A portfolio is not clean because the
gates passed; it is clean when the relaxation counts are zero.

## Scheduled task sessions
Each scheduled run is its own session. Read this file and the ledger Quick
Card first. A scheduled task runs as ARCHIVE: take the ledger and inbox
claims first, and a claim you cannot take turns the run into a report,
never a write. Stay file-scoped: no DraftKings fetching, no destructive git
operations. A scheduled task may process standings CSVs Ben has already
dropped in the inbox and remind him which contests still need a manual pull.
Commit with a descriptive message when a task changes tracked files.
