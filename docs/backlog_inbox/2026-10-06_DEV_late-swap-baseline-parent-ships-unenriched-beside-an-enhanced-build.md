# 2026-10-06 DEV (Session 115, R428): a swap of a baseline-lineage file is labelled unenriched though an enhanced build of the same slate may sit in `runs/`

**Observed.** R428's carry follows the swap's parent run and that run's `parent_run_id` chain. A file delivered from the R389(b) BASELINE lineage was built by `run_baseline`, which passes every enrichment input as None (EP:7695-7701), so its frame measures neutral and, with no `parent_run_id`, the walk ends: `projection frame: UNENRICHED (no run in the parent chain lends an enriched frame for this slate)`. Measured on the 2026-10-05 host from the tracked delivery records: of 51 deliveries for 2026-09/10 that carry a `run_id`, 10 are baseline-lineage at tier `proxy`. The enhanced build the baseline was a safety net for is a SEPARATE run, not an ancestor, so nothing links them, even though R428's slate-identity test (`pool_signature` of the run's salary snapshot against the swap's) could find it exactly.

**Why it is filed and not built.** R428 is deliberately the parent's frame, found through lineage; looking for "any enriched run of this slate" is a different rule (which run, when two enhanced builds disagree, whether the enhanced build was ever delivered) and needs a choice about authority that is Ben's, not an implementation detail. The swap says what it ran on; nothing is silent.

**Candidate item.** When the walk ends unenriched AND the parent is baseline-lineage (its manifest `delivery_lineage` is `baseline`), list the same-slate runs whose frame measures enriched (pool signature equal), newest first, and either carry from the newest PROMOTED one or print the candidates in the label for the session to choose with a flag. Decide the rule first. S.

Nothing here is a lift, an edge, an ROI or a win rate.
