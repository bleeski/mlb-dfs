# MLB Classic version history

This file holds the v2.25.0 through v2.20.0 change sections moved out of
MLB_Classic.md on 2026-07-27. MLB_Classic.md remains the strategy authority
for current behavior.

## 0.0 v2.25.0 changes

- Coverage-guaranteed candidate bank. `optimizer_v3.resolve_candidate_bank_size`
  10+ branch was `min(40, ceil(requested * 1.5))`, so any field above ~27 entries
  capped at 40 candidates; it is now `ceil(requested * 2)` under a raised
  `DEFAULT_CANDIDATE_BANK_CAP` (80 -> 150). New `build_diverse_candidate_bank`
  wraps `build_candidate_lineup_bank`, then deterministically forces additional
  legal lineups across every viable SP pair (breadth) and rotating team stacks
  (depth), deduped by exact player set, until the bank covers the viable SP pairs
  and reaches target size. This fixes the thin-slate collapse where the
  overlap-repulsion heuristic in `build_multi_lineup` halts on the first
  infeasible lineup and the bank clusters on a couple of SP pairs, which no
  exposure cap can repair because the missing diversity was never generated.
  `run_slate` now builds through `build_diverse_candidate_bank`; the augmentation
  provenance is surfaced under `candidate_bank["diversity_augmentation"]`.
- Feasibility-aware control resolution. `execution_pipeline._merged_controls_for_build`
  accepts `feasibility_floors` and raises the tightest-merged
  `max_sp_pair_repetition` and `max_shared_players` to a slate-feasible minimum
  after the min-merge and before the explicit override, so an explicit override
  always wins. `_slate_feasibility` derives the floors from the viable SP-pair
  count, entry count, and stack size: `max_sp_pair_repetition` floors to
  `ceil(entries / viable_sp_pairs)` and `max_shared_players` to
  `min(9, max_stack + 2*(pair repeats) + 1)`. This removes the standing failure
  where a single-entry posture dragged the merged pair cap to 1 and the merged
  shared-players cap to 6, both infeasible across the field, forcing a manual
  override every slate. Applied floors and any override-over-floor are reported
  under `controls_feasibility`.
- Pre-solve feasibility assertion. `run_slate` injects `checkpoint["feasibility"]`
  (via `_feasibility_report`) at the `approve=False` checkpoint. It is structural
  and bank-free, so it runs before the expensive solve: it checks SP-pair capacity
  (`viable_pairs * cap >= entries`) and the shared-players floor, and when a check
  fails it names the exact binding constraint and the required cap value in the
  checkpoint warnings. It is advisory and never a hard block, so an infeasible
  explicit override surfaces as a one-read fix instead of a rediscovery under the
  clock.

## 0.1 v2.24.1 changes

