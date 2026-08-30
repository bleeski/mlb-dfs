# Ben's dated instruction, 2026-08-30: data-driven QA becomes a standing step on every lineup build, time permitting

**For DEV to file.** Filed from a BUILD session on slate `1605_2g`
(2026-08-30, BAL@ATH + PHI@LAA, 2-game Classic turbo, 7 entries).

## The instruction

Ben, 2026-08-30, after the build had already certified and delivered: he wants
the QA pass that ran on this slate run on **any** lineup build, time
permitting. His framing on the same slate, twice, bounds it: "we don't want to
force a change for change's sake, but if there is something notable that we
find that would change it let's do a bit of research to uncover it."

So the instruction has two halves and the second is the load-bearing one. Run
the checks. Change the build only on a finding, never on the fact that a check
ran.

## What "this level" concretely was

Five checks ran on `1605_2g`. Four produced findings, one produced a
correction to my own work, and exactly one changed the delivered file. That
ratio is the point: the value is in the checks that came back clean being
CHEAP, not in every check moving something.

**1. Read the contest's real payout table, not its archetype name.**
Ben supplied the field size and prize curve for two contests after the first
delivery. `MLB $1.25K Solo Shot`: 1486 entrants, paid to 350th (23.5%), curve
$125/$100/$80/$65/$50/$35, then 7-8 $25, 9-10 $15, 11-15 $10, 16-25 $5, 26-50
$3, 51-100 $2.50, 101-180 $2, 181-350 $1.50. Barbell: top 10 hold $535 of
$1250 (43%), ranks 51-350 hold $540 (43%). `MLB 40x Micro Booster`: 237
entrants, top 5 win $10 flat on a $0.25 entry, 6th pays what 237th pays.
**Finding:** the Solo Shot was being built in WTA construction mode against a
curve that pays a quarter of the field. See §A.

**2. Cross-check the engine's own factor multipliers against an independent
source.** Read `Ceiling_Multiplier` for all four slate arms out of the run's
`final/projections.csv`, then read the same arms out of Savant's
`expected_stats_pitching.csv`. **Finding:** the neutral default outranked two
measured arms. See §B. Nothing in `docs/backlog.md` currently greps for
`neutral_default`, `Ceiling_Multiplier`, or `WTA_CONSTRUCTION_SHAPES`, so this
one is new.

**3. Check that a warning's stated remedy actually fixes the case it fires
on.** The `fangraphs_season_pitching.csv` staleness warning prints an export
URL. Read the URL. **Finding:** it cannot fix this class of case. See §B.

**4. Compare frontier proxies ACROSS candidate builds rather than accepting
the first certified one.** Three builds, all certified, all three gates
passing on each. v1 and v2 landed on an identical frontier point (washout
71%, apex concentration 43%, apex total 796.47 vs 796.56). v3 moved it. A
fourth build on refreshed Savant moved it back inside noise. **Finding:** only
one of four builds was worth delivering, and gate status did not distinguish
them. See §C.

**5. Validate any reference-table edit by re-running the inference it is
supposed to drive.** I added two rows to `dk_contest_archetypes.csv` and
re-ran `build_slate.py` with NO `--postures`. **Finding:** one row landed, one
did not, and I would have reported both as done. See §D.

## Time-boxing, which is the part that will decide whether this survives

The T-schedule in CLAUDE.md already governs and this does not amend it. What
this needs is an explicit precedence rule, because on `1605_2g` the checks ran
AFTER delivery and that was the right order:

- A certified, preflight-clean file is delivered FIRST. The QA pass never sits
  between a passing preflight and Ben's hands.
- Inside T-20, checks 1 and 2 only (they are reads, no rebuild).
- Inside T-10, no checks. CLAUDE.md already says approve on posture defaults.
- A finding discovered after delivery is reported as a finding, not acted on,
  unless the clock genuinely allows a rebuild AND re-preflight. On this slate
  the Kikuchi finding (§B) arrived at roughly T-10 and was deliberately NOT
  acted on; that call is stated in the delivery report rather than buried.

## The proposal

**Automate checks 1, 2 and 3 into `tools/qa_portfolio.py` rather than writing
a prose checklist.** A checklist that depends on a session being curious will
decay, and `qa_portfolio` is already the adversarial surface, already reads
the brief and the delivered bytes, and already prints section 1 from the
artifact for exactly this reason. Three concrete panels:

- **(a) Neutral-default rank check.** The brief already carries
  `enrichment.neutral_default` with `in_pool` and `at_neutral` counts and the
  named players. It does not say where the neutral value RANKS among the
  measured members of the same pool. Print the multiplier distribution and
  flag when a neutral default lands above the median measured peer. This is
  the check that would have surfaced Kikuchi with no cleverness required.
