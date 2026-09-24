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
