# Every portfolio control counts ENTRIES; the money is not distributed that way

**Found:** 2026-08-19, BUILD session, slate `1235_4g`, run
`20260819T153118Z_49f8ec18`. Surfaced by an external red-team review of the
delivered file; neither the build, `qa_portfolio.py`, nor this session's own
adversarial pass caught it.

## The gap

`max_player_exposure_pct`, `max_primary_stack_exposure_pct`,
`max_pitcher_exposure_pct` and `max_shared_players` all measure share of
ENTRIES. The washout and apex proxies in `execution_pipeline` do the same.
Every one of them uses an equal-weighted denominator.

The entered set on this slate was not equal-weighted. Eight entries across six
contests, $17.75 total, with a single $15 entry carrying **84.5% of the
money**:

    $15.00   MLB $100K Relay Throw          1 entry
    $ 1.00   MLB $5K Solo Shot              1 entry
    $ 0.50   MLB $7.5K mini-MAX             1 entry
    $ 1.25   five $0.25 satellites          5 entries

Read on the count denominator the build used, the heaviest exposures are 4 of
8, a comfortable 50%. Read on dollars they are not comfortable:

| player | entries | count share | DOLLAR share |
|---|---:|---:|---:|
| Drake Baldwin | 4/8 | 50% | **94.4%** |
| Jackson Merrill | 4/8 | 50% | **94.4%** |
| Paul Skenes | 3/8 | 38% | **91.5%** |
| Michael King | 3/8 | 38% | **88.7%** |
| Matt Olson | 2/8 | 25% | **84.5%** |

Matt Olson is the clearest case. He appears in a quarter of the entries and
carries five sixths of the bankroll, because one of those two entries is the
$15 one. A control that reads 25% is describing a different portfolio than
the one that exists.

This is not a caps-are-too-loose complaint. The caps are enforcing a
constraint nobody chose. Diversifying entries 2 through 8 away from entry 1
costs real ceiling in those entries and buys almost no dollar
diversification, because entries 2 through 8 are $2.75 combined.

## Why it bit here specifically

Ben's dual objective is large wins with no total washout, and CLAUDE.md
already states that the washout objective binds at the PORTFOLIO level rather
than within a lineup. That is right, and it is exactly the sentence this gap
undermines: portfolio-level is being computed as an unweighted mean over
entries. On a menu that is one real entry plus seven tickets, an unweighted
portfolio statistic is close to meaningless. The washout proxy reported 75%
on the binding game by entry count; by dollars the same axis is far worse,
because the $15 entry has six of ten roster spots in that game.

Note this also changes how a session should read a refusal. This session
raised `max_player_exposure_pct` from 0.35 to 0.55 to clear an infeasible
joint MILP, and defended it on the grounds that six of eight entries sit in
independent contests where wins are additive. That reasoning holds on the
count axis and is roughly irrelevant on the dollar axis, where there is
one entry and change.

## What to consider

Not a proposal, an options list; the choice is Ben's because it is a strategy
question, not arithmetic.

1. **Report both.** Cheapest and probably first: `qa_portfolio.py` prints a
   dollar-weighted exposure table beside the count one, and the brief carries
   both denominators. Changes no build, ends the illusion.
2. **Weight the proxies.** Apex and washout become fee-weighted over the
   entered set. This is the one that makes the dual objective mean what it
   says.
3. **Weight the caps themselves.** Largest change and the one most likely to
   have surprising interactions with feasibility; do not do this first.

The entry fee is already in the DKEntries file, column 4, so no new input is
needed for any of the three.

## Related

The equal-weighting assumption is also why "eight unique lineups" reads as
eight independent shots. They are legal and distinct, and on this slate they
were one shot plus seven lottery tickets. See
`2026-08-19_BUILD_f1-implied-split-wrong-on-a-pickem-game.md` for the other
finding from the same slate.
