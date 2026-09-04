# Showdown captain and roster market grade | 41 archived contest(s)

Filed 2026-09-03 by DEV (R306 steps 2-3), from `tools/ownership_grade_archive.py`. ARCHIVE merges into the calibration ledger.

Two distributions over the same collapsed people, each against its own realized shares, per contest and never pooled. `captain` is the 100% one-slot market counted off `entries[].captain_norm`; `roster` is the 600% six-slot market counted off `entries[].players_norm`. Both include the ZERO TAIL: on a Showdown slate the salary file is the contest's player pool, so a player nobody captained has an observed share of 0.0, and dropping those truncates the sample at the end the prior is most likely to get wrong. Each Spearman is a rank correlation between two measured shares over one contest. Nothing here is a win rate, a cash rate, an ROI figure, an edge, or a probability claim.

**The signed error column is near zero BY CONSTRUCTION here, and it is not evidence the level is right.** Both the prior and the realized shares allocate the same budget (100% or 600%) over the same zero-filled pool, so their means are equal and the mean signed error is an accounting identity rather than a measurement. It is printed because its ABSENCE would mean a player left the pool between the softmax and the join. Read MAE and the Spearman instead; and note that the Classic figures in the sibling fragments do NOT have this property, because that join drops players DK listed without a share.

**Self-inclusion caveat, carried forward.** Ben's own entries sit in these denominators, most heavily in the smallest fields.

