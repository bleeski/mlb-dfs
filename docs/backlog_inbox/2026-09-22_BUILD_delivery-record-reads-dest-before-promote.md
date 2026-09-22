# The tracked delivery record (R369) reads its rosters before the file exists

Filed by a BUILD session on 2026-09-22 1915_1g_sd (CIN @ ATL Showdown, 6
entries). Found by comparing `data/deliveries/2026-09-22/1915_1g_sd_norun.json`
against the delivered CSV after a rebuild.

## What happens

`run_showdown` in `skills/generate-lineups/scripts/build_slate.py` writes the
CSV to its provisional `DO_NOT_UPLOAD_` name, calls `record_delivery(...,
delivered_file=dest, hash_source=provisional)`, and only THEN runs
`os.replace(provisional, dest)`. The manifest row's sha256 comes from
`hash_source` and is correct. But `record_delivery` mirrors into
`delivery_record.write_delivery_record`, which fills `entries` from
`entry_rows(<root>/manifest_row["delivered_file"])`, which is `dest`. At that
moment `dest` is either absent (first build of the slate) or the PREVIOUS build's
file (a rebuild).

So the record's `entries[]` is empty on a first build and one build stale on a
rebuild, while its `manifest_row.sha256` names the new file. The two halves of
one record disagree and nothing checks them against each other.

## Evidence

- This slate: v1 built 16:22:58 ET, v2 16:24:47 ET. The record written at
  20:24:48Z carried `manifest_row.sha256 = 98c3f26b...` (v2) and v1's rosters in
  all six `entries` (entry 5266549168 CPT 44234384 JR Ritchie; the delivered v2
  file has CPT 44234397 Austin Riley). Rewritten by hand from the delivered file
  in the same commit as this fragment, with the reason under `extra`.
- Every tracked record, counted 2026-09-22:
  `data/deliveries/2026-09-19/2110_2g_...e40c1f01.json` classic 0 entries;
  `2026-09-19/2138_1g_sd_norun.json` showdown 0; `2026-09-20/1607_4g_...072d85b2.json`
  classic 0; `2026-09-20/1607_4g_...1a1f5c58.json` classic 5 (the one that has
  them). 3 of 4 pre-existing delivery records carry no rosters, so the Classic
  path has the same ordering problem or a sibling of it; not traced here.

## Why it matters

R369's stated purpose is that `outputs/` dies with a cloud container, so the
tracked record is the only way a cloud build is ever joined to its standings.
A record with no rosters cannot be joined; a record with stale rosters joins
the WRONG lineups to the standings and grades them.

## Suggested fix (DEV's call)

Read `entries` from `hash_source` when it is supplied (thread it through
`record_delivery` -> `_mirror_delivery_record` -> `write_delivery_record`), or
write the record after the promote. Then add a test that a rebuild's record
rosters equal the delivered file's, and a check that `manifest_row.sha256`
equals the sha256 of whatever `entries` was read from. The three existing
empty records above are ARCHIVE's to backfill if the files still exist
anywhere; on a reclaimed container they do not.
