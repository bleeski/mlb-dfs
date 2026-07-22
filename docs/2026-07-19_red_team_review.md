# Red Team Review and Fix List — MLB DFS Engine

Date: 2026-07-19
Basis: full read of MLB_Classic.md, CLAUDE.md, the calibration ledger, both 07-18 briefs, the backlog, all 23 engine modules, tools, tests, and production artifacts (outputs/2026-07-19, runs/, data/). Audit verified: `PASS v2.26.0 12 modules 131 tests` after `pip install -r requirements.txt`. Every claim below was verified against code or production output, not against doc claims. Line numbers reference the working tree at commit 4309d98 plus uncommitted changes.

## How to use this file

Each item has a stable ID, priority, evidence, rationale, fix, and acceptance criteria. Items are independently actionable except where a dependency is named. Execute in the order given in the final section. P0 = do before the next slate build. P1 = correctness or material modeling gap. P2 = important, not urgent. OH = overhead to remove. IMP = new capability.

## Ground rules for whoever executes this (do not violate)

- GR-1: The certification spine is untouchable: immutable runs, candidate re-read, final re-read, hash binding, blank-reserved-row block, fail-closed late swap. Route around it, never through it.
- GR-2: The DraftKings wall is absolute. No scripted DK fetches, no uploads, no entry or money automation. Never store DK credentials.
- GR-3: `scipy.optimize.milp` is the only solver. No LLM in the certified build path.
- GR-4: Truthful labels stay. New inputs are deterministic labeled priors, never ROI, win-rate, or probability claims. (OH-4 reduces the repetition of this rule, not the rule.)
- GR-5: `tests/test_golden_replay.py` and its baseline are regenerated deliberately with a stated reason, never silently.
- GR-6: Never print, log, or commit `.env` or `THE_ODDS_API_KEY`.
- GR-7: The working tree is dirty with three in-flight workstreams. P0-1 lands before anything else touches code.

---

## Section 1: Issues

### P0-1. Commit or revert the working tree

- Evidence: 8 modified tracked files, 11 untracked paths, 572 inserted lines (waterfall wiring in `execution_pipeline.py`, field_miner v0.4, intake accent fix, Showdown companions, contest library). CLAUDE.md's own session-start rule requires a clean tree. CLAUDE.md pins the audit at 119 tests while `tools/audit.py` expects and passes 131.
- Why it matters: every rule in this project assumes docs describe code. Right now they do not. A future session (or a fixing agent) cannot tell shipped behavior from experiment, and the accent fix that rescued four confirmed hitters on 07-19 exists only as uncommitted bytes.
- Fix: three logical commits: (1) intake accent fix + slate_intake v1.8 + field_miner v0.4 + posture_allocator inferred-breadth + pipeline waterfall block + tests + audit pins; (2) Showdown companions (`roster_contracts.py`, `showdown.py`, fixtures, tests); (3) contest library + docs. Update CLAUDE.md line 38 from `119 tests` to `131 tests`.
- Acceptance: `git status` clean; `python tools/audit.py --run-tests --terse` prints PASS with the count CLAUDE.md states.

### P0-2. Process the standings inbox: the evidence loop is the declared bottleneck and it is stalled

- Evidence: `data/standings/inbox/` holds 16 unprocessed contest exports (191488360 through 192464820). `data/archive/2026-06-03/standings_191020573.csv` is also unmined. The ledger archive contains exactly one mined slate (A-001, three contests, 2026-06-29). `ownership_rows` exist for one slate. The strategic brief calls this loop "the single most important recurring action in the entire project" and sets the calibration gate at 8 to 15 conditioned slates.
- Why it matters: the entire roadmap (ownership model, duplication priors, opponent registry, projection grading) is gated on archived slates. The gate may already be near or open with data sitting on disk. Every engine hour spent before this is spent on the non-binding constraint.
- Fix: for each inbox CSV, run the documented post-slate protocol: `python -m mlb_engine.field.field_miner --registry --emit-ledger`, verification checklist (utf-8-sig, salary join rate, ownership recompute within 1.5 pts, duplication table, contest JSON), append the ledger archive block, emit `ownership_rows_<date>.csv`, update the registry, move files to `data/archive/<date>/`, commit. Ben captures the contest-page trio (entry fee, payout structure, cash line) for each; flag which contests still need it rather than blocking the mine. Where the salary CSV is missing, use the documented standings-only degraded tier.
- Acceptance: inbox empty except `.gitkeep`; one decomposition block per contest in the ledger archive; one ownership_rows CSV per slate; registry updated; a written count of conditioned slates by archetype versus the 8-to-15 gate, stated in the ledger.

