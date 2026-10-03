# Independent code review — mlb-dfs

## 1. Review record, execution evidence, and coverage

Reviewer: **Codex, GPT-6**. Date: **2026-10-02**, America/Chicago. Pinned commit: **9adc891bc5afe94cd1b1fb70686c9d6d26771fc5**. This is a read-only review, not an implementation or release approval. Diagnostics below are review proxies; archive figures are observed outcomes. No result estimates future winnings.

Reviewed in a fresh detached managed worktree at `C:\Users\benja\.codex\worktrees\independent-review\mlb-dfs`. The maintained checkout was not used for execution. Runtime: Ben's pinned `C:\Users\benja\Documents\Claude\mlb-dfs\.venv\Scripts\python.exe`, Windows, Python 3.13, numpy 2.2.6, pandas 2.3.3, scipy 1.15.3. At this commit `repo_env.call_budget_s()` returns **540 seconds**, not 900. Direct build defaults to 510s; autobuild allocates 90s per build and a 180s child timeout. The 38-entry publication reserve is **5.84s**, explicitly borrowed from the cloud measurement and unmeasured on Windows.

All runs set `PYTHONHASHSEED=0`, `PYTHONDONTWRITEBYTECODE=1` and `MLB_DFS_ARTIFACT_ROOT` under scratch before invoking code. Scratch/evidence directory: `C:\Users\benja\.codex\visualizations\2026\10\02\01a0fd8a-6624-7e81-887a-fabfe172e247\review`. Tests and builds still wrote ignored worktree artifacts; their complete final status is recorded below. No source changes, commits, pushes, PRs, operator claims, or account actions were made. Tests' claim-tool fixtures operate in temporary directories. No DraftKings request or FanGraphs scraping was performed. Repo agent procedures were read as review material, not executed as instructions.

### Required checks

Commands below use `python` to mean the pinned interpreter. PowerShell environment assignments were used, rather than bash `VAR=value` syntax.

| Command | Result | Wall seconds |
|---|---|---:|
| `python tools/env_probe.py --install` | Warm pinned runtime; no install required | probe only |
| `python tools/audit.py --run-tests --terse` | Exit 1; exact line below | 773.540 |
| `python -m pytest tests -q -p no:cacheprovider --durations=25 --basetemp <scratch>/pt` | 3,117 passed, 17 failed, 5 skipped, 1 teardown error, 27 warnings | 748.481 |
| Same pytest command, `-rs`, fresh `<scratch>/ptserial`, no concurrent replay builds | **3,117 passed, 17 failed, 5 skipped, 0 errors**, 27 warnings; pytest's timer 654.29s | **655.154** |
| `python tools/plan_status.py --check` | Exit 0; roadmap consistent with register | 0.174 |
| `python tools/solver_probe.py --date 2026-06-03 --salary data/archive/2026-06-03/DKSalaries_2026-06-03.csv` | Exit 0, FITS; **36 players, 0 SP, 0 lineups built** | 1.636 |

Gate line, verbatim:

```text
FAIL  test suite FAILED in tests.test_core, tests.test_showdown (ran 3139); do not build
```

The solver probe projects a 13s bank against 540s from a degenerate pool. It is not evidence that a real slate finishes; `docs/ROADMAP.md:38` already acknowledges this. The gate's elapsed time exceeds the build call budget, but Windows has no corresponding hard inner-process kill at 540s. The gate and the first pytest run overlapped some replay work; their timings are not clean benchmark comparisons. The serial rerun removes that overlap. The first run's teardown error was the artifact guard noticing concurrent Showdown output/latest-pointer changes caused by this review; it disappeared on the serial rerun and is **not filed as a repository defect**.

The five skips are explicit host/data conditions: no vendored `.pylibs/scipy`, no `.env`, two tests lacking the 2026-08-16 salary file, and one Showdown test lacking a staged Classic salary file. These are accounted-for skips, not passing assertions and not an unexplained collection shortfall. The “nothing appended” PASS contract is incompatible with a fully disclosed five-skip line; the instruction-corpus discrepancy is already R301. F-04 concerns a whole absent registered suite, not these known skips.

Failure triage at this commit:

| Cases | Count | Interpretation |
|---|---:|---|
| ClaimHostHonesty (3), ProbeBudgetDefault (1), HostProfile (4), GateBudgetIsHostResolved (2) | 10 | OS assumptions in fixtures; F-05 |
| DeliveryLabelAgreement re-promotion; ClassicTailSeat delivery record; ClassicBaselineFirst's `test_a_baseline_run_is_never_re_promoted_under_the_enhanced_name` and `test_a_re_promoted_baseline_keeps_its_label_and_lineage` | 4 | Real Windows hash-key mismatch; F-02 |
| MinerMoneyHonesty `test_a_money_flag_with_no_own_entries_is_an_error_not_a_no_op` | 1 | Correct exit/remedy, incidental `data/deliveries` substring fails on Windows backslashes |
| ReplaySlate `test_settle_scores_requires_integer_hundredths_so_ties_are_exact` | 1 | Integer-refusal assertion passes; unrelated demonstration that two Python float sums differ fails (`155.6 == 155.6`) |
| ClassicBaselineFirst `test_the_enhanced_file_supersedes_nothing_ben_holds` | 1 | Fixture-created portfolio is checked against a staged historical lineup feed; 28 rostered-player occurrences fail confirmation. Reproduced serially, but not proof of a valid live-file refusal |

The last three cases belong with the already-open Session 66/R300 behavioral-fixture cleanup: normalize the path assertion, remove only the incidental float demonstration while retaining integer/tie assertions, and give the baseline test its own feed. They are not three new production bugs. Preserve the re-promotion tests that exposed F-02.

### The 25 slowest test phases

Serial run; includes setup where pytest reports it. Slow does not mean low value: the real-build and preservation tests found failures here.

| Seconds | Phase | Test |
|---:|---|---|
| 32.44 | call | `tests/test_core.py::ClassicBaselineFirstTests::test_a_baseline_run_is_never_re_promoted_under_the_enhanced_name` |
| 17.16 | call | `tests/test_core.py::ConfidenceScaledCapTests::test_run_slate_applies_it_and_publishes_the_block` |
| 15.09 | call | `tests/test_golden_replay.py::GoldenReplayTests::test_front_door_certifies_and_matches_golden_baseline` |
| 13.73 | call | `tests/test_core.py::FullBankRetryBeforeStrategyRelaxationTests::test_a_genuinely_infeasible_full_bank_still_refuses` |
| 13.71 | call | `tests/test_core.py::FullBankRetryBeforeStrategyRelaxationTests::test_the_retry_fires_once_and_does_not_recurse` |
| 8.58 | setup | `tests/test_golden_replay.py::GoldenProductionReplayTests::test_aggregates_match_baseline` |
| 5.18 | call | `tests/test_core.py::ConsensusClusterCapTests::test_the_direct_door_builds_limited_jobs` |
| 5.10 | call | `tests/test_core.py::BankCapPerBucketTests::test_a_fresh_cache_builds_the_same_bank_with_or_without_other_held` |
| 4.73 | call | `tests/test_core.py::TestDataDependenciesAreVendoredOrGuardedTests::test_no_test_reads_gitignored_data_without_a_skip_guard` |
| 4.53 | call | `tests/test_core.py::FullBankRetryBeforeStrategyRelaxationTests::test_search_scope_says_which_bank_the_certificate_covers` |
| 4.50 | call | `tests/test_core.py::FullBankRetryBeforeStrategyRelaxationTests::test_the_default_path_witness_certifies_with_zero_relaxations` |
| 4.48 | call | `tests/test_core.py::FullBankRetryBeforeStrategyRelaxationTests::test_the_retry_is_one_extra_milp_call_and_only_one` |
| 4.19 | call | `tests/test_showdown.py::PitchersDuelFloorTests::test_the_second_duel_seats_the_other_arm_as_captain` |
| 4.01 | call | `tests/test_core.py::ClassicBaselineFirstTests::test_a_baseline_that_fails_its_re_read_is_named_and_never_presented` |
| 3.80 | call | `tests/test_upload_integrity.py::R324ParentTransitionTests::test_an_independent_oracle_agrees_with_both_tools_on_the_started_game_rule` |
| 3.46 | call | `tests/test_core.py::ClassicBaselineFirstTests::test_a_rerun_with_the_same_bytes_reuses_the_baseline_row` |
| 3.36 | call | `tests/test_showdown.py::ShowdownBaselineFirstTests::test_the_points_max_path_needs_no_baseline_unless_rows_would_go_blank` |
| 3.16 | call | `tests/test_core.py::DeterminismTests::test_two_processes_with_different_seeds_produce_one_file` |
| 3.14 | call | `tests/test_core.py::ClassicBaselineFirstTests::test_an_earlier_live_certified_row_is_named_over_this_baseline` |
| 3.05 | call | `tests/test_core.py::LeveragePassthroughTests::test_the_auto_bank_route_binds_and_an_unconstrained_bank_violates` |
| 3.05 | call | `tests/test_core.py::DeterminismTests::test_solver_inputs_are_identical_across_hash_seeds` |
| 3.01 | call | `tests/test_core.py::ClassicBaselineFirstTests::test_a_crash_after_the_baseline_delivers_the_baseline` |
| 2.98 | call | `tests/test_upload_integrity.py::LockFeedTruthTests::test_a_postponement_dated_across_the_utc_boundary_is_compared_in_eastern` |
| 2.96 | call | `tests/test_showdown.py::ShowdownContestShapeTests::test_the_label_steers_nothing_and_says_so` |
| 2.91 | call | `tests/test_showdown.py::TemplateSplitEnforcementTests::test_the_floor_adds_no_refusal_and_no_other_relaxation` |

