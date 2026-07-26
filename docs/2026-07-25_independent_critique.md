# Independent Adversarial Critique: MLB DFS Engine

Date: 2026-07-25. Basis: tree at `e58b3ac` plus 5 untracked paths. Prior red-team documents were deliberately ignored for this pass; every finding below was derived from the code and from today's production artifacts. Claims marked **[reproduced]** were executed against real files on disk in this session.

Audience: an AI tool implementing the fixes. Each item has a stable ID, a file:line anchor, the rationale, a concrete fix, and an acceptance test. Effort is S (under 30 min), M (a few hours), L (a day or more).

Method note: findings were produced by four independent sweeps and then fact-checked by a fifth pass that re-derived every anchor and tried to break each claim. That pass found 18 errors in the first draft, including two that changed a recommended fix, and all are corrected here. Where a number could not be reproduced from the tree it has been removed rather than hedged. Nothing in the repo was modified to produce this document.

Priority meaning, ordered by the stated goal of winning lineups quickly:

- **P0** changes or corrupts what gets uploaded, or lets an invalid file certify.
- **P1** silently degrades lineup quality, or destroys the evidence needed to tell whether it did.
- **P2** wastes time, tokens, or traceability without touching tonight's upload.

---

## Top line

Three things are true at once, and the third one governs.

**The engine's certification spine is well built and its front door is not.** `build_state_manager` hashes inputs and artifacts, refuses mutation, and re-verifies before promotion. `FORBIDDEN_CALLER_ASSERTIONS` genuinely prevents a caller from asserting post-export facts. Then `run_slate` hardcodes six of the eight pre-export gates to `True` (`execution_pipeline.py:2262-2270`), so a build with no weather check, no odds packet, no pitcher audit, and no confirmed-lineup gate returns all three certifications green. The architecture defends against the wrong attacker. It is hardened against a lying caller and wide open to an absent check.

**The highest-consequence gap is the one nobody has been burned by yet.** There is no injury or status filter anywhere on the Classic path. DraftKings publishes the answer in the `Status` column of the file the contract already calls authoritative, and the only code on the `run_slate` path that reads it is `showdown.py:102`, which is Showdown-only. (`skills/generate-lineups-workspace/build_apex.py:57` also reads it, but that is gitignored scratch and off the production path.) **[reproduced]** On today's four-game salary file, with lineups forced to the TBD state the platoon fallback exists for, seven IL and DTD players entered the legal pool, including Matt Chapman and Lourdes Gurriel Jr., with zero warnings and zero blockers, every team reporting 9 of 9 and reading as success. Today's delivered lineups are clean, and that is luck of timing rather than a control: every slate posted its lineups before the build, so the confirmed nine came from the feed. The exposure is the T-60 build, which is the build the platoon fallback was written for. The platoon reference is 25 days old (`collected_date: 2026-06-30`), its `stale_teams` field is computed and never read, and staleness is measured against the file's own collection date rather than against today, so the file's age is structurally unobservable.

**The process is out of proportion to the stakes, and that is the finding that should change behavior.** **[reproduced]** Today's 82 unique delivered entries carry $9.37 in total fees, largest single entry $1.00, and the portfolio is almost entirely satellites and qualifiers at $0.01 to $0.25. Against that sit 2,562 lines of governance prose (CLAUDE.md, MLB_Classic.md, the SKILL, the ledger), 14 documents in `docs/`, and three separate red-team reviews inside seven days. Builds themselves take 8 to 11 seconds (`_build3.log: elapsed_s 7.838` and `10.7`). The solver is not the bottleneck and neither is the strategy. The bottleneck is the operator loop: today produced seven DKEntries files, ten briefs, three duplicate `_1` briefs, and two hand-written scripts in `outputs/` that never call `run_slate` and hard-type 24 player names, none of which resolve against any salary file on disk. The correct response to this review is to fix a short list of upload-integrity bugs, add one fast executable check, and then delete ceremony rather than add more.

A blunt implication: at these stakes the marginal dollar from a better projection is near zero, and the marginal dollar from not uploading a lineup with an IL bat in it is the whole game. Prioritize accordingly. If the intent is to scale stakes, that decision is the highest-value item in this document and it is not a code change.

---

# Section 1: Issues and bugs

## P0: can corrupt an upload or let an invalid file certify

| ID | Issue | File |
|---|---|---|
| B1 | No injury or status filter anywhere on the Classic path | `intake/live_data_adapters.py:673-694` |
| B2 | Six of eight pre-export gates hardcoded `True` | `pipeline/execution_pipeline.py:2262-2270` |
| B3 | Roster geometry never validated; Showdown file parsed as Classic | `entries/dk_entries_manager.py:215, 427-463` |
| B4 | Embedded player pool never compared to the salary file, and cannot be read at all on Showdown | `entries/dk_entries_manager.py:245-271, 555` |
| B5 | `verify_export.py` drops unparsable rows and still prints PASS | `tools/verify_export.py:50-61` |

### B1. No injury or status filter on the Classic path (P0, S)

`MLB_Classic.md` §2 lists "confirmed-out hitters are excluded" as non-negotiable. Nothing implements it. `parse_dk_salary_csv` (`slate_intake_manager.py:202-236`) stores the whole row in `.raw` and never reads `Status`. On the production path the only reader is `showdown.py:102`. The `Confirmed_Out` machinery that exists (`late_swap_manager.py:35 BLOCK_STATUSES`, `slate_intake_manager.py:889 pre_prune_player_pool`) is unreachable from `execution_pipeline`.

Both TBD paths admit them. The platoon path keeps whatever `build_projected_order` matched (`live_data_adapters.py:673-676`), and the APPG fallback sorts by `AvgPointsPerGame` with no status predicate (`live_data_adapters.py:688-694`), which puts a recently-shelved high-APPG bat at the top of the sort. Nothing downstream catches it: `dk_entries_manager.py:605-612` only gates confirmed hitters per team, and for a TBD team `team_requires_confirmation` is False.

**[reproduced]** `data/slates/2026-07-25/DKSalaries_1605_4g.csv` carries 386 rows with 89 IL, 1 OUT, 1 DTD. Forcing the feed to TBD produced a legal pool of 80 containing 7 flagged players, warnings `[]`, blockers `[]`.

Rationale: a player who cannot score is a dead roster slot, and on a 10-slot Classic lineup that is 10% of the entry gone before first pitch. This is the cheapest large win available in the codebase, because the data is already in memory.

Fix:
1. In `build_slate_pool`, read `sp.raw.get("Status")`. Drop `OUT`, `IL`, and `NA` from pool eligibility with one warning line naming each player and team. Treat `DTD` as eligible but emit a warning, and raise it to a blocker when the player sits inside a selected primary stack.
2. Carry `Status` onto the projection row so it survives into `projections_df`.
3. Add an independent recheck in `validate_dk_entries_file` and in `tools/verify_export.py`, reading `Status` straight from the salary CSV so the gate does not depend on intake having done its job.
4. Cross-check against DK's `Starting` column (see B17) so a scratch after the file was pulled is also caught.

