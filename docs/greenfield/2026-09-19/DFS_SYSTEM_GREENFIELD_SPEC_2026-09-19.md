# DFS system review, 2026-09-19

**Reviewed commit:** `3951675` (main), the first audit taken from inside a Claude Code cloud container rather than against one.
**Baseline measured here:** `PASS  v2.26.0  40 modules  2165 tests  5 skipped`, exit 0, twice, 197s and 229s wall. Host: 4 vCPU, 15 GB RAM, cp311, numpy 2.2.6 / pandas 2.3.3 / scipy 1.15.3, `BASH_DEFAULT_TIMEOUT_MS=900000` so `repo_env.call_budget_s()` resolves 630s.
**Status of this document:** Sections 1 and 2 are complete and are the record of the audit. Sections 3 and 4 are appended by the sessions that build CC-A5 through CC-A9; until a row lands, its part of those sections says what is proposed, not what exists.

**Truthful labels.** Everything below is a deterministic observation about this tree, a measurement taken on this host, or a labeled proposal. Nothing here is an ROI figure, a win rate, a cash rate, an edge, or a probability claim.

---

## Section 1 — Baseline architecture and forensic audit

### 1.1 Coverage, and what was not inspected

Traced in full: the active Classic build path from `run_slate` through intake, projections, candidate generation, allocation, export and certification; the Showdown path at summary level; the archive-and-ledger outcome loop; the coordination mechanism; every host-dependent constant; the test and CI surface. Read by anchor rather than whole: `docs/backlog.md` (1.1 MB), `CHANGELOG.md` (1.3 MB), `ledger/MLB_Classic_Calibration_Ledger.md` (780 KB). Not inspected: `data/archive/` beyond listings and two vendored contests, the thirteen prior greenfield critique documents beyond their adjudications on the board, and `mlb_engine/production/` beyond confirming it is off the build path.

Three read-only investigations ran in parallel windows and every material finding below was re-verified by hand against the tree before it was written down.

### 1.2 Actual data flow, Classic

`build_slate.py` (or `autobuild.py` above it) stages a slate, then calls `execution_pipeline.run_slate` (`:4802`), the only production door. In order: entry rows and postures; `_assemble_projection_frame` (`:4904`); leverage attachment before schema validation (`:4934-4937`); checkpoint, slate feasibility, shape bands, control merge (`:4949-4986`); gates derived and asserted (`:5092`, `:5131`); hard blocks (`:5172-5199`). With `approve=False` it plans and writes nothing outside a temp cache (`:5220-5237`). With `approve=True` it builds the candidate bank (`:5293`), runs `execute_portfolio` (`:5407`), then mirrors to `outputs/` and hashes the delivered file (`:5442-5448`).

Disk: `runs/<run_id>/` gets `manifest.json`, an `inputs/` snapshot, `final/projections.csv`, `final/assignments.csv`, `final/DKEntries.csv`, `final/diagnostics.json`, and a promoted pointer; `outputs/<date>/` gets the delivered CSV, `upload_manifest.json`, `build_brief*.json`, and where applicable `autobuild_decisions.json` and `ownership_pred_*.json`.

The projection is `Base x F1 x F2 x F3 x F4 x F5` (`projection_builder.py:123-126`), Base being `AvgPointsPerGame` unless supplied, optionally xwOBA-corrected and shrunk. Ownership is not in the optimizer objective; it enters as two optional MILP constraints (`optimizer_v3.py:1175-1200`). Selection is one joint MILP over entry-by-candidate assignment (`contest_allocator.py:2638`) scoring candidates by contest shape. Certification is computed in one place (`dk_entries_manager.derive_workflow_certification:1183-1202`) and written to the diagnostics, the run manifest and both return paths.

### 1.3 Findings

**F1 — severe. No cloud build can be graded, because the outcome loop reads two directories that do not survive the container.** `runs/` and `outputs/` are gitignored (`.gitignore:1-2`); a cloud container is reclaimed at session end. Three archive-side links read only those trees: entered contests from `outputs/*/DKEntries*.csv` (`tools/awaiting_standings.py:178-193`); the operator's Entry IDs from `outputs/<date>/upload_manifest.json` *and* the delivered file it names (`mlb_engine/field/field_miner.py:1311-1342`, which calls `parse_dk_entry_rows(delivered)`); the salary file a build used, via `runs/<run_id>/inputs/` (`field_miner.py:598-640`). The 2026-09-17 and 2026-09-18 cloud builds left hand-written fragments and nothing machine-readable; their delivered sha256 exists in no file in the repository. Compounding it, no live run record carries code identity at all — `build_state_manager.py:118-137` records the interpreter and package versions, and the only `code_sha256` in the tree is in the off-path strangler (`production/workflow.py:34-51`). **Remediation: CC-A6 / R369.**

