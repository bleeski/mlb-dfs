# DraftKings MLB Standings: Greenfield Findings

**Evidence cutoff:** 2026-08-28  
**Standings population:** every file recursively present under `data/standings` at the cutoff  
**Decision unit:** conservative independent slate/draft-group cluster, not entry row  
**Scope:** analysis and recommendations only; no production change was implemented

## 1. Executive decision summary

The archive supports three durable strategy conclusions and two immediate evidence-integrity changes.

1. **Classic should not be forced contrarian.** Top-decile lineups were more likely than their fields to contain no player below 5% ownership (+6.22 percentage points by slate), less likely to contain two or more such players (-5.16 pp), and more likely to contain at least four players owned at 20% or more (+5.66 pp). All three directions replicated chronologically and survived clustered uncertainty, false-discovery control, leave-one-slate-out analysis, field-size exclusions, one-contest-per-slate analysis, and permutation controls. This does **not** mean “make our lineups chalkier”: our historical Classic entries were already much chalkier than the field. The change needed is ownership calibration and removal of forced contrarian constructions, not another blanket chalk increase.
2. **Showdown pitcher CPT is the strongest construction signal.** Pitcher CPT lineups were 44.68% of the field and 57.70% of top-decile lineups, a +12.33 pp slate-weighted lift across 34 independent slates. Discovery was +15.73 pp and validation +6.10 pp. Our share was only 39.45%. This merits a bounded shadow test, not a 58% hard target.
3. **Showdown 5-1 is directionally useful in the field but grossly overconcentrated in our entries.** The field used 5-1 at 37.37%, the top decile at 47.19%, and our entries at 81.32%. The top-decile association is stable directional, not production-grade. The practical decision is to reduce our concentration toward a 45-55% shadow band while restoring 4-2 diversity.
4. **Existing Showdown duplication mining is definitionally wrong.** `mlb_engine/field/field_miner.py` groups exact lineups by the unordered player set and does not include CPT identity. A CPT/UTIL swap is a different DraftKings lineup. The analysis in this report recomputed duplication role-aware; the miner should be corrected before its Showdown duplication figures are trusted.
5. **Cash, min-cash, large-prize, satellite-seat, and contest-selection economics are `DATA BLOCKED`.** None of the 422 contests has verified paid places or an exact cash/seat line. Payout tiers and ticket face values are absent. Rank one and top-decile finishes are reported only as finish cohorts, never as cashes or large prizes.

### Headline evidence table

All effects below are within-contest cohort-share minus field-share differences, averaged equally by conservative slate cluster. `D` and `V` are the frozen chronological discovery and validation periods.

| Finding | Format/segment | Raw contests | Independent slates | Discovery | Validation | Sensitivity | Evidence class | Decision |
|---|---:|---:|---:|---:|---:|---|---|---|
| No player below 5%; top-decile lift +6.22 pp, 95% clustered CI +3.11 to +9.72 | Classic | 240 | 58 | +5.90 pp | +6.83 pp | All six exclusions/weightings positive; permutation BH q=.00064 | `REPLICATED SIGNAL` | `SHADOW TEST` ownership calibration; do not force a low-owned player |
| Two or more players below 5%; top-decile lift -5.16 pp, CI -8.22 to -1.99 | Classic | 229 | 58 | -5.19 pp | -5.10 pp | All sensitivities negative; permutation q=.00107 | `REPLICATED SIGNAL` | `SHADOW TEST` a ceiling on forced punts, not a rigid ban |
| Four or more players at 20%+; top-decile lift +5.66 pp, CI +2.44 to +9.23 | Classic | 239 | 58 | +6.86 pp | +3.39 pp | All sensitivities positive; permutation q=.00064 | `REPLICATED SIGNAL` | Recalibrate concentrated chalk; no blanket chalk increase because our mix is already high |
| 5-2-1; top-decile lift +3.84 pp, CI +1.72 to +6.12 | Classic | 237 | 57 | +4.24 pp | +3.09 pp | Same sign throughout, but one-contest/slate permutation q=.127 | `STABLE DIRECTIONAL` | `SHADOW TEST` a bounded 15-25% mix, not a hard stack rule |
| Pitcher CPT; top-decile lift +12.33 pp, CI +6.40 to +17.80 | Showdown, salary-joined | 177 | 34 | +15.73 pp | +6.10 pp | All sensitivities positive; permutation q=.00064 | `REPLICATED SIGNAL` | `SHADOW TEST` 48-52% portfolio share when starters are declared |
| CPT owned 5-10%; top-decile lift -6.43 pp, CI -9.88 to -3.02 | Showdown, salary-joined | 154 | 34 | -7.43 pp | -4.60 pp | All sensitivities negative; permutation q=.00064 | `REPLICATED SIGNAL` | Do not treat middling CPT ownership as automatic leverage; shadow-test role-calibrated CPT ownership |
| 5-1; top-decile lift +5.48 pp, CI -0.44 to +11.30 | Showdown, salary-joined | 177 | 34 | +3.57 pp | +8.97 pp | Positive throughout; permutation q=.010; CI crosses zero | `STABLE DIRECTIONAL` | Reduce our 81.32% mix toward 45-55%; do not increase it |
| Unique lineup; winner lift +10.75 pp, CI +5.60 to +15.57, but top-decile lift -2.58 pp | Showdown | 182 | 36 | winner +10.76 pp | winner +10.74 pp | Winner result stable; top-1% and top-decile do not agree | `STABLE DIRECTIONAL` | Keep duplication pressure as a tiebreaker; require payout economics before a hard penalty |
| Cash/min-cash/seat/large prize | Both | 422 | 94 | unavailable | unavailable | 0/422 paid-place coverage | `DATA BLOCKED` | Capture exact payout and seat structures prospectively |

The evidence does **not** justify changing salary-left rules, declaring a contest family superior, calling the historical portfolio profitable, or converting any association into a rigid lineup constraint.

## 2. Corpus inventory and data quality

### Complete recursive inventory

Every one of the 457 files under `data/standings` was classified.

| Location/class | Files | Treatment |
|---|---:|---|
| `inbox`, nonzero standings CSV | 83 | Parsed directly |
| `inbox`, nonzero standings ZIP | 152 | Read in memory; no extraction into the repository |
| `processed_zips`, nonzero standings ZIP | 187 | Read in memory |
| `failed_pulls`, zero-byte CSV | 12 | Missing evidence, not a contest |
| `inbox`, zero-byte CSV | 13 | Missing evidence, not a contest |
| `inbox/.gitkeep` | 1 | Placeholder, not evidence |
| Root Markdown/JSON/HTML | 9 | Supporting metadata only |
| **Total** | **457** | **422 candidate standings representations, 25 missing-evidence files, 9 support files, 1 placeholder** |

File types were 339 ZIP, 108 CSV, seven HTML, one JSON, one Markdown, and one `.gitkeep`. All 187 processed files were ZIPs. The 235 nonzero inbox representations were 83 CSVs and 152 ZIPs.

