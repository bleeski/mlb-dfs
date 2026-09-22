# No contest type separates in the archived record (2026-09-16)

Scope: 575 of 584 contests in `ledger/own_results.json` joined to contest names and
format (Classic/Showdown) from 852 `outputs/**/DKEntries*.csv` files plus
`data/reference/dk_contest_money_2026-09-15.json`. 1,435 matched entries, 39 slate
dates, 2026-06-03 to 2026-08-27. 9 contests unjoinable (no name source).

Observed outcomes only. No ROI, win-rate, or probability claim is made or implied.

## Method
Primary comparator is per-contest `median_finish_percentile`, entry-weighted, whose
null expectation is 50 regardless of entry count. `best_finish_percentile` is NOT
comparable across segments because it rises mechanically with entry count. 95% CIs
are bootstrapped by resampling SLATE DATE, because lineups repeat across contests
within a slate: effective n is ~39, not 575.

## Result
Every segment's CI contains 50.

| segment | contests | entries | medP | 95% CI |
|---|---|---|---|---|
| ALL | 575 | 1435 | 47.6 | 44.7 - 50.8 |
| Classic | 337 | 714 | 48.8 | 45.2 - 52.6 |
| Showdown | 238 | 721 | 46.5 | 41.7 - 51.2 |
| Satellite (all) | 461 | 1284 | 47.6 | 44.5 - 51.0 |
| Non-satellite | 114 | 151 | 48.0 | 41.6 - 53.2 |
| field <150 | 369 | 575 | 49.1 | 45.1 - 52.9 |
| field 150-999 | 145 | 772 | 46.4 | 42.4 - 50.3 |
| field 1000+ | 61 | 88 | 49.3 | 40.8 - 55.7 |

Classic vs Showdown paired within slate (26 slates carrying both): mean difference
-0.5 percentile, CI -7.9 to +6.5, Classic higher on 15 of 26.

Top end, contests with at least one entry inside top q vs the null given entry count:
top 1% 16 vs 14.1, top 5% 59 vs 65.3, top 10% 112 vs 119.9, top 20% 195 vs 206.2.

In-money, the 123 contests with `paid_places` known (median breadth 0.0435):
6 entries inside the paid places vs 5.0 expected under the null. Classic satellites
3 vs 2.57, Showdown satellites 3 vs 2.46.

## The two segments to keep watching
Daily Dollar (SE), 18 contests over 12 slates, medP 35.5 (CI 24.4 - 46.2), and
mini-MAX GPP, 19 contests, medP 39.4 (CI 29.1 - 51.1) with 0 of 19 entries reaching
top 20% in fields of 5,044 to 47,562. Both are one entry into a large field. But Solo
Shot is also one entry into fields of 118 to 5,945 and sits at 51.8, so the shared
trait is not the explanation. 37 contests, one CI excluding 50 out of ~16 segments
tested. Treat as noise until the count doubles.

## Why the question is only half answerable
211 of 575 contests carry money, and 196 of those 211 are Satellite or
SUPERSatellite. Net $9.45 is a satellite-only ledger, not a read on contest type.
The fee fallback for the 78 GPP contests
(`docs/backlog_inbox/2026-09-15_ARCHIVE_entry-history-export-omits-gpp-entries-...md`)
is what would make a money-side comparison possible.

Entry concentration is the other limit: 1,435 entries spread over 72 distinct contest
names, 83% of them satellites. Non-satellite is 114 contests and 151 entries total.

Repro: `tools/_scratch_contesttype/` (gitignored) holds `build_map.py`,
`analyze.py`, `stats.py`, `topend.py`, seeded 0 and 1.
