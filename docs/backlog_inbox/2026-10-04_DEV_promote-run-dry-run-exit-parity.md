# 2026-10-04 DEV (Session 142, R473): `promote_run --dry-run` promises exit-code parity and breaks it under R430

**Observed.** `tools/promote_run.py` documents that a dry run reports what the real run would do, exit code included (the comment at the `--dry-run` return, after `plan` is printed: "A dry run reports what the real run would do, exit code included"), and it returns `4 if unbound else 0`. R430 (Session 128) added a refusal inside `record_delivery`, after `deliver` has already staged the file: a record whose run already holds other bytes under the same slate tag is refused. The dry run never reaches it. Reproduced offline at c2979af (the `dfs-premise` agent's scratch `part_a.py`, case A2, re-run by the Session 142 DEV): a tracked record for the run holding a variant's bytes under the run's own slate tag, `--dry-run` exits 0 with the plan, the real promotion exits 2 with `MANIFEST NOT RECORDED: refusing to record run_id ... (R430)` and leaves an orphan `DO_NOT_UPLOAD_...` provisional, rows unchanged.

**Why it is filed and not fixed in Session 142.** The R473 fix changes which row and record a re-promotion reads; it does not touch the dry run's reach. The refusal is `record_delivery`'s, and a dry run that mirrored it would have to call `recorded_sha_for_run(date, tag, run_id)` itself and compare against the run's sha256, which is a second copy of R430's test.

**Candidate item.** In the `--dry-run` branch, read `delivery_record.recorded_sha_for_run(date, tag, run_id)` and, when it is non-empty and differs from `actual_sha`, return 2 with the refusal's wording, so the dry run and the real run agree. Test: the A2 shape through `_promote("--dry-run")` and `_promote()`. Effort XS; no engine surface.

Nothing here is a lift, an edge, an ROI or a win rate.
