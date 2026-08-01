# Fragment: 2026-08-01 mined-data review — items for ARCHIVE

Session: unassigned read-only review, 2026-08-01. Full working in
`outputs/2026-08-01/mined_data_review_2026-08-01.md`. Observed outcomes and
deterministic statistics only; nothing here is ROI, a win rate, or a
probability claim.

1. **~74 contests from 07-29 and 07-30 are delivered but unarchived.**
   `CONTESTS_AWAITING_STANDINGS.md` ("nothing is open", 07-28) is stale;
   regenerate it. Full export-URL list is in the review's appendix for Ben's
   manual pulls. One ID there is a placeholder, flagged inline (199000001,
   Relay Throw, synthetic entry ID 9900000001).
2. **`paid_places` coverage ends at the 07-28 entry-history export.** The
   07-29 mined contests carry no paid line. A fresh export extends it and,
   over time, resolves the $175 held ticket inventory (3.14).
3. **Contest 192464820 is mined into both 2026-07-18 and 2026-07-19 archive
   folders.** Dedupe on contest_id when aggregating; the miner's idempotency
   is per-folder and Late Night contests straddle dates. The 7/30 field-shape
   analysis's "138 contests" counted it twice (moved no conclusion; field 31,
   under every threshold). Deduped money cross-foot reconciles to 3.13
   exactly: 97 contests, −$21.46.
4. **Quick Card item 1 still pins 546 tests.** Current true count 591 (moved by this same session: changelog_debt widening added tests)
   (audit PASS v2.26.0, 25 modules, verified suite-by-suite this session);
   the 556→583 fragment in this inbox is itself one hop stale.
5. **Candidate ledger lines from the review** (ARCHIVE to grade and place;
   statuses suggested per the section 2 vocabulary):
   - Win-line concentration: 5-2-1 + 5-1-1-1 take 46.6% of the 58 Classic
     contest wins on 31.6% field share; holds in the 34 Classic one-seat-sat
     winner subset (13 of 34). Provisional.
   - Cash-line vs top-decile split: shape lifts flatten to ±1pp at the paid
     line while the top-decile spread is ~8pp wide. Our shapes are
     cash-adequate, top-end-poor. Provisional.
   - Satellite winners are unduplicated in 95–100% of contests per field
     bucket; our field-duplicated copies are ~20 of 31 Showdown. Provisional;
     starting priors for R10.
   - Satellite winners run sub-field chalk (median within-field chalk
     percentile 36–40; supersats 30); our satellite entries sit at 39.5.
     Provisional. Argues against adding a contrarian push on top of the
     shape work.
   - One-seat satellites: 0 seats in 234 archived own entries, 8 top-3s,
     median points gap to winner 29%, min 2.7%. Observed outcome, record.
