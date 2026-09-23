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

**Diagnose from the artifact, never from documentation.** The brief carries an
enrichment self-report: `signal_applied`, `requested_but_unapplied`, `degraded`,
`degraded_reason`, `f1_league_mean_implied_total`, `f1_odds`. That is the record
of what the build actually did. On 2026-08-16 a session read the `--odds` help
string ("when omitted, totals are fetched if THE_ODDS_API_KEY is set, else F1
stays 1.0"), concluded F1 was neutral, told Ben the portfolio had no game
environment in it, and spent his pre-lock window on a rebuild. The brief on disk
read `f1_league_mean_implied_total: 4.125` with 15 of 15 games priced;
`resolve_odds_api_key` in `mlb_engine/repo_env.py` had already resolved the key
from `REPO/.env`. A help string describes what the flag is for. Only the artifact
says what happened. `python tools/qa_portfolio.py` prints this section first for
exactly this reason: read it before forming any theory about a build.

**Read the clock from the clock.** `slate_clock.minutes_to_deadline` in the
brief, or `TZ=America/New_York date`. The same session estimated elapsed time
from how many turns it had taken, concluded it was at T-2, and nearly stood down
a build that had 28 minutes left. Turn count is not a clock.

**Print `TZ=America/New_York date` in the SAME bash call as every build.** The
paragraph above was already here on 2026-09-01 and had been read in-session when
a BUILD session concluded, at what it believed was 19:38, that lock was two
minutes away. It was 19:28. Twelve minutes were left, one of them went to writing
a failure narrative, and the slate delivered nothing. A reading printed by the
same call as the build cannot be stale by more than that call.

**Two more doors, R318, 2026-09-04.** A clock figure you QUOTE to Ben is a
separate act from the clock inside a build call and drifts on its own: quote
only a `date` printed in that same turn. And enrichment, research and QA phases
run no build call and still burn the slate clock, so print
`TZ=America/New_York date` entering one and again before deciding what to do
with what you found. One instance each, both on 2026-09-04: a handoff that read
"T-6" at T-18, and a 24-minute enrichment sweep that measured nothing and
surfaced at T-9 believing T-30.

**On a refusal, read `feasibility.checks` where `passed=False` FIRST, before
`errors[]`.** `build_slate.py` prints them to stderr on every refusal now, ahead
of the hint and the clock, so this needs no discipline — but read them there
rather than scrolling to `errors[0]` out of habit. The reason is a whole lost
slate: on 1940_9g `errors[0]` named `max_sp_pair_repetition` on four consecutive
builds, which is a count over the BANK, while the one failing SLATE check
(`shared_players_floor`, carrying `remedy: raise max_shared_players to >= 7`)
never appeared in `errors[]` at all. The session escalated the cap 1 -> 2 -> 10
and grew the bank twice, spending ten minutes of a twenty-three minute window on
a check that was passing. Since R286 the refusal leads with the failing check, so
`errors[0]` is right to read; since R207 `refusal_remedy` carries each remedy as
data (printed as `REMEDY:` lines), and on an interaction refusal it names the one
control that, dropped alone, restores feasibility, and its smallest step.

**A slate-level check and a bank-level count are different objects.** A failing
`feasibility.checks` entry is arithmetic about the SLATE: no bank growth can
clear it, so fix it first. A `BANK-LEVEL` line in `errors[]` is arithmetic about
the candidates this slice happened to build, and growing the bank is the right
first move against it. The refusal now labels which is which; do not treat them
as the same lever.

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

## Preflight: one call, always, at any clock

A fresh sandbox has no scipy, and `scipy.optimize.milp` is the only solver the
optimizer will use. Without it there is no build at all, so this is not a slow
start you can skip under deadline pressure. It is measured at about 9 seconds,
which fits one call with room to spare, and skipping it costs a whole build.

Resolve the repo first, and never hardcode a path you saw last time. The repo
sits somewhere different on each of the three hosts (`docs/hosts.md`), so ask git
where it is:

```bash
REPO=$(git rev-parse --show-toplevel) && cd "$REPO"
python tools/env_probe.py --install --venv
```

**This line used to read `REPO=$(ls -d /sessions/*/mnt/mlb-dfs | head -1)`, which
is a Cowork mount path.** On any other host that glob matches nothing, `REPO` is
empty, `cd ""` fails, and the preflight silently never runs -- while this file's
own first rule is that a session which cannot read the repo must stop. R355,
2026-09-17. `build_slate.py`'s own `_find_repo` had already been rewritten away
from that literal for the same reason; only this prose was left behind.

Drop `--venv` only on a host that manages its own interpreter (Windows, with its
pinned `.venv`; Cowork, with its vendored `.pylibs/`). On a Linux container the
interpreter is shared with the OS package manager and the install belongs in a
virtualenv (R353).

Probe-then-install (R7): a warm sandbox prints `env warm ... pip skipped` and
exits 0 in about a second, never touching pip. A cold one installs the exact
pins in `requirements.lock` (hashes verified), so every session runs the same
resolver state instead of whatever PyPI serves that day. Exit 0 is the green
light; on any other exit, stop and say so rather than starting a build that
cannot finish. `tools/wheel_fetch.py` is the fallback for when a single call
genuinely cannot finish the download; reach for it only after the locked
install has failed. Never hand-`pip install` around a failed probe: an
unpinned resolve is the drift the lock exists to end.

## The fast path: let the supervisor take its own retries

Ben has delegated build decisions (CLAUDE.md, Autonomy). Start here:

```bash
python <repo>/tools/autobuild.py \
  --salary <DKSalaries.csv> --entries <DKEntries.csv> \
  --lineups <feed.json> --postures '<id>=<posture>,...' \
  --stop-after-minutes 12   # + --declare-pitcher <id>[=<role>] per PLR/PO arm (R345)
```

`--per-build-seconds` is left off on purpose: it defaults to this host's call
budget over six (105s on a 630s container, 21s on Cowork), and this recipe used
to pin it at 20, which held every host to the Cowork ceiling one level down
(R349 had already freed the CALL budget). Pass it only to override that.

**Two clocks, and they are not the same number** (R296(f)).
`--stop-after-minutes` is the SLATE's budget; `--call-budget-seconds` is THIS
PROCESS's, and it is resolved per host by `mlb_engine.repo_env.call_budget_s()`
(R349) rather than being the constant 130 it once was -- see `docs/hosts.md`. The
defaults describe eight attempts of up to 110s under a twelve-minute wall, which
on a short-budget host cannot fit one call, so the supervisor stops CLEANLY before an attempt that
cannot finish, exits 5 with `resumable: true`, and the next call picks it up
with **`--resume`**: attempt numbering, the structural floors already applied,
and the pool override are all restored. Without `--resume` a second call
re-derives every floor from attempt 1, and each floor was paid for with a full
build. The first attempt of a call always runs whatever the budget says.

Every `dec.add` is flushed to disk immediately, so a killed call leaves the
decisions it had already taken rather than nothing.

It runs `build_slate.py` in a loop and takes the decisions a human was taking
by hand: grow the bank on exit 10, apply a feasibility remedy the engine named
and classified structural, override a pool blocker whose shape is classified
benign and assert `lineup_gate_passed` on that same evidence. It stops on
anything it cannot classify, and every decision lands in
`outputs/<date>/autobuild_decisions.json`. Exit 0 certified, 3 refused with
reasons, 4 bad input, 5 out of time.

A stop is a real question, not a formality: an exposure cap has no engine-named
floor, and a team matching under 5 of 9 salary hitters is a crosswalk failure,
not an unpriced callup. Read the decision log before overriding by hand.

## Then poke holes in it

Two iterations at most, and only with time on the clock:

```bash
python <repo>/tools/qa_portfolio.py --entries <delivered.csv> \
  --salary <DKSalaries.csv> --brief outputs/<date>/build_brief<suffix>.json
```

Section 1 is what the build applied, from the artifact. Section 2 checks stacks
against market implied totals and arms and bats against Savant expected stats.
Section 3 is the dual-objective frontier. FanGraphs 403s scripted pulls, so a
FanGraphs refresh needs a browser session (Claude in Chrome), which is
post-slate work, not a pre-lock step.

A finding is a question, not a verdict. Heavy exposure to a low implied total
is a leverage play or an oversight and the tool says it cannot tell which; you
decide, say which, and if you rebuild, do it once. Stop at two iterations even
if the second one still shows findings, because a third is fitting the
portfolio to the last thing you looked at.

### The agentic half, when the clock allows (R344)

The tool above measures what it was built to measure. The standing brief at
`references/adversarial_qa_brief.md` is the pass that looks for what it does
NOT measure: three axes (mispriced assets and whether a Pareto improvement
exists; dual-objective adherence at contest and portfolio level as one
frontier; leverage against the sourced ownership prior), report only, truthful
labels, no DK fetch, gaps stated rather than filled, a hard wall-clock budget
with partial-in-time beating complete-late.

Run it as the `dfs-qa` repo agent (`.claude/agents/dfs-qa.md`, R372), handed
the delivered CSV, the salary file, the brief JSON and the ownership prior as
PATHS. It is never automatic and at T-10 or later skipping it is correct.

Its first requirement is the one that cost something: re-pull the lineups feed
as the LAST act before writing, and clock-stamp every liveness claim. A "zero
dead slots" written at 12:57 was false at 12:58 on 2026-09-12.

## The single build, when you want it directly

```bash
python <repo>/skills/generate-lineups/scripts/build_slate.py \
  --salary <uploaded DKSalaries.csv> \
  --entries <uploaded DKEntries.csv>
```

`--max-seconds` is omitted deliberately; it already defaults to this host's
call budget less 30s. The literal `100` this recipe used to carry was Cowork's
130 minus 30, and it capped every other host at Cowork's ceiling.

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
- **`cli_value_invalid`** — a flag VALUE this build cannot use: an unknown
  posture or gate name, a `--declare-pitcher` with no id, or a
  `--controls-override` / `--leverage` that parsed as JSON but is not an object.
  Checked in `main()` before anything is staged. Until R296 these were first
  read inside `run_classic` and aborted at exit 1 with no brief, so a typo in
  `--postures` cost the whole bank spend and then read as a crash.

A build that runs and then does not certify writes its brief, including to an
explicit `--brief` path, carrying `status: not_certified` with `failed_gates`
and `pool_blockers`. **That is true of the exit-3 sites that BUILT and refused,
and it is not true of exit 3 as a code** (R296(h), corrected 2026-09-03; this
paragraph read "exit 3 now always writes its brief" and was false for most of
them). Exit 3 means BUILT AND REFUSED, which is what `autobuild` spends
attempts on: it grows the bank, reads `feasibility`, applies floors. A refusal
that happened BEFORE any solve — bad input, a feed for another slate — is exit
`4`, so the supervisor stops instead of retrying against a verdict that does
not exist.

**Measured at R290(c) (2026-09-03), which is also the second correction to the
count in this paragraph: there are ELEVEN refusal exits, not nine and not
eight.** Eight literal `return 3`, two conditional returns of 3, and one at
exit `10`. Three of the eleven write a brief; the other eight print their JSON
to stdout and nothing else. The count moved three times in three days while the
item sat, which is why nothing here quotes a line number: read
`REFUSAL_SITES` in `build_slate.py`, which is the one table, and
`test_every_refusal_exit_is_classified` fails the suite if a refusal exit is
ever added without a row in it.

### Read the refusal's class before you read its errors

Every refusal now stamps its own payload with `refusal`, `refusal_class` and
`refusal_authority`, so you do not have to infer whether you are looking at a
DK rejection or at one of Ben's own exposure caps. **On 1940_9g a session
inferred wrong, cited the portfolio-level washout clause, and delivered nothing
into a lock window.** The three classes:

| `refusal_class` | what it means | what you do |
|---|---|---|
| `illegal` | DK would reject the file, or a named CLAUDE.md wall forbids the override. Read `refusal_authority` to see which — `dk_rule` and `claude_md_wall` are different facts | refuse, at any clock. Fix the cause or build the next slate |
| `badly_shaped` | what failed is one of Ben's own portfolio preferences, or search effort. The file is LEGAL and merely more concentrated, or thinner, than asked for | open the controls and ship it. CLAUDE.md: if the choice is a concentrated file or no file, ship the concentrated file |
| `read_it` | a fact about the INPUTS or the RECORD, not about the shape of the output. No relaxation reaches it | read the blocker. `refusal_override` names the flag where one exists |
| `split` | one exit standing over several failures with different classes | read `refusal_class_by_gate`, which resolves it per gate on this refusal |

Two exits are `split`, and the split is the thing worth knowing under a clock.
`not_certified` on Classic covers an allocation failure, six workflow gates and
the contest-identity blockers: four of those gates are DK rules, one
(`export_hash_binding_passed`) is provenance, and one
(`portfolio_caps_passed`) is purely Ben's exposure and overlap numbers, every
one of which DK accepts. And `verify_classic`'s "blank slot" was one string
over two facts — a PARTIALLY filled row, which DK rejects, and an ALL-blank
reserved row, which is unresolved coverage rather than an illegal roster (F-2,
Ben 2026-09-22: DK accepts a partial file only with those rows removed, not
left blank; R401, Session 22, builds that form). The brief now carries
`failure_kinds` and `delivery_blocked`; `delivery_blocked: false` with
`passed: false` means the file on disk is legal for every row that is filled
and only the blank rows are stopping it.

Exit `4` is deliberately outside all of this and stays a refusal at every
clock: nothing was solved, so there is no verdict to retry and no shape to
relax. A deadline does not conjure a salary file.

### Under a deadline: V is a wall, S relaxes, P is recorded (R386)

Ben, 2026-09-22: a legal file before the deadline outranks optional research,
simulation and quality gates. CLAUDE.md's Autonomy section is the contract and
MLB_Classic.md §2 defines the three classes; this is what they mean at the
keyboard. Inside T-30:

- **V is a wall at every clock**: IDs, salaries, eligibility, slots, the cap,
  entry mapping, template structure, locks, the delivered bytes.
  `refusal_class: illegal` is V.
- **S is yours to relax without asking**: exposure, stacks, overlap, reuse,
  anti-correlation, ownership. Record every move with its before and after
  value. `badly_shaped` is S. One S control never relaxes: distinct lineups
  within a contest (F-3; DK accepts a repeat, Ben never wants one).
- **P is yours to record**: optional feeds, degraded models, bookkeeping, the
  gate, the solver probe, QA, simulation. It never alone withholds a V-valid
  file. Skip the gate and the solver probe; `env_probe` still runs, because
  without scipy there is no file at all.
- **`read_it` is Mixed** until R388 splits it (Session 05). The engine treats
  it as a wall, so read the gate it names before deciding which class it is.
- **An S or P failure ships review-grade.** It never removes the file and
  never makes it upload-ready.
- **`--force` on the preflight stays Ben's at every clock.** The preflight
  does not yet tell a bookkeeping failure from a byte mismatch (R388(c),
  Session 13), so a file whose only preflight failures you judge P is
  presented review-grade with each failure quoted, and Ben decides at upload.
- **On an authorized repair, `late_swap.py --accept-downgrade` is your call.**
  Label the file review-grade.

Outside T-30, an S or P failure is still Ben's question. The deadline is first
lock minus 5 minutes, because Ben's upload takes 5 (F-1).

### `--deliver-by`: a clock inside the build

Pass `--deliver-by <ISO or HH:MM ET>` and a `badly_shaped` refusal stops being
a refusal from T-6. The build opens every portfolio control in **one move**,
re-solves, and delivers the file labelled `review_grade_deadline_build` with
the ladder it walked in `brief.deadline`. One crude step, not a stepwise walk,
because CLAUDE.md's T-15 rung measured the alternative: five careful control
changes cost 1940_9g five two-minute calls and produced no file.

Pass it on every build, set to the first lock: every build is deadline-aware
(F-4, Ben 2026-09-22). It is still opt-in in code and a build without it is
byte-identical to before, so there is no reason to hold it back; Sessions
15-17 make it the default.

The ladder is fixed and has two rungs:

1. `open_controls` — every portfolio control to its open value at once.
   Overlap opens to roster size **minus one**, never roster size: two lineups
   sharing every slot are the same lineup, and two identical entries in one
   contest are what Ben never wants (F-3: DK accepts them; distinct lineups
   per contest is the one S control that never relaxes).
2. `accept_blank_rows` — deliver the rows the bank filled, leave the rest
   blank. **Showdown only.** On Classic the engine passes
   `require_all_reserved_filled=True` at both validator calls, so a short bank
   fails inside the engine before any caller can label it; the refusal stands
   and stderr says so. A rung-2 file still carries its blank rows, and F-2
   (Ben, 2026-09-22) says DK accepts a partial file only with unresolved rows
   removed, so name the blank Entry IDs when you present it. R401 (Session
   22) builds the removed-rows form.

What it never does, and none of this is negotiable: it never reaches an
`illegal` or `read_it` refusal, never reduces the legal player pool, never
relabels anything `upload_ready`, and blank reserved rows still block
CERTIFICATION. Read `brief.deadline.deadline_ladder` for what was opened and
from what, and **run `tools/preflight_upload.py` on the file** — a governed
delivery is review-grade, so the preflight is the last independent look.

`tools/autobuild.py` takes the same flag and forwards it. There it also clamps
`--stop-after-minutes` to the lock, because `--deliver-by` is an external fact
and the other two clocks are budgets; the clamp lands in the decision log as
`clock_clamped`. `--call-budget-seconds` is untouched: it is a fact about the
shell, not about the slate.

On a host with a short per-call ceiling this command will not fit in one call.
Read "Running a build: what costs time, and the traps" below before you start,
and confirm the salary file is the slate Ben meant.

A typed `--controls-override` value stays relaxable; `--never-relax <control>` holds one under every deadline rung and floor (R388(b)), and a name the engine cannot hold refuses at exit 4. `references/never_relax.md` has the rules.

### Better data when there is time

The script fetches probable pitchers and batting orders itself if it has to, but
the dedicated skills are better and handle more edge cases. When you have a minute
before lock, run them first and pass the results in:

- **mlb-lineups** for confirmed lineups, batting order, and pitcher handedness.
  Save the JSON and pass `--lineups <path>`.

  **Do not hand-roll this feed.** `build_slate.py` reads a specific shape: one
  entry per GAME in `games`, each holding `away` and `home` objects with
  `team_abbrev`, `probable_pitcher`, `lineup_status`, and a `lineup` list of
  `{order, id, name, position, bat_side}`. `fetch_lineups_feed` in
  `tools/fetch_slate_bundle.py` is the reference implementation; copy its output
  shape or call it. A feed shaped one-entry-per-SIDE is rejected as
  `supplied_feed_rejected` with `covered: 0`, which reads exactly like a feed for
  the wrong slate and sent a 2026-08-16 session hunting a nonexistent date bug.
  Two crosswalk facts that cost calls the same day: the MLB API says `AZ` where
  DK says `ARI`, and `bat_side` is not on the schedule payload at all, it is
  backfilled from `/people` in chunks of 100.

  **When `statsapi.mlb.com` is proxy-gated, the `DFS_Architect_MCP` server is
  the substitute.** `get_mlb_lineups` and `get_mlb_probables` return real
  `source: "mlb-stats-api"` payloads carrying `handedness` on every hitter --
  the field the schedule hydrate omits and `fetch_lineups_feed` backfills from
  `/people`. Shape the result into the per-GAME structure above and pass it as
  `--lineups`. Measured 2026-09-18 where every repo fetch died on a 403
  CONNECT: 26 teams with handedness, `f4_platoon_applied: 162` on a 13-gamer.
  Two sessions on 2026-09-17/18 called the feed unreachable with these tools
  loadable throughout; one shipped Showdown at `hitters_with_side: 0`. Reach
  for it before reporting the feed lost.

  **`get_vegas_lines` on that same server is a STUB and must never reach
  `--odds`.** Verified 2026-09-18: `source: "stub"`, `confidence: "stub"`, one
  fabricated `game_id: "stub_game_1"` BOS @ NYY absent from that day's 15-game
  slate, priced at a plausible -150/+130 with a 9.5 total. It is shaped like a
  real payload, so nothing downstream rejects it: F1 would price every hitter
  off a fiction and the brief would call the build enriched. Read `source` and
  `confidence` on any odds payload; when either says `stub`, F1 is neutral.
- **mlb-game-odds** for moneylines, run lines, and totals. Save it and pass
  `--odds <path>`. Odds now DO change the build: they are the input to F1, the
  game-environment factor. When `--odds` is omitted the script fetches totals
  and moneylines itself if `THE_ODDS_API_KEY` is set, and leaves F1 at 1.0 for
  everyone if it is not.
  **`api.the-odds-api.com` is proxy-gated in SOME cloud sessions and not
  others, so check rather than assume (R316, 2026-09-06).** This line read
  "proxy-gated in cloud sessions, exactly as `statsapi.mlb.com` is"; measured
  on the device VM 2026-09-06, both answer normally (the odds API 200 with the
  repo key, statsapi 200 to plain `urllib`). Where it IS gated the fetch dies
  with a 403 tunnel error, the build says `F1 stays neutral` in one stderr
  line, and everything downstream certifies -- which is why the read below is
  the check either way. `enrichment.signal_applied: true` does NOT mean F1 ran -- five
  other factors moving rows set it -- so read `enrichment.counts.f1_games_priced`
  directly, and treat a 0 there as a build to fix rather than to present.
  The fallback when the API is unreachable is a paste, same as for lineups:
  read an odds table (`https://www.actionnetwork.com/mlb/odds` works; the page
  is client-rendered, so Chrome rather than `web_fetch`, and `__NEXT_DATA__`
  carries no prices), then

  ```bash
  python tools/odds_from_paste.py --salary <DKSalaries.csv> --paste - \
      --out data/slates/<date>/odds_from_paste.json
  ```

  One row per game PER BOOK, and the book column is required. Never average
  the book columns yourself: American odds are discontinuous at +/-100, the
  collapsed number is a price no book posted, and no per-book record survives
  it (R205, R236). The tool refuses an unnamed book, an unresolved team, a
  slate game with no priced row, and a payload the engine's own parser cannot
  read back.

### One extra step before lock: emit the ownership prediction (R135)

Two seconds, no network, no quota, and it cannot touch the build. It writes the
field-ownership prior for this slate so the archived standings can grade it after
the fact. Run it once you have the salary file and whatever feed and odds you are
going to use, BEFORE lock:

```bash
python tools/ownership_pred.py emit --salary <DKSalaries.csv> \
    --feed <lineups_feed.json> --odds <odds.json> --slate <tag>
# -> outputs/<date>/ownership_pred_<tag>.json
```

Why it is not optional: a slate that passes without a prediction file can never
be graded, so skipping it does not defer the cost, it destroys the evidence.
R10's bar is a fitted ownership prior that beats flat-12 in the satellite cell,
graded into the ledger, and this is what starts that record accumulating now
instead of on the day the fit begins.

**Since R246 (2026-09-01) this file is also a BUILD input, not only a grading
artifact.** The sentence here read "nothing reads it today" until that date and
it is no longer true: `--leverage` reads this exact file. Emitting it before
lock is now the precondition for the only lever that moves the portfolio off
chalk, so the reason to run it got stronger rather than going away.

It reads the same inputs the build does and reports each one as applied or INERT.
Read that block: `implied_totals INERT` means every hitter fell back to a league
mean, and a prediction with three of four features inert is worth grading but not
worth reasoning from. It never fetches to fill a gap, deliberately, so the
prediction costs no API credit and no clock.

The fourth feature, the value tilt, needs a Base projection and the build is what
produces one. If you have already built and there is still time before lock, add
`--base runs/<run_id>/final/projections.csv` and re-emit; that file has the
`Player_ID` and `Base` columns this reads. Without it the tilt is inert and the
prediction is salary, order, implied total and probable-SP only.

Emitting reaches nothing on its own: no projection, no `Ownership_Tier`, no
solver row. It is an UNCALIBRATED STRUCTURAL PRIOR and the file says so on every
read. What changed at R246 is that a SECOND, opt-in step can now feed it to the
solver, and that step is the next section.

### Leverage: the two constraints that move a portfolio off chalk (R246, opt-in)

Default OFF, and it stays off unless Ben asks. When he does ask to get off chalk
— and he has asked in-slate more than once — this is the answer, and it is a
flag now rather than an engine edit the contract forbids mid-slate.

```bash
python skills/generate-lineups/scripts/build_slate.py ... \
    --leverage '{"archetype": "large_field_gpp", "max_cumulative_ownership_pct": 90, "min_low_owned_hitters": 2}'
```

It reads the slate's own `outputs/<date>/ownership_pred_<tag>.json` (the file the
step above emits), writes `Projected_Ownership_Pct` onto the frame, and forwards
the numbers to the solver on **both** bank routes. Name the file explicitly with
`--ownership-pred <path>` when resolution is ambiguous.