- **(b) Payout-breadth vs construction-mode consistency.** The archetype table
  already carries `payout_breadth`. `WTA_CONSTRUCTION_SHAPES` already decides
  the MILP mode. Nothing compares them. Flag any contest whose resolved shape
  takes WTA construction while its own `payout_breadth` exceeds a bar. On this
  slate `single_entry_gpp` carries breadth 0.01 and the entered contest ran
  0.235, a 23x gap, and no surface said so.
- **(c) Remedy-validity check.** Lower value than (a) and (b) and listed last
  for that reason, but the `qual=y` case shows a warning can name a remedy
  that provably cannot work. At minimum, the FanGraphs warning should stop
  claiming staleness for an arm that is absent by qualification.

Check 4 is largely already there: `qa_portfolio` prints the frontier and the
two proxies. What is missing is the ability to compare TWO briefs in one
invocation. Today that comparison is a hand-written grep across two `_qa.out`
files, which is what I did. A `--compare <other_brief.json>` flag would make
the check cheap enough to actually run under a clock.

Check 5 needs no code: it is one re-run with no `--postures`, and it belongs
in whatever procedure ends up owning archetype-row additions (see R196).

## Evidence

### §A. The Solo Shot was in WTA construction against a 23.5% payout breadth

`mlb_engine/contest_shapes.py`: `WTA_CONSTRUCTION_SHAPES` contains
`single_entry_gpp`. `execution_pipeline.py:4439` reads
`mode = "wta" if dominant_shape in WTA_CONSTRUCTION_SHAPES else "gpp"`. So a
contest resolving to `single_entry_gpp` gets max-concentration construction.
The archetype table gives `single_entry_gpp` a `payout_breadth` of 0.01. The
entered contest paid 350 of 1486, breadth 0.235.

**This corrects R196's proposed fix.** R196 (six sightings now, five prior
plus this one) says the Solo Shot row should be "posture `single_entry`, shape
`single_entry_gpp`." Writing that row exactly as specified would have made the
build WORSE than the manual override it replaces: it would silently pin WTA
construction to a broad-curve contest on every future slate, where today at
least the refusal forces a human to name a posture. R196 is still worth
closing; the shape value in its Fix line is not.

Measured cost on this slate: near zero, and that is itself worth recording. I
rebuilt with `--postures 194686507=small_gpp`, which is GPP construction, and
the frontier did not move (apex 796.47 to 796.56, washout 71% both). On a
2-game slate the allocator had `distinct_lineups_available: 13` for 7 entries,
so construction mode had almost no room. **Do not generalize the null result:**
13 candidates is a 2-game artifact and the same defect on a 12-game slate has
far more room to express itself.

### §B. The neutral K-rate default outranked two measured arms, and the printed remedy cannot fix it

`Ceiling_Multiplier` from `runs/20260830T195329Z_ee5eed92/final/projections.csv`:

| Arm | Ceiling_Multiplier | Source | Savant xwOBA / xwOBAcon |
|---|---|---|---|
| Zack Wheeler | 1.497 | measured | 0.213 / 0.209 |
| **Yusei Kikuchi** | **1.420** | **neutral default** | 0.294 / 0.267 |
| Jeffrey Springs | 1.381 | measured | 0.273 / 0.255 |
| Chris Bassitt | 1.294 | measured | 0.301 / 0.281 |

The neutral default ranks the one unmeasured arm second of four, above both
measured arms. Savant places him BETWEEN Springs and Bassitt on contact
suppression, i.e. below the arm the multiplier puts him above. His Base is
8.95 against Bassitt's 9.50, so the unmeasured multiplier is what lifts his
Ceiling to 12.70, the highest of the three non-Wheeler arms. He was rostered
in 4 of 7 entries, tied for most-used.

**The remedy the warning prints cannot fix this.** The export URL ends
`&qual=y&type=8`, qualified pitchers only. Verified counts on disk after a
same-day Savant refresh: `fangraphs_season_pitching.csv` 211 rows, Kikuchi
absent (0 grep hits); `expected_stats_pitching.csv` 831 rows, Kikuchi present
(1 hit). Kikuchi has faced 165 batters this season against Wheeler's 499 and
Springs' 527. He is not qualified and a fresh `qual=y` export would not add
him.

