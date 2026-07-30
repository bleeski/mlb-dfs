# Field shape analysis — 138 archived contests

ARCHIVE session, 2026-07-30. Built after mining the 37 outstanding contests
(A-027, A-028) from the standings inbox.

**Truthful labels.** Every number here is an observed outcome read out of a DK
standings export or a deterministic descriptive statistic computed from those
observations. None of it is ROI, a win rate, a cash rate, or a probability
claim. "Finish percentile" is a positional observation. "Top-decile lift" is a
shape's top-decile rate inside a contest minus that same contest's overall
top-decile rate, averaged with equal weight per contest. Bootstrap intervals
describe the dispersion of statistics already computed from observed data.
They are not forecasts.

## Sample

| | |
|---|---|
| Contests archived | 138 |
| Contests where our entries were identified | 123 |
| Our entries found in standings | 347 |
| Field entries decomposed | 57,848 |
| Classic contests with >= 40 parsed entries | 78 (43,045 entries) |
| Money coverage | entry fee on all 134 own-result rows; winnings null on the 37 newly mined |

Contest archetypes: 96 satellite, 9 supersatellite, 7 GPP single-entry, 7 GPP
solo shot, 2 GPP max-entry, 1 multiplier, 16 UNRESOLVED (15 of those carry no
contest name because they never appeared in a delivered DKEntries file).

---

## Q1. Do we perform better in certain contest types?

**No. On this archive we cannot distinguish our finish from the field median
in any contest type.** Contest-level means, equal weight per contest, with
bootstrap intervals:

| archetype | contests | mean finish pct | 95% interval |
|---|---|---|---|
| satellite | 96 | 47.8 | [42.3, 53.3] |
| supersatellite | 9 | 52.4 | [33.1, 76.1] |
| gpp_single_entry | 7 | 34.0 | [12.4, 59.6] |
| gpp_solo_shot | 7 | 48.1 | [25.4, 69.1] |
| gpp_max_entry | 2 | 29.9 | n too small |
| multiplier | 1 | 50.0 | n too small |
| **ALL** | **123** | **46.9** | **[42.4, 51.7]** |

Every interval contains 50.0, which is the field median by construction. The
GPP single-entry number (34.0) is the one that looks alarming and it is the one
with seven observations and an interval spanning 12 to 60. It is not evidence.

Classic against Showdown is the only split with enough contests to test, and it
does not survive either:

- Classic, 89 contests, mean of contest means 48.6
- Showdown, 34 contests, mean of contest means 42.4
- Observed difference +6.2 percentile points
- Share of 5,000 label shuffles at least this large: **0.271**

A gap that appears in 27% of random relabelings is contest-level noise. Our own
top-decile rate across all 347 entries is 11.8% against a 10.0% base, which is
also inside noise.

**What this means for the ledger.** The archetype question is not answerable
yet and the honest entry is "no separation detected at n=123 contests." The
sample is also badly unbalanced: 96 of 138 contests are satellites, so even a
real GPP effect would have nowhere to show up. If separating archetypes
matters, the archive needs GPP contests, not more satellites.

**One caveat that cuts against percentile as the metric at all.** In a
satellite the only outcome that pays is finishing inside the seats, and seat
counts were never captured from the contest page. Finish percentile treats
30th of 118 and 90th of 118 as different when both may be worth zero. For 96 of
138 contests the metric above is measuring the wrong thing, and that cannot be
fixed retroactively.

---

## Q2. What are winning lineups doing that we are not?

**One 5-man stack with a 2-man secondary. The 5-2-1 shape.** It is the single
most common Classic winning construction, the field builds it a quarter of the
time, and we build none of it.

### The shape table

Within-contest top-decile lift, equal weight per contest, 53 Classic contests
with at least 40 parsed entries:

| shape | field share | our share | top-decile lift | 95% interval |
|---|---|---|---|---|
| **5-2-1** | **25.1%** | **0.0%** | **+3.1pp** | **[+1.2, +5.1]** |
| 5-1-1-1 (lone 5) | 6.5% | 0.0% | +2.9pp | [-0.6, +6.6] |
| 4-4 | 3.7% | 10.3% | +2.3pp | [-1.6, +6.8] |
| 5-3 (big double) | 16.5% | 16.0% | -0.1pp | [-2.2, +2.2] |
| 4-2-x (spread) | 11.4% | 39.8% | -1.0pp | [-2.9, +0.9] |
| 4-3-1 | 8.8% | 14.1% | -1.5pp | [-3.8, +1.0] |
| <= 3 primary | 28.0% | 6.4% | -2.8pp | [-4.1, -1.5] |

Two rows have intervals that exclude zero. 5-2-1 on the upside and "3 or fewer
primary" on the downside. Everything else is indistinguishable from the
contest's own base rate on this evidence.

The engine already gets the downside right. We build the reliably bad shape
6.4% of the time against a field that builds it 28.0%. The gap is entirely on
the upside: we do not reach for the shape that wins.

### It holds inside our actual contest mix

The concern with a shape finding is that it lives in contests we do not enter.
It does not:

