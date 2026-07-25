---
name: generate-lineups
description: Build a certified DraftKings MLB DFS lineup portfolio from an uploaded DKSalaries CSV and DKEntries CSV, for both Classic and Showdown. Use this whenever Ben uploads DK files and asks to generate, build, make, or optimize lineups, wants a portfolio or entries for a slate, says "generate lineups", "build my lineups", "run the slate", "optimize for tonight", or asks to late-swap or refine lineups he already uploaded. Trigger even when he does not name the contest type or the engine, and even if he only says something like "here are my files, go" with a salary and entries CSV attached, since the files themselves determine everything else. This is the MLB DFS build path; it is not the mlb-lineups skill, which only fetches probable pitchers and batting orders.
---

# Generate lineups

Turn an uploaded DKSalaries CSV plus DKEntries CSV into a certified, upload-ready
file, then hand Ben the file and a short brief.

The engine lives in the `mlb-dfs` repo and does the real work. Your job is to
route to it correctly, notice when something looks wrong, and report honestly.
Read `CLAUDE.md` in that repo before touching anything: it governs strategy,
contracts, and the guardrails below, and it wins over this skill wherever the two
disagree.

## Non-negotiables

These are not style preferences. Each one exists because it was violated once and
cost something.

**Never automate DraftKings.** No uploads, no entry submission or edits, no
deposits, no withdrawals, no scripted reads of draftkings.com. Salaries, entries,
standings, and contest pages are manual downloads by Ben. Lineups and money move
only when Ben clicks. You produce a file; that is where your involvement ends.

**Truthful labels.** Every number here is a deterministic review proxy or a
labeled prior. Never call anything ROI, profitability, win rate, cash rate, edge,
or a probability. "Upload-ready" is reserved for a Classic build where
`workflow_valid`, `selection_certified`, and `allocation_certified` all pass.

**An infrastructure limit may reduce search effort. It may never reduce the legal
player set.** If a build will not fit the time available, shrink the candidate
bank and say so. Never drop players, pitchers, teams, or games to make a solve
finish. Trimming the pool is a strategy change that does not appear anywhere in
the certified output, so nobody reviewing the file can see it happened.

**The DKSalaries CSV is authoritative** for player IDs, salaries, teams, and
eligibility. Never correct it against real-world rosters. If the salary file and a
data feed disagree, the salary file wins.

## The fast path

Almost every request is this one command:

```bash
python <repo>/skills/generate-lineups/scripts/build_slate.py \
  --salary <uploaded DKSalaries.csv> \
  --entries <uploaded DKEntries.csv> \
  --max-seconds 30
```

It detects Classic vs Showdown from the files, stages them into
`data/slates/<date>/`, builds the pool, measures the solver, picks a strategy that
fits the budget, builds, certifies, verifies the written CSV, and writes a brief
to `outputs/<date>/build_brief.json`.

Exit codes: `0` certified, `10` partial progress saved (run the exact same command
again, it resumes), `3` built but did not certify, `4` inputs missing.

An exit of `10` is normal on a big slate, not a failure. The bank persists between
runs. Just run it again.

Inside Cowork's bash sandbox this command usually will not fit in one call. Read
"Running inside the Cowork sandbox" below before you start, and confirm the salary
file is the slate Ben meant.

### Better data when there is time

The script fetches probable pitchers and batting orders itself if it has to, but
the dedicated skills are better and handle more edge cases. When you have a minute
before lock, run them first and pass the results in:

- **mlb-lineups** for confirmed lineups, batting order, and pitcher handedness.
  Save the JSON and pass `--lineups <path>`.
- **mlb-game-odds** for moneylines, run lines, and totals. Save it and pass
  `--odds <path>`. Odds do not change the build; they give you the game
  environment to describe in the brief, which is what makes the brief worth
  reading.

Fresher lineups matter most. A team that has posted since the last pull moves from
a projected batting order to a confirmed one, which is strictly better information.

## Running inside the Cowork sandbox

Cowork's bash gives you one 45-second window per call, and that window includes
container startup, so a `timeout 40` wrapper gets killed before its trailing
`echo` ever runs. Budget the inner timeout at 25 to 33 seconds. Importing
`mlb_engine.optimize.optimizer_v3` off the mounted filesystem costs about 15
seconds by itself. That leaves roughly 15 to 20 seconds of real work per call,
and you cannot escape it by backgrounding, because processes do not survive
between calls.

**Put exactly one expensive thing in each call.** The default path does two
network fetches inside the build: the MLB Stats API lineups pull, which alone has
a 25-second timeout, and the RotoWire merge. Either can consume the whole
remaining budget. Do the fetch in its own call instead, with a short standalone
`urllib` script that hits