| contest | date | field | archetype | cpt rho | cpt signed | cpt MAE | roster rho | roster signed | distinct cpts | zero-cpt |
|---|---|---|---|---|---|---|---|---|---|---|
| `193565124` | 2026-08-11 | 21 | wta_satellite | 0.515 | -0.0 | 1.06 | 0.618 | 0.0 | 9 | 73 |
| `193565122` | 2026-08-11 | 22 | wta_satellite | 0.303 | -0.0 | 1.14 | 0.629 | 0.0 | 7 | 75 |
| `193662821` | 2026-08-13 | 22 | wta_satellite | 0.44 | -0.0 | 0.67 | 0.585 | -0.0 | 8 | 76 |
| `193662822` | 2026-08-13 | 22 | wta_satellite | 0.417 | -0.0 | 1.03 | 0.531 | -0.0 | 9 | 75 |
| `193662823` | 2026-08-13 | 22 | wta_satellite | 0.328 | -0.0 | 0.76 | 0.512 | -0.0 | 6 | 78 |
| `193404259` | 2026-08-08 | 23 | wta_satellite | 0.395 | -0.0 | 0.89 | 0.62 | -0.0 | 6 | 92 |
| `193404260` | 2026-08-08 | 23 | wta_satellite | 0.52 | -0.0 | 0.42 | 0.621 | -0.0 | 10 | 88 |
| `193404261` | 2026-08-08 | 23 | wta_satellite | 0.43 | -0.0 | 0.73 | 0.622 | -0.0 | 7 | 91 |
| `193513999` | 2026-08-09 | 23 | wta_satellite | 0.614 | -0.0 | 0.75 | 0.701 | 0.0 | 12 | 74 |
| `193514633` | 2026-08-09 | 23 | wta_satellite | 0.456 | -0.0 | 1.15 | 0.664 | 0.0 | 9 | 77 |
| `193516017` | 2026-08-09 | 23 | wta_satellite | 0.493 | -0.0 | 1.02 | 0.571 | 0.0 | 10 | 76 |
| `193565126` | 2026-08-11 | 23 | wta_satellite | 0.423 | -0.0 | 1.02 | 0.578 | 0.0 | 6 | 76 |
| `193619827` | 2026-08-12 | 23 | wta_satellite | 0.474 | 0.0 | 0.39 | 0.664 | 0.0 | 8 | 84 |
| `193619828` | 2026-08-12 | 23 | wta_satellite | 0.45 | 0.0 | 0.88 | 0.657 | 0.0 | 8 | 84 |
| `193619829` | 2026-08-12 | 23 | wta_satellite | 0.547 | 0.0 | 0.46 | 0.618 | 0.0 | 11 | 81 |
| `193619919` | 2026-08-12 | 23 | wta_satellite | 0.467 | 0.0 | 0.73 | 0.568 | -0.0 | 8 | 94 |
| `193619920` | 2026-08-12 | 23 | wta_satellite | 0.419 | 0.0 | 0.59 | 0.568 | -0.0 | 8 | 94 |
| `193619921` | 2026-08-12 | 23 | wta_satellite | 0.446 | 0.0 | 0.6 | 0.56 | -0.0 | 9 | 93 |
| `193619830` | 2026-08-12 | 37 | wta_satellite | 0.436 | 0.0 | 0.8 | 0.655 | 0.0 | 7 | 85 |
| `193662824` | 2026-08-13 | 38 | wta_satellite | 0.507 | -0.0 | 0.77 | 0.555 | -0.0 | 11 | 73 |
| `193404262` | 2026-08-08 | 39 | wta_satellite | 0.58 | -0.0 | 0.76 | 0.639 | -0.0 | 12 | 86 |
| `193565127` | 2026-08-11 | 41 | wta_satellite | 0.526 | -0.0 | 0.89 | 0.632 | 0.0 | 10 | 72 |
| `193446432` | 2026-08-09 | 59 | wta_satellite | 0.677 | -0.0 | 0.88 | 0.681 | 0.0 | 17 | 69 |
| `193446436` | 2026-08-09 | 118 | wta_satellite | 0.718 | -0.0 | 0.86 | 0.626 | 0.0 | 19 | 67 |
| `193619823` | 2026-08-12 | 122 | wta_satellite | 0.585 | 0.0 | 0.54 | 0.65 | 0.0 | 17 | 75 |
| `193662817` | 2026-08-13 | 139 | wta_satellite | 0.59 | -0.0 | 0.65 | 0.557 | -0.0 | 18 | 66 |
| `193404256` | 2026-08-08 | 164 | wta_satellite | 0.611 | -0.0 | 0.55 | 0.653 | -0.0 | 17 | 81 |
| `193619824` | 2026-08-12 | 166 | wta_satellite | 0.612 | 0.0 | 0.46 | 0.658 | 0.0 | 17 | 75 |
| `193662818` | 2026-08-13 | 166 | wta_satellite | 0.62 | -0.0 | 0.62 | 0.666 | -0.0 | 16 | 68 |
| `193565115` | 2026-08-11 | 169 | wta_satellite | 0.612 | -0.0 | 0.77 | 0.613 | 0.0 | 18 | 64 |
| `193404255` | 2026-08-08 | 171 | wta_satellite | 0.617 | -0.0 | 0.58 | 0.64 | -0.0 | 17 | 81 |
| `193613968` | 2026-08-11 | 178 | single_entry_gpp | 0.597 | -0.0 | 0.65 | 0.552 | -0.0 | 17 | 65 |
| `193705554` | 2026-08-13 | 206 | single_entry_gpp | 0.628 | -0.0 | 0.66 | 0.535 | -0.0 | 16 | 68 |
| `193565117` | 2026-08-11 | 222 | wta_satellite | 0.64 | -0.0 | 0.73 | 0.697 | 0.0 | 19 | 63 |
| `193514634` | 2026-08-09 | 237 | wta_satellite | 0.719 | -0.0 | 0.73 | 0.605 | 0.0 | 19 | 67 |
| `193514876` | 2026-08-09 | 237 | wta_satellite | 0.694 | -0.0 | 0.88 | 0.576 | 0.0 | 21 | 65 |
| `193515111` | 2026-08-09 | 237 | wta_satellite | 0.698 | -0.0 | 0.83 | 0.602 | 0.0 | 21 | 65 |
| `193619915` | 2026-08-12 | 237 | wta_satellite | 0.537 | 0.0 | 0.43 | 0.603 | -0.0 | 19 | 83 |
| `193619916` | 2026-08-12 | 237 | wta_satellite | 0.558 | 0.0 | 0.4 | 0.59 | -0.0 | 19 | 83 |
| `193678271` | 2026-08-12 | 594 | single_entry_gpp | 0.592 | -0.0 | 0.53 | 0.567 | -0.0 | 21 | 81 |
| `193621098` | 2026-08-12 | 1189 | single_entry_gpp | 0.691 | -0.0 | 0.47 | 0.616 | 0.0 | 19 | 73 |

- `f_0001_0100` (23 contests): median per-contest captain Spearman **0.456**, median captain signed error **-0.0** pts; median roster Spearman 0.62, median roster signed error 0.0 pts.
- `f_0101_0500` (16 contests): median per-contest captain Spearman **0.615**, median captain signed error **-0.0** pts; median roster Spearman 0.609, median roster signed error 0.0 pts.
- `f_0501_2000` (2 contests): median per-contest captain Spearman **0.641**, median captain signed error **-0.0** pts; median roster Spearman 0.591, median roster signed error 0.0 pts.

Medians are medians OF PER-CONTEST STATISTICS inside one field band, never a statistic recomputed over a merged player set.

