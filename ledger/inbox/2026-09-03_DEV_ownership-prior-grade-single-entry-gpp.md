# Ownership prior grade | archetype `single_entry_gpp` | 42 archived contest(s)

Filed 2026-09-03 by DEV (R306 step 1), from `tools/ownership_grade_archive.py`. ARCHIVE merges into the calibration ledger.

Every row is ONE contest measured on its own. Nothing below is pooled across contests: the summary lines are MEDIANS OF PER-CONTEST STATISTICS within one archetype and one field-size band, never a statistic recomputed over a merged player set. Every figure is an observed count from an archived DK standings export or a deterministic statistic over one; the Spearman is a rank correlation between two measured shares. Nothing here is a win rate, a cash rate, an ROI figure, an edge, or a probability claim, and one contest never moves a prior.

**Self-inclusion caveat, carried forward.** Ben's own entries sit in the denominator of every contest he entered, and the small fields here are where that bites hardest. A larger sample dilutes the bias and does not remove it, and a four-figure field is a different archetype rather than a bigger version of a small one -- which is what the field-size banding is for.

## Field band `f_0001_0100` -- 2 contest(s)

| contest | date | field | Spearman | mean signed err (pts) | MAE (pts) | joined | beats flat-budget | tilts inert |
|---|---|---|---|---|---|---|---|---|
| `192934735` | 2026-07-29 | 95 | 0.525 | -2.24 | 10.28 | 21 | True | base_projection, implied_totals |
| `192977444` | 2026-07-30 | 95 | 0.337 | 0.17 | 8.99 | 20 | True | base_projection, implied_totals |

- Median of the per-contest Spearmans in this band: **0.431** (n=2 contests).
- Median of the per-contest mean signed errors: **-1.035** points. Positive means the prior OVER-predicts the level.
- Median of the per-contest MAEs: 9.635 points. Beats a flat-budget allocation in 2 of 2.

## Field band `f_0101_0500` -- 16 contest(s)

| contest | date | field | Spearman | mean signed err (pts) | MAE (pts) | joined | beats flat-budget | tilts inert |
|---|---|---|---|---|---|---|---|---|
| `192754543` | 2026-07-25 | 142 | 0.165 | 0.79 | 16.69 | 24 | False | base_projection, implied_totals |
| `192923620` | 2026-07-29 | 142 | 0.15 | 1.17 | 12.99 | 22 | True | base_projection, implied_totals |
| `192924379` | 2026-07-29 | 178 | 0.221 | -0.61 | 10.64 | 20 | True | base_projection, implied_totals |
| `192935418` | 2026-07-29 | 297 | 0.464 | -2.06 | 12.83 | 22 | True | base_projection, implied_totals |
| `192948814` | 2026-07-29 | 297 | 0.681 | -7.67 | 9.34 | 59 | True | base_projection, implied_totals |
| `192972500` | 2026-07-30 | 334 | 0.826 | -2.11 | 8.97 | 24 | True | base_projection, implied_totals |
| `192976860` | 2026-07-30 | 237 | 0.092 | 0.17 | 11.33 | 20 | True | base_projection, implied_totals |
| `192994189` | 2026-07-30 | 475 | 0.747 | -7.02 | 8.85 | 62 | True | base_projection, implied_totals |
| `192997189` | 2026-07-30 | 356 | 0.637 | -0.78 | 8.82 | 25 | True | base_projection, implied_totals |
| `193076001` | 2026-08-01 | 297 | 0.679 | -0.19 | 10.54 | 24 | True | base_projection, implied_totals |
| `193096806` | 2026-08-01 | 416 | 0.326 | -2.27 | 3.73 | 201 | True | base_projection, implied_totals |
| `193334579` | 2026-08-06 | 118 | 0.574 | -5.33 | 7.37 | 92 | True | base_projection, implied_totals |
| `193575022` | 2026-08-10 | 118 | 0.295 | -3.56 | 5.34 | 119 | True | base_projection, implied_totals |
| `193576674` | 2026-08-10 | 142 | 0.303 | -3.56 | 4.85 | 119 | True | base_projection, implied_totals |
| `193613968` | 2026-08-11 | 178 | 0.302 | -2.28 | 14.7 | 22 | False | base_projection, implied_totals |
| `193705554` | 2026-08-13 | 206 | 0.207 | -2.82 | 16.72 | 21 | False | base_projection, implied_totals |

- Median of the per-contest Spearmans in this band: **0.315** (n=16 contests).
- Median of the per-contest mean signed errors: **-2.19** points. Positive means the prior OVER-predicts the level.
- Median of the per-contest MAEs: 9.94 points. Beats a flat-budget allocation in 13 of 16.