### Deduplication and conflicts

- The 422 nonzero representations contained **422 distinct contest IDs**. No contest ID appeared in both raw and processed locations at this cutoff, so there was no duplicate representation to count twice and no raw/processed disagreement to arbitrate.
- File SHA-256 hashes were computed for the full tree, and candidate contents were normalized before contest-level comparison. No two distinct contest IDs were collapsed merely because their fields overlapped.
- **Usable unique contests: 422. Conflicted nonzero contests: 0. Excluded nonzero contests: 0.**
- The 25 zero-byte files are excluded missing evidence, not zero-entry contests. Their paths are listed at the end of this section.

### Parsed population

| Measure | Total | Classic | Showdown |
|---|---:|---:|---:|
| Unique usable contests | 422 | 240 | 182 |
| Conservative independent slate groups | 94 | 58 | 36 |
| Raw entry rows | 492,217 | — | — |
| Complete lineups | 489,422 | 426,637 | 62,785 |
| Blank/withdrawn/zeroed rows | 2,795 | — | — |
| Partial lineups | 0 | — | — |
| Salary-joined complete lineups | 466,642 | 404,804 | 61,838 |
| Entry-level salary join rate | 95.35% | 94.88% | 98.49% |

The observed dates span **2026-06-03 through 2026-08-27** across 32 calendar dates. Field sizes range from 15 to 47,562 entries; the median complete-lineup field is 125.

### Metadata and taxonomy coverage

- Date, contest name, and entry fee were resolved for 422/422 contests using supporting checklist pages and exact included-contest joins to existing DKEntries/archived metadata.
- Exact own Entry IDs were independently reconciled in 422/422 contests: 1,223 own entries total.
- Salary/pool metadata existed for 417/422 contests; 374 contests had at least 95% complete-lineup salary joins.
- Paid places, exact cash lines, or seat lines existed for **0/422** contests.
- Contest-name parsing was used only for diagnostic family labels. It was not used to invent entry fees, payout tiers, paid-place percentages, ticket counts, rake, or ticket values.

Diagnostic contest mix: 285 satellites, 30 supersatellites, one qualifier, 53 standard GPPs, 52 winner-take-all/solo shots, and one multiplier/double-up. Field bands were 83 under 50, 251 from 50-249, 28 from 250-999, 37 from 1,000-4,999, and 23 at 5,000+. The archive is therefore heavily tilted toward cheap satellites and small fields; it is not a representative sample of the full DraftKings MLB lobby.

Classic game counts were: 43 two-game, 46 three-game, 40 four-game, 21 five-game, 24 six-game, 18 seven-game, 10 eight-game, 18 nine-game, 15 ten-game, and five 12-game contests. Slate windows were 282 main/unspecified, 57 night, 40 turbo, 34 early, and nine late-night.

### Parsing and ownership QA

The parser used BOM-safe decoding and the positional schema exactly as exported:

`Rank,EntryId,EntryName,TimeRemaining,Points,Lineup,,Player,Roster Position,%Drafted,FPTS`

The entry table and player table were parsed separately. Format was detected from lineup tokens: Classic by P/C/1B/2B/3B/SS/OF and Showdown by CPT/UTIL. Slot delimiters, not whitespace alone, bounded multiword names. A complete Classic lineup required two pitchers and eight hitters; a complete Showdown lineup required one CPT and five UTIL. Role-aware Showdown lineup keys were `CPT identity + unordered UTIL identities`.

Ownership was independently recomputed from complete lineups and used as authoritative. DraftKings ownership rows were aggregated to underlying-player grain before reconciliation.

| Format | Contests | Within 0.02 pp | Within 0.11 pp | Median max difference | 90th percentile | Maximum | Missing underlying names |
|---|---:|---:|---:|---:|---:|---:|---:|
| Classic | 240 | 119 | 126 | 0.024 pp | 5.560 pp | 13.750 pp | 0 |
| Showdown underlying-player | 182 | 161 | 163 | 0.008 pp | 0.391 pp | 35.812 pp | 0 |

The larger Classic exceptions arise from DraftKings position/multi-position table behavior even when the lineup parse is structurally exact. In Showdown, only 115/182 exports furnished a complete role-separated player table. Underlying, CPT, and UTIL ownership were nevertheless recomputed independently from complete lineup roles in all 182 contests. No role-specific value was guessed from an underlying-player row.

Spot checks covered small, medium, and very large fields in both formats: Classic contest IDs 193770774 (20 entries), 193091132 (118), and 193962574 (47,562); Showdown 194444631 (15), 194017520 (158), and 194237511 (11,890). All six satisfied roster contracts; blank rows were separated from parse failures; salary-join differences were recorded rather than silently filled.

### Repeated fields and lineups

- 17,314 exact role-aware lineup keys appeared in more than one contest; the maximum was ten contests.
- 91 of 94 conservative slate groups contained at least one exact lineup repeated across contests.
- Five contest pairs met the predeclared high-overlap threshold (overlap coefficient at least .80). All were Showdown subsets of the large 2026-08-23 ATL@MIL contest 194237511. Shared-lineup counts ranged from 19 to 92; their Jaccard values were small because one field was a small subset of the much larger field.
- One-contest-per-slate sensitivity removes the leverage these repetitions could otherwise create. It did not reverse any promoted finding.

### Missing-evidence files

The following 25 zero-byte files were classified as missing evidence and did not enter the contest population:

```text
data/standings/failed_pulls/contest-standings-191047506.csv
data/standings/failed_pulls/contest-standings-192345441.csv
data/standings/failed_pulls/contest-standings-192419758.csv
data/standings/failed_pulls/contest-standings-192420813.csv
data/standings/failed_pulls/contest-standings-193405185.csv
data/standings/failed_pulls/contest-standings-193405226.csv
data/standings/failed_pulls/contest-standings-193451396.csv
data/standings/failed_pulls/contest-standings-193451397.csv
data/standings/failed_pulls/contest-standings-193452362.csv
data/standings/failed_pulls/contest-standings-193458420.csv
data/standings/failed_pulls/contest-standings-193461246.csv
data/standings/failed_pulls/contest-standings-193497117.csv
data/standings/inbox/contest-standings-193712013.csv
data/standings/inbox/contest-standings-193712018.csv
data/standings/inbox/contest-standings-193712021.csv
data/standings/inbox/contest-standings-193712022.csv
data/standings/inbox/contest-standings-193712023.csv
data/standings/inbox/contest-standings-193712048.csv
data/standings/inbox/contest-standings-193773322.csv
data/standings/inbox/contest-standings-193775579.csv
data/standings/inbox/contest-standings-193775591.csv
data/standings/inbox/contest-standings-193850995.csv
data/standings/inbox/contest-standings-193882283.csv
data/standings/inbox/contest-standings-193891713.csv
data/standings/inbox/contest-standings-193957104.csv
```

