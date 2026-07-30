# Fragment: net_to_date TOTAL row uses a different denominator than the date rows

Session: ARCHIVE, 2026-07-30. For: DEV.

`python tools/net_to_date.py` now prints a table whose date column does not sum
to its own TOTAL:

    date rows sum to   $64.21 in fees
    TOTAL row prints   $51.46 in fees

Cause, in `tools/net_to_date.py`:

- line 109-110, per-date rows: `sum(... for r in rows)`, every row for that date
- line 86-87, TOTAL row: `sum(... for r in graded)`, where `graded` requires
  both a fee and winnings to be present

The 37 contests mined on 2026-07-30 (A-027, A-028) carry an entry fee harvested
from the delivered DKEntries `Entry Fee` column but a null winnings, because the
contest-page trio was not captured. They therefore appear in the date rows and
vanish from the TOTAL.

The date rows are the correct ones. A contest with a known fee and unknown
winnings has a known cost.

Suggested fix: compute the TOTAL from the same set as the date rows, and print
the incomplete-money count as a separate note rather than by silently changing
the denominator. The existing footer already says how many contests carry no
fee/winnings; that sentence is now also wrong, since it reports 37 contests with
"no fee/winnings" when all 134 rows in `ledger/own_results.json` carry a fee.

Not urgent and not a labelling problem. The output is still an observed outcome,
it just does not add up.
