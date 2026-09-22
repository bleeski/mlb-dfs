# MLB DFS System Greenfield Specification — 2026-09-03

**Audit date:** 2026-09-03  
**Repository:** `C:\Users\benja\Documents\Claude\mlb-dfs`  
**Audited revision:** `92cd423e735c612cda3973e55afef06d9ec8b556` (`main`, equal to the locally cached `origin/main`)  
**Comparison baseline:** `docs/2026-09-02_critique_greenfield_spec_ed10.md` at `32cdd32`  
**Deliverable status:** read-only analysis; this dated file is the only intended repository change from this audit

## Executive determination

The repository is not a zero-touch, EV-optimizing production system today. It is a large, evidence-conscious deterministic lineup-construction system with a correct-looking SciPy/HiGHS MILP core, strong immutable-run and exact-export ideas, and unusually explicit honesty rules. Its primary risk is no longer the basic roster formulation. Its risk is the network of duplicated readers, exception-prone handoffs, ladder semantics, stale evidence selection, and operator procedures around that formulation.

The current Classic path can produce structurally certified files when its pinned runtime is present. The current checkout could not be dynamically certified in this Windows runtime: `python -B tools/env_probe.py` reported missing `numpy`, `pandas`, and `scipy`, and `scipy.optimize.milp` was unavailable. The non-test audit consequently returned `FAIL dependencies`; the requested test audit could not establish a green suite. That is an environment finding, not evidence that the code tests fail under the pinned Python 3.10/Linux runtime. It does mean this report makes no current clean-runtime claim.

Showdown remains explicitly `review_grade_build`, outside the three Classic certification gates and outside the certified late-swap path (`CLAUDE.md:699-726`; `skills/generate-lineups/scripts/build_slate.py:3634-3648`). This is honest, but it is not production parity.

No current model output is demonstrated expected value, ROI, win probability, cash probability, or profit. `Base`, `Ceiling`, contest-fit scores, ownership, and field-pressure values are deterministic proxies or priors. The name `Portfolio_EV_Proxy` in `mlb_engine/optimize/optimizer_v3.py:3746-3750` is therefore itself a labeling defect. Until replay settlement, calibrated outcome distributions, a contest-conditioned field model, and exact payout/tie handling exist, the only truthful target is **maximum deterministic contest-fit proxy under hard legality and evidence gates**.

“Zero-touch” is bounded by the platform boundary. DraftKings' current US fair-play guidance says browser scripts and bots are prohibited, while its official bulk-lineup workflow requires a user to upload the CSV in a desktop browser. Therefore this specification automates everything from two manually supplied DraftKings files to a validated, hash-bound decision package, and everything from new evidence to a revised package; it does not automate website interaction, contest entry, lineup editing, or upload. See [DraftKings Fair Play Commitment](https://help.draftkings.com/hc/en-us/articles/4405223983635-Fantasy-Sports-Fair-Play-Commitment-US), [DraftKings US Daily Fantasy Terms, updated 2026-06-30](https://sportsbook.draftkings.com/legal/us-terms-of-use), and [DraftKings CSV upload instructions](https://help.draftkings.com/hc/en-us/articles/4405223998867-How-do-I-upload-or-edit-multiple-lineups-at-once-US).

### What changed after the 2026-09-02 review

The 8,343 inserted lines between `32cdd32` and `92cd423` materially changed the verdict. The following earlier findings were re-read and are **closed at the audited revision**, so they are not repeated as live defects below:

| Commit | Verified repair |
|---|---|
| `03fab89` / R291 | `Excluded` now survives Classic frame assembly, bank hashing, Showdown melt, and late swap; the earlier `GF10-I1` and `GF10-D2` blockers are closed. |
| `924bb4f` / R292 | `repair_entry.py` writes one valid table, refuses already-started replacements, and sibling tools share the clock parser; earlier `GF10-T1`, `GF10-T2`, `GF10-T3`, and `GF10-T4` are closed. |
| `cdd42ab` / R296 | malformed JSON/argument inputs are classified before expensive work, autobuild records off-contract exits, and its decision log is made durable; the old T8–T13 cluster is substantially closed. |
| `f2a1712`, `4a7f79d` / R290(c) | a deadline governor, two-rung policy, correct refusal classification, and the 130-second solver-probe budget landed. |
| `92cd423` / R293 | candidate augmentation skips an arm's opponent rather than his own team, anti-correlation reaches both bank routes, and the brief reports the applied value rather than the requested value; earlier `GF10-S1` and `GF10-S2` are closed. |

### Scope and method

The tracked working tree had 1,088 visible files, including 73 Python files. Recursive inventory, including generated and ignored evidence, counted 111 files under `mlb_engine/`, 81 under `tools/`, 33 under `tests/`, 58 under `skills/`, 1,833 under `data/`, 3,534 under `runs/`, and 7,874 under `outputs/`. The data tree alone was about 213 MB. Every visible code/config/document path was inventoried; Python sources in the production/audit scope were syntax-compiled by `tools/audit.py`; schemas and current contracts were traced at their producers and consumers; data and run trees were inspected by structure, manifest, header, count, and targeted sampling rather than pretending that reading every archived byte is useful static analysis.

The working tree already contained three modified reference files and many untracked handoff, log, source, and ledger files. They were treated as user-owned inputs and were not reset, staged, rewritten, or deleted. Findings below cite the current file and current line at `92cd423`, not the September 2 line numbers.

# Section 1: Repository Map, Data Flow, and Solver Formulations

## 1.1 Repository and ownership map

| Surface | Intended owner | Current role | Audit assessment |
|---|---|---|---|
| `CLAUDE.md` | global contract | authority, truth labels, clocks, task roles, money/DK walls | Correct principles mixed with incident history; 763 lines / 51,325 bytes. |
| `MLB_Classic.md` | Classic strategy | scoring, factors, construction, certification interpretation | Valuable model reference; several stale version/source statements remain. |
| `MANIFEST.md` | repository inventory | expected layout and gate line | Stale: still says 12 modules / 119 tests at lines 10, 59, and 73 while the live contract says 28 / 1,768. |
| `skills/generate-lineups/SKILL.md` | operator procedure | intake, build, clock, QA, upload handoff | 1,263 lines / 71,956 bytes; duplicates policy and contains live contradictions. |
| `skills/generate-lineups/scripts/build_slate.py` | command front door | Classic and Showdown orchestration, brief construction, delivery | 4,722-line god script with multiple status/brief shapes and too many policy decisions. |
| `mlb_engine/intake/` | deterministic intake | salary/entries parsing, lineup/odds/reference normalization | Good fail-closed intent, but duplicated token/clock/source-selection rules remain. |
| `mlb_engine/projections/projection_builder.py` | projection frame | Base/Floor/Ceiling and factor assembly | Present model is APPG-centered and heuristic, not calibrated outcome prediction. |
| `mlb_engine/optimize/optimizer_v3.py` | Classic optimizer | single-lineup MILP, candidate-bank generation, candidate scoring | Core formulation is coherent; cache signatures, optional fields, and combinatorial generation remain fragile. |
| `mlb_engine/optimize/showdown.py` | Showdown optimizer | salary melt, 1-CPT/5-UTIL MILP, byte export, local certification | Small coherent MILP; identity key and surrounding ladder are unsafe. |
| `mlb_engine/optimize/showdown_theses.py` | Showdown strategy ladder | thesis-weighted objectives, exposure/relaxation sequence | Sequential construction creates order-dependent cap behavior and inconsistent score scales. |
| `mlb_engine/allocate/contest_allocator.py` | portfolio optimizer | entry×candidate MILP, contest compatibility, exposure/overlap/reuse caps | Correct architectural location; prefilter and status/relaxation semantics can change strategy incorrectly. |
| `mlb_engine/pipeline/execution_pipeline.py` | governed workflow | immutable runs, gates, export, validation, promotion, manifest facts | Strong central seam, but exception lifecycle and evidence summaries are incomplete. |
| `mlb_engine/pipeline/build_state_manager.py` | run state | run creation, input snapshots, artifact hashes, certification state | Atomic manifest writes are good; callers can strand `building` runs. |
| `mlb_engine/entries/dk_entries_manager.py` | exact entry contract | template preservation, salary/roster/cap validation, certification | Most important referee; empty salary pool currently disables its checks. |
| `mlb_engine/entries/upload_manifest.py` | delivery index | delivery record, supersession, status stamping | Atomic per-write, but unlocked read-modify-write allows concurrent lost updates. |
| `tools/preflight_upload.py` / `tools/verify_export.py` | independent byte referee | external-file validation, clocks, manifest/status checks | Valuable second check; live Showdown and evidence-resolution bugs remain. |
| `tools/autobuild.py` | bounded supervisor | retries, bank growth, structural remedies | Better after R296, but still parses one incomplete brief shape and misses explicit BANK-LIMITED refusals. |
| `mlb_engine/field/` | post-contest learning | standings parsing, field summaries, contest registry | Evidence foundation exists; settlement and Showdown identity are not exact enough for EV claims. |
| `tests/` | executable contract | five pinned suites, golden replay, mutations | Large suite with valuable counterfactual tests, but substantial source-string/prose coupling and live-data coupling. |
| `data/`, `runs/`, `outputs/`, `ledger/` | evidence and artifacts | snapshots, references, run manifests, delivered files, learning record | Rich evidence base; mixed mutable/date-global indexes create concurrency and provenance risk. |

## 1.2 Current end-to-end data flow

```text
Manual DraftKings download
  DKSalaries*.csv + DKEntries*.csv
              |
              v
tools/stage_slate.py / build_slate.py
  - infer Classic vs Showdown from entry geometry
  - parse game/date/lock identity
  - hash or copy inputs into data/slates/<date>/ and runs/<run_id>/inputs/
              |
              +-----------------------------+
              | optional evidence           |
              | lineups paste / DK Starting |
              | StatsAPI / boxscore         |
              | odds / weather / Savant     |
              | FanGraphs / StatsAPI refs   |
              +-----------------------------+
              |
              v
live_data_adapters.build_slate_pool (Classic)
or showdown.melt_showdown_salary_csv (Showdown)
              |
              v
projection_builder + execution_pipeline assembly
  Base -> F1..F5 / Floor / Ceiling / ownership prior / exclusions
              |
              +--> optimizer_v3 candidate bank (Classic)
              |      repeated single-lineup MILPs + cache
              |
              +--> showdown_theses ladder (Showdown)
                     thesis-weighted repeated MILPs
              |
              v
contest_allocator.select_and_assign_entries (Classic)
  joint entry x candidate MILP, fixed late-swap rows, caps, overlap, reuse
              |
              v
dk_entries_manager writes candidate from original template
  -> validates exact candidate bytes
  -> promotes immutable run if all three gates hold
  -> mirrors delivery into outputs/<date>/
  -> upload_manifest.json + build_brief*.json
              |
              v
preflight_upload.py + verify_export.py + qa_portfolio.py
              |
              v
Manual DraftKings CSV upload
              |
              v
Contest standings CSV -> field_miner -> ledger / future replay
```

The production Classic front door is `execution_pipeline.run_slate` (`mlb_engine/pipeline/execution_pipeline.py:4383`), invoked by `run_classic` (`skills/generate-lineups/scripts/build_slate.py:2027`). The entry-level portfolio path begins at `execute_portfolio` (`execution_pipeline.py:309`) and `select_and_assign_entries` (`contest_allocator.py:2359`). Late swap is a separate path at `execution_pipeline.py:678` plus `tools/late_swap.py:437`. Showdown bypasses those gates through `run_showdown` (`build_slate.py:3203`).

## 1.3 Current contracts and schemas

### DKSalaries