**This corrects a verified claim already on the board.** The 2026-08-16
DEV merge pass (docs/backlog.md, the R126-R133 batch note) records "Dobnak is
absent from all 212 rows of `fangraphs_season_pitching.csv` (file dated
2026-07-16, which is the 30.2 days the warning reports)." The absence was
verified correctly; the attribution to staleness was not checked and is wrong
for this class. 211 of roughly 831 arms is the qualified subset, so **every
non-qualified starter takes the neutral default all season and no refresh
changes it.** That is a standing condition, not a stale file, and it should be
filed as its own item rather than as a refresh reminder.

Not acted on, deliberately: the correction is roughly 3 to 9% on one
multiplier and the finding landed near T-10.

### §C. Four certified builds, three distinct frontier points, gates identical

All four passed `workflow_valid`, `selection_certified`, `allocation_certified`.

| build | postures | controls | apex total | washout retained | entries untouched | worst salary-left |
|---|---|---|---|---|---|---|
| v1 | `single_entry` | defaults | 796.47 | 63.1% | 2/7 | $10,300 |
| v2 | `small_gpp` | defaults | 796.56 | 63.1% | 2/7 | $10,300 |
| v3 | `small_gpp` | player 0.72 / stack 0.50 | 813.95 | 57.0% | 1/7 | $3,900 |
| v4 | `small_gpp` | player 0.72 / stack 0.50, fresh Savant | 811.58 | 57.3% | 1/7 | $3,900 |

Deterministic review proxies, not probabilities. v4 delivered
(`7f999de88bffeb3468942add70868ee2df9ee9c82bb50e3747d4a9319f182a08`), chosen
over v3 on equal proxies because it rests on same-day Savant rather than
5-day-old Savant, not because it scored better.

**The $10,300 entry is a fresh CLASSIC sighting for R247.** R247's two
sightings are both Showdown (`2145_1g_sd`, `1905_1g_sd`, worst case $6,100
salary-left). This is the same phenomenon on the Classic path at $10,300, on a
7-entry 2-game slate, and it carries R247's signature exactly: every counter
read clean, `counted_relaxations` zero, `relaxations: 0`, nothing relaxed,
gates all green. Worth adding to R247 rather than filing separately, and it
strengthens R247(a) since it shows the defect is not Showdown-specific.

One consequence that should reach R247's entry: **the degraded entry inflated
the washout proxy.** v2's second untouched entry WAS the $10,300 lineup. It
survived a zeroed BAL@ATH because it was cheap and weak, not because it was a
designed hedge, so "2/7 untouched" flattered v2 against v3. A washout count
that cannot distinguish a hedge from a dead entry will keep making that
mistake.

### §D. My own archetype rows: one landed, one did not

Both rows written to `data/reference/dk_contest_archetypes.csv` with the
observed payout tables in `notes`, under a claim taken at Ben's explicit
instruction (ARCHIVE's write surface, BUILD session; noted here because the
contract makes that irregular).

Re-ran `build_slate.py` with no `--postures`:

- `Micro Booster` -> `wta_satellite (name_inference) [matched 'Micro Booster']`. **Lands.**
- `Solo Shot` -> `single_entry (name_inference) [matched 'Solo Shot']`. **Does not land.**

Posture inference reads `inferred_type`. The only truthful value there is
`se_gpp`, because the entry cap really is 1, and `se_gpp` routes to
`single_entry_gpp` and back into WTA construction. I set
`payout_shape_default: broad_micro_gpp` and nothing reads it for posture. **The
table cannot currently express "single entry, broad curve."** Until that is
fixed the Solo Shot still needs `--postures <id>=small_gpp` by hand, which is
R196's tax unchanged after six sightings.

Also a fifth data point for R196's second, smaller question: the Micro Booster
printed `large_wta -> wta_satellite [COLLAPSED]` on a 237-entrant field. The
posture vocabulary exposes only `wta_satellite`, which maps to `large_wta`,
while `contest_shapes.py` also defines `small_wta` and `mid_wta` that no
posture can reach. A 237-person field and a six-figure field get the same
construction.

## Suggested filing

Four items, in the order I would rank them:

1. **The standing QA step itself**, with the three `qa_portfolio` panels and
   the `--compare` flag. This is Ben's dated instruction and the rest are its
   output.
2. **The `qual=y` standing condition** (§B), as its own item, correcting the
   2026-08-16 staleness attribution. Every non-qualified starter, all season.
3. **Append §C to R247** rather than filing new: first Classic sighting, plus
   the hedge-vs-dead-entry consequence for the washout count.
4. **Amend R196's Fix line** (§A, §D): the shape value is wrong, and the row
   as specified would pin the defect rather than close it.
