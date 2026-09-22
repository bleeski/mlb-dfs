# F4 grades hitters against the opener, not the declared bulk arm

BUILD, 2026-09-22, slate 1840_5g (turbo, 4 live games after TOR@BAL was postponed).

## What happened

WSH ran an opener: DK `Starting` tagged Riley Cornelio `PO` and Jackson Kent
`PLR`; RotoWire and CBS both reported Kent as the bulk arm. The build declared
Kent with `--declare-pitcher 44223669=viable_bulk_or_alt_sp`, which cleared the
pool blocker and made him rosterable.

The declaration never reached F4. `extract_opposing_probables` reads the feed's
`probable_pitcher`, which named Cornelio, so every DET hitter was graded against
Cornelio's Savant est_wOBA-against (.296, 142 PA) instead of Kent's (.351, 151
PA). League mean was .332. DET had the slate's top implied team total (4.19).

Measured on the same inputs, fresh Savant references, feed edited so WSH's
probable reads Kent (MLBAM 800600, R, same hand as Cornelio so only the
SP-quality term moves):

| | DET mean F4 | DET mean Ceiling | DET primary stacks (of 4) |
|---|---|---|---|
| probable = Cornelio (run 20260922T202225Z_0c680c49) | 0.911 | 8.75 | 0 |
| probable = Kent (run 20260922T202428Z_a8965ab7, delivered) | 1.059 | 10.13 | 1 |

So an opener game marks down the opposing offense by the opener's quality for
the whole game, and the operator's declaration of the bulk arm does nothing to
correct it. The delivered file used the edited feed
(`data/slates/2026-09-22/lineups_feed_wsh_bulk_kent.json`, gitignored).

## Suggested fix

When a side's DK `Starting` is `PO` and a declared arm exists for that team
(role `viable_bulk_or_alt_sp`, or a `PLR` the operator declared), feed the bulk
arm to `extract_opposing_probables`, or a PA-weighted blend (opener about 1-2
innings, bulk about 4-5). Name the substitution in `pool_report` so the brief
says which arm F4 graded against. Until then the workaround is the one-field
feed edit above, recorded in the brief.
