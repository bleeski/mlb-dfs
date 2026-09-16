# CLAUDE.md - MLB DFS Engine (personal project)

## Status note, 2026-09-15: the thirteenth edition is LANDED AND GATED; the push is Ben's
R338 commit one (`5b1b574`) and R302 stage 0 (`3fcc161`) landed on `main` on
2026-09-11, and on 2026-09-15 a Claude Code DEV session ran what they owed on
Ben's machine: `python tools/audit.py --run-tests --terse` printed
`PASS  v2.26.0  40 modules  2072 tests` (the count moved 2066 -> 2072 in that
session's own R348, then 2089 when R340 landed after it, and 2129 when CC-2
landed on 2026-09-15), and `python tools/solver_probe.py --date 2026-09-08`
FITS at 32s against a 130s budget, which is the schema-2 digest evidence step 8
asked for. R338 is closed and its board entry is deleted; roadmap **CC-0**,
**CC-1** (R340) and **CC-2** (R343 + R333) are done and the NEXT pointer is
**CC-3**. **The push debt this note opened with is PAID**, measured rather than
assumed: `python tools/sync_check.py` on 2026-09-15 read `disk main b0eaa2c` /
`GitHub main b0eaa2c (measured via GH_PAT)` / `disk and GitHub agree`, so
everything through CC-1 is on `origin/main`. Pushing stays Ben's, and the audit
names it on every run while commits sit ahead; run the measurement before
repeating the claim, because a debt written down is exactly the kind of value
that goes stale silently on this board.

Read the gate line's bracketed warnings as facts about the HOST, not the tree.
One of them will persist until Ben removes
`%TEMP%/pytest-of-benja`, an unreadable directory that R348 works around and
does not pretend is gone; see session-start step 2.

Per Ben (2026-09-15) DEV sessions now run in **Claude Code on his machine**, not
Cowork: the Sandbox section below is Cowork's and does not bind a Claude Code
session (the full gate runs in one call -- measured ~9 min on the pinned
`.venv` -- and `rm` works), while the claims protocol, explicit-path `git add`,
and the CHANGELOG-in-the-same-commit rule bind every session whatever runs it.

Nothing below is superseded and NEITHER package is the build path: the Authority
section governs, builds enter at `execution_pipeline.run_slate` through
`skills/generate-lineups/SKILL.md`, and `mlb_engine/production/` is stage 0,
verified offline, not canonical, no projection, ownership, field or archive
source. Do not commit engine files from a BUILD session. `git status` on this
mount no longer shows the landing as dirt; dirt you see is another session's,
and the multi-session contract's foreign-dirt rule applies to it.

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

**Repair is not strategy (R272, Ben 2026-08-29).** His instruction, quoted
because it is the reason this clause exists: *"you made me intervene by
answering questions and I want you to make those changes autonomously."* With a
dead pitcher in 10 of 31 entries and locks at 16:05 and 16:10, BUILD raised two
questions at 15:16 and both came back "recommended option" — the tell that the
question was the session's to decide, and asking it spent Ben's clock inside a
lock window. The section above classifies by what the ENGINE named and by
strategy-vs-feasibility, so a scratched player fell through to "ask." Four
additions, all autonomous:
- **Replacing a player who will not play is a REPAIR, not a strategy change.**
  A scratched arm, a bat absent from a posted lineup, an IL/OUT status. The
  entered set already contains a zero; leaving it there is not the conservative
  choice, it is the damaging one.
