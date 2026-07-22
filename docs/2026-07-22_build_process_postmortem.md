# Build process post-mortem — 2026-07-22 early slate

Scope: the 10-lineup Classic build for the 8-game early slate, from session start
to certified late swap. Written after the fact from the session transcript and
from measurements re-taken against the same pool. Every timing below was measured,
not estimated.

Bottom line: the build shipped, twice, both times certified. But it consumed
roughly 35 minutes of a 40-minute window, and the reason was not the solver. Three
of the four problems Ben flagged are one problem wearing different hats. The two
most dangerous failures of the session were somewhere else entirely, and one of
them was mine.

---

## 1. Severity ranking

Ordered by what each would cost on a future slate, not by when it surfaced.

| # | Failure | Cost if unfixed | Layer |
|---|---------|-----------------|-------|
| 1 | Doubleheader lock-time collision | Missed lock; whole slate lost | Engine |
| 2 | Player pool trimmed to fit a compute budget | Silent strategy change, invisible in output | Process |
| 3 | `AZ` never resolved to `ARI` in platoon handedness | Wrong platoon split, silently | Engine |
| 4 | FanGraphs abbreviations never normalized | Team fills 0/9, warning only | Engine |
| 5 | Sandbox 43s ceiling vs unbounded bank build | ~15 min of thrash per slate | Environment |
| 6 | Late-swap call path undocumented | ~8 wasted calls per swap | Ergonomics |
| 7 | `scipy` absent, audit expectation stale | Session-start gate fails, ad-hoc repair | Environment |

Ben's items (1)–(4) in the prompt are all row 5. They are the symptom chain of a
single environment mismatch, and they were the most *visible* problem because they
generated the most noise. They were not the most expensive.

---

## 2. The doubleheader bug is the one that could have cost the slate

`live_data_adapters.build_status_map_from_lineups_feed` keys every game by matchup
string alone:

```python
game_id = f"{away_team}@{home_team}"        # live_data_adapters.py:205
```

Today's feed contained both legs of two doubleheaders. `PIT@NYY` appeared twice —
17:05 UTC (Game 1, the DK slate game) and 23:05 UTC (Game 2). The second write won.
`BAL@BOS` did the same thing.

Consequence: `slate_clock` reported first lock as **SF@KC at 18:10 UTC**, with
101 minutes to the T-5 deadline. The true first lock was **PIT@NYY at 17:05 UTC**,
with 31 minutes. A 65-minute error, in the direction that gets you locked out.

I caught this only because the DKSalaries `Game Info` column disagreed with the
clock and CLAUDE.md says the salary file is authoritative. The salary file had the
right answer the entire time and the engine never consulted it for lock times.

This is a latent correctness bug that has nothing to do with the sandbox. It fires
on any date with a doubleheader on the slate.

**Fix.** Key games by `game_pk`, or by `(matchup, start_time)`, never by matchup
alone. Then have `slate_clock` cross-check its computed first lock against the
salary file's `Game Info` and raise a hard error on disagreement rather than
preferring the feed. Add a doubleheader fixture to `tests/test_core.py` — there
isn't one, which is why 131 passing tests didn't catch it.

---

## 3. The decision I got wrong

Partway through the budget thrash I wrote:

> "Bank build across 120 SP pairs is the bottleneck. Trimming the SP field to a
> defensible subset (no Coors arms, no road dogs) to fit the solve in budget."

I then dropped seven starting pitchers from the pool and framed it as an
environment screen. Two things are wrong with that.

First, the diagnosis was a guess and it was incomplete. Measured against the same
159-row pool:

| Operation | Measured |
|---|---|
| One unconstrained `build_single_lineup` | 0.52 s |
| `build_multi_lineup` n=3 | 0.74 s |
| `build_multi_lineup` n=5 | 3.15 s |
| `build_multi_lineup` n=8 | 7.56 s |
| `build_multi_lineup` n=10 | 12.22 s |
| `build_multi_lineup` n=12 | 11.63 s |
| Bank target for `requested_n=10` | 20 lineups |

The base bank alone (20 lineups, superlinear growth from overlap repulsion) runs
~25–40s and is already at or over the ceiling before any augmentation. The SP-pair
augmentation then adds ~112 cross-game pairs at ~0.5s each, another ~55s. Trimming
16 SPs to 9 cuts pairs to ~36 and saves maybe 45s of the *second* term while
leaving the first term over budget. That is exactly what happened — the 9-SP
attempt also blew through 43s. The trim bought nothing and I only learned that by
trying it.

