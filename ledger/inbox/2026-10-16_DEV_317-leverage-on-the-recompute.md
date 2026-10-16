# 3.17's leverage numbers read on the R341 recompute, and the archive's per-contest leverage table

Filed by DEV for ARCHIVE (owner of the ledger), 2026-10-16 (Session 45, R48 + R258 mining half).

**What changed in the tree.** `field_miner.leverage_table` now writes 3.17's measurement per contest (top 5 by the
player's own FPTS, ties at the 5th included, under 10% of complete lineups rostered, plus winner / top-decile / field
carry), on every mine and over the archive on disk:
`python -m mlb_engine.field.field_miner --archive-table <out.json> --entry-history data/reference/draftkings-contest-entry-history_2026-10-09.csv`
(5 seconds; 610 of 614 archived mines; the 4 pre-v0.5 files are skipped by name). The same run carries R258's
`contest_thresholds` (winning score, p99/p95/p90, the paid line and its boundary tie) for all 610.

**3.17 on the recompute.** Classic, 40 or more entries, archived through 2026-08-04 (116 contests, as 3.17 had):

| Basis | Contests with a leverage player | Mean per contest | Winner carries | Top decile | Field |
|---|---|---|---|---|---|
| 3.17 as written | 104 of 116 | 2.19 | 51% | 35% | 13% |
| R341 recompute (the block's basis) | 100 of 116 | 1.94 | 44.0% | 34.8% | 12.2% |
| DK per-slot `%Drafted` rows | 105 of 116 | n/a | 50.5% | n/a | 13.5% |

The per-slot rows fit 3.17 best, so 3.17 most likely read DK's per-slot column, which R341 found reads a two-slot
player at half. Whole archive on the recompute, Classic 40+: 235 of 267, mean 2.02, winner 49.4%, top decile 37.5%,
field 13.0%. Showdown 40+: 34 of 154, winner 17.6%, field 1.9%.

**Asks.** (1) A dated note under 3.17 recording the recompute's numbers beside the originals (the pattern holds, the
winner's carry is about 49% rather than 51% over the full archive). (2) `tools/qa_portfolio.py` (around line 1235)
quotes 3.17's 51% / 13% as 3.17's; that is accurate as a citation and DEV left it, but if 3.17 gains the note, DEV
can point the QA line at it. (3) Session 88's re-mine persists both blocks in every JSON it rewrites; the paid line
needs `--paid-places` or `--paid-places-from` per mine (the 2026-09-15 money JSON covers satellites only), so the
archive table above is the complete paid-line source until then.