### P0-3. F1 is 1.0 on every production row while Vegas totals are fetched and discarded

- Evidence: `outputs/2026-07-19/projections.csv`: F1 = 1.0 on 40/40 rows. The same morning's `slate_bundle.json` and `brief.md` carried DK and FD totals for all 16 games, including Coors at 11.0. `tools/stage_slate.py:240` admits the odds packet "is not a run_slate input in the current engine ... so it rides alongside the kwargs." Grep confirms no Vegas input reaches any factor anywhere in `mlb_engine/`.
- Why it matters: game environment is the strongest exogenous projection signal in MLB DFS. The engine currently prices a Coors 11-total game and a pitcher's-park 7-total game identically. You are paying API credits to fetch the one input that would most change lineups, then optimizing without it.
- Fix: add an F1 builder in `projection_builder.py`: per game, implied team totals from the totals packet (total split by moneyline via the existing implied-probability helpers in `live_data_adapters`; plain total/2 when moneylines are absent), F1 = clip(team_total / league_mean_team_total, 0.85, 1.15) for hitters. Pitchers: either leave 1.0 in v1 or apply the inverse clip against the opposing team total. Wire through `run_slate(odds_packet=...)` following the exact `f4_by_player_id` pattern: applied only where no explicit F1 exists, Notes-tagged, surfaced under `projection_enrichment["f1"]`, zero-match on a real pool raises (ledger 3.6 discipline). Labeled prior, never a probability claim.
- Acceptance: a wiring test drives a synthetic totals packet through `run_slate` and asserts a non-neutral F1 lands on the correct rows and that the Coors-style game's hitters exceed the low-total game's; production frame shows non-neutral F1 the next slate; enrichment report present in checkpoint.

### P1-4. Weather and odds gates are stamped True without any check

- Evidence: `execution_pipeline.py:2232-2240`: `gate_defaults = {... "weather_gate_passed": True, "odds_gate_passed": True ...}`, classified `caller_asserted`, flowing into certification.
- Why it matters: every certified run permanently records that weather and odds gates passed when nothing was checked. This is precisely the silent-failure class ledger invariant 3.6 exists to kill, sitting inside the certification record itself.
- Fix: when an odds packet is supplied, derive `odds_gate_passed` from per-game total coverage (the §5 rule: one current total, source, timestamp per game). When a weather packet is supplied, derive `weather_gate_passed` from roof resolution and wind fields for outdoor venues. When neither is supplied, record the gate value as `"not_supplied"` (or `passed=False` with a `skipped` reason), never a bare True, and surface it on the checkpoint Blockers/warnings line.
- Acceptance: diagnostics for a build without packets show `not_supplied`; a build with packets shows derived values; a test covers both.

### P1-5. F5 exists, is audited, and has zero callers

