# Ownership prior grade | archetype `large_field_gpp` | 8 archived contest(s)

Filed 2026-09-03 by DEV (R306 step 1), from `tools/ownership_grade_archive.py`. ARCHIVE merges into the calibration ledger.

Every row is ONE contest measured on its own. Nothing below is pooled across contests: the summary lines are MEDIANS OF PER-CONTEST STATISTICS within one archetype and one field-size band, never a statistic recomputed over a merged player set. Every figure is an observed count from an archived DK standings export or a deterministic statistic over one; the Spearman is a rank correlation between two measured shares. Nothing here is a win rate, a cash rate, an ROI figure, an edge, or a probability claim, and one contest never moves a prior.

**Self-inclusion caveat, carried forward.** Ben's own entries sit in the denominator of every contest he entered, and the small fields here are where that bites hardest. A larger sample dilutes the bias and does not remove it, and a four-figure field is a different archetype rather than a bigger version of a small one -- which is what the field-size banding is for.

## Field band `f_2001_plus` -- 8 contest(s)

| contest | date | field | Spearman | mean signed err (pts) | MAE (pts) | joined | beats flat-budget | tilts inert |
|---|---|---|---|---|---|---|---|---|
| `192798437` | 2026-07-27 | 11890 | 0.762 | -2.89 | 7.56 | 108 | True | base_projection, implied_totals |
| `192847713` | 2026-07-28 | 11890 | 0.62 | -2.79 | 5.37 | 141 | True | base_projection, implied_totals |
| `192897439` | 2026-07-29 | 17835 | 0.447 | -1.59 | 3.47 | 232 | True | base_projection, implied_totals |
| `192944793` | 2026-07-30 | 17835 | 0.669 | -1.77 | 4.03 | 195 | True | base_projection, implied_totals |
| `193035795` | 2026-08-01 | 14268 | 0.758 | -2.61 | 5.51 | 129 | True | base_projection, implied_totals |
| `193565685` | 2026-08-11 | 47562 | 0.567 | -1.05 | 2.38 | 357 | True | base_projection, implied_totals |
| `193702607` | 2026-08-13 | 5460 | 0.545 | -3.33 | 4.52 | 140 | True | base_projection, implied_totals |
| `193726856` | 2026-08-13 | 5044 | 0.637 | -6.6 | 11.91 | 58 | True | base_projection, implied_totals |

- Median of the per-contest Spearmans in this band: **0.629** (n=8 contests).
- Median of the per-contest mean signed errors: **-2.7** points. Positive means the prior OVER-predicts the level.
- Median of the per-contest MAEs: 4.945 points. Beats a flat-budget allocation in 8 of 8.

