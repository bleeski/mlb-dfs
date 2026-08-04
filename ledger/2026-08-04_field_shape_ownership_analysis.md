# Field shape and ownership analysis — 239 archived contests

ARCHIVE session, 2026-08-04. Built after mining the 94 outstanding contests
(A-030..A-034) from the standings inbox, which roughly doubled the archive's
entry count. Companion to, and the first regrade of, the 2026-07-30 field
shape analysis.

**Truthful labels.** Every number here is an observed outcome read out of a DK
standings export or a deterministic descriptive statistic computed from those
observations. None of it is ROI, a win rate, a cash rate, or a probability
claim. "Finish percentile" is a positional observation. "Top-decile lift" is a
shape's top-decile rate inside a contest minus that contest's overall
top-decile rate, averaged with equal weight per contest. Bootstrap intervals
describe dispersion of statistics computed from observed data; they are not
forecasts. Winnings are uncaptured for every contest mined after 2026-07-28
(no entry-history export covers them), so nothing here is a money statement,
and the promotional channel remains unmeasured per ledger 3.14.

## Sample

| | |
|---|---|
| Contests archived, deduped on contest_id | 239 (192464820 counted once, per 3.16) |
| Newly mined this session | 94 (54 Classic, 40 Showdown; 68,855 field entries) |
| Own entries matched in the new tranche | 202 across 88 contests |
| Classic contests with >= 40 parsed entries | 116 (108,469 entries; 32 of them new, 60,184 entries) |
| Salary join on the new tranche | 100.0% on all 94 |
| Paid-places coverage | still ends at the 2026-07-28 entry-history export; 0 of 94 new contests carry a paid line |

New-tranche mix: 68 satellite/supersatellite, 15 solo shot (WTA family),
3 mini-MAX large-field GPP, 3 Showdown multiplier, 1 single-entry GPP, and the
remainder recurring satellites on Showdown slates. The archetype imbalance the
07-30 analysis flagged is unchanged: this is still overwhelmingly a satellite
archive, and GPP conclusions rest on few contests.

---

## Q1. Our results (percentile is not payout; seats stay uncaptured)

Contest-level mean of the median own finish percentile, equal weight per
contest, new tranche:

| type | bucket | contests | mean median pct | 95% interval |
|---|---|---|---|---|
| classic | satellite | 39 | 51.1 | [41.7, 60.4] |
| showdown | satellite | 29 | 47.7 | [39.4, 56.2] |
| classic | solo shot (WTA) | 7 | 63.8 | [51.8, 74.4] |
| showdown | solo shot (WTA) | 8 | 62.0 | [41.7, 80.6] |
| classic | supersatellite | 4 | 78.5 | [60.9, 93.0] |
| classic | mini-MAX | 3 | 48.6 | [7.8, 78.0] |
| showdown | multiplier | 3 | 69.6 | [40.0, 90.8] |

Satellites sit on the field median, as they did at 07-30. The solo-shot and
supersatellite rows sit above 50 with intervals that exclude it, on 4-8
contests; at that n this is worth watching, not acting on. Combined with the
prior archive the solo-shot interval re-includes 50 (55.7 [40.0, 69.9] on 11
Classic contests), which is what a small-sample flatter would look like.

**Two rank-1 finishes, the first in the archive.** 192892126 (MLB Satellite to
$15 Relay Throw, 2026-07-28, field 53) and 192973047 (MLB Satellite to NFL 9-13
$5 FFM (Early), 2026-07-30, field 23), both $0.25 Classic satellites, both
winning scores matched exactly by our best entry. Fee times field against
ticket face implies one-seat structures for both (53 x $0.25 = $13.25 against a
$15 ticket; 23 x $0.25 = $5.75 against a $5 ticket), but seat counts were never
captured from the contest pages, so these are recorded as rank-1 finishes, not
confirmed seats. Six further top-3 finishes landed in 23-entry satellites
(one rank 2, five rank 3), where the points gap to the winner ran 2.2% to 13%.

The 07-30 caveat stands unchanged and matters more now: in a satellite only a
seat pays, percentile is the wrong metric for 68 of the 94 new contests, and
paid-places capture (R30(a)) is still the missing piece.

---

## Q2. Shapes: the 5-2-1 lift decayed while the field crowded into it

The 07-30 analysis measured, on 53 Classic contests: 5-2-1 top-decile lift
+3.1pp [+1.2, +5.1] on 25.1% field share, and recommended reaching for it. The
new 32-contest tranche measures the same statistic at **+0.2pp [-2.1, +2.5] on
29.7% field share**. Combined, 116 contests: +2.0pp [+0.6, +3.5] on 26.6%.