- Evidence: `slate_intake_manager.compute_f5_factor` (line 1346) has no callers in the engine. `fetch_slate_bundle.py` pulls Open-Meteo per-venue hourly weather; `stage_slate.py` returns it under `staged["weather"]` and drops it. F5 = 1.0 on all production rows. The park and wind CSVs are audited schema files feeding nothing.
- Why it matters: same class as P0-3. Wind at Wrigley and a closed roof at Rogers Centre are exactly the deterministic, threshold-gated adjustments the engine already codified, and they never run.
- Fix: adapter from bundle weather to `compute_f5_factor` inputs (wind direction/speed vs the venue threshold in `team_to_venue.csv`, roof status, delay/postponement risk), producing `f5_by_player_id` consumed through the same enrichment pattern as F4/F1. Keep the manual roof rule: a forecast is never a roof status; unresolved retractable roofs stay a checkpoint warning requiring Ben's confirmation. Postponement risk maps to the existing game-exposure-cap control.
- Acceptance: wiring test: 15 mph out at a high-sensitivity park moves hitter F5 up and pitcher F5 down per the band table; closed roof yields no wind adjustment; unresolved roof surfaces a warning.

### P1-6. Three name normalizers that disagree, and unmatched confirmed hitters fail silent

- Evidence: `slate_intake_manager.normalize_name` (NFKD as of uncommitted v1.8; suffix set without "v"), `xwoba_base_correction._norm_name` (ascii-ignore, suffix set with "v"), `field_miner.normalize_name` (a third). The pre-v1.8 accent bug silently dropped confirmed hitters on two real slates (4 on 07-19, 6 on an earlier catch). Joins require exactly one hit; ambiguity or a miss means the player is silently absent from the pool.
- Why it matters: the pool contract is the intake front door; a silently missing confirmed leadoff bat is a strictly worse failure than a crash. Divergent normalizers mean the crosswalks can disagree with each other on the same player.
- Fix: one `normalize_name` in a single shared module; all three call sites import it. NFKD + combining-mark strip, one suffix set (jr, sr, ii, iii, iv; exclude "v" because it eats legitimate middle initials, and document that choice). Escalate any unmatched or ambiguous confirmed hitter from a pool-report warning to the Blockers line (a confirmed starter the pool cannot place is a blocker by definition).
- Acceptance: exactly one definition in the codebase (grep); tests cover Hernández/Giménez accents, Jr. suffixes, an ambiguous two-hit case, and a non-Latin character; a confirmed hitter who fails to match produces a blocker, not absence.

### P1-7. Doubleheader lock times key on "AWAY@HOME" and game 2 overwrites game 1

- Evidence: observed live on 07-19 (LAD@NYY twice: the 7:20 PM entry overwrote 12:35 PM in a diagnostic side-output). The uncovered-player fallback in `live_data_adapters.py:250-264` also binds the first game id containing the team token.
- Why it matters: lock state drives late-swap eligibility. A wrong lock time on a doubleheader day can mark a locked player swappable. The fail-closed doctrine is defeated by a key collision.
- Fix: key lock times by MLB `gamePk` (present in the feed), with the team-pair string retained only as a display label. Fix the uncovered-fallback scan to require date+time agreement, not first substring match.
- Acceptance: a test feed with two same-pair games resolves two distinct lock times and the status map binds each salary row to the correct game.

### P1-8. Allocator percentage caps round down and the production allocator has no infeasibility diagnosis

- Evidence: `contest_allocator.py:523` `_cap_count = max(1, floor(total*pct))`: a 45% player cap at 4 entries floors to 1, an effective 25%. `select_and_assign_entries` returns a bare "MILP infeasible or timed out" with no binding-constraint report (the pre-solve feasibility report lives upstream in `run_slate` only).
- Why it matters: silent cap tightening plus an undiagnosed hard fail is exactly the thin-slate failure family v2.25/v2.26 were built to end; it survives inside the allocator when called directly or when the upstream floors do not cover a control.
- Fix: define cap semantics once: a percentage cap permits `max(1, round_half_up(total*pct))` appearances, documented; apply the v2.26 feasibility floors inside `select_and_assign_entries` itself (not only in `run_slate`); on infeasibility, rerun the cheap structural checks and name the binding constraint and required value in the returned diagnostics.
- Acceptance: unit test: total=4, pct=0.45 yields 2; an intentionally infeasible fixture returns the named binding constraint instead of a bare failure.

