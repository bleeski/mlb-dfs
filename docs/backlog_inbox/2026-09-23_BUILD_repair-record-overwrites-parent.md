# A hand repair has no recording door; the obvious call overwrites the parent's record (R369, R272)

Slate 2026-09-23 1905_10g. `tools/repair_entry.py --mode repair --out outputs/<date>/...`
writes a file under `outputs/`, and `preflight_upload.py` then HARD-FAILS it:
"no manifest record ... this file was not produced by a recorded delivery path".
The repair tool records nothing, and the repair clause (R272) requires the
preflight to exit 0.

The BUILD session recorded it by hand through `upload_manifest.record_delivery`,
passing the parent's `run_id`. `record_name` keys the tracked JSON on
`<tag>_<run_id>`, so that call OVERWROTE the committed parent record
(`1905_10g_20260923T221618Z_4a9aebc0.json`) with the repair's row. It was caught
in `git diff` and rewritten from HEAD, and the repair was re-recorded run-less as
`1905_10g_norun_a403548e4860.json`.

Proposed for DEV:
- `repair_entry.py --out` records its own delivery, run-less, with `repair_of`
  naming the parent sha256 and run.
- Or `record_delivery` refuses a `run_id` whose record already exists with
  different bytes.
