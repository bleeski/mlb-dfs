# 2026-08-14 BUILD: the floored-bank hint names a remedy that cannot converge, and two already-filed defects recurred

Filed by the BUILD session that ran the 10-game main slate (`1910_10g`, 15
entries, first lock 19:10 ET). Delivered `DKEntries_1910_10g.csv` sha
`8ec6b23d309b`, all three gates PASS, preflight exit 0.

One new engine defect below. The other two items are **recurrences of fragments
already sitting in this inbox from earlier today**, which is the more important
finding: filing them did not change behaviour, because nothing in the
operational path forces the check.

---

## 1. NEW: `budget_floored` prints the right remedy on stderr and the wrong one in the JSON

`resolve_bank_budget` already does its job. On four consecutive invocations it
printed, correctly and in full:

```
BANK BUDGET FLOORED (sliced bank): -1.4s remained of --max-seconds after reserve,
so the 5s engine floor applies. This bank is bounded by a constant, not by the
window you asked for. If the build then refuses, grow the bank (re-run; the build
exits 10 and resumes) or raise --max-seconds -- do not relax portfolio controls
against a bank this size.
```

That message is right about everything, including the thing the session then did
wrong. But the JSON `hint` on the same run said:

> **GROW THE BANK FIRST.** The job list was not exhausted (39 of 3600 jobs
> attempted, 1.1%) ... Its time budget also hit the engine floor, so the slice was
> bounded by a constant. **Re-run the SAME command:** the build exits 10 and
> resumes into the same cache.

The two channels name different primary remedies, and **the JSON is the channel
the operator reads.** A session redirects the build to a log and tails the JSON
tail; stderr scrolls past above it. So the advice that actually reached the
session was "re-run the same command" — which is exactly the action that cannot
converge while the budget is floored.

### Evidence: what re-running the same command actually bought

| run | `--max-seconds` | jobs attempted | candidates | floored | elapsed |
|---|---|---|---|---|---|
| 1 | 14 | 39 / 3600 | 33 | yes | 21.2s |
| 2 | 20 | 40 / 3600 | 34 | yes | 22.0s |
| 3 | 22 | 40 / 3600 | 34 | yes | 18.6s |

Three re-runs bought **one job and one candidate.** The floor is 5.0s and a job
costs roughly that, so a floored slice buys ~1 candidate per invocation forever.
The hint's own arithmetic (1.1% explored) was already sufficient to prove the
re-run loop could not finish, and it still led with the re-run.

Meanwhile the session, reading a 34-candidate bank as a considered set, relaxed
five portfolio controls — the precise action the stderr line forbids — and
shipped a portfolio with 7 unique lineups across 15 entries and one stack at
7/15.

### What a long window did instead

| run | `--max-seconds` | strategy | single lineup | result |
|---|---|---|---|---|
| b5 | 140 | direct | — | named the real constraint |
| b7 | 145 | **direct** | **0.35s** | certified |
| b8 | 145 | **direct** | **0.14s** | certified |

Raising the window moved the build off the sliced path entirely. There was never
a bank problem. There was a budget-arithmetic problem, `remaining - 8.0` going
negative, and the engine said so on a stream nobody reads.

### Ask

- When `budget_floored` is true, make **"raise `--max-seconds`"** the FIRST
  remedy in the JSON `hint`, ahead of the re-run, and state the arithmetic:
  `--max-seconds N` minus staging left `N-8-staging` seconds, so the slice was
  the 5.0s constant. Re-running is the correct advice only when the budget was
  NOT floored.
- Consider refusing outright: if `budget_floored` and `jobs_attempted` grew by
  less than some small N against the previous cached run, the loop is not
  converging and the build should say so rather than invite another slice.
- `skills/generate-lineups/SKILL.md` teaches `--max-seconds 14` and `timeout 33`
  for Cowork. On any slate that takes the sliced path **that guidance guarantees a
  floored bank.** The 45-second ceiling it is built on was not true this session:
  `timeout 155` under a 180s MCP timeout ran fine, twice. SKILL.md should tell the
  operator to measure the ceiling once and prefer a long window, and should stop
  recommending a value that floors the budget by construction.

---

## 2. RECURRENCE: F4 inert — same day, second slate, and here is the mechanism

