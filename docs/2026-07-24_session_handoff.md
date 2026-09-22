# Session handoff - 2026-07-24

> **SUPERSEDED as a work list (R385, 2026-09-22).** Open work, its order and its status live only in `docs/ROADMAP.md`; entry bodies in `docs/backlog.md`. This file is a historical record.

Written at the end of a long Cowork session so the next one can start cold. Read
`CLAUDE.md` and the ledger Quick Card first as always; this file covers only what
changed tonight and what is still open.

Tree state: clean at `a97d87f`. `python tools/audit.py --run-tests --terse` prints
`PASS  v2.26.0  13 modules  149 tests`.

---

## 1. What happened tonight

Two Classic slates were built and delivered. Both certified; both were uploaded
by Ben manually.

| Slate | Draftgroup | Entries | Delivered file |
|---|---|---|---|
| Main | 10 games, first lock 7:05 PM ET | 9 | `outputs/2026-07-24/DKEntries_mainslate_20260724T2243Z.csv` |
| Night | 4 games, first lock 8:05 PM ET | 16 | `outputs/2026-07-24/DKEntries_lateslate.csv` (also `DKEntries.csv`) |

Then a red-team review of the whole engine (`docs/2026-07-24_red_team_review.md`,
committed tonight) was worked through: verified, accepted or modified item by
item, and the safe subset was implemented.

### Commits

- `78253c4` intake scoping and blockers, build_slate draftgroup preservation,
  feed staleness, verify_classic DK rules, ledger Quick Card fix
- `24e3b55` five new tests covering all of the above
- `adb40eb` audit test-count pin 144 to 149, plus the three docs that quote it
- `de53e66`, `a97d87f` generate-lineups skill updates

---

## 2. Corrections to earlier beliefs (do not relitigate these)

Three things were believed and then disproved tonight. Each is recorded because a
fresh session will otherwise rediscover the wrong version.

**`salary_cross_check: false` is usually benign.** It does not imply a
doubleheader leg collision. The lineups feed covers the whole day while the salary
file defines the draftgroup, so on any partial-day draftgroup the feed's earliest
lock is an earlier game than the slate's and the check disagrees by construction.
The engine resolves it correctly by deferring to the salary file. On 2026-07-24
the feed's first game was COL@MIL at 3:10 PM ET, in neither draftgroup. Read
`note` and `drift_minutes` before explaining a disagreement.

**Red-team item I-3 was misdiagnosed in the review.** Its evidence, "23 of 29
teams matched 0/9 confirmed hitters," is dominated by teams that were never in the
draftgroup at all, because `confirmed_teams` came from the feed with no filter
against the salary file. The review's proposed fix, blocking any team under 5/9,
would have blocked every build permanently. Implemented instead: scope the
reporting to salary-file teams first, then escalate under 5/9 to a blocker, and
key the feed-alignment check on game coverage rather than on how many lineups
have posted, so an early build with zero confirmed teams is not blocked.

**The Cowork sandbox stalls transiently; it does not degrade cumulatively.** An
engine import went from 15s to over 40s and `git status` hung outright, then
recovered on its own within the hour (0.2s import, 2.4s git, suite in 0.028s)
with nothing changed. Retry once before concluding the environment is unusable.
A Defender exclusion for the repo path was added tonight as the likely fix.

---

## 3. Open work, in the order I would take it

### 3.1 E-1, the signal-complete fast path (highest value, start here)

Nothing else in the review matters as much. Production builds currently rank
players on `AvgPointsPerGame x batting-order-slot factor` and nothing else. No
Vegas totals, no park, no weather, no opposing-pitcher quality, no platoon splits,
no xwOBA correction, no ceiling differentiation. The certification spine cannot
tell the difference between that and real signal, which is exactly why every
reliability item from the 07-19 review landed within three days and no modeling
item landed at all.

This is wiring, not research. The enrichments already exist and have zero callers
on the path that builds slates; the odds are already fetched and discarded.

- **I-1**: make `build_slate.py` enrichment-complete. Cache the two Savant
  expected-stats CSVs and the FanGraphs pitching CSV under `data/reference/` with
  a fetched-date stamp plus a `tools/refresh_reference_data.py`; pass them into
  `_assemble_projection_frame`/`run_slate`; compute `f4_by_player_id` from
  `compute_f4_factors(...)`. Degrade to today's behavior with a loud brief warning
  when the reference files are missing or older than 14 days.
- **I-2**: build F1 from Vegas totals per the 07-19 P0-3 spec (implied team
  totals, hitter F1 clipped to 0.85-1.15, pitcher F1 to 0.90-1.10 or 1.0 in v1),
  wire through `run_slate(f1_by_player_id=...)` following the F4 pattern, and have
  `build_slate.py` fetch totals when `THE_ODDS_API_KEY` is present or accept
  `--odds`. Labeled prior, never a claim.
