# `ownership_grade_archive.salary_candidates` never reaches `runs/`: its glob is dashed and run folders are not

Filed 2026-10-04 by DEV (Session 43, R342(b1)). XS; found while making the saved-prediction grade resolve four 2026-08-19 contests.

**What is wrong (reproduced at 5487553, `tools/_scratch_r342b/glob_defect.py`).** `salary_candidates(slate_date)` (`tools/ownership_grade_archive.py`, the second pattern) globs `runs/*{slate_date}*/inputs/DKSalaries*.csv` with `slate_date = "2026-08-19"`. Run folders are named `<YYYYMMDD>T<HHMMSS>Z_<hash>` (28 on benbook for 2026-08-19 carry a salary file), so the dashed pattern matches 0 of them, and the function returns only the `data/slates/<date>/` and `outputs/<date>/` files (8 for that date). A slate whose `data/slates/<date>/DKSalaries.csv` was overwritten by the next draft group (the 3-game 2005_3g slate of 2026-08-19 survives only in `runs/20260819T225247Z_ee45d0cf/inputs/`) therefore resolves no salary file, and `grade_one` refuses it as "no salary file resolved ... 33% team coverage".

**What it touches.** Only the archive grade's default path (`grade_one`, the R306 loop). The new `--saved` path (R342(b1)) does not depend on it: it looks the salary file up by the saved prediction's recorded sha256 (`recorded_salary_files`). `field_miner.default_salary_candidates` globs `runs/*/inputs/...` with no date and is unaffected.

**Fix.** Glob `runs/*{slate_date.replace('-', '')}*/inputs/DKSalaries*.csv` as well, or key on content as the saved path does. Check the effect on a re-run of the default grade first: more candidates can turn a refusal into a grade and a tie into an "ambiguous" refusal (`resolve_salary_file`'s margin rule), so the 379-contest pass is the measurement, not a unit test alone.