The nine support files were `CONTESTS_AWAITING_STANDINGS.md`, `recorded_exceptions.json`, and seven `standings_pulls_*.html` pages. None contained an additional usable standings export.

## 3. Methodology and signal-versus-noise rules

The following rules were fixed before outcome relationships were examined.

### Questions and outcomes

- Primary question: which pre-lock-observable lineup properties have a persistent within-contest association with a **top-decile** finish, separately for Classic and Showdown?
- Secondary outcomes: top 0.1%, top 1%, and rank-one/co-rank-one cohorts. These may corroborate a primary result but cannot promote a winner-only pattern.
- Cash, min-cash, seat, and large-prize outcomes require verified paid places or payout tiers and remain `DATA BLOCKED` otherwise.
- Cohort thresholds were fixed as rank at or above `ceil(field size × threshold)`, with at least one entry in an apex cohort. Every entry tied at a qualifying rank was retained.

### Effect sizes and evidence gates

- Minimum practical categorical top-decile effect: **3 percentage points** in slate-weighted within-contest representation lift.
- Minimum practical continuous effect: **0.20 within-contest standard deviations**.
- `REPLICATED SIGNAL`: at least 12 independent slates; discovery and validation same direction; validation reaches the practical threshold; clustered interval and BH-adjusted q support the direction; leave-one-slate-out, size/metadata exclusions, one-contest-per-slate, and negative control do not overturn it.
- `STABLE DIRECTIONAL`: at least eight independent slates, same direction, at least 2 pp overall, and stable sensitivities, but at least one promotion gate fails.
- `EXPLORATORY`: sparse or discovery-only.
- `NO RELIABLE EFFECT`: enough observations were available but the practical/replication gates failed.
- `DATA BLOCKED`: a necessary fact was absent or conflicted.

Recommendation promotion was stricter than statistical significance: material size, chronological validation, clustered uncertainty, sensitivity, multiple-testing control, duplication/economic coherence, and a prospective rollback test were all required. Observational associations were not converted directly into hard rules.

### Unit of evidence and uncertainty

- Entries were nested within contest and user; contests were grouped by date, format, and exact game set/matchup. When a draft-group ID was unavailable, this conservative game-set group was used.
- The primary estimate is the contest-level cohort representation minus field representation, averaged first within slate and then across slates.
- Reported uncertainty uses 2,000 slate-cluster bootstrap resamples.
- Entry-weighted and contest-weighted estimates are sensitivity views, not substitutes for the slate estimate.
- No formal Bayesian partial-pooling model was fitted. Conservatism came from slate averaging, minimum-slate gates, chronological validation, clustered intervals, and refusal to rank sparse segments as peers of large ones.

### Discovery, validation, multiplicity, and controls

- Classic split: discovery through 2026-08-13 (38 slates), validation from 2026-08-14 (20 slates).
- Showdown split: discovery through 2026-08-14 (23 slates overall; 22 salary-joined construction slates), validation from 2026-08-15 (13 overall; 12 salary-joined construction slates).
- Declared categorical families: Classic exact stack shape, salary left, low-owned count, chalk count, duplication count; Showdown team split, CPT archetype, CPT ownership, salary left, low-owned count, chalk count, and role-aware duplication.
- There were 59 primary categorical contrasts: 34 Classic and 25 Showdown. The same definitions were checked on the two secondary apex thresholds and winner cohort. Twelve continuous ownership contrasts covered two measures × three outcomes × two formats.
- Benjamini-Hochberg false-discovery control used q=.10 within each declared feature family. Null categories were retained.
- Negative controls used 5,000 within-contest top-decile-label shuffles on one representative contest per slate and BH correction across the 16 headline candidate contrasts.

### Required sensitivities performed

Each potentially actionable result was checked with entry, contest, and slate weighting; discovery versus validation; leave-one-slate-out; one contest per slate; removal of fields below 50; removal of the largest 10% and smallest 10% of fields; restriction to contests with at least 95% salary joins where salary was needed; adjacent band aggregation/continuous ownership alternatives; and top-1%/winner outcome alternatives. One-contest-per-slate also neutralizes highly overlapping fields. A result was downgraded if a single slate, cutoff, weighting, or apex outcome supplied the apparent edge.

## 4. Classic ownership findings

Classic “low-owned” means under 5% actual ownership; “chalk” means at least 20%. These are descriptive field thresholds, not predicted ownership labels.

| Posture | Field | Winner/co-winner | Top 0.1% | Top 1% | Top decile | Ours | Exact-duplication rate |
|---|---:|---:|---:|---:|---:|---:|---:|
| 0 players under 5% | 35.79% | 56.59% | 39.06% | 36.60% | 37.77% | 55.15% | 19.04% |
| 1 player under 5% | 22.87% | 21.32% | 26.77% | 24.64% | 24.11% | 21.82% | 9.92% |
| 2+ players under 5% | 41.34% | 22.09% | 34.17% | 38.76% | 38.11% | 23.04% | 6.44% |
| 0-1 players at 20%+ | 27.37% | 9.69% | 21.57% | 25.24% | 24.46% | 12.74% | 5.69% |
| 2-3 players at 20%+ | 39.14% | 29.84% | 35.59% | 38.74% | 38.77% | 30.54% | 10.14% |
| 4+ players at 20%+ | 33.49% | 60.47% | 42.83% | 36.02% | 36.77% | 56.72% | 18.56% |

The robust statement is about **top-decile representation**, not about selecting post-hoc low-owned scorers. Zero sub-5% pieces and four or more 20%+ pieces replicated; two or more sub-5% pieces underrepresented. The winner shares are much more extreme, but the “zero low-owned” winner effect reversed from discovery (+8.51 pp) to validation (-1.75 pp) and had q=.485. It is not a replicated winner rule.

Continuous ownership was weaker. Top-decile lineups had +0.183 SD cumulative ownership sum (CI +0.049 to +0.310; discovery +0.236, validation +0.083) and +0.205 SD log-product (CI +0.085 to +0.319; discovery +0.257, validation +0.106). Validation missed the frozen 0.20-SD practical threshold. Both are `STABLE DIRECTIONAL`, corroborating the categorical result without earning a hard constraint.

### What this means for our portfolio

Our historical Classic entries already had zero sub-5% players 55.15% of the time versus 35.79% for the field, and four or more 20%+ players 56.72% versus 33.49%. Therefore:

- the evidence rejects a general requirement to include one or two very low-owned pieces;
- it does **not** support increasing our already concentrated chalk mix;
- the actionable gap is a calibrated, contest-conditioned ownership model that can distinguish useful concentrated cores from duplicated chalk, rather than a new global ownership sum target.

### Immutable pre-lock prediction grade

Only Classic has a valid schema-compatible ownership prior. Across 86 contests and 17 independent prediction slates:

