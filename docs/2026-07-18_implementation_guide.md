# MLB DFS Engine: Implementation Guide (current-state, post cross-reference)

Date: 2026-07-18
Supersedes the operational parts of `mlb-cowork-migration-guide.html` (v1.0, 2026-07-16), which was written before the restructure landed and now overstates what remains.
Companion to the 2026-07-18 strategic brief (`docs/2026-07-18_strategic_brief.md`).

This guide is written to be followed in a fresh chat. It states where the project actually is, what the migration guide got right, what is already done, the three scheduled tasks now live, the data-acquisition method for every recurring source, which procedures to promote to skills, and the recommended build sequence.

---

## 1. Where the project actually is

The migration guide's five phases do not match the repo anymore. Real status:

- **Phase 0 (workspace, restructure, golden gate): DONE and green.** The package restructure is committed (`v3.0.0-pre`), `tools/audit.py` is the ported audit, and `tests/test_golden_replay.py` passes inside the 119-test suite, anchored on the 2026-06-03 slate. One environment fact to remember: a fresh Cowork sandbox has no deps, so `pip install -r requirements.txt --break-system-packages` is required before the audit or any optimizer run. The stdlib-only tasks below do not need it.
- **Phase 1 (live data in place): DONE.** `tools/fetch_slate_bundle.py` and `tools/stage_slate.py` both exist and are verified. A real 2026-07-17 slate was staged and built (two run directories, a promoted `latest_valid_run.json`). The authoritative-source decision is locked: `fetch_slate_bundle.py` is the intake path, not the `mlb-lineups` / `mlb-game-odds` skills, which only reintroduce a shape mismatch.
- **Phase 2 (scheduled tasks): NOW LIVE.** Three tasks created 2026-07-18 (Section 3). This is the work this guide stands up.
- **Phase 3 (Showdown) and Phase 4 (ownership model): not started.** Carried forward in Section 7, re-prioritized.

Housekeeping the next chat should clear: `git status` is currently dirty (modified reference CSVs and `live_data_adapters.py`, an untracked `.gitattributes`). Commit or revert those deliberately outside a live slate so the tasks start from a clean tree.

---

## 2. Cross-reference verdict: keep, drop, add

**Keep from the migration guide.** The Phase 2 task shapes (morning pre-stage, standings watcher, weekly reference), the recurring data map, and the gaps list are all sound and carried below. The standing rule that no automation touches DraftKings is correct and permanent.

**Drop.** Task D (the scheduled T-60 certified build). An unattended build contradicts the review-and-approve doctrine, slates lock at inconsistent times, and a full `approve=True` solve on an unfiltered pool blows the workspace's roughly 45-second single-call ceiling (the O(n squared) SP-pair enumeration). Builds stay interactive. If a scheduled pre-compute is ever wanted, schedule only an `approve=False` checkpoint, which is fast and creates no run directory, never the certified build.

**Add (not in the guide).** Two items from the strategic brief. First, wiring the waterfall (`posture_allocator`) into the `run_slate` checkpoint, which is the highest-certainty build-quality win and needs no new data. Second, the correlation model (un-park `slate_sim`), which the guide omits entirely and which I recommend sequencing ahead of Showdown. Both are in Section 7.

---

## 3. The three scheduled tasks (created 2026-07-18)

All three run locally, in Ben's timezone, only while the Claude app is open; a task due while the app is closed runs on next launch. Each is a fresh session that reads CLAUDE.md first and obeys every guardrail. Jitter offsets the fire times by a few minutes automatically.

| Task ID | Cadence | Does | Method |
| --- | --- | --- | --- |
| `mlb-standings-archive` | daily ~7:03 AM | Drains `data/standings/inbox/`: runs `field_miner`, verifies (ownership recompute within 1.5 pts of %Drafted), appends the ledger, updates the opponent registry, moves files to `data/archive/<date>/`. No-op on an empty inbox. | Local files only, stdlib |
| `mlb-morning-prestage` | daily ~9:09 AM | Runs `fetch_slate_bundle.py` (lineups, DK+FD totals, weather), snapshots odds to `odds_history/`, archives batting orders to `order_history/`, flags roofs/wind, writes `data/slates/<date>/brief.md` with a nag list. Stops on a no-games day. | HTTP APIs, stdlib |
| `mlb-reference-watch` | Monday ~8:36 AM | Freshness watchdog: reports the age of every Savant/FanGraphs/park-factor reference file and writes `data/reference/refresh_watch.md` with an exact manual-refresh checklist. Does not scrape. | Local files only |

**First-run approval.** Tool approvals granted during a run are stored on the task and reused. Click "Run now" once on each task (Scheduled section in the sidebar) to pre-approve the bash, file, and git tools so unattended runs never stall on a permission prompt. Run `mlb-standings-archive` against an empty inbox first; it should report "inbox empty" cleanly. To dry-run the mining path, copy `data/archive/2026-06-03/standings_191020573.csv` into the inbox and diff the mined output against the recorded archive before trusting it live.