| shape | new-32 lift | new-32 field% | combined-116 lift | combined field% |
|---|---|---|---|---|
| 5-2-1 | +0.2 [-2.1, +2.5] | 29.7 | +2.0 [+0.6, +3.5] | 26.6 |
| 5-1-1-1 | +2.8 [-1.9, +8.0] | 9.3 | +3.3 [+0.0, +7.0] | 7.8 |
| 5-3 | -1.2 [-3.5, +1.1] | 16.4 | +0.3 [-1.4, +2.1] | 15.8 |
| 4-3-1 | +3.2 [-0.7, +6.9] | 7.9 | +0.5 [-1.5, +2.7] | 7.9 |
| 4-2-x | -0.7 [-3.2, +1.9] | 8.3 | -2.2 [-3.6, -0.8] | 8.5 |
| <= 3 primary | -2.2 [-3.9, -0.6] | 23.1 | -2.8 [-3.8, -1.8] | 24.0 |

Three readings, in decreasing confidence:

1. **The downside shapes repeat and are the strongest result in the archive.**
   "3 or fewer primary" is negative in the prior tranche, the new tranche, and
   every conditioned slice (satellites -2.9 [-4.1, -1.7]; solo shots -2.6
   [-5.3, -0.1]; mini-MAX -2.9 [-3.8, -1.9]; every field-size bucket). 4-2-x,
   our single most-built shape, now excludes zero on the downside combined
   (-2.2 [-3.6, -0.8]).
2. **The 5-2-1 upside shrank as its field share grew.** Field share rose from
   25.1% to 29.7% tranche-over-tranche while the lift fell from +3.1 to +0.2.
   These are two observations of a crowd, not a causal claim, but the
   direction is exactly what crowding into a shape looks like, and it cuts the
   expected payoff of a late mix change toward 5-2-1.
3. **Win-line concentration did not repeat.** The 3.16 provisional line (5-2-1
   plus 5-1-1-1 take 46.6% of wins on 31.6% share) measures 31.2% of wins on
   39.1% of entries in the new tranche, and 31.0% on 34.4% combined —
   at-share, not concentrated. Downgraded to open; the 07-30 number reads as a
   first-tranche artifact.

### Conditioned slices (combined archive)

| slice | contests | 5-2-1 lift | note |
|---|---|---|---|
| satellites + supersats | 70 | +2.0 [+0.2, +3.9] | 5-2-1+5-1-1-1 win 35.7% on 30.3% share |
| solo shot (WTA) | 11 | +2.0 [+0.1, +4.3] | 5-2-1 wins 36.4% of contests on 21.5% share; 5-stack family takes 64% of wins |
| mini-MAX (>10k fields) | 5 | +1.4 [+1.0, +1.7] | 5-1-1-1 stronger: +3.6 [+1.4, +5.6] |
| field 61-150 | 25 | +1.2 [-1.2, +3.7] | |
| field 151-500 | 21 | +3.9 [+1.4, +6.5] | |
| field > 500 | 18 | +1.7 [+0.5, +3.2] | |

The WTA family is where 5-stacks over-win most clearly on this archive, and
the mini-MAX row is the tightest interval (five contests but 73,343 entries).
For "what wins large-field top-heavy contests," the observed answer is the
5-stack family generally and the lone-5 (5-1-1-1) specifically, not the double
stack: 5-3 is at-share everywhere it is measured.

### Our mix did not move

The 07-30 analysis identified the gap; the builds since then did not close it.
Our new-tranche Classic mix against the same contests' field:

| shape | ours | field |
|---|---|---|
| 4-2-x | 35.5% | 8.3% |
| <= 3 primary | 21.5% | 23.1% |
| 5-3 | 15.1% | 16.4% |
| 4-1-1-1-1 | 12.9% | 2.4% |
| 5-2-1 | 2.2% | 29.7% |
| 5-1-1-1 | 0.0% | 9.3% |

We under-stacked the field in 47 of 54 new-tranche contests with our entries
(our 5-stack share 10.8% against a field 47.7%). Two changes against 07-30:
we now build a little 5-2-1 (2.2% from 0.0%), and our "3 or fewer primary"
share tripled to 21.5% — which is the one family with a confirmed negative
lift. The mechanism in the optimizer (no constraint targets primary-stack
size; the exposure cap spreads teams) is unchanged from the 07-30 writeup, and
this is the R37 input, now with a second tranche behind it.

---

## Q3. Ownership: what the field's revealed ownership says about leverage

The engine currently assumes no per-player ownership (Ownership_Tier is a flat
Mid; ledger 4.1 is inert), so there is no predicted-vs-actual error to grade.
What the standings do measure is where revealed ownership sat relative to
outcomes.

**Leverage exists nearly every slate, and winners carry it at four times the
field rate.** In 104 of 116 Classic contests (>= 40 entries) at least one
player finished top-5 in contest FPTS while under 10% drafted (mean 2.19 such
players per contest). The winning lineup carried at least one of them in 51%
of those contests; the top decile carried one at a 35% rate; the field's base
rate was 13%. This is the first quantified statement in the archive of where
differentiation actually pays: low-owned high-scorers are available
essentially every slate, and reaching the win line without one happens only
about half the time.