| Metric | Classic result |
|---|---:|
| Slate-averaged bias | +0.005 pp |
| MAE | 2.696 pp |
| RMSE | 5.800 pp |
| Rank correlation | .599 |
| Top-10 chalk recall | 28.6% |
| Under-5% tail MAE | 1.552 pp |
| Team-total ownership bias | -0.62 pp |
| Team-total ownership MAE | 48.07 pp |

Near-zero aggregate bias hides severe calibration compression:

| Predicted band | Mean prediction | Mean actual | Signed error |
|---|---:|---:|---:|
| 0-1% | 0.462% | 0.034% | +0.428 pp |
| 1-5% | 2.446% | 2.121% | +0.325 pp |
| 5-10% | 6.621% | 8.638% | -2.018 pp |
| 10-20% | 12.990% | 22.100% | -9.110 pp |
| 20%+ | 22.133% | 39.473% | -17.340 pp |

MAE worsened from 2.420 pp in the first half to 3.109 pp in the second. The model has some ordering information but is not magnitude-calibrated and misses much of the top chalk. It should remain a shadow input until a time-held-out recalibration passes.

Files named `ownership_pred_*_sd.json` do not create a valid Showdown role model: the underlying module declares a Classic 2P/8H budget and emits no separate CPT/UTIL probabilities. Same-date Classic prediction files can also overlap Showdown player names. Consequently **Showdown prediction error, CPT error, and UTIL error are `DATA BLOCKED`**, and no numbers from those cross-format matches are used here.

## 5. Classic stack and lineup-shape findings

Shape analyses use the 404,804 complete Classic lineups with salary/team joins. Shares are raw cohort composition; “lift” is the clustered within-contest quantity and must not be inferred by subtracting pooled shares.

| Exact hitter shape | Entries | Contests | Slates | Field | Winner | Top 0.1% | Top 1% | Top decile | Ours | Dup. |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 5-2-1 | 124,193 | 237 | 57 | 30.68% | 28.00% | 34.58% | 37.38% | 34.11% | 1.44% | 8.75% |
| 5-3 | 70,632 | 237 | 57 | 17.45% | 22.00% | 20.29% | 19.11% | 18.79% | 16.70% | 20.57% |
| 5-1-1-1 | 34,285 | 219 | 57 | 8.47% | 8.40% | 11.53% | 9.92% | 9.45% | 1.26% | 6.93% |
| 4-3-1 | 33,088 | 236 | 57 | 8.17% | 8.00% | 8.12% | 8.68% | 8.33% | 11.13% | 8.11% |
| 4-2-1-1 | 25,439 | 231 | 57 | 6.28% | 10.00% | 5.68% | 5.29% | 5.60% | 28.90% | 10.72% |
| 3-2-1-1-1 | 17,244 | 193 | 48 | 4.26% | 4.00% | 3.08% | 2.88% | 3.12% | 2.15% | 13.07% |
| 3-2-2-1 | 14,401 | 214 | 57 | 3.56% | 2.00% | 1.95% | 2.72% | 3.04% | 2.51% | 13.44% |
| 2-2-1-1-1-1 | 13,869 | 164 | 46 | 3.43% | 2.00% | 1.14% | 1.59% | 2.28% | 0.36% | 13.01% |
| 4-4 | 12,685 | 226 | 57 | 3.13% | 6.00% | 5.84% | 3.84% | 3.46% | 10.23% | 12.89% |
| 3-3-1-1 | 9,081 | 218 | 57 | 2.24% | 0.80% | 1.30% | 1.52% | 2.16% | 0.72% | 12.07% |
| 2-2-2-1-1 | 8,904 | 161 | 48 | 2.20% | 2.80% | 1.30% | 0.99% | 1.49% | 0.72% | 12.89% |
| 2-1-1-1-1-1-1 | 8,863 | 125 | 34 | 2.19% | 0.40% | 0.81% | 0.76% | 1.46% | 0.00% | 13.25% |
| 4-2-2 | 8,541 | 201 | 57 | 2.11% | 1.60% | 1.14% | 1.68% | 1.74% | 7.90% | 9.21% |
| 4-1-1-1-1 | 7,532 | 165 | 47 | 1.86% | 1.60% | 1.46% | 1.31% | 1.81% | 14.36% | 9.85% |
| 3-3-2 | 6,878 | 197 | 56 | 1.70% | 2.00% | 1.30% | 1.43% | 1.64% | 0.90% | 13.06% |
| 3-1-1-1-1-1 | 5,214 | 153 | 47 | 1.29% | 0.40% | 0.32% | 0.71% | 0.96% | 0.54% | 13.73% |
| 1-1-1-1-1-1-1-1 | 2,421 | 78 | 29 | 0.60% | 0.00% | 0.00% | 0.09% | 0.34% | 0.00% | 15.70% |
| 2-2-2-2 | 1,534 | 118 | 53 | 0.38% | 0.00% | 0.16% | 0.09% | 0.23% | 0.18% | 14.34% |

Only two exact-shape findings survived enough checks to remain directional:

- **5-2-1:** top-decile slate lift +3.84 pp, BH q=.0049, discovery +4.24, validation +3.09, clustered CI +1.72 to +6.12, leave-one-slate-out +3.34 to +4.12. The result stayed positive after removing tiny fields, largest fields, smallest fields, degraded salary joins, and all but one contest per slate. However, the one-contest-per-slate permutation test was not stronger than the shuffled procedure after correction (q=.127). `STABLE DIRECTIONAL`, not replicated.
- **2-2-1-1-1-1:** top-decile lift -2.24 pp, q<.001, discovery -2.38, validation -2.01, CI -3.14 to -1.26, permutation q=.0135. It misses the frozen 3-pp practical threshold. `STABLE DIRECTIONAL`; no special production ban is warranted.

5-3, 5-1-1-1, 4-3-1, 4-2-2, and 4-2-1-1 did not produce a practical replicated top-decile effect. The apparent 5-1-1-1 discovery benefit reversed slightly in validation. Winner-only lifts for 5-2-1 and 4-2-1-1 had intervals crossing zero and q=.266/.317.

### Primary/secondary size and pitcher correlation

- Primary five-man stacks were 56.60% of joined field lineups and 19.39% of ours; primary four-man stacks were 21.56% of the field and 72.53% of ours. This is the root portfolio mismatch behind the exact-shape table.
- Secondary two-man groups were 52.90% of the field and 44.17% of ours; secondary three-man groups were 29.56% of the field and 29.44% of ours. The primary stack, not secondary size, is the larger difference.
- 86.71% of joined Classic field lineups rostered no hitter against either selected pitcher; their raw top-decile rate was 10.68%. Rates declined to 8.52% with one opposing hitter and 8.06% with two. Our share with zero was already 99.10%, so there is no need to tighten this further.
- Exact pitcher-pair identities are slate-specific and do not form a defensible pooled category. No independent cross-slate pitcher-pair rule cleared the promotion gates. The archive supports continuing to judge pitcher pairs on projections, correlation, and exposure rather than a mined global identity prior.
- Reliable immutable batting-order adjacency was not available across enough of the 94 slate groups. Batting-order concentration is `DATA BLOCKED`, not silently approximated from post-lock FPTS.