Acceptance: a unit test feeds a salary CSV with one `IL` hitter carrying the highest APPG on a TBD team and asserts the player is absent from `projection_rows`, that `pool_report["warnings"]` names him, and that `validate_dk_entries_file` rejects a hand-built export containing him.

### B2. Six of eight pre-export gates are hardcoded `True` (P0, S)

`execution_pipeline.py:2262-2270`:

```python
gate_defaults = {
    "salary_gate_passed": True, "entry_grid_gate_passed": True,
    "lineup_gate_passed": True, "pitcher_audit_gate_passed": True,
    "weather_gate_passed": True, "odds_gate_passed": True,
    ...
}
caller_asserted = sorted(set(gate_defaults) - {...})
```

`PRE_EXPORT_GATES` (`dk_entries_manager.py:33-43`) contains nine names, of which those six are a subset, and `validate_upload_ready_gates` only fails a gate that is present and falsy or absent. Because `run_slate` always supplies all six as `True`, that axis always passes, and `derive_workflow_certification` computes `workflow_valid` from it. `tools/late_swap.py:43-48` hardcodes all eight the same way, on the path that runs closest to lock and never calls `resolve_slate_context_preflight`, so late swap self-certifies with no weather validation at all, including when `postponement_risk` is high.

Compounding it, `caller_asserted` is a static list, so the artifact claims the operator asserted six facts he never saw.

Rationale: "upload-ready" is defined in CLAUDE.md as all three gates passing. If six of the eight inputs to that definition are constants, the phrase carries no information, and the honest-labeling rule the project takes seriously is violated at the front door.

Fix: default the six to `None` so `validate_upload_ready_gates` reports them as `missing_gates` and blocks. Derive `caller_asserted` from `set(workflow_gates or {})` as actually supplied. Add an explicit `assume_gates: list[str]` argument for the T-5 fast path, recorded verbatim in `diagnostics.json` so the artifact says which checks were skipped and why. In `tools/late_swap.py`, either compute the gates from the slate bundle or pass them as `False`.

Acceptance: `run_slate(approve=True)` with no `workflow_gates` returns `workflow_valid=False` with the six names in `missing_gates`; with `assume_gates=["weather_gate_passed"]` it certifies and `diagnostics.json` records the assumption.

### B3. Roster geometry never validated, so a Showdown file parsed as Classic corrupts silently (P0, M)

`dk_entries_manager.py:215` validates four columns and stops:

```python
if not header or [x.strip() for x in header[:4]] != ["Entry ID", "Contest Name", "Contest ID", "Entry Fee"]:
```

`ROSTER_END_COL_EXCLUSIVE = 14` is a module constant. Showdown DKEntries is 12 columns wide, Classic is 16. Two consequences, both verified by a prior sweep against real files:

- The Instructions cell lands inside the assumed roster window, so `is_blank` returns False for a genuinely blank reserved row. The "blank reserved rows block certification" guardrail, which CLAUDE.md calls absolute, is defeated at the reporting layer.
- `write_candidate_from_template` (`:427-430`) widens a 12-column row to 14 and overwrites the padding and Instructions columns, and then `validate_template_preservation` (`:457-463`) exempts columns 4 through 13 unconditionally, so `template_preservation_passed` returns True on a structurally destroyed file.

**[reproduced]** This is live, not theoretical: `md5(data/slates/2026-07-25/DKSalaries.csv) == md5(DKSalaries_showdown.csv)` and `md5(DKEntries.csv) == md5(DKEntries_showdown.csv)`. The default un-suffixed Classic filenames in today's slate directory both contain Showdown data (`hdr[4:7] == CPT,UTIL,UTIL`). A single default path is one typo from a Classic build against a Showdown file. **[reproduced]** Parsing `DKEntries_showdown.csv` at the assumed width 14 makes 17 of 18 reserved rows report `is_blank=False` and pulls embedded-pool IDs into `roster_ids`, including `43683352` (Tyler Glasnow), a player who is in the pool listing rather than in any lineup.

The same constant disables B4's defense: `detect_player_pool_start` requires the pool column index to be at or beyond `ROSTER_END_COL_EXCLUSIVE`, so on a 12-column Showdown file whose pool begins at column 11, `parse_embedded_player_pool` returns `{}`. The pool section is present and simply unreachable. Fixing the width therefore fixes B3 and unlocks B4 in one change, which is why these two should be implemented together.

Fix: derive the roster window from the header rather than a constant. Validate `header[4:4+width]` against the contract slot names, `["P","P","C","1B","2B","3B","SS","OF","OF","OF"]` for Classic and `["CPT","UTIL","UTIL","UTIL","UTIL","UTIL"]` for Showdown, and reject on mismatch. `tools/verify_export.py:37-47` already performs exactly this detection; port it into `dk_entries_manager` and use it in both directions.

Acceptance: `parse_dk_entry_rows` raises on a Showdown file when Classic is expected; a test asserts `is_blank` is True for all 18 reserved rows of `data/slates/2026-07-25/DKEntries_showdown.csv` when parsed at the correct width.

### B4. The entries file fingerprints its own draftgroup and nothing reads it (P0, S)

`parse_embedded_player_pool` (`dk_entries_manager.py:245-271`) extracts the pool DK embeds in every entries file. `summarize_reserved_contests:356` uses it for a count only. `validate_dk_entries_file:555` builds `allowed_ids` from the same salary CSV that built the lineups, so a build against the wrong salary file validates against itself and passes.

Measured overlap between the embedded pool and the salary file, both counted against the 387-id pool: 386 shared for the correct pairing, 0 for a wrong-day pairing. The signal is unmissable and unread.

Rationale: this is the cheapest possible defense against the single most expensive operator error, which is building the right lineups for the wrong slate. DK rejects the upload and the engine reported clean.

Fix: first make the roster window header-derived (B3) so `detect_player_pool_start` can find the pool on a 12-column Showdown file. Then in `validate_dk_entries_file`, require overlap with `allowed_ids` above 0.95 whenever a pool section is found, and error otherwise. Keep the check conditional on a pool being present, but treat an absent pool on a file that should have one as a warning rather than a silent skip, since absence is now evidence of a parse problem rather than a DK format difference.

Acceptance: pairing today's 4-game entries file with the 07-24 salary CSV produces a hard error naming the overlap ratio; `parse_embedded_player_pool` returns a non-empty pool for `data/slates/2026-07-25/DKEntries_showdown.csv`.

### B5. `verify_export.py` silently drops rows and prints PASS (P0, S)

```python
for row in csv.reader(fh):
    if len(row) < end:
        continue
```

