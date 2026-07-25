# Session note - 2026-07-25

Tree clean at `686c931`. `python tools/audit.py --run-tests --terse` prints
`PASS  v2.26.0  13 modules  157 tests`. Showdown and golden replays pass (13).

Scope this session: E-1's first piece (I-1) plus the standings decision. F1 from
Vegas totals (I-2) and F5 weather are still open.

---

## 1. I-1 landed: the build is no longer bare APPG

Four deterministic priors now reach the production build path: the xwOBA Base
correction, xISO hitter ceilings, K-rate pitcher ceilings, and the F4
opposing-SP-quality and platoon matchup factor. Measured on the staged 2026-07-24
main-slate pool:

| Factor | Before | After |
|---|---|---|
| xwOBA corrections applied | 0 | 77 (88% crosswalk match) |
| Hitter ceilings differentiated | 0 | 72 of 72 |
| Pitcher ceilings differentiated | 0 | 7 |
| F4 non-neutral hitters | 0 | 72, spread 0.869 to 1.144 |
| F4 platoon component applied | 0 | 72 |

Three things were wrong, not one.

**The script never passed the CSVs or an F4 map.** That was the known gap.
`build_slate.py` now resolves the reference files, computes `f4_by_player_id`,
and passes both into `_assemble_projection_frame` AND `run_slate`. Passing both
matters: on the sliced-bank path the local frame is what every cached candidate
is built from, so enriching only one of the two would build the bank on enriched
projections and certify against unenriched ones.

**Savant's default export is qualified-players-only.** `min=q` returns 255
batters against 602 at `min=1`, and that alone was holding the xwOBA crosswalk
match rate at 43%. Widening it took the same pool to 88%. This is safe because
the engine already PA-shrinks thin samples toward 1.0 and returns exactly 1.0
below `XWOBA_PA_MIN`. What it cannot do is shrink a row it never saw.

**Both inputs to the platoon prior were missing.** The MLB schedule hydrate
returns lineup players and probable pitchers as id plus name, with neither
`batSide` nor `pitchHand`. So `extract_batter_hands` had nothing to read and
every probable carried `hand: None`, and `platoon_hand_factor` returned 1.0 for
every hitter on the slate. The review flagged half of this as I-16's `bat_side`
note; the pitcher half was not on the list. `fetch_lineups` now hydrates both in
one batched `/people` call. Failure is non-fatal and the SP-quality component
still applies.

### New: tools/refresh_reference_data.py

Fetches the two Savant CSVs, validates the payload before overwriting anything
(an HTML error page landing on top of a good CSV is silent and costs a slate),
and stamps `fetched_at` in `data/reference/reference_manifest.json`. FanGraphs
stays manual by decision: the tool reports the file's age and prints the export
URL rather than fetching it. `--check` reports without fetching.

Files older than 14 days are reported as stale in the brief and still used.
Degraded signal beats no lineups at T-10, but it is never silent.

### Reading the brief

`enrichment.signal_applied` is the one field to check before presenting
anything. False means the build ranked on `AvgPointsPerGame x batting-order
factor` and nothing else. `enrichment.counts` says which factors moved players.
`f1_non_neutral` and `f5_non_neutral` report 0 by construction until I-2 and F5
land; they are present rather than absent so the gap stays visible.

An engine zero-match guard now degrades the build to unenriched and records
`enrichment.degraded_reason` instead of raising. That guard is correct at the
library layer and wrong as a slate-killer at T-10. A shipped build that says it
is on bare APPG is honest; a dead slate is not a better answer.

### Caught during testing

The new test class was initially named `ProjectionEnrichmentWiringTests`, which
already existed at test_core.py:1663. Python silently shadowed the earlier class
and 14 tests stopped being collected while the suite still reported OK. The
audit's count pin is the only thing that caught it. Renamed to
`BuildSlateEnrichmentWiringTests`. Worth remembering that a green suite and a
complete suite are different claims.

---

## 2. The five dead standings exports are closed out

Contests 191489664, 191513240, 191520890, 191521489, 191542451 were deleted from
`data/standings/inbox/` and recorded in the ledger archive as unrecoverable. The
archive stays at 5 slates against the 8-15 ownership gate; these five would have
taken it to 10.

The working theory is that DK's export ages out. It is a theory. The test is the
four 2026-07-24 night contests, still unpulled:

```
https://www.draftkings.com/contest/exportfullstandingscsv/192657350
https://www.draftkings.com/contest/exportfullstandingscsv/192657349
https://www.draftkings.com/contest/exportfullstandingscsv/192667458
https://www.draftkings.com/contest/exportfullstandingscsv/192658268
```

Pull those while logged in, check the file sizes are non-zero, and drop them in
`data/standings/inbox/`. Populated means age is confirmed and the rule is a
same-night pull. Empty means the export path itself is broken and timing was
never the issue. Either result belongs in the ledger.

---

## 3. Next, in order

1. **I-2, F1 from Vegas totals.** The remaining outcome-changing piece of E-1,
   and the one the 07-19 review called highest-value. The F4 pattern this session
   established is the template: build the map upstream, pass it through
   `run_slate`, count it in the brief, test the wiring. `build_slate.py` should
   fetch totals when `THE_ODDS_API_KEY` is present or accept `--odds`. Delete the
   remaining hedge in SKILL.md once F1 is live.
2. **F5 weather** from the bundle's per-venue forecast. The manual roof rule
   stays: an unresolved retractable roof is a checkpoint warning, never a guess.
3. **I-4 / I-6 / I-7 / E-5, one bank authority.** This is what lets the signal
   now reaching the frame actually reach big-slate portfolios instead of being
   dropped by `bank_cache.as_candidates()`.
4. **E-3, record Ben's own results.** Still the only loop that can say whether
   any of this wins.

Every number this session produced is a deterministic review proxy or a labeled
prior. None of it is ROI, win rate, cash rate, or a probability claim.
