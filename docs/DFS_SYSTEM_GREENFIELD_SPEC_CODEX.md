# DraftKings MLB DFS Greenfield System Specification and Code Audit

**Review date:** 2026-08-24  
**Reviewed checkout:** <code>a49bd6108caf6a01ee01efce9f9f12c7b17ec427</code> on <code>main</code>  
**Scope:** DraftKings MLB Classic and Captain Mode/Showdown generation, allocation, validation, late swap, archival, prompts, scripts, tests, and operating controls  
**Write scope:** this new report only; pre-existing tracked and untracked files were treated as immutable  
**Decision:** retain the legality, immutable-artifact, and final-byte verification concepts; replace the projection, simulation, field, portfolio-objective, orchestration, and prompt architecture before making any maximum-EV claim

## Executive verdict

The current repository is a large, thoughtfully defended **legal-lineup and provenance system**. It is not a calibrated expected-value engine. Its primary score is built from DraftKings AvgPointsPerGame plus deterministic multipliers and hand-tuned construction proxies. It does not produce a calibrated joint distribution of MLB outcomes, a contest-conditioned opponent field, exact scenario-by-scenario payout settlement, or a bankroll-aware portfolio objective. Consequently:

- “certified” currently means that the Classic file satisfied the repository’s workflow, legality, allocation, and byte-integrity gates. It does **not** mean the lineups have positive expected profit or maximum EV.
- Showdown is explicitly review-grade and bypasses the Classic certification chain.
- Several unresolved defects can misstate evidence, relax controls after a time limit, select the wrong salary snapshot, miscount Showdown people, or fail to persist the only diagnostic record of a timed-out run.
- The runtime could not be fully executed in this Windows/Python 3.13 session because the repository lock contains Linux CPython 3.10 wheel hashes and NumPy, pandas, and SciPy are absent. Static syntax parsing succeeded for all 73 Python files inspected; the repository audit stopped after 91 tests with missing-dependency failures. Dynamic solver correctness is therefore **not certified by this review**.
- “Zero human intervention” is a valid engineering goal only from an authorized input drop through a decision package. DraftKings login, contest entry, lineup upload/edit, and money movement remain user actions unless DraftKings supplies written authorization and an approved API. Browser botting is not part of the target architecture.

The rational rebuild is not a wholesale deletion. Preserve the hard-won safety kernel, place it behind typed interfaces, and replace the uncalibrated scoring and oversized orchestration layer in parallel. Promotion stays fail-closed throughout the migration.

### Evidence labels used in this report

| Label | Meaning |
|---|---|
| **REPRODUCED** | A deterministic command or focused input demonstrated the behavior in this checkout. |
| **STATIC-CONFIRMED** | The active source path proves the behavior without needing the unavailable numeric runtime. |
| **ENVIRONMENT-BLOCKED** | Runtime verification requires the pinned NumPy/pandas/SciPy environment, which is unavailable here. |
| **DESIGN GAP** | The required quantitative or operational capability does not exist; this is not a claim that a present function is buggy. |

# Section 1: Greenfield System Audit & Legacy Deconstruction

## 1.1 First-principles product definition

The target is:

> Given immutable, authorized slate and entry inputs plus time-stamped public evidence, construct legal candidate lineups; estimate their joint outcome and contest payout distributions without look-ahead; choose a portfolio that maximizes a declared expected-net-return/risk objective; independently re-derive every hard gate from final bytes; and emit a decision-ready package before the deadline without an agent waiting in a loop.

“Maximum EV” is not an observable property of one slate and cannot be certified from proxy scores. The production claim must be narrower:

> “Highest objective value found under model version M, field model F, scenario bank S, roster contract R, portfolio controls C, and solver tolerance T; independently evaluated on untouched referee scenarios.”

That wording is falsifiable. It names the model risk and prevents solver optimality from being confused with predictive truth.

### Hard invariants

1. DraftKings salary bytes own draftable IDs, salary, team, game, and position eligibility.
2. Reserved-entry bytes own Entry ID, Contest ID, contest identity, and untouched non-roster cells.
3. Every volatile fact has a source, retrieval time, event time, effective time, evidence state, and raw-body hash.
4. Missing, stale, conflicted, or unverified hard evidence yields <code>DO_NOT_UPLOAD</code>; it never becomes a neutral numeric factor.
5. Generation may fail open into a diagnostic artifact. Promotion and delivery fail closed.
6. The final CSV is reopened from disk and independently validated. In-memory objects are not delivery evidence.
7. No model is evaluated on facts learned after the prediction timestamp.
8. A solver time limit is <code>LIMIT</code>, not <code>INFEASIBLE</code>. A feasible incumbent is usable only after exact constraint revalidation and honest optimality labeling.
9. The LLM never performs arithmetic, joins, roster legality, exposure accounting, settlement, hashing, or CSV mutation.
10. DraftKings credentials, cookies, account actions, entry submission, and money movement are outside the engine.

## 1.2 What the current system actually is

The active flow is approximately:

~~~text
DK CSVs / public feeds
        |
        v
build_slate.py (3,325 physical lines)
        |
        +--> live_data_adapters.py (2,526)
        +--> slate_intake_manager.py (1,761)
        +--> execution_pipeline.py (4,343)
                    |
                    +--> projection_builder.py: APPG x F1..F5
                    +--> optimizer_v3.py: legal Classic MILPs + proxy ranking
                    +--> bank_cache.py: candidate job grid
                    +--> contest_allocator.py: joint assignment MILP
                    +--> dk_entries_manager.py: CSV write and validation
        |
        +--> separate showdown.py / showdown_theses.py branch
        |
        v
run directory -> promoted output -> preflight / verify / late swap
        |
        v
manual DraftKings upload
~~~

The system has accumulated 45,348 physical Python lines across 61 production/script files, before tests. Five functions exceed 500 logical lines; the largest reviewed functions are <code>build_slate_pool</code> (939), <code>select_and_assign_entries</code> (874), <code>build_multi_lineup</code> (595), and the main Classic/Showdown execution functions (roughly 500–580 each). This makes local changes hard to reason about and encourages duplicated validation definitions.

## 1.3 Preserve, rebuild, merge, quarantine, delete

### Preserve as design concepts

- Run-scoped immutable input snapshots and SHA-256 binding.
- DraftKings-template preservation and exact final-byte re-read.
- Separate candidate generation and reserved-entry allocation.
- Deterministic sparse MILP constraints and explicit incumbent validation in the Classic path.
- Typed roster-contract direction, late-swap Entry-ID authorization, and locked-slot preservation.
- Fail-closed hard gates and diagnostic-only degraded output.
- Post-slate standings mining and prospective calibration intent.
- Explicit prohibition on DK automation.

These are valuable controls. Preserve their behavior with characterization tests, not their present file layout.

### Rebuild

| Surface | Why the present design is insufficient | Greenfield disposition |
|---|---|---|
| Projection core | APPG multiplied by F1–F5 is a collection of labeled priors, not a predictive distribution. Ceiling/floor multipliers do not create joint outcomes. | Event/opportunity model plus calibrated scenario generator. |
| Field model | Historical summaries and ownership priors do not generate contest-conditioned opponent lineups or duplicates. | Conditional field generator calibrated by contest, stakes, slate size, and roster shape. |
| Objective | Ceiling, construction, and “field pressure” proxies are not expected payout. Several ownership terms are constant or dead. | Exact scenario settlement followed by expected net return and explicit risk utility. |
| Showdown | Separate solver and ladder, review-only delivery, role/person identity inconsistencies. | One roster-contract interface and the same evidence/certification lifecycle as Classic. |
| Orchestration | One oversized front door plus ad hoc wrappers, return codes, mutable pointers, and process retries. | Persisted finite-state machine with idempotent tasks, deadlines, leases, and typed outcomes. |
| Evidence | Booleans and prose strings allow “truthy stub” and false-enrichment states. | Typed evidence records: <code>PASS</code>, <code>FAIL</code>, <code>UNKNOWN</code>, <code>STALE</code>, <code>CONFLICTED</code>, <code>NOT_APPLICABLE</code>. |
| Configuration | Constants and strategy prose live across Python, CSV, CLAUDE.md, SKILL.md, and backlog history. | Versioned schemas with units, ranges, ownership, effective dates, and machine validation. |
| Evaluation | Historical results are not yet an untouched prospective forecast ledger. | Pre-lock forecast snapshots, rolling-origin evaluation, design/select/referee scenario separation. |

### Merge

- Merge <code>build_asserted.py</code> into the sole CLI as an explicit evidence-override command requiring evidence URI, actor, timestamp, reason, and allowed gate.
- Merge <code>verify_export.py</code> and <code>preflight_upload.py</code> behind one independent referee library and two thin commands.
- Merge Classic and Showdown roster geometry into a complete <code>RosterContract</code>; delete duplicated slot/cap definitions only after golden parity.
- Merge repeated JSON/CSV atomic-write, hash, finite-number, identity, timeout, and subprocess policies into shared libraries.
- Merge the separate “build brief,” “manifest,” “gate evidence,” and “promotion pointer” writers into one append-only run database plus exported signed manifest.

### Quarantine

- <code>assign_lineups_to_contests</code>, the legacy allocation path that can report certification on an empty entry set, has no production caller and should move behind a legacy import boundary until deletion.
- Scratch trees, cached wheels, local claims, and previous run/output trees must never participate in audit fingerprints or release packaging.
- Any lineup produced from stale/unknown/conflicted evidence belongs under <code>diagnostic/</code>, never <code>final/</code>.
- Existing heuristic projections remain a baseline model named <code>appg_factors_v1</code>. They must not inherit “EV,” “probability,” or “optimal” product labels.

### Delete after migration

- The wrapper-only <code>tools/build_asserted.py</code>.
- Duplicate validators and repeated cap arithmetic after the independent referee implementation has parity fixtures.
- Obsolete migration-seed <code>MANIFEST.md</code> and retired strategy sections after their valid contracts are moved to versioned references.
- Ignored scratch/archive residues and the tracked skill-creator workspace residue, after owner approval and archival verification.
- Incident narratives from always-loaded prompt files. Keep them in searchable history, one link away.

## 1.4 Quantitative deconstruction

### Current projection formula

The present framework is effectively:

~~~text
Base_i = DraftKings AvgPointsPerGame_i adjusted by xwOBA/value guard
Projection_i = Base_i * F1_i * F2_i * F3_i * F4_i * F5_i
Ceiling_i = Projection_i * player-specific or default multiplier
~~~

This can be a transparent prior, but it does not answer the questions that determine DFS EV:

- How many plate appearances will each hitter receive?
- Which events are shared through game state, lineup order, bullpen usage, and scoring?
- What are the tails and covariance of a five-man stack?
- How often does a pitcher earn the win/quality start or lose innings to weather, pitch count, or blow-up risk?
- How does the field construct lineups in this exact contest?
- How many copies share each payout?
- What is the net payout distribution after entry fees and ties?

Multiplying marginal point estimates cannot supply those distributions. “Ceiling” is not a quantile unless it is trained and calibrated as one.

### Minimum viable calibrated MLB model

For each scenario:

1. Sample game availability, start delay/postponement, roof, and lineup participation from evidence-conditioned distributions. Hard contradictions still block; uncertainty is modeled only where entry is legally actionable.
2. Sample starting pitcher batters faced, innings, pitch count, strikeouts, walks/HBP, batted-ball outcomes, earned runs, win/QS/CG events.
3. Simulate plate appearances in batting-order sequence with batter, pitcher, handedness, park, weather, umpire, bullpen, and base/out-state covariates.
4. Convert the same event stream to DraftKings hitter and pitcher points. This creates correlation rather than adding an after-the-fact stack bonus.
5. Score every candidate and opponent lineup on the same scenario.
6. Settle ranks, ties, duplicates, prizes, tickets, and entry fees exactly.

The first production version can use a hierarchical negative-binomial/opportunity model plus copula or residual game shocks, but it must be benchmarked against the event simulator. A faster approximation earns production status only if its portfolio rankings and payout estimates are stable on untouched slates.

### Portfolio objective

For portfolio \(P\), scenario \(s\), contest entries \(e\), payout \(q_{e,s}\), and fees \(f_e\):

\[
R_s(P) = \sum_e q_{e,s}(P) - \sum_e f_e
\]

Risk-neutral:

\[
\max_P \frac{1}{S}\sum_s R_s(P)
\]

Risk-aware:

\[
\max_P E[R(P)] - \lambda \operatorname{CVaR}_{\alpha}(-R(P))
\]

The user must choose the utility policy; “maximum EV” and “reduce bankroll drawdown” are different objectives. Report both mean net return and the selected risk statistic. Do not silently encode risk through arbitrary exposure caps.

Own entries can affect one another’s ranks and ties. Therefore an additive single-lineup reward approximation is not exact. Use a four-stage algorithm:

1. Generate a diverse legal candidate bank with Boolean roster MILPs.
2. Estimate single-entry marginal payout against an exogenous field.
3. Solve joint entry assignment with mean reward, covariance, overlap, duplication, and explicit caps.
4. Run deterministic exchange/local search using **exact full-portfolio settlement** on the selection scenarios.
5. Evaluate once on untouched referee scenarios. No selection decision may read referee results.

### Commercial benchmark, used carefully

Commercial documentation establishes a capability taxonomy, not proof that a vendor or this system has positive EV:

