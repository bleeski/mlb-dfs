# DK Starting=PO on the feed's named starter (BUILD, 2026-09-29 1400_4g)

Observed: the 2026-09-29 salary file tagged Jesus Luzardo (PHI, 44321112) `PO` with Andrew Painter `PLR`,
while MLB StatsAPI probables (via DFS_Architect_MCP) and every preview (FanDuel Research, SI, Yahoo summaries)
named Luzardo the NL Wild Card Game 1 starter. `build_slate_pool` bars a PO arm outright (R104), so without
`--declare-pitcher 44321112=declared_probable_sp` the pool silently lost a 7700 starter; the Painter PLR soft
blocker then refused the lineup gate until overridden (`--ignore-pool-blockers --assume-gates lineup_gate_passed`).

Question for DEV: when the feed's probable is the PO-tagged arm AND the arm's AvgPointsPerGame reads as a
starter's, should intake surface a named soft blocker instead of barring? Evidence the same day: HOU Blubaugh
and CWS Hagen Smith were genuine openers (bullpen games confirmed by Houston Chronicle / Sun-Times), so the
PO token was right for 2 of 3 arms.

Also: odds came from WebSearch summaries with no book attribution (sports.yahoo.com, fanduel.com and
sports.betmgm.com are egress-blocked for WebFetch); pasted under book names `websearch_src1`/`src2`.
`odds_from_paste.py` accepted them. Whether an unattributed book label should warn is a DEV call.