`tools/verify_export.py:50-61`. A prior sweep truncated 2 of 16 real entry rows to 8 columns and the tool printed `PASS  14 classic entries, all checks clean`, exit code 0. Without `--parent` there is no reconciliation to catch the loss.

The same tool is missing three Classic rules that `validate_dk_entries_file:595-604` does enforce: at least two games represented, at most five hitters from one team, and no hitter facing a rostered opposing pitcher. It computes stacks at `:124-128` and reports them without failing.

Rationale: CLAUDE.md names this tool as the pre-upload verifier. A verifier that quietly narrows its own scope and reports success is worse than no verifier, because it terminates inspection.

Fix: count `Entry ID` rows independently of parse success, and fail on any row that cannot be parsed at the detected width. Port the three Classic rules. Derive locked teams from `Game Info` plus `parse_game_info_datetime` instead of requiring the operator to pass `--locked-teams`, which currently makes the excluded-new-teams check a no-op when the flag is omitted.

Acceptance: the truncated-row fixture exits non-zero; a 6-hitter single-team fixture fails.

## P1: silently degrades quality or destroys the evidence

| ID | Issue | File |
|---|---|---|
| B6 | Solver timeout indistinguishable from infeasible; one slow solve aborts the bank | `optimize/optimizer_v3.py:672-684, 1948-1977` |
| B7 | Every counted relaxation is discarded before diagnostics | `pipeline/execution_pipeline.py:2325-2331` |
| B8 | Coverage note claims coverage that did not happen | `optimize/optimizer_v3.py:3330, 3384-3387` |
| B9 | Truncated portfolio passes its own coverage gate | `optimize/optimizer_v3.py:1295-1301` |
| B10 | `Excluded == False` silently removes players from the legal pool | `optimize/optimizer_v3.py:477, 977, 3116` |
| B11 | `bank_cache` job keys omit excludes, target, and stack bounds | `optimize/bank_cache.py:224-225, 276-298` |
| B12 | `as_candidates` omits `primary_stack`, so the stack cap adds no constraints | `optimize/bank_cache.py:159, 189-195` |
| B13 | `'NONE'` becomes a real cap bucket and causes spurious infeasibility | `allocate/contest_allocator.py:1429-1431` |
| B14 | `excluded_new_teams` fails open when the team map is absent | `allocate/contest_allocator.py:1302-1307` |
| B15 | Exclusions never reach lineup construction, only the finished export | `pipeline/execution_pipeline.py:2317-2323` |
| B16 | Partial posted lineups stamped `Confirmed_Starter` | `intake/live_data_adapters.py:333-346` |
| B17 | Platoon reference has no freshness gate; DK's `Starting` column unused | `intake/platoon_order_adapter.py:117-127` |
| B18 | `list(set(...))` feeds MILP row order; hash seed unpinned | `optimize/optimizer_v3.py:1899, 1910, 3275` |
| B19 | Shipped posture caps are looser than the strategy authority | `pipeline/execution_pipeline.py:529-603` |
| B20 | The documented certification stage has zero callers; no DU enforcement | `optimize/optimizer_v3.py:3571-3726` |
| B21 | `field_miner` archives after a failed structural gate | `field/field_miner.py:661, 1127-1147` |

### B6. A timeout is read as infeasibility, and strategy is relaxed to fix a clock (P1, M)

`optimizer_v3.py:672-684` hardcodes `options={'time_limit': 30}` with no parameter, and `scipy.optimize.milp` sets `success=True` only for status 0. A time-limit exit is status 1 with `success=False` and may carry a usable incumbent in `result.x`, which `if not result.success or result.x is None: return None, None` discards.

The caller cannot distinguish the two. On `None`, the inner loop raises `current_overlap` toward `MAX_OVERLAP_CEILING` (8 of 10), steps the DU ladder, and then `failed_indices.append(i); break` at `:1948-1977` exits the **outer** lineup loop, so one slow solve ends the whole bank. `LAST_SOLVER_STATUS` is a module global overwritten by later solves, so the timeout evidence is gone by the time anyone looks.

Rationale: this converts a compute problem into a recorded strategy change, which is the exact inversion CLAUDE.md forbids. It also produces an empty or one-lineup bank that surfaces to the operator as `"no candidates available"`, pointing at the pool instead of the clock.

Fix: thread `time_limit` down from `run_slate`. Return a structured status distinguishing `infeasible` from `time_limit`. Accept `result.x` when a feasible incumbent exists and tag the lineup `solver_status='time_limit'`. Do not enter the overlap or DU relaxation ladder on a timeout. Replace the outer `break` with `continue` so one slow lineup does not end the bank.

Acceptance: a test with `time_limit=0.001` on a real-size pool returns a bank with `failed_indices` populated and `solver_status='time_limit'`, and asserts no relaxation was recorded.

### B7. Relaxations are counted and then thrown away (P1, S)

`build_multi_lineup` returns `du_validation`, `anchor_validation` with `relaxation_applied`, `sp_pair_coverage_validation`, `budget`, `failed_indices`, and per-lineup `relaxed_overlap`. `run_slate` builds `bank_diag` from seven keys and none of those (`execution_pipeline.py:2325-2331`). `bank_diag` does surface in the in-memory return payload as `candidate_bank` (`:2365`), so the precise defect is that it never reaches the immutable `diagnostics.json` written at `:351-368`. A repo-wide grep confirms `du_validation`, `anchor_validation`, and `failed_indices` appear nowhere in `execution_pipeline.py`.

Consequence: a bank that raised overlap from 4 to 8, stepped two DU rungs, and failed 6 of 20 lineups produces an immutable run record containing no trace of any of it. The in-memory payload is not the artifact; only `diagnostics.json` survives the session, and the checkpoint attached to the approved result is the pre-build checkpoint, so it cannot carry post-build facts.

Fix: add the full `bank_diag` to the `diagnostics` dict in `execute_portfolio`, and append a `warnings` entry for each non-null `relaxation_applied` and for any `failed_indices`. Related and cheap: `_blocked_result` reads `diagnostics.get("warnings", [])` (`:209`) but none of the three diagnostics dicts ever set that key, so blocked runs record zero warnings, which is exactly backwards.

Acceptance: a forced-relaxation build writes `diagnostics.json` containing the relaxation counts, and a blocked run's warnings list is non-empty.

### B8, B9. Two gates that report success by moving their own goalposts (P1, S)

`optimizer_v3.py:3384-3387` builds the augmentation note as `f"forced coverage across {n_pairs} viable SP pairs and {len(stack_teams)} stackable teams"` unconditionally. The wrapper's clock starts at `:3165` and hands the same budget to the base bank at `:3177`, so `_budget_exhausted()` can be true before Phase 1 runs. Both phases no-op and the note still asserts forced coverage, with `appended: 0` and `budget_exhausted: True` sitting in the same dict.

