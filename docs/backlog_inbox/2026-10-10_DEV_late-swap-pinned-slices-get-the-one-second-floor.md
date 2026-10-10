# 2026-10-10 DEV (Session 29, R284): after the general slice drains `--budget`, each pinned entry's slice gets the 1.0s floor over a job grid that can be thousands of jobs wide

**Observed.** `tools/late_swap.py` slices ONE total budget (`--budget`, default 30s, R25): the general `extend_bank` call takes `_slice_budget()`, which is everything left, and each pinned entry's call then gets `max(1.0, slice_deadline - now)`, so after the general slice drains the budget every pinned entry is the one-second floor. Measured in scratch on the vendored 2026-06-03 slate (2 games, a 10,200-job grid, about 0.1s per infeasible job): with three hitters pinned on one team a 10s slice built 27 candidates; with two hitters pinned from different teams about 100 jobs were attempted in 10s, all answered infeasible, 0 built. A 1s slice on that grid attempts about 10 jobs.

**Why it is filed and not fixed in Session 29.** The measurement used synthetic pins, not one entry's real locked players, and on the vendored 2-game slate; it has not been seen on a delivered swap. R468's 1400_4g failure (`+0 targeted candidates`) had a different cause (an absent declared arm). Session 29 changed the pinned slices only to ask the four as before and a best-effort five with leftover budget, adding no floor.

**Candidate item.** Measure on an archived multi-game slate with a real parent: how many pinned entries finish with `+0 targeted candidates` at the default `--budget`, and whether reserving a per-entry share of the budget before the general slice runs (or capping the general slice) removes them. If it does, the change is in `late_swap.py` alone. S; needs the measurement first. Held with R25-tail (the late-swap fast path), Session 90.

Nothing here is a lift, an edge, an ROI or a win rate.
