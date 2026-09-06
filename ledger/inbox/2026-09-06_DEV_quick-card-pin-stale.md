# DEV 2026-09-06 — Quick Card item 1's audit pin is three moves stale: `27 modules 1386 tests` against a tree pinned at `28 modules 1810 tests`

ARCHIVE's to merge; `ledger/` is a one-writer surface and this is DEV filing
rather than editing.

## The disagreement

`ledger/MLB_Classic_Calibration_Ledger.md` item 1 of the Quick Card reads:

    python tools/audit.py --run-tests --terse  ->  PASS  v2.26.0  27 modules  1386 tests

The tree at `c6dd17c` pins:

    PASS  v2.26.0  28 modules  1810 tests

Read off `tools/audit.py` this date, `EXPECTED_TEST_COUNT` = 1810 from
`EXPECTED_SUITE_COUNTS` = test_core 1154 / test_showdown 201 /
test_upload_integrity 348 / test_golden_replay 9 / test_paste_lineups 98.
`CLAUDE.md:427` carries the same line and is current. The Quick Card's own rule
is that when the line and the dict disagree, **the dict wins and the line is
stale**, so this is the documented condition rather than a new one.

The pin line was last corrected 2026-08-28. Between then and now it moved
1386 -> 1592 -> 1610 -> 1645 -> 1659 -> 1675 -> 1703 -> 1723 -> 1755 -> 1768 ->
1796 -> 1810, and the module count 27 -> 28 (R290(c) commit 2). The gate
transitions are recorded per item in `CHANGELOG.md` and `docs/backlog.md`, so
the merge needs no re-derivation.

## Two notes for whoever merges it

1. **The line also carries a network claim that R316 retired today.** Inside the
   2026-08-17 R147 correction: "a cloud Cowork session's DEVICE VM cannot reach
   GitHub at all (its proxy 403s CONNECT even for a public repo)". Measured on
   the device VM 2026-09-06: the audit fetched (`fetched: true`,
   `fetch_age_hours: 0.0`, `default_branch_source: remote`), `sync_check.py`
   read GitHub directly with the `GH_PAT`, and `curl` returned 200 from
   api.github.com, statsapi.mlb.com, baseballsavant.mlb.com, fangraphs.com and
   pypi.org. R147's *classification* stands and is the reason the check is
   cheap; the *reading* does not. `CHANGELOG.md`'s R316 entry has the full
   measurement, and the three live documents that carried the same claim are
   corrected there. This line should say the reading was true when taken and is
   a measurement, not a property.
2. **The R236 clause is the same class.** "`api.the-odds-api.com` is proxy-gated
   in cloud sessions exactly as `statsapi.mlb.com` is" — 200 with the repo key
   on this VM today. The *instruction* it carries survives untouched and is the
   part worth keeping: read `counts.f1_games_priced` directly on any archived
   cloud-session build rather than trusting `enrichment.signal_applied`.