`optimizer_v3.py:1295-1301` computes `soft_pass = len(observed) >= min(target_unique, len(lineup_records or []))`, shrinking the target to the number of lineups actually produced, so a short bank always passes. The summary two lines later prints the unshrunk target, producing `pass=True` next to `observed 3/8 target unique pairs`.

Rationale: both are honest-labeling failures in the one field a human reads, and both make an automated check on `pass` useless.

Fix: build the note from observed state (`appended`, `distinct_sp_pairs`, `budget_exhausted`) and reserve a budget slice for augmentation, for example passing 70% to the base bank. Keep the coverage target fixed and report `pass=False` with `truncated_portfolio=True` when fewer lineups were produced than requested.

### B10. A blank cell removes a player from the legal pool (P1, S)

`df = df[df['Excluded'] == False]` at `optimizer_v3.py:477`, repeated at `:978`, `:1008` (`resolve_viable_sp_pool`), and `:3117`. Any value that is not Python or NumPy `False` fails the comparison and the row is dropped, including `NaN`, `None`, and the string `"False"`. `projection_builder.py:125-126` only defaults the column when it is entirely absent, so a `projections_override` frame or a CSV round-trip with one blank cell silently loses that player, and also shrinks the denominator in `_eligible_sp_ids_for_anchor_caps`.

This is the pool-reduction failure CLAUDE.md singles out as forbidden, arriving from a data condition instead of a compute limit.

Fix: coerce once with `mask = df['Excluded'].fillna(False).astype(bool)` plus an explicit string map, and count dropped rows into the pool report.

### B11, B12. The resumable bank reuses stale work and disarms the stack cap (P1, M)

`_job_key(pair, team, lock_sig)` at `bank_cache.py:224-225` excludes `excludes`, `target`, `stack_min`, `stack_max`, and any identity of the projections frame, while `extend_bank` skips any job already in `cache.attempted` (`:325-326`). `pool_signature` covers only the salary file's ID set and its own docstring says it does not affect which candidates are legal. Concrete consequences: a late-swap slice with `excluded_new_teams` never regenerates a job the pre-exclusion slice marked done, so the cache serves the excluded candidate; a `floor` slice after a `ceiling` slice leaves two objective scales in one cache that `_candidate_shape_score` then compares directly; re-running after adding the Savant and FanGraphs CSVs reuses candidates built from the old projections.

Separately, `:276` and `:296-298` build `game_of` with `str(r.Game_ID)`, so two pitchers with a missing `Game_ID` both stringify to `'nan'`, compare equal, and the pair is discarded. `enumerate_sp_pairs` deliberately does the opposite and explains why at `optimizer_v3.py:1099-1103`: an unknown game is not evidence of a same-game pair. The sliced path silently shrinks the legal pair set on incomplete data and reports `jobs_total` against the already-shrunken list.

`as_candidates` (`:159`, payload dict at `:189-195`) omits `primary_stack` and `sp_ids`, so `_candidate_primary_stack` returns empty, `contest_allocator.py:1429-1431` iterates an empty set, and the primary-stack exposure cap adds zero constraint rows while `direct_constraints["max_primary_stack_count"]` still reports the cap. `tools/late_swap.py:162` calls `as_candidates()` with no `projections_df`, so there is no `contest_fit` at all. The post-export validator recomputes the cap independently and blocks, so this costs a wasted solve and a blocked run rather than an uncapped upload, but the diagnostic points at the export instead of the missing field.

Fix: fold a hash of `(excludes, target, stack_min, stack_max)` plus a projections-frame signature into `_job_key`, store it in the cache document, and have `_load` refuse a mismatched file. Mirror the optimizer's unknown-game guard and report pairs dropped for unknown-game reasons. Emit `primary_stack` and `sp_ids` in `as_candidates`, and pass `projections` from `tools/late_swap.py`.

### B13, B14, B15. Three allocator and pipeline defects with the same shape (P1, S each)

**B13.** `_identify_primary_stack` returns the literal `'NONE'` when no team reaches three hitters (`optimizer_v3.py:751-752`). That flows into `contest_fit['primary_stack']` and then into `sorted({x for x in stacks if x})` at `contest_allocator.py:1430`, where `'NONE'` is truthy and becomes a real cap bucket. With 9 entries and a 0.50 stack cap, at most 4 entries may use any stackless candidate, and the joint MILP goes infeasible with the message `"entry-level joint MILP infeasible or timed out"`, pointing the operator at the solver rather than at a pseudo-team cap. Fix: map `'NONE'` to `""` at the allocator boundary.

**B14.** `contest_allocator.py:1302-1307` reads `excluded_new_teams` and `player_team_by_id`. With the map absent, every `.get(pid)` is None, `None in excluded_new_teams` is False, and no candidate is rejected, so the locked-game rule disappears silently. The sibling check at `:1436-1444` explicitly errors when a game-exposure cap is set without `player_game_by_id`. The exposure cap fails closed and the safety rule fails open. `late_swap_manager.py:315` does populate the map, so the shipped wrapper is safe today and the API contract is inverted. Fix: error when `excluded_new_teams` is non-empty and the map does not cover every roster id.

**B15.** `run_slate` forwards `excluded_player_ids` and `confirmed_hitter_ids` to `validate_dk_entries_file`, where they are hard errors, and to `_slate_feasibility` at `:2172` for the pre-solve cap floors, but never into `build_diverse_candidate_bank` (`execution_pipeline.py:2317-2323`), which is where they would actually shape the lineups. So `run_slate(excluded_player_ids=[...])` builds the entire bank and the joint allocation, then blocks. At T-10 that is the whole remaining budget spent to learn a player should have been dropped. Fix: pass `excludes` into the bank build and set `Excluded=True` on non-listed hitters for confirmed teams before building, or at minimum add a checkpoint blocker at `approve=False`.

### B16, B17. The pool trusts data it should be dating (P1, S)

`live_data_adapters.py:333-346` stamps every hitter in `side["lineup"]` as `CONFIRMED_STARTER`, while `fetch_slate_bundle.py:166` sets `lineup_status = "partial"` when fewer than nine are posted. Partial names therefore become `Confirmed_Starter`, which sits in `SAFE_UNLOCKED_STATUSES`, so `validate_tbd_policy` will not flag them. Fix: stamp `PROJECTED_STARTER` unless `lineup_status == "confirmed"`.

The platoon reference decides pool membership and has no freshness gate anywhere. `platoon_report["stale_teams"]` is computed and never read (`live_data_adapters.py:601-606` reads only `zero_fill_teams`), and `platoon_order_adapter.py:117-127` measures staleness against the file's own `collected_date` rather than against today. **[reproduced]** Today the file is 25 days old with per-team pages back to 2026-05-14, and a TBD run emitted zero warnings. `tools/refresh_reference_data.py:89-93` does not track the file at all, so it has no presence check, no age, and no `STALE` flag. That 25-day gap is the mechanism behind B1: players who hit the IL after 2026-06-30 are still in the file.

