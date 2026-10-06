# 2026-10-06 BUILD: preflight's confirmed-lineup check hard-fails a nickname spelling DK already posted

Slate 1800_2g (NLDS G3 LAD@ATL + MIL@SD). `tools/preflight_upload.py` exit 2 on a certified file:
"5 rostered player(s) absent from a confirmed posted lineup: ... Kike Hernandez (LAD) is not in LAD's
confirmed lineup or probables" (5 entries).

Cause: the MLB feed spells the LAD 9th hitter "Enrique Hernández" (MLBAM 571771, order 9); DK spells him
"Kike Hernandez" and posts him `Starting=9` in the salary file. The build resolved it correctly
(`pool.dk_batting_order.disagreements`: `in_feed_not_dk` Enrique Hernández, `in_dk_not_feed` Kike Hernandez,
`resolved_to: dk_salary_starting`), so the roster was right and the preflight's feed name join was the only
thing that failed.

Worked around without `--force`: copied the feed, renamed that one row to DK's spelling, reran with
`--feed <copy>`; exit 0, all hard checks clean. The staged `data/slates/2026-10-06/lineups_feed.json` was
left untouched.

Ask: the preflight's confirmed-lineup check should join on the same key the pool's DK-vs-feed merge
settled (DK `Starting` player id, or MLBAM id) rather than on name, or read `pool.dk_batting_order` from the
brief it already resolves. A late swap re-pulls the feed and will hit the same spelling. `live_data_adapters.py`
line ~420 already notes the Kike/Enrique mismatch for the pool; the preflight has no equivalent.
