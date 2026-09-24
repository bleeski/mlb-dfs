# MCP lineups need a converter; odds had no reachable source (R143, R316)

Slate 2026-09-24 1410_4g (early, 4 games, 12 entries), cloud container.
Delivered certified at 13:17 ET, sha256 f031b666...3984, 48 minutes before
the deadline. Neither item below cost the file. Both cost time, and both
will recur.

**1. Hand-shaping the DFS_Architect_MCP feed.** SKILL.md (the "When
`statsapi.mlb.com` is proxy-gated" paragraph) says to shape
`get_mlb_lineups` + `get_mlb_probables` into the per-GAME feed. The field
list it gives (`team_abbrev`, `probable_pitcher`, `lineup_status`, `lineup`)
omits `game_date_utc`. A feed built from that list was refused at autobuild
attempt 1 with 12 blockers: 4 x "unparseable game_date_utc" and 8 x "no
probable or declared starter". The feed carried all 8 probables; the
probable blockers were a cascade from the missing start time. Adding
`game_date_utc` made the next attempt certify. Separately, the brief read
`draftgroup_coverage: 7/8` with all 8 sides upgraded from DK `Starting`.
The likely cause is the MLB API's `AZ` against DK's `ARI` in the supplied
feed. I did not verify it.

Proposed for DEV: `tools/feed_from_mcp.py`, which takes the two MCP payloads
and the salary file, crosswalks `AZ`->`ARI`, fills `game_date_utc` from the
probables payload's `game_time_utc`, and writes the feed that
`fetch_lineups_feed` would. Failing that, add `game_date_utc` to the
skill's required-field list.

**2. No odds source reachable.** `THE_ODDS_API_KEY` was unset here (neither
env nor `.env`). `site.api.espn.com` returned 403 on CONNECT from curl.
WebFetch was blocked by the egress proxy on fanduel.com, sportsgrid.com,
sports.yahoo.com and site.api.espn.com. WebSearch summaries named numbers
but contradicted each other (ARI@COL total given as both 10 and 11.5 in one
answer), so none of them reached `--odds`. The build shipped with
`f1_games_priced: 0` and `input_confidence.tier: severe` (no_odds_priced plus
Savant expected stats at 24.9 days). This is a host or config gap, not an
engine bug. It should go in `docs/hosts.md` so a BUILD session stops
hunting for a source after the first two blocks.

Resolved in-slate by R236's paste route. `www.actionnetwork.com` was also a
403 CONNECT from this container, which blocks the pre-installed Chromium as
well, so the browser is no workaround here. Ben pasted the page's table at
13:23. `odds_from_paste.py` priced 4 of 4 games (book recorded as
`actionnetwork_page` because the paste named no book). The rebuild
certified at 13:25 with `f1_games_priced: 4`, and `input_confidence`
dropped to `degraded` (Savant only). New sha256 d3c39609...0dea supersedes
f031b666. Lesson for the skill: at a blocked odds host, ask Ben for the
paste at once rather than trying other sites.

**3. Pitcher projections never see the market.** Every SP row in run
20260924T172527Z_8eba2f47 has F1 = F4 = F5 = 1.0. `projection_builder.py:660`
says the opposing total is priced "elsewhere", but nothing on the pitcher rows
moved, so the note there reads as a double-count guard with no primary count
behind it. The result: Tanner Gordon (at Coors against ARI's 5.33 implied,
+163) and Tyler Phillips (against CHC's 3.87, +178) projected identically
(Base 8.03 vs 8.05, Ceiling 11.06 vs 11.03), and Gordon won on $700 of
salary. Proposed for DEV: price the opponent's implied total and the win
share into SP rows, and verify the "elsewhere" claim before building on it.

**4. There is no engine lever for "one lineup in a named contrarian stack."**
Ben's 2026-09-23 fragment was reapplied here: "what if our priors are wrong,"
as one entry carrying a MIA secondary stack (MIA was 0/12 at 3.13 implied).
The R406 sleeves seated no MIA stack. I hand-solved entry 5267953193 with
`optimizer_v3.build_single_lineup` (MIA >= 3 locked, CWS 4 primary), enforced
the portfolio caps by hand, and recorded it through `record_delivery`
(review_grade, refinement=True). The result: sha256 d98252ad, verify_export
and preflight both exit 0, and the consensus cluster at 5/12 against the
build's 0.40 cap (S, relaxed inside T-30 and recorded). Proposed for DEV: a
`--stack-sleeve '{"entries":1,"team":"MIA","min":3,"role":"secondary"}'`
alongside `--captain-sleeve`, so this runs through certification rather than
around it.