Free second source, unused: DK's `Starting` column carries the confirmed slot 1 through 9 for every posted hitter plus a role token for pitchers. Measured on today's 4-game file: `{'SP': 7, '': 305, '1': 8, ..., '9': 8, 'PO': 1, 'PLR': 1}`. That is a batting-order cross-check, a late-scratch detector on refetch, and a free confirmation of B1, all in a file already being parsed. The `PO` token is a probable opener, and `build_slate_pool:714` assigns every feed probable the same `declared_probable_sp` role while `ALLOWED_PITCHER_ROLES` carries a `viable_bulk_or_alt_sp` value nothing ever assigns. An opener projected as a starter is a material error on a two-pitcher roster.

Fix: add the platoon JSON to the tracked reference set with a max age measured in days, not 14. Compare `collected_date` to now inside `build_slate_pool` and warn past three days, block past seven. Pipe `stale_teams` into `pool_report["warnings"]`. Read `Starting` as a `Batting_Order` cross-check and report every disagreement with the feed. Map `PO` to `viable_bulk_or_alt_sp` or surface it as a blocker.

### B18, B19, B20. Determinism, doctrine drift, and a certification stage nobody calls (P1)

**B18 (S).** `kwargs['locks'] = list(set(...) | set(pair))` at `optimizer_v3.py:1899, 1910, 3275`. `build_single_lineup` never sorts, and `_build_single_lineup_scipy` emits one constraint row per lock in list order (`:611-613`), so row order changes the matrix handed to HiGHS. Python randomizes `str` hashing per process and nothing in the repo pins `PYTHONHASHSEED`. With the uniform 1.42 ceiling multiplier, exact ties are routine, so two runs on identical inputs can certify different files, which quietly undermines the golden replay's stability contract. Fix: `sorted(set(...), key=str)` at all three sites, sort `locked_ids` before constraint emission, and pin `PYTHONHASHSEED=0` in the audit and the skill entry point.

**B19 (S, decision needed).** `STRATEGY_DEFAULTS` (`execution_pipeline.py:529-603`) against MLB_Classic §8:

| control | §8 | `wta_satellite` | `large_gpp` |
|---|---|---|---|
| pitcher exposure | 0.43 | 0.70 | 0.55 |
| primary stack | 0.35 | 0.60 | 0.50 |
| max shared players | 5 | 7 | 6 |

§8 verbatim (`MLB_Classic.md:541-547`): "Lean WTA/GPP defaults for at least four entries: Player cap: 45%. Pitcher cap: 43%. Primary stack cap: 35%. ... Maximum shared players: five for portfolios of at least eight." CLAUDE.md makes MLB_Classic the strategy authority, and the code is looser on those three controls, on the two postures most likely to be used. Two honest caveats: §8's numbers are written as qualified defaults rather than hard limits, and on `max_player_exposure` `large_gpp` (0.40) is actually tighter than §8's 45%, so the divergence is specific to the three controls tabled above rather than general. It still matters, because today's portfolio is satellites, where duplication is the main enemy. Pick a winner and edit the loser. Related: `max_overlap_base = max(2, int(ROSTER_SIZE * overlap_pct))` with the `typical` preset truncates to 4 where §8 documents 5 (`optimizer_v3.py:1805-1806`); use `round()` or restate the intent.

**B20 (M, decision needed).** `select_final_portfolio_from_candidate_bank` (`optimizer_v3.py:3571-3726`, 156 lines) has zero callers outside its own definition and one changelog line at `:67`, not in `execution_pipeline`, not in `tools/`, not in any test. Production runs `build_diverse_candidate_bank` then `select_and_assign_entries`. The function is named in no document, so this is a delete-or-wire decision with no doc to correct, and §8's opening rule ("do not select a subset and allocate leftovers afterward") arguably argues against wiring it at all. DU enforcement is disabled on both sides of the handoff it was deferred across: `build_candidate_lineup_bank` sets `bank_du = None if scope == 'selection'` under the default `scope='selection'` (`:3012`), and the selection stage's own default `du_threshold_row=None` resolves to explicitly disabled (`:3578, 3615`). So there is no DU enforcement anywhere on the production path, and portfolio decorrelation rests entirely on the allocator's player-count overlap, which is a weaker and different control than the signature distance the framework specifies. Given §8's rule against subset selection, the likely right answer is to delete the stage and enforce DU inside the bank build by passing `scope='bank'`, but either way record the decision. Note the stage also recomputes the auto SP cap from the bank rather than the pool (`:3607-3611`), so a bank clustered on 4 arms would inflate its own cap to 60% exposure and pass its own check; fix that when wiring it, not before.

### B21. The miner archives after its own gate fails (P1, S)

CLAUDE.md states the structural gate is fail-closed and that a zero parse, an unparsed share over 20%, or a contest-type mismatch all block archiving. `field_miner.py:661` computes `parse_structural_ok`, `:758` writes it into diagnostics, and `:695` branches on it (`elif not parse_structural_ok:`) only to select a `verification_note` string. No branch affects control flow. `main()` at `:1127-1147` calls `update_registry` (behind `if args.registry:`), then `emit_ledger_block`, then `return 0`. A wrong-salary mine exits clean and writes the registry.

Rationale: the ledger is the memory. A gate that prints its failure and then archives anyway corrupts the one artifact the strategy depends on, and it does so invisibly.

Fix: in `main()`, branch on `parse_structural_ok` before `update_registry` and `emit_ledger_block`, and return non-zero. Add a `--force` flag that records the override verbatim in the emitted block.

## P2: waste, traceability, and test coverage

### B22. Today's certified Classic deliverable cannot be re-verified (P2, S)

**[reproduced]** `outputs/2026-07-25/DKEntries.csv` contains 55 distinct player IDs in the range 43680524 to 43681086. All 55 are inside the file's own embedded pool of 922, so the file is internally consistent and DK would accept it. But zero of the 55 appear in any `DKSalaries*.csv` staged on disk, whose ranges are 43679119-43679534, 43679535-43679732, 43680328-43680523, and 43683210-43683411. The salary CSV for that draftgroup was never staged or archived. `build_brief_1805_10g.json` records `salary_cross_check: False` and `source: data/slates/_feed2.json`, an untracked scratch file.

Consequence: `tools/verify_export.py` requires a salary file, so today's main Classic deliverable cannot be checked by the project's own verifier, and no QA gate can be applied to it retroactively. This is the finding that makes B1 through B5 unenforceable in practice, so fix it first among the P2s.

Fix: make `run_slate` copy the exact salary CSV and feed into `runs/<run_id>/inputs/` and hash them into the manifest, and refuse to promote a run whose salary input is absent.

