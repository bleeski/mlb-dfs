# Postseason 2-game Classic: the team cap pins every arm, and TBD sides have no projected-order channel

Filed by BUILD, 2026-10-15, 1300_2g (ALCS G3 TB@CLE 13:00, NLCS G4 MIL@LAD 20:00 ET), 12 entries over 4 contests.
Delivered run `20261015T161906Z_3dee487a`, sha256 7f193d0066e5b012262dcdd7b0e520dce2a7b18dc8a626c1500a2db4056e0416,
certified, preflight exit 0. Ben asked what playoff baseball changes in the engine; these are the parts the build
could not handle with flags.

## 1. On a 2-game slate the team-footprint cap fixes arm exposure, whatever the arm caps say

With `--max-opposing-hitters-per-sp 0` each SP pair leaves exactly two teams to hit from (Williams+Glasnow ->
CLE+LAD; Jax+May -> TB+MIL; and so on). Every lineup counts toward two teams, so 12 lineups make 24 team slots,
and `max_team_exposure_pct` 0.55 (6 of 12) forces each of the four teams to exactly 6. That forced each arm to
exactly 6 of 12, three Jax+May lineups at a 15.8 pitcher Base against 40.7 for Williams+Glasnow, and the brief
reported the pitcher cap 0.5 as a `derived_floor`, which reads as a choice.

- `max_pitcher_exposure_pct` 0.75 + `max_player_exposure_pct` 0.75 + `max_sp_pair_repetition` 6 changed nothing
  (same sha 2a9b2c04 twice). Only `max_team_exposure_pct` 0.75 moved it: Glasnow 8, Williams 7, Williams+Glasnow
  5, the review-proxy ceiling mean 126.9 -> 134.8 (Ben approved the outcome in-session).
- Ask: a feasibility line naming the arm exposure the team cap implies under the opposing-hitter wall, or a team cap
  that scales with the slate's team count. The wall plus a team cap on 4 teams is an arithmetic lock, not a posture.

## 2. `chalk_fails` sleeve is starved on 2 games

R405's cluster held 12 of 36 hitters (a third of the slate), the sleeve built 3 candidates, and it seated a
$43,500 Jax+May lineup ($6,500 unspent) in both the Micro Booster and the Satellite, the worst proxy in each. R406
already drops `environment` on 2 games for the same reason. Ask: drop or shrink `chalk_fails` when the cluster is
that large a share of the pool. Turning all sleeves off was worse on Ben's objective (Williams 9, Glasnow 5,
May+Williams 4, proxy mean 133.0), so the sleeve as a whole is not the problem.

## 3. No channel for an operator PROJECTED order on a TBD side

RotoWire's overlay projected Josue De Paula for LAD (0 starts in NLCS G1-G3, one pinch-hit) and MIL's vs-LHP nine
(Ortiz, Lara, Vaughn) against RHP Glasnow. The first certified build carried De Paula in 5 of 12 lineups. The
boxscores give the postseason nines by opposing hand (MIL vs RHP: Chourio, Turang, Contreras, Bauers, Yelich,
Mitchell, Pratt, Frelick, Hamilton; LAD G1/G2 vs RHP: Betts, Freeman, Smith, Ohtani, T. Hernandez, Muncy, Pages,
Tucker, Kiké/Edman). The only operator door is `lineups_from_paste.py`, which marks the side CONFIRMED. This build
used it and the record says `operator_paste` for MIL and LAD, which overstates them: they are projections.
Ask: `build_slate.py --platoon-json` (`stage_slate.py` already has the flag) so a boxscore-derived postseason
projection reaches the TBD path as a projection.

## 4. Postseason starter workload (judgment, unmeasured)

The ten LCS starts through 2026-10-14 averaged 4.8 IP (2.2 to 6.0) against R470's 5.5 reference; today's Jax is a
named starter on a short leash (stale K line 3.5, no start past 5 IP since July per SI). Season APPG prices every
starter at a regular-season workload. `:ip=N` exists per declared arm; a slate-level postseason default does not.
Measure on the archived postseason slates before building anything.

## 5. Smaller

- There is no pitcher-only form of the person cap: `max_player_exposure_pct` binds arms too, so lifting arms lifts
  every hitter.
- The Solo Shot drew Jax+Glasnow (TB5-LAD3) while Williams+Glasnow is the projection apex. Second occurrence of the
  single-entry shape question in `2026-10-14_BUILD_single-entry-draws-leverage-template.md`, here on Classic.
