# Fragment: the miner's ledger block says "fees not supplied" when fees were supplied

Session: ARCHIVE, 2026-08-03. For: DEV. Small, and it is a truthful-labels wording defect rather
than a math one.

All eight contests in A-029 were mined with `--entry-fee`. The fee landed correctly:
`ledger/own_results.json` carries `entry_fee` and `fees_total` for every one of them
(for example 193033974: `entry_fee 0.1`, `fees_total 0.5`).

The emitted ledger block still reads:

> fees and winnings not supplied, so no net line for this contest

Fees were supplied. Winnings were not, which is why there is no net line. The sentence collapses two
different facts into one and records the false half in the permanent archive, where a later reader
who wants "which contests have a known cost" will read the block and conclude, wrongly, that these
eight do not.

Suggested fix: the block reports what it has. "fee $0.10/entry, $0.50 total; winnings not captured,
so no net line" when only the fee is present, and the current sentence only when neither is. Pairs
with R38, which is the same class of defect one layer down: `net_to_date` drops fee-known,
winnings-unknown contests out of its TOTAL for the same reason.
