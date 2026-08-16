# QA hardening: name the neutral-default arms, split enrichment labels by side, and make apex/washout first-class

Filed by BUILD, 2026-08-15, from the `2138_2g` late slate (KC@LAA + TEX@ATH,
19 entries, 7 contests). Ben asked for this to be merged as the #1 backlog item.

Framing, in Ben's words on 2026-08-15: "the process should be considered more
guidelines that you can overwrite using your judgement when it makes sense," and
"I don't want process to stand in the way from lineup portfolios." Several items
below are cases where a gate or a record blocked a better portfolio, or where a
label read cleaner than the build actually was. Everything here is a deterministic
review proxy or a labeled prior; none of it is ROI, win rate, cash rate, or a
probability claim.

The slate delivered fine (certified, preflight exit 0, sha
`0ff31f0fdc0726848d28fe5c447f46d99ad55696b3f74a8c794836d8f97e630e`). These are
the holes the adversarial QA pass opened afterward.

---

## P1. A pitcher absent from the K-rate reference silently takes the neutral ceiling multiplier

**What happened.** Randy Dobnak (KC) is not in `data/reference/fangraphs_season_pitching.csv`
at all. The K-rate ceiling factor therefore never touched him and he kept the
neutral default multiplier of `1.420`. J.T. Ginn, who IS in the file, earned
`1.389` off a 21.1% K rate. Dobnak's actual 2026 K rate is **12.4%** (4.75 K/9,
36 IP). So the build ranked the worse strikeout arm ABOVE the better one, and
Dobnak was rostered in 9 of 19 lineups at an inflated ceiling.

**Evidence.**

| arm | K% (StatsAPI 2026) | ERA | xERA (Savant) | SIERA (FG) | ceiling multiplier |
|---|---|---|---|---|---|
| Detmers | 28.2 | 4.00 | 3.50 | — | 1.524 |
| Gore | 26.1 | 4.43 | 3.81 | — | 1.513 |
| Ginn | 21.1 | 3.41 | 3.95 | — | 1.389 |
| **Dobnak** | **12.4** | 2.00 | **4.79** | **4.90** | **1.420 (neutral default)** |

Dobnak's 2.00 ERA is carried by an 88.5% strand rate. All seven FanGraphs ROS
systems put him at 4.76-5.32 ERA. A K%-anchored linear fit on the other three
arms evaluates to **1.220** at 12.4% K, so his ceiling was overstated by roughly
2.1 points.

The only signal in the brief was `enrichment.counts.pitcher_ceiling_differentiated: 3`
against 4 rostered arms. That number does not say which arm, does not say why,
and does not say it mattered.

**Proposed change.** Add a named list to the brief, not just a count:

```
enrichment.pitcher_ceiling_neutral_default: [
  {"name": "Randy Dobnak", "player_id": "...", "reason": "absent_from_fangraphs_season_pitching"}
]
```

Emit it as a WARNING (stderr + brief warnings) whenever a player on the list is
in the declared-starter set, since that is the case where it changes selection.
Same treatment for any other factor that falls back to a neutral default on a
rostered player.

**Where.** The enrichment assembly in `execution_pipeline` that populates
`enrichment.counts`; brief writer in `skills/generate-lineups/scripts/build_slate.py`.

---

## P2. `signal_applied: true` while every pitcher had F1 = F4 = F5 = 1.0

**What happened.** The brief reported `enrichment.signal_applied: true` and
non-zero counts for all six factors, so I told Ben the build was fully enriched.
Reading `runs/<id>/final/projections.csv` afterward showed:

- **Every row on the slate**, hitters and pitchers, was `Projection_Mode = emergency_proxy`.
  The base is AvgPointsPerGame for all 40 players.
- All four pitchers had `F1 = 1.0, F4 = 1.0, F5 = 1.0`. The ceiling multiplier
  was the ONLY thing differentiating arms.
- Hitters were genuinely enriched (F1 0.927-1.067, F2 0.910-1.100, F4 0.850-1.063,
  F5 0.940-1.080, all 36 moved).

Pitcher F1 = 1.0 is deliberate (v1 avoids double-counting the opposing team
total) and pitcher F5 = 1.0 held because no wind cleared the venue threshold.
Neither is a bug. The problem is that one boolean covered both sides and read as
"fully enriched" when the pitcher side had one live factor and that factor had a
hole in it (P1).

This is a truthful-labels issue, which CLAUDE.md calls non-negotiable.

**Proposed change.**

1. Split the flag: `signal_applied: {"hitters": true, "pitchers": false}`, or add
   `pitcher_factors_applied: 0` alongside the existing counts.
2. Surface the `Projection_Mode` distribution in the brief so
   `emergency_proxy: 40/40` is visible without opening `projections.csv`.
