# Fragment: two salary-resolution gaps the 2026-08-04 mine worked around by hand

Session: ARCHIVE, 2026-08-04. For: DEV. Both surfaced mining A-030..A-034 (94 contests).

1. **The runbook's salary recovery path is wrong for engine-delivered files.** The archival runbook
   and field_miner's docstring say a retained DKEntries upload "embeds the full salary block" and
   restores coverage for a past slate. That is true only of DK's downloaded template. The engine's
   own delivered `DKEntries_*.csv` carries no Name/Salary columns, and `load_salary_map` raises on
   it. 31 contests hit this before the session switched to `runs/<run_id>/inputs/DKSalaries.csv`.

2. **The miner could resolve salary from the manifest and skip the ambiguity class entirely.** It
   already reads `outputs/<date>/upload_manifest.json` to harvest own entry IDs; each delivery also
   names its `run_id`, and `runs/<run_id>/inputs/DKSalaries.csv` is the authoritative salary file
   for every contest in that delivery. On 2026-08-04 the in-date `--auto-salary` failed for three
   whole slates whose salary files were never staged into `data/slates/` (1210_4g, 2140_3g, 2010_2g,
   1905_7g — every candidate joined 0%), and declined on 2026-07-28 where a 9-game slate's players
   sit inside the 10-game file (three same-family candidates at 100% join). A manifest-first
   resolution order (run inputs -> in-date auto -> repo-wide) would have mined all 94 with zero
   manual steps. Pairs with the stage_slate question of whether run inputs should be mirrored into
   `data/slates/<date>/` under their tag.