### B23. Five of seven files delivered today came through an uncertified path (P2, M)

`_ladder3.log` carries the engine's own caution: `showdown.py is v0.3-review and Phase 3 is not complete ... this is not the Classic three-gate certification. Review before uploading.` It also records that the captain cap relaxed on one slot and that no moneyline was available so entries were split evenly rather than weighted to the market. Meanwhile `showdown.py:475` writes with `target.open("w")` and no temp-plus-`os.replace`, unlike `dk_entries_manager.py:439-442`, and `:390` reads `lineup.get("salary", 0)`, which defaults a missing salary to zero rather than failing.

Rationale: the Showdown path now carries the majority of delivered volume while sitting outside the certification spine the project treats as non-negotiable. That is a governance inversion, not a code bug.

Fix: bring Showdown under the same three gates or state plainly in CLAUDE.md that Showdown ships review-only and what that costs. Make the write atomic and remove the salary default.

### B24. Off-pipeline drift is the actual efficiency problem (P2, M)

**[reproduced]** `outputs/2026-07-25/` holds 7 DKEntries files, 10 briefs including 3 duplicate `_1` mints, 9 scratch logs, and 2 Python scripts. `grep -c run_slate` on both scripts returns 0. `make_theses.py` hard-types 20 player names, 18 per-player bat sides, and both rosters for a NYY@PHI Showdown. None of those 20 names resolve against any 2026-07-25 salary file, and `DKEntries_showdown_theses.csv` (17 entries) has zero player-ID overlap with every staged salary file, so that deliverable cannot be verified against any input on disk.

Two honest qualifications. Ten of the 20 names do appear in older salary CSVs (07-19 and 07-21), so the names are real, they are simply not from the slate that was built. And the charge does not transfer to the second script: `build_thesis_lineups.py` hard-types 14 names in `Name|TEAM` form and all 14 resolve against `data/slates/2026-07-25/DKSalaries_showdown_1610_1g.csv`. The problem is the pattern, not that every instance produced a wrong lineup.

Rationale: hand-typed rosters are an error vector that no gate can see, they cost tokens to regenerate every slate, and at least one of them produced a delivered file with no verifiable input. This is where the time is actually going, not the solver.

Fix: `showdown_theses.py` should read the salary CSV for names, teams, bat sides, and IDs, with a `--game` argument instead of module constants. Commit it: it is untracked today and imported by `build_slate.py:1087` (a function-local import inside `run_showdown`) and by 14 of 27 Showdown tests, so the session-start clean-tree rule is failing on load-bearing files. Delete `outputs/*.py` and treat `outputs/` as write-only for deliverables.

### B25. The test suite measures the wrong 90% (P2, M)

Verified by AST scan and by execution:

- 189 core tests, of which roughly **26 to 30 invoke an engine entry point**, depending on whether `build_projections` and `populate_dk_entries_template` count. The other ~160 are pure-function tests on helpers and dicts.
- **Blocking the scipy import leaves 172 of 189 passing** (12 failures, 5 errors). A suite where 91% is green while no lineup can be built is measuring parsing and dict shapes, not lineup production.
- Behaviors with **no** regression test: blank reserved rows blocking certification on Classic (the word `blank` appears zero times in `test_core.py`, and `require_all_reserved_filled` has zero test references); rejection of an over-cap file; the Classic overlap cap being honored (references set it to 9 or 8 as a loosener, or test the pure-function floor resolver, never that a produced bank honors it); posture and contest-shape resolution; CSV export geometry.
- The golden replay pins `_summarize_allocation` but runs with `LOOSE_CONTROLS` (`:101-108`) disabling every exposure cap, `max_shared_players: 9`, and `projection_mode="emergency_proxy"`, so every factor shipped this week (F1, F4, F5, xwOBA, ceiling multipliers) is outside the gate. It also asserts the aggregates and the per-entry assignment permutation in a single `assertEqual`, so a pure reshuffle of the same lineups across entries fails identically to a real strategy drift, and a re-freeze cannot be distinguished from a regression.
- `tools/audit.py:187` runs `tests.test_core` only, so 28 Showdown and golden tests sit outside the one gate CLAUDE.md mandates. `terse_output` prints `13 modules` from a hand-kept dict while `mlb_engine/` holds 20; the 7 unpinned include `showdown.py`, `showdown_theses.py`, and `field_miner.py`, which is where this week's volume lives.
- The 189 pin was bumped 10 times in 8 days (119, 131, 144, 149, 157, 163, 167, 171, 180, 184, 189), always upward, always in the commit that made it necessary. It is a tripwire against silent test loss, not a coverage measure, and it cannot detect a weakened assertion or a skipped test, because skips still count in `Ran N`. Keep it and stop reading it as coverage.

Fix, in priority order: add solver-independent tests for the five uncovered behaviors using hand-built CSV fixtures; add a second golden replay with production controls and real enrichment; split the replay's single `assertEqual` so the aggregates and the assignment permutation are separate assertions; add `tests.test_showdown` and `tests.test_golden_replay` to the audit; generate the module list from the filesystem instead of a hand-kept dict; separate the audit's `passed` flag so "suite failed" and "count mismatch" report distinctly, since CLAUDE.md's own rule tells the operator to proceed on one and not the other.

---

# Section 2: Ideas, features, enhancements

Ordered by dollars per hour of implementation, given a satellite-heavy portfolio and a build that already runs in 10 seconds.

### I1. One executable pre-upload check, fail-closed on five things only (P0 value, S)

This is the QA process requested, scoped so it can never prevent shipping. Build `tools/preflight_upload.py` taking `--entries <delivered.csv> --salary <DKSalaries.csv>` and nothing else. No engine import, no solver, no network, target under two seconds.

**Fail-closed (exit 2), five checks only:**

1. Every rostered player has an empty `Status` in the salary CSV. Names any `IL`, `OUT`, or `NA` player found. (B1)
2. Header geometry matches the contract for the detected contest type, and every reserved row is either fully filled or fully blank at the correct width. (B3)
3. Every rostered ID exists in the salary CSV, and if the entries file carries an embedded pool, overlap with the salary IDs exceeds 0.95. (B4)
4. Roster legality per lineup: salary at or under 50000, exact slot counts, at least two games, at most five hitters per team, no hitter facing a rostered opposing pitcher, and for Showdown exactly one CPT with both teams represented. (B5)
5. Row accounting: the count of `Entry ID` rows equals the count of rows successfully parsed, and every Entry ID is unique. (B5)

**Advisory (exit 0, prints WARN):** max player exposure, max stack exposure, pairwise overlap histogram, duplicate lineup groups, ownership concentration if a prior exists, and any player whose DK `Starting` slot disagrees with the engine's batting order.

