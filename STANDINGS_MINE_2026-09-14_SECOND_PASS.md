# Standings mine, 2026-09-14 — second pass

Scope: the 248 contest-standings exports in `data/standings/inbox` on
2026-09-14. Greenfield, at Ben's request.

**Updated September 15:** the supplied entry history adds verified economics
for 123 contests and actual receipts for 172 entries. See the
[entry-history update](#september-15-update-entry-history-and-verified-prize-outcomes)
below. The original analysis is preserved, with two payout-limit passages and
the date-span description corrected where directly contradicted.

**Read this after `outputs/standings_research_2026-09-14/REPORT.md`, not
instead of it.** That report was written earlier the same day, covers the same
inbox, and is the primary document. It has two things this pass does not: matched
contest economics (fees, archetypes, paid-place records checked against
`dk_contest_paid_places.json`) and a date-balanced bootstrap with
multiple-comparison correction, which is the stricter and more honest inference
frame. Nothing here overwrites it. This pass ran independently from raw exports
and is worth keeping for five things the first pass does not contain, plus one
correction it applies to this one.

**Labels.** Everything below is a deterministic descriptive statistic of an
observed contest result, or a labeled prior derived from one. No ROI,
profitability, win rate, cash rate, or probability claim. "Top 1%" and "top 20%"
are rank-percentile bands computed from the standings. The exports carry no
payout table and the first pass established that these 235 contest IDs have zero
overlap with the old paid-places reference. The September 15 entry-history
update now supplies paid places for 123 of these contests and verified receipts
for 172 entries. The original percentile analyses remain rank-only: **top 20%
is not cash**. The sample is satellite-heavy (177 satellites/supersatellites,
58 GPPs, median entry fee $0.25 per that report), where winning a ticket and
winning cash are different outcomes. The new addendum reports observed receipt
accounting separately from modeled returns or future probabilities.

**Session constraint.** `device_bash` could not mount the folder ("no Plan9 drive
shares mounted"), the known post-2026-09-08 Windows condition. The mine ran in
the container on staged copies. The ARCHIVE claim could not be taken, so nothing
was written to the ledger, registry, or archive tree. The inbox move is handed
back as a copy-paste block.

---

## What this pass corroborates

Independent parse, independent corpus construction, same conclusions on the two
findings the first pass leads with. That is worth something on its own, because
the two passes share no code.

| Finding | First pass (date-balanced, 11-12 dates) | This pass (pooled, contest- and slate-clustered) |
|---|---|---|
| Classic five-hitter primary stack overrepresents in top 1% | +11.9 pp on a 51.0% base, interval +3.9 to +18.9 | lift 1.124, CI [1.036, 1.202] contest-clustered, [1.035, 1.205] slate-clustered |
| Avoiding a hitter facing your own pitcher | +14.1 pp for first place, interval +4.2 to +26.4 | the inverse flag (pitcher opposing own stack, 13.2% of the field) lifts 0.802 [0.699, 0.902] at top 20% and 0.726 [0.482, 1.037] at top 1% |
| Showdown 5-1 split | +11.7 pp, interval -3.2 to +26.9 | lift 1.552, CI [1.277, 1.787] contest-clustered, [1.217, 1.815] slate-clustered |
| Secondary shape inside the 5-stack family | 5-2-1 and 5-3 both positive, both intervals cross zero, order reverses with slate size | 5-2-1 1.040 [0.995, 1.101], 5-3 0.937 [0.833, 1.044], 5-1-1-1 0.979 [0.846, 1.147]; all three CIs contain 1.0 and each other |

Where the two disagree on confidence, **the first pass is right and this one is
optimistic.** It balances dates equally and corrects for 52 comparisons; this one
pools entries and prices each test on its own. Pooling lets a 47,562-entry
contest outvote a 23-entry one, and the first pass's own sensitivity row makes
the point directly: the five-stack effect is +11.9 pp pooled and +4.0 pp when
restricted to the largest contest per slate. Treat the CIs below as ranking
evidence, not as passing a threshold.

---

## What this pass adds

### 1. The exact mechanism behind the ownership-column discrepancy

The first pass records the symptom: "summing the supplied player/position table
differs from reconstructed ownership by more than one percentage point in 103
contests and more than five in 26", attributed to blank-entry denominators and
position/role handling. Here is the mechanism, which is narrower and fully
determined.

**DK emits one ownership row per player, and that row carries the usage of one
roster slot only.** For a player eligible at two positions, the other slot's
usage is absent from the column entirely.

| Contest | Player | DK `%Drafted` | Recomputed from entry block | Field |
|---|---|---|---|---|
| 194225041 | Shohei Ohtani (row labelled 1B) | 13.75% | 27.50% | 80 |
| 193880063 | Bryson Stott (row labelled 3B) | 12.71% | 25.42% | 118 |
| 194016640 | Kyle Schwarber (row labelled OF) | 11.86% | 23.73% | 59 |

66 of 11,564 classic player-contest rows are understated by more than 1.5 points
(median 3.28, max 13.75). **It never overstates.** It touches 42 of 118 classic
contests and 6 of 117 showdown contests: rare per player, common per contest.

Separately, some exports key the block per roster slot (separate CPT and UTIL
rows in showdown, separate position rows in classic) and others key it per player
with combined usage. Summing rows by player name is correct under both.

Recomputation is exact, not an estimate: for single-eligibility players it
reproduces `%Drafted` to within 0.02 points at every field size tested, including
47,562 entries.

Three consumers inherit the bias, and the first one is the operational cost:

1. `docs/cowork_archival_runbook.md` step 7 reads "ownership recompute self-check
   within 1.5 points of `%Drafted`; if it fails, the parse is wrong; fix before
   archiving." On 42 of 118 classic contests a **correct** parse fails that
   check. The instruction sends a session to fix a parser that is already right,
   or to force the archive through.
2. `extract_winner_archetype`'s `chalk_index` is defined as the mean `%Drafted`
   of the winner's players from the embedded table. On any slate with a two-way
   player or a popular multi-eligible bat it reads low.
3. Anything trained or graded on the archived column carries a bias concentrated
   on exactly the players most likely to be multi-eligible.

### 2. Two joins that turn an undated export into a minable one

`--auto-salary` resolves a price list from the manifest, then in-date
directories, then a repo-wide scan, and the first two tiers need `--slate-date`.
For 235 exports with no manifest entry and no known date, all three tiers are
unavailable. Two deterministic joins recovered slate identity and prices.

**Slate identity from FPTS agreement.** Two contests on the same slate assign
identical actual fantasy points to every shared player. Union-find over pairwise
agreement (5+ shared players, max absolute difference below 0.011) partitioned
235 contests into 83 groups with no disagreement inside any group. It needs no
date, no salary file and no contest metadata, it is exact rather than a
similarity threshold, and it still groups a contest whose price list cannot be
found with its siblings.

**Price list from the salary cap.** The correct day's price list is the one under
which every sampled entered lineup costs $50,000 or less **and the median lineup
spends near the cap**. Under the chosen lists, 0 of 244,286 priced entries breach
the cap; median classic spend $49,800, median showdown $49,700.

Two traps worth recording, because both bit before they were caught:

- Legality alone does not discriminate. Many days' price lists keep a six-player
  showdown lineup under $50,000, which left 66 of 83 groups ambiguous. The
  near-cap median is what separates them, because entrants spend the cap; a
  candidate whose median lineup spends $33,000 is a different slate's list that
  happens to contain these names.
- **A slate that ran both formats is one FPTS group but two price lists.** DK
  prices Classic and Showdown separately. Picking one list per group silently
  mis-priced 19 showdown groups until the pick was split by format. This is
  likely the same condition behind the first pass's "seven Showdown contests for
  LAD at COL on August 18 lack a compatible salary file."

Dates are **not** recovered. Only 17 of 83 groups have exactly one candidate date
under the cap test. A `date_confident` flag ships with the artifacts; trust the
flag, not the date. The first pass's dates, derived from matched contest records,
are the authority.

### 3. Ownership structure: where the variance actually is

The first pass recommends, qualitatively, to "fit team and stack popularity as
well as individual players." Here is the size of that.

Median within-contest R-squared for batter ownership, 51 classic contests of at
least 100 entries, 16 slates:

| model | median R² |
|---|---|
| log salary only | 0.166 |
| log salary + that team's share of the field's primary stacks | 0.388 |

This is a variance decomposition of realized ownership, not a forecast: the team
share is measured from the same contest. It says where the structure lives. A
batter's ownership is mostly a function of how many entrants stacked his team and
only secondarily of his price inside that team, so a player-level model is
fighting the wrong problem. The matching shape is hierarchical: predict each
team's stack share, then allocate within the team.

It is also a cheaper target. Team stack share is a 12-to-30 number vector per
slate instead of 200 player numbers, it is far more stable, and this mine can
produce the realized value for every archived contest, so the grade loop extends
to it without new data.

Against the flat-budget baseline, a log-salary fit reduces mean absolute
ownership error by 10.6% for batters (5.60 → 5.02 pts) and 25.2% for pitchers
(12.03 → 8.33 pts). For bats, price buys about a tenth of the error.

### 4. A per-player popularity prior that persists across slates

Residual of each player against the within-contest log-salary fit, averaged per
player, slates split into two halves:

| players | Pearson | Spearman |
|---|---|---|
| ≥2 contests per half (n=346) | 0.489 | 0.364 |
| ≥3 contests per half (n=298) | 0.467 | 0.414 |
| ≥5 contests per half (n=197) | 0.423 | 0.430 |

A player's tendency to be over- or under-owned relative to his price persists
across slates at r ≈ 0.42 to 0.49. Tail examples in points of ownership: Andy
Pages +14.8, Shohei Ohtani +14.1, Byron Buxton +10.6; Logan Gilbert -10.1,
Jasson Dominguez -9.7, Paul Goldschmidt -7.7.

One exponentially weighted per-player term over the archive captures it. Carry
the caveat with it: part of this is team-stack popularity leaking into a player
label, and this pass has not separated the two. Usable as a prior, not yet
evidence of a player-specific effect independent of his team.

### 5. Field size is a one-parameter transfer, and the parameter is measured

For the 17 slates carrying two classic contests whose field sizes differ by at
least 5x, regressing the large field's realized ownership on the small field's:

- slope **0.76** (IQR 0.68 to 0.81)
- intercept **+2.03** points
- correlation 0.906 (median)

`own_large ≈ 0.76 × own_small + 2.0`. The large field is a flattened copy of the
small one: top-5 ownership share falls 237 → 207 points, max single player 66% →
58%. CLAUDE.md already forbids pooling ownership across archetype and field size.
This puts a number on the transform between them, which makes a cross-archetype
prior usable rather than merely forbidden. It is also the general form of the
first pass's Kaelen Culpepper example (28.0% in a mini-MAX, 47.5% in a
supersatellite on the same slate).

### 6. Stacking the most-popular team is the clearest own-goal in the corpus

Entries with a 4+ primary stack, bucketed by that team's share of the field's
primary stacks inside the same contest:

| quintile | median share of field | top-20% lift | top-1% lift [contest-clustered CI] |
|---|---|---|---|
| Q1 coldest | 3.4% | 1.111 | 1.795 [0.959, 2.596] |
| Q2 | 5.9% | 1.157 | 0.937 [0.647, 1.223] |
| Q3 | 7.5% | 0.891 | 0.777 [0.386, 1.290] |
| Q4 | 11.6% | 1.434 | 1.245 [0.667, 1.918] |
| Q5 chalkiest | 18.6% | 0.407 | **0.246** [0.021, 0.719] |

The reading is asymmetric and that is the point: **avoiding the most-stacked team
is the supported half; chasing the least-stacked team is not.** Q5 is the only
bucket whose CI sits clearly below 1.0 in both bands. Q1's top-1% CI crosses 1.0
under both contest and slate clustering. The middle three are noise.

This is distinct from `max_primary_stack_exposure_pct`, which caps Ben's own
exposure to one team. This is about the **field's** concentration on a team,
which the engine does not currently measure at build time, and which the
ownership work in section 3 would produce as a by-product.

### 7. The top 1% is not uniformly contrarian

Within-contest percentile rank of each feature by finish band (0.50 = field
median on that feature), classic:

| finish band | n | total ownership | highest-owned player | the other nine | players under 5% owned |
|---|---|---|---|---|---|
| top 1% | 2,702 | **0.450** | **0.518** | **0.447** | 1.96 |
| 1-5% | 10,446 | 0.493 | 0.532 | 0.489 | 1.69 |
| 5-20% | 39,083 | 0.534 | 0.539 | 0.530 | 1.52 |
| 20-50% | 78,090 | 0.532 | 0.525 | 0.530 | 1.47 |
| bottom half | 128,413 | 0.472 | 0.470 | 0.475 | 1.59 |

Two structures, and the second is the useful one.

- Total ownership is a **barbell**. The 5-50% band is the chalkiest part of the
  field; the top 1% and the bottom half are both below median. This is consistent
  with the first pass finding that neither ownership extreme is a reliable winner
  recipe.
- The top 1%'s **highest-owned player sits above the field median (0.518) while
  its other nine sit at 0.447**. The shape is one chalk anchor plus a low-owned
  remainder, not nine contrarian picks. In large fields the top 0.5% carries 2.20
  players under 5% owned against a field average of 1.65, and 154.6 total
  ownership points against a field average of 161.0.

**Showdown runs the other way.** Total-ownership percentile by band: top 1%
0.527, 1-5% 0.547, 5-20% 0.560, 20-50% 0.559, bottom half 0.442. Every finishing
band above the median is *more* owned than the field, including the top 1%. Six
slots in one game does not leave room for contrarian construction to pay.
Importing classic leverage instincts into showdown is a mistake this corpus can
see.

### 8. Ben's own entries, and the one gap worth acting on

Identified by fingerprint, not assumption: the 2026-08-19 upload manifest names
five deliveries spanning 30 contests, and `bleeski` is the only entry name
present in every contest of all five. Ben has since confirmed it.

579 entries across all 235 contests, 240 classic and 339 showdown.

| band | Ben's share | uniform field |
|---|---|---|
| top 1% | 1.6% | 1.0% |
| top 5% | 6.0% | 5.0% |
| top 20% | 17.8% | 20.0% |
| top 50% | 44.6% | 50.0% |

Median finish percentile 0.513 classic, 0.574 showdown. The distribution is
tail-weighted: above uniform at the top 1% and 5%, below it at 20% and 50%. In a
satellite-heavy sample that is the intended shape, not a defect, and 579 entries
is an observed distribution rather than evidence of edge.

Structural profile, within-contest percentile rank (0.50 = field median):

| | total ownership | highest-owned player | players <5% owned | salary used | primary stack | bring-back |
|---|---|---|---|---|---|---|
| classic | 0.386 | 0.366 | 0.522 | 0.615 | 0.422 | 0.519 |
| showdown | 0.372 | 0.365 | 0.479 | 0.486 | 0.735 | 0.342 |

Three readings, in descending order of how much I would act on them.

1. **The classic stack mix is inverted relative to the field and to both passes'
   strongest classic finding.** Ben plays a 4-stack in 81.2% of classic entries
   against a field share of 22.1%, and a 5-stack in 15.4% against 56.5%. Both
   passes put the five-hitter primary stack as the most consistent classic
   signal. `max_primary_stack_exposure_pct` caps exposure to one team, not stack
   size, so this is coming from the thesis ladder or the stack plan rather than
   the caps. His own 240 classic entries cannot settle it (195 are 4-stacks, 4
   top-1% finishes); the 118-contest field sample can.
2. **He under-weights the chalk anchor.** Classic highest-owned-player percentile
   is 0.366 while the top-1% band sits at 0.518. He is contrarian on total
   ownership at 0.386, which matches the archive, and *also* contrarian on the
   one slot where the archive says the top 1% is not.
3. **Showdown bring-back at 0.342 with primary concentration at 0.735.** The
   concentration is right and matches the 5-1 finding. Worth confirming the 5-1
   preference is deliberate, since it is the strongest single effect in either
   pass.

Where he is already right: primary-stack popularity quintile Q1 at 34.9% against
a field 20%, Q5 at 13.4% against 20%, which is exactly the direction section 6
supports.

---

## Correction this pass applies to itself

The first pass flags namesake ambiguity (principally the two Max Muncys) and
excludes ambiguous records from identity-dependent comparisons. **This pass does
not.** It assigns team by majority vote over 80 price lists, which silently sends
both Max Muncys to LAD.

Measured exposure: 40 of 1,455 names map to more than one team across the staged
price lists, touching 256 of 14,524 player-contest rows (1.76%) but **130 of 235
contests**. Restricting to the 31 classic contests with no ambiguous name at all
(17,013 entries) keeps the direction and widens the interval, as expected:

| primary stack | all 118 contests | 31 namesake-clean contests |
|---|---|---|
| 3 | 0.821 [0.657, 1.041] | 0.775 [0.228, 0.979] |
| 4 | 0.995 [0.880, 1.094] | 1.026 [0.757, 1.253] |
| 5 | 1.124 [1.036, 1.202] | 1.073 [0.973, 1.529] |

The ordering survives; the significance does not, on 17k entries. Anyone reusing
this pass's artifacts for identity-dependent work should join on DK player ID
rather than name, as the first pass does.

---

## Limits

- 235 contests, 83 FPTS-derived groups in this pass, **14 calendar dates
  (August 14–27, 2026)**, satellite-heavy and low-stakes. The dates agree with
  the first pass and the new exact history joins. Every lift here is one
  archive, not a law.
- CIs are pooled and clustered by contest or slate. The first pass's
  date-balanced, multiple-comparison-corrected frame is stricter and reports that
  **none** of its 52 construction comparisons clears a 5% adjusted threshold.
  Both statements are true of the same data; prefer the stricter one when
  deciding whether something is established.
- 56 contests have no verified price list, so salary-dependent sections exclude
  them. Ownership, stack-shape and finish sections use all 235.
- Team assignment is a name-majority vote and carries the namesake error above.
- Updated September 15: paid-place counts and own-entry receipts now cover
  123 satellite/supersatellite contests and 172 own entries. The other 112
  contests, including all 58 GPPs, and 407 own entries still lack matched
  receipts in the supplied file. Full payout schedules remain unavailable;
  the new addendum distinguishes verified cash, ticket value, and paid-rank
  analysis.
- Section 4's per-player residual is not separated from team-stack popularity.

## Open flags

- **[BEN]** Whether the 4-stack default in classic is a deliberate strategy
  choice (in which case section 8.1 is an argument to revisit) or an artifact of
  the thesis ladder (in which case it is a bug). This is the one question in the
  mine that a person has to answer.
- **[BEN]** Two standings research outputs now exist for 2026-09-14, written
  minutes apart by separate sessions. If that was not intentional, worth knowing
  why a second one started.

## Artifacts

Written to `outputs/standings_research_2026-09-14_secondpass/`, alongside and not
over the first pass:

- `contest_summary_2026-09-14.csv` — one row per contest: slate group, format,
  field size, distinct lineups, duplication, winning score, top-1% and top-20%
  cutoffs, resolved price list, date-confidence flag.
- `player_ownership_2026-09-14.csv.gz` — one row per player-contest: recomputed
  ownership, DK's column, the gap, captain ownership, actual points, team, salary.
- `entry_features_2026-09-14.parquet` — one row per entry: rank, percentile,
  stack shape, primary and secondary stack, bring-back, pitcher-vs-stack flag,
  ownership aggregates, salary used, duplicate count.
- `slate_resolution_2026-09-14.csv` — the 83 groups, their contests, candidate
  dates, chosen price list, confidence flags.

Backlog fragments in `docs/backlog_inbox/`, dated 2026-09-14:

1. `ARCHIVE_ownership-truth-is-the-entry-block-not-dk-column`
2. `ARCHIVE_fpts-agreement-identifies-slates-and-price-lists`
3. `BUILD_pitcher-opposing-own-stack-is-a-constraint`
4. `BUILD_showdown-5-1-split-and-classic-stack-size`
5. `DEV_ownership-model-should-be-hierarchical-with-a-player-prior`

---

## September 15 update: entry history and verified prize outcomes

This update adds new evidence from Ben's supplied
[`draftkings-contest-entry-history.csv`](C:/Users/benja/Downloads/draftkings-contest-entry-history.csv).
It preserves the September 14 analyses and changes only their now-contradicted
blanket payout limitation and the incorrect five-week date description. The
earlier ownership and construction findings remain exploratory. This CSV does
not validate a model or establish a future strategy advantage.

### What this file unlocks, and what it does not

**We can now measure verified ticket awards for part of the original portfolio
and study the actual paid-place boundary for those contests. We still cannot
measure GPP cashing or the full portfolio's economic result.**

The supplied file contains 1,403 entries across six sports. Of its 1,057 MLB
rows, 785 are Classic, 261 are Showdown Captain Mode, and 11 are Best Ball.
The analysis below uses the 1,046 Classic/Showdown rows, all dated in 2026.
The 11 Best Ball records and the other sports are excluded from these results.
Pooling the entire file would mix formats, years, and payout channels.

Matching to the original **235 usable contests** yields **123 contests and
172 of Ben's entries**. Each joins on both Contest ID and Entry ID. Published
rank, contest date, format, and field size agree. Scores agree to the history
file's two-decimal precision. Duplicate entry keys and conflicting contest
economics were not found.

| Format | Original own entries | History matched | Payout records still missing | Matched contests |
| --- | --- | --- | --- | --- |
| Classic | 240 | 105 | 135 | 60 |
| Showdown | 339 | 67 | 272 | 63 |
| Total | 579 | 172 | 407 | 123 |

The earlier count of **579 entries remains correct**. It was independently
recounted from the raw standings, using the username reached by all 172 exact
history joins. The new export is partial coverage of that portfolio, not a
replacement population. A missing row is not a zero payout.

Coverage is heavily selected: **all 123 matched contests are satellites or
supersatellites**. They comprise 60 Classic and 63 Showdown contests. The file
covers **none of the original 58 GPPs**, and leaves another 54 satellite contests
without matched economics. The export's selection mechanism is not recorded, so
do not infer why these contests are absent or generalize the receipt totals to
the full account.

The earlier first-pass report's “no payout evidence” conclusion was correct for
the sources it had on September 14. This supplied CSV changes that conclusion
for these 123 contests. Its `Places_Paid`, `Winnings_Non_Ticket`, and
`Winnings_Ticket` fields are new evidence; the old 100-contest reference file
still has no overlap with the original 235.

### 1. The measured objective is qualification, not a generic percentile

The matched contests pay **one place in 104 contests, two places in 14, and five
places in five**. Their paid-place fraction ranges from **0.46% to 6.67%** of the
field, with a median of **4.35%**. None pays 20% of its field. Four pay fewer than
1% of their field.

This makes the percentile mismatch concrete:

- **29 of the 172 matched own entries finish in the top 20%, but only six receive
  an award.** The other 23 receive neither recorded cash nor a ticket.
- **All six verified awards lie outside a literal `Place / field_size <= 1%`
  filter.** Five are first-place finishes in fields of 23 or 95; the sixth is
  third in a 118-entry contest paying five places. With fewer than 100 entrants,
  even first place has `Place / field_size > 1%`. The first pass correctly
  excluded such fields from top-1% analysis; that exclusion should not exclude
  their actual qualification outcomes.
- Exact paid-place counts therefore add a useful target distinct from top-1%
  and top-20% placement. Store verified receipt outcomes for one's own entries,
  and use the exact contest boundary for field analysis.

**The operational implication is to condition evaluation on the actual prize
objective.** A one-ticket contest, a five-ticket contest, and a cash GPP cannot
share one fixed-percentile definition of success. This updates how to measure
the system, not which untested stack constraint to impose.

### 2. What Ben actually received in the matched cohort

| Matched original-window entries | Entries | Listed fees | Cash winnings | Ticket value recorded |
| --- | --- | --- | --- | --- |
| Classic | 105 | $18.60 | $0.00 | $30.00 |
| Showdown Captain Mode | 67 | $14.35 | $0.00 | $30.00 |
| Total | 172 | $32.95 | $0.00 | $60.00 |

There are **six ticket-awarding entries: three Classic and three Showdown**.
The $60 recorded ticket value consists of **two $20 awards and four $5 awards**.
The two $20 awards account for two thirds of the recorded value, so the result
is concentrated in a few outcomes.

Cash winnings minus listed fees equal **−$32.95** for this matched cohort.
Adding ticket face value produces **+$27.05**, but that arithmetic is **not
realized cash profit**. Ticket redemption, expiration, downstream contest
results, entry-fee funding, and actual bank transactions are not supplied.
`Entry_Fee` is the listed contest fee, not proof that the fee was paid from cash.
Do not count a ticket at face value and then count its downstream result as an
independent additional return without linking the two entries.

This CSV also supplies 11 entries in nine other contests dated August 14–27
that were not in the original 235-contest study. They add **$1.85 in listed fees
and one $5 ticket award**. That is why the all-history date-window total is
183 entries, $34.80 in fees, and $65 in recorded tickets rather than the
matched-study total above. Those extra entries are kept out of the original
field/stack comparisons.

### 3. The six verified award lineups

These use the first pass's same-date, identity-checked lineup features, not the
second pass's majority-team assignments. All six award lineups have complete
team/salary joins and no unresolved same-name player. None is tied across the
paid-place boundary.

| Date | Contest ID | Entry ID | Finish / field | Paid places | Shape | Captain type | Recorded ticket value |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-08-19 | 194017297 | 5223575738 | 1 / 23 | 1 | 4-2-2 | N/A | $5.00 |
| 2026-08-24 | 194282827 | 5229279591 | 1 / 23 | 1 | 5-1 | Pitcher | $20.00 |
| 2026-08-25 | 194370266 | 5230565026 | 1 / 23 | 1 | 5-1 | Hitter | $5.00 |
| 2026-08-26 | 194428622 | 5231484019 | 3 / 118 | 5 | 4-1-1-1-1 | N/A | $5.00 |
| 2026-08-27 | 194485739 | 5232595489 | 1 / 23 | 1 | 5-1 | Hitter | $5.00 |
| 2026-08-27 | 194487179 | 5232476578 | 1 / 95 | 1 | 4-2-1-1 | N/A | $20.00 |

The commonalities are informative but do not settle a strategy:

- **Every award lineup is unique in its own contest.** All three Showdown
  winners are 5–1, with one pitcher captain and two hitter captains. This
  supports retaining captain identity in duplicate measurement and leaves no
  basis for a universal pitcher-captain requirement.
- **All three Classic ticket winners use a four-hitter primary stack.** This
  does not overturn the broader five-stack/top-1% finding. Among the 105 matched
  Classic entries, Ben submitted **88 four-stacks, 14 five-stacks, and three
  three-stacks**. Three awards from 88 attempts versus none from 14 is too little
  and too imbalanced to establish a stack-size advantage.
- Ben submitted **61 Showdown 5–1 entries, one 4–2, and two 3–3** in this
  matched cohort; three other Showdown entries lack a compatible salary join.
  Three 5–1 awards therefore reflect a portfolio already overwhelmingly 5–1.
  They cannot independently validate that concentration.
- One winning Showdown entry spent **$47,200**, leaving $2,800 unused. It is a
  concrete counterexample to “a ticket-winning lineup must spend almost every
  dollar,” not evidence for imposing a large salary-left target. The other
  winning lineups vary in salary and ownership as well.

The new receipts strengthen the case for **objective-specific, controlled
testing**. They do not justify replacing the existing five-stack hypothesis with
a four-stack rule, or increasing an already concentrated Showdown 5–1 mix.

### 4. Full-field construction at the verified paid-place boundary

The 123 matched fields contain **5,859 entry rows**, with **5,817 complete
lineups**, and **157 listed paid positions**. These are mostly small fields,
which is a different population from large-field GPP top-1% analysis.

The history contains Ben's actual receipts, not every entrant's receipts or a
full payout schedule. To avoid inventing opponents' ticket/cash awards, the
field target here is **paid-position weight**. If a cutoff crosses a tie, the
remaining paid positions are divided equally across the tied entries for this
statistical calculation. The weights sum to exactly 157. They are not an
assertion about how DraftKings settled that tie.

Three contests have a boundary tie: **193708561, 193774263, and 194182641**.
Each lists one paid place and has two entries tied first. The raw inclusive
rank criterion identifies 160 entries across all matched contests, rather than
157 paid positions. Opponents' exact awards in those ties remain unknown. Ben's
six award entries do not have this ambiguity.

The table applies the first pass's 95% complete-lineup and salary-join coverage
gates, excludes known name collisions from ownership/duplication comparisons,
and averages contests within slate, slates within date, and dates equally.
Intervals resample calendar dates 5,000 times. These new comparisons are
exploratory and are **not adjusted for multiple comparisons**.

| Characteristic | Share of comparable field | Share of paid-position weight | Difference (pp) | Pointwise 95% interval (pp) | Contests / dates |
| --- | --- | --- | --- | --- | --- |
| Classic four-hitter primary stack | 28.2% | 34.2% | +6.0 | -10.2 to +22.9 | 50 / 12 |
| Classic five-hitter primary stack | 47.1% | 52.9% | +5.9 | -12.7 to +25.5 | 50 / 12 |
| Classic 5–2–1 | 21.9% | 27.2% | +5.3 | -6.5 to +18.7 | 50 / 12 |
| Classic 5–3 | 19.2% | 21.5% | +2.4 | -14.5 to +23.4 | 50 / 12 |
| Classic: no hitter against own pitcher | 74.3% | 88.5% | +14.2 | +4.1 to +26.8 | 50 / 12 |
| Showdown 5–1 | 42.3% | 50.0% | +7.7 | -8.8 to +21.8 | 56 / 11 |
| Showdown 4–2 | 36.3% | 35.4% | -1.0 | -11.5 to +14.2 | 56 / 11 |
| Showdown pitcher captain | 54.9% | 57.5% | +2.6 | -10.4 to +13.8 | 56 / 11 |
| Showdown unique lineup | 93.0% | 100.0% | +7.0 | +2.9 to +12.6 | 56 / 11 |

**Neither the Classic four-versus-five choice nor Showdown 5–1 or pitcher
captain is established by this paid-position sample.** Their intervals are wide
and include zero. Five-stack and 5–2–1 remain reasonable hypotheses, not verified
ticket-winning prescriptions. Avoiding hitters against one's own pitcher
remains directionally favorable. Unique Showdown lineups occupy all of the
paid-position weight in the quality-filtered sample, but the high field
uniqueness and small fields limit how much new information that provides.

Sensitivity matters: the Showdown 5–1 difference is **+7.7 percentage points**
under date balancing but **−4.8 points** when retaining only the largest matched
contest per slate. Classic five-stacks are about **+3.2 points** in one-paid-place
contests and **+11.5** in multiple-paid-place contests; those are small,
nonrandom subsets. These changes argue against treating a single pooled lift
as a portable strategy parameter.

### 5. The broader receipt history cautions against extrapolating a good block

For 2026 MLB Classic and Showdown entries actually present in this file:

| Receipt cohort in this file | Entries | Listed fees | Cash winnings | Ticket value recorded | Cash + ticket value − fees |
| --- | --- | --- | --- | --- | --- |
| 2026 before August 14 | 727 | $136.60 | $0.00 | $100.00 | $-36.60 |
| August 14–27 | 183 | $34.80 | $0.00 | $65.00 | $30.20 |
| August 28–September 14 | 136 | $25.00 | $1.67 | $10.00 | $-13.33 |

The last column is labeled arithmetic with ticket face value, not realized
profit. The 2026 before-August-14 cohort begins on April 11. The August 14–27
window includes the nine extra contests described above. The later block
contains 15 playing dates and has no automatic linkage to the original
lineup-feature sample.

Across all 1,046 included 2026 Classic/Showdown entries, the file records
**$196.40 in listed fees, $1.67 in cash winnings, and $175 in ticket value**.
The favorable original-window ticket arithmetic does not persist in the later
block. This is a reason to evaluate on additional dates and complete receipt
coverage, not evidence that a particular engine change caused a decline.

One row also shows why payout channels must be observed separately from contest
names: on **September 3, contest 194932981**, a Showdown **satellite** records a
first-place finish with **$1.67 in non-ticket winnings and no ticket**. The file
does not establish the settlement mechanism. A classifier that turns every
satellite award into a ticket would misclassify this observed receipt.

### 6. What this adds to the ownership and evaluation models

This file has no player list or projected ownership, so **it does not directly
repair ownership estimates**. It adds useful exact contest context and outcome
labels when joined to the standings:

1. **Use verified contest facts.** Attach filled field size, listed fee, paid
   places, paid-place fraction, and prize pool to each Contest ID. Keep the full
   payout curve, max-entry rules, and ticket settlement terms explicitly missing
   where not supplied. A prize-pool total and paid-place count do not specify
   the payout curve.
2. **Distinguish outcome targets.** Record cash receipt, ticket receipt, cash
   winnings exceeding the listed fee, finish rank, and paid-place-boundary
   performance separately. Use actual receipts for own-entry evaluation. Do not
   treat no history row as no payout.
3. **Separate ticket acquisition from conversion.** Preserve the awarded ticket
   value, destination/use restrictions, redemption Entry ID, downstream cash
   result, and expiry. That allows a later accounting analysis without double
   counting face value and redemption proceeds.
4. **Condition model validation on the contest objective.** The 123 new labels
   principally inform small-field satellite evaluation. They do not supply
   GPP cash labels, validate ownership in cash contests, or justify learning one
   transformation for every contest family.
5. **The next data gap is specific.** Obtain payout-history rows for the
   **407 unmatched own entries**, especially the **58 original GPP contests**,
   plus exact full-field schedules where duplicate/tie economics are to be
   modeled. Preserve the 172 verified rows as their own completed subset.

No optimizer, ownership model, ledger, registry, archive location, or original
standings file was changed as part of this update. The instructions quoted in
the September 14 document about archival or inbox movement were treated as
historical document content, not authorization to execute them.

### Source, verification, and supporting evidence

- Source: `C:\Users\benja\Downloads\draftkings-contest-entry-history.csv`.
- Source SHA-256: `84ce7a814de29f8939e5ecf7b60a5f32844dfe7c8d079910bb5c1132c9cba6d4`.
- Join keys: `Contest_Key` to Contest ID and `Entry_Key` to Entry ID; identifiers
  stay as strings. Currency was parsed in integer cents. Five score differences
  are only rounding/float representation, all within 0.005 points; none changes
  the published ranks.
- All **235 original usable standings exports** were found in their current
  archive/processed locations and verified against the first pass's original
  file or CSV-member hashes before reusing its entry features. Their relocation
  predated this update. None was moved or modified by this analysis.
- Thirteen analysis checks passed: source preservation, exact entry/contest
  matching, own-identity reconciliation, the original 579-entry count,
  metadata/rank/score reconciliation, exact currency totals, paid-position
  weights, and absence of own-entry boundary ties.

Supporting files are in
`C:\Users\benja\Documents\Claude\mlb-dfs\outputs\standings_research_2026-09-15_history`:

- `matched_contest_economics.csv` — the 123 matched contest records.
- `matched_own_entry_results.csv` — the 172 exact matched entries and their
  independently joined lineup features and actual receipt channels.
- `paid_position_feature_results.csv` — effects, pointwise intervals, coverage,
  and one-place/multiple-place/largest-contest sensitivities.
- `followup_summary.json` — cohort definitions, accounting totals, award details,
  boundary ties, and explicit coverage gaps.
- `source_relocation_verification.json` and `verification.json` — source hash and
  reconciliation evidence.

**Preservation note.** The existing second-pass text is retained. The only
replacement passages are the blanket absence-of-payout wording and “roughly
five weeks,” which directly conflict with the new matched evidence. The
historical strategy findings, uncertainty discussion, earlier own-entry count,
and first-pass report were not overwritten.