The actual input has `Position, Name + ID, Name, ID, Roster Position, Salary, Game Info, TeamAbbrev, AvgPointsPerGame, Status, Starting` plus an optional operator `Excluded` column. DraftKings is authoritative for numeric ID, salary, team, eligibility, slate membership, and the `Game Info` clock. Classic rows use roster positions `P/C/1B/2B/3B/SS/OF`; Showdown rows use `CPT/UTIL`, with two priced rows per person.

### DKEntries

Columns 0–3 are `Entry ID, Contest Name, Contest ID, Entry Fee`. The roster window is detected from the header: ten Classic slots `P,P,C,1B,2B,3B,SS,OF,OF,OF`, or six Showdown slots `CPT,UTIL,UTIL,UTIL,UTIL,UTIL`. The writer must preserve row count and every non-roster byte-equivalent cell, fill only authorized reserved rows, and write bare DraftKings IDs into roster cells.

### Run and delivery evidence

`build_state_manager.create_run` creates `inputs/`, `candidate/`, and `final/`, stamps runtime and lock hashes, and starts the manifest in `status: building` (`mlb_engine/pipeline/build_state_manager.py:98-137`). Promotion binds exact hashes and certification. `upload_manifest.json` is a date-level delivery index; `build_brief*.json` is the operator summary. The immutable run is evidence; the mirror and brief are indexes into that evidence and must never be more authoritative than it.

### Current certification vocabulary

Classic certification requires the derived workflow gates, projection schema, optimizer preflight, selection certification, allocation certification, and all post-export checks: template preservation, entry reconciliation, roster legality, portfolio caps, locked immutability, and final-hash binding (`mlb_engine/entries/dk_entries_manager.py:1113-1132`). A gate failure is `DO_NOT_UPLOAD`/not certified even when the bytes are structurally legal. Showdown does not currently enter this state machine.

## 1.4 Current mathematical formulation

Let player-persons be `p`, roster slots `s`, games `g`, teams `t`, requested entries `e`, and generated candidate lineups `k`. `c_p` is salary and `v_p` is a deterministic point/ceiling/floor proxy.

### Classic single-lineup MILP

`optimizer_v3._build_single_lineup_scipy` starts at line 857. Its essential formulation is:

```text
x[p,s] in {0,1}       player p occupies eligible slot s
y[g]   in {0,1}       game g is represented
u[t]   in {0,1}       team t supplies the requested primary stack

maximize  sum[p,s] v[p] x[p,s] + deterministic tie-break / suppression terms

subject to
  sum[s] x[p,s] <= 1                                  every person at most once
  sum[p] x[p,s]  = 1                                  every slot exactly once
  sum[p,s] c[p] x[p,s] <= 50,000                      salary cap
  sum[p in hitters(t),s] x[p,s] <= 5                  maximum five hitters/team
  y[g] <= sum[p in g,s] x[p,s]                        represented-game implication
  sum[g] y[g] >= 2                                    at least two games
  M x[sp] + sum[h in opponent(sp)] x[h] <= M + q      at most q hitters vs rostered SP
  sum[h in t] x[h] >= m u[t],  sum[t] u[t] >= 1       primary stack
  optional secondary stack / bring-back rows
  x[p] = 1 for locks; x[p] = 0 for excludes/OUT/operator Excluded
  sum[p in L_j] x[p] <= |L_j|-1                       exact-roster no-good cut
```

The formulation is structurally sound. The important correctness distinction is that `v_p` is not a random variable and the objective is not expected payout.

### Classic candidate generation

`build_diverse_candidate_bank` (`optimizer_v3.py:4079`) repeatedly solves the single-lineup MILP under seeded perturbations, forced SP-pair/stack jobs, and no-good or overlap rows, storing candidates in `bank_cache.py`. The current cost grows because each new overlap row enlarges the branch-and-bound problem and because model construction is repeated. Candidate generation should only spend search effort; it may never alter the legal player pool or silently loosen strategy controls.

### Entry-level portfolio MILP

`select_and_assign_entries` (`contest_allocator.py:2359`) uses binary `a[e,k]` and optional `z[k]`:

```text
maximize  sum[e,k] score[e,k] a[e,k]

subject to
  sum[k] a[e,k] = 1                                      one candidate per entry
  a[e,k] = 0                                             if entry e is incompatible with k
  a[e,k] <= z[k], z[k] <= sum[e] a[e,k]                 candidate-used linkage
  sum[e,k containing p] a[e,k] <= floor(alpha[p] * N)   player/pitcher exposure
  analogous rows for stack, game, and SP-pair caps
  sum[e in contest C] a[e,k] <= 1                       no duplicate roster in a contest
  z[i] + z[j] <= 1 when |L_i intersect L_j| > overlap   portfolio overlap
  sum[e] a[e,k] <= reuse_cap                             candidate reuse
```

This is the right place to optimize the entered portfolio. The prefilter must preserve per-entry compatibility and every active lower-bound/cap opportunity; solver statuses must be classified before any relaxation ladder runs.

### Showdown MILP

`showdown.build_showdown_lineup` starts at `mlb_engine/optimize/showdown.py:382`:

```text
cpt[p], util[p] in {0,1}

maximize  sum[p] (1.5 v[p] cpt[p] + v[p] util[p])

subject to
  sum[p] cpt[p] = 1
  sum[p] util[p] = 5
  cpt[p] + util[p] <= 1
  sum[p] (salary_CPT[p] cpt[p] + salary_UTIL[p] util[p]) <= 50,000
  each team contributes at least one person
  locks, role excludes, prior-lineup overlap, and no-good rows
```

The local MILP is straightforward. The defect surface is the sequential thesis ladder surrounding it: player/captain exposure is enforced by mutating excludes from already-built lineups, so arrival order, holds, locks, and relaxation order affect the realized portfolio.

# Section 2: Current Code Review and Defect Log

## 2.1 Severity and disposition summary

| ID | Severity | Surface | Status at `92cd423` |
|---|---|---|---|
| D01 | Blocker | empty-salary referee fail-open | verified live |
| D02 | Blocker | unrestricted supplied workflow-gate override | verified live |
| D03 | P1 | run can remain `building` after exception/kill | verified live; 18 artifacts observed |
| D04 | P1 | allocator prefilter ignores per-entry compatibility | verified live; board R294 |
| D05 | P1 | SciPy status 3/4 treated as proven infeasible | verified live; board R294 |
| D06 | P1/performance | relaxation re-solves after slate-level failure | verified live; board R294 |
| D07 | P1 | Showdown captain hold collides with thesis lock | verified live; board R295 |
| D08 | P1 | Showdown weighted proxies compared on one scale | verified live; board R295 |
| D09 | P2/performance | Showdown ladder repeats an identical solve | verified live; board R295 |
| D10 | P1 plausible | Showdown person identity merges namesakes | verified code path; board R295 |
| D11 | P1 | declared-pitcher exception is impossible in Showdown | verified live on 2026-09-03 |
| D12 | P1 | preflight auto-selects another slate's feed | verified live on 2026-09-03 |
| D13 | P1/autonomy | autobuild stops on explicit BANK-LIMITED refusal | verified live on 2026-09-03 |
| D14 | P2 | manifest omits allocator relaxation evidence | verified live; board R298 |
| D15 | P2 | certified Classic brief omits mirror durability facts | verified live; board R298 |
| D16 | P1 | ownership prior may cross draftgroups | verified live; board R298 |
| D17 | P2 | preflight JSON can say `passed:true` after read-back failure | verified live; board R297 |
| D18 | P1 | bank cache ignores leverage inputs | verified live; board R290(a) |
| D19 | P1 | forbidden core shrinks into a stricter constraint | verified live |
| D20 | P2 | optional projection columns are required by late helpers | verified live |
| D21–D26 | P1/P2 | date, token, HTTP, APPG, team-code, and odds intake seams | verified live |
| D27–D29 | P1/P2 | audit gate, durable state, and archive ingestion | verified live |
| D30 | P1 | field-miner identity and winner settlement are inexact | verified live |
| D31 | P1/model | EV label without an EV estimator | verified live |
| D32 | P1/product | Showdown outside certification/late swap | declared current limitation |
| D33 | P2 | deterministic hash seed is bypassed by wrapper | verified live |
| D34 | P1/environment | audited runtime lacks pinned solver dependencies | measured current runtime |
| D35 | P2/operations | auditable odds fallback stops before structured browser extraction | verified 2026-09-03 |

“Blocker” here means the defect can invalidate the system's own hard evidence or certification claim. P1 means a money-adjacent wrong result, lost lock window, or material strategy distortion. P2 means important durability, diagnostic, or restricted-slate correctness. A board item is evidence and prioritization, not proof; each current item below was re-read against the code at the audited revision.

## 2.2 Certification and lifecycle defects

### D01 — empty salary pool disables the independent validator

**Location:** `mlb_engine/entries/dk_entries_manager.py:863-971`  
**Severity:** Blocker  
**Root cause:** `allowed_ids` is empty when a supplied salary file parses zero rows (`:884-887`), and both membership and all salary/position/team/game legality checks are guarded by `if allowed_ids` or `if players` (`:937`, `:955-971`). Ten distinct arbitrary IDs can therefore pass this referee. `run_slate` usually has an earlier salary gate, but direct `execute_portfolio`, `populate_dk_entries_template`, and ad-hoc validation remain exposed.

**Production remediation:** fail closed on a supplied-but-empty authority and on an empty membership universe.

```python
players: dict[str, SalaryPlayer] = {}
if salary_csv_path is not None:
    players = {p.player_id: p for p in parse_dk_salary_csv(str(salary_csv_path))}
    if not players:
        return {
            "passed": False,
            "errors": [f"salary file {salary_csv_path} yielded zero valid players"],
            "warnings": [],
            "roster_legality_passed": False,
        }

allowed_ids = set(players) if players else {
    normalize_player_id(x) for x in (salary_player_ids or [])
}
if not allowed_ids:
    errors.append("no salary/player-id authority supplied; membership cannot be graded")
```

Acceptance test: a valid Classic entries header plus ten arbitrary IDs and a header-only salary CSV must fail with `roster_legality_passed=False`.

### D02 — caller-supplied gates override derived false values without the override policy

**Location:** `mlb_engine/pipeline/execution_pipeline.py:1029-1118, 4674-4696`; `tools/build_asserted.py:43-64, 79-95`  
**Severity:** Blocker  
**Root cause:** `resolve_gate_assertions` correctly limits `assume_gates` overrides to `lineup_gate_passed`, but line 1098 independently merges `supplied` over every `gate_default`. `build_asserted.py` accepts all six derived names and injects them through that unrestricted `workflow_gates` door. A caller can therefore turn a derived salary, entry-grid, pitcher, weather, or odds false into true while the nearby `OVERRIDABLE_GATES` contract claims that is impossible.

**Production remediation:** make one merge function own both `supplied` and `assume_gates`; reject any contradiction outside the one authorized gate.

```python
gates = dict(gate_defaults)
supplied_records = []
for name, value in dict(supplied or {}).items():
    if name not in gates:
        raise ValueError(f"unknown workflow gate: {name}")
    derived = gate_defaults.get(name)
    if bool(value) and derived is False and name not in OVERRIDABLE_GATES:
        raise ValueError(
            f"{name} is derived false and cannot be caller-overridden; fix its input"
        )
    gates[name] = bool(value)
    supplied_records.append({"gate": name, "derived": derived, "supplied": bool(value)})
```

Then restrict `build_asserted.VALID_GATES` to the genuinely assumable/overridable set or remove the wrapper. Mutation test: force `validate_salary_export` false, assert that `--assert-gate salary_gate_passed` cannot produce `workflow_valid=True`.

