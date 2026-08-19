# Cross-book American-odds averaging produces impossible prices at the ±100 boundary

**Found:** 2026-08-19, BUILD session, slate tag `1235_4g`, run
`20260819T153118Z_49f8ec18`. Root cause confirmed, not inferred.

## The bug

`live_data_adapters.parse_the_odds_api_totals` averages moneylines across
books arithmetically. American odds are discontinuous at ±100: -104 and +100
are ADJACENT prices, both about 50%, but their arithmetic mean is -2.0, which
as an American price reads as a 98% favorite.

ATL@MIN on this slate:

    draftkings   ATL -104   MIN -104
    fanduel      ATL -108   MIN +100
    parsed  ->   {'ATL': -106.0, 'MIN': -2.0}

ATL averaged cleanly because both books were negative. MIN straddled the
boundary and came out at -2.0. Downstream:

    american_to_implied_prob(-2.0)   = 0.0196
    devig vs ATL                     -> p_away 0.963, p_home 0.037
    margin = 2.4 * (p_home - p_away) = -2.22
    split  = ((8.5 + 2.22)/2, (8.5 - 2.22)/2) = ATL 5.36 / MIN 3.14

Both halves of the pipeline below the parser are correct.
`american_to_implied_prob`, `vig_free_probabilities` and
`implied_team_totals` all do the right thing with the price they are handed.
The parser hands them a price no book ever posted.

**Reproduce:** any game where two books straddle ±100. On a near-pick'em that
is the NORMAL shape, since one book will juice both sides to -104/-104 and
another will post -108/+100.

**Blast radius:** the closer a game is to a coin flip, the more wrong F1 gets.
That inverts the intent. It is exactly the games with no real edge that get
the largest fabricated split, and F1 clips at 0.85/1.15, so a pick'em can
deliver the maximum boost to one side and the maximum penalty to the other.

## Two related things worth fixing in the same pass

`total` is averaged the same way (DET@PIT: DK 8.5, FD 8.0 -> 8.25). That one
is at least a real number, but it is a line neither book posts, and the
half-run grid exists for a reason.

Averaging books at all is the questionable step. A single-book read, or a
median with a sign guard, or averaging in PROBABILITY space and converting
back, are all defensible. Averaging in American-odds space is not, at any
distance from ±100, because the scale is not linear there either.

## The workaround this session used, and why it was then REVERTED

Filtering `odds_raw_totals` to draftkings only fixes it at the input with no
engine change: one book cannot straddle itself.

    ATL@MIN  8.5  {ATL -104, MIN -104}  ->  ATL 4.25 / MIN 4.25   (correct)

The rebuild on corrected odds was then **rejected and the original delivered**,
which is the more interesting half of this note. Correcting MIN from 3.14 to
4.25 is a 35% swing, and it moved the build hard into MIN bats. MIN had not
posted a lineup, so those bats came off a 14.6-day-old platoon reference.
The corrected build carried 17 projected-order hitters against the original's
8, put the weakest arm on the slate (Robert Stock, roughly his fourth career
start) in 4 of 8 entries against the original's 2, and dropped the apex
contest's entry from 149.9 to 133.4 ceiling.

So: the number got more honest and the portfolio got worse, because the team
the correction promoted is the team with the least reliable roster data. That
is not an argument against fixing the bug. It is an argument that F1 accuracy
and lineup-source confidence interact, and nothing in the build reconciles
them today. A confirmed-lineup team and a platoon-projected team are treated
as equally knowable once F1 has spoken.

Worth asking whether a TBD team should carry a confidence discount that F1
cannot override. Filed as an observation, not a proposal.
