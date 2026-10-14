# 2026-10-14 BUILD (2000_2g late swap): the first live standings export, and `standings_read` cannot read its hidden slots

**Observed.** Ben downloaded mid-slate standings for 196680261 (Quarter Jukebox, field 1,902) and 196714994 (Solo Shot, field 89) after CLE@TB went final and before MIL@LAD started. R472's docstring says 0 of 516,804 archived rows carry a nonzero `TimeRemaining`, so this is the first live sample of the format. What it holds:
- `TimeRemaining` is 9 per player whose game has not started (an innings count): 0, 9, 18 ... 81 in steps of 9. Our four entries read 54, 36, 36, 45 against 6, 4, 4, 5 unstarted players.
- A field entry's unstarted player is HIDDEN and shows as `<slot> LOCKED` inside the `Lineup` cell, for example `... P Parker Messick P Freddy Peralta SS LOCKED`. Our own entries show the same token for our own unstarted players.
- The player table on the right lists only players whose game has started (35 rows in the Jukebox, 21 in the Solo Shot), with `%Drafted` and `FPTS`.

**What broke.** `python tools/standings_read.py --date 2026-10-14 --salary <DKSalaries> --lineups <feed> --standings <both zips> --paid-places 196680261=442,196714994=20 --run-id 20261013T222855Z_8baa2fb6` printed every leader as `not_inferred (leader skipped: 'LOCKED' is not in the salary file)` and every one of our entries as `unknown: cannot build the roster: 'LOCKED' is not in the salary file`. The cash line and #1/#10/#100 points did print. Without `--lineups` it refused first: `no lock times can be derived: DK's Starting column covers 2 side(s) and not ['LAD', 'MIL']` (a Tue-Wed draftgroup; the 10/14 feed had to be merged by hand).

**What the session did instead.** Scored every legal fill of our open slots against a field rebuilt from the standings (each field entry's current points plus a draw for each `<slot> LOCKED`), on the engine's `UNCALIBRATED_CORRELATED_PRIOR` loadings: `tools/_scratch_lcs1013/swap_sim.py`, `swap_eval.py` (scratch, gitignored, kept until the slate closes). Delivery `2000_2g_norun_a6e32257529e`.

**Candidate item.** `parse_standings_export` reads `<slot> LOCKED` as an open slot whose occupant is unknown (never a player name), and `TimeRemaining / 9` as the count of unstarted players, which cross-checks the parsed `LOCKED` count. Our own entries' hidden slots resolve from the delivered file by Entry ID. A leader whose open slots are hitters gets the same inference the open-pitcher path has today. Test: a fixture cut from these two exports (field rows only, entry names stripped). Effort S-M.

Also seen: `paid_places` for both contest types reads about 23% in `data/reference/dk_contest_paid_places.json` (Solo Shots 0.229-0.259, Quarter Jukebox 0.232), so a Solo Shot is not a narrow-breadth contest; the 10-13 build's `wta_satellite` posture for it was the session's error, not the engine's.

Nothing here is a lift, an edge, an ROI or a win rate.