### D03 — exceptions strand immutable runs in an active state

**Location:** `mlb_engine/pipeline/execution_pipeline.py:309-448`; `mlb_engine/pipeline/build_state_manager.py:98-137`  
**Severity:** P1  
**Root cause:** `create_run` persists `status: building` before input snapshots, projection materialization, allocation, and validation. Those operations can raise before `_blocked_result` is reached. The audit found 18 manifests still marked `building`, all with empty `errors`; the newest were dated 2026-08-29. Some may be killed processes rather than Python exceptions, but both cases are terminal artifacts that look in-flight forever.

**Production remediation:** give each run a lease/heartbeat and wrap every post-create path in a terminalizer.

```python
run = create_run(...)
try:
    return _execute_created_run(run, ...)
except BaseException as exc:
    mark_run_terminal(
        run["run_dir"],
        status="crashed",
        errors=[f"{type(exc).__name__}: {exc}"],
        metadata={"traceback": traceback.format_exc(limit=40)},
    )
    raise
```

At startup, mark `building` runs with an expired PID/lease as `abandoned`, never silently delete them. Acceptance: inject an exception at each call after `create_run`; every manifest ends `blocked`, `crashed`, or `abandoned`, never `building`.

### D14 — delivery strategy state cannot see allocator relaxations

**Location:** `mlb_engine/pipeline/execution_pipeline.py:5103-5165`; producer fields at `mlb_engine/allocate/contest_allocator.py:3113-3117, 3162-3253`  
**Severity:** P2  
**Root cause:** `manifest_strategy_state` inspects only `bank_diagnostics` and `candidate_bank`. Classic allocator relaxations live at top-level `candidate_reuse`, `primary_stack_floor`, and `five_stack_quota`. On the production candidate-override path the inspected holders contain no relaxation block, so a relaxed portfolio reports `unknown/absent` instead of the exact counts.

**Production remediation:** normalize relaxation evidence at the allocator boundary and require it at delivery.

```python
def allocation_relaxations(result: Mapping[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for key in ("candidate_reuse", "primary_stack_floor", "five_stack_quota"):
        block = result.get(key)
        if not isinstance(block, Mapping):
            continue
        n = int(block.get("relaxations") or len(block.get("relaxation_steps") or []))
        if n:
            counts[key] = n
    return counts

# execute_portfolio result
result["strategy_relaxations"] = allocation_relaxations(allocation)
```

`manifest_strategy_state` should read only `strategy_relaxations`; missing evidence on a purportedly certified Classic delivery must block the `clean` label.

### D15 — Classic brief does not disclose mirror/manifest durability failure

**Location:** `skills/generate-lineups/scripts/build_slate.py:2724-2760` versus Showdown `:3634-3650`  
**Severity:** P2  
**Root cause:** the Classic brief can say `status: certified` and point to a run-final fallback while omitting `mirror_error`, `delivered_sha256_error`, and `manifest_recorded`. The Showdown brief already records the manifest outcome. Certification and delivery durability are different facts and must both be visible.

**Production remediation:** add the durability block to both modes and reserve `certified` for a recorded delivery.

```python
delivery = {
    "mirror_error": result.get("mirror_error"),
    "delivered_sha256_error": result.get("delivered_sha256_error"),
    "manifest_recorded": bool(result.get("manifest_recorded")),
}
brief["delivery"] = delivery
if checks["passed"] and not delivery["manifest_recorded"]:
    brief["status"] = "certified_unrecorded"
```

### D17 — post-readback failure does not update `report.passed`

**Location:** `tools/preflight_upload.py:2174-2181, 2289-2323`  
**Severity:** P2  
**Root cause:** `report["passed"]` is frozen before the manifest write/readback. Lines 2310-2320 can add a hard failure and change the verdict/exit code, but never recompute `passed`. JSON can therefore contain `passed: true`, `verdict: blocked`, and a nonzero exit.

**Production remediation:** finalize once, after every check and durable write.

```python
# immediately before rendering
report["failures"] = list(rep.failures)
report["warnings"] = list(rep.warnings)
report["passed"] = not report["failures"]
report["verdict"] = final_verdict(report, force=args.force)
code = verdict_exit_code(report["failures"], args.force)
```

One test must force manifest readback failure and assert all three surfaces agree.

## 2.3 Optimizer and allocator defects

### D04 — compatibility-blind candidate prefilter changes strategy

**Location:** `mlb_engine/allocate/contest_allocator.py:1074-1149, 2632-2670`  
**Severity:** P1  
**Root cause:** the prefilter preserves a candidate only when it is an entry's sole compatible option, then spends the budget on one representative per stack/SP pair and global shape score. It can discard every one of two or more compatible floor-qualified options for an entry while retaining candidates incompatible with every entry. The MILP then “proves” the reduced problem infeasible and the reuse/quota/floor ladders loosen controls against a full bank that was feasible.

**Production remediation:** prefilter the selectable union, keep at least two compatible candidates per entry, and retry the unfiltered bank before any strategy relaxation or “proven infeasible” claim.

```python
selectable = {k for k in range(K) if any(compatible[e][k] for e in range(E))}
keep: set[int] = set()
for e in range(E):
    ranked = sorted(
        (k for k in selectable if compatible[e][k]),
        key=lambda k: (-entry_shape_score(entries[e], candidates[k]),
                       _candidate_id(candidates[k], k)),
    )
    keep.update(ranked[:2])

# spend the remaining budget only on selectable candidates
for k in order:
    if k in selectable and len(keep) < keep_target:
        keep.add(k)

emptied = [entry_ids[e] for e in range(E)
           if not any(compatible[e][k] for k in keep)]
assert not emptied
```

Acceptance: the R294 60-candidate fixture assigns two size-four stacks with zero relaxations.

### D05 — non-proof solver states drive proof-only behavior

**Location:** `mlb_engine/allocate/contest_allocator.py:2923-3118`  
**Severity:** P1  
**Root cause:** only status 1 is treated as time-limited. Any other no-incumbent result enters infeasibility diagnostics and the three relaxation ladders. SciPy/HiGHS status 2 means infeasible; status 3 is unbounded and status 4 is other/numerical failure. Neither 3 nor 4 proves infeasibility.

**Production remediation:** use an explicit state machine.

```python
status = int(getattr(result, "status", 4))
proven_infeasible = status == 2
timed_out = status == 1
solver_fault = status in {3, 4}

if incumbent is None and solver_fault:
    return refusal(
        kind="solver_fault",
        errors=[f"joint MILP returned scipy status {status}; no infeasibility proof"],
        relaxations_attempted=0,
    )
```

Every ladder guard must require `proven_infeasible` rather than merely `not timed_out`.

### D06 — impossible slate checks still trigger up to seven allocation solves

**Location:** `contest_allocator.py:2935-3100`; helper invariant `:833-944`  
**Severity:** P1/performance  
**Root cause:** the reuse, five-stack-quota, and primary-stack-floor re-entry guards do not consult `failing_feasibility_checks(feasibility_checks)`. Those checks are slate-level structural facts that none of the ladders changes. A refused build can spend the lock window re-solving the same impossible slate.

**Production remediation:** terminate before entering any ladder.

```python
slate_failures = failing_feasibility_checks(feasibility_checks)
if incumbent is None and slate_failures:
    return refusal(
        kind="slate_infeasible",
        errors=compose_slate_failure_errors(slate_failures),
        relaxations_attempted=0,
    )

if proven_infeasible and not slate_failures:
    return run_documented_relaxation_ladder(...)
```

### D07 — Showdown captain reservation can force the player cap off

**Location:** `mlb_engine/optimize/showdown_theses.py:1091-1126, 1261-1334`  
**Severity:** P1  
**Root cause:** a player held out of UTIL to preserve future captain capacity may also be locked into the current thesis while a different player is `cpt_lock`. The lock needs `cpt_X + util_X >= 1`, the hold imposes `util_X = 0`, and the other captain lock imposes `cpt_Y = 1`: the first rungs are artificially infeasible. Rung three drops the whole player cap and hold, producing realized exposure above the requested 50% cap.

**Production remediation:** a current thesis lock outranks a future hold, and hold-only relaxation gets its own recorded rung.

```python
current_locks = set(locks)
util_blocked = [
    k for k, held in reserved_remaining.items()
    if held > 0
    and k not in current_locks
    and player_counts.get(k, 0) >= player_cap - held
]

# after the ordinary capped rung, before dropping the player cap
if lu is None and not latch["timed_out"] and util_blocked:
    lu = _rung(..., excludes=with_cap, util_excludes=None)
    if lu is not None:
        hold_relaxed += 1
```

The clean verdict must require `hold_relaxed == 0`.

### D08 — Showdown degraded-lineup detector compares different units

**Location:** `mlb_engine/optimize/showdown.py:563-649`; `showdown_theses.py:1140-1191, 1763-1791`; consumer in `build_slate.py:3631-3632`  
**Severity:** P1  
**Root cause:** each thesis mutates the frame's Base values (for example, suppressing the opposing side or all bats), and `proj_points` is calculated from that mutated frame. The degraded detector compares those numbers across theses as though they share one scale. A correct blowout/duel lineup can be flagged as 25% below the portfolio median by construction.

**Production remediation:** preserve both units and use only unweighted points for cross-thesis comparison.

```python
base = dict(zip(original_df["Player_Key"], original_df["Base"]))
cpt_key = lu["captain"]["player_key"]
util_keys = [p["player_key"] for p in lu["players"] if p["role"] == "UTIL"]
lu["proxy_points_thesis_weighted"] = lu.pop("proj_points")
lu["proxy_points_base"] = 1.5 * base[cpt_key] + sum(base[k] for k in util_keys)
```

### D09 — rung five can duplicate rung one

**Location:** `showdown_theses.py:1335-1341`  
**Severity:** P2/performance  
**Root cause:** the captain-lock relaxation rung runs even when `cpt_lock` was already cleared by a cap reassignment. Its arguments then duplicate the first rung and can repay the full eight-second time limit; it may also record a lock relaxation where no lock existed.

**Production remediation:** add `and cpt_lock` to the solve and the accounting guard.

```python
if lu is None and not latch["timed_out"] and cpt_lock:
    lu = _rung(...)
    if lu is not None:
        cpt_relaxed += _record_lock_relaxation(thesis, lu)
```

### D10 — Showdown identity is `(Name, Team)` instead of a person ID

**Location:** `mlb_engine/optimize/showdown.py:206-267`  
**Severity:** P1 plausible  
**Root cause:** `key = (name, team)` merges two distinct players with the same displayed name on one team, with last-writer-wins CPT/UTIL IDs and salary. The output's `Player_Key` repeats the same weak identity, so the local certification cannot discover the merge.

**Production remediation:** pair the CPT and UTIL rows by a stable person identity. If DraftKings supplies different role IDs without a person ID, use an explicit composite and refuse ambiguous duplicates.

```python
person_key = (normalize_name(name), team, str(r.get("Position") or "").upper())
if person_key in by_key and by_key[person_key]["Name"] != name:
    raise ValueError(f"ambiguous Showdown person identity: {person_key}")
```

Best solution: persist a reviewed `draftable_id -> person_id` relation at intake and use `person_id` everywhere.

### D18 — bank cache reuses candidates across leverage questions

**Location:** `mlb_engine/optimize/bank_cache.py:540-620, 635-658, 661-890`  
**Severity:** P1  
**Root cause:** leverage controls change the solver matrix but are absent from `conditions_signature`; `Projected_Ownership_Pct`, the value those controls read, is absent from `_PROJECTION_COLUMNS`. A cached bank built under one ownership vector/cap can be reused under another without invalidation.