- **F5**: adapt the bundle's per-venue weather to `compute_f5_factor`. The manual
  roof rule stays: an unresolved retractable roof is a checkpoint warning, never
  a guess.

Acceptance: one command produces a brief showing non-neutral F1/F4/F5 counts and
enrichment match rates, with a wiring test per factor. Also delete the
"odds do not change the build" line from the skill once it is false.

Note the enrichment-pattern rule this project already holds itself to: labeled
prior, Notes-tagged, surfaced in the brief, wiring-tested, loud on zero match.

### 3.2 One bank authority (I-4, I-6, I-7, E-5)

Do this after E-1, because it is what lets E-1's signal reach big-slate
portfolios instead of being dropped.

- **I-4**: `bank_cache.as_candidates()` emits only roster/objective, so whenever
  the sliced-bank strategy is chosen the allocator ranks on raw objective with no
  shape score, no correlation bonus, no floor logic. Score cached candidates
  before allocation.
- **I-6**: `enumerate_sp_pairs` includes same-game pairs, which are
  anti-correlated, and feasibility counts them as capacity. Add cross-game
  filtering and update `_slate_feasibility`.
- **I-7**: Phase 1 truncates SP-pair coverage in Player_ID string order under a
  time budget. Order by combined pitcher Ceiling so truncation degrades from the
  weak end.

### 3.3 The evidence loop (needs Ben)

The review's standing rule: the evidence loop outranks the engine. Currently the
archive holds 5 slates against an 8-15 gate for ownership work, and the project
records the field exhaustively and Ben not at all.

- **Standings, immediate.** The five exports in `data/standings/inbox/` for
  contests 191489664, 191513240, 191520890, 191521489, 191542451 are all zero
  bytes. Ben re-pulled them two different ways on 2026-07-24 and they still came
  back empty, so they are most likely aged out server-side and unrecoverable.
  Pending decision: delete them and record the loss in the ledger so future
  sessions stop proposing a re-pull.
- **Test of the aging theory.** Pull standings for the four 2026-07-24 night
  contests (192657350, 192657349, 192667458, 192658268) the morning after. If they
  come back populated, age is confirmed and the rule is a same-night or
  next-morning pull. If they are also empty, the export path itself is the
  problem.
- **Nothing noticed for five days.** That is the real defect. Proposed: a
  contests-awaiting-standings check in the standings scheduled task that reads
  promoted runs, lists every contest ID with no archive entry, reports its age,
  and escalates past 48 hours. Not yet built.
- **E-3**: record Ben's own results (fees, winnings, finish percentile,
  duplication count) via `field_miner`. The project cannot presently answer
  whether it is winning.

### 3.4 Accepted but not yet done

`I-5` six workflow gates hardcoded True on every production build; `I-8` Showdown
same-six-different-captain unreachable; `I-10` allocator cannot distinguish
infeasible from timed out; `I-11` four name normalizers, consolidate to one;
`I-12` dead scoring config including the satellite profile advertising a
floor split it does not apply; `I-16` remainder (Showdown melt warnings,
`_try_accept` swallowing all exceptions, `fetch_lineups` omitting `bat_side`,
repo hygiene: `_scratch_20260722/`, stray root `slate_bundle.json`, bank-cache
residue in `runs/`); `E-7` the deletion pass; `E-8` decide the simulation question
on the record.

Deliberately deferred as lower value than the above: `E-2` ownership v0 (blocked
on the archive count), `E-4` Showdown signal, `E-6` decorrelation number, `E-9`
late-swap leverage, `E-10` generated `ENGINE_STATE.md`.

---

## 4. Environment notes

**Ben's shell is Windows PowerShell 5.1.** `&&` is a parse error there. Give one
command per line, backslash paths, and always open with
`cd C:\Users\benja\Documents\Claude\mlb-dfs`.

**The Cowork sandbox has a 45-second ceiling per bash call**, including container
startup, so budget inner timeouts at 25-33s. Background processes do not survive
between calls and `/tmp` is not shared. Pre-fetch the lineups feed in its own
light call and pass `--lineups ... --no-rotowire` so the build fits. A fresh
sandbox has no scipy; `tools/wheel_fetch.py` fetches wheels resumably. Full
details are in the generate-lineups skill under "Running inside the Cowork
sandbox".

**Do not commit with `git add -A` from a task.** It swept `tools/wheel_fetch.py`
into `78253c4` unintentionally. Scope commits to the files the work touched.

---

## 5. First actions for the next session

1. Confirm `git status` is clean and the audit prints 149 tests.
2. Pull and mine the four night-slate standings exports if they have not been
   done; decide the fate of the five dead ones.
3. Start E-1 with I-1, since it is self-contained and unblocks the rest.
