# DraftKings MLB DFS Greenfield System and Code Review Specification

**Review date:** 2026-08-27  
**Reviewed branch / commit:** `main` / `245de5148a906c6fae2283f06d5b47b400a13d38`  
**Scope:** DraftKings MLB Classic and Showdown generation, field modeling, contest allocation, late swap, QA, delivery, prompts, skills, tests, reference data, and operational scripts  
**Review mode:** read-only static analysis; this file is the only artifact created  
**Decision status:** **DO_NOT_UPLOAD as a maximum-EV or EV-certified system**

This is a greenfield specification, not an endorsement of the current design. The current repository contains unusually substantial legality, provenance, deterministic-seed, and independent-export work. Those are valuable controls. They do not establish calibrated player distributions, a contest-conditioned field distribution, exact contest settlement, or positive expected value. The present optimizer selects plausible lineups with heuristic projection and contest-fit proxies. It does not solve the economic problem stated in the objective.

The review was performed against the exact commit above. All tracked Python files parsed successfully as Python source. A dynamic audit was attempted with `python -B tools/audit.py --run-tests --terse`; the host interpreter is Python 3.13 without NumPy, Pandas, or SciPy, while `requirements.lock` is a Python 3.10/Linux wheel lock. The audit therefore failed closed: SciPy MILP was unavailable and five suites failed after 91 tests ran. No package was installed and no existing file was changed. Runtime-dependent conclusions below are explicitly distinguished from source-proven defects.

---

## Section 1: Greenfield System Audit & Legacy Deconstruction

### 1.1 Executive verdict

The current system answers this question reasonably well:

> Given a DraftKings player pool, a set of heuristic point estimates and modifiers, and portfolio rules, can the repository construct legal-looking lineups, retain evidence, and guard an export?

It does **not** yet answer the economically relevant question:

> Conditional on all information known at lock, which assignment of lineups to exact contests maximizes expected bankroll utility after opponent behavior, duplication, payout curvature, ties, late news, model uncertainty, and fees?

The gap is architectural, not a tuning problem. More stack bonuses, more thesis labels, or a larger candidate bank cannot convert a point-estimate proxy into expected contest profit. The greenfield engine needs four coupled probability objects:

1. A calibrated joint distribution of player fantasy outcomes, including playing-time uncertainty and within-game dependence.
2. A contest-conditioned distribution of opponent lineups, not only marginal ownership.
3. An exact settlement function over the submitted portfolio and simulated field, including ties and duplicate entries.
4. A capital-aware portfolio objective over exact entry-to-contest assignments.

Until those objects exist, are prospectively calibrated, and are reproducible from frozen inputs, words such as `EV`, `optimal`, `maximum-EV`, and `upload-ready` must be withheld from economic claims. `OPTIMAL` may describe a solver status for the *implemented proxy objective* only.

### 1.2 What should survive, what should be replaced

| Current capability | First-principles judgment | Greenfield action |
|---|---|---|
| Immutable input hashes, manifests, deterministic seeds | Necessary for reproducibility and incident response | Keep the intent; replace scattered implementations with one artifact store and schema |
| DraftKings ID joins and exact-byte export checks | Essential | Keep and centralize in an independent referee package |
| Classic legality MILP | Necessary, but legality is only a candidate-generation constraint | Preserve as a verified kernel behind one roster contract |
| Showdown legality MILP | Necessary, but current result handling and projection inputs are incomplete | Rewrite behind the same solver/result interface |
| Factor chain `Base * F1 * ... * F5` | Explainable but not a calibrated outcome model; missing features can become numeric neutrality | Replace as the production scoring model; retain only as a benchmark baseline |
| Stack/thesis/posture labels | Useful as diagnostics or proposal features | Stop treating them as economic objectives; estimate their value from simulations |
| Marginal ownership priors | Necessary but insufficient | Replace with contest-conditioned joint lineup sampling and calibration |
| Candidate-bank cache | Useful when keyed by complete immutable inputs | Rewrite around content-addressed scenario, contest, model, and solver identities |
| Global exposure caps | Safety heuristic, not a portfolio optimizer | Replace with per-contest and capital-aware risk constraints |
| Position-based entry assignment in Showdown | Artificial and economically blind | Delete; assign lineups jointly to exact entries and contests |
| LLM-authored operational workflow | Helpful for explanation and unstructured recovery | Thin it drastically; deterministic state machine owns the run |
| Browser-driven scraping and upload | Fragile, hard to certify, and constrained by platform terms | Do not build as the production control plane; use approved/licensed feeds and a human-controlled final boundary unless written authorization exists |
| Large always-loaded instruction/history documents | Context-expensive and drift-prone | Move history to progressive references; generate current facts from code |
| Historic standings/raw artifacts | Valuable immutable training and replay evidence | Preserve read-only; index by content hash and schema version |
| Scratch scripts, archives, handoff fragments | Useful evidence but unsafe execution surface | Quarantine under a documented `legacy/experiments/` boundary; never put on production import paths |

### 1.3 Current data and decision flow

The current repository roughly performs:

```text
DK CSV + live/reference sources
        |
        v
slate intake / identity / status reports
        |
        v
Base projection + multiplicative factors
        |
        v
Classic bank MILPs OR Showdown thesis ladder
        |
        v
contest posture + heuristic candidate scores
        |
        v
entry allocation + exposure caps
        |
        v
CSV render -> manifest/promotion -> preflight/referee
```

The right-hand controls are more mature than the left-hand predictive model. This creates a dangerous asymmetry: an export can accumulate considerable structural evidence while the central economic assumptions remain uncalibrated. A deterministic, legal, hash-bound CSV can still have negative expected value.

### 1.4 First-principles deconstruction by layer

#### Intake and identity

DraftKings draftable IDs and exact contest-entry rows are the correct primary keys for delivery. MLBAM/person IDs are the correct bridge for baseball data. Names must be display attributes, never join keys. The repository mostly recognizes this, but still contains normalized-name recovery paths and team-alias duplication. The greenfield rule is:

- `draftable_id` identifies a selectable DraftKings role.
- `person_id` identifies a human baseball player.
- `role` identifies Classic roster eligibility or Showdown `CPT`/`UTIL` representation.
- Every mapping carries source artifact, effective time, confidence/state, and collision evidence.
- No collision is resolved by “highest PA,” first row, or name alone.

#### Projection and outcome modeling

`projection_builder.py:82-135` composes a deterministic point estimate from `Base` and five factors. `execution_pipeline.py:3076-3084` can seed `Base` from DraftKings `AvgPointsPerGame`. That is an expedient baseline, not a forecast distribution. APPG is backward-looking, role- and slate-insensitive, and does not model starts, batting order, plate appearances, bullpen paths, opposing pitcher removal, weather distributions, or variance.

The production replacement must predict event or plate-appearance distributions, not multiply a single mean. A useful hierarchy is:

1. Probability of being active and starting.
2. Conditional batting slot / pitcher workload distributions.
3. Per-PA or per-batter-faced event distributions with opponent, park, weather, handedness, and bullpen context.
4. Shared latent game/team factors to preserve correlations.
5. Direct conversion of simulated baseball events to DraftKings scoring.

The old factor model remains valuable only as a challenger baseline. It earns production status only if prospective out-of-sample scoring and calibration beat simpler baselines.

#### Candidate optimization

`optimizer_v3.py:3473-3568` optimizes a weighted proxy combining ceiling/floor, stack structure, and duplication-related terms. Right-tail and low-owned diagnostics are calculated but not included in the shown contest-fit objective. Even a perfectly solved MILP therefore finds the exact optimum of an incomplete proxy.

Candidate generation should be separated from portfolio economics. Its job is to enumerate a diverse set of *legal and potentially efficient* rosters using scenario scores, reduced-cost search, randomized/perturbed objectives, or column generation. It should not pretend a universal weighted score is expected value.

#### Field model

The field-mining layer extracts useful construction evidence, but its registry pools observations across contest contexts and its duplicate keys ignore Showdown captain role. Marginal ownership alone cannot price duplication or payout tails. A field model must generate complete legal opponent lineups conditional on:

- format, slate, contest field size, buy-in/stakes, max entries, payout shape, and time to lock;
- ownership marginals and pairwise/higher-order construction dependencies;
- salary usage, stack shapes, pitcher-hitter rules, captain choice, and public projection concentration;
- uncertainty in all estimated parameters.

Calibration targets are not only player ownership MAE. They include lineup salary distribution, stack frequencies, pair/co-occurrence rates, captain shares, duplicate-count distribution, and rank/payout behavior.

#### Settlement and portfolio construction

The repository lacks scenario returns produced from a complete simulated field and exact payout curve. Without them, global exposure caps and posture assignment are heuristics.

The target allocator must build complete assignment packages for all user entries within each contest, settle each package jointly with the sampled opponent field, and then choose packages across contests. This is necessary because the user's own entries compete for ranks and can join the same tie; per-entry returns are not generally additive. The allocator must respect per-contest constraints, exact entry counts, lineup reuse rules, and capital concentration. Its objective should be declared explicitly: expected profit, expected log bankroll, mean-CVaR, or another approved utility. Changing that choice changes the optimal portfolio; it is a product decision, not a hidden constant.

#### Late swap

Late swap is a conditional re-optimization problem. Locked players, actual scores, remaining opponent rosters, updated news, and contest state change the scenario distribution. It is not a string-diff operation followed by a new heuristic build. The current delta validator is valuable, but the final exact bytes must always pass the independent referee before delivery.

#### Delivery and platform boundary

Zero-touch computation is achievable from a user-supplied or licensed slate artifact through a signed, verified candidate delivery. Fully automated site interaction is not an acceptable greenfield assumption. DraftKings' current US Terms of Use prohibit automated scripts and third-party tools from interacting with the site in ways that include creating or editing lineups, and impose additional conditions on content providers. The architecture must therefore end at a **human-controlled decision and upload boundary** unless DraftKings supplies written authorization or an approved API. This is a product constraint, not a software defect, and this report is not legal advice. See the [DraftKings US Terms of Use](https://sportsbook.draftkings.com/legal/us-terms-of-use), [Fair Play Commitment](https://help.draftkings.com/hc/en-us/articles/4405223983635-Fantasy-Sports-Fair-Play-Commitment-US), and [official CSV upload instructions](https://help.draftkings.com/hc/en-us/articles/4405223998867-How-do-I-upload-or-edit-multiple-lineups-at-once-US).

### 1.5 LLM versus deterministic execution boundary

| Task | Owner | Reason |
|---|---|---|
| CSV parsing, hashes, ID reconciliation, schema validation | Deterministic code | Exact, cheap, testable, byte-sensitive |
| Salary, roster, stack, exposure, and lock constraints | MILP / deterministic validator | Formal feasibility and reproducibility |
| Projection inference and simulation | Local statistical/numerical code | Vectorized, high-volume, measurable |
| Field generation and payout settlement | Local code | Millions of repeated calculations; exact rules |
| Entry-to-lineup allocation | MILP / stochastic optimizer | Formal constraints and declared utility |
| Retry/deadline/circuit-breaker behavior | Deterministic orchestrator | Must not improvise during lock pressure |
| Web page interpretation when no structured/licensed source exists | LLM-assisted quarantine path | Unstructured semantics; output remains untrusted evidence |
| Provider schema-change triage | LLM-assisted diagnostic | Useful for explaining diffs, never for silently approving them |
| Operator explanation and incident summary | LLM | Natural-language compression is useful |
| Deciding whether evidence is fresh enough, a lineup is legal, or bytes may ship | Deterministic policy | Must be auditable and fail closed |
| Site login, clicks, lineup creation/edit, contest entry | Human or explicitly authorized integration | Platform/legal boundary and irreversible external action |

An LLM should never perform arithmetic row by row, format final CSV bytes, infer missing IDs, relax a constraint, or decide that missing evidence is “probably neutral.” It may propose a recovery, but a typed deterministic gate accepts or rejects it.

### 1.6 Prompt and context audit

The always-visible instruction surface is too large and contains mutable operational facts. `CLAUDE.md` is approximately 35 KB, `MLB_Classic.md` approximately 49 KB, and `skills/generate-lineups/SKILL.md` approximately 52 KB. Test-count claims already disagree: `MANIFEST.md:10,39,59,73` says 12 modules/119 tests; `CLAUDE.md:297` says 26 modules/1,313 tests; `skills/generate-lineups/SKILL.md:873` says 26 modules/1,276 tests. An agent cannot know which claim is authoritative without re-running the repository.

The replacement context design should contain:

- a root instruction file under 200 high-signal lines: safety boundary, canonical entrypoints, typed states, and links;
- a machine-generated `system_facts.json` for module count, test inventory, schema versions, and supported modes;
- progressive references for Classic, Showdown, late swap, settlement, and incident history;
- one canonical command per lifecycle action;
- no historic changelog, old test counts, or duplicated policy prose in the hot context;
- short tool descriptions with non-overlapping responsibilities.

This matches Anthropic's current guidance to treat context as finite, keep high-signal information, use progressive disclosure, minimize overlapping tools, start with the simplest viable agent pattern, and give loops explicit stopping conditions: [effective context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) and [building effective agents](https://www.anthropic.com/engineering/building-effective-agents).

### 1.7 Commercial-engine benchmark: useful mechanics, not proof

Public vendor material supports a capability taxonomy, not a claim that any proprietary implementation is correct or profitable:

