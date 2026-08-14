---
name: generate-lineups
description: Build a DraftKings MLB DFS lineup portfolio from an uploaded DKSalaries CSV and DKEntries CSV. Classic builds are certified; Showdown builds are review-grade and are never upload-ready. Use this whenever Ben uploads DK files and asks to generate, build, make, or optimize lineups, wants a portfolio or entries for a slate, says "generate lineups", "build my lineups", "run the slate", "optimize for tonight", or asks to late-swap or refine lineups he already uploaded. Trigger even when he does not name the contest type or the engine, and even if he only says something like "here are my files, go" with a salary and entries CSV attached, since the files themselves determine everything else. This is the MLB DFS build path; it is not the mlb-lineups skill, which only fetches probable pitchers and batting orders.
---

# Generate lineups

Turn an uploaded DKSalaries CSV plus DKEntries CSV into a file plus a short brief.
A Classic build can reach certified and upload-ready. A Showdown build is
**review-grade** and never upload-ready: it does not pass through the three
certification gates. Do not let the two collapse into one sentence anywhere.

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

## Multi-session check, before anything else

CLAUDE.md carries the multi-session contract; a build session is BUILD,
and builds never block builds. As soon as you have printed the slate
identity and before staging, light the slate beacon:
`python tools/claim.py take slate_<date>_<tag> --role BUILD --beacon`. A
beacon another session already lit means a parallel build is running:
note it to Ben and continue, never stop and never wait. The beacon exists
so DEV knows builds are live and a same-slate double delivery is a
visible fact; the upload manifest's supersession and the sha256 in your
report name the delivery, and Ben's check at upload is the arbiter. At
delivery, release it: `python tools/claim.py release slate_<date>_<tag>`.
Never edit the ledger or the backlog from a build session; drop a
fragment in ledger/inbox/ or docs/backlog_inbox/ instead.

## Preflight: one call, always, even inside T-20

A fresh sandbox has no scipy, and `scipy.optimize.milp` is the only solver the
optimizer will use. Without it there is no build at all, so this is not a slow
start you can skip under deadline pressure. It is measured at about 9 seconds,
which fits one call with room to spare, and skipping it costs a whole build.

Resolve the repo first. The mount directory name changes between sessions, so
never hardcode the path you saw last time:

```bash
REPO=$(ls -d /sessions/*/mnt/mlb-dfs | head -1)
cd "$REPO" && python tools/env_probe.py --install
```

