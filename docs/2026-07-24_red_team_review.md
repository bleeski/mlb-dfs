# Red Team Review — MLB DFS Engine — 2026-07-24

Basis: full read of CLAUDE.md, MLB_Classic.md, the calibration ledger, the 07-19 red-team review and response, the 07-22 postmortem, the backlog, all engine modules, tools, skills, tests, and production artifacts (outputs/, runs/, data/). Independently verified: `tools/audit.py` passes and the full suite runs green (144 core + 13 golden/showdown tests, scipy 1.15.3) on a clean copy. Every claim below was checked against code or production output at commit fb21235 (tree clean). Line numbers reference that tree.

Goal alignment: the mandate is winning DraftKings lineups across a portfolio of contests, quickly and efficiently, without spending effort on marginal items. This review is ranked accordingly: items that change what lineups get built outrank items that change how cleanly they get built.

## How to use this file

Each item has a stable ID, priority, evidence, rationale, fix, and acceptance criteria. P0 = changes what gets built, do first. P1 = correctness that can cost a slate or corrupt evidence. P2 = real but deferable. E-n = enhancements ranked by expected benefit per unit effort (S/M/L). Items are independently actionable unless a dependency is named.

## Ground rules (unchanged from 07-19, still binding)

- GR-1: The certification spine is untouchable. Route around it, never through it.
- GR-2: The DraftKings wall is absolute. No scripted DK access, no uploads, no money automation.
- GR-3: `scipy.optimize.milp` only. No LLM in the certified build path.
- GR-4: Truthful labels stay. New inputs are labeled priors, never ROI/win-rate/probability claims.
- GR-5: Golden replays are regenerated deliberately with a stated reason, never silently.
- GR-6: Never print, log, or commit `.env` or `THE_ODDS_API_KEY`.

---

## Section 0: The headline finding

**The engine certifies beautifully and projects poorly, and the work keeps flowing to the certifier.**

The 07-19 review was accepted nearly in full. Cross-checking it against today's tree, the pattern is stark:

| Class of accepted item | Status on 07-24 |
|---|---|
| Reliability/infra (doubleheader keying, solver probe, time budgets, bank cache, late-swap CLI, verify_export, team-code normalization, dependency preflight, outputs mirror) | **All landed**, within 3 days, tested |
| Modeling/edge (F1 from Vegas totals "the highest-value item on the list", F5 weather, ownership v0, scenario families, correlation proxy, floor/ceiling bands, dup screen wiring, own-results P&L) | **None landed** |
| Honesty/cleanup (gate stamps, normalizer consolidation, dead config, DU deletion, legacy sizing, doc reconciliation) | **Almost none landed** (normalizers went 3 → 4) |

