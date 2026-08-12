# DraftKings MLB DFS Greenfield System Specification

**Review date:** 2026-08-12
**Repository reviewed:** `mlb-dfs` at commit `6c96474d075b4040497d16ae35ba248e93d54f22`
**Scope:** DraftKings MLB Classic and single-game Showdown research, modeling, lineup construction, portfolio allocation, late swap, evidence, QA, and delivery  
**Audience:** An implementation agent that has no access to the reasoning that produced this document

**Executive verdict:** The repository is a serious legality-and-audit system, but it is not yet an expected-value system. It can construct legal rosters, preserve useful evidence, and run substantial QA. Its production objective is nevertheless a collection of hand-tuned projection, ownership, stack, contest, and diversity proxies. It does not generate calibrated joint game outcomes, simulate a contest-conditioned opponent field, settle exact payouts and ties, or optimize a bankroll-aware portfolio over scenario-level profit. Calling the result maximum-EV would be false.

The greenfield recommendation is to retain the useful domain knowledge but replace the runtime architecture. The target is a deterministic, persisted event-driven system in which immutable inputs feed calibrated baseball simulations, contest-specific opponent-field simulations, exact payout settlement, scenario-level portfolio optimization, and an independent fail-closed certifier. The language model is a research and exception-handling assistant, not the control plane, calculator, evidence authority, or release signer.

There is also a non-negotiable product constraint. DraftKings' current [Terms of Use](https://sportsbook.draftkings.com/legal/us-terms-of-use) prohibit automated scripts, bots, scrapers, and tools that interact with the service, including tools that create, enter, or edit lineups. Its [Community Guidelines](https://support.draftkings.com/dk/en-us/what-are-the-draftkings-community-guidelines?id=kb_article_view&sysparm_article=KB0010710) permit third-party lineup tools only when the player incorporates substantive independent decisions. Therefore, literal zero-human-intervention account submission is not an acceptable production requirement. The compliant design target is zero-touch computation through a decision-ready package, followed by a logged substantive user choice and manual DraftKings login, entry, upload, and money movement. An authenticated automation capability must remain disabled unless DraftKings grants written authorization or supplies an authorized API and counsel approves its use.

The design follows four rules:

1. **Compute continuously; promote conservatively.** Missing evidence may never stall diagnostic calculation, but it must prevent a package from becoming certified.
2. **No EV label without economics.** A score becomes EV only after calibrated outcomes, a contest-conditioned field, exact payout/tie logic, and uncertainty accounting exist.
3. **No assumption becomes evidence.** `UNKNOWN`, `STALE`, and `CONFLICTED` remain first-class states and cannot be converted to `PASS` by a caller flag.
4. **No model grades itself.** Final legality, evidence, identity, and byte-level delivery checks run in an independent process from different inputs or independently loaded artifacts.