```
https://statsapi.mlb.com/api/v1/schedule?sportId=1&date=<date>&hydrate=lineups,probablePitcher,team
```

shapes the response into the same structure `fetch_lineups` produces, and writes
it into the slate directory. That call is cheap because it imports nothing from
the engine. Then build:

```bash
timeout 33 python -u <repo>/skills/generate-lineups/scripts/build_slate.py \
  --salary <DKSalaries.csv> --entries <DKEntries.csv> \
  --lineups <the feed you just wrote> --no-rotowire --max-seconds 14 \
  > outputs/<date>/_build.log 2>&1
```

On 2026-07-24 that took a 16-entry Classic build to 10.8 seconds elapsed and it
certified on the first attempt, after three runs with in-build fetching had been
killed at the wall.

**Diagnostics, which matter more than they sound.** Always run `python -u` and
redirect the log inside the repo. `/tmp` is not shared between calls, and
buffered stdout vanishes when the call is killed; on 2026-07-24 fourteen minutes
went to a build whose real error, a missing scipy, sat unread in a log that no
longer existed. Never check liveness with `pgrep -f build_slate.py`, because the
pattern matches the checking command's own command line and reports RUNNING
forever. And note that a repo-wide `grep -rn` on this mount can return empty
without erroring, which reads exactly like "no matches"; scope greps to specific
files before concluding a symbol is absent.

**Check dependencies before any build, including inside T-20.** A fresh sandbox
has no scipy, and a `pip install` does not persist across sessions. The probe
costs two seconds, and a missing solver is not a slow build, it is no build.

If the build still will not fit, use the exit-10 resume and run the identical
command again. The bank persists between invocations, so each call adds a slice.
Shrink the bank, never the pool.

## Confirm which slate you were handed

Before staging, print the salary file's game list, game count, and first lock from
the `Game Info` column, and the entries file's contest IDs. Compare them against
the games Ben named. Two traps, both seen on 2026-07-24:

- A re-uploaded file can land under a hashed filename while the generic
  `DKSalaries.csv` still resolves to the earlier upload. Run `ls -la` on the
  uploads directory and read mtimes; be suspicious whenever a generic name and a
  hashed variant coexist.
- If the entries file's contest IDs match a build already delivered this session,
  treat it as a stale upload until proven otherwise, not a new slate.

A stale-but-valid salary file is still a valid salary file, so the build succeeds,
certifies, and reports clean gates for the wrong slate. Nothing downstream can
catch this. State the slate identity out loud before you solve.

Related: DK often runs more than one Classic draftgroup on a date (a main slate
and a Night slate). Staging and delivery are keyed by date today, so the second
build overwrites the first one's staged inputs and its delivered
`outputs/<date>/DKEntries.csv`. Copy any delivered file aside before building a
second draftgroup for the same date.

## Reporting back

Lead with the file and whether it is certified. Then a short brief, roughly:

- **Gates**: all three pass, or exactly which failed
- **Time**: minutes to the T-5 delivery deadline, and whether the slate clock
  agreed with the salary file (`salary_cross_check`). On disagreement the salary
  file wins and the clock is rewritten, which is the correct behavior. Read the
  `note` and `drift_minutes` before explaining it: a doubleheader leg collision is
  one cause, but a partial-day draftgroup is another and is benign, because the
  lineups feed covers the whole day so its earliest lock is an earlier game than
  the draftgroup's. Do not report the doubleheader reading as the diagnosis
  without checking which one you have.
- **Pool**: teams kept, how many are on confirmed lineups versus projected platoon
  orders, and any team the platoon file covers but could not fill
- **Portfolio**: primary stacks and their exposure, the SP pairs used
- **Environment**: if odds were pulled, the totals that shaped the stacks
- **Anything odd**: stale platoon pages, teams with 8 of 9 hitters matched,
  warnings from the pool report

Keep it to a handful of lines. Ben can open the JSON if he wants the rest. Do not
narrate the steps you took; he watched them happen.

Then present the delivered file so he can open it, and remind him the upload is
manual.

## When the deadline has already passed

The brief carries `minutes_to_deadline`. A negative value means the first game of
the slate has already started, so the draftgroup is closed and the file cannot be
uploaded no matter how clean it is.

Say so immediately and plainly, at the top of your reply, before the file. A
certified file that cannot be entered is not a deliverable, and burying that under
a passing gate report is the kind of thing that reads as success and is not.

Then offer the two things that are actually available: a late swap, if Ben already
has entries in and only some games have locked, or building the next slate. Do not
call a past-deadline file upload-ready.

Check this before you start, not after. If the clock is already negative when you
stage the files, tell Ben first and ask what he wants rather than spending the
build.

