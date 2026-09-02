# DFS System Greenfield Spec, Tenth Edition

**Review date:** 2026-09-02. **Reviewed base:** `main` at `32cdd32` (R271 doc-truth sweep), 22 commits and ~24,400 inserted lines past ed7's base `a49bd610`; 8 commits past Codex ed9's base `0a83cac`. HEAD did not move during the review.
**Repository:** the live mount, `C:\Users\benja\Documents\Claude\mlb-dfs`. Working-tree dirt at start: 3 modified `data/reference/*` files (ARCHIVE's), untracked `NEXT_SESSION_PROMPT*.md`, `PUSH_THESE_COMMITS.md`, ~40 `ledger/inbox/*_miner_*.md` fragments (ARCHIVE's). None touched. `git status` left a fresh `.git/index.lock`; moved aside with a timestamped `mv` per R109.
**Suite evidence:** not re-run (the gate is a five-call assembly and the sandbox bridge died mid-review; see Method appendix). The tree's own record at this head is `PASS v2.26.0 27 modules 1645 tests` (NEXT_SESSION_PROMPT.md:63, CLAUDE.md:414); the pin sum in `tools/audit.py` was re-derived by read (1040+166+332+9+98 = 1645).
**Mandate:** Ben's greenfield prompt, tenth run (editions 1-7 Claude, ed8/ed9 Codex). The adjudication record was read FIRST: ed7 in full (`docs/2026-08-24_critique_greenfield_spec_ed7.md`), the backlog's "Do not build (updated)" section in full (backlog.md:7840-8156), the queue (backlog.md:1010-1207), NEXT_SESSION_PROMPT.md, and the R286-R289 landing. Nothing below re-argues a standing rejection (the nine-times-rejected program family: SQLite/WAL run store, content-addressed artifacts, DAG/FSM orchestrator, CP-SAT migration, signed manifests, watcher daemons, field-ROI simulators ahead of R10/R13). Where this edition disagrees with the record it says so and names the measurement.
**Filename note:** the requested name `DFS_SYSTEM_GREENFIELD_SPEC.md` is occupied at repo root by the tracked third edition, which the adjudication protocol keeps as the diff base. The prompt's read-only rule forbids overwriting it. This file follows the ed5/ed6/ed7 convention: dated, in `docs/`, beside the prior editions. A create-only fragment for the DEV merge sits at `docs/backlog_inbox/2026-09-02_REVIEW_greenfield-spec-ed10.md`.
**Method:** six parallel reviewer lanes, each reading its files line by line: (1) solver core and bank; (2) pipeline, allocator, state, export; (3) intake and projections; (4) Showdown, field miner, late swap; (5) operator tools; (6) instruction files, context economics, test assertion strength. Repros ran in `/tmp` for lanes 1-4 until the sandbox bridge died; lane 5 ran with file tools only. The coordinator re-read every Blocker and every headline Bug citation against the tree before filing (list in the appendix). Labels: VERIFIED-repro (script ran, output quoted), VERIFIED-read (exact lines quoted; coordinator re-read where marked), PLAUSIBLE (mechanism read, not executed).
**Walls, held throughout:** DraftKings reads are manual; the money-and-entry wall is absolute; nothing below automates DraftKings. Zero-touch is designed between the two manual clicks, as every adjudicated edition has held. Truthful labels govern this document: nothing here is ROI, win rate, cash rate, EV, or a probability claim; every objective named is a deterministic proxy and every prior is a labeled prior. The prompt asks for "maximum expected-value lineups"; this repo has not earned that label and this edition does not award it (Section 4.6 says what would).
**Numbering:** findings carry GF10 ids with a lane letter (S solver, P pipeline, I intake, D showdown/field, T tools, X tests, C context). R-numbers are allocated by the landing DEV session by scanning backlog + CHANGELOG at commit time (current max R290); no number in this file is a board number.

---

# Section 0: Verdict, in one page

**The MILP core is correct and fast. The defects live in the seams and the operator layer, and the fix rate is not keeping up with the seam-defect rate.** Three Blockers, 35 Bugs and 6 Performance findings were filed in this pass; the Blockers and the majority of the Bugs sit on surfaces landed since 2026-08-24 (the R246, R249, R250, R270, R272 and R286-R289 code), and two of the three Blockers sit inside the two most recent fixes: the R289 landing that answers the lost 1940_9g slate does not reach the optimizer on the production Classic path (GF10-I1), and the R272 autonomous-repair clause rests on a tool whose only write path cannot produce a clean file (GF10-T1) and whose replacement filter admits a player the boxscore says is already in a game (GF10-T2).

**Measured, not argued:**
- Engine wall time is not the problem. 208 build briefs since 2026-07-18: certified builds median 22.7 s, p90 56.7 s; refusals median 28.4 s. A single Classic solve is 11-114 ms in `milp`. Sub-second is a bank-strategy question, not a solver question (Section 4.3).
- Attempts per delivery are the problem. 2026-09-01 produced 22 briefs (8 certified, 7 refused, 7 review-grade) and one slate with no file at all. 32 of 208 briefs are refusals, each ~30 s of engine and several minutes of session.
- The instruction corpus a BUILD session reads before its first command is 46-59k tokens (CLAUDE.md 12.0k, SKILL.md 16.0k, `git log --oneline -12` 7.2k because 22 commit subjects exceed 500 chars, the ledger Quick Card item 1 ~11k in one physical line). CLAUDE.md is 5.0x its 2026-07-25 size, 135 of 271 commits touch it, ~55% of its bytes are dated incident narrative, and three tests pin its prose so it cannot shrink without reddening the gate (Section 3.1).
- The same rule is stated in 5-11 places (bash ceiling 11 sites, PASS line 9 live + 3 stale, pool rule 8, truthful labels 9). The R271 sweep that unified the ceiling left `timeout 33` at SKILL.md:616 and :665. R233's N+1 event, inside the fix that cites R233.
- 15 quoted contradictions between live files, the worst at the money boundary (Section 3.2).
- 1,645 tests: 9.2% touch a solver or pipeline entry, 7.7% read source or walk an AST, 22.7% of assertions are substring checks. Of 33 high-stakes samples, 19 pin the counterfactual, 8 are string pins (including the R272 safety argument and the R288 export-validator claim), 5 are conditional, 1 asserts nothing. The R289 acceptance test builds its frame from `pool["projection_rows"]` directly and never executes `_assemble_projection_frame`, which is where the column is dropped.

**Where this edition agrees with the record:** every prior rejection of the enterprise program family stands, on the same grounds. The Tier 2 ordering (measure first: R118 replay → R48/R83 → R10 → R140, R13 as the funding gate) is right, and the archive already holds the per-player FPTS rows the replay needs (ed7 §3.1, re-confirmed by read of `field_miner.py` player_table survival).

**Where it disagrees, with the measurement:** the record rejects "monolith decomposition, no named measurement" and "under-30-line CLAUDE.md absolutism". The measurements are now named: R118 has been Tier 2's head for six weeks and has not been built, because Tier 1 refills daily from defects in the previous week's fixes (R233 has paid nine times; this edition adds three more members of closed classes). A defect-fix treadmill that never reaches the measuring instrument is a measured cost. The greenfield target in Section 4 is therefore SUBTRACTION, not the rejected additions: one deterministic command between the two clicks, one owner per rule, no LLM in the critical path, the replay tool shipped first so the new engine is graded against the old on the archive before it replaces anything.

---

# Section 1: Repository Architecture & Data Flow Map

## 1.1 Inventory

99,051 lines across `mlb_engine/ tools/ tests/ skills/` (Python, Markdown, JSON, CSV fixtures). Engine and tools ≈ 60k lines of Python; tests 31,274 lines / 1,645 methods; instruction and record corpus ≈ 2.63 MB (CLAUDE.md 47,862 B; SKILL.md 64,089 B; MLB_Classic.md 50,995 B; backlog.md 727,030 B / 9,203 lines; CHANGELOG.md 956,971 B / 13,200 lines; ledger 778,825 B).

| Area | File | Lines | Role |
|---|---|---:|---|
| Authority docs | `CLAUDE.md`, `MLB_Classic.md`, `skills/generate-lineups/SKILL.md` | 718 / 620 / 1,143 | contracts + gotchas; strategy numerics; per-slate procedure |
| Intake | `mlb_engine/intake/live_data_adapters.py` | 3,174 | `build_slate_pool` front door; DK `Starting` merge; feed status map; boxscore tier; odds fetch/parse |
| | `mlb_engine/intake/slate_intake_manager.py` | 1,874 | DKSalaries parser, name/id normalizers, weather F5, `slate_clock`, Game Info parse |
| | `paste_lineups.py`, `paste_odds.py`, `platoon_order_adapter.py`, `team_codes.py`, `repo_env.py` | 1,087 / 433 / 370 / 115 / 159 | operator pastes, TBD-team platoon projection, DK abbrev remap, env/secrets |
| Projections | `mlb_engine/projections/projection_builder.py`, `xwoba_base_correction.py` | 993 / 313 | Base×F1..F5, Floor/Ceiling, xwOBA/xISO/K-rate joins |
| Solver | `mlb_engine/optimize/optimizer_v3.py` | 4,463 | Classic single-lineup MILP (`scipy.optimize.milp`), bank builder, reuse ladder, DU, scoring |
| | `bank_cache.py`, `roster_contracts.py`, `contest_shapes.py`, `determinism.py`, `tail_candidate_scanner.py` | 997 / 83 / 189 / 165 / 656 | resumable job-grid bank; roster geometry; shape vocabulary; sort-before-solve; review screen |
| | `showdown.py`, `showdown_theses.py` | 1,083 / 1,812 | Showdown melt, CPT/UTIL MILP, caps, thesis ladder |
| Pipeline | `mlb_engine/pipeline/execution_pipeline.py` | 5,167 | `run_slate` (the only production entry), `execute_portfolio`, gates, certification, `run_late_swap`, mirror |
| | `build_state_manager.py` | 589 | `runs/<id>/` manifest, promote, pointer CAS |
| Allocation | `mlb_engine/allocate/contest_allocator.py`, `posture_allocator.py` | 3,390 / 356 | joint entry↔candidate MILP with exposure caps; inert waterfall |
| Export | `mlb_engine/entries/dk_entries_manager.py`, `upload_manifest.py` | 1,197 / 531 | template writer, `validate_dk_entries_file`, delivery manifest |
| Field | `mlb_engine/field/field_miner.py`, `ownership_prior.py`, `contest_library.py` | 2,263 / 562 / 439 | DK standings miner → archive; satellite ownership prior; unused registry |
| Swap | `mlb_engine/swap/late_swap_manager.py`, `tools/late_swap.py` | 404 / 904 | frozen-slot contract; swap driver |
| Driver | `skills/generate-lineups/scripts/build_slate.py` | 4,086 | per-slate CLI: stage → pool → enrich → probe → direct/sliced bank → `run_slate(approve=True)` → brief; Showdown driver |
| Supervisor | `tools/autobuild.py` | 532 | unattended retry loop over `build_slate.py` with structural remedies |
| Gates | `tools/preflight_upload.py`, `tools/verify_export.py` | 2,405 / 619 | stdlib-only pre-upload referee; weaker sibling |
| Repair | `tools/repair_entry.py` | 562 | single-slot dead-player repair (R272) |
| Audit | `tools/audit.py` | 2,530 | inventory/version pins; chunked five-call test gate |
| Other tools | `qa_portfolio`, `solver_probe`, `stage_slate`, `promote_run`, `claim`, `sync_check`, `fetch_*`, `refresh_reference_data`, `ownership_pred`, `awaiting_standings`, `lineups_from_paste`, `odds_from_paste`, `env_probe`, `rebuild_registry`, `build_asserted`, `stack_shape_probe`, `wheel_fetch`, `net_to_date`, `extract_inbox_zips` | 6,700 total | |
| Tests | `tests/test_core.py`, `test_upload_integrity.py`, `test_showdown.py`, `test_paste_lineups.py`, `test_golden_replay.py` | 20,269 / 5,856 / 2,928 / 1,591 / 630 | 1,040 / 332 / 166 / 98 / 9 methods |
| Data | `data/slates/<date>/`, `data/reference/`, `data/archive/`, `data/standings/inbox/`, `runs/` (573 entries), `outputs/<date>/`, `ledger/` | | staged inputs; Savant/FanGraphs/StatsAPI reference; 271+ mined contests; standings; immutable runs; delivered mirrors + briefs; calibration ledger |

Dependencies: Python 3.10, numpy 2.2.6, pandas 2.3.3, scipy 1.15.3 (HiGHS via `scipy.optimize.milp`), stdlib `urllib` for every fetch, `zoneinfo`/`tzdata` for ET. No PuLP, no OR-Tools, no requests. `.pylibs/` is a vendored Linux wheel set; Ben's Windows Python has no scipy, so the engine runs only in the Cowork sandbox.

## 1.2 End-to-end data flow (Classic, as shipped)

```
 [Ben: click 1]  DKSalaries.csv + DKEntries.csv  (+ optional mlb.com lineup paste, odds paste)
        |
        v
 build_slate.py main()  ............................................  BS:3559-4082
   args (24 flags) -> units gate -> slate_signature(Game Info) -> stage to data/slates/<date>/
        |
        |  lineup-source ranking PER SIDE (R143): DK `Starting` 1-9 > paste > statsapi feed > boxscore once underway
        v
 live_data_adapters.build_slate_pool()  ...........................  LDA:1489-2499
   parse salary -> status tiers -> merge_dk_starting_into_feed -> build_status_map -> postponement
   -> TBD teams: platoon_order_adapter (FanGraphs ref, aged vs slate) -> confirmed 9 / posted partial / top-9 APPG
   -> pitchers: probables + --declare-pitcher -> pool_report{teams, blockers, thin_teams, excluded_column, slate_clock}
        |                                   projection_rows (Player_ID, Team, Pos, Salary, Game_ID, APPG, Batting_Order, Excluded, DK_Status)
        v
 run_classic() enrichment  ........................................  BS:1637-1745
   reference status -> F4 (opp xwOBA + platoon prior) -> venues -> odds (the-odds-api or paste) -> F1 (implied totals) -> F5 (park/weather)
        |
        v
 execution_pipeline._assemble_projection_frame()  .................  EP:3625-4138
   salary join -> F1/F4/F5 maps -> F2 from batting order -> Base = APPG (or supplied)          <-- GF10-I1: `Excluded` NOT carried
   -> xwOBA Base correction (shrink 50/100 PA, clip .85-1.15 / .90-1.10) -> xISO ceiling mult (1.42 ± .30·(pct-.5), clip 1.25-1.60)
   -> K-rate pitcher ceiling -> value guard (p90 pts/$k × 1.08) -> build_projections: Base_Projection = Base·F1·F2·F3·F4·F5,
      Floor = .58·BP, Ceiling = mult·BP, Ceiling<Floor raises
        |
        v
 probe (one build_single_lineup timing) -> direct vs sliced  ......  BS:1776-1805
   sliced: bank_cache.extend_bank (pair × team job grid, resumable JSON, conditions_signature buckets)  BC:660-960
   direct: run_slate's build_diverse_candidate_bank (base bank + SP-pair/stack augmentation)            OV3:4017-4365
        |                                                                                              <-- GF10-S1, GF10-S2
        v
 run_slate(approve=True)  .........................................  EP:4353-4944
   postures -> entry_requirements (one per reserved row) -> _slate_feasibility (viable SP pairs, stackable teams, floors)
   -> _merged_controls_for_build (posture defaults ⊕ floors ⊕ override) -> _feasibility_report -> slate_clock
   -> _derive_workflow_gates (salary, entry_grid, lineup, pitcher_audit, weather, odds; None/False/True)
   -> resolve_gate_assertions (--assume-gates: None->assumed; False->overridden only for lineup_gate)
   -> execute_portfolio()  ........................................  EP:309-602
        create_run(runs/<ts>_<hex>/) -> snapshot inputs
        -> contest_allocator.select_and_assign_entries(): joint MILP over x[e,k] with caps      CA:2359-3327  <-- GF10-P1
        -> validate_upload_ready_gates (pre) -> write_candidate_from_template -> validate_dk_entries_file (post)  <-- GF10-P3
        -> copy to final/DKEntries.csv, hash-bind -> derive_workflow_certification -> promote_run (pointer CAS)
   -> mirror_to_outputs: outputs/<date>/DKEntries_<tag>.csv + upload_manifest.json row
        |
        v
 brief (build_brief_<tag>.json) -> qa_portfolio.py (report) -> preflight_upload.py (stdlib gate, exit 0/2/3/4)
        |
        v
 [Ben: click 2]  upload DKEntries_<tag>.csv in the DK UI, checking the sha256 in the brief
        |
   later: standings CSV -> data/standings/inbox/ -> field_miner -> data/archive/<date>/mined_<contest>.json -> ledger
```