**Production remediation:** version the signature and include canonical typed values.

```python
_PROJECTION_COLUMNS = (
    "Player_ID", "Ceiling", "Floor", "Base", "Salary", "Excluded",
    "Projected_Ownership_Pct",
)

def conditions_signature(..., leverage=None) -> str:
    digest.update(b"v3\n")
    for key in LEVERAGE_KEYS:
        digest.update(f"{key}={canonical_number((leverage or {}).get(key))}\n".encode())
    digest.update(_projection_bytes(canonical_projection_frame(df)))
    return digest.hexdigest()[:16]
```

Invalidate old entries explicitly; do not let a v2 key appear valid under v3.

### D19 — partial forbidden cores become stricter after exclusions

**Location:** `mlb_engine/optimize/optimizer_v3.py:1129-1144`  
**Severity:** P1  
**Root cause:** `_known_pids(core)` drops members absent from the active pool, then sets the upper bound to `len(pids)-1`. A forbidden three-player core with only one survivor becomes `x_survivor <= 0`, excluding the survivor even though the original forbidden combination is impossible.

**Production remediation:** only emit the row when every member is present.

```python
for core in stack_core_blocklist or ():
    original = tuple(dict.fromkeys(normalize_player_id(x) for x in core))
    present = _known_pids(original)
    if len(present) == len(original) and present:
        add_selected_sum_constraint(present, -np.inf, len(present) - 1)
```

### D20 — “optional” columns can crash post-solve helpers

**Location:** `optimizer_v3.py:451-453, 1481-1501, 2164-2177`  
**Severity:** P2  
**Root cause:** schema metadata treats `Ownership_Tier` and `Notes` as optional, while one-off classification indexes both columns unconditionally. A lean frame can pay for the bank and then crash in reporting/signature code.

**Production remediation:** choose one contract. Recommended: normalize optional columns once at the frame boundary.

```python
OPTIONAL_DEFAULTS = {"Ownership_Tier": "Mid", "Notes": ""}
for column, default in OPTIONAL_DEFAULTS.items():
    if column not in frame:
        frame[column] = default
    frame[column] = frame[column].fillna(default)
```

## 2.4 Intake, live evidence, and time defects

### D11 — `--declare-pitcher` is dead for every Showdown file

**Location:** `tools/preflight_upload.py:1652-1685`; brief writers at `build_slate.py:2692, 2744`  
**Severity:** P1  
**Root cause:** `is_pitcher` checks `Roster Position == "P"`. In Showdown that column is always `CPT` or `UTIL`; arm identity is in `Position` (`SP`/`RP`). The tool therefore calls every declared arm a hitter and retains the hard failure. This occurred on the 2026-09-03 SF@PIT file. The Classic and Showdown brief paths now write `declared_pitchers`, so the remaining live failure is the geometry test.

**Production remediation:** derive person role from the correct columns under the detected roster contract.

```python
position = str(row.get("Position") or "").upper()
roster_position = str(row.get("Roster Position") or "").upper()
is_pitcher = roster_position == "P" or position in {"P", "SP", "RP"}
```

Use the same helper in every preflight/verification site and reconcile the two exposure counters in the warning.

### D12 — freshest-by-date feed can belong to another draftgroup and format

**Location:** `tools/preflight_upload.py:1354-1385`  
**Severity:** P1  
**Root cause:** auto-resolution derives only a calendar date, globs `lineups_feed*.json`, and selects the newest mtime. On 2026-09-03 a Classic six-game file selected an older one-game Showdown feed and emitted 73 false roster warnings. Neither slate tag, game-set fingerprint, team set, nor contest geometry participates.

**Production remediation:** make feed selection a typed compatibility join, never an mtime contest.

```python
want = {
    "contest_type": detected_contract.lower(),
    "games": sorted(game_ids_from_salary(salary)),
    "teams": sorted(teams_from_salary(salary)),
}
compatible = []
for path in candidates:
    feed = read_json_object(path)
    got = feed_identity(feed)
    if got == want:
        compatible.append((feed_timestamp(feed), path))
if len(compatible) != 1:
    rep.fail(f"lineups feed resolution is {'missing' if not compatible else 'ambiguous'} for {want}")
    return None
return compatible[0][1]
```

When every salary team has complete numeric DK `Starting` data, prefer that file-local evidence and report that no external feed was needed.

### D13 — supervisor ignores the engine's explicit BANK-LIMITED classification

**Location:** `tools/autobuild.py:607-643`; current incident `docs/backlog_inbox/2026-09-03_BUILD_autobuild-bank-limited-and-stale-preflight-feed.md:3-17`  
**Severity:** P1/autonomy  
**Root cause:** the supervisor grows on exit 10 or `brief.solve.bank.job_list_exhausted is False`. A direct-path refusal may have neither field while its errors explicitly classify a constraint as `BANK-LIMITED` and name bank growth as the remedy. The supervisor stops for a human on a remedy it is authorized to execute; a manual second build cleared the 2026-09-03 refusal.

**Production remediation:** stop parsing prose and put a typed cause/remedy on every refusal.

```python
# engine payload
payload["refusal"] = {
    "class": "bank_limited",
    "remedy": "grow_bank",
    "job_list_exhausted": False,
    "jobs_attempted": attempted,
    "jobs_total": total,
}

# supervisor
refusal = brief.get("refusal") or {}
if refusal.get("class") == "bank_limited" and refusal.get("remedy") == "grow_bank":
    dec.add(attempt, "grow_bank", "typed engine remedy", **refusal)
    continue
```

No regular expression over `errors[]` belongs in the final fix.

### D16 — a single ownership file is accepted even when its tag is wrong

**Location:** `tools/qa_portfolio.py:622-649`; leverage consumers in `build_slate.py`  
**Severity:** P1  
**Root cause:** if the exact `ownership_pred_<tag>.json` does not exist but exactly one prediction file exists for the date, that file is returned without comparing its tag/draftgroup. It can feed another slate's ownership prior into hard leverage constraints.

**Production remediation:** require content identity, not filename cardinality.

```python
if len(found) == 1:
    candidate = read_prior(found[0])
    got_tag = str((candidate or {}).get("slate_tag") or "")
    if tag and got_tag != tag:
        return None, f"AMBIGUOUS: prior tag {got_tag!r} != brief tag {tag!r}"
    if prior_player_pool_hash(candidate) != brief_player_pool_hash(brief):
        return None, "AMBIGUOUS: ownership prior player-pool hash differs"
    return found[0], "content identity matched"
```

### D21 — slate date falls back to the UTC day

**Location:** `mlb_engine/intake/live_data_adapters.py:1706-1716`  
**Severity:** P1  
**Root cause:** when the feed has no game date, the pool uses `datetime.now(timezone.utc).date()`. After 20:00 Eastern that is tomorrow relative to an evening slate, corrupting the pool's date and reference-age arithmetic. The salary `Game Info` already contains the authoritative Eastern date.

**Production remediation:** salary clock first, feed date second, injected Eastern “today” last.

```python
salary_dates = sorted({dt.date() for dt in salary_game_times.values() if dt})
if len(salary_dates) == 1:
    slate_date = salary_dates[0]
elif feed_date is not None:
    slate_date = feed_date
else:
    slate_date = (now or datetime.now(timezone.utc)).astimezone(EASTERN).date()
```

### D22 — pandas-round-tripped batting-order tokens become unposted

**Location:** `live_data_adapters.py:404, 2139`  
**Severity:** P2  
**Root cause:** `str.isdigit()` rejects `"1.0"` through `"9.0"`, even though derived salary files commonly round-trip numeric columns through pandas and the ID normalizer already accepts a `.0` suffix.

**Production remediation:** one token parser.

```python
def batting_order_slot(value: Any) -> Optional[int]:
    try:
        n = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    i = int(n)
    return i if n == i and 1 <= i <= 9 else None
```

### D23 — HTTP adapter leaks timeout and decode exceptions outside its contract

**Location:** `live_data_adapters.py:134-148`  
**Severity:** P2  
**Root cause:** `_http_get_json` catches `HTTPError` and `URLError` only. A read-phase `socket.timeout`, `TimeoutError`, or JSON decode error from an HTML proxy body escapes as an unrelated exception; no retry/backoff exists.

**Production remediation:** bounded retry for transient network faults, typed refusal for invalid content, and secret-scrubbed diagnostics.

```python
for attempt in range(3):
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8")), dict(resp.headers)
    except (socket.timeout, TimeoutError, urllib.error.URLError) as exc:
        if attempt == 2:
            raise RuntimeError(scrub(f"network failure: {exc}", secret)) from exc
        time.sleep(0.25 * (2 ** attempt))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("source returned non-JSON content") from exc
```

### D24 — one blank APPG aborts the whole Classic build

**Location:** `mlb_engine/pipeline/execution_pipeline.py:3808-3812`; warning producer `live_data_adapters.py:2351-2356`  
**Severity:** P2  
**Root cause:** intake warns that a kept row is missing APPG, but frame assembly raises if both Base and APPG are blank. The same condition is therefore described as degradable and fatal in adjacent layers.

**Production remediation:** decide at the intake gate. Recommended: exclude an unprojectable person from optimization with an explicit reason; never invent zero silently.

```python
if base is None:
    exclusion_reasons[pid] = "missing Base and AvgPointsPerGame"
    continue
```

If policy prefers a zero prior, stamp `Projection_Basis=missing_appg_zero` and make certification `UNKNOWN`; do not raise mid-assembly.

### D25 — team-code crosswalk is incomplete and unknown codes pass silently

**Location:** `mlb_engine/team_codes.py:35-78`; consumers in `live_data_adapters.py:313-314, 923-924, 1170`  
**Severity:** P1  
**Root cause:** the DK target map lacks known vocabulary edges including `WAS -> WSH` and the current Athletics naming/code variants. Unknown codes are returned unchanged, then fail to join much later as zero-coverage lineup/odds facts.

**Production remediation:** maintain a canonical 30-team set, explicit aliases, and a typed unknown result.

```python
DK_TEAMS = frozenset({...})
DK_ABBREV_REMAP = {..., "WAS": "WSH", "OAK": "ATH"}

def to_dk_abbrev(raw: Any) -> str:
    value = DK_ABBREV_REMAP.get(normalize_team_code(raw), normalize_team_code(raw))
    if value not in DK_TEAMS:
        raise UnknownTeamCode(str(raw))
    return value
```

### D26 — odds parser splits a team name on the letters `at`

**Location:** `mlb_engine/intake/paste_odds.py:211`  
**Severity:** P2  
**Root cause:** `re.split(r"\s*(?:@|vs\.?|at)\s*", ...)` lets bare `at` match inside “Nationals”. It fails loudly, but it makes valid pasted odds unusable.

**Production remediation:** require whitespace around word separators.

```python
parts = re.split(r"\s*@\s*|\s+(?:vs\.?|at)\s+", game, maxsplit=1,
                 flags=re.IGNORECASE)
```

## 2.5 Audit, durability, archive, and performance defects

### D27 — split audit can reuse stale results across relevant changes

**Location:** `tools/audit.py:1523-1551, 2562-2630`; `tools/env_probe.py:135-140, 191-197`  
**Severity:** P1 for release claims  
**Root cause:** the gate fingerprint hashes Python only under `mlb_engine`, `tools`, and `tests`; it omits `skills/**/*.py`, the wrapper scripts, authoritative documents pinned by tests, the lock file, and runtime identity. Records are accepted up to six hours old. `--gate-report --output path` prints JSON but never writes the requested path. The ordinary test runner (`audit.py:1356`) and environment probe subprocesses have no timeout.

**Production remediation:** fingerprint the actual test dependency graph plus runtime, write reports atomically, and bound every child.