Five things to know before you use it:

- **Emit the prediction file FIRST.** With no file it REFUSES and names the path
  rather than building unconstrained. That refusal is the feature: a leverage
  build that silently ignored the flag is the failure this item exists to end.
- **`archetype` is REQUIRED whenever the prediction file carries more than
  one, which is every file in practice.** The example above carried no
  `archetype` key until 2026-09-06 and did not run: on 2210_2g the prior file
  held six (`cash`, `large_field_gpp`, `mme`, `single_entry_gpp`, `small_gpp`,
  `wta_satellite`) and the build exited `leverage_unresolved` with no brief
  written, which also means the JSON explaining it is in
  `outputs/<date>/_<tag>.out` and not at the brief path you passed. The refusal
  names the valid set and the exact syntax; it cost a call to see it.
- **`max_cumulative_ownership_pct` is the sum over ten slots**, so on a thin
  slate an unconstrained lineup lands near 100-105 and a cap of 90 is a real
  bind.
  Measured on 1605_2g: cap 90 cost **-7.72%** of the single-lineup objective, cap
  80 cost **-32.50%**, cap 75 was INFEASIBLE. Start at 90-95 on a slate shaped
  like that one, not at 80; the third reading below is why that is not a rule.
  **That -7.72% is a 1605_2g reading and not a budget: re-measure per slate,
  because the cost scales with slate thinness.** On the 2026-09-04 2210_2g
  2-gamer, where the prior spreads over ~40 rosterable bats so the cumulative
  cap binds far earlier, cap 95 with `min_low_owned_hitters: 1` certified at
  apex 883.84 -> 688.27, **-22.1%**, and cap 90 with a floor of 2 REFUSED.
  **And it scales the other way on a wide slate: the cap can sit ABOVE the
  unconstrained sum and bind nothing.** On the 2026-09-08 2140_5g 5-gamer (208
  priced hitter rows, top hitter 14.7%) the delivered ten-slot sums ran 53.5 to
  93.9 under cap 95, low-owned carry stayed 0 of 15 in both builds, and only
  `min_low_owned_hitters: 1` moved the file. So the start is a little under the
  UNCONSTRAINED build's own maximum ten-slot sum, not a constant. The brief does
  not print that sum yet (R197 rider, 2026-09-09): until it does, sum
  `Projected_Ownership_Pct` over each delivered lineup before choosing a cap,
  and if the cap sits above that maximum say so in the handoff rather than
  reporting a leverage build.