**F2 — egress is asserted in documentation and measured differently every session.** `mlb_engine/intake/paste_odds.py:3-10` states the odds API is proxy-gated; `skills/generate-lineups/SKILL.md:393-398` (R316) records it answering 200; the 2026-09-18 build fragment records 403. Measured 2026-09-19 from this container: statsapi 200 (15 games hydrated), Savant CSV 200, mlb.com starting lineups 200, open-meteo 200, the odds API 401 (reachable, no key), FanGraphs 308 by curl, RotoWire 200. Each reading was true where taken; a document is the wrong place to freeze one. Separately, `THE_ODDS_API_KEY` is unset and `.env` cannot exist in a fresh clone (`repo_env.py:83-95`), so the F1 implied-total factor is neutral on every cloud build until the variable is set on the environment. **Remediation: CC-A5 / R367, plus one operator action.**

**F3 — the split-gate constants are the last live Cowork numbers in code.** `tools/audit.py:2046` `GATE_DEFAULT_BUDGET_S = 28.0` and `:2066` `GATE_CALL_CEILING_S = 39.0`, with help text at `:3215-3228` naming Cowork, against a CI job and a container that both run the whole gate in one call. The comment at `:2037-2045` keeps them deliberately as a floor for an unknown host; the board overrides that. **Remediation: CC-A1 / R358.**

**F4 — the claims mutex reads false in the cloud.** `claims/*` is gitignored and `tools/claim.py` has no host branch, so a cloud session takes a claim nobody can see and reads "none held" regardless of what else is running. **Remediation: CC-A2 / R359.**

**F5 — stale host prose in the contract and the rules.** `CLAUDE.md:49,60,67,70`; `.claude/rules/engine.md:20-21` and `.claude/skills/dev-session/SKILL.md:41` call `/tmp`, `nohup` and `rm` "Cowork-only idioms", measurably false here. `docs/cowork_migration_handoff.md:20` instructs a pip invocation `.claude/settings.json` denies. Two pins constrain any fix: `tests/test_core.py:12314-12316` requires the three `docs/cowork_*.md` to exist and stay referenced from CLAUDE.md, and `:12333-12336` requires the literals `## Sandbox`, `T-15` and `## Showdown` to remain in it. **Remediation: CC-A1 / R356 and CC-A5 / R368.**

**F6 — the candidate bank was never Cowork-capped, and the live path has no performance baseline.** `resolve_candidate_bank_size` (`optimizer_v3.py:3393-3422`) is entry-derived and reads no clock; the cap is `DEFAULT_CANDIDATE_BANK_CAP = 150` (`:3245`). The Cowork residue was the per-attempt search budget, fixed by R360. `MLB_Classic.md:251` still says "Default near-lock cap: 24 candidates; 40 only when justified", which the code contradicts (open since 2026-07-19 as OH-7). `tools/benchmark_engine.py:38-46` imports only `mlb_engine.production.*`, so nothing measures the path that actually builds slates. **Remediation: CC-A5 / R368 for the document, CC-A9 / R374 for the measurement.**

**F7 — postmortems exist at one end and not the other.** The execution retro is a written, used, manual skill step (`skills/generate-lineups/references/retro.md`); R363, R364 and R365 were filed through it. But the facts it asks a session to reconstruct are in the artifacts and none are extracted, and the only telemetry is one `elapsed_s` per brief (`build_slate.py:5453`). `.claude/settings.json` carries `SessionStart` and `PreToolUse` hooks only. On the outcome side the archive loop is complete and manual, joining the operator's entries by Entry ID (`field_miner.py:1388-1420`), but nothing joins a run or a delivered sha256 to a result, and `ledger/own_results.json` records carry no `run_id`. **Remediation: CC-A7 / R370 and R371.**

**F8 — the dual objective is measured as proxies, and the instrument that would price it in dollars is unbuilt.** Apex and washout review proxies exist per build (R126, `execution_pipeline.py:2612-2693`) and two portfolio-level washout caps shipped in CC-2. There is no simulation and no payout settlement anywhere on the build path: `monte|random` over `mlb_engine/` excluding `production/` returns zero hits. Exact-fraction tie settlement already exists off-path (`production/simulation.py:95`) and observed payout facts exist for 611 contests (`data/reference/dk_contest_money_2026-09-15.json`). The gap is CC-6 / R118, which this plan does not close.

### 1.4 Observations filed rather than fixed

The `F3` projection factor has no producer anywhere and is defaulted to 1.0 at `execution_pipeline.py:4206`, making it a permanently inert term in the documented five-factor model. `tail_candidate_scanner` has no production caller. Two independent `sha256_file` implementations exist (`build_state_manager.py:42`, `upload_manifest.py:100`). `production/csvio.py:146` re-implements the `Excluded` reader that CLAUDE.md declares single-sourced, off the build path. R297(c) remains: a crash between `create_run` and the first refusal strands a run at `status: building`.

### 1.5 The highest-value item this plan does not touch