- **Choosing among the legal replacements is autonomous.** Five of the six
  filters are mechanical legality and enumerable: DK slot eligibility, salary
  cap, game not yet locked, confirmed starter, not already rostered. The sixth,
  **not opposing a rostered SP, is NOT legality — it is the anti-correlation
  CONVENTION** (R288, corrected 2026-09-01; this sentence listed all six as
  legality and that was false about DK's rules). It is KEPT as the repair's
  default anyway, and the reason is narrow: a repair runs unattended inside a
  lock window, so the conservative construction is the right default there even
  though the wall is wrong at build time.
  Rank survivors by the build's own projection (APPG where no Base exists) and
  take the top one. `tools/repair_entry.py` is that filter and it prints a
  first-match rejection census, so a refusal can be argued with rather than
  overridden.
- **A collateral downgrade needed to afford a repair is autonomous when it is
  the minimum-loss one.** Pick the open-game hitter swap costing the least
  projection and record it.
- **Shipping a hand-corrected file is autonomous when the engine cannot produce
  one and both `verify_export.py` and `preflight_upload.py` exit 0.** Labeled
  review-grade, never certified; full diff against the parent reported; sha256
  stated. A preflight-clean repair beats an engine-certified file carrying ten
  dead slots.
  **That two-referee sentence was worth less than it read until R292
  (2026-09-02), and it is worth more now.** `verify_export.py` never called
  `check_started_games` — R287's blanket "no roster slot holds a player whose
  game has begun" — so on a file with no parent to diff against it WARNED and
  exited 0 on exactly the condition that cost the 09-01 slate. It runs that check
  now — on the no-parent branch only until R324 (2026-09-08), because a late swap
  legitimately retains started players in its frozen slots and only a CHANGED
  slot is the question when a parent exists; both branches now go through the one
  transition helper under Hard guardrails, so this clause's "both referees exit
  0" is a single rule rather than two that agreed by inspection. R324 also made
  that clause SATISFIABLE on a postponed-game slate, where R314 had left it
  impossible: both tools hard-failed a legal file and the only ways past were
  `--force` and a false clock, which this section forbids. Two further R292 corrections to what this clause assumed
  about its own tool: `repair_entry.py --out` could not write a DK-valid file at
  all (it re-emitted the whole source table after the repaired rows, two headers
  and every dead player intact, and exited 0 saying `wrote <path>`), and its
  candidate filter ADMITTED a player whose game was already underway. Both are
  fixed; the clause now rests on tools that do what it says they do.

**The no-hitter-versus-rostered-SP rule is a GUIDELINE, not a wall, and
overriding it is autonomous (R288, Ben 2026-09-01).** His instruction, verbatim:
*"the answer might be to have some lineups where we have batters facing pitchers
in the same lineup."* DraftKings does not prohibit the construction and the
evidence is DK's own scored output rather than a reading of its rules page:
across 22 archived slate dates, 19,072 of 102,201 fully-resolvable Classic
entries in `data/archive/` roster a hitter facing a rostered SP, and
contest-standings-192464310 (2026-07-19, 1,486 entries) has ranks 1, 2 AND 3 all
holding Ryan McMahon (NYY) beside a rostered Yamamoto (LAD) starting against NYY.
DK accepted, scored and paid those. The frequency is slate-size dependent — 62.5%
of entries on that 2-game slate, 3.2% on the 12-game 2026-08-11 slate — so on a
small slate the convention forbids most of the legal space.

So it sits with postures and stack plans among the delegated decisions, NOT with
the money-and-entry wall. The control is `--max-opposing-hitters-per-sp` (engine
default 0, which is the behaviour the unconditional constraint enforced); it is
PER SP, so a Classic lineup holding two arms has a per-lineup worst case of twice
the value. Move it on judgment without asking, and record the value and the
reason in the brief, which carries `anti_correlation` on every Classic build
including the default. `preflight_upload.py` WARNS and no longer fails, so
`--force` is not the price of a legal roster; `--force` stays frightening.

The measured cost of treating it as a wall, on 1940_9g: a hand builder carried
the convention as a hard rule with Gabriel Hughes at 54% exposure, which banned
every BAL bat from 20 of 37 lineups. BAL was the highest implied team total on
the slate (~5.9, in an 11.0-total game at Coors) and finished with 2 roster slots
out of 370. A pitcher-selection error became a hitter-distribution error through
a constraint nobody re-examined.

The safety argument is narrow and it is checkable: **`repair_entry.py` touches
no portfolio control** (R267(c)), so none of the above can move exposure, a
stack plan or an overlap bound as a side effect. `SingleSlotRepairTests.
test_it_touches_no_portfolio_control` asserts that against the source. If a
change ever makes the repair path read one, this clause has lost its argument
and the two are revisited together, in the same commit.

What stays hard, and is not reopened by this section:
- The money-and-entry wall and the manual-DK rule. Nothing in the repair clause
  touches them: a repair writes a FILE, and Ben still uploads it by hand.
- Any exposure or stack change with **no dead player behind it**. The repair
  clause is licensed by a scratch; without one it does not apply, and the
  strategy bullet below governs.
- Anything needing `--force`, or leaving a gate failing.
- Any reduction of the legal player pool, for any reason (restated because a
  repair is the moment it would be tempting).
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

**Blank or unfilled entries are the MAXIMUM washout, not a conservative
outcome. The washout objective never justifies withholding a deliverable. If
the choice is a concentrated file or no file, ship the concentrated file, state
the concentration plainly, and let Ben decide whether to enter it. Refusal is
only correct when the file would be ILLEGAL — a player in a started game, a
blown cap, a slot violation — never when it is merely poorly shaped.**

That paragraph is here because the rule above it was read backwards and cost a
slate (2026-09-01, 1940_9g). At T-5 the BUILD session wrote *"I'm stopping
rather than shipping 37 entries stacked on three pitcher pairs"* and cited the
portfolio-level washout clause to defend it. Thirty-seven blank entries is not
a hedge against washout; it is a washout with certainty 1.0, and three SP pairs
across 37 entries is a bad portfolio that can still win a satellite. Three
games left the addressable pool permanently. The clause exists to stop a
session quietly building for floor, never to license refusing to build.

## Build contract
The steps are in SKILL.md. These five hold whatever path a build takes:
1. `live_data_adapters.build_slate_pool` is the required intake front door.
   Hitters are the confirmed nine per posted lineup plus the platoon-projected
   nine per TBD team; pitchers are feed probables plus explicit declarations.
   Every other salary row is absent, not excluded.
   **Once a game is UNDERWAY the boxscore outranks all three sources below
   (R270(b), 2026-08-31).** `liveData.boxscore.teams.<side>.battingOrder` and
   `.pitchers[0]` from `statsapi.mlb.com/api/v1.1/game/<gamePk>/feed/live` are a
   RECORD of who played; DK, a paste and the API are PREDICTIONS of who will.
   A prediction cannot improve after first pitch and a record cannot be wrong,
   so the record wins for that game and only for that game. The reason this tier
   has to exist rather than being implied: the schedule hydrate stops carrying a
   game's lineup once it starts, so a "confirmed" test against the feed silently
   becomes "not posted" for exactly the games whose answer is certain, and a
   dead bat then reads identically to an unposted side. `observed_starter_state`
   returns THREE values (`started` / `did_not_start` / `unobserved`) and never a
   bool: `unobserved` means this game has not begun and the caller must fall
   through to the ranking below, and collapsing it into `did_not_start` is the
   same conflation R237 is filed on arriving through a new door. A side whose
   boxscore block came back empty on a game that IS underway is an unread block,
   named in `sides_unread`, never nine scratches.
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
   **The two REFEREES read this ranking too, since R305.**
  `preflight_upload.py` and `verify_export.py` prefer the salary file's own
  `Starting` column over any staged feed, by way of `dk_order_coverage` and
  `merge_dk_starting_into_feed` rather than a second reading of the column; the
  import is lazy and guarded, so a copy of the tool run from a bare directory
  still works and says which fallback it took.
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
   all. Read the reason before touching the token.
   **The device VM's egress is not a constant, and this paragraph asserted that
   it was (R316, 2026-09-06).** It read: "a cloud Cowork session's device VM is
   that sandbox: DNS resolves, TCP to GitHub does not, and the proxy answers
   CONNECT with 403 even for a public repo, so the fetch there never succeeds
   and `behind` stays a fallback reading." Measured on the device VM this date,
   every clause of that is false. `tools/audit.py` reported `fetched: true`,
   `fetch_age_hours: 0.0`, `default_branch_source: remote`; `.git/FETCH_HEAD`
   was written by that call; `tools/sync_check.py` printed
   `GitHub main c6dd17c (measured via GH_PAT)` and `disk and GitHub agree`; and
   `curl` returned 200 from api.github.com, statsapi.mlb.com,
   baseballsavant.mlb.com, fangraphs.com and pypi.org, with
   api.the-odds-api.com at 401 unkeyed and 200 with the repo key. The container
   still reaches GitHub too.
   So MEASURE the egress rather than reading it off this file, in EITHER
   direction: a session that assumes network is as wrong as one that assumes
   none, and both errors are silent. This is the same shape as the
   `master`-versus-`main` paragraph below -- a value nothing on this disk can
   re-read, written down as permanent -- and R147 is what makes the measurement
   free, because the audit already NAMES which of the three stopped a fetch.
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
   `PASS  v2.26.0  40 modules  2129 tests`. The module count comes off the
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
   test_upload_integrity, test_golden_replay, test_paste_lineups, and — since
   R338 closed R180(e) on 2026-09-11 — test_greenfield_regressions and
   test_production, which are PYTEST suites. `python -m unittest` collects
   nothing from those two and reports `Ran 0 tests ... OK`, an empty pass, so
   `PYTEST_SUITES` names them and the gate runs each whole in one pytest
   subprocess rather than chunking it by class; both together take ~7s. pytest
   is in `requirements-production.lock`. If it is missing for the interpreter
   running the audit the suite reports a runner error and FAILS; it never reads
   as clean.
   **A third abnormality the line can append, new 2026-09-15 (R348): the pytest
   temp root.** Those two suites are the gate's only users of `tmp_path`, which
   pytest roots at `<system temp>/pytest-of-<user>` -- outside this repo, not
   this project's to create, and leavable behind by anything on the host. On
   Ben's machine one was, unreadable by `benja`, and `mktemp` raised
   `PermissionError` at session-scoped fixture setup: all 131 tests in both
   suites ERRORED and the gate printed `FAIL  test suite FAILED in
   tests.test_greenfield_regressions, tests.test_production (ran 2066); do not
   build`. The tree was green -- re-run against a clean root the same two
   suites were 131 passed. The audit now PROBES that root and, only when it is
   unusable, redirects the suites to a throwaway one and appends a warning
   naming the bad path. Read that warning as a fact about the HOST, never about
   the tree: every test ran and every test passed, and the directory still
   wants removing (it may need elevation). An operator's own
   `PYTEST_DEBUG_TEMPROOT` is never overwritten and never reported. Keep the
   redirect SHORT if you ever pin one: the first cut of this fix rooted it 120
   characters deep and turned the PermissionError into a MAX_PATH
   FileNotFoundError, which reads like a real failure.
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
   The two pytest suites R338 added are one call each at ~1s and ~6s, so they
   ride inside that budget rather than extending it.
   **R271(c)'s REASON for not asking Ben to run it is gone as of 2026-09-11;
   the instruction is not.** This read "his Windows Python has no scipy and
   `.pylibs/` is a Linux build, so `--run-tests` cannot pass on his host". The
   thirteenth edition installed a pinned project `.venv` on that machine
   (CPython 3.13.7, numpy 2.2.6, pandas 2.3.3, scipy 1.15.3, pydantic 2.12.5,
   from `requirements-production.lock`) and the baseline suite ran there: 1,935
   passed in 512s. `tools/env_probe.ensure_vendored_on_path` returns None when
   `sys.prefix` is that `.venv`, so `.pylibs` cannot shadow it. The gate is
   still the session's job, by POLICY rather than by impossibility: a gate the
   operator runs is a gate the session that changed the code did not.
   The one licensed exception is a session that cannot reach the mount at all,
   which since 2026-09-09 is the ordinary state (see the sandbox note). A
   container reproduction is PARTIAL by construction and may never be quoted as
   the mount's gate, so there the real gate is the one thing only Ben's machine
   can produce, and asking for exactly that one thing is correct.
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
   **The default is now 130, the inner budget a build on this mount actually
   gets, so `--budget` no longer has to be passed and is an override rather
   than a correction (R290(c) rider, 2026-09-03).** It was 43 until then, the
   ninth and last live member of the retired 45-second ceiling; R271 swept the
   class out of five files and deliberately left this one because changing it
   changes the probe's VERDICT rather than a doc string. R290(c) is the item
   about refusals an operator reads under a clock and that is exactly what a
   stale `EXCEEDS` was: against 43 the probe exited 3 for banks that fit the
   real window with 87 seconds to spare, and sent a session slicing a bank
   that never needed slicing. A verdict measured against a ceiling that no
   longer exists is not conservative, it is wrong. The report and the printed
   line both name `budget_source` now, so the next `EXCEEDS` can be told from
   a stale constant without reading this file.
   **An absent `lineups_feed.json` is no longer "missing inputs".** It used to
   exit 4 there, which since R143 is the NORMAL state of a fully DK-covered
   slate (DK publishes the batting order in the salary file, so nothing writes a
   feed) -- the mandated step refused on the ordinary case, which is why this
   step was skipped in practice. It now times the platoon-projected pool and
   says so; only a missing SALARY file is exit 4.
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
  **The feed it cross-checks against is chosen by IDENTITY, not by mtime
  (R305), and on a DK-covered slate it needs no feed at all.** Both referees
  resolve through one function: DK's own `Starting` column first (the ranking
  build contract item 1 already sets, so a fully posted slate that wrote no feed
  is cross-checked against the salary file itself and the report says no
  external feed was needed), then a feed staged beside the salary file, then the
  staged feeds for that date -- and a candidate is usable only if it holds every
  GAME these entries roster. Two consequences to read rather than rediscover
  under a clock. `feed_autoresolve` can now say `REFUSED`, which means a wrong
  feed was declined and the posted-lineup check did not run: that is a stated
  absence, not a failure, and `--feed <path>` overrides it. And a WARN about
  absent players is no longer routinely false -- the three sightings that made
  it so (61, 73 and 28 false warnings across 2026-09-03 and 09-04) were all this
  resolver handing a referee another slate's feed.
  **It hard-fails a player whose game has already started (R287), and `--as-of`
  pins the clock for a replay.** It did not until 2026-09-01, and the miss is
  the worst kind because the tool reported PASS: a 37-entry file holding 151
  roster slots from three games that started at 19:40 ET was run through
  preflight at ~19:56, which PRINTED `first lock: 2026-09-01 19:40 ET` and then
  `PASS ... all hard checks clean`, exit 0. A second file that night carried 78
  such slots and also cleared. DK would have rejected both. The start times come
  from the salary file's `Game Info`, so the check needs no lineups feed —
  `verify_export.py` had the rule and needed both a feed and a `--parent`, which
  meant a freshly built post-lock file was checked by nobody.
  **R324 (2026-09-08) makes that rule a TRANSITION, and it is the same rule in
  both referees now.** The blanket form was right about a file built after first
  pitch and wrong about a late swap, which legitimately RETAINS started players
  in its frozen slots: preflight ran the blanket form UNCONDITIONALLY, including
  with `--parent`, so on a staggered slate every legal post-first-pitch swap
  exited 2 here and 0 in `verify_export`, and the tool this file calls THE
  pre-upload rule left the operator `--force` or an `--as-of` pinned to a lie.
  What holds now, in one function
  (`preflight_upload.check_parent_transition`), called by both tools and
  implemented by neither:
  an UNCHANGED slot passes whatever its lock state and is named as carried
  forward; a CHANGED slot needs both its old and its new player known-not-locked;
  a `Game Info` of `TBD` or anything unparseable is UNKNOWN and UNKNOWN REFUSES a
  changed slot (it used to warn, so an edit into a game nobody could time was
  never refused); a game a lineups source affirmatively reports postponed,
  cancelled or suspended is EXEMPT (R314) and the exemption is named, never
  silently applied; the entry-id set and each entry's contest may not change; and
  an initial build is the all-empty parent, which is where R287's blanket rule
  now lives, salary file only, no lineups source and no parent needed. An
  unreadable clock on an initial build stays a named warning rather than a
  refusal — there is no change to refuse, and refusing the ordinary first
  delivery at T-5 is the harm R324 exists to remove.
  **The exemption needs a source, in BOTH tools, or R314's own complaint
  survives its fix.** `verify_export` takes it from `resolve_locked_teams`,
  which computed it and threw it away; preflight has no auto-resolved feed at
  this point in its run (the resolution is later, and R287 put the check early on
  purpose), so an explicit `--feed` is its door and the absence of one is NAMED
  in `postponed_source`. Exempting one referee and not the other would have left
  the R272 two-referee clause exactly as unsatisfiable on a postponed-game slate
  as it was before.