## Contest types

The files declare which one, so never ask. A Showdown salary file lists Roster
Position `CPT`/`UTIL` and its entries header is `CPT,UTIL,UTIL,UTIL,UTIL,UTIL`;
Classic lists `P/C/1B/...` and `P,P,C,1B,2B,3B,SS,OF,OF,OF`.

**Classic** is the production path with the full three-gate certification.

**Showdown** is real but it is `v0.1-review`, and Phase 3 is not complete in the
implementation guide. The script runs per-lineup certification and verifies the
DK template was preserved, and it labels the result `review_grade_build` rather
than certified. Pass that label through to Ben honestly. Do not describe a
Showdown file as upload-ready in the sense Classic means it. See
`references/showdown.md` if you need the internals.

The Showdown pool is restricted to the players DraftKings declares in the salary
file's `Starting` column: the declared starting pitchers and the posted batting
orders. The brief reports this as `pool.basis`. When it reads `declared_starters`
the build only used players who will take the field. When it reads `all_healthy`,
nothing had posted yet, so the pool is everyone and the lineups are built on
AvgPointsPerGame alone, which does not know who is playing. Say which one you got,
because a Showdown build off an unposted slate is a much weaker object than one
built after lineups drop.

## Late swap

When Ben has already uploaded and wants to refine, this is a swap, never a
rebuild. A rebuild would move players in games that have already locked, and DK
will reject it.

```bash
python <repo>/tools/late_swap.py --date <date> \
  --parent-entries runs/<run_id>/final/DKEntries.csv \
  --budget 30
```

Add `--entry-ids` to authorize specific entries only. Add `--dry-run` to see what
is pinned and how many candidates exist before committing.

Two rules the engine enforces and you should understand, because they explain
most "no compatible candidate" errors: a locked slot cannot move, and a game that
has locked admits **no new players at all**, even into slots that are still open.
So an entry holding one locked Yankee cannot pick up a different Yankee.

Details in `references/late_swap.md`.

## When something goes wrong

**Blockers in the pool report.** Read them. A team with no probable and no
declared starter is a real decision, not a glitch; ask Ben which arm to declare
rather than guessing.

**"no compatible candidate for Entry ID ..."** means the bank has nothing legal
for that entry's pins and exclusions. Run the command again to add another slice.
If it persists, the entry may pin so many hitter slots that a 4-man stack cannot
fit; the bank relaxes that automatically, but say so in the brief.

**Certification fails.** Do not hand over the file. Report which gate failed and
what the errors say. A file that does not certify is not a deliverable.

**Blank reserved entry rows block certification.** Never bypass that.

**Ceiling below Floor is a hard error.** Never silently repair it.

**Do not repair test or audit infrastructure during a live slate.** If the audit
fails on versions or inventory while the suite itself passes, build anyway and
flag it for afterward. Getting the file in hand before lock beats a tidy repo.

## Session hygiene

Before a build, when there is time:

```bash
cd <repo> && git status --short
python tools/audit.py --run-tests --terse    # expect PASS, 13 modules, 144 tests
```

The audit checks dependencies first and names the install command if something is
missing, because a missing solver is not a slow build, it is no build.

Skip the test suite under deadline pressure. Inside T-20, go straight to the
build. The dependency check is the one part that is never skipped: it takes two
seconds, and a fresh sandbox with no scipy produces no build at all, which costs
far more than the check.

## Verifying a file you did not just build

```bash
python <repo>/tools/verify_export.py --salary <DKSalaries.csv> --entries <file.csv> \
  [--parent <prior file>] [--locked-teams PIT,NYY]
```

Checks blanks, duplicates, the salary cap, slot eligibility, and, against a
parent, that locked slots held and no new player came from a locked game. Exit 3
on any failure.

## The engine, briefly

You rarely need this, but when the script is not enough:

- `mlb_engine/intake/live_data_adapters.build_slate_pool` is the required intake
  front door. It restricts the slate to players who can actually take the field
  and loads `data/reference/fangraphs_platoon_lineups.json` by default, so a team
  with no posted lineup keeps a projected batting order instead of being dropped.
- `mlb_engine/pipeline/execution_pipeline.run_slate` is the only production entry
  point for Classic builds. `bank_time_budget_s` bounds the candidate bank.
- `mlb_engine/optimize/optimizer_v3` is the lineup source of truth,
  `scipy.optimize.milp` only.
- `mlb_engine/optimize/bank_cache` persists candidates across calls so a bounded
  environment can build a large bank in slices.
- `tools/solver_probe.py` estimates whether a build fits a budget before you start
  one. Use it when you want the answer without committing to a build.
