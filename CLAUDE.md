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
- Supervised build that takes its own retries: `python tools/autobuild.py`,
  policy described under Autonomy below.
- Adversarial review of a delivered portfolio, and the dual-objective
  frontier: `python tools/qa_portfolio.py`. Report, never a gate.
- Post-slate archival: docs/cowork_archival_runbook.md
- Keeping disk, container and GitHub in sync: docs/cowork_sync_protocol.md,
  which wraps `python tools/sync_check.py`. Read it before moving files
  between the mount and a container, before believing `git status` on the
  mount, and when a git operation dies on a stale `.git/index.lock` — this
  mount grants create and truncate but not unlink, so `rm` cannot clear one
  and the remedy is a timestamped `mv` (R109).
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

## Autonomy (Ben, 2026-08-16)
Ben's instruction: use your intelligence to override, relax and constrain
without his intervention, then try to poke holes in the result. Build
decisions are yours. Do not ask permission for a call you can make on
evidence you can gather; ask only for a fact only Ben has.

What you may do unattended, because the engine has already classified it:
- Grow the bank, always. It is search effort, never strategy, and it is the
  first remedy for every refusal against an unexhausted job list.
- Apply a feasibility remedy the engine NAMED and classified structural
  (`STRUCTURAL_FEASIBILITY_CHECKS`), to the named value and no further.
- Override a pool blocker whose shape you have classified benign, and assert
  `lineup_gate_passed` on that same evidence, since the gate derives from the
  pool report. Both together or neither.
- Choose postures, stack plans, and where to sit on the frontier below.

What stays hard, and is not reopened by this section:
- The money-and-entry wall and the manual-DK rule.
- Truthful labels. Ben wrote that rule; autonomy does not license a
  probability claim, and the proxies below are proxies.
- The preflight before upload, and blank reserved rows.
- Any reduction of the legal player pool, for any reason.
- An exposure cap. It has no engine-named floor, so raising one concentrates
  the entered set: that is a strategy change and it is Ben's.
- A pool blocker you cannot classify, a name-crosswalk failure (under 5 of 9
  hitters matched) above all. Stop and ask.

`tools/autobuild.py` is that policy as code and records every decision in
`outputs/<date>/autobuild_decisions.json`. Reach for it first; it is not a
replacement for judgment, and a stop it reports is a real question.

**The dual objective.** Ben wants large wins and no total washout. These are
one frontier, not two maxima: concentration is what wins a winner-take-all
ticket and is exactly what loses every entry at once. `tools/qa_portfolio.py`
reports both ends as deterministic review proxies. Note that in a one-ticket
satellite a non-winning finish and a last-place finish pay the same, so the
washout objective binds at the PORTFOLIO level (correlated failure across
entries), not within a lineup. Say so rather than quietly building for floor.

## Build contract
The steps are in SKILL.md. These five hold whatever path a build takes:
1. `live_data_adapters.build_slate_pool` is the required intake front door.
   Hitters are the confirmed nine per posted lineup plus the platoon-projected
   nine per TBD team; pitchers are feed probables plus explicit declarations.
   Every other salary row is absent, not excluded.
   **Lineup sources rank, and the ranking is PER SIDE (R143, Ben 2026-08-17):
   the DKSalaries CSV first, a paste second, an API pull third.** DK publishes
   the batting order in the `Starting` column, 1-9 next to the Player_ID this
   file already calls authoritative, so a side DK has posted is sourced from
   the salary file and stamped confirmed, and no paste or fetch is spent on it.
   Only a COMPLETE 1-9 counts; a partial DK side is a projection and falls
   through to the feed unchanged. `merge_dk_starting_into_feed` runs inside the
   front door so no caller can bypass the ranking, and it only ever adds or
   upgrades a side. `dk_order_coverage` is the one definition of "covered",
   shared by the pool and by any caller deciding whether to fetch; when it
   reports every side covered, `build_slate.py` makes no API call at all.
   Two consequences to state rather than discover. DK ships no handedness, so a
   side DK covers and no feed does is named in `f4_handedness_unavailable` and
   its F4 platoon component is unavailable, not silently zero; supply a feed if
   F4 matters more than the fetch costs. And where DK and a paste disagree on
   the same posted side, DK wins per the ranking and the difference is NAMED in
   `dk_batting_order.disagreements`, never silently resolved: the CSV is a
   point-in-time download and a paste has no timestamp, so neither can be
   proven fresher and the operator gets the fact instead of a guess.
   A PARTIAL side is a third case and it is now stated rather than implied
   (R60). It is not confirmed, so it routes through the TBD path and its
   posted hitters stay `Projected_Starter` — but a posted slot is OBSERVED and
   the two fills below it are PRIORS, so the order is posted starters, then
   platoon projection, then APPG, and a posted starter is never displaced by
   either. Ranking the whole roster by APPG is what let a bench bat with a
   better season take a posted starter's seat while the report read
   `fallback_top9_appg, 9 hitters`. Any posted starter that still does not
   reach the pool is NAMED in the pool report; and `tbd_fallback='exclude'`
   drops the team's seeded rows too, because "team excluded" has to mean
   excluded. What the seed does NOT do is stamp F2 from the posted slot: F2
   from batting order belongs to the confirmed path, and whether an
   incomplete lineup's slot earns it is a strategy question for
   MLB_Classic.md, not a pool-membership fix.
   **A lineup Ben pastes outranks any API pull and is never re-fetched (R32).**
   R143 narrowed this: the paste is second, not first, behind a complete DK
   1-9 for the same side. It is still primary over the API and over every side
   DK has not posted, which on a pre-lock slate is most of them.
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
3. Every build is reviewed before it certifies, and WHERE the review happens
   depends on the door (R63, decided 2026-08-08). Entering at the engine API,
   `run_slate(approve=False)` comes first, always; it is the only caller of
   R28's `_plan_joint_allocation`, so it is the only place the BANK-interaction
   verdict exists. Entering at `build_slate.py`, the review is the script's own,
   on its single `approve=True` call: slate clock, pool report, postures, stack
   plan, caps, feasibility, and one Blockers line where every blocker maps to an
   engine action, with a refusal at exit 3 carrying all of it in the brief.
   build_slate does NOT run a plan leg first, deliberately: on the sliced path
   that solves the identical MILP on the identical candidates twice, and on the
   direct path it builds a second bank that is not the build's and spends the
   window the real bank needs. What build_slate therefore does not have is the
   plan verdict, and it does not pretend to; what it has instead is the refusal
   itself, which is the same MILP's answer and now names bank growth before any
   control change (R98). Never approve a slate whose pool report you have not
   read.
