# No reachable named-book odds source when both the device VM and the container are egress-blocked

Slate 2140_5g (2026-09-08), BUILD. F1 shipped NEUTRAL and the build certified without it.

**What happened.** The device VM had no network at all (curl 000 to statsapi,
baseballsavant, fangraphs, api.the-odds-api.com) and the container's own curl was
also 000 to all four. So `build_slate.py`'s auto-fetch died on the documented
`Tunnel connection failed: 403` and F1 stayed neutral. `WebFetch` DOES work from
the container, which is the only egress this session had.

**Why the paste path did not rescue it.** `odds_from_paste.py` requires
`away_ml`, `home_ml` AND `total`. The one reachable odds page (covers.com;
teamrankings 403s, oddsshark 302s to covers) literally prints only the OPENING
total per game. Two separate reads of that page produced per-book moneyline
grids that CONTRADICTED each other -- one had ATH favored -134, the other TOR
favored -120 -- so the per-book detail was extraction noise, not prices. The
tool refused the totals-only paste with exactly the right reasoning: "an even
split on a game the book did price is a fabrication the report cannot see."
The refusal was the feature working; recording it so the next session does not
re-litigate it under a clock.

**The gap.** There is no documented WebFetch-based odds route, and R316's
"measure the egress rather than reading it off this file" cuts both ways: this
session measured NO egress on the device VM, four days after R316 measured full
egress there. Candidate work, in preference order:
1. A `--paste` mode that accepts totals-only and marks the per-team split
   explicitly UNAVAILABLE rather than even-splitting it, so F1 can use the
   cross-game signal (TOR@ATH 10.0 vs WSH@SD 7.5 is real) while the within-game
   split stays inert and SAYS so. Today it is all-or-nothing.
2. A named, server-rendered odds page that survives WebFetch's markdown
   conversion with per-book prices intact. Worth finding one and pinning it here.

**Do not** let a session hand-name a book for a consensus line to get past the
refusal. That is the fabrication the tool is built to stop.