### P2-9. Bank "diversity" can legally collapse to 8-of-10 shared players

- Evidence: `MAX_OVERLAP_CEILING = ROSTER_SIZE - 2 = 8` (`optimizer_v3.py:143`); the relaxation loop climbs to it under pressure; dedup is exact-player-set only, so one bench swap counts as a distinct lineup.
- Why it matters: ledger 3.5 doctrine is decorrelated ceiling; a bank of near-clones satisfies every constraint while delivering correlated bullets. The failure is invisible because feasibility and certification still pass.
- Fix: cap relaxation at 7 (both SPs plus 5 shared hitters) unless explicitly overridden; emit a bank overlap distribution (max, median pairwise shared players) on the checkpoint; warn whenever relaxation exceeded 6 on any accepted pair.
- Acceptance: checkpoint carries the overlap histogram; test asserts the warning fires and the ceiling honors the new default.

### P2-10. Showdown bank cannot generate captain-swap variants

- Evidence: `showdown.py` forbids by the sorted 6-player set (`:161-165, :206, :226`); CPT identity is not in the signature, so same-six-different-captain lineups are unreachable. The captain choice is the primary lever in that format.
- Fix: bank-generation signature becomes `(frozenset(players), cpt_id)`; same-contest duplication legality keeps the DK definition (same six plus same captain).
- Acceptance: the bank produces CPT rotations over a strong core; certifier treats them as distinct; test covers it.

### P2-11. The roadmap depends on modules that do not exist in this repo

- Evidence: `parked/` is absent from the tree and from all git history (repo starts at the restructure). `docs/legacy/mlb_v2_26_0_manifest.txt` confirms `slate_sim.py`, `calibration_engine.py`, `contest_results_tracker.py`, `post_slate_evaluator.py` lived in `parked/` pre-migration. MLB_Classic.md §15/15a/16 describe them as present; the strategic brief's Horizon 2 ("un-park the correlation sim, the crown jewel") points at nothing.
- Why it matters: the single component that ever distinguished ceiling from mean at the portfolio level is the sim, and the plan to fit it is a dangling pointer. Docs that describe absent code are how the xwOBA no-op happened.
- Fix, path A (preferred): recover `parked/` from the pre-migration project seed and store under `research/` (untracked). Path B: mark §15/15a/16 "retired at migration, spec retained" and treat §16 as the reimplementation spec (it is detailed enough). Either way, docs and tree must agree.
- Acceptance: no doc references a file that does not exist; the brief's Horizon 2 names a real path.

### P2-12. Contest-shape scoring is partly dead config

- Evidence: `optimizer_v3.py:2738-2742`: non-cash shapes use `projection_component = ceiling`, ignoring the per-shape `ceiling_weight`/`floor_weight`. `leverage_bonus_weight` and `right_tail_weight` are defined in `CONTEST_SHAPE_PROFILE_WEIGHTS` (2123-2196) and never read anywhere. `right_tail_bonus` is computed and never added to `contest_fit`. The MILP objective itself is plain `sum(Ceiling)` regardless of shape (`:479-486, :564`); shape only reranks the bank.
- Why it matters: the config advertises differentiation the math does not perform. An operator (or a future agent) tuning `right_tail_weight` is turning a disconnected knob. "WTA_First_Place_Proxy" and "Portfolio_EV_Proxy" produce nearly identical orderings today, especially since uniform 0.58/1.42 multipliers make ceiling rank-near-identical to mean outside the xISO/K-rate spread.
- Fix, v1 (now): delete the dead keys, document the real formula (ceiling + stack bonus + order-cluster bonus + salary-uniqueness minus field pressure), and add a test that enumerates profile keys and asserts each is consumed. Fix, v2 (after IMP-3/P2-11): reintroduce shape-specific terms only when a variance-aware metric exists to feed them.
- Acceptance: every key in every profile is consumed or removed; the formula in MLB_Classic §7 matches the code.