### Salary and duplication

Classic salary-left bands were nearly unchanged between field and top decile. For example, $0 left was 23.78% of the field and 23.24% of the top decile; more than $1,500 left was 7.47% and 7.45%. No band produced a replicated practical effect. `NO CHANGE`.

Role-aware exact uniqueness was common: 88.26% of field lineups were unique, 91.09% of winner/co-winner lineups were unique, and 87.40% of top-decile lineups were unique. No Classic lineup with six or more copies was rank one, but this is a sparse winner-only fact, not a top-decile advantage. Duplication should remain a tiebreaker, not override projection and correlation.

## 6. Showdown ownership findings

Showdown ownership was retained at three grains: underlying player, CPT, and UTIL. Low-owned means underlying ownership below 10%; chalk means underlying ownership at least 40%. Role-specific CPT ownership uses realized CPT share, not underlying ownership.

- Cumulative underlying ownership did **not** replicate. Top-decile ownership-sum effect was +0.066 SD (CI crosses zero; discovery +0.151, validation -0.086). Log-product was +0.127 SD overall but collapsed to +0.008 in validation. Both are `NO RELIABLE EFFECT` for production.
- Zero underlying players below 10% was 90.49% of the field and 95.34% of the top decile. Slate lift was +2.64 pp, discovery +2.70, validation +2.53, negative-control q=.062. It misses the 3-pp practical threshold: `STABLE DIRECTIONAL` only.
- The role-specific signal is sharper: 5-10% CPTs were 17.48% of the field but 9.38% of the top decile and 8.04% of winners. The top-decile lift replicated at -6.43 pp.
- CPTs at 20%+ were 36.89% of the field and 46.59% of the top decile. Overall lift was +9.06 pp with q=.015 and permutation q=.018, but validation was only +1.39 pp. Under the frozen rule this is `STABLE DIRECTIONAL`, not `REPLICATED SIGNAL`.

| CPT ownership | Field | Winner/co-winner | Top 0.1% | Top 1% | Top decile | Ours | Dup. rate |
|---|---:|---:|---:|---:|---:|---:|---:|
| Under 5% | 29.35% | 24.11% | 27.57% | 29.13% | 25.22% | 31.24% | 26.04% |
| 5-10% | 17.48% | 8.04% | 7.72% | 8.07% | 9.38% | 19.65% | 36.67% |
| 10-20% | 16.28% | 22.77% | 24.26% | 17.78% | 18.81% | 23.99% | 41.50% |
| 20%+ | 36.89% | 45.09% | 40.44% | 45.02% | 46.59% | 25.12% | 59.95% |

Because no immutable prediction artifact supplies separate CPT and UTIL probabilities, the historical associations cannot yet be translated into prospective CPT leverage. A Showdown role model must be emitted before lock and graded separately by role.

## 7. Showdown construction and duplication findings

Shape analyses use 61,838 role-complete, salary/team-joined lineups from 177 contests and 34 independent slates.

### Team split and CPT archetype

| Construction | Field | Winner/co-winner | Top 0.1% | Top 1% | Top decile | Ours | Role-aware dup. |
|---|---:|---:|---:|---:|---:|---:|---:|
| 5-1 | 37.37% | 36.16% | 43.01% | 52.71% | 47.19% | 81.32% | 52.01% |
| 4-2 | 38.76% | 45.54% | 40.07% | 34.43% | 34.68% | 12.88% | 37.84% |
| 3-3 | 23.87% | 18.30% | 16.91% | 12.86% | 18.13% | 5.80% | 36.95% |
| Pitcher CPT | 44.68% | 62.05% | 59.93% | 57.00% | 57.70% | 39.45% | 56.32% |
| Hitter CPT | 55.32% | 37.95% | 40.07% | 43.00% | 42.30% | 60.55% | 32.10% |

Pitcher CPT is the only Showdown construction that meets every replicated-signal gate on the primary outcome. Its winner association does **not** independently replicate: discovery was +16.15 pp but validation -1.36 pp. The production case therefore rests on the top-decile result, not hindsight about winners.

5-1 is directional, but our 81.32% concentration is already far beyond both field and successful-cohort shares. Four CPT teammates—usually the same 5-1 posture—were 35.89% of the field and 76.65% of ours. Their raw top-decile rate was 13.15%; this is not a separate independent signal from 5-1. Portfolio action should reduce concentration, not chase the raw rate.

The “hitters opposing their pitcher” count is highly entangled with whether one or both pitchers are rostered and with team split. Zero such pairs was 26.84% of the field but had only a 5.28% raw top-decile rate; one pair was 25.14% of the field with a 13.69% rate; four pairs was 29.43% with a 13.08% rate. Because this is not ordinal and overlaps the CPT/team-split families, no independent hard rule is promoted.

### Salary left

No Showdown salary-left band replicated. More than $1,500 left was 7.74% of the field and 6.09% of the top decile; its slate lift was about -2.2 pp and permutation q=.220. Spending exactly the cap was 16.09% of the field and 17.66% of the top decile. `NO CHANGE`.

### Exact duplication and prize splitting

The report's duplication key includes CPT role. Under that definition:

| Copies | Field | Winner/co-winner | Top 0.1% | Top 1% | Top decile | Ours |
|---|---:|---:|---:|---:|---:|---:|
| 1 | 57.28% | 74.68% | 67.97% | 55.24% | 51.34% | 85.85% |
| 2 | 13.68% | 7.73% | 10.68% | 14.30% | 14.15% | 9.08% |
| 3-5 | 14.59% | 6.44% | 7.83% | 12.45% | 15.20% | 4.46% |
| 6+ | 14.45% | 11.16% | 13.52% | 18.00% | 19.31% | 0.62% |

Unique lineups overrepresented winners by +10.75 pp with chronological stability, but underrepresented the top decile by -2.58 pp. This is consistent with uniqueness improving prize-split economics conditional on an apex score, not improving the chance of scoring well. Because actual payout tiers are missing, expected-value impact cannot be measured. Keep a bounded duplicate penalty and collect payouts; do not turn uniqueness into a scoring proxy.

## 8. Winning, large-prize, and cash-line characteristics

Ties were explicit. There were 383 contests with one rank-one entry, 25 with two co-winners, eight with three, two with four, two with six, and two with seven. Every co-winner was retained in winner shares.

The most repeatable apex-adjacent characteristics were:

- Showdown pitcher CPT: strong top-decile and top-1% overrepresentation; winner validation failed, so the winner label is not the basis for action.
- Showdown 5-10% CPT: underrepresented in top-decile, top-1%, and winner cohorts with consistent direction.
- Classic 5-2-1: top-decile and top-1% directional, but the permutation promotion gate failed.
- Showdown exact uniqueness: winner-only economic signal; not a scoring signal.

