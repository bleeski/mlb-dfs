# 2026-10-05 DEV (Session 141, R472): the review-grade reason for a downgrade names only `--accept-downgrade`

**Observed.** `tools/preflight_upload.py` `REVIEW_GRADE_REASONS["review_grade_downgrade_accepted"]` reads "A late swap took entries that score below the lineups they replaced (--accept-downgrade), so it ships review-grade (R386)." Since R472 a swap can also ship under that label with NO flag: `late_swap.py --standings` exempts a `live_for_target` entry from the downgrade refusal, the entry stays in `downgraded`, and `swap_certification` still returns `review_grade_downgrade_accepted`. The delivery record then carries `relaxations: {"downgrades_accepted": 0, "downgrades_exempted_by_standings": N}`.

**Why it is filed and not fixed in Session 141.** The label is deliberately unchanged (the file IS review-grade, R386) and the printed line, the record and the run metadata already say it was exempted, not accepted. The reason sentence is true of the file and silent on why; editing it touches `preflight_upload.py` and its pinned documentation test, which the R472 write set does not otherwise reach.

**Candidate item.** Make the reason sentence say "(--accept-downgrade, or a standings exemption recorded in the swap run's `metadata.standings`)", and have the verdict note read `relaxations.downgrades_exempted_by_standings` from the tracked record to pick the sentence. XS; `PreflightContractDocumentation` pins the wording.

Nothing here is a lift, an edge, an ROI or a win rate.