### P2-13. Small correctness and honesty cleanups

- `posture_allocator.classify_tier`: clamp inferred breadth to [0,1] and warn on out-of-range library values (currently `float()` with no validation; 1.5 silently classifies Tier F).
- Stale "untracked companion / 26-file cap" headers on `field_miner.py`, `ownership_prior.py`, `posture_allocator.py`, `contest_library.py`: they are tracked, and the file cap and checksum manifest were retired at v3.0.0-pre. Update headers to "companion, outside the audited test pins."
- `execution_pipeline.py` title line says v1.9; `VERSION = "v1.10"`. Align.
- MLB_Classic.md §13 still references `checksums_sha256_v2_24_0.json`; the manifest retired checksums ("git history is provenance"). Update §13.
- Acceptance: greps for "26-file", "untracked companion", and the checksum filename return only historical notes in docs/legacy.

---

## Section 2: Overhead to remove (doing it costs more than it returns)

### OH-1. Delete the Diversification Units subsystem

- Evidence: the production path sets `bank_du=None` (`optimizer_v3.py:2925`, `bank_constraint_scope='selection'`); `contest_allocator.py:548` states production "replaces DU/right-tail machinery." The DU code (signatures, penalty rotation, relaxation ladder, validators, ~1331-1655 plus retry machinery) runs only in the non-default path.
- Rationale: several hundred lines of intricate, tested, dead-in-production machinery that every future reader must understand before trusting the bank builder. Git history preserves it if ever wanted.
- Fix: remove DU code paths, parameters, and their tests; simplify `build_multi_lineup` accordingly.
- Acceptance: audit passes with reduced count; no `du_` references outside git history; golden replay unchanged (it never exercised DU).

### OH-2. Delete the legacy allocator and the contradictory bank-sizing function

- Evidence: `assign_lineups_to_contests` + `_assign_lineups_greedy_fallback` (`contest_allocator.py:458-774`) are marked legacy. `_default_candidate_bank_target` (`:947-955`) still hard-caps at `min(40, ceil(1.5*n))`, the exact behavior v3.18's `resolve_candidate_bank_size` was shipped to remove; two sizing authorities now disagree.
- Fix: remove both; `optimizer_v3.resolve_candidate_bank_size` is the single sizing authority.
- Acceptance: one sizing function; grep clean; tests updated.

### OH-3. Drop the reuse-penalty objective term in the joint MILP

- Evidence: `contest_allocator.py:1388` adds `reuse_penalty * 0.01` on the used-candidate indicators. Under minimization this mildly prefers fewer distinct candidates (more concentration), the opposite of its apparent intent, at a magnitude that is noise against 0-100 normalized scores.
- Fix: keep the `y` variables (they linearize `max_shared_players`), delete the objective coefficient.
- Acceptance: objective contains only normalized shape scores; a test pins that.

### OH-4. Compress the truthful-labels boilerplate to one authority

- Evidence: "never a win-rate, ROI, or probability claim" and variants appear dozens of times; several docstrings are longer than the functions they guard and mostly re-justify the feature's right to exist.
- Rationale: the discipline is correct and stays (GR-4). The repetition costs operator attention on every read and burns context in every agent session. One authoritative statement is stronger than fifty scattered ones.
- Fix: state the rule once in MLB_Classic.md §1 and once in the ledger header; replace module-level repetitions with a one-line pointer ("Labels: see MLB_Classic §1"). Trim feature docstrings to what the function computes and its contract.
- Acceptance: grep count for the phrase drops to a handful; no semantic content lost (the rule text itself is unchanged where it lives).

### OH-5. Retire the triple version bookkeeping