- SaberSim describes game simulation, realistic field construction, exact payout structures, and lineup ROI distributions in its contest-simulation workflow; its projection documentation also distinguishes probabilistic simulation from a single point projection. See [How Contest Sims Work](https://support.sabersim.com/en/articles/12079199-how-contest-sims-work) and [How Projections Work](https://support.sabersim.com/en/articles/12078831-how-projections-work).
- Stokastic markets pre-sim/post-sim tooling, ROI-oriented outcomes, ownership, and late swap. See [Stokastic](https://www.stokastic.com/).
- FantasyLabs exposes contest-specific ownership views, reinforcing that ownership is conditional on contest context. See its [ownership dashboard description](https://www.fantasylabs.com/articles/introducing-new-fantasylabs-ownership-dashboard/).

The extractable mechanics are joint simulation, field sampling, exact payout settlement, contest conditioning, and portfolio-level risk. Vendor marketing must not be treated as independent evidence of predictive edge, profitability, or implementation quality.

### 1.8 File-by-file disposition

The table below covers every active production Python module and executable script. Packaging-only `__init__.py` files contain no business logic and should remain empty. Historic raw data and frozen fixtures are evidence, not executable production code; their disposition follows the table.

#### `mlb_engine`

| File | Necessity / defect concentration | Greenfield disposition |
|---|---|---|
| `allocate/contest_allocator.py` | Necessary assignment concept; global denominators, permissive fractions, and monolithic joint model are wrong abstractions | Rewrite as exact-entry, per-contest, capital-aware portfolio optimizer |
| `allocate/posture_allocator.py` | Heuristic posture quota allocator | Retain only as a baseline/challenger; remove from production decision path |
| `contest_shapes.py` | Useful contest vocabulary, but duplicates Showdown posture/archetype concepts | Replace with one `ContestSpec`/`ContestObjective` schema |
| `determinism.py` | Necessary deterministic seed/config utilities | Keep behind artifact/run identity; extend to numerical runtime identity |
| `entries/dk_entries_manager.py` | Necessary DK parsing/rendering; shares/clamps policy and contract logic | Split parser, immutable template, renderer, and referee contracts |
| `entries/upload_manifest.py` | Necessary delivery lineage; concurrent read-modify-write can lose records | Replace mutable index with immutable records plus transactional index |
| `field/contest_library.py` | Useful contest metadata; direct JSON writes and mutable registry are fragile | Migrate to versioned SQLite/Parquet observations and generated views |
| `field/field_miner.py` | Valuable archive extraction; role-blind duplication, winner selection, pooled contexts, lost updates | Rewrite ingestion as immutable normalized observations; keep raw archives |
| `field/ownership_prior.py` | Useful baseline prior; not a joint field model | Retain as baseline feature; replace production model with contest-conditioned sampler |
| `intake/live_data_adapters.py` | Necessary adapters; very large, mixed providers, wrong-leg evidence and odds aggregation defects | Split one adapter per provider plus independent reconciliation policy |
| `intake/paste_lineups.py` | Useful manual quarantine parser | Keep outside certified primary path; every output remains untrusted until ID-joined |
| `intake/platoon_order_adapter.py` | Useful normalized lineup adapter | Keep intent; emit typed evidence and immutable provider artifact |
| `intake/slate_intake_manager.py` | Necessary slate lifecycle; clock and wind-band gaps | Split pure parsing, reconciliation, weather, and clock policies |
| `optimize/bank_cache.py` | Caching is useful; current job grid does avoidable MILPs | Rewrite as content-addressed column store with feasibility pruning |
| `optimize/optimizer_v3.py` | Legal Classic kernel is valuable; 4K-line proxy optimizer mixes too many responsibilities | Extract verified Classic legality kernel; replace scoring/portfolio logic |
| `optimize/roster_contracts.py` | Correct direction but only Showdown is centralized | Make it the sole source for both formats and generated referee fixtures |
| `optimize/showdown.py` | Necessary legality kernel; point-estimate inputs and status conflation | Rewrite with typed solve result and scenario-score interface |
| `optimize/showdown_theses.py` | Sequential thesis ladder causes reservation and relaxation errors | Delete from production; use joint portfolio optimization; retain as benchmark |
| `optimize/tail_candidate_scanner.py` | Potential diagnostic | Keep only if it contributes measurable candidate recall under replay tests |
| `pipeline/build_state_manager.py` | Necessary lifecycle idea; promotion does not require final artifact role | Replace with transactional state machine and required artifact schema |
| `pipeline/execution_pipeline.py` | 4K-line orchestration monolith; evidence, modeling, policy, and I/O are entangled | Decompose; state machine coordinates pure stage services |
| `projections/projection_builder.py` | Explainable baseline; not calibrated and contains collision handling defect | Retain as benchmark only; build probabilistic model pipeline |
| `projections/xwoba_base_correction.py` | Potential feature engineering | Keep only after leakage-safe prospective validation; output feature, not hidden correction |
| `repo_env.py` | Useful repository-root isolation | Keep small and side-effect free |
| `swap/late_swap_manager.py` | Useful locked-slot/delta rules; validation flag is hardcoded | Split immutable state reconstruction, conditional optimizer, and referee |
| `team_codes.py` | Necessary alias mapping | Generate one versioned mapping consumed by engine and independent referee |

#### Executable tools and skills

| File | Necessity / defect concentration | Greenfield disposition |
|---|---|---|
| `tools/audit.py` | Important gate; incomplete fingerprint, shared state, unbounded child process | Replace with hermetic task runner and signed result manifest |
| `tools/autobuild.py` | Useful supervisor concept; decision log loss and control replacement | Replace by declarative state-machine runner |
| `tools/awaiting_standings.py` | Operational queue helper | Keep as a thin database query/view |
| `tools/build_asserted.py` | Duplicates build/gate composition | Merge into one `dfs run` lifecycle CLI |
| `tools/claim.py` | Claim/evidence workflow is useful but separate surface area | Fold into artifact store and signed assertions |
| `tools/env_probe.py` | Necessary preflight; subprocesses lack deadlines | Keep as fast hermetic runtime probe with timeouts |
| `tools/extract_inbox_zips.py` | Useful archive intake; vulnerable to decompression resource exhaustion | Rewrite as quota-bound streaming quarantine extractor |
| `tools/fetch_fangraphs_platoon.py` | Provider fetcher | Put behind licensed-source adapter, deadline, schema, raw-byte retention |
| `tools/fetch_rotowire_lineups.py` | Provider fetcher | Same; never silently substitute providers |
| `tools/fetch_slate_bundle.py` | Bundle fetch is useful | Replace with manifest-driven source acquisition and one approved fallback per field |
| `tools/late_swap.py` | Necessary product action; does not run final referee before success | Rewrite around conditional portfolio optimizer and mandatory final-byte gate |
| `tools/lineups_from_paste.py` | Manual recovery | Keep quarantine-only; not a certified source |
| `tools/net_to_date.py` | Reporting helper | Rebuild from exact settlement ledger; never feed optimizer directly |
| `tools/ownership_pred.py` | Baseline ownership command | Replace with trained contest-conditioned field-model CLI |
| `tools/preflight_upload.py` | Valuable independent boundary; alias and durability defects | Preserve as separate package/process; reduce duplicated policy via generated contracts |
| `tools/promote_run.py` | Necessary release gate; missing required final-artifact check | Replace with transactional delivery command |
| `tools/qa_portfolio.py` | Useful human report; conflates unavailable with neutral | Make a view of typed evidence, never a separate source of truth |
| `tools/rebuild_registry.py` | Registry maintenance | Replace with deterministic view rebuild from immutable observations |
| `tools/refresh_reference_data.py` | Useful source refresh | Fold into source acquisition state machine with per-field policies |
| `tools/solver_probe.py` | Useful diagnostics | Keep in development/CI only; include solver version and termination behavior |
| `tools/stack_shape_probe.py` | Research diagnostic | Move to research namespace; do not load during production |
| `tools/stage_slate.py` | Useful immutable staging | Fold into one artifact-store command |
| `tools/sync_check.py` | Repository coordination, not DFS economics | Keep operationally separate from run certification |
| `tools/verify_export.py` | Valuable independent check | Merge its non-overlapping checks into the referee package |
| `tools/wheel_fetch.py` | Ad hoc environment bootstrap | Remove from the run path; build pinned images in CI |
| `skills/generate-lineups/scripts/build_slate.py` | 3K-line second orchestration path; Classic/Showdown split and positional assignment | Replace with thin CLI calling shared services |
| `skills/generate-lineups/evals/run_evals.py` | Useful agent-evaluation harness | Keep, but separate agent-behavior evals from code correctness |
| `skills/generate-lineups/SKILL.md` | Necessary user-facing skill, far too large and fact-drifting | Replace with a short router plus progressive references |
| `skills/mlb-standings-pull-checklist/SKILL.md` | Manual archival workflow | Keep outside lineup production; automate only authorized downloads |

#### Tests, configuration, data, and documentation

- `tests/test_core.py`, `test_showdown.py`, `test_upload_integrity.py`, `test_golden_replay.py`, and `test_paste_lineups.py` contain meaningful regression coverage. Split the 17K-line core suite by bounded domain; add property, mutation, concurrency, timeout, and economic-oracle tests. A passing synthetic suite is not EV evidence.
- `tests/fixtures/**` and `tests/golden/**` should remain immutable. Every golden record needs source hash, schema version, expected state, and explicit reason it is representative.
- `requirements.txt` and `requirements.lock` do not provide a runnable current-host environment. Replace them with a cross-platform lock for development and an OCI image digest for certification.
- `data/reference/**` files are inputs, not truth. Every row needs a primary source, `as_of`, acquisition time, raw artifact hash, schema version, and typed freshness state. Mutable “latest” files must be generated views.
- `data/archive/**`, `data/odds_history/**`, `data/order_history/**`, and `data/standings/**` are valuable evidence. Preserve exact bytes; ingest them once into normalized immutable observation tables. Never rewrite archives during training.
- `CLAUDE.md`, `MLB_Classic.md`, `MANIFEST.md`, `CHANGELOG.md`, `.audit/**`, `docs/**`, and `ledger/**` contain substantial history and operating knowledge. They must not be co-equal sources of current runtime truth. Keep historic material under `docs/history/`; generate present facts and policies from schemas/tests.
- `claims/.gitkeep`, `data/slates/.gitkeep`, and other placeholders have no logic. Keep only if required by packaging.

There are no tracked PowerShell or shell scripts. The filesystem also contains ignored first-party Python residue that is not part of the registered production surface. It was inspected separately because it remains executable:

| Ignored / historical Python | Review result |
|---|---|
| `.tmp/backlog_patch.py:7,145,191,198`; `.tmp/splice_ledger.py:8,56` | Hardcoded obsolete `/sessions/...` roots and direct document rewrites; preserve only as patch history, never execute |
| `outputs/2026-07-25/_scratch/build_thesis_lineups.py:15,107`; `make_theses.py:33-167` | Slate-specific hardcoded workflow and artifact writer; archive as dated research |
| `outputs/2026-08-08/drive_build.py:24-76` | Monkeypatches posture parsing with slate-specific contest facts; proves the canonical CLI cannot express needed context; replace with typed `ContestSpec` |
| `outputs/2026-08-11/_dump_alloc.py:12-44` | Monkeypatch/pickle diagnostic that changes import paths; development-only and unsafe as an entrypoint |
| `outputs/2026-08-13/run_build.py:7-49` | Dated wrapper injects ignored `.pylibs` and launches an unbounded child; archive |
| `outputs/2026-08-16/assert_lineup_gate_driver.py:1-12` | Correctly self-terminates as superseded; retain only if historic path resolution matters |
| `skills/generate-lineups-workspace/build_apex.py:26-195`; `deepen_bank.py:27-79` | Unregistered parallel skill implementation; fold any still-needed controls into typed production requests, then archive |
| `tools/_scratch_1835_9g/grow_bank.py:23-55` | Imports ignored `.pylibs` and monkeypatches bank limits at runtime; archive after preserving the incident evidence |
| `tools/_scratch_archive0822/build_ledger_entries.py:8-91`; `mine_driver.py:17-125`; `tranche.py:8-87` | One-off mutable mining/ledger pipeline with cwd-relative paths and direct rewrites; replace with immutable observation ingestion |

Ignored `.pylibs/**` and `.tmp/pylibs/**` contain third-party SciPy package trees, not first-party source. They were excluded from the line-by-line product-code review. Their presence is itself an environment hazard: dated wrappers can import unverified ignored dependencies that the default runtime cannot see. Certified execution must never depend on these trees.

Reference/config artifacts were reviewed as follows:

| Artifact | Disposition |
|---|---|
| `data/reference/contest_library.json` | Mutable contest metadata view; rebuild from immutable contest/payout observations |
| `dk_contest_archetypes.csv`, `dk_contest_paid_places.csv` | Useful empirical labels; add schema/as-of/source/sample-size and never substitute for exact payout data |
| `expected_stats_batting.csv`, `expected_stats_pitching.csv`, `fangraphs_season_pitching.csv`, `fangraphs_platoon_lineups.json` | Provider-derived model inputs; bind to raw source artifacts and effective dates, then freeze per run |
| `f5_park_factors.csv`, `f5_weather_adjustments.csv` | Handcrafted factor policies; retain as a baseline only until prospective calibration supports them |
| `field_opponent_registry.json` | Mutable pooled field view with the F-18/F-19 defects; replace with immutable normalized observations |
| `game_venue_overrides.csv`, `team_to_venue.csv` | Deterministic mappings; version, validate uniqueness/effective dates, and consume through one contract |
| `reference_manifest.json` | Correct checksum intent; make it generated, immutable per run, and complete for all referenced inputs |
| untracked root `slate_bundle.json` | A dated 2026-07-21 acquisition snapshot adjacent to current code; archive by hash and never resolve it implicitly as current |
| `skills/generate-lineups/evals/evals.json` and eval templates/shim | Agent-behavior fixtures; keep isolated from production model/test truth |
| `requirements.txt`, `requirements.lock` | Dependency configuration with the F-46 runtime gap; replace certification with a digest-pinned image |

### 1.9 Resolved defects that must not be re-reported as current

The prior Codex audit reviewed an older commit. Current head includes repairs that change the defect log:

- degraded DraftKings merge and off-slate blocker handling were repaired in R219/R220;
- preflight now refuses the wrong salary artifact when geometry or IDs mismatch;
- Showdown exposure counts now collapse `CPT` and `UTIL` roles to a person where required;
- ownership ingestion now collapses role rows for salary-person accounting.

Those behaviors still require regression coverage, but they are not listed below as open defects. Several earlier fraction-unit and registry-write concerns were only partially repaired; the remaining, narrower failures are listed with current line references.

---

## Section 2: Comprehensive Code Review & Defect Log

### 2.1 Severity and evidence conventions

- **Blocker:** can invalidate legality, delivery identity, lifecycle truth, or the claimed EV objective.
- **Bug:** produces an incorrect result or fail-open/fail-wrong state under a reachable input.
- **Performance:** causes avoidable latency, blocking, memory pressure, or unbounded work.
- **Technical Debt:** materially increases drift, ambiguity, or change risk even when current output may be correct.
- **Security:** exposes the pipeline to unsafe content, unauthorized interaction, or resource abuse.

“Source-proven” means the failure follows from the current control/data flow without needing the unavailable numerical runtime. “Reproduction required” means the static risk is real but its frequency or exact consequence must be measured in the pinned environment. Each remediation below is intended as copyable implementation direction; shared primitives are deliberately reused rather than inventing a new one-off fix per caller.

### F-01 — Audit cache can certify behavior it did not fingerprint — **Blocker**

**File & line / function:** `tools/audit.py:1044-1066`, `_code_fingerprint` and unit-record reuse.  
**Evidence:** source-proven.

**Issue / root cause / failure mode:** The fingerprint walks Python under `mlb_engine`, `tools`, and `tests`. The production entrypoint also executes `skills/generate-lineups/scripts/build_slate.py`, uses skill eval code, dependency locks, and behavior-changing reference/config files. A change in those inputs can reuse an earlier partial test record because the cache key did not change. The gate is then answering “did a related tree pass?” rather than “did these exact executable inputs pass in this exact runtime?”

**Remediation:** Define an explicit behavior manifest, hash paths and bytes in stable order, and include runtime/solver identity. A unit result may be reused only when the manifest digest, command digest, environment digest, and result schema all match.

```python
from __future__ import annotations

import hashlib
import json
import platform
from pathlib import Path

BEHAVIOR_GLOBS = (
    "mlb_engine/**/*.py",
    "tools/**/*.py",
    "skills/generate-lineups/**/*.py",
    "requirements.lock",
    "requirements.txt",
    "data/reference/reference_manifest.json",
)

def behavior_fingerprint(root: Path, *, solver_version: str) -> str:
    paths = sorted({p for pattern in BEHAVIOR_GLOBS for p in root.glob(pattern) if p.is_file()})
    h = hashlib.sha256()
    runtime = {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "solver": solver_version,
    }
    h.update(json.dumps(runtime, sort_keys=True, separators=(",", ":")).encode())
    for path in paths:
        rel = path.relative_to(root).as_posix().encode("utf-8")
        payload = path.read_bytes()
        h.update(len(rel).to_bytes(8, "big")); h.update(rel)
        h.update(len(payload).to_bytes(8, "big")); h.update(payload)
    return h.hexdigest()
```

### F-02 — Audit and environment probes can block forever — **Performance**

**File & line / function:** `tools/audit.py:886-889`; `tools/env_probe.py:139-140,192`; direct `subprocess.run` calls.  
**Evidence:** source-proven.

**Issue / root cause / failure mode:** The full test subprocess, environment reprobe, and pip probe have no deadline or process-tree cleanup. A hung solver, import hook, filesystem call, or child process can stall the only supervisor during the lock window. The target requirement explicitly forbids this.

**Remediation:** Route every child through one bounded runner. On timeout, terminate the process group, retain stdout/stderr, and return a typed `TIMEOUT` state. Never translate timeout into infeasibility or an empty result. Configure SciPy `milp(..., options={"time_limit": ...})` too; its documented default is unbounded. See [SciPy `milp`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.milp.html).

```python
from __future__ import annotations

import os
import signal
import subprocess
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

class ProcessState(StrEnum):
    COMPLETE = "COMPLETE"
    TIMEOUT = "TIMEOUT"

@dataclass(frozen=True)
class ProcessResult:
    state: ProcessState
    returncode: int | None
    stdout: str
    stderr: str

def run_bounded(argv: list[str], *, cwd: Path, timeout_s: float) -> ProcessResult:
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    proc = subprocess.Popen(
        argv, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        creationflags=creationflags, start_new_session=(os.name != "nt"),
    )
    try:
        out, err = proc.communicate(timeout=timeout_s)
        return ProcessResult(ProcessState.COMPLETE, proc.returncode, out, err)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            proc.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            os.killpg(proc.pid, signal.SIGTERM)
        try:
            out, err = proc.communicate(timeout=5.0)
        except subprocess.TimeoutExpired:
            proc.kill(); out, err = proc.communicate()
        return ProcessResult(ProcessState.TIMEOUT, None, out, err)
```

### F-03 — Fraction controls accept NaN, booleans, negatives, and unvalidated map entries — **Bug**

**File & line / function:** `mlb_engine/allocate/contest_allocator.py:1011-1043`, `assert_fraction_cap`; `contest_allocator.py:908-912,2524-2544`, game-cap clamps; `mlb_engine/entries/dk_entries_manager.py:765-767`; `mlb_engine/pipeline/execution_pipeline.py:2203-2223`, override-key policy.  
**Evidence:** source-proven.

**Issue / root cause / failure mode:** Validation converts with `float()` and principally rejects values above one. `bool` is accepted as a number, `NaN` evades ordered comparisons, negatives survive, and per-game map values are later clamped instead of rejected. Game-cap map keys are not covered by the same override validation. The run can therefore certify a different policy than the operator supplied.

**Remediation:** Parse every fraction once at the schema boundary; reject coercive and non-finite values; never clamp a policy input. Apply the same validator recursively to every map.

```python
import math
from numbers import Real
from typing import Mapping

def strict_fraction(value: object, *, key: str, allow_zero: bool = True) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{key} must be a real number, not {type(value).__name__}")
    parsed = float(value)
    lower_ok = parsed >= 0.0 if allow_zero else parsed > 0.0
    if not math.isfinite(parsed) or not lower_ok or parsed > 1.0:
        interval = "[0, 1]" if allow_zero else "(0, 1]"
        raise ValueError(f"{key} must be finite and in {interval}; got {value!r}")
    return parsed

def strict_fraction_map(values: Mapping[str, object], *, key: str) -> dict[str, float]:
    if not isinstance(values, Mapping):
        raise TypeError(f"{key} must be an object")
    return {str(k): strict_fraction(v, key=f"{key}.{k}") for k, v in values.items()}
```

### F-04 — Outer autobuild timeout loses its own decision record — **Bug**

**File & line / function:** `tools/autobuild.py:188-191`, outer-deadline branch; compare `tools/autobuild.py:230-242`, child-timeout branch.  
**Evidence:** source-proven.

**Issue / root cause / failure mode:** The outer-deadline branch appends a decision and returns exit code 5 without calling `_write`. The more specific child-timeout branch does persist. A deadline failure can therefore disappear from the durable audit trail—the exact incident that most needs evidence.

**Remediation:** Persist from `finally`, using an atomic writer. Exit status must be derived only after persistence succeeds.

```python
def run_supervisor(ctx: BuildContext) -> int:
    outcome = 1
    try:
        outcome = execute_until_terminal(ctx)
        return outcome
    except DeadlineExceeded as exc:
        ctx.decisions.append({"state": "TIMEOUT", "detail": str(exc)})
        outcome = 5
        return outcome
    finally:
        # atomic_write_json raises; a missing durable log is itself a failed run.
        atomic_write_json(ctx.decision_path, ctx.to_record(final_exit_code=outcome))
```

### F-05 — Supervisor controls replace the caller's entire JSON object — **Bug**

**File & line / function:** `tools/autobuild.py:193-219`, construction of the child command and repeated `--controls-override`.  
**Evidence:** source-proven under normal last-option-wins argument parsing.

**Issue / root cause / failure mode:** Caller arguments are forwarded and a supervisor-generated `--controls-override` is appended. When both occur, the later JSON value replaces the earlier object rather than merging individual controls. Enabling one supervisor control can silently discard unrelated caller controls.

**Remediation:** Parse child options into typed configuration, reject unknown/conflicting ownership, deep-merge only allowlisted keys, and emit exactly one canonical JSON object.

```python
from collections.abc import Mapping
from copy import deepcopy

def merge_controls(base: Mapping[str, object], supervisor: Mapping[str, object]) -> dict[str, object]:
    allowed = {"outer_deadline_s", "solver_time_limit_s", "max_retries", "source_timeouts"}
    unknown = set(supervisor) - allowed
    if unknown:
        raise ValueError(f"supervisor cannot own controls: {sorted(unknown)}")
    merged = deepcopy(dict(base))
    for key, value in supervisor.items():
        if key in merged and merged[key] != value:
            raise ValueError(f"conflicting control {key}: caller={merged[key]!r}, supervisor={value!r}")
        merged[key] = value
    return merged

controls_json = json.dumps(merge_controls(caller_controls, supervisor_controls), sort_keys=True)
child_argv.extend(["--controls-override", controls_json])
```

### F-06 — Doubleheader disagreement evidence is computed before slate-leg selection — **Bug**

**File & line / function:** `mlb_engine/intake/live_data_adapters.py:622-674`, raw game/order merge; selected-game use at `live_data_adapters.py:884-886`.  
**Evidence:** source-proven; the final pool was repaired, but the disagreement report still observes the broader raw set.

**Issue / root cause / failure mode:** Team-keyed DraftKings orders are compared across raw schedule games before the intended doubleheader leg is selected. Status may later use the correct leg while conflict evidence came from the dropped leg. On a doubleheader, the system can block or warn for a disagreement that is not on the slate.

**Remediation:** Select slate legs before any team-keyed reconciliation and retain an explicit exclusion record.

```python
selected_games, excluded_games = select_slate_legs(
    provider_games=tuple(games),
    dk_game_keys=frozenset(dk_game_keys),
    scheduled_start_tolerance_s=300,
)
orders_by_game = reconcile_orders(
    games=selected_games,
    dk_orders=dk_orders,
    key=lambda game: (game.away_team, game.home_team, game.start_utc),
)
report = {
    "selected_game_ids": [g.game_id for g in selected_games],
    "excluded_games": [e.to_dict() for e in excluded_games],
    "disagreements": build_disagreements(orders_by_game),
}
```

### F-07 — F4 normalized-name collisions are detected and then discarded — **Bug**

**File & line / function:** `mlb_engine/projections/projection_builder.py:844-977`, especially `887-893`, `_build_name_to_mlbam` result handling.  
**Evidence:** source-proven.

**Issue / root cause / failure mode:** `_build_name_to_mlbam` returns a lookup and a collision report. The caller discards the second value and continues with a highest-PA/name fallback. Homonyms or normalization collisions can therefore attach expected-stat evidence to the wrong player without a typed conflict.

**Remediation:** Use IDs first; allow a name fallback only when `(normalized_name, canonical_team)` is unique in both sources. Preserve every collision and fail the player feature closed.

```python
from dataclasses import dataclass
from enum import StrEnum

class JoinState(StrEnum):
    MATCHED = "MATCHED"
    UNKNOWN = "UNKNOWN"
    CONFLICTED = "CONFLICTED"

@dataclass(frozen=True)
class JoinResult:
    state: JoinState
    person_id: int | None
    candidates: tuple[int, ...]

def resolve_person(name: str, team: str, index: dict[tuple[str, str], set[int]]) -> JoinResult:
    candidates = tuple(sorted(index.get((normalize_name(name), canonical_team(team)), set())))
    if len(candidates) == 1:
        return JoinResult(JoinState.MATCHED, candidates[0], candidates)
    if not candidates:
        return JoinResult(JoinState.UNKNOWN, None, candidates)
    return JoinResult(JoinState.CONFLICTED, None, candidates)
```

### F-08 — Showdown MILP collapses time limit, solver error, and infeasibility to `None` — **Blocker**

**File & line / function:** `mlb_engine/optimize/showdown.py:238-367`, especially `354-365`, solver-result branch.  
**Evidence:** source-proven.

**Issue / root cause / failure mode:** `not res.success or res.x is None` returns `None`. SciPy/HiGHS distinguishes limit reached, infeasible, unbounded, and solver error. A limit-reached result can include an incumbent; a true infeasibility needs different control flow. The caller cannot tell them apart and may relax strategy as though the roster were impossible.

**Remediation:** Return a typed solve result. Only a proven infeasible status authorizes an infeasibility branch. A time-limit incumbent may be used only after deterministic constraint verification and must remain `FEASIBLE_LIMIT`, never `OPTIMAL`.

```python
from dataclasses import dataclass
from enum import StrEnum
import numpy as np

class SolveState(StrEnum):
    OPTIMAL = "OPTIMAL"
    FEASIBLE_LIMIT = "FEASIBLE_LIMIT"
    INFEASIBLE = "INFEASIBLE"
    UNBOUNDED = "UNBOUNDED"
    ERROR = "ERROR"

@dataclass(frozen=True)
class SolveResult:
    state: SolveState
    selected: tuple[int, ...] = ()
    objective: float | None = None
    message: str = ""

def decode_milp_result(res, contract, candidates) -> SolveResult:
    if res.status == 2:
        return SolveResult(SolveState.INFEASIBLE, message=res.message)
    if res.status == 3:
        return SolveResult(SolveState.UNBOUNDED, message=res.message)
    if res.x is None:
        return SolveResult(SolveState.ERROR, message=res.message)
    chosen = tuple(int(i) for i in np.flatnonzero(np.asarray(res.x) >= 0.5))
    contract.assert_indices_legal(chosen, candidates)
    state = SolveState.OPTIMAL if res.status == 0 else SolveState.FEASIBLE_LIMIT
    return SolveResult(state, chosen, float(res.fun), res.message)
```

### F-09 — Showdown captain-cap relaxation can occur without being counted — **Bug**

**File & line / function:** `mlb_engine/optimize/showdown_theses.py:694-734`, `_record_lock_relaxation` and floor fallback.  
**Evidence:** source-proven.

**Issue / root cause / failure mode:** The floor solve omits captain exclusions, thereby dropping a portfolio constraint. `captain_relaxed_slots` increments through a helper focused on named thesis-lock substitution. If no named lock is involved, the cap was still relaxed but the counter can remain zero. Conversely, named substitution can increment the counter even if the realized cap remains below its bound.

**Remediation:** Record constraint relaxations and named-thesis substitutions as separate typed events; postvalidate realized person-level captain counts from the final portfolio.

```python
@dataclass(frozen=True)
class RelaxationEvent:
    constraint: str
    scope: str
    reason: str

events: list[RelaxationEvent] = []
if floor_result is not None and cpt_excludes:
    events.append(RelaxationEvent(
        constraint="captain_exposure_cap",
        scope=contest_id,
        reason="floor solve removed captain exclusions",
    ))

realized = Counter(lineup.captain_person_id for lineup in final_lineups)
for person_id, count in realized.items():
    if count > captain_limit[person_id]:
        raise PortfolioConstraintViolation(person_id, count, captain_limit[person_id])
```

### F-10 — Run promotion does not require a final DraftKings artifact — **Blocker**

**File & line / function:** `mlb_engine/pipeline/build_state_manager.py:347-425`, `promote_run`; `tools/promote_run.py:165-175`, recorded-hash check.  
**Evidence:** source-proven.

**Issue / root cause / failure mode:** Promotion verifies artifacts that happen to be recorded but does not require a final/DKEntries role. The CLI compares the selected file only if `recorded_sha` is non-empty. A run with no recorded final artifact can therefore bypass the intended identity check and be promoted by supplying an external path.

**Remediation:** Promotion schema must require exactly one final-delivery record whose path, byte length, and SHA-256 match the selected regular file. Never make the check conditional on a non-empty stored hash.

```python
from pathlib import Path

def require_final_artifact(run: RunRecord, selected: Path) -> ArtifactRecord:
    finals = [a for a in run.artifacts if a.role == "dk_entries_final"]
    if len(finals) != 1:
        raise PromotionError(f"expected exactly one dk_entries_final artifact; found {len(finals)}")
    record = finals[0]
    resolved = selected.resolve(strict=True)
    if not resolved.is_file():
        raise PromotionError("selected final artifact is not a regular file")
    payload = resolved.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    if digest != record.sha256 or len(payload) != record.byte_length:
        raise PromotionError("selected bytes do not match the recorded final artifact")
    return record
```

### F-11 — Salary resolution is tied to a mutable global pointer and excludes Showdown lifecycle — **Blocker**

**File & line / function:** `tools/preflight_upload.py:393-465`, `resolve_salary_from_promoted_run`; Showdown path in `skills/generate-lineups/scripts/build_slate.py:2262-2420`.  
**Evidence:** source-proven.

**Issue / root cause / failure mode:** Preflight looks to a global promoted-run pointer to recover salary evidence. That is an ambient mutable dependency. Showdown does not use the same run-promotion lifecycle, so a zero-touch referee cannot reliably resolve its exact salary snapshot and falls back to manual `--salary`. Current geometry checks appropriately prevent a wrong file; they do not solve missing lineage.

**Remediation:** Every delivery gets a self-contained manifest binding final bytes to the exact staged salary artifact, entries template, mode, contest rows, and code/runtime identities. Preflight resolves by the final artifact hash, never by “latest.”

```python
@dataclass(frozen=True)
class DeliveryManifest:
    schema_version: str
    mode: str
    final_csv: ArtifactRef
    salary_csv: ArtifactRef
    entries_template: ArtifactRef
    run_id: str

def resolve_salary(delivery: DeliveryManifest, store: ArtifactStore) -> Path:
    store.assert_bytes(delivery.final_csv)
    salary = store.path_for(delivery.salary_csv.sha256)
    store.assert_bytes(delivery.salary_csv)
    return salary
```

### F-12 — Consensus moneyline aggregates raw American odds — **Bug**

**File & line / function:** `mlb_engine/intake/live_data_adapters.py:2390-2417`, moneyline consensus at `2409`.  
**Evidence:** source-proven.

**Issue / root cause / failure mode:** The code takes a median in American-odds space. American odds are nonlinear and discontinuous around even money. `-110` and `+110` are not symmetric probability observations, and books include vig. Raw-price aggregation distorts implied win probabilities and downstream features.

**Remediation:** Convert each book's paired sides to implied probability, remove vig within the book, aggregate probabilities, and retain dispersion. Convert back to display odds only after modeling.

```python
import math
from statistics import median

def american_to_prob(price: float) -> float:
    if not math.isfinite(price) or price == 0:
        raise ValueError(f"invalid American odds: {price!r}")
    return (-price) / ((-price) + 100.0) if price < 0 else 100.0 / (price + 100.0)

def no_vig_pair(home: float, away: float) -> tuple[float, float]:
    ph, pa = american_to_prob(home), american_to_prob(away)
    total = ph + pa
    if total <= 0:
        raise ValueError("invalid paired market")
    return ph / total, pa / total

def consensus_home_probability(pairs: list[tuple[float, float]]) -> float:
    if not pairs:
        raise ValueError("no paired moneyline observations")
    return median(no_vig_pair(home, away)[0] for home, away in pairs)
```

### F-13 — Local value guard can falsely upgrade projection provenance to enriched — **Bug**

**File & line / function:** `mlb_engine/pipeline/execution_pipeline.py:1092-1112`, `_applied`; `execution_pipeline.py:3302-3308`, value guard; `execution_pipeline.py:4221-4234`, projection-tier decision.  
**Evidence:** source-proven.

**Issue / root cause / failure mode:** `_applied` treats an `applied: true` object with no matched key as applied. The local value guard sets `applied: true` even when it clipped zero rows. Later logic includes it among signals that elevate the projection tier. A local sanitation rule can therefore make an unenriched projection appear externally enriched.

**Remediation:** Model source signals and local guards separately. A tier upgrade requires a predictive source with matched IDs, fresh evidence, and at least one changed value; guards can only lower trust.

```python
def source_signal_applied(report: Mapping[str, object]) -> bool:
    return (
        report.get("state") == "PASS"
        and report.get("kind") == "external_predictive_signal"
        and int(report.get("matched_players", 0)) > 0
        and int(report.get("changed_players", 0)) > 0
        and bool(report.get("evidence_sha256"))
    )

projection_tier = "ENRICHED" if any(source_signal_applied(x) for x in feature_reports) else "BASELINE"
```

### F-14 — Pool-agreement gate accepts vacuous truthy reports — **Blocker**

**File & line / function:** `mlb_engine/pipeline/execution_pipeline.py:1170-1197`, pool-agreement decision.  
**Evidence:** source-proven.

**Issue / root cause / failure mode:** A truthy mapping with missing schema, expected teams, evidence ID, or state can pass because empty blocker/thin collections look clean. This converts malformed or old upstream output into an affirmative gate.

**Remediation:** Validate a versioned report schema and exact expected team/game set. Missing fields are `UNKNOWN`, never `PASS`.

```python
def require_pool_agreement(report: object, *, expected_teams: set[str]) -> None:
    if not isinstance(report, dict):
        raise EvidenceUnknown("pool agreement report is absent or not an object")
    required = {"schema_version", "evidence_id", "state", "teams", "blockers"}
    missing = required - report.keys()
    if missing:
        raise EvidenceUnknown(f"pool agreement missing fields: {sorted(missing)}")
    if report["schema_version"] != "pool_agreement.v2" or report["state"] != "PASS":
        raise EvidenceUnknown(f"pool agreement state={report['state']!r}")
    observed = {canonical_team(x) for x in report["teams"]}
    if observed != expected_teams or report["blockers"]:
        raise EvidenceConflict("pool agreement does not match the exact slate")
```

### F-15 — Ownership/leverage controls exist but are not wired into production scoring — **Technical Debt**

**File & line / function:** `mlb_engine/optimize/optimizer_v3.py:778-780`, solver parameters; `optimizer_v3.py:3473-3505`, diagnostics; `optimizer_v3.py:3515-3528`, contest-fit objective; production call sites in `execution_pipeline.py` and `build_slate.py`.  
**Evidence:** source-proven by call-site trace; tests exercise some controls directly.

**Issue / root cause / failure mode:** Ownership/leverage parameters and tail diagnostics imply an economically informed optimizer, but production call sites do not supply the relevant controls and the displayed diagnostics are absent from the contest-fit objective. This is misleading API surface and creates a false sense that leverage is already optimized.

**Remediation:** Either delete dormant controls or wire a calibrated field prior explicitly. The recommended greenfield interface refuses a leverage objective unless the model artifact is supplied and validated.

```python
@dataclass(frozen=True)
class CandidateObjective:
    scenario_scores: "NDArray[np.float64]"
    field_model: ArtifactRef | None
    mode: Literal["diversity", "scenario_tail", "field_relative"]

    def validate(self) -> None:
        if self.mode == "field_relative" and self.field_model is None:
            raise ValueError("field_relative objective requires a calibrated field-model artifact")
```

### F-16 — Showdown duplicate identity ignores captain role — **Bug**

**File & line / function:** `mlb_engine/field/field_miner.py:767-779,1240-1248,1339-1346`, `players_norm` lineup keys.  
**Evidence:** source-proven.

**Issue / root cause / failure mode:** Duplicate keys are built from the set/sorted list of people. In Showdown, the same six people with different captains have different salaries and fantasy scores. Treating them as the same lineup corrupts duplication rates, winner attribution, and field-shape evidence.

**Remediation:** Canonical identity must include format and captain person. Roles may collapse to people for person exposure, but not for lineup identity.

```python
@dataclass(frozen=True, order=True)
class LineupIdentity:
    contest_type: str
    captain_person_id: int | None
    person_ids: tuple[int, ...]

def lineup_identity(contest_type: str, slots: Sequence[Slot]) -> LineupIdentity:
    captain = next((s.person_id for s in slots if s.role == "CPT"), None)
    if contest_type == "SHOWDOWN" and captain is None:
        raise ValueError("Showdown lineup has no captain")
    return LineupIdentity(contest_type, captain, tuple(sorted(s.person_id for s in slots)))
```

### F-17 — “Winner” selection maximizes points instead of requiring rank one — **Bug**

**File & line / function:** `mlb_engine/field/field_miner.py:774-779`, winner selection; rank parsing at `field_miner.py:1232-1238`.  
**Evidence:** source-proven.

**Issue / root cause / failure mode:** The miner selects the maximum fantasy-points record while rank is parsed elsewhere. That can select a tied or malformed row without establishing official rank, and it cannot distinguish multiple rank-one ties. Training “winner construction” on these rows introduces label error.

**Remediation:** Require parsed rank one, validate point/tie consistency, and preserve all tied winners with payout metadata. Missing rank produces `UNKNOWN`, not an inferred winner.

```python
def official_winners(rows: Sequence[StandingRow]) -> tuple[StandingRow, ...]:
    ranked = [row for row in rows if row.rank is not None]
    if not ranked:
        raise EvidenceUnknown("standings contain no parseable ranks")
    winners = tuple(row for row in ranked if row.rank == 1)
    if not winners:
        raise EvidenceConflict("standings contain no rank-one row")
    top_points = max(row.points for row in winners)
    if any(abs(row.points - top_points) > 1e-9 for row in winners):
        raise EvidenceConflict("rank-one rows disagree on fantasy points")
    return winners
```

### F-18 — Opponent registry pools incompatible contest populations — **Blocker**

**File & line / function:** `mlb_engine/field/field_miner.py:1300-1374`, `update_registry`; `mlb_engine/field/contest_library.py:185-189`, mutable registry persistence.  
**Evidence:** source-proven.

**Issue / root cause / failure mode:** User histories are primarily keyed by username and aggregate contest types and contexts. Classic and Showdown, small and large fields, single-entry and 150-max, and different stakes have different construction behavior. Pooling them yields a prior that is not conditional on the contest being entered.

**Remediation:** Store immutable observations at the finest supported context and derive shrinkage views. Do not overwrite a user blob.

```sql
CREATE TABLE field_entry_observation (
    contest_id TEXT NOT NULL,
    entry_id TEXT NOT NULL,
    observed_at_utc TEXT NOT NULL,
    contest_type TEXT NOT NULL,
    field_size INTEGER NOT NULL CHECK (field_size > 0),
    entry_fee_cents INTEGER NOT NULL CHECK (entry_fee_cents >= 0),
    max_entries INTEGER NOT NULL CHECK (max_entries > 0),
    archetype TEXT NOT NULL,
    username_hash TEXT NOT NULL,
    lineup_identity TEXT NOT NULL,
    raw_artifact_sha256 TEXT NOT NULL,
    PRIMARY KEY (contest_id, entry_id)
);
CREATE INDEX field_observation_context
ON field_entry_observation(contest_type, archetype, field_size, entry_fee_cents);
```

### F-19 — Atomic replacement does not prevent concurrent registry lost updates — **Bug**

**File & line / function:** `mlb_engine/field/field_miner.py:1310-1392`, read-modify-write and `_write_registry`; `mlb_engine/field/contest_library.py:185-189`, `save_registry`.  
**Evidence:** source-proven.

**Issue / root cause / failure mode:** One writer now replaces a complete temporary file atomically, preventing torn bytes. Two writers can still read the same old registry, independently add different observations, and replace each other; the last writer wins. The second direct `write_text` path is not atomic at all.

**Remediation:** Make the observation table authoritative and use a database transaction with an immutable primary key. Regenerate JSON only as a disposable view.

```python
def insert_observations(db: sqlite3.Connection, rows: Iterable[Observation]) -> None:
    with db:  # BEGIN/COMMIT; WAL mode is configured at connection creation.
        db.executemany(
            """INSERT INTO field_entry_observation
               (contest_id, entry_id, observed_at_utc, contest_type, field_size,
                entry_fee_cents, max_entries, archetype, username_hash,
                lineup_identity, raw_artifact_sha256)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(contest_id, entry_id) DO NOTHING""",
            (row.as_sql_tuple() for row in rows),
        )
```

### F-20 — Upload manifest can drop concurrent deliveries and supersessions — **Bug**

**File & line / function:** `mlb_engine/entries/upload_manifest.py:253-310`, `record_delivery`.  
**Evidence:** source-proven.

**Issue / root cause / failure mode:** The manifest performs read-modify-write on a shared document. Atomic replace protects file integrity, not serializability. Concurrent Classic/Showdown builds or late-swap delivery can each write a valid document that omits the other's record or supersession edge.

**Remediation:** Write each delivery record immutably by hash and update a transactional index. A supersession edge is an append-only record, not mutation of the old delivery.

```python
def record_delivery(db: sqlite3.Connection, delivery: DeliveryRecord) -> None:
    payload = delivery.canonical_json_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    with db:
        db.execute(
            "INSERT INTO deliveries(delivery_sha256, run_id, payload) VALUES (?, ?, ?)",
            (digest, delivery.run_id, payload),
        )
        for old_digest in delivery.supersedes:
            db.execute(
                "INSERT INTO supersessions(new_sha256, old_sha256) VALUES (?, ?)",
                (digest, old_digest),
            )
```

### F-21 — Immutable run artifacts are written non-atomically — **Bug**

**File & line / function:** `mlb_engine/pipeline/execution_pipeline.py:202-231`, JSON/CSV writers.  
**Evidence:** source-proven.

**Issue / root cause / failure mode:** Direct `write_text`, `open(..., "w")`, and `DataFrame.to_csv(path)` calls can leave a partial file after interruption. If the path is intended to become immutable run evidence, partial visibility violates the artifact model and can poison a subsequent resume.

**Remediation:** Serialize to a same-directory temporary file, flush and fsync, atomically replace, then re-read and hash the final bytes. Never record before replacement succeeds.

```python
import os
import tempfile
from pathlib import Path

def atomic_write_bytes(path: Path, payload: bytes) -> tuple[str, int]:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(payload); fh.flush(); os.fsync(fh.fileno())
        os.replace(temp, path)
        final = path.read_bytes()
        if final != payload:
            raise IOError("post-replace byte verification failed")
        return hashlib.sha256(final).hexdigest(), len(final)
    finally:
        temp.unlink(missing_ok=True)
```

### F-22 — Audit records share mutable state without session isolation — **Bug**

**File & line / function:** `tools/audit.py:980-1100`, `.audit_gate` records/fingerprint flow.  
**Evidence:** source-proven; concurrency reproduction required.

**Issue / root cause / failure mode:** Multiple runs share JSONL/state paths while the fingerprint omits important runtime/config identity. Concurrent audits can interleave records or reuse a unit whose execution context is not the current session. A flat “latest pass” is not adequate evidence.

**Remediation:** Give every gate execution an immutable `session_id`; write records under that directory; merge only after checking exact session/manifest identity. Use a transaction or exclusive lock for the small current-session pointer.

```python
@dataclass(frozen=True)
class AuditSession:
    session_id: str
    behavior_sha256: str
    runtime_sha256: str
    started_at_utc: str

def session_dir(root: Path, session: AuditSession) -> Path:
    path = root / ".audit_gate" / "sessions" / session.session_id
    path.mkdir(parents=True, exist_ok=False)
    atomic_write_bytes(path / "session.json", canonical_json(session))
    return path
```

### F-23 — ZIP intake has no decompression resource limits — **Security**

**File & line / function:** `tools/extract_inbox_zips.py:28-42`, member extraction.  
**Evidence:** source-proven.

**Issue / root cause / failure mode:** Flattening the filename limits path traversal, but `src.read()` loads an entire member into memory and there are no limits on member count, expanded bytes, or compression ratio. A malformed or accidental archive can exhaust memory/disk or monopolize the pipeline.

**Remediation:** Quarantine archives, reject duplicate flattened names, enforce size/count/ratio quotas, and stream to an atomic temporary file.

```python
MAX_MEMBERS = 500
MAX_MEMBER_BYTES = 256 * 1024 * 1024
MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
MAX_RATIO = 200.0
CHUNK = 1024 * 1024

def validate_member(info: zipfile.ZipInfo) -> None:
    ratio = info.file_size / max(1, info.compress_size)
    if info.file_size > MAX_MEMBER_BYTES or ratio > MAX_RATIO:
        raise UnsafeArchive(f"unsafe member {info.filename!r}")

def copy_member(zf: zipfile.ZipFile, info: zipfile.ZipInfo, target: Path) -> int:
    validate_member(info)
    written = 0
    temp: Path | None = None
    try:
        with zf.open(info, "r") as src, tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as out:
            temp = Path(out.name)
            while chunk := src.read(CHUNK):
                written += len(chunk)
                if written > MAX_MEMBER_BYTES:
                    raise UnsafeArchive("member exceeded declared quota")
                out.write(chunk)
            out.flush(); os.fsync(out.fileno())
        os.replace(temp, target)
        return written
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)

def extract_archive(archive: Path, quarantine: Path) -> list[Path]:
    extracted: list[Path] = []
    total = 0
    names: set[str] = set()
    with zipfile.ZipFile(archive) as zf:
        members = [x for x in zf.infolist() if not x.is_dir()]
        if len(members) > MAX_MEMBERS:
            raise UnsafeArchive("archive member-count quota exceeded")
        for info in members:
            flat = Path(info.filename).name
            if not flat or flat in names:
                raise UnsafeArchive(f"empty or duplicate flattened name: {flat!r}")
            names.add(flat)
            target = quarantine / flat
            total += copy_member(zf, info, target)
            if total > MAX_TOTAL_BYTES:
                raise UnsafeArchive("archive expanded-byte quota exceeded")
            extracted.append(target)
    return extracted
```

### F-24 — Slate clock silently ignores malformed game start times — **Blocker**

**File & line / function:** `mlb_engine/intake/slate_intake_manager.py:1727-1737`, timestamp parsing; `slate_intake_manager.py:1740-1792`, `slate_clock`.  
**Evidence:** source-proven.

**Issue / root cause / failure mode:** Failed timestamp parses are skipped. If at least one other game parses, the clock can be marked available even though a relevant game's lock is unknown. That can authorize edits or late-swap assumptions after an unrecognized lock time.

**Remediation:** Return a result per scheduled game. The slate clock is complete only when every in-scope game has a validated, timezone-aware lock; otherwise its state is `UNKNOWN` and delivery blocks.

```python
@dataclass(frozen=True)
class GameLock:
    game_id: str
    state: EvidenceState
    start_utc: datetime | None
    raw_value: str

def build_slate_clock(games: Sequence[Game]) -> SlateClock:
    locks = tuple(parse_game_lock(game) for game in games)
    complete = bool(locks) and all(x.state is EvidenceState.PASS for x in locks)
    return SlateClock(
        state=EvidenceState.PASS if complete else EvidenceState.UNKNOWN,
        locks=locks,
        earliest_lock_utc=min((x.start_utc for x in locks if x.start_utc), default=None),
    )
```

### F-25 — Wind-speed bands contain floating-point gaps — **Bug**

**File & line / function:** `mlb_engine/intake/slate_intake_manager.py:1557-1602`, wind bands and `_wind_band_for_speed`; silent downstream no-factor path at `1668-1674`.  
**Evidence:** source-proven.

**Issue / root cause / failure mode:** Bands are encoded as `8.0-12.999`, `13.0-17.999`, and `18+`. Valid floats between 12.999 and 13.0 (and 17.999 and 18.0) match nothing. The downstream path silently applies no factor rather than raising a coverage error.

**Remediation:** Use ordered half-open intervals and validate that they cover the policy domain without gaps/overlap.

```python
WIND_BANDS = (
    (0.0, 8.0, "CALM"),
    (8.0, 13.0, "MODERATE"),
    (13.0, 18.0, "STRONG"),
    (18.0, float("inf"), "SEVERE"),
)

def wind_band(speed_mph: float) -> str:
    if not math.isfinite(speed_mph) or speed_mph < 0:
        raise ValueError(f"invalid wind speed {speed_mph!r}")
    matches = [name for low, high, name in WIND_BANDS if low <= speed_mph < high]
    if len(matches) != 1:
        raise AssertionError(f"wind-band policy has {len(matches)} matches for {speed_mph}")
    return matches[0]
```

### F-26 — Classic roster rules remain duplicated despite a roster-contract module — **Technical Debt**

**File & line / function:** `mlb_engine/optimize/roster_contracts.py:1-15`; Classic constants and validations across `optimizer_v3.py`, `dk_entries_manager.py`, `build_slate.py`, and `preflight_upload.py`.  
**Evidence:** source-proven.

**Issue / root cause / failure mode:** The contract module explicitly centralizes only part of the format surface. Classic slot counts, salary cap/floor, team limits, hitter/pitcher rules, and CSV geometry are repeated. Independent checks are valuable, but duplicated handwritten rules drift. An independent referee should consume a generated immutable contract, not copy policy constants manually.

**Remediation:** Define one versioned data contract and generate both solver coefficients and referee fixtures from it. Independence is maintained by separate implementations and golden vectors.

```python
@dataclass(frozen=True)
class RosterContract:
    version: str
    mode: Literal["CLASSIC", "SHOWDOWN"]
    slots: tuple[str, ...]
    salary_cap: int
    salary_floor: int | None
    max_players_per_team: int | None
    score_multiplier_by_slot: Mapping[str, float]
    salary_multiplier_by_slot: Mapping[str, float]

    def validate(self) -> None:
        if len(set(self.slots)) != len(self.slots):
            raise ValueError("slot names must be unique")
        if self.salary_cap <= 0 or (self.salary_floor is not None and self.salary_floor > self.salary_cap):
            raise ValueError("invalid salary bounds")
```

### F-27 — Core modules are orchestration monoliths — **Technical Debt**

**File & line / function:** `optimizer_v3.py` (~4,277 lines), `execution_pipeline.py` (~4,343), `build_slate.py` (~3,325), `contest_allocator.py` (~2,984), `live_data_adapters.py` (~2,664), `field_miner.py` (~2,073), `preflight_upload.py` (~1,930).  
**Evidence:** source-proven structural finding.

**Issue / root cause / failure mode:** Parsing, policy, model features, I/O, solver construction, reporting, and lifecycle transitions live in the same files. This makes it difficult to prove pure invariants, encourages circular data dictionaries, and makes every change carry a large regression surface. It also prevents cheap stage-level retries.

**Remediation:** Use explicit ports and immutable stage results. The orchestrator contains no domain math.

```python
class Stage(Protocol[InputT, OutputT]):
    name: str
    input_schema: str
    output_schema: str

    def run(self, value: InputT, context: RunContext) -> OutputT: ...

def execute_stage(stage: Stage[InputT, OutputT], value: InputT, ctx: RunContext) -> OutputT:
    input_ref = ctx.store.put(stage.input_schema, canonical_bytes(value))
    cached = ctx.store.lookup_stage(stage.name, input_ref, ctx.code_ref, ctx.runtime_ref)
    if cached is not None:
        return decode_checked(cached, stage.output_schema)
    output = stage.run(value, ctx)
    ctx.store.commit_stage(stage.name, input_ref, output, ctx)
    return output
```

### F-28 — Game-cap test is confounded by the default candidate-reuse cap — **Technical Debt**

**File & line / function:** `tests/test_core.py:1278-1293`, game-cap allocation test.  
**Evidence:** source-proven test-design defect.

**Issue / root cause / failure mode:** The fixture has two entries/candidates while the default reuse rule independently forces diversification. The test passes even if the game-exposure constraint is removed, so it does not prove the named behavior.

**Remediation:** Neutralize every competing constraint, use enough entries to expose the bound, and add a mutation assertion showing the counterfactual.

```python
def test_game_cap_is_binding():
    entries = make_entries(3)
    candidates = [candidate("X", game="G1", score=100), candidate("Y", game="G2", score=90)]
    result = allocate(entries, candidates, max_candidate_reuse=3, game_caps={"G1": 1 / 3})
    assert [x.candidate_id for x in result].count("X") == 1
    assert [x.candidate_id for x in result].count("Y") == 2

    without_cap = allocate(entries, candidates, max_candidate_reuse=3, game_caps={})
    assert [x.candidate_id for x in without_cap].count("X") == 3
```

### F-29 — Candidate-bank expansion launches avoidable infeasible/equivalent MILPs — **Performance**

**File & line / function:** `mlb_engine/optimize/bank_cache.py:616-835`, `extend_bank`; Cartesian jobs at `768-773`.  
**Evidence:** source-proven opportunity; runtime savings require benchmark.

**Issue / root cause / failure mode:** Jobs are constructed across usable pitcher pairs and stack teams before inexpensive team/lock/exclusion feasibility tests and canonical equivalence collapse. Many solver calls can be proven impossible or identical with bitsets first.

**Remediation:** Compute player/team eligibility bitsets, reject underfilled stack structures, canonicalize constraints, and run unique jobs through a bounded worker pool. Cache by complete immutable job identity.

```python
@dataclass(frozen=True, order=True)
class JobKey:
    pitcher_ids: tuple[int, ...]
    stack_team: str
    contract_sha256: str
    locks_sha256: str
    scenario_sha256: str

def feasible_job(pair: tuple[int, int], team: str, pool: PlayerBitsets, stack_size: int) -> bool:
    if pair[0] == pair[1] or not pool.pitchers.contains_all(pair):
        return False
    eligible_hitters = pool.hitters_by_team[team] & ~pool.excluded & ~pool.conflicts_with_pitchers(pair)
    return eligible_hitters.bit_count() >= stack_size

jobs = sorted({make_job(pair, team) for pair in pairs for team in teams if feasible_job(pair, team, pool, 5)})
```

### F-30 — Exposure constraints are global rather than contest- and capital-aware — **Blocker**

**File & line / function:** `mlb_engine/allocate/contest_allocator.py:2477-2548`, portfolio exposure constraints.  
**Evidence:** source-proven design mismatch.

**Issue / root cause / failure mode:** Exposure denominators use total portfolio entries. A player can be concentrated in one high-dollar contest while diluted by many low-dollar entries elsewhere, passing the global cap while concentrating bankroll risk. Different contests also have different field distributions and payout curvature.

**Remediation:** Index assignment by exact entry and contest. Apply count and entry-fee-weighted limits within declared scopes; optimize the scenario return matrix instead of a global heuristic score.

```python
# y[e, l] is binary. These rows are added to a MILP builder.
for entry in entries:
    model.add_eq(sum(y[entry.id, l.id] for l in eligible[entry.id]), 1)

for contest in contests:
    scoped = [e for e in entries if e.contest_id == contest.id]
    for person in persons:
        model.add_le(
            sum(y[e.id, l.id] for e in scoped for l in eligible[e.id] if person in l.person_ids),
            math.floor(contest.player_cap[person] * len(scoped)),
        )

for person in persons:
    model.add_le(
        sum(e.entry_fee_cents * y[e.id, l.id] for e in entries for l in eligible[e.id] if person in l.person_ids),
        capital_cap[person] * sum(e.entry_fee_cents for e in entries),
    )
```

### F-31 — Late-swap success does not execute the final-byte referee — **Blocker**

**File & line / function:** `tools/late_swap.py:805-883`, delivery/promotion path; printed preflight command at `880`; `mlb_engine/swap/late_swap_manager.py:339-369`, delta-only validation.  
**Evidence:** source-proven.

**Issue / root cause / failure mode:** The tool writes, records, and promotes the late-swap CSV, then prints a preflight command and returns success. The independent referee is optional human follow-up. A rendering, salary, identity, or manifest defect introduced after delta validation can therefore be delivered as successful.

**Remediation:** Write to a candidate path, run the independent referee in a separate process against exact bytes and bound evidence, record its signed result, and rename/promote only on `PASS`.

```python
candidate_ref = store.put("dk_entries_candidate.v1", rendered_csv_bytes)
referee = run_referee_bounded(
    final_ref=candidate_ref,
    salary_ref=delivery.salary_csv,
    entries_ref=delivery.entries_template,
    contract_ref=delivery.roster_contract,
    timeout_s=30.0,
)
if referee.state is not EvidenceState.PASS or referee.subject_sha256 != candidate_ref.sha256:
    raise DeliveryBlocked(f"late-swap referee state={referee.state}")
delivery_ref = store.commit_delivery(candidate_ref, referee)
```

### F-32 — Forced-swap validation is hardcoded true — **Bug**

**File & line / function:** `mlb_engine/swap/late_swap_manager.py:372-388`, validation result construction.  
**Evidence:** source-proven.

**Issue / root cause / failure mode:** Both branches set `forced_swap_validation_passed=True`; the value is not derived from a validation artifact. A report field that always says “passed” is worse than absent because downstream code can treat it as evidence.

**Remediation:** Require a hash-bound validation report and derive the boolean/state from it. If no forced swaps exist, use `NOT_APPLICABLE`, not `PASS`.

```python
def forced_swap_state(required: set[int], report: SwapValidationReport | None, final_sha256: str) -> EvidenceState:
    if not required:
        return EvidenceState.NOT_APPLICABLE
    if report is None or report.subject_sha256 != final_sha256:
        return EvidenceState.UNKNOWN
    if report.missing_required or report.illegal_changes or not report.referee_passed:
        return EvidenceState.FAIL
    return EvidenceState.PASS
```

### F-33 — Independent preflight uses an incomplete team-alias boundary — **Bug**

**File & line / function:** `tools/preflight_upload.py:1362-1417`, confirmed-team comparisons; canonical mapping in `mlb_engine/team_codes.py`.  
**Evidence:** source-proven for alias divergence; affected slates require reproduction.

**Issue / root cause / failure mode:** The referee uppercases raw feed and salary team strings but does not use the engine's canonical mappings. Aliases such as `AZ`/`ARI` can split the same club, making a confirmed-lineup check degrade or disagree with production. Independence does not require inconsistent nomenclature.

**Remediation:** Generate a dependency-free, versioned alias artifact from the canonical contract and make both implementations verify its hash. Normalize both operands before comparison.

```python
def load_team_alias_contract(path: Path, expected_sha256: str) -> dict[str, str]:
    payload = path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != expected_sha256:
        raise EvidenceConflict("team alias contract hash mismatch")
    doc = json.loads(payload)
    return {str(k).strip().upper(): str(v).strip().upper() for k, v in doc["aliases"].items()}

def canonical_team(value: object, aliases: Mapping[str, str]) -> str:
    raw = str(value).strip().upper()
    if raw not in aliases:
        raise EvidenceUnknown(f"unknown team alias {raw!r}")
    return aliases[raw]
```

### F-34 — Preflight can return success when durable manifest stamping fails — **Blocker**

**File & line / function:** `tools/preflight_upload.py:1032-1107`, `stamp_manifest_status`; `preflight_upload.py:1834-1863`, exit flow.  
**Evidence:** source-proven.

**Issue / root cause / failure mode:** Missing/unreadable target records cause an early return, and write failures are warnings. The main path calculates the successful exit code before stamping and can return zero even though the `upload_ready` verdict was never durably bound to the delivery.

**Remediation:** Return a structured persistence result. For a shipping verdict, absence, mismatch, or failed persistence is a hard failure. Re-read the committed status and compare the subject hash before returning zero.

```python
def persist_referee_verdict(index: DeliveryIndex, verdict: RefereeVerdict) -> ArtifactRef:
    delivery = index.require_delivery(verdict.subject_sha256)
    verdict_ref = index.store.put("referee_verdict.v1", verdict.canonical_bytes())
    index.bind_verdict_transactionally(delivery.sha256, verdict_ref.sha256)
    rebound = index.require_verdict(delivery.sha256)
    if rebound.sha256 != verdict_ref.sha256:
        raise DeliveryBlocked("referee verdict was not durably bound")
    return verdict_ref

exit_code = 0 if verdict.state is EvidenceState.PASS else 2
if exit_code == 0:
    persist_referee_verdict(index, verdict)  # Any exception keeps the process nonzero.
return exit_code
```

### F-35 — Showdown's flat person cap is skill-blind — **Blocker**

**File & line / function:** `mlb_engine/optimize/showdown_theses.py:633-668`, person-cap exclusion ladder; observed build analysis in `docs/backlog_inbox/2026-08-27_BUILD_player-exposure-cap-is-skill-blind.md:10-59`.  
**Evidence:** source-proven mechanism; repository build evidence shows tightening a cap can move slots from higher-prior to lower-prior players, but the prior itself is not validated EV.

**Issue / root cause / failure mode:** Once a person reaches a flat count, every role for that person is excluded regardless of projection edge, uncertainty, correlation, contest, entry fee, or opportunity cost. A cap may reduce portfolio quality more than it reduces risk and can systematically push tail entries toward dominated replacements.

**Remediation:** Optimize scenario return/risk jointly. If an operational cap remains, make it contest- and capital-scoped and report its utility cost. Never call the resulting portfolio maximum-EV unless the cap is part of the declared utility/risk mandate.

```python
unconstrained = solve_portfolio(problem, caps=None)
constrained = solve_portfolio(problem, caps=policy_caps)
utility_cost = unconstrained.expected_utility - constrained.expected_utility
if utility_cost > policy.max_allowed_utility_cost:
    raise PortfolioPolicyConflict(
        f"exposure policy costs {utility_cost:.6f} utility units; human policy decision required"
    )
report = CapCostReport(
    expected_profit_delta=constrained.expected_profit - unconstrained.expected_profit,
    cvar_delta=constrained.cvar - unconstrained.cvar,
    utility_delta=-utility_cost,
)
```

### F-36 — Sequential thesis ladder spends capacity before named-captain requirements — **Bug**

**File & line / function:** `mlb_engine/optimize/showdown_theses.py:625-668`, sequential solve and captain exclusion construction; observed build analysis in `docs/backlog_inbox/2026-08-27_BUILD_thesis-ladder-spends-cap-in-util-before-captain.md:8-34`.  
**Evidence:** source-proven mechanism; repository build evidence documents named-captain substitutions under the ladder.

**Issue / root cause / failure mode:** Earlier generic thesis rows consume person/CPT capacity. Named-captain rows are solved later and can be blocked by choices that a joint optimizer would have rearranged. Order becomes an undocumented economic priority.

**Remediation:** Solve all requested entries jointly. Named captain requirements are assignment constraints, not sequential locks.

```python
# y[e, l] assigns lineup l to entry e.
for entry in entries:
    model.add_eq(sum(y[entry.id, l.id] for l in eligible[entry.id]), 1)
    if entry.required_captain_person_id is not None:
        model.add_eq(
            sum(y[entry.id, l.id] for l in eligible[entry.id]
                if l.captain_person_id == entry.required_captain_person_id),
            1,
        )
# Portfolio caps are added once over all entries, so the solver reserves capacity globally.
```

### F-37 — Showdown tail degradation is legal but economically invisible — **Blocker**

**File & line / function:** `mlb_engine/optimize/showdown_theses.py:647-665`, cap-driven reassignment/floor substitution; observed build analysis in `docs/backlog_inbox/2026-08-27_BUILD_showdown_tightened_cap_degrades_bank_tail_uncounted.md:1-37`.  
**Evidence:** source-proven absence; severity of loss requires calibrated model.

**Issue / root cause / failure mode:** When caps force substitutions, the system can produce a fully legal portfolio with clean counters but no constrained-vs-unconstrained utility delta. Salary remaining or projection loss is not a sufficient proxy for contest profit. The weakest tail can degrade severely without a blocking or even quantified signal.

**Remediation:** Always solve and retain a policy-free benchmark under identical evidence; compare expected profit, loss quantiles, CVaR, duplication, and calibration uncertainty. Set explicit policy thresholds.

```python
def compare_portfolios(base: PortfolioMetrics, governed: PortfolioMetrics) -> GovernanceImpact:
    return GovernanceImpact(
        expected_net_delta=governed.expected_net - base.expected_net,
        p_profit_delta=governed.p_profit - base.p_profit,
        cvar_05_delta=governed.cvar_05 - base.cvar_05,
        worst_entry_ev_delta=min(governed.entry_ev[e] - base.entry_ev[e] for e in base.entry_ev),
    )
```

### F-38 — QA calls missing F1 evidence “neutral” — **Bug**

**File & line / function:** `tools/qa_portfolio.py:146-155`, enrichment summary.  
**Evidence:** source-proven.

**Issue / root cause / failure mode:** When the enrichment block is absent, the report renders `F1 NEUTRAL`. For Showdown, Classic F1 may never have been computed. Absence, not-applicable, zero effect, and fresh evidence whose estimate is exactly neutral are distinct states.

**Remediation:** Render typed state independently from numeric effect.

```python
def describe_feature(feature: FeatureEvidence | None) -> str:
    if feature is None:
        return "F1 NOT_COMPUTED"
    if feature.state is EvidenceState.NOT_APPLICABLE:
        return "F1 NOT_APPLICABLE"
    if feature.state is not EvidenceState.PASS:
        return f"F1 {feature.state}"
    return f"F1 APPLIED effect={feature.effect:+.4f}" if feature.applied else "F1 PASS_NO_EFFECT"
```

### F-39 — Showdown does not resolve the same contest archetype/economic context — **Blocker**

**File & line / function:** Showdown build flow in `skills/generate-lineups/scripts/build_slate.py:2262-2420`; unresolved QA branch in `tools/qa_portfolio.py:683-720`; Classic shape resolution in the alternative path.  
**Evidence:** source-proven.

**Issue / root cause / failure mode:** Showdown bypasses the Classic contest-posture resolver and has incomplete ownership/field fields. A single-entry small-field contest and a top-heavy large-field 150-max contest therefore share the same thesis ladder even though duplication, optimal risk, and payout utility differ.

**Remediation:** Build one exact `ContestSpec` from each DK entry row and payout table before either format branches. Every field model and portfolio solve requires that object.

```python
@dataclass(frozen=True)
class ContestSpec:
    contest_id: str
    mode: Literal["CLASSIC", "SHOWDOWN"]
    field_size: int
    max_entries: int
    entry_fee_cents: int
    payouts_cents: tuple[int, ...]
    archetype: str
    source_ref: ArtifactRef

    def validate(self) -> None:
        if len(self.payouts_cents) > self.field_size:
            raise ValueError("payout curve exceeds field size")
        if any(x < 0 for x in self.payouts_cents):
            raise ValueError("negative payout")
```

### F-40 — Showdown has no external projection-bundle input — **Blocker**

**File & line / function:** `mlb_engine/optimize/showdown.py:117-176`, `Base` from `AvgPointsPerGame`; `skills/generate-lineups/scripts/build_slate.py:2262-2334`, Showdown melt/build arguments.  
**Evidence:** source-proven.

**Issue / root cause / failure mode:** Showdown construction uses DraftKings APPG as the base and the build path exposes no equivalent current projection bundle. Current lineup, batting slot, pitcher role, game environment, and uncertainty do not enter through a calibrated shared model.

**Remediation:** Both formats consume the same person-level scenario matrix, with slot multipliers applied by the roster contract. Role rows must not create two independent player outcomes.

```python
@dataclass(frozen=True)
class PlayerScenarioBundle:
    person_ids: "NDArray[np.int64]"       # P
    scores: "NDArray[np.float32]"         # S x P, person outcomes
    active: "NDArray[np.bool_]"            # S x P
    artifact: ArtifactRef

def role_scores(bundle: PlayerScenarioBundle, roles: Sequence[DraftableRole], contract: RosterContract):
    person_col = {int(pid): i for i, pid in enumerate(bundle.person_ids)}
    return np.column_stack([
        bundle.scores[:, person_col[role.person_id]] * contract.score_multiplier_by_slot[role.slot]
        for role in roles
    ])
```

### F-41 — Showdown lineups are assigned to entries by position — **Blocker**

**File & line / function:** `skills/generate-lineups/scripts/build_slate.py:2355-2360`, positional assignment.  
**Evidence:** source-proven.

**Issue / root cause / failure mode:** The nth generated lineup is written to the nth entry. Entry fee, field size, payout curve, max-entry context, duplication distribution, and existing exposure are ignored. Even if the lineups were individually good, the assignment can be economically dominated.

**Remediation:** Treat each reserved row as a decision variable in the joint portfolio MILP. Output order is restored only after allocation.

```python
assignments = portfolio_solver.solve(
    entries=tuple(exact_entries),
    candidates=tuple(candidate_bank),
    scenario_net_returns=returns_by_entry_candidate,
    risk_policy=risk_policy,
)
rows_by_entry_id = {a.entry_id: render_lineup(a.lineup_id) for a in assignments}
output_rows = [template.with_lineup(rows_by_entry_id[template.entry_id]) for template in entries_in_original_order]
```

### F-42 — Relaxation counters conflate thesis substitution with cap violation — **Bug**

**File & line / function:** `mlb_engine/optimize/showdown_theses.py:694-715`, `_record_lock_relaxation`; observed QA evidence in `docs/backlog_inbox/2026-08-27_BUILD_showdown_f1_and_archetype_gaps.md:34-42`.  
**Evidence:** source-proven semantics; repository evidence contains a run with `captain_relaxed_slots=1` while the realized captain cap remained below the bound.

**Issue / root cause / failure mode:** A named captain replacement increments a field named like a constraint relaxation even when no exposure cap is exceeded. The metric cannot answer whether a portfolio rule was actually relaxed.

**Remediation:** Use disjoint event types and compute all cap compliance from final lineups, not procedural counters.

```python
@dataclass(frozen=True)
class ThesisSubstitution:
    entry_id: str
    requested_person_id: int
    selected_person_id: int
    reason: str

@dataclass(frozen=True)
class ConstraintAudit:
    name: str
    limit: float
    realized: float
    state: EvidenceState

captain_audits = audit_person_caps(final_lineups, captain_limits)
if any(a.realized > a.limit for a in captain_audits):
    raise PortfolioConstraintViolation("captain exposure")
```

### F-43 — Missing projection factors are numerically rewritten as `1.0` — **Blocker**

**File & line / function:** `mlb_engine/pipeline/execution_pipeline.py:3059-3062`, F1-F5 fill; projection build/gating downstream.  
**Evidence:** source-proven.

**Issue / root cause / failure mode:** Missing factor columns receive `1.0` with notes. Numeric neutrality erases epistemic state: “known to have no adjustment,” “not applicable,” “provider failed,” and “not computed” become identical model inputs. The engine can then solve and promote a lineup without propagating a potentially material unknown.

**Remediation:** Store values and states separately. Policy decides whether a state permits a numeric fallback; the fallback never changes the state.

```python
@dataclass(frozen=True)
class FeatureValue:
    value: float | None
    state: EvidenceState
    evidence: ArtifactRef | None

def numeric_feature(feature: FeatureValue, policy: FeaturePolicy) -> float:
    if feature.state is EvidenceState.PASS and feature.value is not None:
        return feature.value
    if feature.state is EvidenceState.NOT_APPLICABLE:
        return policy.not_applicable_value
    if policy.blocks(feature.state):
        raise EvidenceBlocked(f"feature state {feature.state}")
    return policy.degraded_value  # state remains non-PASS in the run manifest
```

### F-44 — Instruction and manifest truth is duplicated and stale — **Technical Debt**

**File & line / function:** `MANIFEST.md:10,39,59,73`; `CLAUDE.md:297`; `skills/generate-lineups/SKILL.md:873`; large always-loaded instruction documents.  
**Evidence:** source-proven.

**Issue / root cause / failure mode:** Documents disagree on 12 vs. 26 modules and 119 vs. 1,313 vs. 1,276 tests. Mutable operational facts are hand-copied into multiple prompts. Agents either trust stale prose or spend tokens rediscovering truth.

**Remediation:** Generate a small facts artifact in CI and validate documentation references. Keep root instructions policy-only.

```python
def build_system_facts(root: Path) -> dict[str, object]:
    production = sorted(root.glob("mlb_engine/**/*.py"))
    discovered = unittest.defaultTestLoader.discover(str(root / "tests"))
    return {
        "schema_version": "system_facts.v1",
        "production_python_files": len(production),
        "test_cases": discovered.countTestCases(),
        "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
    }
```

### F-45 — Scratch and handoff residue creates an ambiguous execution surface — **Technical Debt**

**File & line / function:** `.tmp/backlog_patch.py:7,145-198`; `.tmp/splice_ledger.py:8,56`; `outputs/2026-08-08/drive_build.py:24-76`; `outputs/2026-08-11/_dump_alloc.py:12-44`; `outputs/2026-08-13/run_build.py:7-49`; `skills/generate-lineups-workspace/build_apex.py:26-195`; `deepen_bank.py:27-79`; `tools/_scratch_1835_9g/grow_bank.py:23-55`; `tools/_scratch_archive0822/*.py`.  
**Evidence:** source-proven workspace observation; no files were changed.

**Issue / root cause / failure mode:** Old runnable scripts and copied trees are discoverable next to canonical tools but absent from audit fingerprints and review scope. A human or agent can execute a stale entrypoint that looks current. Untracked artifacts also make broad staging dangerous.

**Remediation:** Preserve evidence but quarantine it. Production resolves entrypoints from a checked manifest; anything outside it refuses to run without an explicit research flag.

```python
def require_registered_entrypoint(script: Path, manifest: Mapping[str, str], root: Path) -> None:
    rel = script.resolve().relative_to(root.resolve()).as_posix()
    expected = manifest.get(rel)
    if expected is None:
        raise SystemExit(f"unregistered entrypoint: {rel}")
    actual = hashlib.sha256(script.read_bytes()).hexdigest()
    if actual != expected:
        raise SystemExit(f"entrypoint hash mismatch: {rel}")
```

### F-46 — The certification runtime is not reproducible on the current host — **Blocker**

**File & line / function:** `requirements.lock`; `requirements.txt`; `tools/env_probe.py`; audit invocation on 2026-08-27.  
**Evidence:** directly reproduced in this review.

**Issue / root cause / failure mode:** The lock identifies Python 3.10/Linux wheels, while the default available host interpreter is Python 3.13 and cannot import NumPy, Pandas, or SciPy. Ignored `.pylibs`/`.tmp/pylibs` SciPy trees exist and dated scratch wrappers inject them into `sys.path`, but they are not a validated, default, hash-bound environment. Static code can be reviewed, but solver semantics, numerical behavior, and the claimed test gate cannot be reproduced in a certified runtime here. A developer-specific or ignored installation is not a certification boundary.

**Remediation:** Publish a pinned OCI image by digest for certified runs and a generated multi-platform development lock. Persist interpreter, OS, architecture, BLAS, NumPy, SciPy, HiGHS, and locale/timezone identities in each run.

```dockerfile
FROM python:3.12.6-slim@sha256:<approved-digest>
ENV PYTHONHASHSEED=0 TZ=UTC LC_ALL=C.UTF-8
COPY requirements.lock /app/requirements.lock
RUN python -m pip install --no-deps --require-hashes -r /app/requirements.lock
COPY . /app
WORKDIR /app
ENTRYPOINT ["python", "-m", "dfs_cli"]
```

### F-47 — Contest-objective vocabulary is duplicated and lossy — **Technical Debt**

**File & line / function:** `skills/generate-lineups/scripts/build_slate.py:2786-2812`, six displayed postures; `mlb_engine/contest_shapes.py:49-62`, twelve shapes; `mlb_engine/field/ownership_prior.py:77-84`, ownership archetypes.  
**Evidence:** source-proven.

**Issue / root cause / failure mode:** Posture, contest shape, and ownership archetype are related but independently enumerated. Mappings are lossy and scattered. Reports can name one concept while the allocator/model uses another.

**Remediation:** Separate observed contest metadata from modeled objective/risk policy. Keep one explicit versioned mapping for display only.

```python
@dataclass(frozen=True)
class ContestObjective:
    utility: Literal["EXPECTED_NET", "LOG_BANKROLL", "MEAN_CVAR"]
    risk_aversion: float
    cvar_alpha: float | None
    field_model_ref: ArtifactRef
    payout_ref: ArtifactRef

    def validate(self) -> None:
        if self.utility == "MEAN_CVAR" and not (self.cvar_alpha and 0 < self.cvar_alpha < 1):
            raise ValueError("MEAN_CVAR requires alpha in (0, 1)")
```

### F-48 — The codebase has no exact contest-settlement engine in the optimization loop — **Blocker**

**File & line / function:** architecture-wide; `optimizer_v3.py` proxy objective, `contest_allocator.py` heuristic scores, `field_miner.py` historic rows, and reporting tools.  
**Evidence:** source-proven absence by repository-wide call and symbol search.

**Issue / root cause / failure mode:** There is no component that combines a simulated opponent field, all user entries in each contest, exact payout curve, rank ties, duplicates, and entry fees to generate exact scenario returns for complete contest assignment packages used by allocation. Without this, “EV” is neither computed nor optimized. Settling each user entry separately would also be wrong for multi-entry contests because the user's entries share ranks and tie groups.

**Remediation:** Implement exact vectorized settlement and verify it against hand-worked golden contests. A tie occupying ranks `r..r+k-1` splits the sum of those payout slots across the `k` tied entries; duplicates remain separate entries in that tie group.

```python
def settle_scores(scores: np.ndarray, payouts: np.ndarray, entry_fee: float) -> np.ndarray:
    """Return net dollars for one scenario; scores has one value per field/user entry."""
    order = np.argsort(-scores, kind="stable")
    sorted_scores = scores[order]
    gross = np.zeros(scores.shape[0], dtype=np.float64)
    start = 0
    while start < len(order):
        end = start + 1
        while end < len(order) and sorted_scores[end] == sorted_scores[start]:
            end += 1
        pool = payouts[start:min(end, len(payouts))].sum()
        gross[order[start:end]] = pool / (end - start)
        start = end
    return gross - entry_fee
```

### F-49 — The projection layer has no prospective calibration gate — **Blocker**

**File & line / function:** architecture-wide; `projection_builder.py`, calibration ledger, goldens, and optimizer inputs.  
**Evidence:** source-proven absence of an enforceable calibration artifact in the run gate.

**Issue / root cause / failure mode:** Historic analyses and factor reports exist, but a build does not require a temporally held-out model card showing calibration and predictive quality for means, tails, starts/workload, and joint dependence. In-sample fit or plausible components cannot support a maximum-EV claim.

**Remediation:** Train only on information available before each historic lock; produce prospective rolling-origin metrics; gate model promotion against declared baselines and uncertainty. Persist every split and prediction.

```python
@dataclass(frozen=True)
class CalibrationGate:
    evaluation_start: date
    evaluation_end: date
    slates: int
    mean_mae: float
    crps: float
    interval_80_coverage: float
    start_brier: float
    baseline_crps: float
    leakage_audit_passed: bool

    def passes(self, policy: CalibrationPolicy) -> bool:
        return (
            self.leakage_audit_passed
            and self.slates >= policy.min_slates
            and self.crps <= self.baseline_crps - policy.min_crps_improvement
            and abs(self.interval_80_coverage - 0.80) <= policy.max_coverage_error
        )
```

### F-50 — Automated DraftKings site interaction conflicts with the stated zero-touch target — **Security**

**File & line / function:** requested target architecture; proposed browser/headless discovery and submission; operational instructions.  
**Evidence:** current official platform terms, last checked 2026-08-27.

**Issue / root cause / failure mode:** Building a bot that logs in, scrapes, creates/edits lineups, enters contests, or uploads autonomously introduces account, compliance, credential, and irreversible-action risk. The current DraftKings terms expressly constrain automated scripts/third-party site interaction and impose rules for content-provider tools. Browser automation is therefore not a legitimate default implementation detail.

**Remediation:** End the certified computation at an immutable candidate delivery. Require an explicit human decision and manual upload, or a separately reviewed integration backed by written authorization and approved credentials. The system should make the boundary impossible to cross accidentally.

```python
class DeliveryBoundary:
    def prepare(self, artifact: ArtifactRef, verdict: RefereeVerdict) -> HumanHandoff:
        if verdict.state is not EvidenceState.PASS or verdict.subject_sha256 != artifact.sha256:
            raise DeliveryBlocked("artifact is not independently verified")
        return HumanHandoff(
            artifact=artifact,
            action="REVIEW_AND_UPLOAD_MANUALLY",
            automated_site_actions_allowed=False,
        )

    def submit_to_draftkings(self, *_: object) -> NoReturn:
        raise PermissionError("site submission is outside the authorized system boundary")
```

### 2.2 Defect priority and dependency order

The findings should not be implemented in numerical order. The dependency-aware priority is:

1. **Truth and delivery integrity:** F-10, F-11, F-14, F-24, F-31, F-34, F-43, F-46, F-50.
2. **One contract and immutable lifecycle:** F-01, F-20, F-21, F-22, F-26, F-33, F-44, F-45, F-47.
3. **Correct current algorithms:** F-03, F-06 through F-09, F-12, F-13, F-16, F-17, F-23, F-25, F-28, F-32, F-42.
4. **Replace the economic core:** F-18, F-30, F-35 through F-41, F-48, F-49.
5. **Throughput and maintainability:** F-02, F-05, F-19, F-27, F-29.

Fixing only group 1 can make delivery claims more truthful. It does not create EV. Fixing groups 1–3 creates a substantially safer heuristic engine. Only group 4, followed by prospective evaluation, addresses the primary objective.

### 2.3 Static review limitations

This is an exhaustive review of the active source surface at the named commit in the sense that every tracked production module and executable tool was inventoried, Python syntax was parsed, relevant entrypoints and call sites were traced, and current control/data flows were compared to the requested economic objective. It is not a dynamic proof of numerical correctness because the pinned scientific runtime was unavailable on this host. In particular:

- HiGHS status/incumbent behavior must be replayed under the certified SciPy version.
- Concurrency defects require multi-process stress tests.
- Vendor/API schema paths require frozen-response and live-authorized contract tests.
- EV, calibration, and throughput claims require held-out slates and exact settlement; none may be inferred from static analysis.

---

## Section 3: Target Greenfield Architecture & Implementation Specs

### 3.1 Non-negotiable design principles

1. **Evidence and values are different things.** Every material value has a state, source, observation time, effective time, schema, and immutable hash.
2. **Names never identify players.** Draftable role ID, person ID, game ID, contest ID, and entry ID are explicit and cannot be substituted for one another.
3. **One primary source per field, at most one approved fallback.** No averaging providers merely because they disagree; no silent fallback. A conflict is evidence.
4. **Legality is a contract, not scattered code.** Solver, renderer, and independent referee consume the same versioned rule artifact through separate implementations.
5. **A solver status describes only its implemented objective.** `OPTIMAL` never means profitable or globally maximum-EV unless the full economic objective and evidence are present.
6. **No unbounded operation.** Every network request, subprocess, solver call, queue wait, and retry loop has a deadline, a retry budget, and a terminal typed state.
7. **No ambient latest pointer in certification.** Every stage resolves inputs from content-addressed references in its own run manifest.
8. **Every stage is idempotent.** Same code, runtime, configuration, and input hashes produce the same artifact identities or a hard determinism failure.
9. **The final referee is independent and byte-bound.** It validates the exact delivered bytes after all mutation.
10. **Economic claims require prospective evidence.** Structural pass, legal construction, synthetic tests, or solver optimality are not EV certification.
11. **The authorized boundary is explicit.** The system may operate zero-touch through verified candidate delivery; DraftKings site interaction remains human-controlled absent written authorization.

### 3.2 Target repository layout

```text
dfs/
  cli.py                         # thin command router only
  contracts/
    evidence.py                  # typed states and freshness
    identity.py                  # person/draftable/game/contest/entry IDs
    roster.py                    # versioned Classic and Showdown contracts
    contest.py                   # payout and contest specifications
    artifacts.py                 # immutable artifact references
  artifacts/
    store.py                     # content-addressed storage
    index.py                     # transactional metadata / lineage
  sources/
    policies.yaml                # primary + one approved fallback per field
    draftkings.py
    lineups_primary.py
    lineups_fallback.py
    odds_primary.py
    weather_primary.py
    injuries_primary.py
    reconciliation.py
  models/
    workload.py                  # start, batting-order, PA/BF/IP distributions
    event_rates.py               # batter/pitcher/bullpen outcome rates
    ownership.py                 # contest-conditioned marginal model
    field_sampler.py             # complete opponent lineups
    registry.py                  # immutable observed-field database
    calibration.py               # rolling-origin metrics and gates
  simulation/
    game_simulator.py            # shared latent game and event simulation
    score_matrix.py              # S x P DraftKings scores
    settlement.py                # exact ranks, ties, payouts, fees
  optimize/
    candidate_classic.py         # verified Classic legality/column generator
    candidate_showdown.py        # verified Showdown legality/column generator
    portfolio.py                 # exact-entry joint optimizer
    late_swap.py                 # conditional re-optimizer
    solver.py                    # typed status/deadline interface
  pipeline/
    states.py                    # lifecycle FSM
    orchestrator.py              # bounded, idempotent stage coordination
    deadlines.py
  delivery/
    renderer.py                  # pure DK CSV renderer
    manifest.py                  # signed delivery record
  referee/                       # separately packaged/import-isolated
    parser.py
    legality.py
    bytes.py
    verdict.py
  reports/
    portfolio.py                 # views only; no policy decisions
    incidents.py
  tests/
    unit/
    property/
    mutation/
    replay/
    concurrency/
    chaos/
    economic_oracles/
  research/                      # cannot be imported by production package
  legacy/                        # immutable old code/evidence, no entrypoints
```

The CLI exposes a few verbs—`stage`, `build`, `swap`, `referee`, `deliver`, `settle`, `replay`—rather than one script per historical need. No CLI performs domain computation; it validates arguments, creates a run request, and calls the orchestrator.

### 3.3 Canonical typed contracts

The following contracts remove the repository's most damaging ambiguity.

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Generic, Literal, Mapping, TypeVar

class EvidenceState(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"
    STALE = "STALE"
    CONFLICTED = "CONFLICTED"
    NOT_APPLICABLE = "NOT_APPLICABLE"

T = TypeVar("T")

@dataclass(frozen=True)
class ArtifactRef:
    sha256: str
    byte_length: int
    media_type: str
    schema_version: str

    def __post_init__(self) -> None:
        if len(self.sha256) != 64 or any(c not in "0123456789abcdef" for c in self.sha256):
            raise ValueError("sha256 must be 64 lowercase hex characters")
        if self.byte_length < 0:
            raise ValueError("byte_length must be non-negative")

@dataclass(frozen=True)
class Evidence(Generic[T]):
    state: EvidenceState
    value: T | None
    source: str
    observed_at_utc: datetime
    effective_at_utc: datetime
    artifact: ArtifactRef
    reason: str = ""

    def require(self, *, max_age_s: float, now: datetime) -> T:
        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        if self.state is not EvidenceState.PASS or self.value is None:
            raise EvidenceBlocked(f"{self.source}: {self.state} {self.reason}")
        age = (now.astimezone(timezone.utc) - self.observed_at_utc.astimezone(timezone.utc)).total_seconds()
        if age < 0 or age > max_age_s:
            raise EvidenceBlocked(f"{self.source}: evidence age {age:.0f}s exceeds {max_age_s:.0f}s")
        return self.value

@dataclass(frozen=True)
class PersonId:
    value: int

@dataclass(frozen=True)
class DraftableRole:
    draftable_id: int
    person_id: PersonId
    mode: Literal["CLASSIC", "SHOWDOWN"]
    slot_role: str
    team: str
    game_id: str
    salary: int
    eligible_positions: frozenset[str]
```

Policy uses a complete state table. There is no generic truthiness:

| State | May feed model? | May certify delivery? | Required action |
|---|---:|---:|---|
| `PASS` | Yes | Yes, if fresh and exact-scope | Continue |
| `NOT_APPLICABLE` | Only with declared neutral semantics | Yes | Preserve state and reason |
| `UNKNOWN` | Only in an explicitly degraded research run | No | Approved fallback or stop |
| `STALE` | No | No | Refresh or stop |
| `CONFLICTED` | No | No | Deterministic reconciliation or stop |
| `FAIL` | No | No | Stop |

### 3.4 Immutable artifact store and run identity

Every raw input and derived output is written by content hash. A run manifest is also immutable and contains no unresolved filesystem paths.

```python
@dataclass(frozen=True)
class RunIdentity:
    run_id: str
    code: ArtifactRef
    runtime: ArtifactRef
    configuration: ArtifactRef
    request: ArtifactRef
    seed: int

@dataclass(frozen=True)
class StageRecord:
    stage: str
    state: EvidenceState
    inputs: tuple[ArtifactRef, ...]
    outputs: tuple[ArtifactRef, ...]
    started_at_utc: datetime
    finished_at_utc: datetime
    reason: str

class ArtifactStore:
    def put(self, *, media_type: str, schema_version: str, payload: bytes) -> ArtifactRef:
        digest = hashlib.sha256(payload).hexdigest()
        target = self.root / digest[:2] / digest[2:]
        if not target.exists():
            atomic_write_bytes(target, payload)
        elif target.read_bytes() != payload:
            raise ArtifactCollision(digest)
        return ArtifactRef(digest, len(payload), media_type, schema_version)

    def get(self, ref: ArtifactRef) -> bytes:
        payload = (self.root / ref.sha256[:2] / ref.sha256[2:]).read_bytes()
        if len(payload) != ref.byte_length or hashlib.sha256(payload).hexdigest() != ref.sha256:
            raise ArtifactCorruption(ref.sha256)
        return payload
```

The transactional index stores lineage, stage uniqueness, delivery bindings, and supersession edges. The bytes remain useful even if the index is rebuilt.

### 3.5 Source acquisition and reconciliation

Each modeled field declares its source policy in data, for example:

```yaml
schema_version: source_policy.v1
fields:
  dk_player_pool:
    primary: user_supplied_dk_salary_csv
    fallback: null
    max_age_seconds: 86400
  confirmed_lineup:
    primary: licensed_lineup_provider_a
    fallback: licensed_lineup_provider_b
    max_age_seconds: 180
    conflict_policy: block
  market_total:
    primary: licensed_odds_consensus
    fallback: licensed_sportsbook_feed
    max_age_seconds: 300
    conflict_policy: block_if_probability_delta_gt_0_04
  weather:
    primary: licensed_weather_feed
    fallback: official_venue_status
    max_age_seconds: 600
    conflict_policy: block_if_roof_or_ppd_state_differs
```

Acquisition rules:

- Requests use connect/read/total deadlines, a descriptive user agent where allowed, capped response bytes, retry only for declared transient failures, exponential backoff with jitter, and a circuit breaker.
- Raw response bytes and normalized records are both retained. The normalized artifact cites the raw hash and parser schema.
- Schema drift creates `UNKNOWN_SCHEMA`; no “best effort” field rearrangement enters production.
- The fallback is invoked only when the primary is unavailable under policy. Both are never averaged unless the field policy explicitly defines a statistical multi-book consensus such as odds.
- Disagreement beyond policy produces `CONFLICTED`; an LLM may explain the diff but cannot clear it.
- Slate scope is reconciled by stable game/team/time keys before team-level data is merged. Doubleheader leg is explicit.

The adapter interface is intentionally small:

```python
class SourceAdapter(Protocol[T]):
    source_name: str
    schema_version: str

    def fetch(self, request: SourceRequest, deadline: Deadline) -> RawResponse: ...
    def parse(self, raw: RawResponse) -> Evidence[T]: ...

def acquire(policy: FieldSourcePolicy[T], request: SourceRequest, deadline: Deadline) -> Evidence[T]:
    primary = bounded_attempt(policy.primary, request, deadline.child(policy.primary_budget_s))
    if primary.state is EvidenceState.PASS:
        return primary
    if policy.fallback is None or not policy.allows_fallback(primary.state):
        return primary
    fallback = bounded_attempt(policy.fallback, request, deadline.child(policy.fallback_budget_s))
    return fallback.with_reason(f"approved fallback after primary state={primary.state}")
```

### 3.6 Probabilistic player and game model

#### Workload first

For every scenario `s`, sample active/starting state before performance:

- Hitter: `start`, batting slot, home/away, plate appearances, pinch-hit/removal probability.
- Starter: start probability, batters faced / innings / pitch-count distribution, earned-run and win/quality-start opportunities.
- Reliever/bullpen: shared game run-prevention effects needed for opponent hitter distribution.

Model uncertainty must include parameter uncertainty, not only outcome noise. A lineup scratched with 20% probability is not represented by multiplying its mean by 0.8; the scenario matrix must contain discrete inactive outcomes so tail and correlation effects survive.

#### Joint event simulation

One acceptable initial design is hierarchical Monte Carlo:

```text
scenario
  -> weather/roof and run-environment latent variables by game
  -> starter availability/workload and bullpen path
  -> team offensive latent state
  -> batter starts/order/PA
  -> PA outcomes conditional on batter, pitcher hand/quality, park, weather
  -> baseball counting events
  -> exact DraftKings scoring by person
```

Pitcher strikeouts and opposing hitter contact/outcomes must share events or latent factors; team batters share run environment and lineup turnover. Independent normal draws per player are not an acceptable production joint distribution.

The output is a memory-mapped or chunked `float32` matrix `scores[S, P]` plus active/workload matrices and full artifact lineage. Classic and Showdown consume the same person outcomes. Showdown applies `1.5x` fantasy scoring to the captain through the role incidence matrix; it does not simulate a second captain person.

#### Calibration

Use rolling-origin evaluation: for slate date `t`, train only on artifacts whose effective/observed times precede lock at `t`. Required diagnostics include:

- start/active Brier score and reliability;
- PA/BF/IP distribution calibration;
- player mean MAE and bias by role/salary/team total;
- CRPS or log score for full distributions;
- 50/80/95% interval coverage and sharpness;
- cross-player covariance and game/team tail co-occurrence;
- top percentile hit rates;
- comparison against APPG and a simple shrinkage baseline.

Promotion requires enough independent slates, predeclared thresholds, leakage audit, and no material subgroup regression. Metrics and thresholds must be chosen before looking at the candidate result.

### 3.7 Contest-conditioned field model

The field model predicts **complete legal lineups**, not independent player Bernoulli selections.

Inputs:

- `ContestSpec` and time-to-lock;
- public/market projection and ownership features frozen as of lock;
- salary/position/role pool and slate topology;
- historic immutable observations matched to context;
- user-segment mixture if supportable without identity leakage.

Initial implementation:

1. Predict contest-conditioned player/captain ownership marginals with calibrated intervals.
2. Predict construction distributions: salary bins, Classic stack shapes, pitcher pair patterns, Showdown captain/team composition, opposing-player rules, and value concentration.
3. Sample a mixture component/archetype.
4. Sample a legal lineup using sequential importance sampling or a stochastic MILP with Gumbel/perturbed utilities.
5. Reweight/calibrate the generated population to target marginals and construction moments.
6. Validate the full generated field and record deviations.

```python
@dataclass(frozen=True)
class FieldCalibration:
    ownership_mae: float
    pairwise_mae: float
    stack_shape_total_variation: float
    salary_wasserstein: float
    captain_mae: float | None
    duplicate_count_error: float

def validate_generated_field(field: Sequence[Lineup], target: FieldTargets, policy: FieldPolicy) -> FieldCalibration:
    metrics = compute_field_calibration(field, target)
    if metrics.ownership_mae > policy.max_ownership_mae:
        raise FieldModelRejected("ownership marginal calibration failed")
    if metrics.stack_shape_total_variation > policy.max_stack_tv:
        raise FieldModelRejected("construction distribution failed")
    return metrics
```

No individual historical username is required in the production objective. Aggregate, privacy-preserving behavior is sufficient; the field model should not overfit sparse identities.

### 3.8 Candidate generation formulations

Candidate generation produces columns for the portfolio optimizer. It uses multiple scenario-aware objectives to increase recall; it does not assign an economic value until settlement.

#### Classic legality

Let `x[p,k]` be binary if person `p` occupies slot `k`. Let `z[p]` indicate selection. The canonical contract supplies eligible slot set `E[p]`, salary `c[p]`, team `t[p]`, game `g[p]`, and pitcher/hitter role.

```text
for every slot k:                  sum_p x[p,k] = 1
for every player p:                sum_k x[p,k] = z[p] <= 1
eligibility:                       x[p,k] = 0 if k not in E[p]
roster size:                       sum_p z[p] = 10
salary:                            floor <= sum_p c[p] z[p] <= 50,000
team maximum:                      sum_{p:t[p]=T} z[p] <= contract limit
locked/excluded:                   z[p] = 1 / 0 as applicable
pitcher-versus-hitter rule:        contract-specific linear constraints
optional stack proposal:           linear shape constraint, not universal EV truth
duplicate exclusion for old row L: sum_{p in L} z[p] <= 9
```

Position eligibility is attached to `x[p,k]`; counting `z[p]` by a single primary position is insufficient for multi-position players. Every returned incumbent is reconstructed by slots and independently checked.

#### Showdown legality

Let `c[p]` and `u[p]` indicate captain and utility selection:

```text
sum_p c[p] = 1
sum_p u[p] = 5
c[p] + u[p] <= 1 for every person
sum_p (cpt_salary[p] * c[p] + util_salary[p] * u[p]) <= 50,000
team-composition constraints from the versioned contract
locks/exclusions by person and role
```

The DraftKings CSV may contain separate role rows and may already encode captain salary. The solver maps both to one `person_id` and uses the exact bound role salaries (`cpt_salary`, `util_salary`) from the staged salary artifact; it never applies a second multiplier to an already multiplied salary. The contract supplies the captain fantasy-score multiplier. Exposure is counted by person or by captain role according to the named rule.

#### Scenario-aware proposal objectives

For scenario subset `Q`, player scores `A[q,p]`, and roster selection `z[p]`, useful column-generation objectives include:

- maximize mean plus a sampled scenario perturbation;
- maximize a selected upper quantile via auxiliary variables;
- find rosters with positive reduced cost from the master portfolio problem;
- minimize distance from undercovered construction regions;
- generate solutions under bootstrap draws of model parameters.

All objectives must be labeled. A “ceiling” proposal is a proposal strategy, not a statement of expected profit.

Typed solver wrapper:

```python
@dataclass(frozen=True)
class SolverRequest:
    model_sha256: str
    time_limit_s: float
    mip_relative_gap: float
    seed: int

@dataclass(frozen=True)
class SolverResult:
    state: SolveState
    incumbent: tuple[int, ...] | None
    objective: float | None
    bound: float | None
    relative_gap: float | None
    runtime_s: float
    solver_message: str

def accept_incumbent(result: SolverResult, validator: Callable[[tuple[int, ...]], None]) -> tuple[int, ...]:
    if result.state not in {SolveState.OPTIMAL, SolveState.FEASIBLE_LIMIT} or result.incumbent is None:
        raise NoUsableIncumbent(result.state)
    validator(result.incumbent)
    return result.incumbent
```

### 3.9 Vectorized exact settlement

For simulation `s`, concatenate `F` sampled field entries with `U` proposed user entries. If player score matrix is `P_s` and lineup incidence is `L`, lineup score is matrix multiplication `L @ P_s`. For Showdown, captain incidence already carries the scoring multiplier.

For every equal-score tie group occupying ranks `a..b`, gross payout per entry is:

```text
gross = (payout[a] + payout[a+1] + ... + payout[b]) / (b - a + 1)
net   = gross - entry_fee
```

Duplicate lineups remain separate field entries. They naturally tie and split occupied payout slots; there is no ad hoc “duplication penalty.” This is the correct way to price duplication.

The settlement engine should operate in scenario chunks to cap memory:

```python
def single_entry_candidate_returns(
    player_scores: np.ndarray,        # S x P
    field_incidence: np.ndarray,      # F x P
    user_incidence: np.ndarray,       # C x P
    payouts: np.ndarray,
    entry_fee: float,
    *, chunk_size: int = 512,
) -> np.ndarray:                      # S x C; screening or one user entry per contest only
    out = np.empty((player_scores.shape[0], user_incidence.shape[0]), dtype=np.float32)
    for start in range(0, player_scores.shape[0], chunk_size):
        stop = min(start + chunk_size, player_scores.shape[0])
        scores = player_scores[start:stop]
        field_scores = scores @ field_incidence.T
        candidate_scores = scores @ user_incidence.T
        for row in range(stop - start):
            for candidate in range(user_incidence.shape[0]):
                combined = np.concatenate((field_scores[row], candidate_scores[row, candidate:candidate + 1]))
                out[start + row, candidate] = settle_scores(combined, payouts, entry_fee)[-1]
    return out
```

The inner reference implementation above is deliberately clear. It evaluates candidates one at a time against the opponent field, so it is appropriate for screening or a contest containing one user entry. The production implementation should group/sort candidates in vectorized or compiled chunks, but it must match this oracle within declared float tolerance on randomized tests. Multi-entry portfolios must use the joint contest-package settlement in the next section so the user's own entries share ranks and ties correctly.

### 3.10 Joint portfolio and contest allocation

Multiple user entries in the same contest compete with one another and can join the same tie group. Therefore net return is **not generally additive by entry-lineup pair**. A tensor `R[s,e,l]` computed by inserting one user entry at a time is valid for single-entry contests and candidate screening, but it is not an exact 20-max/150-max portfolio objective.

The exact linear master uses complete within-contest assignment packages:

- `C` is the set of exact contests;
- `E_c` is the user's reserved entries in contest `c`;
- `Q_c` is a set of feasible packages, where one package assigns a legal lineup to every entry in `E_c`;
- `y[c,q]` is binary and selects package `q` for contest `c`;
- `R[s,c,q]` is total net return after scenario `s` settles the sampled opponent field **and every user entry in package `q` together**;
- `a[c,q,p]` is the package's person/captain/game exposure attribute;
- `w_s` is scenario probability.

The opponent sampler generates `field_size - len(E_c)` entries for contest `c`; exact settlement then combines those opponents with all lineups in the package. This preserves own-entry cannibalization, duplicate ties, and payout-slot sharing.

Master constraints and scenario return:

```text
for each contest c:                sum_{q in Q_c} y[c,q] = 1
person/captain/game limits:        sum_c sum_q a[c,q,p] y[c,q] <= scoped limit
capital-weighted limits:           use package exposures weighted by contest fees
cross-contest lineup reuse:        package attributes enforce declared policy

Z_s = sum_c sum_q R[s,c,q] y[c,q]
```

For a single user entry, a package is simply a lineup choice. For a multi-entry contest, packages can be generated by a nested assignment/pricing problem, large-neighborhood search, or complete enumeration when small. The package generator evaluates every proposal with exact joint settlement. Column generation stops only under a declared bound/stability rule. If `Q_c` is restricted, the solver result is “optimal within the generated package set,” never a global maximum-EV claim.

Three supported objectives:

1. **Expected net:** maximize `sum_s w_s Z_s`.
2. **Mean-CVaR:** maximize `E[Z] - lambda * CVaR_alpha(loss)` using standard linear auxiliary variables.
3. **Expected log bankroll:** maximize `sum_s w_s log(B + Z_s)` through a validated piecewise-linear concave approximation, with `B + Z_s > 0` enforced.

Mean-CVaR linearization for loss `-Z_s`:

```text
u_s >= -Z_s - eta
u_s >= 0
CVaR_alpha = eta + (1 / (1 - alpha)) * sum_s w_s u_s
maximize sum_s w_s Z_s - lambda * CVaR_alpha
```

The user/product owner chooses utility and bankroll/risk policy explicitly. There is no universal “maximum EV lineup portfolio” independent of risk tolerance, contest inventory, and capital.

Implementation interface:

```python
@dataclass(frozen=True)
class ContestPackage:
    package_id: str
    contest_id: str
    assignments: tuple[Assignment, ...]
    person_counts: Mapping[PersonId, int]
    captain_counts: Mapping[PersonId, int]
    game_counts: Mapping[str, int]

@dataclass(frozen=True)
class PortfolioProblem:
    contests: tuple[ContestSpec, ...]
    packages_by_contest: Mapping[str, tuple[ContestPackage, ...]]
    net_returns: "NDArray[np.float32]"  # S x Q, each column is an exact contest package
    scenario_weights: "NDArray[np.float64]"
    objective: ContestObjective
    policy: PortfolioPolicy

@dataclass(frozen=True)
class PortfolioSolution:
    assignments: tuple[Assignment, ...]
    solve: SolverResult
    expected_net: float
    probability_profit: float
    cvar: float
    exposure_audits: tuple[ConstraintAudit, ...]
    model_uncertainty: Mapping[str, float]

def solve_portfolio(problem: PortfolioProblem) -> PortfolioSolution:
    validate_problem(problem)
    model, package_variables = build_package_master_milp(problem)
    raw = solve_bounded(model, problem.policy.solver_request)
    selected = accept_incumbent(raw, lambda x: validate_package_indices(problem, x))
    solution = materialize_solution(problem, selected, raw)
    independently_validate_solution(problem, solution)
    return solution
```

If the `S x Q` matrix is too large, use scenario decomposition, sample-average approximation with an untouched validation scenario set, dominated-package pruning, and iterative package generation. Exact within-contest settlement is never replaced by unreported additive or positional assignment.

### 3.11 Late swap as conditional portfolio optimization

At decision time `t`:

1. Hash and parse the exact currently uploaded CSV or the last delivered artifact.
2. Determine locks from a complete, timezone-aware game clock and current DraftKings rules.
3. Freeze locked slot/person assignments and actual points/events already realized.
4. Refresh only authorized evidence with `observed_at <= t` and retain prior/current artifacts.
5. Re-simulate remaining outcomes conditional on realized game state when supported; otherwise record the approximation.
6. Re-sample remaining opponent roster uncertainty and contest returns.
7. Jointly re-optimize all swappable entries under exact locked-slot constraints.
8. Render a candidate CSV, compute exact byte hash, run the independent referee, and create a superseding delivery record.
9. Present the artifact for human review/upload. Never interact with the site automatically by default.

Swap invariants:

```python
def assert_swap_authority(before: EntryLineup, after: EntryLineup, clock: SlateClock) -> None:
    if before.entry_id != after.entry_id or before.contest_id != after.contest_id:
        raise SwapViolation("entry/contest identity changed")
    for slot_before, slot_after in zip(before.slots, after.slots, strict=True):
        if clock.is_locked(slot_before.game_id) and slot_before.draftable_id != slot_after.draftable_id:
            raise SwapViolation(f"locked slot changed: {slot_before.slot}")
    roster_contract(before.mode).assert_legal(after)
```

### 3.12 Lifecycle state machine

The orchestration flow is a finite state machine, not an open-ended agent loop:

```text
REQUESTED
  -> SNAPSHOTTED
  -> RECONCILED
  -> MODELED
  -> SIMULATED
  -> FIELD_GENERATED
  -> CANDIDATES_GENERATED
  -> ALLOCATED
  -> RENDERED_CANDIDATE
  -> REFEREED
  -> DELIVERED_FOR_HUMAN_REVIEW

Any stage -> BLOCKED_EVIDENCE | FAILED | TIMED_OUT | CANCELLED
```

Permitted transitions are data, and every transition commits atomically with its artifacts:

```python
ALLOWED: dict[RunState, frozenset[RunState]] = {
    RunState.REQUESTED: frozenset({RunState.SNAPSHOTTED, RunState.FAILED}),
    RunState.SNAPSHOTTED: frozenset({RunState.RECONCILED, RunState.BLOCKED_EVIDENCE, RunState.FAILED}),
    RunState.RECONCILED: frozenset({RunState.MODELED, RunState.BLOCKED_EVIDENCE, RunState.FAILED}),
    # ...all states enumerated; no wildcard transition...
    RunState.REFEREED: frozenset({RunState.DELIVERED_FOR_HUMAN_REVIEW, RunState.FAILED}),
}

def transition(index: RunIndex, run_id: str, expected: RunState, new: RunState, record: StageRecord) -> None:
    if new not in ALLOWED[expected]:
        raise InvalidTransition(f"{expected} -> {new}")
    index.compare_and_swap_state(run_id, expected=expected, new=new, stage_record=record)
```

Retries happen only inside an individual idempotent acquisition/computation stage. Retry policy includes `max_attempts`, allowed exception classes/status codes, elapsed deadline, and backoff cap. `UNKNOWN`, `CONFLICTED`, schema errors, illegal roster, and deterministic data errors are not retryable.

### 3.13 Deadlines, throughput, and concurrency

The run has a monotonic outer deadline. Each child receives `min(stage_budget, remaining_outer_time)`. No child can extend the parent.

```python
@dataclass(frozen=True)
class Deadline:
    expires_monotonic: float

    @classmethod
    def after(cls, seconds: float) -> "Deadline":
        if not math.isfinite(seconds) or seconds <= 0:
            raise ValueError("deadline seconds must be finite and positive")
        return cls(time.monotonic() + seconds)

    def remaining(self) -> float:
        return max(0.0, self.expires_monotonic - time.monotonic())

    def child(self, budget_s: float) -> "Deadline":
        return Deadline(min(self.expires_monotonic, time.monotonic() + budget_s))

    def require_time(self) -> None:
        if self.remaining() <= 0:
            raise DeadlineExceeded
```

Performance rules:

- Parse and normalize tabular data in vectorized column operations after strict schema validation. Small control-flow loops are clearer and not a problem; do not “vectorize” I/O or policy for style.
- Represent player/lineup membership with sparse matrices or packed bitsets.
- Use matrix multiplication for scenario lineup scores; chunk by scenarios/contests to bound memory.
- Precompute eligibility and conflict bitsets before solver construction.
- Parallelize independent game simulations and candidate proposal jobs with a fixed worker count and process-level memory budget.
- Keep one writer/transaction owner for the metadata index; workers return immutable artifacts.
- Cache only by complete input/code/runtime/configuration identity.
- Emit stage latency, queue time, peak RSS, solver gap/status, cache hit, and artifact sizes.

Initial SLOs are hypotheses to benchmark, not current claims:

| Stage | Proposed deadline | Failure behavior |
|---|---:|---|
| Local schema/identity/referee checks | 5–30 seconds depending on portfolio size | Hard fail, no retry |
| Individual source request | 3s connect / 10s read / 15s total | Approved fallback or block |
| Individual candidate MILP | 2–10 seconds | Accept verified incumbent as `FEASIBLE_LIMIT` or continue bounded proposals |
| Joint portfolio MILP | 30–120 seconds | Verified incumbent with reported gap or block per policy |
| Full pre-lock refresh/build | Benchmark target under 5 minutes | Outer timeout, retain evidence, do not deliver |
| Late-swap refresh/build | Benchmark target under 90 seconds | Outer timeout, leave prior delivery untouched |

These budgets must be validated on representative large slates and contest portfolios before becoming contractual.

### 3.14 Independent final-byte referee

The referee runs in a separate package/process and receives only immutable references. It does not import optimizer modules. It performs:

1. Exact byte hash/length check and encoding/newline policy.
2. CSV header/row count/order preservation against the entry template.
3. Entry ID and contest ID one-to-one identity.
4. Mode detection from bound contract and salary geometry—never filename.
5. Draftable ID lookup against exact salary bytes.
6. Slot eligibility, uniqueness by person, salary, team, pitcher/hitter, and Showdown multiplier checks.
7. Locked-slot equivalence for late swap.
8. Required exposure/portfolio policy postvalidation.
9. No blanks in authorized reserved rows and no changes outside them.
10. Manifest/run/salary/template/code/runtime hash binding.
11. Re-read after any copy/rename and verify the delivered path still has the same bytes.

Verdict contract:

```python
@dataclass(frozen=True)
class RefereeVerdict:
    schema_version: str
    state: EvidenceState
    subject_sha256: str
    salary_sha256: str
    entries_template_sha256: str
    roster_contract_sha256: str
    checks: tuple[CheckResult, ...]
    referee_code_sha256: str
    runtime_sha256: str

    def assert_deliverable(self) -> None:
        if self.state is not EvidenceState.PASS:
            raise DeliveryBlocked(self.state)
        failed = [x for x in self.checks if x.state is not EvidenceState.PASS]
        if failed:
            raise DeliveryBlocked(f"non-pass referee checks: {[x.name for x in failed]}")
```

The renderer is pure: `(entry_template_bytes, assignments, contract) -> bytes`. The referee reparses those bytes. In-memory DataFrames are never accepted as delivery evidence.

### 3.15 Cowork-native skill specification

The skill should be a thin operator interface to the deterministic lifecycle. It should not contain hundreds of lines of copied policy or ask an LLM to choose lineup mathematics.

```markdown
---
name: generate-mlb-lineups
description: Build or refresh a governed DraftKings MLB Classic or Showdown candidate delivery.
---

# Generate MLB lineups

Use this skill when the user asks to stage, build, refresh, late-swap, referee, or deliver an MLB slate.

1. Preserve the supplied DK salary and entry files exactly; stage them through `dfs stage`.
2. Read `references/classic.md`, `references/showdown.md`, or `references/late-swap.md` only for the requested mode.
3. Run `dfs build --request <artifact-id>` or `dfs swap --request <artifact-id>`. Do not reproduce solver or CSV logic in the agent.
4. Surface typed evidence blockers exactly. Do not reinterpret UNKNOWN, STALE, or CONFLICTED as PASS and do not invent a fallback.
5. A solver OPTIMAL result refers only to its declared objective. Report EV only when the delivery manifest contains passing calibration, field-model, settlement, and portfolio-economic gates.
6. Run `dfs referee --delivery <artifact-id>` and show the exact final SHA-256.
7. Stop at the human review/upload boundary. Never automate DraftKings site actions without an explicitly approved integration.
```

Tool surface:

| Tool | Input | Output | Agent judgment allowed? |
|---|---|---|---:|
| `dfs_stage` | local DK files + requested rows | immutable request ID | No |
| `dfs_status` | request/run ID | typed state and blockers | No reinterpretation |
| `dfs_build` | request ID + objective policy ID | run ID | No hidden controls |
| `dfs_swap` | prior delivery ID + current evidence policy | run ID | No lock override |
| `dfs_referee` | delivery candidate ID | verdict ID | No |
| `dfs_report` | run/delivery ID | human-readable report | Explanation only |

The agent loop is bounded: submit once, poll at a capped interval until terminal or outer deadline, then report. A terminal blocker ends the loop. There is no multi-agent debate during a live slate.

### 3.16 Browser and live-data design

Preferred order:

1. Licensed/approved structured API.
2. User-supplied official file.
3. Approved headless fetch of a public source if terms and robots/policy allow it.
4. Human paste/screenshot quarantine for recovery.

Browser/LLM extraction may create a `candidate_observation` containing raw HTML/screenshot hash, parsed value, selector/extraction explanation, and `UNKNOWN` state. A deterministic reconciler must match identity/scope/schema and promote it to usable evidence. Signed-in browser sessions, credential storage, lineup creation/edit, contest entry, and upload remain outside the default system.

### 3.17 Testing and verification strategy

#### Unit and contract tests

- Every parser: valid, missing column, duplicate column, wrong encoding, CP1252, blank/NaN, oversized value, reordered columns, provider schema drift.
- Every fraction/deadline: booleans, strings, infinities, NaN, negative, zero boundary, >1.
- Every identity: role duplicate, name collision, team alias, doubleheader, traded player, same-name players.
- Every solver state: optimal, feasible limit with valid incumbent, limit without incumbent, infeasible, unbounded, numerical error.

#### Property and metamorphic tests

- Permuting input rows does not change canonical artifacts/solutions under the same seed.
- Increasing a salary cannot make an otherwise identical roster cheaper.
- Removing a player cannot introduce that player into a solution.
- Changing only Showdown captain must change lineup identity and scenario scores.
- Duplicating a field entry affects tie splitting exactly as a second entry should.
- Adding a zero-payout rank cannot increase a tied group's payout.
- A stricter cap cannot be reported as less binding without a corresponding portfolio change.

Use Hypothesis or an equivalent property framework, plus mutation testing. A test for a cap must fail when that exact constraint is deleted.

#### Economic oracles

Create tiny hand-enumerable contests:

- 2–8 legal lineups;
- 3–20 field entries;
- explicit scenario probabilities;
- ties, duplicate lineups, flat/top-heavy payouts, and multiple contests;
- brute-force enumeration of every assignment.

The MILP must match the brute-force optimal utility and assignment set within declared tolerance. These tests prove formulation correctness, not real-world edge.

#### Replay and prospective gates

- Freeze full pre-lock artifacts and settlement data.
- Replay without network access in the certified runtime.
- Compare exact artifact hashes when determinism is expected.
- Evaluate predictions only against future results unavailable at build time.
- Maintain a final untouched holdout season/slate range for architecture decisions.
- Report survivorship, missing-data, contest-selection, and user-selection biases.

#### Chaos and concurrency

- Kill a writer between temp write and replace.
- Run two field ingestions and two deliveries simultaneously.
- Hang solver and subprocess children.
- Return truncated HTTP, slow streaming, 429/500, wrong content type, and schema change.
- Move the system clock/timezone while using monotonic deadlines.
- Exhaust disk quota and verify no delivery status becomes `PASS`.
- Crash after referee and before delivery-index commit; restart must resume idempotently.

### 3.18 Observability and incident behavior

Every run emits structured events with `run_id`, `stage`, monotonic elapsed time, artifact hashes, code/runtime identities, and typed state. Do not log CSV bodies, credentials, cookies, or provider secrets.

Required counters/histograms:

- source latency/state/fallback use by field/provider;
- schema drift and identity collision counts;
- scenario generation rate and memory high-water mark;
- candidate jobs pruned/launched/cached;
- solver state, bound, incumbent, gap, duration;
- field calibration and settlement dimensions;
- portfolio expected net, risk metrics, and policy utility cost;
- referee check states and delivery hash;
- late-swap time remaining at every stage.

Alerts are deterministic. The engine never asks an LLM to decide whether to keep retrying. On a non-retryable or deadline failure it preserves current evidence, marks the run terminal, and leaves the prior delivery untouched.

### 3.19 Cost controls

The dominant production cost should be local simulation/optimization, not tokens.

- Keep LLM calls off the normal slate path.
- Deduplicate provider requests by field/scope/as-of key.
- Store raw and normalized artifacts once by hash.
- Use cheap analytic/bitset feasibility before MILP.
- Reuse scenario and field artifacts across contests only when their complete conditioning inputs match.
- Share person outcome simulations across Classic/Showdown on the same exact games, then apply mode-specific role matrices.
- Use successive fidelity: small scenario set for candidate proposals, independent larger scenario set for ranking/portfolio selection, untouched evaluation scenarios for final estimates.
- Measure marginal value of more scenarios/candidates; stop when uncertainty and solution stability meet policy rather than using a fixed oversized loop.

### 3.20 Implementation sequence and exit gates

#### Phase 0 — Freeze and measure the current baseline

**Work:** preserve current head, current raw/golden fixtures, current outputs, current heuristic objective, and performance measurements in the pinned runtime. Establish an immutable replay corpus.  
**Exit gate:** every representative Classic/Showdown build can be reproduced or is explicitly labeled non-reproducible; current claims are cataloged.

#### Phase 1 — Contracts, artifacts, referee, and hermetic runtime

**Work:** implement typed evidence/identity/roster/contest/artifact contracts; content-addressed store; transactional index; cross-platform development lock; certified container; standalone referee. Repair F-01 through F-05, F-10, F-11, F-14, F-20 through F-28, F-31 through F-34, and F-43 through F-47 where still relevant.  
**Exit gate:** exact-byte golden deliveries pass in the container; corrupt/missing/wrong-salary inputs fail; concurrent writers cannot lose data; every child timeout is terminal and recorded.

#### Phase 2 — Source evidence and identity

**Work:** one adapter per provider, source-policy registry, bounded requests, doubleheader/game identity, unified aliases, collision-safe joins, immutable normalized observations.  
**Exit gate:** frozen schema-change/conflict/staleness cases reach the correct typed state; no name-only join can enter production; every live value is traceable to raw bytes.

#### Phase 3 — Probabilistic projection model

**Work:** workload/start distributions, event-rate model, joint game simulator, exact DK scoring, calibration pipeline, leakage audit. Keep APPG/factor chain as baselines.  
**Exit gate:** predeclared rolling-origin calibration thresholds beat approved baselines across Classic/Showdown-relevant subgroups; uncertainty is propagated into scenarios.

#### Phase 4 — Field generator and settlement

**Work:** normalized contest observation database, contest-conditioned ownership/construction models, legal field sampler, exact vectorized ties/duplicates/payout engine.  
**Exit gate:** full-field calibration thresholds pass on held-out contests; settlement matches hand-worked and brute-force goldens.

#### Phase 5 — Candidate and joint portfolio optimization

**Work:** extract verified roster kernels, scenario-aware column generation, exact-entry return matrices, expected-net/mean-CVaR/log-bankroll objectives, capital-aware limits, solver-state handling. Delete sequential production thesis/posture allocation.  
**Exit gate:** tiny economic oracles match brute force; large replays satisfy legality and gap/deadline policy; constrained utility cost is reported.

#### Phase 6 — Conditional late swap and operations

**Work:** locked-state reconstruction, conditional simulations, opponent remaining-roster uncertainty, joint swap optimizer, final-byte referee, state-machine supervisor, metrics and incident controls.  
**Exit gate:** chaos tests prove bounded completion and prior-delivery preservation; a representative late-swap workload meets the validated latency budget.

#### Phase 7 — Prospective shadow and limited launch

**Work:** run without entry submission over a predeclared future sample; compare predicted distribution/EV to realized settlement; investigate drift; complete legal/platform review.  
**Exit gate:** calibration and economic error bars meet declared thresholds; no critical integrity incident; the authorized human upload boundary is documented. Positive realized ROI alone is insufficient because variance and selection bias can dominate small samples.

### 3.21 Deletion and migration plan

Do not delete evidence during implementation. The controlled sequence is:

1. Copy current head and raw archives into an immutable legacy tag/store with hashes.
2. Build greenfield modules beside the old system and replay both against the same staged artifacts.
3. Mark every old entrypoint `legacy_only` and refuse new production runs through it after the replacement gate passes.
4. Remove duplicated policy/constants only after both new solver and referee consume the versioned contract and goldens pass.
5. Move thesis/posture allocators, factor-chain projection, scratch scripts, and old prompts to `legacy/` as baselines/history.
6. Delete an old module only after its output/side effects are either intentionally retired or covered by a new contract test.

Suggested burn-down:

| Legacy surface | Replacement condition | Final action |
|---|---|---|
| `showdown_theses.py` production path | Joint Showdown portfolio oracle and replay gates pass | Remove from production imports; retain benchmark snapshot |
| `posture_allocator.py` production path | Exact settlement/portfolio optimizer passes | Retain only as challenger |
| `projection_builder.py` production model | Probabilistic model calibration gate passes | Retain factor baseline in research |
| `build_slate.py` monolith | Thin `dfs` CLI covers both modes | Delete executable logic after parity window |
| Mutable JSON registries/manifests | Transactional store and rebuild command proven | Freeze old files; generate compatibility views only |
| `audit.py` partial cache | Hermetic task/result manifest passes CI/replay | Retire shared `.audit_gate` state |
| Large current instruction docs | Short router plus progressive references validated | Archive history; stop loading by default |

### 3.22 Definition of done

The replacement is not done when it emits legal CSVs. It is done only when all of the following are true:

- Exact salary, entry template, live evidence, model, field, payout, code, runtime, configuration, seed, and final bytes have immutable references.
- Classic and Showdown share person identity, scenario outcomes, roster contract concepts, contest specification, portfolio optimizer, lifecycle, and referee.
- Current lineups, starting pitchers, weather/roof, and other material volatile evidence are fresh and conflict-free under explicit policies.
- Player distributions pass prospective calibration; the field generator passes contest-conditioned full-lineup calibration.
- Settlement handles exact payouts, ties, duplicates, and fees and matches independent economic oracles.
- The portfolio optimizer assigns exact lineups to exact contests under a declared utility and reports solver status/gap plus model uncertainty.
- Late swap is conditional, lock-safe, bounded, and independently refereed after final bytes.
- Every external/child operation has a deadline and terminal state; no infinite retry or agent chatter exists.
- The independent referee binds `PASS` to the exact delivery SHA-256 and a durable manifest transaction.
- The system never represents missing/stale/conflicted evidence as neutral or passing.
- Economic claims are supported by a predeclared prospective evaluation, not a synthetic fixture or solver label.
- The default workflow stops at a human-controlled review/upload boundary unless a separately approved integration exists.

### 3.23 Immediate implementation handoff

The secondary implementation agent should begin with a new branch and **not** start by tuning projections or stack weights. The first pull request should contain only:

1. `contracts/evidence.py`, `contracts/artifacts.py`, `contracts/identity.py`, and `contracts/roster.py`;
2. content-addressed atomic artifact writes plus transactional delivery/run index;
3. a hermetic runtime manifest;
4. a separate final-byte referee consuming the contracts through generated data;
5. migrations/adapters that read current Classic and Showdown artifacts without changing current production behavior;
6. tests for F-01, F-03, F-08, F-10, F-14, F-20, F-21, F-23, F-24, F-26, F-31, F-33, F-34, F-43, and F-46.

Only after that integrity base is merged should the team build the probabilistic player model, field generator, settlement engine, and joint portfolio optimizer. This ordering prevents a more sophisticated model from being wrapped in the same ambiguous evidence and delivery lifecycle.

### 3.24 Bottom line

The existing repository should not be burned down wholesale. Its strict ID handling, immutable-evidence intent, deterministic controls, legality kernels, final-byte discipline, and historic contest corpus are the right foundations. The production decision layer, however, should be replaced rather than incrementally decorated.

The shortest credible path to the requested objective is:

```text
typed immutable evidence
  -> calibrated joint MLB outcomes
  -> contest-conditioned legal field samples
  -> exact ties/duplicates/payout settlement
  -> exact-entry capital-aware portfolio optimization
  -> conditional late swap
  -> independent final-byte referee
  -> human-controlled DraftKings upload boundary
```

Anything less can be a useful lineup generator. It is not yet a zero-touch maximum-EV engine, and it should not be represented as one.