`2026-08-14_BUILD_adversarial-qa-pass.md` already records F4 inert on slate
`1810_3g` ("F4 computed for 54 hitters but every value is neutral 1.0"). It
happened again tonight on `1910_10g`: `f4_non_neutral: 0`,
`f4_platoon_applied: 0`, of 180 hitters scored. Certified clean both times.

**New here is the root cause, and it is in the paste path.**
`tools/lineups_from_paste.py` does not attach pasted probables. The paste
supplied both probables per game in the documented mlb.com shape, name line then
`LHP 2-3, 3.76 ERA, 65 SO`, and the parser reported, for all 20 sides:

> `DK STARTING WSH: Andrew Alvarez -- the paste left this side's probable unnamed
> and DK's Starting column names him; no handedness, so the platoon view falls back`

The resulting feed carries `"id": null, "hand": ""` for every probable. F4 is
`(opposing-SP xwOBA-against ratio) x (platoon-hand prior)`; a null id fails the
join to `expected_stats_pitching.csv` and an empty hand collapses the prior, so
**both terms go to 1.0 and the hitter side of the slate loses its entire
opposing-pitcher signal.**

Confirmed by repair: patching `id` (MLBAM) and `hand` into the 20 probables and
rebuilding took F4 to **180 non-neutral, 161 platoon applied**, and the primary
stacks moved off Oracle Park (Statcast 2024-26 wOBA 97, **HR 78, second-worst in
MLB**) which had held 4 of 15 primary stacks in the F4-dead build.

### Ask

- Parse the `LHP|RHP <record>, <era> ERA, <k> SO` line following a probable's
  name and attach it, with hand. The paste is the primary source per R32; it
  should not lose to the DK column on a side it actually named.
- When a probable reaches the pool with a null `id` or empty `hand`, raise it as
  a **named pool warning**, not a per-side info line repeated 20 times. It is a
  silent projection degradation and the current wording ("the platoon view falls
  back") reads as routine. F4 neutrality should be loud in the brief: if
  `f4_non_neutral == 0`, say so where the operator reads gates.

---

## 3. RECURRENCE: the fabricated clock, filed this morning, repeated tonight

`2026-08-14_BUILD_fabricated-deadline-countdown.md` describes a session carrying
a decremented mental clock instead of re-measuring, erring monotonically in one
direction. This session did the identical thing hours later: measured 18:26 ET
once at start, then estimated across tool calls, believed it was 18:55 when a
shell `date` said **18:43**, and told Ben "6 minutes to T-5" when there were 27.

**That mis-estimate is the proximate cause of item 1's bad decision.** The
controls were relaxed against a 34-candidate bank because the session believed
the window was gone. It was not; a 145-second build fit comfortably, twice.

The prior fragment already proposes the fix. It has not landed, and one session
filing it did not stop the next from repeating it. Escalating the ask:

- `build_slate.py` should print `T-minus <n> min to first lock` **at the start of
  the run**, not only as `minutes_to_deadline` in the JSON at the end. The number
  exists; it arrives after the decision it should inform.
- SKILL.md rule: never state a time remaining that was not read from a shell in
  the same tool call. An estimate carried across calls is not a measurement.

---

## Smaller items observed, not investigated

- `salary_cross_check: false` appeared in every brief today. SKILL.md says to
  read `note` and `drift_minutes` before explaining it; neither surfaced in the
  summary path. Both sources agreed on 19:10, so it is likely benign, but the
  session could not tell benign from a doubleheader collision without digging.
- `--declare-pitcher` plus a hand-patched `probable_pitcher` makes
  `preflight_upload`'s confirmed-lineup check pass on operator-supplied input.
  The bulk arm was independently confirmed by the beat writer, so the fact is
  right, but the green light is partly self-certified. Worth a distinct preflight
  label so it is not read as independent confirmation.
- Restoring an earlier certified run to the canonical delivered path made
  preflight FAIL with `manifest marks this file superseded by <same path>`.
  Recovery needs a run-scoped filename. The message should name the `run_id` to
  restore from.
- `fangraphs_platoon_lineups.json` at 10.0 days (limit 7) and
  `fangraphs_season_pitching.csv` at 29.1 days (limit 14) were reported as
  warnings and used. The platoon file fabricated the TEX batting order that took
  **19 roster slots across 15 lineups** on a team that never posted. Consider
  naming it in the brief when a past-limit reference feeds a team that then lands
  a primary stack.