- Evidence: docstring framework stamps + module VERSION constants + hand-maintained pins in `tools/audit.py` (`EXPECTED_VERSION_TEXT`). Every functional bump edits three places; the working tree already shows the drift this invites (P2-13). MANIFEST.md declared git the provenance authority.
- Fix: keep module `VERSION` constants; delete docstring framework stamps; have `audit.py` read versions from the imported modules rather than string-matching pinned literals, so a bump is one edit. Keep the test-count pin (it catches silent test loss).
- Acceptance: version bump touches exactly one file plus the changelog; audit still fails on import/compile/test-count problems.

### OH-6. One canonical export name per slate in outputs/

- Evidence: `outputs/2026-07-17/` holds three names for the same deliverable plus `_v2` variants; `runs/` already preserves full provenance immutably.
- Fix: adopt `outputs/<slate>/DKEntries_<slate>_CERTIFIED.csv` (the 07-19-afternoon4 pattern) as the only certified name; superseded certified files move to `outputs/<slate>/superseded/`. Add one line to CLAUDE.md's deliverables rule.
- Acceptance: naming rule documented; next slate produces exactly one certified file at the stated path.

### OH-7. Reconcile the compact-bank doctrine with the 150-cap reality

- Evidence: MLB_Classic §7 prescribes ~8-24 candidates ("compact bank, unique demand"); v2.25 raised `DEFAULT_CANDIDATE_BANK_CAP` to 150 and forces SP-pair coverage; the 07-19 two-game build used 30. Both texts are presented as current doctrine.
- Fix: rewrite §7 to the actual rule: size to unique demand plus forced coverage of viable SP pairs and stack teams, cap 150, with the coverage report as the arbiter. Delete the stale numbers.
- Acceptance: §7 matches `resolve_candidate_bank_size` and `build_diverse_candidate_bank` behavior.

### OH-8. Stop hand-narrating validation the pipeline already certifies

- Evidence: build reports restate row counts, cap checks, and salary ranges by hand ("independent validation"); the post-export gates already computed all of it into diagnostics.json.
- Rationale: hand-restated numbers can drift from the diagnostics they mirror, which is the exact doc-vs-code failure class this project keeps meeting.
- Fix: generate the build report's validation section from diagnostics.json (small helper emitting markdown), keep prose for thesis and findings only.
- Acceptance: validation numbers in reports are generated, not typed.

---

## Section 3: Improvements

### IMP-1. Fit ownership v0 from the archive you are about to have (after P0-2)

- Rationale: `_ownership_pct_for_row` already prefers a `Projected_Ownership_Pct` column (`optimizer_v3.py:2244-2249`); today it always falls back to a flat Mid=12.0, so the entire field-pressure term is a constant. The moment the column carries real numbers, the existing scoring math wakes up with zero engine changes. The inbox likely holds 6-8 slates of actuals; the ledger says 8-15 opens the gate.
- Fix: cold-path script (research/, untracked): features per player-slate from data already captured (salary percentile, value, batting-order slot, probable-SP flag, team implied total once P0-3 lands, archetype and field-size band), target = archived `%Drafted`. Start linear or isotonic-per-feature; grade with `ownership_prior.grade_against_actuals` (MAE, Spearman, largest misses) every slate into the ledger; promote to a per-slate `Projected_Ownership_Pct` column only after the graded error beats the flat-12 baseline across the gate count. Labels: prediction under grading, never a claim.
- Acceptance: per-slate graded error in the ledger; a stated go/no-go vs the flat baseline; production frames carry the column once promoted.

### IMP-2. Scenario-family candidate generation from the odds packet