```python
FINGERPRINT_GLOBS = (
    "mlb_engine/**/*.py", "tools/**/*.py", "tests/**/*.py",
    "skills/**/*.py", "requirements.lock", "CLAUDE.md", "MLB_Classic.md",
)
identity = {
    "python": sys.version,
    "executable": str(Path(sys.executable).resolve()),
    "platform": platform.platform(),
    "lock_sha256": sha256_file(root / "requirements.lock"),
}

proc = subprocess.run(cmd, timeout=per_suite_timeout, ...)
if args.output:
    atomic_write_json(Path(args.output), assembled)
```

Claim each saved unit by suite name, command, exit code, count, duration, fingerprint, and identity. `gate-report` must refuse mixed identities.

### D28 — durable JSON/index updates are atomic but not transaction-safe

**Location:** `mlb_engine/entries/upload_manifest.py:203-310`; `mlb_engine/field/contest_library.py:177-189`  
**Severity:** P1 for delivery supersession; P2 for contest history  
**Root cause:** `upload_manifest.record_delivery` reads the date-global manifest, mutates it, and atomically replaces it without a lock/CAS. Two writers can each write valid JSON while one loses the other's record or supersession. `contest_library` is worse: bare `json.loads` and `write_text` can crash on or create a truncated registry.

**Production remediation:** append immutable events, then derive the index; or use a lock plus expected-hash CAS. For the small local footprint, SQLite in WAL mode is also acceptable if and only if it replaces, rather than duplicates, these indexes.

```python
with acquire_file_lock(manifest_lock_path(date), timeout=5):
    before = manifest_path(date).read_bytes() if manifest_path(date).exists() else b""
    manifest = parse_or_quarantine(before)
    updated = apply_delivery_event(manifest, event)
    atomic_replace_json(manifest_path(date), updated)
```

The lock must be held from read through replace. Tests need two processes racing distinct deliveries and a supersession race.

### D29 — ZIP intake has no member/size/collision limits

**Location:** `tools/extract_inbox_zips.py:28-42`  
**Severity:** P2/security-hardening  
**Root cause:** every CSV member is read fully and flattened to its basename. Two different members can collide; a compressed bomb can consume unbounded memory/disk; overwrite writes directly to the target. Path traversal is avoided by basename flattening, but the remaining resource and collision risks are real.

**Production remediation:** enforce count, individual size, aggregate size, compression ratio, and unique target names; stream to a temp file then replace.

```python
MAX_MEMBERS, MAX_MEMBER, MAX_TOTAL = 50, 100 * MiB, 500 * MiB
infos = [i for i in zf.infolist() if i.filename.lower().endswith(".csv")]
if len(infos) > MAX_MEMBERS:
    raise ValueError("too many CSV members")
seen, total = set(), 0
for info in infos:
    name = Path(info.filename).name
    if name.casefold() in seen or info.file_size > MAX_MEMBER:
        raise ValueError(f"unsafe or colliding member: {name}")
    total += info.file_size
    if total > MAX_TOTAL:
        raise ValueError("ZIP expands beyond aggregate limit")
    atomic_stream_extract(zf, info, dest / name)
```

### D30 — standings duplication and winner facts are not exact for Showdown

**Location:** `mlb_engine/field/field_miner.py:223-304, 957-969, 1428-1438`  
**Severity:** P1 for any future calibration/EV work  
**Root cause:** duplication is keyed only by sorted normalized player names, ignoring the Showdown captain role. Two lineups with the same six people and different captains are not duplicates. Winner selection takes maximum parsed fantasy points rather than authoritative rank 1; live/frozen or partial exports can therefore name a non-winner. The same weak key is reused in entered-lineup grading.

**Production remediation:** define a contract-aware identity and settle from final rank.

```python
def lineup_identity(entry: Mapping[str, Any], contest_type: str) -> tuple:
    players = tuple(sorted(entry["players_norm"]))
    if contest_type == "showdown":
        captain = entry.get("captain_norm")
        if not captain:
            raise ValueError("Showdown lineup lacks captain identity")
        return ("showdown", captain, players)
    return ("classic", players)

winner = next((e for e in complete if parse_rank(e.get("rank")) == 1), None)
```

Require a finalized-status marker before any row enters calibration; live exports are diagnostic snapshots only.

### D31 — proxy name contains an EV claim the model cannot support

**Location:** `mlb_engine/optimize/optimizer_v3.py:3689-3750`  
**Severity:** P1/model governance  
**Root cause:** the score combines projection, correlation, salary uniqueness, and a heuristic field-pressure term and calls the non-WTA result `Portfolio_EV_Proxy`. “EV proxy” still asserts that the quantity proxies expected value, but no calibrated payout expectation, field distribution, duplicate/tie settlement, or out-of-sample relationship is computed.

**Production remediation:** rename now; earn EV later.

```python
metric_name = (
    "WTA_First_Place_Fit_Proxy" if mode == "wta"
    else "Portfolio_Contest_Fit_Proxy"
)
```

The target EV estimator in Section 4 is a separate versioned model with calibration gates; it must never silently replace this metric.

### D32 — Showdown lacks production certification and late swap

**Location:** `CLAUDE.md:699-726`; `build_slate.py:3203-3650`; Classic-only validator guard `dk_entries_manager.py:900-905`  
**Severity:** P1/product limitation  
**Root cause:** Showdown uses a separate review-grade path, local certification, and manual thesis ladder. It does not pass workflow/selection/allocation certification and cannot use `run_late_swap`. Roughly correct local rosters are not equivalent to an evidence-bound production workflow.

**Production remediation:** make roster geometry a parameter of one pipeline and one independent validator. Nonzero strategy relaxations, incomplete starter basis, or missing evidence must produce `review_ready`, not `certified`. Add Showdown late swap only after the same started-game invariant and exact-byte gates pass.

### D33 — wrapper bypasses the deterministic hash-seed re-exec

**Location:** `tools/build_asserted.py:90-95`; `build_slate.py` module-entry seed guard  
**Severity:** P2/reproducibility  
**Root cause:** the wrapper loads `build_slate.py` with `spec_from_file_location` and calls `main()`; code under the script's `if __name__ == "__main__"` seed guard does not execute. Hash-based iteration can therefore differ from the direct path.

**Production remediation:** set/verify the seed before Python starts, or move the guard into a callable reached by every entry point.

```python
def ensure_deterministic_process(argv: Sequence[str]) -> NoReturn | None:
    if os.environ.get("PYTHONHASHSEED") != "0":
        env = {**os.environ, "PYTHONHASHSEED": "0"}
        os.execve(sys.executable, [sys.executable, *argv], env)
```

Call it at the start of every CLI `main`; better, delete `build_asserted.py` after D02 is closed.

### D34 — current runtime cannot execute the certified solver/test path

**Location:** `requirements.lock`; `tools/env_probe.py`; measured on `C:\Python313\python.exe`  
**Severity:** P1/environment blocker  
**Root cause:** current interpreter lacks the pinned numerical packages and `.pylibs` is insufficient. The repository expects Python 3.10/Linux with NumPy 2.2.6, pandas 2.3.3, and SciPy 1.15.3, while this audit host exposed Python 3.13 without them.

**Production remediation:** ship one reproducible runtime invocation and make every command use it.

```text
docker run --rm --network=none -v <repo>:/work -w /work <pinned-image-digest> \
  python tools/audit.py --run-tests --terse
```

On Windows, an equally valid alternative is a checked `.venv` bootstrap from `requirements.lock`; the output must record interpreter path, version, platform, lock hash, and package versions. “Audit PASS” is forbidden if the runtime identity differs from the recorded certified identity.

### D35 — the practical odds fallback is neither encoded nor auditable end to end

**Location:** `tools/odds_from_paste.py`; current incident `docs/backlog_inbox/2026-09-03_BUILD_odds-fallback-ladder-action-network.md:1-100`  
**Severity:** P2/operations  
**Root cause:** direct API access is proxy-gated in the observed environment; plain page-text fetches return empty/client-rendered content; the in-app browser can reach Action Network but flattened text loses the book-column association required by `odds_from_paste.py`. Hand-reading a consensus would violate the per-book provenance contract, so F1 correctly remained inert.

**Production remediation:** add a structured, testable browser-export adapter only if the source terms permit it. It consumes a saved accessibility-tree/table artifact, maps each column to a named book, writes the existing per-book schema, and rejects missing headers or totals. If structured extraction is unavailable, accept one explicitly named book as a labeled fallback; never average anonymous numbers.

## 2.6 Performance analysis

The dominant hot-path cost is repeated branch-and-bound, not CSV parsing. In the September 2 measurement retained as the comparison baseline, a ten-line WTA bank took about ten seconds and 96% of wall time was inside `milp`; solve time rose from roughly 0.09 to 1.33 seconds as overlap rows accumulated. The current code still rebuilds sparse matrices and uses accumulating overlap constraints during bank generation (`optimizer_v3.py` around the single-lineup loop), then constructs an entry×candidate assignment with pairwise overlap edges. `candidate_prefilter_target` reduces the quadratic allocation graph but D04 shows that the reduction is not semantics-preserving.

Concrete improvements, in safe order:

1. Correct D04–D06 before optimizing. A faster wrong reduced problem is worse.
2. Build the per-slate eligibility/legality matrix once; vary only objective coefficients and a small set of job rows.
3. Generate unique candidates with exact no-good cuts, not diversity overlap cuts. Enforce overlap at the portfolio level where it belongs.
4. Cache by a complete, canonical typed signature (D18), including runtime/model version and source hashes.
5. Parallelize independent candidate jobs only after deterministic seed partitioning and stable merge order are pinned.
6. Stop all ladders on a structural failure or solver fault; budget against an absolute delivery deadline.
7. Benchmark p50/p95 by slate size and entry count. “Sub-second” applies to a warm incremental late-swap/assignment after cached intake and candidate availability, not network fetches or a cold 150-candidate bank.

# Section 3: Greenfield Audit, Anti-Patterns, and Context Engineering

## 3.1 Context cost is now an operational defect

The live instruction/record layer is larger than the program a session needs to run:

| File | Lines | Bytes | Approximate tokens at bytes/4 |
|---|---:|---:|---:|
| `CLAUDE.md` | 763 | 51,325 | 12.8k |
| `skills/generate-lineups/SKILL.md` | 1,263 | 71,956 | 18.0k |
| `MLB_Classic.md` | 620 | 50,995 | 12.7k |
| `MANIFEST.md` | 95 | 5,127 | 1.3k |
| `docs/backlog.md` | 9,702 | 790,117 | 197.5k |
| `CHANGELOG.md` | 14,331 | 1,034,427 | 258.6k |

The first three alone are about 43.5k tokens before a build session reads a brief, a slate, a queue item, or any code. The problem is not that the project has detailed history; detailed history is valuable. The problem is that history is embedded in executable instructions, and tests pin parts of that prose. A session pays for prior incidents on every run, then still has to reconcile contradictions manually under the lock clock.

This creates four measurable failure modes:

1. **Rule displacement:** the current rule is separated from its action by paragraphs of incident narrative.
2. **N-copy drift:** one number changes in code or CLAUDE.md while reference docs and examples retain the old value.
3. **Context-induced omission:** an agent follows one valid paragraph and misses a later override.
4. **Gate coupling:** wording cleanup becomes a code change because tests assert English text rather than behavior.

## 3.2 Live contradictions at the audited revision

These are not stylistic disagreements; each can change an operator action or claim.