- Park factor data refresh. `f5_park_factors.csv` raw run and HR factors are
  re-sourced from Baseball Savant Statcast park factors (paired batter/pitcher
  methodology, handedness-controlled; multi-season window per the export's PA
  counts; pulled 2026-07-07): `Run_Factor_Raw` = R / 100, `HR_Factor_Raw` =
  HR / 100, applied values re-derived with the standing clip(raw, 0.94, 1.08),
  `Wind_Sensitivity` and canonical venue keys unchanged (Savant's "UNIQLO
  Field at Dodger Stadium" maps to "Dodger Stadium" per `team_to_venue.csv`).
  28 of 30 venues moved on at least one applied value, several in the opposite
  direction from the unrecorded-provenance 2026-05-05 predecessor: Angel
  Stadium run 1.00 -> 0.94 and HR 1.08 -> 0.94, Chase 1.08 -> 0.98, Target
  1.08 -> 0.98, Dodger run 1.04 -> 0.94, Wrigley run 0.94 -> 1.04, Tropicana
  run 0.94 -> 1.02 and HR 0.97 -> 1.08. These values feed hitter F5 and the
  tail scanner's `park_total_div` signal directly. Deterministic data inputs,
  never a win-rate, ROI, or probability claim. Provenance rule added to the
  calibration ledger (3.1): every park factor refresh records source, window,
  and pull date.
- `project_audit.py` constants regenerated at the current version. The
  checked-in copy was stale at v2.23.0 (v2.23.0 filenames and module-version
  pins), so the session-start audit could not pass against the v2.24.0 tree.
  Constants brought to v2.24.1; audit logic unchanged; module version stays
  v2.0.
- Four pinned F5 regression assertions in `test_core.py`
  (`DeterministicF5Tests`) updated from the superseded Great American Ball
  Park run factor 1.06 to the refreshed 1.02. Test count unchanged at 100.
- No engine logic changes. MILP, certification gates, provenance chain, and
  strategy priors untouched.

## 0.2 v2.24.0 changes

- Per-pitcher Ceiling multipliers from a K-rate input, closing the "hitters
  only until a K-rate input exists" gap declared in v2.23.0. A FanGraphs
  season pitching CSV (per-slate data input, never checksummed) supplies the
  rate: `projection_builder.load_fangraphs_pitching` +
  `build_k_rate_ceiling_multipliers` rank K% (preferred) or K/9 as a
  percentile within the starter rows (GS >= 1), shrink on batters faced (real
  `TBF` column when present, else IP x 4.25) under the shared 50/100
  discipline, and clip 1.25-1.60 around the 1.42 neutral, the exact xISO
  formula. `xwoba_base_correction.build_dk_keyed_pitcher_ceiling_multipliers`
  re-keys onto DK ids through the same name normalizer, pitchers only,
  higher-TBF row wins a name collision and the collision is reported.
  `run_slate(fangraphs_pitching_csv=...)` fills the same per-row
  `Ceiling_Multiplier` column the xISO block uses for hitters, tags applied
  rows in Notes (`k_rate_ceiling: X.XX`), surfaces
  `projection_enrichment["pitcher_ceiling"]`, and raises the same zero-match
  wiring error on a real pool (>= 10 salary pitchers). Unmatched,
  non-starter, or sub-floor arms take the uniform neutral, so the column
  stays strictly additive. K rate is the pitcher right-tail shape signal (DK
  pitcher scoring is strikeout-heavy) and is deliberately distinct from the
  xwOBA-against contact signal the Base correction carries, which is exactly
  why re-ranking pitcher ceilings by xwOBA-against was rejected as
  rank-redundant in v2.23.0. Deterministic labeled prior, never a win-rate,
  ROI, or probability claim. `projection_builder.py` moves to
  `VERSION = "v1.4"`; `xwoba_base_correction.py` to `VERSION = "v1.2"`;
  `execution_pipeline.py` to `VERSION = "v1.7"`. Seven new wiring tests;
  the suite moves from 93 to 100.
- Pitcher F4 still stays 1.0: its gate is a team-level opposing-lineup input
  (team K% and wOBA vs LHP/RHP), not the pitcher's own K rate. Two FanGraphs
  team-batting-splits exports (vs LHP, vs RHP, with PA, K%, wOBA) trigger
  that build.

## 0.3 v2.23.0 changes

- FIXED a silent accuracy defect: `_assemble_projection_frame` applied the
  MLBAM-keyed xwOBA map (`build_xwoba_corrections`) to a frame keyed by
  DraftKings Player_ID. The two id universes never intersect, so every player
  fell back to the neutral 1.0 and any `run_slate` build that supplied the
  Savant CSVs ran on uncorrected Bases while the docs claimed a correction. The
  front door now joins through
  `xwoba_base_correction.build_dk_keyed_corrections` (the registered name
  crosswalk), surfaces the match report under `projection_enrichment["xwoba"]`,
  RAISES when a supplied correction matches zero players on a pool of at least
  `XWOBA_WIRING_MIN_POOL` (10), warns when the match rate is below 50%, and
  warns instead of silently skipping when CSVs are supplied without
  AvgPointsPerGame values. `execution_pipeline.py` moves to `VERSION = "v1.6"`;
  `_assemble_projection_frame` now returns `(projections, enrichment)`.
- Codified the value-sanity guard inside the engine. Previously a manual
  protocol step (the same silent-failure class as the xwOBA join), hitter Base
  is now capped at the slate's 90th-percentile hitter pts/$1k times 1.08
  BEFORE F1-F5 (`VALUE_GUARD_PCTL`, `VALUE_GUARD_HEADROOM`), opt-out per build
  via `run_slate(apply_value_sanity_guard=False)`. Pitchers are never capped.
  Clips are tagged in Notes and reported under
  `projection_enrichment["value_guard"]` with a checkpoint warning.
- Per-player Ceiling multipliers from expected ISO. Uniform 0.58/1.42
  multipliers made ceiling-maximization rank-identical to mean-maximization, so
  the GPP ceiling objective carried no player-specific variance information.
  `projection_builder.build_xiso_ceiling_multipliers` (xISO = est_slg - est_ba,
  league-percentile scaled, PA-shrunk, clipped to 1.25-1.60 around the 1.42
  neutral) plus `xwoba_base_correction.build_dk_keyed_ceiling_multipliers`
  (same name crosswalk as the xwOBA join) feed an optional per-row
  `Ceiling_Multiplier` column that `build_projections` consumes; rows without a
  value take the uniform neutral. Hitters only in v2.23.0 (the Savant pitching
  CSV carries no K-rate input, and re-ranking pitcher ceilings by
  xwOBA-against would be rank-redundant with the Base correction, the exact
  flaw this removes); superseded by the v2.24.0 K-rate input above.
  Floors stay uniform on purpose. `projection_builder.py` moves to
  `VERSION = "v1.3"`; `xwoba_base_correction.py` to `VERSION = "v1.1"`.
- Deterministic F4 (matchup quality) for hitters. F3/F4 were structurally
  absent (1.0 unless hand-typed). `projection_builder.compute_f4_factors`
  emits `{Player_ID: F4}` = (opposing-SP Savant xwOBA-against over the league
  mean, PA-shrunk, clipped 0.90-1.10) x (platoon hand prior, labeled priors in
  `F4_PLATOON_PRIOR`), combined clip 0.85-1.15. The SP-quality component
  applies team-wide even when batter hands are unavailable, so TBD lineups
  still receive it. `live_data_adapters.py` (`VERSION = "v1.1"`) gains
  `extract_opposing_probables` (DK team -> opposing probable with MLBAM id and
  hand; the MLBAM id joins the Savant table directly, no name match) and
  `extract_batter_hands` (DK id -> bat side for posted hitters). Consumed via
  `run_slate(f4_by_player_id=...)`, applied only to rows lacking an explicit
  F4 so a hand-supplied factor always wins; applied rows are tagged in Notes
  and surfaced under `projection_enrichment["f4"]`. Pitcher F4 stays 1.0 in
  this version. F3 (skill) remains 1.0-default; the xwOBA Base correction is
  the skill signal for now.
- `run_slate` surfaces `projection_enrichment` (xwoba, ceiling, value_guard,
  f4, warnings) in both the checkpoint payload and the approved result, with
  enrichment warnings appended to the checkpoint warnings. The
  `projections_override` path carries a note that assembly enrichments do not
  apply to a prebuilt frame. All enrichments are deterministic labeled priors
  or review inputs, never ROI, win-rate, or probability claims.
- Seven wiring tests (`ProjectionEnrichmentWiringTests`) drive synthetic salary
  and Savant fixtures through the real joins and assert non-neutral values
  reach the frame, including the zero-match wiring error. This class exists
  because 86 unit tests passed while the front-door correction was a no-op:
  unit-tested parts, untested join. The suite moves from 86 to 93. Active file
  count stays 24 of 26; both open slots remain reserved for the ownership
  model.

## 0.4 v2.22.0 changes

- Added `platoon_order_adapter.py` (module `VERSION = "v1.0"`), a tracked engine
  module that turns the FanGraphs RosterResource "Platoon Lineups" JSON into two
  opt-in, upstream capabilities. Both run before `run_slate` and neither touches
  the certified solve. The FanGraphs file is a per-slate data input, the same
  status as the two Savant CSVs, not a checksummed engine file.
  - `mispricing_screen(...)` is a deterministic review proxy. For each hitter it
    compares tonight's projected batting slot (the handedness-appropriate view)
    against that player's own RHP/LHP-frequency-weighted typical slot from the
    same file, and reports the F2-implied projection lift that the slot move
    represents. It routes attention to bats whose salary was likely set near a
    lower typical slot but who project higher tonight. It is never an ROI, edge,
    win-rate, or probability claim and changes no projection by itself. An
    external typical-slot baseline (for example the output of
    `build_typical_order_from_statcast.py`) can override the within-file blend per
    player.
  - `build_projected_order(...)` is the TBD-lineup fallback. It emits a
    `{Player_ID: slot}` map for the requested teams from the handedness view,
    crosswalked to DraftKings ids through the authoritative salary file using the
    same canonical name normalizer as the xwOBA join. It intentionally never emits
    `confirmed_teams`: a projected order must not trigger the confirmed-starter
    exclusion, so unconfirmed teams keep projected lineups. A real posted lineup
    later supersedes it through `refresh_confirmed_lineups`.
- Wired the projected order into the initial build path. `run_slate` gains
  `platoon_order_by_player_id`; `_assemble_projection_frame` applies it as
  `Batting_Order` and `F2 = batting_order_factor(slot)` for any row that lacks an
  order, BEFORE `build_projections`, so the slot flows into Base_Projection,
  Floor, and Ceiling. A row that already carries a Batting_Order is left
  untouched, so a confirmed or explicit order always wins. The applied set is
  surfaced under `projected_order` in both the checkpoint and the approved result.
  This closes the standing gap where F2 was derived from the batting order only in
  `refresh_confirmed_lineups`, never on the initial build.
  `execution_pipeline.py` moves to module `VERSION = "v1.5"`.
- The adapter is consumed two ways: pass the map to
  `run_slate(platoon_order_by_player_id=...)`, or enrich projection rows directly
  with `apply_projected_order_to_rows` when you want to inspect or override the
  enriched rows before building. Both share identical semantics.
- No change to the optimizer, the allocator, certification gates, provenance, the
  projection math, or the strategy priors. Active file count moves from 23 to 24
  against a cap of 26; the test suite moves from 76 to 86 with ten adapter tests
  in `PlatoonOrderAdapterTests`.

## 0.5 v2.21.0 changes

- Added a bank-diversification guardrail to `execution_pipeline.py` (module
  `VERSION = "v1.4"`). It closes the failure mode where a high-ceiling hitter who
  loses a roster slot to a comparable, more flexible hitter (for example a pure-3B
  bat behind a 1B/3B bat of equal or higher ceiling) is never generated into the
  candidate bank, so no exposure cap can place them. Three pieces, all
  deterministic review proxies and never win-rate, ROI, or probability claims:
  - `contested_slot_audit(projections, top_n=14)` runs inside
    `build_checkpoint_plan`. It flags top-ceiling single-position hitters whose
    only slot is covered by a multi-eligible hitter of equal or higher ceiling,
    returns the list under the checkpoint key `contested_slot_audit`, and appends
    a checkpoint warning. The operator sees the crowd-out risk at `approve=False`,
    before the bank is built.
  - `audit_bank_player_coverage(candidates, projections, top_n=14)` runs on every
    full `run_slate` build (the `approve=True` path) and is reported under the
    result key `bank_player_coverage`. It is path-agnostic: whether the bank came
    from `candidates_override` or the auto bank builder, any top-ceiling hitter
    appearing in zero candidates is reported with `passed=False`.
  - `generate_positional_variant_candidates(projections, focus_player_id,
    variant_specs, *, builder=None)` builds forced-lock candidates that cover a
    flagged slot. The builder defaults to `optimizer_v3.build_single_lineup` and is
    injectable for testing.
- The guardrail surfaces and never auto-applies an override, consistent with the
  engine's review-proxy doctrine. When a slot is flagged the operator builds
  variant coverage and re-runs; nothing is silently injected into the bank.
- No change to the optimizer, the allocator, certification gates, provenance,
  projections, or the strategy priors. Active file count stays 23; the test suite
  moves from 71 to 76 with five guardrail tests in
  `BankDiversificationGuardrailTests`.

## 0.6 v2.20.0 changes

- Added a single front door, `execution_pipeline.run_slate`. It takes raw slate
  inputs (salary CSV, entries template, per-player projection rows or a prebuilt
  frame, contest postures) and runs intake assembly, candidate-bank construction,
  entry-requirement derivation, strategy mapping, and the existing certified
  `execute_portfolio` path. With `approve=False` it returns a one-screen pre-build
  checkpoint and stops before the expensive solve, so a construction error is
  caught in seconds. The input contract is pinned in the untracked companion
  `MLB_Classic_Integration_Contract.md`.
- Added `STRATEGY_DEFAULTS`, posture-keyed construction priors (single_entry,
  wta_satellite, small_gpp, large_gpp, mme, cash). These are principled priors,
  not calibrated values, and are never to be read as win rate or ROI. They feed
  the checkpoint and the merged portfolio controls; override per slate.
- Added the assembly conformance step (DK slot-token coercion, explicit
  `Ownership_Tier` default of `Mid`, `Stack_Group` default to team) so the frame
  drops into the optimizer without per-slate hand fixing.
- Added a lighter `light_satellite` path that skips only the bank-coverage solve.
  The immutable run directory, the final-export re-read, and the blank-reserved-row
  block are always retained because they are the guardrail against a broken upload.
- Parked the dormant results/calibration/simulation apparatus to `parked/`:
  `contest_results_tracker.py`, `slate_sim.py`, `calibration_engine.py`,
  `post_slate_evaluator.py`, plus their data artifacts. These are below their
  signal thresholds at current slate volume (one accumulated slate) and are no
  longer audited engine files. Sections 15, 15a, and 16 describe parked
  components. Their 24 tests moved to `parked/test_parked.py`; the audited suite
  in `test_core.py` is now 52 tests including front-door coverage.
- File-cap headroom: active tracked files dropped to 22 against a cap of 26.