Showdown diverges at `build_slate.py:3915` into `run_showdown` (BS:2553-3131): `showdown.melt_showdown_salary_csv` (CPT/UTIL rows → persons) → thesis ladder (`showdown_theses.build_thesis_ladder` / `solve_ladder`) or fallback `build_showdown_bank` → `certify_showdown` per lineup → `write_showdown_entries` → review-grade brief. It never enters `run_slate` and never certifies (CLAUDE.md "Showdown").

Late swap: `tools/late_swap.py` → `run_late_swap` (EP:678-784): parent run from `runs/latest_valid_run.json`, frozen slots from lock times, `fixed_exposure`, `excluded_new_teams`, then `execute_portfolio(mode="late_swap")`.

## 1.3 Solver formulations as implemented

**Classic single lineup** (`optimizer_v3._build_single_lineup_scipy`, OV3:811-1182). Binary `x[p,s]` per (player, exact slot in `P1,P2,C,1B,2B,3B,SS,OF1,OF2,OF3`) where the player's position set admits the slot; binary `y[g]` per game; continuous `z ∈ [0, 0.75]` suppression tiebreaker. Objective (scipy minimizes the negation): maximize `Σ x[p,s]·obj_p + z`, `obj_p = Ceiling_p` (GPP target) or `Floor_p` (cash), minus caller penalties. Base_Projection, stack bonuses, batting order, ownership and field pressure do NOT enter the MILP; they are post-solve rerank (`score_lineup_candidate`, OV3:3627-3723) and allocator inputs. Rows, in emission order: one slot per player (:904); each slot filled once (:906); `z ≤ Σ bonus·x` (:909-921); salary ≤ 50,000 (:922); optional cumulative-ownership cap (:934) and low-owned floor (:940-971); ≤ 5 non-P hitters per team (:973-976); game indicators `y_g ≤ Σ_{p∈g} x`, `x[p,·] ≤ y_g`, `Σ y_g ≥ 2` (:978-992); locks and slot locks (:994-1015); per-SP anti-correlation big-M row `M·x_sp + Σ_{h∈opp} x_h ≤ M + k`, `k = max_opposing_hitters_per_sp` default 0 (:1039-1069); stack min/max (:1071-1074); bring-back (:1075-1078); overlap vs each prior roster (:1079-1083); WTA core blocklist and forbidden combos (:1084-1093). Integrality on all binaries, `Bounds(0,1)`, `time_limit = max(0.001, min(30, remaining))`, HiGHS default gap 1e-4. Measured on the 3-game frozen fixture: 277 vars, 305 rows, `milp` 11-12 ms; on the 6-game fixture 499 vars, 546 rows, 68-114 ms.

**Bank / reuse ladder** (`build_multi_lineup`, OV3:2346-2968): sequential solves with `max_overlap` starting at `max(2, int(10·pct))` (6/4/3 by posture), climbing by one on non-timeout infeasibility, never on timeout; anchor caps (SP and SP-pair) applied as excludes/forbidden combos; DU units disabled on the production `'selection'` scope. Measured: a 10-lineup WTA bank on the 6-game frame is 10.0 s wall, 96% inside `milp`, per-solve cost rising 0.09 → 1.33 s as overlap knapsack rows accumulate; symmetry-breaking rows gave no gain. `build_diverse_candidate_bank` (OV3:4017-4365) then forces one lineup per viable SP pair with a 4-stack. `bank_cache.extend_bank` (BC:660-960) is the sliced alternative: a `|pairs| × |teams|` job grid, resumable, keyed by `conditions_signature` (excludes, stack bounds, `opp:k` when non-default, projection bytes).

**Portfolio allocation** (`contest_allocator.select_and_assign_entries`, CA:2359-3327). Binary `x[e,k]` (entry × candidate), optional `y[k]` for overlap. Objective: minimize `−normalized_shape_score(e,k)` (per-entry min-max in [-100, 0]). Rows: `Σ_k x[e,k] = 1`; same-contest same-signature ≤ 1; per-signature reuse ≤ `max_candidate_reuse` (engine default `ceil(total/distinct)`, rungs `[first, 2·first]`); player / pitcher / primary-stack caps ≤ `floor(total·pct + 1e-9)` (`max(1, ·)` clamp) minus fixed rows; SP-pair ≤ cap; five-stack quota ≥ need; per-game caps; overlap linkage `y_i + y_j ≤ 1` for signatures sharing > limit; incompatible pairs `x ≤ 0`. Prefilter to `max(6E, 40)` candidates before the solve (CA:1074-1149). Refusal path: binding-constraint diagnosis, then reuse → quota → floor re-entry ladders, never on timeout. `time_limit` 30 s.