**Pitching chalk is not where winners differentiate.** Winners used their
contest's #1 SP pair 24% of the time against that pair's 20.7% average field
share (115 contests) — at-share, slightly above. Eating the chalk SP pair and
differentiating with bats is what the winning population actually did; this is
consistent with the 4.3 hypothesis but now carries a number.

**Winner chalk posture splits by format and contest type** (within-contest
chalk-score percentile of the winner, median across contests; higher =
chalkier than field):

| | winner | top decile | ours |
|---|---|---|---|
| classic satellite (n=110) | 54.5 | 63.6 | 40.0 |
| showdown satellite (n=57) | 37.3 | 49.9 | 47.3 |
| classic supersatellite (n=12) | 38.6 | 67.4 | 31.4 |
| classic solo shot (n=11) | 53.9 | 52.1 | 53.0 |
| classic mini-MAX (n=5) | 60.1 | 59.1 | 41.1 |
| classic single-entry GPP (n=8) | 54.3 | 58.3 | 21.4 |

The 3.16 chalk-posture line ("satellite winners run sub-field chalk, median
36-40") survives only on the Showdown side and in supersatellites. Classic
satellite winners on the fuller sample run at-to-above field chalk (54.5), and
Classic GPP winners run chalk-positive. Cumulative lineup ownership agrees:
paired within contest, winners run above the field mean in Classic satellites
(+4.9 pts median), solo shots (+9.5), and single-entry GPPs (+8.6), and below
it only in supersatellites (-13.2). The regrade: **contrarianism is not the
observed winning posture anywhere except supersatellites; differentiation
shows up as one or two low-owned pieces inside an otherwise chalk-positive
lineup, and as stack shape.** Our own posture is mildly contrarian in exactly
the buckets where winners are not (classic satellites 40.0, single-entry GPPs
21.4, mini-MAX 41.1).

---

## Duplication and salary (re-observed, same directions)

Duplication is a Showdown problem and grows with field size: median share of
entries sitting in duplicated lineups is 27.2% in 151-500 Showdown fields
(winner duplicated 17% of the time) and 53.4% above 500 (winner duplicated
40%), against 0-13% for Classic. Our own lineups were duplicated by the field
27 times across 109 Showdown entries in the new tranche, against 4 of 93 on
the Classic side. Classic satellite winners remain essentially unduplicated.
The R10 priors hold.

Salary discipline runs the same wrong way as 07-30 in both formats: Classic
winners leave more salary than the field (median $250 left vs $200) while we
leave the least ($100); Showdown winners spend closer to the cap ($200 left vs
field $300) while we sit at the field's looseness ($300). Not independent of
the shape finding; recorded, not acted on.

---

## What this means, by the three questions asked

- **Lineups that cash:** unanswerable beyond top-decile proxies until
  paid-places capture resumes (no new contest carries a paid line; the
  entry-history export ends 2026-07-28). The 3.16 cash-line finding stands
  unregraded for lack of new coverage.
- **Lineups that win large prizes** (mini-MAX, >10k fields): 5-stack family,
  and specifically the lone-5 (5-1-1-1, +3.6pp [+1.4, +5.6]); chalk-positive
  cores (winner chalk percentile ~60) with leverage carried as one or two
  sub-10% pieces; salary not forced to the cap.
- **Lineups that win WTA** (solo shots): 5-2-1 over-wins its share (36.4% of
  wins on 21.5% field share); winners run at-field chalk, not contrarian; the
  "3 or fewer primary" family is as bad here as everywhere (-2.6pp).

## Verification notes

- All 94 new mines joined salary at 100.0%; zero structural-parse failures;
  14 contests flagged `ownership_recompute_ok: false` and every one satisfies
  the 3.16 identity exactly (max deviation < 0.1 pt), so lineup-derived
  ownership is authoritative throughout. Largest DK-table deficit: 23.7 pts
  (192896255).
- 192464820 is deduplicated on contest_id per 3.16 before every count above.
- Shape families here group by prefix (5-2-x under 5-2-1, 4-2-x spread), the
  same grouping as 07-30; per-entry patterns come from the Lineup column, not
  %Drafted, and are unaffected by the DK-table deficits.
- Old-tranche "our shape" rows exclude 40 entries from standings_only-era
  contests that carry no stack pattern; new-tranche coverage is complete.
- Every own-results row in the new tranche carries its entry fee from the
  delivered DKEntries files ($35.87 total across 94 contests); winnings are
  null pending an entry-history export, so no net lines exist for this
  tranche (cash-only when they do; the promotional channel stays unmeasured
  per 3.14).