Classic “four or more chalk” and “zero low-owned” had striking winner shares, but their winner-specific chronological behavior was not sufficiently stable to create a rank-one rule. Winner cohorts supply roughly one independent outcome per contest and are appropriately noisier than top-decile cohorts.

`DATA BLOCKED` answers:

- **Actual cash/min-cash:** no paid-place or cash-line coverage in 422 contests.
- **Satellite seat rate:** no exact seat count/line or ticket award evidence.
- **Large prizes:** no verified payout tier or prize attached to the standings ranks.
- **Cash-line score gaps:** no exact cash line.

Top-decile and rank-one results above are not substitutes for any of those monetary outcomes.

## 9. Our performance by contest type

Own identity was based on exact reconciled Entry IDs, never username inference.

### Overall and by format

| Segment | Entries | Contests | Slates | Fees | Top 1%, entry weighted | Top decile, entry weighted | Top decile, contest weighted | Top decile, slate weighted | Mean finish percentile | Exact duplicated |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| All | 1,223 | 422 | 94 | $190.96 | 1.47% | 9.89% | 11.05% | 10.89% | 46.85% | 10.06% |
| Classic | 573 | 240 | 58 | $135.77 | 2.09% | 10.12% | 11.72% | 11.57% | 47.54% | 5.41% |
| Showdown | 650 | 182 | 36 | $55.19 | 0.92% | 9.69% | 10.17% | 9.80% | 46.23% | 14.15% |

Own top-0.1% rates were 0.90% overall, 1.22% Classic, and 0.62% Showdown. The median best-own score gap to the contest winner was 51.93 DK points in Classic (34.40% of winning score) and 24.60 in Showdown (30.24%). These are finish diagnostics, not value estimates.

### Diagnostic family results

| Family | Entries | Contests | Slates | Entry-weighted top decile | Contest-weighted | Slate-weighted | Status |
|---|---:|---:|---:|---:|---:|---:|---|
| Satellite | 1,009 | 285 | 87 | 10.11% | 12.24% | 11.78% | Seat outcome `DATA BLOCKED` |
| Supersatellite | 69 | 30 | 23 | 10.14% | 12.78% | 14.86% | Seat outcome `DATA BLOCKED` |
| Standard GPP | 88 | 53 | 39 | 5.68% | 3.11% | 4.23% | `EXPLORATORY`; small, selected sample |
| Winner-take-all/solo shot | 52 | 52 | 52 | 11.54% | 11.54% | 11.54% | `NO RELIABLE EFFECT` versus other families |
| Qualifier | 4 | 1 | 1 | 25.00% | 25.00% | 25.00% | Too sparse |
| Multiplier/double-up | 1 | 1 | 1 | 0.00% | 0.00% | 0.00% | Too sparse |

The apparent standard-GPP cash ledger line—$20 winnings against $4.50 fees in five covered contests—is driven by one result and excludes 48 GPP contests. Across all formats, only 46 contests have any usable cash-winnings field, totaling $28.50 against $23.38 in fees for that subset. Satellite ticket values are absent and zero cash winnings cannot be interpreted as a loss. No ROI is reported.

No field-size, fee, entry-cap, slate-window, or contest-family segment survived the independent-slate and economic-data gates. The 0-for-24 own top-decile count in 5,000+ fields spans only 20 slates and is exploratory; it is not enough to change contest selection.

## 10. Additional material findings

### Cross-contest reuse and cannibalization

Within the same slate, 101 distinct own lineup keys were reused across more than one contest. This covered 235 of 1,223 own entries (19.22%); one lineup appeared in as many as five contests. Reuse can be rational when the same best lineup fits multiple contests, but it concentrates outcome risk and makes contest results non-independent. Without payout curves and ticket values, the balance between efficient reuse and cannibalization is `DATA BLOCKED`.

### Temporal drift

The categorical Classic ownership effects held their validation direction. The continuous effects weakened materially in validation, and Classic ownership-prediction MAE worsened from 2.42 to 3.11 pp. Showdown 20%+ CPT strength and pitcher-CPT winner strength also weakened sharply in validation, which is why only the primary pitcher-CPT top-decile result is promoted.

### Multi-entry opponent behavior

Multi-entry declarations and exact field duplicates were retained, but users, contests, and same-slate fields were clustered rather than treated as independent. The archive does not support a separate opponent-entry-count prior after multiple-testing control. `NO RELIABLE EFFECT`.

### Payout concentration and contest conditioning

Family, fee, field, window, game count, and entry-cap labels are available. Exact payout concentration and paid percentage are not. Contest-conditioned ownership/shape models should therefore be fit only on structurally known dimensions until payout evidence exists; “satellite,” by name alone, cannot stand in for an exact seat line.

## 11. Findings that failed validation or appear to be noise

| Candidate finding | What happened | Final classification |
|---|---|---|
| Classic 5-3 advantage | +1.72 pp discovery, -0.39 pp validation; CI crosses zero | `NO RELIABLE EFFECT` |
| Classic 5-1-1-1 advantage | +2.85 pp discovery, -0.12 pp validation | `NO RELIABLE EFFECT` |
| Classic 4-2-1-1 winner effect | Winner-only, CI crosses zero, q=.317 | `NO RELIABLE EFFECT` |
| Classic salary left | Top-decile shares track field shares across all six bands | `NO RELIABLE EFFECT` |
| Showdown cumulative chalk | Continuous effect weakens or reverses in validation | `NO RELIABLE EFFECT` |
| Showdown 20%+ CPT as replicated | Overall strong, but validation only +1.39 pp | `STABLE DIRECTIONAL` |
| Showdown 3-3 penalty | Direction negative, but one-contest/slate permutation q=.605 | `STABLE DIRECTIONAL`, no hard rule |
| Showdown salary >$1,500 left penalty | About -2.2 pp; below practical threshold; permutation q=.220 | `NO RELIABLE EFFECT` |
| Unique lineups score better | Unique Showdown lineups underrepresent the top decile even though they overrepresent winners | `NO RELIABLE EFFECT` as scoring claim; `STABLE DIRECTIONAL` for split economics |
| Any contest family is better for us | Sparse, selected segments and missing economics | `DATA BLOCKED` |

### Comparison with the earlier standings analysis

Only after the greenfield findings were frozen was `ledger/2026-08-04_field_shape_ownership_analysis.md` inspected.

| Earlier claim | Greenfield regrade |
|---|---|
| 5-2-1 upside had decayed in a newer tranche | The enlarged corpus restores a +3.84 pp clustered top-decile lift with D/V agreement, but it still fails the permutation promotion gate. Direction replicated; certainty remains bounded. |
| Primary stacks of three or fewer and 4-2-x were consistently bad | Dispersed 2-2-1-1-1-1 remains directionally negative. Exact 4-2-1-1 is null and the broader “4-2-x” grouping is too coarse; the earlier generalization is weakened. |
| Winning differentiation came from one or two low-owned high scorers | That definition uses realized FPTS to identify the low-owned scorer and is therefore hindsight. Under pre-lock-observable ownership counts, top-decile Classic lineups favor zero sub-5% players and penalize two or more. The earlier production interpretation reverses. |
| Classic winners were chalk-positive | Broadly consistent descriptively, but our entries are already substantially chalkier than the field. Calibration, not more chalk, is the decision. |
| Classic winners leave more salary; Showdown winners spend nearer the cap | Neither salary-left direction survives the current clustered validation. Downgraded to `NO RELIABLE EFFECT`. |
| Showdown duplication is a larger concern | Replicates descriptively, but the current miner's position-blind exact key overstates Showdown copies when CPT differs. Role-aware measurement is required first. |