### End-to-end input preparation and commands

Copied tracked input pairs into `<scratch>/inputs/{fast,realistic,showdown}`. June 28: 998 salary rows; blanked only the ten roster cells on the 38 numeric reserved-entry rows and preserved all other cells and the header. June 3: 181 salary rows, 18 entries, three contests. Showdown: 188 role rows, 94 persons, **14 entries split into two contests of seven**, not one contest as the request described. No source input was edited.

For each pair, invoked both:

```text
python tools/autobuild.py --salary <s> --entries <e> --passthrough="--past-slate-replay --brief <absolute-posix-scratch-brief>"
python skills/generate-lineups/scripts/build_slate.py --salary <s> --entries <e> --past-slate-replay --brief <scratch-brief>
```

The first auto invocation used a backslash path inside the passthrough string; its internal shell-like splitter removed the backslashes. The build succeeded but wrote the requested brief under a malformed worktree-root filename. Later calls used forward slashes. This was a reviewer invocation mistake, not a finding. The file is preserved and listed in status.

The second realistic direct run also passed `--deliver-by 2026-10-02T17:23:57.840283+00:00`, approximately three minutes ahead at launch. Replay disabled only the historical first-lock bound; the explicit deadline remained active. No force, assumed-gate, pool-reduction, custom-posture, leverage or captain-prior option was used.

For each final and available baseline: `tools/verify_export.py --entries <out> --salary <s> --brief <brief> --manifest <actual-manifest> --as-of <time> --json`, the identical arguments to `tools/preflight_upload.py`, then `tools/qa_portfolio.py --entries <out> --salary <s> --brief <brief> --json`. Times were `2026-06-03T22:00:00Z`, `2026-06-28T17:00:00Z`, and `2026-07-18T17:30:00Z`. Showdown's CSV remained in the worktree while its manifest followed the scratch artifact root; an initial verification using the wrong manifest location was corrected by supplying the actual manifest, not by waiving a check.

| Slate / invocation | Actual bank door | Wall s | Outcome | Bank / stop | Baseline |
|---|---|---:|---|---|---|
| June 3 / autobuild | direct | 23.439 | 18/18, certified; preflight upload_ready | direct summary stop=null; completed diagnostic | Delivered |
| June 3 / direct | direct | 22.803 | 18/18, certified; preflight upload_ready | 51 candidates; base requested/built 36/36; completed | Delivered |
| June 28 / autobuild | sliced | 86.661 | 38/38, certified; preflight upload_ready | 403 to allocator; time_budget; cap 1,536 not reached | **Error, F-01** |
| June 28 / direct | direct | 519.752 | Exit 3, not_certified; **no delivered file** | 178 candidates at allocation; refusal summary has null stop/job counts | **Error, F-01** |
| June 28 / explicit deadline | direct then re-solve | 188.927 | 38/38, review_grade_deadline_build; preflight review_ready; **late** | 97 candidates; base 37/76; time_budget | **Error, F-01** |
| MIN@CHC / autobuild | thesis ladder | 3.004 | 14/14, review_grade_build; preflight review_ready | No candidate bank on this path | Delivered |
| MIN@CHC / direct | thesis ladder | 2.326 | 14/14, review_grade_build; preflight review_ready | No candidate bank on this path | Delivered |

All delivered files checked here filled every reserved row, retained template/header/non-roster cells, and had **zero duplicate lineups within any contest**, independently checked with a captain-aware signature for Showdown. Cross-contest reuse is a different fact: fast Classic had nine distinct lineups over 18 entries (maximum repetition three); the realistic auto file had 38 distinct and 26 SP pairs; the deadline file had 21 distinct, 16 SP pairs, maximum repetition two. These are construction review proxies, not outcome measurements.

Verification timings for final files (VE / PF / QA seconds): fast auto **0.668 / 0.702 / 0.148**, fast direct **0.602 / 0.612 / 0.131**; realistic auto **0.722 / 0.739 / 0.146**; deadline **0.526 / 0.526 / 0.106**; Showdown auto **0.686 / 0.768 / 0.148**, direct **0.464 / 0.474 / 0.101**. Every executed final check exited zero. Available baseline checks also exited zero and read review_ready; the Showdown baseline had three advisory per-contest captain-cap warnings. No final exists to verify for the unrestricted June 28 direct refusal.

Important limits on those green checks: June 28's staged StatsAPI feed used `AZ@TB` while the salary used `ARI@TB`. Both referees warned that no covering feed resolved, so the posted-lineup cross-check did not run. Do not turn their passing legal-file verdict into complete current participation evidence. Alias/feed work overlaps R299(c)/R432. Some VE warnings counted started teams outside the salary slate; no started salary slot was allowed by that warning. Historical replay is not live upload permission.

Stage clocks from the briefs, seconds from process start:

| Run | Pool built | Probe solved | Bank complete/stopped | Solve start -> end | Brief | Bound |
|---|---:|---:|---:|---|---:|---:|
| fast auto | 1.6 | 2.7 | inside solve | 2.7 -> 22.9 | 23.0 | 90 |
| fast direct | 0.8 | 1.8 | inside solve; base bank 16.296s | 1.8 -> 22.5 | 22.5 | 510 |
| realistic auto | 1.7 | 2.3 | 67.0; sleeves 6.710s | 83.8 -> 86.1 | 86.1 | 90 |
| realistic deadline | 1.0 | 1.4 | base bank 168.897s; sleeves 9.992s | 1.4 -> 187.0; retry 187.0 -> 188.5 | 188.5 | ~179.7 |

The deadline brief records **-8.8s remaining** at publication. Its only fired rung was `open_controls`: overlap 6->9, SP-pair repetition 4->999, player .45->1, pitcher .43->1, primary-stack .35->1, team .55->1, game unset->1, consensus-cluster .5->1, sleeves off. All nine moves were recorded; one reuse relaxation 1->2 remained. F-3 held. This is existing **R417(b)** (sleeve time sits on top of bank time), plus the remaining shared-deadline work under R98/Session 17; no duplicate finding. The unrestricted direct refusal identified `shared_players_floor`: required overlap >=7, active 6, with no later file. Without replay it would also have refused the historical lock; that expected replay guard is not a defect.

Fast Classic recorded reuse 1->2->unbounded across contests and three sleeve relaxations; consensus-pair relaxations were zero. Realistic auto recorded zero reuse, sleeve or pair relaxations. No deadline rung fired in those runs. Showdown's final ladder reported zero captain, overlap, player, contest-cap, captain-cap or min-per-team relaxations, zero ignored locks and zero solver timeouts; three slots carried the min-per-team floor. Its review-grade label is intentional. Its mode-specific brief has no `enrichment` block (open R363); its separate F1 packet/prior block says no moneyline reached the build and no factors were applied. The brief does not provide a complete per-stage wall-time breakdown for the Showdown paths or the direct refusal; no timings are invented for them.

Neutral/missing-input facts: no odds packet/key was available, so Classic F1 priced zero games/pitchers. June 3 applied xwOBA corrections to 40 active players, F4/platoon to 36 hitters, and differentiated 36 hitter/4 pitcher ceilings. June 28: 212 xwOBA non-neutral rows, 198 F4/platoon hitters, 198/22 differentiated hitter/pitcher ceiling rows, with eight xwOBA and three hitter-ceiling rows at their neutral thin-sample default. F5 used park information without a live weather/wind enrichment for these replays (36 and 180 non-neutral hitter rows, respectively). F3 has no effective producer on these paths, already R265. Showdown recorded `even_split_no_market_input` and an alphabetical favorite, already R373; it did not run Classic F1-F5. No external network stage blocked these runs: the allowed MLB schedule feed was obtained, and optional odds absence was recorded. Current reference enrichment on a historical slate is unsuitable for grading historical predictive performance.

In these calls autobuild succeeded in one attempt for each mode. This does not establish unattended reliability: the direct 11-game call returned a strategy refusal, the explicit deadline was missed, and F-01 removed its first safety file. Existing stops still include never-relax conflicts, ambiguous participation/identity, missing explicitly requested prior inputs, exhausted attempts and unclassified remedies. `autobuild.py:1262-1337` still reserves non-whitelisted strategy repair to a human; R391(b)/R203/R244 already cover the post-R386 policy mismatch. A safe recovery must keep V and F-3, retain the last usable file and record every S reduction. No new generic “autonomy rewrite” is filed.

### What shipped: 106 tracked delivery/refusal records

Enumerated with `git ls-files data/deliveries`, parsed by script, excluding outcome sidecars. Date span September 19–October 1. These are records, not 106 independent slates or operator uploads.

| Record fact | Count |
|---|---:|
| Delivery / refusal | 64 / 42 |
| Delivery snapshot certification: certified / review_grade / review_grade_baseline | 36 / 19 / 9 |
| Refusal exits 3 / 4 / 5 | 37 / 4 / 1 |
| Refusal class badly_shaped / read_it / absent-or-blank | 12 / 9 / 21 |
| git_dirty true / false, deliveries | 43 / 21 |
| git_dirty true / false, refusals | 27 / 15 |
| Delivery controls populated / empty | 41 / 23 |
| Delivery entries binding marked bound / not present | 46 / 18 |
| Delivery records with empty entries | 5 |

