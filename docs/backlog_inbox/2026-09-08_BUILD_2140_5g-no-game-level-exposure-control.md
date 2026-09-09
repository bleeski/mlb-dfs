# The washout axis the QA tool names has no control behind it: game-level exposure

Slate 2140_5g (2026-09-08), BUILD, 15 entries, 5 games. Both delivered candidates
sat at ~81% ceiling retained on the binding game with exactly 1 entry intact by
design, and NO available control could move it.

**The measurement exists and the lever does not.** `qa_portfolio.py` prints
`washout axis 'game': most-shared value is CIN@LAD at 7/15 (47%)` and the run's
own `frontier.washout` names CIN@LAD as binding at 81.3% retained. But the three
portfolio controls bind on a PERSON (`max_player_exposure_pct`), a STACK
(`max_primary_stack_exposure_pct`) and an ARM (`max_pitcher_exposure_pct`).
CIN@LAD reached 39 of 150 roster slots without any of them binding, because the
exposure arrived as many individually-legal one-offs plus the arm: Skubal 6/15
(under the 0.43 pitcher cap), LAD as a PRIMARY stack only 1/15 (far under the
0.35 stack cap), and then Betts 7, Smith 7, Freeman 5, Teoscar 3, Muncy 2,
Edman 1 as ordinary roster filler. Every count legal, the aggregate the single
largest correlated exposure in the file.

**Measured feasibility edge, which is why this is not fixable by tightening what
exists.** On this bank `max_player_exposure_pct` at 0.35 refused (R157 rescue),
0.40 refused, 0.50 certified with four bats pinned at exactly 7/15 = the cap
count. So the concentration on those four is STRUCTURAL for 15 entries out of a
5-game pool, not a preference, and there is no room to decorrelate by lowering
the person cap.

**Proposed:** a `max_game_exposure_pct` control counting roster slots (or
entries touched) per GAME, relaxing in the documented order alongside the other
three. It is the one axis the dual objective's washout half actually names and
the only one the solver cannot see. Note the open question the tool already
flags: whether an ARM in a game belongs in a game-washout count at all, since an
arm can benefit from the script that kills the bats. Decide that before
implementing, or the control will count the wrong thing.

**Also worth fixing:** `--leverage` was near-inert here. At the skill's own
recommended starting cap (`max_cumulative_ownership_pct: 95`) the delivered
cumulative sums were 53.5 to 93.9, so the cap never bound; only
`min_low_owned_hitters: 1` moved anything (entries carrying at most one of the
top trio 8 -> 10, apex 1975.69 -> 1956.34, -1.0%). Low-owned carry stayed 0/15
in BOTH builds. The prior spreads ~800% over 208 priced hitter rows with a top
hitter at 14.7%, so on a slate this size the cumulative cap cannot bind at 95
and the skill's "start at 90-95" is the wrong starting point here. Either scale
the recommended cap to the prior's own spread, or say plainly that the cap is
inert until the prior is fitted and `min_low_owned_hitters` is the only live half.