- **`min_low_owned_hitters` has a hard infeasibility edge**, at 6 on that same
  pool. If the build refuses, lower the floor before you touch the cap; they are
  independently settable for exactly this reason.
- **The bank returns FEWER candidates under a cap at a fixed budget** (6 -> 4
  measured). That is search effort, not a pool reduction, and on a tight clock it
  means giving the bank more budget, never trimming the pool.
- **It is a DIRECTION TO TEST, never a number to apply.** The prior is
  uncalibrated and within-file ORDER is what it supports; ledger 3.17 has
  supersatellites chalk-NEGATIVE for winners, so a cap is wrong for that
  archetype. Record what you used in the brief (it does this itself, with the
  file's sha256) so the next slate has something to compare against.

Showdown refuses the flag before staging, because the Showdown bank builds no
ownership row and accepting it there would be a silent no-op. **Late swap cannot
carry it either** (R284, open): a portfolio delivered under a cap is refined by a
bank that never saw the cap, so say so rather than implying the delivered file's
leverage survived a swap.

### Batters facing your own SP: a control, not a wall (R288, Classic only)

```bash
python skills/generate-lineups/scripts/build_slate.py ... \
    --max-opposing-hitters-per-sp 1
```

Default **0**, which is byte-for-byte what the engine did before this flag
existed, so nothing changes unless you pass it. It is **per SP**, so a Classic
lineup carrying two arms has a per-lineup worst case of twice the value.

DraftKings does not prohibit the construction, and the evidence is DK's own
scored output rather than a reading of its rules page (CLAUDE.md bars fetching
draftkings.com by any route, and this section does not claim it was read):
19,072 of 102,201 fully-resolvable archived Classic entries in `data/archive/`
roster a hitter facing a rostered SP, and one 1,486-entry contest's ranks 1, 2
**and** 3 all did. DK accepted, scored and paid them.

**The frequency is slate-size dependent, and that is the whole reason to reach
for it.** 62.5% of entries on an archived 2-game slate carry one; 3.2% on a
12-game slate. So on a small slate the old wall forbade most of the legal space,
and on a big one it barely bound. The measured cost of treating it as a rule: on
1940_9g a hand builder held a 54%-exposure arm that banned every BAL bat from 20
of 37 lineups, and BAL — highest implied team total on the slate at ~5.9, in an
11.0-total game at Coors — took 2 roster slots out of 370. A pitcher-selection
error became a hitter-distribution error through a constraint nobody re-examined.

Four things follow:

- **It is yours to move.** CLAUDE.md puts it with postures and stack plans among
  the delegated decisions, not with the money-and-entry wall. Record the value
  and the reason in the brief, which carries `anti_correlation` on every Classic
  build including the default.
- **The preflight WARNS and no longer fails**, so a legal roster no longer costs
  a `--force`. You will see a line naming the entries and the count.
- **The export validator grades against the DECLARED allowance**, so a raised
  build reaches a file. Before R288 it hard-errored regardless and the control
  would have been unusable end to end.
- **Showdown refuses the flag** before staging rather than ignoring it, and
  `tools/repair_entry.py` KEEPS the no-opposing-hitter filter as its default,
  deliberately: a repair runs unattended inside a lock window, where the
  conservative construction is the right default even though the wall is wrong
  at build time.

### The two washout-axis caps: team footprint and game exposure (R343, R333, Classic only)

Ben's dual objective has two halves and the washout half binds at the PORTFOLIO
level (CLAUDE.md), not inside a lineup. Until 2026-09-15 it had one live lever,
`max_player_exposure_pct`, and two that could not reach it.

**`max_team_exposure_pct` — a team's footprint over EVERY hitter slot, any stack
role.** `max_primary_stack_exposure_pct` counts the PRIMARY stack alone, so a
team can arrive in most of the entered set through secondary stacks with nothing
binding and nothing reporting it: on 1310_9g (9 games, 21 entries) NYY sat in 15
of 21 entries, then 17 of 21 on the rebuild. Posture defaults ship at 0.55
(`wta_satellite`), 0.65 (`mme`), 0.70 (`large_gpp`), 0.75 (`small_gpp`), 1.0
(`single_entry`) — each about 0.20 above that posture's primary-stack cap, so
the primary cap stays the binding one on an ordinary build. An entry counts
toward a team at **2+ hitters** from it (`team_exposure_min_hitters`): a lone
filler bat is not a stack role, and at 1+ every team on a small slate reads near
1.0 by arithmetic.

**`max_game_exposure_pct` — a slate-wide scalar that expands to every game.**
It **ships OFF** and the brief says so on every Classic build, so its absence is
visible rather than merely true. The per-game form
`max_game_exposure_pct_by_game` is unchanged and wins where it is tighter. The
count is **every rostered player in the game, arms included** (R150, Ben
2026-09-15: a washout is a game outcome and the arm is in it) — which is a
DIFFERENT definition from the team cap's hitters-only one, on purpose, because a
teammate arm does not go quiet when the offense does.

```bash
python skills/generate-lineups/scripts/build_slate.py ...     --controls-override '{"max_team_exposure_pct": 0.6, "max_game_exposure_pct": 0.6}'
```

Both are fractions of the entered set and both go through the units gate, so a
`60` typed for `0.60` is refused rather than silently disabling the cap. Both
are floored UP to a slate-feasible value before the solve
(`floor_team_exposure_pct`, `floor_game_exposure_pct`) the same way the other
exposure ceilings have been since v1.9 — a one-game Classic slate floors the
team cap to 1.0 rather than refusing — and an arithmetically impossible value is
named in `feasibility.checks` as `team_exposure_capacity` /
`game_exposure_capacity` with the value to raise it to. Neither is relaxed by
the allocator's ladder; exposure CEILINGS on Classic are handled by that floor
merge, and the ladder relaxes only lower bounds and the engine's own reuse
default.

Where to read the result: the brief's `team_footprint_any_role` (beside
`primary_stacks`, which is the primary-only line it completes),
`game_exposure_request` and `team_exposure` in the checkpoint, and
`tools/qa_portfolio.py`'s washout section, which now carries a
`team_footprint` axis and names the control on every axis it reports.
`tools/late_swap.py` maps a `team T footprint N>M` refusal to this control the
way it already mapped `game G exposure N>M`.

