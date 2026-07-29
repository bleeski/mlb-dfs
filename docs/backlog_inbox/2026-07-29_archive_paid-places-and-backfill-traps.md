# Fragment: three miner gaps the money backfill exposed

Session: ARCHIVE, 2026-07-29, satellite conversion audit + money backfill.
For: DEV. One note, three items, ordered by what blocks what.

## 1. The miner cannot write `paid_places`, and that is what gates R10 (P1, S)

`paid_places` has no path into the archive. The miner has no `--paid-places` flag,
`own_results.json` has no field for it, and the only consumer,
`posture_allocator.classify_*`, reads it off a contest dict that nothing in the
archival path populates. `contest_library.record_observation` accepts it but no
CLI reaches it, and its `main()` requires `--entries` (a DKEntries CSV), which a
historical contest does not have.

The values exist and are not in dispute. Ben's DraftKings contest entry history
export carries `Places_Paid` for **all 100** archived contests, and I have parked
them, with `field_size` and observed `breadth`, in
`data/reference/dk_contest_paid_places.json` (ARCHIVE-owned, keyed by
`contest_id`). Nothing needs re-deriving; the flag needs somewhere to read from.

Smallest fix that closes it: `--paid-places` on `field_miner`, written into the
`own_results` record beside `entry_fee`, plus an optional
`--paid-places-from <json>` that reads the parked file by contest_id so a bulk
re-mine does not need 100 command lines. Done when a mined record carries
`paid_places` and `posture_allocator` stops returning UNRESOLVED on an archived
contest.

**Do not treat this as R10 unblocked.** With the values in hand the R10 gate is
now *measurable* rather than unmeasurable, and measured it reads: 76 backfilled
contests fall in 15 distinct (paid_places, field-bucket) archetype cells, and 58
of the 76 sit in one cell (`paid_places == 1`, satellite). Every other cell holds
1 to 3 contests. R10 asks for "roughly eight archetype-conditioned slates"; the
archive supplies one deep cell and fourteen shallow ones. The gate stays shut,
for a better-stated reason. Full numbers in ledger 3.13.

## 2. `--entry-fee` / `--winnings` silently no-op without `--my-entry-ids` (P1, S)

This one cost a full pass before I caught it, and it fails in the worst possible
way: exit 0, no warning, fees on the floor.

Both flags are consumed only inside the own-results stage, and that stage runs
only when own entry IDs resolve. They are harvested from
`outputs/<slate-date>/upload_manifest.json`, which exists for 4 of the 10 slate
dates I backfilled. On the other 6 the mine printed no `own results:` line, exited
0, and left `entry_fee` null. Nothing said so.

Fix: if `--entry-fee` or `--winnings` is supplied and no own entry IDs resolve,
print a warning naming the missing manifest, or exit nonzero. Passing fees for a
contest whose entries cannot be identified is a caller error, not a no-op.
Workaround, now in the runbook and ledger 3.13: always pass `--my-entry-ids`
explicitly on a historical mine. The entry history's `Entry_Key` column **is** the
standings `EntryId`, verified row-for-row, so it is a reliable source.

## 3. `--auto-salary` scans all 170 salary CSVs in the repo (P2, XS)

A mine ran 7-25s; with `--salary-dir data/slates/<slate_date>` the same mine runs
under a second, and the 100%-join check still guards against the wrong slate. All
10 backfilled dates had a local salary dir, so the restriction cost no coverage.
Worth defaulting `--auto-salary` to `data/slates/<slate-date>` then
`data/archive/<slate-date>` before falling back to the repo-wide scan. Pure speed;
no behavior change if the join check stays in front.

## Not done, and it is Ben's call, not mine

The satellite audit produced exactly the curated input R1(c) has been waiting on:
nine recurring satellite/qualifier families Ben demonstrably enters, by name
substring, with the `Places_Paid` values actually observed (for a satellite,
`Places_Paid` is the ticket count awarded). The table is in ledger 3.14.

I did not add them to `data/reference/dk_contest_archetypes.csv`. A curated
`ticket_count` reaches `resolve_contest_shape` immediately, where 1 routes to
`wta_ticket_satellite` and anything else takes the ticket-line blend. That
reranks lineups on contests entered tonight, which makes it a strategy change and
Ben's dated decision, not an archival write. Same reasoning for BUILD's suggested
`Solo Shot` row. What I did land is the pure observed-history half: BUILD's
Solo Shot page facts are recorded in `data/reference/contest_library.json`
(`mlb $1.25k solo shot (early)|1.00`, field 1486, paid 350, breadth 0.2355), which
is trust-order-2 and outranks name inference the next time that exact contest+fee
recurs, without changing any shape mapping.
