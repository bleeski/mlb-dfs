# Showdown tool gaps found during 2026-08-21 ATL@MIL build (BUILD role)

1. `tools/solver_probe.py` errors on a Showdown salary CSV: `_assemble_projection_frame`
   in `mlb_engine/pipeline/execution_pipeline.py` raises `ValueError: projection_rows is
   empty; supply per-player rows or projections_override` when given a melted CPT/UTIL
   Showdown salary file. The probe appears to assume Classic's pool shape. CLAUDE.md's
   session-start step 3 calls for `solver_probe.py` "before any build" with no Classic-only
   carve-out; either the tool should learn to read a Showdown salary CSV, or CLAUDE.md /
   the generate-lineups skill should say the probe is Classic-only. Skipped for this build
   after the error; the 20-player Showdown pool built in 2.9s, so infeasibility risk was
   low, but the skip was a judgment call under time pressure, not a passing check.

2. `tools/qa_portfolio.py` section 1 ("what the build applied") printed `controls relaxed:
   none` and `gates: {}` for a Showdown brief that actually shows
   `counted_relaxations.captain_relaxed_slots: 1` and `counted_relaxations.clean: false`
   (one captain-lock substitution forced by the overlap bound: "Pitchers duel - both
   starters rostered" swapped Chris Sale -> Jacob Misiorowski). Section 1 looks like it
   reads a Classic-shaped relaxation/gates field and doesn't know about Showdown's
   `counted_relaxations` / `captain_exposure` / `player_exposure` blocks. Read the primary
   brief directly rather than trusting section 1 for a Showdown build.

3. `tools/qa_portfolio.py` section 4 reported all 7 contest IDs as "archetype UNRESOLVED
   ... the brief carries no contest_shape for this id," even though `build_slate.py
   --postures <id>=<archetype>,...` was passed for all 7 on this build. Showdown's
   thesis-ladder construction doesn't appear to branch by contest at all: one 19-lineup
   ladder was built across the whole entries file regardless of which of the 7 contests
   each blank row belonged to. `--postures` may be a silent no-op for Showdown today.
   Worth confirming with DEV whether Showdown is meant to read postures, and if not,
   whether the flag should warn (rather than silently accept) when passed on a Showdown
   build.

Filed by BUILD, `slate_2026-08-21_atlmil_sd` (delivered
`outputs/2026-08-21/DKEntries_showdown_1610_1g_sd.csv`,
sha256 `05185e4d955cb0d93e8033077658a5de429a0d985ab84cd77c8e7973cab837a5`).
