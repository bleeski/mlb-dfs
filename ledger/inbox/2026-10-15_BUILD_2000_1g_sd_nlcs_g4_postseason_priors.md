# 2026-10-15 2000_1g_sd (MIL@LAD NLCS G4, Showdown): postseason priors, for ARCHIVE to grade

Delivered: `outputs/2026-10-15/DKEntries_showdown_2000_1g_sd_REVIEW_GRADE_final.csv`, sha256 b8849500fc6a (review-grade,
thesis-ladder build 8a1328db plus two captain role swaps, no player changed; record
`data/deliveries/2026-10-15/2000_1g_sd_norun_b8849500fc6a.json`). Preflight exit 0 at 19:30 ET.
23 entries: mini-MAX 196753109 x1, $750 QJ 196753111 x2, Micro Booster top-5 196753465 x7, NFL Millionaire sat
196753498 x7, $100 Dime 196777927 x2, $100 Dime 196778190 x2, $125 QJ 196779067 x2.

## Inputs (19:24-19:30 ET)
- Series: MIL led 3-0 (G3 MIL 6-2). LAD elimination game. No off day after G3.
- Odds paste (cbs/si/hardrock; odds API 401): LAD -165 / MIL +140, total 7.5. No-vig LAD ~0.60.
- Weather 89F clear, wind 4 mph out to RF (statsapi).
- Both nines DK `Starting`. MIL arms: Drohan PO (opener, LHP), May PLR (bulk, RHP). LAD: Glasnow SP.

## Priors the build carried
| input | value | reason |
|---|---|---|
| Glasnow Base | 19.1 (APPG 21.2 x0.90) | elimination-game hook risk; 1.93 postseason ERA, K line 5.5 juiced over |
| May Base | 9.5 | bulk arm behind an opener, ~3.5 IP |
| Drohan Base | 4.0 | opener, ~1.5 IP; at APPG 10.3 v1 rostered him in most lineups |
| Harrison Base | 5.0 | DK RP with starter APPG 13.6; only relevant when kept |
| LAD platoon | neutral vs L (ops_vs_L = overall, 10000 PA) | engine grades LAD vs the opener's hand (L); May and the MIL pen are mostly R |
| `--keep-arms` | off | v2 kept 10 active-roster relievers; Hall (9) and Ashby (8) went in as cheap UTIL fill inside LAD stacks |
| Micro Booster | wta_satellite posture + two role swaps | top 5 pay: Pratt CPT -> Bauers CPT, May CPT -> Yelich CPT |

## Questions for grading (observed outcomes only)
1. Realized IP for Glasnow, Drohan and May against the 0.90 / 4.0 / 9.5 priors. Who got the MIL decision?
2. Did any MIL reliever post a top-6 Showdown score (the case for keeping Hall/Ashby)?
3. Micro Booster: did any of the seven finish top 5, and which captain?
4. Field captain share for May (bulk arm) vs our 4 of 23.
