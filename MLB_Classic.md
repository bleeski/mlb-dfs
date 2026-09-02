# MLB Classic Execution Project — v2.26.0

Compiled: 2026-07-08  
Optimizer source of truth: `optimizer_v3.py` v3.18  
Supported solver: `scipy.optimize.milp` only  
Release posture: workflow reliability release addressing the structural causes of the missed-lock incidents that persisted regardless of engine version. Three changes: (1) `live_data_adapters.build_slate_pool` becomes THE required intake step, restricting every build to the players who can actually take the field (confirmed-lineup hitters, platoon-projected hitters for TBD teams, probable and declared starters); every other salary row is dropped before the engine sees it, ending both the full-CSV projection waste and the recurring non-starter pitcher-role confusion. (2) `slate_intake_manager.slate_clock` detects the first game lock from the salary file or lineups feed and computes the T-5 delivery deadline, surfaced on every `run_slate` checkpoint and result with warnings when the window is tight; the standing delivery rule is that the certified file is presented no later than T-5, with refinements handled through late swap. (3) Percentage exposure caps join the feasibility floors, retiring the last recurring manual relaxation. The default per-slate workflow is cut to two calls, `build_slate_pool` then `run_slate`; the tail scanner, contested-slot audit, platoon mispricing screen, and fill-depth narration move to opt-in. MILP hard constraints, certification gates, and the provenance chain are untouched; all additions are deterministic review inputs, never ROI, win-rate, or probability claims.

## 0. v2.26.0 changes

- Pool contract. `live_data_adapters.build_slate_pool(salary_csv, lineups_feed,
  platoon_json, declared_pitchers)` is the required front door for every build.
  Hitters are the nine in each confirmed lineup (Batting_Order plus a stamped
  F2 from the posted slot) plus the platoon-projected nine for each TBD team
  (slots flow through `platoon_order_by_player_id`, never Batting_Order, so a
  posted lineup still supersedes); pitchers are the feed's probables plus
  explicit declarations. Every other salary row is absent, not Excluded. A TBD
  team the platoon data cannot fill falls back to its top-9 salary hitters by
  AvgPointsPerGame with a loud warning (or is excluded via
  `tbd_fallback='exclude'`); postponed games are excluded; a team with no
  probable and no declared arm is a surfaced blocker. Output bundles
  `run_slate_kwargs` ready to splat, the F4 building blocks
  (`team_by_player_id`, `opposing_probables`, `batter_hands`), the slate clock,
  and a `pool_report` with per-team status, warnings, and blockers.
- Slate clock and the T-5 delivery rule. `slate_intake_manager.slate_clock`
  parses game datetimes from the salary Game Info column (or accepts the feed's
  `lock_time_by_game_id`), names the first game to lock, and computes the
  delivery deadline at lock minus 5 minutes. `run_slate` surfaces it as
  `checkpoint["slate_clock"]` and on the result, warning when the deadline is
  inside 15 minutes or already past. The delivery rule: the best certified file
  is presented no later than T-5; refinements go through `run_late_swap`.
  Deterministic bookkeeping, never a guarantee the session meets it.
- Percentage exposure caps join the feasibility floors. `_slate_feasibility`
  derives the minimum feasible `max_pitcher_exposure_pct`
  (`ceil(2*entries / viable_SPs)` appearances for some arm),
  `max_primary_stack_exposure_pct` (`ceil(entries / stackable_teams)` for some
  team), and `max_player_exposure_pct` (the max of both demands), and
  `run_slate` floors the tightest-merged caps to those values before the
  explicit override, which still wins. `_feasibility_report` gains matching
  capacity checks naming the exact required cap. This retires ledger 3.3's
  manual pct-cap relaxation.
- Floors only relax, never restrict. `_merged_controls_for_build` now applies
  feasibility floors only to keys already present after the posture merge; the
  v1.8 behavior could insert an absent repetition key at its floor value,
  adding a cap where no posture set one.
- Workflow cuts. The tail scanner, contested-slot audit, and platoon mispricing
  screen are opt-in only; the fill-depth plan stays computed on the checkpoint
  but leaves the required build report; the three-assumption kill list is
  replaced by a single Blockers line; the session-start ledger read is replaced
  by the ledger's 15-line Quick Card. The default loop is
  `build_slate_pool` -> review one checkpoint -> `run_slate(approve=True)` ->
  present, with the file in hand at T-5.
- Module versions: slate_intake_manager v1.7, live_data_adapters v1.2,
  execution_pipeline v1.9, project_audit v2.2. Twelve new tests (107 -> 119).

Earlier version-change sections (v2.25.0 back to v2.20.0) live in docs/legacy/MLB_Classic_version_history.md.

## 1. Objective

Create legal DraftKings MLB Classic lineups that match the contest shape and, for GPP/WTA portfolios, provide multiple coherent first-place paths. Deterministic contest-fit, ownership, exposure, tail, stack, allocation, and redundancy diagnostics are review proxies only. Never label them ROI, profitability, win rate, cash rate, or Perfect% without a real simulation. The calibration loop in §15 exists to measure whether those proxies deserve continued use.

## 2. Non-negotiable rules

- DraftKings salary CSV is authoritative for Player_ID, salary, team, game, and eligibility.
- Salary cap: $50,000. Roster slots: `P1,P2,C,1B,2B,3B,SS,OF1,OF2,OF3`.
- No duplicate player within a lineup.
- **No hitter against a rostered opposing pitcher is a GUIDELINE, not a rule in this section's sense, and the session may override it on judgment (R288, 2026-09-01).** It is a DFS convention about negative correlation. DraftKings does not prohibit the construction: across 22 archived slate dates, 19,072 of 102,201 fully-resolvable Classic entries in `data/archive/` carry one, and contest-standings-192464310 (2026-07-19, 1,486 entries) has ranks 1, 2 AND 3 all holding a NYY bat beside a rostered LAD arm starting against NYY — DK accepted, scored and paid those. Frequency is slate-size dependent (62.5% of entries on that 2-game slate, 3.2% on the 12-game 2026-08-11 slate), so on a small slate the convention forbids most of the legal space. The control is `optimizer_v3` `max_opposing_hitters_per_sp` / `build_slate.py --max-opposing-hitters-per-sp`, default 0 and PER SP (a two-arm Classic lineup's per-lineup worst case is twice the value); every Classic brief records `anti_correlation` including the default, and `preflight_upload.py` warns rather than failing. CLAUDE.md Autonomy delegates the decision; record the value and the reason in the brief.
  This line read "unless the user explicitly overrides" from the start and no override existed: `optimizer_v3` emitted the constraint unconditionally with no parameter, and `preflight_upload` returned exit 2 on it. The strategy authority said overridable and both implementations said never — three readers, two disagreeing with the authority, which is why the wall survived unexamined into a hand builder on 1940_9g and cost the highest-implied-total team on the slate 2 roster slots out of 370.
