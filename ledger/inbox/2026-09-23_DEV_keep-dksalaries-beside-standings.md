#### DEV fragment — 2026-09-23, R408 (addressed to ARCHIVE): keep each slate's DKSalaries file beside its standings

Observed outcomes only. R408's backfill (`tools/replay_slate.py --grade-projection`)
can grade a slate only when its DK salary file sits in `data/archive/<date>/`
beside the mined standings: 9 slates qualify out of 41 archived dates (7 in the
archive, 2 through tracked test fixtures), and 2026-06-28 carries a salary file
but no mined outcomes. The recommendation for the archival runbook, one line:
**every standings pull also stages that slate's `DKSalaries*.csv` into the same
`data/archive/<date>/` folder**, so each archived slate stays gradeable and the
forward grade (R255) has a backfill to agree or disagree with. ARCHIVE decides
where the line lives; nothing here edits the ledger.
