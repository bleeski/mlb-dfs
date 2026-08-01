# DFS_SYSTEM_GREENFIELD_SPEC.md

## 1. Critical Flaws, Bottlenecks & Architectural Anti-Patterns

**Title / Component:** LLM-Based Combinatorics & Roster Construction
**Adversarial Critique & Rationale:** Relying on a large language model to parse DraftKings CSVs, calculate salaries, and enforce positional constraints is a fundamental architectural failure. LLMs are non-deterministic, slow, and mathematically unreliable. Using tokens to evaluate combinations guarantees high latency, frequent salary busts, invalid rosters, and infinite self-correction loops that inevitably crash or timeout.
**Proposed Architecture & Implementation Spec:** Complete decoupling. The LLM must be stripped of all math and roster-building duties. Implement a deterministic Linear Programming (LP) mathematical model using Python's `PuLP` library to handle the actual optimization[cite: 2]. The LLM's role shifts to a strategic orchestrator: it analyzes slate context, dictates exposure limits, sets correlation weights, and triggers the Python solver.

**Title / Component:** Monolithic Context & Prompt Bloat (`CLAUDE.md`)
**Adversarial Critique & Rationale:** Shoving all MLB DFS rules, slate variables, strategy logic, and formatting instructions into a single `CLAUDE.md` degrades context window efficiency. It increases Time to First Token (TTFT), raises inference costs, and dilutes the model's attention, leading to instruction drift mid-run.
**Proposed Architecture & Implementation Spec:** Adopt a progressive disclosure architecture. Break `CLAUDE.md` down into atomic, situation-specific instruction files (e.g., `mlb_weather_rules.md`, `stacking_logic.md`). The system will dynamically inject only the context required for the specific phase of the pipeline.

**Title / Component:** Manual/Blocking Data Ingestion
**Adversarial Critique & Rationale:** Any workflow requiring human intervention to download DraftKings CSVs, monitor late scratches, or update starting lineups destroys the zero-touch objective. Polling these elements through slow agentic browser tools creates blocking bottlenecks that stall the pipeline right up to lock.
**Proposed Architecture & Implementation Spec:** Deploy an autonomous headless browser scraping module (via Playwright or Puppeteer) or direct API hooks running on a high-frequency background cron job. This data layer continuously fetches salaries, scrapes starting lineups, and flags discrepancies to a Redis/Celery queue. The AI orchestrator only interacts with the cleaned, formatted JSON outputs of this background process.

**Title / Component:** Mean-Projection Optimization Fallacy
**Adversarial Critique & Rationale:** Optimizing purely for the highest aggregate projected points ignores the reality of DFS. Tournaments are game-theory puzzles; winning requires exploiting field ownership inefficiencies and penalizing heavy duplication[cite: 2]. Generating lineups in a vacuum without field simulation guarantees negative ROI in high-stakes contests.
**Proposed Architecture & Implementation Spec:** Integrate Stokastic-style field simulation[cite: 2]. Before generating user lineups, the Python engine simulates thousands of expected opponent lineups based on projected ownership. The LP optimizer objective function is then modified to rank generated portfolios by simulated ROI against the field, rather than raw projection.

---

## 2. Greenfield Architecture, Feature Enhancements & Implementation Specs

**Title / Component:** Project Olympus: Decoupled Cloud Orchestration
**Adversarial Critique & Rationale:** Local agent loops are fragile and prone to workstation failures, network blips, or session timeouts. A production-grade multi-sport pipeline cannot rely on an active Cowork window.
**Proposed Architecture & Implementation Spec:** Transition to a decoupled, cloud-hosted API framework. 
*   **Message Broker:** Use RabbitMQ or AWS SQS to handle the event-driven pipeline.
*   **Microservices:** Isolate data scraping, projection modeling, LP optimization, and CSV formatting into separate Docker containers.
*   **Agent Orchestrator:** The Claude agent monitors the message queue, analyzes the incoming slate data, adjusts parameters, and fires API requests to the microservices.

**Title / Component:** Cowork Skills as Deterministic Executables
**Adversarial Critique & Rationale:** General-purpose browser actions and file edits are too broad and error-prone for precision pipeline execution. 
**Proposed Architecture & Implementation Spec:** Turn all recurring actions into hardcoded, scoped Cowork Skills or MCP (Model Context Protocol) tools.
*   `skill_fetch_dk_salaries(sport, slate_id)`: Triggers the Python scraper.
*   `skill_run_pulp_optimizer(config_json)`: Executes the LP model with LLM-defined parameters.
*   `skill_submit_lineups(file_path)`: Automates the final CSV upload to DraftKings.

**Title / Component:** Adversarial Pre-Flight Validation Pipeline
**Adversarial Critique & Rationale:** Submitting invalid lineups costs money and ruins slates. Validation must be absolute, instantaneous, and non-blocking to the main generation loop.
**Proposed Architecture & Implementation Spec:** Implement a deterministic Python validation script (`validate_lineups.py`) that operates entirely outside the LLM. 
*   Checks exactly 8 players per Classic lineup, exactly 6 per Showdown.
*   Enforces the $50,000 salary cap.
*   Verifies no scheduled weather postponements or late-scratch players are included.
*   If a violation is found, the script instantly rejects the output, logs the specific constraint failure, and returns the error code to the LP optimizer to rerun the failed iterations, never bothering the LLM.

**Title / Component:** Real-Time Multi-Book Line Scanner Integration
**Adversarial Critique & Rationale:** Static projections are dead on arrival. Market movement provides the most accurate indicator of player expectation, but manual monitoring is impossible at scale.
**Proposed Architecture & Implementation Spec:** Build a continuous sportsbook line scanner that evaluates multi-book odds and player props. When line discrepancies, positive EV arbitrage, or middle-finding opportunities occur, the scanner automatically updates the baseline player projections in the database. The LP optimizer reads the freshest projections at the exact moment of lineup generation.

**Title / Component:** Organic Correlation via Play-by-Play Simulation
**Adversarial Critique & Rationale:** Manually defining rule trees (e.g., "Stack QB + WR + Opp WR") is rigid and misses nuanced game scripts[cite: 2].
**Proposed Architecture & Implementation Spec:** Emulate SaberSim's paradigm[cite: 2]. Implement a Python-based Markov chain or Monte Carlo simulation that runs the slate play-by-play. The optimizer pulls lineups directly from the simulation iterations where specific game scripts hit their 99th-percentile tail outcomes, ensuring true, organic correlation without manual rule-setting.