| Conflict | Current evidence | Resolution |
|---|---|---|
| Showdown captain cap | `skills/generate-lineups/references/showdown.md:11-12` says two controls and 0.33; `CLAUDE.md:719-721` says three controls and 0.25/0.50. | Generate the reference from the typed controls schema; current authority is 0.25 CPT and 0.50 person. |
| Late-swap locked teams | `skills/generate-lineups/references/late_swap.md:144` passes `--locked-teams`; `SKILL.md:1232-1238` says do not pass it because locks are derived. | Remove the example flag; keep it only as an explicit additive test/operator override. |
| Inner timeout | `SKILL.md:721,770` still uses `timeout 33`; `CLAUDE.md` and audit help describe a 130-second inner ceiling. | One `deadline_governor` constant and generated CLI examples. |
| Audit inventory | `MANIFEST.md:10,59,73` says 12 modules / 119 tests; `CLAUDE.md:427` says 28 modules / 1,768 tests. | Delete hand-maintained counts; render them from `tools/audit.py`. |
| Gate command feasibility | the main contract tells sessions to run the full gate, then says it cannot fit a normal call and provides a multi-call gate. | Expose one `dfs doctor` command that resumes internally and emits one signed-by-hash report. |
| Network expectations | sync/runbook prose says the mount has no network while the main audit contract expects fetch-based freshness. | Treat network as a capability result, not a host identity: `available`, `blocked`, `auth_missing`, `source_error`. |

Every contradiction has the same architectural cause: mutable policy is represented as prose in more than one place. The fix is not another synchronization test. The fix is one typed owner and generated human-readable documentation.

## 3.3 Code-level anti-patterns

### God scripts and dual control planes

`build_slate.py` (4,722 lines), `execution_pipeline.py` (4,827), `optimizer_v3.py` (4,097), and `contest_allocator.py` (3,102) form two overlapping orchestration layers. Flags are parsed in one, evidence is derived in another, refusal briefs are composed in both, and delivery state is split across runs, outputs, brief, and manifest. This is why a new field repeatedly reaches N readers and misses reader N+1.

Target rule: the CLI parses; the application service orchestrates; domain modules compute; repositories persist. No layer both decides a gate and formats a separate version of that gate.

### Booleans pretending to be evidence states

The system frequently compresses `PASS/FAIL/UNKNOWN/STALE/CONFLICTED/NOT_APPLICABLE` into true/false/absent, then recovers nuance in warnings and prose. Assumed and overridden gates demonstrate the problem. A Boolean cannot say whether no source existed, a source was stale, two sources disagreed, or the check did not apply.

Target rule: every evidence field is a typed verdict carrying status, source, observed time, source time, hash, detail, and optional operator decision. Certification is a pure function over these records.

### Generated artifacts used as mutable shared databases

Date-global JSON files (`upload_manifest.json`, caches, registries, feed names) are read-modify-replace indexes. Atomic rename prevents torn bytes, not lost updates. Filenames and mtimes are used as weak identities when the inputs already contain stronger draftgroup/game/player keys.

Target rule: immutable content-addressed facts first; derived indexes second. A derived index can always be rebuilt and may never be the only copy of an event.

### Search controls mixed with strategy controls

Bank size, prefiltering, solver time, and retries are search effort. Stack size, exposure, overlap, and leverage are strategy. D04 shows a prefilter silently moving the stack floor; D06 shows a strategy ladder reacting to a structural failure. The current code documents the distinction but does not encode it as types.

Target rule: `SearchBudget` and `StrategyPolicy` are disjoint dataclasses. Functions that accept one cannot mutate or return changes to the other. Every relaxation is a `PolicyDecision` with authority and reason.

### Sequential Showdown portfolio construction

The Showdown ladder builds one lineup at a time, infers remaining exposure from arrival order, and uses exclusions/holds to simulate portfolio constraints. That makes a portfolio-level question path-dependent. D07 is not an isolated bug; it is the expected failure mode of expressing global caps through sequential local solves.

Target rule: generate Showdown candidates independently, then solve one assignment/selection MILP across the full entered set.

### Internal referee shares the builder's blind spots

There are useful independent tools, but contracts are still copied: roster slots, salary parsing, `Game Info`, team tokens, cap arithmetic, and source resolution. “Independent” requires separate implementation of the checker, not merely a second CLI importing the producer's assumptions. Exact-byte template preservation is a good independent invariant; using the same weak person key is not.

Target rule: the builder consumes `domain.contract`; the referee consumes a small separately implemented `referee.contract` generated from an external declarative roster specification, with property/mutation tests proving disagreement is caught.

### Prose-driven automation

`autobuild` must parse status shapes and sometimes error text to decide whether it may grow a bank or move a control. A correct system does not make a supervisor infer machine state from an operator sentence.

Target rule: every command returns one versioned JSON envelope on stdout and logs on stderr. `kind`, `status`, `authority`, `remedies`, `artifacts`, and `retryable` are enums/typed fields. Human text is derived from that envelope.

## 3.4 LLM boundary: narrower and more useful

The LLM should not parse numeric CSVs, join players, calculate odds, compute exposure, choose a solver status, validate a DraftKings file, advance a relaxation ladder, infer a clock, or settle contests. Those operations are local, deterministic, testable, fast, and money-adjacent.

The LLM has four legitimate roles:

1. **Unstructured evidence acquisition:** find a lineup/news/roof source when an approved structured source is unavailable, then save a verbatim snapshot with URL and retrieval time. A deterministic parser either accepts or rejects it.
2. **Ambiguity resolution:** present bounded identity candidates (for example two Wilsons) and capture the human's reviewed mapping. The accepted mapping is frozen by numeric DraftKings ID.
3. **Exception diagnosis:** explain a typed refusal and suggest only remedies allowed by the policy object. It does not execute a strategy change without the required authority.
4. **Adversarial review:** read the final report and ask a fixed set of “does this make sense?” questions. It cannot change the certified bytes.

Everything else belongs in code. The operational path must work with no LLM at all when structured inputs are complete.

## 3.5 Context engineering specification

### Always-loaded contract: at most 6 KB

`CLAUDE.md` should contain only:

- truth-label vocabulary and prohibited claims;
- manual DraftKings/money boundary;
- repository authority pointers;
- the single build/check command and exit meanings;
- dirty-worktree preservation rules;
- where immutable evidence, decisions, and history live.

No dates, incident narratives, queue history, copied numeric controls, or multi-page procedures belong there.

### Operator skill: at most 150 lines

The lineup skill should answer: when it applies, required inputs, one command, how to read the one-page result, and the four conditions that require a human. Detailed source-specific collection instructions live in routed references and are loaded only when a typed blocker names them.

### Decisions and history

Use one short active queue table with ID, priority, dependency, acceptance test, and status. Move rationale to `docs/decisions/R###.md`; keep chronological landing evidence in append-only changelog fragments or generated release notes. Do not make a single million-byte file the lookup mechanism.

### Generated documentation

Roster slots, caps, solver status mappings, gate names, versions, test counts, and CLI examples are generated from schemas/code. Tests compare the generated artifact to the checked-in artifact. Tests never assert free-form English from CLAUDE.md or a skill.

### Retrieval packet

Every command emits `report.json` and `report.md`. A future session reads only the report plus the one active decision file. The report includes links/hashes to deeper evidence; it does not inline the incident history.

## 3.6 What to remove or consolidate

The following is a target-state deletion list, not authorization to delete now:

- Fold `tools/build_asserted.py` into the typed CLI, then remove the unrestricted gate-injection path.
- Retire legacy allocation entry points that can mint certification fields without the current joint MILP.
- Merge the duplicated salary parsers, `Game Info` parsers, Eastern-clock fallbacks, roster-slot tuples, team normalizers, and `--as-of` readers.
- Replace `contest_library.py`'s mutable registry with the same immutable observation store the miner uses, or remove it if still callerless.
- Move review-only scanners and heuristics behind `dfs review`; keep them out of production certification.
- Replace 20+ build flags with three explicit inputs: policy file, replay clock, and bounded operator decisions.
- Remove dated narrative from CLAUDE.md/SKILL.md after moving it to decisions/history.
- Replace prose-pinning tests with behavior/property/mutation tests.
- Delete stale counts/examples from MANIFEST and references; generate them.

Do not execute a wholesale rewrite first. Build the replay/referee instrument, repair the current P1 boundaries, then strangle the old paths behind equivalence tests. The repository's current backlog has the same dependency shape in R302; the design here updates its preconditions for the current revision.

# Section 4: Target Architecture and Implementation Specification

## 4.1 Design goals and non-goals

The target is a deterministic, local-first system that turns immutable operator-supplied DraftKings inputs plus approved evidence into the highest model-estimated expected-net-payout portfolio it can certify before lock. It must update that portfolio after relevant news, preserve locked slots, validate exact output bytes independently, and produce one unambiguous file/report for a human to upload.

The target must:

- support Classic and Showdown through the same state machine and certification vocabulary;
- distinguish legality, evidence sufficiency, model calibration, solver optimality, and delivery durability;
- run without an LLM when structured evidence is complete;
- make every network source optional, bounded, cached, and provenance-stamped;
- never reduce the legal player pool to meet a compute deadline;
- never move a strategy control because search time expired;
- make current state recoverable after a killed process;
- make a repeated identical request idempotent;
- expose a warm late-swap decision in less than one second at p95 on the reference host, subject to benchmark;
- retain a legal, last-known-good deliverable when a later refinement fails.

It must not:

- log into, scrape, click, submit, edit, reserve, enter, or upload on DraftKings;
- store DraftKings credentials;
- call a deterministic proxy EV, ROI, win probability, or cash probability;
- silently fill missing evidence from a second source;
- use fuzzy names as production joins;
- add distributed services, a message broker, a daemon fleet, or a database merely for fashion;
- promise global real-world optimality. “Maximum EV” means maximum estimated expected net payout under the versioned, calibrated model, finite candidate universe, sampled field/scenarios, and stated solver gap.

## 4.2 Proposed package architecture

```text
dfs/
  domain/
    contracts.py       Classic/Showdown roster and scoring contracts
    ids.py             DraftKings ID/person/role identity; team crosswalk
    evidence.py        typed evidence status and provenance
    policy.py          strategy policy, search budget, authority, relaxations
    result.py          one command/result envelope and exit vocabulary
  intake/
    dk_salary.py       one strict DKSalaries parser
    dk_entries.py      one strict template parser/preservation map
    lineups.py         per-side source selection and complete-order contract
    odds.py            per-book odds schema and de-vigging
    references.py      read-only point-in-time reference joins
    clock.py           one injectable Eastern/UTC/lock implementation
  model/
    proxy.py           current APPG/F1..F5 model, labels preserved as proxy
    outcomes.py        calibrated player/game scenario generator
    field.py           contest-conditioned field-lineup generator
    payouts.py         exact ranks, ties, duplication, fees, net payout
    registry.py        model card, feature schema, calibration gates
  optimize/
    matrix.py          one sparse legality model per roster contract/slate
    candidates.py      deterministic k-best/forced-coverage generation
    portfolio.py       Classic/Showdown entry assignment and hard caps
    expected_value.py  scenario-average portfolio objective and evaluator
    swap.py            conditional re-optimization with locked variables
  application/
    build.py           one transaction from staged inputs to result
    refresh.py         bounded source refresh; never writes build policy
    replay.py          settle historic portfolios and compare policies
    recover.py         leases, abandoned-run repair, last-good lookup
  referee/
    contract.py        deliberately small independent legality implementation
    bytes.py           template preservation, IDs, salary, slots, clocks, caps
    certification.py   pure certification function over evidence/results
  storage/
    content.py         content-addressed immutable blobs
    run.py             append-only events + monotonic state
    index.py           rebuildable current-delivery/current-model indexes
  reporting/
    render.py          report.json -> one-page report.md
    vocabulary.py      prohibited claims and truthful labels
  cli.py               dfs stage/build/watch/swap/check/replay/doctor

config/
  contracts.yaml       declarative roster/scoring rules, dated source
  policy.yaml          strategy controls and their authority
  sources.yaml         one primary + at most one approved fallback per field
  model_registry.json  active proxy/outcome/field model IDs and gates
```

