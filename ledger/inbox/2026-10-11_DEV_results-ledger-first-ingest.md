# DEV to ARCHIVE, 2026-10-11: run the first `results_ledger.py ingest` and commit its two files

Session 162 (R496) shipped `tools/results_ledger.py`. It reads the DraftKings contest entry-history exports committed under `data/reference/` and writes `data/reference/dk_entry_results.csv` with a `.meta.json` sidecar. `data/reference/` is ARCHIVE's write set, so the DEV session verified against a scratch copy and committed neither file.

What to run, outside a live build window:

```bash
python tools/results_ledger.py ingest
python tools/results_ledger.py report --sport MLB
```

What the DEV session saw on the same two exports (`draftkings-contest-entry-history_2026-09-15.csv`, 1,403 rows, sha256 `84ce7a81…`; `..._2026-10-09.csv`, 10,095 rows, sha256 `5752c7f3…`). A different result means the archive or the delivery records changed in between, not that the tool drifted.
- 10,095 entries out, 1,403 identical rows merged, 0 disagreeing. CSV sha256 `0d8f731b62d0f824…`, sidecar `a0e2b2dbf3d051a3…`.
- MLB, paid entries outside Best Ball: 7,598 entries in 242 slates. Fees $1,249.05, net -$270.36. Finish percentile 52.05 [51.1, 53.1]. Blank classes 90 `blank_no_lineup`, 3 `zero_unknown`, 1 `zero_complete`.

Run `ingest` again whenever a new export lands or the archive gains standings for a contest that holds a zero-point entry. The procedure is in `docs/cowork_archival_runbook.md`, under "Read every entry's finish from the entry-history export (R496)".

These are observed outcomes. None of them is ROI, a win rate, a cash rate or a probability.