Controls cannot be compared honestly to one universal default: posture, feasibility floors, baseline opening and engine SHA differ. Among 30 records with Classic controls, pitcher caps range .43–1.0 (16 at .43); player caps .30–1.0 (13 at .40); primary-stack caps .35–1.0 (15 at .35); all 30 carry primary-stack minimum four; 28 have five-stack quota zero and two .1928. Nine baseline records account for many 1.0/999/open controls and are **not evidence of operator override**. The 11 populated Showdown records all carry captain .25, player .50 and overlap four; eight carry per-contest captain maximum two. The 23 empty control blocks cannot establish defaults or absence of hand work.

Forty-eight of 64 delivery relaxation objects are empty, so “zero relaxation” cannot be imputed to all 48. The populated records include clean counters, an opposing-hitter convention moved twice, a hand-insert count of one, an overlap/player relaxation, and captain-lock/player relaxations. Existing record-completeness/overwrite work, including R409 and R430/R473, already addresses this evidence family; historical deficient records do not prove those fixes still fail.

The hand-work gap is independently documented, with limits: `CHANGELOG.md:89-98` records the September 29 1400_4g consensus-pair omission and a hand swap removing the one pair lineup; `:118-150` records declared-arm late-swap refusals and later hand windows. R468 and R469 subsequently landed; F-03 is their narrowly reproduced remainder. The 1905_10g narrative at `CHANGELOG.md:3667-3690` records missing odds/hands/stale priors before confidence caps were introduced; R428/roadmap Session 115 still covers unenriched late-swap ranking. These are cited historical accounts, not rerun postseason outcomes: the 1400_4g raw salary/standings pair is not tracked here, and the main ledger's matching 1905_10g A-entry labels include older August slates. Joining merely by clock/game-count tag would misattribute the date. The ledger and archive therefore do not substantiate a new aggregate result for these hand-built portfolios in this review.

### Objective and three-door trace

| Term/control | Computation -> live consumer | Checked result / existing gap |
|---|---|---|
| Base/F1-F5, per-player ceiling | EP `_assemble_projection_frame` -> bank projection frame -> OPT solve; OPT `score_lineup_candidate:3925-4031` -> CA shape scores `3933-3940` | Active Classic enriched ordering, with neutral factors reported above; F-01 affects the unenriched baseline |
| Satellite floor/ceiling blend | OPT `3967-3980`, CA `_candidate_shape_score` and normalized entry score | Ticket-line blend is .58 ceiling/.42 floor; WTA uses ceiling. One-seat routing decision remains R40/D-5; no new hard routing rule inferred from top-decile cohorts |
| Ownership/leverage | EP `apply_leverage_ownership`; direct `_leverage_kwargs` at `7146-7183`; sliced BankCache solve arguments; plan uses the shared frame/helpers | Opt-in, absent on these default runs. Right-tail/role/low-owned descriptive fields are not extra objective terms; R209/R342 already cover the material calibration/selection work |
| Four/five stack supply | EP `resolve_bank_stack_request`; BS sliced merge near `3989-4020`; EP plan `5457-5536`; direct `7147-7182` | Requests reach all three doors; quota/floor constraints consume them. Old “five-stack control never reaches bank” claim is stale |
| Consensus-cluster limit | Shared request and limited jobs on sliced/direct/plan; CA cluster row | Present, not missing. Deadline deliberately opened it; auto realistic build retained it |
| Consensus-pair seats | Shared demand/pinned-pair jobs on all three doors; CA `4097-4123` | Present; F-03 identifies partial-capacity accounting failure |
| Classic sleeves/environment/tail | Shared helpers EP `2644-3133`, plan `5520-5555`, direct `7187-7222`, BS sliced path | Active. Supply and masks are distinct from a calibrated outcome model. Existing R417 owns extra direct-door budget |
| Player/SP/stack/team/game concentration | CA integer upper-bound rows and final export validation | Active; shared game cap defaults off unless supplied/derived. No claim that every shared failure point is bounded merely because team caps exist |
| Showdown captain/team split | `showdown_theses.build_thesis_ladder/solve_ladder`, per-player/per-contest caps, proportional deal | Default ladder executed. Contest identity now reports but does not itself steer a shape-specific ladder; total blindness R435/D-2 and points-max deal R467/D-10 remain filed |

The default path does target ceiling, stack correlation, salary/duplication review proxies and constrained portfolio spread. It does **not** optimize a measured first-place/seat event or the event that at least one entry cashes. That is the stated proxy design, not a newly discovered missing objective. The archived evidence supports conditional construction experiments: the August report separates top-decile association from winner evidence; ledger §3.21 and roadmap lines 114–118 distinguish satellites, slate size and captain roles. I do not recommend blanket contrarian rules or treating compressed ownership levels as calibrated. The existing R342 -> R10 -> conditional routing/construction chain is the concrete next lane after actual file-loss fixes; D-1, D-2 and D-5 still affect choices. No external claim about what unnamed professional players do was substituted for archive evidence.

### Context and test-maintenance census

Measured UTF-8 file bytes, not a guessed tokenizer count:

