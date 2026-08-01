# MLB Classic Integration Contract (companion, untracked)

Pins the data shapes the front door and allocator pass between each other. This
file is intentionally not in `ACTIVE_FILES` and is not checksummed; it is
reference for callers of `execution_pipeline.run_slate`.

## run_slate inputs

Required:
- `runs_root`: directory for the immutable run.
- `salary_csv`: DraftKings salary export. Authoritative for Player_ID, salary,
  team, game, opponent, and eligibility. Parsed by
  `slate_intake_manager.parse_dk_salary_csv`.
- `entries_csv`: DKEntries template export. Parsed ONLY by
  `dk_entries_manager.parse_dk_entry_rows` (positional; never DictReader),
  because of the embedded salary block.

Projection source (exactly one):
- `projection_rows`: iterable of per-player dicts (assembly path). Each row needs
  `Player_ID` and `Base` (or `AvgPointsPerGame`). Optional `F1..F5` (each missing
  factor defaults to 1.0 and is surfaced in `Notes`), `Position` override,
  `Batting_Order`, `Stack_Group`, `Ownership_Tier`. Salary is authoritative for
  Team/Salary/Game_ID/Opponent; Position is coerced to DK slot tokens.
- `projections_override`: a prebuilt optimizer frame (skips assembly). Must carry
  the CORE columns below.

Optional: `contest_postures`, `projection_mode` (default `emergency_proxy`),
`candidates_override`, `savant_batting_csv`, `savant_pitching_csv`,
`confirmed_hitter_ids`, `confirmed_teams`, `pitcher_roles`,
`excluded_player_ids`, `portfolio_controls_override`, `workflow_gates`,
`requested_n`, `archetypes_path`, `approve` (default False),
`light_satellite` (default False), `platoon_order_by_player_id`,
`f4_by_player_id`, `apply_value_sanity_guard` (default True), `source_metadata`,
`metadata`.

**`excluded_player_ids` caveat:** this parameter is forwarded to
`run_initial_build` (validation and export), but it does NOT propagate to
`build_candidate_lineup_bank`. The bank will build lineups around excluded
players if they have valid projections. To keep excluded players out of bank
candidates, drop them from `projection_rows` before calling `run_slate`.

**xwOBA correction (wired v2.23.0):** when `savant_batting_csv` or `savant_pitching_csv`
is supplied, the assembly path calls `xwoba_base_correction.build_dk_keyed_corrections`,
which does a name-crosswalk from Savant MLBAM IDs to DK Player IDs using the
salary file. Players with no name match fall back to a 1.0 neutral multiplier.
The match report is surfaced under `projection_enrichment["xwoba"]`. A supplied
correction matching ZERO players on a pool of at least 10 raises a ValueError
(wiring failure; omit the CSVs to build uncorrected on purpose); a match rate
below 50% adds a warning; CSVs supplied without `AvgPointsPerGame` values warn
instead of silently skipping. The batting CSV also drives per-player Ceiling
multipliers (`build_dk_keyed_ceiling_multipliers`, xISO-based, clipped
1.25-1.60 around the 1.42 neutral) delivered through a per-row
`Ceiling_Multiplier` column that `build_projections` consumes; unmatched rows
take the uniform neutral, hitters only.

**Value-sanity guard (v2.23.0, default on):** on the assembly path, hitter
`Base` is capped at the slate's 90th-percentile hitter pts/$1k x 1.08 BEFORE
F1-F5. Pitchers are never capped. Clips are Notes-tagged and reported under
`projection_enrichment["value_guard"]` plus a checkpoint warning. Opt out with
`apply_value_sanity_guard=False`; the opt-out is reported. Not applied on the
`projections_override` path.

**Deterministic F4 (v2.23.0):** `f4_by_player_id` is a `{Player_ID: F4}` map
built upstream by `projection_builder.compute_f4_factors` from
`live_data_adapters.extract_opposing_probables(lineups_json)` (DK team -> the
opposing probable SP; its MLBAM `id` joins the Savant pitching table directly),
the Savant pitching frame (`load_savant_expected_stats`), and optionally
`extract_batter_hands(lineups_json, salary_players)`. On the assembly path it
applies ONLY to rows that carry no explicit `F4`, so a hand-supplied factor
always wins; applied rows are Notes-tagged (`f4_matchup`) and surfaced under
`projection_enrichment["f4"]` (`requested`, `applied_count`,
`applied_player_ids`). Ignored on the `projections_override` path. Labeled
deterministic prior.

**Projected batting order (platoon fallback):** `platoon_order_by_player_id` is a
`{Player_ID: slot}` map built by `platoon_order_adapter.build_projected_order` from
the FanGraphs platoon-lineups file (a per-slate data input, not a tracked engine
file). On the assembly path it sets `Batting_Order` and
`F2 = batting_order_factor(slot)` for any row that lacks an order, before
projections are built, so the slot flows into Floor and Ceiling. Rows that already
carry an order are left untouched. It is a projected order only and never sets
`confirmed_teams`; it is ignored on the `projections_override` path. The applied set
is surfaced under `projected_order` (`requested`, `applied_count`,
`applied_player_ids`). The same enrichment is available at the row level via
`platoon_order_adapter.apply_projected_order_to_rows` before the call.

## CORE projection columns (optimizer-ready frame)