Second, and worse: I let an infrastructure limit change the legal player set. That
is a strategy change disguised as plumbing, and it does not show up anywhere in the
certified output. A reviewer looking at the export would see a portfolio with no
Mitch Keller and no Coors arms and have no way to know a 43-second timeout caused
it.

**The rule this should have followed:** an infrastructure limit may reduce *search
effort* — bank size, augmentation breadth, time per solve — and may never reduce
the *legal player pool*. If the budget cannot fit the search, shrink the bank and
say so. Never quietly shrink what the optimizer is allowed to see.

The later fallback to confirmed-lineups-only was a defensible version of the same
pressure, because excluding teams whose batting order is unknown is a data-quality
argument that stands on its own. The SP trim had no such standing.

---

## 4. The sandbox ceiling, diagnosed properly

Bash calls in this environment are capped at 45s and **every process is killed the
instant the call returns**. Not backgrounded, not suspended — killed. `nohup`,
`setsid`, and `disown` all fail; I confirmed it with a heartbeat file that froze at
36 seconds while the log stayed empty. The filesystem persists between calls; only
processes do not.

So the real constraint is: **~43 seconds of compute per call, with disk as the only
carry-over.** The engine was built for a laptop where `run_slate` can take five
minutes. Under that assumption an unbounded loop is fine. Here it is a guaranteed
silent kill that produces no output and no diagnostic — which is why the first four
attempts told me nothing.

I lost roughly 15 minutes establishing this empirically, at T-30, on a live slate.

**Fix, in order of leverage:**

**(a) A solver probe, run at session start.** `tools/solver_probe.py` builds the
frame, times one `build_single_lineup` and a 5-lineup `build_multi_lineup`,
extrapolates to the requested bank size, and prints projected wall time against a
declared budget. Ten seconds of work. Run today it would have said "projected 95s
against a 43s ceiling" before I wrote a single workaround, and the bad SP-trim
decision would never have been made. This is the highest-value item on the list.

**(b) Make the budget a first-class parameter.** `build_multi_lineup` and
`build_diverse_candidate_bank` should accept `time_budget_s`, return partial
results with a `budget_exhausted` diagnostic, and pass a per-solve `time_limit` to
HiGHS so one pathological MILP cannot eat the whole allowance. Returning 14 good
candidates with a flag beats returning nothing after being killed.

**(c) A real resumable bank in the repo.** My `_bank.py` was a throwaway; the
pattern was right and should be promoted to `mlb_engine/optimize/bank_cache.py`:
persist candidates to `runs/<id>/bank/` incrementally, record completed
(SP-pair, stack-team, locked-slot-signature) jobs, resume on the next call, and
feed both `run_slate(candidates_override=...)` and `run_late_swap(candidates=...)`.
This converts "will the build finish before it is killed?" into "how many calls do
I need?" — a schedulable question rather than a risk.

One detail worth carrying over: **dedupe candidates on the ordered ten-slot roster
tuple, not the player set.** I used a `frozenset` of player IDs and it silently
discarded valid slot orderings, which is what made two entries unfillable during
the late swap. For late swap, slot assignment is part of the candidate's identity.

---

## 5. Two silent-degradation bugs in the platoon path

Both surfaced only because I checked the report line by line. Both produce a
warning and keep going.

**`AZ` never becomes `ARI`.** `live_data_adapters` defines `DK_ABBREV_REMAP =
{"AZ": "ARI"}` and applies `to_dk_abbrev()` correctly in its own functions. But
`platoon_order_adapter.extract_opp_throws_from_lineups` uses the raw feed value:

```python
a_team = str(away.get("team_abbrev") or "").strip().upper()   # no to_dk_abbrev
```

So `opp_throws` came back keyed `AZ`, the lookup for `ARI` missed, and the adapter
fell back to `default_hand='R'`. Arizona faces Gage Jump, a lefty. The first pass
built ARI's projected order off the wrong platoon split and recorded it as
`hand_assumed_teams: ['ARI']` — a warning, not a blocker.