The F5 material-weather cap (0.25 on medium postponement risk) is merged into
the per-game dict by MIN and named in `weather_game_caps_applied`. It was
computed and read by nobody before R333.

These are deterministic portfolio-shape controls. No archive number prices a
team footprint; neither cap is a win rate, a cash rate, or a probability.

### The consensus-cluster cap (R405, Classic only, ON by posture default)

The team, game and stack caps cannot see a CROSS-TEAM pool of bats the search
keeps choosing. On 1905_10g nine hitters sat at the 0.35 person cap and filled
36% of hitter slots; 27 of 34 lineups carried three or more of them while the
brief read 15 distinct primary stacks.

- **The cluster** is the BANK's consensus: every hitter in 15% or more of the
  distinct lineups the unconstrained search built, most-shared first, at most
  twelve. Derived by the allocator from the bank it receives, so every door
  agrees; cluster-limited bank jobs are excluded from the definition.
- **The cap**, `max_consensus_cluster_share_pct`, bounds the share of entries
  whose lineup carries k or more members (`consensus_cluster_min_members`,
  default 3). Ben's defaults (2026-09-23): 0.50 on `wta_satellite`,
  `large_gpp`, `small_gpp`, `mme`; 1.0 on `single_entry`; `cash` none. MIN wins
  across a mixed entered set. A fraction, through the units gate.