Probe-then-install (R7): a warm sandbox prints `env warm ... pip skipped` and
exits 0 in about a second, never touching pip. A cold one installs the exact
pins in `requirements.lock` (hashes verified), so every session runs the same
resolver state instead of whatever PyPI serves that day. Exit 0 is the green
light; on any other exit, stop and say so rather than starting a build that
cannot finish. `tools/wheel_fetch.py` is the fallback for when a single call
genuinely cannot finish the download; reach for it only after the locked
install has failed. Never hand-`pip install` around a failed probe: an
unpinned resolve is the drift the lock exists to end.

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
again, it resumes), `3` built but did not certify, `4` a precondition was never
met (inputs missing, solver missing, or the slate's first lock already passed).

An exit of `10` is normal on a big slate, not a failure. The bank persists between
runs. Just run it again.

Three refusals happen before anything is staged, so they cost one line and leave
no byproducts (R28):

- **`missing_dependencies`** — the same import check `tools/audit.py` runs, at the
  front door. Fix with `python tools/env_probe.py --install`, never hand-pip.
- **`past_slate_locks_passed`** — this slate's first lock is in the past, so no
  lineup built from it can be entered. Replays and evals pass
  `--past-slate-replay`; a live build never needs it.
- **`missing_inputs`** — the salary or entries path does not exist.

A build that runs and then does not certify (exit `3`) now always writes its
brief, including to an explicit `--brief` path, carrying `status: not_certified`
with `failed_gates` and `pool_blockers`. A refusal is no longer stdout-only.

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
  `--odds <path>`. Odds now DO change the build: they are the input to F1, the
  game-environment factor. When `--odds` is omitted the script fetches totals
  and moneylines itself if `THE_ODDS_API_KEY` is set, and leaves F1 at 1.0 for
  everyone if it is not.

### Projection enrichment (this is what makes the build more than APPG)

The build applies six deterministic priors: the xwOBA Base correction, xISO
hitter ceilings, K-rate pitcher ceilings, the F4 opposing-SP-quality and platoon
matchup factor, F1 from Vegas implied team totals, and F5 park and weather. Most
read files in `data/reference/`. Refresh those when the brief says they are stale:

```bash
python tools/refresh_reference_data.py     # pulls Savant, reports all three
```

Savant is fetched over HTTP. FanGraphs stays manual by decision; the tool prints
the export URL and reports the file's age rather than fetching it.

Read `enrichment.signal_applied` in the brief before you present anything. False
means this build ranked players on `AvgPointsPerGame x batting-order factor` and
nothing else, which is a materially weaker portfolio, and Ben should be told
plainly rather than handed a certified file that looks identical to a good one.
`enrichment.counts` says which factors moved players and by how many. Every
factor is wired now; a 0 means that factor found nothing to apply on this slate,
which is a fact about the slate rather than a gap in the build.

On F1 specifically: the books post a game total but not per-team totals, so the
split is DERIVED from the total and the moneyline. Say "implied team total"
rather than implying DraftKings published it. Hitter F1 is the team's implied
total over the slate's mean, clipped to 0.85-1.15; pitcher F1 stays 1.0 in v1 so
the opposing-team total is not counted twice. `enrichment.f1_implied_total_by_team`
carries the numbers if Ben asks which games the build liked.

On F5: park factors apply from `data/reference/` with no forecast at all, which
is most of the signal, since Coors is Coors in any weather. Wind needs a
`--bundle` (from `tools/fetch_slate_bundle.py`) and applies only when the roof is
open, the direction is out or in, and the speed clears the venue threshold.

**The retractable-roof rule is manual and stays manual.** A roof's open/closed
state appears in no forecast, and a closed roof cancels the wind adjustment
entirely, so guessing wrong moves every hitter in that game the wrong way. Those
venues take the park factor only and are listed in
`enrichment.f5_retractable_unresolved` plus a stderr line. Surface them to Ben
when the game matters to the slate; never resolve one yourself.

Fresher lineups matter most. A team that has posted since the last pull moves from
a projected batting order to a confirmed one, which is strictly better information.
The script now ages a disk-cached feed itself: anything older than
`--feed-max-age-minutes` (default 90) is refetched, and the brief records which
feed was used and how old it was.

## When Ben pastes lineups, that paste is the source (R32)

If the prompt contains a copy/paste from https://www.mlb.com/starting-lineups,
**do not fetch lineups.** The paste is ground truth for every team in it. Write it
to a file and convert it:

```bash
python <repo>/tools/lineups_from_paste.py \
  --salary data/slates/<date>/DKSalaries.csv \
  --paste data/slates/<date>/pasted_lineups.txt \
  --out data/slates/<date>/lineups_feed.json
```

The output is an ordinary feed, so `build_slate.py --lineups` and
`late_swap.py --lineups` take it unchanged. Every side carries
`source: operator_paste`.

Five things to know before you run it.

**It exits 2 and writes nothing when a name will not resolve.** mlb.com
abbreviates first names (`J Peña`), so matching is on first initial plus surname
plus team, and two same-initial teammates are ambiguous. On the first real paste
this hit SEA's `W Wilson`, which matched both `Will Wilson` (IL) and
`Weston Wilson`. The blocker prints each candidate's DK Status, which is usually
the deciding fact. State the answer and re-run:

```bash
  --resolve "W Wilson=Weston Wilson"
```

Do not work around a blocker by editing the paste. A half-resolved lineup reaches
the build looking like a posted partial, which is the pool reduction the contract
forbids.

**`NOT IN DK POOL` on its own is not a blocker (R32 round 2).** A name that
resolves but has no salary row means DK never listed him, and DK owns
eligibility, so he is unrosterable regardless. The side ships one hitter short,
labelled `partial`, and the slot is named in `unrostered_starters`. In bulk it
DOES block, because it stops being N facts: past half of one posted side, or a
quarter of the whole paste with at least six, the paste and the salary file are
not the same slate. If that fires, check the pairing before anything else.

**Paste every game, including the ones nobody has posted.** An unposted side
renders `1. TBD` and an unannounced probable renders a bare `TBD`. Both are
positional facts the parser needs: they hold the empty slot so the counts line up
and each lineup goes to the side that posted it. Trimming them out is what makes
a half-posted game ambiguous, and the tool will then refuse the game rather than
guess. Paste the page as it comes.

**A side the paste leaves unnamed gets its probable from DK.** The salary file's
`Starting` column (SP/P) is a first-class source, printed as `DK STARTING`. On
2026-07-30 DK declared Robbie Ray for SF while mlb.com and the StatsAPI both
still showed TBD, so the CSV was ahead of both feeds. The paste wins where both
name someone and the disagreement is reported. A DK-derived probable carries no
handedness, so the opposing platoon view falls back to its default.

**Fall back only for what the paste does not cover.** If some games are still TBD,
fetch a feed for those and pass it as `--merge-feed <api_feed.json>`. A pasted
side is never overwritten; the merge report says which games and sides came from
the API, and prints `Zero lineup fetches` when the paste covered everything.

**A fully pasted slate needs no platoon reference and no handedness lookup.**
Handedness is in the paste as `(R)/(L)/(S)`, and with no TBD teams the platoon
reference is never read, so the 7-day staleness warning has nothing to gate.
That is the fast path: one conversion call, then build.

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
the engine.

**The hydrate does not return handedness.** The schedule response gives lineup
players and probable pitchers as id plus name, with neither `batSide` nor
`pitchHand`. Both are inputs to the F4 platoon prior, so a hand-shaped feed that
omits them silently zeroes that component. `fetch_lineups` fills them with one
batched call; a hand-rolled pre-fetch must do the same:

```
https://statsapi.mlb.com/api/v1/people?personIds=<ids>&fields=people,id,batSide,pitchHand,code
```

Write `bat_side` onto each lineup hitter and `hand` onto each probable pitcher.
Check `enrichment.counts.f4_platoon_applied` in the brief afterward; a zero there
on a slate with confirmed lineups means the feed was missing handedness.

Then build:

```bash
timeout 33 python -u <repo>/skills/generate-lineups/scripts/build_slate.py \
  --salary <DKSalaries.csv> --entries <DKEntries.csv> \
  --lineups <the feed you just wrote> --no-rotowire --max-seconds 14 \
  > outputs/<date>/_build.log 2>&1
```

On 2026-07-24 that took a 16-entry Classic build to 10.8 seconds elapsed and it
certified on the first attempt, after three runs with in-build fetching had been
killed at the wall.

**The mount stalls intermittently, and it recovers.** Late on 2026-07-24 a single
engine module import stopped fitting in 40 seconds and `git status` hung
indefinitely; roughly half an hour later, with nothing changed, the same import
took 0.2 seconds, `git status` returned in 2.4 seconds, and the suite ran in
0.028 seconds. This is a transient I/O stall on the host-backed mount, most
likely antivirus or file-sync contention on the repo path, not progressive decay.

So do not conclude the environment is broken from one observation. Pause, retry
once, and only then decide. On 2026-07-24 I declared the test suite unrunnable and
handed it to Ben when it would have run fine twenty minutes later. Keep per-call
work bounded so a stall costs one call instead of a build, and if a stall persists
across retries during a live slate, deliver from what is already certified rather
than waiting it out.

**Diagnostics, which matter more than they sound.** Always run `python -u` and
redirect the log inside the repo. `/tmp` is not shared between calls, and
buffered stdout vanishes when the call is killed; on 2026-07-24 fourteen minutes
went to a build whose real error, a missing scipy, sat unread in a log that no
longer existed. Never check liveness with `pgrep -f build_slate.py`, because the
pattern matches the checking command's own command line and reports RUNNING
forever. The same self-match trap applies to `ps | grep`. And note that a
repo-wide `grep -rn` on this mount can return empty without erroring, which reads
exactly like "no matches"; scope greps to specific files before concluding a
symbol is absent. When you pipe a command into `head`, `$?` is head's exit code,
not the command's; capture to a file and check the real status.

**Capture stdout and stderr to SEPARATE files when a command exits non-zero.**
This is not a style preference, it cost most of an hour on 2026-07-29. Several
`late_swap.py` calls returned exit 3 with a `2>&1` log that ended abruptly right
after `joint solve next: ...` and no error text at all, despite `python -u`. The
real failure (`no compatible candidate for Entry ID ...`, and later the
informative `SP pair ... count 2>1`) only appeared once the two streams went to
separate files. The process really had exited 3 and really had printed the reason;
the merged stream did not show it inside the window it was captured in. A silent
exit therefore looks identical to "still building the bank", and the session
re-ran the same command with the same budget several times expecting different
output. So:

```bash
timeout 33 python -u <cmd> > outputs/<date>/_x.out 2> outputs/<date>/_x.err
echo "exit=$?"; tail -30 outputs/<date>/_x.err
```

Read the `.err` file first on any non-zero exit. This is a sandbox quirk, not
repo behavior, so no engine change fixes it.

**Odds fetches need the key resolved, and the default output shape now works.**
`build_slate.py`'s own auto-fetch resolves `THE_ODDS_API_KEY` from the environment
or `REPO/.env`, so a build needs no export. The standalone `mlb-game-odds` skill
still reads only two `/mnt/...` paths and the env var, none of which is this
repo's `.env`, so when you call that skill directly, put the key in the
environment without putting it on a command line (a `grep | cut` pipeline leaves
it in shell history and in `ps`, and the guardrail says never echo a key):

```bash
python -c "import sys; sys.path.insert(0,'<repo>'); from mlb_engine.repo_env import load_repo_dotenv as l; print(','.join(l()))"
# then, in the SAME call, run the fetch under env -S or via os.environ in one script
```

Simpler in practice: prefer the build's own auto-fetch, or pass `--odds` a file
you already have. Passing the skill's output to `--odds` works with or without
`--raw`: the default
`games`-keyed schema is recognised as of 2026-07-29. If an odds file is not
understood, the build now says which keys it found instead of reporting the game
as having no moneyline.

**Dependencies do not persist across sessions.** The preflight at the top of this
file is the whole answer, and it is never the step you skip to save time. A
sandbox that looks identical to yesterday's still has no scipy today.

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

DK often runs more than one Classic draftgroup on a date (a main slate and a night
slate). `build_slate.py` now compares game sets and moves a prior draftgroup's
staged inputs, brief, and delivered file aside rather than overwriting them, and
the brief carries a `slate` block with a tag like `2005_4g`. Read that tag back to
Ben so he can confirm which draftgroup he is entering.

## Reporting back

Lead with the file and whether it is certified. Then a short brief, roughly:

- **Gates**: all three pass, or exactly which failed
- **Identity**: the delivered file's exact path and its sha256, so Ben can
  confirm at upload that the file he selects is the file that certified
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

Pool warnings are now scoped to the draftgroup, so a team named in them is a team
on this slate. A team matching fewer than 5 of 9 salary hitters is a blocker, not
a warning, because that is a name-crosswalk failure and building anyway
substitutes a projected order while the real lineup sits unused.

Keep it to a handful of lines. Ben can open the JSON if he wants the rest. Do not
narrate the steps you took; he watched them happen.

Then present the delivered file so he can open it, and remind him the upload is
manual.

## Always run the preflight before presenting a file

Between "build finished" and "Ben uploads," run this on every deliverable,
Classic and Showdown alike. No exceptions and no exemption at T-5: it imports no
engine, touches no network, and finishes in under two seconds.

```bash
python <repo>/tools/preflight_upload.py --entries <delivered file>
```

Three inputs resolve themselves, because a check that runs only when you remember
a flag is a check that does not run at T-5:

- `--salary`: the promoted run's `inputs/DKSalaries.csv` snapshot, which cannot be
  clobbered by a later same-date build the way the staged copy can.
- `--manifest`: `outputs/<date>/upload_manifest.json`, found next to the entries
  file, cross-checked on sha256, entry count, and contest IDs. For a **delivered**
  file, one resolving under `outputs/`, a missing manifest row or a sha256
  mismatch is a hard failure; `--no-manifest` is the explicit waiver for a file
  that was never meant to have a record. A hand-built file elsewhere still only
  warns.
- `--feed`: the freshest `lineups_feed.json` for the slate date, which the tool
  reads off the entries file's own Game Info cells. A rostered player absent from
  his team's CONFIRMED lineup is a hard failure; `--feed-lenient` demotes it to a
  warning. A team that has not posted stays soft. The feed's age prints next to
  the verdict and warns past 90 minutes, so a stale all-clear is visibly stale.

One optional flag closes the identity loop the report's sha256 line opens:
`--expect-sha256 <hex>` (12+ chars of the brief's `delivered_sha256`)
hard-fails unless the file on disk hashes to it, so the file Ben selects at
upload is provably the file that certified. Use it when re-checking a file
you did not just build, and always after a late swap.

### The four exit codes

| exit | verdict | what you say |
|---|---|---|
| 0 | `upload_ready` | the one-line verdict and nothing more |
| 2 | `blocked` | lead with the failure, quote it verbatim, do not present the file as ready |
| 3 | usage or IO error | the check did not run; say that, and do not report a clean file |
| 4 | `acknowledged` | see below |

**Exit 4 is not exit 0.** `--force` prints the failures, leaves the file
unblocked, and exits 4, so the tool can never be the reason a slate is not
entered while still telling the caller the truth. Use it only when Ben has seen
the failure and said to ship anyway. On exit 4 your reply must name every
overridden failure, quoted, and say the file was forced past a failing check.
Never report an exit-4 file as clean, upload-ready, or certified: the manifest
records it as `acknowledged` with the failure list, and your reply has to match
the record.

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

**Showdown** is real but it is `v0.3-review`, and Phase 3 is not complete in the
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

### The thesis ladder is the default Showdown construction

A Showdown slate is one game, so a points-max solve has exactly one answer and a
portfolio built from it is that answer with punt bats rotated.
`mlb_engine/optimize/showdown_theses.py` instead conditions each entry on a game
state: `LAD win big`, `NYM win close`, `pitchers duel`, `both offenses explode`,
`ace dominates and takes the loss`, and so on. Every template is a roster SHAPE,
not a captain preference; two templates that produce the same shape are one
template.

`run_showdown` routes through it automatically whenever `pool.basis` is
`declared_starters` and both orders are posted. With nothing posted there is no
batting order to condition on, so it falls back to `build_showdown_bank` and the
brief says so in `construction.mode` and `construction.reason`. Read that field
before describing the build: `thesis_ladder` and `points_max_bank` are different
objects and only one of them is what Ben asked for.

Entries are allocated across game states by the vig-free moneyline when odds are
available. `construction.win_share_basis` says which input was used. On
`even_split_no_market_input` the two sides got equal weight because no moneyline
matched, which is a real weakness on a lopsided game and belongs in your report.

**Two portfolio controls, both enforced in the solver, both reported:**

- `max_shared_players` (default 4 of 6). No two lineups may share more than four
  players. Overlap counts the PLAYER, not the role, because promoting a UTIL to
  CPT is not a differentiated lineup. Exact-set forbidding, the old default,
  called a one-player swap unique.
- `max_cpt_exposure_pct` (default 0.33). The count is a `floor()`, which is why
  the default is 0.33 and not 0.35: at 20 entries 0.35 permits seven captains,
  a realized 35%.

Both relax rather than truncate, and in a fixed order: the overlap bound gives
way first, then the captain lock, then the thesis. A short bank leaves a blank
reserved row and a blank row blocks certification, so silently shrinking is the
one outcome not on offer. Every relaxation is counted in `diversity` and
`captain_exposure` and repeated in `caution`. Read those before reporting the
portfolio as clean. Override either through `--controls-override`.

Both defaults live in `mlb_engine/optimize/showdown.py`. The Showdown suite is
`tests/test_showdown.py`, and `tools/audit.py` DOES gate it, along with
`test_core`, `test_upload_integrity`, `test_golden_replay` and
`test_paste_lineups`. (This paragraph claimed the opposite until 2026-07-30; the
audit has gated four suites since 07-28 and five since 07-30.)

## Late swap

When Ben has already uploaded and wants to refine, this is a swap, never a
rebuild. A rebuild would move players in games that have already locked, and DK
will reject it.

```bash
python <repo>/tools/late_swap.py --date <date> \
  --parent-entries runs/<run_id>/final/DKEntries.csv \
  --salary runs/<run_id>/inputs/DKSalaries.csv \
  --budget 30
```

Add `--entry-ids` to authorize specific entries only. Add `--dry-run` to see what
is pinned and how many candidates exist before committing.

**Pass `--salary` at the run's own snapshot whenever another session might be
building this date.** Without it the swap reads
`data/slates/<date>/DKSalaries.csv`, which is keyed on date alone and is therefore
shared: on 2026-07-29 a concurrent Showdown build overwrote it mid-swap and every
entry failed with "embedded player pool overlaps the salary file at 0.0%". The
run's `inputs/` snapshot cannot be clobbered, and `--salary` is read-only. The
tool prints which path it resolved and flags the shared one. Same reasoning for
`--lineups`.

Two rules the engine enforces and you should understand, because they explain
most "no compatible candidate" errors: a locked slot cannot move, and a game that
has locked admits **no new players at all**, even into slots that are still open.
So an entry holding one locked Yankee cannot pick up a different Yankee.

**A failed swap now tells you which of the two problems you have.** A portfolio
control naming itself (`binding control: max_sp_pair_repetition=3`) means the caps
are the problem and `--controls-override` is the lever; "no compatible candidate"
now says explicitly that it is NOT a control, so the bank or the pins are the
problem and `--budget` is the lever. Do not grow the bank against a control
failure: on 2026-07-29 that mistake cost twenty minutes because the two failures
printed the same sentence. The swap also inherits the parent build's posture-based
caps now, so you should not need `--controls-override` at all unless the parent
build itself used one.

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
python tools/audit.py --run-tests --terse    # expect PASS, 26 modules, 928 tests
```

When the skill or its scripts change, run the fixture evals too (not part of
the audit; they are the skill-development harness and each pins an exit code,
artifact states, and forbidden claims):

```bash
python skills/generate-lineups/evals/run_evals.py    # --only <id> for one
```

The audit checks dependencies first and names the install command if something is
missing, because a missing solver is not a slow build, it is no build. It also
pins the test count, so adding tests requires bumping `EXPECTED_TEST_COUNT` and
the three docs that quote the expected line (CLAUDE.md, the ledger Quick Card,
and this file). A count mismatch is the pin working, not a broken suite.

Skip the test suite under deadline pressure. Inside T-20, go straight to the
build. The preflight is the one part that is never skipped: it costs about 9
seconds, and a fresh sandbox with no scipy produces no build at all.

## Verifying a file you did not just build

For a file with no parent, `preflight_upload.py` above is the whole check. When
the file refines an earlier one, use:

```bash
python <repo>/tools/verify_export.py --entries <file.csv> --parent <prior file> \
  [--salary <DKSalaries.csv>]
```

It runs every preflight rule (blanks, partial rows, duplicate Entry IDs, header
geometry, DK Status, embedded-pool overlap, cap, slot eligibility, duplicate
persons, two games, five hitters per team, hitter versus rostered SP, Showdown
both-teams and recomputed captain price) and adds the swap-specific ones:
contest-identity diff against the parent, per-entry slot churn, no player
introduced from a game that has already started, and no replacement of a player
whose game has started. Exit 2 on any failure.

**Run it again for each file in a correction chain, and do not pass
`--locked-teams` at all.** Locked teams are derived on every invocation from the
lineups feed's own clock (falling back to the salary file's Game Info), and the
report prints the clock and the source it used. `--locked-teams` ADDS to that set
and can no longer replace it. This is not a preference: on 2026-07-29 a list
passed once at 7:23 PM ET was still in use at 8:02, three games locked underneath
it, this tool printed PASS, and DraftKings rejected 7 of 16 entries. If you see
`STALE --locked-teams` in the output, drop the flag. Pass `--as-of` only to test
the derivation against a fixed clock.

## Commands for Ben

Ben runs Windows PowerShell 5.1, not bash. `&&` is a parse error there. Give him
one command per line, Windows paths with backslashes, and always start with
`cd C:\Users\benja\Documents\Claude\mlb-dfs`, because he will not necessarily be
in the repo.

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