This is a logical map, not a requirement for dozens of tiny files. The implementation target is roughly 4,000–6,000 lines excluding tests and generated docs. Modules should be combined when a boundary has no independent invariant.

### One owner per fact

| Fact | Single owner | Consumers |
|---|---|---|
| roster slots, salary cap, CPT multiplier, scoring | `domain.contracts` | optimizer, referee spec generator, docs |
| current time, slate date, started/locked | `intake.clock` | build, swap, referee, report |
| numeric player/person/role identity | `domain.ids` | every join and lineup identity |
| evidence state and source ranking | `domain.evidence` + `sources.yaml` | intake, certification, report |
| exposure/cap rounding | `domain.policy.cap_count` | portfolio optimizer and independent generated test vectors |
| solver status | `domain.result.SolverState` | candidate/portfolio/swap/report |
| delivery status | `storage.run` state machine | index and report |
| human text | `reporting.render` | CLI only; never parsed by code |

## 4.3 Immutable data and state model

### Content-addressed inputs

Every input is stored once at `artifacts/sha256/<first2>/<sha256>` with metadata:

```json
{
  "schema": "dfs.artifact.v1",
  "sha256": "...",
  "size": 12345,
  "media_type": "text/csv",
  "role": "dk_salary",
  "observed_at_utc": "2026-09-03T22:30:00Z",
  "source_time_utc": null,
  "source": "operator_download",
  "original_name": "DKSalaries.csv"
}
```

No build edits an input. Operator-authored exclusions or mappings are separate decision artifacts referencing the input hash; derived salary copies are outputs, not replacements.

### Typed evidence

```python
class EvidenceStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"
    STALE = "STALE"
    CONFLICTED = "CONFLICTED"
    NOT_APPLICABLE = "NOT_APPLICABLE"

@dataclass(frozen=True)
class Evidence:
    field: str
    subject: str
    status: EvidenceStatus
    value: Any
    source_id: str
    source_artifact_sha256: str | None
    observed_at_utc: datetime
    source_at_utc: datetime | None
    detail: str
```

Each field in `sources.yaml` has one primary and at most one fallback. Fallback is activated only by a typed primary failure and is recorded; values are never averaged across sources unless the field's explicit method is a per-book market aggregation.

### Run state machine

```text
DISCOVERED -> STAGED -> EVIDENCE_READY -> SOLVING -> VALIDATING
     |          |             |              |            |
     +----------+-------------+--------------+----------> BLOCKED
                                               +--------> CRASHED
                                                         |
VALIDATING -> DELIVERED_CERTIFIED | DELIVERED_REVIEW_READY
                       |
                       +-> SUPERSEDED

Any nonterminal state with an expired lease -> ABANDONED
ABANDONED may spawn a new run; it is never rewritten as if it succeeded.
```

Each transition appends one JSONL event with expected prior state, timestamp, PID/host, code version, policy/model IDs, and input hashes. `current.json` is a rebuildable index written by compare-and-swap. No mutable file is the only record of a decision.

### Result envelope

Every command emits one JSON object:

```json
{
  "schema": "dfs.command-result.v1",
  "command": "build",
  "status": "delivered_certified",
  "exit_code": 0,
  "retryable": false,
  "refusal_class": null,
  "artifacts": {"entries": {"path": "...", "sha256": "..."}},
  "evidence_summary": {"FAIL": 0, "UNKNOWN": 0, "STALE": 0, "CONFLICTED": 0},
  "solver": {"state": "optimal", "gap": 0.0, "elapsed_ms": 182},
  "relaxations": [],
  "remedies": []
}
```

Stdout is this envelope only. Human logs use stderr. Supervisors read enum fields, never prose.

## 4.4 Roster and legality formulations

Let `E_p` be the set of eligible slots for person `p`. Use one binary per eligible player-slot pair, not a dense player×slot rectangle.

### Classic

```text
x[p,s] in {0,1}, s in E_p
y[g] in {0,1}
u[t] in {0,1}

sum[p:s in E_p] x[p,s] = 1                              for every slot s
sum[s in E_p] x[p,s] <= 1                               for every person p
sum[p,s] salary[p] x[p,s] <= 50,000
sum[p in hitters(t),s] x[p,s] <= 5                      for every team t
y[g] <= sum[p in game(g),s] x[p,s]                      for every game g
sum[g] y[g] >= 2

For rostered pitcher a and q allowed opposing hitters:
  q + M(1 - sum[s]x[a,s]) >= sum[h in hitters(opponent(a)),s] x[h,s]

Primary stack of size m:
  sum[h in hitters(t),s] x[h,s] >= m u[t]                for every team t
  sum[t] u[t] >= 1

Locks:    sum[s] x[p,s] = 1
Excludes: sum[s] x[p,s] = 0, preferably remove variables
Prior roster L_j no-good: sum[p in L_j,s] x[p,s] <= 9
```

The independent referee reconstructs all constraints from exported IDs and the salary authority. It does not inspect the solver matrix or trust a builder-supplied `passed` Boolean.

### Showdown

```text
c[p], u[p] in {0,1}

sum[p] c[p] = 1
sum[p] u[p] = 5
c[p] + u[p] <= 1                                        for every person p
sum[p](salary_cpt[p] c[p] + salary_util[p] u[p]) <= 50,000
sum[p in team t](c[p] + u[p]) >= 1                      for both teams
```

Identity is the person key, never the role-specific draftable ID. The export maps the chosen person-role pair back to the exact role-specific DraftKings ID.

## 4.5 Projection and outcome model

### Model tier 0: current deterministic proxy

Retain today's transparent construction as a baseline:

```text
Base[p] = supplied_projection[p] if authorized else DraftKings_APPG[p]
Proxy[p] = Base[p] * F1[p] * F2[p] * F3[p] * F4[p] * F5[p]
```

Every factor has `applied`, source hash, coverage, and a neutral value of 1.0 when unavailable. Neutral is not “passed”; its evidence status remains `UNKNOWN` or `NOT_APPLICABLE`. Outputs are named `Base_Prior`, `Floor_Proxy`, `Ceiling_Proxy`, and `Contest_Fit_Proxy`.

### Model tier 1: calibrated scenario generator

Expected payout needs joint outcomes, not independent point estimates. For scenario `r`, represent each player's fantasy points as:

```text
Y[p,r] = mu[p] + beta_game[p] G[game(p),r]
                 + beta_team[p] T[team(p),r]
                 + beta_role[p] R[role(p),r]
                 + sigma_idio[p] epsilon[p,r]
```

`G`, `T`, and `R` are empirical residual factors fit only on prior slates; `epsilon` is sampled from position/role-conditioned empirical residuals or a calibrated heavy-tailed distribution. Pitcher and opposing-hitter factors carry negative dependence; same-team hitters share positive run-environment dependence. A player's marginal distribution must pass out-of-sample interval-coverage and probability-integral-transform checks before activation. Sparse/new-player cases use a documented hierarchical prior and remain flagged low-confidence.

Lineup score under scenario `r` is:

```text
Classic:  S[k,r] = sum[p in lineup k] Y[p,r]
Showdown: S[k,r] = 1.5 Y[captain(k),r] + sum[p in utility(k)] Y[p,r]
```

DraftKings scoring constants are pinned in `contracts.yaml` with the source date. Historical grading always uses the scoring contract in effect for that contest.

### Calibration gates

An outcome model is `ACTIVE_FOR_EV` only when a frozen out-of-sample evaluation, clustered by slate, passes:

- mean error and calibration by pitcher/hitter and salary band;
- 50%, 80%, and 95% interval coverage within predeclared tolerances;
- tail calibration at contest-relevant quantiles;
- correlation error for same-team hitters and pitcher-vs-opponent hitters;
- stability by slate size and season window;
- no overlap between fitting slates and evaluation slates;
- material improvement over the APPG proxy in settled contest payout replay.

Until then the optimizer stays in proxy mode automatically.

## 4.6 Contest-conditioned field and ownership model

Marginal ownership alone cannot price duplication or finish probability. For contest archetype `c`, estimate a constrained distribution over legal field lineups:

```text
P(L | c, slate, evidence) proportional to
  exp(
      sum[p in L] theta_p
    + sum[(p,q) in L] theta_pq
    + theta_salary * salary_left_bin(L)
    + theta_stack * stack_shape(L)
    + theta_cpt * captain_role(L)       # Showdown
  ) * 1{L is legal}
```

Fit/smooth `theta` from settled standings for the same contest class and slate-size regime. Generate complete legal opponent lineups with sequential importance sampling or MCMC over roster-preserving swaps; validate that simulated marginals, stack distributions, salary-left distributions, pitcher pairs, captain rates, and duplicate-count histograms match held-out fields.

If the field model fails calibration or the contest identity is unknown, expected-payout mode is unavailable. The system may still build a proxy portfolio, labeled accordingly.

## 4.7 Exact payout, ties, duplication, and EV

For contest `c`, scenario `r`, let the simulated field plus the user's selected entries have scores `S_jr`. For an entry `j`, define:

```text
a_jr = 1 + count(i != j where S_ir > S_jr)               first rank occupied by tie group
d_jr = count(i where S_ir = S_jr)                         tie/duplicate group size
Payout_jr = (1 / d_jr) * sum[h=a_jr to a_jr+d_jr-1] prize_c[h]
Net_jr = Payout_jr - entry_fee_c
EV_j = (1 / R) * sum[r=1..R] Net_jr
SE(EV_j) = sample_sd(Net_jr) / sqrt(R)
```

This definition handles exact duplicates and equal scores by splitting the prizes spanning the tied ranks. It uses the actual payout curve and fee, never a generic contest-shape weight.

For a portfolio decision `X` selecting/assigning candidates to reserved entries:

```text
EV_portfolio(X) = (1/R) * sum[r] sum[e in entries] Net_e,r(X)
```

The primary objective is maximize `EV_portfolio(X)` subject to legality and user policy. A secondary lexicographic objective may reduce drawdown/CVaR or concentration only if the policy explicitly requests bankroll utility; it must never be smuggled into “EV”.

Because the user's own entries affect one another's ranks, the exact finite-scenario objective is not generally a simple sum of independent candidate EVs. Implement it in two stages:

1. Solve the linear assignment MILP using candidate EV measured against the exogenous simulated field.
2. Evaluate the selected portfolio jointly, then search a deterministic feasible swap neighborhood; accept only positive common-random-number EV improvements. For small entry sets, solve the exact scenario MILP/CP-SAT linearization and record its gap. For 150-max, report `locally_optimized_saa` unless a global bound is proved.

All candidates in one comparison use the same frozen scenarios and simulated fields. Selection and final grading use independent random seeds. Report model ID, scenario count, Monte Carlo standard error, optimizer status/gap, and search neighborhood. “Max EV” without those qualifiers is prohibited.

## 4.8 Candidate and portfolio optimization

### Candidate generation

Build the sparse legality matrix once. Generate candidates with deterministic seeds:

```text
v[p,i] = base_objective[p] * (1 + epsilon[p,i])
epsilon[p,i] ~ Uniform(-delta, delta), seed = H(run_hash, i)
```

Use exact no-good cuts for uniqueness. Run explicit forced-coverage jobs for viable SP pairs, stack teams, captain candidates, and model-tail scenarios. Every job carries the complete strategy policy and source/model signature. Results merge by `(job_id, objective, canonical_lineup_id)` so worker completion order cannot affect output.

