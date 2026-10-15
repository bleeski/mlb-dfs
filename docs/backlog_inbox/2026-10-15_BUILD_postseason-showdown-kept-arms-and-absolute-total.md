# Postseason Showdown: kept relievers are not state-conditioned, and a one-game F1 drops the absolute total

Filed by BUILD, 2026-10-15, ALCS G3 TB@CLE Showdown (1300_1g_sd), 7 entries over 5 contests.

## 1. Kept arms ride every thesis at full Base (P1 for any postseason `--keep-arm` build)
`_template_specs` (`mlb_engine/optimize/showdown_theses.py:840-875`) suppresses only the losing side's HITTERS
(`_suppress(_hitters(shape, o), ...)`). A kept reliever keeps his Base in every game state, so the ladder uses him as the
cheap required other-side body in exactly the scripts where he does not pitch. First build (sha256 0a5f98717f51,
19 active-roster arms kept via `--keep-arm`, supplied Base 0.3-3.4): CLE closer Cade Smith ($4,000, Base 3.4) was the one
CLE player in all three TB-leaning lineups (3/7), and TB closer Bryan Baker was the one TB player in the
`favorite_win_big` lineup. A closer on the trailing side of a blowout is a likely zero, and three correlated zeros is a
washout axis. Rebuilt without kept arms (sha256 454538605850), which removed it.

Ask: condition kept arms per template. In `win_big` / `win_big_no_sp`, suppress the losing side's kept relievers (and
arguably the winning side's high-leverage ones); in `win_close` and `pitchers_duel`, leave the winning side's (or both)
closers live. Until then, `references/showdown.md`'s "use it in an elimination or late-postseason game" advice puts a
hazard on the ladder path, and the R484 2026-10-13 rider (label says "both arms off") is the same class.

## 2. On a one-game slate F1 cancels the run environment's LEVEL
`f1.prior` reads "implied team total over the slate mean of the two sides" (brief: CLE 1.0325, TB 1.0). With one game the
mean IS this game, so a 6.5 total and a 10.5 total price hitters against arms identically; only the side split survives.
Today's 6.5 is about 74% of a league-average game, so APPG-based hitters sit high relative to any arm whose Base was set
in absolute terms. Workaround used: supplied SP Base (Williams 19.5, Jax 11.0). Ask: a Showdown anchor of implied team
total over a league-mean constant (with the existing clip), so a low-total postseason game moves value toward the arms.
Distinct from the pinned park de-parking and `F1_HITTER_CLIP` bounds near backlog R295's text; those are about the
side ratio, not the level.

## 3. Positional deal put the most fragile thesis in a flat-payout satellite (third occurrence)
`thesis_deal` gave `underdog_win_big` (Griffin Jax CPT, a ~4 IP starter, proxy 52.60) to the Satellite to $20 NFL
Millionaire and `pitchers_duel` (Gavin Williams CPT, proxy 64.18) to the $300 Solo Shot. Delivered instead: the same 7
lineups with those two rows swapped, recorded through `upload_manifest.deliver` with notes (sha256 1e563ec54c3f,
preflight exit 0). Same call as 2026-10-06 2130_1g_sd and 2026-10-14 2000_1g_sd; supports that fragment's
`--deal-override` ask, and adds a posture case: `wta_satellite` should draw the highest-median template.

## 4. qa_portfolio section 1 misreads Showdown F1
It printed "F1 NEUTRAL: no implied totals reached the projections" against a brief whose `f1.prior.applied` is true with
18 non-neutral players. The reader looks for a Classic key; it should read `brief["f1"]["prior"]` on Showdown.