- [SaberSim’s contest-simulation description](https://support.sabersim.com/en/articles/12079199-how-contest-sims-work) describes play-by-play outcomes, contest-specific field lineups, exact payouts, ownership, and simulated ROI.
- [SaberSim late swap](https://support.sabersim.com/en/articles/12079563-using-late-swap) describes re-simulation after news while preserving locked players.
- [Stokastic’s MLB workflow](https://www.stokastic.com/articles/mlb-dfs/how-to-win-mlb-dfs) describes pitch-by-pitch simulations, ownership, stack analysis, and tournament simulation.
- [FantasyLabs’ optimizer](https://www.fantasylabs.com/tools/fantasy-lineup-optimizer/) and [MLB product](https://www.fantasylabs.com/daily-fantasy-sports/mlb/) emphasize projections, trends, stacking, ownership, and multi-lineup construction.

The greenfield bar is not “copy these claims.” It is: build those mechanics behind reproducible data lineage, then prove calibration and decision value prospectively.

Relevant academic anchors are Hunter, Vielma, and Zaman’s top-heavy DFS portfolio formulation ([arXiv](https://arxiv.org/abs/1604.01455)) and Haugh and Singal’s opponent-aware payout optimization ([Management Science](https://pubsonline.informs.org/doi/pdf/10.1287/mnsc.2019.3528)). They support modeling opponent behavior, payout structure, and portfolio dependence; they do not validate this repository’s current proxies.

## 1.5 LLM versus deterministic boundary

### Deterministic local code owns

- File discovery, byte hashing, schema/type/unit validation, CSV parsing, identity reconciliation, and artifact naming.
- Official API requests, retry/deadline policy, freshness, source conflict rules, and cached raw responses.
- All math: feature generation, distributions, simulations, lineup/field scoring, MILP/CP-SAT, exposure, allocation, settlement, and calibration.
- Clock and lock-cohort calculations.
- Final CSV writes, byte re-read, independent QA, manifests, promotion, and archival.
- State transitions and degraded-mode policy.

### The LLM may own

- Extraction of roof/status/lineup facts from an authorized unstructured public page when no structured source exists.
- Mapping a novel error or schema change to a bounded diagnostic proposal.
- Summarizing the decision package and explaining model/evidence uncertainty.
- Drafting a structured override request for human review.

Every LLM output must include a schema version, source URL, source timestamp, quoted evidence span or screenshot hash, confidence, and abstention reason. Deterministic code revalidates entity identity, units, time, and allowed vocabulary. One generation plus one repair attempt is the maximum; failure becomes <code>UNKNOWN</code>. An LLM cannot clear a hard gate.

## 1.6 Prompt and context audit

The always-reachable instruction surface is oversized:

| File | Current size or extent | Problem |
|---|---:|---|
| <code>CLAUDE.md</code> | 33,975 bytes | Standing contracts mixed with incidents, execution detail, and repeated workflow rules. |
| <code>skills/generate-lineups/SKILL.md</code> | 52,192 bytes / 950 lines | Front-door routing mixed with sandbox quirks, command transcripts, edge-case history, and mode-specific procedure. |
| <code>MLB_Classic.md</code> | 49,179 bytes | Strategy, implementation, tests, version history, and retired contracts in one file; version text contradicts itself. |
| <code>docs/backlog.md</code> | 5,000+ lines | Useful adjudication history but not an execution-time context source. |

Specific drift:

- <code>MLB_Classic.md:1</code> declares v2.26.0 while <code>:512</code> says the authoritative project version is v2.24.0.
- <code>MANIFEST.md:8-17</code> still reports 12 modules/119 tests and “remaining” work that has already shipped, while active instructions expect 26 modules/1,276 tests.
- The Classic prompt says probable pitchers join directly by MLBAM ID, while <code>projection_builder.py:883-905</code> now includes a name fallback and silently discards its collision report.
- Retired sections remain loaded beside active rules, so a model must infer which prose is operative.

[Anthropic’s context-engineering guidance](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) recommends the smallest high-signal token set and progressive disclosure instead of exhaustive edge-case lists. Its [agent design guidance](https://www.anthropic.com/engineering/building-effective-agents) favors simple composable workflows. Apply that directly:

~~~text
skills/generate-lineups/
  SKILL.md                 # <= 300 lines: trigger, inputs, one command, outcomes
  references/
    contracts.md           # immutable invariants and evidence states
    classic.md             # Classic-only workflow
    showdown.md            # Showdown-only workflow
    late_swap.md
    incident_index.md      # links and one-sentence morals, no transcripts
  schemas/
    inspect_result.schema.json
    build_request.schema.json
~~~

The skill should call <code>dfs inspect --json</code>, read a compact machine result, and route once. It should not rediscover files, dependencies, dates, contest mode, or recovery steps through prose.

## 1.7 Zero-touch and DraftKings boundary

The permitted target is **zero-touch between two deliberate user actions**:

1. User exports/drops the DraftKings salary and entries files.
2. User reviews the decision package and manually uploads/edits on DraftKings.

DraftKings’ current [Daily Fantasy Terms of Use](https://sportsbook.draftkings.com/legal/us-terms-of-use) prohibit automated means from interacting with or scraping the site, its [Fair Play Commitment](https://help.draftkings.com/hc/en-us/articles/4405223983635-Fantasy-Sports-Fair-Play-Commitment-US) specifically says browser scripts and bots are prohibited, and its [bulk lineup instructions](https://help.draftkings.com/hc/en-us/articles/4405223998867-How-do-I-upload-or-edit-multiple-lineups-at-once-US) describe a desktop CSV workflow. Therefore:

- Do not automate DK login, downloading, contest selection, reservation, upload, entry editing, submission, or money movement.
- Do not store DK passwords, cookies, tokens, or browser profiles.
- Do not use Claude in Chrome, Playwright, Selenium, or headless tools against DraftKings.
- Browser automation may read authorized public sources only when their terms and robots controls permit it; prefer official APIs.
- If DraftKings later provides written API authorization, implement it as a separately permissioned adapter with audit logs and a kill switch. It is not a hidden feature flag in this engine.

This boundary is not optional friction. It protects the user, preserves substantive decision-making, and removes an account-security failure domain.

## 1.8 Risk register

| Priority | Risk | Present consequence | Target control |
|---|---|---|---|
| P0 | No calibrated joint outcome/field/settlement model | Proxy optimization can be perfectly solved and still lose EV. | Prospective calibrated scenario and contest model. |
| P0 | Evidence booleans and false-positive paths | A gate can appear supported when the payload is merely truthy. | Typed evidence and minimum-evidence schemas. |
| P0 | Separate review-only Showdown path | No equivalent final-byte certification. | One lifecycle and referee for both contracts. |
| P0 | Wrong or unbound artifacts at promotion/preflight | Correct file can be validated against another slate or an unrecorded hash. | Content-addressed artifact relationships, no global “latest.” |
| P1 | Limit/infeasible conflation | The system relaxes strategy because compute expired. | Typed solver outcome and incumbent verifier. |
| P1 | Non-reproducible runtime | Audit cannot prove the current checkout on this supported desktop. | OCI image digest plus per-platform lock/attestation. |
| P1 | Monolithic orchestration | Errors cross concerns and are expensive to isolate. | Persisted task graph/FSM and small pure stages. |
| P1 | Same scenarios used to tune and report | Optimistic selection bias. | Design/select/referee banks and immutable RNG lineage. |
| P2 | Prompt and document drift | Agents spend tokens reconciling stale procedures. | Generated state card and progressive disclosure. |
| P2 | Mutable JSON registries and global pointers | Torn writes and concurrent-session cross-talk. | Transactional run DB and atomic published views. |

# Section 2: Comprehensive Code Review & Defect Log

## 2.1 Review method and limitations

The review enumerated tracked and untracked source surfaces, read the controlling instructions, parsed every Python file with the standard-library AST, indexed top-level functions/classes, inspected solver construction and status handling, traced Classic and Showdown flows, checked all subprocess/network call sites, and ran the repository’s own dependency probe and audit.

Observed results:

- Git HEAD: <code>a49bd6108caf6a01ee01efce9f9f12c7b17ec427</code>.
- Existing modified/untracked files were left untouched.
- 73 Python files parsed successfully; zero syntax failures.
- The active interpreter lacks NumPy, pandas, and SciPy.
- <code>python -B tools/env_probe.py</code> reported a cold environment and unavailable <code>scipy.optimize.milp</code>.
- <code>python -B tools/audit.py --run-tests --terse</code> failed the dependency gate and stopped after 91 tests.
- The lock is explicitly for Python 3.10/Linux x86_64; this review ran on Windows/Python 3.13.

Therefore static findings are exact to the reviewed checkout, but no claim below says the full 1,276-test gate or production MILP suite passed. Installing packages would have changed the workspace/environment and was outside this read-only review.

## 2.2 File-by-file disposition

This table covers every non-test Python surface in the reviewed production and command paths. “Rebuild” means preserve characterized behavior while moving it behind the target interfaces; it does not authorize an in-place rewrite.

| File | Disposition | Review conclusion |
|---|---|---|
| <code>mlb_engine/__init__.py</code> and package <code>__init__.py</code> files | Keep minimal | Empty namespace files are harmless; do not add runtime side effects. |
| <code>mlb_engine/contest_shapes.py</code> | Rebuild as schema | Contest taxonomy is useful but should be data with effective dates and validation. |
| <code>mlb_engine/determinism.py</code> | Keep/expand | Stable ordering and hash-seed reporting belong in the safety kernel. |
| <code>mlb_engine/repo_env.py</code> | Keep/limit | Repository environment loading is useful; accept an allowlist and never make arbitrary keys process-global. |
| <code>mlb_engine/team_codes.py</code> | Keep as reference adapter | Central normalization is correct; version mappings and preserve raw value. |
| <code>allocate/contest_allocator.py</code> | Split/rebuild | Joint assignment concept is correct; 2,984 lines mix scoring, feasibility, relaxation, solve, and reporting. |
| <code>allocate/posture_allocator.py</code> | Replace | Heuristic contest postures become explicit utility/risk configurations, not EV surrogates. |
| <code>entries/dk_entries_manager.py</code> | Split/keep referee logic | Preserve template/legality checks; move shared parsing and atomic writes to the artifact kernel. |
| <code>entries/upload_manifest.py</code> | Keep/rebuild | Good hash/promotion intent; use content-addressed relationships and mandatory hashes. |
| <code>field/contest_library.py</code> | Rebuild as transactional store | Pattern inference is useful only as labeled prior; registry I/O is unsafe and unversioned. |
| <code>field/field_miner.py</code> | Split/rebuild | Valuable parsers and archival data; role-blind Showdown duplication, winner ambiguity, pooled modes, and quadratic rewrite path must be fixed. |
| <code>field/ownership_prior.py</code> | Keep as baseline | Correctly labeled prior; it is not yet a contest-conditioned field generator. |
| <code>intake/live_data_adapters.py</code> | Split/rebuild | Useful source adapters but 2,526 lines combine transport, identity, DH resolution, evidence policy, and pool construction. |
| <code>intake/paste_lineups.py</code> | Keep at LLM/manual edge | Convert pasted facts to typed observations; never let paste clear a hard gate without provenance. |
| <code>intake/platoon_order_adapter.py</code> | Merge | Fold into feature/identity adapters after parity tests. |
| <code>intake/slate_intake_manager.py</code> | Split/rebuild | Salary parsing and slate clock belong in separate pure libraries; weather heuristics belong in the model. |
| <code>optimize/bank_cache.py</code> | Rebuild cache interface | Answered-job semantics are thoughtful; keys and job-grid generation need canonical dependency hashes and deduplication. |
| <code>optimize/optimizer_v3.py</code> | Preserve constraints, split | Classic MILP is the strongest core, but 4,277 lines include proxies, diagnostics, retries, and bank logic. |
| <code>optimize/roster_contracts.py</code> | Expand and make authoritative | Direction is correct; Classic does not consume it and the contract omits eligibility/team-cap/rule-version details. |
| <code>optimize/showdown.py</code> | Merge into contract solver | Legal formulation is compact; status handling is wrong and lifecycle is separate. |
| <code>optimize/showdown_theses.py</code> | Replace with scenario policy | Hand-authored thesis weights are not expected payout and the relaxation ladder can misreport controls. |
| <code>optimize/tail_candidate_scanner.py</code> | Quarantine baseline | Diagnostic proxy only; scenario quantiles should supersede it. |
| <code>pipeline/build_state_manager.py</code> | Replace with transactional FSM | Run-state idea is correct; use compare-and-swap transitions and leases. |
| <code>pipeline/execution_pipeline.py</code> | Decompose | 4,343 lines mix frame assembly, gates, allocation, writes, promotion, late swap, and reporting. |
| <code>projections/projection_builder.py</code> | Keep as named baseline | APPG/F-factor model remains a benchmark, not the target model. |
| <code>projections/xwoba_base_correction.py</code> | Merge into feature/model layer | Useful source transform; retain collision evidence and prospective versioning. |
| <code>swap/late_swap_manager.py</code> | Keep/rebuild | Entry authorization and parent integrity are strong; post-export locked-team re-derivation must become mandatory. |
| <code>skills/generate-lineups/scripts/build_slate.py</code> | Replace with thin CLI | At 3,325 lines it is a second application layer. It should parse one request and call the FSM. |
| <code>tools/audit.py</code> | Split/harden | Valuable independent gate; shared state, incomplete fingerprint, ignored output option, and unbounded suite calls undermine it. |
| <code>tools/autobuild.py</code> | Replace with FSM worker | Bounded attempts are good; command-string control composition and lost terminal logging are fragile. |
| <code>tools/awaiting_standings.py</code> | Keep as scheduled archival task | Must use transactional claims and typed “not available” outcomes. |
| <code>tools/build_asserted.py</code> | Delete after merge | Dynamic import/monkey-patch wrapper duplicates CLI behavior and bypasses one determinism guard. |
| <code>tools/claim.py</code> | Replace with DB leases | Filesystem claims are operational scaffolding, not a concurrency primitive. |
| <code>tools/env_probe.py</code> | Rebuild | Fail-closed pin checking is right; install/reprobe calls need deadlines and platform-aware locks. |
| <code>tools/extract_inbox_zips.py</code> | Harden | Flattening prevents traversal, but extraction is unbounded and non-atomic. |
| <code>tools/fetch_fangraphs_platoon.py</code> | Adapter | Add response caps, evidence schema, source license/terms metadata, and fixture contracts. |
| <code>tools/fetch_rotowire_lineups.py</code> | Adapter/review licensing | Same controls; do not make a commercial page an unqualified source of truth. |
| <code>tools/fetch_slate_bundle.py</code> | Split adapter | Timeouts and secret scrubbing are good; move transport policy to one client. |
| <code>tools/late_swap.py</code> | Thin CLI | Move retry/relaxation/clock decisions into the FSM and independent referee. |
| <code>tools/lineups_from_paste.py</code> | Keep edge tool | Produce observations only; no direct projection mutation. |
| <code>tools/net_to_date.py</code> | Keep report-only | Never feed retrospective totals into same-slate decisions. |
| <code>tools/ownership_pred.py</code> | Rebuild into field package | Useful baseline/grade skeleton; Showdown identity and false-applied reporting are unresolved. |
| <code>tools/preflight_upload.py</code> | Keep as referee entry point | Strong independent design; global latest-run resolution and Showdown exposure identity are money-boundary bugs. |
| <code>tools/promote_run.py</code> | Harden | Promotion must require a manifest hash, artifact relation, and all typed gates. |
| <code>tools/qa_portfolio.py</code> | Merge into referee/reporting | One source of portfolio metrics; no Classic-shaped fallback for Showdown. |
| <code>tools/rebuild_registry.py</code> | Replace with incremental materialization | Rebuild from append-only observations, partitioned by contest contract. |
| <code>tools/refresh_reference_data.py</code> | Adapter scheduler | Content-address raw responses; never mutate an active run’s inputs. |
| <code>tools/solver_probe.py</code> | Keep benchmark-only | Add representative fixtures, status assertions, and machine-readable timings. |
| <code>tools/stack_shape_probe.py</code> | Keep diagnostic-only | Stack-shape summaries are descriptive, not EV claims. |
| <code>tools/stage_slate.py</code> | Replace with ingest command | Stage by hashes and relationships, not shared date directories. |
| <code>tools/sync_check.py</code> | Keep outside slate critical path | Repository synchronization is not a lineup-quality gate. Avoid writing helpers under <code>.git</code>. |
| <code>tools/verify_export.py</code> | Merge into referee | Its divergence from preflight creates two meanings of “verified.” |
| <code>tools/wheel_fetch.py</code> | Remove from production flow | Build dependencies in CI into an immutable runtime image. |

### Non-Python configuration and reference surfaces

No PowerShell, shell, batch, or command scripts are present in the active source tree; operational scripting is Python. The non-Python surfaces were reviewed as data contracts:

| File/group | Disposition | Review conclusion |
|---|---|---|
| <code>requirements.txt</code>, <code>requirements.lock</code> | Replace build process | Floors plus a Linux-only hash lock are not a multi-platform runtime contract; use an image digest and per-platform attestations. |
| <code>.gitignore</code>, <code>.gitattributes</code> | Keep/harden | LF normalization and ignored runtime trees are useful. CI must separately reject tracked scratch/cache/output files because ignore rules do not clean existing residue. |
| <code>.env</code> | Secret-only, never artifact input | File presence was noted but values were not read into this report. Load an explicit key allowlist, use OS secret storage in production, and exclude the file/hash/content from manifests and prompts. |
| <code>data/reference/contest_library.json</code>, <code>dk_contest_archetypes.csv</code>, <code>dk_contest_paid_places.json</code> | Labeled prior only | Pattern/name inference cannot supply current contest economics. Add schema/effective date/source hash and require observed Contest-ID economics for EV. |
| <code>expected_stats_batting.csv</code>, <code>expected_stats_pitching.csv</code>, <code>fangraphs_season_pitching.csv</code>, <code>fangraphs_platoon_lineups.json</code> | Immutable raw/model inputs | Content needs source URL, fetch/as-of time, season, license, schema version, and prospective run binding. Never refresh a file under an active run’s path. |
| <code>f5_park_factors.csv</code>, <code>f5_weather_adjustments.csv</code> | Replace heuristics in predictive model | Preserve as baseline coefficients. Validate complete/non-overlapping bands, units, factor ranges, and effective dates. |
| <code>game_venue_overrides.csv</code>, <code>team_to_venue.csv</code> | Identity/reference input | Bitemporal game/venue IDs must supersede date/team text keys; manual roof assertions remain typed evidence. |
| <code>reference_manifest.json</code> | Expand | Bind every reference by hash, source, schema, as-of/effective time, and allowed model versions. |
| <code>field_opponent_registry.json</code> | Migrate | At roughly 6.8 MB it is a mutable derived database serialized as one JSON object. Move raw observations to append-only rows and build per-mode views transactionally. |
| <code>data/odds_history/*.json</code>, <code>data/order_history/*.json</code> | Preserve as raw observations | Add content hashes and observation/effective timestamps; exclude post-lock captures from pre-lock features. |
| <code>data/slates/*</code>, root <code>DKEntries.csv</code>/<code>DKSalaries.csv</code>/<code>slate_bundle.json</code> | Never shared authority | Treat only as import/drop locations. A run consumes a content-addressed snapshot; shared filenames are not lineage. |
| <code>skills/generate-lineups/evals/evals.json</code> and templates | Rebuild evals | Agent-routing evals should test compact tool use and safety boundaries, not encode engine math or stale command transcripts. |
| <code>MANIFEST.md</code>, <code>MLB_Classic.md</code>, <code>CLAUDE.md</code>, <code>SKILL.md</code> | Progressive disclosure | Preserve valid contracts, generate current state, and move incidents/history out of always-loaded context. |

## 2.3 Prioritized defect log

### C01 — The objective is not expected value

- **File & Line / Function:** <code>mlb_engine/pipeline/execution_pipeline.py:786-856</code> strategy defaults; <code>:2860-3335</code> projection assembly; <code>mlb_engine/optimize/optimizer_v3.py:2864-3556</code> contest-fit and field-pressure scores.
- **Severity:** **[Blocker]**
- **Evidence:** **DESIGN GAP / STATIC-CONFIRMED**
- **Issue description:** APPG, deterministic F1–F5 factors, ceiling multipliers, stack bonuses, and construction penalties are optimized as if they were payout value. There is no scenario payout variable, opponent field, or contest settlement. A solver can be mathematically optimal for this score while being economically dominated.
- **Remediation / corrected code:** Rename the present model to a baseline and make the optimizer consume scenario rewards only.

~~~python
@dataclass(frozen=True)
class ScenarioRewards:
    # net dollars, already settled against a contest-conditioned field
    lineup_ids: tuple[str, ...]
    scenario_ids: tuple[str, ...]
    net_usd: np.ndarray  # shape [lineup, scenario]

def expected_net_usd(rewards: ScenarioRewards) -> np.ndarray:
    if rewards.net_usd.shape != (len(rewards.lineup_ids), len(rewards.scenario_ids)):
        raise ValueError("scenario reward matrix has invalid shape")
    if not np.isfinite(rewards.net_usd).all():
        raise ValueError("scenario rewards contain non-finite values")
    return rewards.net_usd.mean(axis=1)
~~~

Do not expose <code>EV</code>, <code>ROI</code>, or <code>probability</code> until prospective calibration gates in Section 3 pass.

### C02 — No joint outcome, contest field, or exact settlement engine

- **File & Line / Function:** no production implementation; current closest surfaces are <code>field/ownership_prior.py</code>, <code>field/field_miner.py</code>, and proxy diagnostics in <code>optimizer_v3.py</code>.
- **Severity:** **[Blocker]**
- **Evidence:** **DESIGN GAP**
- **Issue description:** Marginal player points and historical construction summaries cannot price stack covariance, pitcher-versus-opponent conflict, duplicates, tie splitting, or contest-specific payouts.
- **Remediation / corrected code:** Add a settlement contract whose tests use hand-calculated ties and duplicates.

~~~python
def settle(scores: np.ndarray, prizes: np.ndarray, fees: np.ndarray) -> np.ndarray:
    """scores [scenario, entry]; prizes is 1-based rank schedule."""
    if scores.ndim != 2 or fees.shape != (scores.shape[1],):
        raise ValueError("invalid settlement shapes")
    out = np.empty_like(scores, dtype=np.float64)
    for s, row in enumerate(scores):
        order = np.argsort(-row, kind="stable")
        sorted_scores = row[order]
        payouts = np.zeros(row.size, dtype=np.float64)
        start = 0
        while start < row.size:
            end = start + 1
            while end < row.size and sorted_scores[end] == sorted_scores[start]:
                end += 1
            pool = prizes[start:min(end, prizes.size)].sum()
            payouts[order[start:end]] = pool / (end - start)
            start = end
        out[s] = payouts - fees
    return out
~~~

Production code must vectorize/batch this loop, but it must preserve these exact semantics.

### C03 — Showdown has a separate review-only certification lifecycle

- **File & Line / Function:** <code>skills/generate-lineups/SKILL.md:3-10, 704</code>; <code>skills/generate-lineups/scripts/build_slate.py:2240-2390</code> Showdown branch.
- **Severity:** **[Blocker]**
- **Evidence:** **STATIC-CONFIRMED**
- **Issue description:** Showdown explicitly never passes through the Classic workflow gates and is never upload-ready. This violates the requested unified zero-touch target and creates two definitions of correctness.
- **Remediation / corrected code:** Require all modes to use one lifecycle and declare differences only in the roster contract.

~~~python
def build(request: BuildRequest, contract: RosterContract) -> DecisionPackage:
    run = ingest(request)
    evidence = reconcile_evidence(run, contract)
    scenarios = simulate(run, evidence, contract)
    candidates = generate_candidates(run, scenarios, contract)
    portfolio = select_portfolio(run, candidates, scenarios, contract)
    return referee_and_package(run, portfolio, evidence, contract)
~~~

No mode-specific branch may bypass <code>referee_and_package</code>.

### C04 — Runtime lock is not reproducible on the reviewed desktop

- **File & Line / Function:** <code>requirements.lock:1-21</code>; <code>tools/env_probe.py:130-140, 191-198</code>.
- **Severity:** **[Blocker]**
- **Evidence:** **REPRODUCED**
- **Issue description:** The hash lock explicitly supports Python 3.10/Linux x86_64. The active Windows/Python 3.13 environment cannot install those exact wheels, so the nominal repository gate is not portable and this checkout’s full behavior cannot be reproduced here.
- **Remediation / corrected code:** Make the production runtime an immutable image and provide independently generated platform locks for supported developer environments.

~~~toml
# pyproject.toml
[project]
requires-python = "==3.12.*"
dependencies = ["numpy==2.2.6", "pandas==2.3.3", "scipy==1.15.3"]

[tool.dfs.runtime]
production_image = "ghcr.io/example/mlb-dfs@sha256:<immutable-digest>"
supported_locks = ["linux-x86_64", "windows-x86_64"]
~~~

The audit must record interpreter, OS/architecture, package hashes, HiGHS version, and image digest.

### C05 — Prospective calibration and scenario-bank independence are absent

- **File & Line / Function:** <code>ledger/</code>, <code>field/field_miner.py</code>, and strategy prose; no immutable pre-lock forecast record consumed by an independent evaluator.
- **Severity:** **[Blocker]**
- **Evidence:** **DESIGN GAP**
- **Issue description:** Retrospective standings mining is valuable, but without a prediction-time snapshot the model can accidentally consume later lineup, weather, ownership, or result information. Reusing scenarios for tuning, selection, and reporting makes performance optimistic.
- **Remediation / corrected code:**

~~~python
@dataclass(frozen=True)
class ScenarioBankKey:
    slate_hash: str
    model_hash: str
    purpose: Literal["DESIGN", "SELECT", "REFEREE"]
    seed: int
    created_at_utc: datetime

def assert_independent(*keys: ScenarioBankKey) -> None:
    purposes = {k.purpose for k in keys}
    seeds = {k.seed for k in keys}
    if purposes != {"DESIGN", "SELECT", "REFEREE"} or len(seeds) != 3:
        raise ValueError("scenario banks are not independent")
~~~

Forecast inputs, scenario key, candidate decisions, and final portfolio must be committed before standings are ingested.

### D01 — Audit fingerprint omits executable skill scripts and configuration

- **File & Line / Function:** <code>tools/audit.py:1007-1029 tree_fingerprint</code>.
- **Severity:** **[Bug]**
- **Evidence:** **STATIC-CONFIRMED**
- **Issue description:** The split audit fingerprints only Python under <code>mlb_engine</code>, <code>tools</code>, and <code>tests</code>. It omits <code>skills/generate-lineups/scripts/build_slate.py</code>, which tests and production execute, plus roster/config/reference inputs. A prior green gate can be reused after production behavior changes.
- **Remediation / corrected code:**

~~~python
FINGERPRINT_GLOBS = (
    "mlb_engine/**/*.py",
    "tools/**/*.py",
    "tests/**/*.py",
    "skills/generate-lineups/scripts/**/*.py",
    "data/reference/**/*",
    "requirements*.txt",
    "requirements.lock",
)

def tree_fingerprint(root: Path) -> str:
    paths = sorted({p for pattern in FINGERPRINT_GLOBS
                    for p in root.glob(pattern) if p.is_file()})
    rows = [f"{p.relative_to(root).as_posix()}:{sha256_file(p)}" for p in paths]
    return hashlib.sha256("\n".join(rows).encode()).hexdigest()
~~~

Record runtime identity separately; code hashes cannot prove interpreter/reference equivalence.

### D02 — Main audit and environment subprocesses can hang forever

- **File & Line / Function:** <code>tools/audit.py:844-852 run_test_suite</code>; <code>tools/env_probe.py:135-140 _reprobe_subprocess</code>; <code>:191-198</code> locked install.
- **Severity:** **[Performance]**
- **Evidence:** **STATIC-CONFIRMED**
- **Issue description:** These <code>subprocess.run</code> calls have no timeout. A deadlocked test, stalled package manager, filesystem bridge, or child process can block the zero-touch workflow indefinitely.
- **Remediation / corrected code:**

~~~python
def run_bounded(argv: Sequence[str], *, cwd: Path, timeout_s: float,
                env: Mapping[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            list(argv), cwd=cwd, env=None if env is None else dict(env),
            text=True, capture_output=True, timeout=timeout_s, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(f"{argv[0]} exceeded {timeout_s:.1f}s") from exc
~~~

Use a workflow deadline to cap all child timeouts; package installation is a build-time operation, not a slate-time recovery.

### D03 — Fraction controls omit per-game caps and accept non-finite/bool values

- **File & Line / Function:** <code>skills/generate-lineups/scripts/build_slate.py:117-129, 3106-3119</code>; <code>execution_pipeline.py:2215-2223</code>; <code>contest_allocator.py:1011-1043 assert_fraction_cap</code>; <code>dk_entries_manager.py:751-767</code>.
- **Severity:** **[Bug]**
- **Evidence:** **STATIC-CONFIRMED**
- **Issue description:** <code>max_game_exposure_pct_by_game</code> values are not validated by the front-door fraction list or merged-control validator. Game-cap helpers clamp values into [0,1], so <code>40</code> becomes 100% instead of failing. The shared validator accepts <code>nan</code>, infinities, and booleans because <code>float()</code> succeeds and only values above 1 are rejected.
- **Remediation / corrected code:**

~~~python
def fraction(value: object, *, key: str, allow_zero: bool = True) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{key} must be numeric, not bool")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be numeric") from exc
    low = 0.0 if allow_zero else np.nextafter(0.0, 1.0)
    if not math.isfinite(parsed) or not low <= parsed <= 1.0:
        raise ValueError(f"{key} must be finite and in [{low}, 1.0]")
    return parsed

game_caps = {
    game_id: fraction(raw, key=f"max_game_exposure_pct_by_game.{game_id}")
    for game_id, raw in raw_game_caps.items()
}
~~~

Use the same parser on ingest, solver construction, and independent QA, while keeping their arithmetic implementations independently tested.

### D04 — Autobuild loses its terminal decision on the outer wall-clock path

- **File & Line / Function:** <code>tools/autobuild.py:182-191 main</code>.
- **Severity:** **[Bug]**
- **Evidence:** **STATIC-CONFIRMED**
- **Issue description:** When the overall deadline expires between attempts, the code appends <code>stop</code> and returns 5 without calling <code>_write</code>. The most important post-mortem evidence is lost.
- **Remediation / corrected code:**

~~~python
if time.monotonic() >= deadline:
    dec.add(attempt, "stop", "supervised wall clock spent")
    _write(dec, last_brief, salary=a.salary)
    return 5
~~~

Better: the FSM commits every transition transactionally before returning.

### D05 — Autobuild replaces, rather than merges, user controls

- **File & Line / Function:** <code>tools/autobuild.py:184, 195-219</code>.
- **Severity:** **[Bug]**
- **Evidence:** **STATIC-CONFIRMED**
- **Issue description:** A user <code>--controls-override</code> inside passthrough works on attempt one. After the supervisor derives a structural floor, it appends a second JSON flag; argparse last-wins and drops every user key the supervisor does not own. The decision log then describes only the replacement dictionary.
- **Remediation / corrected code:**

~~~python
user_controls, passthrough = extract_json_option(
    shlex.split(a.passthrough), "--controls-override"
)
controls = dict(user_controls)

# Later, supervisor owns only explicitly delegated structural keys.
for key, value in applied.items():
    controls[key] = value
cmd += passthrough
if controls:
    cmd += ["--controls-override", json.dumps(controls, sort_keys=True)]
~~~

Reject duplicate/malformed options and persist <code>user_controls</code>, <code>derived_controls</code>, and <code>effective_controls</code> separately.

### D06 — Front-door lineup JSON reads can crash without a typed refusal

- **File & Line / Function:** <code>skills/generate-lineups/scripts/build_slate.py:3218-3219, 3257-3262</code>.
- **Severity:** **[Bug]**
- **Evidence:** **STATIC-CONFIRMED**
- **Issue description:** Supplied and staged lineup feeds use unguarded <code>read_text/json.loads</code>. Missing, concurrently replaced, truncated, or malformed files escape as exceptions, bypass the brief, and violate the documented return-code contract.
- **Remediation / corrected code:**

~~~python
def read_json_object(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InputRefused("LINEUP_FEED_UNREADABLE", path=str(path),
                           detail=str(exc)) from exc
    if not isinstance(value, dict):
        raise InputRefused("LINEUP_FEED_WRONG_SHAPE", path=str(path))
    return value
~~~

The CLI catches <code>InputRefused</code>, writes the run event, emits JSON, and exits with the declared input-failure code.

### D07 — Degraded DraftKings order merge treats any feed lineup as complete

- **File & Line / Function:** <code>mlb_engine/intake/live_data_adapters.py:676-696</code>.
- **Severity:** **[Bug]**
- **Evidence:** **STATIC-CONFIRMED**
- **Issue description:** The comment says a complete nine-player feed outranks DraftKings’ degraded eight, but the condition is merely <code>if side.get("lineup")</code>. A one-player partial feed wins, discarding richer DK evidence. The later warning says the surviving DK hitters were seeded even when they were not.
- **Remediation / corrected code:**

~~~python
feed_lineup = list(side.get("lineup") or [])
feed_complete = (
    str(side.get("lineup_status") or "").lower() == "confirmed"
    and {int(h["order"]) for h in feed_lineup if str(h.get("order", "")).isdigit()}
        == set(range(1, 10))
)
if feed_complete:
    keep_feed(side, team)
else:
    side = merge_partial_orders(
        primary=order, secondary=feed_lineup,
        primary_source="dk_salary_starting_degraded",
    )
~~~

The merge result must enumerate conflicts and per-slot provenance.

### D08 — DK batting orders are merged across every doubleheader leg before leg selection

- **File & Line / Function:** <code>mlb_engine/intake/live_data_adapters.py:622-674</code>.
- **Severity:** **[Bug]**
- **Evidence:** **STATIC-CONFIRMED**
- **Issue description:** Team-keyed DK orders are applied while iterating all feed games. Same-team doubleheader games can both match, causing wrong-leg upgrades/disagreements before salary start time selects the intended event.
- **Remediation / corrected code:**

~~~python
def choose_event(events: Sequence[Game], salary_start: datetime,
                 tolerance: timedelta = timedelta(hours=2)) -> Game:
    ranked = sorted(events, key=lambda g: abs(g.start_utc - salary_start))
    if not ranked or abs(ranked[0].start_utc - salary_start) > tolerance:
        raise EvidenceConflict("no feed event matches salary-file doubleheader leg")
    if len(ranked) > 1 and abs(ranked[0].start_utc - salary_start) == \
            abs(ranked[1].start_utc - salary_start):
        raise EvidenceConflict("doubleheader leg is ambiguous")
    return ranked[0]
~~~

Select by stable game ID/start time first; merge sides only into that event.

### D09 — Off-slate games can create lock-time blockers

- **File & Line / Function:** <code>mlb_engine/intake/live_data_adapters.py:1461-1469</code>.
- **Severity:** **[Bug]**
- **Evidence:** **STATIC-CONFIRMED**
- **Issue description:** <code>games_without_lock_time</code> is appended to blockers without checking whether the game belongs to the salary slate. A full-day feed can block a valid draftgroup because an unrelated game has an unparseable time.
- **Remediation / corrected code:**

~~~python
slate_game_ids = frozenset(player_game_by_id.values())
for rec in status.get("games_without_lock_time") or []:
    if rec["game_id"] not in slate_game_ids:
        continue
    blockers.append(lock_time_blocker(rec))
~~~

All evidence and gates must be scoped by draftgroup/slate identity before evaluation.

### D10 — F4 probable-pitcher name collisions are discarded

- **File & Line / Function:** <code>mlb_engine/projections/projection_builder.py:883-905</code>.
- **Severity:** **[Bug]**
- **Evidence:** **STATIC-CONFIRMED**
- **Issue description:** <code>_build_name_to_mlbam</code> returns a collision report, but the caller assigns it to <code>_</code>. A normalized-name collision is deterministically resolved to one MLBAM ID with no evidence warning, so the wrong pitcher row can silently drive a team-wide factor.
- **Remediation / corrected code:**

~~~python
sp_id_by_name, collisions = _build_name_to_mlbam(table, sp_row_by_id)
if collisions:
    sp_quality_unavailable.extend({
        "team": None,
        "probable": collision["name"],
        "reason": "ambiguous_savant_name",
        "candidate_ids": collision["player_ids"],
    } for collision in collisions)
    for collision in collisions:
        sp_id_by_name.pop(collision["name_norm"], None)
~~~

Identity ambiguity is <code>CONFLICTED</code>, not a “highest PA wins” fact.

### D11 — Showdown maps solver limits to infeasibility and triggers relaxation

- **File & Line / Function:** <code>mlb_engine/optimize/showdown.py:247-250, 354-366 build_showdown_lineup</code>; relaxation consumers in <code>showdown_theses.py:669-736</code>.
- **Severity:** **[Bug]**
- **Evidence:** **STATIC-CONFIRMED / ENVIRONMENT-BLOCKED**
- **Issue description:** SciPy returns <code>success=False</code> for a time-limited solve even when a feasible incumbent exists. Showdown returns <code>None</code> for every non-success status, and the thesis ladder interprets <code>None</code> as infeasibility and relaxes captain/overlap/player controls.
- **Remediation / corrected code:**

~~~python
@dataclass(frozen=True)
class SolveResult:
    status: Literal["OPTIMAL", "FEASIBLE_LIMIT", "INFEASIBLE", "LIMIT_NO_SOLUTION", "ERROR"]
    lineup: dict[str, Any] | None
    mip_gap: float | None

status = {0: "OPTIMAL", 1: "LIMIT", 2: "INFEASIBLE",
          3: "UNBOUNDED"}.get(res.status, "ERROR")
if status == "LIMIT" and res.x is not None and incumbent_is_feasible(res.x, matrix, lbs, ubs):
    return SolveResult("FEASIBLE_LIMIT", assemble(res.x), getattr(res, "mip_gap", None))
if status == "INFEASIBLE":
    return SolveResult("INFEASIBLE", None, None)
if status == "LIMIT":
    return SolveResult("LIMIT_NO_SOLUTION", None, None)
return SolveResult("ERROR", None, None)
~~~

Only <code>INFEASIBLE</code> may advance a relaxation ladder. See [SciPy’s MILP status contract](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.milp.html).

### D12 — Showdown floor rung drops the captain cap without accounting for it

- **File & Line / Function:** <code>mlb_engine/optimize/showdown_theses.py:716-743</code>.
- **Severity:** **[Bug]**
- **Evidence:** **STATIC-CONFIRMED**
- **Issue description:** The floor rung omits <code>cpt_excludes</code>, intentionally removing the captain cap, but increments <code>cpt_relaxed</code> only when a thesis captain lock was substituted. A cap breach without a lock can be reported as clean.
- **Remediation / corrected code:**

~~~python
before_cpt = set(cpt_excludes or ())
result = solve_without_controls(...)
if result.lineup is not None:
    selected = result.lineup["captain"]["player_key"]
    captain_cap_relaxed += int(selected in before_cpt)
    captain_lock_relaxed += record_lock_substitution(thesis, result.lineup)
~~~

Use separate counters and evidence fields for player cap, captain cap, captain lock, and overlap.

### D13 — Promotion permits a final artifact with no recorded manifest hash

- **File & Line / Function:** <code>tools/promote_run.py:165-175</code>.
- **Severity:** **[Bug]**
- **Evidence:** **STATIC-CONFIRMED**
- **Issue description:** Hash mismatch blocks only when <code>recorded_sha</code> is non-empty. If the artifact row or hash is absent, promotion continues, laundering an unbound file.
- **Remediation / corrected code:**

~~~python
recorded = (run_manifest.get("artifacts") or {}).get("final/DKEntries.csv")
if not isinstance(recorded, dict) or not recorded.get("sha256"):
    return _refuse("manifest does not bind final/DKEntries.csv to a sha256")
recorded_sha = require_sha256(recorded["sha256"])
actual_sha = sha256_file(source)
if not hmac.compare_digest(recorded_sha, actual_sha):
    return _refuse("final export differs from the run manifest")
~~~

Also require the manifest’s input hashes, contract version, and referee result before promotion.

### D14 — Preflight can resolve salary from an unrelated latest run

- **File & Line / Function:** <code>tools/preflight_upload.py:358-388 resolve_salary_from_promoted_run</code>.
- **Severity:** **[Bug]**
- **Evidence:** **STATIC-CONFIRMED**
- **Issue description:** The resolver reads a global <code>runs/latest_valid_run.json</code> and never inspects the entries bytes, contest mode, date, draftgroup, or delivery manifest. A same-day Showdown file can be checked against a Classic salary snapshot from another session.
- **Remediation / corrected code:**

~~~python
def resolve_salary(entries_path: Path, manifest_path: Path) -> Path:
    manifest = load_manifest(manifest_path)
    assert_artifact_hash(entries_path, manifest.require("delivered_entries"))
    salary_ref = manifest.require("inputs.DKSalaries.csv")
    salary = content_store_path(salary_ref["sha256"])
    assert_artifact_hash(salary, salary_ref)
    return salary
~~~

If the entries file has no manifest-bound salary relationship, preflight must require <code>--salary</code> and refuse auto-resolution.

### D15 — Showdown exposure is counted by role/draftable ID, not underlying person

- **File & Line / Function:** <code>tools/preflight_upload.py:1529-1542 advisory</code>.
- **Severity:** **[Bug]**
- **Evidence:** **STATIC-CONFIRMED**
- **Issue description:** Showdown CPT and UTIL are separate salary rows/IDs. Counting roster cells directly drops or splits the captain’s person exposure, understating concentration at the last money boundary.
- **Remediation / corrected code:**

~~~python
def person_key(row: Mapping[str, str]) -> tuple[str, str]:
    return normalize_name(row.get("Name")), normalize_team(row.get("TeamAbbrev"))

person_by_draftable = {pid: person_key(row) for pid, row in salary.items()}
counts = Counter(
    person_by_draftable[pid]
    for entry in filled for pid in entry.cells if pid in person_by_draftable
)
~~~

Captain-role exposure is a second counter, not a substitute for person exposure.

### D16 — American moneylines are aggregated in price space

- **File & Line / Function:** <code>mlb_engine/intake/live_data_adapters.py:2252-2279 parse_the_odds_api_totals</code>.
- **Severity:** **[Bug]**
- **Evidence:** **STATIC-CONFIRMED**
- **Issue description:** The median of American prices has no probabilistic meaning and, with two books, is their arithmetic mean. Opposite-signed pick’em prices can produce a near-zero or otherwise undefined synthetic line. The code then converts that synthetic price to an implied split.
- **Remediation / corrected code:**

~~~python
def consensus_two_way(book_prices: Mapping[str, tuple[float, float]]) -> tuple[float, float]:
    devigged = []
    for away_price, home_price in book_prices.values():
        pa = american_to_implied_prob(away_price)
        ph = american_to_implied_prob(home_price)
        total = pa + ph
        if not math.isfinite(total) or total <= 0:
            continue
        devigged.append((pa / total, ph / total))
    if not devigged:
        raise EvidenceUnknown("no complete two-way moneyline books")
    arr = np.asarray(devigged, dtype=np.float64)
    consensus = arr.mean(axis=0)
    return float(consensus[0]), float(consensus[1])
~~~

Never average American or decimal prices directly; aggregate normalized probabilities per complete book.

### D17 — “Enriched” projection tier is true when only the value guard ran

- **File & Line / Function:** <code>mlb_engine/pipeline/execution_pipeline.py:4221-4234 manifest_projection_tier</code>.
- **Severity:** **[Bug]**
- **Evidence:** **STATIC-CONFIRMED**
- **Issue description:** <code>value_guard</code> is included in the list that promotes a run from <code>proxy</code> to <code>enriched</code>. The value guard is an outlier clip, not new predictive evidence; default proxy builds can therefore carry a false enrichment label.
- **Remediation / corrected code:**

~~~python
PREDICTIVE_ENRICHMENTS = ("xwoba", "ceiling", "f4", "f1", "f5", "pitcher_ceiling")

def projection_tier(enrichment: Mapping[str, Any]) -> str:
    applied = [name for name in PREDICTIVE_ENRICHMENTS
               if evidence_applied(enrichment.get(name))]
    return "enriched" if applied else "baseline_proxy"
~~~

Record transforms such as clipping separately under <code>data_quality_transforms</code>.

### D18 — A truthy but schema-empty pool report can pass the lineup gate

- **File & Line / Function:** <code>mlb_engine/pipeline/execution_pipeline.py:1170-1205 derive_workflow_gates</code>.
- **Severity:** **[Bug]**
- **Evidence:** **STATIC-CONFIRMED**
- **Issue description:** Any non-empty mapping enters the pool-report branch. A stub such as <code>{"summary": "ok"}</code> has no blockers, teams, or thin teams and yields <code>lineup_gate_passed=True</code>. Presence is mistaken for evidence.
- **Remediation / corrected code:**

~~~python
class PoolEvidence(BaseModel):
    schema_version: Literal["pool-evidence/1"]
    slate_id: str
    teams: dict[str, TeamPoolEvidence]
    blockers: list[EvidenceBlocker]
    evaluated_at_utc: datetime

def lineup_gate(raw: Mapping[str, Any], expected_teams: set[str]) -> EvidenceState:
    try:
        report = PoolEvidence.model_validate(raw)
    except ValidationError:
        return EvidenceState.UNKNOWN
    if set(report.teams) != expected_teams:
        return EvidenceState.CONFLICTED
    return EvidenceState.FAIL if report.blockers else EvidenceState.PASS
~~~

Do not derive a hard gate from an optional dictionary’s truthiness.

### D19 — Ownership and leverage diagnostics contain dead or constant terms

- **File & Line / Function:** <code>mlb_engine/optimize/optimizer_v3.py:3035-3045 _low_owned_hitter_count</code>; <code>:3435-3556</code> field-pressure score; <code>execution_pipeline.py:3412-3413</code> default <code>Ownership_Tier="Mid"</code>; <code>tools/ownership_pred.py:18, 434</code>.
- **Severity:** **[Bug]**
- **Evidence:** **STATIC-CONFIRMED**
- **Issue description:** The production predictor explicitly never writes <code>Ownership_Tier</code>, while the frame defaults every row to <code>Mid</code>. Thus the low-owned count is always zero, ownership-total contributions can be constant, and “has duplication signal” can be true even without real ownership evidence.
- **Remediation / corrected code:**

~~~python
def ownership_pct(row: Mapping[str, Any]) -> float | None:
    raw = row.get("Projected_Ownership_Pct")
    if raw in (None, ""):
        return None
    value = float(raw)
    if not math.isfinite(value) or not 0.0 <= value <= 100.0:
        raise ValueError("ownership must be finite percent in [0,100]")
    return value

def low_owned_hitter_count(lineup: pd.DataFrame, threshold: float) -> int | None:
    values = [ownership_pct(row) for _, row in lineup.iterrows() if is_hitter(row)]
    if any(v is None for v in values):
        return None
    return sum(v < threshold for v in values)
~~~

If ownership evidence is absent, duplication/field-pressure diagnostics must be <code>UNKNOWN</code>, not zero or true.

### D20 — Showdown duplication keys ignore the captain

- **File & Line / Function:** <code>mlb_engine/field/field_miner.py:767-779</code>; <code>:1240-1248</code>; <code>:1339-1346</code>.
- **Severity:** **[Bug]**
- **Evidence:** **STATIC-CONFIRMED**
- **Issue description:** All three duplication calculations group on a slot-agnostic sorted player set. Two Showdown entries with the same six people but different captains have different salaries and scores, yet are counted as copies. Winner-copy and opponent recurrence statistics are inflated.
- **Remediation / corrected code:**

~~~python
def lineup_identity(entry: Mapping[str, Any], contest_type: str) -> tuple[Any, ...]:
    people = tuple(sorted(entry["players_norm"]))
    if contest_type == "showdown":
        captain = entry.get("captain_norm")
        if not captain:
            raise ValueError("showdown entry has no captain identity")
        return ("showdown", captain, people)
    return ("classic", people)
~~~

Use this one identity at all three sites and partition historical aggregates by contract.

### D21 — “Winner” selection is maximum points, not verified rank one

- **File & Line / Function:** <code>mlb_engine/field/field_miner.py:774-779</code>.
- **Severity:** **[Bug]**
- **Evidence:** **STATIC-CONFIRMED**
- **Issue description:** The miner selects the maximum parsed points row even if rank parsing failed or the file contains a partial/nonstandard export. It then labels that entry as the winner and propagates winner construction/copy statistics.
- **Remediation / corrected code:**

~~~python
rank_one = [e for e in complete if parse_rank(e.get("rank")) == 1]
if not rank_one:
    winner = None
    winner_state = "UNKNOWN_NO_RANK_ONE"
else:
    top_score = max(e["points"] for e in rank_one if e.get("points") is not None)
    winners = [e for e in rank_one if e.get("points") == top_score]
    winner = winners[0] if winners else None
    winner_state = "TIED" if len(winners) > 1 else "OBSERVED"
~~~

Never silently substitute maximum points for an absent rank.

### D22 — Opponent registry pools Classic and Showdown construction statistics

- **File & Line / Function:** <code>mlb_engine/field/field_miner.py:1300-1365 update_registry</code>.
- **Severity:** **[Technical Debt]**
- **Evidence:** **STATIC-CONFIRMED**
- **Issue description:** Per-user salary, stack, chalk, and duplication aggregates share one record. Classic and Showdown have different roster sizes, roles, salary geometry, and duplication definitions; pooled averages are not interpretable.
- **Remediation / corrected code:**

~~~python
bucket = (
    users.setdefault(username, {})
         .setdefault(contest_type, new_user_bucket(contest_type))
)
update_user_bucket(bucket, entry, lineup_identity(entry, contest_type))
~~~

The target store keys observations by <code>(contest_id, contest_type, entry_id)</code> and materializes per-mode views.

### D23 — Registry load/save is non-atomic and unvalidated

- **File & Line / Function:** <code>mlb_engine/field/contest_library.py:177-189 load_registry/save_registry</code>.
- **Severity:** **[Bug]**
- **Evidence:** **STATIC-CONFIRMED**
- **Issue description:** A malformed JSON file crashes loading; saving truncates the target directly. A kill, full disk, or concurrent process can destroy the registry. This is inconsistent with the atomic helper already present in <code>field_miner.py:1385-1392</code>.
- **Remediation / corrected code:**

~~~python
def atomic_json_replace(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp",
                                dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(value, fh, sort_keys=True, separators=(",", ":"))
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(name, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(name)
~~~

In the target, replace mutable registries with transactions and rebuildable materialized views.

### D24 — Final run JSON/CSV writers can leave torn artifacts

- **File & Line / Function:** <code>mlb_engine/pipeline/execution_pipeline.py:202-221 _write_json/_write_assignments</code>; similar direct <code>Path.write_text</code> calls across tools.
- **Severity:** **[Technical Debt]**
- **Evidence:** **STATIC-CONFIRMED**
- **Issue description:** Direct truncate-write is common on run and report artifacts. Unique run directories reduce collision risk but do not prevent a process kill from leaving validly named partial files that later discovery code can read.
- **Remediation / corrected code:** Use one atomic artifact writer, hash while writing, and make the manifest reference the hash only after replace succeeds.

~~~python
def publish_bytes(path: Path, payload: bytes) -> ArtifactRef:
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tmp.open("xb") as fh:
        fh.write(payload)
        fh.flush()
        os.fsync(fh.fileno())
    digest = hashlib.sha256(payload).hexdigest()
    os.replace(tmp, path)
    return ArtifactRef(path=str(path), sha256=digest, size=len(payload))
~~~

### D25 — Shared audit gate state can cross-contaminate concurrent sessions

- **File & Line / Function:** <code>tools/audit.py:943, 1032-1060</code>; <code>:2095-2103</code>.
- **Severity:** **[Bug]**
- **Evidence:** **STATIC-CONFIRMED**
- **Issue description:** Every session appends to one <code>.audit_gate/gate_units.jsonl</code>. Fingerprints reduce stale reuse but do not serialize concurrent writers or separate runtime identity. <code>--gate-report --output</code> ignores the output path, unlike the full-audit path.
- **Remediation / corrected code:**

~~~python
def gate_dir(root: Path, fingerprint: str, runtime_id: str) -> Path:
    safe = re.fullmatch(r"[0-9a-f]{64}", fingerprint)
    if not safe:
        raise ValueError("invalid fingerprint")
    return root / ".audit_gate" / fingerprint / runtime_id

assembled = gate_report(root, fingerprint=fingerprint, runtime_id=runtime_id)
if args.output:
    atomic_json_replace(Path(args.output), assembled)
~~~

Use one SQLite transaction per completed unit or per-run JSON files created with <code>O_EXCL</code>; never append uncoordinated shared evidence.

### D26 — Inbox ZIP extraction is vulnerable to decompression/resource abuse

- **File & Line / Function:** <code>tools/extract_inbox_zips.py:28-42 extract_zip</code>.
- **Severity:** **[Security]**
- **Evidence:** **STATIC-CONFIRMED**
- **Issue description:** Flattening to basename prevents path traversal, but the code reads each CSV member fully with no member count, uncompressed-size, compression-ratio, collision, or aggregate limit. An untrusted/broken export can exhaust disk/RAM or overwrite a same-basename file when <code>--overwrite</code> is used.
- **Remediation / corrected code:**

~~~python
MAX_FILES = 10
MAX_MEMBER = 100 * 1024 * 1024
MAX_TOTAL = 250 * 1024 * 1024
MAX_RATIO = 200

infos = [i for i in zf.infolist()
         if not i.is_dir() and i.filename.lower().endswith(".csv")]
if len(infos) > MAX_FILES or sum(i.file_size for i in infos) > MAX_TOTAL:
    raise ValueError("ZIP exceeds extraction policy")
seen = set()
for info in infos:
    name = Path(info.filename).name
    if not name or name in seen:
        raise ValueError("duplicate/empty flattened member name")
    seen.add(name)
    if info.file_size > MAX_MEMBER or (
        info.compress_size and info.file_size / info.compress_size > MAX_RATIO
    ):
        raise ValueError(f"unsafe ZIP member: {name}")
    stream_copy_bounded(zf.open(info), atomic_target(dest / name), info.file_size)
~~~

### D27 — Clock parsing silently drops malformed game rows

- **File & Line / Function:** <code>mlb_engine/intake/slate_intake_manager.py:1625-1635 parse_game_info_datetime</code>; <code>:1664-1698 slate_clock</code>.
- **Severity:** **[Bug]**
- **Evidence:** **STATIC-CONFIRMED**
- **Issue description:** An unparseable <code>Game Info</code> returns <code>None</code> and the clock simply skips that row. If at least one other game parses, <code>available=True</code> can be returned without naming incomplete coverage. A malformed earlier lock can make the delivery deadline late.
- **Remediation / corrected code:**

~~~python
parsed, missing = {}, {}
for player in players:
    gid = canonical_game_id(player)
    dt = parse_game_info_datetime(player.game_info)
    if dt is None:
        missing.setdefault(gid, player.game_info)
    else:
        parsed[gid] = min(dt, parsed.get(gid, dt))
state = "PASS" if not missing else ("FAIL" if not parsed else "CONFLICTED")
return ClockEvidence(state=state, locks=parsed, unparseable_games=missing)
~~~

Any incomplete slate clock blocks delivery and names the affected game.

### D28 — Weather-band boundaries can produce an unlabeled neutral

- **File & Line / Function:** <code>mlb_engine/intake/slate_intake_manager.py:1496-1500 _wind_band_for_speed</code> plus <code>data/reference/f5_weather_adjustments.csv</code>.
- **Severity:** **[Bug]**
- **Evidence:** **STATIC-CONFIRMED**
- **Issue description:** Closed intervals are data-defined, and any gap, overlap, below-minimum, or above-maximum value returns an empty band. Downstream lookup can silently fall back to neutral instead of surfacing a reference-table defect.
- **Remediation / corrected code:**

~~~python
def validate_bands(bands: Sequence[tuple[str, float, float]]) -> None:
    ordered = sorted(bands, key=lambda b: b[1])
    for i, (label, low, high) in enumerate(ordered):
        if not label or not math.isfinite(low + high) or low > high:
            raise ValueError("invalid wind band")
        if i and not math.isclose(low, ordered[i - 1][2]):
            raise ValueError("wind bands must be contiguous")

def wind_band(speed: float) -> str:
    hits = [label for label, low, high in WIND_SPEED_BANDS if low <= speed < high]
    if len(hits) != 1:
        raise EvidenceConflict(f"wind {speed} matches {len(hits)} bands")
    return hits[0]
~~~

Use a final unbounded high interval explicitly if intended.

### D29 — Classic and Showdown roster rules are not truly centralized

- **File & Line / Function:** <code>mlb_engine/optimize/roster_contracts.py:25-76</code>; docstring <code>:11-15</code>.
- **Severity:** **[Technical Debt]**
- **Evidence:** **STATIC-CONFIRMED**
- **Issue description:** The contract admits Classic still uses in-module constants. It omits max hitters/team, position eligibility logic, duplicate-person rules, role-specific salary/draftable identity, rule effective date, and contest-template recognition. Drift remains possible.
- **Remediation / corrected code:**

~~~python
@dataclass(frozen=True)
class RosterContract:
    id: str
    effective_from: date
    salary_cap: int
    slots: tuple[SlotRule, ...]
    max_people_per_team: int | None
    min_teams: int
    person_identity_fields: tuple[str, ...]
    template_schema: CsvSchema
    validate_extra: Callable[[Roster], Sequence[Violation]]
~~~

Both solver and independent referee consume the same immutable rule data but implement checks independently.

### D30 — Monolithic functions and repeated policy definitions make defects systemic

- **File & Line / Function:** <code>execution_pipeline.py:3620-4150 execute_portfolio</code>; <code>build_slate.py:2144-2390 run_showdown</code> and <code>:2790-3320 main/run path</code>; <code>contest_allocator.py:1940-2820 select_and_assign_entries</code>; <code>live_data_adapters.py</code> pool builder.
- **Severity:** **[Technical Debt]**
- **Evidence:** **STATIC-CONFIRMED**
- **Issue description:** Functions of 500–939 lines own parsing, policy, mutation, solve, recovery, I/O, and reporting. Repeated cap and evidence logic has already diverged. Unit tests must mock too much state and mutation coverage is weak.
- **Remediation / corrected code:**

~~~python
def execute(request: BuildRequest, services: Services) -> RunId:
    run = services.runs.create(request)
    for stage in PIPELINE:
        outcome = stage.execute(run, services)
        services.runs.commit_transition(run.id, stage.name, outcome)
        if outcome.state in TERMINAL_STATES:
            break
    return run.id
~~~

Each stage accepts immutable typed input, returns a typed outcome, performs one side effect through an injected port, and stays below an enforced complexity/line budget.

### D31 — Game-exposure solver test can pass for the wrong constraint

- **File & Line / Function:** <code>tests/test_core.py:1278-1293 test_game_exposure_cap_solver_and_validator</code>.
- **Severity:** **[Technical Debt]**
- **Evidence:** **STATIC-CONFIRMED**
- **Issue description:** The expected one-X/one-Y result can also be forced by the allocator’s default candidate-reuse cap. Removing the game-exposure constraint can leave the test green, so it does not prove the intended row exists.
- **Remediation / corrected code:**

~~~python
result = select_and_assign_entries(
    candidates=[candidate("X", g1, 100), candidate("Y", g2, 1)],
    entries=three_entries(),
    controls={
        "max_candidate_reuse": 3,
        "max_game_exposure_pct_by_game": {"G1": 1 / 3},
        "player_game_by_id": game_map,
    },
)
assert Counter(a["candidate_id"] for a in result["assignments"]) == {"X": 1, "Y": 2}
~~~

Add a mutation test that deletes the game-cap row and requires failure.

### D32 — Bank job grid repeats equivalent and provably impossible solves

- **File & Line / Function:** <code>mlb_engine/optimize/bank_cache.py:740-814</code>.
- **Severity:** **[Performance]**
- **Evidence:** **STATIC-CONFIRMED**; repository backlog records prior measured repetitions.
- **Issue description:** The Cartesian/rotating SP-pair × stack-team grid does not canonicalize problems after locks, excludes, or team incompatibility. Different jobs can collapse to identical MILPs, and impossible pitcher/team combinations still consume solver calls.
- **Remediation / corrected code:**

~~~python
def canonical_job(pair: tuple[str, str], team: str, ctx: SolveContext) -> JobKey | None:
    if not set(pair) <= ctx.viable_pitchers:
        return None
    if violates_pitcher_vs_stack(pair, team, ctx):
        return None
    effective_locks = tuple(sorted(set(pair) | ctx.locked_people))
    return JobKey(effective_locks, team, ctx.constraints_hash)

jobs = sorted({
    key for pair, team in raw_jobs
    if (key := canonical_job(pair, team, context)) is not None
})
~~~

Benchmark the optimized grid on representative 1/3/6/12-game Classic and Showdown fixtures before considering a solver migration.

### D33 — All portfolio controls are entry-count weighted, not capital weighted

- **File & Line / Function:** <code>mlb_engine/allocate/contest_allocator.py</code> exposure/candidate constraints; <code>execution_pipeline.py:960-980</code> fee parsing and controls.
- **Severity:** **[Blocker]**
- **Evidence:** **DESIGN GAP / STATIC-CONFIRMED**
- **Issue description:** One $15 entry and one $1 entry each count as one unit. If the intent is bankroll risk, player/game/stack/candidate exposure by entry count can leave most dollars concentrated. If the intent is lineup diversity, dollar weighting is wrong. The current configuration does not declare which policy it serves.
- **Remediation / corrected code:**

~~~python
@dataclass(frozen=True)
class ExposurePolicy:
    basis: Literal["ENTRY_COUNT", "AT_RISK_USD"]
    max_player_fraction: float

def exposure_weight(entry: Entry, policy: ExposurePolicy) -> Decimal:
    return Decimal("1") if policy.basis == "ENTRY_COUNT" else entry.fee_usd
~~~

Report both count and dollar exposure. Require an explicit user-owned policy; never infer it from contest name.

### D34 — Independent post-export late-swap rails are incomplete

- **File & Line / Function:** <code>mlb_engine/swap/late_swap_manager.py:339-369 validate_late_swap_delta</code>; <code>tools/verify_export.py:303-399</code>; separate preflight path.
- **Severity:** **[Blocker]**
- **Evidence:** **STATIC-CONFIRMED**
- **Issue description:** The manager verifies authorized Entry IDs and changed cells but does not independently re-derive the “no newly introduced player from a locked team” rule from final bytes. That logic lives in a separate verifier whose checks and manifest/contest parity differ from preflight. A production guarantee exists only if the caller remembers the right tool and inputs.
- **Remediation / corrected code:**

~~~python
def referee_late_swap(parent: Entries, child: Entries, salary: SalaryPool,
                      clock: ClockEvidence, authorized: frozenset[str]) -> Result:
    violations = []
    violations += compare_template_and_entry_ids(parent, child)
    violations += reject_unauthorized_roster_changes(parent, child, authorized)
    violations += preserve_locked_slots(parent, child, salary, clock)
    violations += reject_new_people_from_locked_games(parent, child, salary, clock)
    violations += validate_all_rosters(child, salary)
    return Result.pass_() if not violations else Result.fail(violations)
~~~

This referee runs automatically after every swap and before promotion; there is no weaker alternate “verify” command.

### D35 — “Latest” mutable pointers create cross-session artifact races

- **File & Line / Function:** <code>runs/latest_valid_run.json</code> consumers in <code>preflight_upload.py:358-388</code> and <code>late_swap_manager.py:244-260</code>; promotion paths.
- **Severity:** **[Bug]**
- **Evidence:** **STATIC-CONFIRMED**
- **Issue description:** A global last-writer pointer is not an artifact relationship. Parallel Classic/Showdown sessions or two slates on the same date can make a consumer bind to another run between resolution and use.
- **Remediation / corrected code:**

~~~python
@dataclass(frozen=True)
class ArtifactRelation:
    relation: Literal["INPUT_SALARY", "PARENT_ENTRIES", "DELIVERED_ENTRIES"]
    from_sha256: str
    to_sha256: str
    run_id: UUID

def require_relation(db: Connection, relation: str, from_sha: str) -> ArtifactRelation:
    row = db.execute(
        "SELECT * FROM artifact_relation WHERE relation=? AND from_sha256=?",
        (relation, from_sha),
    ).fetchone()
    if row is None:
        raise EvidenceUnknown(f"missing {relation} relationship")
    return ArtifactRelation(**row)
~~~

Pointers may exist as human conveniences, never as certification evidence.

### D36 — Tool and prompt surfaces preserve obsolete state and scratch residue

- **File & Line / Function:** <code>MANIFEST.md:1-17, 83-95</code>; <code>MLB_Classic.md:1, 512</code>; <code>CLAUDE.md</code>; <code>skills/generate-lineups/SKILL.md</code>; current <code>tools/_scratch_*</code>, <code>.audit*</code>, <code>.pylibs</code>, <code>.tmp</code>, <code>claims</code>, <code>runs</code>, and <code>outputs</code> trees.
- **Severity:** **[Technical Debt]**
- **Evidence:** **STATIC-CONFIRMED**
- **Issue description:** Stale versions and completed migration tasks remain authoritative-looking; scratch and cache trees increase audit/search cost and risk accidental packaging. Prompt history consumes context on every run.
- **Remediation / corrected code:** Generate one state card from code and isolate all ephemeral output outside the source tree.

~~~python
state = {
    "git_head": git_head,
    "runtime_id": runtime_id,
    "contract_versions": contract_versions(),
    "suite_registry_hash": suite_registry_hash(),
    "reference_hash": reference_tree_hash(),
}
publish_bytes(repo / "ENGINE_STATE.json", canonical_json(state))
~~~

CI fails if hand-authored docs repeat generated state values or if tracked scratch/cache patterns are present.

## 2.4 Cross-cutting root causes

The defects above are not 36 unrelated mistakes:

1. **Evidence is represented as permissive dictionaries and booleans.** That produces truthy-stub gates, false enrichment, missing-hash promotion, and prose/data disagreement.
2. **Identity lacks one canonical person/game/contest layer.** That produces DH contamination, Showdown CPT/UTIL splits, name collision loss, and global-latest cross-talk.
3. **Policy is duplicated.** Fraction units, cap math, locked-team checks, contest verification, roster rules, and prompt state diverge.
4. **Solver outcome and strategy recovery are coupled.** Compute limits can relax lineup strategy.
5. **Mutable files are used as a database.** Registries, gate JSONL, shared staged feeds, and pointers are vulnerable to concurrency and partial writes.
6. **The model objective is a proxy while the product objective is dollars.** This is the dominant economic risk; code correctness cannot compensate for it.

## 2.5 Verification debt to carry into implementation

Before any refactor is merged, reproduce the current production environment and freeze:

- Golden Classic and Showdown parse/roster/export bytes.
- Hand-verified salary, slot, team, and duplicate-person fixtures.
- Solver status fixtures for optimal, feasible-at-limit, limit-without-incumbent, proven infeasible, unbounded/model error, and NaN input.
- Doubleheader, stale feed, partial lineup, shelved hitter, postponed game, roof, and unparseable lock fixtures.
- Preflight/promote/swap artifact-relationship fixtures across concurrent Classic and Showdown runs.
- Mutation tests for every hard constraint and every hard gate.

The greenfield package must run in shadow mode until it matches legacy legality/referee outcomes and surpasses the baseline on untouched calibration metrics. It must not inherit legacy “certified” labels merely because its CSV is legal.

# Section 3: Target Greenfield Architecture & Implementation Specs

## 3.1 Architectural principles

1. **Functional core, imperative shell.** Pure transformations and math sit behind small adapters for network, disk, clock, database, and solver.
2. **Content-address everything.** A run uses hashes and explicit relationships, never a date directory or “latest” pointer as truth.
3. **Evidence before numbers.** Unknown/stale/conflicted facts retain their state; they do not silently become 1.0, zero, empty, or false.
4. **One contract, two modes.** Classic and Showdown differ by data, not by lifecycle.
5. **Model uncertainty, do not hide it.** Separate legal certainty, evidence uncertainty, predictive uncertainty, solver optimality, and business decision.
6. **One writer, many readers.** A transactional local state store coordinates stages. Artifacts are immutable files.
7. **Deadline-aware, bounded work.** Every network, process, solver, and task call has a deadline, cancellation path, and typed terminal result.
8. **Independent referee.** The code that generates or writes a portfolio cannot certify it.
9. **Prospective evaluation.** Predictions are frozen before outcomes; design, selection, and referee scenario banks never overlap.
10. **Human account boundary.** The engine emits a decision package. It never acts on DraftKings.

## 3.2 Logical architecture

~~~text
                 AUTHORIZED INPUT DROP
              DKSalaries + DKEntries bytes
                           |
                           v
  +------------------ Safety / data plane --------------------+
  | artifact store -> identity graph -> evidence reconciliation|
  |       |                 |                 |                |
  |       +----------- immutable run snapshot ----------------+
  +------------------------------------------------------------+
                           |
                           v
  +---------------- Predictive / economic plane ---------------+
  | features -> opportunity/event model -> scenario bank        |
  |                              |                              |
  | contest field model ---------+                              |
  |                              v                              |
  | candidate MILP -> score matrix -> exact settlement          |
  |                              v                              |
  | joint assignment -> exact local search -> referee scenarios |
  +------------------------------------------------------------+
                           |
                           v
  +---------------- Independent decision plane ----------------+
  | roster/evidence/lock checks -> write candidate CSV          |
  | reopen exact bytes -> referee -> manifest -> decision package|
  +------------------------------------------------------------+
                           |
                           v
             USER REVIEW + MANUAL DK UPLOAD

  Thin agent plane: inspect -> start -> status -> summarize
  It never owns a loop, equation, gate, or CSV mutation.
~~~

## 3.3 Target repository layout

~~~text
pyproject.toml
uv.lock / platform lock attestations
Dockerfile
src/dfs/
  cli.py
  domain/
    artifacts.py
    evidence.py
    identity.py
    runs.py
    solver.py
  contracts/
    base.py
    classic_v1.py
    showdown_v1.py
    registry.py
  adapters/
    dk_csv.py
    mlb_stats.py
    statcast.py
    weather.py
    odds.py
    public_page_extract.py
  features/
    opportunities.py
    park_weather.py
    matchups.py
  models/
    baseline_appg.py
    participation.py
    hitter_events.py
    pitcher_events.py
    ownership.py
    field.py
  simulate/
    game.py
    score.py
    scenario_bank.py
  optimize/
    candidate.py
    assignment.py
    exact_search.py
    backend.py
  settle/
    payouts.py
    contests.py
  referee/
    rosters.py
    evidence.py
    late_swap.py
    export.py
  orchestrate/
    state.py
    store.py
    worker.py
    policy.py
  reporting/
    package.py
    calibration.py
tests/
  unit/
  property/
  mutation/
  integration/
  golden/
  performance/
schemas/
  build_request.schema.json
  evidence.schema.json
  manifest.schema.json
config/
  contracts/
  freshness/
  contest_policies/
skills/generate-mlb-dfs-decision-package/
  SKILL.md
  references/
~~~

Generated artifacts live outside source, for example <code>%LOCALAPPDATA%/dfs-engine</code> on Windows or a user-configured workspace. A run directory is immutable after terminal state.

## 3.4 Core domain types

Use strict models at every I/O boundary. The following is the minimum contract:

~~~python
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Mapping

Sha256 = str
RunId = str
PersonId = str
GameId = str
ContestId = str

class EvidenceState(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"
    STALE = "STALE"
    CONFLICTED = "CONFLICTED"
    NOT_APPLICABLE = "NOT_APPLICABLE"

class RunState(StrEnum):
    CREATED = "CREATED"
    INPUTS_CAPTURED = "INPUTS_CAPTURED"
    EVIDENCE_READY = "EVIDENCE_READY"
    MODEL_READY = "MODEL_READY"
    CANDIDATES_READY = "CANDIDATES_READY"
    PORTFOLIO_READY = "PORTFOLIO_READY"
    REFEREE_PASS = "REFEREE_PASS"
    DECISION_READY = "DECISION_READY"
    DO_NOT_UPLOAD = "DO_NOT_UPLOAD"
    FAILED = "FAILED"

class SolverState(StrEnum):
    OPTIMAL = "OPTIMAL"
    FEASIBLE_LIMIT = "FEASIBLE_LIMIT"
    INFEASIBLE = "INFEASIBLE"
    LIMIT_NO_SOLUTION = "LIMIT_NO_SOLUTION"
    UNBOUNDED = "UNBOUNDED"
    MODEL_INVALID = "MODEL_INVALID"
    ERROR = "ERROR"

@dataclass(frozen=True)
class ArtifactRef:
    sha256: Sha256
    byte_length: int
    media_type: str
    logical_name: str
    path: Path

@dataclass(frozen=True)
class Evidence:
    kind: str
    subject_id: str
    state: EvidenceState
    source: str
    observed_at_utc: datetime
    effective_at_utc: datetime | None
    expires_at_utc: datetime | None
    raw_artifact: ArtifactRef
    schema_version: str
    detail: Mapping[str, Any]

@dataclass(frozen=True)
class Entry:
    entry_id: str
    contest_id: ContestId
    contest_name: str
    fee_usd: Decimal
    original_cells: tuple[str, ...]

@dataclass(frozen=True)
class SolverResult:
    state: SolverState
    incumbent: tuple[str, ...] | None
    objective: float | None
    best_bound: float | None
    mip_gap: float | None
    elapsed_s: float
    backend: str
    backend_version: str
    diagnostics: Mapping[str, Any]
~~~

Rules:

- Validate SHA-256 as exactly 64 lowercase hex characters.
- Money uses <code>Decimal</code> at input/output; scenario matrices may use integer cents.
- Time is timezone-aware UTC internally.
- IDs remain strings; never coerce DraftKings IDs through floating point.
- Reject booleans anywhere a numeric configuration is expected.
- Canonical JSON is UTF-8, sorted keys, no NaN/Infinity, and a trailing newline only at published text boundaries.

## 3.5 Complete roster contract

~~~python
@dataclass(frozen=True)
class SlotRule:
    name: str
    eligible_positions: frozenset[str]
    score_multiplier: Decimal = Decimal("1")
    salary_multiplier: Decimal = Decimal("1")
    role: Literal["BASE", "CAPTAIN"] = "BASE"

@dataclass(frozen=True)
class RosterContract:
    id: str
    contest_type: Literal["CLASSIC", "SHOWDOWN"]
    effective_from: date
    effective_until: date | None
    salary_cap: int
    slots: tuple[SlotRule, ...]
    max_people_per_team: int | None
    min_distinct_teams: int
    template_header_predicate: Callable[[tuple[str, ...]], bool]

    def validate(self, roster: Roster, pool: PlayerPool) -> tuple[Violation, ...]:
        # Implementation is independent from the optimizer matrix.
        ...
~~~

Identity is always a person. Draftable IDs are role-specific offers:

~~~python
@dataclass(frozen=True)
class Draftable:
    draftable_id: str
    person_id: PersonId
    team_id: str
    game_id: GameId
    role: Literal["BASE", "CAPTAIN"]
    salary: int
    positions: frozenset[str]
~~~

The Showdown solver chooses one role-specific draftable per slot while enforcing at most one offer per <code>person_id</code>. Exposure reports always include both person exposure and captain-role exposure.

## 3.6 Artifact store and transactional state

### Files

Raw and derived artifacts use:

~~~text
store/sha256/ab/cd/<full-sha256>
runs/<run-id>/manifest.json
runs/<run-id>/decision-package/
~~~

Ingestion copies bytes once, computes the digest during streaming, fsyncs, and atomically renames. Logical names are metadata only.

### SQLite schema

Use SQLite on a local same-host filesystem, not OneDrive/network shares. WAL allows readers alongside a writer but still permits only one writer; see [SQLite WAL](https://www.sqlite.org/wal.html) and [transaction behavior](https://www.sqlite.org/lang_transaction.html). Pin a SQLite build containing the current WAL-reset fixes and record <code>sqlite_version()</code>.

~~~sql
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA synchronous = FULL;
PRAGMA busy_timeout = 5000;

CREATE TABLE run (
    run_id TEXT PRIMARY KEY,
    state TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 0,
    contract_id TEXT NOT NULL,
    request_sha256 TEXT NOT NULL,
    deadline_utc TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL,
    terminal_reason TEXT
);

CREATE TABLE transition (
    run_id TEXT NOT NULL REFERENCES run(run_id),
    sequence INTEGER NOT NULL,
    from_state TEXT NOT NULL,
    to_state TEXT NOT NULL,
    task_key TEXT NOT NULL,
    outcome_json TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    PRIMARY KEY (run_id, sequence),
    UNIQUE (run_id, task_key)
);

CREATE TABLE artifact (
    sha256 TEXT PRIMARY KEY CHECK(length(sha256) = 64),
    byte_length INTEGER NOT NULL CHECK(byte_length >= 0),
    media_type TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    created_at_utc TEXT NOT NULL
);

CREATE TABLE run_artifact (
    run_id TEXT NOT NULL REFERENCES run(run_id),
    role TEXT NOT NULL,
    sha256 TEXT NOT NULL REFERENCES artifact(sha256),
    PRIMARY KEY (run_id, role)
);

CREATE TABLE artifact_relation (
    run_id TEXT NOT NULL REFERENCES run(run_id),
    relation TEXT NOT NULL,
    from_sha256 TEXT NOT NULL REFERENCES artifact(sha256),
    to_sha256 TEXT NOT NULL REFERENCES artifact(sha256),
    PRIMARY KEY (run_id, relation, from_sha256)
);

CREATE TABLE evidence (
    run_id TEXT NOT NULL REFERENCES run(run_id),
    kind TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    state TEXT NOT NULL,
    observed_at_utc TEXT NOT NULL,
    effective_at_utc TEXT,
    expires_at_utc TEXT,
    source TEXT NOT NULL,
    raw_sha256 TEXT NOT NULL REFERENCES artifact(sha256),
    payload_json TEXT NOT NULL,
    PRIMARY KEY (run_id, kind, subject_id, source, observed_at_utc)
);

CREATE TABLE lease (
    task_key TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES run(run_id),
    owner_id TEXT NOT NULL,
    expires_at_utc TEXT NOT NULL
);
~~~

State transitions use optimistic concurrency:

~~~python
def transition(conn: sqlite3.Connection, run_id: str, expected_version: int,
               from_state: RunState, to_state: RunState, task_key: str,
               outcome: Mapping[str, Any]) -> None:
    with conn:
        changed = conn.execute(
            """UPDATE run SET state=?, version=version+1, updated_at_utc=?
               WHERE run_id=? AND version=? AND state=?""",
            (to_state, utc_now(), run_id, expected_version, from_state),
        ).rowcount
        if changed != 1:
            raise ConcurrentTransition(run_id)
        conn.execute(
            """INSERT INTO transition
               (run_id, sequence, from_state, to_state, task_key,
                outcome_json, created_at_utc)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (run_id, expected_version + 1, from_state, to_state, task_key,
             canonical_json(outcome), utc_now()),
        )
~~~

No task polls with <code>while True</code>. A worker acquires one expiring lease, performs one bounded unit, commits one outcome, and exits.

## 3.7 Evidence reconciliation

Each evidence kind owns:

- required sources or source preference;
- identity key;
- freshness duration;
- conflict tolerance;
- minimum completeness;
- state derivation;
- whether the gate is hard, soft, or modelable uncertainty.

Example:

~~~python
@dataclass(frozen=True)
class EvidencePolicy:
    kind: str
    max_age: timedelta
    hard_gate: bool
    min_sources: int
    conflict: Callable[[Sequence[Evidence]], bool]
    completeness: Callable[[Sequence[Evidence], Slate], bool]

def reconcile(policy: EvidencePolicy, observations: Sequence[Evidence],
              slate: Slate, now: datetime) -> EvidenceState:
    current = [e for e in observations
               if e.expires_at_utc is None or e.expires_at_utc >= now]
    if not current:
        return EvidenceState.STALE if observations else EvidenceState.UNKNOWN
    if len({e.source for e in current}) < policy.min_sources:
        return EvidenceState.UNKNOWN
    if policy.conflict(current):
        return EvidenceState.CONFLICTED
    if not policy.completeness(current, slate):
        return EvidenceState.UNKNOWN
    return EvidenceState.PASS
~~~

Example hard policies:

| Evidence | Identity/scope | State needed for decision-ready |
|---|---|---|
| Salary/eligibility | salary hash + draftgroup | PASS |
| Reserved entries | entries hash + contest IDs | PASS |
| Game/lock time | every salary-slate game | PASS |
| Starting hitter status | every rostered hitter’s team | PASS or explicit pre-lock modeled state allowed by user policy; never contradicted |
| Starting pitcher role | every rostered pitcher | PASS |
| Weather/postponement | every outdoor/retractable game | PASS; roof uncertainty stays explicit |
| Odds | every modeled game | PASS or NOT_APPLICABLE if the selected model version does not use odds |
| Contest payout/field size | each reserved contest | PASS for EV selection; UNKNOWN forces legality-only diagnostic |

An override is an evidence object, not a boolean:

~~~python
@dataclass(frozen=True)
class OverrideEvidence:
    gate: str
    actor: str
    reason: str
    source_artifact_sha256: Sha256
    asserted_at_utc: datetime
    expires_at_utc: datetime
    scope_id: str
~~~

Only a configuration allowlist defines overridable gates. Salary legality, template identity, final-byte integrity, lock preservation, and required contest economics are never overridable.

## 3.8 Identity and source adapters

### Stable identity graph

Create bitemporal mappings among DraftKings draftable, person, MLBAM, source-specific player, team, game, and contest IDs:

~~~python
@dataclass(frozen=True)
class IdentityEdge:
    namespace_from: str
    id_from: str
    namespace_to: str
    id_to: str
    valid_from: datetime
    valid_until: datetime | None
    observed_at: datetime
    source_sha256: Sha256
    method: Literal["EXACT_ID", "EXACT_NAME_TEAM", "REVIEWED_ALIAS"]
~~~

Rules:

- Exact platform/source IDs beat names.
- Name joins include normalized name, team, game, role, and effective time.
- One-to-many or many-to-one name matches become <code>CONFLICTED</code>; never “take the first” or “highest PA.”
- Doubleheaders use source game ID plus start time, not <code>AWAY@HOME</code> alone.
- Preserve the raw value and normalization function version for audit.

### HTTP adapter policy

~~~python
@dataclass(frozen=True)
class HttpPolicy:
    connect_timeout_s: float = 3.0
    read_timeout_s: float = 10.0
    max_response_bytes: int = 25_000_000
    max_attempts: int = 3
    backoff_base_s: float = 0.4

def fetch_json(client: HttpClient, request: Request, policy: HttpPolicy,
               deadline: datetime) -> RawResponse:
    last: Exception | None = None
    for attempt in range(policy.max_attempts):
        remaining = (deadline - utc_now_dt()).total_seconds()
        if remaining <= 0:
            raise DeadlineExceeded(request.source)
        try:
            return client.get_json(
                request,
                timeout=min(policy.read_timeout_s, remaining),
                max_bytes=policy.max_response_bytes,
            )
        except RetryableHttpError as exc:
            last = exc
            if attempt + 1 == policy.max_attempts:
                break
            bounded_backoff(policy, attempt, deadline)
    raise SourceUnavailable(request.source) from last
~~~

Retry only timeouts, connection resets, 429, and selected 5xx responses. Do not retry schema, authentication, 4xx request, identity, or conflict errors. Persist every raw response before parsing. Secrets go in authorization headers where the API permits and are redacted structurally, not by log-string hope.

## 3.9 Predictive model specification

### Baseline

Ship <code>baseline_appg_v1</code> first as a parity model. It reproduces present projection behavior behind a truthful interface:

~~~python
class ProjectionModel(Protocol):
    id: str
    def predict(self, slate: ModelSlate, as_of: datetime) -> ForecastBundle: ...

@dataclass(frozen=True)
class ForecastBundle:
    model_id: str
    as_of_utc: datetime
    input_hashes: tuple[Sha256, ...]
    player_mean: np.ndarray
    player_quantiles: Mapping[float, np.ndarray]
    scenario_bank: ScenarioBank | None
    calibration_status: EvidenceState
~~~

The baseline returns no scenario bank and <code>calibration_status=UNKNOWN</code>. It can build legal diagnostic lineups, not an EV portfolio.

### Participation/opportunity model

Before event outcomes, model:

- hitter start probability and lineup slot;
- projected plate appearances conditional on slot/home-away/game run environment;
- starter probability, batters faced, pitch count, innings, and bullpen transition;
- weather/roof/postponement state;
- win and quality-start eligibility through shared game state.

Recommended first models:

- Ordinal/categorical model for lineup slot with a separate confirmed-lineup point mass.
- Negative binomial or hurdle-negative-binomial for PA/BF/IP opportunity.
- Hierarchical shrinkage by player, handedness, team, park, and season with rolling time decay.

### Plate-appearance/event model

For batter \(b\), pitcher \(p\), context \(c\), estimate:

\[
P(Y \in \{K, BB, HBP, 1B, 2B, 3B, HR, OUT\} \mid b,p,c)
\]

Then simulate base/out advancement and run/RBI credit on a shared event stream. A practical v1 can use multinomial logistic/gradient-boosted probabilities with hierarchical empirical-Bayes shrinkage. Preserve probability calibration; a small log-loss gain that breaks tail calibration is not automatically better for DFS.

For pitchers, derive scoring from the same batters faced so hitter/pitcher opposition is structurally correlated. Add pitcher win/QS/CG/no-hitter events from game state, never independent Bernoulli bonuses detached from innings and score.

### Calibration gates

Rolling-origin splits only. At each evaluation date, train solely on prior observations.

| Component | Metrics | Minimum reporting |
|---|---|---|
| Participation/lineup | log loss, Brier, calibration slope/intercept | by source state, horizon, team, confirmed/projected |
| PA/BF/IP | MAE, CRPS, interval coverage/width | by lineup slot, pitcher role, horizon |
| Player fantasy points | CRPS, pinball loss, PIT/reliability, mean bias | hitter/pitcher, salary tier, slate size |
| Pair dependence | covariance/correlation error, stack-tail coverage | same team, opposing pitcher, same game |
| Ownership | MAE, log loss after share transform, calibration | contest/stakes/field/slate size |
| Field construction | stack/SP/CPT frequencies, salary-left, overlap, duplicates | contest-conditioned |
| Payout/portfolio | mean net bias, interval coverage, rank calibration | contest class and portfolio size |

Promotion criteria are pre-registered. Example:

~~~python
@dataclass(frozen=True)
class ModelGate:
    min_slates: int
    max_mean_bias: float
    coverage_80_range: tuple[float, float]
    max_crps_ratio_vs_baseline: float
    require_no_time_leakage: bool = True
~~~

Do not auto-tune on every slate. Candidate model versions are promoted only after an untouched evaluation and recorded review.

## 3.10 Scenario engine and performance contract

### Deterministic RNG lineage

Use <code>numpy.random.SeedSequence</code> and named child streams:

~~~python
root = np.random.SeedSequence(run_seed)
participation_ss, game_ss, field_ss = root.spawn(3)
game_streams = {
    game_id: np.random.default_rng(ss)
    for game_id, ss in zip(sorted(game_ids), game_ss.spawn(len(game_ids)))
}
~~~

Persist the root entropy, spawn keys, NumPy version, model hash, and scenario purpose. Never depend on iteration order from a set/dict.

### Score matrix

Let <code>X</code> be scenario-by-person base fantasy points and <code>A</code> be lineup-by-person sparse incidence with role multipliers. Then:

\[
\text{scores} = X A^\top
\]

~~~python
def score_lineups(player_scores: np.ndarray, incidence: scipy.sparse.csr_matrix,
                  batch_size: int = 4096) -> np.ndarray:
    if player_scores.ndim != 2 or incidence.shape[1] != player_scores.shape[1]:
        raise ValueError("score matrix shape mismatch")
    result = np.empty(
        (player_scores.shape[0], incidence.shape[0]), dtype=np.float32
    )
    for start in range(0, player_scores.shape[0], batch_size):
        stop = min(start + batch_size, player_scores.shape[0])
        result[start:stop] = player_scores[start:stop] @ incidence.T
    return result
~~~

Avoid Python loops over scenario × lineup × player. Store large banks as memory-mapped arrays or chunked Parquet/Zarr with exact metadata. Use <code>float32</code> for point matrices only after an error bound test; keep payout cents in integer/float64.

### Adaptive compute

Accuracy, not a fixed scenario count, controls stopping:

~~~python
def simulation_converged(history: Sequence[Estimate], policy: SimPolicy) -> bool:
    recent = history[-policy.windows:]
    return (
        len(recent) == policy.windows
        and max(x.top_portfolio_ev_se for x in recent) <= policy.max_ev_se
        and jaccard_stable([x.top_lineup_ids for x in recent]) >= policy.min_jaccard
    )
~~~

Use a hard cap and deadline regardless of convergence. Record effective sample size and Monte Carlo standard errors. Do not claim two portfolios differ when their interval overlaps materially.

## 3.11 Contest-conditioned field model

The field generator conditions on:

- contest ID/archetype, field size, entry limit, stakes, payout breadth, and satellite/ticket economics;
- slate size, salary distribution, game totals, projected ownership, stack availability;
- observed stack shapes, SP pairs, captain choices, salary left, and user-level lineup recurrence;
- duplication behavior and lineup-builder archetypes.

Recommended v1:

1. Predict player ownership shares with a compositional model.
2. Predict construction archetype distribution.
3. Sample an archetype.
4. Draw a legal lineup using weighted sampling plus a fast repair MILP/CP-SAT.
5. Calibrate marginal ownership, pair co-ownership, stack frequencies, salary-left distribution, and duplicate counts simultaneously.

~~~python
class FieldModel(Protocol):
    id: str
    def sample(self, contest: Contest, slate: ModelSlate, n_entries: int,
               rng: np.random.Generator) -> FieldSample: ...

@dataclass(frozen=True)
class FieldDiagnostics:
    marginal_mae_pct: float
    stack_total_variation: float
    salary_left_wasserstein: float
    duplicate_count_error: float
    effective_sample_size: int
~~~

Opponent users and construction priors are partitioned by Classic/Showdown, contest class, entry limit, and stakes. Sparse categories use hierarchical backoff whose level is recorded. Do not pool modes.

## 3.12 Candidate solver

### Mathematical formulation

Let \(x_{i,r}\) be 1 when person/draftable \(i\) fills slot \(r\), and \(u_i\) be selected:

\[
\sum_i x_{i,r}=1 \quad \forall r
\]
\[
\sum_r x_{i,r}=u_i \le 1 \quad \forall person\ i
\]
\[
x_{i,r}=0 \quad \text{when } i \text{ is not eligible for } r
\]
\[
\sum_{i,r} salary_{i,r}x_{i,r}\le SalaryCap
\]

Add contract-specific team bounds, explicit locks/excludes, and optional construction constraints. Diversity constraints compare underlying people, not role-specific draftables.

### Backend interface

~~~python
class RosterSolver(Protocol):
    def solve(self, problem: RosterProblem, limits: SolveLimits) -> SolverResult: ...

@dataclass(frozen=True)
class SolveLimits:
    wall_time_s: float
    node_limit: int | None
    relative_gap: float
    random_seed: int
    threads: int = 1
~~~

Do not migrate solvers by fashion:

- SciPy/HiGHS is appropriate for sparse linear MILPs and already works conceptually in the current Classic engine. Set <code>time_limit</code>, <code>node_limit</code>, <code>mip_rel_gap</code>, and <code>presolve=True</code>; validate statuses per [SciPy milp](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.milp.html).
- OR-Tools CP-SAT is attractive for Boolean roster/assignment models and solution enumeration. It is integer-only and returns explicit <code>OPTIMAL</code>, <code>FEASIBLE</code>, <code>INFEASIBLE</code>, <code>MODEL_INVALID</code>, or <code>UNKNOWN</code>; see [CP-SAT](https://developers.google.com/optimization/cp/cp_solver) and [time limits](https://developers.google.com/optimization/cp/cp_tasks).

Implement both adapters behind the same fixture suite. Benchmark wall time, memory, feasible incumbent quality, determinism, and bank throughput at real sizes. Choose per problem family.

### Status handling

~~~python
def accept_incumbent(result: SolverResult, problem: RosterProblem,
                     referee: RosterReferee) -> Roster:
    if result.state not in {SolverState.OPTIMAL, SolverState.FEASIBLE_LIMIT}:
        raise NoAcceptableIncumbent(result.state)
    roster = decode(result.incumbent)
    violations = referee.validate(roster, problem)
    if violations:
        raise InvalidIncumbent(violations)
    return roster
~~~

Never relax a strategy constraint on <code>LIMIT_NO_SOLUTION</code>, <code>UNKNOWN</code>, or <code>ERROR</code>. A relaxation policy can run only after a proven infeasibility and must create a new problem hash.

### Candidate diversity

Generate candidates from outcome/field scenario clusters, not dozens of arbitrary objective jitter values:

- top-tail game-state clusters;
- ownership/duplication regimes;
- weather/participation states;
- contest-specific payout utility;
- controlled legal construction families.

Every candidate stores its generating scenario cluster, objective, problem hash, solver status, and constraint vector. Deduplicate by role-aware roster identity before writing the bank.

## 3.13 Exact settlement and contest economics

The contest adapter must ingest and bind:

- Contest ID/name, entry fee, field size, maximum entries.
- Cash payout by rank, tie semantics, tickets/seats and explicit dollar valuation policy.
- Cancellation/refund assumptions.
- User’s reserved entry IDs.

~~~python
@dataclass(frozen=True)
class Prize:
    start_rank: int
    end_rank: int
    value_cents: int
    kind: Literal["CASH", "TICKET"]

@dataclass(frozen=True)
class ContestEconomics:
    contest_id: str
    field_size: int
    entry_fee_cents: int
    prizes: tuple[Prize, ...]
    ticket_valuation_policy: str | None
    source_sha256: Sha256
~~~

Unknown payout/field economics means the engine cannot estimate contest EV. It may produce a legality-only diagnostic package but not select across contests using inferred name patterns.

Settlement tests must cover:

- exact ties spanning differently valued ranks;
- three or more duplicate lineups;
- own entries tied with each other and the field;
- unpaid ranks and entry-fee subtraction;
- satellites with multiple seats;
- partial payout schedules and invalid field sizes;
- Classic and Showdown scores with role multipliers.

## 3.14 Portfolio selection

### Stage A: linear assignment approximation

Let \(y_{e,l}\) assign lineup \(l\) to entry \(e\):

\[
\sum_l y_{e,l}=1 \quad \forall e
\]

Add lineup compatibility, candidate reuse, person/game/stack/CPT count or dollar exposure, contest diversity, and optional covariance/overlap penalties. Coefficients are net cents estimated on SELECT scenarios.

All controls declare units:

~~~python
@dataclass(frozen=True)
class PortfolioPolicy:
    objective: Literal["MEAN_NET", "MEAN_CVAR"]
    cvar_alpha: float
    cvar_lambda: float
    exposure_basis: Literal["ENTRY_COUNT", "AT_RISK_USD"]
    player_caps: Mapping[PersonId, float]
    game_caps: Mapping[GameId, float]
    max_candidate_reuse: int
    max_pair_overlap: int | None
~~~

### Stage B: exact portfolio exchange

~~~python
def improve_exact(
    portfolio: Portfolio,
    alternatives: Mapping[str, Sequence[Lineup]],
    evaluator: ExactPortfolioEvaluator,
    deadline: datetime,
) -> Portfolio:
    current = portfolio
    current_value = evaluator.utility(current)
    while utc_now_dt() < deadline:
        best: tuple[float, Portfolio] | None = None
        for entry_id in sorted(current.entry_ids):
            for lineup in alternatives[entry_id]:
                trial = current.replace(entry_id, lineup)
                if not trial.controls_pass:
                    continue
                value = evaluator.utility(trial)
                candidate = (value, trial)
                if value > current_value and (best is None or candidate[0] > best[0]):
                    best = candidate
        if best is None:
            break
        current_value, current = best
    return current
~~~

The production version caches settlement deltas and evaluates swaps in parallel deterministic batches. It remains bounded by a deadline/max rounds. Report the seed portfolio, accepted exchanges, final exact utility, Monte Carlo error, and optimality label <code>HEURISTIC_LOCAL_OPTIMUM</code>; do not call it global optimum.

## 3.15 Orchestration and non-blocking execution

### Finite-state graph

~~~text
CREATED
  -> INPUTS_CAPTURED
  -> EVIDENCE_READY
  -> MODEL_READY
  -> CANDIDATES_READY
  -> PORTFOLIO_READY
  -> REFEREE_PASS
  -> DECISION_READY

Any state -> DO_NOT_UPLOAD  (hard evidence/referee/deadline failure)
Any state -> FAILED         (software/infrastructure failure)
~~~

Transitions are monotonic. A correction creates a new evidence/artifact version and a new transition; it does not edit history. Terminal state changes require a new run derived from the prior run.

### Task definition

~~~python
@dataclass(frozen=True)
class TaskSpec:
    name: str
    from_state: RunState
    success_state: RunState
    timeout_s: float
    max_attempts: int
    retryable: frozenset[str]

PIPELINE = (
    TaskSpec("capture_inputs", RunState.CREATED, RunState.INPUTS_CAPTURED,
             10, 1, frozenset()),
    TaskSpec("reconcile_evidence", RunState.INPUTS_CAPTURED, RunState.EVIDENCE_READY,
             45, 3, frozenset({"HTTP_429", "HTTP_5XX", "TIMEOUT"})),
    TaskSpec("model", RunState.EVIDENCE_READY, RunState.MODEL_READY,
             60, 1, frozenset()),
    TaskSpec("candidates", RunState.MODEL_READY, RunState.CANDIDATES_READY,
             90, 1, frozenset()),
    TaskSpec("portfolio", RunState.CANDIDATES_READY, RunState.PORTFOLIO_READY,
             60, 1, frozenset()),
    TaskSpec("referee", RunState.PORTFOLIO_READY, RunState.REFEREE_PASS,
             20, 1, frozenset()),
    TaskSpec("package", RunState.REFEREE_PASS, RunState.DECISION_READY,
             10, 1, frozenset()),
)
~~~

Task keys include run ID, stage, stage input hashes, model/contract/config hashes, and code version. Repeating a completed task returns its committed outcome; it does not execute again.

### Deadline policy

Compute a hard workflow deadline from the earliest verified lock minus the configured delivery buffer. Every stage receives the remaining budget. It cannot start if its worst-case minimum budget does not fit.

~~~python
def stage_budget(now: datetime, deadline: datetime, requested_s: float,
                 reserve_s: float) -> float:
    remaining = (deadline - now).total_seconds() - reserve_s
    if remaining <= 0:
        raise DeadlineExceeded("no time remains for a safe stage")
    return min(requested_s, remaining)
~~~

No hidden budget floor may exceed the caller’s remaining wall clock.

## 3.16 Deterministic degradation ladder

Degradation reduces search precision; it never weakens hard evidence or roster legality.

| Trigger | Allowed action | Forbidden action |
|---|---|---|
| Source timeout | Use fresh cached observation whose policy remains PASS; otherwise UNKNOWN/STALE. | Treat missing source as neutral. |
| Simulation budget tight | Reduce scenarios to declared minimum and report larger Monte Carlo error. | Reuse referee scenarios for selection. |
| Candidate budget tight | Reduce scenario clusters/candidates deterministically. | Remove locks, exclusions, salary, eligibility, or hard team rules. |
| Solver time limit with feasible incumbent | Validate and label FEASIBLE_LIMIT. | Label optimal or infeasible. |
| Solver time limit without incumbent | Stop or retry once with same strategy and smaller problem. | Relax exposure/diversity because time expired. |
| Proven infeasible strategy | Apply only pre-authorized ordered relaxation and create a new problem hash. | Silent relaxation or “best effort” promotion. |
| Missing contest economics | Produce legality-only diagnostic. | Claim EV/ROI or allocate across contests by name heuristic. |
| Deadline reached | Emit last independently referee-passed decision package if still evidence-current; otherwise DO_NOT_UPLOAD. | Finish after lock and call it upload-ready. |

Late-swap degradation is cohort-aware. Locked slots and teams remain hard. Only unlocked candidates are regenerated, and the parent/child exact-byte relationship is mandatory.

## 3.17 Independent referee and delivery package

The referee is a separate package with no imports from candidate, portfolio, or CSV-writer implementations except shared immutable domain types and rule data.

It reopens:

- original salary bytes;
- original entries bytes;
- proposed final entries bytes;
- contract version;
- evidence snapshot;
- parent entries for a swap;
- portfolio policy;
- manifest relationships.

It independently proves:

1. Header, encoding, column count, Entry IDs, Contest IDs, blank/non-reserved rows, and all non-roster cells are preserved.
2. Every reserved entry is filled exactly once with the correct mode geometry.
3. Every draftable ID exists in the bound salary file, is eligible for its slot/role, and maps to one person.
4. Salary, team, duplicate-person, and all contract rules pass.
5. Count- and dollar-based portfolio controls pass from final bytes.
6. Evidence gates are current, complete, slate-scoped, and bound by hashes.
7. No locked slot changed and no newly introduced player belongs to a locked game/team.
8. The final artifact hash matches the manifest and the file is not past deadline.

Output:

~~~python
@dataclass(frozen=True)
class RefereeReport:
    state: Literal["PASS", "FAIL"]
    final_sha256: Sha256
    salary_sha256: Sha256
    source_entries_sha256: Sha256
    contract_id: str
    evidence_snapshot_sha256: Sha256
    violations: tuple[Violation, ...]
    metrics: Mapping[str, Any]
    referee_code_sha256: Sha256
~~~

### Decision package

~~~text
decision-package/
  DKEntries.csv
  manifest.json
  referee.json
  portfolio.json
  evidence.json
  model_card.json
  operator_summary.md
~~~

The summary leads with one of:

- <code>DECISION_READY — manual review/upload required</code>
- <code>LEGALITY_ONLY — EV model unavailable; DO_NOT_CALL_EV</code>
- <code>DO_NOT_UPLOAD — reasons...</code>

Never use “upload-ready” without also stating that the user must make substantive independent decisions and upload manually.

## 3.18 End-to-end operational flow

### A. Initial build

1. **User drop:** User exports DraftKings salary and entries CSVs and places them in the watched input folder. The watcher observes filesystem events only; it does not touch DraftKings.
2. **Capture:** Stream-copy, hash, virus/resource-policy check, parse mode, bind salary↔entries↔contest relationships, and create the run.
3. **Contract:** Detect Classic/Showdown from template geometry and salary role rows; require exactly one matching effective contract.
4. **Clock:** Parse every salary-slate game, reconcile source game IDs, and compute verified lock cohorts and hard deadline. Incomplete coverage blocks.
5. **Public evidence:** Fetch authorized official/public sources concurrently with per-source deadlines; persist raw bytes first.
6. **Reconcile:** Resolve people/games, lineup/probable/weather/roof/odds/payout evidence, freshness, conflicts, and completeness.
7. **Model:** Freeze an as-of feature snapshot and run the production-calibrated model. If the model gate is unavailable, select only the named baseline diagnostic path.
8. **Scenarios:** Generate independent SELECT and REFEREE banks from distinct RNG streams. DESIGN banks are created offline, not during selection.
9. **Field:** Generate contest-conditioned opponent entries and verify field diagnostics.
10. **Candidates:** Solve legal candidate rosters by scenario cluster under bounded solver limits; validate every incumbent independently.
11. **Score/settle:** Vector-score candidates and field on shared scenarios and settle exact contest payouts.
12. **Allocate:** Solve the joint entry assignment with explicit count/dollar controls; improve by exact settlement exchanges.
13. **Referee:** Write a provisional CSV, reopen exact bytes, and run all independent gates.
14. **Package:** Atomically publish the decision package and mark <code>DECISION_READY</code> only on referee PASS.
15. **User action:** Present evidence status, model/solver uncertainty, exposures in counts and dollars, final SHA-256, and the file. User reviews and manually uploads.

### B. Late swap

1. User drops the current DK entries export or selects the prior decision package.
2. Bind the parent by exact entries hash, not latest run.
3. Recompute time and lock cohorts from current evidence.
4. Reconcile changed lineup/pitcher/weather evidence.
5. Freeze locked slots and derive the authorized mutable Entry-ID set.
6. Re-simulate only affected games plus dependent contest scenarios; reuse unaffected scenario chunks only when their dependency hashes match.
7. Rebuild/allocate unlocked portions.
8. Independent referee compares parent and child bytes, preserves locked slots, rejects newly introduced locked-game people, and rechecks all rules.
9. Publish a new derived decision package; user manually uploads the edit.

### C. Post-slate

1. User manually downloads standings/contest files or supplies an authorized API export.
2. Safe extraction and schema validation capture immutable raw bytes.
3. Bind results to the exact pre-lock run, contest, entries, model, and scenario hashes.
4. Grade forecasts and field/settlement predictions prospectively.
5. Append observations; rebuild materialized aggregates transactionally.
6. Model promotion remains a separate reviewed workflow. No same-run auto-retuning.

## 3.19 Cowork/Codex skill and custom-tool boundary

The skill is a thin router. Proposed <code>SKILL.md</code>:

~~~markdown
---
name: generate-mlb-dfs-decision-package
description: Build or refresh a DraftKings MLB Classic or Showdown decision package from user-supplied salary and entries CSV files. Use for initial builds and late swaps. Never interacts with DraftKings.
---

# MLB DFS decision package

## Inputs

- One user-supplied DKSalaries CSV.
- One user-supplied DKEntries CSV.
- Optional parent decision package for late swap.

## Safety boundary

Never log in to, scrape, download from, upload to, edit, or submit on DraftKings.
Never store DK credentials or cookies. The user reviews and uploads manually.

## Procedure

1. Call dfs.inspect with the supplied paths.
2. If inspect returns INPUT_REFUSED, report its reasons and stop.
3. Call dfs.start once with inspect.request_sha256.
4. Call dfs.status using the returned run_id. Do not create a shell polling loop.
5. When terminal:
   - DECISION_READY: present operator_summary and DKEntries.
   - LEGALITY_ONLY: state that no EV claim is available.
   - DO_NOT_UPLOAD or FAILED: present the typed reasons.

Do not alter controls, evidence, or files. An override requires the dedicated
reviewed override workflow and a source artifact.
~~~

Required deterministic tools:

| Tool | Input | Output | Side effect |
|---|---|---|---|
| <code>dfs.inspect</code> | file paths/hashes | mode, contract, input errors, request hash | none |
| <code>dfs.start</code> | request hash | run ID and deadline | creates one run |
| <code>dfs.status</code> | run ID | compact state/progress/terminal artifacts | none |
| <code>dfs.cancel</code> | run ID/reason | terminal cancellation | one state transition |
| <code>dfs.override-request</code> | run/gate/source/reason | review artifact | does not clear gate |
| <code>dfs.referee</code> | artifact hashes | independent report | publishes report |
| <code>dfs.grade</code> | run/standings hashes | prospective metrics | append-only grade |

The agent receives compact JSON, not multi-megabyte logs. Tool descriptions use distinct verbs and non-overlapping purposes.

## 3.20 Testing and assurance strategy

### Test pyramid

| Layer | Required coverage |
|---|---|
| Unit | parsers, units, IDs, evidence states, clock, payout/tie math, atomic artifacts |
| Property | every generated roster legal; salary/slot/team invariants; settlement conservation; serialization round trips |
| Mutation | delete/flip every hard MILP constraint and gate; at least one test must fail |
| Golden | exact original→delivered bytes for Classic, Showdown, late swap, duplicate headers, CP1252/BOM |
| Integration | full FSM with fake adapters and solver statuses |
| Concurrency | two modes/slates in parallel; killed writer; lease expiry; pointer independence |
| Fault injection | truncated JSON/CSV/ZIP, HTTP 429/5xx/timeouts, disk full, child kill, stale/conflicted evidence |
| Statistical | seeded distribution moments, calibration metrics, scenario independence, settlement sampling error |
| Performance | representative 1/3/6/12-game slates and 1/20/150-entry portfolios under deadline budgets |
| Security | ZIP bombs, formula injection, secret redaction, path/symlink policy, dependency/SBOM scan |

### Solver assertions

For every solve:

- record status, wall time, node count, incumbent, bound, gap, backend/version, threads, and seed;
- independently check integer distance and every constraint from decoded values;
- compare both backends on small exhaustive fixtures;
- enumerate all legal rosters for tiny fixtures and verify global optimality;
- ensure a limit never increments an infeasibility or relaxation counter.

### Statistical assurance

- Pre-register evaluation windows and metrics.
- Use rolling-origin evaluation with slate-clustered uncertainty intervals.
- Report calibration by subgroup, not only aggregate.
- Run shadow predictions without changing delivered portfolios until promotion.
- Monitor input/population drift, missingness, residual bias, correlation error, and field-model divergence.
- Automatic response to drift is <code>DEGRADED/DO_NOT_UPLOAD</code> or baseline fallback, not silent online retraining.

## 3.21 Security and privacy specification

- Treat CSV, ZIP, JSON, HTML, and prompt text as untrusted data.
- Validate paths stay under configured input/artifact roots; reject symlinks/reparse points when crossing trust boundaries.
- Enforce file/member/response byte limits and stream data.
- Escape cells beginning with <code>=</code>, <code>+</code>, <code>-</code>, or <code>@</code> in human-facing spreadsheets; preserve DK template cells exactly where required.
- Use OS credential storage for public-data API keys. Never put keys in query logs, manifests, prompts, or exception URLs.
- Run with no DK credentials and no permission to control the DK site.
- Generate an SBOM and pin dependency/image hashes. Dependency updates require the full golden, solver, and referee gates.
- Sign release manifests if artifacts cross machines; a signature proves provenance, not lineup quality.
- Log structured error codes and redacted metadata; never raw environment dumps.

## 3.22 Cost and throughput controls

The target reduces both token and compute waste:

- The LLM performs at most one inspect/start/status/summarize path; no multi-agent chatter or shell retry loop.
- Network fetches run concurrently with small response caps and shared cached raw artifacts.
- Features and scenario chunks cache by exact dependency hashes.
- Scenario scoring uses sparse matrix multiplication.
- Candidate jobs are canonicalized and deduplicated before solving.
- Solver selection is empirical; keep SciPy/HiGHS when it is faster and truthful.
- Field generation uses fast sampling plus batched repair, not one MILP per opponent entry where avoidable.
- Exact settlement deltas are cached during local search.
- Referee work is linear in final bytes and never invokes an LLM.

Performance service-level objectives must be measured on declared hardware. Suggested initial targets, subject to benchmark validation:

| Workflow | Target p95 after inputs/evidence available |
|---|---:|
| Inspect/hash/parse | 2 seconds |
| Evidence reconciliation from warm cache | 5 seconds |
| Classic candidate + portfolio, 20 entries | 60 seconds |
| Showdown candidate + portfolio, 20 entries | 30 seconds |
| Independent referee/package | 5 seconds |
| Late swap, affected cohort only | 45 seconds |

If a target is missed, report the measured stage and profile. Do not compensate by weakening gates.

## 3.23 Implementation sequence and exit gates

### Phase 0 — Freeze behavior and runtime

Deliver:

- Immutable production image and supported developer locks.
- Current legacy characterization/golden fixtures.
- AST/lint/type baseline and per-suite wall-clock report.
- Explicit artifact backup and no-write migration plan.

Exit gate:

- Full current audit passes in the production image.
- Every current legal/export/referee behavior needed for compatibility has a golden or property test.

### Phase 1 — Safety kernel

Deliver:

- Artifact store, canonical JSON, atomic publishers.
- SQLite run/transition/evidence/relationship/lease schema.
- Strict evidence, artifact, clock, and solver result types.
- One platform-aware CLI.

Exit gate:

- Concurrency, kill, disk-full, partial-write, wrong-artifact, and stale-evidence fault tests pass.

### Phase 2 — Unified roster/referee contract

Deliver:

- Complete Classic and Showdown contracts.
- Person↔draftable identity.
- Candidate backend interface.
- Independent final-byte and late-swap referee.
- One preflight/promotion path.

Exit gate:

- Legacy and new systems agree on legal/illegal golden fixtures.
- Every hard constraint survives mutation testing.
- Showdown can reach the same <code>REFEREE_PASS</code> lifecycle as Classic, while still carrying no EV claim.

### Phase 3 — Orchestration and baseline parity

Deliver:

- Persisted bounded FSM.
- Idempotent ingest/evidence/baseline/candidate/portfolio/referee/package tasks.
- <code>baseline_appg_v1</code> adapter.
- Thin skill and compact deterministic tools.

Exit gate:

- From input drop to decision package requires no prompt adjustment or manual mid-run action.
- Parallel Classic/Showdown sessions cannot cross-bind artifacts.
- Terminal diagnostics survive every deadline path.

### Phase 4 — Prospective forecast and scenario foundation

Deliver:

- Bitemporal feature store.
- Participation/opportunity and player outcome models.
- DESIGN/SELECT/REFEREE scenario banks.
- Prospective forecast ledger and calibration reporting.

Exit gate:

- Minimum pre-registered sample and calibration thresholds pass on untouched slates.
- Joint stack/pitcher dependence tests beat the APPG baseline.
- No time leakage audit findings.

### Phase 5 — Field and settlement

Deliver:

- Contest economics ingestion.
- Contest-conditioned opponent generator.
- Exact cash/ticket/tie/duplicate settlement.
- Field calibration and settlement tests.

Exit gate:

- Marginal ownership and construction/duplicate distributions meet pre-registered thresholds.
- Hand-settled fixtures and randomized conservation properties pass.

### Phase 6 — EV portfolio and shadow evaluation

Deliver:

- Scenario reward matrix.
- Joint assignment with declared risk and exposure bases.
- Exact settlement local search.
- Referee scenario evaluation and uncertainty report.

Exit gate:

- Stable decision rankings under additional scenarios.
- Prospective performance improves on the baseline under the declared metric with uncertainty reported.
- No “maximum EV” or “positive ROI” claim unless the model governance review explicitly authorizes it.

### Phase 7 — Production cutover

Deliver:

- Shadow comparison dossier.
- Rollback/kill switch.
- Operator guide and alerting.
- Archived legacy baseline.

Exit gate:

- Two release candidates complete all legal, evidence, calibration, deadline, concurrency, security, and final-byte gates.
- User approves the declared risk policy and manual DK boundary.

## 3.24 Implementation priority

The secondary implementation agent should start in this order:

1. Fix D13/D14/D15/D34/D35 at the money boundary.
2. Fix D01–D12 and D16–D31 with regression/mutation tests, without changing projection rankings.
3. Establish the reproducible runtime and transactional artifact/FSM kernel.
4. Unify Showdown with the roster/referee lifecycle.
5. Move current APPG/F-factor behavior behind the baseline interface.
6. Build the prospective model/scenario/field/settlement stack in shadow mode.
7. Enable portfolio EV selection only after calibration gates pass.

Do not begin with a solver rewrite, an LLM orchestration framework, browser automation, or wholesale deletion. The first economic milestone is not “more lineups faster”; it is one prospectively gradeable contest payout distribution bound to the exact pre-lock evidence snapshot.

## 3.25 Definition of done

The target system is complete only when all statements below are true:

- A single command/tool request takes immutable user-supplied Classic or Showdown files to a terminal decision package without prompt edits or mid-run debugging.
- Every task is bounded, idempotent, cancelable, and recoverable after process death.
- Every hard fact has typed, current, slate-scoped evidence; unknown/stale/conflicted states fail closed.
- Classic and Showdown share one complete roster contract interface and one independent final-byte referee lifecycle.
- Solver status, feasibility, optimality, and predictive/model quality are distinct fields.
- Outcome scenarios are jointly generated, field lineups are contest-conditioned, and payouts/ties/duplicates/fees are settled exactly.
- Portfolio controls declare whether they operate on entries or dollars; both are reported.
- Forecasts are prospective and DESIGN/SELECT/REFEREE scenario banks are independent.
- Model and field calibration pass pre-registered untouched-data thresholds.
- Final bytes are hash-bound to salary, entries, evidence, contract, model, scenarios, policy, code, and referee report.
- Late swap independently re-derives lock constraints from parent and final bytes.
- The skill is small, uses progressive disclosure, and cannot alter math, evidence, gates, or DK account state.
- DraftKings review/upload remains a substantive manual user decision.
- Existing inputs and legacy artifacts remain preserved and recoverable through the migration.

Until then, the truthful product label is:

> **Legal, evidence-audited lineup decision support — not a proven maximum-EV engine.**

## 3.26 Source notes

Primary technical and policy references used for the target specification:

- [SciPy MILP reference](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.milp.html)
- [OR-Tools CP-SAT solver](https://developers.google.com/optimization/cp/cp_solver)
- [OR-Tools solver time limits](https://developers.google.com/optimization/cp/cp_tasks)
- [SQLite WAL](https://www.sqlite.org/wal.html)
- [SQLite transactions](https://www.sqlite.org/lang_transaction.html)
- [Anthropic: Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
- [Anthropic: Building effective agents](https://www.anthropic.com/engineering/building-effective-agents)
- [Hunter, Vielma, and Zaman: Picking Winners in Daily Fantasy Sports](https://arxiv.org/abs/1604.01455)
- [Haugh and Singal: How to Play Fantasy Sports Strategically](https://pubsonline.informs.org/doi/pdf/10.1287/mnsc.2019.3528)
- [DraftKings Community Guidelines](https://www.draftkings.com/community-guidelines)
- [DraftKings Daily Fantasy Terms of Use](https://sportsbook.draftkings.com/legal/us-terms-of-use)
- [DraftKings Fantasy Sports Fair Play Commitment](https://help.draftkings.com/hc/en-us/articles/4405223983635-Fantasy-Sports-Fair-Play-Commitment-US)
- [DraftKings bulk lineup CSV workflow](https://help.draftkings.com/hc/en-us/articles/4405223998867-How-do-I-upload-or-edit-multiple-lineups-at-once-US)
- [SaberSim contest simulations](https://support.sabersim.com/en/articles/12079199-how-contest-sims-work)
- [SaberSim late swap](https://support.sabersim.com/en/articles/12079563-using-late-swap)
- [Stokastic MLB DFS workflow](https://www.stokastic.com/articles/mlb-dfs/how-to-win-mlb-dfs)
- [FantasyLabs lineup optimizer](https://www.fantasylabs.com/tools/fantasy-lineup-optimizer/)

Vendor pages are cited only as descriptions of product mechanics. They are not treated as independent evidence that any vendor, model, or strategy has positive expected return.