**Showdown** (`showdown.build_showdown_lineup`, SD:343-556). `2n` binaries `cpt(i)`, `util(i)`. Objective `1.5·Base_i·cpt_i + Base_i·util_i`. Rows: exactly one CPT, exactly five UTIL, `cpt_i + util_i ≤ 1`, salary `Σ CPT_Salary_i·cpt_i + UTIL_Salary_i·util_i ≤ 50,000` (DK's own CPT-row price), each team ≥ 1, locks, `cpt_lock`, `cpt_excludes`, `util_excludes` (R250 hold), prior-lineup overlap ≤ `min(max_shared, 5)` counting the person. Three portfolio caps (`max_shared_players` 4, `max_cpt_exposure_pct` 0.25, `max_player_exposure_pct` 0.50) plus the per-contest captain rule `1 if n==1 else max(1, min(2, n-1))` are enforced rung by rung in `solve_ladder` (ST:1010-1598) against realized counts.

## 1.4 Contracts and schemas

**DKSalaries.csv** (consumed columns): `Position`, `Name + ID`, `Name`, `ID`, `Roster Position` (Classic `P/C/1B/...`; Showdown `CPT`/`UTIL` with the CPT row carrying its own ID and 1.5× salary), `Salary`, `Game Info` (`AWAY@HOME MM/DD/YYYY HH:MMPM ET`, parsed by two divergent regexes: SIM:1721-1724 requires `ET`, PF:166-168 requires 2-digit fields and no `ET`), `TeamAbbrev` (DK vocabulary is the target; `team_codes.DK_ABBREV_REMAP` maps API codes, missing `WAS`→`WSH` and `OAK`→`ATH`), `AvgPointsPerGame`, `Starting` (1-9 batting order, `SP`/`P`/`PLR`), `Status` (`OUT`/`IL`… shelved), `Excluded` (affirmative tokens only; one reader `optimizer_v3.read_excluded_cell`). The CSV is authoritative for ids, salaries, teams, eligibility (CLAUDE.md "Authority").

**DKEntries.csv** (template in, upload out): columns 0-3 `Entry ID, Contest Name, Contest ID, Entry Fee`; roster window from column 4, geometry detected from the header against `roster_contracts.CLASSIC.slots` / `SHOWDOWN.slots`; DK's embedded player pool sits to the right of the roster window. Reserved rows = all-digit Entry ID and Contest ID. The writer (`write_candidate_from_template`, DEM:611-677) writes bare ids into the ten roster cells and touches nothing else; `validate_template_preservation` requires identical row count and identical non-roster cells. Blank reserved rows block certification.

**Certification** (`derive_workflow_certification`, DEM:1113-1132): `workflow_valid` = all six derived gates + schema + optimizer + `selection_certified` truthy pre-export, and all six post-export gates (template preservation, reconciliation, roster legality, portfolio caps, locked immutability, candidate==final hash) true, and `allocation_method` in the scipy whitelist; `selection_certified` and `allocation_certified` AND `workflow_valid`. "Upload-ready" is reserved for a delivered file whose manifest row reads `certification: certified` and whose preflight exits 0.

**Brief** (`build_brief_<tag>.json`): `status ∈ {certified, not_certified, review_grade_build, verify_failed}`, `delivered_path`, `delivered_sha256`, `gates`, `solve{strategy, bank}` (bank is `None` on the direct path: R285), `slate_clock`, `pool`, `exposure`, `verification`, `controls_override_applied`, `anti_correlation`, `leverage`, `enrichment`, `elapsed_s`. Refusal briefs carry `errors[]`, `feasibility.checks` (failing checks printed first since R286), `slate_clock`, `hint`.

# Section 2: Comprehensive Code Review & Defect Log

Line numbers are against `32cdd32`. Board status is stated per finding: NEW, `board-known (R###)` where an open item already holds it, or a CLOSED item shown incomplete with the evidence. Abbreviations: OV3 `mlb_engine/optimize/optimizer_v3.py`, BC `bank_cache.py`, EP `execution_pipeline.py`, CA `contest_allocator.py`, DEM `dk_entries_manager.py`, LDA `live_data_adapters.py`, SIM `slate_intake_manager.py`, PB `projection_builder.py`, SD `showdown.py`, ST `showdown_theses.py`, FM `field_miner.py`, BS `skills/generate-lineups/scripts/build_slate.py`, AB `tools/autobuild.py`, PF `tools/preflight_upload.py`, VE `tools/verify_export.py`, RE `tools/repair_entry.py`, AU `tools/audit.py`.

## 2.1 Blockers

**[Blocker | GF10-I1] EP:3806-3822 + PB:126-127 — R289's `Excluded` column is dropped at frame assembly; the operator exclusion still never reaches the optimizer, the bank, or the bank digest on the production Classic path.** VERIFIED-repro (lane 3) + coordinator re-read of both sites and of `run_slate` EP:4449 and the checkpoint reader EP:3108-3119.
```python
# EP:3806-3822 -- the rebuilt row, fixed key set, no "Excluded"
assembled.append({
    "Player_ID": pid, "Name": r.get("Name") or sp.name, "Team": sp.team, ...,
    "Batting_Order": bo_val, "Stack_Group": ..., "Ownership_Tier": ..., "AvgPointsPerGame": ..., "Notes": notes,
})
# PB:126-127
if "Excluded" not in frame.columns:
    frame["Excluded"] = False
```
Mechanism. R289 (landed `6ebcdb9`) made `_pool_row` (LDA:1464-1476) carry `Excluded`/`Excluded_Source` and the pool report count them (LDA:2332-2350). Every Classic build then passes `pool["projection_rows"]` through `_assemble_projection_frame` (`run_slate` EP:4449; both `build_slate.py` routes BS:1700/1725), which constructs a new dict per row and omits the key; `build_projections` stamps `Excluded=False` on every row. The bank (`extend_bank` BS:1813; plan bank EP:3443-3455; auto-bank EP:4798-4804, which sets `Excluded` only from TYPED excludes) and `projection_digest` (BC:542-544 hashes the assembled frame's `Excluded`) therefore see an all-False column. The checkpoint's own `exclusions.excluded_column` (EP:3109 reads the assembled frame) reports 0 while `pool_report.excluded_column` reports the salary count: one brief, two disagreeing counts. Third discard site: `refresh_confirmed_lineups` PB:189-193 assigns `Excluded = pid not in starter_set` on the late-swap path. Repro (synthetic 4-team salary, `Excluded=TRUE` on T3/T4, through `build_slate_pool` then `_assemble_projection_frame`): `pool Excluded=True: 20 / pool_report.excluded_column.applied: 20 / frame Excluded=True count: 0 / T3,T4 rows in frame: 20`. The R289 acceptance test (test_core.py:4016-4036) builds `pd.DataFrame(pool["projection_rows"])` and calls `_drop_excluded_rows` directly, so the wiring never executed (the R249-M1 shape from two commits earlier). The R289 CHANGELOG enumeration names two stamp sites; the class has five.
First bad moment: the next Classic build staged from a salary file carrying an `Excluded` column, i.e. a re-run of 1940_9g's `DKSalaries_excl_locked.csv`. It is worse than pre-R289 in one respect: the pool report and a warning now tell the operator "legal pool is N−288" while the frame, bank and certified file hold all 288.
Fix (EP:3806-3822; PB:126 already tolerates presence):
```python
        assembled.append({
            ...,
            "Notes": notes,
            # R289 second landing: the front door's reading of the salary Excluded
            # column, carried verbatim. Absent key -> False, never re-derived here.
            "Excluded": bool(r.get("Excluded", False)),
            "Excluded_Source": r.get("Excluded_Source") or "absent_or_blank",
        })
```
and PB:189-193 must OR, not assign:
```python
    operator_flag = bool(row.get("Excluded")) and str(row.get("Excluded_Source") or "") == "salary_file"
    frame.at[index, "Excluded"] = operator_flag or (pid not in starter_set)
```
Test: call `_assemble_projection_frame` (or `run_slate(approve=False)`) on the R289 fixture; assert `projections["Excluded"].sum() == 20` and that `projection_digest` differs between the plain and the excluded salary file. Board: R289 is CLOSED; reopen as incomplete.

**[Blocker | GF10-T1] RE:426-434, :464, :527 — `write_entries` re-emits the entire original table after the repaired rows; the tool's only write path produces a file with two header rows and every dead player still present.** VERIFIED-read; coordinator re-read RE:426-434, RE:464, RE:527 and PF:383-400.
```python
contest, slots, entries, trailing, _ = load_entries(args.entries)   # RE:464; PF:400 returns `rows` = the FULL table incl. header
def write_entries(path, header, entries, trailing):                 # RE:426
    writer.writerow(header)
    for entry in entries: writer.writerow(entry.raw)                 # repaired copies (EntryRow.raw = list(raw), PF:343)
    for row in trailing: writer.writerow(row)                        # header + ORIGINAL entry rows (dead player intact) + pool rows
```
Preflight fails the output (row accounting PF:703, duplicate Entry IDs PF:711), so no money is at risk; but the R272 autonomous-repair clause (CLAUDE.md "Repair is not strategy") rests on a write path that cannot produce a clean file. Every test drives `--dry-run` or never reads the output (test_upload_integrity.py:5642-5645, :5712-5726); CHANGELOG:1313 records that on 1305_12g "the hand-built file is what shipped". First bad moment: the first non-dry-run `repair_entry.py` inside a lock window. Fix (RE:464 onward):
```python
    entry_ids = {e.entry_id for e in entries}
    trailing = [r for r in trailing[1:]
                if not (_cell(r, 0).isdigit() and _cell(r, 0) in entry_ids)]
    write_entries(out_path, header, entries, trailing)
```
plus a test that writes, re-loads via `load_entries`, and asserts `entry_id_rows == len(entries)` and the dead id absent.

**[Blocker | GF10-T2] RE:286-301, :313 — a replacement candidate the observed tier marks `started` is admitted; by that tier's own contract (LDA:1269-1287) the player's game is UNDERWAY.** VERIFIED-read; coordinator re-read RE:280-318 and RE:475-501.
```python
if team in locked: census["team_locked"] += 1; continue           # `locked` is feed-derived only (RE:475-481), empty with no --feed
state = observed_starter_state(observed, pid, team) if observed is not None else "unobserved"
if state == "did_not_start": ...; continue
if state != "started" and pid not in confirmed: ...; continue      # "started" bypasses the feed test
"confirmed_source": "observed" if state == "started" else "feed",
```
`observed_starter_state` returns `started` only for a team in `observed_teams`, filled only when the boxscore says the game is live. The only guard is `locked`, empty without `--feed` (the CLI allows it) and blind to any game the feed does not carry. First bad moment: `repair_entry.py --boxscores …` with no or a stale feed on a slate with one game in progress: the top-projected `started` player is written into the entry; preflight's R287 check is the last line. Fix:
```python
        if state == "started" or team in set((observed or {}).get("observed_teams") or []):
            census["team_locked"] += 1
            continue
```
and drop the `"observed"` branch of `confirmed_source`. Board: R279 discusses `check_feed`; nothing files this admission path.

## 2.2 Bugs: solver and bank (lane S)

**[Bug | GF10-S1] OV3:4163-4174, :4289-4293, :4308-4313 — the diverse bank's infeasible-stack skip excludes the pitcher's OWN team, not the opponent; every attempt against an opponent is a paid guaranteed-infeasible solve and every legal SP-plus-own-offense stack is unreachable through augmentation.** VERIFIED-repro (lane 1) + coordinator re-read.
```python
def _teams_of_pair(pair):
    ...
    for pid in pair:
        row = projections_df[_bank_pid_col == normalize_id(pid)]
        if len(row):
            teams.add(str(row.iloc[0].get('Team')))          # :4172  own team, not Opponent
excluded_teams = _teams_of_pair(pair)                       # :4289
if team in excluded_teams: continue                         # :4292-4293
```
With `k=0` the anti-correlation rows bar a 4-stack of an arm's Opponent before the solve; the closure returns the arms' own teams. Repro (synthetic 3-game, `requested_n=6, bank=12`): 13 augmentation attempts, 6 (46%) stacked an arm's opponent and returned infeasible, 0 stacked an arm's own team; 27 solver calls, ~1.5 s of a 6.4 s budget bought nothing. R164(b) (backlog:5338-5341) and the R165 mutation notes assert the skip targets opposing teams; the test at test_core.py:19843-19848 asserts dtype invariance only. Fix: return `Opponent` when the effective `max_opposing_hitters_per_sp < bank_stack_min_size`, else the empty set; pin `excluded_teams == {opp(a), opp(b)}` on a fixture that reaches Phase 1. Board: contradicts R164(b)'s premise; re-scope that item.

**[Bug | GF10-S2] OV3:4071-4087 + EP:4813-4822 — `max_opposing_hitters_per_sp` is not on every rung: the auto-bank path never receives it and the augmentation pass's whitelist drops it, while the brief writes `anti_correlation.applied` from the REQUEST (BS:2211-2215).** VERIFIED-repro (lane 1) + coordinator re-read of both sites.
`passthrough_keys` (OV3:4071-4086) carries the three R246 leverage keys and not the R288 key; `build_diverse_candidate_bank(...)` at EP:4813-4822 passes `excludes` and `**_leverage_kwargs(leverage)` and nothing for anti-correlation although `controls` carries it. On the DIRECT strategy (chosen whenever the probe says the direct build fits, BS:1800-1806) the whole bank solves at k=0; the export validator grades against `controls.max_opposing_hitters_per_sp` (DEM:988) and passes; the brief says `applied: 2`. Repro (synthetic, k=3): `{'base_with': 6, 'base_without': 2, 'aug_with': 0, 'aug_without': 18}`. R288's enumeration found five members; these are six and seven. Fix: add the key to `passthrough_keys`; add `max_opposing_hitters_per_sp=controls.get("max_opposing_hitters_per_sp")` at EP:4813; have `applied` come from the bank report, not `args`. Board: R288 CLOSED, incomplete.

**[Bug | GF10-S3] OV3:1084-1093 — `stack_core_blocklist` / `forbidden_player_combos` rows shrink to the pool and become STRICTER: a 3-core with two members excluded emits `Σ x ≤ 0` over the survivor, a pool reduction nothing records.** VERIFIED-repro (lane 1): lock two of a core, exclude the third, blocklist the core → `proven_infeasible=True`; without the blocklist → optimal. Reachable via `mode='wta'` + `scenario_families` + `bank_constraint_scope='bank'` once a stack-team SP hits `active_sp_cap`. Fix: emit the row only when `len(pids) == len(core)`. NEW.

**[Bug | GF10-S4] OV3:1441-1442, :2120-2121 — `compute_unit_signature` indexes `Ownership_Tier` and `Notes` unconditionally; both are `OPTIONAL_PROJECTION_FIELDS` (:404-408), so a frame that passes `validate_projection_schema` KeyErrors after the bank solves are paid for.** VERIFIED-repro (80-row lean frame → traceback at :1441 after 12 solves). Production is shielded only by EP stamping `"Mid"`. Fix: default the columns in both helpers or name them in the schema. NEW.

**[Bug | GF10-S6] BC:582-620, :542-544 — R290(a) at HEAD is two omissions, not one: the three leverage controls are absent from the bucket key AND `Projected_Ownership_Pct` (the column those constraints read) is absent from `_PROJECTION_COLUMNS`, so `apply_leverage_ownership`'s overwrite (EP:4479) moves neither the bucket nor the digest.** VERIFIED-read. The allocator has no per-candidate ownership filter, so the "bank is a superset, allocator filters" argument (BC:39-43) does not hold for this control. Fix: append `lev:<k=v…>` and the sorted ownership column to the signature only when leverage is non-empty (keeps existing signatures byte-identical). `board-known (R290(a))`, with the second omission added.

**[Performance | GF10-S5] BC:731-737, :816-820 — the job grid enumerates arms and teams the pool already proved impossible: `extend_bank` reads `excl` but never the `Excluded` column, and `_check_stack_feasibility` runs (OV3:750) before the Excluded/excludes drops (:752-754), so every such job is a full frame prep + matrix + `milp` ending `proven_infeasible`.** VERIFIED-read. On R289's slate (288 of 842 rows excluded) the first slices, the T-minus ones, pay for the locked games' arms and teams. Fix: `_drop_excluded_rows` before :731; `_parse_positions` for the P test; skip `(pair, team)` when `team ∈ {opp(a), opp(b)}` and `k < stack_min`. Half `board-known (R164(b)(c))`; the Excluded half is new (R289 post-dates R164).

**[Performance | GF10-S7] OV3:3899-3903, :4143-4146 — the meta-lineup MILP is solved twice per diverse bank, unbudgeted.** VERIFIED-repro (`base_without: 2` in GF10-S2's counter). `board-known (R73(a))`, still present.

**[Performance | GF10-S8] OV3:987-991 — the per-player `x[p,·] − y_g ≤ 0` rows are 136 of 305 rows (45%) on the 3-game frame and are logically redundant for a MIN-games lower bound (`y_g ≤ Σ_{p∈g} x` plus `Σ y_g ≥ 2` already forces a player from every counted game).** VERIFIED-read, row count measured. Presolve likely drops them; the win is construction time (~17 ms of 29 ms wall on 136 rows). Must be checked against the golden replay (F19 names row order as a tie-break input). NEW.

**[Performance | GF10-S9] OV3:2589-2620 — bank solve time is HiGHS branch-and-bound on the accumulating overlap knapsack rows, not Python.** VERIFIED-repro: 10-lineup WTA bank on the 6-game frame, 10.0 s wall, 96% in `milp`, per-solve `[0.09, 0.15, 0.31, 0.99, 1.04, 2.0, 1.13, 1.25, 1.33, 1.33]` s while rows went 546→555; every gap ≤ 8e-5; symmetry-breaking rows gave no gain (8.7 → 9.3 s). This is the number Section 4.3's sub-second design is built against.

**TechDebt (lane S):** GF10-S10 `_check_stack_feasibility` returns early on any lock (OV3:540-541) so the named `StackInfeasibleError` never fires on the paths that stack (`board-known R73(d)`, ordering half new). GF10-S11 `du_threshold_row` defaults None while `_DU_AUTO` promises auto (`R73(c)`). GF10-S12 augmented `lineup_id = len(existing)+1` collides after a failed base index (OV3:4245, `R73(e)`). GF10-S13 every `Ownership_Tier` reader is inert because the only writer emits `"Mid"`; `_classify_chalk_one_off`'s `'Low'` branch and six labels are dead, `high_owned_one_offs` is identically 0 (`R197`, extended). GF10-S14 `ensure_pinned_hash_seed` has zero callers; BS:47-51 and late_swap.py:51-55 inline copies, solver_probe has none (R233 class; `R73(f)` half). GF10-S15 `max_candidates` tested against `len(cache)` across all live buckets (BC:837), so a second slice under a new `--exclude` set can be refused zero jobs. GF10-S16 `_projection_bytes` is dtype-sensitive (`"10" < "9"`, `1` vs `1.0`; BC:547-564), PLAUSIBLE. GF10-S17 `validate_projection_schema` passes a NaN Ceiling (OV3:414-415), PLAUSIBLE. GF10-S18 budget comment says running average, code keeps max (OV3:2514-2517 vs :2793); `budget_report['exhausted']` only set on the pre-check. GF10-S19 `bank_cache.py:59` imports `ENTRY_ROSTER_SLOTS` from `allocate` (optimize→allocate inversion) while `roster_contracts.CLASSIC.slots` is the declared owner; `VERSION` says `v1.1` at :3 and `v1.3` at :65; OV3:4 says v2.16.0 against the v2.26.0 pin. GF10-S20 `_stackable_teams_by_strength` ignores `bank_stack_min_size` and `excludes` (OV3:4095). GF10-S21 big-M aggregate anti-correlation row has a weaker LP relaxation than the pairwise family it replaced (OV3:1039-1069), PLAUSIBLE, unmeasured; a 10-line A/B before anyone acts on it.

## 2.3 Bugs: pipeline, allocation, export (lane P)

**[Bug | GF10-P1] CA:1122-1135 + :2632-2659 — the prefilter's score-ordered fill ignores `compatible`, so the R37 primary-stack floor and the R116 reuse ladder relax against a bank that could have satisfied them, and the record blames the bank.** VERIFIED-repro (lane 2) + coordinator re-read of CA:1074-1149.
```python
# CA:1132-1135
for k in order:
    if len(keep) >= keep_target: break
    _take(k)                       # keeps candidates every entry has already been marked incompatible with
```
Repro (60 candidates, 50 at stack size 3 with high score, 10 at size 4 with low score, E=2, `primary_stack_min_size=4`): `passed: True | milp calls: 3 | floor: applied_relaxed 4→3, relaxations 1 | assigned sizes [3, 3] | eligible size>=4 in full bank: 10`, with the WARN lines attributing both relaxations to the bank. A search-effort limit moved a strategy control, invisibly (CLAUDE.md "never trim … a strategy change … invisible in the certified output"). The comment at CA:2632-2636 claims the opposite. Fix: iterate only `selectable = [k for k if any(compatible[e][k])]`, keep the top-2 compatible per entry before the fill, and report `entries_emptied_by_prefilter`. Root `board-known (R36 F10)`; the ladder consequence and false comment are new.

**[Bug | GF10-P2] EP:5087-5118 — `manifest_strategy_state` reads only `bank_diagnostics`/`candidate_bank` holders; the three allocator ladders (`candidate_reuse`, `primary_stack_floor`, `five_stack_quota` relaxations, CA:3162-3250) are never read, so a Classic production row reads `state: unknown, evidence: absent` even when all three relaxed.** VERIFIED-repro. On the production `candidates_override` path `candidate_bank` is `{source, candidate_count}` and `bank_diagnostics` is not on the result, so `absent` is structural. CLAUDE.md's "a portfolio is clean when the relaxation counts are zero" is read off this field at T-5. Fix: read the three allocator blocks; have `execute_portfolio` return `primary_stack_floor`/`five_stack_quota` beside `candidate_reuse` (EP:569-570, :594-595). NEW (R64(a) covered bank holders only).

**[Bug | GF10-P3] DEM:887, :937-941, :955-971 — `validate_dk_entries_file` fails open when the salary pool is empty: any ten distinct ids certify `roster_legality_passed=True` with no warning.** VERIFIED-repro (valid header, zero rows → `passed: True, errors: [], warnings: []`) + coordinator re-read.
```python
allowed_ids = set(players) if players else {normalize_player_id(x) for x in (salary_player_ids or [])}
missing = [pid for pid in roster if allowed_ids and pid not in allowed_ids]        # :937 -- empty set, nothing missing
```
Masked inside `run_slate` by `salary_gate_passed`; live for `execute_portfolio` called directly, `populate_dk_entries_template` (DEM:1135-1192), and any tool validating against a truncated salary copy. Fix: error when `salary_csv_path` yields no players; refuse to grade with an empty `allowed_ids`. NEW (sibling of R177).

**[Bug | GF10-P4] EP:1098 vs :1029-1037 — `workflow_gates` merges over ANY derived gate against a derived False and records only the name, while `OVERRIDABLE_GATES = ("lineup_gate_passed",)` is "deliberately one entry and deliberately not a knob".** VERIFIED-read. `tools/build_asserted.py:43-46` accepts all six derived names including `salary_gate_passed`, which R133(4)'s own comment calls a way to certify a broken CSV. `overridden_gates` never reaches `diagnostics.json` (EP:518-520 write `assumed_gates` and `caller_asserted_gates` only). Fix: route supplied values through the same classifier and raise on a contradicted non-overridable gate; write `overridden_gates` into diagnostics. NEW.

**[Performance | GF10-P5] CA:2990-3100 — the three re-entry ladders re-solve after a proven infeasibility even when a slate-level `feasibility_check` failed, which R286 established no ladder can clear; worst case seven MILP solves × 30 s before one refusal, inside a 130 s bash ceiling.** VERIFIED-read. Fix: guard each re-entry on `not failing_feasibility_checks(feasibility_checks)`. NEW (R286 supplied the invariant that makes it provable).

**[Bug | GF10-P6] CA:2905-2950 — scipy status 3 (`unbounded`) and 4 (`other`) fall into the "proven infeasible" branch: `timed_out = scipy_status == 1`, everything else with no incumbent is diagnosed and labelled proven, and the ladders step on a non-proof.** VERIFIED-read; coordinator re-read. Fix: `proven = scipy_status == 2`; name status 3/4 as neither a proof nor a clock, skip the ladders. NEW.

**[Bug | GF10-P7] EP:349-387, :436-448 — any exception between `create_run` and the first `_blocked_result` strands the run at `status: building` with empty `errors`, indistinguishable from an in-flight build.** VERIFIED-read. Reachable raise sites: `select_and_assign_entries` ValueError on duplicate entry ids (CA:2460) or a candidate without a ten-slot roster (CA:1987); `_lineup_from_assignment` (EP:722); validator `_cap_count` on NaN (DEM:766); salary schema errors (EP:375, :821). One instance fixed at its trigger under R167; no general guard. Fix: wrap the body in `try/except Exception` → `_blocked_result(run, [f"{type(exc).__name__}: {exc}"], {..., "crashed": True})`. NEW.

**TechDebt (lane P):** GF10-P8 the validator's `_cap_count` (DEM:744-766) disagrees with `assert_fraction_cap` on R215(b)'s inputs (`_cap_count(20, True) = 20` silently disables the cap; NaN raises an unnamed ValueError), VERIFIED-repro; R215 CLOSED kept the copy "unchanged". GF10-P9 `roster_legality_passed` is a string-prefix partition (DEM:1080) and the embedded-pool error starts with `"entries "` so a wrong-draftgroup file reads legality-passed, caps-passed, passed=False. GF10-P10 `_gate_bool(float("nan"))` is True (DEM:146-154). GF10-P11 the R34 five-stack "preventive rung" is dead arithmetic: `S·⌈E/S⌉/E ≥ 1` always (EP:3041-3045). GF10-P12 two derivations of the inherent-overlap floor differ by one (EP:3199-3200 vs :3266-3267; R286's quoted remedy on 1940_9g was the tighter one). GF10-P13 `_diagnose_binding_constraints(E, …)` counts against `E` while caps resolved against `total`, over post-prefilter sets (adjacent to R166 / R36 F10). GF10-P14 a promotion refused by `verify_inputs_unmoved` leaves `manifest.certification.workflow_valid=True` under `status: blocked` (BSM:403-407 with EP:538-542). GF10-P15 `record_delivery` same-bytes branch overwrites a preflight `upload_ready` stamp with `candidate` (UM:296-308; rider to R269). GF10-P16 two candidate-id derivations (`""` at CA:1992 vs `L001` from `_candidate_id`), so an id-less bank under `apply_script_routing` is wholly incompatible, PLAUSIBLE. GF10-P17 a sorted `player_ids` set is accepted as an "ordered ten-slot roster" (CA:1957-1958). GF10-P18 default contest-shape literals disagree: `"large_field_gpp"` (EP:1462, :4489, :4769) vs `"large_wta"` (CA:1099, :2682; LSM:311). GF10-P19 `List`/`Tuple` used in 20+ annotations and never imported (EP:163); only `from __future__ import annotations` keeps the module importable. GF10-P20 `run_slate` never calls the "required intake front door": the pool report arrives as free-form `source_metadata["pool_report"]` (EP:4632) and, absent, the lineup gate passes on batting orders alone (EP:1323-1350). GF10-P21 a second Classic build for the same `(date, tag)` overwrites the delivered mirror in place (EP:4978-4981; `board-known R283` for the replay case). GF10-P22 `posture_allocator._find_archetypes_csv` resolves against `os.getcwd()` (PA:162-172).

## 2.4 Bugs: intake and projections (lane I)

**[Bug | GF10-I2] LDA:1704-1716 — `slate_date` falls back to the UTC calendar day; `build_slate.py` passes `{"games": []}` on the DK-covered path and never `now=`, so any build after 20:00 ET stamps tomorrow's date into the pool report and the platoon-age arithmetic.** VERIFIED-repro (`now=2026-07-10T01:30Z` → `slate_date 2026-07-10`). `repo_env.py:98-117` documents this exact class (R65) and enumerated three sites; this was not among them. The salary file carries the ET date in every `Game Info` cell and it is never consulted. Fix: `min(_salary_game_times(salary_map).values()).date()`, then feed date, then `today_et(now)`. NEW.

**[Bug | GF10-I3] paste_odds.py:211 — `re.split(r"\s*(?:@|vs\.?|at)\s*", …)` matches a bare `at` inside a team name: `"Nationals@Yankees"` → `['N', 'ionals@Yankees']`.** VERIFIED-repro. Loud (refuses), never silent. Fix: `r"\s*@\s*|\s+(?:vs\.?|at)\s+"`. NEW.

**[Bug | GF10-I4] team_codes.py:35-40 — `WAS` and `OAK` are absent from `DK_ABBREV_REMAP`; `to_dk_abbrev("WAS") → "WAS"`, `team_name_to_dk_abbrev("Sacramento Athletics") → None`.** VERIFIED-repro. Feed-side readers (`_select_slate_legs` LDA:312-315, status map :923-924, `parse_boxscore_feed` :1170) silently mint a `WAS@…` game_id that matches no salary `WSH@…`, and the side goes uncovered. `board-known (R82)` for the report; the two missing entries are new facts.

**[Bug | GF10-I5] LDA:404, :2139 — DK `Starting` slot tokens are read with `str.isdigit()`, so a pandas-round-tripped salary file (`"1.0"`…`"9.0"`) reads as unposted; `normalize_player_id` (SIM:151-152) already tolerates the `.0` form on the id column.** VERIFIED-repro (synthetic). R289's operator built exactly such a derived file. Degrades to "fetch needed", not a wrong lineup. Fix: one `_slot_token()` helper used at both sites. NEW.

**[Bug | GF10-I6] LDA:134-148 — `_http_get_json` catches `HTTPError`/`URLError` only; a read-phase `socket.timeout` and a `JSONDecodeError` on a proxy HTML body (the device-VM 403 CONNECT case CLAUDE.md documents) escape the `RuntimeError` contract. No fetcher retries.** VERIFIED-read. Fix: catch `(TimeoutError, socket.timeout)` and `ValueError`, scrub, re-raise as RuntimeError. NEW.

**[Bug | GF10-I7] EP:3803-3804 — one blank `AvgPointsPerGame` on any kept row raises and aborts the whole Classic build; the pool only warns (LDA:2351-2356) and nothing in `build_slate.py` supplies Base.** PLAUSIBLE (DK usually ships `0`). A posted call-up with a blank cell would kill the slate rather than degrade one row. Fix: `base = 0.0` with a `Notes` tag and a pool warning count. NEW.

**TechDebt (lane I):** GF10-I8 `refresh_confirmed_lineups` silently repairs Ceiling<Floor (PB:201-202) against MLB_Classic.md:155 and the CLAUDE.md hard guardrail; dead in practice, opposite policy. GF10-I9 two American→probability rules (`_american_to_prob(0) → 1.0` PB:588-592 vs `american_to_implied_prob(0)` raises LDA:2897-2903), `board-known (R264)`. GF10-I10 MLB_Classic.md governs neither the F1 numerics (`F1_MARGIN_RUNS_PER_PROB_GAP = 2.4`, de-parking, slate-mean ratio, 0.85-1.15 clip; PB:562-563) nor the F2 table (PB:58); grep of the four authority docs for the constant returns nothing. GF10-I11 two copies of a DST-approximation fallback (SIM:1727-1735, PF:251-273), both wrong Mar 8-14 and Nov 2-7 when `tzdata` is missing; `repo_env.now_et` has no fallback; `tzdata` is in `requirements.lock` only. GF10-I12 `xwoba_base_correction._read_salary_pool` (:92-103) is a second salary parser with no `Name + ID` fallback (`board-known R75` for the join). GF10-I13 `appg_of` reads only `AvgPointsPerGame` while `_pool_row` also accepts `AvgPointsPerContest` (LDA:1617 vs :1435). GF10-I14 `lock_time_by_game_id` is day-wide, so `slate_clock` can pick an off-slate matinee before the salary cross-check corrects it and blame "a doubleheader leg collision" (LDA:956/:1043/:2431; SIM:1848-1851), PLAUSIBLE. GF10-I15 paste probables parse only after a clock line (`seen_clock`, paste_lineups.py:411/:418), PLAUSIBLE. GF10-I16 two readers of DK `Starting=SP` with opposite two-arm policies (LDA:463-469 takes lowest id; paste_lineups.py:690-695 refuses; `R108` adjacent). GF10-I17 Ceiling<Floor check is NaN-blind for a supplied Ceiling (PB:119), PLAUSIBLE. GF10-I18 `compute_f5_factor` reads an unmatched venue as `park_run 1.0` with no marker (SIM:1658-1659; R127's silent-neutral class). GF10-I19 `iterrows`/per-cell `.at` loops in PB:175-216, :288, :420, :522, XB:75, EP:4012-4025 — tens of ms each on a 300-row frame, immaterial next to the MILP.

## 2.5 Bugs: Showdown, field, late swap (lane D)

**[Bug | GF10-D1] ST:1275-1334 — the R250 UTIL hold collides with a thesis lock, and the ladder answers by dropping the PLAYER CAP; realized exposure then breaches the cap the hold exists to protect.** VERIFIED-repro (lane 4) + coordinator re-read of ST:1268-1337.
A held player `X` in this thesis's `locks` (shootout locks the side's top-4 at ST:397; both_explode locks three at :518; duel hard-locks both SPs at :505) with the captain locked to `Y`: the lock says `cpt_X + util_X ≥ 1`, the hold says `util_X = 0`, `cpt_lock` says the one CPT is `Y`. Rungs 1-2 (ST:1310-1318) are infeasible ONLY because of the hold; rung 3 (:1320-1326) drops the cap together with the hold (`excludes=without_cap`, no `**util_kw`), readmitting every capped player, and counts `player_relaxed`. Repro on the MIN@CHC fixture, `{MIN:+150, CHC:-170}`, n=12: 2 hold-only-infeasible rungs, Busch 7/12 and Bell 7/12 against `player_cap_count=6` (58.3% under a 50% cap). At `{MIN:+300, CHC:-350}`, n=9: three players at 5/9 over a cap of 4 AND a `captain_budget_inversion` for Suzuki, the inversion R250 exists to prevent. Across 6 moneyline scenarios × n=6..30 the collision fired in 16 of 150 combinations. The R250 test class (test_showdown.py:2195-2202) builds every thesis with `"locks": []`; the CHANGELOG entry (:2587-2593) measured `player_relaxed 0` on that lock-free fixture. Fix: (a) at hold computation skip any `k` in this thesis's `locks` while `cpt_lock` is someone else and record `{"player": k, "yielded_to": "lock"}`; (b) insert a hold-only rung between 2 and 3 counted under `captain_budget_hold_relaxed`, outside `clean`. Test with locks on the held player and a `cpt_lock` elsewhere; assert `player_relaxed == 0` and realized max ≤ `player_cap_count`. Board: R250 CLOSED, incomplete.

**[Bug | GF10-D2] SD:206-241 — the Showdown melt never reads the salary file's `Excluded` column; R289's "both intake sites" missed the third, and the Showdown path has no pool report to count it.** VERIFIED-read; coordinator grep of `showdown*.py` for `Excluded`: zero hits. The exact 2026-09-01 workaround R289 records, staged on a Showdown file, ships a review-grade file rostering the excluded players with nothing on the record; preflight does not read `Excluded` either. Fix: read through `optimizer_v3.read_excluded_cell` (lazy import, the pattern SD:391 already uses), OR across the two role rows, fold into `excl` at SD:393-394, add `pool.excluded_column` to the Showdown brief. Board: R289 CLOSED, incomplete (third site).

**[Bug | GF10-D3] SD:550, :565, :584 + ST:1187-1191 + BS:3263-3264 — on the ladder path `proj_points` is the THESIS-WEIGHTED proxy (win_big prices the other side's bats at 0.40, duel prices every bat at 0.78), and R247(a)'s proxy-margin trigger compares those across theses as one scale, so a duel or blowout roster is flagged degraded by construction.** VERIFIED-read. The filed 1905_1g_sd sighting ("proxy 38.19 against a median of 54.87", CHANGELOG:1127-1128) is consistent with a 0.40-suppressed thesis rather than a bad roster. Fix: recompute `proj_points_base = 1.5·Base[cpt] + Σ Base[util]` from the unweighted `df` after each solve; have `showdown_degraded_entries` read it; label the weighted number `proxy_points_thesis_weighted`. NEW (R247(a) CLOSED; its Showdown reading is wrong).

**[Performance | GF10-D4] ST:1335-1341 — rung 5 has no `cpt_lock` guard; when the captain was already reassigned pre-solve (`cpt_lock is None`) it re-solves an argument-for-argument copy of rung 1 and re-pays `time_limit` (8 s), and `_record_lock_relaxation` at :1341 would record a lock relaxation for a slot with no lock.** VERIFIED-read. Fix: `and cpt_lock` on :1335 and :1341. NEW.

**TechDebt (lane D):** GF10-D5 melt keys a person on `(Name, Team)`, last writer wins on a same-name same-team pair (SD:224, :234-237), PLAUSIBLE. GF10-D6 captain-pool widening runs only when a contest id is known, and an empty `own_ladder` increments a relaxation counter for a slot with no captain (ST:891-919). GF10-D7 `--entries-count` on Showdown below the blank-row count always refuses and the refusal's remedy is to lower it further (BS:2565, :2677-2686). GF10-D8 `showdown_handedness` matches feed hitters to DK by RAW name with no `normalize_name` (BS:2283-2305; rider to R122). GF10-D9 doc drift: `references/showdown.md:10-12, 56` still says two controls at 0.33; `references/late_swap.md:124-128` hand-drive passes `None` contest shapes (the R66(a) default); SD:109-114 misdescribes preflight's bar; `contest_library.py:3-4` still claims to be "outside the audited engine"; the duel docstring and R211 claim `hard_locks` survive every rung while ST:1261-1266 drops any capped lock. GF10-D10 `contest_library._DEFAULT_REGISTRY` is never referenced, so trust-order tier 2 cannot fire unless a path is typed; `_money("$1,000") = 1.0` (:78-84). GF10-D11 `field_miner` smalls: `own_results.contest_name` always null (:2132); Showdown `salary_name_collisions` always `[]` (:421-428); a mine with no `--contest-id` dedupes under the winner's ENTRY id (:1513); `n_cheap` prices the CPT slot at the UTIL key (:952-955). GF10-D12 two implementations of "when does this game lock" (feed `game_date_utc` for swap, DK `Game Info` for preflight R287) with no per-game agreement check, PLAUSIBLE. GF10-D13 `tools/late_swap.py:661-662` targeted slices exclude only MAPPED-team pids, so unmapped pids are built into candidates the allocator then rejects (wasted slice budget on the path with the least clock). GF10-D14 `score_duplication_risk` has no production caller (FM:1233-1300; R77 class).

## 2.6 Bugs: operator tools (lane T)

**[Bug | GF10-T3] RE:472-473, VE:479-483, PF:777-805 — `--as-of` has three semantics in three sibling tools: repair leaves a naive value naive (then `TypeError` at VE:216), verify_export reads naive as UTC, preflight reads naive as ET (the documented one). A verify run with a bare ET stamp reads 19:40 as 15:40 ET, so games started 16:05-19:40 are NOT locked and "introduced from an already-started game" goes quiet.** VERIFIED-read. Fix: both import `preflight_upload.parse_as_of`. NEW.

**[Bug | GF10-T4] VE:512-519 — `verify_export` never runs `check_started_games`; its import list (VE:92-98) omits it while VE:8-13 claims parity with preflight. CLAUDE.md's R272 clause requires "both verify_export.py and preflight_upload.py exit 0"; a post-lock file with no `--parent` prints PASS here and FAIL there.** VERIFIED-read. Extends `R175`.

**[Bug | GF10-T5] PF:1652, :1685 — pitcher identity is `Roster Position == "P"`, never true on a Showdown file (CPT/UTIL), so the R114 declared-arm and R67 bullpen-game exemptions are dead on Showdown and a legal arm HARD-FAILS; the only way through is `--force`.** VERIFIED-read. Fix: also accept `Position ∈ {P, SP, RP}`. NEW.

**[Bug | GF10-T6] PF:2164-2170, :2296-2310 — `report["passed"]` is frozen before the R176 read-back can add a failure, so `--json` can print `passed: true` beside `verdict: blocked` and exit 2.** VERIFIED-read. Same shape R266 fixed for the advisory. Fix: recompute after :2310. NEW.

**[Bug | GF10-T8] BS:1840, :1863, :1618, :1934 — `--postures` and `--assume-gates` are parsed AFTER the pool build, enrichment and bank spend, and abort via `raise SystemExit(str)` = exit 1, outside the 0/3/4/10 contract; `main()`'s `try/except Exception` at :1835-1848 does not catch `SystemExit`.** VERIFIED-read. First bad moment: a `--postures 1234=wta` typo → 30-120 s spent, exit 1, autobuild logs "refused with no remedy" (GF10-T11). Fix: parse both in `main()` after `parse_args`, refuse at exit 4 with a payload. R167's shape on two more flags. NEW.

**[Bug | GF10-T9] BS:3618-3619, :3754-3756, :3655, :2347 — `--controls-override` and `--leverage` accept any JSON; a non-object crashes (`AttributeError` pre-staging for controls; `TypeError` inside `run_classic` after the pool build for leverage). autobuild's `lift_controls_override` (AB:187-190) already refuses non-objects; the producer does not.** VERIFIED-read. Fix: argparse `type=_json_object`. NEW.

**[Bug | GF10-T10] BS:2112, :2140-2223 — the certified Classic brief carries neither `mirror_error`, `delivered_sha256_error` nor `manifest_recorded`; when the mirror fails, `delivered_path` falls back to `runs/<id>/final/DKEntries.csv` and `status` stays `certified`. The Showdown brief carries both (BS:2902-2903). CHANGELOG:2276-2279 says the brief records `mirror_error`; the BRIEF does not.** VERIFIED-read. Board: R176(d) CLOSED, incomplete on the artifact half.

**[Bug | GF10-T11] AB:375-377, :396-473 — any child exit outside {0, 4, 10} is handled as a code-3 refusal; a crash (1) or argparse error (2) logs "refused with no remedy, errors=[]" and records neither `returncode` nor a stderr tail. `outputs/2026-09-01/_ab1.err` shows exactly that line.** VERIFIED-read. Also AB:393 reads `brief.solve.bank.jobs_attempted` on exit 10 but the partial payload (BS:1852-1859) has no `solve` (R285's shape, a third reader). Fix: refuse off-contract codes by name with `returncode` and `stderr[-2000:]` in the record. Extends `R285`.

**[Bug | GF10-T12] AB:496-508, :513 — `_decision_log_date`'s fallback `from mlb_engine.repo_env import today_et` is unguarded and `autobuild.py` never inserts REPO on `sys.path`, so under a bare `python tools/autobuild.py` every date-less stop crashes inside `_write`. 17 of `build_slate.py`'s 20 status payloads carry no `date`; R169(b) added it to three.** PLAUSIBLE (depends on the caller's `PYTHONPATH`; `sync_check.py:106-112` fixes this class for itself). Fix: `sys.path.insert(0, str(REPO))`; guard :507; `"date": args.date` on every payload after BS:3797.

**[Bug | GF10-T13] AB:302-317, :363-364, :475 + SKILL.md:135-138 — the supervisor's defaults (8 attempts × up to 110 s, 12-minute wall clock) cannot fit the runtime's ~130 s call ceiling (CLAUDE.md "Sandbox"), and the decision log is flushed only at terminal exits, so an outer kill loses every decision. First bad moment: the first run that grows the bank once.** VERIFIED-read against the documented ceiling. Fix: `_write` after every `dec.add`; a `--resume` that reads `autobuild_decisions.json`; cap attempts by the ceiling. NEW.

**[Bug | GF10-T14] tools/late_swap.py:552 — unguarded `json.loads(feed_path.read_text())` on the tool that runs closest to lock; a torn `lineups_feed.json` (R213's "ordinary consequence of a killed Cowork call") tracebacks at exit 1 with no `FEED BLOCKER` line.** VERIFIED-read. R213 CLOSED for `build_slate.main()` only; fourth door.

**[Bug | GF10-T15] tools/solver_probe.py:80-83 — exits 4 "missing inputs" whenever `data/slates/<date>/lineups_feed.json` is absent, which is the NORMAL state of a fully DK-covered slate (R143 makes no fetch and writes no feed, BS:3946-3951). CLAUDE.md step 3 mandates the probe before any build.** VERIFIED-read. Fix: treat an absent feed as `{"games": []}` and say so; guard the `json.loads`. NEW (R202 covers draftgroup naming).

**[Bug | GF10-T16] tools/qa_portfolio.py:637-644 (from BS:2356-2358) — `find_prior_file` falls back to "the one prediction file in outputs/<date>/" even when the brief's tag is known and does not match, so `--leverage` can feed another draftgroup's ownership prior into the MILP constraints (BS:2386-2389, :1822, :1981).** VERIFIED-read. Fix: refuse as AMBIGUOUS when the single hit's tag differs. NEW.

**[Bug | GF10-T17] BS:4007 vs :3973 — `supplied_feed_rejected` (wrong-slate `--lineups`) exits 3 while its sibling `supplied_feed_unreadable` exits 4; and R290(c)'s "eight `return 3` sites" is nine literal sites (1581, 1607, 2110, 2646, 2665, 2673, 2686, 2709, 4007) plus two conditionals (2224, 3131) at HEAD. Only 2110 and the two conditionals write a brief; SKILL.md:205-207 "exit 3 now always writes its brief" is false for the other seven.** VERIFIED-read. `board-known (R290(c))` with the count corrected before the governor is built.

**TechDebt / Security (lane T):** GF10-T18 `[Security]` `tools/wheel_fetch.py:38-51, :54-80` fetches wheels from PyPI without checking `digests.sha256`; a resumed partial is declared done by size alone, PLAUSIBLE. GF10-T19 the "mirrored" Game Info parser and ET fallback are not mirrors (PF:166-168/:251-273 vs SIM:1721-1748). GF10-T20 `preserve_prior_slate` lists `outputs/<date>/DKEntries{suffix}.csv`, a name the mirror never writes (BS:3903-3907 vs EP:4978-4981). GF10-T21 `ownership_pred.py:832-833` prints "nothing here reaches the optimizer", false since R246. GF10-T22 `fetch_slate_bundle.py:418-443` exits 0 with `lineups: None`; `--out`/`--venues` defaults are CWD-relative. GF10-T23 `audit.py` compile check and `changelog_debt` omit `skills/…/build_slate.py`, `MLB_Classic.md`, `MANIFEST.md`, `requirements*` (AU:989-993, :1902-1904; rider to R216/R180). GF10-T24 `qa_portfolio.py:1045` `--reference-dir` default is CWD-relative. GF10-T25 `--assume-gates`, `--ignore-pool-blockers`, `--declare-pitcher` are accepted and never read on Showdown (BS:2553-3131; R210(c) files `--postures` alone). GF10-T26 every exit 4 is logged as "inputs missing" (AB:385-388) though 4 covers seven statuses. GF10-T27 `csv.Error` escapes preflight's `except (OSError, ValueError)` (PF:2232-2236) and a malformed salary tracebacks in BS:3797-3799 before any exit-4 payload. GF10-T28 (rider to R242) the auto-resolve tests only `rostered ⊆ snapshot` (PF:493-497), so a SUPERSET draftgroup snapshot resolves and passes pool membership at 100%; cross-checking each rostered id's embedded `Salary` closes it stdlib-only. GF10-T29 `autobuild` never records `cmd` in the decision log despite R169(d)/R214's stated rationale (AB:320-353). GF10-T30 `build_asserted.py` never pins `PYTHONHASHSEED` (`board-known R179`).

## 2.7 Test assertion findings (lane X)

**[Bug | GF10-X1] test_core.py:4016-4036 — the R289 acceptance test is conditional and never executes the wiring: the frame is `pd.DataFrame(pool["projection_rows"])`, `_drop_excluded_rows` is called directly, and the lineup assert is `if lineup is not None:`, vacuous when the solver returns None.** VERIFIED-read; the production defect it should have caught is GF10-I1.

**[TechDebt | GF10-X2] String pins standing in for behaviour on money-adjacent claims:** test_core.py:3921-3941 (R288 export-validator allowance: four `assertIn(…, src)`, nothing runs the validator; the docstring calls it "the one that would have made the control unusable end to end"); test_upload_integrity.py:5754-5763 (R272's "touches no portfolio control": `assertNotIn` on source with a hand-excised comment; CLAUDE.md:181-186 calls this "the whole of the argument"); :5796-5798 (`assertIn("REVIEW-GRADE", source)`); :669-683 (`assertNotIn` of `urlopen` etc. in preflight source). Of 33 high-stakes samples: 19 counterfactual, 8 string pins, 5 conditional, 1 with zero assertions (test_core.py:11214).

**[TechDebt | GF10-X3] The wall-clock branch of preflight (`parse_as_of` PF:777-791, `datetime.now` PF:2096-2098), the path that printed the false PASS on 09-01, is exercised by exactly one test (test_upload_integrity.py:1703) and it asserts only `feed_autoresolve` fields, not the return code; since R287 that run exits 2 and the test cannot tell.** Every other preflight test runs under the injected `FIXTURE_AS_OF_BEFORE_FIRST_PITCH = "2026-07-25T18:00:00-04:00"` (:117-138).

**[TechDebt | GF10-X4] Suite shape:** 1,645 methods; 152 (9.2%) call a solver or pipeline entry; 126 (7.7%) read source or walk an AST (113 with no solver call); 42 read a `.md`; 1,182 of 5,207 assertions (22.7%) are `assertIn`/`assertNotIn`, 185 of them pinning ≥3-word English phrases. The nine golden-replay tests are the only MILP-through-export regression and cost ~17% of runtime. Three tests pin CLAUDE.md prose (test_core.py:11541-11546, :12664, :17771); test_core.py:9166-9176 and :11625-11628 pin SKILL.md and the runbook; test_upload_integrity.py:2316-2354 pins SKILL.md table cells. Trimming instruction prose reddens the gate.

**[TechDebt | GF10-X5] R155 class at HEAD:** test_core.py:13021 copies the live `data/reference/fangraphs_platoon_lineups.json` (ARCHIVE's write set; three sibling files are modified on disk now); :9567 pins against the real `dk_contest_paid_places.json`; :15737 runs `sync_check.py` behind an `.env`-exists guard (skipped in every clone); sync_protocol.md:147 records a clone printing `4 skipped` at an identical PASS count, so disk and clone run different subsets under one green line. Seams from ed7 still open: GF7-X1 (vacated game-cap pin, `R230(a)(d)`), X2 (`VALUE_GUARD_PCTL` unpinned downward), X3 (bank membership conditions-only fixture).

## 2.8 Board corrections and landing-vs-claim audit

Closed items shown incomplete at HEAD: **R289** (GF10-I1 production path; GF10-D2 Showdown melt; enumeration two of five); **R288** (GF10-S2: auto-bank and augmentation are members six and seven; brief `applied` copied from the request); **R250** (GF10-D1: hold-vs-lock interaction untested, cap breached); **R247(a)** (GF10-D3: Showdown proxy is thesis-weighted); **R272's safety argument** (GF10-T1/T2: the repair tool cannot write a clean file and admits a started player; the "touches no portfolio control" test is a grep); **R176(d)** (GF10-T10: brief half not landed); **R213** (GF10-T14: `late_swap.py:552` same class); **R169(b)** (GF10-T12: 3 of 20 payloads carry `date`); **R215** (GF10-P8: the kept validator copy disagrees on bool/NaN); **R286** (GF10-P5: the invariant it proved is not used to stop the ladders); **R164(b)** premise (GF10-S1: the skip's direction is own-team, the item says opposing); **R290(c)** count (GF10-T17: 9 + 2, not 8); **R285** (GF10-T11: third reader at AB:393, no `returncode` recorded).

Open items re-verified present at HEAD, no new evidence: R290(a)(b), R166, R174, R175, R177, R245, R281, R283, R248, R179, R216, R217(b)(c), R218, R180, R242, R202, R210(c), R268/R204, R207/R244/R203, R121, R284, R264/R265, R181, R195, R31(b)(c)(d), R86, R80(a)/R88, R82, R279, R225, R226, R227, R224(a)(b), R123 rider, R211(2), R208, R238/R239(a), R240, R66(a)(c), R68(a)(b)(c), R17, R73(a)(c)(d)(e)(f), R197, R115/R132, R230, R36 F10, R269.

MLB_Classic.md numerics vs code: xwOBA 100/50 PA shrink and clips, xISO 1.42 ± 0.30 with 1.25-1.60 clip, K-rate TBF 4.25, F4 priors and clips, value guard 0.90/1.08, Floor 0.58 / Ceiling 1.42, F5 composition all match. Ungoverned in the document: F1's `2.4` runs per probability gap, de-parking, slate-mean ratio and clip; the F2 table (GF10-I10). MLB_Classic.md:4 says optimizer v3.18 (audit pins v3.23); :517 says `v2.24.0` under a v2.26.0 title; :513 cites a retired checksum manifest, flagged by three prior reviews (docs/2026-07-19_red_team_review.md:112, ed6:416, backlog.md:6533).

## 2.9 Verified-clean census (so ed11 does not re-derive)

Classic MILP legality rows match DK MLB Classic (P/P/C/1B/2B/3B/SS/OF/OF/OF, $50,000, ≤5 non-P hitters per team, ≥2 games); anti-correlation algebra correct at k=0 and k≥M skip correct; suppression tiebreaker has no feasibility effect; time-limited incumbent verified against the same matrix and never climbs the ladder; no `list(set(...))` reaches any solver; every set→solver path is sorted. `excluded_flags`/`read_excluded_cell` is the one token rule and `_drop_excluded_rows` the one removal site in the optimizer. Bank cache dedupes on the ordered ten-slot roster, saves reload-union + tmp + `os.replace`, fails closed on unplaceable signatures. Allocation: `assert_fraction_cap` rejects bool/non-finite/>1; `_cap_count` `max(1, floor(total·pct + 1e-9))`; headroom ≥ 0; fixed-exposure keys agree between `fixed_portfolio_exposure` and the reader; incumbent acceptance verifies integrality, bounds and rows; ladders never step on a timeout; overlap rows exempt identical signatures on both sides. Pipeline: `_blocked_result` writes `status: blocked` and all three flags False; `resolve_gate_assertions` assumes None only and overrides `lineup_gate_passed` only; `validate_upload_ready_gates` drops None as Missing and blocks `FORBIDDEN_CALLER_ASSERTIONS`; `execute_portfolio` re-validates the FINAL file and binds `candidate_hash == final_hash`; `promote_run` CAS distinguishes no-pointer from unchecked; `_assert_parent_lineage` fails closed on an empty parent hash; `write_candidate_from_template` refuses Showdown, never writes in place, tmp+replace; `upload_manifest.deliver` orders write→record→promote with `DO_NOT_UPLOAD_` self-labelling on every failure path. Intake: one leg rule (`select_one_leg_per_matchup`) reached by every reader; `dk_side_readings` rejects duplicate/0/>9 slots; `merge_dk_starting_into_feed` seeds only where nothing complete holds the side; status tier drop precedes every selection branch; R60 posted-partial seeding never displaced by priors; PO barred from `pitcher_roles`; odds consensus de-vigs per book then averages in probability space with non-finite rejected; `_scrub` scrubs raw and URL-quoted key; `_et_day_utc_bounds` via ZoneInfo; every documented projection constant matches. Showdown: CPT 1.5× on points AND CPT-row salary on cost; no person in both roles; both teams; overlap counts the person; caps bind against realized counts on every rung including the captain slot (modulo GF10-D1's hold path); every rung increments each control it drops; Gale-Ryser check in correct max-flow form; time-limited incumbent verified; delivery ordering and review-grade labelling hold. Field miner parse grammar survives suffixes/hyphens/accents; ownership prior is NaN-safe and shape-map-checked at import. Late swap: aware UTC `now`; unknown lock state freezes the slot; unknown authorized ids raise; fully locked entries excluded and delta-protected; allocator fails closed on unmapped pids under `excluded_new_teams`. Tools: no tool fetches or posts to draftkings.com; `THE_ODDS_API_KEY` never printed; `--force` never exits 0 with failures anywhere; `is_delivered_file` resolves both sides; `parse_as_of` bare `HH:MM` is ET; units gate coerces and refuses pre-staging; refusal prints failing checks then the clock then the hint (R286); manifest stamping uses uuid tmp + replace and the R176 read-back; audit gate never prints the pinned line on a partial assembly and refuses stale fingerprints; `claim.take` is atomic mkdir; `extract_inbox_zips` flattens member names; `lineups_from_paste`/`odds_from_paste` write via tmp+replace and write nothing on a blocker.

# Section 3: Greenfield System Audit & Anti-Pattern Deconstruction

## 3.1 Context economics, measured

What a session reads before its first useful command (tokens ≈ bytes/4):

| File | Bytes | ≈ tokens | Who, when |
|---|---:|---:|---|
| `CLAUDE.md` | 47,862 | 12.0k | every session, auto-loaded |
| `skills/generate-lineups/SKILL.md` | 64,089 | 16.0k | every BUILD session |
| `git log --oneline -12` output | 28,854 | 7.2k | session-start step 1 (CLAUDE.md:354 says "~310 tokens") |
| ledger Quick Card item 1 (ONE physical line) | ~45,000 | ~11k | session-start step 4 (CLAUDE.md:459) |
| `MLB_Classic.md` | 50,995 | 12.7k | "governs strategy" |
| `docs/backlog.md` lines 35-1850 ("What do we tackle next") | 124,898 | 31.2k | every DEV session |
| `NEXT_SESSION_PROMPT.md` | 11,858 | 3.0k | DEV |
| mean CHANGELOG entry (956,971 B / 146 H2) | 6,600 | 1.6k | "read that entry in full" (CLAUDE.md:359) |

A BUILD session's nominal pre-build read is **46-59k tokens**; a DEV session's is **≈55k**. The whole instruction-plus-record corpus is ≈2.63 MB ≈ 656k tokens. The `git log` line alone is 23× its documented cost because 22 of 271 commit subjects exceed 500 characters (median 95, max 6,711: commit `5afbaef`'s subject is the entire R249 changelog entry).

Growth (by `git show <hash>:<file> | wc -c` at the nearest commit):

| Date | CLAUDE.md | SKILL.md | CHANGELOG.md | backlog.md |
|---|---:|---:|---:|---:|
| 2026-07-25 | 9,552 | 24,617 | — | — |
| 2026-08-01 | 14,601 | 37,820 | 150,847 | — |
| 2026-08-12 | 18,936 | 37,820 | 406,980 | — |
| 2026-08-24 | 34,933 | 52,192 | 662,256 | 506,242 |
| 2026-09-01 | 47,862 | 64,089 | 956,971 | 727,030 |

CLAUDE.md: 5.0× in 38 days, accelerating (+11.3 KB in 08-12→08-18, +12.9 KB in 08-29→09-01); 135 of 271 commits touch it. Ed7 reported the curve "at least flattened" at 33,975 B; it has grown 41% since. By section: Autonomy 11,649 B (24% of the file), Session start 7,785, Build contract 7,564, Multi-session 5,579, Hard guardrails 5,008; the four pure-rule sections (Context wall, Truthful labels, Authority, Scheduled tasks) total 1,696 B (3.5%). Of 41 paragraphs, 19 (46%) cite an R-number or a 2026 date; 4 carry `(Ben, 2026-…)` attributions; 3 carry verbatim italic quotes. Estimated composition: ~30% contract, ~12% procedure, ~55% incident narrative and rationale, ~3% stale. SKILL.md: 202 paragraphs, 45 (22%) dated or R-numbered; the H2 "The single build, when you want it directly" is 14,880 B with five unrelated H3s; `references/` holds 15% of the skill's text, the body 85%: not progressive disclosure, a second CLAUDE.md.

**Why the files only grow.** Three tests pin CLAUDE.md prose (test_core.py:11541-11546 `assertIn("CHANGELOG.md carries its entry", text)`; :12664 and :17771 pin the PASS line), two pin SKILL.md and the runbook (test_core.py:9166-9176, :11625-11628), one pins SKILL.md table cells (test_upload_integrity.py:2316-2354). Trimming wording reddens the gate. And the project's own doctrine, "every rule carries the incident that earned it", is executed as prose inside the rule file rather than as a pointer to a CHANGELOG entry.

## 3.2 One rule, N places (the R233 class applied to the documents)

| Rule | Live sites | Where |
|---|---:|---|
| bash timeout / ceiling (130 s / ~180 s / retired 45 s) | 11 | CLAUDE.md:430-433, :656-659; SKILL.md:566-577, :616, :665, :1053; NEXT_SESSION_PROMPT.md:4, :37-39, :66; sync_protocol.md:70-77; runbook.md:139-140 |
| gate command / pinned PASS line | 9 live + 3 stale | CLAUDE.md:414, :433, :447-448; SKILL.md:1053-1054; NEXT_SESSION_PROMPT.md:11, :19, :63-67; sync_protocol.md:77-79; **ledger Quick Card item 1 reads `1386 tests`, four moves stale, with 29 nested "(Corrected 2026-…)" parentheticals on one line**; sync_protocol.md:147 (`1217`), MANIFEST.md:10/:73 (`119`) |
| "never reduce the legal pool" | 8 | CLAUDE.md:199, **:204 (verbatim duplicate bullet five lines later)**, :495-496, :509; SKILL.md:34-36, :513-515, :698; autobuild.py:32 |
| truthful labels / never ROI | 9 | CLAUDE.md:10; MLB_Classic.md:6, :59, :204, :213, :217, :603; runbook.md:28; SKILL.md:30 |
| git lock sweep | 6 | CLAUDE.md:40-45, :446; SKILL.md:1064; NEXT_SESSION_PROMPT.md:45-49, :59, :165; sync_protocol.md:192-217 |
| preflight before upload | 5 | CLAUDE.md:151, :175, :481; SKILL.md:773, :1094 |
| DK manual / money wall | 5 | CLAUDE.md:469-484; SKILL.md:24-27; standings SKILL.md:22-23, :127-131; runbook guardrail 4 |
| read the clock from the clock | 4 | CLAUDE.md:646-650; SKILL.md:57-60 AND :62-67 (consecutive paragraphs); ledger QC item 3 |
| Showdown three controls + order | 3 | CLAUDE.md:672-709 (~3 KB); SKILL.md:910-967 (~4 KB); showdown.md:8-12 (stale: says two, 0.33) |

The code carries the same shape: the ten roster slots spelled three times (`ROSTER_SLOTS` DEM:36, `ENTRY_ROSTER_SLOTS` CA:1943, `CLASSIC.slots` RC:50); the DK `Game Info` regex twice, divergently (SIM:1721-1724 vs PF:166-168); the DST fallback twice, both wrong for the same weeks (SIM:1727-1735, PF:251-273); `--as-of` semantics three ways (GF10-T3); the salary parser twice (SIM:243-282 vs XB:92-103); the name normalizer three times (`R55`); the default contest shape two ways (GF10-P18); the inherent-overlap floor two ways (GF10-P12); the hash-seed re-exec three ways (GF10-S14); the American-odds conversion two ways (GF10-I9); the lock clock two ways (GF10-D12). Every one of this edition's "closed item incomplete" findings is this shape: R289 two of five, R288 five of seven, R213 three of four, R169(b) three of twenty, R271 eight of ten.

## 3.3 Contradictions between live files (quoted)

1. CLAUDE.md:656 "**The inner bash timeout is 130s. One number, this one.**" vs SKILL.md:616 `timeout 33 python -u …/build_slate.py` and :665 `timeout 33 python -u <cmd>`.
2. CLAUDE.md:429 "`tests.test_core` alone needs ~89s" vs NEXT_SESSION_PROMPT.md:43 "~68s warm" vs ledger line 19 "133.0s".
3. Test pin `1645` (CLAUDE.md:414, SKILL.md:1054, NEXT_SESSION_PROMPT.md:63) vs the mandated session-start read, ledger Quick Card item 1: `PASS v2.26.0 27 modules 1386 tests`.
4. `references/showdown.md:8-12` "**Two** portfolio controls … `max_cpt_exposure_pct=0.33`" vs CLAUDE.md:672-676 "THREE … 0.25 … 0.50".
5. `references/late_swap.md:146` instructs `verify_export.py … --locked-teams PIT,NYY`; SKILL.md:1111-1118 "**do not pass `--locked-teams` at all**" (the flag DK rejected 7 of 16 entries over).
6. MLB_Classic.md:4 "optimizer_v3.py v3.18" vs audit pin v3.23; :517 "`v2.24.0`" under a v2.26.0 title; :513 cites the retired checksum manifest.
7. MLB_Classic.md:202/511 and ledger QC item 7 name the FanGraphs K-rate loader; MANIFEST.md:55 says StatsAPI since R278; `git ls-files` still tracks `fangraphs_season_pitching.csv`.
8. `docs/cowork_archival_runbook.md:3-5` "Last updated: 2026-07-04 … The engine stays in the claude.ai project"; Job 2 runs `python fetch_slate_bundle.py` from the wrong directory; the standings skill (:127) still routes ARCHIVE to it.
9. sync_protocol.md:27-30 "**The mount has no network.** No Cowork session can `git pull` or `git push`" vs CLAUDE.md:372 "the audit FETCHES before measuring" and NEXT_SESSION_PROMPT.md:158 "measured `ahead: 2` this session".
10. CLAUDE.md:412-414 tells the session to run `python tools/audit.py --run-tests --terse`; CLAUDE.md:427 says that command "does not fit one Cowork bash call".
11. CLAUDE.md:295 "**A lineup Ben pastes outranks any API pull and is never re-fetched (R32).** R143 narrowed this: the paste is second…": a rule and its override in one paragraph.
12. CLAUDE.md:103-120 delegates the R157 exposure-cap rescue; autobuild.py:29-31 "WHAT IT WILL NOT DO, EVER: touch an exposure cap"; CLAUDE.md:116-118 concedes the gap.
13. CLAUDE.md:565-568 vs claim.py:81-83: `WRITE_SETS` omits CHANGELOG.md and requirements.lock (R31(c), open six weeks).
14. CHANGELOG.md:10496 reprices an item "as R102" while R102 is the sync protocol; renumbered to R103 at :9901 with the old text "left as written". Numbering is manual.
15. SKILL.md:1049-1054 runs the gate before a build "when there is time"; NEXT_SESSION_PROMPT.md:69 "run the gate LAST".

## 3.4 The LLM-versus-deterministic boundary

The record's own rule is right: parsing, joins, legality, feasibility, solving, exposure math and hashing are deterministic and are in code. What is NOT in code is the operating procedure, and the session is asked to execute it by hand under a lock window. Decisions SKILL.md/CLAUDE.md assign to the session that a script already can or should make:

| # | Decision the session makes | Asked at | Deterministic basis already present |
|---|---|---|---|
| 1 | resolve repo path, `env_probe --install`, light beacon, release beacon | SKILL.md:116-117, :95, :101 | pure shell; no single entry command chains them |
| 2 | confirm slate identity (games, first lock, contest ids, hashed vs generic upload names, mtimes) | SKILL.md:700-715 | `build_slate.py` computes the `slate` block (:717-721), only after staging |
| 3 | compute T-minus and walk the T-20/15/10/6/5 ladder | CLAUDE.md:629-653; SKILL.md:57-67 | `slate_clock.minutes_to_deadline` is in every brief (BS:2063-2072); R290(c) is the open governor |
| 4 | decide whether to fetch lineups; hand-roll a `urllib` call | SKILL.md:585-611 | `dk_order_coverage` already decides (BS:3923-3951) |
| 5 | read `feasibility.checks` with `passed=False` before `errors[]`; apply the named structural remedy | SKILL.md:69-88; CLAUDE.md:651-653 | `autobuild.py` does the structural half |
| 6 | the R157 exposure-cap rescue: open all three to 1.0, re-derive a target from the structural floors | CLAUDE.md:103-120 | fully specified arithmetic; autobuild refuses it (R203) |
| 7 | classify a pool blocker benign vs crosswalk | CLAUDE.md:225-240 | autobuild regexes; residual "cannot classify → ask" |
| 8 | emit the ownership prediction before the build, re-emit with `--base` after | SKILL.md:261-296 | separate manual step, "not optional" |
| 9 | run `qa_portfolio`, run `preflight_upload`, state the sha256 | SKILL.md:158, :773, :727-729 | separate manual steps; the R287 miss is literally "checked by nobody" |
| 10 | read brief fields against fixed verdict rules (`f1_games_priced==0`, `f4_platoon_applied==0`, `factors_inert`, `construction.mode`, `pool.basis`, `counted_relaxations.clean`) | SKILL.md:238-243, :462-468, :545-552, :898-903, :941-961 | every rule is a scalar compare; no verdict renderer |
| 11 | shell hygiene: stdout/stderr split, `python -u`, log under repo, capture `$?` before `head` | SKILL.md:640-670 | a wrapper would own it |
| 12 | sweep `.git/*.lock` in the same call as the git write | NEXT_SESSION_PROMPT.md:45-49 | no `tools/git_safe` |
| 13 | drive the five-call gate and hand-copy the PASS line into three docs | CLAUDE.md:427-457; SKILL.md:1081 | generated line, hand-maintained, drifted in the ledger |
| 14 | pick `--max-seconds`/`--per-build-seconds` to force the sliced bank | SKILL.md:138, :180, :618 | `solver_probe.py` exists and is not consulted by `build_slate` (and refuses on a DK-covered slate, GF10-T15) |
| 15 | choose the replacement in a repair, including the minimum-loss collateral downgrade | CLAUDE.md:139-150 | `repair_entry.py` implements the filter (and cannot write the file, GF10-T1) |

`autobuild.py` chains none of `preflight_upload`, `qa_portfolio`, `ownership_pred`, `claim` (grep: zero hits), so the documented "fast path" is one of at least seven mandatory processes. The nominal Classic build per SKILL.md is 7 tool processes plus one improvised check plus `TZ=… date` in every call; with pastes, a reference refresh, a re-emit and the gate, 14-16; `autobuild` itself may spawn eight child builds at up to 110 s each against a 130 s call ceiling (GF10-T13).

Where the LLM belongs and is correctly placed: paste-name disambiguation (`--resolve "W Wilson=Weston Wilson"`, the tool prints candidates and the session picks), the leverage direction "a DIRECTION TO TEST, never a number", QA's "leverage play or oversight" reading, posture choice per contest, roof state. Where a judgment is encoded as a pattern and should not be: autobuild's benign-blocker regexes (`(\d+)/9 hitters`, "no rosterable starter") are an LLM-shaped judgment ("DK never priced a called-up starter") frozen as a regex.

## 3.5 Autonomy blockers between the two clicks

1. Cold sandbox has no scipy every session; ~9 s, mandatory, hand-driven (SKILL.md:107-110).
2. `statsapi.mlb.com` and `api.the-odds-api.com` are proxy-gated in cloud sessions; DK's `Starting` covers order but ships no handedness, so F4 platoon is dead unless Ben pastes mlb.com ("still ask Ben for a paste when there is time", SKILL.md:462-472): a Ben action per slate to keep one factor alive.
3. FanGraphs platoon reference behind membership; canonical file untouched since 2026-08-05 (ledger QC 4a "STILL STALE … Open for Ben").
4. "No probable, no declared arm → ask Ben" (SKILL.md:1027-1029) inside a lock window, in tension with R272's "asking it spent Ben's clock".
5. The R157 rescue is manual `--controls-override` reasoning (CLAUDE.md:116-120).
6. The gate: 5 × ~130 s ≈ 11 min of session time before a build "when there is time".
7. Skill cache drift (R142): the loaded skill may not be the repo's.
8. Housekeeping the mount cannot do (`rm` refused): residue accumulates until Ben runs PowerShell.
9. Every item in 3.4 is a place the session stalls, mis-reads, or spends a call.

## 3.6 What the last eight days demonstrate

24,400 lines landed in 8 days. This edition found 3 Blockers and 35 Bugs, most of them on the surfaces that code touched. Two of the three Blockers sit inside the two most recent fixes. The pattern "fix closes N sites, class has N+1" has now paid twelve times (nine by the board's count plus GF10-I1/D2, GF10-S2, GF10-T14). R118, the head of Tier 2 and the instrument that would grade construction against the archive, has been the head of Tier 2 for six weeks and is unbuilt because Tier 1 refills daily. The "Do not build" list rejects decomposition for want of a named measurement; the measurement is this paragraph.

The record's ordering argument (measure first, R13 funds) is right and is not what is being challenged. What is challenged is the implicit premise that the current codebase is the vehicle that reaches the measuring instrument. At the current rate it is not, and the cost is paid in Ben's lock windows.

## 3.7 Deletion candidates (what goes, with the reason)

Remove or fold, in the order of least risk: `build_asserted.py` (fold into `build_slate --assert-gate`, then remove the unrestricted `workflow_gates` door, GF10-P4); `posture_allocator.py` (inert waterfall, documented as such); `contest_library.py` (no production caller since R17, dead default registry); `tail_candidate_scanner.py` (one caller, review-only); `score_duplication_risk` (no caller); the legacy half of `contest_allocator` (`assign_lineups_to_contests`, no production caller, mints certification flags for a solve that never ran); DU units machinery in `optimizer_v3` (disabled on the production scope, `_DU_AUTO` uncalled); `resolve_sp_pair_coverage_plan`/`validate_sp_pair_coverage` (tests only); `ensure_pinned_hash_seed` (zero callers) OR the two inline copies; one of the two Game Info parsers, one of the two DST fallbacks, two of the three normalizers, two of the three roster-slot tuples, two of the three `--as-of` readers, one of the two salary parsers, one of the two American-odds converters, one of the two default-shape literals, one of the two inherent-overlap derivations; 21 of `build_slate.py`'s 24 flags (Section 4.4 keeps three); autobuild's regex classification (replace with the engine naming its own blocker class); every dated incident paragraph in CLAUDE.md and SKILL.md (move to the CHANGELOG entry it cites, leave the pointer); the 1,816-line "What do we tackle next" narrative (replace with the 14-line queue table it wraps); the three tests that pin CLAUDE.md prose; every string-pin test that stands in for a behaviour test on a money-adjacent claim (GF10-X2).

# Section 4: Target Greenfield Architecture & Implementation Specs

## 4.1 Design position, stated against the record

The nine rejections of the "program family" stand: no run database, no artifact store, no orchestrator, no solver migration for its own sake, no signed manifests, no daemons, no field simulator ahead of R10/R13. The 2026-08-01 rejection of "a greenfield parallel package" was grounded in that spec's premise, a calibrated EV core R13 has not funded. This design has a different premise: **the same proxy engine, the same walls, the same labels, one tenth the code, one command, no session decisions in the critical path.** It asks Ben for one decision (Section 4.8), and it puts the measuring instrument (R118) first so the new engine is graded against the old one on the archive before it replaces anything. Everything in this section is a deterministic review proxy or a labeled prior; nothing here is EV.

## 4.2 Module architecture (`dfs/`, ~4,000 lines target)

```
dfs/
  contract.py        roster geometry + scoring table + DK legality rules, ONE owner (Classic, Showdown)
  clock.py           slate clock from Game Info; ET/UTC; started/locked per game; `now` injectable; no fallback DST table
  salary.py          DKSalaries parser (one), team-code remap (one), Excluded/Status/Starting readers (one each)
  lineups.py         per-side source ranking: DK Starting > paste > statsapi > boxscore(underway); one leg rule
  reference.py       Savant/StatsAPI/FanGraphs tables, refreshed by a SEPARATE scheduled task, read-only at build
  project.py         Base=APPG (or supplied) × F1..F5, Floor/Ceiling, xwOBA/xISO/K joins; constants in ONE table, doc generated FROM it
  ownership.py       satellite ownership prior (labeled prior); leverage as CONSTRAINTS, never objective, until graded
  model.py           ONE constraint-matrix builder per contract; built once per slate, objective swapped per solve
  candidates.py      k-best generation: seeded objective perturbation + no-good cuts; no accumulating overlap rows
  portfolio.py       assignment MILP: entries × candidates, caps as floor(pct·n), overlap pairwise, per-contest rules
  export.py          template writer (bare ids in the roster window, nothing else touched); sha256
  validate.py        the ONE legality validator; imported by export, by preflight, by swap; started-game check inside
  swap.py            late swap: frozen slots from clock, no new player from a locked game, same validator
  report.py          one-page report: sha256, clock, pool basis, exposure table, every relaxation, every warning
  replay.py          R118: grade a delivered file (or a policy) against an archived contest's per-player FPTS
  cli.py             `dfs build`, `dfs swap`, `dfs replay`, `dfs check`; exit contract 0/2/3/4 owned here
config/
  controls.yaml      posture defaults, caps, k, stack sizes; every key has one reader; schema-validated at load
```

Boundaries. Deterministic Python owns everything from click 1 to click 2. The Cowork session (or a scheduled task) does three things: runs `dfs build` when two CSVs appear, transcribes a paste when Ben provides one (`dfs paste lineups.txt`), and reads the one-page report to decide whether Ben uploads. No session reads a brief field against a rule; the report states verdicts. No session chooses which cap to relax; `portfolio.py` relaxes in the documented order and prints the count. No session computes T-minus; the report prints it and `dfs build` refuses to start a solve it cannot finish before the first lock. No session drives a supervisor loop; `dfs build` owns its own retries inside one process, inside one bash call, with the decision log flushed after every decision.

## 4.3 Mathematical formulations

Notation: players `p`, slots `s`, games `g`, teams `t`, entries `e`, candidates `k`. Salary `c_p`, projection proxy `v_p` (Ceiling for GPP postures, Floor for cash; Base_Projection only for the duplication reference). All objectives are labeled deterministic proxies.

**DK MLB scoring (the unit the proxy is in).** Hitters: 1B +3, 2B +5, 3B +8, HR +10, RBI +2, R +2, BB +2, HBP +2, SB +5. Pitchers: IP +2.25, K +2, W +4, ER −2, H −0.6, BB −0.6, HBP −0.6, CG +2.5, CGSO +2.5, no-hitter +5. Stated from the reviewer's knowledge; the DK wall bars a session from fetching the rules page, so Ben verifies once by hand and `contract.py` pins it with a dated comment.

**Classic single lineup** (kept from `optimizer_v3`, minus the redundant rows; measured 305 → ~170 rows on the 3-game frame):

```
x_{p,s} ∈ {0,1}   for s ∈ {P1,P2,C,1B,2B,3B,SS,OF1,OF2,OF3}, p eligible for s
y_g     ∈ {0,1}   per game
u_t     ∈ {0,1}   per team (primary-stack indicator)

max  Σ_{p,s} v_p x_{p,s}  + λ z                              z ∈ [0, 0.75] suppression tiebreak, z ≤ Σ_p b_p x_p
s.t. Σ_s x_{p,s} ≤ 1                          ∀p            one seat per player
     Σ_p x_{p,s} = 1                          ∀s            every slot filled
     Σ_{p,s} c_p x_{p,s} ≤ 50 000                           salary
     Σ_{p∈t, p hitter} x_p ≤ 5                ∀t            DK max hitters per team
     y_g ≤ Σ_{p∈g} x_p                        ∀g            game counted only if rostered      (DROP x_p ≤ y_g: redundant for a lower bound)
     Σ_g y_g ≥ 2                                            DK min games
     M_sp x_sp + Σ_{h∈opp(sp)} x_h ≤ M_sp + k  ∀sp          anti-correlation, k = max_opposing_hitters_per_sp (0 default; per SP)
     Σ_{h∈t} x_h ≥ m u_t,  Σ_t u_t ≥ 1                     primary stack of size ≥ m on at least one team (m from posture: 5-3, 4-4, 4-2-1 …)
     Σ_{h∈t'} x_h ≥ m₂ u'_{t'}, Σ u' ≥ 1, u'_t + u_t ≤ 1   secondary stack, distinct team (when the posture asks)
     Σ_{h∈opp(t)} x_h ≥ r u_t                                bring-back r ≥ 0 (posture)
     x_p = 1 (locks), variable removed (excludes, Excluded column, OUT status)
     Σ_{p∈L_j} x_p ≤ |L_j| − 1                ∀ prior L_j    no-good cut: forbids an identical roster only (see 4.4)
```
`v_p` carries F1 (implied team total ratio), F2 (batting-order table), F4 (opponent xwOBA quality × platoon prior), F5 (park/weather) multiplicatively as today; the constants live in one table in `project.py` and MLB_Classic.md's numerics section is GENERATED from it (closing GF10-I10 permanently). Batting-order adjacency inside a stack is a post-solve rerank term (adjacent pairs bonus), not a MILP term: it is a proxy for run-scoring correlation and stays out of the objective until graded.

**Candidate generation, sub-second target.** The measured cost driver is B&B on accumulating overlap knapsack rows (GF10-S9: 0.09 → 1.33 s per solve across ten lineups). Replace with: (1) the matrix is built ONCE per slate (removes 17-40 ms per solve); (2) candidate `i` maximizes `Σ v_p (1 + ε_{i,p}) x_p` with `ε_{i,p} ~ U(−δ, δ)` from a seeded generator (`PYTHONHASHSEED=0`, `numpy.random.default_rng(seed=i)`), `δ = 0.08` by default and recorded; (3) one no-good cut per prior roster (`Σ_{p∈L_j} x ≤ 9`), which is cheap and does not blow up B&B; (4) forced-coverage passes for every viable SP pair and every stackable team with `u_t = 1`, exactly as `build_diverse_candidate_bank` intends, with the opponent (not the own team) skipped under `k < m` (fixing GF10-S1) and every control on every solve (fixing GF10-S2); (5) `mip_rel_gap = 1e-3` for candidates (they are proxies; the assignment MILP below is solved to 1e-4). Expected: 60-150 candidates × 11-70 ms = 1-10 s single-process on scipy; with the matrix reused and four worker processes, ≤ 2 s for a 12-game slate. Showdown: 2n ≈ 40 binaries, every solve < 20 ms, a 20-entry portfolio < 0.5 s. `scipy.optimize.milp` stays the authority; the one measurement that could justify calling HiGHS directly (`highspy`, same binary, model reuse) is the per-call overhead, and it should be measured on the 6-game frame before anyone proposes it.

**Portfolio assignment** (kept from `contest_allocator`, with the prefilter made compatibility-aware, GF10-P1):

```
x_{e,k} ∈ {0,1},  y_k ∈ {0,1}  (y_k = 1 if candidate k used anywhere)
max  Σ_{e,k} w_{e,k} x_{e,k}                                w = per-entry min-max normalized shape score in [0,100]
s.t. Σ_k x_{e,k} = 1                          ∀e
     x_{e,k} ≤ y_k,  y_k ≤ Σ_e x_{e,k}
     Σ_{k ∋ p} Σ_e x_{e,k} ≤ ⌊pct_p · n⌋       ∀p            player cap (pitcher cap, stack cap, game cap same shape); ⌊·⌋ then max(1,·) when pct·n < 1
     Σ_{k ∋ (sp₁,sp₂)} Σ_e x_{e,k} ≤ R                        SP-pair repetition
     Σ_{e ∈ contest C} x_{e,k} ≤ 1               ∀C,k        no duplicate roster inside one contest
     y_i + y_j ≤ 1  for |L_i ∩ L_j| > L                      pairwise overlap (L = 6/4/3 by posture); NOT applied at generation
     Σ_e x_{e,k} ≤ reuse                       ∀k            per-candidate reuse
     x_{e,k} = 0 where incompatible (locked slots, authorized ids, excluded teams in a swap)
```
Caps are computed against the REALIZED entered set (`n` = entries being solved + frozen rows in a swap) and the validator recomputes them from the exported bytes with the SAME function (`validate.py` imports `portfolio.cap_count`; closes the R167/R215/GF10-P8 copy family). Relaxation order when infeasible: overlap → player exposure → captain lock (Showdown) → thesis/quota → floor, each counted, printed, and never reached while a SLATE-level structural check fails (GF10-P5). A `proven infeasible` label requires scipy status 2; status 3/4 is named as neither (GF10-P6).

**Showdown** (kept from `showdown.py`, correct as read):

```
cpt_i, util_i ∈ {0,1}
max  Σ_i (1.5 v_i cpt_i + v_i util_i)
s.t. Σ cpt_i = 1;  Σ util_i = 5;  cpt_i + util_i ≤ 1
     Σ_i (c^CPT_i cpt_i + c^UTIL_i util_i) ≤ 50 000        c^CPT is DK's own CPT-row price (1.5× UTIL), read from the file
     Σ_{i∈t} (cpt_i + util_i) ≥ 1                ∀t          both teams
     util_x = 0 for a player holding reserved captain budget ONLY while x is not locked in this thesis (GF10-D1)
```
Portfolio caps: `max_shared_players` 4 of 6 counting the person, `max_cpt_exposure_pct` 0.25, `max_player_exposure_pct` 0.50, per-contest captains `1 if n=1 else max(1, min(2, n−1))`, all enforced in the SAME assignment MILP as Classic rather than in a rung-by-rung ladder; thesis templates become objective multiplier vectors that generate candidates, and each candidate's reported proxy is the UNWEIGHTED `1.5 v_cpt + Σ v_util` (GF10-D3). Captain budget reservation (R250) becomes a lower bound `Σ_e x_{e,k: cpt=i} ≥ q_i` in the assignment MILP, where a hold cannot collide with a lock because there are no locks at assignment time.

**What earns EV language.** Nothing above. The path is the record's: `dfs replay` grades every delivered file against the archived contest's per-player FPTS (already in `player_table` of every `mined_*.json`), settles at the archived payout curve (F-48, accepted), conditions on archetype and field size, never pools. When enough graded slates exist, a calibrated per-player outcome model with a variance basis (sim-gate clause 3), separate seeded banks for selection and grading (clause 4), and a contest-conditioned field (R10) are what would let an objective be called expected value. R13 funds it or does not.

## 4.4 The command and its contract

`dfs build <slate_dir>`: reads `DKSalaries*.csv`, `DKEntries*.csv`, optional `lineups_paste.txt`, `odds_paste.txt`, `boxscores.json`; writes `outputs/<date>/DKEntries_<tag>.csv`, `report.md`, `run.json` (inputs' sha256, controls in effect, every decision, every relaxation count, solver statuses, elapsed). Flags, three: `--posture <name|contest_id=name,…>`, `--controls <yaml>` (schema-validated, refused pre-solve on any type or units error), `--as-of <ISO|HH:MM ET>` (replay only). Exit codes: 0 delivered and validator-clean; 2 delivered but validator-flagged (file present, DO_NOT_UPLOAD prefix, reasons in report); 3 nothing delivered because the file would be ILLEGAL (started game, blown cap, slot violation, empty pool); 4 inputs unusable (before any solve). A crash is exit 1 with a traceback and a `run.json` carrying `crashed: true`; nothing else may exit 1. Under the clock: `dfs build` measures one solve, projects the candidate pass, and if `projected > minutes_to_first_lock − margin` it reduces candidate COUNT (search effort), never the pool, and says so; at `T−5` it delivers the best legal file it holds (the T-schedule as code, R290(c)).

`dfs swap <delivered.csv>`: frozen slots from `clock.py` (players whose game started), `n` includes frozen rows, no new player from a started game, same validator, same report; refuses only on illegality.

`dfs check <file>`: the stdlib-only referee, importing `validate.py` (one legality module; no second regex, no second cap arithmetic), with the started-game check reading the same clock; exit 0/2/3/4; `--force` exits 4, never 0.

`dfs replay <mined.json> <file|policy>`: R118.

## 4.5 Zero-touch operational loop (between the two clicks)

1. **Click 1.** Ben downloads DKSalaries and DKEntries into `inbox/`. Nothing else is asked of him unless the report says so.
2. **Trigger.** A scheduled task (the project's primitive; no daemon) every N minutes during the slate window runs `dfs build inbox/` when a new pair is present; or the session runs it on request. Same command either way.
3. **Stage.** Slate identity from `Game Info` (games, first lock, contest ids); contest type from the entries geometry; inputs hashed into `run.json`.
4. **Lineups.** DK `Starting` per side (complete 1-9 only); paste file if present (transcribed by the session with `dfs paste`); StatsAPI with a 10 s timeout if reachable, else skipped and named; boxscore tier for any game underway. Every side's source and status in the report.
5. **Project.** APPG base, reference joins from the cached tables (refreshed by a separate `dfs refresh` scheduled task, never at build time), F-factors, Floor/Ceiling; the `Excluded` and `Status` columns carried through as columns, never re-derived (GF10-I1/D2 cannot recur because the frame IS the pool frame plus columns).
6. **Solve.** Candidates (4.3) then assignment; controls from `controls.yaml` merged with structural floors computed from the pool; every relaxation counted.
7. **Validate.** `validate.py` on the exported bytes: geometry, ids in pool, salary, slots, hitters per team, games, anti-correlation allowance, started games against the clock, caps recomputed, template preservation, reserved rows filled.
8. **Report.** One page: sha256, first lock and minutes remaining, pool basis per team, exposure table, relaxations, warnings, exit code meaning. Truthful-labels vocabulary enforced by a word list in `report.py`.
9. **Late news.** New paste or boxscore → `dfs swap` on the delivered file; same validator; the report states what changed and why.
10. **Click 2.** Ben uploads the file the report names, checking the sha256.
11. **After.** Standings CSV → `inbox/` → miner → archive → `dfs replay` grades the delivery. The ledger is written by the tool, not by hand.

Nothing in the loop reads or writes draftkings.com; no credentials are stored; every network call has a timeout and a named failure; the two clicks are constraints, not friction.

## 4.6 Instruction files, redesigned

CLAUDE.md ≤ 6 KB: context wall; truthful labels; the two walls; authority pointers (`contract.py`, `controls.yaml`, `MLB_Classic.md`); the one command and its exit contract; where the record lives (CHANGELOG for what changed, `docs/decisions/` for why, backlog table for what next). No dated paragraphs: a rule cites its R-number, the story lives in the CHANGELOG entry. SKILL.md ≤ 150 lines: when to run, the command, how to read the report, the four things that need Ben (roof, a paste, a declared arm, the upload). `references/` holds depth. The backlog's "What do we tackle next" becomes a 14-row table; session notes go to the CHANGELOG entry they belong to. Commit subjects ≤ 100 characters; the body carries the rest (fixes the 7.2k-token `git log`). No test pins instruction prose; the generated PASS line is checked by generating it.

## 4.7 Test strategy for the target

Property tests: every emitted lineup satisfies `contract.py` under an INDEPENDENT checker (not the builder's own matrix). Mutation tests per constraint family: delete the row, the test must fail (the game-cap and reuse seams from ed7 become the template). Golden equivalence: for every archived certified run, the new engine under the same controls and seed reproduces the delivered file byte-for-byte or the diff is graded by `dfs replay` against the archived field. Clock tests inject `now`, and ONE test builds a fixture whose game time is `now + 1h` at test time and runs the real clock path (GF10-X3). No `assertIn` on English; no `read_text()` of source as a stand-in for behaviour on a money-adjacent claim (GF10-X2).

## 4.8 Sequencing, and the one decision that is Ben's

1. **Land the three Blockers and the seven headline Bugs** in the current tree first (GF10-I1, T1, T2; S1, S2, P1, P3, D1, D2, T15). Each is S or XS and each is on the delivery path this week.
2. **Ship `tools/replay_contest.py` (R118) next**, before any further Tier 1 refill. The archive already carries what it needs; ed7 priced it and nothing has changed. This is the instrument that grades old versus new.
3. **Build `dfs/` beside `mlb_engine/`**, strangler-pattern: `dfs build` must reproduce the certified files of ten archived slates under matched controls, and where it differs `dfs replay` must show it no worse against the archived fields. Then `build_slate.py` becomes a shim; then it is deleted with the list in 3.7.
4. **Rewrite the instruction files** (4.6) in the same window; delete the prose-pinning tests.

The decision: step 3 is the "greenfield parallel package" the 2026-08-01 adjudication rejected, on a premise this design does not share. Building it is a Ben decision, priced at roughly the lines this repo added in the last eight days, and this edition recommends it on the measurements in Section 3.6. Steps 1, 2 and 4 are DEV's under the standing contract and need no decision.

**Addendum, same day (board merge).** On Ben's instruction the findings were merged into `docs/backlog.md` as R291-R303 and the queue was re-prioritized by prize impact, lift and dependency. The board's sixteen-slot list supersedes the sequencing above where they differ: the strangler engine is R302 at slot 14 behind a hard start condition (R118 built and ten deliveries graded), R118 is at slot 6, and the instruction-corpus restructure is R301 at slot 13. The adjudication paragraph above the list in the backlog is the record of why.

---

# Method appendix

**Lanes and files read in full:** (1) `optimizer_v3.py`, `bank_cache.py`, `roster_contracts.py`, `contest_shapes.py`, `determinism.py`, `tail_candidate_scanner.py`; (2) `execution_pipeline.py`, `contest_allocator.py`, `posture_allocator.py`, `build_state_manager.py`, `upload_manifest.py`, `dk_entries_manager.py`; (3) `live_data_adapters.py`, `slate_intake_manager.py`, `paste_lineups.py`, `paste_odds.py`, `platoon_order_adapter.py`, `team_codes.py`, `repo_env.py`, `projection_builder.py`, `xwoba_base_correction.py`, MLB_Classic.md §5-6; (4) `showdown.py`, `showdown_theses.py`, `field_miner.py`, `ownership_prior.py`, `contest_library.py`, `late_swap_manager.py`, `tools/late_swap.py`, the Showdown half of `build_slate.py`, `references/showdown.md`, `references/late_swap.md`; (5) `build_slate.py`, `autobuild.py`, `preflight_upload.py`, `repair_entry.py`, `verify_export.py`, `audit.py` in full, every other `tools/*.py` at argparse/main/exit/IO depth; (6) CLAUDE.md, SKILL.md, MLB_Classic.md, MANIFEST.md, both cowork docs, NEXT_SESSION_PROMPT.md, the standings skill, the runbook; structural greps of backlog and CHANGELOG; AST scan of every test body.

**Coordinator re-read (against the tree, by file tools):** EP:3750-3829 and :4434-4459 and :3100-3123 and :4785-4822 (GF10-I1, GF10-S2); RE:280-318 and :420-558 with PF:336-400 (GF10-T1, GF10-T2); OV3:4060-4087 and :4158-4174 and :4276-4320 (GF10-S1, GF10-S2); CA:1074-1149 (GF10-P1); DEM:878-947 (GF10-P3); CA:2897-2956 (GF10-P6); ST:1268-1337 (GF10-D1); grep `Excluded` over `showdown*.py` (GF10-D2); PB:96-135 (GF10-I1 stamp). Every other citation is the lane's, quoted with its line numbers.

**Environment events, disclosed:** the Cowork Linux workspace bridge died mid-review for lanes 1-4 ("Failed to create bridge sockets") after their early repros ran, and was denied to the coordinator for the second half of the session. Repros that completed and are quoted: GF10-I1 (frame count), GF10-I2 (UTC date), GF10-I3, GF10-I4, GF10-I5, GF10-S1 (13 attempts / 6 infeasible), GF10-S2 (`aug_without: 18`), GF10-S3, GF10-S4, GF10-S7, GF10-S9 (timings), GF10-P1 (allocator output), GF10-P2, GF10-P3, GF10-P8, GF10-P9, GF10-P10, GF10-D1 (7/12 under a cap of 6). Everything else is VERIFIED-read or PLAUSIBLE as labelled. The test gate was not run; the session-start measurement is the tree's own record. The write scope of this review is exactly two new files: this document and `docs/backlog_inbox/2026-09-02_REVIEW_greenfield-spec-ed10.md`. No existing file was modified, no claim taken, no engine path executed that writes, no git write command issued; one stale `.git/index.lock` left by `git status` was moved aside with a timestamped `mv` per R109.

**Verification census:** 3 Blockers (all coordinator re-read), 35 Bugs (12 VERIFIED-repro, 21 VERIFIED-read, 2 PLAUSIBLE), 6 Performance (2 repro, 4 read), ~55 TechDebt, 1 Security, 5 test-suite findings, 15 quoted document contradictions. Board: 13 CLOSED items shown incomplete, 47 open items re-verified present, 1 open premise (R164(b)) shown reversed, 1 count (R290(c)) corrected.

**For the landing session:** renumber GF10 ids from the current board max at commit time (R290 at review time); re-verify GF10-I1, T1, T2, S1, S2, P1, D1 at the landing head if not same-day. Suggested batch shape: I1 + D2 + S5 (the Excluded class, one enumeration: `grep -rn "Excluded" mlb_engine tools skills` with the hit list, per R233); T1 + T2 + T3 + T4 (the repair/verify clock family); S1 + S2 (the bank on every rung; re-scope R164(b)); P1 + P5 + P6 (allocator truth); D1 + D3 + D4 (Showdown ladder); T8 + T9 + T11 + T12 + T13 + T15 (lost-window doors); P3 + P4 + P7 (fail-open and crash doors); X1 + X3 (the two tests that would have caught I1 and the 09-01 PASS). Highest-value hand mutations: delete the `Excluded` carry at EP:3806 and watch the R289 test stay green (it will); delete the started-game guard in preflight and watch every test but one stay green under the injected 2026-07-25 clock; swap `Team` for `Opponent` at OV3:4172 and watch test_core.py:19843 stay green.