R317, board row CC-15. `data/reference/fangraphs_platoon_lineups.json` supplies the projected batting order for any team that has not posted, and a partial refresh stamps the current date on all thirty teams while leaving most of them months old, so the seven-day staleness check goes quiet on a stale file. The 2026-09-18 build ran on a platoon reference 44.9 days old against that limit, with 43 of 220 delivered roster slots in unposted games. On any slate with a TBD side this outranks everything in Phase A0.

### 1.6 Unresolved access and evidence gaps

`DFS_ENGINE_COWORK_SKILL_MASTER_SPEC.md` is not present in the repository or the working tree; the reference architecture used instead was `MLB_Classic.md` and `DFS_SYSTEM_GREENFIELD_SPEC.md` (twelfth edition), whose disposition table is already adjudicated on the board. Which attachment root receives a chat upload remains unmeasured (R354's open item). Whether a larger candidate bank improves portfolio quality is unmeasured by construction, which is what CC-A9 exists to settle.

---

## Section 2 — Greenfield decisions and boundary analysis

### 2.1 Retain

The architecture stands. `run_slate` to `optimizer_v3` to `contest_allocator` to a certified export remains the build path; the solver stays `scipy.optimize.milp` as CLAUDE.md pins it, and the bank fits one call inside the 630s this host affords. No simulation, no expected-value objective and no field model are introduced here, because the board already sequences them (CC-18 through CC-21) behind the settlement instrument that would grade them (CC-6), and that ordering is correct: a model promoted before its grader exists cannot be told from a model that is wrong.

Also retained deliberately: the manual retro as a skill step rather than a hook, which is the operator's dated decision of 2026-09-18 (R362) and survives scrutiny, since a session finishing its turn is not a build completing; the claims mechanism itself, because two hosts still share a disk and genuinely need it; and the three `docs/cowork_*.md` runbooks, which are pinned and still describe a live host.

### 2.2 Change

The governing decision is **instrument before model**. The severe finding is not a modeling gap but an evidence gap: every cloud build currently vanishes, so no amount of better modeling could be graded. The first structural change is therefore a durable, tracked, machine-readable record of every build, written through the one choke point all three delivery tools already call, and read by the three archive-side links that today read ephemeral directories.

Everything else follows from it. The outcome review is a join over that record. The deterministic half of the retro is an extraction from it. The subagent cost accounting writes into it. The bank measurement is the only item that does not depend on it, and it is last and conditional.

### 2.3 Remove

Two documents that instruct a workflow that no longer exists and in one case a command the settings deny: `docs/cowork_migration_handoff.md` and the body of `MANIFEST.md`, both to `docs/legacy/` with headers naming what superseded them. `MANIFEST.md` keeps a pointer stub in place because it is named in the DEV write set in two files. One document sentence is corrected rather than removed: `MLB_Classic.md:251`'s candidate cap, which the code has contradicted since 2026-07-19.

A third agent was considered and declined: a diff reviewer, because `/code-review` already ships and does that work.

### 2.4 The deterministic and LLM boundary

Unchanged in principle and tightened in practice. Deterministic code owns ingestion, joins, projections, ownership arithmetic, optimization, salary math, validation and export. The language model researches, interprets unstructured input, and reviews adversarially. The tightening is that subagents are handed an artifact path rather than a repository to explore, which is the same boundary applied to cost: the first agentic QA run spent roughly 109k tokens and produced one acted-on finding of five, and most of that spend was gathering facts a deterministic tool already had.

### 2.5 Resource and cost analysis

The scarce resource is the operator's usage allowance, not money. The CI gate is GitHub's and runs inside the free allowance for private repositories. Hooks and subagents carry no separate billing. Two capabilities that would be tier-gated were declined on their merits before the question arose: scheduled Routines, because standings still arrive by manual download and a scheduled run would mostly idle; and storing the odds key as an API credential rather than an environment variable.

The plan's own largest saving is that this audit is written down here, so no later session re-derives it, and that `docs/PROGRESS.md` lets a session read one screen instead of a 1.1 MB board.

### 2.6 Crosswalk to the reference architecture

Retained from the twelfth edition's disposition table: preserve the DraftKings parsers, Entry-ID handling and roster legality as characterized adapters; preserve the archive immutably and re-index it; keep promotion fail-closed while generation fails open. Rejected for now, with reasons already on the board: replacing the runtime state model with a transactional store (the strangler that would do it is stage-0 and ungraded), and replacing the production objective with scenario-level profit (blocked on the settlement instrument, CC-6). Not applicable: its NFL examples, its named vendors, and any requirement that introduces a paid feed.

### 2.7 Explicitly rejected assumptions

That the candidate bank was capped by the Cowork sandbox: false, and CC-A9 exists partly to stop it being re-raised. That the egress picture recorded in the documentation is current: it was true where measured and is not a property of the repository. That a hand-maintained tracker would be followed: this repository has eighteen ledger fragments unmerged since 2026-08-13 and a gate pin about twelve moves stale, both because a second surface needed a second write, which is why the status view here is generated and gate-checked rather than maintained.
