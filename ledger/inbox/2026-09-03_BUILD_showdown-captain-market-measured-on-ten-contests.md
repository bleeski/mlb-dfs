# Realized Showdown captain ownership, measured on ten archived contests

Answers the measurement the companion fragments asked for
(`2026-09-03_BUILD_captain-ownership-is-its-own-market.md` step 1 and step 3,
`..._captain-leverage-and-qa-as-research-arm.md` part 1). Run during the
2210_1g_sd build (STL@LAD, 19 entries). No new parsing was needed:
`mlb_engine.field.field_miner.parse_standings_export` already returns
`captain_norm` per entry, so this is aggregation over what is on disk.

Ten Showdown contests in `data/standings/inbox/` carry >=30 complete lineups.
Each measured on its own, never pooled. Same caveats the companion fragment
states and they are not small: 31-48 entry satellite fields, Ben's own entries
in the denominator, so both concentration and the pitcher finding carry
self-inclusion and small-field-archetype bias.

## Finding (c) confirmed, 10 of 10

The most-captained player is a STARTING PITCHER in every one of the ten:
Yamamoto, Gore, Tolle, Cole, Cease, Drohan, Rocker, Houser, Lambert, Cole.
Median top-captain share **42%**, range 16-58%. Median distinct captains 13.
Most-rostered == most-captained in 8 of 10.

This upgrades the companion fragment's finding (c) from "six of eight" to
unanimous and moves it out of hypothesis. It is worth stating in the Showdown
strategy doc: **the captain slot is where the field buys the ace.**

## The new result: winning captains are BIMODAL, and the middle is the dead zone

Winner's captain, by that captain's realized share of the field:

| contest | N | winner's captain | its field share | popularity rank |
|---|---|---|---|---|
| ...774286 | 31 | mackenzie gore | 48% | 1 of 10 |
| ...182642 | 43 | dylan cease | 58% | 1 of 8 |
| ...068551 | 40 | gerrit cole | 45% | 1 of 11 |
| ...017526 | 40 | brandon pfaadt | 22% | 2 of 10 |
| ...225137 | 47 | ronald acuna | 17% | 2 of 13 |
| ...370267 | 43 | rafael devers | 14% | 2 of 13 |
| ...429261 | 32 | ben rice | 9% | 4 of 13 |
| ...485718 | 39 | hayden wesneski | 8% | 3 of 13 |
| ...708607 | 48 | andy pages | 6% | 3 of 13 |
| ...282826 | 48 | wyatt langford | 2% | 10 of 13 |

Four winners at >=22%, four at <=9%, two in between. The median of 15.5% is a
statistic of a bimodal distribution and should not be quoted as a target -- that
is the number this fragment most expects to be misread, so it is flagged here
rather than in a footnote. Field median captain share is 3.6%.

**The winner took the most-captained player in 3 of 10** while that player held a
median 42% of the field: under-represented at rank 1. But pooling the TOP FIVE
finishers over all ten contests, the #1 captain accounts for **23 of 50 (46%)**,
which against a ~42% field share is proportional.

The two readings are consistent and the split matters for contest selection:
**captaining the chalk ace is roughly neutral for a multi-place payout and
slightly negative for an outright win.** Satellites and Solo Shots pay rank 1
only, so on those the ace captain is the weaker side of a coin flip; a Jukebox
paying several places is indifferent.

## What it says about the delivered file

`DKEntries_showdown_2210_1g_sd.csv`, sha `588965d69e5b`, 19 entries, 8 distinct
captains: Skubal 21.1%, Freeman 21.1%, Betts 15.8%, Mathews 15.8%, Walker 10.5%,
Edman/Tucker/Baez 5.3% each.

Entry-weighted median captain share **15.8%** against the archived winners'
15.5%. That agreement is a coincidence of two medians and is NOT evidence the
portfolio is well-aimed -- our share is not the field's share, and the whole
point of the companion fragment is that we cannot yet compute the field's.
Stated so the next reader does not take it as validation.

The honest read: 4 entries sit on the chalk pole (Skubal, whom the field will
likely captain near 40% on this slate), roughly 9 in the middle band, roughly 6
on the contrarian pole. If the bimodal result holds, the portfolio is
over-weighted in the dead zone. That was NOT acted on tonight, for three reasons
worth recording:

1. Placing a barbell requires tonight's field captain shares, which is exactly
   the uncalibrated quantity the companion fragment is filed about. Acting would
   substitute a guess for the missing input.
2. The companion fragment already MEASURED every available lever and found each
   produces the opposite of the intent: tightening `max_cpt_exposure_pct` buys
   diversity and raises mean captain ownership; a CPT-row-only tilt scores worse
   than no tilt; a global `--projections` tilt breaks UTIL construction. The
   per-entry sleeve that would express this does not exist.
3. Hand-editing captains in a delivered file is a strategy change with no dead
   player behind it, which CLAUDE.md's Autonomy section reserves to Ben.

## The RotoWire rung, on a Showdown slate: do not spend the clock

Per `2026-09-03_BUILD_external-ownership-pull-is-not-in-the-build-loop.md` the
pull worked exactly as documented -- Ben signed in, Chrome, all 250 rows, all 20
players found, about 3 minutes. **The output was unusable for this build and the
reason is structural, not a transport failure.** The grid is ALL GAMES at Classic
pricing (Skubal $10,500, Betts $4,200). On a 12-game Classic slate the STL bats
read 0.04% to 2.26% because nobody rosters a rebuilding club's callups; in a
one-game Showdown the same players are rostered heavily because there are only 20
men available. Levels are meaningless across that gap and ordering is
contaminated by it: Alex Call reads 20.38% (a cheap Classic punt) against
Freeman's 12.71%.

Proposed amendment to that fragment's step 4: the clock gate should be
**Classic-only** until a per-draftgroup RST% is confirmed to exist. Its own open
question ("does RotoWire publish a per-draftgroup RST%") is answered NO for the
default view, which is the view the extraction snippet reads.

## What this unblocks

Step 3 of the companion fragment is done for ten contests and needed no new
code. The cheap next move is the same aggregation over all 53 Showdown files in
the inbox with the >=30-entry floor dropped, conditioned on archetype and field
size, filed as `ledger_block` output by ARCHIVE. That turns "the field captains
the ace" into a per-archetype number and gives the sleeve something to aim with.

## Labels

Every number is an observed count from an archived DK standings export or a
deterministic statistic over one. Nothing is ROI, win rate, cash rate, edge, or a
probability. n=10 contests, one archetype band, self-inclusion bias present.

## Reproduce

`parse_standings_export(p)` -> filter `lineup_complete`, count `captain_norm` for
the 100% captain budget and `set(players_norm)` for the 600% roster budget, per
contest, no pooling. Rank the top-5 finishers' captains by that contest's own
captain-popularity order.