Design notes that keep it from becoming the thing Ben is worried about. It reads two CSVs and nothing else, so it cannot be blocked by a stale reference, a missing feed, or a failed import. Its five hard checks are all facts about the file rather than judgments about strategy, so they cannot be wrong in a way that costs a slate. `--force` prints the failures and exits 0 for the case where the clock beats the fix. It never writes and never modifies. Run it manually or from the skill immediately before the upload step.

Acceptance: running it against `outputs/2026-07-25/DKEntries_1605_4g.csv` with the matching salary file exits 0; against the same file with a hand-inserted IL player it exits 2 naming the player; against `DKEntries.csv` with no matching salary file it exits 2 naming the missing draftgroup, which is the correct answer for B22.

### I2. A skeptic pass that reviews the artifact, not the codebase (P1 value, S)

The adversarial view Ben asked for should run on tonight's file, take one minute, and produce five bullets. Add a `review-slate` skill whose entire job is: read the delivered CSV, the brief, and the `preflight_upload` output, then answer five questions and stop.

1. Which single player is most exposed across the portfolio, and would a scratch of that player damage more than a third of the entries?
2. Is any lineup indistinguishable from another after ordering, and does any contest hold two near-duplicates?
3. Does every entry sit in a contest whose type matches its roster geometry?
4. What did the engine relax to produce this, taken from `diagnostics.json` once B7 is fixed?
5. What is the single most likely reason this portfolio finishes out of the money, stated in one sentence?

This replaces the practice of writing a 250-line codebase review per slate, which is where the tokens are going. Three such reviews exist in seven days (07-19, 07-24, 07-25), and this pass independently rediscovered most of what they contain, which is itself the evidence: a loop that re-derives the same findings three times is not a verification loop, it is a treadmill. The fix is the standard one from the verification-loop literature: encode the check as an executable artifact so the agent gets deterministic feedback on the thing being shipped, and keep the prose pass short and scoped to tonight's file.

### I3. Cheap ownership and duplication priors from data already archived (P1 value, M)

The one capability the commercial tools have that materially changes satellite results is knowing what the field will do. Full Monte Carlo contest simulation is not worth building here. A prior fitted to already-mined standings is.

Most of this is already written and simply not wired. `mlb_engine/field/ownership_prior.py` already implements an archetype-conditioned structural prior with a `grade_against_actuals` loop, and `field_miner` already parses `%Drafted` per contest conditioned on archetype and field size. The genuine gaps are two:

1. **Wire the existing prior into the build.** Nothing loads `ownership_prior` output into `Projected_Ownership_Pct`, which `optimizer_v3.py:2331-2332` already consumes and which currently falls back to the tier defaults at `:2189` (`{'Low': 5.0, 'Mid': 12.0, 'High': 25.0}`). Fit per archetype from the archive, write `data/reference/ownership_prior_<archetype>.json`, and load it in `_assemble_projection_frame`. This is wiring, not modeling.
2. **Turn on the duplication screen that exists.** `score_duplication_risk` (`field_miner.py:785`) is called only from `--selftest`. For a satellite portfolio, expected duplicates is the number that matters most, because winning a ticket means clearing a cut line rather than maximizing points.

Label both as priors, never as probabilities, consistent with the project's rule.

Related and nearly free: `run_meta_lineup` failure is swallowed at `optimizer_v3.py:3032-3036`, and with `meta_lineup_ids = []` the `0.70 * meta_overlap` term goes to zero for every candidate, removing the chalk-avoidance component from ranking with no report. Record `meta_lineup_status` (`ok`, `failed:<exc>`, or the fallback column used) and surface it as a checkpoint warning. Its fallback chain at `:3744` ends at `Ceiling`, so when both `Base_Projection_MetaLineup` and `Base_Projection` are absent the meta lineup becomes the ceiling-max lineup and the signal degenerates into "how much does this look like the optimum," which is a different measurement wearing the same name.

### I4. Match the objective to the contests actually being entered (P1 value, S)

Today's 82 entries are almost entirely satellites and qualifiers. A satellite pays a ticket for finishing above a cut, which is closer to top-heavy WTA than to cash. Two mismatches to fix while B19 is being reconciled:

- `single_entry_gpp` builds in `wta` mode (`execution_pipeline.py:2306`) but `_mode_for_contest_shape` scores it as `portfolio_ev` (`optimizer_v3.py:2970-2976`). Construction and scoring disagree on the objective family.
- `leverage_bonus_weight` and `right_tail_weight` are defined in all 12 contest-shape profiles (`optimizer_v3.py:2212-2279`), appearing exactly 12 times each, which is definitions and zero readers. `right_tail_bonus` is computed at `:2613` and returned at `:2865` but `contest_fit` at `:2837` never adds it. For satellites, right-tail weight is the correct knob and it is currently decoration. Either wire it or delete it, and say which in the doc.

### I5. Apply progressive disclosure to the governance corpus (P1 value, S)

The project carries 2,562 lines of instruction prose. Anthropic's current guidance is to keep CLAUDE.md light, spend its tokens on gotchas rather than restating what the filesystem shows, and move procedures into skills loaded on demand. CLAUDE.md at 166 lines is close to right. The load-bearing problems are elsewhere:

- `MLB_Classic.md` (839 lines) is both strategy doctrine and API contract. Split it: keep the numeric contracts the code must honor in one short file, move the reasoning into a reference the agent loads when a strategy question is live. Anything describing a directory that does not exist (`parked/`, referenced at `:312, 317, 730, 765, 792, 808`) is worse than absent, because a conflicting instruction costs reasoning on every request.
- The ledger (1,085 lines) is memory and should be read by its Quick Card, which CLAUDE.md already does correctly.
- The truthful-labels boilerplate is repeated across dozens of lines in `mlb_engine/*.py` and can compress to one sentence in CLAUDE.md plus a short module docstring convention. The rule is good; restating it in every module is the "repeat yourself" pattern that newer models no longer need.
- Reconcile the contradictions a reader currently hits: `MLB_Classic.md:493` says a 24-candidate default cap while `:60` documents 150; `execution_pipeline.py:1` says v1.9 while `:137` says v1.11; the ledger header says untracked and the file is tracked; `audit.py` prints 13 modules against 20 on disk.

### I6. Make the deliverable path single-valued (P1 value, S)

Seven DKEntries files and ten briefs in one directory, three of them `_1` duplicates, is a wrong-file upload waiting to happen, and it is the same class of risk as B3 and B22. One canonical name per slate plus an `upload_manifest.json` recording, for each delivered file, the run id, the salary CSV hash, the contest ids, the entry count, and the `preflight_upload` result. The manifest is what makes "which file do I upload" answerable in one second at T-5.

### I7. Pin determinism, then make the replay mean something (P1 value, S)