Stop conditions are search-only: candidate count, time budget, or exhausted job set. A stopped search reports coverage and gap; it never excludes a player or relaxes a policy.

### Portfolio assignment

Use one contract-parametric assignment model for Classic and Showdown. In addition to the formulation in Section 1, support:

```text
sum[e,k containing person p] a[e,k] <= cap_person[p]
sum[e,k with p at CPT] a[e,k] <= cap_cpt[p]
sum[e in contest c,k with p at CPT] a[e,k] <= cap_cpt_contest[c,p]
sum[e,k with stack t] a[e,k] <= cap_stack[t]
sum[e,k with game g] a[e,k] <= cap_game[g]
sum[e,k with SP pair q] a[e,k] <= cap_pair[q]
a[e,k] = 0 if candidate k violates e's locked slots or allowed future teams
```

Cap rounding is one function:

```text
cap(alpha, N) = max(1, floor(alpha * N)) when alpha > 0 and N > 0
cap(0, N) = 0
```

Frozen rows in late swap count in both numerator and denominator. The optimizer and referee use independently generated test vectors for the same declarative rule; they do not import one another's implementation.

### Relaxation policy

Every control declares:

```yaml
max_player_exposure_pct:
  kind: strategy
  authority: user
  relaxable: false
max_candidate_reuse:
  kind: strategy_default
  authority: engine
  ladder: [computed_default, 4, 5, null]
candidate_count:
  kind: search
  authority: engine
```

A structural failure stops. A time limit stops. A solver fault stops. Only proven infeasibility under status 2 can advance a declared ladder, and only when that control's authority permits it. Each step is an append-only decision event and appears in the report.

## 4.9 Zero-touch workflow between the two required human actions

### Human action 1: supply platform inputs

The user downloads the DraftKings salary and entries CSVs into a watched local inbox. That manual action supplies platform-authoritative IDs, salaries, eligibility, entry reservations, contest IDs, and first-lock time.

### Automatic local workflow

1. `dfs watch <inbox>` notices a stable file pair after size/hash remains unchanged for two observations.
2. It detects contract geometry, slate date, games, teams, draftgroup fingerprint, contest IDs, and reserved-row count.
3. It content-addresses both inputs and creates a run in `STAGED`.
4. It reads DK `Starting`; if every side is complete, no lineup fetch is needed. Otherwise it polls only approved sources with per-source timeouts and backoff, storing raw responses.
5. It refreshes odds/weather/news only through approved structured adapters. Each failure is classified; missing enrichment stays neutral and visible.
6. It joins references by numeric/player evidence keys, builds proxy projections, and activates EV mode only if the model and contest gates pass.
7. It generates/reuses a signature-correct candidate bank.
8. It solves entry assignment/portfolio selection under the absolute delivery deadline.
9. It exports from the untouched entries template, independently validates exact bytes, and appends the run transition.
10. It writes `report.json`, `report.md`, and one named delivery. The last-known-good delivery remains untouched until a new one validates and is durably indexed.
11. It continues polling until the configured stop time. A material evidence change creates a child run; immaterial/unchanged polls are silent.

### Late swap

At evidence change time `t`, define locked persons/slots from the single clock:

```text
locked(p,t) = game_start_utc(game(p)) <= t
```

For each existing entry, fix every locked slot to its current person. A new person may be selected only if `locked(p,t) = false`. Observed started players from a boxscore are locked even when a schedule feed is stale. Recompute remaining salary, eligibility, exposures including untouched entries, and conditional scenario outcomes:

```text
Y[p,r | observed through t] = observed_points[p,t] + simulated_remaining_points[p,r,t]
```

The swap objective maximizes conditional estimated net payout, not raw remaining points. If EV gates are not active, it maximizes the same labeled proxy used by the parent and explicitly states which parent controls were preserved or unavailable. Every changed entry carries a reason (`scratch`, `lineup_absence`, `weather`, `model_delta`, or authorized policy change).

### Human action 2: upload

The user uploads the exact file named in `report.md` through DraftKings' supported desktop CSV workflow and can compare the displayed SHA-256 prefix. No code interacts with the website.

## 4.10 Deadlines and performance service levels

Use an absolute `deliver_by_utc`, not nested relative timeouts. Reserve time for export/referee/durable write before admitting solves.

| Operation | Target on reference host | Hard behavior |
|---|---:|---|
| stable-input detection and hashing | p95 < 250 ms after files settle | no partial reads |
| cached intake/projection rebuild | p95 < 150 ms | typed missing joins |
| warm single-lineup solve | p95 < 100 ms Classic; < 30 ms Showdown | status/gap recorded |
| warm entry assignment | p95 < 500 ms for 150×150 | no compatibility-blind trim |
| warm late-swap decision package | p95 < 1 s when candidate coverage exists | retain parent on failure |
| cold 100-candidate bank | p95 < 5 s after matrix reuse/parallelism | report partial coverage honestly |
| exact-byte referee + atomic delivery | p95 < 250 ms | reserved deadline budget |

These are acceptance targets, not claims about the current code. Establish them with checked-in benchmark fixtures for 1-, 3-, 6-, 9-, and 12-game Classic plus representative Showdown and 150-entry portfolios. Report distributions, not one best run.

## 4.11 Independent QA and certification

Certification is a pure function:

```text
CERTIFIED =
  input_identity == PASS
  and roster_legality == PASS
  and template_preservation == PASS
  and locked_immutability == PASS
  and export_hash_binding == PASS
  and delivery_durability == PASS
  and every required evidence gate == PASS
  and solver_state in {OPTIMAL, FEASIBLE_WITH_ACCEPTED_GAP}
  and every relaxation is permitted and disclosed
  and mode-specific certification policy == PASS
```

Any `UNKNOWN`, `STALE`, or `CONFLICTED` required fact yields `REVIEW_READY` or `DO_NOT_UPLOAD` according to the explicit policy; it never becomes pass by truthiness. An unavailable EV model downgrades the objective label to proxy but does not by itself make a structurally legal Classic file illegal.

The referee reopens the delivered CSV, recomputes:

- row geometry and reserved-row coverage;
- every ID against the exact salary hash;
- slot eligibility, person uniqueness, salary, team and game rules;
- status/exclusion and started-game constraints;
- per-entry and portfolio caps, contest duplicates, overlap, and locks;
- exact non-roster-cell preservation;
- output hash, run artifact hash, mirror hash, and index hash.

The report is rendered only after durable readback. Its `passed`, `status`, exit code, and manifest/index state must be derived together in the finalizer.

## 4.12 Test and evaluation strategy

### Unit and property tests

- Generate legal and illegal salary/entries fixtures for both geometries.
- Property: every emitted lineup passes a separately implemented referee.
- Property: changing any non-roster template cell is detected.
- Property: every active cap's realized count is at or below the exact rounded cap.
- Property: a prefilter never reduces an entry's compatible set below `min(2, available)`.
- Property: statuses 1/3/4 never advance a proof-only ladder.
- Property: killed writes leave either the old complete artifact or the new complete artifact.
- Property: same-name players never merge without an explicit identity conflict.

### Mutation tests

Delete or invert each legality row, bypass each evidence failure, alter cap rounding, drop one propagated control, change a clock timezone, ignore a role, and corrupt a hash. Each mutation must be killed by a behavior test, not a source-string assertion.

### Golden and replay tests

Use at least ten archived certified Classic deliveries and representative review-grade Showdown slates. Under the same proxy model/policy/seed, the strangler must reproduce exact bytes or produce a documented candidate difference. The independent replay tool grades both portfolios on the same finalized contest data. Differences are accepted only if legality/evidence is no worse and the predeclared settled metric is no worse out of sample.

### Model evaluation

Split by slate/date cluster, never by lineup row. Freeze training, calibration, and test partitions. Report calibration, scenario correlation, ownership/field fit, duplicate distribution, expected-payout error, realized net-payout uncertainty, and comparison with the proxy baseline. Do not promote on a single slate or on in-sample ROI.

### Concurrency and recovery

Run multiprocess races for delivery recording, supersession, cache merges, and feed updates. Kill the process after every state transition and file write point. On restart, `dfs recover` must classify the run and preserve the last-good delivery without manual file surgery.

## 4.13 Migration plan and gates

### Phase A — repair current money-adjacent boundaries

Land D01–D18 in bounded batches with counterfactual tests. Re-run the pinned five-suite audit in the pinned runtime and produce one complete gate artifact whose runtime/fingerprint match the head. Do not start a new engine while the current referee can certify arbitrary IDs or a caller can assert past derived false gates.

### Phase B — build the measuring instrument

Implement the current R118 replay/settlement tool first: finalized rank/payout curves, contract-aware lineup identity, exact ties/duplicates, and immutable source hashes. Backfill the archived deliveries that have sufficient evidence. This is the acceptance oracle for every later migration and the prerequisite for any EV terminology.

### Phase C — extract contracts, intake, and referee

Introduce `dfs/domain`, `dfs/intake`, and `dfs/referee` beside the old code. Route the old CLI through them. Generate docs/test vectors from the contracts. Remove duplicate clocks, team maps, roster tuples, salary parsers, and status vocabularies only after both paths pass golden equivalence.

### Phase D — replace candidate and portfolio internals

Build the matrix-once candidate generator and one contract-parametric portfolio optimizer. Compare ten archived deliveries under the current proxy objective. Require exact-byte equivalence or a settled replay result no worse under predeclared metrics. Convert `build_slate.py` into a compatibility shim.

### Phase E — bring Showdown under the gates

Replace the sequential thesis ladder with candidate generation plus joint assignment. Add exact person identity, certified export, and late swap. Retain `review_ready` until every evidence and relaxation policy is explicit and the independent referee passes.

### Phase F — activate calibrated EV mode

Build the outcome and field models offline. Register a model only after frozen out-of-sample gates pass. Run proxy and EV selection in shadow mode first; compare settled outcomes with uncertainty. Promotion requires a written model card, reproducible training/evaluation hashes, enough independent slates to support the claim, and an automatic fallback to proxy mode on drift or missing contest identity.

### Phase G — simplify context and delete old paths

After the new path has at least ten successful equivalence/replay deliveries and one complete late-swap exercise, remove superseded code and prose in the same commits that remove their callers/tests. Reduce CLAUDE.md and the operator skill to the limits in Section 3. Generate MANIFEST, command examples, and gate counts.

## 4.14 Definition of done

The redesign is complete only when all of the following are demonstrated, not merely implemented:

1. One command consumes a stable salary/entries pair and emits one typed result, one report, and at most one current delivery.
2. Classic and Showdown share the run/evidence/certification state machine and independent exact-byte referee.
3. A killed process is recoverable and never leaves an apparently active terminal run.
4. Concurrent writers cannot lose a delivery or supersession event.
5. Every field source has one primary, at most one fallback, and frozen provenance.
6. Every solver status and relaxation has exact typed semantics.
7. Warm late swap meets the measured p95 target without weakening strategy or legality.
8. Ten archived Classic deliveries and representative Showdown deliveries pass equivalence/replay acceptance.
9. The current pinned test suites pass under a recorded pinned runtime and audit fingerprint.
10. EV terminology is enabled only with an active calibrated outcome model, active field model, exact payout/tie settlement, independent scenario seeds, Monte Carlo error, and recorded optimization gap.
11. The human performs only the two platform-required actions: supply DraftKings files and upload the named CSV.
12. No code automates DraftKings interaction or stores account credentials.

Until item 10 holds, the system's strongest truthful claim is: **evidence-qualified, independently validated optimization of a deterministic contest-fit proxy**.