4. The certified artifact is runs/<run_id>/final/DKEntries.csv and it is
   immutable. outputs/<date>/ holds the mirror, returned as `delivered_path`.
5. Refinements after delivery go through `run_late_swap` with
   authorized_entry_ids, never a rebuild. A locked game admits no new players.

## Session start
1. `git status`: apply the foreign-dirt rule in the multi-session contract
   below. Say what is dirty, and whose it is where a claim names an owner,
   before touching anything.
2. `python tools/audit.py --run-tests --terse` must print
   `PASS  v2.26.0  26 modules  1034 tests`. The module count comes off the
   filesystem and moves on its own; the test count is a pin, and since R62 it
   is a PER-SUITE pin (`EXPECTED_SUITE_COUNTS`) that the total is derived
   from. Each audited suite runs in its own subprocess, so a shortfall names
   the suite that lost it. A clean run prints exactly the line above; anything
   else appends what is abnormal — `N skipped`, and `{suite ran/pinned
   state}` for each suite off its pin. Read the state word before touching a
   pin: only `grew` is a stale pin. `shortfall`, `skipped_in_place` and
   `absent` are LOST COVERAGE, they name the precondition to stage, and
   lowering the pin to meet them is how the golden replay's nine tests would
   leave the gate for good. All four are WARNINGS: proceed, fix after the
   slate. A failing suite blocks. The audit gates test_core, test_showdown,
   test_upload_integrity, test_golden_replay, and test_paste_lineups.
3. `python tools/solver_probe.py --date <date> --entries <n> --budget <s>`
   before any build. Exit 3 means the bank does not fit: pass `time_budget_s`
   and accept a partial bank, or slice with `mlb_engine.optimize.bank_cache`.
4. Read the ledger Quick Card: ledger/MLB_Classic_Calibration_Ledger.md
   section 0 plus section headers. The full read is post-slate work.

5. `grep '^## ' CHANGELOG.md | head -15`: the newest fifteen HEADINGS, which
   is roughly 400 tokens. Read the heading list, not the entries. Before
   touching any area a heading names, read that entry in full. This is the
   answer to "am I about to act on something that moved last week", and it is
   the step that would have caught the 2026-08-16 skill snapshot 85 commits
   behind. Ben asked for a full changelog review at session start (2026-08-17);
   the file is 5,800 lines and ~119,000 tokens, so reading it whole would spend
   most of a context window before any work and would be skipped under deadline
   within a week. Headings survive; the full read does not. Note this step is
   about STALENESS only. The other half of Ben's ask, nothing gets overwritten,
   is step 1 plus the claims mutex, not this.

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
- DEV: writes mlb_engine/, tools/, tests/, docs/, skills/, CHANGELOG.md,
  MLB_Classic.md, MANIFEST.md, .gitignore, .gitattributes, requirements.txt,
  requirements.lock, and this file. `claim.py`'s own `WRITE_SETS` carries
  that list minus CHANGELOG.md and requirements.lock, so `dirt --role DEV`
  under-reports foreign dirt on the one file the contract most wants
  serialized (R31(c), open). Never edits
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
Take with plain mkdir (atomic, fails when THAT EXACT NAME is held):
`mkdir claims/<resource>_<utc-date>`, then write owner.json (role, scope,
taken_utc). Two kinds. Engine, ledger, and inbox are MUTEXES: a failed
mkdir means held, read owner.json and stop; never delete or take over
another session's claim. **That mutex is NOMINAL and it has now cost
something.** mkdir only collides on the identical name, so `take
engine_myslug` mints its own directory and blocks nobody: take the BARE
resource name, and glob `claims/<resource>*` before writing, not just the
dated name you would mint. On 2026-08-11 a second DEV session took
`engine_branchfix_2026-08-11` beside a held `engine_2026-08-11` and its
working-tree restore destroyed three uncommitted files in the first
session's write set. The blast radius is UNCOMMITTED work only, so commit
early and by explicit path; making the mutex refuse a held sibling is
Ben's call and stays open (R31(d)). Slate claims are BEACONS: BUILD lights one
before staging (`python tools/claim.py take slate_<date>_<tag> --role
BUILD --beacon`) so DEV can see that builds are live, and a beacon
another session already lit means a parallel build, which never stops a
build. Yesterday's claims are stale by definition; a stale claim today is
Ben's to arbitrate. Release with `python tools/claim.py release
<resource>`, which writes released_utc AND touches the RELEASED marker;
owner.json is authoritative, so a hand-written marker alone does not
release and `check` will keep reporting the claim HELD (R102). Re-read claims/ immediately before writing any contended surface,
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
