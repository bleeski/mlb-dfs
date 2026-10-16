# Stage 0's referee names a primary stack on stackless rosters (the R449 seam, one copy left)

Filed by DEV, 2026-10-16 (Session 65, R449), found by the R233 enumeration.

R449 gave `dk_entries_manager._primary_stack` the optimizer's rule (`PRIMARY_STACK_MIN_HITTERS`, 3 hitters, most
first, alphabetical on a tie). `mlb_engine/production/referee.py:76-87` still takes the most-represented team with no
threshold (`min(stack_counts, key=lambda t: (-stack_counts[t], t))`), so a 2-2-2-2 roster lands in the alphabetically
first team's `primary_counts` bucket and costs `max_primary_stack_exposure` a unit the solve never spent. Stage 0 is
R302's strangler, off the build path, so Session 65 named it as a kept copy rather than changing it.

Do not threshold it naively: `primary_counts[primary] += 1` then feeds the cap check at `:146-153`, which iterates every
key, so a `""` for a stackless roster becomes a phantom bucket capped like a team (F15's 'NONE' defect again). The fix
is the threshold plus skipping `""` in both `primary_counts` and the cap loop, and the same in stage 0's own optimizer
if it buckets `c.primary_stack` (`portfolio.py:58`). Showdown mode counts every player toward `stack_counts`; keep that.

Check: a stage-0 test with a 2-2-2-2 Classic roster and `max_primary_stack_exposure` below 1.0 that fails today.
