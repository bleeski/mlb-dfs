# BUILD 2026-09-06 (2210_1g_sd, WSH@LAD): `dk_order_coverage` reports ZERO covered
# sides on a Showdown salary file carrying a complete 1-9 for BOTH teams

Same family as R297(d) / R304(b)(c) -- a referee's check that cannot run on
Showdown geometry, rendered as an affirmative statement about the input. Third
member of the class; the first two were the pitcher test, this is the posted-
lineup test.

## Repro, on the delivered slate's own staged file

    from mlb_engine.intake.live_data_adapters import dk_order_coverage
    dk_order_coverage("data/slates/2026-09-06/DKSalaries_showdown.csv")
    -> ([], ['LAD', 'WSH'])          # covered: none. uncovered: both.

The file it just read:

    LAD order tokens (all rows): 18  ['1'..'9']  | distinct on UTIL rows: ['1'..'9']
    WSH order tokens (all rows): 18  ['1'..'9']  | distinct on UTIL rows: ['1'..'9']

A Showdown salary file carries TWO rows per player (a CPT row and a UTIL row,
different ids, different salaries), so a complete 1-9 arrives as EIGHTEEN order
tokens per side. Whatever completeness test `dk_order_coverage` applies, 18
tokens for 9 slots is not "a complete 1-9", and both fully posted sides fall
through as uncovered. `mlb_engine/optimize/showdown.py`'s own melt collapses the
two rows to one person; this function does not.

## What it cost on this slate, and what it did not

Not the build. `build_slate.py` read the column correctly through its own path:
`pool.basis = declared_starters`, `posted_hitters = 18`, `declared_starters = 2`.
The POOL is fine.

It cost the REFEREE. `tools/preflight_upload.py` printed

    WARN  no lineups feed resolved; the posted-lineup cross-check did not run and
          a benched starter would not be caught here. no lineups_feed*.json under
          data/slates/2026-09-06

on a slate where CLAUDE.md's R305 paragraph says the answer should have been the
opposite -- "a fully posted slate that wrote no feed is cross-checked against the
salary file itself and the report says no external feed was needed." The referee
had the posted orders in the file in its hand and could not see them, so the one
check that would catch a late scratch was silently absent. Exit 0, PASS, all hard
checks clean. Read the direction: this is not a false WARN, it is a REAL check
that did not run, reported as a missing input rather than as a blind spot.

Note the interaction with R305's own selling point: the whole reason the DK
column outranks a feed is that a fully posted slate needs no fetch. On Showdown
that path never engages, so every Showdown slate is permanently on the
"no feed, no check" branch and nothing says so.

## Fix, small

Collapse to one row per person before the completeness test, the way the
Showdown melt already does, or key the test on `Roster Position == 'UTIL'` when
the file is Showdown geometry (`detect_salary_contract` already answers that).
Then R305's "no external feed was needed" line becomes reachable on Showdown and
the referee's posted-lineup check runs on the commonest Showdown state there is.
Per R233, the enumeration belongs in the entry: grep the class for every reader
of the `Starting` column that counts rows rather than people --
`dk_order_coverage`, `merge_dk_starting_into_feed`, and both referees' resolvers.

## Two riders, recorded not filed

**R316's egress reading was already stale on the day it was written, in the
other direction.** R316 (2026-09-06) replaced "the device VM has no network"
with a measurement showing statsapi, savant, fangraphs, pypi and the odds API
all answering. Measured again 2026-09-06 20:37 ET from a Cowork device VM on the
same mount: `curl` returns 000 to all five from the device VM AND from the cloud
container. Both R316's reading and the sentence it corrected are true-on-their-
day. The paragraph's own instruction ("MEASURE the egress rather than reading it
off this file, in EITHER direction") is the part that held. Nothing to fix; the
value of the note is that the half-life turned out to be hours, not days.

**The APPG ratio table ran BEFORE the first build this time, as R123/R310's
second-instance entry asked.** Same game, same two declared LHP arms
(Alvarez / Wrobleski) as 2026-09-04's 2210_1g_sd.
`dailyfantasyfuel.com/mlb/showdown-single-game-projections/` answered `WebFetch`
again and carried all 20 posted players; its salary column matched the
DKSalaries UTIL column on all 20 rows, which is the same-slate proof. The
handedness signature R320 names reproduced exactly: everything APPG OVERRATED
was a left-handed bat (Abrams 0.729, Muncy 0.767, Wood 0.787, Lile 0.833) and
everything it UNDERRATED was a right-handed bat (Kike 1.606, Rojas 1.514,
Teoscar 1.194, Smith 1.186, Betts 1.167). Handedness codes from
`statsapi /teams/<id>/roster?hydrate=person`. Ratio spread 0.729-1.606, 20 of 20
differing from APPG. Result at default controls: `player_exposure.relaxed_slots`
0, `overlap_relaxed_slots` 0, captain cap held at 25.0%, player cap held at
50.0%. Yohandy Morales, the 2026-09-04 small-sample trap, is not in today's
posted WSH order at all, so the predicate that entry proposes (highest-APPG
hitter in the pool AND bottom-quartile salary) had nothing to fire on. Two
captain LOCK relaxations remain (Wood -> Teoscar, Betts -> Teoscar), which is
the overlap bound and not a cap.

## The R233 reading, which is why this is worth a slot rather than a footnote

HEAD at the time of this build is `c0ef0ab`, subject *"R305 and R304 CLOSED,
R297(d) landed out of its batch: the two referees stop asserting a false thing
about a Showdown file."* That commit is hours old. The very next Showdown build
run against it hit a referee asserting a false thing about a Showdown file,
through a site neither R305's nor R304's enumeration named. This is R233's
finding for the eighth time: a fix closed N named sites and the class had N+1.
The N+1 here is one function upstream of both referees, which is why fixing each
referee's own resolver did not reach it -- both now resolve THROUGH
`dk_order_coverage`, so a single blind spot in it makes both of them blind
together, and R305's "no external feed was needed" line is unreachable on
Showdown by construction.
