# DFS System Greenfield Red-Team and Implementation Specification

**Review date:** 2026-08-01  
**Repository snapshot:** branch **master**, commit **48b4e7e**  
**Scope:** DraftKings MLB Classic and single-game Showdown lineup generation, portfolio construction, late swap, evidence collection, certification, and delivery  
**Review mode:** Existing workspace files were inspected read-only. This document is the only file created by the review.

**Executive verdict:** The current repository is a serious legality-and-audit engine wrapped around a weak quantitative core. It can construct legal rosters, preserve artifacts, and expose many operational warnings. It cannot truthfully claim to maximize expected value because it has no calibrated joint player-outcome distribution, no fitted contest-specific opponent model, no payout/tie-split simulator, and no bankroll-aware objective. Its live promotion boundary is also unsafe: missing, stale, partial, or unreadable lineup evidence can remain warnings; odds and weather can be assumed; late swap treats any confirmed team as a slate-wide lineup pass; and concurrent manifest writers can lose state. The correct greenfield move is to retain the useful roster contracts and adversarial QA lessons, but replace the prompt-led workflow, factor-multiplier projection stack, heuristic candidate scoring, filesystem coordination, and ambiguous certification model.

**Hard truth about “zero human intervention”:** Zero-touch data ingestion, modeling, candidate generation, QA, monitoring, and file delivery are achievable. Zero-touch DraftKings login, salary/entry download, contest entry, lineup upload, or late-swap submission is not an acceptable design target under the current [DraftKings Fantasy Sports Fair Play Commitment](https://support.draftkings.com/dk/en-us/fantasy-sports-fair-play-commitment?id=kb_article_view&sysparm_article=KB0010662), which identifies browser scripts and bots as prohibited assistance. The current repository correctly recognizes that boundary in **CLAUDE.md:102-115**. Therefore:

- The production target is **zero-touch from an authorized input drop or licensed feed to a signed, hash-bound, promotion-eligible upload candidate**.
- DraftKings account interaction remains one explicit human action unless DraftKings grants written, machine-readable API access and written authorization for the intended automation.
- Claude-in-Chrome or any other browser agent must never be used to bypass this boundary.

**Evidence standard:** “Observed” below means directly verified in this repository. “Vendor-claimed” means a feature described by a vendor on its own current product page, not independently validated performance. The supplied **C:\Users\benja\Downloads\dfs_analytics_platforms_comparison.md** was used as a hypothesis map, not as proof. The linked X post could not be reliably extracted and is not treated as an architectural authority; the loop design instead relies on Anthropic’s current, directly accessible guidance.

## 1. Critical Flaws, Bottlenecks & Architectural Anti-Patterns

### F-01 — The engine optimizes a score, not expected value

- **Title / Component:** Objective function and product truth
- **Adversarial Critique & Rationale:** The system’s central optimization claim is structurally weaker than the requested business objective. Classic candidate generation maximizes deterministic projection-derived scores and hand-authored bonuses. Entry allocation normalizes a contest-shape heuristic to a 0–100 range and minimizes its negative (**mlb_engine/allocate/contest_allocator.py:1615-1627**). There is no simulated contest field, payout curve, tie splitting, entry fee, or opponent duplication in this objective. “Best lineup” therefore means “highest internal proxy under constraints,” not “highest expected net return.” The current truthful-label rule in **CLAUDE.md:8-14** correctly forbids calling this ROI, but that also concedes the primary greenfield objective is absent.
- **Proposed Architecture & Implementation Spec:** Replace every production ranking with a payout-aware expected-net-profit estimate derived from a joint game simulation and contest-specific opponent field. Until that model clears prospective shadow validation, expose only **proxy_score**, **mechanically_valid**, and **diagnostic_candidate**. Reserve **estimated_ev**, **roi**, **win_probability**, and **cash_probability** for versioned, calibrated model outputs whose prediction timestamp predates lock.

### F-02 — DraftKings AvgPointsPerGame contaminates the quantitative foundation

- **Title / Component:** Base projections and emergency proxy
- **Adversarial Critique & Rationale:** The pipeline falls back from Base to DraftKings **AvgPointsPerGame** (**mlb_engine/pipeline/execution_pipeline.py:2391-2395**), and the Showdown module explicitly uses it as the deterministic base proxy (**mlb_engine/optimize/showdown.py:1-13**). When Savant corrections are supplied, the pipeline can still recalculate Base from AvgPointsPerGame (**execution_pipeline.py:2447-2451**). AvgPointsPerGame is a backward-looking platform display statistic, not a context-neutral estimate of today’s plate appearances, matchup, role, or distribution. It can embed prior batting-order position, injuries, changing roles, small samples, and DraftKings-specific selection effects. Multiplying it by factors does not turn it into a calibrated forecast.
- **Proposed Architecture & Implementation Spec:** Delete AvgPointsPerGame from every production numerical path. It may remain an audit-only comparison baseline. Build player forecasts from projected opportunity and event rates: plate appearances and batting-order turnover for hitters; batters faced, innings, pitch count, and role for pitchers; then convert simulated baseball events to DraftKings scoring. If required inputs are absent, generate a clearly labeled diagnostic from a league-average replacement model, but never promote it.

### F-03 — Multiplicative factors manufacture false precision

- **Title / Component:** Projection builder
- **Adversarial Critique & Rationale:** The current formula is Base × F1 × F2 × F3 × F4 × F5, with default Floor = 0.58 × projection and Ceiling = 1.42 × projection (**mlb_engine/projections/projection_builder.py:81-149**). This is deterministic scenario dressing, not a probability distribution. Fixed floor and ceiling multipliers are especially misleading in MLB, where a leadoff power hitter, a ninth-place contact hitter, a high-strikeout starter, and a volatile opener have radically different tail shapes. Multiplicative adjustment factors can double-count correlated evidence such as implied totals, park, weather, and opponent quality.
- **Proposed Architecture & Implementation Spec:** Replace factor multiplication with explicit probabilistic submodels. Every adjustment must enter once at the causal layer it affects: weather and park alter batted-ball outcomes; batting order alters opportunity; pitcher handedness alters event rates; bullpen quality alters later plate appearances. Produce scenario matrices, quantiles, and covariance diagnostics from simulation rather than fixed multipliers.

### F-04 — Player outcomes are not simulated jointly

- **Title / Component:** Correlation and tail modeling
- **Adversarial Critique & Rationale:** MLB tournament edge is driven by conditional co-outcomes: a team scoring ten runs lifts several hitters together, opposing pitchers collapse, bullpen exposure changes, and lineup turnover creates additional plate appearances. The current system approximates this through stack rules, ceiling multipliers, and named theses. That encodes average human intuition but cannot distinguish two stacks with similar means and very different joint tail behavior. The supplied platform comparison correctly points toward play-by-play simulation; SaberSim also currently claims full game scripts and correlated ranges, but that is a vendor capability claim rather than proof of model quality.
- **Proposed Architecture & Implementation Spec:** Generate a joint scenario matrix with one column per player and one row per simulated slate. Simulate games sequentially at the plate-appearance level or with a validated vectorized approximation that preserves shared game state. Use the same scenario identifier across hitters, pitchers, bullpen transitions, weather, and late-swap conditioning. Candidate and field lineups must be scored against the identical scenario rows.

### F-05 — No opponent field means no leverage model

- **Title / Component:** Ownership and field construction
- **Adversarial Critique & Rationale:** The only ownership model is explicitly an “UNCALIBRATED STRUCTURAL PRIOR” that softmaxes salary, batting order, implied totals, probable-starter status, and optional value (**mlb_engine/field/ownership_prior.py:1-27, 48-68, 101-215**). It is not integrated into production. Player marginal ownership alone is insufficient: MLB fields make correlated choices involving primary stack team, stack shape, secondary stack, salary left, pitcher pairs, lineup order, chalk concentration, and contest archetype. Without a realistic field distribution, “leverage” is a slogan.
- **Proposed Architecture & Implementation Spec:** Fit a contest-archetype-conditioned generative field model from archived standings, with separate components for player inclusion, stack team, stack geometry, pitcher pair, salary utilization, and conditional co-roster patterns. Calibrate the generated field against player, team-stack, pair, shape, duplication, and salary-left distributions. A field simulator that matches only marginal ownership does not pass.

### F-06 — Payout shape, ties, and duplication are absent

- **Title / Component:** Contest economics
- **Adversarial Critique & Rationale:** A lineup’s value depends on where its score lands in a specific payout table and how many opponents tie it. A lineup that wins rarely but alone may dominate a lineup that cashes often in a flat payout, while the reverse can hold in cash games. Current contest-shape bonuses such as Stable, Volatile, and Eruption tiers are manually weighted proxies. They cannot price an exact top-heavy payout, a one-seat satellite, a double-up, or a 150-max tournament.
- **Proposed Architecture & Implementation Spec:** Parse and snapshot the exact contest payout table, entry fee, field size, maximum entries, and reserved-entry count. For every scenario, rank user and field lineups, split tied prizes exactly, subtract entry fees, and retain the complete profit distribution. Optimize mean net profit subject to configured risk and bankroll limits. A contest with no exact payout snapshot cannot receive an EV label.

### F-07 — The allocator contains a known objective-sign defect

- **Title / Component:** Joint candidate-to-entry allocation
- **Adversarial Critique & Rationale:** When max_shared_players is active, the allocator assigns a positive minimization cost to each candidate-use variable (**contest_allocator.py:1608-1627**). This rewards using fewer distinct candidates, the opposite of the apparent “reuse_penalty” name. The live backlog and **docs/next_session_prompts.md:39-62** already acknowledge the defect. This is not merely cosmetic: near-tie entries can collapse onto reused lineups, directly degrading portfolio diversification.
- **Proposed Architecture & Implementation Spec:** Remove the term immediately in the legacy engine. In the greenfield engine, express reuse only through explicit, tested constraints or a correctly signed portfolio utility. Never retain a configuration key whose behavior is ambiguous. Add an objective-coefficient snapshot test and a behavioral near-tie test.

### F-08 — Candidate prefiltering can create phantom infeasibility

- **Title / Component:** Candidate-bank coverage and solve strategy
- **Adversarial Critique & Rationale:** The allocator reduces the bank before solving because pairwise overlap constraints scale quadratically (**contest_allocator.py:1581-1596**). If the filtered bank cannot satisfy interacting exposure constraints, the solver returns failure without retrying the full bank (**contest_allocator.py:1786-1826**). A legal solution can therefore exist in discarded candidates while the system reports infeasibility. This is an architecture tax created by building a large generic bank and then applying dense pairwise constraints.
- **Proposed Architecture & Implementation Spec:** Generate contest-specific candidates, retain coverage diagnostics, and build a sparse conflict graph. On failure, deterministically widen the bank or add violated overlap cuts iteratively. A proof of infeasibility must refer to the complete eligible candidate universe or explicitly say **SEARCH_INCOMPLETE**. Never collapse timeout, search truncation, and mathematical infeasibility into one state.

### F-09 — The bank is heuristic and expensive at the same time

- **Title / Component:** Candidate generation
- **Adversarial Critique & Rationale:** Candidate generation repeatedly solves deterministic MILPs across forced pitcher pairs, stack teams, and scenario families. It pays repeated solver setup costs but still explores a hand-authored slice of lineup space. The build records when its job list was not exhausted or budget was exhausted (**skills/generate-lineups/scripts/build_slate.py:1374-1390**), yet later allocation can still treat the slice as the working universe. The approach is neither exhaustive nor tied to contest payout utility.
- **Proposed Architecture & Implementation Spec:** Use scenario-conditioned k-best generation. Sample high-value slate scenarios, solve the lineup best responding to each scenario and contest field, retain near-optimal alternatives, deduplicate, and Pareto-prune dominated candidates. Cache roster constraint matrices and warm-start the solver. Bank completeness is measured by scenario coverage and marginal EV convergence, not a fixed lineup count.

### F-10 — “Assumed” gates can certify production artifacts

- **Title / Component:** Workflow gates and certification semantics
- **Adversarial Critique & Rationale:** The build automatically assumes odds and weather gates when their maps are absent (**build_slate.py:1394-1408**). The pipeline then changes a missing derived gate from None to True (**execution_pipeline.py:3026-3034**). Recording the assumption in diagnostics is honest narration, but it does not make the evidence true. A certification bit built from assumed facts is a false authorization boundary.
- **Proposed Architecture & Implementation Spec:** Delete Boolean gate overrides. Each gate evaluation must carry **status = PASS | FAIL | UNKNOWN | STALE | NOT_APPLICABLE**, evidence snapshot IDs, policy version, evaluated_at, and expires_at. Only PASS or justified NOT_APPLICABLE may enter promotion. UNKNOWN and STALE may generate diagnostics but can never become promotion-eligible.

### F-11 — Missing, unreadable, or stale lineup evidence can still be upload-ready

- **Title / Component:** Preflight lineup validation
- **Adversarial Critique & Rationale:** An unreadable feed is a warning and skips the cross-check; a feed older than 90 minutes is a warning; no resolved feed is a warning (**tools/preflight_upload.py:761-782, 942-949**). With no other failure and no non-certified manifest label, the verdict becomes upload_ready (**preflight_upload.py:997-1018**). The behavior is intentionally pinned by **tests/test_upload_integrity.py:611-615**. This directly contradicts zero-touch safety: the case most likely to roster a benched player is permitted to promote.
- **Proposed Architecture & Implementation Spec:** Generation remains fail-open, promotion becomes fail-closed. Require a current lineup fact for every rostered hitter’s team and a current starter/role fact for every rostered pitcher. Missing, unreadable, stale, partial, or conflicting evidence yields **EVIDENCE_PENDING** or **QUARANTINED**, never upload-ready. Freshness thresholds must be policy-driven by time to lock, not a fixed 90-minute constant.

### F-12 — Partial feeds can overwrite durable slate state

- **Title / Component:** Lineup feed staging
- **Adversarial Critique & Rationale:** A supplied feed is rejected only when it covers under half the slate’s teams, so exactly 50% coverage is accepted and written to the shared date-level feed path (**build_slate.py:2207-2238**). The write is not transactional with its validation. When a stale feed refetch fails, the stale feed is reused by design (**build_slate.py:2239-2252**). A partial or stale feed can therefore become the durable basis for a later build while looking structurally normal.
- **Proposed Architecture & Implementation Spec:** Never overwrite source snapshots. Store every fetch as immutable content-addressed JSON, then derive a separate normalized fact set. Coverage is evaluated per required game side and player role, not by a 50% slate threshold. Publish a new active evidence version only inside one database transaction after schema, identity, coverage, and freshness checks pass.

### F-13 — Late swap’s lineup gate is globally wrong

- **Title / Component:** Late-swap evidence
- **Adversarial Critique & Rationale:** Late swap sets lineup_gate_passed to bool(confirmed_teams), so one confirmed team makes the slate-wide gate true (**tools/late_swap.py:605-626**). It also assumes pitcher audit, weather, and odds (**late_swap.py:88-100, 620-634**). This is most dangerous at the moment the engine is supposed to react to asymmetric news.
- **Proposed Architecture & Implementation Spec:** Evaluate lineup status at the player/team/game grain. Every proposed unlocked player must reference a current eligible-status fact; every locked player must be preserved; every affected game must reference the latest weather/roof and starter evidence. Late-swap promotion requires a complete evidence closure over the exact proposed portfolio, not a global slate Boolean.

### F-14 — Manifest writes are atomic but not concurrent

- **Title / Component:** Artifact registry and supersession
- **Adversarial Critique & Rationale:** The manifest uses temp-file plus os.replace, which prevents half-written JSON, but record_delivery performs an unlocked read-modify-write (**mlb_engine/entries/upload_manifest.py:85-104, 107-171**). Two writers can read the same version, independently supersede records, and overwrite one another. read_manifest also converts unreadable state into an empty manifest, erasing the distinction between “never existed” and “corrupt.”
- **Proposed Architecture & Implementation Spec:** Move artifact and promotion state to a transactional database with unique keys and optimistic version checks. Keep the JSON manifest as an immutable exported view, never the authority. Corruption is a hard state with preserved bytes and an alert; it is never interpreted as empty.

### F-15 — Showdown is a second, uncertified product

- **Title / Component:** Classic/Showdown architecture
- **Adversarial Critique & Rationale:** The root contract explicitly states Showdown is review-grade, bypasses workflow_valid, selection_certified, allocation_certified, and cannot use the certified late-swap path (**CLAUDE.md:216-223**). The Showdown module says it imports nothing from the Classic solver (**mlb_engine/optimize/showdown.py:15-16**). Duplication reduces test coupling but also creates two product semantics, two promotion paths, and no unified evidence contract.
- **Proposed Architecture & Implementation Spec:** Implement one mode-agnostic engine with roster-contract plugins. Classic and Showdown share ingestion, evidence, projections, scenarios, field simulation, payout evaluation, portfolio optimization, manifests, and promotion. Only roster geometry, role multipliers, salary identity, stacking priors, and lock rules differ.

### F-16 — Showdown theses are handcrafted stories, not game states

- **Title / Component:** Showdown scenario generation
- **Adversarial Critique & Rationale:** The thesis ladder uses fixed suppression factors and a deterministic prior allocation (**mlb_engine/optimize/showdown_theses.py:1-18, 37-50, 367-454**). The solver can relax overlap, captain locks, and theses to fill the requested bank (**showdown.py:328-389; showdown_theses.py:484 onward**). A label such as “favorite wins a shootout” does not prove the chosen roster is valuable in a probabilistically coherent subset of outcomes.
- **Proposed Architecture & Implementation Spec:** Derive Showdown theses from clusters of simulated game trajectories. Each thesis is a human-readable summary of a scenario cluster after the model exists, never an input multiplier. Captain selection is valued through role-specific scenario payoff and predicted role-aware duplication. Portfolio caps remain hard unless a policy explicitly authorizes a diagnostic relaxation; relaxed output cannot promote.

### F-17 — Showdown starter filtering is vulnerable to partial-post state

- **Title / Component:** Showdown pool construction
- **Adversarial Critique & Rationale:** If any salary rows carry a declared Starting value, melt_showdown_salary_csv restricts the pool to declared rows (**mlb_engine/optimize/showdown.py:138-150**). The two-team check prevents a one-team pool, but a partially posted set on both sides can still yield a small biased pool. “Some declared rows exist” is not evidence that both teams’ complete eligible roles are posted.
- **Proposed Architecture & Implementation Spec:** Construct the pool from team-side evidence states: **UNPOSTED**, **PARTIAL**, **CONFIRMED_COMPLETE**, **CONFLICTED**. Restrict a side to confirmed starters only when that side is complete. Treat partial as non-promotable and retain the prior complete version for diagnostics, never blend implicit partial truth.

### F-18 — Monoliths concentrate change risk and import cost

- **Title / Component:** Code modularity
- **Adversarial Critique & Rationale:** The tracked tree has 60 Python files and roughly 37,400 Python lines, but the largest files dominate: test_core about 6,248 lines, optimizer_v3 about 3,644, execution_pipeline about 3,118, build_slate about 2,097, and contest_allocator about 1,765. Live acquisition, enrichment, bank strategy, gating, promotion, reporting, and CLI behavior are intertwined. A small state change requires understanding thousands of lines and can create accidental cross-mode effects.
- **Proposed Architecture & Implementation Spec:** Split by stable domain contracts, not by arbitrary file size: identity, roster rules, evidence facts, projection distributions, scenario store, field model, contest economics, candidate generation, portfolio solve, QA, promotion, and orchestration. Keep modules below a soft 500-line review threshold and functions below a soft 60-line threshold, with exceptions justified by generated code or declarative schemas.

### F-19 — Prompt and skill context are production dependencies

- **Title / Component:** Claude Cowork context engineering
- **Adversarial Critique & Rationale:** **CLAUDE.md** is about 224 lines and the generation skill about 569 lines. They contain crucial truth, historical incidents, scheduling behavior, file coordination, test pins, environment repairs, and operational procedure. Some instructions conflict in spirit: “do not write a new review document” conflicts with the present user request; build paths warn but ship stale platoon data; session docs disagree on 589 versus 591 tests. Anthropic’s current guidance says it removed over 80% of its own system prompt without measurable evaluation loss, recommends lightweight CLAUDE.md files, interface design, and progressive disclosure.
- **Proposed Architecture & Implementation Spec:** Make the live system independent of agent recall. Move invariants into typed code, state transitions, database constraints, and deterministic validators. Reduce root CLAUDE.md to product boundary, destructive-action constraints, and repository gotchas. Split skills by operator intent and load references only when invoked. A skill may call the engine; it must not define the engine’s truth.

### F-20 — Filesystem claims are a homemade scheduler

- **Title / Component:** Concurrency and session coordination
- **Adversarial Critique & Rationale:** **CLAUDE.md:148-208** implements claims, beacons, owner files, stale-date conventions, role-specific write sets, and manual arbitration because Cowork sessions have no shared scheduler. This is fragile distributed-systems logic encoded in prose and mkdir conventions. It does not provide leases, fencing tokens, atomic state transitions across resources, dead-worker recovery, or durable queued work.
- **Proposed Architecture & Implementation Spec:** Replace claims with a persisted job/state system. A single-node deployment should use SQLite transactions, leases, and fencing tokens. A distributed deployment may move to Postgres or a durable workflow engine. Agents become clients that request operations; they do not coordinate by editing files.

### F-21 — Network acquisition is synchronous, duplicated, and deadline-hostile

- **Title / Component:** Live-data adapters
- **Adversarial Critique & Rationale:** The repository contains repeated urllib fetch logic in build_slate, fetch_slate_bundle, fetch_rotowire_lineups, live_data_adapters, refresh_reference_data, and wheel_fetch. Calls use independent 20–25 second timeouts and mostly sequential control flow. There is no shared connection pool, circuit breaker, provider health state, global deadline, retry budget, or stale-while-revalidate policy. A single provider can consume most of the lock window.
- **Proposed Architecture & Implementation Spec:** Implement one asynchronous acquisition service with provider-specific adapters, connection reuse, per-call timeout, global stage deadline, exponential backoff with jitter, maximum attempts, circuit breakers, cache validators, and stale snapshot semantics. Fetch independent sources concurrently. Retries stop at the earlier of attempt budget or stage deadline.

### F-22 — Runtime setup is not productionized

- **Title / Component:** Packaging, environment, and CI
- **Adversarial Critique & Rationale:** requirements.txt has only unbounded floors; requirements.lock is pinned to Python 3.10 Linux x86_64; there is no pyproject.toml and no tracked CI workflow. The current Windows audit failed because NumPy, pandas, and SciPy were unavailable and ran only 60 tests before failing. **docs/next_session_prompts.md:18-36** describes broken local libraries, manual wheel installation, a full filesystem, and a stale Git lock. These are symptoms of treating an ephemeral Cowork sandbox as the runtime platform.
- **Proposed Architecture & Implementation Spec:** Ship a reproducible application image and a cross-platform developer environment. Use pyproject.toml, locked dependency groups, hash-verified wheels, a prebuilt solver runtime, CI on Windows and Linux, and a startup health check. Live runs must never install packages. Environment readiness is established before slate day.

### F-23 — Test count has become a proxy for correctness

- **Title / Component:** Verification quality
- **Adversarial Critique & Rationale:** CLAUDE.md pins 591 tests, next_session_prompts pins 589, MANIFEST.md records 119, and the ledger reports intermediate counts. More importantly, a named test deliberately requires missing feed to “never block.” A large test count can faithfully preserve the wrong product contract. A 6,000-line test monolith also makes targeted ownership and fault isolation harder.
- **Proposed Architecture & Implementation Spec:** Stop gating on a magic count. Gate on named suites, coverage of safety invariants, mutation score, property-based fuzzing, schema compatibility, fault injection, and replay fixtures. Break tests into domain modules. Explicitly classify tests as **mechanical**, **evidence**, **model**, **economic**, **concurrency**, and **recovery**.

### F-24 — Historical data is incomplete and selection-biased

- **Title / Component:** Calibration archive
- **Adversarial Critique & Rationale:** The current review fragment reports about 74 delivered contests unarchived, payout coverage ending on 2026-07-28, a contest duplicated across date folders, and 0 seats in 234 archived one-seat-satellite entries (**ledger/inbox/2026-08-01_REVIEW_mined-data-review.md:8-24, 27-41**). Manual standings download creates missing-not-at-random data: painful or forgotten slates may be underrepresented. Post-hoc field mining cannot validate a model that did not publish predictions before lock.
- **Proposed Architecture & Implementation Spec:** Create an immutable prediction ledger before every lock and a completeness ledger after contests. Dedupe on contest_id plus operator. Track missingness explicitly. Model evaluation uses walk-forward splits and only predictions timestamped before the relevant lock. No backfilled feature may masquerade as a live prediction.

### F-25 — Contest identity and policy are inferred too loosely

- **Title / Component:** Contest truth
- **Adversarial Critique & Rationale:** Salary and entry CSVs are treated as strong inputs, but exact payout, field size, max entries, late-swap eligibility, and contest status are not uniformly bound to the promoted artifact. Contest names and local archetype mappings are useful hints but can drift. A legal-looking roster for the wrong contest is still a failure.
- **Proposed Architecture & Implementation Spec:** Require a normalized, immutable ContestSnapshot keyed by operator contest ID and draft-group identity. Bind the entries CSV hash, salary CSV hash, roster contract version, payout table, entry fee, field size, max entries, lock schedule, and late-swap policy into the promotion manifest. Unknown contest economics permits legal diagnostic generation but not EV labeling.

### F-26 — Browser automation is proposed where APIs and policy should dominate

- **Title / Component:** Browser and scraping strategy
- **Adversarial Critique & Rationale:** Browser agents are slow, expensive, visually brittle, hard to replay, and poor evidence sources unless every response is snapshotted. Using Claude-in-Chrome for DraftKings would also conflict with the fair-play boundary. Browser automation can make a demo look autonomous while creating an untestable single point of failure.
- **Proposed Architecture & Implementation Spec:** Prefer licensed APIs, public structured endpoints, email/file drops, or operator-provided exports. Use browser automation only for permitted public sources that lack structured access, behind a provider adapter that captures URL, timestamp, raw response/screenshot, parser version, and terms review. Browser failure must not block the state machine indefinitely.

### F-27 — Current data sources are not governed as a portfolio

- **Title / Component:** Provider authority and conflict resolution
- **Adversarial Critique & Rationale:** The system mixes operator files, pasted MLB lineups, an API feed, RotoWire, odds, weather references, Savant, FanGraphs, and hand-maintained mappings. Authority rules exist in prose but not in a single machine-readable matrix. Conflicts, staleness, and partial coverage are handled differently across scripts.
- **Proposed Architecture & Implementation Spec:** Define a versioned EvidencePolicy per fact type with source priority, freshness, minimum coverage, conflict behavior, fallback behavior, and promotion criticality. Preserve all source assertions; derive one effective fact only through the policy evaluator. Never silently overwrite a higher-authority assertion.

### F-28 — The loop has no bounded, persisted control plane

- **Title / Component:** Autonomous execution loop
- **Adversarial Critique & Rationale:** The current T-minus schedule is a prompt procedure, not a durable finite-state process. A tool call can time out, a session can die, a filesystem can fill, or a provider can hang, leaving the next session to reconstruct intent from files. “Never block execution” is interpreted inconsistently: some failures warn and proceed, while other paths stop without a resumable job identity.
- **Proposed Architecture & Implementation Spec:** Implement a persisted finite-state machine with explicit stage deadlines, retry budgets, terminal states, and idempotency keys. Separate “continue generating the best diagnostic” from “authorize promotion.” Every wait must be attached to a timer or event subscription and have a maximum duration. No while-true loop without a durable stop condition.

### F-29 — There is no economic feedback loop

- **Title / Component:** Model and strategy evaluation
- **Adversarial Critique & Rationale:** The ledger contains useful observed shape statistics, but the system does not persist pre-lock player distributions, ownership forecasts, field samples, candidate EV estimates, selected-versus-rejected candidate comparisons, or confidence intervals. It therefore cannot attribute profit/loss to projection error, ownership error, field-shape error, payout simulation error, optimization, or variance.
- **Proposed Architecture & Implementation Spec:** Persist all pre-lock model outputs and selection decisions. After result ingestion, grade each layer separately: opportunity, event probabilities, player distributions, covariance, ownership, stack distributions, duplication, contest ranks, payouts, and portfolio utility. Strategy changes require prospective evidence, not result-based storytelling.

### F-30 — Bankroll and contest selection are outside the optimizer

- **Title / Component:** Capital allocation
- **Adversarial Critique & Rationale:** Even perfect lineup EV can be overwhelmed by entering the wrong contests, overconcentrating a bankroll, or buying too many correlated entries. The current system assigns reserved entries but does not optimize whether those contests and quantities should have been entered. One-seat satellites with 0 seats in 234 archived entries demand economic scrutiny, not just better lineup geometry.
- **Proposed Architecture & Implementation Spec:** Add a separate pre-entry bankroll service that evaluates contest selection and entry counts before money is committed. It may recommend zero entries. Because DraftKings entry and money actions remain human-only, output a contest plan with expected edge, uncertainty, correlation, maximum loss, bankroll fraction, and a hard responsible-gaming cap.

## 2. Greenfield Architecture, Feature Enhancements & Implementation Specs

### A-01 — Define the product as two planes with one manual boundary

- **Title / Component:** System operating model
- **Adversarial Critique & Rationale:** Making an LLM the workflow, data model, and control plane produces slow, expensive, irreproducible execution. Pretending DraftKings account interaction can be automated creates a compliance defect.
- **Proposed Architecture & Implementation Spec:** Build:
  1. A **deterministic data plane** for ingestion, modeling, simulation, optimization, QA, state, and artifacts.
  2. A **thin agent/operator plane** for natural-language requests, research, exception explanation, and postmortems.
  3. A **manual DraftKings boundary** for authorized source exports and final upload/submission.

  The engine runs with no LLM dependency. An operator drops authorized inputs into an inbox or an approved licensed feed posts them. The system emits **HUMAN_UPLOAD_REQUIRED** plus one exact file, hash, contest identity, expiry, and preflight result. Full account automation is feature-flagged off permanently unless a reviewed written authorization artifact is present.

### A-02 — Target component architecture

- **Title / Component:** Greenfield service map
- **Adversarial Critique & Rationale:** The current build script mixes stages that have different correctness, latency, and retry semantics.
- **Proposed Architecture & Implementation Spec:** Implement this dependency flow:

        authorized input drop / licensed feeds
                       |
                       v
        Intake + Identity Registry
                       |
                       v
        Immutable Raw Snapshot Store
                       |
          +------------+-------------+
          |                          |
          v                          v
        Evidence Normalizer       Contest Snapshot
          |                          |
          +------------+-------------+
                       v
        Feature Store + Opportunity Models
                       |
                       v
        Joint Game/Slate Scenario Simulator
                       |
          +------------+-------------+
          |                          |
          v                          v
        Field Generator          Candidate Generator
          |                          |
          +------------+-------------+
                       v
        Payout/EV Evaluator + Portfolio Solver
                       |
                       v
        Independent QA + Promotion Policy
                       |
                       v
        Signed Artifact Registry
                       |
                       v
              HUMAN_UPLOAD_REQUIRED

  Every arrow passes a versioned typed object by ID. No stage discovers truth by scanning an output directory.

### A-03 — Create a clean implementation tree

- **Title / Component:** Python package structure
- **Adversarial Critique & Rationale:** A secondary implementation agent needs boundaries that make ownership and tests obvious.
- **Proposed Architecture & Implementation Spec:** Start a new package beside the legacy engine and do not incrementally mutate the monolith:

        pyproject.toml
        src/dfs_greenfield/
          contracts/
            roster.py
            contest.py
            evidence.py
            promotion.py
          intake/
            dk_csv.py
            identity.py
            inbox.py
          providers/
            base.py
            mlb_lineups.py
            weather_nws.py
            odds.py
            projections_vendor.py
          evidence/
            normalize.py
            policy.py
            closure.py
          models/
            opportunity_hitters.py
            opportunity_pitchers.py
            event_rates.py
            game_simulator.py
            calibration.py
          field/
            ownership.py
            lineup_generator.py
            calibration.py
          economics/
            payouts.py
            tie_split.py
            ev.py
            bankroll.py
          optimize/
            candidate_generator.py
            portfolio.py
            conflicts.py
          qa/
            mechanical.py
            evidence.py
            independent_export.py
          orchestration/
            state_machine.py
            worker.py
            deadlines.py
          artifacts/
            store.py
            manifest.py
            signer.py
          cli.py
        tests/
          contracts/
          property/
          replay/
          concurrency/
          model/
          promotion/

  Legacy code is read-only during shadow development. Promote modules by contract replacement, not file copying.

### A-04 — Use a persisted, monotonic state machine

- **Title / Component:** Run lifecycle
- **Adversarial Critique & Rationale:** Boolean flags and filenames cannot express partial evidence, supersession, or bounded retry.
- **Proposed Architecture & Implementation Spec:** Persist these states:

        RECEIVED
        IDENTITY_VALIDATED
        EVIDENCE_PENDING
        EVIDENCE_COMPLETE
        SCENARIOS_READY
        FIELD_READY
        CANDIDATES_READY
        PORTFOLIO_READY
        MECHANICALLY_VALID
        MODEL_ELIGIBLE
        PROMOTION_ELIGIBLE
        HUMAN_UPLOAD_REQUIRED
        SUPERSEDED
        QUARANTINED
        EXPIRED
        FAILED

  State transitions are append-only events and use compare-and-swap on run_version. Generation may proceed from EVIDENCE_PENDING using diagnostic fallbacks, but promotion may only proceed through EVIDENCE_COMPLETE. Quarantined and expired runs are terminal for promotion. New evidence creates a new version and supersedes downstream artifacts by dependency graph; it never mutates a prior artifact.

### A-05 — Replace date folders as authority with transactional identity

- **Title / Component:** Database and immutable store
- **Adversarial Critique & Rationale:** Date folders collide across slates, late games, modes, and concurrent writers.
- **Proposed Architecture & Implementation Spec:** Use SQLite in WAL mode for a single machine; graduate to Postgres only when multi-host execution is required. SQLite documents that WAL permits readers and a writer concurrently; still enforce one transaction writer and bounded busy timeouts. Core tables:

  - **slates**: slate_id, operator, sport, mode, draft_group_key, first_lock, roster_contract_version.
  - **contests**: contest_id, slate_id, snapshot_id, entry_fee, field_size, max_entries, payout_hash, late_swap_policy.
  - **input_snapshots**: snapshot_id, kind, sha256, byte_size, acquired_at, source, schema_version, immutable_uri.
  - **source_assertions**: assertion_id, snapshot_id, fact_type, entity_key, value_json, observed_at, source_priority.
  - **effective_facts**: fact_id, fact_type, entity_key, value_json, policy_version, source_assertion_ids, status, expires_at.
  - **model_runs**: model_run_id, code_sha, config_hash, training_cutoff, input_snapshot_ids, seed.
  - **scenario_sets**: scenario_set_id, model_run_id, count, matrix_uri, checksum.
  - **field_samples**: field_sample_id, contest_snapshot_id, model_run_id, count, checksum.
  - **candidates**: candidate_id, slate_id, roster_hash, source_scenarios, utility_json.
  - **assignments**: portfolio_id, contest_id, entry_id, candidate_id.
  - **gate_evaluations**: gate_id, run_id, name, status, evidence_ids, policy_version, evaluated_at, expires_at.
  - **artifacts**: artifact_id, run_id, kind, sha256, state, created_at, supersedes.
  - **state_events**: event_id, run_id, prior_state, next_state, cause, created_at, run_version.

  Raw bytes live in a content-addressed object directory keyed by SHA-256. Database rows reference hashes; no mutable “latest.json” is authoritative.

### A-06 — Define machine-readable evidence policy

- **Title / Component:** Evidence resolver
- **Adversarial Critique & Rationale:** Authority and staleness in prose cannot be exhaustively tested.
- **Proposed Architecture & Implementation Spec:** Store policy as versioned YAML validated at startup:

        fact_types:
          hitter_lineup_status:
            authorities: [operator_input, operator_paste, licensed_lineup_feed, public_mlb_feed]
            required_coverage: per_rostered_team
            fresh_before_lock_seconds: 300
            on_conflict: quarantine
            promotion_required: true
          probable_pitcher:
            authorities: [operator_input, official_team_announcement, public_mlb_feed]
            fresh_before_lock_seconds: 600
            on_conflict: quarantine
            promotion_required: true
          weather_game:
            authorities: [roof_status_feed, licensed_weather, nws_api]
            fresh_before_lock_seconds: 600
            promotion_required: only_open_air
          market_total:
            authorities: [licensed_odds_feed]
            fresh_before_lock_seconds: 900
            promotion_required: model_specific

  The resolver retains every assertion and outputs an effective fact plus status. **UNKNOWN** never becomes True. A policy change creates a new evaluation version and invalidates affected downstream artifacts.

### A-07 — Build provider adapters around contracts, not pages

- **Title / Component:** Live acquisition layer
- **Adversarial Critique & Rationale:** Scrapers that return ad hoc dictionaries leak source quirks downstream.
- **Proposed Architecture & Implementation Spec:** Every adapter implements:

        async fetch(request: ProviderRequest, deadline: datetime) -> RawSnapshot
        parse(snapshot: RawSnapshot) -> list[SourceAssertion]
        coverage(assertions, requested_entities) -> CoverageReport
        health() -> ProviderHealth

  Required controls: TLS verification; named user agent; allowlisted hosts; rate budget; ETag/Last-Modified caching; response-size ceiling; JSON/schema validation; redacted secrets; per-attempt timeout; retryable error classification; circuit breaker; raw byte persistence before parsing. Use NWS’s documented cache-friendly [API](https://www.weather.gov/documentation/services-web-api) for open-air weather. Treat public MLB StatsAPI endpoints as useful but not officially documented contracts: wrap them with recorded fixtures, schema-drift alerts, and a licensed fallback.

### A-08 — Build complete, side-specific lineup truth

- **Title / Component:** Active roster and lineup service
- **Adversarial Critique & Rationale:** “Some teams confirmed” and “some rows declared” are not sufficient promotion facts.
- **Proposed Architecture & Implementation Spec:** Model every game side independently:

        LineupSideState =
          UNAVAILABLE
          PROJECTED_COMPLETE
          POSTED_PARTIAL
          CONFIRMED_COMPLETE
          CONFLICTED

  Store nine ordered hitter slots, probable/confirmed pitcher, designated opener/follower, team, game, source assertions, and freshness. Promotion closure requires CONFIRMED_COMPLETE for every team contributing a hitter and a current eligible pitching-role fact for every pitcher. The player pool remains operator salary-file authoritative for eligibility; real-world starters absent from the operator pool are recorded but cannot be invented into it.

### A-09 — Implement an opportunity-first probabilistic model

- **Title / Component:** Player projection system
- **Adversarial Critique & Rationale:** Scoring opportunity is the largest first-order driver in MLB and must not be hidden inside an average.
- **Proposed Architecture & Implementation Spec:** Hitter model:

  1. Predict starting probability and batting-order distribution.
  2. Predict team plate-appearance distribution conditional on home/away, implied scoring environment, and game length.
  3. Allocate plate appearances through lineup turnover and substitution/pinch-hit hazard.
  4. Estimate handedness-conditional BB, HBP, K, 1B, 2B, 3B, HR, and reaching-on-error probabilities with hierarchical shrinkage.
  5. Estimate stolen-base attempt and success conditional on player, pitcher, catcher, base state, and game state where data supports it.

  Pitcher model:

  1. Predict start/opener/follower probability.
  2. Predict pitch-count and batters-faced distribution from recent workload, injury/news, team tendencies, and role.
  3. Simulate K, BB, HBP, HR, and balls in play against the actual opposing order.
  4. Model earned runs, innings, win, and quality-start conditions from shared game state.
  5. Simulate bullpen transition rather than applying one bullpen multiplier.

  Baseball Savant’s [expected-statistics definitions](https://baseballsavant.mlb.com/expected_statistics) support contact-quality inputs, but xwOBA is a component feature, not a complete DFS projection. Use rolling, park-adjusted, handedness-aware rates with uncertainty and league/player shrinkage.

### A-10 — Produce joint scenarios efficiently

- **Title / Component:** Game and slate simulation
- **Adversarial Critique & Rationale:** Full sequential simulation can be computationally wasteful if naively rebuilt after each news event.
- **Proposed Architecture & Implementation Spec:** Generate independent game scenario blocks and combine them into slate scenario IDs using deterministic seed maps. Store dense float32 or integer-scaled arrays by player ID in Arrow/Parquet or memory-mapped NumPy. Use:

  - 5,000 scenarios for early exploratory builds.
  - 20,000 for routine shadow evaluation.
  - 50,000–100,000 for final large-field EV when convergence requires it.
  - Common random numbers across model/config comparisons.
  - Delta recomputation only for affected games.
  - Vectorized DraftKings scoring after event simulation.

  Stop increasing scenarios when the top portfolio’s mean EV ranking and confidence intervals stabilize under a predeclared convergence rule. Scenario count is a statistical budget, not a marketing number.

### A-11 — Calibrate distributions, not just means

- **Title / Component:** Model validation
- **Adversarial Critique & Rationale:** A low mean absolute error model can still have useless tails and correlations.
- **Proposed Architecture & Implementation Spec:** Use rolling-origin walk-forward evaluation with training_cutoff recorded. Grade:

  - Opportunity: start probability, batting-order accuracy, plate appearances, batters faced.
  - Event probabilities: log loss and Brier score for discrete events where appropriate.
  - Marginals: MAE for means, pinball loss for quantiles, CRPS, interval coverage, tail exceedance.
  - Dependence: within-team and opposing-pitcher rank correlations, joint top-decile hit rates, stack-score tail calibration.
  - DFS totals: calibration by salary, order, handedness, role, slate size, and weather bucket.

  Promotion rule for a model version: it must beat the AvgPointsPerGame audit baseline and the legacy factor model prospectively on declared metrics over a minimum number of slates, with no material calibration regression in protected subgroups. Do not hard-code an arbitrary improvement percentage before establishing variance and sample size.

### A-12 — Fit contest-specific ownership and field behavior

- **Title / Component:** Field model
- **Adversarial Critique & Rationale:** Marginal ownership and stack templates cannot reproduce realistic opponent portfolios.
- **Proposed Architecture & Implementation Spec:** Use a two-stage model:

  1. **Behavioral prior:** gradient-boosted or hierarchical models for player inclusion, pitcher pairing, stack team, stack shape, salary left, and batting-order adjacency, conditioned on contest archetype, field size, entry fee, max entries, slate size, salary, projection, value, team total, and news timing.
  2. **Constrained lineup sampler:** CP-SAT or k-best MILP draws legal lineups whose aggregate features match the modeled distributions. Use contest-specific temperature or Plackett-Luce/Gumbel perturbations to create realistic choice variation.

  Validate generated fields against held-out standings on:

  - Per-player ownership MAE and rank correlation.
  - Primary/secondary stack ownership.
  - Pitcher-pair ownership.
  - Stack-shape frequency.
  - Salary-left distribution.
  - Lineup duplication distribution.
  - Pairwise co-roster lift.

  Model each contest archetype separately where sample size permits; otherwise use hierarchical pooling with explicit uncertainty.

### A-13 — Implement exact payout and tie simulation

- **Title / Component:** Contest simulator
- **Adversarial Critique & Rationale:** “Simulated ROI” is only as real as the field and payout inputs.
- **Proposed Architecture & Implementation Spec:** For contest c, scenario s, user lineup l, and generated opponent field F:

        score[s, lineup] = sum(player_scenario_points)
        rank and tie groups over l union F
        gross_payout[s, l] = sum(prizes_covered_by_tie_group) / tie_group_size
        net_profit[s, l] = gross_payout[s, l] - entry_fee
        estimated_ev[l] = mean_s(net_profit[s, l])

  Repeat across multiple field draws to integrate opponent-model uncertainty. Store standard error, downside quantiles, win probability, top-1%, cash probability, and expected duplicated first-place share. If field or payout coverage is incomplete, call the result **scenario_utility**, not EV.

  Vendor benchmarking supports the capability target but not an automatic build-vs-buy conclusion: Stokastic currently describes a field-shaped pool and roughly 40,000 simulated contests; SaberSim describes complete game scripts and contest-specific ownership. Both are vendor claims and should be benchmarked with the same held-out slates used for the internal engine.

### A-14 — Generate candidates as best responses to scenarios

- **Title / Component:** Candidate generator
- **Adversarial Critique & Rationale:** Forced stack enumeration wastes solves on low-value regions and can miss unconventional high-EV combinations.
- **Proposed Architecture & Implementation Spec:** Candidate sources:

  - Scenario winners: optimize fantasy points in sampled joint scenarios.
  - Leverage winners: optimize scenario payoff minus predicted duplication cost.
  - Contest best responses: optimize approximate expected payout against sampled field subsets.
  - Robust candidates: maximize lower confidence bound or CVaR-aware utility.
  - Coverage candidates: explicitly cover underrepresented high-impact game/stack/pitcher states.

  Use deterministic seeds, k-best solution enumeration, no-good cuts, and warm starts. Retain provenance for each candidate. Pareto-prune any lineup that is no better in estimated EV, upper-tail payoff, downside, duplication, and portfolio correlation. Never prefilter solely by mean projection.

### A-15 — Use a sparse, contest-aware portfolio optimizer

- **Title / Component:** Candidate-to-entry and portfolio solve
- **Adversarial Critique & Rationale:** Dense K² overlap rows are an implementation artifact, not a DFS requirement.
- **Proposed Architecture & Implementation Spec:** Build one conflict graph whose edges represent disallowed overlap or duplicate-underlying-player relationships. Optimize binary assignment variables with:

  - One lineup per entry.
  - Entry/contest compatibility.
  - Exact duplicate limits per contest.
  - Player, pitcher, stack, game, and captain exposure limits where policy requires.
  - Portfolio scenario profit or covariance penalty.
  - Contest-specific expected net profit.
  - Optional CVaR or maximum-loss constraint.
  - Candidate reuse only when explicitly permitted.

  For the open-source baseline, benchmark Google OR-Tools CP-SAT; its official documentation distinguishes OPTIMAL, FEASIBLE, INFEASIBLE, MODEL_INVALID, and UNKNOWN, which maps cleanly to the required state model. Keep SciPy/HiGHS as a correctness baseline; SciPy’s milp documentation confirms time-limit status is distinct from infeasibility. For large banks, add violated conflict cuts iteratively instead of materializing every pair. A commercial solver is justified only if measured final-window latency or lazy-cut support materially improves utility.

### A-16 — Unify Classic and Showdown through roster contracts

- **Title / Component:** Mode plugin
- **Adversarial Critique & Rationale:** Separate product paths duplicate bugs and leave Showdown uncertified.
- **Proposed Architecture & Implementation Spec:** Define a RosterContract interface:

        slots()
        allowed_positions(slot)
        salary_cost(player, slot)
        points_multiplier(player, slot)
        underlying_player_identity(player, slot)
        team_representation_constraints()
        lock_key(player)
        export_id(player, slot)

  Classic and Showdown implementations share every downstream component. Showdown must preserve CPT and UTIL Draftable IDs, prevent the same underlying player in two roles, model captain ownership separately, and enforce the portfolio captain exposure policy. The 1/3 captain cap is a policy input, not a universal mathematical truth; it can only change through versioned strategy configuration and prospective evaluation.

### A-17 — Derive Showdown theses from simulation clusters

- **Title / Component:** Explainable game-state portfolios
- **Adversarial Critique & Rationale:** Human-readable theses are useful for audit, but harmful when they generate the states they purport to explain.
- **Proposed Architecture & Implementation Spec:** Cluster game scenarios using features such as final run margin, total runs, starter quality, bullpen innings, leading team, extra innings, and player scoring concentration. Label clusters after fitting. For each selected Showdown lineup, report the scenario clusters that drive its EV and the captain’s payoff/duplication tradeoff. Thesis coverage becomes a diagnostic; it is never a relaxation ladder that overrides hard portfolio constraints.

### A-18 — Make late swap conditional, incremental, and policy-compliant

- **Title / Component:** Late-swap optimizer
- **Adversarial Critique & Rationale:** Re-running a pre-lock objective after some games start ignores observed points, actual ownership, and conditional contest position.
- **Proposed Architecture & Implementation Spec:** At each permitted swap window:

  1. Snapshot operator lock rules and current time.
  2. Freeze locked roster cells and verify their identities.
  3. Ingest observed points and, where legitimately available, actual ownership.
  4. Condition remaining game scenarios on observed state.
  5. Recompute contest payoff distributions and optimize only unlocked cells.
  6. Require per-player evidence closure for every proposed replacement.
  7. Emit a new immutable child artifact with parent hash and exact changed cells.

  Trigger on evidence changes or a bounded schedule, whichever occurs first. Stop at each contest’s last actionable lock. Produce a file and concise action report; do not automate the DraftKings edit.

### A-19 — Separate generation status from promotion status

- **Title / Component:** Fail-open/fail-closed contract
- **Adversarial Critique & Rationale:** “Never block execution” is valuable for throughput but dangerous when it leaks into upload authorization.
- **Proposed Architecture & Implementation Spec:** Every run has two orthogonal outcomes:

  - **Generation outcome:** COMPLETE, PARTIAL, or FAILED.
  - **Promotion outcome:** ELIGIBLE, INELIGIBLE, PENDING, EXPIRED, or SUPERSEDED.

  A partial run may still deliver a diagnostic CSV, projection gaps, and actionable blockers. Its filename begins **DO_NOT_UPLOAD_** and its manifest promotion status is INELIGIBLE. Only the promotion service can create the canonical upload candidate. No generator, optimizer, agent, or CLI flag can directly set ELIGIBLE.

### A-20 — Implement independent, layered QA

- **Title / Component:** Validation pipeline
- **Adversarial Critique & Rationale:** Reusing the same parser and assumptions for generation and verification creates common-mode failure.
- **Proposed Architecture & Implementation Spec:** Required layers:

  1. **Schema QA:** CSV headers, encoding, row counts, duplicate IDs, immutable hashes.
  2. **Mechanical QA:** roster slots, eligibility, salary, team rules, unique underlying players, entry IDs.
  3. **Evidence QA:** exact proposed-player closure, source freshness, conflict status, contest lock.
  4. **Allocation QA:** exposure limits, overlaps, reuse, entry-to-contest mapping.
  5. **Economic QA:** payout hash, field-model eligibility, scenario convergence, EV label eligibility.
  6. **Independent export QA:** separately implemented CSV reader recomputes all roster facts from the operator salary snapshot.
  7. **Round-trip QA:** parse the emitted CSV and verify exact equality to assignments.
  8. **Artifact QA:** manifest hash, parent/supersession, expiration, code/config/input hashes.

  Mechanical and evidence QA must not import the optimizer. Promotion requires every hard layer PASS. Advisory warnings can never mask a hard UNKNOWN.

### A-21 — Make promotion a signed policy decision

- **Title / Component:** Artifact authorization
- **Adversarial Critique & Rationale:** A mutable JSON status and a filename are not strong authorization.
- **Proposed Architecture & Implementation Spec:** The promotion service reads immutable artifacts and gate rows in one transaction, then writes:

        {
          "artifact_id": "...",
          "state": "HUMAN_UPLOAD_REQUIRED",
          "entries_sha256": "...",
          "salary_sha256": "...",
          "contest_snapshot_sha256": "...",
          "roster_contract_version": "...",
          "model_version": "...",
          "scenario_set_id": "...",
          "field_model_version": "...",
          "gate_policy_version": "...",
          "gate_evaluation_ids": ["..."],
          "created_at": "...",
          "expires_at": "...",
          "supersedes": "...",
          "signature": "..."
        }

  Use an HMAC with a locally protected key for tamper evidence, or a signing key if artifacts cross machines. A second preflight verifies signature, exact file hash, current time, supersession, and evidence expiry in under two seconds. It cannot waive failures.

### A-22 — Use durable orchestration with bounded retries

- **Title / Component:** Autonomous control loop
- **Adversarial Critique & Rationale:** Zero-touch operation requires crash recovery, not longer prompts.
- **Proposed Architecture & Implementation Spec:** Begin with a local scheduler and SQLite event log; do not deploy Temporal merely because it is fashionable. Implement leases, fencing tokens, idempotent stage keys, timers, event subscriptions, and deterministic retry policies. If multi-host scale becomes real, Temporal is a reasonable migration target because its workflow executions persist state, replay after failure, and resume from event history.

  Default stage policy:

        fetch:
          attempts: 3
          per_attempt_timeout_s: 4
          total_deadline_s: 10
          backoff_s: [0.25, 1.0]
        normalize:
          attempts: 1
          deadline_s: 2
        simulate:
          attempts: 2
          deadline_s: 15
        optimize:
          attempts: 2
          deadline_s: 20
        qa:
          attempts: 1
          deadline_s: 2

  When a stage exhausts its budget, record a terminal stage result and continue only along an explicitly permitted diagnostic edge. No recursive retries; no unbounded browser wait; no lock acquisition without expiry.

### A-23 — Use event-driven refresh with a bounded fallback schedule

- **Title / Component:** Slate watcher
- **Adversarial Critique & Rationale:** Polling everything frequently wastes requests; polling too slowly misses scratches.
- **Proposed Architecture & Implementation Spec:** Subscribe to provider events where available. Otherwise:

  - Earlier than T-120: every 15 minutes.
  - T-120 to T-30: every 5 minutes.
  - T-30 to T-10: every 2 minutes.
  - T-10 to lock: every 30–60 seconds for unresolved games only, respecting provider limits.
  - Post-lock: only games/entries with remaining late-swap utility.

  Hash normalized facts. A no-change refresh ends immediately. A changed fact invalidates only dependent games, scenario columns, candidates, and entries. Anthropic’s current loop guidance likewise recommends event reaction, explicit stop criteria, and scripts for deterministic work; those principles belong in this scheduler, not in a token-consuming prompt loop.

### A-24 — Redesign Claude context and skills

- **Title / Component:** Cowork-native interface
- **Adversarial Critique & Rationale:** The agent should explain and invoke a reliable system, not re-derive its procedure.
- **Proposed Architecture & Implementation Spec:** Target root **CLAUDE.md** at roughly 40–80 lines:

  - Product purpose and manual DraftKings boundary.
  - “Never call a proxy EV.”
  - Existing-file preservation and secret handling.
  - One command to inspect system status.
  - Links to skills and architecture docs.
  - Repository-specific gotchas only.

  Create narrowly triggered skills:

  - **ingest-dk-slate** — validate authorized salary/entry drops and start a run.
  - **inspect-slate-status** — explain state, evidence gaps, deadlines, and latest artifact.
  - **build-diagnostic-portfolio** — request diagnostic generation without promotion.
  - **promote-upload-candidate** — invoke deterministic promotion and report exact blockers.
  - **run-late-swap** — request conditional child artifact.
  - **archive-and-grade** — ingest results and grade pre-lock predictions.
  - **model-audit** — offline calibration and drift report.

  Put CLI schemas and behavior in tool descriptions. Put long statistical references in separate files loaded only by model-audit or development work. Use deterministic hooks only for fast invariants such as preventing direct writes to immutable artifacts; do not use hooks to do long network or solver work.

### A-25 — Remove the LLM from the lock-window critical path

- **Title / Component:** Cost and latency
- **Adversarial Critique & Rationale:** Tokens are the wrong unit of compute for CSV parsing, source polling, scoring, MILP construction, and byte verification.
- **Proposed Architecture & Implementation Spec:** The engine runs as a pre-warmed local service. LLM use is limited to:

  - One optional morning research synthesis.
  - Exception explanation when the deterministic blocker message is insufficient.
  - Offline model-development proposals.
  - Post-slate attribution and report drafting.

  Use the smallest capable model for summaries and a frontier model only for architecture or anomalous cases. Cache all deterministic results by input/config/code hashes. Zero LLM calls are required to produce or refresh the final artifact.

### A-26 — Add observability tied to lock risk and economics

- **Title / Component:** Metrics, logs, and alerts
- **Adversarial Critique & Rationale:** Generic logs do not reveal whether the system is losing time, evidence, or expected value.
- **Proposed Architecture & Implementation Spec:** Emit structured events and metrics:

  - Seconds to first diagnostic and promotion-eligible artifact.
  - Provider latency, success, freshness, coverage, conflicts, and circuit state.
  - Scenario generation throughput and convergence.
  - Candidate count, provenance coverage, dominance-prune rate.
  - Solver status, incumbent gap, time, variables, constraints, conflict edges.
  - QA latency and failures by gate.
  - Artifact version churn and evidence-to-promotion lag.
  - Projected EV and uncertainty at selection time.
  - Post-lock calibration and realized profit attribution.
  - LLM calls, tokens, and cost per slate.

  Alerts are deadline-aware: a missing lineup at T-60 is informational; the same fact at T-5 is critical. Do not alert on every retry. Alert on state change, deadline risk, conflict, quarantine, or promotion expiry.

### A-27 — Secure secrets, artifacts, and network scope

- **Title / Component:** Security and compliance
- **Adversarial Critique & Rationale:** Automation expands the blast radius of leaked credentials and accidental external actions.
- **Proposed Architecture & Implementation Spec:** Keep DraftKings credentials and cookies entirely out of the system. Store provider secrets in the OS credential manager or injected process environment; redact raw URLs and headers; use a network host allowlist; run browser adapters in a restricted profile; sign promoted manifests; mark raw and derived artifacts with retention policies; hash every input. CI uses fake credentials and recorded fixtures. Add a policy test that any attempt to access a DraftKings authenticated endpoint or automate an account action is denied and logged.

### A-28 — Adopt a hybrid build-versus-buy strategy

- **Title / Component:** Vendor and internal edge strategy
- **Adversarial Critique & Rationale:** Building every projection, news, ownership, and contest-simulation input from scratch is not automatically cheaper. It can take months of engineering before it beats a licensed feed, while using one vendor blindly creates correlated model risk and no proprietary edge.
- **Proposed Architecture & Implementation Spec:** Use a staged hybrid:

  1. License or manually import, under permitted terms, at least one high-quality projection and ownership source with timestamped exports or an API.
  2. Build the evidence, field, payout, portfolio, QA, and audit layers internally.
  3. Ensemble vendor and internal forecasts using walk-forward weights.
  4. Add the internal event model in shadow; promote only after it adds prospective value.
  5. Maintain a replacement feed so one vendor outage cannot force unsafe promotion.

  Benchmark capability, latency, data rights, API/export support, update cadence, historical availability, ownership granularity, Showdown support, and total cost. Current product pages suggest useful reference features: [SaberSim](https://www.sabersim.com/mlb/projections) claims game-script simulations, ranges, contest-specific ownership, and automatic updates; [Stokastic](https://www.stokastic.com/articles/dfs-strategy/mlb-dfs-contest-simulator) describes field-mirroring contest simulation and payout-aware ROI; [RotoGrinders LineupHQ](https://rotogrinders.com/lineuphq) claims confirmed MLB lineups, ownership, stacks, weather, umpire data, and pitch counts. Treat all as vendor claims until replayed on held-out data. Do not assume an API or redistribution right from a marketing page.

### A-29 — Establish a complete test and evaluation matrix

- **Title / Component:** Engineering acceptance tests
- **Adversarial Critique & Rationale:** Happy-path unit tests cannot establish zero-touch safety.
- **Proposed Architecture & Implementation Spec:** Required suites:

  **Contracts and property tests**

  - Random legal/illegal Classic and Showdown rosters.
  - Salary boundary, multi-position eligibility, CPT identity, duplicate underlying player.
  - CSV encoding, commas/quotes, reordered columns, duplicate Entry IDs.

  **Evidence tests**

  - Missing, stale, unreadable, partial, conflicting, wrong-slate, and future-dated sources.
  - Exactly 50% lineup coverage.
  - One confirmed team versus all required teams.
  - Roof/open-air policy and postponed game.

  **Concurrency and recovery tests**

  - 50 simultaneous artifact/promotion attempts with no lost state.
  - Crash after every state transition, then deterministic resume.
  - Database busy timeout and expired lease fencing.
  - Raw snapshot saved but parser crash.

  **Solver tests**

  - OPTIMAL, FEASIBLE, UNKNOWN/time limit, and proven INFEASIBLE remain distinct.
  - Full-bank widening recovers a solution discarded by the first prefilter.
  - No objective sign reversals.
  - Sparse conflict cuts equal exhaustive constraints on small fixtures.

  **Model tests**

  - No future information in features.
  - Scenario reproducibility from seed/config/input hashes.
  - Marginal and joint calibration on frozen walk-forward folds.
  - Field generator matches held-out ownership, shapes, salary, and duplication.
  - Payout/tie split against hand-calculated fixtures.

  **Promotion tests**

  - Any hard gate FAIL, UNKNOWN, or STALE denies promotion.
  - Diagnostic generation still completes where safe.
  - Superseded/expired/hash-mismatched artifact cannot pass preflight.
  - No review-grade or proxy model receives EV/upload-ready labels.

  Add mutation testing around promotion and roster rules. A build passes because named safety properties pass, not because an integer test count matches documentation.

### A-30 — Set measurable latency and cost budgets

- **Title / Component:** Performance service-level objectives
- **Adversarial Critique & Rationale:** “Fast” without stage budgets encourages hidden stalls and compensating prompt behavior.
- **Proposed Architecture & Implementation Spec:** On the target local machine after warm start:

  - Input identity and schema: p95 under 0.5 seconds.
  - Cached evidence normalization: p95 under 0.5 seconds.
  - Fresh parallel evidence fetch: p95 under 8 seconds, hard deadline 10 seconds.
  - Affected-game scenario refresh: p95 under 8 seconds.
  - Candidate generation: p95 under 15 seconds for 20,000 scenarios and the reserved portfolio scale.
  - Portfolio allocation: p95 under 3 seconds.
  - Independent QA and promotion decision: p95 under 2 seconds.
  - No-change event reaction: under 1 second.
  - Warm final refresh target: under 30 seconds end to end.
  - Hard final-window deadline: 45 seconds; on expiry retain prior valid artifact if unexpired, otherwise emit DO_NOT_UPLOAD.
  - LLM calls in final-window path: exactly zero.

  Treat these as initial budgets to benchmark, not promises. Record p50/p95/p99 and regress in CI using representative slate/entry sizes.

### A-31 — Define a risk-aware portfolio objective

- **Title / Component:** Utility and bankroll constraints
- **Adversarial Critique & Rationale:** Maximizing noisy estimated EV can overfit Monte Carlo error and concentrate correlated downside.
- **Proposed Architecture & Implementation Spec:** Default utility:

        portfolio_utility =
          mean(simulated_net_profit)
          - lambda_se * monte_carlo_standard_error
          - lambda_tail * max(0, target_cvar_loss - cvar_alpha)
          - lambda_corr * concentration_penalty

  Estimate utility across scenario and field-draw blocks. Tune lambdas prospectively by contest class and bankroll policy, never to explain yesterday’s results. Apply hard maximum daily loss, per-contest exposure, and total entry-fee caps before lineup optimization. Cash, GPP, and satellite objectives use exact payout distributions rather than tier labels.

### A-32 — Build explainability from provenance, not LLM narratives

- **Title / Component:** Decision audit
- **Adversarial Critique & Rationale:** A fluent explanation can conceal missing evidence or a weak objective.
- **Proposed Architecture & Implementation Spec:** Every selected lineup exposes:

  - Model, scenario, field, payout, and policy versions.
  - Exact input hashes and effective evidence facts.
  - Mean projection and quantiles.
  - Estimated EV, standard error, downside metrics, and duplication estimate where eligible.
  - Scenario clusters driving upside.
  - Closest rejected candidates and the utility delta.
  - Portfolio constraints that bound or selected it.
  - Any diagnostic fallback or relaxation.

  The agent may translate this record into plain language but cannot add facts. If EV eligibility is false, the explanation must say why.

### A-33 — Execute a safety-first migration

- **Title / Component:** Implementation phases
- **Adversarial Critique & Rationale:** Replacing the system in one slate risks losing the current legality and artifact safeguards. Incrementally adding more heuristics to the current engine preserves the wrong objective.
- **Proposed Architecture & Implementation Spec:** Use these phases:

  **Phase 0 — Immediate containment, 1–3 days**

  - Remove reuse_penalty from the current joint allocator.
  - Make missing/stale/unreadable lineup evidence fail promotion.
  - Remove assume_gates from certification.
  - Fix late swap’s per-team lineup closure.
  - Put a process lock around legacy manifest writes or disable concurrent promotion.
  - Keep generation diagnostic and label failed/unknown runs DO_NOT_UPLOAD.

  **Exit:** Known certification defects cannot produce upload_ready.

  **Phase 1 — Greenfield control plane, 1–2 weeks**

  - Create pyproject, typed contracts, SQLite schema, immutable store, state machine, artifact registry, and independent mechanical QA.
  - Implement DK CSV intake and exact contest snapshot schema.
  - Wrap the legacy optimizer behind the new diagnostic interface.

  **Exit:** A crash-safe, fully auditable diagnostic run completes without an LLM.

  **Phase 2 — Evidence service, 1–2 weeks**

  - Implement provider adapters, source assertions, evidence policy, per-side lineup state, deadlines, and event-driven refresh.
  - Add policy-compliant manual input and output boundary.

  **Exit:** Partial/stale/conflicting facts are reproduced in tests and cannot promote.

  **Phase 3 — Distribution engine, 3–6 weeks**

  - Implement opportunity and event-rate models, joint scenarios, scoring, calibration harness, and scenario storage.
  - Run alongside vendor and legacy baselines.

  **Exit:** Prospective distribution metrics beat the declared baselines with stable subgroup calibration.

  **Phase 4 — Field and economics, 3–6 weeks**

  - Ingest and clean standings/payout history.
  - Fit ownership/field generator.
  - Implement tie-aware payout simulation and candidate EV evaluation.

  **Exit:** Held-out field distributions pass calibration criteria; exact payout fixtures pass; EV labels become model-eligible.

  **Phase 5 — Portfolio, Showdown, and late swap, 2–4 weeks**

  - Implement scenario-conditioned candidates, sparse portfolio solve, unified roster contracts, role-aware Showdown field model, and conditional late swap.

  **Exit:** Classic and Showdown share promotion and QA; late swap produces only evidence-closed child artifacts.

  **Phase 6 — Shadow-to-production promotion, minimum 20–40 slates**

  - Freeze predictions pre-lock.
  - Compare legacy, vendor, and greenfield engines without cherry-picking.
  - Review calibration, utility stability, latency, failure recovery, and realized outcomes.
  - Promote only after a documented model risk review.

  **Exit:** Greenfield becomes default; legacy remains replay-only for a defined deprecation window.

### A-34 — Give the implementation agent an ordered ticket backlog

- **Title / Component:** Executable work breakdown
- **Adversarial Critique & Rationale:** Architecture documents fail when they do not define the first mergeable slices.
- **Proposed Architecture & Implementation Spec:** Implement in this dependency order:

  1. GF-001: pyproject, package skeleton, lint/type/test configuration.
  2. GF-002: RosterContract for Classic and Showdown with property tests.
  3. GF-003: immutable RawSnapshot store and SHA-256 utilities.
  4. GF-004: SQLite schema, migrations, transaction wrapper, WAL configuration.
  5. GF-005: run state machine with optimistic versioning and event log.
  6. GF-006: DK salary/entry parsers and SlateIdentity/ContestSnapshot contracts.
  7. GF-007: independent mechanical/export validator.
  8. GF-008: evidence assertion and policy evaluator with five-state gates.
  9. GF-009: per-side lineup service and coverage closure.
  10. GF-010: artifact registry, supersession, signing, and preflight.
  11. GF-011: provider adapter interface, async worker, deadlines, retry budget, circuit breaker.
  12. GF-012: diagnostic wrapper around legacy projection/optimizer, never promotion-eligible.
  13. GF-013: hitter/pitcher opportunity models and frozen training pipeline.
  14. GF-014: event-rate and game simulator with reproducible scenario store.
  15. GF-015: calibration dashboards and prospective prediction ledger.
  16. GF-016: contest payout parser and tie-split engine.
  17. GF-017: ownership model and constrained field generator.
  18. GF-018: EV evaluator with uncertainty.
  19. GF-019: scenario-conditioned candidate generator.
  20. GF-020: sparse conflict portfolio solver.
  21. GF-021: unified Showdown and role-aware duplication.
  22. GF-022: conditional late swap.
  23. GF-023: event-driven scheduler and lock-window service.
  24. GF-024: Cowork skills and compact CLAUDE.md.
  25. GF-025: shadow evaluation, model-risk review, and cutover.

  Every ticket must include typed inputs/outputs, migrations, deterministic tests, metrics, rollback behavior, and one end-to-end fixture. No ticket may introduce an **assume**, **force promotion**, or **warning means pass** escape hatch.

### A-35 — Definition of done

- **Title / Component:** Greenfield acceptance contract
- **Adversarial Critique & Rationale:** “Works autonomously” is otherwise subjective and easy to declare prematurely.
- **Proposed Architecture & Implementation Spec:** The redesign is complete only when all are true:

  - One authorized input drop starts a run without prompt edits or mid-run intervention.
  - Existing inputs are hashed and immutable; every derivative traces to them.
  - Classic and Showdown use the same state, evidence, QA, manifest, and promotion services.
  - Missing, stale, unreadable, partial, or conflicting hard evidence cannot produce promotion eligibility.
  - No Boolean assumption can satisfy a hard gate.
  - Every wait and retry has a deadline and terminal outcome.
  - Crash injection at every state transition resumes without duplicate or lost artifacts.
  - Concurrent writers cannot lose state or produce two current promotions for one contest/version.
  - Candidate generation and allocation distinguish optimal, feasible, incomplete search, timeout, and proven infeasible.
  - Production numerical paths never use DraftKings AvgPointsPerGame.
  - EV labels require exact contest economics, calibrated scenarios, a calibrated field model, and pre-lock timestamped predictions.
  - Independent QA round-trips every delivered entry and recomputes eligibility/salary from the exact operator snapshot.
  - A promoted artifact is signed, hash-bound, contest-bound, unexpired, and not superseded.
  - Final-window generation uses zero LLM calls and meets the measured service-level budgets.
  - The system never logs in to DraftKings, moves money, enters contests, uploads, or edits lineups automatically without written authorization.
  - A human can identify the one current file, exact hash, contest, expiry, and blockers in under ten seconds.
  - Shadow evaluation demonstrates prospective improvement over declared baselines before production cutover.

**Bottom line:** Preserve the current system’s insistence on operator-file authority, immutable evidence, legal rosters, independent validation, and visible DO_NOT_UPLOAD outcomes. Burn down the rest of the live architecture. The decisive edge will not come from a longer Cowork prompt or more stack rules. It will come from calibrated opportunity and event distributions, a realistic opponent-field generator, exact payout/tie simulation, contest-aware portfolio utility, a durable evidence state machine, and a hard promotion service that cannot be talked into believing unknown facts.

**Primary research anchors used for this specification:**

- [Anthropic: The new rules of context engineering for Claude 5 generation models](https://claude.com/blog/the-new-rules-of-context-engineering-for-claude-5-generation-models)
- [Anthropic: Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
- [Anthropic: Building verification loops in Claude Code with Skills](https://claude.com/blog/building-verification-loops-in-claude-code-with-skills)
- [Anthropic: Getting started with loops](https://claude.com/blog/getting-started-with-loops)
- [Anthropic: Effective harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)
- [DraftKings: Fantasy Sports Fair Play Commitment](https://support.draftkings.com/dk/en-us/fantasy-sports-fair-play-commitment?id=kb_article_view&sysparm_article=KB0010662)
- [DraftKings: Late Swap overview](https://support.draftkings.com/dk/en-us/late-swap-overview?id=kb_article_view&sysparm_article=KB0010786)
- [DraftKings: MLB rules](https://www.draftkings.com/help/rules/mlb)
- [Baseball Savant: Expected statistics](https://baseballsavant.mlb.com/expected_statistics)
- [National Weather Service API](https://www.weather.gov/documentation/services-web-api)
- [SciPy milp documentation](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.milp.html)
- [Google OR-Tools CP-SAT documentation](https://developers.google.com/optimization/cp/cp_solver)
- [SQLite write-ahead logging](https://www.sqlite.org/wal.html)
- [Temporal workflow execution](https://docs.temporal.io/workflow-execution)
- [SaberSim MLB projections and simulation claims](https://www.sabersim.com/mlb/projections)
- [Stokastic MLB contest simulator claims](https://www.stokastic.com/articles/dfs-strategy/mlb-dfs-contest-simulator)
- [RotoGrinders LineupHQ feature claims](https://rotogrinders.com/lineuphq)