- **The bank** gets cluster-limited jobs on all three doors (sliced, direct,
  plan leg): the ordinary bank holds almost nothing below k (6 of 408 on
  1905_10g, 0 of 30 on the vendored 2026-06-03 slate), so without them the cap
  refuses BANK-LIMITED. Those jobs solve with at most k - 1 cluster members
  together; every player stays legal in every job. Search effort, never a pool
  cut.
- **Deadline and swap.** S class under R386: the T-15 rung opens it. Late swap
  strips it and prints the parent's cluster beside the swapped file's (the
  swap's bank has no limited jobs; enforcement is a rider on R284).

```bash
python skills/generate-lineups/scripts/build_slate.py ...     --controls-override '{"max_consensus_cluster_share_pct": 1.0}'   # off for one build
```

Where to read it: the brief's `exposure.consensus_cluster` (members and shares,
the delivered member-count histogram, the share at k or more, and the
`objective_median` price, bank and delivered side by side), the `consensus:`
stderr line, `consensus_cluster_request` in the checkpoint, and
`tools/qa_portfolio.py`'s `consensus_cluster` washout axis. A decorrelation
preference over labeled priors; never a win rate, a cash rate, or a probability.

### Classic scenario sleeves (R406, Classic only, ON by default)

Every Classic candidate used to be an argmax of ONE projection, so a systematic
projection error was shared by every entry. Sleeves build part of the portfolio
in worlds where the projection is wrong in named ways, and the allocator
confines each entry to one sleeve through its compatibility mask. The joint
MILP and every cap still bind across the whole entered set.

| Sleeve | World | Built as |
| :--- | :--- | :--- |
| `projection` | today's frame | the ordinary bank (and R405's limited bucket) |
| `salary_only` | DK salary as the only prior (group points-per-dollar, group median ratios) | its own cache file; scored in its own world |
| `chalk_fails` | the projection, with at most 1 of R405's consensus cluster per lineup | a limited bucket in the bank |
| `environment` | the top 2 games by implied total, else by static park run factor | projection lineups stacking those games' teams; restricted jobs only add depth |

- **Weights** (Ben, 2026-09-23): 40/20/20/20; `wta_satellite` and WTA contests
  30/20/30/20. Largest remainder per contest; a single-entry or cash contest
  seats `projection` only.
- **Fallbacks are counted**: a sleeve with no candidate, or fewer distinct
  lineups than entries in a contest, seats its excess on `projection`. On a
  two-game slate the environment sleeve is DROPPED (its top two games are the
  whole slate) and its seats fall back.
- **Off**: `--controls-override '{"classic_sleeves": false}'`. The T-15 rung
  opens it; late swap has no sleeve bank, so it seats as before.
- **Where to read it**: the brief's `exposure.classic_sleeves` (the request,
  the jobs, entries per sleeve per contest, fallbacks, and each sleeve's
  delivered apex and washout proxies) and the `sleeves:` stderr line.
  Constructions over labeled priors; a sleeve that does well in a replay is
  "supported in the shapes replayed", never a probability or an edge.

### Caps that scale with input confidence (R407, Classic only)