**Research basis.** Current source material used for the redesign includes Anthropic's guidance on [context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents), [agent skills](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills), [long-running agent harnesses](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents), and [long-running app harness design](https://www.anthropic.com/engineering/harness-design-long-running-apps); MLB's definitions of [expected wOBA](https://www.mlb.com/glossary/statcast/expected-woba), [expected statistics](https://baseballsavant.mlb.com/expected_statistics), and [bat tracking](https://baseballsavant.mlb.com/leaderboard/bat-tracking); DraftKings' [Classic rules](https://support.draftkings.com/dk/en-us/game-style-classic-overview?id=kb_article_view&sysparm_article=KB0010665), [Showdown rules](https://support.draftkings.com/dk/en-us/game-style-showdowns-overview?id=kb_article_view&sysparm_article=KB0010694), [CSV workflow](https://support.draftkings.com/dk/en-us/how-do-i-upload-or-edit-multiple-lineups-at-once?id=kb_article_view&sysparm_article=KB0010800), and [lock policy](https://support.draftkings.com/dk/en-us/when-do-lineup-entries-and-edits-close?id=kb_article_view&sysparm_article=KB0010806); official [SciPy MILP](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.milp.html), [OR-Tools CP-SAT](https://developers.google.com/optimization/cp/cp_solver), and [SQLite transaction](https://www.sqlite.org/lang_transaction.html) / [WAL](https://www.sqlite.org/wal.html) documentation; and vendor capability descriptions from [SaberSim contest simulations](https://support.sabersim.com/en/articles/12079199-how-contest-sims-work), [SaberSim late swap](https://support.sabersim.com/en/articles/12079563-using-late-swap), [Stokastic MLB tools](https://www.stokastic.com/fanduel/), and [RotoGrinders LineupHQ](https://rotogrinders.com/lineuphq). Vendor pages are capability benchmarks and product-taxonomy inputs, not independent evidence of profitability.

## Audit method, evidence limits, and current baseline

This is a current-checkout, zero-base design review rather than an endorsement of the existing implementation. The review covered all 56 production Python files, the six Python test files, top-level instruction and operating documents, runtime manifests, archived field artifacts, source ledgers, and the principal Classic, Showdown, allocation, late-swap, certification, and delivery paths. The production tree is approximately 32,835 Python lines; the test tree is approximately 14,512 lines. The tracked repository contains 724 files, including 597 under `data/`. The field archive contains 267 contest standings CSVs across 19 slate dates and a record-only opponent registry of 267 contests and 15,402 usernames. These counts show substantial operating and validation investment; they do not establish predictive edge.

The prior greenfield document was re-audited against the current commit. Changes landed after 2026-08-10 repaired several concrete defects, including Showdown paste parsing, out-status manifest vocabulary, relaxation labeling, preflight contest-name handling, skipped-test accounting, and delivery-manifest ordering. Those repaired defects are not repeated below as current failures. The remaining findings are based on the code and artifacts present at the reviewed commit.

Runtime verification was environment-limited. `tools/env_probe.py` reported that NumPy, pandas, SciPy, and `scipy.optimize.milp` were unavailable in the active Windows Python 3.13 environment; the repository lock targets Python 3.10 on Linux x86-64. `tools/audit.py --run-tests --terse` therefore stopped at the dependency gate after 79 dependency-independent tests. No ad-hoc packages were installed. Runtime claims in this report are consequently either direct static-code observations or explicitly marked design requirements, not claims that the locked suite passed here.

Evidence labels used implicitly throughout this report are: `VERIFIED_CURRENT` for direct current-tree observations, `REPAIRED_SINCE_PRIOR` for issues confirmed fixed in later commits, `STATIC_ONLY` where the locked runtime could not be executed, and `EXTERNAL_CURRENT` for current official or vendor documentation. Only this specification is an authorized workspace change.

### Current data flow and where value is lost

The live path is broadly: supplied DraftKings salary/entry CSVs → mutable staging files and live-data adapters → APPG-centered multiplicative projections and heuristic ceilings → legal lineup enumeration/optimization → heuristic candidate prefilter → proxy-scored contest allocation → entry-keyed CSV export → run/output manifests → preflight. This flow has useful legality controls, but no calibrated joint outcome distribution, contest-conditioned opponent field, exact settlement, or scenario-level dollar objective. Promotion truth is distributed across flags, manifests, file naming, warnings, and prose rather than one transactional state authority.

### Module and artifact disposition

| Current component family | Greenfield action | Reason and migration rule |
|---|---|---|
| DraftKings CSV parsers, Entry-ID preservation, roster legality checks, deterministic token parsing, golden fixtures | **Preserve as characterized adapters** | These encode real platform contracts. Freeze current behavior with golden tests, move behind typed interfaces, and independently reparse final bytes. |
| `roster_contracts.py` and shared status/token vocabularies | **Preserve and complete** | Make one versioned package authoritative for both Classic and Showdown; remove mirrored constants after parity tests. |
| `projection_builder.py`, APPG paths in `execution_pipeline.py`, heuristic ceilings/value guards, `showdown_theses.py` | **Retire from production selection** | Keep only as named cold-start baselines for champion/challenger tests. They are diagnostics, not forecasts or EV. |
| `ownership_prior.py` | **Retain only as a cold-start prior** | It is honestly uncalibrated. Replace production leverage decisions with a contest-conditioned legal field generator. |
| `optimizer_v3.py` and legal lineup constraints | **Extract and rebuild** | Preserve validated constraint semantics; replace the proxy objective and monolithic orchestration with solver-neutral candidate and portfolio services. |
| `contest_allocator.py` | **Replace objective; retain fixtures** | Current selection optimizes a dimensionless proxy. Reuse assignment and Entry-ID fixtures while rebuilding around scenario profit and covariance. |
| `showdown.py` | **Rebuild on the common scenario/economics kernel** | Role-weighted legality is reusable; APPG scoring, categorical role assumptions, and review-only promotion are not. |
| `tools/late_swap.py` | **Replace runtime state model** | Preserve lock and slot semantics, but eliminate shared date-keyed mutable feeds and implement conditional re-simulation plus bounded re-optimization. |
| `preflight_upload.py`, upload integrity checks, final-byte verifier | **Split and harden** | Preserve proven checks; make missing/stale evidence and missing manifest hard non-waivable states in an independent certifier. |
| `upload_manifest.py`, run manifests, claims files, mutable JSON state | **Replace with transactional records** | Keep append-only audit exports, but move authority to a local same-host database with leases, constraints, immutable artifact hashes, and signed transitions. |
| Live-data adapters and public-source fetchers | **Rebuild behind provider contracts** | Centralize identity, timestamps, provenance, rate limits, retries, and conflict resolution. Browser use is a bounded fallback, never the state authority. |
| `CLAUDE.md`, `MLB_Classic.md`, the 569-line skill, runbooks, backlog, changelog, `MANIFEST.md` | **Prune and generate** | Keep a short invariant root, progressively disclosed task references, generated command/schema docs, and archived decision records. Do not load the backlog/changelog into routine execution context. |
| Archived standings, mined field summaries, source ledgers | **Preserve immutably, re-index** | They are valuable raw evidence. Add hashes, acquisition cutoffs, contest identities, deduplication, and a prospective prediction ledger before using them for calibration. |

Production Python coverage is explicit rather than implied:

- **Characterize, then preserve behind new interfaces:** `determinism.py`, `team_codes.py`, `repo_env.py`, `entries/dk_entries_manager.py`, `optimize/roster_contracts.py`, the legal-constraint portions of `optimize/optimizer_v3.py` and `optimize/showdown.py`, lock/slot behavior in `swap/late_swap_manager.py`, and final-byte behaviors in `tools/verify_export.py`. Preservation means golden parity tests, not continued ownership of runtime state.
- **Rebuild and replace in place only after parity:** `allocate/contest_allocator.py`, `contest_shapes.py`, `field/contest_library.py`, `field/field_miner.py`, all four `intake/` adapters/managers, `optimize/bank_cache.py`, `pipeline/build_state_manager.py`, `pipeline/execution_pipeline.py`, `tools/stage_slate.py`, `tools/late_swap.py`, `tools/preflight_upload.py`, and every network fetch/refresh tool. Their useful parsing or domain rules move into the vNext contracts; their mutable-file orchestration does not.
- **Retire from production ranking; keep as named baselines:** `allocate/posture_allocator.py`, `field/ownership_prior.py`, `projections/projection_builder.py`, `projections/xwoba_base_correction.py`, `optimize/showdown_theses.py`, and `optimize/tail_candidate_scanner.py`. Baseline outputs may appear in research reports but cannot influence a certified economic portfolio after cutover.
- **Move off the slate critical path:** `tools/audit.py`, `env_probe.py`, `solver_probe.py`, `sync_check.py`, `stack_shape_probe.py`, `claim.py`, `wheel_fetch.py`, `extract_inbox_zips.py`, `awaiting_standings.py`, `net_to_date.py`, `rebuild_registry.py`, and the skill evaluation harness. Convert relevant checks to CI/startup probes or offline ingestion jobs. Delete `claim.py` after database leases are authoritative. Replace `skills/generate-lineups/scripts/build_slate.py` with the thin vNext CLI and split its skill context as specified below.
- Package `__init__.py` files contain no product decision and remain packaging-only. Data, tests, documents, and archived artifacts are governed by the family-level rules in the table; no historical input is deleted during migration.

Anything not justified by a typed contract, a measured predictive lift, a compliance requirement, or an independent certification rule is deletion-eligible. Migration should preserve old outputs as fixtures, not preserve old architecture by default.

## 1. Greenfield Audit & Legacy Deconstruction

### F-01 — Product boundary: literal zero-touch DraftKings operation is non-compliant

**Component / Discovery Question:** Product objective, platform automation, and required human agency

**Unbiased Critique & Root Cause:** The prompt's literal objective—maximum-EV lineups with zero human intervention—collides with current DraftKings rules. The Terms prohibit automated means, scripts, and tools from interacting with the site, including screen scraping and creating or editing lineups. The Community Guidelines permit an optimizer only when the user incorporates substantive independent decisions; a system distributing prebuilt lineups that require no substantive user input is specifically outside that boundary. Automating authenticated salary downloads, entry editing, upload, or submission with a browser is therefore not a clever autonomy win. It is account, funds, and product risk. A manual click added after an otherwise predetermined workflow is unlikely to be a substantive decision.

**Greenfield Solution & Technical Spec:** Define two product modes. `SHADOW_AUTONOMOUS` may run research through economic recommendations without account interaction and is used for model evaluation. `DK_COMPLIANT_PRODUCTION` must stop at `DECISION_READY`, present at least two meaningfully different portfolios with material trade-offs, record the user's independent selection or parameter choice, then create a manually uploaded CSV. Login, contest entry, upload, editing, withdrawal, and payment remain manual. Put authenticated DraftKings automation behind a compile-time-disabled capability named `AUTHORIZED_DK_API`, requiring written platform approval, legal review, explicit credentials, and a new threat model before it can be built.

### F-02 — Objective function: an honestly labeled proxy still cannot satisfy the EV objective

**Component / Discovery Question:** Contest allocator and portfolio objective

**Unbiased Critique & Root Cause:** `mlb_engine/allocate/contest_allocator.py` explicitly says it does not perform true ROI simulation, and `optimizer_v3.py` calls its composite output `Portfolio_EV_Proxy`. That labeling discipline is a strength; the mathematical gap remains. The score combines normalized candidate shape, contest weights, stack bonuses, pitcher tiers, reuse rules, ceiling/floor terms, and duplication heuristics. It has no dollar units and cannot price top-heavy payouts, duplicate lineups, ties, entry fees, field strength, or cross-entry covariance. A transparently named proxy can still be systematically negative-EV, and tuning its weights without a prospective target is not economic optimization.

**Greenfield Solution & Technical Spec:** Replace the production objective with scenario-level net profit. For lineup `l`, contest `c`, and scenario `s`, calculate `profit[l,c,s] = settled_prize[l,c,s] - entry_fee[c]`. Portfolio selection must choose one lineup per reserved Entry ID and maximize a declared utility such as expected profit minus downside risk, Monte Carlo uncertainty, and concentration costs. Keep the old score only as `proxy_score_v1`, never `EV`, `ROI`, or `expected_profit`. Require an `economics_complete=true` contract before any EV field can be populated.

### F-03 — Projection core: AveragePointsPerGame is not a forecast

**Component / Discovery Question:** `projection_builder.py`, `execution_pipeline.py`, and `showdown.py`

**Unbiased Critique & Root Cause:** The current engine can use DraftKings `AvgPointsPerGame` as the base of a multiplicative projection, and Showdown paths use it directly. APPG is a backward-looking mixture of role, opponents, parks, lineup spots, injuries, variance, and sample length. It is especially fragile for call-ups, platoon players, openers, bulk relievers, recently injured players, and pitchers changing workload. Salary and APPG also encode DraftKings' own priors, which creates circularity when the system later treats price-based leverage as independent information.

**Greenfield Solution & Technical Spec:** Build forecasts from opportunity and event distributions. Project hitter plate appearances conditional on lineup slot and team run environment; pitcher batters faced and innings conditional on role, pitch count, efficiency, and removal hazard; then project K, BB, HBP, batted-ball outcomes, steals, runs, RBI, wins, and quality starts. APPG may be a weak fallback feature with an explicit `emergency_proxy` tier, never the primary mean. Every prediction must carry model version, as-of time, feature cutoff, mean, quantiles, and uncertainty.

### F-04 — Projection multipliers create false precision and hidden double counting

**Component / Discovery Question:** Multiplicative factor model and manual adjustments

**Unbiased Critique & Root Cause:** The documented `Base × F1 × F2 × F3 × F4 × F5` model looks interpretable but multiplies correlated signals: salary, recent fantasy output, batting order, handedness, park, implied total, Statcast quality, and manual context. Products amplify measurement error, make interactions accidental, and provide no calibrated predictive distribution. Expected statistics such as xwOBA are valuable descriptive features, but MLB defines them from comparable batted balls and selected running characteristics; they are not complete forward DFS forecasts. A 7% multiplier is not evidence of a 7% change in expected fantasy points.

**Greenfield Solution & Technical Spec:** Replace manual multiplicative factors with versioned probabilistic submodels trained and evaluated out of time. Use partial pooling for players with sparse data, time-decay or dynamic latent skill, explicit park/handedness/opponent terms, and workload models. Preserve human-readable factor reports as Shapley-style or counterfactual explanations generated after inference, not as the inference mechanism. Calibration and ablation tests must determine whether each feature stays.

### F-05 — Outcome model: the runtime truthfully lacks the simulation required for EV

**Component / Discovery Question:** Joint slate simulation and documentation truth

**Unbiased Critique & Root Cause:** The current documentation now labels retired simulation concepts as non-production, and the source tree contains no live slate simulator, settlement engine, or training package. That honesty repairs the older documentation defect; it does not supply the missing outcome distribution. The runtime still produces point estimates and heuristic ceilings rather than internally consistent joint outcomes. Without shared game states, stack upside, opposing-hitter versus pitcher conflict, bullpen exposure, weather effects, and teammate correlations are approximations.

**Greenfield Solution & Technical Spec:** Introduce an event-driven `GameSimulator` that generates coherent plate appearances and scoring events for every game, then combines game blocks into slate scenarios with deterministic seeds. Make the simulator an importable, tested package with calibration reports and a deliberately weak baseline comparator. Generate executable-component documentation from registries and artifact schemas where possible; CI must fail if a production document names a missing command, schema, or component.

### F-06 — Opponent model: ownership priors are not a simulated field

**Component / Discovery Question:** `ownership_prior.py` and absent contest-field generator

**Unbiased Critique & Root Cause:** The ownership module correctly labels itself an uncalibrated structural prior, yet downstream strategy can still treat its output as contest leverage. Player marginals alone cannot reproduce lineup stacks, pitcher pairs, salary usage, max-entry behavior, optimizers, chalk concentration, or duplicate counts. The archive now contains hundreds of mined contest artifacts, which is meaningful raw material, but roughly a few weeks of repeated contest observations is not automatically a calibrated population model. Contest size and entry limit materially change field construction.

**Greenfield Solution & Technical Spec:** Train a hierarchical field model conditioned on slate, contest family, fee, field size, maximum entries, payout shape, and observed ecosystem regime. It must match player ownership, team stack rates, stack shapes, pitcher pairs, salary-left distribution, player-pair correlations, lineup duplication, and entrant portfolio behavior. Generate only legal lineups through sequential constrained sampling or conditional optimization. Evaluate with held-out contests and reliability plots; retain the structural prior only as a cold-start distribution.

### F-07 — Contest economics: payout and tie settlement are missing from selection

**Component / Discovery Question:** Payout tables, ranking, duplicate handling, and ROI

**Unbiased Critique & Root Cause:** Contest metadata and payout rows may be stored, but the production allocator does not rank the user's lineup against a simulated field and settle the exact payout table. This ignores the defining economics of GPPs. Duplicate lineups share prizes across tied positions; a high-owned lineup can project well yet lose value through duplicated top finishes. Flat, satellite, single-entry, three-max, and 150-max contests demand different portfolios even on the same slate.

**Greenfield Solution & Technical Spec:** Create a vectorized `ContestSettlementEngine`. For each scenario, score all field and user lineups, rank them, group exact ties, and divide the sum of prizes occupying the tied positions equally among tied entries. Subtract fees to produce net profit. Store the exact payout-table hash and contest snapshot with every result. If field size, fee, or payout is missing or inconsistent, set `economics_state=INCOMPLETE` and prohibit EV terminology.

### F-08 — Historical data exists, but there is no clean prospective prediction ledger

**Component / Discovery Question:** Calibration archive, leakage control, and feedback loop

**Unbiased Critique & Root Cause:** The repository has expanded its mined field archive, but mining results after contests is not the same as preserving what the model knew before lock. Without append-only pre-lock forecasts, ownership estimates, evidence versions, generated candidates, and decisions, later analysis can silently mix revised lineups, final ownership, or postgame information into evaluation. That produces excellent backtests and disappointing live results. Repeated contest exports can also overweight a slate unless grouped correctly.

**Greenfield Solution & Technical Spec:** Add an append-only prediction ledger keyed by slate identity, contest identity, model snapshot, and cutoff time. Persist pre-lock distributions before outcomes are available. After settlement, join results in a separate namespace and calculate metrics only through a time-aware dataset builder. Enforce train/validation/test splits by date and slate, group duplicate contest observations, and prohibit post-lock features with automated provenance checks.

### F-09 — Candidate prefiltering can manufacture infeasibility

**Component / Discovery Question:** `contest_allocator.py` candidate pruning

**Unbiased Critique & Root Cause:** The allocator retains sole-compatible candidates, limited representatives by stack/pitcher structure, and high-score candidates before solving the joint assignment. A candidate that appears weak in isolation can be the only combination that satisfies global exposure, uniqueness, or contest-fit constraints. Dropping it turns a feasible portfolio into a solver-reported infeasible one. The solver then receives blame for a lossy heuristic performed before it saw the actual problem.

**Greenfield Solution & Technical Spec:** Remove destructive score-only prefiltering. Use dominance rules that are proven safe under the active constraint set, or solve with column generation: start from a compact bank, obtain dual pressure or conflict diagnostics, generate improving lineups, and repeat to convergence or a hard time budget. When the problem is infeasible, generate an irreducible-conflict explanation against the unpruned contract and label heuristic exhaustion separately from mathematical infeasibility.

### F-10 — Candidate generation is not tied to economic marginal value

**Component / Discovery Question:** Candidate bank generation and diversity rules

**Unbiased Critique & Root Cause:** Random perturbations, stack quotas, ownership buckets, overlap caps, and no-good cuts can create a visually diverse bank while missing the lineups that improve portfolio EV. Conversely, generating thousands of variants before contest economics are applied consumes CPU and memory without knowing which columns matter. Fixed diversity targets can also remove rational concentration on small slates.

**Greenfield Solution & Technical Spec:** Generate candidates as best responses to sampled outcome scenarios, field compositions, contest types, and current portfolio dual prices. Add columns for high-value stack/game-state clusters, ownership-error stress cases, late-swap branches, and downside hedges. Stop when recent columns fail to improve held-out portfolio utility or the regret bound, not when an arbitrary bank size is reached. Record why each candidate entered the bank.

### F-11 — Evidence semantics: callers can convert unknown facts into passing gates

**Component / Discovery Question:** `build_slate.py` and `execution_pipeline.py` evidence assumptions

**Unbiased Critique & Root Cause:** Current paths can mark odds and weather gates assumed when data maps are absent, and caller assumptions can turn `None` into `True`. This destroys the difference between verified fact, policy default, and missing evidence. It is a direct route to an upload-ready claim with no current source behind it. Boolean gates cannot express staleness, disagreement, partial coverage, or not-applicable states.

**Greenfield Solution & Technical Spec:** Replace booleans with immutable `EvidenceAssertion` and derived `EffectiveFact` records. Status is one of `PASS`, `FAIL`, `UNKNOWN`, `STALE`, `CONFLICTED`, or `NOT_APPLICABLE`; only the evidence resolver can derive it from policy. Callers may request a diagnostic continuation but may not mutate an evidence state. Promotion requires every policy-declared critical fact to be `PASS` or `NOT_APPLICABLE` with provenance.

### F-12 — Preflight can warn on missing or stale evidence and still declare upload-ready

**Component / Discovery Question:** `preflight_upload.py` certification verdict

**Unbiased Critique & Root Cause:** Unreadable lineup feeds, feeds older than the current threshold, and even missing feed files can remain warnings. The `--no-manifest` path can waive the manifest cross-check; if the remaining mechanical checks have no hard failure, the verdict can still become `upload_ready`. This is a category error: legality of a CSV does not establish that every selected player is currently active, starting, eligible, unlocked, or bound to the reviewed evidence. A warning-heavy or manifest-free report is not independent certification.

**Greenfield Solution & Technical Spec:** Split outputs into `structural_qa`, `live_evidence_qa`, `economic_qa`, and `delivery_qa`. Structural checks may pass while live evidence remains unknown. Only their policy-complete conjunction can produce `CERTIFIED_FOR_USER_REVIEW`. Every other artifact must visibly carry `DO_NOT_UPLOAD` plus machine-readable blockers. Use deadline-aware diagnostic completion, not permissive promotion.

### F-13 — Shared lineup feeds accept weak coverage and overwrite provenance

**Component / Discovery Question:** Supplied-feed ingestion and `data/slates/<date>/lineups_feed.json`

**Unbiased Critique & Root Cause:** Current tools still default to a mutable date-level `data/slates/<date>/lineups_feed.json`. Even where a producer enforces useful minimum coverage, multiple draft groups, game sets, modes, and sessions on the same date share a collision domain. A later source can replace a better one, and the filename cannot express contest, draft group, retrieval time, source, parser version, or raw-response hash. A consumer therefore cannot prove which bytes produced a decision.

**Greenfield Solution & Technical Spec:** Store every acquired response as a content-addressed blob and insert a versioned assertion set keyed by game-set fingerprint and source time. Never overwrite raw evidence. Calculate coverage per required game and team, not against an arbitrary fraction. Promote a resolved view only after identity and completeness checks. A `latest` pointer is a derived database query, never the source of truth.

### F-14 — Late-swap evidence is slate-global and unsafe

**Component / Discovery Question:** `tools/late_swap.py` lineup, pitcher, weather, and odds gates

**Unbiased Critique & Root Cause:** `execution_pipeline.py` can convert missing gate values to true through `assume_gates`, while `tools/late_swap.py` treats a wrong-date feed as a blocker but stale or weakly covered feeds as warnings. The evidence state is too slate-global: one apparently healthy feed or set of confirmed teams does not verify every unlocked rostered player. Near lock, an assumption flag or warning downgrade can preserve a scratched player in another game while the workflow remains mechanically valid.

**Greenfield Solution & Technical Spec:** Evaluate each rostered player and each relevant game independently at a precise decision timestamp. Model locked, unlocked, postponed, delayed, and uncertain games explicitly. Re-simulate or reweight only the remaining conditional game distribution, freeze all locked slots, and certify that every unlocked selected player has valid evidence. Unresolved facts produce a fast diagnostic swap branch and a promotion blocker, never a stall.

### F-15 — Delivery manifest is a race-prone mutable JSON document

**Component / Discovery Question:** `upload_manifest.py` read-modify-write and corruption handling

**Unbiased Critique & Root Cause:** Manifest updates perform an unlocked read-modify-write around a whole JSON document. Concurrent sessions can lose deliveries, supersession links, or status changes. An unreadable manifest is converted into an empty manifest, masking corruption as a fresh state. The manifest primarily hashes the delivered file rather than binding the full evidence, model, candidate, portfolio, and contest dependency graph.

**Greenfield Solution & Technical Spec:** Make a transactional database the authority and the JSON manifest a generated view. Use append-only delivery events, unique constraints, foreign keys, optimistic version checks, and short transactions. Bind every promoted byte to a Merkle-style dependency manifest containing input hashes, contest identity, evidence snapshot, code/model versions, scenarios, solver configuration, QA report, and user-decision record. Corruption is `QUARANTINED`, never empty.

### F-16 — Promotion state is still distributed even though the immediate vocabulary conflict was repaired

**Component / Discovery Question:** Showdown preflight and manifest state model

**Unbiased Critique & Root Cause:** The prior `review_ready` versus delivery-status contradiction has been repaired and contract-tested. The deeper state problem remains: artifact lifecycle, structural validity, evidence readiness, economic readiness, user decision, delivery, and supersession still live across JSON manifests, flags, filenames, reports, and prose. A closed enum in one module cannot enforce legal cross-artifact transitions or atomically prevent contradictory writers.

**Greenfield Solution & Technical Spec:** Define separate enums: `artifact_state`, `certification_state`, `decision_state`, and `delivery_state`. Generate language bindings and migrations from one schema. Reject unknown values at write time. Model legal transitions in the persisted state machine, and add a contract test that every producer/consumer handles every enum value. Never overload `upload_ready` as a generic success word.

### F-17 — Date-based mutable paths do not provide slate identity

**Component / Discovery Question:** Artifact naming, run directories, and contest reconciliation

**Unbiased Critique & Root Cause:** Some run-manager paths are immutable and hashed, which is a real strength, but shared date-level inputs and `latest` pointers still permit collisions across Classic, Showdown, contest sets, draft groups, and simultaneous sessions. Date plus mode is not enough to prove that a salary file and reserved-entry template describe the same game set. Contest discovery can change while a run is active.

**Greenfield Solution & Technical Spec:** Use a canonical identity tuple: `contest_id`, `draft_group_id`, `game_set_fingerprint`, `mode`, `salary_hash`, `entries_hash`, and `roster_contract_version`. Every artifact must carry it. Reconciliation must compare embedded player pools, game IDs, salary identities, and entry slots before any modeling. Use content hashes for storage and stable logical IDs only as indexes.

### F-18 — Classic and Showdown are two products with unequal safety guarantees

**Component / Discovery Question:** Roster modes, certification, and late swap

**Unbiased Critique & Root Cause:** Classic flows through stronger projection, validation, and certification machinery while Showdown remains review-grade in important paths. Separate implementations duplicate logic and allow fixes to land in only one mode. The user receives a similarly shaped CSV but materially different assurance. Showdown's CPT/UTIL role makes identity more complex, not less deserving of certification.

**Greenfield Solution & Technical Spec:** Implement a common `RosterContract` interface with mode plugins. Shared services own ingestion, evidence, player identity, scenarios, field simulation, economics, optimization, QA, manifests, and late swap. The Classic plugin defines two pitchers, positional slots, salary cap, team minimum, and game diversity. The Showdown plugin defines one CPT, five UTIL, 1.5× salary/points, both-team requirement, and underlying-player uniqueness. Both must satisfy the same promotion policy.

### F-19 — Showdown theses are handcrafted labels rather than latent game states

**Component / Discovery Question:** `showdown_theses.py`, captain logic, and bank relaxations

**Unbiased Critique & Root Cause:** Current theses apply deterministic multipliers to salary-regressed APPG and name narratives such as game scripts. Candidate construction can relax overlap or captain constraints to fill a bank. This creates narrative confidence without a probability model and can quietly violate portfolio intent under scarcity. A thesis written after selecting players is explanation theater if it did not correspond to simulated states used in selection.

**Greenfield Solution & Technical Spec:** Cluster simulated game outcomes into reproducible latent states—pitcher duel, one-sided rout, bullpen collapse, extra innings, concentrated scoring, and so on—and compute each lineup's conditional payoff by cluster. Derive thesis labels from those clusters after selection. Hard constraints remain hard; any configured relaxation creates a new policy version, diagnostic-only state, and explicit blocker. Captain exposure should be portfolio-level and configurable, with `<= 1/3` as the default for a 17-lineup portfolio unless prospective evidence supports another value.

### F-20 — Showdown identity parsing was repaired, but empty starter evidence still degrades to an unsafe pool

**Component / Discovery Question:** `paste_lineups.py` and Showdown pool validation

**Unbiased Critique & Root Cause:** Current parsing correctly collapses CPT and UTIL roster variants to an underlying player, repairing the prior ambiguity defect. However, `showdown.py` can fall back from an empty `Starting` signal to an `all_healthy` pool. That converts absent or unusable role evidence into permissive eligibility. In a single-game product, bench hitters, openers, and uncertain pitchers can then enter a review bank through a structurally valid but evidentially weak path.

**Greenfield Solution & Technical Spec:** Preserve the repaired `UnderlyingPlayer`/roster-variant behavior as golden fixtures. Replace the fallback with an explicit `starter_evidence_state`; `UNKNOWN`, `STALE`, or `CONFLICTED` may generate diagnostic candidates but cannot promote. Starter validation must use normalized evidence roles, never DK position tokens. Test duplicate CPT/UTIL rows, suffixes, accents, abbreviations, both probable pitchers, empty feeds, partial feeds, and contradictory feeds.

### F-21 — Pitcher role vocabulary is duplicated and workload remains categorical

**Component / Discovery Question:** `live_data_adapters.py`, PO/PLR handling, and lineup eligibility

**Unbiased Critique & Root Cause:** Current Showdown policy correctly excludes `PO` and explicitly declares `PLR`, repairing an immediate token-policy defect. But the vocabulary is still mirrored across modules, and a categorical token still mixes evidence (announced opener), forecast (bulk role), and policy (may be rostered). Neither token carries a batters-faced distribution. A cheap pitcher expected to face four batters can still look like value if categorical status substitutes for workload modeling.

**Greenfield Solution & Technical Spec:** Define distinct typed fields: `announced_role`, `projected_role`, `role_confidence`, `expected_batters_faced`, `expected_innings`, and `roster_policy`. `PO` is ineligible to start by default. `PLR` requires an independently sourced bulk-role projection and workload threshold; otherwise it remains diagnostic only. Centralize the policy in the roster contract and test every provider code mapping.

### F-22 — Contest truth is incomplete and too easy to infer

**Component / Discovery Question:** Contest card, entries template, payout, and lock identity

**Unbiased Critique & Root Cause:** A legal lineup file does not prove which reserved contest, fee, field size, payout table, entry limit, or lock schedule it belongs to. Contest attributes can be inferred from filenames or loosely reconciled inputs. Wrong-contest allocation makes all field and EV calculations irrelevant while still yielding valid player IDs and salaries.

**Greenfield Solution & Technical Spec:** Require a signed `ContestSnapshot` assembled from user-supplied files or a permitted structured provider. It must include contest ID, draft group, name, mode, fee, field size, maximum entries, reserved Entry IDs, payout rows, game IDs, lock times, and source provenance. Never infer missing economics from contest-name text for promotion. A missing field may permit structural lineup generation but not EV selection or certification.

### F-23 — Oversized modules and duplicated infrastructure make fixes non-local

**Component / Discovery Question:** Runtime modularity and shared infrastructure

**Unbiased Critique & Root Cause:** The current Python surface is more than thirty thousand lines, with individual modules thousands of lines long. Network clients and durable-write behavior are distributed across many files. This makes a timeout, parser, atomic-write, or identity fix difficult to apply universally and encourages mode-specific shortcuts. Long files also make LLM-assisted maintenance more expensive because every change requires loading unrelated context.

**Greenfield Solution & Technical Spec:** Split packages by stable domain contracts rather than workflow chronology. Centralize HTTP behavior, clocks, identifiers, serialization, content storage, transactions, and policy evaluation. Set review thresholds—roughly 400 lines for ordinary modules and 800 for cohesive numerical kernels—with exceptions justified in architecture records. Require dependency direction from domain to adapters, never the reverse.

### F-24 — Instruction bloat consumes context and creates policy drift

**Component / Discovery Question:** `CLAUDE.md`, `MLB_Classic.md`, and `skills/generate-lineups/SKILL.md`

**Unbiased Critique & Root Cause:** The main instruction files collectively contain many thousands of words, repeated procedures, historical constraints, mode-specific details, and multi-session guidance. Important rules compete with stale implementation commentary. Current context-engineering guidance favors the smallest high-signal system context and just-in-time progressive disclosure. A long prompt does not make an agent more reliable if the decisive rules are buried and duplicated.

**Greenfield Solution & Technical Spec:** Reduce root `CLAUDE.md` to purpose, safety boundaries, authoritative commands, artifact states, and where to load deeper references. Move roster contracts, evidence policy, model notes, incident playbooks, and provider instructions into versioned references retrieved only for the current task. Split the monolithic lineup skill into thin operator, diagnose, research, postmortem, and migration skills. Treat machine-readable schemas and executable checks as authority over prose.

### F-25 — The LLM is being asked to perform deterministic control-plane work

**Component / Discovery Question:** Cowork orchestration and token economics

**Unbiased Critique & Root Cause:** Asking an agent to discover files, interpret state, decide the next routine command, copy fields, retry feeds, and narrate every transition is slower, costlier, and less reproducible than code. The language model's flexibility is useful for ambiguous sources and diagnosis, but it is a liability for hashes, roster rules, deadlines, and state transitions. More agent autonomy inside a prompt does not repair the absence of a durable orchestrator.

**Greenfield Solution & Technical Spec:** Run the normal path from one deterministic CLI/service call. The orchestrator owns state, timers, retries, cancellation, idempotency, and promotion. Invoke an LLM only for approved unstructured public-page extraction, provider mapping proposals, incident explanations, or model research; require structured output and deterministic verification. Budget normal critical-path LLM calls at zero.

### F-26 — Retry logic is local, but the end-to-end process is not a bounded durable loop

**Component / Discovery Question:** Autonomous execution, resumption, and deadlock prevention

**Unbiased Critique & Root Cause:** Individual adapters may have timeouts, yet the overall workflow is driven through sessions and mutable files rather than a persisted state machine. A crash, context reset, partial write, repeated exception, or hung external dependency can leave ambiguous progress. “Keep trying until complete” is not a stopping rule and can burn lock-window time and tokens.

**Greenfield Solution & Technical Spec:** Every unit of work needs an idempotency key, attempt count, next-at time, deadline, and terminal outcome. Use bounded exponential backoff with jitter, circuit breakers, per-provider concurrency limits, and lock-aware cancellation. A watchdog must move overdue work to `FAILED_BOUNDED` or a lower diagnostic tier. Restarting the process must replay state without duplicating side effects.

### F-27 — Runtime is not hermetic on the actual operator platform

**Component / Discovery Question:** Python, NumPy/pandas/SciPy, and deployment

**Unbiased Critique & Root Cause:** The checked lock file targets a specific Python/Linux environment, while this review ran on Windows with Python 3.13 and no NumPy, pandas, or SciPy. The environment probe reports a cold runtime and SciPy MILP unavailable; the audit test run stops after dependency failure. That is an environment-limited validation result, not proof that the code is broken, but it proves the repository alone cannot reproduce its declared runtime here. Installing numerical packages during a lock window is operationally unacceptable.

**Greenfield Solution & Technical Spec:** Ship a prebuilt, versioned runtime for each supported OS/architecture or a locally available OCI image. Pin Python, wheels, native solver, model artifacts, and hashes; publish an SBOM and startup self-test. Warm the worker before slate day and refuse production mode if its image digest differs from the certified digest. No package installation or compilation is allowed in the critical path.

### F-28 — Browser automation is aimed at the wrong surfaces

**Component / Discovery Question:** Claude in Chrome, scraping, and authenticated actions

**Unbiased Critique & Root Cause:** Browser-driving DraftKings to download files, inspect entries, edit rosters, or submit uploads would violate current automation restrictions and create brittle selectors, secret exposure, and ambiguous responsibility for financial actions. Browser extraction from public news pages can also be less reliable and slower than a licensed or documented feed.

**Greenfield Solution & Technical Spec:** Never automate the authenticated DraftKings site. Prefer licensed feeds, official APIs, permitted public endpoints, and user-supplied DK files. Permit browser research only for allowlisted public sites whose terms permit it and only when structured sources are unavailable. Capture raw HTML/screenshot, URL, retrieval time, parser version, and extraction confidence; the browser output enters evidence resolution like any other untrusted source.

### F-29 — Provider authority and freshness rules are scattered in code

**Component / Discovery Question:** Live lineup, injury, weather, roof, umpire, and odds evidence

**Unbiased Critique & Root Cause:** Provider mappings, freshness thresholds, fallbacks, and assumptions are embedded across adapters and workflow files. The system cannot answer one simple question: “Why did this source have authority for this fact at this time?” Adding umpires or a new lineup source under this pattern multiplies special cases. A cached success can be mistaken for a current success.

**Greenfield Solution & Technical Spec:** Define a versioned evidence-policy document with source priority, fact type, allowed age as a function of time to lock, minimum coverage, conflict resolution, and promotion criticality. Adapters only emit assertions; they never decide gates. The resolver produces an explanation graph. Cache raw responses and assertions, but freshness is recomputed at decision time.

### F-30 — Tests and documentation can validate the wrong contract

**Component / Discovery Question:** `MANIFEST.md`, regression tests, and permissive behavior

**Unbiased Critique & Root Cause:** `MANIFEST.md` still describes an older migration seed with stale module and test counts, while current operating instructions expect 26 modules and 871 tests. The test suite is large, but the active environment could execute only the dependency-independent slice. More importantly, many tests necessarily characterize today’s legality/proxy contracts; they cannot establish calibration, exact contest economics, prospective profitability, or deployment reproducibility.

**Greenfield Solution & Technical Spec:** Replace hand-maintained inventory counts with generated reports. Build contract, property, metamorphic, replay, chaos, and golden-file tests around the new invariants. A policy change must update a machine-readable version and its tests. CI must run in the exact production image and report skipped tests as explicit coverage gaps, not success.

### F-31 — Backtests are vulnerable to time leakage and optimizer overfitting

**Component / Discovery Question:** Model selection, scenario reuse, and historical evaluation

**Unbiased Critique & Root Cause:** The live system does not yet contain scenario banks, so scenario reuse is a greenfield risk rather than a current runtime defect. The current defect is the absence of an append-only prospective ledger binding pre-lock predictions and decisions to an as-of evidence snapshot. Once simulation is added, using final lineups, final ownership, settled roles, or the same scenario bank for discovery, selection, tuning, and certification would create leakage and Monte Carlo overfitting.

**Greenfield Solution & Technical Spec:** Use as-of data joins and rolling-origin evaluation. Keep separate scenario banks for model development, candidate discovery, portfolio selection, and an independent referee, each with logged seeds. Lock evaluation protocols before reading holdout results. Promote models through shadow runs and prospective slates, not retrospective anecdotes.

### F-32 — Bankroll and contest selection are outside the optimizer

**Component / Discovery Question:** Portfolio risk, allocation, and contest choice

**Unbiased Critique & Root Cause:** Maximizing lineup upside inside a preselected group of entries ignores the first-order decisions of which contests to enter and how much bankroll to risk. Contest attractiveness is represented by hard-coded scores rather than simulated net utility. Correlated entries can create large hidden downside, and optimizing expected value alone can still be ruinous under model error.

**Greenfield Solution & Technical Spec:** Add bankroll state, daily/weekly risk caps, contest exposure limits, model-uncertainty haircuts, and a utility configuration. Evaluate available contests only from user-supplied or authorized data. Optimize contest-entry count and lineup assignment jointly where allowed, using expected profit plus CVaR or another explicitly selected risk measure. Money movement and final entry remain manual.

### F-33 — Governance currently protects the proxy system from the work needed to become an EV system

**Component / Discovery Question:** Backlog policy and architectural decision making

**Unbiased Critique & Root Cause:** Current backlog guidance deliberately defers Monte Carlo, field ROI, play-by-play simulation, a transactional database, and machine-readable evidence policy. That was defensible scope control for stabilizing the existing legality engine. It is incompatible with the newly stated maximum-EV product objective. Continuing to polish proxy semantics under those anti-goals would be coherent maintenance of the wrong product, not greenfield optimization.

**Greenfield Solution & Technical Spec:** Create a new architecture decision record that supersedes the anti-goals for a separate vNext package. Freeze the current engine as a reference implementation and operational fallback. Fund the EV prerequisites in dependency order and require each milestone to demonstrate measurable information or economic value. Do not retrofit every new concept into the monolith.

### F-34 — Secrets, provenance, and promotion authority are insufficiently isolated

**Component / Discovery Question:** Security and release trust

**Unbiased Critique & Root Cause:** A process that can fetch arbitrary pages, run model code, write artifacts, and label them upload-ready has excessive authority. A compromised provider response or parser could influence both the selected lineup and the system that certifies it. Mutable reports do not prove which bytes were reviewed. Browser sessions compound credential risk.

**Greenfield Solution & Technical Spec:** Use least-privilege service roles: acquisition can write raw blobs, modeling can read resolved evidence, optimization can write candidates, and certification can only read immutable dependencies and sign promotion records. Store secrets outside the repository, redact logs, validate schemas and content sizes, and sandbox parsers. Use keyed signatures or a local signing identity for promotion manifests; verification must occur before a file is presented for manual upload.

### F-35 — Filesystem coordination is advisory and has already failed under concurrent work

**Component / Discovery Question:** Claims files, shared checkout coordination, and writer isolation

**Unbiased Critique & Root Cause:** The documented claims protocol is nominal rather than transactionally enforced, and the repository history records an incident in which concurrent work destroyed uncommitted changes. Runtime coordination also relies on shared mutable date-level files. A prose mutex cannot guarantee exclusive ownership, detect a dead worker, atomically commit state, or prevent two sessions from certifying different bytes. Adding more agents increases collision surface and token spend without increasing truth.

**Greenfield Solution & Technical Spec:** Remove chat/session coordination from the critical path. Give each job an immutable `run_id`, a database-backed lease with owner, expiry, heartbeat, and fencing token, and an isolated content-addressed artifact namespace. Enforce transitions and uniqueness in transactions; a stale worker with an old fencing token cannot write. Keep the source checkout read-only during production runs and write generated artifacts to a separate local runtime root. Use one deterministic orchestrator; parallelize stateless numerical workers only where benchmarks show wall-clock benefit.

## 2. Target Greenfield Architecture & Implementation Specs

### A-01 — Operating model: autonomous computation with a hard decision wall

**Component / Discovery Question:** Product modes and platform-safe operating boundary

**Unbiased Critique & Root Cause:** “Zero touch” is useful when it means no prompt babysitting, but unsafe when it means the system makes every substantive lineup and account decision. The architecture must maximize unattended computation without pretending current DraftKings rules allow unattended production submission.

**Greenfield Solution & Technical Spec:** Implement these modes:

- `SHADOW_AUTONOMOUS`: run the entire research-to-portfolio loop, settle after contests, and never create an account-action instruction. Use it for evaluation.
- `DK_COMPLIANT_PRODUCTION`: autonomously produce a `DecisionPackage` containing two or more portfolios with meaningful EV/risk/ownership differences, explanations, blockers, and immutable hashes. Require a logged substantive user choice before final CSV materialization.
- `DIAGNOSTIC`: always finish structural work when possible, label model/evidence gaps, and produce no upload claim.
- `AUTHORIZED_API`: absent and disabled by default. It can exist only after documented platform permission and a separate security review.

The user must never be asked to supervise retries, fix prompt wording, copy values between stages, or perform intermediate QA. Their only production roles are substantive strategy choice and manual DraftKings account actions.

### A-02 — System topology: separate data, intelligence, economics, and trust planes

**Component / Discovery Question:** Service boundaries and dependency direction

**Unbiased Critique & Root Cause:** A single workflow that downloads data, interprets it, builds projections, selects lineups, and certifies itself cannot isolate failures or establish trust. Separating modules only by filename is insufficient if they share mutable state and authority.

**Greenfield Solution & Technical Spec:** Build five planes with typed artifacts between them:

```mermaid
flowchart LR
  S["Permitted sources and user files"] --> I["Ingestion and immutable evidence"]
  I --> M["Baseball model and joint scenarios"]
  M --> E["Field, payouts, and economics"]
  E --> O["Candidate and portfolio optimization"]
  O --> Q["Independent certification"]
  I --> Q
  Q --> D["Decision-ready package"]
  D --> H["Substantive user choice"]
  H --> X["Manual DraftKings action"]
```

Ingestion has no optimization authority. Modeling cannot alter evidence. Optimization cannot mark itself certified. Certification is a separately launched process with read-only access to immutable inputs. The orchestrator coordinates IDs and events but cannot override policy results.

### A-03 — Clean implementation tree and package contracts

**Component / Discovery Question:** Repository layout for vNext

**Unbiased Critique & Root Cause:** Incremental additions to the current large modules will preserve circular dependencies and mode-specific behavior. An implementation agent needs a target layout and clear ownership.

**Greenfield Solution & Technical Spec:** Create a new package alongside the current engine:

```text
dfs_vnext/
  domain/       ids.py contest.py roster.py evidence.py artifacts.py states.py
  ingest/       dk_files.py provider_client.py adapters/ normalize.py
  store/        schema.sql blob_store.py repositories.py migrations/
  model/        opportunity.py skills.py event_rates.py game_sim.py calibration.py
  field/        ownership.py construction.py sampler.py duplication.py
  economics/    payouts.py settlement.py utility.py uncertainty.py
  optimize/     roster_contract.py candidates.py portfolio.py solvers.py
  swap/         observations.py conditioning.py optimizer.py
  certify/      legality.py evidence.py economics.py referee.py promotion.py
  orchestrate/  fsm.py workers.py retries.py scheduler.py watchdog.py
  explain/      decision_package.py reports.py
  cli.py
tests_vnext/
schemas/
policy/
```

Domain objects must be dependency-free and immutable. Adapters implement protocols owned by the domain layer. No module may read an arbitrary workspace path; all I/O goes through injected repositories and content stores.

### A-04 — Canonical identity and immutable artifact graph

**Component / Discovery Question:** IDs, hashes, provenance, and reproducibility

**Unbiased Critique & Root Cause:** Reproducible optimization is impossible if “today's slate” or a mutable filename identifies inputs. Every downstream conclusion must be traceable to exact bytes and code.

**Greenfield Solution & Technical Spec:** Define:

```python
SlateKey = (
    contest_id,
    draft_group_id,
    game_set_fingerprint,
    mode,
    salary_sha256,
    entries_sha256,
    roster_contract_version,
)
```

Every artifact header contains `artifact_id`, `artifact_type`, `schema_version`, `created_at_utc`, `as_of_utc`, `producer_version`, `configuration_hash`, `parent_artifact_ids`, and `payload_sha256`. Store payloads by hash and never modify them. Derived logical names resolve through database rows. Reproduction means loading the same dependency graph and deterministic seeds, not copying a date folder.

### A-05 — Transactional state store with append-only events

**Component / Discovery Question:** SQLite/PostgreSQL authority and JSON views

**Unbiased Critique & Root Cause:** JSON is excellent for interchange and poor as a concurrently updated authority. The system needs atomic state transitions, uniqueness, crash recovery, and inspectable history.

**Greenfield Solution & Technical Spec:** Use SQLite in WAL mode for one local host, short write transactions, a bounded busy timeout, explicit checkpointing, and storage on a local filesystem. SQLite documents that readers and a writer can coexist in WAL mode but there is still only one writer; serialize high-contention commands accordingly. Use PostgreSQL only when multi-host workers are justified. Minimum tables: `slates`, `contests`, `runs`, `artifacts`, `artifact_edges`, `evidence_assertions`, `effective_facts`, `jobs`, `events`, `model_snapshots`, `scenario_banks`, `candidates`, `portfolios`, `certifications`, `decisions`, and `deliveries`. JSON files are regenerated immutable reports.

### A-06 — Persisted finite-state machine with monotonic transitions

**Component / Discovery Question:** Orchestration lifecycle

**Unbiased Critique & Root Cause:** A reliable autonomous system must know what has completed, what can run in parallel, what can be retried, and what has permanently failed without relying on chat history.

**Greenfield Solution & Technical Spec:** Use this primary lifecycle:

```text
DISCOVERED
  -> INPUTS_VALIDATED
  -> EVIDENCE_COLLECTING
  -> MODEL_READY
  -> SCENARIOS_READY
  -> CANDIDATES_READY
  -> PORTFOLIO_READY
  -> QA_COMPLETE
  -> DECISION_READY
  -> USER_DECISION_RECORDED
  -> CERTIFIED_PACKAGE
  -> DELIVERED
```

Parallel terminal or holding states are `DIAGNOSTIC_READY`, `EVIDENCE_PENDING`, `QUARANTINED`, `EXPIRED`, `SUPERSEDED`, and `FAILED_BOUNDED`. Transitions append events and use compare-and-swap versions. Unknown evidence can allow modeling states but cannot cross the certification transition. Jobs resume from committed artifacts after restart.

### A-07 — Bounded workers, deadlines, and a deterministic degradation ladder

**Component / Discovery Question:** Non-blocking autonomy and lock-window behavior

**Unbiased Critique & Root Cause:** High throughput is not achieved by infinite retries or by dropping safety checks. The system needs an explicit answer when time or data runs out.

**Greenfield Solution & Technical Spec:** Every job specifies `deadline`, `timeout`, `max_attempts`, `backoff`, `idempotency_key`, and `fallback_tier`. Use bounded exponential backoff with jitter and provider circuit breakers. Define degradation:

1. full calibrated model, full scenario and field counts;
2. fewer simulations with reported Monte Carlo standard error;
3. cached model parameters plus current evidence;
4. legal diagnostic proxy with no EV claim;
5. structural report only.

Never degrade player eligibility, roster legality, identity checks, or promotion evidence. The watchdog terminates overdue processes and records a reason. No worker is allowed to wait past the package's useful lock-relative deadline.

### A-08 — Machine-readable evidence policy and explanation graph

**Component / Discovery Question:** Fact resolution and promotion gates

**Unbiased Critique & Root Cause:** Evidence rules will drift if freshness and authority live in arbitrary code branches. Operators and certifiers need the same declarative contract.

**Greenfield Solution & Technical Spec:** Add `policy/evidence_policy.v1.yaml` with entries for `batting_lineup`, `player_active`, `pitcher_role`, `weather`, `roof`, `postponement`, `game_start`, `lock`, `contest_contract`, and `payout`. Each entry declares authoritative sources, backup sources, maximum age by minutes-to-lock, required coverage, conflict rules, and whether it blocks modeling, selection, or promotion. Assertions retain raw source hashes. The resolver emits an explanation graph showing which assertions produced each effective fact. Only resolver output can feed certification.

### A-09 — Unified provider framework

**Component / Discovery Question:** Network acquisition, normalization, and observability

**Unbiased Critique & Root Cause:** Duplicated network behavior creates inconsistent caching, retries, timestamps, and failure semantics. Provider data must be treated as untrusted and temporally scoped.

**Greenfield Solution & Technical Spec:** Implement one async `ProviderClient` with connection and total timeouts, retry budgets, host rate limits, response-size limits, caching, ETag/Last-Modified support, schema validation, and raw-blob capture. Adapters return typed assertions and never write shared files. Normalize team, player, game, and timezone identities centrally. Log retrieval start/end, source URL or endpoint identifier, status, hash, parser version, and coverage without logging secrets.

### A-10 — DraftKings file intake and reconciliation

**Component / Discovery Question:** Salaries, entries, contest templates, and immutable preservation

**Unbiased Critique & Root Cause:** User-provided DK files are the safest source of contest and player-pool truth, but filename guesses and partial parsing can mix slates. Input bytes must be preserved before any normalization.

**Greenfield Solution & Technical Spec:** On receipt, hash and copy bytes to the blob store, detect encoding and dialect without mutating the source, parse into versioned schemas, and reconcile salaries with entries at row and player-pool level. Detect Classic versus Showdown from slot contracts, not names. Reject ambiguous multiple templates into `INPUT_CONFLICT`, while still providing a diagnostic inventory. Preserve the original column order and values for final byte-level comparison.

### A-11 — Typed player, role, and roster identity

**Component / Discovery Question:** Underlying players, roster variants, teams, and game roles

**Unbiased Critique & Root Cause:** String names, DK position tokens, and provider status codes cannot safely represent the same person across Classic, Showdown, and late swap.

**Greenfield Solution & Technical Spec:** Create `UnderlyingPlayer(player_id, canonical_name, team_id, game_id)` and mode-specific `RosterVariant(slot_role, salary, scoring_multiplier)`. Store provider aliases separately with confidence and source. Pitchers get an independent role object rather than a position-code inference. Enforce that two roster variants of one underlying player cannot coexist in Showdown. All exports resolve back to the exact DK ID and roster position required by the source template.

### A-12 — Opportunity-first hitter and pitcher models

**Component / Discovery Question:** Playing time, lineup position, and workload distributions

**Unbiased Critique & Root Cause:** Event-rate sophistication is wasted if plate appearances or pitcher workload are wrong. DFS scoring is highly sensitive to opportunity.

**Greenfield Solution & Technical Spec:** Model hitter lineup inclusion and plate appearances jointly with lineup slot, home/away status, expected innings, team scoring, and pinch-hit/substitution risk. Model pitcher start probability, opener/bulk role, pitch-count distribution, batters faced, innings, and removal hazard. Use hierarchical priors for sparse players and explicit injury/return states. Output samples, not just means. A role confidence below policy threshold prevents production selection even if the mathematical projection is attractive.

### A-13 — Calibrated baseball event-rate models

**Component / Discovery Question:** Batter-pitcher skills, Statcast, park, weather, and bullpen

**Unbiased Critique & Root Cause:** Maximum EV depends on calibrated tails and correlations, not a list of advanced-stat multipliers. The model must distinguish signal from descriptive noise and quantify uncertainty.

**Greenfield Solution & Technical Spec:** Fit probabilistic K, BB/HBP, home-run, batted-ball type, hit, extra-base, and steal submodels with handedness interactions, player latent skill, pitcher mix/velocity/location, catcher/umpire where reliable, park, roof, temperature, wind, altitude, bullpen quality/availability, and defense. Use shrinkage and missingness indicators. Retain features only after rolling-origin improvement in log loss or proper scoring rules. Version data cutoffs and publish feature lineage.

### A-14 — Joint plate-appearance and game simulator

**Component / Discovery Question:** Correlated fantasy scoring scenarios

**Unbiased Critique & Root Cause:** Independent player samples cannot correctly value stacks, pitcher opposition, bullpen cascades, win bonuses, or concentrated scoring.

**Greenfield Solution & Technical Spec:** Simulate lineups through innings or an equivalent state model. Each plate appearance samples event type conditioned on batter, pitcher, base/out state, handedness, environment, and fatigue; update runners, outs, score, pitcher removal, bullpen, and batting-order turn. Translate events to DraftKings scoring in a separate roster-contract module. Use deterministic counter-based random streams so parallel execution is reproducible. Combine independent games into slate scenarios while preserving within-game dependence.

### A-15 — Calibration, uncertainty, and model promotion

**Component / Discovery Question:** Distribution validation and prospective model registry

**Unbiased Critique & Root Cause:** A simulator can be detailed and still be wrong. Mean error alone will not reveal bad tails, correlations, or overconfidence—the quantities tournament optimization uses most.

**Greenfield Solution & Technical Spec:** Evaluate opportunity, event, and fantasy-point distributions with log score, Brier score, calibration curves, PIT diagnostics, interval coverage, tail exceedance rates, covariance error, and stratified residuals. Compare against simple baselines. Use rolling time splits and prospective shadow runs. Register a model only after predefined gates pass; failed or uncertain models remain shadow-only. Store parameter and training-data hashes.

### A-16 — Disjoint scenario banks and simulation governance

**Component / Discovery Question:** Candidate discovery, selection, and referee independence

**Unbiased Critique & Root Cause:** Optimizing and evaluating on the same random scenarios converts Monte Carlo noise into apparent edge.

**Greenfield Solution & Technical Spec:** Produce at least four seeded banks: `development`, `candidate_discovery`, `portfolio_selection`, and `independent_referee`. They may share a model snapshot but not random streams. The selection bank estimates the objective; the referee bank reports held-out EV, risk, and Monte Carlo error after the portfolio is frozen. Scenario artifacts record seed families, counts, weighting, simulator version, and effective sample size. Never retune on referee results for the same slate.

### A-17 — Hierarchical ownership and field-construction model

**Component / Discovery Question:** Contest-conditioned opponent behavior

**Unbiased Critique & Root Cause:** Ownership is a joint lineup-generation problem. Commercial DFS tools publicly emphasize realistic opponent-field simulations because payout value depends on who else enters what, not only on individual popularity.

**Greenfield Solution & Technical Spec:** Model player selection logits plus construction structure hierarchically by Classic/Showdown, contest family, stakes, field size, max entries, slate size, and time regime. Include team stacks, stack size and order adjacency, bring-backs, pitcher pairs, salary left, total ownership, captain choice, and entrant portfolio correlations. Sample legal opponent lineups and calibrate against held-out mined fields. Report uncertainty bands, especially for rare contest segments.

### A-18 — Exact payout, tie, and duplicate settlement

**Component / Discovery Question:** Contest simulation economics

**Unbiased Critique & Root Cause:** An EV engine must turn fantasy outcomes and field construction into dollars with correct tie behavior. Approximate percentile scores are not enough.

**Greenfield Solution & Technical Spec:** Vectorize lineup scoring by sparse player-incidence matrices and scenario score matrices. For each contest/scenario, add the user's candidate, rank all entries, identify tie blocks, sum prizes for occupied ranks, divide by all tied entries, and subtract the entry fee. Support flat payouts, satellites/tickets, and noncash prizes only through explicit valuation policy. Validate against hand-calculated golden contests and permutation invariance.

### A-19 — Monte Carlo uncertainty and conservative EV labels

**Component / Discovery Question:** Estimation error and decision robustness

**Unbiased Critique & Root Cause:** Rare top prizes create noisy EV estimates. Selecting the largest noisy sample mean creates winner's-curse bias, especially across a huge candidate bank.

**Greenfield Solution & Technical Spec:** Use common random numbers across candidates, batched estimates, bootstrap or batch-means standard errors, and a conservative score such as `LCB_EV = mean_profit - z * standard_error`. Shrink unstable segment estimates toward a baseline. Report effective scenario count, EV standard error, probability of profit, cash rate, top-percentile rate, and CVaR. If uncertainty exceeds policy, increase simulations within budget or downgrade the claim to `ECONOMIC_ESTIMATE_UNSTABLE`.

### A-20 — Economically driven candidate generation

**Component / Discovery Question:** Best-response columns, k-best solutions, and convergence

**Unbiased Critique & Root Cause:** A candidate bank should cover economically useful responses to plausible futures, not merely combinatorial diversity.

**Greenfield Solution & Technical Spec:** Seed with high-mean legal lineups, then add scenario best responses, leverage-sensitive solutions, game-state-cluster winners, contest-segment solutions, and risk hedges. Use no-good cuts for k-best enumeration and perturb economic coefficients rather than arbitrary player scores. Iterate candidate generation and portfolio selection with held-out marginal utility estimates. Stop on a hard deadline or when no recent column improves conservative held-out utility beyond tolerance.

### A-21 — Solver adapter with benchmarked MILP/CP-SAT choices

**Component / Discovery Question:** Optimization backend and termination semantics

**Unbiased Critique & Root Cause:** Solver fashion is not architecture. SciPy MILP/HiGHS and OR-Tools CP-SAT have different strengths, and status handling matters more than the logo. A time-limited feasible solution is not optimal; `UNKNOWN` is not infeasible.

**Greenfield Solution & Technical Spec:** Define a `SolverResult` contract with `status`, incumbent, bound, gap, runtime, node count where available, and diagnostics. Benchmark SciPy/HiGHS, native HiGHS if appropriate, and CP-SAT on representative Classic, Showdown, candidate, and joint-portfolio models. Use integer-safe CP-SAT formulations only where appropriate. Pick backends per problem based on prospective latency and correctness tests. Enforce time limits and distinguish `OPTIMAL`, `FEASIBLE`, `INFEASIBLE`, `MODEL_INVALID`, `TIME_LIMIT_NO_SOLUTION`, and `ERROR`.

### A-22 — Scenario-level portfolio optimization

**Component / Discovery Question:** Entry assignment, reuse, exposure, and risk

**Unbiased Critique & Root Cause:** Lineups are not independent assets. Their returns share players, stacks, games, and field-duplication risk. Exposure rules are rough substitutes for direct scenario covariance.

**Greenfield Solution & Technical Spec:** For selected lineups `x[l,c]`, maximize a declared portfolio utility over scenario total profit:

```text
maximize  mean(P_s)
        - lambda * CVaR_alpha(-P_s)
        - eta * MonteCarloUncertainty
        - kappa * concentration_cost
```

subject to one lineup per Entry ID, contest eligibility, bankroll limits, uniqueness, configured exposure limits, and any operator decision. Use sparse conflict graphs, decomposition, or lazy cuts to control size. Treat lineup reuse as an explicit variable whose economics include duplicate and covariance effects, not a sign-prone score penalty.

### A-23 — Contest selection and bankroll utility

**Component / Discovery Question:** Which contests and how many entries

**Unbiased Critique & Root Cause:** The best lineup for a bad contest is still a bad allocation. Bankroll survival and model uncertainty must constrain theoretical EV.

**Greenfield Solution & Technical Spec:** Accept a user-supplied or authorized contest catalog. Estimate field strength and economics by contest segment, then jointly recommend contest counts and portfolios subject to daily risk, sport allocation, max loss, entry-limit, and liquidity policies. Support expected log growth, fractional Kelly with conservative edge haircuts, or mean-CVaR as explicit configuration. Default to no recommendation when the contest economics are incomplete.

### A-24 — Unified Classic and Showdown roster contracts

**Component / Discovery Question:** Mode plugins and legality

**Unbiased Critique & Root Cause:** Shared economics and evidence should not be duplicated, but roster constraints must remain explicit and mode-aware.

**Greenfield Solution & Technical Spec:** Define `RosterContract` methods for slots, salary/scoring transform, team/game requirements, variant identity, legality constraints, scoring, and export. `ClassicContract` enforces the current DK slot and salary rules from the input template. `ShowdownContract` uses one CPT and five UTIL, 1.5× salary and fantasy points for CPT, at least one player from each team, and no repeated underlying player. Rules must be versioned from current DK documentation and confirmed against each source template.

### A-25 — Showdown-specific field and portfolio design

**Component / Discovery Question:** Captain, duplication, underlying-player overlap, and theses

**Unbiased Critique & Root Cause:** Showdown has a small combinatorial space and severe duplication. Captain identity and game-state dependence dominate economics, so generic Classic diversity logic is inadequate.

**Greenfield Solution & Technical Spec:** Generate role-aware opponent fields with captain ownership, salary duplication, and common construction archetypes. Jointly enforce the configured captain cap, defaulting to no more than 5 of 17 lineups for one underlying player, and a default pairwise overlap limit of four underlying players unless a contest-specific model justifies another policy. Each selected lineup receives a named thesis derived from its highest-payoff simulated game-state cluster plus probability and conditional EV. No post-hoc player swaps are allowed to manufacture thesis diversity.

### A-26 — Conditional late swap as a new optimization problem

**Component / Discovery Question:** Observed outcomes, locks, ownership, and remaining uncertainty

**Unbiased Critique & Root Cause:** Late swap is not a projection refresh with locked columns. The value of an unlocked player depends on observed portfolio performance, actual ownership if legitimately available, opponents, remaining games, and payout thresholds.

**Greenfield Solution & Technical Spec:** At each allowed refresh, freeze locked underlying players and observed fantasy points, update permitted evidence, condition or resimulate remaining games, and rebuild the relevant opponent-field branches. Optimize remaining slots for conditional portfolio utility. Add lineup churn only as a secondary operational cost. Use DraftKings' player lock-at-game-time rule from the supplied contest/template; never scrape authenticated live standings. If actual ownership/standings are supplied by the user, preserve and hash them as new observations.

### A-27 — Generation fail-open; promotion fail-closed

**Component / Discovery Question:** Availability without false assurance

**Unbiased Critique & Root Cause:** Treating every missing feed as fatal prevents useful computation, while treating it as a warning makes certification meaningless. These are different stages and should have different policies.

**Greenfield Solution & Technical Spec:** Candidate and portfolio generation may proceed with explicit priors, cached models, or unknown evidence and must complete within budget. The artifact state records every degradation. Promotion is a separate transaction and fails closed on any hard-gate `FAIL`, `UNKNOWN`, `STALE`, or `CONFLICTED`. The system always emits the best safe diagnostic plus a concise blocker list. Only certified bytes lose the prominent `DO_NOT_UPLOAD` marker.

### A-28 — Independent referee and final-byte certification

**Component / Discovery Question:** QA process and trust separation

**Unbiased Critique & Root Cause:** Re-running the same functions that generated a lineup is not independent QA. Shared bugs and mutable files will pass twice.

**Greenfield Solution & Technical Spec:** Launch `dfs-certify` as a clean process. It independently parses the original DK inputs and proposed final bytes, rebuilds the roster contract, validates player IDs, salaries, slot eligibility, team/game rules, uniqueness, Entry ID mapping, lock state, exposure and overlap policy, evidence closure, contest identity, and artifact dependency hashes. It must not import optimizer selection code. It writes an immutable `CertificationReport` and a signed promotion event. Corrupt or missing dependencies yield `QUARANTINED`.

### A-29 — Decision-ready package and substantive user choice

**Component / Discovery Question:** Human interface at the platform-compliance boundary

**Unbiased Critique & Root Cause:** A vague “review this” click is neither helpful nor clearly substantive. Conversely, forcing the user to inspect hundreds of rows defeats autonomy.

**Greenfield Solution & Technical Spec:** Present two to four portfolio alternatives that differ materially—for example, higher mean EV, lower downside risk, lower duplication, or different game-state concentration. For each, show conservative EV estimate, uncertainty, loss probability, CVaR, major exposures, model/evidence grade, and a plain-language trade-off. Require the user to select an alternative or set a material risk/strategy parameter; record the selection and artifact hashes. After selection, rerun the independent byte certifier and produce a manual-upload CSV plus DraftKings' documented upload instructions.

### A-30 — Signed, hash-bound promotion manifest

**Component / Discovery Question:** Delivery integrity and supersession

**Unbiased Critique & Root Cause:** A CSV can be modified after review, and a filename cannot prove which run is current.

**Greenfield Solution & Technical Spec:** The promotion manifest contains final-file SHA-256, full artifact dependency root, contest/slate identity, code and model versions, evidence policy version, effective-fact snapshot, solver results, referee report, user-decision record, creation/expiry times, and superseded package IDs. Sign it with a local promotion key. A lightweight verifier recomputes the CSV hash immediately before presentation. Any changed byte, expired lock state, or newer critical evidence revokes the package and returns to `DECISION_READY`.

### A-31 — Event-driven evidence refresh and invalidation

**Component / Discovery Question:** Lineups, injuries, weather, odds, and lock scheduling

**Unbiased Critique & Root Cause:** Fixed polling either wastes traffic early or reacts too slowly near lock. New evidence can invalidate projections, candidates, portfolios, and certifications at different scopes.

**Greenfield Solution & Technical Spec:** Schedule refresh frequency by time to lock and provider policy, with jitter and strict rate limits. Normalize new assertions and compare effective facts. Emit scoped invalidation events: a lineup-slot change reruns opportunity and affected game simulations; a weather change reruns the game block; a payout change reruns economics; a salary/contest identity change invalidates the full run. Cancel stale jobs by generation number so old results cannot overwrite new state.

### A-32 — Context-engineered Cowork skills

**Component / Discovery Question:** `CLAUDE.md`, skills, and progressive disclosure

**Unbiased Critique & Root Cause:** The operator should not pay a context and error tax for loading the entire system every run. Anthropic's current guidance emphasizes lightweight root instructions and progressively disclosed skills and references.

**Greenfield Solution & Technical Spec:** Keep root instructions to roughly 60–100 high-signal lines: goal, compliance boundary, do-not-upload semantics, source of truth, one command, and emergency stop. Create thin skills:

- `dfs-run`: identify supplied inputs and invoke the orchestrator;
- `dfs-status`: read the state store and explain blockers;
- `dfs-diagnose`: collect reproducible failure evidence;
- `dfs-research-provider`: investigate an unknown public source under allowlist policy;
- `dfs-postmortem`: settle predictions and produce calibration reports;
- `dfs-migrate`: execute versioned artifact/schema migrations.

Each skill loads only its schema, reference, and commands. Do not duplicate executable rules in prose.

### A-33 — Bounded agent exception loop

**Component / Discovery Question:** LLM planning, verification, and stopping conditions

**Unbiased Critique & Root Cause:** Modern agent loops are useful only when the environment supplies durable state and skeptical evaluation. An unbounded “continue until done” prompt can repeat the same failure.

**Greenfield Solution & Technical Spec:** When an exception genuinely requires an LLM, pass a compact packet: goal, current state, immutable evidence, allowed tools, deadline, previous attempts, and acceptance tests. The agent proposes one structured action. A deterministic verifier decides whether it worked. Limit attempts by error class and total wall time; after repeated identical failure, open a diagnostic incident and continue at the next safe degradation tier. The agent cannot edit evidence statuses, certification results, or platform capability flags.

### A-34 — Performance budgets and warm execution

**Component / Discovery Question:** Latency SLOs, caching, and throughput

**Unbiased Critique & Root Cause:** “Lightning-fast” without target hardware, scenario counts, error bars, and deadlines is marketing. Speed must be measured against output quality.

**Greenfield Solution & Technical Spec:** Benchmark on the actual deployment machine and target a warm news-to-revised-decision-package p95 under 45 seconds with a 60-second hard deadline. Initial budgets: intake/reconciliation 1 second; permitted provider fan-out 8 seconds; incremental model update 3 seconds; affected game simulations 15 seconds; candidate refresh 20 seconds; field/economic evaluation 20 seconds; portfolio solve 8 seconds; independent QA 3 seconds. Stages may overlap, so budgets are not summed mechanically. Report achieved scenario count, standard error, solver gap, and degradation tier. Preload models and numerical libraries before the slate.

### A-35 — Cost architecture and build-versus-buy decisions

**Component / Discovery Question:** Compute, data licensing, and LLM spend

**Unbiased Critique & Root Cause:** Local Python is cheap, but reliable real-time data and engineering attention are not. Recreating every provider is not automatically lower cost, and constant LLM browsing is both expensive and unreliable.

**Greenfield Solution & Technical Spec:** Instrument cost per slate by provider, CPU/GPU, storage, and LLM. Keep LLM calls off the normal path. Benchmark licensed lineup/injury/weather/odds sources by timeliness, historical availability, identity quality, and terms—not headline price. Shadow-test internal field and projection models against vendor exports when lawfully available. Buy commodity truth when it is cheaper than maintaining scrapers; build the proprietary joint modeling and portfolio economics where differentiation lives.

### A-36 — Observability, replay, and incident evidence

**Component / Discovery Question:** Metrics, logs, traces, and operator visibility

**Unbiased Critique & Root Cause:** Autonomous systems fail silently unless their timing, evidence, uncertainty, and state transitions are visible. Raw logs are not an operating dashboard.

**Greenfield Solution & Technical Spec:** Emit structured events with run/slate/job IDs. Track minutes to lock, evidence coverage/freshness/conflicts, provider latency and circuit state, artifact generation age, scenario counts and Monte Carlo error, calibration drift, field-model error, solver status/gap/runtime, candidate marginal utility, QA blockers, package expiry, and cost. Provide one local status page and a machine-readable summary. A replay command must rebuild any run from its event log and immutable artifacts without network access.

### A-37 — Security and platform-action isolation

**Component / Discovery Question:** Credentials, network allowlists, sandboxing, and financial safety

**Unbiased Critique & Root Cause:** Optimization output can affect real money. A high-autonomy research process should never inherit account authority by convenience.

**Greenfield Solution & Technical Spec:** Run acquisition with an outbound allowlist and no DraftKings credentials. Store provider secrets in the operating system secret store or injected environment, never files or logs. Validate content types, schemas, decompression limits, and filenames. Run untrusted parsers in a restricted process. The certifier has no network and read-only artifact access. The delivery UI cannot click, paste into, or control DraftKings. Add tests proving those network and action boundaries.

### A-38 — Test strategy based on invariants and adversarial cases

**Component / Discovery Question:** Unit, property, replay, chaos, and economic validation

**Unbiased Critique & Root Cause:** Example-based happy-path tests will miss the identity, concurrency, and evidence failures most likely to cause a bad upload.

**Greenfield Solution & Technical Spec:** Require:

- property tests for salary, slots, uniqueness, underlying-player identity, tie settlement, and deterministic seeds;
- golden tests for real redacted Classic and Showdown templates;
- metamorphic tests such as field-entry permutation invariance and prize conservation across ties;
- concurrency tests for duplicate jobs, lost updates, supersession, and database locks;
- chaos tests for truncated files, corrupt manifests, provider timeouts, stale caches, process kills, and clock boundaries;
- as-of leakage tests and disjoint scenario-bank tests;
- independent certifier mutation tests that alter one byte, ID, salary, status, or evidence timestamp;
- performance tests in the production image.

No skipped hard-gate test counts as a passing production build.

### A-39 — Prospective evaluation and economic scorecard

**Component / Discovery Question:** Shadow results, calibration, and promotion evidence

**Unbiased Critique & Root Cause:** DFS returns are noisy and top-heavy; a few wins do not validate a model, while a short losing streak does not disprove it. The system needs a prospective scorecard instead of anecdotes.

**Greenfield Solution & Technical Spec:** Before production recommendation, run full shadow mode over a prespecified number of future slates and record predictions before lock. Report projection calibration, ownership calibration, construction-distribution fit, duplication error, contest profit with confidence intervals, downside risk, turnover, latency, and failure rates by segment. Use historical seasons for training and rolling tests, but reserve future slates for final validation. Define thresholds before the sample begins and disclose when the sample lacks power for a profitability claim.

### A-40 — Migration plan that preserves operations while replacing the engine

**Component / Discovery Question:** Incremental greenfield rollout

**Unbiased Critique & Root Cause:** Burning down the current engine in one release would discard valuable legality rules and create a long period with no operational fallback. Equally, indefinitely wrapping the old monolith would prevent the new trust and economic model from emerging.

**Greenfield Solution & Technical Spec:** Execute in dependency order:

1. **Baseline:** freeze current behavior, golden inputs, latency, QA findings, and proxy outputs.
2. **Foundation:** implement domain IDs, blob store, transactional schema, FSM, evidence policy, and roster-contract parity.
3. **Model shadow:** build opportunity/event models, joint simulator, ledger, and calibration without affecting production output.
4. **Economics shadow:** build field sampling, payout/tie settlement, uncertainty, and EV scorecards.
5. **Optimization:** add economic candidate generation, portfolio selection, and conditional late swap.
6. **Trust:** deploy the independent referee, signed manifests, decision package, and security boundaries.
7. **Controlled cutover:** compare both systems prospectively; retain the current engine as rollback until vNext meets every acceptance gate.

Each phase produces a usable artifact and can be stopped without corrupting the old workflow.

### A-41 — First implementation backlog for a secondary agent

**Component / Discovery Question:** Ordered epics and concrete deliverables

**Unbiased Critique & Root Cause:** A visionary document fails if the next agent cannot translate it into a dependency graph. Starting with a sophisticated simulator before identity, evidence, and replay would recreate the current trust problem.

**Greenfield Solution & Technical Spec:** Create these epics in order:

1. `VNX-001` canonical schemas and roster contracts, including Showdown CPT/UTIL and PO/PLR tests;
2. `VNX-002` content-addressed blob store and original-input preservation;
3. `VNX-003` SQLite schema, migrations, append-only events, and concurrency tests;
4. `VNX-004` persisted FSM, idempotent job runner, watchdog, and replay;
5. `VNX-005` provider client, typed assertions, and evidence-policy resolver;
6. `VNX-006` independent structural/live-evidence certifier and signed manifest;
7. `VNX-007` prospective ledger and as-of dataset builder;
8. `VNX-008` opportunity and event models with baseline comparisons;
9. `VNX-009` joint game simulator and calibration harness;
10. `VNX-010` contest-conditioned field generator and duplication validation;
11. `VNX-011` exact payout/tie settlement and uncertainty estimates;
12. `VNX-012` candidate column generation and portfolio optimizer;
13. `VNX-013` conditional late swap and mode parity;
14. `VNX-014` decision package and substantive-choice audit trail;
15. `VNX-015` performance, chaos, security, and prospective shadow gates.

Each ticket must specify schemas, commands, tests, migration behavior, rollback, and measurable acceptance evidence.

### A-42 — Definition of done and non-negotiable acceptance gates

**Component / Discovery Question:** Release criteria for the greenfield system

**Unbiased Critique & Root Cause:** Without a hard definition of done, proxy outputs will gradually acquire EV labels and diagnostic files will be called upload-ready. The system must be judged by falsifiable properties.

**Greenfield Solution & Technical Spec:** The system is not complete until all of the following hold:

- Original salary, entries, contest, and evidence bytes are immutable and hash-bound to every output.
- Classic and Showdown legality match current DraftKings templates, including role-aware underlying-player identity.
- `UNKNOWN`, `STALE`, `CONFLICTED`, and failed evidence can never reach a certified state.
- Missing economics can never produce an EV, ROI, or expected-profit label.
- Joint scenarios, field samples, exact payouts, ties, fees, and duplicate counts are used in the production objective.
- Candidate discovery, portfolio selection, and referee simulations use disjoint random streams.
- Every solver outcome exposes status, incumbent, bound/gap, and deadline behavior.
- Process kills, retries, duplicate jobs, corrupt artifacts, and concurrent sessions replay without silent loss.
- The independent certifier detects single-byte and single-field mutations and binds the final CSV to its dependency graph.
- Warm end-to-end refresh meets the benchmarked lock-window SLO or produces a bounded, clearly degraded diagnostic.
- The normal critical path uses no LLM calls and performs no automated DraftKings account action.
- Production materialization requires a recorded substantive user decision; account login, upload, entry, and money movement remain manual.
- Prospective calibration and economic scorecards meet thresholds defined before their evaluation window; otherwise the system remains shadow or diagnostic.

Until those gates are satisfied, the honest label for the current and transitional systems is **legal-lineup and portfolio-shape tooling with diagnostic economic proxies**, not a maximum-EV engine.

### A-43 — Exact zero-touch execution contract from input arrival to delivery

**Component / Discovery Question:** One-command workflow, event triggers, outputs, and bounded failure behavior

**Unbiased Critique & Root Cause:** A component diagram is not an autonomous operating procedure. If the implementation still requires an agent to remember command order, interpret a warning, move a file, or decide whether to retry, human supervision has merely moved from a checklist into chat. The workflow must specify its legal input boundary, automatic transitions, time budgets, terminal states, and the one point at which user agency is intentionally required.

**Greenfield Solution & Technical Spec:** Expose one normal entry point, for example `dfs run --inbox <local-path> --mode dk-compliant`, plus a local scheduler that watches only an authorized local inbox. It must execute this contract:

1. **Acquire local inputs:** detect newly supplied salary, entries, and contest files; copy exact bytes to the content store; hash, schema-validate, reconcile, and create `SlateKey`/`ContestSnapshot`. Never browse or control DraftKings.
2. **Start a fenced run:** create `run_id`, lease, deadlines, code/runtime digest, and immutable configuration. Duplicate idempotency keys attach to the existing run rather than start a second writer.
3. **Collect permitted evidence:** fan out typed provider jobs concurrently under rate, retry, and wall-clock budgets. Store raw responses and assertions; resolve effective facts through policy. Missing facts do not stop diagnostic computation.
4. **Freeze model inputs:** materialize an as-of feature snapshot, opportunity distributions, model version, and uncertainty metadata. Record the snapshot in the prospective ledger before lock.
5. **Simulate:** create disjoint candidate-discovery, portfolio-selection, and referee scenario banks from counter-based seed families. Incremental refresh regenerates only invalidated game blocks.
6. **Build field and economics:** generate legal contest-conditioned opponent entries, validate held-out construction statistics, settle the exact payout/tie table, and attach uncertainty. Incomplete contest economics blocks EV labels.
7. **Generate candidates:** run mode-specific roster contracts and economic column generation in parallel partitions; merge by canonical lineup hash; stop at convergence tolerance or deadline.
8. **Optimize the portfolio:** assign one candidate per Entry ID using the declared utility and solver adapter. Persist incumbent, bound/gap, status, runtime, and degradation tier. A feasible time-limit result is labeled feasible, never optimal.
9. **Run the independent referee:** freeze selection, evaluate it on unseen scenarios, independently verify artifact graph, evidence closure, contest identity, roster legality, Entry IDs, exposures, and byte determinism. Failures create `DIAGNOSTIC_READY` or `QUARANTINED`, not a retry loop.
10. **Emit `DecisionPackage`:** if policy-complete, create two to four materially distinct portfolio alternatives with conservative economics, uncertainty, risk, exposure, duplication, evidence grade, and trade-offs. If not, create the best diagnostic package with `DO_NOT_UPLOAD` and exact blockers. Send only a local notification; do not require an LLM to narrate status.
11. **Pause for the sole required production decision:** the user selects a material portfolio/risk alternative. Record the choice and hashes. A timeout leaves the run at `DECISION_READY`; it never chooses on the user's behalf.
12. **Materialize and certify final bytes:** fill only the selected reserved Entry IDs in a derivative of the exact supplied template, preserve non-target rows and columns, independently reparse the bytes, sign the promotion manifest, and show expiry plus manual-upload instructions. The system must not open, log into, paste into, or submit to DraftKings.
13. **React before lock:** new effective facts emit scoped invalidations. Debounce bursts, cancel older generation numbers, condition on locked players, repeat steps 4–10 within the 60-second hard budget, and revoke stale packages automatically.
14. **Evaluate after the contest:** when the user or an authorized source supplies standings, store them immutably, settle the pre-lock ledger without rewriting forecasts, update calibration/economic reports, and leave model promotion to prespecified gates.

Every step is idempotent and produces either a committed artifact plus next event or a bounded terminal/holding state. No step may sleep indefinitely, install dependencies, request prompt edits, convert unknown evidence to pass, or mutate an earlier artifact. The implementation acceptance test is an unattended replay from local input drop to `DECISION_READY`, crash/restart at every transition, deterministic output hashes under fixed inputs/seeds, and a proof that no DraftKings network or UI action is possible.
