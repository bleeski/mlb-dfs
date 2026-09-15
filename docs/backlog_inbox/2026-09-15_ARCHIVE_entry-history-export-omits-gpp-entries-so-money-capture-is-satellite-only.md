# 2026-09-15 ARCHIVE — DK's entry-history export carries only satellites and Best Ball, so R30 money capture reaches none of Ben's GPP entries

Mined the 235-contest 2026-09-14 inbox backlog (slate dates 2026-08-14 to
2026-08-27) with `--my-entry-ids` / `--entry-fee` / `--winnings` /
`--paid-places` sourced per contest from
`data/reference/dk_contest_money_2026-09-15.json`, built from
`data/reference/draftkings-contest-entry-history_2026-09-15.csv` (611 MLB
`Contest_Key`s, 1,057 entry rows, 2026-04-11 to 2026-09-14).

What the export contains, measured:

| | contests | max `Contest_Entries` | names |
|---|---|---|---|
| Satellite | 600 | 500 | every name contains "Satellite" |
| Best Ball | 11 | 500 | "MLB Best Ball $30K Knuckleball" |
| GPP / mini-MAX / Solo Shot / Showdown cash | **0** | n/a | n/a |

What the mine found: 123 of the 235 contests matched a `Contest_Key` and all 123
matched own entries in the standings (field_size from the standings equals the
export's `Contest_Entries` on every one). Of the other 112, **78 still matched
Ben's entries through the `upload_manifest.json` harvest**, so he was in them and
DK scored them, and they are the large-field contests: "MLB $100K Relay Throw
[$25K to 1st]" (7,833 entries, $15 per `outputs/2026-08-19/DKEntries*.csv`),
"MLB $12K mini-MAX [150 Entry Max]" (28,537 entries, $0.50), "MLB Showdown $30
Quarter Jukebox" (142 entries, $0.25). None appears in the export. The obvious
reading is that ticket-funded entries (the satellites' `Winnings_Ticket`) are
invisible to DK's export, which is the same channel
`dfs-results-have-an-invisible-promo-channel` names; whether that is the cause
or the export was filtered at download is **[BEN]**'s to answer.

Consequence for the ledger: `ledger/own_results.json` now carries fee,
paid_places and net for 123 satellites and for zero of the 78 GPP entries on the
same slates. `python tools/net_to_date.py` will therefore read as a satellite
ledger, and the observed net it prints (+$27.05 across today's 123, fees $32.95
against $60.00 of ticket value) says nothing about the GPP side of the book.
Observed outcomes only; not a rate or a claim about skill.

## The ask

1. **A fee fallback the miner already half-supports.** R50 made own_results a
   three-state record (fee and winnings, fee only, neither), so `--entry-fee`
   without `--winnings` is a legal, labelled state. The fee for every one of
   the 78 is on disk: the `Entry Fee` column of the `outputs/<date>/DKEntries*.csv`
   row for that contest id, which `awaiting_standings.scan_entered` already
   parses. Let the miner (or the bulk runner) take `--entry-fee` from that row
   when the entry-history export lacks the contest, and record winnings as
   "not captured" rather than null-and-silent. Fees are half of net and they
   are recoverable today; winnings for those 78 may already be gone.
2. **Say which export a money file came from, in the file.** The 07-29 file
   (`dk_contest_paid_places.json`, 100 contests) and the 09-15 file agree on all
   46 contests they share, so the two can be unioned, but neither states the
   filter DK applied. A `coverage` line ("satellites and Best Ball only, max
   field 500, N contests") in the JSON header would have made this finding a
   read rather than a mine.
3. **Ask DK's export for the GPP rows once.** If a re-download with every
   contest type selected still omits them, the omission is structural and the
   runbook's step 2 ("contest-page trio ... only Ben's own DK page can supply")
   should say the entry history is not that page for ticket-funded entries.

Where the evidence lives: `tools/_scratch_bulk_mine/results3.jsonl` (156
records, one per mine, with the `own results:` line captured) and
`remine_money.jsonl` (46 re-mines of this morning's batch from the archive
path, `--no-archive-move`). Both are gitignored scratch and will be swept.