## 12. Comparison with current system behavior

| Current behavior | Independent evidence | Class | Mismatch/root cause | Recommended response | Affected area | Expected impact | Overfit risk | Prospective test |
|---|---|---|---|---|---|---|---|---|
| `field_miner.py` groups duplicates by `players_norm`, excluding CPT identity; CPT is stored separately | DK defines CPT swap as a different lineup; independent report key is role-aware | Structural correctness | Showdown role was normalized out of the duplicate key | `CHANGE NOW`: role-aware field duplicate/winner-copy key; preserve player-set key separately for portfolio overlap | `mlb_engine/field/field_miner.py` and downstream mined schema | Correct copy counts for all Showdown analyses | Low | Unit fixture with same six players and swapped CPT must yield two exact lineups but one player-set overlap group |
| Classic auto-bank calls `build_diverse_candidate_bank` with defaults `bank_stack_min_size=4`, `bank_secondary_size=0`; 5-2-1 forced augmentation requires 5 and 2 | 5-2-1 directional +3.84 pp; ours 1.44% versus field 30.68% | `STABLE DIRECTIONAL` | Generator/selection path does not deliberately supply the shape; historical portfolio concentrates on four-man primaries | Shadow a bounded 15-25% 5-2-1 candidate/selected mix | `mlb_engine/optimize/optimizer_v3.py`, `mlb_engine/pipeline/execution_pipeline.py`, allocator mix controls | More correlated five-man coverage without monoculture | Medium-high | 15 new Classic slates; compare incumbent and shadow on frozen projections and realized post-slate scores; rollback on projection loss or duplication increase |
| Ownership prior is labeled uncalibrated; optimizer can read `Projected_Ownership_Pct`, falls back to tiers, and cumulative magnitude enters field-pressure score; optional hard bounds exist | Classic prior rank corr .599 but severe 10%+ underprediction and 28.6% top-chalk recall | Model/data integrity plus replicated field posture | Rank signal and magnitude calibration are conflated in some scoring/constraint paths | Gate magnitude-bearing use on an explicit calibration status; retain diagnostic/rank-only use until time-held-out calibration passes | `mlb_engine/field/ownership_prior.py`, `tools/ownership_pred.py`, `mlb_engine/optimize/optimizer_v3.py` | Prevent unsupported leverage/duplication penalties from reshaping lineups | Low-medium | Calibration report must pass MAE, band error, recall, drift, and holdout gates before status changes |
| Showdown thesis ladder includes pitcher CPT in starter-led templates and pitchers-duel; each individual CPT is capped at 25% | Pitcher CPT +12.33 pp top-decile; ours 39.45% versus top-decile 57.70% | `REPLICATED SIGNAL` | Aggregate pitcher-CPT mix remains low even though no individual pitcher may exceed 25% | Shadow 48-52% total pitcher CPT when both starters are declared; preserve 25% individual cap initially | `mlb_engine/optimize/showdown_theses.py`, `mlb_engine/optimize/showdown.py`, `skills/generate-lineups/scripts/build_slate.py` | Better alignment with replicated construction without one-pitcher concentration | Medium | 15 new Showdown slates, stratified by starter quality/game total; require role-aware duplication and no single-CPT cap breach |
| Showdown game-state suppression produces many 5-1 builds; no portfolio target normalizes team-split mix | Ours 81.32% 5-1 versus field 37.37% and top-decile 47.19% | `STABLE DIRECTIONAL` | Thesis allocation and suppression collapse diversity into the same team shape | Shadow a 45-55% 5-1 band and minimum 30% 4-2; do not force 3-3 | `showdown_theses.py`, Showdown portfolio allocation/reporting | Reduce correlated failure and duplication while retaining directional 5-1 edge | Medium | Same prospective 15-slate factorial test; report projection, role-aware copies, team exposure, and realized ranks |
| Allocator forbids same-contest duplicate player sets and permits controlled cross-contest reuse | 19.22% of own entries reuse a lineup across contests; exact payout effects unavailable | `DATA BLOCKED` | Reuse posture cannot be priced without payout/seat curves | Keep existing conservative controls; add reuse reporting by slate and contest economics before changing caps | `mlb_engine/allocate/contest_allocator.py` | Makes correlation visible without assuming it is bad | Low | Capture exact payouts, then compare marginal expected payout under reuse scenarios |
| Contest taxonomy and deterministic allocation proxies exist, including special satellite warnings | 0/422 exact paid-place/seat-line coverage | `DATA BLOCKED` | Labels are richer than outcome evidence | Do not retune contest allocation from percentile results; capture economics first | contest intake, contest cards, own-results schema | Prevent false ROI/seat claims | Low | 100% paid-place, ticket-count, ticket-value, and winnings-channel coverage for a prospective block |
| Salary uniqueness/pressure bonuses exist | Neither format has a replicated salary-left effect | `NO RELIABLE EFFECT` | Historical salary narratives did not validate | `NO CHANGE` to salary-left rules from this study | optimizer candidate scoring | Avoid overfitting a null | Low | Continue monitoring as a preregistered secondary metric |

## 13. Recommended changes

No strategy-setting change qualifies for immediate production promotion. The two `CHANGE NOW` items are measurement/gating corrections, not historical strategy rules.