- Confirmed-out hitters are excluded. Once a team is confirmed, only listed starters from that team are eligible; unconfirmed teams are not restricted by other teams' confirmations.
- Missing salary-row players are unrosterable; never substitute by name.
- Locked players remain in their exact DraftKings slots.
- Teams whose games have locked cannot be introduced into newly rebuilt slots.
- Same-contest duplicate rosters are forbidden. Cross-contest reuse is allowed when strategically justified.
- Greedy/manual fallback is diagnostic-only and must remain `DO_NOT_UPLOAD`.
- Upload-ready output requires `workflow_valid=True`, `selection_certified=True`, and `allocation_certified=True` when joint allocation is used.
- Late swap mutates only explicitly authorized Entry IDs (§11).
- A player absent from the late-swap status map is never treated as unlocked (§11).

## 3. Phase 0: choose the correct operating mode

### Reserved-entry execution mode

Use when DKEntries already contains reserved contests and the user is not deciding where to enter.

1. Parse exact Entry IDs, Contest IDs, names, fees, blank/completed rows, and embedded player-pool IDs.
2. Preserve the source template and every populated roster unless the user explicitly authorizes unlocked late-swap slots.
3. Accept the user's declared contest posture. Do not request ticket value, rake, paid spots, or budget data that cannot change reserved entries.
4. Fill or reoptimize only the authorized Entry IDs.

### Contest-selection mode

Use only when the user is choosing contests or allocating a budget. Then field size, payout shape, ticket count/value, rake, and entry limits may be decision-critical.

## 4. Slate intake

### Hitters

- Explicit confirmed lineups override projections.
- TBD teams may use projected starters until confirmation.
- At refresh, remove players omitted from a newly confirmed lineup. Confirmation is per team: pass `confirmed_teams` so a confirmed team restricts only its own hitters.
- Missing salary-row starters are unrosterable and must be surfaced.

### Pitchers

1. User-declared or verified starters are eligible.
2. Other salary-row pitchers are excluded by default.
3. Research exceptions only for two plausible starters, opener/bulk reports, a high-salary unverified pitcher, or a declared starter missing from the salary file.
4. Roles are `verified_starter`, `declared_probable_sp`, `viable_bulk_or_alt_sp`, `leverage_only_uncertain_role`, or `explicit_exclude`.
5. Never silently omit a viable audited SP.

## 5. Material weather, minimal odds, and deterministic F5

Weather is a decision system, not a full meteorological model.

For each game determine:

1. Roof open/closed when retractable.
2. Meaningful wind direction at wind-sensitive parks: `out`, `in`, `cross`, `variable`, or `not_material`.
3. Delay risk: `none`, `low`, `medium`, or `high`.
4. Postponement risk: `none`, `low`, `medium`, or `high`.

Temperature and humidity are optional. Dome or verified closed roof skips outdoor weather. A retractable roof requires fresh source, status, and timestamp; absence from an outdoor-weather packet is not roof verification.

Wind adjustments activate only at the venue threshold from `team_to_venue.csv`:

- High sensitivity: default 8 mph.
- Moderate sensitivity: default 13 mph.
- Low/none/closed roof: no wind adjustment.

Delay affects pitchers only:

- Medium delay: SP factor 0.95.
- High delay: SP factor 0.85 plus warning.
- Medium postponement risk: warning and a 25% game exposure cap, enforced through the allocator game-cap control (§8).
- High postponement risk: exclude/block the game.

One current game total, source, and timestamp are required per game. Team totals and moneylines are optional.

### Deterministic F5

F5 is computed, not eyeballed. `slate_intake_manager.compute_f5_factor(...)` derives hitter and pitcher F5 from `f5_park_factors.csv` and `f5_weather_adjustments.csv`:

- Hitter F5 = park `Run_Factor_Applied` × wind hitter factor.
- Pitcher F5 = wind pitcher factor × delay pitcher factor (park factor for pitchers is intentionally 1.0; park run environment is carried on the hitter side only).
- Wind applies only when direction is `out` or `in`, speed meets the venue threshold, and the roof is not closed. Speed bands: 8–12, 13–17, 18+.
- The same call returns `hr_environment`, the postponement-driven `game_exposure_cap`, and `exclude_game`.

Manual F5 overrides remain allowed but must be surfaced as overrides with a reason. Both F5 CSVs are audited schema files and are now consumed by production code. Park raw factors are sourced from Baseball Savant Statcast park factors (`Run_Factor_Raw` = R / 100, `HR_Factor_Raw` = HR / 100; applied = clip(raw, 0.94, 1.08)); every refresh must record source, window, and pull date (last refresh 2026-07-07, v2.24.1).

## 6. Projection contract

Core required fields:

`Player_ID, Name, Team, Opponent, Position, Salary, Game_ID, Floor, Ceiling, Excluded, Locked`

`Ceiling >= Floor` is enforced: a Ceiling below Floor is a hard error listing the offending Player_IDs. The builder never silently repairs it.

All projection construction and confirmed-lineup refreshes use `projection_builder.py` and exactly:

`Base × F1 × F2 × F3 × F4 × F5`

- F1: market scoring environment.
- F2: opportunity and confirmed batting order.
- F3: player skill.
- F4: matchup quality.
- F5: park plus material environment (§5).

