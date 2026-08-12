# DFS_SYSTEM_GREENFIELD_SPEC.md

## 1. Greenfield Audit & Legacy Deconstruction

An architectural review of the current workspace—specifically the heavy reliance on static `.md` instruction files (`CLAUDE.md`, `MLB_Classic.md`), local CSV file drops (`DKSalaries`, `DKEntries`), and JSON mining dumps—reveals a system optimized for human-in-the-loop oversight rather than machine-speed autonomy. 

**Core Anti-Patterns & Bottlenecks Identified:**
*   **File I/O Bottleneck:** Depending on directory-based daily archives (`data/archive/YYYY-MM-DD/`) creates artificial latency and breaks down during live, event-driven scenarios (like late scratches 5 minutes before lock).
*   **LLM Misallocation:** Monolithic prompts suggest the LLM is being forced to reason about matrix construction, correlation stacking, or constraint validation—tasks that are inherently deterministic and computationally expensive when tokenized. 
*   **State Bloat:** Stacking rules, slate context, and logic into massive markdown files degrades the LLM's attention mechanism and burns tokens unnecessarily on every generation loop.
*   **Synchronous Polling:** Manual data drops imply a synchronous execution flow. A true zero-touch system must be asynchronous and event-driven.

---

## 2. Target Greenfield Architecture & Implementation Specs

To achieve maximum EV, non-blocking throughput, and absolute zero-touch autonomy, we must transition to a decoupled, cloud-native API framework (the Project Olympus model). The LLM's role must be strictly confined to unstructured data parsing (news, scratches, weather) and strategy formulation, completely offloading all mathematical portfolio construction to local deterministic solvers.

### Architectural Vectors

*   **Component / Discovery Question:** Local Code Boundaries & Solvers (PuLP)
    *   *Why are we generating or validating lineups via LLM instructions?*
*   **Unbiased Critique & Root Cause:** Relying on an LLM to enforce DraftKings salary caps ($50k), position requirements, and team stacking limits is fundamentally flawed. It leads to hallucinations, infinite self-correction loops, and massive latency. LLMs are probabilistic; DFS constraints are deterministic. 
*   **Greenfield Solution & Technical Spec:** 
    Extract all generation math into a dedicated, local Python microservice powered by `PuLP` (Linear Programming). 
    *   **Input:** The LLM agent passes a strict JSON payload containing player projections, variance bounds, exposure caps (e.g., Max 30% Aaron Judge), and stack rules (e.g., 5-3, 4-3-1).
    *   **Execution:** The Python script instantly compiles the simplex matrix, runs the LP solver to maximize EV across the portfolio, and natively outputs the `DKEntries.csv`.
    *   **Skill Spec:** Create a Claude Cowork Skill: `execute_pulp_portfolio(projections_json, rules_json)`. The LLM never sees the 150 lineups; it only receives a success boolean and the top-line EV/Salary metrics.

---

*   **Component / Discovery Question:** Real-Time Data Pipeline & Browser Automation
    *   *Why are we manually managing `DKSalaries.csv` and `mined.json` in daily archive folders?*
*   **Unbiased Critique & Root Cause:** The current setup guarantees failure during late-swap windows. File system manipulation requires human triggering or clumsy cron jobs. If a weather delay hits at 6:55 PM, the file system state is instantly stale.
*   **Greenfield Solution & Technical Spec:** 
    Burn down the local CSV archive structure. Implement a headless, event-driven data pipeline.
    *   **Execution:** Deploy a background Node.js/Python process using Playwright or direct API scraping to poll sportsbook lines, weather APIs, and DraftKings endpoints every 60 seconds.
    *   **State Management:** Push all real-time data into an in-memory Redis cache (or SQLite for local setups). 
    *   **Trigger:** When a positive-EV middle opportunity appears, or a starting lineup changes, the pipeline triggers a webhook that wakes the agent to update projections and silently re-run the `execute_pulp_portfolio` skill for a late swap.

---

*   **Component / Discovery Question:** Context Bloat & Prompt Engineering
    *   *Are `CLAUDE.md` and `MLB_Classic.md` structured optimally, or are they legacy instruction dumps?*
*   **Unbiased Critique & Root Cause:** Global instruction files create context bloat. Loading the entire MLB Classic strategy into the context window for a simple projection update wastes tokens and dilutes the model's focus on the immediate task.
*   **Greenfield Solution & Technical Spec:** 
    Implement Progressive Disclosure using modular Cowork Skills. 
    *   Burn `MLB_Classic.md` as a global prompt. Break it down into discrete, callable tools: `analyze_weather_impact()`, `evaluate_pitcher_matchup()`, `calculate_stack_ev()`.
    *   The orchestrator agent operates on a minimal base prompt. It queries specific strategic modules *only* when the slate parameters dictate they are necessary. 

---

*   **Component / Discovery Question:** Zero-Touch Workflow Orchestration
    *   *Where does the system stall, and how do we remove human approval?*
*   **Unbiased Critique & Root Cause:** Multi-agent chatter or complex iterative loops introduce points of failure. If an agent hallucinates a CSV column, the run stalls waiting for human correction.
*   **Greenfield Solution & Technical Spec:** 
    Transition to a rigid, one-way execution graph with deterministic fallbacks.
    1.  **Ingestion:** Scraper detects a new slate and pushes DK salaries to the database.
    2.  **Analysis:** Orchestrator agent evaluates slate odds and generates target exposures/projections.
    3.  **Optimization:** Agent calls `execute_pulp_portfolio()`.
    4.  **Validation:** A separate deterministic Python script validates the output CSV against DK rules (no LLM involved). If it fails, Python corrects the exposure caps and re-runs the solver instantly.
    5.  **Submission:** Headless browser automatically uploads the validated CSV to DraftKings. No human review step. If EV meets the threshold, the system ships it.