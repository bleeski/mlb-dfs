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
  mount, and when a git operation dies on a stale lock — this
  mount grants create and truncate but not unlink, so `rm` cannot clear one
  and the remedy is a timestamped `mv` (R109).
  **The lock is a CLASS, not `index.lock` (R109 third sighting, 2026-08-29).**
  `HEAD.lock` and `next-index-*.lock` block every git write with the same
  message `index.lock` produces, so a session sweeping only the one name reads
  a still-blocked repo as clean. Diagnose with `find .git -name '*.lock'` and
  `mv` each hit aside. Sweep at session start AND before every git write: on
  this mount a plain `git status` leaves a fresh `index.lock` behind, so the
  read that tells you the tree is clean is itself what blocks the next `add`.
- What's missing from the standings inbox: skills/mlb-standings-pull-checklist/SKILL.md,
  which wraps `python tools/awaiting_standings.py scan`. Regenerated, never
  hand-maintained.
- Showdown mechanics: skills/generate-lineups/references/showdown.md
- Any tool's flags: `python tools/<tool>.py --help`
- What to build next: docs/backlog.md, the single live backlog.
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
  **R233. An entry claiming a rule now lives in ONE place carries the grep
  that enumerates the class at that head, with its hit list.** Seven greenfield
  editions have found the same event: a fix closes N named sites and the class
  has N+1. R167 unified four copies of the units rule and the fifth still
  clamps; R169(a) saved the decision log on the timeout path and the sibling
  wall-clock exit still destroys it; R153 bound both Showdown caps "on every
  rung" and the floor rung still drops one; R159 unified two components and
  minted a new disagreement between its own comment and its own guard. Each
  was cheap to prevent and expensive to find. The rule is not "grep before
  fixing" — sessions already do — it is that the enumeration goes in the ENTRY,
  where the next reader and the next reviewer can check the count instead of
  re-deriving it. A deliberately-kept copy is fine; it is named in the entry
  with the reason it survives.

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
  pool report. Both together or neither. **This pair did not actually work until
  R133 (2026-08-18):** `--assume-gates` promoted a gate only where the derived
  value was None, so asserting the gate against a derived False was discarded
  while still being recorded, and both moves together still lost the build at the
  pre-export gate. The assertion now reaches it, lands in `overridden_gates` with
  the evidence it contradicts, and is a different record from `assumed_gates` --
  one says nothing checked, the other says the check said no.
- Choose postures, stack plans, and where to sit on the frontier below.
- **Loosen `max_pitcher_exposure_pct` / `max_player_exposure_pct` /
  `max_primary_stack_exposure_pct` to rescue a proven-infeasible joint MILP
  (R157, Ben 2026-08-22).** Conditions, both required: both
  `STRUCTURAL_FEASIBILITY_CHECKS` remedies are already applied at their named
  values, and the engine's own infeasibility error names no single control as
  binding (`"no single control is arithmetically binding... the interaction of
  the active controls is"`) -- i.e. the remaining bind is the exposure caps'
  interaction, not something the engine can name a floor for on its own.
  Confirm with all three fully open (1.0) first as a sanity check that the
  bank can certify at all, then set a delivered-file target looser than the
  posture defaults but short of 1.0 -- re-derive it from that slate's
  structural floors (`player_exposure_floor` etc. in the feasibility report),
  never hardcode a number forward. 0.55 was that target on 1335_3g (9 entries,
  6 pitchers, 3 games; floors were all 3-of-9); a bigger or thinner slate
  floors differently. Never leave the delivered file at 1.0. Record the
  before/after values and the triggering diagnostic in the brief, same
  discipline as any other override. Origin: asked to arbitrate this exact
  infeasibility on 1335_3g via AskUserQuestion, Ben answered, then delegated
  the class of decision rather than answer it per slate -- `tools/autobuild.py`
  does not implement this yet (its docstring still lists exposure caps under
  "WHAT IT WILL NOT DO, EVER"); until it does, this is manual
  `--controls-override` reasoning, not the supervisor's own loop.

What stays hard, and is not reopened by this section:
- The money-and-entry wall and the manual-DK rule.
- Truthful labels. Ben wrote that rule; autonomy does not license a
  probability claim, and the proxies below are proxies.
- The preflight before upload, and blank reserved rows.
- Any reduction of the legal player pool, for any reason.
- An exposure cap changed as a STRATEGY preference -- more or less
  concentration for its own sake, independent of whether the build certifies.
  That still has no engine-named floor and is still Ben's. (Loosening one to
  rescue a proven-infeasible joint MILP is the delegated case above, R157,
  and is a feasibility rescue, not a strategy change.)
