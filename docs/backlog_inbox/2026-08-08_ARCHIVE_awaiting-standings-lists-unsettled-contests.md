# awaiting_standings lists contests whose slate has not settled

2026-08-08, ARCHIVE. The scan enrolls a contest the moment its delivered
DKEntries file exists, so today's 1505_3g contests appeared on the pull list
(and in the clickable HTML) at 12:43, before the slate locked. Ben clicked all
four; DK serves a zero-byte export pre-settle, and a zero-byte
`contest-standings-<id>.csv` in the inbox then reads as "pulled" by filename,
which is the exact wrong-direction failure R74(b) exists to prevent. The four
files were quarantined to `_to_delete/` and the contests re-listed. Fix
options: exclude contests whose slate_date >= today (cheapest); or treat a
zero-byte inbox file as not-pulled and say so in the checklist. Contests:
193403851, 193403935, 193405185, 193405226 — re-pull after tonight's settle.