With B18 fixed and `PYTHONHASHSEED=0` pinned, a second golden replay under production controls and real enrichment becomes a genuine regression gate. Assert the aggregates and the assignment permutation separately, so a reshuffle reads differently from a drift. Add both extra suites to `tools/audit.py`.

### I8. Worth knowing about, not worth building

Stated explicitly so implementation effort does not leak here.

- **Full Monte Carlo contest simulation.** This is what SaberSim and Stokastic sell, using thousands of correlated game-script sims to optimize for contest ROI rather than flat projections. It is weeks of work, it needs a calibrated correlation model to beat a good ceiling proxy, and at $9.37 of exposure per slate the expected return does not cover the build. Revisit only if stakes rise by two orders of magnitude. If a cheap version is ever wanted, a correlated bootstrap over archived box scores for stack-ceiling ranking captures much of the benefit at a fraction of the cost.
- **Deleting the DU subsystem.** `du_` appears on 83 lines of `optimizer_v3.py` across 14 distinct identifiers, currently enforced nowhere on the production path. Deleting it is real cleanup, but it is a day of work that changes no lineup. Decide it once (B20) and either wire it or remove it, but do not spend a session debating it.
- **Vectorizing the scoring hot path.** 21 `iterrows` in `optimizer_v3.py`. Builds take 10 seconds. There is no problem here.
- **A daily written red-team review.** Three exist in seven days. The follow-through rate says the constraint is implementation, not analysis. Replace with I1 plus I2.

### I9. The decision that dominates every item above

The engine is built to a standard that suits four-figure exposure and is being run at $9.37. That gap explains most of what this review found: the certification spine is over-built, the injury check is missing, and three review cycles produced nine fixes. Two coherent paths:

**Scale the stakes** to match the engineering, in which case B1 through B5 and I1 are mandatory before the next upload, and I3 becomes the highest-value feature.

**Freeze the engine** and run it as-is, in which case do B1, B2, B3, B4, B5, and I1, skip everything in P1 that does not touch the upload, and stop writing reviews.

Either is defensible. Continuing to build features against unfixed upload-integrity bugs is not. This is a call only Ben can make, and making it explicitly, with a date, is worth more than any code change in this document.

---

# Implementation order

Sequenced so each step is shippable alone and nothing blocks a build.

**Stage 1, before the next upload (about half a day).** B1 status filter. B2 gates default to absent, with `assume_gates` for the fast path. B3 header-derived roster geometry, which must land before B4 because it is what makes the embedded pool readable at all. B4 embedded-pool cross-check. B5 verify_export row accounting plus the three Classic rules. I1 `tools/preflight_upload.py`. B22 archive the salary CSV into the run directory, since without it none of the above can be applied retroactively to a delivered file.

**Stage 2, evidence and honesty (about half a day).** B7 relaxations into diagnostics and warnings into blocked runs. B8 and B9 stop the two gates from moving their goalposts. B21 miner branches on its own gate. B17 platoon freshness plus DK `Starting` cross-check. I6 canonical output name and upload manifest.

**Stage 3, quality (a day).** B6 timeout distinct from infeasible. B10 `Excluded` coercion. B11 and B12 cache keys and `primary_stack`. B13, B14, B15. B16. B18 determinism pin. B19 and B20 as explicit decisions recorded in the ledger.

**Stage 4, only after Stage 1 through 3 are green.** I2 review-slate skill. I3 ownership and duplication priors. I4 objective alignment. I5 corpus split. B25 the five missing tests and the second golden replay. I9 the stakes decision, which should be dated in the ledger regardless of when the code lands.

---

# Reproduction commands

```bash
# B1: IL players entering the legal pool on the TBD path
python3 - <<'PY'
import json, csv
from mlb_engine.intake import live_data_adapters as lda
sal='data/slates/2026-07-25/DKSalaries_1605_4g.csv'
feed=json.load(open('data/slates/2026-07-25/lineups_feed.json'))
status={r['ID'].strip():(r.get('Status') or '').strip() for r in csv.DictReader(open(sal,encoding='utf-8-sig'))}
for g in feed['games']:
    for s in (g.get('away') or {}, g.get('home') or {}):
        if s.get('lineup'): s['lineup']=[]; s['lineup_status']='tbd'
pool=lda.build_slate_pool(sal, feed)
rows=pool['run_slate_kwargs']['projection_rows']
flag=[str(r['Player_ID']) for r in rows if status.get(str(r['Player_ID']))]
print(len(rows),'pool |',len(flag),'flagged |',pool['pool_report'].get('warnings'))
PY

# B3: Classic-named files in today's slate dir contain Showdown data
md5sum data/slates/2026-07-25/DKSalaries.csv data/slates/2026-07-25/DKSalaries_showdown.csv
head -1 data/slates/2026-07-25/DKEntries.csv | cut -d, -f5-7

# B22: today's Classic deliverable has no salary file on disk
python3 -c "
import csv,re,glob
ids={m.group(1) for r in csv.reader(open('outputs/2026-07-25/DKEntries.csv',encoding='utf-8-sig'))
     if len(r)>4 and r[0].strip().isdigit()
     for c in r[4:14] if (m:=re.fullmatch(r'(\d+)',c.strip()))}
for f in glob.glob('data/slates/2026-07-25/DKSalaries*.csv'):
    s={r['ID'].strip() for r in csv.DictReader(open(f,encoding='utf-8-sig')) if r.get('ID')}
    print(f.split('/')[-1], len(ids&s),'/',len(ids))
"

# B25: the suite is 91% green with no solver available.
# Use an import shim so scipy stays installed; do not uninstall it.
mkdir -p /tmp/noscipy/scipy && printf 'raise ImportError("blocked")\n' > /tmp/noscipy/scipy/__init__.py
PYTHONPATH=/tmp/noscipy python -m unittest tests.test_core 2>&1 | tail -3
# expected: Ran 189 tests, FAILED (failures=12, errors=5) -> 172 passing
```

---

Sources consulted for the external comparisons: [The new rules of context engineering for Claude 5 generation models](https://claude.com/blog/the-new-rules-of-context-engineering-for-claude-5-generation-models), [Building verification loops in Claude Code with skills](https://claude.com/blog/building-verification-loops-in-claude-code-with-skills), [Loop engineering: getting started with loops](https://claude.com/blog/getting-started-with-loops), [Best MLB DFS optimizer tools 2026](https://onlydfs.com/blog/best-mlb-dfs-optimizer-tools-2026.html), [Stokastic MLB DFS strategy framework](https://www.stokastic.com/articles/mlb-dfs/mlb-dfs-strategy-guide), [Stokastic multi-entry stack portfolio strategy](https://www.stokastic.com/articles/mlb-dfs/mlb-dfs-multi-entry-strategy), [Stokastic contrarian ownership strategy](https://www.stokastic.com/news/mlb-dfs-contrarian-strategy-how-to-use-ownership-projections-ac11/).