| Priority | Format | Contest segment | Current behavior | Recommended change | Evidence class | Effect size | Independent slates | Expected impact | Validation gate |
|---|---|---|---|---|---|---:|---:|---|---|
| P0 | Showdown | All | Exact copies ignore CPT identity in field miner | `CHANGE NOW`: role-aware exact key; keep separate player-set overlap key | Structural correctness | Definition affects potentially every CPT swap | 36 observed | Correct duplication, winner-copy, and own-copy evidence | Fixture and full re-mine produce CPT-aware counts without changing Classic |
| P0 | Both | All | Paid places/payouts/tickets not captured | `CHANGE NOW`: immutable capture of paid places, full payout tiers, seat count, ticket face value, cash winnings, promotional value | `DATA BLOCKED` | Coverage 0/422 | 94 blocked | Unlock cash, min-cash, prize, ROI, and contest-selection analysis | 100% required fields or explicit typed missing reason before archival certification |
| P0 | Classic | All | Uncalibrated ownership magnitude can be consumed by score/optional bounds | `CHANGE NOW`: require explicit calibrated status before magnitude-bearing optimizer use | Model integrity | 20%+ band underpredicted 17.34 pp; top-chalk recall 28.6% | 17 prediction slates | Prevent unsupported leverage penalties | Time-held-out grade and status assertion tests |
| P1 | Showdown | Declared two-starter slates | Ours 39.45% pitcher CPT | `SHADOW TEST` 48-52% total pitcher CPT; keep 25% per-player cap | `REPLICATED SIGNAL` | +12.33 pp top-decile lift | 34 | Improve construction mix | 15 new slates; same direction, at least +3 pp versus field, no duplication/economic regression |
| P1 | Showdown | All salary-joined | Ours 81.32% 5-1 | `SHADOW TEST` 45-55% 5-1 and at least 30% 4-2 | `STABLE DIRECTIONAL` plus portfolio mismatch | Top-decile +5.48 pp; ours +34.13 pp above cohort share | 34 | Reduce monoculture while retaining likely edge | 15 new slates; no realized-rank decline, lower max team exposure and role-aware copies |
| P1 | Classic | Contest-conditioned | Prior is compressed and weak on top chalk | `SHADOW TEST` fitted calibration by format/archetype; never use actual ownership at build time | Prediction evidence | MAE 2.70 pp; high bands -9.11/-17.34 pp | 17 prediction slates | Better duplication/leverage estimates | Rolling-origin holdout: MAE improvement, band bias within ±3 pp, top-10 recall at least 60%, no second-half drift |
| P2 | Classic | GPP/WTA candidate banks | Ours 1.44% 5-2-1 | `SHADOW TEST` 15-25% mix; keep other shapes available | `STABLE DIRECTIONAL` | +3.84 pp top-decile lift | 57 | Correct underrepresentation without chasing pooled 34.11% | 15 new slates; pass permutation-style prospective comparison and projection/duplication guardrails |
| P2 | Both | All | Salary-left heuristics exist | `NO CHANGE` | `NO RELIABLE EFFECT` | Near zero practical differences | 57 Classic / 34 Showdown | Avoid unnecessary constraint | Revisit only after 15 new slates and preregistered threshold |
| P2 | Both | Contest selection | Uses deterministic taxonomy proxies | `DATA BLOCKED`: do not retune selection yet | `DATA BLOCKED` | No paid-place evidence | 94 blocked | Avoid false ROI optimization | Exact economics captured prospectively |

## 14. Prospective testing plan

1. **Freeze new evidence per slate.** Before lock, store salary/draft-group ID, format, contest ID, exact payout and paid-place/seat structure, ticket value, contest family, ownership predictions by role, prediction generation time, and candidate portfolio hashes.
2. **Run shadow variants, not uploaded overrides.** For at least 15 new independent slates per format:
   - Classic A: incumbent; B: calibrated ownership only; C: calibrated ownership plus 15-25% 5-2-1 mix.
   - Showdown A: incumbent; B: 48-52% pitcher CPT; C: pitcher-CPT target plus 45-55% 5-1/at least 30% 4-2.
3. **Keep the evaluation blind to post-lock inputs.** Grade frozen lineups after settlement; actual FPTS may evaluate them but may never be a construction feature.
4. **Primary prospective outcomes.** Within-slate top-decile representation for submitted or shadow-ranked lineups, realized score percentile, exact role-aware copies, and—once captured—expected/actual payout and seat advancement. Projection loss, ownership calibration, max player/team exposure, and portfolio overlap are safety metrics.
5. **Promotion gate.** At least 12 usable independent slates, same direction in the final five-slate holdout, practical effect at least 3 pp, clustered interval not materially negative, no single-slate dominance, and no duplication/economic offset. Strategy changes roll back automatically if the last-five-slate effect reverses or safety limits breach.
6. **Factorial isolation.** Do not change ownership calibration, stack mix, CPT mix, and contest selection simultaneously. The variants above isolate which intervention produced the difference.
7. **Contest-family models wait.** Do not fit satellite/GPP-specific outcome priors until each target family has at least 12 independent slates with exact payout structure.

## 15. Missing-data and evidence backlog

Ordered by decision value:

1. Exact paid places/cash line or seat line for every contest.
2. Full payout tier table, cash winnings, satellite seat count, ticket face value, and promotional value as separate fields.
3. A declared role-aware Showdown ownership prediction schema with underlying, CPT, and UTIL probabilities that sum to the correct budgets.
4. Draft-group ID and immutable slate identity, rather than reconstructed game-set grouping.
5. Salary/team/game joins for the five contests without salary metadata and improvement of the 43 contests below 95% join.
6. Immutable confirmed batting-order evidence with source timestamp so adjacency can be tested without hindsight.
7. Stable team and game identifiers inside ownership prediction artifacts to make team-error grading first-class.
8. Explicit ownership calibration status and version on every candidate bank and final portfolio.
9. Role-aware exact duplication plus separate player-set overlap, both persisted in mined evidence.
10. Cross-contest reuse attribution by slate, contest payout curve, and lineup hash.
11. Exact rake and entry cap from contest evidence rather than diagnostic name parsing.

Until items 1-2 exist, cash rate, min-cash traits, seat rate, large-prize traits, net cash result, promotional value, and ROI must remain `DATA BLOCKED`.

## 16. Limitations and verification notes

- This is observational evidence. A shape can be associated with success because it captures correlation or because it co-occurs with better projections; it is not a causal estimate.
- The archive spans 32 observed dates and 94 conservative slate groups, with a strong cheap-satellite/small-field skew. Entry-row volume does not erase that limited effective sample.
- Salary-derived construction tables exclude lineups without complete joins; ownership and role-aware duplication use all structurally complete lineups.
- DraftKings ownership-table discrepancies were not guessed through. Lineup-recomputed ownership is authoritative, and direct-table disagreement remains visible in QA.
- Showdown direct role tables are incomplete in 67 contests; role ownership was independently recomputed from lineup slots rather than inferred.
- Batting-order adjacency, actual cash, min-cash, payout concentration, large prizes, ticket advancement, and promotional ROI are unavailable.
- The analysis used conservative slate averaging rather than a formal hierarchical partial-pooling model. This reduces pseudo-replication but does not create more independent slates.
- Multiple-testing control substantially downgraded attractive raw results. In particular, 5-2-1 is directional rather than replicated, salary-left claims are null, and winner-only patterns do not become production rules.
- All ZIPs were read in memory. No standings file was extracted, moved, renamed, copied, archived, deleted, or modified.
- Pre-existing tracked and untracked workspace changes were preserved. No source, configuration, test, ledger, registry, reference, manifest, report, or production output was edited. The sole persistent project write from this analysis is this Markdown report.

**Bottom line:** recalibrate ownership rather than forcing contrarianism; shadow more pitcher CPT while reducing our extreme Showdown 5-1 concentration; cautiously test more Classic 5-2-1; fix role-aware duplication measurement; and refuse monetary or contest-selection claims until exact payout and seat evidence exists.
