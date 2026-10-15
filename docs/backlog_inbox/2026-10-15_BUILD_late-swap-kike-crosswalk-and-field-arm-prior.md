# Late swap on 1300_2g: a fetched feed hard-fails Kiké Hernández, and the ownership prior gives idle starters the field's P slot

Filed by BUILD, 2026-10-15, 1300_2g late swap after TB@CLE went final (CLE 3-2). Ben uploaded live standings for the
Jukebox (196753088), Solo Shot (196766327) and Satellite (196753409). Delivered `1300_2g_norun_1e306d9a2f5c`,
review-grade, verify_export 0 and preflight 0 at 16:54 ET.

## 1. `verify_export` / `preflight_upload` hard-fail a DK nickname on a fetched feed

LAD posted Enrique Hernández 9th. `fetch_slate_bundle.fetch_lineups_feed` writes him as `"Enrique Hernández"`, DK's
salary file says `Kike Hernandez`, and `verify_export.py --lineups <fetched feed>` printed
`FAIL ... 5296171432: Kike Hernandez (LAD) is not in LAD's confirmed lineup or probables` (exit 2) for a player who
was in it. The alias exists in one place only: `DK_FIRST_NAME_ALIASES = {"kike": ("e",)}` in
`mlb_engine/intake/paste_lineups.py:723`. `preflight_upload._norm_name` (`tools/preflight_upload.py:224`) and the
fetched-feed path do not use it. Workaround used: rebuilt the feed through `lineups_from_paste.py`, which printed
`NAME FORM LAD slot 9: pasted 'E Hernandez' read as DK 'Kike Hernandez' (nickname table)`, then both checks passed.
Ask: the liveness cross-check matches by MLBAM id where the feed has one, else through the same alias table.
A false hard-fail at the money boundary costs the same as a true one inside a lock window.

## 2. The ownership prior spreads the opponent's P slot over starters who are not pitching

To rebuild the live field I drew each opponent's `P LOCKED` from the prior. `large_field_gpp` gives Glasnow
10.9% and about 2.5-2.8% each to roughly ten idle MIL/LAD starters (Misiorowski, Skubal, Yamamoto, Snell, Henderson,
Gasser, Sasaki ...), so the field's MIL@LAD arm came out mostly idle and the leaders far too weak. With a judgment
override (Glasnow 72, May 8, Drohan 5, Misiorowski 3, thin tail) the rebuilt field held Glasnow in 67-76%, which
matches the salary arithmetic: the Jukebox leader had $15,600 for P+SS, and Glasnow + Betts is $14,700. Ask:
`probable_sp` should zero, not merely discount, an arm the feed and DK both show is not starting.

## 3. Salary inference of hidden slots works and belongs in `standings_read` (extends 2026-10-14's fragment)

Ben's suggestion: weight each opponent's hidden fill by how close it spends their remaining salary (each
`<slot> LOCKED` filled from the pool within `50000 - visible salary`, kernel exp(-left/600)). It sharpens the
leaders. Scratch: `tools/_scratch_lcs1015/swap_sim.py` (gitignored, kept until the slate closes) also scores each
legal fill of our open slots against the contest's target (first place; the Booster's top 5, "any of seven"), and
the portfolio's no-cash count, so a move can be tested as Pareto. Four moves were Pareto on 30,000 draws and one
(the Solo Shot's Kiké + Tucker) traded +101 first-place for +625 no-cash; the Ohtani variant beat both. Counts
are review proxies over the engine's UNCALIBRATED_CORRELATED_PRIOR loadings, never probabilities.

## 4. Smaller

- `preflight_upload.py` refuses to pick between two feeds in the slate folder ("equally compatible ... pass --feed"),
  which is right; a backup feed belongs outside `data/slates/<date>/`.
- `.claude/hooks/guard_commands.py` denies `git checkout` unconditionally, while its message and CLAUDE.md say
  "while any claim you do not own is live". With no foreign claim, restarting a merged branch needs
  `git merge --ff-only origin/main` instead.