- Rationale: MLB_Classic §7 already says scenario families should represent baseball outcomes (SP pairs, offenses, game environments), but the implemented diversity is roster-space overlap repulsion, which manufactures difference without decorrelation. With F1 wired (P0-3), you can generate outcome-space diversity deterministically: build sub-banks under labeled scenario tilts and union them.
- Fix: define K deterministic scenarios per slate (e.g., "game G over-scenario": that game's hitter F1 +10%, its pitchers -5%; one per top-total game, one chalk-neutral), solve the usual bank per scenario, tag candidates with their scenario, dedupe by signature. The allocator then naturally spreads entries across scenario argmaxes. Fully deterministic, fully labeled, no simulation required.
- Acceptance: bank candidates carry a scenario tag; checkpoint shows per-scenario counts; on a multi-game slate the bank's primary stacks span the scenario games rather than clustering on raw-ceiling argmax.

### IMP-3. A portfolio decorrelation number, cheap now, sim later

- Rationale: ledger 3.5's objective (P(at least one first) via decorrelated ceiling) is measured today only by shared-player counts. Two lineups with disjoint players in the same game still rise and fall together. A closed-form proxy needs no simulator: pairwise lineup correlation approximated from shared-team stack sizes and shared-game exposure.
- Fix: add a deterministic `portfolio_correlation_report`: pairwise proxy correlation matrix from stack/game overlap, an "effective independent bullets" summary (entries divided by mean pairwise correlation factor), shown on the checkpoint next to the exposure table. When P2-11 restores `slate_sim`, replace the proxy with sim covariance; validate sim marginals against the archived FPTS you now have per player per slate (that validation needs no ownership data and is the fastest path to a real ceiling objective).
- Acceptance: checkpoint carries the report; on the 07-19 archived build it flags that 9/15 entries share Schlittler exposure as the dominant correlation, which the exposure table alone understated.

### IMP-4. Record your own results: fees, winnings, finish percentile

- Rationale: the archive captures the field exhaustively and captures Ben not at all (the A-001 gap list literally includes "Ben's own Entry IDs"). Recording dollars in, dollars out, and finish percentile per contest is an observed outcome, fully compatible with truthful labels, and it is the only way the project ever learns whether it makes money. Right now the system can certify a file perfectly and cannot answer "are we winning."
- Fix: add a per-slate results section to the ledger schema (contest id, archetype, entries, fees, winnings, best finish percentile, notes), populated at archive time from the standings join on Ben's entry names/IDs (the standings already contain his entries). A cumulative table at the top of the archive. No claims, just bookkeeping.
- Acceptance: every archived slate carries the section; a cumulative fees/winnings line exists; A-001 and the newly mined slates are backfilled where his entries are identifiable.

### IMP-5. Data-driven Floor/Ceiling bands to replace uniform 0.58/1.42

- Rationale: uniform multipliers make ceiling-maximization rank-identical to mean-maximization except where xISO/K-rate spreads them; the sim's own formula (sigma from Ceiling minus Floor) inherits whatever these say. Archived FPTS per player per slate (post P0-2) supports fitting realized spread by role, salary band, and order slot: hitters are fat-right-tailed, aces are narrower, bottom-order bats cluster near zero.
- Fix: cold-path fit of p10/p90 by bucket from mined slates; replace the uniform constants with a small banded table (still labeled priors), keeping the Ceiling >= Floor hard error and per-player multipliers on top.
- Acceptance: banded table checked in with provenance (source slates, date); wiring test; sim calibration report (when restored) compares realized p10/p90 against the new bands.

### IMP-6. Make the opponent registry and duplication screen first-class for Tier A

- Rationale: small recurring fields are the one setting where an empirical opponent model is buildable, and the repo already captures it; meanwhile `field_miner.score_duplication_risk` is called only by its selftest. The strategic brief called duplication "the honest anti-chalk lever available today" and it is not wired.
- Fix: after P0-2 populates the registry across ~19 contests, add a checkpoint block for Tier A builds: registry match rate for the contest's known entrants, their observed chalk/stack/at-cap tendencies, plus `score_duplication_risk` run over the bank with the archetype-conditioned field tables. Review-only surface, no auto-application, consistent with doctrine.
- Acceptance: Tier A checkpoint shows the block when registry data exists; the screen's inputs cite which archived contests they came from.

### IMP-7. One-command post-slate orchestrator, plus a reminder task

- Rationale: the evidence loop stalled because it is a manual multi-step ritual. Everything downstream of Ben's one manual click is explicitly automatable per CLAUDE.md.
- Fix: `tools/post_slate.py`: unzip inbox, mine each contest, verify, append ledger blocks, update registry, emit ownership rows, move to archive, commit, and print which contest IDs still lack standings or the contest-page trio with their exact `exportfullstandingscsv/<id>` URLs. Optionally a scheduled task that runs it and reminds Ben what needs a manual pull.
- Acceptance: one command takes a full inbox to an updated ledger and clean inbox; the reminder lists outstanding pulls.

### IMP-8. Close the stage-to-run gap for bundles

- Rationale: `stage_slate.py` already assembles everything; after P0-3/P1-5, the odds and weather packets should ride inside `run_slate_kwargs`, not alongside them, so a session cannot forget to pass them.
- Fix: `build_slate_pool`/`stage_slate` emit `odds_packet` and `weather_packet` in `run_slate_kwargs`; also capture `x-requests-remaining` into the bundle (flagged in the 07-19 brief and dropped).
- Acceptance: splatting `run_slate_kwargs` alone produces non-neutral F1/F5 when data exists; quota surfaces in the bundle.

### IMP-9. Second golden replay on a thin slate

- Rationale: the existing golden anchors a 2026-06-03 mid-size slate; the historical failure cluster (feasibility floors, diverse-bank forcing, pct-cap floors) lives on 2-game slates. The archived 07-19 run inputs are a ready-made fixture.
- Fix: `test_golden_replay_thin.py` against the archived 07-19 two-game inputs, asserting gate results, applied feasibility floors, and assignment shape. Regenerate deliberately per GR-5 when engine changes legitimately shift it.
- Acceptance: both replays in the audited suite; thin-slate floor behavior is now regression-locked.

### IMP-10. Vectorize the scoring hot path (do this last)

- Rationale: `score_lineup_candidate` and its helpers run `iterrows` per candidate per shape, and pairwise overlap constraints are O(K^2) with the cap now 150. It is real waste, but compute is not the binding constraint; evidence is. Sequence it after everything above.
- Fix: precompute per-candidate player-id arrays and per-player attribute lookups once per bank; score shape-independent components once per candidate; vectorize overlap counts with set arrays.
- Acceptance: bank scoring wall-time drops measurably on a 150-candidate bank; identical scores (bitwise) to the current implementation.

### IMP-11. Decide what winning means, on the record

- Rationale: the mandate says "winning lineups quickly and efficiently"; the engine is ~23k lines wrapped around $1-5 contests at 15 entries a slate. That is a fine craft project or an underfunded edge project, but it cannot be both by accident. IMP-4 gives you the P&L record to decide with.
- Fix: after 15 graded slates, write a one-page ledger entry: observed net, observed finish distribution, and a decision: scale stakes, keep building, or freeze the engine and just play the loop. Set the review date now so the decision is scheduled, not drifted into.
- Acceptance: a dated decision entry exists in the ledger.

---

## Suggested execution order

1. P0-1 (clean tree) — everything else assumes it.
2. P0-2 + IMP-7 (mine the inbox, build the orchestrator while doing it) — unblocks IMP-1/4/5/6 and may open the calibration gate.
3. P0-3, P1-4, P1-5, IMP-8 (odds and weather become real inputs and real gates).
4. P1-6, P1-7, P1-8 (correctness edges that can cost a live slate).
5. OH-1 through OH-8 (one deletion pass, one doc-reconciliation pass).
6. P2-9 through P2-13 (bank honesty, showdown captains, roadmap/doc truth).
7. IMP-1, IMP-2, IMP-3, IMP-4, IMP-5, IMP-6 (the modeling layer, now fed by evidence).
8. IMP-9, IMP-10, IMP-11.

Two structural rules for the whole effort: no new subsystem lands until the inbox is empty and stays empty (the loop outranks the engine), and every new input follows the enrichment pattern that already works (labeled prior, Notes-tagged, surfaced in projection_enrichment, wiring-tested, loud on zero-match).