- Never trim the player pool to fit a compute limit. An infrastructure limit
  may reduce search effort; it may never reduce the legal player set, because
  that is a strategy change and it is invisible in the certified output. A
  timeout is recorded in `solver_report`, never climbs the overlap ladder, and
  never enters `attempted` in the bank cache. A time-limited incumbent is
  verified against the constraint matrix and then
  accepted, tagged `optimality='time_limited'`. The allocator says "time limit
  at gap X" or "proven infeasible: <constraint>", never both.
- The Excluded column has one reading, in `optimizer_v3.excluded_flags` and its
  scalar half `optimizer_v3.read_excluded_cell`. Only an affirmative token
  removes a player; blank, NaN, "False" and unrecognized cells keep them. Never
  compare the column to False directly, and never re-derive the token rule.
  A player leaving the pool on a blank cell is the forbidden pool reduction
  arriving as a data condition.
  **A salary-file `Excluded` column now reaches the frame, and the pool report
  carries the count (R289).** It did not until 2026-09-01: both intake sites
  stamped `"Excluded": False` before the frame existed, so an operator who staged
  a salary file with `Excluded=TRUE` on all 288 players from locked games got a
  CERTIFIED build delivering 151 of them, with nothing on the record saying the
  instruction had been dropped. Read the direction: the guardrail above forbids
  trimming the pool because a trim is invisible in the output, and this was the
  mirror image — an explicit, visible, instructed restriction silently ignored
  while the build certified. Same shape, pool membership not represented in the
  artifact. `pool_report.excluded_column` names the count, the teams and the
  ids, and a warning states the legal pool the build actually has.
  `optimizer_shell_preflight`'s hardcode is KEPT on purpose: it is a neutral
  feasibility test of the salary file's shape and honouring an operator
  exclusion there would make a narrowed pool read as a broken file.
  **Two sentences this paragraph carried until 2026-09-02 were FALSE, and R291
  is why they are gone: the column reached the POOL REPORT and stopped there,
  and the digest re-key was true only of a hand-built frame.** R289 named two
  stamp sites and the class had five. `_assemble_projection_frame` built a new
  dict per row with a fixed key set that omitted the column, so every Classic
  build got an all-False frame; `build_projections` then stamped the default
  over it; `refresh_confirmed_lineups` ASSIGNED the starter test on the swap
  path, revoking an operator flag; the Showdown melt did not read the token at
  all; and `extend_bank` enumerated excluded arms and teams into the job grid.
  Measured on the R289 fixture at `b4ad0f7`: pool report 20, frame 0,
  checkpoint 0, and the SAME projection digest for the plain and the restricted
  salary file, so a restricted build was served an unrestricted bank's bucket.
  All five now carry it, the pool report and the checkpoint print the same
  number, and each claim above has a test that runs the production function --
  the R289 acceptance test did not, which is how it shipped green (R300(a)).
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
A ladder with ACTIONS, not a list of postures. Rewritten 2026-09-01 after a
23-minute window produced no file at all, because every rung said what to be
and none said what to do.