## Field band `f_0501_2000` -- 18 contest(s)

| contest | date | field | Spearman | mean signed err (pts) | MAE (pts) | joined | beats flat-budget | tilts inert |
|---|---|---|---|---|---|---|---|---|
| `192454586` | 2026-07-19 | 1189 | 0.537 | -2.16 | 3.93 | 182 | True | base_projection, implied_totals |
| `192464310` | 2026-07-19 | 1486 | 0.597 | -5.22 | 11.34 | 59 | True | base_projection, implied_totals |
| `192627933` | 2026-07-22 | 594 | 0.836 | -6.99 | 7.78 | 61 | True | base_projection, implied_totals |
| `192656508` | 2026-07-23 | 594 | 0.699 | -8.45 | 12.21 | 46 | True | base_projection, implied_totals |
| `192710479` | 2026-07-25 | 891 | 0.715 | -3.15 | 5.92 | 108 | True | base_projection, implied_totals |
| `192897471` | 2026-07-29 | 1189 | 0.6 | 4.9 | 11.82 | 38 | True | base_projection, implied_totals |
| `192897496` | 2026-07-29 | 1783 | 0.81 | 3.8 | 8.67 | 42 | True | base_projection, implied_totals |
| `192900602` | 2026-07-28 | 594 | 0.342 | -0.35 | 11.97 | 23 | True | base_projection, implied_totals |
| `192921966` | 2026-07-29 | 1486 | 0.594 | -3.77 | 5.19 | 112 | True | base_projection, implied_totals |
| `193035792` | 2026-08-01 | 1189 | 0.638 | -7.17 | 11.17 | 61 | True | base_projection, batting_order, implied_totals, probable_sp |
| `193205103` | 2026-08-03 | 891 | 0.409 | -2.31 | 4.06 | 165 | True | base_projection, implied_totals |
| `193254942` | 2026-08-05 | 1189 | 0.587 | -2.65 | 4.23 | 157 | True | base_projection, implied_totals |
| `193333016` | 2026-08-06 | 891 | 0.655 | -3.17 | 5.65 | 121 | True | base_projection, implied_totals |
| `193621098` | 2026-08-12 | 1189 | 0.67 | 2.93 | 11.72 | 31 | True | base_projection, implied_totals |
| `193666509` | 2026-08-13 | 883 | 0.557 | -2.56 | 4.58 | 146 | True | base_projection, implied_totals |
| `193666510` | 2026-08-13 | 657 | 0.747 | -5.2 | 11.27 | 57 | True | base_projection, implied_totals |
| `193678271` | 2026-08-12 | 594 | 0.651 | -2.02 | 9.52 | 22 | True | base_projection, implied_totals |
| `193679368` | 2026-08-12 | 891 | 0.736 | -8.69 | 12.21 | 47 | True | base_projection, implied_totals |

- Median of the per-contest Spearmans in this band: **0.645** (n=18 contests).
- Median of the per-contest mean signed errors: **-2.9** points. Positive means the prior OVER-predicts the level.
- Median of the per-contest MAEs: 9.095 points. Beats a flat-budget allocation in 18 of 18.

## Field band `f_2001_plus` -- 6 contest(s)

| contest | date | field | Spearman | mean signed err (pts) | MAE (pts) | joined | beats flat-budget | tilts inert |
|---|---|---|---|---|---|---|---|---|
| `192630776` | 2026-07-23 | 2378 | 0.675 | 3.02 | 10.66 | 42 | True | base_projection, implied_totals |
| `192658268` | 2026-07-24 | 3567 | 0.793 | -2.36 | 5.24 | 118 | True | base_projection, implied_totals |
| `192798445` | 2026-07-27 | 2378 | 0.702 | 4.47 | 10.21 | 44 | True | base_projection, implied_totals |
| `193035787` | 2026-08-01 | 2972 | 0.781 | -3.13 | 5.46 | 109 | True | base_projection, implied_totals |
| `193303593` | 2026-08-06 | 3567 | 0.708 | 4.79 | 9.06 | 44 | True | base_projection, implied_totals |
| `193565681` | 2026-08-11 | 2378 | 0.676 | -3.43 | 7.21 | 85 | True | base_projection, implied_totals |

- Median of the per-contest Spearmans in this band: **0.705** (n=6 contests).
- Median of the per-contest mean signed errors: **0.33** points. Positive means the prior OVER-predicts the level.
- Median of the per-contest MAEs: 8.135 points. Beats a flat-budget allocation in 6 of 6.

