# 2026-08-08 tranche analysis — 31 contests, 4 slates, Classic vs Showdown

Written by ARCHIVE after mining the 2026-08-08 inbox (A-035, A-036, A-037).
Everything here is an observed outcome or a deterministic descriptive
statistic, conditioned on contest archetype and field size per Section 2 of
the ledger. None of it is ROI, a win rate, a cash rate, or a probability
claim; nothing auto-applies to builds. Cash figures are cash-only; the
promotional channel stays unmeasured (3.14). Intervals are per-contest means
with a normal approximation, stated as (mean, lo, hi, n).

## 1. What was mined

| slate | format | contests | notes |
| --- | --- | --- | --- |
| 2026-07-29 2138_3g | Classic | 1 | late pull; A-037 |
| 2026-08-05 1905_7g | Classic | 5 | full coverage |
| 2026-08-05 1905_1g_sd STL@NYY | Showdown | 7 | standings_only: no showdown salary file exists anywhere in the repo for this slate |
| 2026-08-06 1235_5g | Classic | 6 | full coverage |
| 2026-08-06 1910_4g | Classic | 5 | standings_only: slate salary never staged AND the delivery is absent from outputs/2026-08-06/upload_manifest.json |
| 2026-08-06 2140_1g_sd SD@ARI | Showdown | 7 | full coverage |

Tranche: 17 Classic + 14 Showdown, 67 own entries, $12.58 fees captured at
mining time, winnings null throughout (entry-history export still ends
2026-07-28). Four additional pulls for the 2026-08-08 1505_3g slate came back
zero-byte because the slate had not locked; quarantined, re-pull after settle.
Archive after this tranche: 270 distinct contests (179 Classic, 91 Showdown).

## 2. Regrades of standing findings (tranche = Classic >=40 full-coverage, n=8, unless stated)

**5-2-1 top-decile lift rebounded as the shape un-crowded.** Tranche lift
+13.6pp (5.6, 21.6, 8) on 21.6% field share. Three-tranche trajectory:
+3.1pp on 25.1% share (07-30), +0.2pp on 29.7% (08-04), +13.6pp on 21.6%
(08-08). Combined archive: +4.5pp (1.7, 7.3, 99) on 21.9%. The 08-04
"crowding decay" read does not survive; lift has moved opposite to the
shape's field share in three consecutive tranches (record-only observation,
three points). Regrade: win-line concentration moves open -> provisional
again. 5-2-1 won 8 of the 12 shape-known Classic tranche contests.

**<=3-primary stays firm-negative, third consecutive tranche.** Tranche
-9.8pp (-18.0, -1.6, 8) on a 31.8% field share; combined -7.4pp
(-9.8, -4.9, 99). No conditioned slice has ever measured it positive.

**4-2-x provisional-negative stands.** Tranche +0.5pp, interval straddles
zero on n=8; combined -1.9pp (-3.3, -0.5, 99).

**Our mix drifted further into the firm-negative family.** Own Classic
tranche entries: 68% 4-primary, 5% 5-primary, <=3-primary share 26.3% —
after 7.0% (07-30) and 21.5% (08-04). The R37 input now has three tranches
pointing the same way: the field's best-performing shape family is the one
we build least, and our largest families are the two negative ones.

**Leverage replicated in direction.** In all 8 conditioned tranche contests a
sub-10%-drafted player finished top-5 in contest FPTS; the winner carried at
least one in 3 of 8; top-decile carry rate 0.15 vs field 0.06. Archive:
winner 46/88, decile 0.33, field 0.13.

**Classic satellite chalk posture took its first counter-tranche.** Archive
winner cum-own delta vs field mean: median +9.0 pts over 135 winners
(chalk-positive). Tranche-only: -23.9 median over 11 winners. The tranche
slates were 4-7 game slates with larger player pools than the small-slate
archive mass, so slate size is a live confounder; the 08-04 format split
stands but the next review should condition satellite chalk on slate size.
Showdown satellite winners stayed sub-field (-3.7 archive, -8.1 tranche),
supersatellites stayed most contrarian (-14.0 archive).

**Salary discipline, same directions again.** Classic winners median $200
left = field $200, ours $100 (tightest). Showdown winners $200 vs field
$300; our archive $300, but our tranche showdown entries ran $100 — we
tightened toward the winner side of that split this week.

**SP #1 pair stays at-share.** Winners used their contest's most-common SP
pair 33/134 (24.6%) against a 20.8% mean field share; tranche 2/11.

**Duplication, re-confirmed and unimproved on our side.** Median
duplicated-entry share by bucket: Showdown 151-500 27.5%, >500 55.9% (winner
itself duplicated in 3 of 6); Classic <=150 ~0%. Own entries duplicated by
the field: Showdown 9/38 tranche (archive 50/260), Classic 0/29 tranche
(archive 7/237). The R10 priors hold; our Showdown dupe exposure did not
improve this week.

## 3. New: cash-line anatomy (winner vs the paid line), 100 contests with observed paid_places, vintage <= 2026-07-28

Bands per contest: winner (rank 1), last-cash (the 3 ranks ending at the paid
line), just-missed (the 3 ranks after it), field median. Chalk is the entry's
within-field cumulative-ownership percentile; primary is the largest team
stack.

