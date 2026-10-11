# DEV to ARCHIVE, 2026-10-11: run `results_ledger.py resolve` after the first ingest, and decide when to switch the standings scan

Session 163 (R497) shipped three things ARCHIVE runs. `data/reference/` is ARCHIVE's write set, so the DEV session wrote only to `tools/_scratch_r497/` and committed nothing there. This adds to `2026-10-11_DEV_results-ledger-first-ingest.md`; run that one first.

What to run, outside a live build window, after the first `ingest`:

```bash
python tools/results_ledger.py resolve
python tools/outcome_review.py --date <date>
```

`resolve` writes `data/reference/dk_entry_resolution.csv` and its `.meta.json`; commit both. What the DEV session saw on this container: 443 recorded entries with a result, every one `no_crosswalk`, across 29 draftgroups (a 30th, 2026-10-10, is past the export's last contest; 37 entries have no result yet). No delivery record before 2026-10-11 carries a player map, and no salary file or DKEntries file for 2026-09-19 to 2026-10-10 is in a cloud container. On a machine where `data/slates/<date>/DKSalaries*.csv` or the delivered `outputs/<date>/DKEntries*.csv` survive with the bytes the record hashed, those entries move to `no_standings` and resolve once the draftgroup's standings are pulled. Until then `outcome_review.py` grades nothing for those dates, by design, and "outcome review due" stays where it is.

The standings scan has a per-draftgroup mode:

```bash
python tools/awaiting_standings.py scan --per-draftgroup
```

It asks for one export per draftgroup, newest first: 30 pulls cover the 159 contests open since 2026-09-19 (field sizes from the results table; 2026-10-10's pick is by contest ID until an export covers it). The per-contest list stays the default until ARCHIVE switches. The trade: after the switch, `outcome_review.py` reads `standings_absent` for the contests not pulled, because it grades a contest only from its own export; the entry-history export still gives every entry's finish.

Also fixed: run as a script, `awaiting_standings.py scan` could not import the engine before reading the delivery records and listed 0 open contests in a cloud container (159 with PYTHONPATH set). A pull list written from a cloud session before 2026-10-11 may have missed every contest that only a delivery record names.

These are observed outcomes and arithmetic on them. None of it is ROI, a win rate, a cash rate or a probability.
