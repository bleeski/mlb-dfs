# DK Starting=PO on the feed's named starter was RIGHT (BUILD, 2026-09-29 1400_4g)

Observed: the 2026-09-29 salary file tagged Jesus Luzardo (PHI, 44321112) `PO`, with Andrew Painter `PLR`.
The MLB StatsAPI probables (via DFS_Architect_MCP) and the headline previews named Luzardo the NL Wild Card Game 1
"starter". The session declared him (`--declare-pitcher 44321112=declared_probable_sp`) and delivered a certified
file at 12:40 ET that rostered him in 3 of 9 entries.

Then a QA pass found the truth. Luzardo was a confirmed OPENER: his first outing since left shoulder inflammation
on Sept. 7, framed as "two clean innings", with Painter as the bulk arm (Inquirer, PhillyVoice, NBC Sports Philadelphia).
DraftKings Sportsbook priced his strikeout line at 2.5 against Sale's roughly 7.5. The session rebuilt with him barred,
and run 20260929T165713Z_0efaf97e superseded the earlier file. DK's `PO` token was right for all three
arms that day (Luzardo, HOU Blubaugh, CWS Hagen Smith).

Question for DEV: R104's bar held and the operator override was the error. Should `--declare-pitcher` on a
`PO`-tagged arm demand an evidence note, since a feed "probable" and a headline "starter" both read the same for an
opener? One cheap, deterministic signal is available pre-lock: a strikeout prop far below the arm's season norm.

Also: odds came from WebSearch summaries with no book attribution. sports.yahoo.com, fanduel.com,
sports.betmgm.com and dknetwork.draftkings.com are egress-blocked for WebFetch. The rows were pasted under the book names
`websearch_src1`/`src2`, and `odds_from_paste.py` accepted them. Whether an unattributed book label should warn
is a DEV call.