Supported modes:

- `provider_projection`
- `emergency_proxy`

Emergency projections are usable under time pressure only when clearly labeled. Every player row must retain Base, F1-F5, source, timestamp, and projection-quality audit fields.

### Baseline correction (xwOBA)

The Base is the proxy starting point, normally DraftKings AvgPointsPerGame. That number is a raw results average: it carries the park a player's points were earned in (a Coors hitter is inflated), the pitchers he happened to face, and small-sample noise. An optional, context-neutral correction strips the park and contact-luck part of that using Baseball Savant Expected Statistics, applied as a multiplier on the Base **before** F1-F5.

- Batter factor is `est_woba / woba`; a hitter who out-hit his contact quality is pulled down, one who under-hit it is pulled up.
- Pitcher factor is `woba / est_woba`, inverted because a low wOBA-against is good for a pitcher; an unlucky arm is pulled up.
- Each factor is shrunk toward 1.0 below `XWOBA_PA_FULL` (100 PA) and ignored below `XWOBA_PA_MIN` (50 PA), then clipped to the role band (batter 0.85-1.15, pitcher 0.90-1.10, tighter because batted-ball contact is a smaller share of a pitcher's DK score). A player with no expected-stats row falls back to the uncorrected AvgPointsPerGame.

Because the factor is applied before F1 and F5, it does not double count the implied total (F1) or tonight's park (F5): it corrects the historical park contamination in the base level, while F1/F5 add tonight's environment. The correction is a deterministic review input, never a profitability or win-rate claim. The two Savant CSVs (batter and pitcher Expected Statistics) are per-slate data inputs, not checksummed engine files.

Savant keys every row on the MLBAM `player_id`, while the slate and the entire pipeline key on DraftKings draftable ids, so the two id systems never join directly. `build_xwoba_corrections` returns a map keyed by MLBAM id; the registered helper `xwoba_base_correction.build_dk_keyed_corrections(salary_csv, batting_csv, pitching_csv)` re-keys it onto DraftKings ids by name match (batter file for hitters, pitcher file for pitchers, role-correct ratio already baked in), keeping the higher-PA row on a name collision and reporting it. The build sequence is:

`xwoba_base_correction.build_dk_keyed_corrections(salary_csv, batting_csv, pitching_csv)` → `projection_builder.apply_xwoba_correction(rows, corrections)` to set the corrected Base → `build_projections`.

As of v2.23.0 this sequence is wired into the front door: `run_slate` with `savant_batting_csv`/`savant_pitching_csv` (and, from v2.24.0, `fangraphs_pitching_csv` for pitcher ceilings) runs it inside `_assemble_projection_frame`, never through the raw MLBAM-keyed map (the pre-v1.6 silent no-op), and surfaces the match report under `projection_enrichment["xwoba"]`. A supplied correction that matches ZERO players on a pool of at least `XWOBA_WIRING_MIN_POOL` (10) raises as a wiring error, because the caller can always omit the CSVs to build uncorrected on purpose; a match rate below 50% warns; supplying CSVs without AvgPointsPerGame values warns instead of silently skipping. An unmatched player falls back to the uncorrected AvgPointsPerGame, and a player below `XWOBA_PA_MIN` is passed through neutral (1.0) even when matched, so the correction never invents signal for small-sample call-ups. DraftKings ids are reassigned every slate, so the join runs per slate against that night's salary file, exactly like loading the Savant CSVs. Live fetching is an external refresh step, kept out of the audited engine so projection construction stays deterministic.

`refresh_confirmed_lineups(...)` accepts `confirmed_teams` and applies starter restrictions per team. Passing a global starter set without `confirmed_teams` over-excludes TBD-team hitters and is deprecated.

Salary suppression is a bounded tiebreaker only. Only confirmed `role_elevation`—a promotion of at least two batting-order spots versus expected/recent median—may activate it.

### Value-sanity guard (v2.23.0)

Hitter Base is capped at the slate's 90th-percentile hitter points-per-$1k times 1.08 (`VALUE_GUARD_PCTL`, `VALUE_GUARD_HEADROOM`) BEFORE F1-F5, inside `_assemble_projection_frame`, after the xwOBA correction. Without it, a min-salary small-sample bat with an inflated AvgPointsPerGame dominates every candidate lineup. It was previously a manual protocol step, which is the same silent-failure class as the pre-v1.6 xwOBA join; it is now code. Pitchers are never capped. Clips are tagged in Notes (`value_guard: Base capped X->Y`), reported under `projection_enrichment["value_guard"]`, and surfaced as a checkpoint warning. Opt out per build with `run_slate(apply_value_sanity_guard=False)`; the opt-out is itself reported.

### Per-player Ceiling multipliers from expected ISO (v2.23.0)

Uniform Floor/Ceiling multipliers (0.58/1.42) made ceiling-maximization rank-identical to mean-maximization, so the GPP ceiling objective carried no player-specific variance information. When the batting CSV is supplied, `build_dk_keyed_ceiling_multipliers` re-keys `build_xiso_ceiling_multipliers` output (xISO = est_slg - est_ba, ranked as a percentile within the qualified rows of the Savant table so the league, not the slate, defines power; multiplier = 1.42 + (percentile - 0.5) x 0.30; PA-shrunk below 100 and neutral below 50 like the xwOBA discipline; clipped 1.25-1.60) onto DK ids through the same name crosswalk as the xwOBA join. The values land in a per-row `Ceiling_Multiplier` column that `build_projections` consumes; rows without a value take the uniform neutral, so the column is strictly additive, and the `Ceiling >= Floor` hard error still governs. This block is hitters only; pitcher ceilings come from the K-rate input below (v2.24.0), not from re-ranking xwOBA-against, which would be rank-redundant with the Base correction. Floors stay uniform on purpose; the GPP objective consumes Ceiling. `refresh_confirmed_lineups` preserves per-player ratios automatically because it rescales from the row's own Ceiling/Base_Projection ratio. Deterministic prior, never a probability claim.

### Per-pitcher Ceiling multipliers from a K-rate input (v2.24.0)

The v2.23.0 block above left pitchers at the uniform 1.42 pending a K-rate input; a FanGraphs season pitching CSV supplies it. `projection_builder.load_fangraphs_pitching` validates the export (requires `Name` and at least one of `K%`, `K/9`; raises otherwise so a truncated export cannot silently neutralize the feature). `build_k_rate_ceiling_multipliers` ranks the rate (K% preferred, K/9 accepted; K/9 slightly flatters pitchers who allow more baserunners, which the percentile rank and the clip absorb) as a percentile within the starter rows (GS >= 1 when a GS column exists; reliever K rates run structurally higher and would depress every starter's percentile, so a GS == 0 arm takes the neutral), multiplier = 1.42 + (percentile - 0.5) x 0.30, shrunk on batters faced (real `TBF` column when present, else IP x `K_RATE_TBF_PER_IP` = 4.25) under the shared 50/100 discipline, clipped 1.25-1.60. `xwoba_base_correction.build_dk_keyed_pitcher_ceiling_multipliers` re-keys onto DraftKings ids through the same name normalizer as the xwOBA and xISO joins, pitchers only, higher-TBF row wins a name collision and the collision is reported. `run_slate(fangraphs_pitching_csv=...)` fills the same per-row `Ceiling_Multiplier` column, independent of the Savant CSVs; applied rows are Notes-tagged (`k_rate_ceiling: X.XX`) and reported under `projection_enrichment["pitcher_ceiling"]` (matched, unmatched, match_rate, differentiated_rows, rate_column, name_collisions). A supplied file matching zero pitchers on a pool of at least 10 raises as a wiring error; omit the file to build with uniform pitcher ceilings on purpose. The rationale is the WTA/GPP objective: at identical contact quality (identical Savant est_woba, so identical corrected Bases) a 13 K/9 arm and a 7 K/9 arm carry very different right tails because DK pitcher scoring is strikeout-heavy, and until this input the ceiling objective could not tell them apart at the two SP slots. The FanGraphs CSV is a per-slate data input on the same footing as the Savant CSVs, never checksummed. Deterministic labeled prior, never a win-rate, ROI, or probability claim.

### Deterministic F4: matchup quality (v2.23.0)

F4 was structurally absent: it defaulted to 1.0 unless hand-typed per row, leaving the two strongest matchup signals outside the projection. `projection_builder.compute_f4_factors` emits a `{Player_ID: F4}` map for hitters as (opposing-SP quality) x (platoon hand prior):

- Quality: the opposing probable's Savant xwOBA-against over the league mean of the supplied pitching table, PA-shrunk with the same 50/100 discipline, clipped 0.90-1.10. The mlb-lineups feed's `probable_pitcher.id` is an MLBAM id and joins the Savant table directly, no name match. The component applies team-wide even when batter hands are unavailable, so TBD lineups still receive it.
- Platoon: labeled priors in `F4_PLATOON_PRIOR` (LHB vs RHP 1.04, LHB vs LHP 0.94, RHB vs LHP 1.03, RHB vs RHP 0.99, switch 1.02 both ways), 1.0 when either hand is unknown. These are standard platoon-split priors, not calibrated values; override the table per slate if a better split exists.

Combined clip 0.85-1.15. Inputs come from `live_data_adapters.extract_opposing_probables` and `extract_batter_hands` (both v1.1), which reuse the status map's name+team salary match. Consumed via `run_slate(f4_by_player_id=...)`; applied only to rows lacking an explicit F4, so a hand-supplied factor always wins; applied rows are tagged in Notes and surfaced under `projection_enrichment["f4"]`. Applied before F1/F5 it does not double count the implied total or tonight's park. Pitcher F4 stays 1.0 in this version (the opposing-lineup aggregation waits for a team-level input: team K% and wOBA vs LHP/RHP; the v2.24.0 pitcher K-rate input drives ceilings, not F4), and F3 remains 1.0-default with the xwOBA Base correction carrying the skill signal. Deterministic labeled prior, never a win-rate, ROI, or probability claim.

### Projected batting order and platoon mispricing screen (v2.22.0)

`platoon_order_adapter.py` consumes the FanGraphs RosterResource "Platoon Lineups" JSON, a per-slate data input on the same footing as the Savant CSVs. It serves two opt-in purposes, both upstream of the solve and both deterministic review inputs, never ROI or win-rate claims.

- TBD-lineup fallback. When a team's DK lineup is not yet posted, `build_projected_order` selects the `vs_RHP` or `vs_LHP` order by the opposing starter's hand (from the mlb-lineups feed, usually populated even when the batting order is TBD) and emits a `{Player_ID: slot}` map crosswalked to DK ids via the salary file. Passed to `run_slate` as `platoon_order_by_player_id`, it sets `Batting_Order` and `F2 = batting_order_factor(slot)` on rows that lack an order, before `build_projections`. It never sets `confirmed_teams`: a projected order is not a confirmation and must not trigger the per-team starter restriction (Section 4). A posted lineup supersedes it through `refresh_confirmed_lineups`.
- **OPEN, awaiting Ben (filed here 2026-08-18 by R133(2)): a seeded ninth is
  selectable at the same weight as an observed posted starter.** When a side is
  PARTIAL — mlb.com posted fewer than nine, or posted nine and DK rosters fewer —
  the team routes through the TBD path and the empty seats are filled from this
  file, then from top AvgPointsPerGame. R60 stopped a fill from DISPLACING a
  posted starter. It did not change the WEIGHT of a fill that displaced nothing.
  Live case, 2026-08-12 slate 1840_3g: DET posted all nine, DK had no row for the
  ninth, the fill picked the highest-APPG DET bat available (a bench catcher at
  $4500 / 9.07 APPG against the posted catcher's $5600 / 8.63), and the optimizer
  took him in 6 of 18 certified entries. He was not playing.
  The question is whether a labelled prior standing in for an unknown should be
  selectable at parity with an observation, and the two candidate answers are a
  weight penalty on a seeded fill, or seeding no ninth at all for a partial side.
  A third answer is in the 2026-08-12 fragment and belongs to the same decision:
  mark such a side `confirmed` with its rosterable posted starters, which would
  end the seeding and stamp F2 from the real slots in one move.
  **Note precisely what R60 deferred, because the backlog has been imprecise
  about it: R60's deferral to this document covered F2-FROM-A-POSTED-SLOT only.
  The equal-weight question has never actually been asked of anyone.** R133 landed
  the three label-and-override halves (see CHANGELOG.md, 2026-08-18) and left this
  untouched on purpose: it changes what gets SELECTED, so it is Ben's.
- Batting-order mispricing screen. `mispricing_screen` compares tonight's slot against the player's RHP/LHP-frequency-weighted typical slot from the same file and reports the F2-implied lift. It formalizes the `role_elevation` signal noted just above: a promotion versus the player's own typical order, surfaced for review. It does not activate salary suppression or change any projection on its own; the operator reviews it and decides.

## 7. Candidate construction

Use a compact bank based on unique lineup demand, not raw reserved entries.

- Single lineup: about 8 candidates.
- Two to three: about 12.
- Four to nine: requested count plus roughly six.
- Larger reserved grids: largest same-contest block, reuse-cap minimum, and a small shape buffer.
- Default near-lock cap: 24 candidates; 40 only when justified.

Scenario families should represent baseball outcomes—different SP pairs, offenses, and game environments—not repeated arbitrary exclusions. Game totals, park factors, and wind from §5 are the preferred seeds for scenario families.

Candidate score may use:

1. Projection appropriate to contest shape.
2. Stack correlation and batting-order connectivity.
3. Credible duplication/ownership inputs.
4. Joint marginal portfolio diversity.
5. Precomputed simulated review metrics from §16 (mean, p50, p95, p99, and p_ge_threshold when a winning threshold is available), passed in as constants at candidate-construction time.

Unknown ownership or volatility is neutral.

### Bank coverage diagnostic

Bank starvation is silent: the joint solve stays feasible and certified while quality degrades. Every production build therefore records `optimizer_v3.bank_coverage_report(...)`: one unconstrained single-lineup solve per contest shape, compared against the best bank candidate for that shape. The report stores `gap_points` and `gap_pct` in run diagnostics. It never blocks and never certifies; a persistent gap above roughly 5% means widen the bank or revisit scenario families.

## 8. Entry-level joint portfolio MILP

`contest_allocator.select_and_assign_entries()` is the production assignment contract. It selects one candidate for every exact Entry ID in one SciPy MILP. Do not select a subset and allocate leftovers afterward.

Entry requirements may contain:

- `entry_id`
- `contest_id`
- `contest_shape`
- `locked_slot_assignments`
- `locked_player_ids`
- `allowed_candidate_ids`
- `excluded_player_ids`
- `excluded_new_teams`
- `player_team_by_id`

The joint solve enforces, as applicable:

- Exactly one candidate per Entry ID.
- Same-contest roster uniqueness.
- Candidate reuse cap, grouped by roster signature so identical rosters under different candidate IDs share one cap.
- Player exposure cap.
- Pitcher exposure cap.
- Primary-stack exposure cap.
- SP-pair repetition cap.
- Maximum shared players between distinct selected rosters.
- Game exposure cap via `max_game_exposure_pct_by_game` (requires `player_game_by_id`; a capped game with missing mapping fails the solve).
- Entry-specific exact-slot lock compatibility.
- No introduction of players from already locked teams.

**The production caps table is `execution_pipeline.STRATEGY_DEFAULTS`, keyed by
posture.** `run_slate` merges it; an explicit `portfolio_controls_override` wins
over it; `_slate_feasibility` floors any cap up to the slate minimum and reports
what it floored. The numbers below are this section's own row, and they are the
`wta_satellite` row as of the 2026-07-27 caps decision (ledger 3.11).

Satellite and WTA family, at least four entries:

- Player cap: 45%.
- Pitcher cap: 43%.
- Primary stack cap: 35%.
- SP pair: about 12% of entries, minimum two. `STRATEGY_DEFAULTS` pins a flat
  two, which is equal below sixteen entries and tighter above.
- Maximum shared players: five for portfolios of at least eight.
  `STRATEGY_DEFAULTS` pins a flat five and lets the feasibility floor lift it.

The GPP postures ladder deliberately and do not take the row above:
`small_gpp` 0.50 / 0.60 / 0.55 / 6, `large_gpp` 0.40 / 0.55 / 0.50 / 6, `mme`
0.35 / 0.50 / 0.45 / 6 (player / pitcher / stack / shared). A wider field gets
wider exposure and more decorrelation, which one flat row cannot express. Read
the divergence between those numbers and the row above as the ladder, not as
drift.

Any relaxed cap must be surfaced. Hard all-pairs SP coverage remains explicit opt-in only. The medium-postponement 25% cap from §5 is applied through the game exposure control, not as an advisory note.

## 9. Immutable run provenance

Every production execution runs through `execution_pipeline.py` and receives a unique Run ID:

```text
runs/<UTC_TIMESTAMP>_<RANDOM_SUFFIX>/
    inputs/
    candidate/
    final/
    manifest.json
```

Rules:

- Date-only production filenames are forbidden.
- Inputs are copied and hashed into the run.
- Candidate and final artifacts are registered with SHA-256.
- A late-swap run references its promoted parent Run ID and records lineage metadata: `parent_export_sha256`, `current_entries_sha256`, and `current_matches_parent_export`.
- A parent run is loaded only through `load_latest_valid_parent_run(...)`, which re-verifies the full run bundle (manifest, artifact hashes, pointer). A tampered or incomplete parent blocks the late swap.
- Promoted runs are immutable.
- `latest_valid_run.json` is only an atomic pointer to a promoted run.
- Repeated executions at the same timestamp remain separate and cannot overwrite one another.
- Run status is one of `building`, `blocked`, `diagnostic`, `promoted`. A failed gate or failed allocation sets `blocked`; nothing remains `building` after the pipeline returns.

## 10. Export authority and reconciliation

The exact exported DKEntries file is the source of truth for diagnostics and certification. In-memory allocator output cannot certify an export.

### Pre-export gates

Callers may provide only:

1. Salary gate.
2. Entry-grid gate.
3. Confirmed-lineup/status gate.
4. Pitcher audit gate.
5. Material-weather/roof gate.
6. Minimal-odds gate.
7. Projection schema gate.
8. Optimizer gate.
9. Selection certification.
10. Allocation method/certification when applicable.

Callers may not assert `workflow_valid`, `dk_export_gate_passed`, or any post-export gate.

### Post-export gates

After writing the candidate, the project re-reads that exact file and derives:

1. Template preservation.
2. Exact Entry ID and ordered ten-slot reconciliation.
3. Roster legality.
4. Portfolio-cap compliance, including game exposure caps when supplied.
5. Locked-slot immutability.
6. Export/diagnostic hash binding.

Blank reserved entries block promotion. Export writing refuses a pre-existing output path and never deletes a pre-existing file on failure.

Full export validation includes salary, position eligibility, exactly two pitchers, uniqueness, team/game limits, hitter-vs-SP, per-team confirmed starters, pitcher roles, excluded players, locked slots, same-contest duplicates, player/SP/stack/SP-pair caps, game exposure caps, and maximum overlap.

Diagnostics must contain:

- `diagnostic_source_file`
- `diagnostic_source_sha256`
- `assignment_sha256`
- Run ID and parent Run ID
- Solver method/status
- All pre/post gate results
- Any cap relaxation
- `bank_coverage` report when computed

A mismatch between allocator diagnostics, assignments, and the actual export means `DO_NOT_UPLOAD`.

## 11. Late swap

Two explicit modes exist. Both fail closed on lock-state ambiguity.

### Authorization

`run_late_swap(...)` requires `authorized_entry_ids`. Only those Entry IDs may be rewritten; every other reserved entry is preserved byte-for-byte and re-verified after export. An unknown authorized Entry ID is an error. An empty authorization set is an error. Fully locked authorized entries are skipped, surfaced, and preserved rather than forced through an exact-replica solve.

### Lock-state policy

Lock state derives from the status map and game times. `missing_status_policy` is one of:

- `error` (default): any rostered player absent from `status_by_player_id` aborts the swap.
- `treat_as_locked`: absent players are frozen in place.

There is no fail-open option. A player or team missing from `player_team_by_id` is likewise an error, never an unlocked assumption. Prefer building the status map from the live lineups feed (§14) so completeness is structural, not manual.

### `reoptimize`

Used when the user requests a late swap or rebuild.

1. Load the newest promoted run through verified parent loading (§9).
2. Determine lock state from actual game times.
3. Freeze exact locked slots.
4. Exclude already locked teams from new additions.
5. Refresh confirmed lineups through the shared projection builder with `confirmed_teams`.
6. Rebuild the candidate bank as needed.
7. Jointly optimize every authorized mutable Entry ID.
8. Re-read the exported file and validate locked immutability and unauthorized-entry preservation.
9. Promote only if every gate passes; otherwise the run is `blocked`.

An unchanged lineup after this full solve remains certified.

### `validate_only`

Used only to determine whether forced swaps exist. It creates a real run with mode `validate_only`, snapshotted inputs, a registered `final/late_swap_requirements.json`, and status `diagnostic`, so the check itself has provenance. It may report:

- `forced_swap_validation_passed=True`
- `late_swap_optimization_performed=False`

It must report:

- `selection_certified=False`
- `allocation_certified=False`

It no longer reports `forced_swap_validation_passed` (R176(c), 2026-08-30). That
key was written as a literal `True` on both modes for a validation that does not
exist in the tree, so it stated nothing and could be mistaken for evidence.

Manual comparison or catcher-only pivot review cannot inherit certification.

## 12. Canonical execution commands

Production code calls only:

- `execution_pipeline.run_slate(...)` — the front door. Assembles the projection
  frame, derives entry requirements and postures, emits the pre-build checkpoint
  (`approve=False`), and on `approve=True` builds the bank and runs the certified
  path below. Use `light_satellite=True` to skip only the bank-coverage solve.
- `execution_pipeline.run_initial_build(...)`
- `execution_pipeline.run_late_swap(...)`

Both paths execute:

```text
create immutable run
→ snapshot and hash inputs
→ materialize shared projections
→ entry-level joint SciPy MILP
→ write DO_NOT_UPLOAD candidate
→ re-read and validate candidate
→ copy exact candidate to final export
→ re-read final export
→ recompute diagnostics from final export
→ hash-bind export, assignments, and diagnostics
→ atomically promote or set blocked
```

No slate-specific script may write a production artifact directly.

## 13. Testing and audit

`python tools/audit.py --run-tests --terse` is the audit entry point. It pins the test count, so the suite must reproduce the pinned number on the PASS line.

Required regression coverage includes:

- Export/diagnostic mismatch.
- Stale diagnostic hash.
- Same-date run separation.
- Duplicate DraftKings roster headers.
- Exact Entry ID reconciliation.
- Exact locked-slot immutability.
- Validate-only certification block and diagnostic-run provenance.
- Unknown retractable-roof block.
- Post-export exposure mismatch.
- End-to-end initial build.
- End-to-end late swap with an authorized subset, including unauthorized-entry preservation.
- Missing-status fail-closed behavior for both policies.
- Tampered-parent block.
- Per-team confirmed refresh and validation.
- Deterministic F5 computation, including threshold and postponement behavior.
- Game exposure cap in the allocator and validator.
- Adapter parsing: status map construction, totals packet, implied probabilities, vig removal.
- Tail candidate scanner: all four signal paths, coverage-tier degradation, threshold overrides, and the park-only fallback.
- xwOBA baseline correction: batter and pitcher ratio direction, PA shrinkage, clip bands, sub-floor neutral fallback, BOM handling, and unmatched fallback.
- Contest-type classification from dk_contest_archetypes.csv by longest-pattern match.
- Curated archetype columns (R1c, 2026-07-27): `objective_class` is a cross-check
  against the row's own `payout_shape_default` and fails the load on a
  disagreement, never routing anything; `ticket_count` is the one satellite fact
  no title inference can recover, where 1 routes to the `wta_ticket_satellite`
  profile, more than 1 routes to the ticket-line blend, and blank keeps the
  multi-ticket default and stays a decision-critical gap at the checkpoint.
- Front-door run_slate: plan-only creates no run, approved build promotes, bad schema blocks, posture mapping.
- Projection-enrichment wiring (v2.23.0): the DK-keyed xwOBA correction demonstrably reaches the frame with the exact clipped values, a zero-match on a real pool raises the wiring error, the value guard caps the outlier hitter and never a pitcher and honors the opt-out, per-player xISO ceilings flow into Ceiling with unmatched rows at the uniform neutral, the F4 map applies only where no explicit F4 exists, compute_f4_factors quality-and-platoon math, and run_slate surfaces projection_enrichment.
- Pitcher K-rate ceiling wiring (v2.24.0): the FanGraphs loader rejects a rate-less export, the multiplier scales/shrinks/floors and leaves a GS-0 reliever neutral, K% outranks K/9 when both exist, the DK-keyed join maps pitchers only and resolves a name collision to the higher-TBF row with the collision reported, the multipliers demonstrably reach Ceiling with hitters untouched, the K-rate and xISO values coexist in one Ceiling_Multiplier column, a zero-match on a 10-pitcher pool raises the wiring error, and run_slate surfaces projection_enrichment["pitcher_ceiling"].

`checksums_sha256_v2_24_0.json` covers every active file except itself. Any missing file, version mismatch, checksum mismatch, compile failure, CSV schema failure, test-count mismatch, or unavailable `scipy.optimize.milp` fails the audit.

### Versioning convention

The authoritative project version is the manifest `Project_Version` field (`v2.24.0`). The authoritative per-module version is each module's `VERSION` constant. The module docstring framework stamp (`MLB Classic vX.Y.Z`) records the last release in which that file changed functionally; it is intentionally not bumped on releases that do not touch that module. This means the optimizer's `Framework integration: MLB Classic v2.16.0` stamp is correct historical metadata, not drift. Future code sweeps should not flag docstring stamps as version mismatches against the manifest.

## 14. Live data adapters

`live_data_adapters.py` converts external feeds into pipeline input contracts. It uses stdlib HTTP only, never logs API keys, and every fetcher has a matching parser that accepts pre-fetched JSON, so the module works in environments without network egress by pasting skill output.

### Source truth table

| Source | Use | Trust |
|---|---|---|
| MLB Stats API lineups feed (mlb-lineups skill shape) | Status map, confirmed teams, confirmed hitters, lock times | Production |
| the-odds-api.com v4 featured markets (h2h/totals/spreads) | Game totals packet for the odds gate | Production |
| the-odds-api.com v4 per-event player props | Optional HR/prop implied probabilities | Production, quota-expensive |
| odds-api.io | HR prop prices (existing arb skill shape) | Production |
| sportsdata.io free tier | Nothing | Blocked: free-tier data is intentionally scrambled and not decision-grade |

### Status map construction

`build_status_map_from_lineups_feed(feed, salary_players, ...)` returns `status_by_player_id` keyed by DraftKings Player_ID (name+team matched against the salary file), `confirmed_teams`, `confirmed_hitter_ids`, lock times from game start times, and explicit `unmatched`/`uncovered` lists. Feed player IDs are MLB IDs, never DraftKings IDs. Unmatched feed players or uncovered salary players are surfaced so the `error` lock policy fails closed instead of guessing.

### Odds packets and quota budgeting

`build_odds_packet_from_totals(...)` produces per-game `{total, source, fetched_at}` with consensus as the median across books. the-odds-api quota math: featured markets cost markets × regions per call for the whole slate (one totals pull ≈ 3 credits; a daily pull fits the free 500/month). Per-event prop markets cost markets × regions per event (≈ 13 credits per 12-game slate per market); budget before pulling. The adapters surface `x-requests-remaining` after every fetch.

### Implied probabilities

American or decimal prices convert to implied probabilities; paired over/under prices are normalized to remove vig. Prop-implied probabilities are review inputs for ownership/leverage judgment, not projection substitutes.

## 15. Results tracking and calibration
> Retired as of v2.20.0 and not present in this repo. The results tracker and post-slate evaluator were below their signal thresholds at one accumulated slate. Raw standings are still archived by hand.


`contest_results_tracker.py` closes the feedback loop. After each slate:

1. Download the DraftKings contest standings export.
2. `parse_dk_contest_standings(...)` reads ranks, points, lineups, and the embedded ownership table.
3. `record_slate_results(run_dir, ...)` joins standings to the promoted run's `assignments.csv` by Entry ID and appends one row per entry to `results_history.csv`: slate date, Run ID, contest, contest shape, contest-fit score, realized points, rank, field size, and duplication count. It also writes the field ownership table to the ownership CSV when the standings export embeds one.
4. `realized_duplication(...)` counts exact roster duplicates in the field.
5. `calibration_report(history)` reports, per contest shape, sample size, Spearman correlation between contest-fit score and realized points, and quartile means.

v1.1 adds slate memory on top of the per-entry loop:

- `archive_raw_standings(standings_path, archive_dir)` copies the raw DraftKings export unmodified and writes a sidecar JSON with its sha256 and a UTC timestamp. Raw capture is time-gated, so this runs every slate even when nothing else does.
- `extract_winner_archetype(parsed, salary_name_team_map=None, top_pct=0.01)` returns the winning score, the top-1% threshold score, the winner's primary and secondary hitter stack sizes, distinct game count (None without a team map), and chalk_index, the mean %Drafted of the winner's players from the embedded ownership table.
- `append_slate_archetype(archetype_csv, slate_profile, archetype_row)` records one row per contest per slate. The slate profile carries game_count, top_game_total, and mean_game_total from the odds packet.
- `winning_threshold(archetype_csv, game_count_range=None, total_range=None)` returns the matching-slate count and the median winning and median top-1% scores for slates whose profile matches tonight's.

For WTA contest shapes, when the archetype table holds at least 8 comparable slates for tonight's profile, candidate review prefers `p_ge_threshold` against that historical winning score; otherwise it uses p99. Both are simulated review metrics, never win-rate claims.

Calibration outputs are review diagnostics. They do not retune `CONTEST_SHAPE_PROFILE_WEIGHTS` automatically; weight changes are manual, justified by at least 30 slates of history per shape, and recorded in the release notes. If calibration shows no useful correlation for a shape, say so plainly and stop presenting that proxy as informative.

### Contest comparability

`winning_threshold` now also filters by `field_size_band` and `contest_type`, and the archetype table carries both columns. One slate's winning score moved 14 points across contests of different size, so a WTA threshold query restricts to the band and type it is building for. `field_size_band(field_size)` buckets field size with `FIELD_SIZE_BANDS`; `classify_contest_type(contest_name, archetypes)` infers the type from `dk_contest_archetypes.csv` by longest-pattern match. When either filter is set, archetype rows that predate the columns are excluded because their comparability cannot be confirmed.

## 15a. Propose-only recalibration
> Retired as of v2.20.0 and not present in this repo. `calibration_engine.py` was statistically inert at current slate volume. No weights, factors, or scores are auto-applied.


`calibration_engine.py` v1.0 is the decision layer that converts the results-loop artifacts into act-or-hold verdicts. It reads `results_history.csv` (weights), an accumulated player-level ownership evaluation (ownership), and accumulated per-venue residuals from `post_slate_evaluator` (venue). It applies a gate, proposes changes, and writes a `calibration_review.json` plus a proposals file. It writes nothing back to its inputs, to weights, factors, scores, or the CSVs.

The signal gate, all three required per surface:

1. Sample floor: 30 slates per shape for weights, 15 slates per ownership bucket, 50 player-games across 6 slates per venue.
2. Effect beyond noise: a slate-clustered bootstrap (resampling slates, not rows, so within-slate correlation is respected) whose 95% interval excludes the null. Null is zero bias for ownership, ratio 1.0 for venue, and the useful Spearman floor for weights.
3. Materiality: weights propose a re-fit when the Spearman interval tops out below `WEIGHTS_SPEARMAN_USEFUL_FLOOR` or the fit quartiles invert; ownership needs a mean bias of at least `OWNERSHIP_MATERIAL_BIAS_PCT` points; venue needs the shrunk applied-factor change to reach `VENUE_MATERIAL_FACTOR_DELTA`.

A change that clears the gate is shrunk toward the current value by `SHRINK_FRACTION` (0.5) rather than jumping to the realized estimate. Venue stays flag-the-raw: the engine reports the realized ratio and a shrunk suggestion, and the operator sets `Run_Factor_Applied` within the raw-to-applied cap, re-checksums `f5_park_factors.csv`, and records it. Anything significant but immaterial is logged as `watch`. The post-slate evaluator's `evaluate_venue_residuals` produces the per-venue measurement (summed projection and actual, mean residual, realized/projected ratio, roof type) and stamps the slate date; the park-only restriction is the engine's job.

The loop needs five inputs per slate to produce signal: the promoted run, the matching DraftKings salary CSV, the projection bundle with projected ownership, the standings export, and the odds packet for the slate profile. Arbitrary contests the operator did not build feed only the archetype/`winning_threshold` layer, and only with a correct slate profile and a comparable field-size band.

## 16. Correlated slate simulation
> Retired as of v2.20.0 and not present in this repo. Below the comparable-slate threshold `slate_sim.py` fell back to a static tail and added no signal, so it left the audited engine.


`slate_sim.py` v1.0 produces correlated outcome draws for candidate review. It is numpy-only, deterministic under a required integer seed, and it never touches the MILP, certification gates, or provenance chain. Its outputs feed §7 candidate scores as precomputed constants.

Model:

- Marginals: mu is the projection column; sigma = (Ceiling − Floor) / (2 × 1.2816), placing Floor and Ceiling at p10/p90 of the unclipped marginal, floored at a small positive epsilon. Hitters clip at 0; pitchers do not. Clipping distorts p10 for very low-Floor hitters; accepted and reported in `calibration_report()`.
- Correlation: Gaussian factor loadings. Hitters load on their team factor (0.45 for batting order 1–6, 0.35 for 7–9, 0.40 unknown), a top-of-order sub-factor (0.15 for slots 1–5), and a game factor (0.15). Pitchers load −0.40 on the opposing hitters' team factor and −0.15 on the game factor. Residual weight is sqrt(1 − Σb²).
- Market totals do not rescale factors. Totals already shape mu through F1/F5 in the projection pipeline; the sim adds correlated variance around those means. Rescaling here would double count.
- The top-of-order sub-factor is the v1 stand-in for pairwise batting-order adjacency. Exact pairwise adjacency is future work.

SimResult exposes `lineup_quantiles`, `prob_at_or_above`, `candidate_metrics(bank, threshold)` (mean, p50, p95, p99, p_ge_threshold), a `config_hash()` of the sorted sim config for run diagnostics, and `calibration_report()` comparing realized p10/p90 against Floor/Ceiling with tolerance flags. The same seed and inputs reproduce the matrix bit-for-bit.

Truthful labels: every sim output is a simulated review metric. Never present sim quantiles or exceedance probabilities as ROI, win rate, cash rate, or Perfect%. The sim sharpens whatever marginals it is given; bad projections in means confident garbage out, so the evaluator's projection-accuracy report remains the weekly first check.

## 17. Output contract

Surface:

- Slate Thesis.
- Contest Allocation.
- Portfolio concentrations.
- Material rationale.
- Blockers and relaxed caps.
- Gate results.
- Bank coverage gaps when material.
- Run ID and parent Run ID.
- Optimizer provenance.
- Links to the exact promoted artifacts.

Never label output upload-ready unless the promoted run manifest has `workflow_valid=True`, `selection_certified=True`, and `allocation_certified=True` when applicable.