The reason is structural, not lazy: infra failures bite loudly during a live build, so they get fixed; projection quality failures never bite during a build, because the build certifies either way. A certified file built on season-average points is indistinguishable, at certification time, from a certified file built on real signal. The only place projection quality ever shows up is contest results, and the results loop (Ben's P&L, graded projections) is exactly the part that was never built.

Consequence, concretely, as of the current production path: **lineups are built from `AvgPointsPerGame × batting-order-slot factor` and nothing else.** No Vegas totals, no park, no weather, no opposing-pitcher quality, no platoon splits, no xwOBA correction, no ceiling differentiation. Section 1 items I-1 through I-3 document this precisely. Everything else in this file matters less than closing that gap.

---

## Section 1: Issues / bugs

### I-1 (P0). The production fast path bypasses the entire projection enrichment stack

- **Evidence:** `skills/generate-lineups/scripts/build_slate.py:269-272` assembles the frame with `savant_batting_csv=None, savant_pitching_csv=None`, no `f4_by_player_id`, no `fangraphs_pitching_csv`; its `run_slate` call at :326-337 splats `pool["run_slate_kwargs"]`, which (`live_data_adapters.py:719-725`) carries only `projection_rows`, `confirmed_*`, `pitcher_roles`, and the platoon map. `build_slate_pool` returns `opposing_probables` and `batter_hands` as building blocks, but nothing computes or passes an F4 map. The Quick Card documents the enrichments as "one call each through run_slate"; no production caller makes those calls.
- **Why it matters:** v2.23.0 and v2.24.0 shipped the xwOBA Base correction, xISO hitter ceilings, K-rate pitcher ceilings, and deterministic F4 specifically because AvgPointsPerGame is a contaminated base and uniform ceilings make the GPP objective rank-identical to mean-maximization. All four enrichments have zero callers on the path that actually builds slates. The engine's "ceiling" target is currently an APPG ranking wearing a ceiling costume.
- **Fix:** make `build_slate.py` enrichment-complete by default. (a) Cache the two Savant expected-stats CSVs and the FanGraphs pitching CSV in `data/reference/` with a fetched-date stamp and a `tools/refresh_reference_data.py` that pulls them (Savant and FanGraphs are freely exportable; weekly refresh is plenty for season-long rates). (b) In `run_classic`, when the cached files exist and are < 14 days old, pass them into `_assemble_projection_frame`/`run_slate` and compute `f4_by_player_id = compute_f4_factors(pool["team_by_player_id"], pool["opposing_probables"], savant_pitching_table, pool["batter_hands"])`. (c) Surface `projection_enrichment` match rates in the brief. Stale/missing reference files degrade to today's behavior with a loud brief warning.
- **Acceptance:** a build_slate.py run on a real slate shows non-neutral xwOBA/ceiling/F4 counts in `build_brief.json`; a wiring test drives the script path (not just run_slate) and asserts enrichment reaches the frame; brief warns when reference data is stale.

### I-2 (P0). F1 is still 1.0 everywhere; Vegas totals remain fetched-and-discarded (accepted 07-19, open)

- **Evidence:** no `odds_packet` parameter reaches any factor: `grep -rn odds_packet mlb_engine/` returns nothing outside adapters/tools. `tools/stage_slate.py:240-242` still ships the "not a run_slate input in the current engine … rides alongside the kwargs" comment. `skills/generate-lineups/SKILL.md:72-75` institutionalizes it: "Odds do not change the build; they give you the game environment to describe in the brief."
- **Why it matters:** game environment is the strongest exogenous signal in MLB DFS and the market prices it for you. The engine prices an 11.5-total Coors game and a 7-total pitcher's park identically. This was called the highest-value item on 07-19 and accepted "strongly"; five days and six slates later the skill documents the gap as intended behavior.
- **Fix:** exactly the 07-19 P0-3 spec. `projection_builder.build_f1_factors(odds_packet, team_by_player_id, opposing_probables)`: implied team totals (total split by moneyline via the existing implied-probability helpers; total/2 when absent), hitter F1 = clip(team_total / league_mean_team_total, 0.85, 1.15); pitcher F1 = clip(inverse vs opposing team total, 0.90, 1.10) or 1.0 in v1. Wire through `run_slate(f1_by_player_id=...)` following the F4 pattern (applied only where no explicit F1, Notes-tagged, `projection_enrichment["f1"]`, zero-match raises). Then have `build_slate.py` fetch totals when `THE_ODDS_API_KEY` is present (one featured-markets call ≈ 3 credits) or accept `--odds`, and pass the packet. Labeled prior, never a claim.
- **Acceptance:** wiring test proves a synthetic 11-total game's hitters carry F1 > a 7-total game's; next production frame shows non-neutral F1; brief reports the totals used.

### I-3 (P0). Pool-integrity failures ship as warnings: 23 of 29 teams matched 0/9 confirmed hitters and the build still certified

- **Evidence:** `outputs/2026-07-22/build_brief.json`: status "certified", `blockers: []`, warnings list "ARI: confirmed lineup matched 0/9 salary hitters" ×23 teams, plus `salary_cross_check: false` on the slate clock. `live_data_adapters.py:628` emits the n/9 line as a warning regardless of n, including 0. The 07-19 review (P1-6) required escalating unmatched confirmed hitters to Blockers after the accent bug dropped 4 starters; the fix never landed and the failure recurred at 23-team scale.
- **Why it matters:** a team whose posted lineup matches zero salary rows builds on a projected/APPG order while real information exists, or signals the feed and the draftgroup are misaligned entirely (the `runs/bank_cache_2026-07-22.STALE_OTHER_DRAFTGROUP*.json` residue says the session fought exactly that). "Certified" measures export legality, not input integrity, but the operator reads the headline. This is the project's own no-op failure class (ledger 3.6) at intake.
- **Fix:** three parts. (a) In `build_slate_pool`, a confirmed team matching < 5/9 becomes a blocker naming the team and match count; 5-8/9 stays a warning. (b) Add a feed-alignment gate: if fewer than half the salary file's teams receive any feed coverage, or `slate_clock.salary_cross_check` disagrees, emit a blocker ("feed does not match this draftgroup; refetch with --lineups"), not a warning. (c) `build_slate.py` must refuse to reuse a disk-cached `lineups_feed.json` older than N minutes (default 90) without printing that it did so — see I-9.
- **Acceptance:** replaying the 07-22 inputs produces blockers, not a certified headline; a fixture test covers 0/9-confirmed-team → blocker and feed/draftgroup mismatch → blocker.

### I-4 (P0). The sliced-bank path silently discards all contest-shape and duplication scoring

- **Evidence:** `bank_cache.as_candidates()` (bank_cache.py:159-171) emits only `roster_slot_ids/player_ids/objective`. `contest_allocator._candidate_shape_score` (:393-418) falls back to `objective` when `contest_fit_by_shape`/`contest_fit` are absent; right-tail tier defaults to Stable (+0.0); the cash branch reads `floor_sum` = 0.0. So whenever `build_slate.py` chooses `strategy="sliced_bank"` (any big slate under the 43 s ceiling), the allocator ranks candidates purely by raw objective: no stack-correlation bonus, no batting-order-cluster bonus, no salary-uniqueness/field-pressure adjustment, no cash/floor logic.
- **Why it matters:** the big slates where the sliced path activates are exactly the slates where shape scoring matters most. Two parallel candidate-generation subsystems now exist (`build_diverse_candidate_bank` and `bank_cache.extend_bank`) with different dedup keys, different pair orderings, and different scoring downstream — the same two-authorities smell OH-2 flagged for bank sizing, now at subsystem scale.
- **Fix:** score cached candidates before allocation. Cheapest correct version: in `run_slate`'s `candidates_override` path (or in `build_slate.py` before the call), reconstruct a lineup frame per candidate from the projections and run `score_lineup_candidate` per requested shape, attaching `contest_fit`/`contest_fit_by_shape`/`floor_sum`. Longer term, fold `extend_bank` into `build_diverse_candidate_bank` behind one interface (one dedup key: ordered roster; one pair ordering: strength-ranked; one budget mechanism) so a candidate is a candidate regardless of which loop produced it.
- **Acceptance:** on a sliced-path build, assignments show non-degenerate shape scores (cash entries prefer higher-floor candidates; test asserts a cached candidate's contest_fit is populated); one candidate-generation authority remains, or the two share dedup/ordering/scoring by construction.

### I-5 (P1). Six workflow gates are hardcoded True on every production build (accepted 07-19 as P1-4, open)

- **Evidence:** `execution_pipeline.py:2233-2240`: `salary/entry_grid/lineup/pitcher_audit/weather/odds` gates all default True, labeled `caller_asserted`, flowing into the certification payload. No production caller supplies `workflow_gates` (only tests do); `build_slate.py` passes nothing.
- **Why it matters:** every promoted run's permanent record asserts checks that never ran. This is the certification spine lying about its inputs — the exact silent-failure class the project prosecutes elsewhere.
- **Fix:** as accepted on 07-19: derive `odds_gate_passed` from packet coverage when supplied, `weather_gate_passed` from roof/wind resolution when supplied, and record `"not_supplied"` (never bare True) when absent; surface not-supplied gates on the checkpoint Blockers/warnings line. Salary and entry-grid gates can be derived cheaply from work run_slate already does (schema validation, reserved-row parse) instead of asserted.
- **Acceptance:** diagnostics for a packet-less build show `not_supplied`; a test covers both derivations; no gate defaults to True without a computation behind it.

### I-6 (P1). Same-game SP pairs are counted as capacity and force-covered in the bank

- **Evidence:** `optimizer_v3.enumerate_sp_pairs` (:1058-1066) enumerates all 2-combinations; `_slate_feasibility` (execution_pipeline.py:1370-1372) counts them as `viable_sp_pairs`; `build_diverse_candidate_bank` Phase 1 (:3281-3294) forces one lineup per enumerated pair. `bank_cache.extend_bank` (:249-251) deliberately excludes same-game pairs ("two starters in the same game cannot both be right").
- **Why it matters:** on a 14-game slate ~14 of the pairs are opposing starters — negatively correlated at the win/quality-start level. Phase 1 spends budgeted solves manufacturing candidates around anti-correlated SP pairs, and the feasibility floors are derived from a capacity number that includes them, understating the true repetition floor on thin slates (the exact failure family 3.3 exists to prevent).
- **Fix:** add `cross_game_only=True` to `enumerate_sp_pairs` (or filter at the two call sites) using `Game_ID`; keep an opt-in for deliberate same-game pairs. Update `_slate_feasibility` to count cross-game pairs.
- **Acceptance:** feasibility inputs on a fixture slate report cross-game pair count; Phase 1 attempts contain no same-game pair; existing thin-slate tests updated.

### I-7 (P1). Bank coverage under a time budget is truncated in Player_ID-string order, not strength order

- **Evidence:** `enumerate_sp_pairs` sorts by string ID; `build_diverse_candidate_bank` Phase 1 iterates that order and stops on budget exhaustion (:3281-3294). `bank_cache.extend_bank` ranks SPs by Ceiling first (:226-258). The production run_slate path uses the former.
- **Why it matters:** under the 43 s sandbox ceiling, a big-slate bank covers an alphabetical-ID prefix of SP pairs and may never touch the two best arms' pairings. Budget truncation should degrade toward the strongest pairs, not arbitrary ones.
- **Fix:** order Phase 1/Phase 2 pairs by combined pitcher Ceiling descending (reuse the bank_cache ranking); document that budget exhaustion truncates from the weak end.
- **Acceptance:** test: with a tight budget, the covered pairs are the top-ceiling ones; augmentation report lists coverage order basis.

### I-8 (P1). Showdown: same-six-different-captain lineups are still structurally unreachable (P2-10 half-done)

- **Evidence:** `showdown.py` bank forbids the exact 6-player set via `forbidden_sets` (:218-222: selection sum ≤ 5 over those six players regardless of role), so a CPT rotation over the same core is infeasible by construction. The 07-23 fix added a captain exposure cap (:38, :272-318), which forces different captains only by forcing different six-sets.
- **Why it matters:** captain choice is the primary leverage lever in Showdown; DK treats same-six-different-CPT as distinct lineups, and rotating CPT across a strong core is a standard construction the bank cannot produce. The exposure cap treats the symptom (24/24 same captain) while the dedup signature still forbids the cure.
- **Fix:** as accepted on 07-19: forbid on `(sorted 6-set, cpt_id)` — encode by adding the CPT variable of the prior captain to the forbidden constraint (six selection vars ≤ 5 OR captain differs: add `cpt(prior_cpt_idx)` with coefficient 1 and bound the sum over {6 players + prior captain-role var} ≤ 6). Keep the exposure cap on top.
- **Acceptance:** bank on a fixture produces same-core CPT rotations; certifier and `write_showdown_entries` treat them as distinct; the 24/24 regression fixture still passes with the cap.

### I-9 (P1). `build_slate.py` prefers a stale disk feed over a fresh fetch, silently

- **Evidence:** :623-630: if `data/slates/<date>/lineups_feed.json` exists it is loaded with no staleness check; the file carries `fetched_at` and it is never read. The 07-22 slate directory's `lineups_feed.json.bak_pre_confirm` residue and the 23×0/9 brief are what this looks like in production.
- **Why it matters:** lineups confirm continuously through the afternoon. A morning feed on disk quietly beats a fresh fetch, downgrading confirmed teams to projected orders at exactly the moment fresher information exists. The skill says "fresher lineups matter most" and the script disagrees.
- **Fix:** if the cached feed's `fetched_at` is older than `--feed-max-age-minutes` (default 90), refetch; on refetch failure fall back to the stale file with a brief warning naming its age. Always print which feed (path + age) was used.
- **Acceptance:** test with a stale fixture feed asserts refetch attempt and the brief's feed-age field; the brief always names feed age.

### I-10 (P1). Allocator: infeasible and timed-out are indistinguishable, and the pairwise-overlap model is O(K²) at K up to 240

- **Evidence:** `select_and_assign_entries` returns the single string "entry-level joint MILP infeasible or timed out" (:1494) without reading `result.status` (HiGHS distinguishes infeasible from limit-hit). With `max_shared_players` set, :1462-1465 scans all K² pairs and adds a constraint row per violating pair; `build_slate.py`'s sliced path feeds up to `max(n*12, 60)` candidates and run_slate's direct path up to 150, under a 30 s default `time_limit`.
- **Why it matters:** on big slates the failure mode is a timeout that reads as infeasibility, sending the operator to loosen caps (wrong fix) instead of extending time or shrinking K (right fix). The 07-19 P1-8 diagnosis fix was accepted and is still absent at this layer.
- **Fix:** (a) branch on `result.status`: report "time limit reached at gap X" vs "proven infeasible", and on infeasibility rerun the cheap structural checks (`_slate_feasibility` logic) inside the allocator to name the binding constraint. (b) Prefilter candidates before the pairwise loop: cap K at ~6× entries by shape score, keeping forced SP-pair coverage representatives.
- **Acceptance:** a deliberately infeasible fixture names the binding constraint; a deliberately time-limited fixture reports the limit; allocator wall time on a 240-candidate fixture drops measurably.

### I-11 (P1). Four name normalizers now exist; consolidation was accepted when there were three

- **Evidence:** `slate_intake_manager.normalize_name` (:118), `xwoba_base_correction._norm_name` (:52), `field_miner.normalize_name` (:99), and new `contest_library.normalize_name` (:71). The suffix and accent behaviors differ across them (the "v" suffix issue documented 07-19 persists in `_norm_name`).
- **Why it matters:** every crosswalk in the project is a name join; divergent normalizers mean two subsystems can disagree about the same player. The 07-22 intake failure is at minimum adjacent to this class.
- **Fix:** one `mlb_engine/common/names.py:normalize_name` (NFKD + combining-mark strip; suffix set jr/sr/ii/iii/iv, position-anchored; documented "v" exclusion); all four call sites import it; keep `contest_library`'s contest-name normalizer separate and named `normalize_contest_name` since its domain is different.
- **Acceptance:** grep shows one player-name normalizer definition; tests cover Hernández/Giménez, "Jr.", a trailing "V", and a two-hit ambiguity.

### I-12 (P2). Dead and contradictory scoring config still advertises differentiation the math does not perform (P2-12 open, plus one new case)

- **Evidence:** `leverage_bonus_weight` and `right_tail_weight` defined in every profile (optimizer_v3.py:2163-2236), read nowhere; `right_tail_bonus` computed and returned (:2819) but never added to `contest_fit`; non-cash shapes take `projection_component = ceiling` (:2778-2781), ignoring their advertised ceiling/floor splits — including the `satellite` profile whose `mode_family='ticket_line'` silently gets pure ceiling despite advertising 0.58/0.42. `_default_candidate_bank_target` (contest_allocator.py:947-955) still carries the superseded `min(40, 1.5×)` sizing plus a `runtime == "chatgpt"` relic (:1023). DU machinery (~500 lines) still ships dead in the production path; `reuse_penalty` still mildly rewards concentration (:1386-1388).
- **Why it matters:** every future tuning session (human or agent) reads these knobs as live. The satellite case is worse than dead config: satellites are a real, recurring contest type here (ledger 3.4), and their advertised floor-weighting silently doesn't exist.
- **Fix:** delete `leverage_bonus_weight`/`right_tail_weight` or consume them (consuming right_tail is one line: `contest_fit += profile['right_tail_weight'] * right_tail['right_tail_bonus']` — decide, don't straddle); make `ticket_line` take the cash-style weighted component or relabel it honestly; delete `_default_candidate_bank_target`, the chatgpt runtime branch, the legacy allocator, and the DU paths (OH-1/OH-2 as accepted); remove the reuse-penalty objective coefficient (OH-3). Add the key-consumption test from P2-12.
- **Acceptance:** every profile key is consumed or gone; a test enumerates profile keys and asserts consumption; grep for `du_` and `chatgpt` is clean outside git history.

### I-13 (P2). `build_brief.json` collides across contest types on the same date

- **Evidence:** both builders write `outputs/<date>/build_brief.json` (build_slate.py:640-643). `outputs/2026-07-23/` holds Classic and Showdown deliverables but only the Showdown brief exists; on any same-date double build the second brief overwrites the first.
- **Why it matters:** the brief is the per-slate record of gates, pool basis, and exposure; losing the Classic one on any Classic+Showdown day deletes evidence the post-slate loop needs. The staged-inputs collision was fixed for salaries/entries on 07-23; the brief was missed.
- **Fix:** `build_brief{suffix}.json` using the same `_showdown` suffix rule as staged inputs.
- **Acceptance:** a Classic + Showdown same-date sequence leaves both briefs on disk.

### I-14 (P2). The ledger Quick Card — the mandated session-start read — cannot be executed

- **Evidence:** ledger §0 line 1 still instructs `cp -r /mnt/project/* … && python project_audit.py --run-tests --terse` → `PASS v2.26.0 24 files 119 tests`. The repo has no `project_audit.py`; the audit is `tools/audit.py`; the count is 144; `/mnt/project` is the dead claude.ai mount. CLAUDE.md gives the correct command two files away.
- **Why it matters:** every session is instructed to read this first; its first instruction is wrong in four ways. Doc claims are audit surface (ledger 3.6's own lesson), and this one costs a confused model-minute at the top of every scheduled run.
- **Fix:** rewrite Quick Card items 1 and 7 to the v3.0.0-pre layout (`python tools/audit.py --run-tests --terse` → `PASS v2.26.0 13 modules 144 tests`); while in there, fix the 3.7 invariant text vs field_miner v0.4 drift the 07-22 session flagged (structural gate hard, DK-table agreement advisory).
- **Acceptance:** Quick Card commands run verbatim from the repo root; 3.7 wording matches field_miner v0.4 behavior.

### I-15 (P2). Standings inbox: the five zero-byte CSVs from 07-19 are still there and still zero bytes

- **Evidence:** `data/standings/inbox/` holds five 0-byte `contest-standings-*.csv` (191489664, 191513240, 191520890, 191521489, 191542451), flagged for re-download in the 07-19 response. Ledger archive holds A-001..A-005 (5 slates); the ownership-model gate is 8-15.
- **Why it matters:** the ownership model is the single gating dependency for the entire field/leverage layer (ledger §5), and five contests' evidence has been sitting corrupt for five days. The archetype "trio" (entry fee, payout, cash line) is also listed as a gap on A-002/A-003.
- **Fix:** this is a Ben action, not an engine action: re-pull the five exports (the miner can emit the exact `exportfullstandingscsv/<id>` URLs), drop them in the inbox, let the scheduled task mine them; capture the trio for A-002/A-003 while there. Add a zero-byte check to the scheduled task's report so corrupt downloads are named every run until replaced.
- **Acceptance:** inbox empty except .gitkeep; archive count and per-archetype conditioning stated in the ledger; scheduled-task output names any zero-byte file.

### I-16 (P2). Small correctness edges, batched

- **Showdown melt:** a team absent from its own `Game Info` matchup silently gets `opponent = away` (showdown.py:97-98); make the mismatch a warning row. Locks/cpt_lock/cpt_excludes referencing unknown keys are silently ignored (:209-217) — a silently dropped lock is fail-open; raise or report.
- **`_try_accept` swallows all exceptions** as infeasibility (optimizer_v3.py:3230-3233); a schema error mid-augmentation reads as "no lineup". Catch the solver's expected exceptions narrowly, re-raise the rest.
- **Every augmented candidate is forced to carry a 4-5 stack** (:3228): cash-shape banks inherit GPP construction. Acceptable if intended; document it in the augmentation note, or relax stack_min for cash-dominant slates.
- **`fetch_lineups` fallback omits `bat_side`** (build_slate.py:132), so the F4 platoon component is structurally dead on the fallback path even after I-1; include the hydrate fields or note the degradation in the brief.
- **`verify_classic` omits DK legality rules** the engine checks elsewhere: max 5 hitters/team and min 2 games (build_slate.py:219-249). It is the last independent look at the file; add both (cheap, pure-CSV).
- **Repo hygiene:** `_scratch_20260722/` (18 dead scripts) and the stray root `slate_bundle.json` are gitignored but still on disk feeding every future session's directory listings; delete them. `runs/bank_cache_2026-07-22*.json` manual-rename residue predates pool-signature keying; delete.

---

## Section 2: Ideas / features / enhancements

Ranked by expected benefit per unit effort, with the mandate (winning lineups, fast, no marginal work) as the yardstick. E-1 through E-4 are the ones that change outcomes; the rest are compounding efficiency.

### E-1 (effort M, benefit highest). Ship the "signal-complete fast path": I-1 + I-2 + weather F5 as one workstream

- **Rationale:** the three inputs that most move MLB DFS lineups — Vegas team totals, park/weather, opposing-pitcher/platoon context — are all either already fetched (odds, weather via `fetch_slate_bundle`; probables/hands via the pool) or freely cacheable (Savant/FanGraphs CSVs). The enrichment pattern (labeled prior, Notes-tagged, zero-match raises, enrichment report) is proven. This is wiring, not research.
- **Sketch:** I-1 fix + I-2 fix + an `f5_by_player_id` adapter from the bundle's per-venue weather to the existing `compute_f5_factor` (wind vs `team_to_venue.csv` thresholds; the manual roof rule stays: unresolved retractable roof = checkpoint warning, never guessed; postponement risk maps to the existing game-exposure-cap control). `build_slate.py` grows `--bundle` (or fetches totals/weather itself when keys exist) and passes everything.
- **Payoff test:** after this lands, a Coors game on the slate visibly reshapes stacks and pitcher avoidance in the delivered portfolio with zero manual steps. That is the first slate where the engine's output differs from "APPG sorted by batting order."
- **Acceptance:** one command produces a brief showing non-neutral F1/F4/F5 counts and enrichment match rates; wiring tests per factor; SKILL.md's "odds do not change the build" line deleted.

### E-2 (effort M, benefit high). Ownership v0 + wake up the duplication layer (IMP-1, unblocked at ~8 slates)

- **Rationale:** `_ownership_pct_for_row` already prefers a `Projected_Ownership_Pct` column (optimizer_v3.py:2284-2289); today every row is Mid=12.0, so the field-pressure term is a constant and the entire anti-dup apparatus reduces to "avoid the meta lineup and leave $800 on the table." The archive is at 5 slates with 5 more sitting as zero-byte re-pulls (I-15). The moment a graded model beats flat-12, the existing scoring machinery activates with zero engine changes.
- **Sketch:** per ledger §5: features = salary percentile, value (APPG/$), batting-order slot, probable-SP flag, team implied total (exists after E-1), archetype + field-size band; target = archived `%Drafted`; start linear/isotonic; grade every slate with `ownership_prior.grade_against_actuals` into the ledger; promote to a per-slate column only after beating the flat baseline across the gate count. Then wire `field_miner.score_duplication_risk` (currently selftest-only) into the Tier A checkpoint (IMP-6).
- **Acceptance:** per-slate graded MAE/Spearman in the ledger; a stated go/no-go vs flat-12; production frames carry the column once promoted; Tier A checkpoints show the dup screen.

### E-3 (effort S, benefit high). Record Ben's own results: fees, winnings, finish percentile (IMP-4/IMP-11, still unbuilt)

- **Rationale:** the archive captures the field exhaustively and Ben not at all. The project cannot currently answer "are we winning" — the one question the mandate asks. This is bookkeeping, fully compatible with truthful labels, and it is the input to the scale/keep-building/freeze decision (IMP-11) that should be scheduled, not drifted into.
- **Sketch:** field_miner already parses every entrant row; add `--own-entry-names` (or read Ben's entry IDs from the promoted run's assignments) and emit a per-contest block: fees, winnings, finish percentile, duplication count of Ben's lineups. Append a cumulative table at the top of the ledger archive. Backfill A-001..A-005 where his entries are identifiable.
- **Acceptance:** every archived slate carries the section; one cumulative line answers net-to-date; a dated review entry exists after 15 graded slates.

### E-4 (effort M, benefit high for Showdown). Give Showdown the same signal Classic gets, plus construction templates

- **Rationale:** Showdown builds run on raw `AvgPointsPerGame` with zero context (showdown.py:6-8 admits it; the 07-23 production build shipped on it). Single-game contests are decided by captain leverage and game script; season averages know neither. Showdown is also where the engine has real recurring volume now (8 entries on 07-23).
- **Sketch:** (a) reuse the Classic enrichment stack: melt → join xwOBA correction + F4 (opposing SP is known) + Vegas total tilt onto `Base` before solving — the projections transfer claim in the docstring becomes true. (b) I-8's captain-rotation dedup. (c) 5-1 / 4-2 team-split templates and an SP-anchored template as explicit bank jobs (backlog B-14's open items). (d) fold Showdown into the run_slate certification chain per the guide's Phase 3 so "review_grade_build" stops being the permanent label.
- **Acceptance:** Showdown brief shows enrichment counts and template mix; captain rotations present in the bank; a Showdown golden fixture pins the path.

### E-5 (effort S). Strength-ordered, budget-aware bank everywhere (pairs with I-6/I-7)

- **Rationale:** one candidate-generation authority with ceiling-ranked pair coverage and cross-game filtering makes the 43 s ceiling degrade gracefully toward the strongest slate structures instead of alphabetical ones. Mostly lands as part of I-4/I-6/I-7; listed here so the consolidation is planned as one refactor, not three patches.

### E-6 (effort M). A portfolio decorrelation number on the checkpoint (IMP-3, still absent)

- **Rationale:** ledger 3.5's objective is P(at least one first place), measured today only by shared-player counts; two disjoint lineups in the same game still rise and fall together. A closed-form proxy (pairwise correlation approximated from shared-team stack sizes and shared-game exposure, summarized as "effective independent bullets") needs no simulator and directly informs how many entries a thin slate deserves (a standing 3.5 question).
- **Sketch:** deterministic `portfolio_correlation_report(assignments, projections)` on the checkpoint and in the brief. When/if the sim returns (E-8), replace the proxy with sim covariance.
- **Acceptance:** checkpoint and brief carry the number; a fixture asserts a same-game disjoint pair scores more correlated than a cross-game pair.

### E-7 (effort S). Kill the dead weight for token efficiency (OH-1..OH-5, OH-7..OH-8, still open)

- **Rationale:** this project's operating cost is measured in agent-session tokens. ~500 lines of dead DU machinery, a dead legacy allocator, triple version bookkeeping, dozens of repeated truthful-labels paragraphs, and a §7 bank doctrine that contradicts the shipped 150-cap all get re-read by every session that touches those files. The 07-19 review already specced the deletions; they were accepted; they cost nothing but an afternoon and pay every session afterward.
- **Sketch:** execute OH-1 (DU), OH-2 (legacy allocator + sizing), OH-3 (reuse penalty), OH-4 (labels boilerplate → one authority + pointers), OH-5 (audit reads VERSION from imports; delete docstring stamps), OH-7 (rewrite §7 to match `resolve_candidate_bank_size`/diverse-bank reality), OH-8 (build reports generated from diagnostics.json).
- **Acceptance:** audit passes at the reduced count; greps clean; MLB_Classic §7 matches code; a version bump touches one file.

### E-8 (effort decision, then M-L). Decide the simulation question on the record (P2-11 still dangling)

- **Rationale:** the market's winning tools are simulation-based (contest-level sims for win-rate-aware lineup selection are the 2025-26 standard across SaberSim/Stokastic-class products — see Sources). This project's counter-position is deterministic proxies + truthful labels, which is defensible for its stakes, but MLB_Classic §15/15a/16 still describe a parked sim apparatus that does not exist in this repo, and the strategic brief's Horizon 2 still points at it. That is a dangling architectural decision, not a doc nit.
- **Sketch:** pick one, on the record: (a) recover `parked/` from the pre-migration seed into `research/` and schedule the §16 sim's validation against archived per-player FPTS (now 5+ slates of it — the validation needs no ownership data); or (b) declare the sim retired, mark §15/15a/16 as spec-only, and commit to the E-6 closed-form proxy as the permanent decorrelation metric. The wrong state is the current one, where the docs promise a crown jewel nobody can find.
- **Acceptance:** a dated decision in the ledger; docs match the tree; if (a), a sim-vs-realized calibration report exists within 10 slates.

### E-9 (effort S). Late-swap leverage pass (defer until E-2 lands)

- **Rationale:** late swap currently re-optimizes the same projections. The EV of a swap is mostly ownership/leverage-driven (fade the chalk that already failed, pivot into low-owned remaining games). Without an ownership model this is guesswork, so sequence it after E-2; when it lands, it is a small addition: score swap candidates with the ownership-adjusted shape score instead of raw objective.
- **Acceptance:** swap diagnostics show the leverage inputs used; a fixture demonstrates a chalk-fade pivot beats a projection-only pivot under the scoring.

### E-10 (effort S). Auto-generate a 15-line `ENGINE_STATE.md` at commit time

- **Rationale:** every session re-derives the same facts (current versions, test count, open blockers, archive count, enrichment coverage of the last build) by reading large files. A tiny generated status file — audit summary, ledger archive count vs the 8-15 gate, last build's enrichment counts, open zero-byte inbox files — cuts session startup tokens and makes drift (I-14 class) visible at a glance. Generate it from `tools/audit.py --write-state`; never hand-edit.
- **Acceptance:** file regenerates on audit runs; CLAUDE.md session-start points at it; hand-editing is rejected by a header note.

---

## Suggested execution order

1. **I-3 + I-9** (intake integrity gates + feed freshness) — cheapest slate-loss insurance, blocks the 07-22 recurrence.
2. **E-1** (signal-complete fast path: I-1, I-2, F5) — the outcome-changing workstream; nothing else in Section 2 matters until builds stop running on bare APPG.
3. **I-4 + I-6 + I-7 / E-5** (one bank authority, scored cached candidates, cross-game strength-ordered coverage) — makes E-1's signal actually reach big-slate portfolios.
4. **I-15 + E-3** (re-pull evidence, record Ben's results) — restarts the only loop that can ever say whether any of this wins.
5. **I-5, I-8, I-10, I-11, I-13** (gates honesty, showdown captains, allocator diagnosis, one normalizer, brief collision).
6. **E-2** (ownership v0) the moment the archive crosses ~8 conditioned slates; then IMP-6's dup screen and E-9.
7. **E-7 + I-12 + I-14 + I-16** (deletion pass, dead config, doc truth, small edges) — one focused cleanup session.
8. **E-4** (Showdown signal + templates), **E-6** (decorrelation number), **E-8** (sim decision), **E-10** (state file).

Two standing rules carried forward from 07-19, both still being violated in spirit: every new input follows the enrichment pattern (labeled prior, Notes-tagged, surfaced, wiring-tested, loud on zero-match), and **the evidence loop outranks the engine** — no new subsystem lands while known evidence (zero-byte standings, missing contest trios, Ben's own results) sits uncaptured.

## Sources (external claims)

- DraftKings late swap mechanics: https://help.draftkings.com/hc/en-us/articles/4405224380051-Late-Swap-Overview-US and DK MLB rules: https://www.draftkings.com/help/rules/mlb
- Simulation-based optimizers as the current MLB DFS competitive standard: https://www.stokastic.com/articles/mlb-dfs, https://www.v12dfs.com/best-dfs-optimizer, https://onlydfs.com/blog/best-mlb-dfs-optimizer-tools-2026.html
