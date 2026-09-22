# Five smaller defects met on the 2026-09-22 1915_1g_sd Showdown build

Filed by BUILD. None blocked the delivery; the first two changed what a build
does or can do, the other three are reports that say something false.

## 1. `build_slate.py --help` crashes

`ValueError: unsupported format character 'b' (0x62) at index 319`. The
`--captain-prior` help string contains "(a 100% budget over one slot)"; argparse
%-formats help text and reads `% b` as a directive. Fix: `100%%`. A test that
calls `format_help()` on the parser would catch the whole class.

## 2. Showdown handedness misses accented names

`showdown_handedness` keys `bat_side` by the feed's `name` and counts
`hitters_with_side` by exact membership in `df["Name"]`. The MLB feed writes
Acuña, Suárez, Rodríguez, Dubón; DK writes them ASCII. Result on this slate:
`hitters_with_side: 14` of 18, and those four took a flat 1.00 platoon factor
with nothing but the count saying so. BUILD worked around it with an
ASCII-folded copy of the feed (`unicodedata` NFKD) and got 18 of 18. The
engine already has name normalization for the Classic crosswalk; this lookup
should use it. Worth a WARN when `hitters_with_side < posted_hitters`.

## 3. `f1.prior.factor_by_team` reports a pitcher's pinned 1.0

`showdown_theses` builds `factor_by_team` with `by_team.setdefault(team,
factor)` over covered rows, so it records the FIRST row per team. When that row
is the declared SP (pinned to `F1_PITCHER_NEUTRAL`) the team reads 1.0. This
slate: `{"ATL": 1.0617, "CIN": 1.0}` with `implied_total_by_team` ATL 5.04 /
CIN 4.46 and `non_neutral_f1: 18`, so CIN's hitters actually got ~0.939.
Report the hitter factor, or both.

## 4. `qa_portfolio.py` says "F1 NEUTRAL" on a Showdown brief that applied F1

Section 1 printed `F1 NEUTRAL: no implied totals reached the projections`
against `build_brief_1915_1g_sd_v2.json`, whose `f1.prior.applied` is true with
18 non-neutral hitters. It is reading the Classic `enrichment` shape. This is
the one section SKILL.md tells a session to read before forming any theory
about a build, so a false NEUTRAL there is the 2026-08-16 failure in reverse.

## 5. Two stale texts about the sleeve selector

`--captain-sleeve` help still says the `prior_own_below` selector "is refused:
it needs a captain-ownership prior this build path does not read", which R382
made false. And `brief.captain_sleeve.label` says "No ownership number exists
on this path" on a build where `captain_prior.applied` is true.
