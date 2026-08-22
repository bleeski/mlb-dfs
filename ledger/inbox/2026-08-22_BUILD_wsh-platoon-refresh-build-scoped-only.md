# WSH platoon refresh was build-scoped, canonical file still stale

Raised by a BUILD session, slate 2026-08-22 tag `1335_3g`. Create-only
fragment; the owning role (ARCHIVE) merges and deletes it.

`data/reference/fangraphs_platoon_lineups.json` was 17.7 days old at build
time (collected 2026-08-05), past the 7-day block threshold; `build_slate.py`
runs `stale_platoon_policy='warn'` so it printed and shipped, per contract.

On Ben's explicit instruction this session, I refreshed Washington's entry
specifically (the only team still TBD after the DK/paste/API lineup chain
resolved ATL/MIL/NYY/MIA/TOR) via a same-origin Claude-in-Chrome read of
`https://www.fangraphs.com/roster-resource/platoon-lineups/nationals`. Two
things to know before trusting or extending this:

1. **It is BUILD-scoped, not canonical.** I copied `data/reference/` to
   `data/slates/2026-08-22/reference/` and patched only that copy (per the
   BUILD/ARCHIVE write-set split — `data/reference/` is ARCHIVE's), then
   pointed `build_slate.py --reference-dir` at it. The canonical file at
   `data/reference/fangraphs_platoon_lineups.json` is untouched and still
   17.7+ days old for all 30 teams, WSH included. A future slate gets no
   benefit from this refresh unless ARCHIVE lands it for real.
2. **It is 'Current Year', not 'Projected'.** FanGraphs RosterResource gated
   the 'Projected' stat set behind membership as of today; this browser
   session was not logged in to a member account. The bare-URL default the
   project's own `fetch_fangraphs_platoon.py` assumes ('Projected', matching
   the file's global `stat_set`) is therefore not freely reachable right now.
   I used the free 'Current Year' (Go-To Starting Lineup) table instead, same
   vs_RHP/vs_LHP table shape, and labeled the WSH entry's own `stat_set` and
   `collected_via` fields accordingly rather than overwriting the file's
   global (and still-accurate-for-29-teams) `Projected` label. Worth flagging
   to Ben: if `--fetch`/`--from-dir` refreshes are meant to keep working,
   whatever FanGraphs session does the fetching needs to be logged into a
   member account now, or every future refresh is stuck on 'Current Year'
   too.

Confirmed working: the delivered build's preflight shows Brady House,
Abimelec Ortiz and CJ Abrams (WSH) rostered from this projected order, so the
patched copy fed the build correctly.
