# Deadline delivery QA — 2026-09-22

## DEADLINE DELIVERY, AUTONOMOUS RECOVERY, AND CONSTRAINT RELAXATION

**Verdict: the active production path does not yet satisfy the governing delivery priority.** It contains useful recovery mechanisms, independently checked solver incumbents, and artifact safeguards. It can still withhold feasible work over strategy or process requirements, exhaust time before producing its first usable export, and call an internal write a delivery without evidence that the operator received it.

**Scope and authority.** This is an audit and implementation handoff, not an implementation. The operator's 2026-09-22 instruction governs the assessment: first deliver a genuinely usable submission before the effective deadline; then improve large-prize equity and washout avoidance; then spend remaining safe time on research, diversification, and explanation. Reduced strategic quality is acceptable when necessary. Invalid submissions, fabricated evidence, changed locked selections, and violations of access permissions are not.

**Repository snapshot:** [bleeski/mlb-dfs, main at 5b831655](https://github.com/bleeski/mlb-dfs/commit/5b831655fdd2c12d0f4277cdbbfb1165b0c948c8), committed 2026-09-22 15:56:23 UTC. All code links below are pinned to this commit. This report supplements the historical August 14 audit; it does not present that audit's observations as current.

**Audit boundary:** inspected both active Classic and Showdown routes, the supervisor, optimizer and allocator recovery, certification, independent preflight, artifact publication, late swap, relevant instructions, existing tests, CI, and all eight tracked delivery/refusal records. No engine, configuration, test, salary, entry, or lineup files were changed in GitHub. No new tests were written. No live slate was generated, no external feeds were exercised, and no DraftKings access or upload occurred.

### Evidence standard and verification

- **Executed:** 114 existing tests passed in the audit environment, covering deadline parsing/filtering/wiring, refusal classification, incumbent handling, supervisor failure/resume behavior, promotion, manifest publication, gate assumptions, Showdown solver status, and postmortem clock facts. Some tests intentionally mock the final solve or child process; those boundaries are stated below.
- **Inspected:** behavior traced in production code at the pinned commit. An inspection is not a timed end-to-end production demonstration.
- **Recorded:** repository artifacts or historical incident accounts. These establish what was recorded, not unobserved operator receipt.
- **Unverified:** missing tests, missing authoritative platform evidence, or an operational outcome that available artifacts cannot establish.

The local diagnostics used Python 3.12.14, numpy 2.3.5, pandas 2.2.3, and scipy 1.17.0. This differs from the repository's pinned runtime, so these results are supplemental, not a replacement for its gate. The final source snapshot was checked against Git blob hashes: 104 materialized files matched. The diagnostics were rerun after restoring exact source bytes.

The exact audited commit also has a successful [GitHub gate run](https://github.com/bleeski/mlb-dfs/actions/runs/35750714120). Its actual line includes qualifications:

    PASS  v2.26.0  41 modules  2379 tests  5 skipped
    {test_core 1406/1406 (4 skipped) skipped_in_place;
     test_showdown 334/334 (1 skipped) skipped_in_place}

The log warns that those skipped counts do not prove coverage. Do not abbreviate this as 2,379 fully executed passing tests. A green code gate does not establish timely operator delivery.

### 1. Actual path to the first usable export

| Stage | Active Classic route | Delivery consequence |
| --- | --- | --- |
| Session preparation | CLAUDE.md requests the audit, solver probe, pool review, and use of autobuild. | These consume the live window unless the session applies the delivery policy. The audit is an engineering health check, not proof a particular CSV is usable. |
| Input preparation | build_slate main parses flags, resolves dependencies, stages salary/entry files, resolves the feed, and calls run_classic. | Missing essential authority correctly blocks; some optional inputs and unsupported strategy flags also stop before any solve. |
| Pool and research | run_classic builds the pool; resolves reference data, venues, odds, weather, and enrichments; then resolves leverage inputs. | Optional work precedes the first export. There are useful degraded-input branches, but no preserved baseline yet. |
| Timing probe | build_single_lineup is called to measure speed. Its returned lineup is discarded. | A potentially legal solution does not become an entry-mapped, validated baseline. |
| Candidate bank | Direct bank generation or cached slices; the sliced route demands count/pair coverage before proceeding. | A thin bank can return exit 10 before allocation or the governor, even if its candidates could cover entries with weaker diversity. |
| Allocation | run_slate assembles projections and controls, resolves every contest, builds/accepts the bank, and calls execute_portfolio. | A joint failure prevents the whole allocation. There is no independent group-delivery boundary here. |
| Candidate CSV and certification | execute_portfolio writes candidate/DO_NOT_UPLOAD_DKEntries.csv; aggregates pre-export, template, reconciliation, roster, strategy, and lock checks. | A legal candidate can remain withheld because a nonessential gate fails. |
| Final export | Only after those checks pass is final/DKEntries.csv created, validated, certified, registered, and promoted. | This is the first normal final artifact, after the preferred pipeline has largely completed. |
| Publication and handoff | Mirror to outputs, manifest recording, independent verify_classic, brief/report work, preflight, then the session attaches the file. | Internal export, promotion, and a printed path are not verified receipt. The operator still needs access and upload time. |

Evidence: [Classic preparation and probe][E02], [bank and governor][E03], [run_slate][E04], [execute_portfolio][E05], [publication][E06], [handoff instructions][E07].

Showdown uses a separate run_showdown route. It prices a pool, builds and solves a thesis ladder or bank, checks every lineup, assigns rows, writes an export, records the manifest, constructs the brief, and relies on independent preflight and session handoff. It has its own bounded relaxation ladder, but no early baseline publication. Complete existing rows are preserved; only incomplete reserved rows are targeted. The runtime's relative deadline argument is not passed into run_showdown, and its solve calls do not receive that budget. [Showdown route][E08]

**Important existing foundation:** mlb_engine/production/workflow.py already implements baseline-before-enhancement publication and catches enhancement failures while retaining its baseline. Existing tests cover simulation failure and missing simulation moments. However, CLAUDE.md explicitly identifies that package as the R302 offline stage-0 path, not the active build path. It cannot be credited as production protection. Reuse its verified concepts only after checking its stricter input/strategy contracts; switching entry points wholesale is not this audit's recommendation. [Authority][E01], [prototype][E09]

### 2. Material findings

| ID / priority | Finding and operational impact | Evidence / status |
| --- | --- | --- |
| DD-01 / P0 | **No early usable baseline in the active path.** Research, the bank, and joint allocation run before normal export. The timing probe's lineup is discarded. A crash, timeout, or optional failure during that prefix leaves no deliverable to preserve. | Inspected: E02–E05. Prototype baseline protection exists only in E09. |
| DD-02 / P0 | **No single effective deadline with a publication reserve.** The opt-in governor starts acting on refusals at a fixed six-minute threshold. Relative build budgets, subprocess limits, allocator limits, network timeouts, and lock warnings are separate. A child gets per_build_seconds + 90 even when less delivery time remains; the supervisor checks the slate deadline between attempts. Showdown is not passed the relative deadline. | Inspected: E03, E08, E10, E11. Existing clock tests pass, but whole-run reserve enforcement is unverified. |
| DD-03 / P0 | **The thin-bank refusal bypasses its own recovery classification.** run_classic returns exit 10 at the count/pair shortfall before reaching the governor. autobuild responds by growing the bank again. Declaring bank_thin_partial “badly_shaped” does not make that branch recover. | Inspected: E03, E11. Existing refusal tests verify classification; no executed thin-sliced-bank-to-on-time-export acceptance case was found. |
| DD-04 / P1 | **Usability, quality, and workflow are still coupled.** Pre-export selection/allocation certification and an approved solver-method vocabulary block normal export. Unknown strategic contest posture blocks all entries. Odds/weather checks remain gate fields, although the CLI has a useful missing-map assumption path. | Inspected: E04, E05, E12, E13. Gate-assumption tests executed. |
| DD-05 / P1 | **Runtime autonomy is narrower than the operator's standing authorization.** autobuild stops on strategy remedies outside its structural whitelist, unclassified pool blockers, crashes, and timeouts. CLAUDE.md tells the session that exposure/stack strategy changes and any remaining failed gate are Ben's decisions. Its grow-the-bank-first instruction can conflict with deadline recovery. | Inspected and supervisor tests executed: E01, E11, E14. These are prescribed stops; this audit did not observe a live Claude conversation asking the operator. |
| DD-06 / P1 | **Recovery does not guarantee independently feasible entry coverage.** Classic requires all reserved rows filled at both validators and has no usable partial result from joint allocation. Showdown can accept fewer requested lineups than reserved rows, but a true bank/ladder shortfall returns earlier; blank rows also fail mandatory preflight. | Inspected: E03, E05, E08, E15. Existing test explicitly pins the unavailable Classic rung. |
| DD-07 / P1 | **The governor's “open every control” description is incomplete.** Its fixed dictionaries omit explicit candidate reuse, anti-correlation, ownership requirements, allowed candidate/script restrictions, and Showdown's per-contest captain cap. Per-game caps survive the scalar opening, including weather-derived caps merged by minimum. Some stack/reuse controls have separate ladders, with independent solve costs. | Inspected: E10, E16, E17. No comprehensive value-aware recovery policy covers this control set. |
| DD-08 / P1 | **Local artifact bookkeeping can block usable delivery, and receipt is not verified.** Manifest recording failure leaves a self-labelled provisional file; mandatory preflight can reject missing/broken record fields or a failed status write even when file-level checks pass. There is no automatic return to a prior usable export. Handoff remains a session instruction. | Manifest failure/promotion tests executed; E06, E07, E18. No live access receipt was available. |
| DD-09 / P1 | **Degraded labels can disagree across surfaces.** A successful governed Classic retry is certified and mirrored inside run_slate; only afterward does build_slate add “review_grade_deadline_build” and “not certified” to its brief. The gates and manifest certification remain independent of that downgrade, and preflight uses the manifest certification to select “upload_ready.” | Inspected: E05, E06, E19. The wiring test mocks run_slate and does not verify the real manifest/preflight chain. Full reproduction remains an implementation acceptance requirement. |
| DD-10 / P1 | **Delivery records can omit or lag the CSV they claim to describe.** record_delivery calls the tracked-record mirror before the provisional CSV is renamed to its destination. write_delivery_record reads that destination, not the provisional bytes. On a first delivery it records no entries; on replacement it can read the previous file. | Inspected: E06, E20. Recorded: three of four tracked delivery records contain entries: []; the fourth contains five rows. That fourth record's row-to-hash binding is unverified. |

P0 means the next implementation priority because a feasible slate can produce no usable delivery. P1 means a material acceptance blocker or misleading delivery evidence. These are audit severities, not claims that every historical run failed.

**Preserve the distinction about timeouts:** the solver correctly does not label a timeout as proven infeasibility. That does not require another expensive attempt at the same strategy. A future deadline policy may autonomously simplify after a timeout while recording the reason as time pressure, not a mathematical proof.

**Preserve explicit prohibitions:** current overrides are plain values, without a general provenance field distinguishing a default, a relaxable operator preference, and an explicit current “never relax” restriction. merge_open_controls overwrites some operator values and preserves others. The future policy must represent that distinction explicitly before generalizing recovery. An old configuration or a typed cap alone is not proof that the operator prohibited relaxation. [Governor merge][E10]

### 3. Export-blocking gate inventory and classification

Classes below apply under the current governing instruction:

- **V — essential submission validity or authority:** preserve, verify, or repair from authoritative inputs; never fake a pass.
- **S — strategic preference:** autonomously relax when necessary, unless supported by a current explicit never-relax instruction.
- **P — process, model confidence, provenance bookkeeping, or research completeness:** preserve truthful status; should not alone suppress an independently validated usable file.
- **Mixed:** split the check. Do not disable a mixed gate wholesale.

#### Named Classic certification gates

| Current gate | Classification | Required treatment |
| --- | --- | --- |
| salary_gate_passed | V | Real player IDs, official salary/eligibility, correct slate and parseable authority remain essential. |
| entry_grid_gate_passed | V | Correct Entry IDs, contest mapping, geometry, row accounting and authorization remain essential. |
| lineup_gate_passed | Mixed V/S/P | Distinguish player identity or known unavailability from missing confirmation, stale references, and “team cannot fill a preferred stack.” Missing confirmation is not a scratch. |
| pitcher_audit_gate_passed | Mixed V/P | Preserve identity and best available participation evidence; a missing preferred role label is not itself a platform rule. Do not manufacture a declaration. |
| weather_gate_passed | Mixed V/P/S | Missing optional forecast is degraded research; a material-risk cap is strategy; known postponement/unavailability and true lock effects require separate treatment. |
| odds_gate_passed | P | Missing or unmatched market evidence must not block a legal export. Record unavailable/unused, not an invented market. |
| projection_schema_gate_passed | Mixed V/P | Corrupt IDs/salaries/eligibility are V. Missing statistical estimates should activate a safe simpler model. Bad numeric model values require repair or omission, never fabricated data. |
| optimizer_gate_passed | P with V revalidation | scipy availability/provenance is not platform validity. A permitted independent fallback still needs complete submission validation. |
| selection_certified | S/P | Separate requested strategy satisfaction from validity of selected rosters. |
| allocation_certified | Mixed V/S/P | Entry assignment correctness is V. Global portfolio optimality and preferred allocation quality are S/P. |
| allocation_method | P | Allowlisting only scipy joint-MILP methods is an architecture requirement, not a submission rule. A fallback must have an honest method label and independent validation. |
| template_preservation_passed | V, with scoped partial-output contract | Preserve identity, required file structure and nonauthorized cells. Do not implement partial coverage by silently corrupting or truncating the user's original template. |
| entry_reconciliation_passed | V | The file must contain the intended roster for each delivered entry. |
| roster_legality_passed | Mixed V/S/P today | Retain actual roster rules. Move nonplatform anti-correlation, completeness accounting, and unsupported duplicate-lineup assumptions into their own outcomes. |
| locked_immutability_passed | V | Preserve genuinely locked slots and unauthorized existing selections. No deadline override. |
| export_hash_binding_passed | V for delivered-byte identity; P for redundant record plumbing | Validate and bind the actual bytes presented. A broken auxiliary manifest should trigger reconstruction or an independent delivery receipt, never an invented hash or use of stale bytes. |
| portfolio_caps_passed | S | Player/pitcher/stack/SP-pair/game/team caps and overlap are strategy unless a current explicit prohibition establishes otherwise. |
| Forbidden caller assertions / unresolved gate names | V/P | Prevent fabricated validation. Unknown checks require classification; do not permit a generic “assume everything” recovery. |

Evidence: [gate declaration and validation][E12], [evidence derivation][E13], [export validator][E21], [certification path][E05].

The CLI already assumes unevidenced odds/weather gates when their maps are empty, with explicit assumption records. Therefore **ordinary missing odds/weather does not always block**. The deficiency is the design: absent optional evidence can become a passing workflow flag; false-derived optional checks and direct API calls can still block. Keep “not checked” distinct from “checked and passed.” [CLI assumptions][E22]

#### Refusal sites, upstream stops, and independent preflight

| Current condition / surface | Classification | Audit assessment |
| --- | --- | --- |
| pool_blocked_hard | Mixed V/S/P | Some blockers protect slate identity; others concern pool size or evidence completeness. Classify individual facts and salvage unaffected entries. |
| pool_blocked_crosswalk | Mixed V/P | Preserve authoritative identities. The blanket under-five-name wall is a repository rule, not a demonstrated DK rule. Repair safe mappings or use unaffected authoritative data; never guess IDs. |
| bank_thin_partial, exit 10 | S/P | Candidate count and pair coverage are search targets, not a proof no usable entry exists. Currently bypasses the governor. |
| classic_not_certified | Mixed | Split by actual failure; current generic bucket also covers process and preference refusals. |
| classic_verify_failed | V for partial roster/unknown ID/cap/slot/team/game failures; coverage for fully blank rows | Its own verifier distinguishes blank from partially filled rows, but its return still refuses; upstream Classic already requires full coverage. |
| showdown_ladder_infeasible / showdown_bank_short | S/P until legal infeasibility is established | A thesis or limited bank shortfall is not legal impossibility. Preserve solved rows and try bounded simpler completion. |
| showdown_not_certified | V | Recheck captain/UTIL roles, person uniqueness, salary and applicable team requirements. |
| showdown_bank_short_of_reserved_rows | Coverage/S/P | A partial route exists only after earlier solve success. Mandatory blank-row preflight still prevents a clean handoff. |
| showdown_export_failed / showdown_template_broken | V or actual I/O failure | Preserve file structure and identity; retry only a bounded safe writer or another authorized destination. |
| No blank Showdown rows | State, not impossibility | Existing completed selections are work to preserve. Do not equate “nothing to fill” with “no usable lineup exists.” |
| Exclusions leave only one Showdown team | Mixed V/S | Both-team feasibility must hold; distinguish a current never-roster instruction from an old strategic exclusion before recovery. |
| Unknown contest posture / archetype | S/P when Entry ID and contest identity are known | The strategic objective may be uncertain; that is different from not knowing which contest an entry belongs to. A labelled default can preserve submission. |
| Bad units/CLI values, unsupported strategy flag for format | Mixed V/S/P | Never silently reinterpret money, IDs or contest format. Correct routine strategy flags autonomously and record the correction instead of consuming repeated operator turns. |
| Missing/unreadable salary or entry template; inconsistent draftgroup | V | Need sufficient authoritative inputs for that scope. Deliver independently resolvable groups only. |
| Missing solver dependencies | P / operational capability | Not proof of legal impossibility. Current runtime has no automatic independent construction route. |
| Missing/unusable explicitly supplied lineup feed | Mixed V/P | Current exit 4 prevents fallback. A bad optional feed should be quarantined while authoritative salary data and other honest participation evidence remain usable. |
| Missing ownership/leverage file; invalid captain prior/sleeve; unreadable supplied Showdown projections | S/P, except identity conflicts | These can exit 4 before the governor. Disable optional features or use an honest simpler model under the standing authorization. |
| Past-slate/started-game/parent-lock checks | V for true submission/slot locks | Preserve locked selections and distinguish initial build from authorized late swap. A historical replay flag is not permission to claim a live submission. |
| Preflight row structure, ID membership, salaries, position eligibility, captain pricing/role, person uniqueness, platform team/game limits | V | Must pass on the exact delivered bytes. |
| Preflight partial roster | V | Never present an incomplete roster as usable. |
| Preflight all-blank reserved rows | Coverage, not invalidity of unrelated complete rows | A separately validated partial upload contract is needed; do not count unresolved rows as delivered. Actual platform acceptance of the partial format must be established. |
| Preflight known out/shelved or posted-lineup absence | Participation protection, distinct from mere uncertainty | Retain evidence of unavailability; missing confirmation and DTD warnings must not be misreported as the same condition. |
| Preflight optional missing feed | P | Already warns in several cases. Missing evidence must remain visible and must not become a false confirmation. |
| Preflight manifest missing/corrupt, stale status, missing manifest count/contest fields, failed status persistence | Mixed V/P | Genuine byte/entry mismatch must block the affected artifact. Bookkeeping absence should have a safe reconstruction/receipt path. |
| Preflight superseded-file check | V/state | Do not silently send stale selections; reconcile the latest validated version. |
| Preflight strict captain-diversity flag | S | Default is advisory; an explicitly selected strict mode should be classified by the operator's current intent, not assumed immutable forever. |
| Plan approval, full suite gate, strategic QA, simulation completion, narrative/postmortem | P | Development approval remains separate. Runtime review can be autonomous and bounded; optional completion must not withhold a validated baseline. |

The refusal table contains eleven named sites, but it is not the complete operational inventory: early exit-4 paths, dependency failures, exceptions, publication failures, and preflight add other stops. This audit includes those boundaries. [Refusal table][E23], [early CLI stops][E24], [preflight][E15], [manifest checks][E18]

#### Strategy controls whose “hard” treatment needs reconsideration

| Control family | Current behavior | Required distinction |
| --- | --- | --- |
| Player, pitcher, stack, team, game and captain exposure | Some defaults get feasibility floors; governor opens a subset. Per-game minimum merge and per-contest captain limits remain. | Preserve current explicit never-relax limits; otherwise trade concentration against deadline and slate value autonomously. |
| Overlap, same-contest duplication, candidate reuse, distinct-unit preferences | Overlap opens only to roster size minus one; duplicate Classic rosters are placed in legality errors; only engine-default reuse receives its ladder. | Within-lineup duplicate people is a roster violation. Repeated lineups across entries is a separate contest-policy/strategy question. The blanket assertion that DK rejects identical entries was not independently established here; verify applicable rules before allowing repeats. |
| Primary/secondary stacks, stack floors and five-stack quota | Separate allocator/bank relaxations exist. | Strategy; account for combined retry cost and do not require completion of a fixed sequence when time is short. |
| Anti-correlation, forbidden combinations, allowed-candidate/script routing | Can make generation or allocation infeasible; anti-correlation errors currently enter roster_legality_passed. | Strategic unless a current explicit prohibition says otherwise. Respect truly locked and authorized selections separately. |
| Ownership cap, minimum low-owned hitters, captain prior/sleeve | Optional by default; requested but unavailable inputs can stop the run. | Omit unsupported estimates, record degraded modeling, and reassess remaining strategy. Never invent ownership. |
| Salary-spend targets, candidate counts, bank breadth and modeling thresholds | Must not be inferred as platform requirements merely because configured hard. | The upper salary cap is V; preferred spending, bank targets and quality thresholds are S/P. No claim is made that every example is enabled on every current route. |

The governor's comment that per-game entries are only operator-typed is stale: build_slate now forwards weather_game_caps, which the control merge incorporates. A fixed “open scalar” action cannot be credited with opening all those constraints. [Weather cap writer][E17]

### 4. Existing fallback and recovery worth keeping

1. Missing initial lineup fetch can fall back to DK Starting data and the platoon reference; stale-feed refresh failures preserve the cached feed with a warning. The script uses a warning policy for stale platoon data. Projected participation is represented separately from confirmed teams. [E02][E24]
2. Missing/unreadable odds returns a neutral map with a reason. Missing reference data is reported. A caught enrichment ValueError rebuilds an unenriched frame. These are real degraded-model paths, although the later gates and optional feature failures still need consolidation. [E02][E22]
3. The governor records the controls it opens and their previous values. Its retry count is bounded. Showdown has counted overlap/player/captain/thesis relaxations. [E08][E10]
4. The allocator retries a restricted candidate set against the full bank before some strategic relaxations. It can relax engine-default reuse, five-stack quota and stack floors on proven infeasibility. [E16]
5. Classic and Showdown verify time-limited incumbents against constraints and accept usable incumbents without proof of optimality. Invalid incumbents are rejected. The executed existing tests cover this distinction. [E25]
6. Cached bank slices preserve candidates, and unanswered/time-limited jobs remain retryable rather than falsely marked impossible. Retryability needs an overall stop policy so it does not become repeated expensive work. [E25]
7. Immutable run artifacts, hashes, atomic latest-pointer updates and compare-and-swap protect against some overwrite and concurrent-publication mistakes. Deferred late-swap promotion protects the prior pointer while acceptance is unresolved. [E26]
8. Strategic QA is explicitly a report, not a gate. Instructions already require preflight followed immediately by file handoff, with repository housekeeping and postmortem afterward. Keep this ordering. [E01][E07]

**No universal relaxation order is proposed.** The appropriate compromise depends on slate feasibility, contest sizes, current evidence, known candidate quality and the measured remaining time. A fixed order can be a default only if the deadline policy can bypass low-value work and retain a usable result.

### 5. Avoidable operator intervention

The deficiencies are instructions and executable stopping points, not an assertion that the operator personally intervened in every recorded run.

- CLAUDE.md's “Ben's, not the session's” paragraph reserves non-scratch exposure/stack strategy changes and any failing gate for the operator. That conflicts with the new standing authorization where those conditions are relaxable strategy/process facts. Its separate development approval rules remain appropriate.
- autobuild stops with “a human decides this one” for an unclassified pool blocker or a remedy/control mismatch, and “not mine to move” for a strategy check outside its structural whitelist. A genuinely ambiguous authoritative fact may require the operator; choosing a known recovery method or dropping optional research does not.
- Unknown strategic contest posture can demand a supplied posture or reference-table change while correct Entry IDs and contest mapping already exist.
- After an off-contract crash or child timeout the supervisor records the failure and exits; it does not try an independent simple path or retrieve a prior usable deliverable.
- Manual hand-build instructions exist at T-6, but execution is left to the session. They are not an implemented fallback with a reproducible validity contract.
- late_swap's accept-downgrade control needs the same distinction: an authorized repair under the delivery policy should not require a fresh strategy-approval conversation merely because replacement quality is lower. Preserve the genuine authorization and locked-slot boundaries. [E01][E11][E14][E27]

### 6. Preservation, access, and late swap

**Preservation is partial, not absent.** Once the Classic run's final artifact exists, subsequent blocked runs do not normally rewrite that immutable file. Atomic pointer and compare-and-swap tests passed. However, the active pipeline has no general result object that returns the last usable artifact when a later stage fails. Same-name output mirrors and manifest supersession also create a separate publication state: old bytes can still exist while their current status or path no longer identifies them as usable. A durable baseline must cover bytes, essential validation, entry coverage, current label, and accessible location together.

The current production prototype has stronger baseline-preserving enhancement behavior; its presence does not close the live-path gap.

**Delivery instructions are good, delivery evidence is incomplete.** SKILL.md says to attach the file with its hash immediately after preflight. tools/retro.py explicitly says no artifact stamps handoff and accepts a manually supplied handover time. Moreover, its “gate-clean” timestamp is derived from manifest recording, which occurs before independent preflight; for Showdown it is not a three-gate certification timestamp. Keep separate timestamps for export written, essential validation completed, attachment/access verification, and operator presentation. [E07][E20][E28]

**Late swap is bounded by actual state.** The active Classic tools preserve locked slots, require authorized Entry IDs, compare parent lineage, and validate deltas. Showdown does not use run_late_swap. No general promise that late swap is available can be made from these code paths. The implementation must use the applicable contest's rules and submitted state. A file written after the initial submission window is not an on-time success merely because the governor remains active past the deadline. [E10][E27]

### 7. Requested failure-scenario assessment

| Scenario | Verified behavior / evidence | Missing acceptance evidence and implementation requirement |
| --- | --- | --- |
| Short upload window remains | Executed governor tests activate at T-6 and remain active after the timestamp. The mocked Classic wiring test obtains a file after opening controls. | No timed real end-to-end proof including research, independent validation, accessible attachment and upload reserve. Establish the effective deadline once and preserve publication time. |
| Ownership or optional feed unavailable | Inspected neutral odds, stale/empty feed and unenriched-model fallbacks. Requested ownership/prior/projection failures can exit 4. Gate assumptions were tested. | Exercise unavailable optional features through real CLI → export → preflight → handoff. Do not fabricate missing evidence. |
| Preferred exposure cap makes portfolio infeasible | Executed allocator tests distinguish a proven binding cap from a timeout. Governor opens specified caps; some default controls get feasibility floors. | Verify the actual runtime recovers without operator input, including explicit relaxable caps and per-game/per-contest limits. |
| Uniqueness or stacking cannot be satisfied | Inspected reuse/quota/stack ladders and overlap limits. | Verify permitted repeated-lineup completion; prove where repeats are disallowed; ensure mandatory distinctness is not presumed from configuration. |
| Solver times out with legal incumbent | Executed Classic, allocation and Showdown incumbent acceptance and invalid-incumbent rejection tests. | Keep this behavior; measure remaining export/handoff time and verify the real artifact chain, not only solver output. |
| Strategic QA finds no acceptable improvement | QA is documented as advisory. Stage-0 enhancement retains a baseline if no better accepted result is produced. | Active route needs an explicit “deliver/retain incumbent” outcome independent of optional QA completion. No live failure scenario was executed. |
| Optional certification step fails | Executed gate-assumption/override and manifest-failure tests; inspected mixed certification blocking. | A file that passes essential checks must be deliverable with quality/process status incomplete. Do not set failed quality flags to true. |
| Enhancement crashes after baseline | Inspected the inactive prototype's catch/preserve path and its existing tests. Active immutable/pointer behavior tested. | No active end-to-end crash-preserves-and-presents-baseline proof. Test it on the production entry point after implementation. |
| One entry group fails, others feasible | Inspected all-entry Classic allocation and required-full-row validators; existing test pins unavailable Classic rung. | Validate and deliver independent groups, preserve submitted rows, list unresolved Entry IDs separately, and verify a platform-acceptable partial file format. |
| Full portfolio feasible only with weaker diversification | Existing ladders help; thin-bank threshold, duplicate classification and residual caps can still stop delivery. | Establish full coverage before stopping at partial coverage, using repeated lineups only where permitted and disclosed strategic relaxation. |
| Source repeatedly times out | Per-request timeouts exist; supervisor attempts are bounded and timeout behavior tested. The budget is not shared across all calls/retries. | Add deadline-based retry admission, cached/neutral fallbacks and a stopping condition that produces the current usable artifact. A hanging optional source must not consume the publication reserve. |
| Explanation/postmortem would consume upload window | Instructions explicitly put handoff before housekeeping/postmortem; retro clock tests distinguish missing handover evidence. | Instrument the actual sequence and verify that report/brief failure or latency cannot withhold a validated artifact. No live receipt timing was available. |

**Recorded incident evidence:** the governor documentation and September 3 changelog describe the September 1 1940_9g incident: 37 reserved entries, files staged 23 minutes before first lock, and no delivery. This is a historical account, not a rerun at this commit. [E10][E29]

**Recent durable evidence:** the tree holds four delivery records and four refusal records for September 19–20. All four delivery manifest snapshots are still “candidate”; three carry no entry rows. The refusal records retain arguments and generic exit notes but do not establish exact root cause or whether the operator had to intervene. They cannot support an on-time delivery rate. [September 19 Classic][R01], [September 19 Showdown][R02], [September 20 first][R03], [September 20 second][R04]

### 8. Prioritized implementation handoff

These are proposed packages for the **next authorized development session**. This audit authorizes none of their implementation.

| Package | Priority and scope | Acceptance requirements |
| --- | --- | --- |
| A. Essential validity and explicit constraint authority | P0 foundation. Split submission validity, entry-assignment validity, coverage, strategic quality, process completion, evidence confidence and publication state. Represent current immutable operator restrictions separately from relaxable values. | A legal file survives an optional gate failure with an honest degraded label; invalid IDs/salaries/slots/locks/mapping still fail. Every enabled hard control has an authority and scope. No blanket bypass or force-to-success. |
| B. Baseline plus one deadline | P0. Active Classic and Showdown entry points establish and independently validate an entry-mapped baseline before optional expensive work. Capture the useful probe solution where appropriate. One shared deadline governs orchestration, children, native solve limits and publication reserve. | Slow fetch/solve/serialization cannot consume reserved validation and presentation time. No retry resets the deadline. A failed enhancement returns the last validated deliverable. On-time acceptance uses actual presentation/access time. |
| C. Bounded autonomous completion and partial salvage | P0. Route thin-bank exit 10 through recovery; address strategic infeasibility and timeout differently; recover from optional input/tool failures; preserve independent groups. | Thin bank plus feasible entries produces a file; weaker diversity completes the file where permitted; otherwise partial coverage is usable and explicitly scoped. Recovery converges to simpler work with finite attempts and a stopping outcome. |
| D. Publication and receipt | P1, required before declaring B/C production-ready. Publish validated versions transactionally; retain last usable artifact and supersession history; reconstruct nonessential record metadata safely; present the file before ancillary narrative. | A failed manifest/brief/report operation cannot erase the baseline or mislabel a provisional file as delivered. Exact bytes, hash, coverage and accessible attachment agree. No unverified file is presented as usable. |
| E. Labels and durable telemetry | P1. Unify governor, engine, manifest, preflight and tracked-record states. Build the record from the exact newly validated CSV, not a pre-promotion destination. | Governed Classic output has one consistent quality label; record rosters match its hash. First delivery records full rows; replacement records new rows. Handoff is a distinct measured event. |
| F. Scenario acceptance and degraded-quality review | P1 release gate for A–E. Add the missing diagnostics/tests in the implementation session, using real production entry points and authoritative fixture CSVs. | Cover all 12 scenarios above, hard process interruption, corrupt optional metadata, and mandatory-rule failures. Record quality differences without claiming calibrated win/cash probabilities from proxies. |

Suggested bounded recovery contract: maintain the best *currently valid and accessible* artifact; admit optional work only when estimated remaining work fits before the publication reserve; classify a refusal; choose the smallest useful recovery that can finish; independently validate each replacement; stop with the current artifact when further improvement cannot safely finish. Scope authoritative impossibility to affected entries. A fallback must not require the optional feed, expensive model, or failing component that caused the primary failure. Candidate reuse, simple assignment, or a simpler independent construction path are alternatives to evaluate, not a mandated universal order.

**Deadline policy must be measured.** Track stage and host latency distributions, solver tails, upload/access requirements and portfolio size. Use the earlier of the requested delivery cutoff and the relevant submission/lock opportunity minus the necessary access/upload allowance, with validation/publication reserve inside that bound. Handle contest/group deadlines and already locked rows explicitly. Do not substitute a universal T-6 threshold or a new unmeasured constant for the policy.

**Reconcile existing work instead of duplicating it:**

- R98(3)/F18 already proposes a shared deadline with a publication reserve. The roadmap currently places throughput/deadline follow-ons in CC-17; elevate delivery-critical portions ahead of optional modeling work.
- R290's recorded surviving Classic partial-delivery remainder has no slot despite the headline saying closed. Restore it to an actionable delivery package and expand acceptance to mandatory preflight and operator handoff.
- R125(b)/(c) still treats strategy fallback/relaxation as decision-first. The present operator instruction supplies runtime recovery authorization; implementation remains a separate authorized session.
- R302's baseline/state package is a source of reviewed components, not evidence that the active route already meets the requirement.
- R369 delivery records and R371 retro facts provide useful starting points; correct their byte/timestamp boundaries and add actual receipt/coverage events.

Evidence: [backlog R290 remainder][E30], [backlog R98/F18][E31], [backlog R125][E32], E09, E20, E28. Do not mark any implementation item complete based on this report.

### 9. Telemetry and honest success criteria

| Event or field | What it must distinguish |
| --- | --- |
| run_started, requested_delivery_deadline, relevant_locks, effective_deadline | An authorized production attempt versus no run; operator cutoff versus contest lock; explicit upload/access reserve. |
| baseline_written, essential_validation_passed, artifact_hash | Internal candidate versus independently valid, entry-mapped export. |
| artifact_access_verified, presented_at, channel/receipt reference | A path/log line versus an artifact the operator can access. Presentation is not a claim that the operator uploaded it. |
| entries_requested / preserved / usable_delivered / unresolved | Full versus partial coverage, without counting duplicate Entry IDs, blank rows, or invalid rows as delivered. |
| first_usable_presented_at and deadline margin | Usable on-time delivery, late delivery, or no verified delivery. |
| fallback and recovery events | Trigger, failure class, elapsed cost, attempts, method, result and whether the next path depends on the failed component. |
| constraint relaxation | Original value, applied value, authority/provenance, reason, scope and estimated quality tradeoff. |
| operator intervention | Required missing authoritative fact versus avoidable technical/strategy rescue; count and time cost. |
| quality and evidence state | Requested versus applied strategy, uncertainty, optional sources unavailable, solver optimality, simulation/QA status, and normal-versus-degraded comparisons. |
| supersession and baseline preservation | Which hash is current, which remains recoverable, and whether a failed improvement affected either artifact. |
| run_terminal outcome | A refusal/exception/timeout with no usable delivery, plus a reconciled terminal record for interrupted processes. |

Report **usable on-time delivery** only when essential validation passes, covered entries are unambiguous, access/presentation is verified before the effective deadline, and coverage is explicitly full or partial. A late file, invalid output, unverified local path, or a misleading success label cannot improve that metric.

Track partial usable delivery separately from full completion. Track known legal infeasibility and missing authoritative inputs separately from avoidable failure; do not hide avoidable failures by excluding them from the denominator. Evaluate degraded quality using existing labelled proxies and subsequent observed results under comparable slate/contest conditions. Do not invent calibrated probabilities or ownership.

### 10. Cases where delivery can genuinely be impossible

- Authoritative player identities, salaries, eligibility, entry mapping or required template structure are unavailable or contradictory, and cannot be resolved in time for the affected scope.
- No roster satisfies actual platform rules plus genuinely locked/unauthorized selections and current explicit never-relax instructions.
- The applicable submission window has closed and the contest/submitted state offers no authorized late-swap opportunity for that scope.
- No permitted write/presentation mechanism can make the validated file accessible before the effective deadline.
- Security/access requirements prohibit the needed operation and there is no authorized alternative.

Preferred-model infeasibility, no proof of optimality, unavailable optional research, incomplete strategic QA, a thin candidate bank, and a missing provenance sidecar do not by themselves establish those cases. When impossibility is genuine, identify the exact affected rows and missing authority or rule, preserve prior submitted selections, and deliver independently usable work. An audit report is not a substitute for a feasible production submission.

### Reproduction record for this audit

No tests were created or edited. These existing classes were executed together from a read-only source snapshot; test scratch artifacts were isolated by the repository's existing test setup:

    PYTHONHASHSEED=0 python -m unittest \
      tests.test_core.DeadlineGovernorTests \
      tests.test_core.DeadlineGovernorWiringTests \
      tests.test_core.DeadlineGovernorCliTests \
      tests.test_core.RefusalClassificationTests \
      tests.test_core.SolverTimeoutSemanticsTests \
      tests.test_core.AllocatorSolverStatusTests \
      tests.test_core.SupervisorLostWindowTests \
      tests.test_core.PromotePointerCasTests \
      tests.test_core.DeferredPromotionTests \
      tests.test_core.RetroFactsTests \
      tests.test_upload_integrity.R96UnrecordedDeliveryTests \
      tests.test_upload_integrity.GateAssumptionVersusOverrideTests \
      tests.test_showdown.ShowdownSolverStatusTests -q

Result: **114 tests, OK**. This does not execute the entire production suite or the prototype's runtime-pinned end-to-end tests. No claim is made that an actual user-accessible CSV was delivered under injected deadline pressure. That remains the central implementation acceptance question:

> Did the operator receive a genuinely usable lineup or portfolio in time, without having to rescue the process manually?

### Pinned evidence index

[E01]: https://github.com/bleeski/mlb-dfs/blob/5b831655fdd2c12d0f4277cdbbfb1165b0c948c8/CLAUDE.md
[E02]: https://github.com/bleeski/mlb-dfs/blob/5b831655fdd2c12d0f4277cdbbfb1165b0c948c8/skills/generate-lineups/scripts/build_slate.py#L2275
[E03]: https://github.com/bleeski/mlb-dfs/blob/5b831655fdd2c12d0f4277cdbbfb1165b0c948c8/skills/generate-lineups/scripts/build_slate.py#L2540
[E04]: https://github.com/bleeski/mlb-dfs/blob/5b831655fdd2c12d0f4277cdbbfb1165b0c948c8/mlb_engine/pipeline/execution_pipeline.py#L4802
[E05]: https://github.com/bleeski/mlb-dfs/blob/5b831655fdd2c12d0f4277cdbbfb1165b0c948c8/mlb_engine/pipeline/execution_pipeline.py#L309
[E06]: https://github.com/bleeski/mlb-dfs/blob/5b831655fdd2c12d0f4277cdbbfb1165b0c948c8/mlb_engine/entries/upload_manifest.py#L385
[E07]: https://github.com/bleeski/mlb-dfs/blob/5b831655fdd2c12d0f4277cdbbfb1165b0c948c8/skills/generate-lineups/SKILL.md#L989
[E08]: https://github.com/bleeski/mlb-dfs/blob/5b831655fdd2c12d0f4277cdbbfb1165b0c948c8/skills/generate-lineups/scripts/build_slate.py#L3698
[E09]: https://github.com/bleeski/mlb-dfs/blob/5b831655fdd2c12d0f4277cdbbfb1165b0c948c8/mlb_engine/production/workflow.py#L233
[E10]: https://github.com/bleeski/mlb-dfs/blob/5b831655fdd2c12d0f4277cdbbfb1165b0c948c8/mlb_engine/pipeline/deadline_governor.py
[E11]: https://github.com/bleeski/mlb-dfs/blob/5b831655fdd2c12d0f4277cdbbfb1165b0c948c8/tools/autobuild.py#L478
[E12]: https://github.com/bleeski/mlb-dfs/blob/5b831655fdd2c12d0f4277cdbbfb1165b0c948c8/mlb_engine/entries/dk_entries_manager.py#L181
[E13]: https://github.com/bleeski/mlb-dfs/blob/5b831655fdd2c12d0f4277cdbbfb1165b0c948c8/mlb_engine/pipeline/execution_pipeline.py#L1248
[E14]: https://github.com/bleeski/mlb-dfs/blob/5b831655fdd2c12d0f4277cdbbfb1165b0c948c8/tools/autobuild.py#L674
[E15]: https://github.com/bleeski/mlb-dfs/blob/5b831655fdd2c12d0f4277cdbbfb1165b0c948c8/tools/preflight_upload.py#L736
[E16]: https://github.com/bleeski/mlb-dfs/blob/5b831655fdd2c12d0f4277cdbbfb1165b0c948c8/mlb_engine/allocate/contest_allocator.py#L3319
[E17]: https://github.com/bleeski/mlb-dfs/blob/5b831655fdd2c12d0f4277cdbbfb1165b0c948c8/skills/generate-lineups/scripts/build_slate.py#L2694
[E18]: https://github.com/bleeski/mlb-dfs/blob/5b831655fdd2c12d0f4277cdbbfb1165b0c948c8/tools/preflight_upload.py#L1496
[E19]: https://github.com/bleeski/mlb-dfs/blob/5b831655fdd2c12d0f4277cdbbfb1165b0c948c8/skills/generate-lineups/scripts/build_slate.py#L3137
[E20]: https://github.com/bleeski/mlb-dfs/blob/5b831655fdd2c12d0f4277cdbbfb1165b0c948c8/mlb_engine/entries/delivery_record.py#L244
[E21]: https://github.com/bleeski/mlb-dfs/blob/5b831655fdd2c12d0f4277cdbbfb1165b0c948c8/mlb_engine/entries/dk_entries_manager.py#L904
[E22]: https://github.com/bleeski/mlb-dfs/blob/5b831655fdd2c12d0f4277cdbbfb1165b0c948c8/skills/generate-lineups/scripts/build_slate.py#L2765
[E23]: https://github.com/bleeski/mlb-dfs/blob/5b831655fdd2c12d0f4277cdbbfb1165b0c948c8/skills/generate-lineups/scripts/build_slate.py#L218
[E24]: https://github.com/bleeski/mlb-dfs/blob/5b831655fdd2c12d0f4277cdbbfb1165b0c948c8/skills/generate-lineups/scripts/build_slate.py#L5315
[E25]: https://github.com/bleeski/mlb-dfs/blob/5b831655fdd2c12d0f4277cdbbfb1165b0c948c8/tests/test_core.py#L7454
[E26]: https://github.com/bleeski/mlb-dfs/blob/5b831655fdd2c12d0f4277cdbbfb1165b0c948c8/mlb_engine/pipeline/build_state_manager.py#L386
[E27]: https://github.com/bleeski/mlb-dfs/blob/5b831655fdd2c12d0f4277cdbbfb1165b0c948c8/tools/late_swap.py#L783
[E28]: https://github.com/bleeski/mlb-dfs/blob/5b831655fdd2c12d0f4277cdbbfb1165b0c948c8/tools/retro.py#L121
[E29]: https://github.com/bleeski/mlb-dfs/blob/5b831655fdd2c12d0f4277cdbbfb1165b0c948c8/CHANGELOG.md#L5794
[E30]: https://github.com/bleeski/mlb-dfs/blob/5b831655fdd2c12d0f4277cdbbfb1165b0c948c8/docs/backlog.md#L4757
[E31]: https://github.com/bleeski/mlb-dfs/blob/5b831655fdd2c12d0f4277cdbbfb1165b0c948c8/docs/backlog.md#L7887
[E32]: https://github.com/bleeski/mlb-dfs/blob/5b831655fdd2c12d0f4277cdbbfb1165b0c948c8/docs/backlog.md#L8057
[R01]: https://github.com/bleeski/mlb-dfs/blob/5b831655fdd2c12d0f4277cdbbfb1165b0c948c8/data/deliveries/2026-09-19/2110_2g_20260920T005753Z_e40c1f01.json
[R02]: https://github.com/bleeski/mlb-dfs/blob/5b831655fdd2c12d0f4277cdbbfb1165b0c948c8/data/deliveries/2026-09-19/2138_1g_sd_norun.json
[R03]: https://github.com/bleeski/mlb-dfs/blob/5b831655fdd2c12d0f4277cdbbfb1165b0c948c8/data/deliveries/2026-09-20/1607_4g_20260920T193659Z_072d85b2.json
[R04]: https://github.com/bleeski/mlb-dfs/blob/5b831655fdd2c12d0f4277cdbbfb1165b0c948c8/data/deliveries/2026-09-20/1607_4g_20260920T193713Z_1a1f5c58.json