**FanGraphs abbreviations are a third vocabulary.** The platoon file uses WSN, TBR,
CHW, KCR, SDP, SFG where DK uses WSH, TB, CWS, KC, SD, SF. Washington matched
nothing and filled **0 of 9** hitters, dropping silently to the AvgPointsPerGame
fallback. I normalized the saved reference file, which fixes it for this file, but
the adapter will do the same thing to the next one.

**Fix.** Route every team code through `to_dk_abbrev()` at every ingest boundary,
extend the map with the six FanGraphs codes, and add a startup assertion that every
team code in every feed resolves to a code present in the DKSalaries file. Then
make a team filling 0/9 a **blocker, not a warning** — a silent 0/9 is
indistinguishable from having no data at all, and it currently reads as success.

More broadly: `tbd_fallback='top9_appg'` guesses a batting order and labels it a
prior. That is honest, but it should require explicit per-team opt-in rather than
happening by default. Guessing Colorado's order at Coors is a decision worth
making out loud.

---

## 6. Ergonomics: the late-swap path cost eight calls

`run_late_swap` is only exercised inside `tests/test_core.py`, and getting a live
call to pass required discovering, one failure at a time:

- `build_status_map_from_lineups_feed(feed, salary_csv)` — feed first, not salary
- `stack_constraints={'team': ..., 'min_size': ...}` — not `primary_team`
- `workflow_gates` is a required keyword on `execute_portfolio`
- candidates need `roster_slot_ids` in `ENTRY_ROSTER_SLOTS` order, not a player list
- entry requirements carry `excluded_new_teams`, which forbids introducing *any*
  new player from a locked game — the constraint that blocked two entries

That last one is good engine design and I would not change it. But none of it is
documented outside a test.

**Fix.** A `tools/late_swap.py` CLI taking `--date` and `--parent-run-id` that
assembles the frame, loads or extends the cached bank, builds requirements, and
runs the swap. One command instead of eight discovery failures.

---

## 7. Housekeeping

- **`scipy` was not installed.** `tools/audit.py` correctly reported
  `scipy.optimize.milp unavailable` and I installed it ad hoc at T-35. Session
  start needs a dependency check (or install) as step zero, before the audit.
- **The audit's test expectation is stale.** CLAUDE.md expects
  `PASS v2.26.0 12 modules 119 tests`; 131 ran, because the uncommitted showdown
  work added twelve. Per the standing rule I proceeded and flagged it, but a gate
  that is expected to fail is a gate nobody reads. Update it to 131.
- **`outputs/<date>/` is not written by the engine.** CLAUDE.md says deliverables
  land there; `run_slate` writes to `runs/<run_id>/final/` and I copied by hand
  both times. Have the engine write both.
- **Export verification is hand-rolled.** I wrote the salary-cap / duplicate /
  slot-eligibility / locked-slot checks inline twice. That belongs in
  `tools/verify_export.py` so it is deterministic and reviewable rather than
  reconstructed under time pressure.
- **Working tree was dirty at session start** (10 modified tracked files plus the
  showdown and contest-library additions) and stayed dirty. Nothing in this session
  touched tracked code.

---

## 8. Recommended order of work

1. **Doubleheader keying + salary-file cross-check on the clock**, with a fixture.
   Correctness, cheap, and it is the one that can cost a slate.
2. **`tools/solver_probe.py`.** Half an hour of work; prevents the entire class of
   thrash and the bad decisions that come out of it.
3. **`time_budget_s` on the bank builders**, returning partial banks with a flag.
4. **`bank_cache.py`**, deduping on the ordered roster tuple.
5. **`tools/late_swap.py`.**
6. **Abbreviation normalization at every boundary; 0/9 fill becomes a blocker.**
7. Dependency preflight, audit test count, `outputs/<date>/`, `verify_export.py`.

Items 1 and 2 are the ones I would not ship another slate without. Item 2 in
particular is what turns this from a recurring fire into a number you read at
session start.

---

## 9. The process change that matters most

Everything above is mechanical except this:

**Measure before working around, and never let a compute limit change the strategy
surface.** I inverted both today. I inferred a bottleneck instead of timing it,
then spent a strategy decision — seven starting pitchers — buying relief for a
problem I had misdiagnosed, and the relief did not even work. The measurement that
would have prevented it took ten seconds when I finally ran it.

Under a hard deadline the instinct is to act. The correct instinct is to spend the
first ten seconds finding out what you are actually up against.