- A pool blocker you cannot classify, a name-crosswalk failure (under 5 of 9
  hitters matched) above all. Stop and ask. R133 made that enforcement rather
  than instruction: `--ignore-pool-blockers` REFUSES a crosswalk failure by name
  at the blocker, instead of spending the build and losing it at the gate.
  Two related things the same item settled, because this bar had three readers
  and two of them disagreed. The 5-of-9 above is the CROSSWALK bar and always
  was; a team merely short of nine hitters is a different fact, and its bar is
  `MAX_HITTERS_PER_TEAM` (5), the count that fills a maximum DK stack. A team at
  5 through 8 warns and certifies, which is what the pool report's confirmed
  path always said and what the thin-team blocker and the lineup gate both used
  to override at `< 9`. `pool_report.thin_teams` is now the one definition.

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
1. `git status --short; git log --oneline -12`: one call answering both halves
   of "what am I walking into". `git status` gets the foreign-dirt rule in the
   multi-session contract below; say what is dirty, and whose it is where a
   claim names an owner, before touching anything. `git log` is how a session
   learns what MOVED, including a session on another machine that has only
   just pulled. The subjects carry the R-numbers, so this is the recency index
   and CHANGELOG.md is the reasoning behind it: before touching any area a
   subject names, read that entry in full.
   Git is the mechanism here, not a document (Ben, 2026-08-17). A changelog
   heading read was tried the same day and dropped: it cost the same ~310
   tokens, could not answer "since when", and needed its own call, while this
   rides the `git status` call that already runs. Two consequences worth
   stating. A commit subject is only as good as the contract that writes it,
   so a vague subject breaks this step, not just the log. And git tells a
   clone nothing it has not PULLED, which makes step 0 below the real
   prerequisite.
0. Step 1's `git log` is only as current as the clone, and since R146 the
   audit in step 2 FETCHES before measuring, so `behind` is a measurement
   rather than a hedge. The credential is `GH_PAT` in `REPO/.env`
   (`sync_check.find_token` resolves it there as well as from the
   environment); it reaches git through `GIT_ASKPASS` only and never touches
   argv, a remote URL, `.git/config`, or any output. `--no-fetch` opts out and
   says so. If the fetch cannot run, the reading falls back to the stale ref
   and is LABELLED, never presented as clean.
   **A failed fetch names WHICH of three things stopped it (R147): no network,
   a rejected credential, or unknown.** It read "check the token scope or
   expiry" for every failure until 2026-08-17, which sent a session at a
   working PAT while the real cause was a sandbox with no outbound network at
   all. Read the reason before touching the token. A cloud Cowork session's
   device VM is that sandbox: DNS resolves, TCP to GitHub does not, and the
   proxy answers CONNECT with 403 even for a public repo, so the fetch there
   never succeeds and `behind` stays a fallback reading. The container reaches
   GitHub normally.
   What no fetch can fix: sessions COMMIT and Ben PUSHES
   (docs/cowork_sync_protocol.md), so disk routinely runs ahead of GitHub and
   the audit names that too. `default_branch_mismatch` USED to read this clone's
   LOCAL `origin/HEAD`, a cached copy of GitHub's default from whenever
   `set-head` last ran, so it agreed with the cache and never with GitHub;
   since R148(a) it reads the remote itself and reports which source answered,
   so a null there means "asked and agrees" only when `default_branch_source`
   says `remote`, and it carries R147's classified reason when it could not ask.
   **The default is `main` and `master` is deleted. Verified 2026-08-18 from
   Ben's Windows machine, and the COMMAND is the citation, not the person:**

       git ls-remote --symref origin HEAD  ->  ref: refs/heads/main   HEAD
       git fetch --prune                   ->  - [deleted]  (none) -> origin/master

   This file asserted "still `master`" until that date, and
   the failure is worth keeping: the reading was TRUE when R111 verified it the
   same way on 2026-08-11 (`ref: refs/heads/master`, `master` = `d0212c2`), Ben
   then acted on it, and no document was
   updated, so an 08-18 session repeated a seven-day-old reading as current and
   sent him to change a setting he had already changed. That is R145-R147's
   lesson applied to a SETTING rather than a ref — a value nothing on this disk
   can re-read goes stale silently and confidently. Trust the method, not the
   number: `git ls-remote --symref origin HEAD` from a machine holding the
   credential is the only reading of GitHub's default, it cannot run on the
   device VM at all, and this clone can carry a stale `origin/master`
   indefinitely because a push never prunes.