The brief already reports when the inputs are weak; since R407 the build reads
it back. Four facts, each the one the brief prints: no odds priced
(`enrichment.counts.f1_games_priced == 0`); a side the pool used came from a
platoon reference older than 7 days (R27's check); a Savant `expected_stats`
file is past the enrichment age warning's own threshold; no handedness
(`f4_platoon_applied == 0` with hitters in the pool).

| Tier | Facts | `max_player_exposure_pct` | `max_consensus_cluster_share_pct` |
| :--- | :--- | :--- | :--- |
| clean | none | unchanged | unchanged |
| DEGRADED | exactly one | -0.05 | -0.10 |
| SEVERE | two or more | -0.10 | -0.20 |

- **Floors win**: the result is `max(tightened, feasibility floor)`. An explicit
  `--controls-override` of either key wins over the tightening. A cap already
  at 1.0 is off and stays off.
- **Relaxed first**: inside T-30 the first solve runs without the tightening,
  and on a proven-infeasible joint MILP the build re-solves once without it
  BEFORE the deadline governor moves anything. Both record the before and the
  would-be after (`relaxed_deadline_t30`, `relaxed_proven_infeasible`).
- **Where to read it**: the brief's `input_confidence` (tier, the facts that set
  it, each control's before and after, provenance `confidence_derived`) and the
  `input confidence:` stderr line. A `run_slate` caller that supplies no facts
  reads `not_assessed` and nothing moves. A deterministic schedule over labeled
  inputs, never a probability that the projection is wrong.

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
rather than implying DraftKings published it. The MONEYLINE in the packet is
derived too (R205): each book that posts a complete two-way is de-vigged, the
probabilities are averaged, and the price carried forward is the vig-free one
implying that average. `moneyline_books` holds what each book actually posted;
quote that, not the consensus, if Ben asks what the market said. Hitter F1 is the team's implied
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

## Lineup sources rank, and the ranking is PER SIDE (R143, Ben 2026-08-17)

**The DKSalaries CSV first, a paste second, an API pull third.** DK publishes the
batting order in the `Starting` column, 1-9 next to the Player_ID this project
already calls authoritative, so a side DK has posted needs no paste and no fetch.
Measured on the 2026-08-16 file: 15 of 16 sides carried a complete 1-9 while the
build went to a paste or a 25-second API call for the same fact.

You do not wire this up. `merge_dk_starting_into_feed` runs inside
`build_slate_pool`, the required intake front door, so every path gets the
ranking and no caller can bypass it. It only ever ADDS a confirmed side or
upgrades one, which is what makes the ranking per side rather than per slate.
`build_slate.py` calls `dk_order_coverage` before deciding to fetch and makes no
API call at all when DK covers every side; the brief says
`"DK posted every side in the salary file; no paste and no API call were needed"`.

Four things to read off it rather than rediscover:

- **Only a COMPLETE 1-9 counts.** A partial DK side is a projection, so it falls
  through to the feed untouched and routes through the TBD path (same reasoning
  as R60).
- **DK ships no handedness, and that is the cost of the zero-fetch path.** The
  merge keeps `bat_side` from a feed that has it and names sides where none does
  in `dk_batting_order.f4_handedness_unavailable`. On a slate DK covers whole,
  nothing supplies handedness, so the **F4 platoon component is neutral for every
  hitter** and the brief reads `f4_platoon_applied: 0`. That is stated, not
  silent, and it is a real tradeoff: the API call R143 stopped spending was
  buying handedness as well as batting order.
- **So still ask Ben for a paste when there is time.** It costs nothing in
  precedence, since DK outranks it on order either way, and it carries
  `(R)/(L)/(S)`, which is what keeps F4 alive. The zero-fetch path is for when
  there is no paste, not a reason to stop asking for one.
- **Where DK and a paste disagree on the same posted side,** DK wins and the
  difference is NAMED in `dk_batting_order.disagreements`. Never resolve it
  yourself: the CSV is a point-in-time download and a paste has no timestamp, so
  neither can be proven fresher, and the operator gets the fact instead of a
  guess. Surface it when the disputed name matters to the build.

## When Ben pastes lineups, that paste outranks any API pull (R32)

R143 narrowed this: the paste is second, behind a complete DK 1-9 for the SAME
side. It is still primary over the API and over every side DK has not posted,
which on a pre-lock slate is most of them, and everything below is unchanged.

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

Six things to know before you run it.

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

**Check that the probables actually attached (R117).** The parser reads both
renders of mlb.com's hand line -- `RHP` alone, and `RHP 8-7, 3.87 ERA, 144 SO` on
one line -- but only the first was read until 2026-08-18, and the failure was
silent in every direction: zero probables attached, no warning, the held name
became the game's VENUE, and DK's `Starting` fallback then supplied a name with a
null id and an empty hand, which kills F4's Savant join AND its platoon prior.
Three slates certified that way with `f4_non_neutral: 0`. So: if the tool prints
`DK STARTING` for every side of a paste that clearly named pitchers, the hand line
is a THIRD render and the parse warning names the line it could not read. Two
surfaces answer this after the build without re-reading the log --
`pool_report.opposing_probables_incomplete` names the sides whose opposing
probable carries no id or no hand, and the brief's `factors_inert`, printed as the
`factors:` line beside the frontier line, names any factor that scored rows and
moved none of them.

**Fall back only for what the paste does not cover.** If some games are still TBD,
fetch a feed for those and pass it as `--merge-feed <api_feed.json>`. A pasted
side is never overwritten; the merge report says which games and sides came from
the API, and prints `Zero lineup fetches` when the paste covered everything.

**A fully pasted slate needs no platoon reference and no handedness lookup.**
Handedness is in the paste as `(R)/(L)/(S)`, and with no TBD teams the platoon
reference is never read, so the 7-day staleness warning has nothing to gate.
That is the fast path: one conversion call, then build.

## Running a build: what costs time, and the traps

Host facts -- call budgets, whether `rm` works, where the repo sits, where
attachments land -- live in `docs/hosts.md` and are resolved in code by
`mlb_engine.repo_env.host_profile()`. Ask those, not this file, for a number.
R354, 2026-09-17: this section used to be 147 lines of Cowork device-VM mechanics
with the durable advice mixed in. The mechanics moved; what follows is what stays
true on every host.

**Put one expensive thing in each call.** The default path does two network
fetches inside the build: the MLB Stats API lineups pull, which alone has a
25-second timeout, and the RotoWire merge. Either can consume the whole remaining
budget on a constrained host. Do the fetch in its own call instead, with a short
standalone `urllib` script that hits

```
https://statsapi.mlb.com/api/v1/schedule?sportId=1&date=<date>&hydrate=lineups,probablePitcher,team
```

shapes the response into the same structure `fetch_lineups` produces, and writes
it into the slate directory. That call is cheap because it imports nothing from
the engine.

**The hydrate does not return handedness, and the omission is silent.** The
schedule response gives lineup players and probable pitchers as id plus name,
with neither `batSide` nor `pitchHand`. Both are inputs to the F4 platoon prior,
so a hand-shaped feed that omits them silently zeroes that component.
`fetch_lineups` fills them with one batched call; a hand-rolled pre-fetch must do
the same:

```
https://statsapi.mlb.com/api/v1/people?personIds=<ids>&fields=people,id,batSide,pitchHand,code
```

Write `bat_side` onto each lineup hitter and `hand` onto each probable pitcher.
Check `enrichment.counts.f4_platoon_applied` in the brief afterward; a zero there
on a slate with confirmed lineups means the feed was missing handedness.

Then build:

```bash
python -u "$REPO/skills/generate-lineups/scripts/build_slate.py" \
  --date <date> --salary <salary.csv> --entries <entries.csv> \
  --lineups <feed.json> --no-rotowire \
  > "$REPO/outputs/<date>/build.log" 2>&1
```

Pass `--max-seconds` only to fit a host that has told you its budget; the default
is resolved per host and is usually right. On a host with a short per-call
ceiling, read `docs/hosts.md` before you pick a number rather than deriving one.

### Three shell traps, each of which has cost a session

- **`python -u`, and redirect the log into the repo.** Unbuffered, or a killed
  call leaves you an empty log and no idea how far it got.
- **Never `pgrep -f build_slate.py` or `ps | grep build_slate`.** The pattern
  matches the grep itself, so it reports RUNNING forever and you wait on a
  process that exited.
- **`$?` after a pipe into `head` is `head`'s exit code, not the command's.** A
  failed build reads as success. Capture the log, then read it.

### When something looks broken

Do not conclude the environment is broken from one observation. Pause, retry
once, and check whether a second attempt behaves differently. If a stall persists
across retries during a live slate, deliver from what is already certified rather
than waiting it out -- a certified file in hand beats a better one that misses
lock.

**Dependencies do not persist between sessions.** The preflight at the top of
this file is the whole answer; run it rather than diagnosing an import error.

**On exit 10 the bank is thin, not wrong.** Use the exit-10 resume and run the
identical command again; the bank persists between invocations and each pass adds
to it. Shrink the bank, never the pool.

## Where the files come from

Ben attaches the DKSalaries and DKEntries CSVs to the chat. Find them, stage them,
and never commit them: `data/slates/<date>/` is gitignored and that is where they
belong.

```bash
python tools/stage_slate.py --from-attachments --date <date>
```

That searches the host's attachment locations, identifies each file **by its
header rather than its name**, copies the matches into `data/slates/<date>/`, and
prints the directory it used and the sha256 of each staged copy. Two files
matching one role is a block, not a guess (R70) -- it names both and exits 4, and
you resolve it by passing `--salary-csv` / `--entries-csv` explicitly. Those flags
accept an absolute path, so a file somewhere the search did not look is one
argument away, never a dead end.

**Read back the directory it used.** Attachment paths differ per host and have
moved before; if the tool reports a location you did not expect, say so rather
than assuming it found the right slate. If it finds nothing, ask Ben to re-attach
rather than building from a stale copy already sitting in `data/slates/`.

Never correct the DKSalaries CSV against real-world rosters. It is authoritative
for player IDs, salaries, teams, and eligibility, whatever it says.

## Confirm which slate you were handed

Before staging, print the salary file's game list, game count, and first lock from
the `Game Info` column, and the entries file's contest IDs. Compare them against
the games Ben named. Two traps, both seen on 2026-07-24:

- A re-uploaded file can land under a hashed filename while the generic
  `DKSalaries.csv` still resolves to the earlier upload. `--from-attachments`
  prints the directory it searched; run `ls -la` on THAT directory and read
  mtimes. Be suspicious whenever a generic name and a hashed variant coexist.
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

R133, 2026-08-18: a team merely SHORT OF NINE is a different fact and no longer
blocks. Its bar is `MAX_HITTERS_PER_TEAM` (5), the count that fills a maximum DK
stack, so 5 through 8 warns and certifies while under 5 blocks. Read
`pool_report.thin_teams`, which splits the two and carries the bar. Also worth
knowing at T-10: `--ignore-pool-blockers` alone never certified, because the
pre-export gate re-reads the pool report; pair it with `--assume-gates
lineup_gate_passed` (the tool now prints this at the override) and the assertion
lands in `overridden_gates` with the evidence it contradicts. A crosswalk failure
is refused outright rather than overridden.

Keep it to a handful of lines. Ben can open the JSON if he wants the rest. Do not
narrate the steps you took; he watched them happen.

### Hand the file over, do not just name it

**Send the delivered file itself into the conversation**, with its sha256 in the
same message, and remind Ben the upload is manual. A path is not a delivery.

This is the step a cloud session cannot skip. `outputs/<date>/` is gitignored and
a cloud container is destroyed when the session ends, so a certified file that
only ever exists on disk is a build that produced nothing Ben can upload. On
Windows a path alone is survivable because the disk is his; nowhere else. R354,
2026-09-17 -- before it, this read "present the delivered file so he can open
it", which named no mechanism at all.

Order matters and does not bend: `preflight_upload.py` exits 0 FIRST, then the
file goes over. Never hand over a file you have not preflighted, and never at
T-5 "to save a step" -- the preflight is under two seconds and it is the last
thing standing between a bad file and an upload.

The sha256 you state must be the one in `outputs/<date>/upload_manifest.json`.
If they differ, say so and stop: two files are in play and Ben is about to
upload the wrong one.

**Nothing goes between the preflight and the hand-over.** Not a commit, not a
push, not the gate, not a PR. Repo housekeeping is real work and it belongs
AFTER Ben has the file, because until then the slate can still be lost and
none of it helps. On 2026-09-17 a Showdown file was gate-clean at 19:20:08 and
reached Ben at 19:28 with commit, push, a 3m33s audit gate and a PR in
between. Lock was 21:38, so it cost nothing; at T-12 it would have cost the
slate. The ordering is the lesson, not the eight minutes.

Nothing here touches DraftKings. Ben uploads by hand, always.

### Commit the delivery record, AFTER the hand-over

R369, 2026-09-19. Every delivery now writes a tracked JSON at
`data/deliveries/<date>/<tag>_<run_id>.json` — the manifest row, the entry rows
parsed out of the delivered file, the input fingerprints, the code identity, the
effective controls, the host and the egress line. It is written for you by
`upload_manifest.record_delivery`, so there is nothing to run; what a cloud
session has to do is **commit and push it**, because `outputs/` and `runs/` are
gitignored and the container is reclaimed. Without this commit the build is
ungradeable: `awaiting_standings`, `field_miner.harvest_own_entry_ids` and the
outcome review all read this file and nothing else survives.

```bash
git add data/deliveries/<date>
git commit -m "record: <date> <tag> delivery (R369)"
git push -u origin <branch>
```

This belongs in the same "repo housekeeping" block as the commit and the push,
which means **after** Ben has the file. The ordering rule above is unchanged and
outranks this: nothing goes between the preflight and the hand-over, this
included. A record committed ten minutes late still grades; a slate lost at T-8
does not come back.

A refusal writes a record too, keyed `<date>_<tag>_<utc>` with `kind: refusal`
and the exit code. Commit those the same way. A night that shipped nothing is
the night the record is worth most.

## Always run the preflight before presenting a file

Between "build finished" and "Ben uploads," run this on every deliverable,
Classic and Showdown alike. No exceptions and no exemption at T-5: it imports no
engine, touches no network, and finishes in under two seconds.

```bash
python <repo>/tools/preflight_upload.py --entries <delivered file>
```

**It hard-fails a player whose game has already started (R287), and that check
needs no feed.** Start times come from the salary file's own `Game Info`, so a
file built after first pitch is caught even when nothing else about the slate is
available — which is exactly the state a slate is in at 19:56 on a night that
went sideways. On 2026-09-01 this tool printed `first lock: 19:40 ET` and then
`PASS ... all hard checks clean`, exit 0, on a file holding 151 roster slots from
games that had already started; a second file that night carried 78 and also
cleared. DK would have rejected both. It is a hard failure and not a warning,
because a warning at the money boundary is one the clock talks someone past.
`--as-of "19:56"` pins the clock to replay a check against a past moment, and a
bare `HH:MM` is read as **Eastern**. R292(c): `preflight_upload.parse_as_of` is
now the ONE reader of that flag, so `verify_export.py` and `tools/repair_entry.py`
answer identically — until 2026-09-02 the same characters meant ET here, UTC in
`verify_export` (four hours early, which reads a 19:40 first pitch as still open)
and a naive `TypeError` in the repair tool, and only this tool took `HH:MM`.

Four inputs resolve themselves, because a check that runs only when you remember
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
- `--brief`: the build brief for this delivery, matched among the sibling
  `build_brief*.json` files by `delivered_sha256`. It is read for one field,
  `declared_pitchers`, so an arm the build rostered on a declaration is an
  acknowledged WARN naming the role instead of a hard failure (R114). An
  **undeclared** missing arm still fails. Two things follow for you. A declared
  arm no longer needs `--force`, so if you find yourself reaching for it on a
  "not in X's confirmed lineup or probables" line, check the brief resolved
  first: exit 4 on a spurious failure is the habit that eats the real one. And
  the WARN says `Evidence: operator_declared`, which is the truthful label — the
  build's own statement, not confirmation from the feed. Where there is no run
  to read, `--declare-pitcher <id>[=role]` states it by hand, same grammar as
  `build_slate.py`'s flag.

A confirmed lineup with **no probable** is a bullpen game, and its posting
evidences bats only (R67). Those hitters bind exactly as before; the arm is
named soft rather than contradicted, because nine posted bats say nothing about
who starts.

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

**Three portfolio controls, all enforced in the solver, all reported:**

- `max_shared_players` (default 4 of 6). No two lineups may share more than four
  players. Overlap counts the PLAYER, not the role, because promoting a UTIL to
  CPT is not a differentiated lineup. Exact-set forbidding, the old default,
  called a one-player swap unique.
- `max_cpt_exposure_pct` (default **0.25**, Ben 2026-08-19). No captain above a
  quarter of the entered set.
- `max_player_exposure_pct` (default **0.50**, Ben 2026-08-19, new in R153). No
  PLAYER, in any role, above half of it. This is the portfolio-level washout
  control the module lacked: on the 2026-08-19 ARI@BOS build the overlap bound
  was clean at 0 relaxations, the captain cap was clean, and Nick Sogard was in
  12 of 19 entries because he was the cheapest posted leadoff bat and every
  BOS-leaning thesis reached for the same salary relief. One 0-for-4 took down
  twelve entries, which is exactly the correlated failure the other two controls
  were never measuring.

Every cap count is a `floor()` of pct * entries, so realized exposure lands at or
below the requested pct. That rounding rule is why the captain cap used to be
0.33 rather than 0.35 (at 20 entries 0.35 permits seven captains, a realized
35%); 0.25 has no such edge. The one escape is `pct * n < 1`, where the count
clamps to 1 rather than forbidding everyone.

They relax rather than truncate, in a fixed order: overlap gives way first, then
player exposure, then the captain lock, then the thesis. A short bank leaves a
blank reserved row and a blank row blocks certification, so silently shrinking is
the one outcome not on offer. Player exposure sits second because relaxing it
puts one more entry on a player already at half the set, a washout cost spread
thin, where relaxing the captain lock concentrates the single highest-leverage
slot.

**Read `counted_relaxations.clean` and understand what is NOT in it.** Both caps
bind against the REALIZED set. When a thesis names a player who is already at a
cap, the player comes off that thesis's `cpt` and `locks` before the solve, the
thesis still builds, and the removal lands in `player_exposure.cap_reassignments`
and `.locks_dropped`. Those are not relaxations and are not counted as such:
nothing gave way, the cap held, and what moved was the thesis label. So a thesis
row reading "BOS win close (variant 2, Wilyer Abreu captain)" can legitimately
have a different captain, and the reassignment list is where that is stated.

R153 second pass, worth knowing because both leaks shipped once: a cap enforced
anywhere other than where the roster spots are actually spent is not a cap.
`solve_ladder` enforced no captain cap at all, trusting `build_thesis_ladder`'s
apportionment, so a lock substitution landed on top of a full captain (26.3%
under a 25% cap). And the player cap's original carve-out for a thesis's own
names let one player reach 57.9% under a 50% cap while `player_relaxed` read 0 —
the cap reporting itself clean while not binding.

Every relaxation is counted in `diversity`, `captain_exposure` and
`player_exposure`, and repeated in `caution`. Read those before reporting the
portfolio as clean. Override any of the three through `--controls-override`,
which reads all of them from one dict.

`player_exposure.structural_floor_pct` is `roster_size / pool_size`, the lowest
cap that can fill the entries from the pool by counting alone. A cap below it
cannot hold no matter what the solver does. The engine reports that and does not
widen the cap, because raising an exposure cap is a strategy change and CLAUDE.md
makes it Ben's.

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

**What the swap does NOT inherit is leverage (R284, open).** The swap builds its
candidates with no `max_cumulative_ownership_pct` and no `min_low_owned_hitters`,
whatever the parent was built under, so a portfolio delivered at cap 90 comes back
from a refinement with no cap on the entries the swap touched. Nothing false is
reported — the control is absent, not applied against the wrong number — but if
Ben asked for leverage on the build, say plainly that the swapped entries are not
carrying it rather than letting the parent's brief speak for the new file.

Details in `references/late_swap.md`.

## After the slate: the retro

After delivery, never inside the T-window, spend a few minutes on the run
itself. The brief self-reports the INPUTS; nothing self-reports the session, so
a misfiring tool, an unreached fallback or a costly ordering is visible only
here and only now. Findings route by layer: engine/tool and ergonomics to a
`docs/backlog_inbox/` fragment, process to a skill edit, environment/host to
Ben, who is the only one who can change it. **No findings means file nothing** —
a clean run is one line in chat. `references/retro.md`.

## When something goes wrong

**Blockers in the pool report.** Read them. A team with no probable and no
declared starter is a real decision, not a glitch; ask Ben which arm to declare
rather than guessing.

**"no compatible candidate for Entry ID ..."** means the bank has nothing legal
for that entry's pins and exclusions. Run the command again to add another slice.
If it persists, the entry may pin so many hitter slots that a 4-man stack cannot
fit; the bank relaxes that automatically, but say so in the brief.

**Which tool owns the entry: `late_swap.py` while it is mostly OPEN,
`tools/repair_entry.py` once it is mostly LOCKED, and the boundary is
`open <= pinned`.** The repair tool prints that boundary in its own refusal
("more open slots than pins: the whole-lineup solve optimises jointly and owns
this entry"), so a `deferred` record means you reached for the tail tool at the
head of the slate — which is what happened on 2026-09-02 1940_6g, with 3 of 6
games locked and 8 slots still live. Going the other way, growing the bank
against a 9-pin prefix cannot work and is not a search-effort problem: on
1305_12g it went 566 → 1425 candidates across six invocations and the message
never changed.

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
python tools/audit.py --run-tests --terse
```

Whether that fits one call, and how long it takes, is a host fact:
`docs/hosts.md` has the table, and `docs/cowork_sandbox.md` has the split gate
for Cowork, the one host where it does not fit. The gate is the session's job.

When the skill or its scripts change, run the fixture evals too (not part of
the audit; they are the skill-development harness and each pins an exit code,
artifact states, and forbidden claims):

```bash
python skills/generate-lineups/evals/run_evals.py    # --only <id> for one
```

The audit checks dependencies first and names the install command if something is
missing, because a missing solver is not a slow build, it is no build. It also
pins the test count, PER SUITE since R62: `EXPECTED_SUITE_COUNTS` in
`tools/audit.py` is the source of truth and `EXPECTED_TEST_COUNT` is only its
sum, so adding tests means bumping the suite's own entry, not a single total.
Only the ledger Quick Card quotes the counts, and it is ARCHIVE's to move. A
count mismatch is the pin working, not a broken suite, but read the state word
the audit prints before touching a pin. Only
`grew` is a stale pin. `shortfall`, `skipped_in_place` and `absent` are lost
coverage, they name the precondition to stage, and lowering a pin to meet them
retires the tests for good.

Inside T-30, skip the gate and the solver probe and go straight to the build
(R386): they measure engineering health, not the file. `env_probe` is the one
part that is never skipped: it costs about 9 seconds, and a fresh sandbox with
no scipy produces no build at all.

## Verifying a file you did not just build

For a file with no parent, `preflight_upload.py` above is the whole check. When
the file refines an earlier one, use:

```bash
python <repo>/tools/verify_export.py --entries <file.csv> --parent <prior file> \
  [--salary <DKSalaries.csv>]
```

It runs every preflight rule (blanks, partial rows, duplicate Entry IDs, header
geometry, DK Status, embedded-pool overlap, cap, slot eligibility, duplicate
persons, two games, five hitters per team, players whose games have already
started, hitter versus rostered SP — a WARN since R288, not a failure — Showdown
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
