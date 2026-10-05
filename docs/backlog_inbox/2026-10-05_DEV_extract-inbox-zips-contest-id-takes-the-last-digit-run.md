# 2026-10-05 DEV (Session 141, R472): `extract_inbox_zips.infer_contest_id` returns the last digit run, so a browser's duplicate suffix wins

**Observed.** `tools/extract_inbox_zips.py` `infer_contest_id` takes the LAST digit run of a file name ("DK names exports like contest-standings-<id>.zip/.csv; take the last digit run"). A browser that saves a second copy of the same download names it `contest-standings-195970831 (1).zip`, and the last digit run is `1`. R472's `tools/standings_read.infer_contest_id` prefers the last run of six or more digits (a DK contest id is nine) and falls back to the last run of any length, and `late_swap --standings` additionally takes the contest from entry membership when the name's id matches no contest of ours. `extract_inbox_zips` and its callers (`outcome_review.standings_candidates` matches by `contest-standings-<id>.csv` globs, which is unaffected) were not changed.

**Why it is filed and not fixed in Session 141.** `extract_inbox_zips.py` is ARCHIVE's inbox tool and outside R472's write set; two readers of one rule is the R233 class, so the candidate item below makes one definition.

**Candidate item.** Make `extract_inbox_zips.infer_contest_id` and `standings_read.infer_contest_id` one function (the six-digit-run rule), pinned by a test with a `(1)`-suffixed name. Check first that no existing inbox file relies on a short id (`ls data/standings/inbox` was empty on 2026-10-05; the archived names are all nine-digit). XS.

Nothing here is a lift, an edge, an ROI or a win rate.
