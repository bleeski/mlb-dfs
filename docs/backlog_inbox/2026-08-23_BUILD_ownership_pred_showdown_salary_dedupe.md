# `ownership_pred.py` does not dedupe a Showdown salary file, and every feature that joins on a person goes INERT

**Filed by BUILD** from the 2026-08-23 ATL@MIL Little League Classic Showdown
slate (`1910_1g_sd`). Review-only tool, so nothing about the delivered
portfolio is affected. It matters because R135's whole point is that a slate
passing without a prediction file can never be graded, and on Showdown the
file it writes is close to ungradeable.

## What happened

Emitted the prior pre-lock, exactly as SKILL.md prescribes:

```
python tools/ownership_pred.py emit \
  --salary "<DKSalaries - sunday night showdown.csv>" \
  --feed data/slates/2026-08-23/lineups_feed.json \
  --slate 1910_1g_sd
```

Exit 0, file written to `outputs/2026-08-23/ownership_pred_1910_1g_sd.json`.
The self-report:

```
ownership prior v0.1-prior | 2026-08-23 1910_1g_sd | 180 salary players | 6 archetypes
  batting_order    INERT: no side is posted 1-9 in the salary file and no feed
                   supplied one, so the batting-order attention prior is INERT
                   for every hitter and the no-known-slot discount applies to all
  implied_totals   INERT: no --odds file supplied
  probable_sp      applied (2)
  base_projection  INERT: no --base file supplied
  crosswalk        90 ambiguous name(s), excluded from any grade join
```

Two of those lines are false on their face. DK had posted a **complete 1-9 for
both sides** in the `Starting` column of that very file, which is why the build
itself took R143's zero-fetch path. And a `--feed` WAS supplied.

`180 salary players` is the tell. There were 90.

## Root cause

A Showdown salary file carries **two rows per person**, one `CPT` and one
`UTIL`, with different `ID`s and different salaries:

```
Ronald Acuna Jr.   CPT   43915094   14700   Starting='2'
Ronald Acuna Jr.   UTIL  43915004    9800   Starting='2'
```

Measured on the file:

| | count |
|---|---|
| total rows | 180 |
| `CPT` rows / `UTIL` rows | 90 / 90 |
| distinct names | 90 |
| rows with a `Starting` token | 40 (20 CPT + 20 UTIL) |
| distinct persons with a `Starting` token | 20 (18 hitters + 2 SP) |

The tool reads all 180 rows as 180 players. Two consequences, and they are the
two INERT lines above:

1. **Crosswalk.** Every name maps to two IDs, so every name is ambiguous. That
   is exactly the 90 reported, i.e. the entire pool, all excluded from any
   grade join. The prediction can therefore never be joined to archived
   standings, which is the one thing it exists for.
2. **Batting order.** Each side presents slots 1-9 **twice**. Whatever
   completeness test runs over the per-side order does not see a clean 1-9, so
   it concludes nothing is posted and applies the no-known-slot discount to
   every hitter on a slate where all 18 bats had a confirmed slot.

I did not read the source, so the mechanism inside the order check is inferred
from its output rather than confirmed. The duplication and the counts above are
measured.

One thing to check that I could not rule out: the message also claims no feed
was supplied when one was. That may be the same completeness test speaking for
both sources in a single sentence, or it may be a second defect in the feed
path. Worth separating before fixing.

## Suggested fix

Dedupe to one row per person at intake, keyed on `Name + TeamAbbrev`, keeping
the `UTIL` row as the canonical person (base salary, base ID) and carrying the
`CPT` id and salary alongside if the captain view is ever wanted. That is the
same shape `build_slate_pool` already has to produce for Showdown, so the
cleanest version is probably to read the pool the engine builds rather than
re-parsing the CSV.

Detection is cheap and worth adding regardless: if
`row_count == 2 * distinct_names` and `Roster Position` holds `CPT`/`UTIL`,
this is a Showdown file. Failing loudly on an undeduped Showdown file beats
writing a prior with three of four features inert and a crosswalk that matches
nothing.

## Bar for done

On a posted Showdown slate, `emit` reports the true player count, `crosswalk`
reports zero ambiguous names, and `batting_order` applies rather than going
INERT. Re-running against this slate's salary file is the regression case:
90 players, 0 ambiguous, 18 hitters with a known slot.

## Not in scope

`implied_totals` and `base_projection` were INERT because I passed neither
`--odds` nor `--base`, which is the tool behaving as documented. Only the
crosswalk and batting-order lines are defects.
