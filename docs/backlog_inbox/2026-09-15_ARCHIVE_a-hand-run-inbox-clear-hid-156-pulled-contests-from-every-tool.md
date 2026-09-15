# 2026-09-15 ARCHIVE — a copy-paste "clear the inbox" block moved 156 pulled-not-mined exports where no tool looks, and the checklist grew by 156

`data/standings/processed/2026-09-14/` (308 files) and
`processed/2026-09-14_empty/` (13 zero-byte files) appeared on 2026-09-15. No
tool writes a path called `processed/`: `grep -rn "standings/processed" tools/
skills/ docs/ mlb_engine/` returns only the `processed_zips/` convention. The
writer was `outputs/standings_research_2026-09-14_secondpass/clear_inbox.ps1`,
a PowerShell block the 2026-09-14 second-pass research session handed back
because its device shell could not mount the folder and it could not take the
ARCHIVE claim. That session analysed the 235 exports in the container and never
wrote a `mined_<id>.json`, a fragment, a registry line or an archive move, so
"processed" meant "read by a research pass", not "archived". Someone ran the
block at 15:50Z on 2026-09-15, mid-way through the morning ARCHIVE mine, and
swept the 156 CSVs that mine had not yet reached out of the inbox.

`tools/awaiting_standings.py` computes "pulled" as `data/archive/*/mined_*.json`
∪ `data/standings/inbox/*` and nothing else, so the 156 contests reverted to
open: the checklist read 333 on the morning scan and 489 after the move, with
zero new entries behind the jump.

Resolution this session (claims held): the 156 CSVs went back to
`data/standings/inbox/` and were mined (156/156, 0 blocked, 0 errors, coverage
full on all); the 13 zero-byte pulls went to `data/standings/failed_pulls/`
(R95: an empty file is a failed pull, and they are correctly the 13 oldest
rows on the regenerated list); the 152 zips stay in `processed/2026-09-14/`
because a live session's `source_relocation_verification.json` cites those
paths byte-for-byte. Checklist is back to 333 across 19 dates.

## The ask

1. **The runbook and the pull checklist should say where a pulled file may
   go.** Two destinations exist today: `data/archive/<date>/`, reached only by
   the miner's own archive move, and `data/standings/failed_pulls/` for
   zero-byte pulls. A hand-move to anywhere else makes a pulled contest read as
   unpulled, and the checklist then asks Ben to click an export DK may have
   aged out. One sentence in `docs/cowork_archival_runbook.md` Job 1 and in
   `skills/mlb-standings-pull-checklist/SKILL.md`, and a rule that a no-shell
   session never hands back a block that moves inbox files.
2. **`awaiting_standings.py` could name the leak instead of counting it.**
   A `contest-standings-<id>.csv` found anywhere under `data/standings/` other
   than `inbox/` or `failed_pulls/` is a pulled export in the wrong place; list
   it under its own heading rather than re-opening the contest. Cheap: it is
   the same filename regex the inbox scan already uses.
3. **R44's zip residue has a third home now.** `processed_zips/` holds 187
   hand-moved zips, `processed/2026-09-14/` holds 152 more, and
   `extract_inbox_zips.py` still moves none. When the live research session
   is done with its byte check, the 152 belong in `processed_zips/` with the
   rest, and the R44 fix (move to `processed_zips/`, skip ids with a mine)
   would end the class.
