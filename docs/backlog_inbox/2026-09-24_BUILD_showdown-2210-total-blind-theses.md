# 2026-09-24 BUILD 2210_1g_sd (SD@LAD Showdown, 21 entries): three findings

Delivered sha256 cb57178d665491d8f5e11dbc814ea41f24b993a37277d938564d0e962397c273,
review-grade, preflight exit 0. Market: FanDuel LAD -174 / SD +146, total 7.5
(O -122 / U +100), via `tools/odds_from_paste.py` because the odds API returned 401.

## 1. NEW: thesis weights never read the posted total (P2, S)

`build_thesis_ladder` (`mlb_engine/optimize/showdown_theses.py` ~1493-1515) splits
the directional templates by moneyline win share and gives the neutral templates
a fixed `NEUTRAL_SHARE`. Nothing reads the game total, so a 7.5-total game with two
high-strikeout starters (Glasnow 11.57 K/9, Pivetta 10.5 K/9) got the same shape
mix a 10.5 total would. Result on this build: 7 of 21 lineups roster NEITHER
starter (`*_no_sp`, `*_shootout`, `both_explode`), and only 2 roster both
(`pitchers_duel` x2). The market's lowest environment on the board drew a third
of the portfolio on high-scoring game states.

Fix direction: scale the shootout / both-explode / no-SP weights against the
duel / starter-carries weights by the game total relative to a league or slate
reference, recorded in `construction` beside `win_share_basis`. Template weights
are strategy (R156's note), so this needs Ben's ruling on the curve before code.

## 2. NEW: the Dodger Stadium rename drops F5 weather for every LAD home game (P2, XS)

The MLB feed now names the venue `UNIQLO Field at Dodger Stadium`.
`tools/fetch_slate_bundle.py` keys weather on that string and printed
`weather: venue 'UNIQLO Field at Dodger Stadium' not in team_to_venue.csv; skipped`.
`data/reference/team_to_venue.csv:15` still reads `Dodger Stadium`. The engine's
own venue resolution is keyed by home team, so park factors should be unaffected
(verify); the weather join is what breaks. Fix: an alias column or a venue alias
map, owned by ARCHIVE for the CSV and DEV for the join.

## 3. Sightings of filed items (no new entry needed)

- **R399(b)**, again: `showdown_handedness` matched 17 of 18. Feed `Teoscar
  Hernández`, DK `Teoscar Hernandez`. He took a flat 1.00 platoon factor instead of
  same-hand vs RHP Pivetta, in 4 delivered lineups.
- **R399(d) / R210**, again: `qa_portfolio.py` section 1 printed `F1 NEUTRAL` and
  `controls relaxed: none` on a brief carrying `f1.prior.non_neutral_f1: 18` and
  `counted_relaxations` overlap 1 / player 1.
- **R238**, again: 14 of 21 entries sit in ticket-line satellites and the
  Showdown path read no contest shape; `--postures` is inert here.
- **R153**: the player cap relaxed one slot; Dustin Harris ($5,000 UTIL) and
  Hunter Feduccia ($3,000) each landed in 11 of 21 against a 10 cap, together in 6.
- `tools/solver_probe.py` refuses a Showdown salary file (exit 4, "times the
  Classic solver"), so session-start step 3 has no Showdown form. CLAUDE.md says
  run it "before any build"; worth one line saying Showdown skips it.