**Two known caveats, both handled defensively in the task prompts.** Git writes may fail on this mount (the folder disallows delete/rename, which can break git's lock-then-rename); every task attempts a commit and, on failure, leaves files in place and reports that a manual commit is needed. And the tasks are seasonal: `mlb-morning-prestage` self-stops when the fetcher returns zero games, but in the off-season you should disable all three from the Scheduled panel rather than let them run empty and spend odds credits.

**Odds budget.** One totals pull is about 3 credits on the-odds-api free 500/month plan, so the daily pre-stage spends roughly 90 a month. Comfortable. A second T-60 snapshot (gaps item 3) would add about 90 more, still within budget, but is not scheduled by default.

---

## 4. Method for every recurring source (the Chrome question, answered)

The determination Ben asked for: Chrome is the wrong tool for almost everything here. Every automatable source is a plain HTTP endpoint reachable from the workspace with no login, so the tasks run bash scripts, not a browser. The only login-gated source is DraftKings, which is deliberately never automated. That leaves no routine role for Claude-in-Chrome in this pipeline. Reserve the browser for genuinely interactive, human-supervised one-offs, and never inside a scheduled task.

| Source | Data | Method | Why |
| --- | --- | --- | --- |
| MLB Stats API | lineups, probables, hands, lock times | HTTP via `fetch_slate_bundle.py` | Free, public, no login. Already working. |
| the-odds-api | DK+FD game totals | HTTP via `fetch_slate_bundle.py`, key in `.env` | Public API with a key. Already working. |
| Open-Meteo | per-venue weather | HTTP via `fetch_slate_bundle.py` | Free, public. Already working. |
| Baseball Savant | expected stats CSVs | Manual (weekly), watchdog-nagged | Public CSV export exists; kept manual per Ben. Optional automation in Section 6. |
| FanGraphs | platoon JSON, K%, splits vs hand | Manual, watchdog-nagged | Kept fully manual by decision. May sit behind a membership. |
| DraftKings | salaries, entries, standings, contest pages, entry history | Manual, always | Login-gated; scripted access violates DK terms and is an account and prompt-injection risk. Standing rule. |

Net manual surface per slate, unchanged from the guide's target: download the DKSalaries and DKEntries files, drop the FanGraphs platoon JSON in the slate folder, upload the certified file by hand, and drop standings CSVs plus the contest-page trio in the inbox after the slate.

---

## 5. What to turn into skills

The scheduled tasks already hold the recurring procedures. Skills add on-demand, interactive invocation of the same work (run the pre-stage now, archive tonight's standings now), exactly the way the `datagolf-*` skills back the golf tasks. Create these through the skill-creator flow or Settings, then optionally slim each task's prompt to a one-line "invoke skill X" so the procedure lives in one place.

Recommended, in value order:

1. **`mlb-slate-run`** (interactive only, never scheduled). The nightly build driver: `stage_slate.py --date <date> --checkpoint`, review the checkpoint and Blockers line, then `run_slate(approve=True)` to `outputs/<date>/`. This is the daily driver you run by hand today, and it is the single highest-value skill because it turns the whole per-slate loop into one command. It stays interactive on purpose; the build is never automated.
2. **`mlb-prestage`** (interactive twin of `mlb-morning-prestage`). For when you want the bundle and brief on demand, off the morning schedule.
3. **`mlb-standings-archive`** (interactive twin of the nightly task). For archiving a slate the moment standings are ready rather than waiting for 7 AM.
4. **`mlb-reference-watch`** (optional). Lower value as a skill since it is a passive watchdog; create it only if you want an on-demand freshness check.

Do not create skills for `mlb-lineups` or `mlb-game-odds`; `fetch_slate_bundle.py` supersedes them for this pipeline. Leave `mlb-hr-prop-arb` alone; it is a separate betting tool, not part of the DFS engine.

Note for the session that creates these: I cannot create skills from inside this chat (skill files here are a read-only cache). Create them via the skill-creator skill or Settings, Capabilities.

---

## 6. Remaining setup items

Short, mostly verification.

1. **Pre-approve the three tasks.** "Run now" on each once (Section 3).
2. **Commit the dirty tree** outside a live slate so the tasks start clean.
3. **Confirm git-commit works from inside Cowork.** If a task reports commit failures, plan to commit task outputs manually, or run the tasks and commit from a regular terminal on a cadence. This is the one unresolved environment risk.
4. **Optional: automate the Savant refresh.** Savant expected-stats CSVs are a public export, so a small `tools/fetch_savant_expected.py` (batting and pitching, min PA 25, preserve the BOM) could turn the reference watchdog into an auto-pull for the Savant half while FanGraphs stays manual. Build and verify it interactively first, then have `mlb-reference-watch` call it. Low priority; the watchdog nag already prevents silent staleness.
5. **Create the skills** in Section 5 when you want interactive invocation.

---

## 7. Recommended build sequence (Ben delegated this)

The migration guide sequences Showdown (Phase 3) before the ownership model (Phase 4) and omits correlation. I recommend a different order. The reasoning is the strategic brief's core point: the binding constraint is graded evidence, and the archive fills passively now that the tasks are live, so active build effort should go where it compounds the Classic edge and needs the least new data.

**Now, live and passive.** The three tasks plus the interactive `mlb-slate-run` loop. The archive accumulates toward the ownership gate with no further work.

**Build step 1: wire the waterfall into the checkpoint.** Promote `posture_allocator` from a side report into a first-class `run_slate` checkpoint block, and point `build_diverse_candidate_bank` at tier-specific coverage targets (Apex demands SP-pair spread and a duplication screen; Floor tolerates a shared chalk core; Volume follows the concentration rule). Highest certainty, no new data, changes surface not certified logic. This is the best single build-quality win available.

**Build step 2: the correlation model, ahead of Showdown.** Un-park `slate_sim` and fit its marginals against realized FPTS, starting with pairwise batting-order adjacency, the mechanism through which MLB ceiling is actually produced. Its data gate is soft (baseball structure, not standings volume), it feeds the Apex objective the waterfall just wired, and it compounds the Classic archive rather than splitting it. This is why it precedes Showdown.

**Build step 3: fit the ownership model, at 8 to 15 archived Classic slates.** The guide's Phase 4, reached in weeks by the archive tasks, not months. Join actual %Drafted through the `build_dk_keyed_corrections` crosswalk, grade with `ownership_prior.grade_against_actuals`, condition on archetype and field size, never pool. Only here does calibrated leverage become real, and only here does the language of edge become defensible. Predictions stay labeled priors that nothing auto-applies.

**Opportunistic: Showdown.** Do it when you want single-game contest variety, not as a critical-path item. It starts a new archetype series from zero, which splits thin data across two contest types and slows both ownership gates, and it does not compound the core Classic edge. The build itself is well specified (Appendix), so it is a clean drop-in whenever you choose.

---

## Appendix: carried build prompts (Showdown and ownership)

These are the migration guide's Phase 3 and Phase 4 prompts, preserved so a new chat is self-sufficient. Priority is per Section 7, not the guide's original order.

### Roster contract refactor (prerequisite for Showdown)

```
Read CLAUDE.md first. Test-first refactor: extract a RosterContract.
Define mlb_engine/optimize/roster_contracts.py with a contract carrying slot
definitions, per-slot eligibility, the salary rule, roster size, the player
uniqueness rule, team-representation constraints, per-slot scoring multipliers,
and the DKEntries export header. Express current Classic rules as CLASSIC and
make optimizer_v3, contest_allocator, and dk_entries_manager consume the
contract instead of hard-coded Classic assumptions.
Acceptance: full suite green, test_golden_replay passes unchanged, no Classic
behavior differs. Commit as "v3.0.0: roster contracts".
```

### Showdown implementation

```
Read CLAUDE.md first. Implement the SHOWDOWN contract, test-first, using the
fixture salary CSV and DKEntries template in tests/fixtures/showdown/.
Rules: rosters are 1 CPT plus 5 UTIL. CPT scores 1.5x and uses the CPT row's
own salary and draftable ID. A player never fills CPT and UTIL in the same
lineup. At least one player from each team. Salary cap 50000. Scoring is
identical to Classic, so projections transfer untouched.
Build: (1) an intake melt to player grain with role-specific salary and ID;
(2) the MILP variant with per-role binaries (CPT picks sum to 1, UTIL to 5,
per-player role exclusivity, both-teams constraint, role salaries in the cap);
(3) a dk_entries template mode keyed off the CPT/UTILx5 header; (4) postures
showdown_gpp, showdown_wta, showdown_single_entry, decorrelation as CPT rotation
and team-split templates (5-1, 4-2, SP-anchored); (5) a showdown golden test
certifying a build end to end. F5 applies as a slate-level tilt, not a player
differentiator, on a one-game slate. Run the duplication-risk screen on every
showdown checkpoint; it stays a structural review proxy.
```

### Ownership model fit (at the sample floor)

```
Read CLAUDE.md and the full ledger first. The Classic archive has reached the
sample floor. Fit the ownership model. Join actual %Drafted from every archived
contest to its slate salary file through the build_dk_keyed_corrections
crosswalk. Features per ownership_prior.py: salary, implied totals, batting
order, probable-SP status, and value, conditioned on contest archetype and
field size, never pooled. Grade with ownership_prior.grade_against_actuals per
archived slate: MAE, signed error, Spearman, and largest misses into the ledger.
The model graduates into mlb_engine/field/ once it emits a per-slate prediction
the next slate can grade. Predictions are labeled priors and review inputs;
nothing auto-applies to projections, candidate selection, or the optimizer.
```

---

## Quick reference: the loop once this is running

Daily in season: the 7 AM archive task drains any standings you dropped overnight, the 9 AM pre-stage writes `brief.md`. You download DKSalaries and DKEntries, drop the FanGraphs platoon JSON, run `mlb-slate-run` (or `stage_slate.py --checkpoint` then `run_slate(approve=True)`), review, upload by hand, and drop standings plus the contest-page trio in the inbox. Monday the watchdog tells you which reference files to refresh. Everything else is automated or deliberately manual.
