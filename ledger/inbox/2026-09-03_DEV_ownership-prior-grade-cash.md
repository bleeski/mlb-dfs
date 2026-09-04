# Ownership prior grade | archetype `cash` | 1 archived contest(s)

Filed 2026-09-03 by DEV (R306 step 1), from `tools/ownership_grade_archive.py`. ARCHIVE merges into the calibration ledger.

Every row is ONE contest measured on its own. Nothing below is pooled across contests: the summary lines are MEDIANS OF PER-CONTEST STATISTICS within one archetype and one field-size band, never a statistic recomputed over a merged player set. Every figure is an observed count from an archived DK standings export or a deterministic statistic over one; the Spearman is a rank correlation between two measured shares. Nothing here is a win rate, a cash rate, an ROI figure, an edge, or a probability claim, and one contest never moves a prior.

**Self-inclusion caveat, carried forward.** Ben's own entries sit in the denominator of every contest he entered, and the small fields here are where that bites hardest. A larger sample dilutes the bias and does not remove it, and a four-figure field is a different archetype rather than a bigger version of a small one -- which is what the field-size banding is for.

## Field band `f_0101_0500` -- 1 contest(s)

| contest | date | field | Spearman | mean signed err (pts) | MAE (pts) | joined | beats flat-budget | tilts inert |
|---|---|---|---|---|---|---|---|---|
| `193564594` | 2026-08-11 | 124 | 0.026 | -3.86 | 5.55 | 152 | False | base_projection, implied_totals |

- Median of the per-contest Spearmans in this band: **0.026** (n=1 contests).
- Median of the per-contest mean signed errors: **-3.86** points. Positive means the prior OVER-predicts the level.
- Median of the per-contest MAEs: 5.55 points. Beats a flat-budget allocation in 0 of 1.