- **T-20.** Skip every optional step.
- **T-15. Open every binding control AT ONCE, not stepwise.** The 1940_9g
  session moved `max_sp_pair_repetition` 1 -> 2 -> 10, then three exposure caps,
  then `max_shared_players`, one per ~2-minute call, five calls. Under a
  deadline the minimal move is the expensive one: five careful steps cost more
  than one crude step, and the crude step is reversible while the lock is not.
- **T-10. The best legal file is the deliverable and certification is a bonus.**
  Approve on posture defaults and auto-floors. Stop optimizing.
- **T-6. Hand-build if the engine has not produced one**, and run the preflight
  on it. `tools/repair_entry.py` and a throwaway greedy script are both
  legitimate here. Label it review-grade, state the sha256, never say certified.
- **T-5.** Present the best file immediately with zero diagnostic narration.

Two readings that are not optional. **Read the clock from the clock**: print
`TZ=America/New_York date` in the same bash call as every build, and never infer
elapsed time from turn count — on 1940_9g a session believed it was 19:38 with
lock two minutes away, it was 19:28, and it spent one of its twelve remaining
minutes writing a post-mortem. **R318 widens that to the two doors the
build-call wording does not reach, both measured on 2026-09-04.** Every clock
figure you STATE -- a handoff, a status line, a verdict -- comes from a `date`
printed in that same turn: 2210_1g_sd opened its handoff with "T-6 min" at T-18
and stopped working with 18 minutes live. And any phase that runs NO build call
still burns the slate clock -- web research, a data hunt, reading an artifact, a
QA pass, a discussion with Ben -- so print the date when you enter one and again
before you decide what to do with what you found: 2140_3g spent ~24 unmeasured
minutes on an enrichment sweep, read T-9 where it had been working as though
T-30, and did not attempt a rebuild it could have afforded at T-30. Two of the
three recorded instances OVERSTATED elapsed time and one UNDERSTATED it, so
there is no safe direction to lean; an overstated clock ends a session that
still had time and an understated one spends time it does not have.
**Read `feasibility.checks` where `passed=False`
BEFORE `errors[]`**; `build_slate.py` prints both on every refusal now, so this
costs nothing.

## Sandbox
**The inner bash timeout is 130s. One number, this one.** Cowork's real ceiling
is ~180s when the call passes an explicit timeout, and the safe inner budget
underneath it is 130 (which is also `--gate-budget`'s value in the session-start
gate command above). A session that reached for `timeout 168` against a ~164s
harness ceiling on 2026-09-01 lost the call and its work with it; the number came
from a different measurement. Do not re-derive it per call.

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
