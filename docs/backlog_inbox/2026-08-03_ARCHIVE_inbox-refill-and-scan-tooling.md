# Fragment: two standings-inbox tool gaps, both hit this session

Session: ARCHIVE, 2026-08-03. For: DEV.

## 1. `extract_inbox_zips.py` re-extracts already-archived contests, refilling the inbox

The contract says the inbox is a work queue: a successful mine moves the standings CSV out to
`data/archive/<slate_date>/`. The zip does not move, so it stays in the inbox forever, and the next
run of `extract_inbox_zips.py` recreates the CSV the miner just archived.

Measured at this session's start: 91 CSVs in the inbox, 83 of them already mined, 46 byte-identical
to the copy in `data/archive/`. The 8 that actually needed work were invisible in the pile. Finding
them meant scripting a diff of inbox IDs against `data/archive/*/mined_*.json`, which is a thing an
operator should never have to do to answer "what is left to mine".

Suggested fix: extraction skips a zip whose contest is already archived, and a successful mine
relocates the zip the same way it relocates the CSV. This session moved all 158 files by hand (CSVs
to their `data/archive/<date>/`, zips to a new `data/standings/processed_zips/`), so the inbox is
empty and flat right now; without a tool fix it refills on the next extraction.

## 2. The awaiting-standings scan has no tool, and the hand-written version emits dead URLs

`CONTESTS_AWAITING_STANDINGS.md` says "do not hand-maintain this list", and then every session
hand-writes the scan, because there is nothing in `tools/` that runs it. Three sessions have now
written it independently (07-28, 08-02, 08-03).

Writing it a third time surfaced a defect the earlier passes had: accepting any non-empty
`Contest ID` from `outputs/*/DKEntries*.csv` picks up `0` (`Showdown Manual - KC @ DET`, 2026-07-25)
and `900` (`Test WTA`, 2026-06-11), and emits
`https://www.draftkings.com/contest/exportfullstandingscsv/0` as a link for Ben to click. Real DK
contest IDs are 9 digits. Both are now named in the file's do-not-pull section.

Suggested fix: `tools/awaiting_standings.py`, filtering to 9-digit IDs, subtracting
`data/archive/*/mined_*.json`, the inbox, the synthetic `199000001`, and the recorded unrecoverable
set, and writing both the markdown and the clickable HTML checklist. It emits DK URLs from contest
IDs already in Ben's files, which is explicitly allowed; it never fetches DK.