`Player_ID, Name, Team, Opponent, Position, Salary, Game_ID, Floor, Ceiling,
Excluded, Locked`. `Ownership_Tier` is optional; the optimizer defaults it to
`Mid`. `Ceiling < Floor` is a hard error.

## Candidate record contract (allocator input)

The allocator reads candidates through accessors, so either the hand-built shape
or the optimizer bank record works:
- id: `candidate_id` (or `lineup_id`).
- roster: `roster_slot_ids` (dict of DK slot to Player_ID, preferred for exact
  ten-slot placement) or `slot_assignments`, else `lineup_ids` / `roster_ids` /
  `player_ids`, else a `lineup` DataFrame with `Assigned_Slot`/`Assigned_Position`.
- pitchers: `sp_ids` (or `contest_fit.sp_ids`).
- stack: `primary_stack` (or `contest_fit.primary_stack`).
- score: `contest_fit_by_shape[shape]`, else `contest_fit.contest_fit_score`,
  else `objective`.

`run_slate` passes `build_candidate_lineup_bank(...)['candidate_lineups']`
directly and additionally pins `roster_slot_ids` from each record's `lineup`
`Assigned_Slot` column when present.

## entry_requirements (allocator input)

List of `{entry_id, contest_id, contest_name, contest_shape}`, one per reserved
Entry ID. `contest_shape` comes from the resolved posture.

## portfolio_controls keys

`max_player_exposure_pct, max_pitcher_exposure_pct,
max_primary_stack_exposure_pct, max_sp_pair_repetition, max_shared_players,
max_candidate_reuse`. Percentage caps convert to a per-player
count of `floor(pct * entry_count)`; on small banks tight caps can make the
joint MILP infeasible, so loosen and surface the relaxation. `_merged_controls`
takes the tightest cap across contests, then applies
`portfolio_controls_override`.

`reuse_penalty` is NOT on that list and has not been a joint control since R36
Finding 11. Supplying it is not fatal and changes no coefficient; the allocator
names it in `warnings` and ignores it. Reuse is governed by
`max_candidate_reuse` and cross-lineup overlap by `max_shared_players`, both
hard rows. The name survives only as a keyword parameter on the legacy
`assign_lineups_to_contests`, where it weights an EXCESS variable and is
correctly signed.

## DK roster slot order

`P1, P2, C, 1B, 2B, 3B, SS, OF1, OF2, OF3`. Position coercion: SP/RP -> P;
LF/CF/RF -> OF; C/1B/2B/3B/SS pass through.

## run_slate output

- `approve=False`: `{status: "plan_pending_approval", checkpoint_plan,
  projection_schema, entry_requirements, posture_by_contest, merged_controls,
  caller_asserted_gates, projected_order, projection_enrichment}`. No run
  directory is created.
- `approve=True`: the `execute_portfolio` result (`passed`, `workflow_valid`,
  `selection_certified`, `allocation_certified`, `output_path`, `run_id`,
  `diagnostics_path`, `bank_coverage`) plus `checkpoint_plan`, `posture_by_contest`,
  `merged_controls`, `candidate_bank`, `projected_order`, `projection_enrichment`.
- `projection_enrichment` (both paths, v2.23.0): `{xwoba, ceiling, value_guard,
  f4, warnings}`. `xwoba` carries the DK-keyed match report
  (`applied, considered, matched, unmatched, match_rate, non_neutral_applied,
  name collisions, unmatched_rows`); `ceiling` carries the xISO join
  (`matched, match_rate, differentiated_rows`); `value_guard` carries
  `applied, p90_pts_per_k, clipped_count, clipped`; `f4` carries
  `requested, applied_count, applied_player_ids`. Enrichment warnings are also
  appended to `checkpoint_plan["warnings"]` prefixed `projection_enrichment:`.
  On the `projections_override` path all four are None with a note that
  assembly enrichments do not apply to a prebuilt frame. Everything in it is a
  deterministic labeled prior or review input, never a win-rate, ROI, or
  probability claim.

## Post-slate archive (calibration ledger inputs)

The calibration ledger (`MLB_Classic_Calibration_Ledger.md`) is an untracked
companion, not in `ACTIVE_FILES` and not checksummed, on the same footing as this
file and the backlog. It is the project's persistent memory layer and is read first
at session start. Its calibration content is inert: it moves no projection until a
projected-ownership model emits a per-slate prediction to grade against archived
actuals and enough archetype-conditioned slates exist for a pattern to repeat.

Per-slate input is the DraftKings contest standings export, archived by hand. Its
schema is `Rank, EntryId, EntryName, TimeRemaining, Points, Lineup, , Player,
Roster Position, %Drafted, FPTS`. Read with `encoding="utf-8-sig"` because exports
may carry a BOM. The right-hand block (Player / Roster Position / %Drafted / FPTS)
is the actual ownership and actual scoring table. `EntryName (n/n)` is entries used
over max per user. `Points` of 0.0 is a real zeroed or late entry. The export OMITS
entry fee, payout structure, and the cash line; winning score is derivable from max
`Points`, the cash line is not. Capture the omitted fields from the contest page,
and join `%Drafted` to the slate salary file (by name and team, the crosswalk used
in `build_dk_keyed_corrections`) for salary and value. There is no parser module and
no tracked artifact for this; archiving is manual and the ledger is the store.