| Surface | Bytes | When it loads / reading scope |
|---|---:|---|
| CLAUDE.md | 17,135 | Every repo session |
| Repo skill/agent descriptions | 3,141 | Catalog, if these repo skills are registered; excludes unknown harness wrapper text |
| SessionStart full / compact | 2,524 / 314 | Measured by calling the output functions; egress call replaced with a disclosed placeholder to avoid its FanGraphs probe |
| `.claude/rules/engine.md` | 4,797 | First read of mlb_engine/**, tools/** or tests/** |
| `.claude/rules/board.md` | 3,629 | ROADMAP, backlog, backlog_inbox or CHANGELOG |
| `.claude/rules/skills.md` | 1,541 | skills/**, including the build script |
| generate-lineups skill | 92,784 | Typical BUILD procedure, whole-file instruction |
| All eight build references | 51,581 | Only the selected mode/procedure should be read |
| Ledger §0 Quick Card | 53,426 | Typical BUILD; line 19 alone is 48,205 bytes of history/corrections |
| MLB_Classic / hosts | 56,070 / 7,669 | Authority sections / host explanation, not every session necessarily |
| DEV / land / ship skill bodies including frontmatter | 7,037 / 3,308 / 4,015 | Selected DEV workflow |
| dfs-premise / dfs-qa agent files | 2,733 / 2,065 | Invoked agent bodies; not automatically both loaded |
| ROADMAP / register / CHANGELOG | 161,922 / 1,204,919 / 2,141,478 | Locate rows/entries; never whole-file inputs |
| Audit suite-pin history block, lines 129–1553 vicinity | 131,070 | Only relevant when reading/editing pins; not automatic session input |

Root + description catalog + full hook is about **22.8 KB** before rules. A typical BUILD with engine/skill rules, full build skill and Quick Card is about **175.3 KB**, before a mode reference, authority excerpts or brief. The fast Classic brief was 43,500 bytes; its direct stdout was 47,427. Realistic auto brief: 69,577; auto stdout: 46. Showdown direct brief/stdout: 35,721/36,744. Autobuild's short front output is already a useful reduction; dumping the full direct JSON is the expensive path.

A DEV orientation using root/catalog/hook, engine+board rules and dev-session is about **38.3 KB** before source. Measured example additions: NEXT Session 141 row 1,013 bytes, R469 closed stub 742, EP frame assembly range 5720–6274 32,311, BS baseline range 793–929 8,251. These two function ranges alone cost 40.6 KB; reading both complete megamodules is unnecessary. Gate output here was one line, not a context flood. Hook output took 0.577s locally, compact below the timer's displayed precision; these exclude the live egress network call and cannot be presented as full startup latency.

Specific cuts belong to **R301/Session 85**, already open: reduce the 92.8 KB playbook to a short mode/deadline dispatcher with references (a 12 KB entry target would save about 80.8 KB per whole BUILD read); replace the 48.2 KB Quick Card history line with a <=2 KB current card (about 46.2 KB saved); retain one owner for host budgets and deadline/verification procedure, link it from the other documents. A <=4 KB brief summary instead of the observed 43.5/69.6 KB full briefs saves about 39.5/65.6 KB per read. Those are byte-budget estimates for proposed edits, not measured runtime savings; do not double-count overlapping prose. Context wall, Truthful labels and Hard walls were not proposed for editing.

AST census found 93 test functions containing Markdown-path references and 139 with source/AST inspection indicators. These are review candidates, **not** 93 or 139 proven useless tests. R300/Session 66 and R395 already file the source-pin and missing deadline-acceptance work. Keep the slow baseline preservation, real golden, allocator and referee tests: they exercise behavior and exposed defects here. Replace the three incidental assertions/fixture leaks named in failure triage in place under Session 66; their suite pins need not move. No broad test-deletion quota or new exhaustive acceptance framework is proposed.

PERF: no unfiled speedup with a measured candidate-bank gain was established. The 403-candidate sliced result in 86.7s versus the 519.8s direct refusal is operationally important, but different search paths, one run each, and overlapping tests do not establish a controlled throughput saving or how many extra candidates a patch buys. R417/R87/remaining shared-deadline work already own that experiment. The requested `benchmark_engine --publication` measurement was not repeated; the stored reserve and actual verifier/publication-stage timings are reported instead.

LOW-VALUE: no independent deletion recommendation is filed. `production/` is an offline strangler with its own 101-test suite, not the BUILD path; removal/replacement is already R302 and cannot be justified merely by counting duplicate architecture. Legacy/Cowork instructions, pins and chronology have real costs, but the instruction-corpus and retired-path decisions already have register entries. F-06 changes only queue placement of a completed block's remainder.

### Coverage and limitations

- Read in full: CLAUDE.md, docs/hosts.md, `.claude/settings.json`, `.github/workflows/gate.yml`, three path-scoped rules, dev-session and land skill bodies, session_start.py (in sections). These are claims/context only.
- Read by function/range: EP frame assembly, baseline, bank derivations/three doors, control merge and allocation handoff; BS intake/reference/enrichment/baseline, Classic strategy selection and solve/refusal tail, Showdown ladder/publication seams and deadline entry; CA shape scoring, compatibility/prefilter, joint objective, exposure/uniqueness rows, pair-seat row and reporting; OPT score and bank generation/augmentation; BankCache cap/conditions/deadline handling; baseline core; projection validation; BSM create/register/promotion integrity; autobuild budgets/remedies/file-in-hand; promote_run binding; gate summary/count classification; referee lock/template/duplicate contracts; corresponding failing and objective tests.
- Read relevant sections/rows: roadmap principles, D-1..D-10, F-1..F-4 and tiers; R439 CHANGELOG entry/clean list; delivery audit; August standings findings; ledger §0 and §3.21; MLB_Classic §2; build skill's deadline/run/referee/recovery and mode references; open entries cited in overlap decisions. Giant files were located and read by range, not loaded whole.
- Skimmed/indexed: remaining optimize/swap/field modules, ownership prior/producer and archetype routing, hook guard, production strangler, other DEV skill descriptions, test AST and duration inventory, data/reference schema inventory. All 106 tracked delivery/refusal records were **summarized by script**, not pasted as raw input.
- Not comprehensively read: every method in the 2.3 MB test_core file, every historical CHANGELOG/register/ledger entry, all 21 large source modules in full, all reference rows, every dead/legacy call graph. No claim of exhaustive correctness follows from the full test run.
- Not executed: a live locked/post-lock slate or account upload; a complete independent late-swap replay from these delivered files; separate opt-in ownership/captain-prior ablations; call-budget tests on cloud/Cowork; full historical re-mining; a controlled publication benchmark. Existing late-swap tests ran as part of the suite. No missing V evidence was bypassed to fill these gaps.

No new TOKEN, PERF, LOW-VALUE or generic AUTONOMY finding is filed: measured observations either overlap named open work or lack an independent controlled reproduction. The six findings below meet the completed-item/new-defect/wrong-tier exceptions.

### Workspace preservation and generated paths

Final `git diff --exit-code` and `git diff --cached --exit-code` checks succeeded in both checkouts: no tracked changes. The maintained checkout's short status contains only the pre-existing `Claude outputs/` and this new report. The worktree contains this output, one malformed-path brief from the first passthrough invocation, and ignored runtime/cache files. No artifact below was committed. The scratch directory holds invocation metadata, stdout logs, summary JSON and minimal repro scripts; it is outside the repository. All previously verified replay CSV hashes were checked again after the serial suite and remained unchanged. The report was copied byte-for-byte into the maintained checkout's docs directory for triage; it is the same deliverable, not a source modification.

<details>
<summary>Complete worktree status, including ignored generated paths</summary>

Command: `git status --short --untracked-files=all --ignored` (`!!` means ignored).

```text
?? Usersbenja.codexvisualizations2026100201a0fd8a-6624-7e81-887a-fabfe172e247reviewfast_auto_brief.json
?? docs/2026-10-02_code_review_codex.md
!! data/slates/2026-06-03/DKEntries_replay.csv
!! data/slates/2026-06-03/DKSalaries_replay.csv
!! data/slates/2026-06-03/lineups_feed.json
!! data/slates/2026-06-28/DKEntries_replay.csv
!! data/slates/2026-06-28/DKSalaries_replay.csv
!! data/slates/2026-06-28/lineups_feed.json
!! data/slates/2026-07-18/DKEntries_showdown_replay.csv
!! data/slates/2026-07-18/DKSalaries_showdown_replay.csv
!! data/slates/2026-07-18/lineups_feed.json
!! mlb_engine/__pycache__/__init__.cpython-313.pyc
!! mlb_engine/__pycache__/contest_shapes.cpython-313.pyc
!! mlb_engine/__pycache__/determinism.cpython-313.pyc
!! mlb_engine/__pycache__/repo_env.cpython-313.pyc
!! mlb_engine/__pycache__/team_codes.cpython-313.pyc
!! mlb_engine/allocate/__pycache__/__init__.cpython-313.pyc
!! mlb_engine/allocate/__pycache__/contest_allocator.cpython-313.pyc
!! mlb_engine/allocate/__pycache__/posture_allocator.cpython-313.pyc
!! mlb_engine/entries/__pycache__/__init__.cpython-313.pyc
!! mlb_engine/entries/__pycache__/delivery_record.cpython-313.pyc
!! mlb_engine/entries/__pycache__/dk_entries_manager.cpython-313.pyc
!! mlb_engine/entries/__pycache__/gate_classes.cpython-313.pyc
!! mlb_engine/entries/__pycache__/upload_manifest.cpython-313.pyc
!! mlb_engine/field/__pycache__/__init__.cpython-313.pyc
!! mlb_engine/field/__pycache__/contest_library.cpython-313.pyc
!! mlb_engine/field/__pycache__/field_miner.cpython-313.pyc
!! mlb_engine/field/__pycache__/ownership_prior.cpython-313.pyc
!! mlb_engine/intake/__pycache__/__init__.cpython-313.pyc
!! mlb_engine/intake/__pycache__/live_data_adapters.cpython-313.pyc
!! mlb_engine/intake/__pycache__/paste_lineups.cpython-313.pyc
!! mlb_engine/intake/__pycache__/paste_odds.cpython-313.pyc
!! mlb_engine/intake/__pycache__/platoon_order_adapter.cpython-313.pyc
!! mlb_engine/intake/__pycache__/slate_intake_manager.cpython-313.pyc
!! mlb_engine/optimize/__pycache__/__init__.cpython-313.pyc
!! mlb_engine/optimize/__pycache__/bank_cache.cpython-313.pyc
!! mlb_engine/optimize/__pycache__/classic_sleeves.cpython-313.pyc
!! mlb_engine/optimize/__pycache__/optimizer_v3.cpython-313.pyc
!! mlb_engine/optimize/__pycache__/roster_contracts.cpython-313.pyc
!! mlb_engine/optimize/__pycache__/showdown.cpython-313.pyc
!! mlb_engine/optimize/__pycache__/showdown_theses.cpython-313.pyc
!! mlb_engine/optimize/__pycache__/tail_candidate_scanner.cpython-313.pyc
!! mlb_engine/pipeline/__pycache__/__init__.cpython-313.pyc
!! mlb_engine/pipeline/__pycache__/baseline.cpython-313.pyc
!! mlb_engine/pipeline/__pycache__/build_state_manager.cpython-313.pyc
!! mlb_engine/pipeline/__pycache__/deadline.cpython-313.pyc
!! mlb_engine/pipeline/__pycache__/deadline_governor.cpython-313.pyc
!! mlb_engine/pipeline/__pycache__/execution_pipeline.cpython-313.pyc
!! mlb_engine/production/__pycache__/__init__.cpython-313.pyc
!! mlb_engine/production/__pycache__/contracts.cpython-313.pyc
!! mlb_engine/production/__pycache__/csvio.cpython-313.pyc
!! mlb_engine/production/__pycache__/demo.cpython-313.pyc
!! mlb_engine/production/__pycache__/evidence.cpython-313.pyc
!! mlb_engine/production/__pycache__/intake.cpython-313.pyc
!! mlb_engine/production/__pycache__/monitor.cpython-313.pyc
!! mlb_engine/production/__pycache__/optimizer.cpython-313.pyc
!! mlb_engine/production/__pycache__/portfolio.cpython-313.pyc
!! mlb_engine/production/__pycache__/referee.cpython-313.pyc
!! mlb_engine/production/__pycache__/simulation.cpython-313.pyc
!! mlb_engine/production/__pycache__/state.cpython-313.pyc
!! mlb_engine/production/__pycache__/workflow.cpython-313.pyc
!! mlb_engine/projections/__pycache__/__init__.cpython-313.pyc
!! mlb_engine/projections/__pycache__/projection_builder.cpython-313.pyc
!! mlb_engine/projections/__pycache__/xwoba_base_correction.cpython-313.pyc
!! mlb_engine/swap/__pycache__/__init__.cpython-313.pyc
!! mlb_engine/swap/__pycache__/late_swap_manager.cpython-313.pyc
!! outputs/2026-06-03/autobuild_child_1.json
!! outputs/2026-06-03/autobuild_decisions.json
!! outputs/2026-06-28/autobuild_child_1.json
!! outputs/2026-06-28/autobuild_decisions.json
!! outputs/2026-07-18/DKEntries_showdown_1420_1g_sd.csv
!! outputs/2026-07-18/DKEntries_showdown_1420_1g_sd_BASELINE_8e53318d4b43.csv
!! outputs/2026-07-18/autobuild_child_1.json
!! outputs/2026-07-18/autobuild_decisions.json
!! outputs/2026-07-18/build_brief_showdown_1420_1g_sd_BASELINE_8e53318d4b43.json
!! runs/.publication-lock.sqlite3
!! runs/20261002T170234Z_11cf9b24/candidate/DO_NOT_UPLOAD_DKEntries.csv
!! runs/20261002T170234Z_11cf9b24/final/DKEntries.csv
!! runs/20261002T170234Z_11cf9b24/final/assignments.csv
!! runs/20261002T170234Z_11cf9b24/final/diagnostics.json
!! runs/20261002T170234Z_11cf9b24/final/projections.csv
!! runs/20261002T170234Z_11cf9b24/inputs/DKEntries_replay.csv
!! runs/20261002T170234Z_11cf9b24/inputs/DKSalaries_replay.csv
!! runs/20261002T170234Z_11cf9b24/manifest.json
!! runs/20261002T170254Z_bb179654/candidate/DO_NOT_UPLOAD_DKEntries.csv
!! runs/20261002T170254Z_bb179654/final/DKEntries.csv
!! runs/20261002T170254Z_bb179654/final/assignments.csv
!! runs/20261002T170254Z_bb179654/final/diagnostics.json
!! runs/20261002T170254Z_bb179654/final/projections.csv
!! runs/20261002T170254Z_bb179654/inputs/DKEntries_replay.csv
!! runs/20261002T170254Z_bb179654/inputs/DKSalaries_replay.csv
!! runs/20261002T170254Z_bb179654/manifest.json
!! runs/20261002T170416Z_d2fed36a/candidate/DO_NOT_UPLOAD_DKEntries.csv
!! runs/20261002T170416Z_d2fed36a/final/DKEntries.csv
!! runs/20261002T170416Z_d2fed36a/final/assignments.csv
!! runs/20261002T170416Z_d2fed36a/final/diagnostics.json
!! runs/20261002T170416Z_d2fed36a/final/projections.csv
!! runs/20261002T170416Z_d2fed36a/inputs/DKEntries_replay.csv
!! runs/20261002T170416Z_d2fed36a/inputs/DKSalaries_replay.csv
!! runs/20261002T170416Z_d2fed36a/manifest.json
!! runs/20261002T170437Z_1495cc09/candidate/DO_NOT_UPLOAD_DKEntries.csv
!! runs/20261002T170437Z_1495cc09/final/DKEntries.csv
!! runs/20261002T170437Z_1495cc09/final/assignments.csv
!! runs/20261002T170437Z_1495cc09/final/diagnostics.json
!! runs/20261002T170437Z_1495cc09/final/projections.csv
!! runs/20261002T170437Z_1495cc09/inputs/DKEntries_replay.csv
!! runs/20261002T170437Z_1495cc09/inputs/DKSalaries_replay.csv
!! runs/20261002T170437Z_1495cc09/manifest.json
!! runs/20261002T170748Z_7d5afb51/candidate/DO_NOT_UPLOAD_DKEntries.csv
!! runs/20261002T170748Z_7d5afb51/final/DKEntries.csv
!! runs/20261002T170748Z_7d5afb51/final/assignments.csv
!! runs/20261002T170748Z_7d5afb51/final/diagnostics.json
!! runs/20261002T170748Z_7d5afb51/final/projections.csv
!! runs/20261002T170748Z_7d5afb51/inputs/DKEntries_replay.csv
!! runs/20261002T170748Z_7d5afb51/inputs/DKSalaries_replay.csv
!! runs/20261002T170748Z_7d5afb51/manifest.json
!! runs/20261002T171939Z_19c032ea/final/diagnostics.json
!! runs/20261002T171939Z_19c032ea/final/projections.csv
!! runs/20261002T171939Z_19c032ea/inputs/DKEntries_replay.csv
!! runs/20261002T171939Z_19c032ea/inputs/DKSalaries_replay.csv
!! runs/20261002T171939Z_19c032ea/manifest.json
!! runs/20261002T172404Z_adfdd349/final/diagnostics.json
!! runs/20261002T172404Z_adfdd349/final/projections.csv
!! runs/20261002T172404Z_adfdd349/inputs/DKEntries_replay.csv
!! runs/20261002T172404Z_adfdd349/inputs/DKSalaries_replay.csv
!! runs/20261002T172404Z_adfdd349/manifest.json
!! runs/20261002T172405Z_1d805441/candidate/DO_NOT_UPLOAD_DKEntries.csv
!! runs/20261002T172405Z_1d805441/final/DKEntries.csv
!! runs/20261002T172405Z_1d805441/final/assignments.csv
!! runs/20261002T172405Z_1d805441/final/diagnostics.json
!! runs/20261002T172405Z_1d805441/final/projections.csv
!! runs/20261002T172405Z_1d805441/inputs/DKEntries_replay.csv
!! runs/20261002T172405Z_1d805441/inputs/DKSalaries_replay.csv
!! runs/20261002T172405Z_1d805441/manifest.json
!! runs/bank_cache_2026-06-28_74f2ce40d4.json
!! runs/bank_cache_2026-06-28_74f2ce40d4.json.lock.sqlite3
!! runs/bank_cache_2026-06-28_74f2ce40d4_salary_only.json
!! runs/bank_cache_2026-06-28_74f2ce40d4_salary_only.json.lock.sqlite3
!! runs/latest_valid_run.json
!! tests/__pycache__/__init__.cpython-313.pyc
!! tests/__pycache__/conftest.cpython-313.pyc
!! tests/__pycache__/test_core.cpython-313.pyc
!! tests/__pycache__/test_golden_replay.cpython-313.pyc
!! tests/__pycache__/test_greenfield_regressions.cpython-313.pyc
!! tests/__pycache__/test_paste_lineups.cpython-313.pyc
!! tests/__pycache__/test_production.cpython-313.pyc
!! tests/__pycache__/test_showdown.cpython-313.pyc
!! tests/__pycache__/test_upload_integrity.cpython-313.pyc
!! tools/__pycache__/audit.cpython-313.pyc
!! tools/__pycache__/autobuild.cpython-313.pyc
!! tools/__pycache__/awaiting_standings.cpython-313.pyc
!! tools/__pycache__/benchmark_engine.cpython-313.pyc
!! tools/__pycache__/bootstrap_engine.cpython-313.pyc
!! tools/__pycache__/build_asserted.cpython-313.pyc
!! tools/__pycache__/claim.cpython-313.pyc
!! tools/__pycache__/dfs.cpython-313.pyc
!! tools/__pycache__/env_probe.cpython-313.pyc
!! tools/__pycache__/extract_inbox_zips.cpython-313.pyc
!! tools/__pycache__/fetch_fangraphs_platoon.cpython-313.pyc
!! tools/__pycache__/fetch_rotowire_lineups.cpython-313.pyc
!! tools/__pycache__/fetch_slate_bundle.cpython-313.pyc
!! tools/__pycache__/late_swap.cpython-313.pyc
!! tools/__pycache__/lineups_from_paste.cpython-313.pyc
!! tools/__pycache__/net_to_date.cpython-313.pyc
!! tools/__pycache__/odds_from_paste.cpython-313.pyc
!! tools/__pycache__/outcome_review.cpython-313.pyc
!! tools/__pycache__/ownership_grade_archive.cpython-313.pyc
!! tools/__pycache__/ownership_pred.cpython-313.pyc
!! tools/__pycache__/plan_status.cpython-313.pyc
!! tools/__pycache__/preflight_upload.cpython-313.pyc
!! tools/__pycache__/promote_run.cpython-313.pyc
!! tools/__pycache__/qa_portfolio.cpython-313.pyc
!! tools/__pycache__/rebuild_registry.cpython-313.pyc
!! tools/__pycache__/refresh_reference_data.cpython-313.pyc
!! tools/__pycache__/repair_entry.cpython-313.pyc
!! tools/__pycache__/replay_slate.cpython-313.pyc
!! tools/__pycache__/retro.cpython-313.pyc
!! tools/__pycache__/solver_probe.cpython-313.pyc
!! tools/__pycache__/stack_shape_probe.cpython-313.pyc
!! tools/__pycache__/stage_slate.cpython-313.pyc
!! tools/__pycache__/sync_check.cpython-313.pyc
!! tools/__pycache__/verify_engine.cpython-313.pyc
!! tools/__pycache__/verify_export.cpython-313.pyc
!! tools/__pycache__/wheel_fetch.cpython-313.pyc
```

</details>

## 2. Summary table

| ID | Category | Priority | Class | Tier | Effort | Confidence | One line | Overlap |
|---|---|---|---|---|---|---|---|---|
| F-01 | BUG | P0 | P | 1 | S | REPRODUCED | Normalize negative historical points before building the baseline | R389 Complete; distinct from R299(f) |
| F-02 | BUG | P0 | V | 1 | S | REPRODUCED | Use portable artifact keys when restoring Windows runs | new; distinct from R473 |
| F-03 | OBJECTIVE | P1 | S | 2 | S | REPRODUCED | Count partially reduced consensus-pair seat requirements as relaxations | R469 Complete |
| F-04 | TEST | P2 | P | 7 | S | REPRODUCED | Fail the development gate when a registered suite is absent | new; distinct from R180(c) |
| F-05 | TEST | P2 | P | 7 | S | REPRODUCED | Make simulated host tests independent of the executing OS | new; completed host support |
| F-06 | STRATEGY | P2 | P | 7 | XS | INFERRED | Move the atomic-write remainder out of Tier 2 | R227(b): wrong tier |

## 3. Findings

### F-01: Normalize negative historical points before building the baseline

| Field | Value |
|---|---|
| Category | BUG |
| Priority | P0 |
| Class | P |
| Tier | 1 (docs/ROADMAP.md, 2026-09-25 priority rule) |
| Effort | S |
| Confidence | REPRODUCED |
| Location | `mlb_engine/pipeline/execution_pipeline.py:5885-5909`; `mlb_engine/pipeline/execution_pipeline.py:7506-7516`; `mlb_engine/projections/projection_builder.py:87-120` at 9adc891bc5afe94cd1b1fb70686c9d6d26771fc5 |
| Overlap | R389(b), Session 11 is Complete, but its baseline still fails. R299(f)/Session 46 covers BLANK APPG; its proposed missing-value fallback does not handle this finite negative value. This is the completed-baseline exception, not a duplicate blank-cell report. |
| Requires | none |
| Depends on | none |
| Decision | **Accept** (re-adjudicated at HEAD 9adc891, 2026-10-02, Session 144). Premise holds on its stated scope: EP `_assemble_projection_frame` (:5895-5897) writes Base from APPG unclipped and `projection_builder.validate_projection_factors` (:95-96) rejects it. Reproduced by this session with `baseline.unenriched_frame` on Bieber (ID 43433715, APPG -1.15) from the tracked 2026-06-28 CSV: `ValueError: projection factors invalid: ... 'Base contains negative values'`; APPG 0.0 passes with `Base_Projection [0.0]`. 25 of 998 salary rows are negative, all P (8 SP, 17 RP). Scope correction, not a rejection: the ENRICHED frame already clips at `apply_xwoba_correction` (pb:450) when the Savant CSVs are present, so the failure is the baseline (`run_baseline` passes `savant_*=None`, EP:7554), the degrade fallback (BS:3879) and `--no-enrichment`; the review's no-file direct run is UNCHECKED as coming from this mechanism. No open entry covers negative APPG (0 register and roadmap hits); R299(f), blank APPG in the same EP block, is batched into the chunk. Filed as R476, Session 145, exception band: the baseline safety net is absent on an ordinary slate (8 of that slate's SPs negative). |

**Issue.** The baseline converts historical DraftKings AvgPointsPerGame directly into Base, then rejects any negative Base. A finite negative historical score is not a corrupt salary, identity, or roster eligibility. The tracked June 28 slate has one such arm in the actual 220-player pool, so all three realistic runs lost their baseline before optional enrichment; the unrestricted direct run subsequently refused and left no file.

**Evidence.** The actual pool contains one negative APPG, **-1.15**; the full salary table contains 25 negatives, all pitcher rows. `baseline.unenriched_frame` on a single authoritative salary ID with its negative APPG raises:

```text
ValueError: projection factors invalid: {'passed': False, 'missing_fields': [], 'errors': ['Base contains negative values']}
```

The same row with APPG zero produces one retained row with Base_Projection 0.0. Reproduce without network: read the tracked June 28 CSV with `csv.DictReader`, select a row whose APPG is negative, and call `unenriched_frame(salary, [{"Player_ID": row["ID"], "AvgPointsPerGame": float(row["AvgPointsPerGame"])}])`. The full default direct invocation in §1 exited 3 after 519.752s, with `baseline.status=error` and no delivered path. `gate_classes.py:225-228` explicitly classifies bad statistical estimates as P.

**Why it matters.** One eligible arm prevents a baseline for all 38 reserved entries. In the deadline replay, the first legal output arrived after the requested deadline; in the unrestricted direct replay none arrived. Thus the roadmap statement that only the enhanced file remains at risk is false at this commit.

**Recommendation.** In `_assemble_projection_frame`, when deriving Base from finite historical APPG, use a declared nonnegative emergency prior, `max(0.0, APPG)`, and record the changed-row count and original value in the existing audit/Notes channel. Retain the player, salary, identity and eligibility. Preserve rejection of nonfinite numbers and explicitly supplied invalid Base values. This fixes the shared baseline and unenriched-fallback input boundary in EP alone; do not relax the numerical validator or filter the arm out.

**Acceptance.** UT `test_core.BaselineCoreTests`: add a negative-APPG retention case and an explicit-invalid-Base refusal case (+2 core tests; 2019 -> 2021 if landed alone). Extend `ClassicBaselineFirstTests` with one recorded June 28 pool fixture: a normal invocation publishes a baseline before enrichment, then an injected enhancement refusal still names a 38/38 template-exact file (+1 core; combined 2022). Assert both referees pass at 2026-06-28T17:00:00Z and each contest has distinct lineups. Budget the integration case below 15s on this host by failing enhancement immediately. GOLD unmoved unless normalization reaches an existing negative row, with any movement explicitly reviewed; PROBE, LINT, GATE.

**Risk.** The prior changes ordering for negative historical APPG. It must not erase operator-supplied projections or convert nonfinite data into plausible evidence. Baseline artifacts and immutable final bytes remain separate; no legal player-pool reduction is authorized.

### F-02: Use portable artifact keys when restoring Windows runs

| Field | Value |
|---|---|
| Category | BUG |
| Priority | P0 |
| Class | V |
| Tier | 1 (docs/ROADMAP.md, 2026-09-25 priority rule) |
| Effort | S |
| Confidence | REPRODUCED |
| Location | `mlb_engine/pipeline/build_state_manager.py:190-201`; `tools/promote_run.py:188-218` at 9adc891bc5afe94cd1b1fb70686c9d6d26771fc5 |
| Overlap | new. R228 is closed; its missing-hash refusal is correct. R473/Session 142 concerns re-promotion labels and record overwrites, not the platform-dependent artifact lookup. |
| Requires | none |
| Depends on | none |
| Decision | **Modify** (re-adjudicated at HEAD 9adc891, Session 144). The defect holds and is wider than filed. BSM :195/:200 write `str(relative)` (and `snapshot_run_inputs` :165); `promote_run.py:201` looks up the literal key `final/DKEntries.csv`. The premise agent reproduced exit 2 with the real `create_run`/`register_artifact`, and a dry-run control with only the key rewritten binds (`immutability_bind: verified`). Nine real manifests in `runs/` (2026-09-16 16:30Z, six backing 1310_4g rows, one `upload_ready certified`) carry the backslash key and refuse re-promotion from ANY host, because the lookup is a dict key; `verify_run_bundle` (BSM:277-297) and `usable_artifact` (EP:367) resolve a backslash `relative_path` as one component on POSIX. Changed: class P, not V (the delivered bytes and their legality are untouched; the recovery tool's lookup is bookkeeping); priority P1, not P0 (no file lost; the bytes sit in `runs/<id>/final/`); the fix adds the two resolution sites and the snapshot site. Filed as R477, Session 146 (batched with R478: both make the gate red on the Windows DEV host), band 2. |

**Issue.** Windows registers the export under `final\DKEntries.csv`. `promote_run` only looks up `final/DKEntries.csv`, concludes the hash is absent and refuses a correctly bound export. Rebuilding on the same host produces the same key; the offered force-unbound path unnecessarily requires Ben and discards the binding claim.

**Evidence.** A scratch run created with real `create_run` and `register_artifact`, containing a copy of the independently verified June 3 export, produced:

```text
registered_keys = ['final\DKEntries.csv']
hash_matches = True
promote_run exit = 2
REFUSED ... records no sha256 for final/DKEntries.csv ...
```

Command shape: `python tools/promote_run.py --run-id <scratch-run> --repo-root <scratch-root> --date 2026-06-03 --tag repro`. No force option was used. Four suite failures reach the same seam: `DeliveryLabelAgreementTests.test_a_re_promotion_keeps_the_review_grade_label_and_the_controls`, `ClassicTailSeatTests.test_the_delivery_record_carries_the_market_the_build_ranked_by`, and the two baseline re-promotion tests listed in §1.

**Why it matters.** A legal final export cannot be restored through the documented recovery tool on Ben's supported Windows host. This is a reachable stranded recovery file, hence P0 under this review's scale; it does not mean the initial mirror always fails or that the final bytes were deleted.

**Recommendation.** Write new relative artifact keys and `relative_path` values with `Path.as_posix()` in BSM. Add a narrowly scoped reader in `promote_run` that recognizes historical forward- and backslash forms, requires an unambiguous binding, and still compares the recorded hash against actual bytes. If both normalized keys exist with conflicting hashes, refuse. Do not rewrite old run manifests or use `--force-unbound` as migration.

**Acceptance.** UT the four existing failing re-promotion cases, plus `test_core.RunProvenanceTests` cases for canonical new keys and conflicting historical aliases (+2 core tests; 2019 -> 2021 if alone). Parameterize existing promotion coverage over forward/backslash historical keys so Linux CI exercises the Windows record shape. The verified export re-promotes with its existing review label and matching SHA; absent hash and changed bytes still refuse. GOLD unmoved; LINT, GATE.

**Risk.** A careless normalization could merge conflicting identities or weaken R228. Keep refusal for ambiguity, absolute/traversing keys and changed bytes. Preserve `runs/<id>/final/` and existing labels; the R473 label issue remains separate.

### F-03: Count partially reduced consensus-pair seat requirements as relaxations

| Field | Value |
|---|---|
| Category | OBJECTIVE |
| Priority | P1 |
| Class | S |
| Tier | 2 (docs/ROADMAP.md, 2026-09-25 priority rule) |
| Effort | S |
| Confidence | REPRODUCED |
| Location | `mlb_engine/allocate/contest_allocator.py:4097-4123`; `mlb_engine/allocate/contest_allocator.py:4998-5020` at 9adc891bc5afe94cd1b1fb70686c9d6d26771fc5 |
| Overlap | R469 / Session 138 is Complete. Its zero-compatible-candidate branch records a relaxation; this positive-but-insufficient eligible-entry branch does not. |
| Requires | none |
| Depends on | none |
| Decision | **Modify** (Session 144). Mechanism verified at CA:4117 and reproduced by this session with the review's snippet: seat block `required_by_contest {'A': 2}`, `seated_by_contest {'A': 1}`, `relaxed []`, `relaxation_steps []`, `relaxations 0`, `selection_certified True`, `allocation_certified True`. Two corrections. (1) Certification is hardcoded True on the allocator's success return (CA:5075-5076) and no S relaxation ever read it, so "certified" is by design, not the defect. (2) The acceptance assumes a label or certification consumer that would see a seat relaxation, and none exists: `manifest_strategy_state` (EP:7846, called from `_deliver_mirror` :7976) reads the ladder tuple `(candidate_reuse, primary_stack_floor, five_stack_quota)` and never `consensus_pair_seats`, so R469's zero-capacity relaxation also records `strategy_state: clean` (probed: zero-capacity and partial-capacity both `clean`). The fix therefore has two write sites (the CA relaxed row when `0 < eligible < seat_need`; the EP ladder tuple) plus `references/chalk_core_seat.md:30-33`. Band 3, not Tier 2 (judgment): it changes no lineup and prevents no washout; it makes a construction control's shortfall visible on the record. Filed as R479, Session 147. |

**Issue.** The allocator silently clamps a requested seat count to the number of eligible entries. It can report two required consensus-pair seats, select only one, and still report zero relaxations with both selection and allocation certified. The normal posture default is one; this reproduction uses the supported integer override of two and an entry compatibility mask.

**Evidence.** The real allocator, with existing test builders and no solver stub:

```python
from tests.test_core import ConsensusPairSeatTests as T
from mlb_engine.allocate.contest_allocator import select_and_assign_entries
reqs = T._reqs([("A", "large_gpp", 2)])
reqs[1]["allowed_candidate_ids"] = ["top0", "top1", "top2"]
controls = {"consensus_sp_pair": ["PA", "PB"],
            "min_consensus_pair_entries_per_contest": 2}
result = select_and_assign_entries(T._bank(), reqs, portfolio_controls=controls)
```

Result: required `A:2`, seated `A:1`, `relaxed=[]`, `relaxation_steps=[]`, `relaxations=0`, `selection_certified=True`, `allocation_certified=True`. The critical line is `lower = min(seat_need[cid], len({e for e, _k in qual}))`. The bank has multiple pair candidates; the compatibility mask leaves only one eligible entry.

**Why it matters.** The declared construction protection against a shared failure point is weaker than requested without being accounted for. A session choosing more than one consensus-pair seat for a larger contest cannot distinguish compliance from degradation. This is not evidence that the default one-seat portfolios in this review omitted their seats.

**Recommendation.** When eligible-entry capacity is positive but below `seat_need[cid]`, append one explicit relaxation with requested count, applied count, contest and reason before adding the reduced row. Use the existing seat-report counting path and expose the applied requirement alongside the requested one. Keep delivery legal and distinct; do not turn an S shortage into a V refusal or trigger an unnecessary repeated solve.

**Acceptance.** UT `test_core.ConsensusPairSeatTests`: add the exact two-entry fixture above; assert one recorded relaxation, requested=2, applied=1, seated=1 and distinct signatures (+1 core; 2019 -> 2020 alone). Retain zero-capacity and ordinary one-seat cases. Verify the existing pipeline label/certification consumer sees the nonzero strategy relaxation without hiding the file. GOLD should remain unchanged for default count=1; PROBE, LINT, GATE.

**Risk.** Changing the row itself instead of its accounting can make a feasible degraded portfolio refuse. Report-only repair must still reach the strategy-state consumer; merely adding prose to the brief is insufficient.

### F-04: Fail the development gate when a registered suite is absent

| Field | Value |
|---|---|
| Category | TEST |
| Priority | P2 |
| Class | P |
| Tier | 7 (docs/ROADMAP.md, 2026-09-25 priority rule) |
| Effort | S |
| Confidence | REPRODUCED |
| Location | `tools/audit.py:2240-2244`; `tools/audit.py:2294-2326`; `tools/audit.py:1770-1779`; `.github/workflows/gate.yml:73-81` at 9adc891bc5afe94cd1b1fb70686c9d6d26771fc5 |
| Overlap | new. R180(c) covers an UNREGISTERED new suite, whereas this case removes a suite already in AUDITED_SUITES. R217 concerns split-run state/runtime identity. Neither files this aggregation hole. |
| Requires | none |
| Depends on | none |
| Decision | **Accept** (Session 144). Verified at HEAD: `audit.py:2300-2301` filters `present: False` out of `suite_ok`, :2308-2312 routes the absent suite's advice to `warnings`, :1777 and :2985 extend `_errors` with nothing, so the aggregate passes and both the one-shot and the split path print `PASS  v2.26.0  45 modules  3038 tests  {test_production None/101 absent} [...]`; `gate.yml:80` accepts any `^PASS  v[0-9]`. Reproduced by the premise agent through the real `run_audit` and the real `assemble_gate`/`gate_report` with only the runner substituted (no tracked file deleted). R180(c) covers the opposite direction (an unregistered file on disk); R62(b) named the `absent` state and never wired it to `_errors`. No build path reads the audit verdict, so R386 is untouched. Filed as R480, batched into Session 71 (the audit-gate holes, same file), band 3. |

**Issue.** An absent registered suite is excluded from `suite_ok`, then its lost coverage becomes only a warning. The aggregate audit returns passed=True and the CLI exits zero even while checks.tests.passed=False. CI accepts any leading PASS line, so its second check does not catch this case.

**Evidence.** Injected classified runner results for all seven suites, with only `tests.test_production` marked `{present: False, ran: None}`. The real `summarize_suite_results` and `run_audit` aggregation returned:

```text
tests.passed=False; suite_passed=True; count_matches=False
aggregate.passed=True; CLI exit would be 0
PASS  v2.26.0  45 modules  3038 tests  {test_production None/101 absent}  [tests.test_production is in AUDITED_SUITES but tests/test_production.py is not on disk, so its 101 tests did not run and were never counted. This is missing coverage, not a stale pin.]
```

The runner was substituted to avoid deleting a tracked file; git/debt/skill-drift probes were neutralized, while the aggregation and formatter were real. `run_audited_suites` creates exactly this record when the registered file is absent. `classify_suite` already correctly calls it missing coverage.

**Why it matters.** All 101 tests in a required suite can disappear from a branch without making the CI gate fail. A warning that says the gate was not complete should not be accepted as its passing verdict. This is distinct from the five explicit host-dependent skips observed here.

**Recommendation.** Make an absent registered suite an `_errors` entry in the shared summary, so one-shot and split reports have the same verdict. Preserve the existing warning treatment for known guarded skips and `grew` bookkeeping; do not broaden this patch into a live-build gate or a general pin-policy change. Keep CI's exit-code check; correcting the producer is sufficient.

**Acceptance.** UT `test_core.AuditSkipHonestyTests`: add one aggregate case with an absent registered suite and one intact control (+2 core; 2019 -> 2021 alone). Both the ordinary aggregate and a complete split report must fail the absent case and omit a PASS prefix. The intact case remains passing, and known skips retain explicit warnings. Test through the aggregation entry points, not only `classify_suite`. LINT, GATE.

**Risk.** An intentional suite retirement must update AUDITED_SUITES and its pin in the same change. This is development/CI completeness only; R386 still permits a V-valid live file when a process gate is unavailable.

### F-05: Make simulated host tests independent of the executing OS

| Field | Value |
|---|---|
| Category | TEST |
| Priority | P2 |
| Class | P |
| Tier | 7 (docs/ROADMAP.md, 2026-09-25 priority rule) |
| Effort | S |
| Confidence | REPRODUCED |
| Location | `tests/test_core.py:11890-11950`; `tests/test_core.py:28232-28386`; `tests/test_showdown.py:1517-1576`; `mlb_engine/repo_env.py:255-280` at 9adc891bc5afe94cd1b1fb70686c9d6d26771fc5 |
| Overlap | new residual of completed R349/R358/R359 host support. R217(d) records runtime identity; it does not make these test fixtures portable. No production-host precedence change is proposed. |
| Requires | none |
| Depends on | none |
| Decision | **Accept** as its own entry (Session 144); the review's "new" holds: R300(c)(d) and R217(d) cover string pins and runtime identity, not OS-dependent fixtures. `repo_env.detect_host` :267-283 tests `os.name == "nt"` before the ceiling variables, by design since 8f2c6e0 (R349); the ten failures reproduced exactly (`10 failed, 13 passed, 2421 deselected`), and this session's own gate on the Windows host is the live reproduction. The gate has been red on this host since those classes were written on posix (R349 2026-09-17, R359 2026-09-19); CI is `ubuntu-latest` and green at 9adc891. A global `os.name` patch fails (`UnsupportedOperation: cannot instantiate 'PosixPath'`); a local stub for `repo_env`'s OS probe returns the expected values (unknown 130.0, declared 630.0, small 42.0). Extended: part (b) takes the three incidental Windows-only failures from §1's triage (MinerMoneyHonesty path substring, ReplaySlate float demonstration, ClassicBaselineFirst staged feed), the same class. Filed as R478, Session 146 with R477; band 3 inside a band-2 chunk. |

**Issue.** Ten tests simulate a cloud or unknown host by changing environment variables while leaving the real Windows OS probe active. Production correctly gives Windows precedence over the bash ceiling, so these fixtures fail on a supported host. They are tests of an unstated Linux precondition, not evidence that Windows should plan against 130 or 630 seconds.

**Evidence.** Both full runs failed the same ten cases: three `ClaimHostHonestyTests` cloud/foreign-cwd methods; `ProbeBudgetDefaultTests.test_the_unknown_host_still_gets_the_one_sandbox_number`; four `HostProfileTests` methods for unknown, declared ceiling, small ceiling and profile keys; and the two `GateBudgetIsHostResolvedTests` declared/unknown cases. Typical output is `540.0 != 130.0` or `'windows' != 'claude_code'`.

Reproduction: `python -m pytest tests/test_core.py tests/test_showdown.py -q -k "ClaimHostHonesty or ProbeBudgetDefault or HostProfile or GateBudgetIsHostResolved"`. `detect_host` explicitly tests `os.name == "nt"` before the bash-ceiling variables.

**Why it matters.** The required gate is red before any DEV work on Ben's pinned Windows runtime. The serial full suite spent 655s to rediscover these fixture errors; the gate spent 774s. They obscure the four real Windows recovery failures instead of helping distinguish them.

**Recommendation.** Keep production precedence. In the cloud claim subprocess fixture, set `MLB_DFS_HOST=claude_code` explicitly. In tests of unknown-host and ceiling detection, replace only the repo_env OS-probe dependency with a local test object reporting posix; avoid globally patching os.name, which also changes pathlib behavior. For import-time audit/probe subprocess tests, apply that local dependency patch before importing the target module. Preserve separate real-Windows and explicit-host precedence assertions. Reuse the existing methods rather than adding another prose/AST pin.

**Acceptance.** Run the four named classes on both the pinned Windows venv and Linux CI. The same behavioral cases must pass without skip decorators and without changing the runtime budget returned to an actual Windows build. Replace fixture setup in place: core=2019 and showdown=425 pins unchanged. A mutation that ignores an explicit call-budget override must still fail. LINT, GATE; no GOLD change.

**Risk.** A global os.name mock can make Path instantiate an unsupported path class; isolate the dependency. Do not force the entire test process to a cloud profile, because that would hide real Windows bugs such as F-02.

### F-06: Move the atomic-write remainder out of Tier 2

| Field | Value |
|---|---|
| Category | STRATEGY |
| Priority | P2 |
| Class | P |
| Tier | 7 (docs/ROADMAP.md, 2026-09-25 priority rule) |
| Effort | XS |
| Confidence | INFERRED |
| Location | `docs/ROADMAP.md:77-85`; `docs/ROADMAP.md:162-168`; `docs/backlog.md:7472-7478` at 9adc891bc5afe94cd1b1fb70686c9d6d26771fc5 |
| Overlap | R227(b) / Session 42: wrong tier under the 2026-09-25 priority rule. The implementation is already filed and is not being filed again. |
| Requires | none |
| Depends on | none |
| Decision | **Accept** as a ranking judgment; no R-number (Session 144). Verified: Session 42 holds only R227(b) (P3, S, plan-mode; the entry's own harm is "quiet loss, not a wrong file"); the only row citing it is 43, whose Needs already names R341 as landed 2026-09-30; no truncation incident is recorded in CHANGELOG.md, the ledger or either inbox. Phase 4 of this session replaces the tiers with Ben's 2026-10-02 bands, and R227(b) ranks in band 3 by impact against difficulty. |

**Issue.** Session 42 kept its Tier 2 position after all of its miner-truth work landed. Its only remainder is atomic publication of hashed support files, explicitly classified P, with no reproduced stranded delivery in that entry. Session 43's dependency is the already-landed R341, not this remainder; the current ordering therefore puts housekeeping ahead of available construction/model work for no live dependency.

**Evidence.** The roadmap row at line 162 now contains only R227(b). The next row explicitly says “Needs 42's R341, landed 2026-09-30.” The register's rewritten entry says its remaining harm is quiet loss after interruption, with readers degrading, and its proposed fix changes no optimizer or allocator line. Tier 7 is named “guard, record, hygiene”; Tier 2 is construction supported by the archive. This is a ranking judgment, not a measured lineup improvement.

**Why it matters.** A scarce postseason development session can be consumed by a plan-approval and storage patch ahead of Session 43 and the unresolved Showdown total/contest work. The remaining atomic write can still be useful, but its old miner dependency no longer earns that position.

**Recommendation.** Move the existing Session 42 remainder unchanged to Tier 7, retain its ID/status/plan, and rewrite prerequisite references to R341's completed landing wherever they still imply the whole session is needed. Keep the current NEXT instruction unless its prerequisites require a change. Do not delete the atomic-write work or reopen the rejected parallel-engine program.

**Acceptance.** LINT must exit 0; grep Session 42 and R341 references to show no construction row waits for R227(b). The row stays Pending and its original acceptance tests remain attached. No test addition or suite-pin move; no solver or golden artifact changes. GATE is the repository's normal landing requirement, not a reason to add a prose-reading test for this relocation.

**Risk.** The prerequisite wording could be updated too broadly and hide a real dependency. Preserve all dependencies other than the specifically discharged miner-truth prerequisite. If triage produces a concrete lost-file reproduction for R227(b), rank that evidence under Tier 1/3 instead.

## 4. Verified sound

- Both referees and independent cell/signature checks accepted every delivered replay file; no within-contest duplicate was found. This re-verifies the tested portion of R439's legality/F-3 clean list at this SHA, not every solve door.
- Fast auto/direct final bytes match exactly, SHA `04eb11615217224f69dbab9ba6deedebea596cf9349c39e87d67f46128f303ff`; the current full suite's determinism tests also passed. No claim of timing-independent equality for every large bank.
- Realistic auto final SHA `553e214f86d274d80bbba228378f2e8b1f890862df756440074d1a3b4ad9be6a`; deadline final SHA `2d0627a48df69b2c1dc0a0fe822d1f04d7b114a9dc1add109d586f8aad9c8b42`; both remain legal and distinct under the requested historical as-of checks.
- Showdown final SHA `4b68dde0112e87c66a081681ee6ddccfbcbec518d83437056fde4522d8a54c6a`; captain identity participates in the independent duplicate key. Its review-ready label does not claim Classic three-gate certification.
- Baseline and enhanced files remained separately named in the successful fast/Showdown runs; the supplied baseline hashes remained readable. This is narrower than claiming all failure/re-promotion paths sound; F-01/F-02 are exceptions.
- The default Classic bank now receives four/five-stack requests, cluster-limited jobs and consensus-pair jobs on sliced, direct and plan paths; grep-and-trace disproved the old “control absent everywhere” hypothesis.
- The R453 cap repair distinguishes an explicit `other_held` count from None; the None path intentionally counts the full cache, so sleeve-relative caps were not broken by that fix. Open R465 still owns served-union policy.
- The CA joint objective has no positive distinct-candidate penalty: x terms are negative normalized shape scores, y terms zero; hard overlap/reuse constraints supply that diversity. This was re-read at this commit, not inferred from comments alone.
- Known deadline S relaxations in the executed late run were recorded and kept F-3 intact. The late finish is explicitly reported rather than counted as timely delivery.
- R469's default one-seat requirement was represented in the realistic auto result; F-03 is confined to partial-capacity accounting for larger requested counts.
- `plan_status --check` succeeds at the pinned commit. The roadmap linter validates structure, not economic ordering; F-06 therefore remains possible.
- The five skipped cases have explicit missing-data/environment reasons. No skipped assertion is counted as executed coverage here.

## 5. Questions for Ben

1. **D-1 / R13:** Which remaining-postseason ladder matters: seats into larger tickets, or larger direct GPP stakes? This changes the value and frequency of nondefault consensus-seat counts in **F-03**, and the construction work advanced by **F-06**. File validity/recovery fixes F-01/F-02 do not depend on this answer.
2. **D-1 and planned volume:** Which contest types, entry counts and largest per-slate entry count will you actually use in the remaining 1–4-game slates? This determines whether F-03's count>1 trigger is relevant soon and which construction/deadline experiments follow **F-06**. No assumption that June 28's 38-entry/11-game workload is the postseason norm.
3. **D-3 / D-4, bankroll constraints:** Is any player, captain, team, game or consensus-pair concentration an explicit never-relax preference outside F-3, and should that limit be by entries or dollars? This affects **F-03** acceptance of a declared shortfall and the construction priority under **F-06**; the current review assumes only the existing recorded contract.
4. **D-9 / R13:** Can the missing GPP entry-history/payout evidence and the September 29 final hand-swap files be supplied through the existing manual archive process? This affects how the work after **F-06** is graded and how often F-03's construction choice mattered. The current record counts cannot establish what was uploaded or the outcome of every hand change.

Claude Code: leave the evidence and commit pin intact when triaging. Fill each blank Decision cell with accept, reject or modify and its reason; re-reproduce at the implementation HEAD. This document changes no strategy setting or repository authority.
