# 2026-10-14 2000_1g_sd (MIL@LAD NLCS G3, Showdown): postseason priors, for ARCHIVE to grade

Delivered: `outputs/2026-10-14/DKEntries_showdown_2000_1g_sd_REVIEW_GRADE_final.csv`, sha256 0fc959426dfd (review-grade,
operator permutation of ladder build sd_87f55d515c4c, no lineup changed; record `data/deliveries/2026-10-14/2000_1g_sd_norun_0fc959426dfd.json`).
17 entries: Relay Throw sat 196718330 x2, NBA sat 196718334 x2, NFL Millionaire sat 196749605 x7, Solo Shot 196719588 x1,
Daily Dollar SE 196719594 x1, $100 Dime Time 196744625 x2, $300 Dime Time 196746443 x2.

## Inputs (18:34-18:43 ET)
- Series: MIL led 2-0 (G1 2-1, G2 7-4); off day 10/13. Odds cbs LAD -174 / MIL +150, si -180 / +148, total 7.5 (paste; odds API 401). No-vig LAD 0.614.
- Weather: 84F, clear, wind 1 mph (statsapi). Both nines DK `Starting`, matched the statsapi feed. Ohtani batting 6th vs LHP; Muncy and Yelich sat.
- Both starters LHP. Starter IP this series: Skubal 5.0, Misiorowski 4.1, Yamamoto 2.2, Henderson 4.0.

## Priors the build carried
| input | value | reason |
|---|---|---|
| Snell Base | 15.9 (APPG 18.7 x0.85) | last two starts 4.0 IP / 77 NP and 3.2 IP / 90 NP; W needs 5 IP |
| Gasser Base | 11.0 (APPG 13.8 x0.80) | NLDS 4.0 IP on 56 NP; MIL starters 4.1 and 4.0 IP this series |
| platoon splits | ops_vs_L blended 50/50 with ops_overall | both starters LHP and ~half of PA go to mixed-hand pens; the per-hitter factor otherwise prices all PA vs the starter |
| `--keep-arms` | off | R484 fragment (2026-10-13): kept relievers are unconditioned UTIL fill |

## Questions for grading (observed outcomes only)
1. Realized IP for Snell and Gasser against the 0.85 / 0.80 factors.
2. Field captain share for pitchers vs hitters. Ours was 7 of 17 pitchers (Snell 4, Gasser 3); construction_shadow's regular-season band is 48-52.
3. Was Rojas pinch-hit for once a RHP entered (.505 OPS vs RHP, Muncy on the bench)?
4. Winner's captain and Turang's captain share: DK Network recommended Betts and Turang captains; the build had Turang at 0 captains (split .620 vs LHP).