2. `python tools/audit.py --run-tests --terse` must print
   `PASS  v2.26.0  27 modules  1468 tests`. The module count comes off the
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
   **That one command does not fit one Cowork bash call, so the gate has a
   supported split (R152).** Measured 2026-08-18 on the device mount:
   `tests.test_core` alone needs ~89s and one of its tests needs 35.8s by itself.
   **The 45-second figure this paragraph carried until 2026-08-29 was WRONG, and
   so are the flag defaults derived from it (R271(b)).** The real Cowork bash
   ceiling is ~180s when the call passes an explicit timeout. Pass the budget:
   `python tools/audit.py --gate-run --gate-budget 130 --gate-ceiling 165`.
   Measured 2026-08-29 on this mount: **one** `--gate-run` assembled all five
   suites warm, and **five** did it from a cold `__pycache__` (one suite per
   call, `test_core` being the expensive one), against the twenty-odd calls the
   28/39 defaults force either way. Budget for five, not one — a session that
   has just cleared caches for a mutation check pays the cold price, and quoting
   the warm number as the expectation is how a measurement becomes a promise.
   Do not ask Ben to run it instead: his Windows Python has no scipy and
   `.pylibs/` is a Linux build, so `--run-tests` cannot pass on his host
   (R271(c)). The gate is the session's job.
   Backgrounding it is the trap and not the workaround —
   `nohup` and `setsid` both die with the call, the log comes back EMPTY, which
   reads exactly like a silent pass, and a killed `audit.py` strands the
   session's next commit on a zero-byte `.git/index.lock` (R109). Instead:
   `python tools/audit.py --gate-run` until it prints `GATE COMPLETE` (exit 3
   means more remains), then `python tools/audit.py --gate-report --terse`,
   which prints the SAME pinned line above when every unit ran and
   `GATE INCOMPLETE ...` when it did not. Only a complete assembly may print
   that line. Completeness is class coverage and not a matching count, every
   record is stamped with a content fingerprint of the tree so an edit mid-run
   resets the state rather than mixing two trees, and a unit that cannot finish
   in one call is NAMED rather than skipped. State lives in `.audit_gate/`
   (gitignored); `--gate-reset` starts over.
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

A run-scoped patch or throwaway runner goes in `tools/_scratch_<tag>/`,
never a bare `tools/_something.py` (Ben, 2026-08-18). `_scratch_*/` is
already gitignored AT ANY DEPTH, so the directory keeps `dirt` clean while
the file stays where the build imports it; a bare file in `tools/` is
foreign dirt that blocks every later DEV session and names an owner who
went home. Two such files did exactly that for five days after the 08-13
1507_3g slate. Sweep the directory when the slate closes, which on this
mount means `mv` into `_to_delete/`, because a patch that outlives its
slate is a HAZARD and not clutter: both 08-13 anchors still matched the
tree on 08-18, so importing that file would have silently changed engine
behaviour on a slate it was never scoped to.

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

THREE portfolio controls are enforced in the solver, not in review, and relaxed
only in the stated order and counted (R153, Ben 2026-08-19):
- `max_shared_players`, 4 of 6, counting the PLAYER and not the role.
- `max_cpt_exposure_pct`, **0.25**, no captain above a quarter of the entered set.
- `max_player_exposure_pct`, **0.50**, no PLAYER in any role above half of it.
  This is the portfolio-level washout axis the dual objective names and the
  module did not have. On the 2026-08-19 ARI@BOS build the overlap bound was
  clean, the captain cap was clean, and one cheap leadoff bat was in 12 of 19
  entries: correlated failure neither other control was measuring.

Every cap count is a `floor()` of pct * entries, so realized exposure lands at
or below the requested pct at every entry count. (That rounding rule is why the
captain cap used to be 0.33 rather than 0.35; 0.25 has no such edge.) The one
escape is `pct * n < 1`, where the count clamps to 1 rather than forbidding
everyone.

They relax before they truncate, in the order overlap, then player exposure,
then captain lock, then thesis, because a short bank leaves a blank reserved row
and a blank row blocks certification. Player exposure sits second because
relaxing it puts one more entry on a player already at half the set, a washout
cost spread thin, where relaxing the captain lock concentrates the single
highest-leverage slot.

**Both caps bind against the REALIZED set, not against an apportionment**, and
that distinction is the whole of R153's second pass. A cap enforced anywhere
other than where the roster spots are actually spent is not a cap: `solve_ladder`
trusted `build_thesis_ladder`'s captain apportionment and its own lock-relaxation
rung then substituted a captain with no cap awareness (26.3% realized under a 25%
cap), and the player cap carved out a thesis's own `cpt` and `locks` on the
reasoning that a lock is more specific (57.9% realized under a 50% cap, with
every relaxation counter reading clean). A capped player now comes off the
thesis's captain slot and locks BEFORE the solve. That is not a relaxation and is
not counted as one — nothing gave way, the cap held and the thesis label moved —
so it is named in `player_exposure.cap_reassignments` and `.locks_dropped`.

Every relaxation is counted in the brief. A portfolio is not clean because the
gates passed; it is clean when the relaxation counts are zero. Override any of
the three through `--controls-override`, which reads all of them from one dict.

## Scheduled task sessions
Each scheduled run is its own session. Read this file and the ledger Quick
Card first. A scheduled task runs as ARCHIVE: take the ledger and inbox
claims first, and a claim you cannot take turns the run into a report,
never a write. Stay file-scoped: no DraftKings fetching, no destructive git
operations. A scheduled task may process standings CSVs Ben has already
dropped in the inbox and remind him which contests still need a manual pull.
Commit with a descriptive message when a task changes tracked files.