| slice | contests | 5-2-1 lift | 95% interval |
|---|---|---|---|
| all | 53 | +3.1pp | [+1.2, +5.1] |
| satellite and supersatellite | 44 | +3.4pp | [+1.1, +5.8] |
| GPP, non-satellite | 9 | +1.6pp | [+0.1, +3.1] |
| field <= 150 | 31 | +3.3pp | [+0.5, +6.4] |
| field 151-500 | 12 | +4.1pp | [+0.9, +7.6] |
| field > 500 | 10 | +1.5pp | [+0.2, +2.9] |

Positive in every slice, and the interval excludes zero in every slice. The
effect is smaller in large fields, which is what you would expect when the
winning score has to be more extreme.

### The size gap, paired inside each contest

Across 69 Classic contests where we had entries and the field had at least 20:

- Our 5-stack share: **6.5%**
- The same contests' field 5-stack share: **44.2%**
- The same contests' top-decile 5-stack share: **49.9%**
- Winners with a 5-stack: **52.2%**
- Contests where we stacked 5 less than that contest's field: **63 of 69 (91%)**

Independent recomputation straight from the mined JSON, bypassing the
intermediate dataset: 5-2-1 lift +3.11pp, positive in 37 of 53 contests, field
share 25.1%, our share of Classic entries in those contests 0.0% of 156. The
two paths agree.

### What we build instead

Our Classic shape mix against the field's, same contests:

| our shape | our share | field share |
|---|---|---|
| 4-2-1-1 | 32.1% | 7.2% |
| 5-3 | 16.0% | 16.5% |
| 4-3-1 | 14.1% | 8.8% |
| 4-1-1-1-1 | 12.8% | low |
| 4-4 | 10.3% | 3.7% |
| 4-2-2 | 7.7% | 2.5% |

We are a 4-stack shop. Where we do build a 5-stack it is almost always 5-3,
which is the one member of the 5-stack family with no measurable lift
(-0.1pp, interval spanning zero). We build the two shapes with positive lift,
5-2-1 and 5-1-1-1, essentially never.

### Why the engine does this

The mechanism is visible in the code and it is not a bug.

1. `MAX_HITTERS_PER_TEAM = 5` in `optimizer_v3.py`, so 5-stacks are legal.
2. `PRIMARY_STACK_MIN_HITTERS = 3`. The primary stack is *identified* at 3 or
   more. Nothing *requires* it to be 5.
3. There is no constraint anywhere that targets primary stack **size**. The one
   stack control in `STRATEGY_DEFAULTS` is
   `max_primary_stack_exposure_pct`, 35% on the `wta_satellite` row, and that
   caps how many entries may share a primary stack **team**.

So the solver maximizes projected points subject to salary and exposure, and
correlation is not in the objective. The fifth bat of a stack is usually a
weaker projection than the best available isolated bat, so a mean-maximizing
MILP declines it every time. The 35% team-concentration cap then pushes the
portfolio to spread across more teams, which mechanically produces 4-2-1-1 and
4-3-1. The engine is doing exactly what it was told. It was never told that
stack size is the thing that wins.

### Size of the prize

Applying the archive's own within-contest lifts to a mix change:

- Our current mix, weighted average top-decile lift: **-0.74pp**
- A mix of only 5-2-1 and 5-1-1-1: **+2.99pp**
- Arithmetic difference: **+3.73pp of top-decile rate**

This is arithmetic on observed outcomes. It is not a projection of results, and
it assumes the lift survives us actually building the shape, which is exactly
the thing a portfolio-level change can break.

---

## Secondary finding: salary discipline runs the wrong way in each format

| | our median salary left | field median | winner median | our at-cap share | winner at-cap share |
|---|---|---|---|---|---|
| Classic | $100 | $200 | $300 | 61.0% | 29.7% |
| Showdown | $300 | $200 | $100 | 35.5% | 58.1% |

In Classic we spend to the cap harder than the field and much harder than
winners. In Showdown we leave money on the table while winners spend it. Both
sit inside noise at this sample size (43 Showdown winners), and neither is
independent of the stack finding: a 5-2-1 costs differently than a 4-2-1-1, so
the Classic salary gap may just be the shape gap wearing a different hat. Do
not act on this row on its own.

---

## Verification notes

- **42 of 138 contests report `ownership_recompute_ok: false`.** All 42 also
  report `parse_structural_ok: true`, `roster_slots_observed ==
  roster_slots_expected`, and a lineup recompute totalling exactly
  100 x roster_size. This is the small-field condition already recorded in the
  ledger above A-013: DK's `%Drafted` table sums short because DK omits
  position rows for multi-position players. Lineup-derived ownership is
  authoritative. The construction features used throughout this analysis come
  from the Lineup column, not from `%Drafted`, so they are unaffected.
- **The pooled comparison was wrong and was discarded.** Comparing our 347
  entries against every winner in the archive compares two different
  populations, because our entries concentrate in satellites on particular
  slates. Every headline number above is paired inside a contest.
- **`tools/net_to_date.py` has a total-line inconsistency.** The per-date rows
  sum fees over all contests; the TOTAL line sums over contests that have both
  a fee and winnings. The date column now sums to $64.21 while TOTAL prints
  $51.46. The date rows are right. Logged for DEV in
  `docs/backlog_inbox/2026-07-30_archive_net-to-date-total.md`.
- **The full test suite could not be run.** `tools/audit.py --run-tests` exceeds
  the 45s sandbox call ceiling and scipy is absent from this sandbox. No engine
  file was touched by this session, and the miner does not import scipy.