3. Reword the stale-reference warning to name what it feeds AND which players on
   THIS slate it failed to cover. The current text ("30.2 days old; season rates
   are drifting") led me to report that the stale file did not touch the build,
   which was wrong: it feeds the pitcher K-rate ceiling and it is exactly what
   would have caught Dobnak.

---

## P3. Manifest supersession is a one-way door inside a session

**What happened.** I built five variants exploring the apex/washout tradeoff. Two
of them (`v2`, `v3`) were better on both axes than the first build. By the time I
picked one, the manifest had marked it `superseded`, and `preflight_upload.py`
correctly hard-failed:

```
FAIL  manifest marks this file superseded by outputs/2026-08-15/DKEntries_2138_2g.csv; do not upload it
```

The tool was right. But the only escapes are `--no-manifest` (a waiver that
misrepresents a file that DOES have a record) or reproducing the build, which
failed because the bank had drifted underneath (see P4). A measurably better
portfolio became undeliverable for bookkeeping reasons. That is precisely
"process standing in the way."

**Proposed change.** Add an explicit re-promote path, e.g.
`tools/promote_run.py --run-id <id>`, that copies the run's immutable
`final/DKEntries.csv` to the delivery path and APPENDS a truthful new manifest
row (`status: current`, `re_promoted_from: <run_id>`, prior current row marked
superseded by it). Honest record, no waiver, and exploring alternatives stops
being a one-way door.

---

## P4. The bank cache is keyed on date, so repeated builds under different controls pollute it

**What happened.** Seven builds on one slate, several with different
`--controls-override` values, all sharing `runs/bank_cache_2026-08-15_*.json`.
Results became non-reproducible and then degraded:

| build | controls | distinct lineups | max overlap |
|---|---|---|---|
| v1 | auto-floors | **19/19** | 5 |
| v3 | pitcher .85 / shared 9 / stack .55 | **19/19** | 5 |
| rerun of v3's exact config | identical string | **7/19** | 10 |
| later reruns | auto-floors again | **10/19** | 10 |

The same command produced 19/19 distinct once and 7/19 later. Rebuilding on a
cleared bank then failed the other way (`entry-level joint MILP proven
infeasible`) because the fresh bank was too thin for the auto-floor caps. Three
of my builds were spent on this.

**Proposed change.** Key the bank cache on a hash of the resolved controls plus
the date, not the date alone. Failing that, record the controls signature inside
the cache file and warn in the brief when the cached bank was built under a
different signature than the current build.

---

## P5. Duplicate-lineup reporting has no contest context, and it reads as a failure when it is correct

**What happened.** The preflight printed `duplicate lineup groups: 9` on the
delivered file. I nearly rejected a good portfolio over it. A separate ad-hoc
script showed the truth:

```
contest 193774256:  7 entries,  7 distinct, 0 duplicate-within
contest 193774257:  7 entries,  7 distinct, 0 duplicate-within
(5 single-entry contests, 1 each)
TOTAL duplicate-within-contest: 0
```

The repeats were the same 7 lineups mirrored across two IDENTICAL Pocket Cup
satellites. That is correct construction: separate contests, separate prize
pools, duplication across them is free. Duplication INSIDE one contest is waste.
The tool conflates them.

**Proposed change.** `preflight_upload.py` and the brief should report
`duplicates_within_contest` and `duplicates_across_contests` separately. Only the
first is a finding. This one is cheap and it prevents a correct file from looking
broken at T-5.

---

## P6. Apex and washout are not first-class anywhere, and they are the stated objective

**What happened.** Ben named the goal on 2026-08-15: "dually optimize apex
lineups with preventing a total washout across the portfolio." Nothing in the
engine, the brief, or the skill measures either. I hand-rolled both in a scratch
script, which means they are not reproducible run to run and not comparable
across slates.

What I used, offered as the starting definition:

- **Apex**: portfolio ceiling total, mean, and best single lineup, summed off the
  run's own `Ceiling` column.
- **Washout**: for each game, zero that game's HITTERS, keep the arms, and report
  the percent of portfolio ceiling retained. Plus a histogram of how many bats
  each lineup draws from each game.

The histogram is what actually caught the bad build. One variant posted the
highest apex on the slate (2365) and looked strong until the split showed every
single lineup carrying 4-5 bats from the same game:

```
game-split histogram, rejected build:  [(4, 11), (5, 8)]
game-split histogram, delivered build: [(0, 2), (3, 5), (4, 4), (5, 6), (8, 2)]
```

Same gates passed on both. Only the histogram separated them.

**Proposed change.** Compute both in the pipeline, write them to the brief, and
have `build_slate.py` print them in the review block. Then a build can be
compared against its alternatives on the objective Ben actually holds, instead of
on gates that both pass.

---

## P7. Small items

- **`Solo Shot` is missing from `dk_contest_archetypes.csv`.** Two contests
  ("MLB $2.5K Solo Shot (Night)", "MLB $500 Solo Shot (Night)") matched no row,
  which blocks the build until postures are passed by hand. They are single-entry
  GPPs. This is ARCHIVE's write set, so it needs that role. Recurring DK family,
  worth pinning.
- **`fetch_slate_bundle.py --venues` takes a FILE PATH**, not a comma-separated
  venue list. Passing a list produced an empty weather block and the warning
  `weather skipped: venue file not found at Sutter Health Park,Angel Stadium`,
  which reads like a missing file rather than a misused flag. One line in the
  skill, or accept both forms.
- **`SKILL.md` should carry the iteration discipline**: each rebuild grows the
  bank and changes results; past two rebuilds expect collapse and
  non-reproducibility; the delivery must be the newest certified run, so decide
  before rebuilding. All three cost time tonight.
- **`SKILL.md` should carry the dual objective** (P6) so it survives outside a
  chat prompt.

---

## Suggested order

P3 and P5 first: both are small, and both are cases where the record or the
report blocked or nearly blocked a good portfolio. Then P2 and P1, which are the
truthful-labels and correctness pair. Then P4 and P6. P7 alongside whatever
touches the same files.