| band | Classic satellite (60) | Classic GPP (15) | Showdown satellite (22) |
| --- | --- | --- | --- |
| winner | chalk 32, $300 left, primary 4, duped 5% | chalk 54, $200, primary 4, duped 18% | chalk 31, $100, duped 11% |
| last-cash | chalk 30, $300, primary 4, duped 8% | chalk 40, $500, primary 4 | chalk 31, $100, duped 15% |
| just-missed | chalk 40, $200, primary 5, duped 2% | chalk 64, $200, primary 5 | chalk 39, $300, duped 13% |
| field median | chalk 51, $200, primary 4 | chalk 52, $200, primary 4 | chalk 46, $200 |

Two observed patterns, stated as distributions, not causes:

1. **In satellites, the winner and the last seat look alike** — sub-median
   chalk, looser salary, 4-primary — and the band just outside the line is
   *more* 5-stacked and *more* chalky than the band that got paid. Ceiling
   shapes cluster immediately outside satellite seat lines; the seats
   themselves went to balanced, below-median-chalk builds.
2. **In Classic GPPs the winner is chalkier than the satellite winner**
   (chalk 54 vs 32) and got duplicated in 17.6% of contests. The flat-payout
   and top-heavy formats paid different constructions at the top, which is
   the posture split (3.9) showing up in field data.

## 4. New: Showdown captain anatomy (64 contests with CPT ownership rows)

Winner CPT %Drafted median 14.8 vs field median 13.0 — captains are
at-share among winners, like SP pairs in Classic. The winner used the
top-owned captain in only 22/85 cases (26%). Tranche: winner CPT own median
9.1 (0/8 top-owned) while our own tranche CPT choices ran 15.4 median — this
week we captained chalkier than the winners did. Across the archive our CPT
own median is 12.2, at-field. Observed distribution for the Showdown captain
selection question; no build action derives from one tranche.

## 5. New: the field is mostly the same people

Median share of a Classic satellite field that appears in >=5 archived
contests: 91.3% (Showdown satellites 80.8%). Winners were such regulars in
132/148 Classic and 83/92 Showdown satellite wins. One username appears in
270 of 270 archived contests; the top eight appear in 92+. These micro-stakes
satellite fields are a small, stable, measurable population, which is what
makes the opponent registry and a per-opponent construction prior worth
building (Section 5 adjacency; no model exists yet, so this grades nothing).

## 6. New: family cards (observed, per recurring contest family)

| family | contests | own entries | own pctile med | rank-1s | top-3s | win margin med | dup share med |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Classic $0.25 FFM satellite (~23) | 43 | 43 | 47.6 | 1 | 6 | 4.4% | 0% |
| Classic Relay Throw satellite | 18 | 66 | 31.0 | 1 | 2 | 3.0% | 0.6% |
| Showdown FFM satellite | 41 | 45 | 39.4 | 1 | 7 | 6.1% | 6.9% |
| Showdown penny MEGA qualifier | 33 | 231 | 47.4 | 0 | 1 | 3.7% | 27.5% |

The penny MEGA qualifiers are our largest volume block (231 entries) with
zero observed rank-1s in 33 contests and the harshest duplication
environment (27.5% median duplicated-entry share). Observed outcomes only;
entry decisions stay with Ben and cannot be graded on cash alone while the
promotional channel is unmeasured (3.14).

## 7. Own results, tranche

Classic: satellites median finish percentile 28.6 (archive 43.8),
supersatellites 12.8 (archive 28.2, our weakest Classic family in both
windows), the three >500-field entries all finished in the bottom third.
Showdown: satellites 74.2 (archive 46.9), one satellite rank-1
(193253743, $0.25 FFM STL@NYY), two further top-3s (193253738 3/126,
193296913 3/59), solo shots 85.4/81.6 percentiles. Median
points-gap-to-winner: Classic satellites 41.8% (archive 26.4%), Showdown
satellites 19.1% (archive 30.1%). A strong Showdown week and a weak Classic
week, stated as this tranche's draw, nothing more.

## 8. Data-quality findings filed to docs/backlog_inbox/ (2026-08-08, ARCHIVE)

1. field_miner does not create the --json parent directory; 30 mines failed
   on a fresh archive date until mkdir.
2. An explicit wrong --salary joining 0.0% passes as coverage "full"; the
   wrong-salary gate fires only under --auto-salary. Five 1910_4g contests
   initially archived with join 0.0 before re-mine to standings_only.
3. update_registry runs only when --registry is passed; the runbook says to
   omit the flag and rely on the default, so all 31 mines skipped registry
   accumulation. Rebuild in progress via tools/rebuild_registry.py.
4. awaiting_standings lists contests whose slates have not settled; the four
   1505_3g pulls today came back zero-byte pre-lock.
5. The 1910_4g delivery exists on disk with filled entries but has no
   upload_manifest.json record and no runs/ directory, and its salary file
   was never staged.

Registry rebuild state at write time: resumable via
`python tools/rebuild_registry.py --max-seconds 145`, progress in
`.field_opponent_registry.json.rebuild`.
