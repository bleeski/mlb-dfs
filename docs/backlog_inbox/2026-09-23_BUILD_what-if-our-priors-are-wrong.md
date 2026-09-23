# Ben, 2026-09-23: "what if all the conventional wisdom and our priors are wrong"

Ben stated this as the standing question for portfolio construction, during the
1905_10g slate. It is the washout objective applied to MODEL error rather than
game outcomes: no single prior should be able to take down the whole entered
set at once.

## What the delivered file does today (1905_10g, sha256 76c84563c7b9)

R406 sleeves seated 18 of 32 lineups in named "projection is wrong" worlds:
salary_only 6, chalk_fails 8, environment 4, with projection 14
(`exposure.classic_sleeves`).

Some priors are shared by ALL 32 lineups, in every sleeve, so no sleeve hedges
them:

1. **A primary stack of 4+.** All 32 lineups have one (30 are 4-man, 2 are
   5-man), and the minimum is 4 in every sleeve.
2. **Zero hitters facing the lineup's own SP** (the R288 convention). This
   holds in all 32 lineups. With Yamamoto in 10 lineups, SD bats were barred
   from those 10.
3. **The pool's projected orders for TBD sides**, from a 49-day-old platoon
   reference.
4. **The market and opposing-SP factors.** F1 (market totals) and F4
   (opposing-SP quality) shape 26 of 32 lineups: every sleeve except
   salary_only. The environment sleeve stacks the top implied totals, so it
   ADDS to the market bet rather than hedging it.

A possible double count, found while explaining why the file had 0 SD hitters:
F1's implied total already prices the opposing SP, and F4 penalizes the same SP
again. SD vs Yamamoto sat at F4's floor of 0.900 (F4_QUALITY_CLIP,
`projection_builder.py:912`), for x0.823 combined, 17th of 20 teams. This is
unverified and worth a DEV look.

## Proposed for DEV

- **A prior-washout axis in `qa_portfolio.py`.** For each shared prior (stack
  floor, anti-correlation, F1, F4, F5, platoon-sourced sides), report the count
  of entries that depend on it, beside the existing game and team axes.
- **Grade each shared prior against the archive**, conditioned on archetype and
  field size, never pooled. Examples: winners' primary-stack sizes; how often
  winners rostered a hitter facing their own SP (the R288 section already cites
  19,072 of 102,201); stacks facing an ace. These are observed outcomes, not
  probabilities.
- **If the archive supports it, add a sleeve that breaks a STRUCTURAL
  convention**, not only a projection one, so the portfolio is not unanimous on
  any single rule.
