# 2026-10-06 2130_1g_sd (MIL@SD NLDS G3, Showdown): supplied postseason Base, for ARCHIVE to grade

Delivered: `outputs/2026-10-06/DKEntries_showdown_2130_1g_sd_REVIEW_GRADE_final.csv`, sha256 b9638868fe13 (review-grade,
operator assembly of build 206ce1850e1b plus one row swap; record `data/deliveries/2026-10-06/2130_1g_sd_norun_b9638868fe13.json`).
31 entries: mini-MAX 196429127 x1, Solo Shot 196429128 x1, Quarter Jukebox 196429129 x2, NFL Millionaire satellite 196429409 x7,
Dime Time 196463022 x20. Postures: large_gpp, small_gpp, small_gpp, wta_satellite, small_gpp.

## Inputs (19:35-19:44 ET)
- Series: MIL led 2-0 (G1 3-2, G2 4-3); off day 10/5, so every reliever was fresh. SD faced elimination.
- Odds: BetMGM MIL +110 / SD -133, total 7 (O -117), via `odds_from_paste.py`; the odds API returned 401.
- Weather: 83F, clear, wind 9 mph in from LF (statsapi feed).
- Both nines confirmed at 19:43:55 ET and matched DK `Starting`.

## The supplied Base (sha256 d651bccdbc948)
The base is the engine's own derived prior (`apply_base_prior` x F1, F1 MIL 0.969 / SD 1.031) multiplied by the factors below.
I dumped it with a scratch wrapper around `price_showdown_pool`. Because a supplied Base bypasses F1, `qa_portfolio` reads
"F1 NEUTRAL", but the F1 split is inside these numbers.

| player | factor | reason |
|---|---|---|
| Pivetta (SD SP) | 0.88 | back from a 5-month IL in Sep, 5.0 IP max since then, WC 3.1 IP / 66 NP, elimination-game hook |
| May (MIL SP) | 0.84 | last six starts 4.1/3.2/6.0/2.1/2.0/3.0 IP, 5.65 ERA in 10 MIL starts |
| all hitters | 0.87 | environment: 7.0 total at Petco, wind in; engine hitter Base summed ~64/team against ~55 implied |
| Tatis, Machado, France, Bogaerts | x1.03 | RHB facing a LHP-heavy MIL pen (Ashby, Hall, Romero, Harrison) once May exits |
| Merrill | x0.95 | LHB; the engine's platoon credit covers only the RHP starter |
| Salas, Harris, Cronenworth | x0.95 x0.90 | LHB plus pinch-hit risk: Salas and Cronenworth were PH'd in G1, Harris was lifted in G2 |
| Yelich | x0.92 | Vaughn pinch-hit for him against LHP Morejon in G1 |
| Frelick | x0.94 | Lara started over him against LHP in G1 |
| Bauers, Mitchell | x0.96 | late swap or PH candidates against LHP |
| Ortiz | x0.95 | Hamilton started 3B in G2 |
| Taylor | x0.97 | DH mix, came off the bench in G2 |

## Questions for grading (observed outcomes only)
1. Did the starters' realized IP land near 4.0 (Pivetta) and 3.7 (May)?
2. Were Salas, Cronenworth, Harris, or Yelich pinch-hit for, and in which inning?
3. Pitcher CPT was 9 of 31. What was the field's pitcher CPT share, and the winner's captain?
4. Relievers sit outside the Showdown pool by contract (`starters_only`). What did the high-leverage arms score
   (Miller, Morejon, Megill, Uribe, Ashby)? Did any reliever at 4000 UTIL beat the punt bats?
