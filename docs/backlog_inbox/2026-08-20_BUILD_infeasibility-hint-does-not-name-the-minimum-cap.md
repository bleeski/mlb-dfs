# The infeasibility hint says "the interaction" and makes the operator binary-search it

Slate 2026-08-20 1240_6g, 6 entries across 4 contests, 6-game Classic.

`build_slate.py` refused three times at the posture/auto-floored defaults
(`max_pitcher_exposure_pct=0.43, max_player_exposure_pct=0.4,
max_primary_stack_exposure_pct=0.35, max_shared_players=6,
max_sp_pair_repetition=1`) against a bank that grew 25 -> 68 candidates with 61
distinct SP pairs and 12 distinct stacks represented. The hint each time:

> no single control is arithmetically binding against this bank, so the
> interaction of the active controls is.

Growing the bank was tried first per the autonomy policy and did not clear it.
Relaxing only the two STRUCTURAL checks (`max_shared_players` 6->8,
`max_sp_pair_repetition` 1->2) did not clear it either. What cleared it was one
cap, alone: `max_player_exposure_pct` 0.4 -> 0.5, i.e. floor(pct*n) 2 -> 3.

Finding it cost four full builds (~35s each) because the hint names the active
set but not which member to move, so the only way to locate the minimum change
is to re-run the whole build once per candidate control. The delivered portfolio
then posted 6 distinct primary stacks, 6 distinct SP pairs, 0 candidate-reuse
relaxations and a realized max player exposure of exactly 3/6 -- so the binding
cap was genuinely that one and everything else had slack.

Suggested: when the joint MILP proves infeasible, re-solve once per active
control with that control alone dropped (5 solves against an in-memory bank,
cheap next to 4 bank rebuilds) and name the ones whose removal restores
feasibility, with the smallest pct step that changes `floor(pct*n)`. That turns
a four-build search into one line the operator can take to Ben, which matters
because raising an exposure cap is explicitly Ben's call and the current hint
gives him no way to see how far the raise has to go.

Second, smaller: an IIS from HiGHS would say it directly if it is available on
this backend.
