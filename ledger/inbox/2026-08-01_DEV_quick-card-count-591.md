# Fragment: Quick Card macro count is two generations stale; current pin is 591

Session: DEV, 2026-08-01 (critique adjudication). For: ARCHIVE.

Quick Card #1 still says `PASS  v2.26.0  25 modules  546 tests` with paste at
29. The audit pin as of 48b4e7e is 591: core 377 + showdown 49 + upload 100 +
golden 9 + paste 56. The suite-by-suite fallback list is right; only the
counts moved.

This supersedes the count half of
`2026-07-31_DEV_paste-placeholder-quick-card.md` (589; core was 375 when it
was written) and the pin number in `2026-07-30_dev_audit-pin-556.md`. The
placeholder-invariant proposal in the 07-31 fragment is untouched and still
worth merging.

If this goes stale again, the source of truth is `EXPECTED_TEST_COUNT` in
`tools/audit.py`.
