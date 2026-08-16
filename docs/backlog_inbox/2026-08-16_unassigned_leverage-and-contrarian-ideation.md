# Leverage and intelligent contrarianism: ideation bundle (2026-08-16)

Provenance: Ben asked an unassigned session for ideas to gain more leverage
and be intelligently contrarian in the lineup portfolios. No code touched, no
claims taken; this fragment is the only write. Sources read in full or in the
cited sections: ledger 0/3.17/3.18/3.19/4.1-4.6/5, backlog Tier 2 and
R10/R48/R118/R126/R37(2)/R40/R13, MLB_Classic.md, and
`mlb_engine/field/ownership_prior.py` (v0.1, unwired). Everything below is a
deterministic review proxy or a labeled prior; nothing is ROI, win rate, or a
probability claim. DEV merges what survives; items marked (decision) are
Ben's.

## The frame the archive imposes

Broad contrarianism is the wrong knob here and the board already says so:
winners run chalk-POSITIVE cumulative ownership in every archetype except
supersatellites (3.17: satellites +4.9, solo shots +9.5, single-entry +8.6,
mini-MAX +1.1, supersats -13.2), and Ben's 2026-08-13 directive reads
"chalk-positive core, one or two sub-10% differentiators, bigger primary
stacks." So "intelligently contrarian" means four specific things in this
project, each with an archive measurement behind it:

1. Sub-10% carry: 104/116 Classic contests had at least one top-5 FPTS player
   under 10% drafted; winners carried one 51% vs a 13% field base rate (3.17).
2. Duplication, not ownership, is the satellite game ("clearing the cut line
   unduplicated is the whole game", R10). Being contrarian against COPIES of
   lineups, not against players.
3. Construction shape vs the field's current shape mix: 5-2-1 lift has moved
   opposite to its field share in all three tranches; the field 5-stacks 47.7%
   while we under-stacked in 47 of 54 contests (3.17/3.18).
4. Archetype conditioning: supersats are the one anti-chalk cell and our
   weakest family (12.8 median percentile vs 28.2 archive); Showdown captain
   is its own measured surface (tranche winners captained at 9.1 median own,
   ours ran 15.4, 0/8 top-owned; dup share 27.5% median in 151-500 fields,
   55.9% above 500).

The Tier 2 spine (R118 replay -> R48+R83 grading substrate -> R10 satellite
prior) is already the right order and nothing below jumps it. The ideas are
grouped by when they can land.

## A. Landable now, no engine change, no new data

**I1. Start the predict-then-grade shadow loop with ownership_prior v0.1
(new, S).** The module exists for exactly this ("start the loop on slate one")
and is unwired. Proposal: BUILD emits `outputs/<date>/ownership_pred_<slate>.json`
pre-lock from the salary file + odds packet + posted orders (review-only, no
engine import), and ARCHIVE grades it via `grade_against_actuals` at mine time
into the ledger. Costs one skill step on each side. Payoff: by the time R10
fits the real satellite prior, there are graded per-feature errors saying
which structural signals (salary, total, order, SP status) miss and how badly,
and the flat-12 baseline has a second, harder baseline beside it. Labels: the
v0.1 file already carries them.

**I2. qa_portfolio leverage panel (new, S; pairs with R126).** The frontier
report today shows apex and washout; add the field-facing third axis as
report-only columns per portfolio: structural chalk-sum per lineup (v0.1 prior
until R10), count of sub-10%-structural hitters per lineup, captain own-tier
histogram for Showdown, and salary-leave distribution vs the archived winner
medians (3.17: winners leave $250, field $200, us $100). R126's washout
histogram answers "do we all die with one game"; this answers "do we all die
with the field." Never a gate.

**I3. Market-vs-crowd divergence screen (new, S).** The adapters already
ingest HR-prop implied probabilities and MLB_Classic.md 14 already licenses
them for "ownership/leverage judgment." A small `tools/` report: hitters whose
HR-implied percentile exceeds their structural-own percentile by a stated
margin, per slate, deterministic, review-only. This is the classic leverage
screen built from two sources we already pay for, and it feeds candidate
review under section 7's "credible duplication/ownership inputs" without
touching the solver.

**I4. Bank-side scenario coverage practice (SKILL.md note, XS).** Section 7
seeds scenario families from totals/park/wind; the field concentrates on the
top totals (the same feature the prior weights highest). Standing practice:
the bank always contains at least one stack family per GAME, not per
top-ranked game, so the allocator can choose mid-total coverage when caps
bind instead of finding none in the bank. Bank growth is already the
always-permitted remedy; this just aims it. R126's game-split histogram is
the check that it happened.

## B. Attaches to already-sequenced Tier 2 items

**I5. Leverage-carry rule (attaches to R10).** Once `Projected_Ownership_Pct`
is live in the satellite cell: a counted, relaxable per-lineup rule for
narrow-breadth postures, at least one hitter under 10% predicted own INSIDE
the primary stack. Inside the stack matters: the archive's paying pattern is
low-owned pieces within chalk-positive correlated lineups, not dangling
one-offs, and the optimizer's `high_owned_one_offs` term already penalizes
the dangling kind once real tiers exist. Relax-and-count like every other
control; never a pool edit.

**I6. Duplication budget, replay-calibrated (attaches to R10 + R118).** R10
already grades the prior on duplication; the control half: per-portfolio cap
on lineups in the top predicted-dup decile for satellite postures, calibrated
against R118's exact dup counts vs real archived fields, relax-and-count.
R118's replay also A/Bs it for free (same bank, control on/off, scored
against the real field).

**I7. Field-share-adaptive shape allocation (generalizes R37(2)(b)).**
R37(2)(b) already mandates reading the shape's CURRENT field share rather
than assuming lift. Generalize: R48's persisted per-contest tables give a
rolling field share for 5-stack / 4-2-x / SP-pair concentration; the stack
plan tilts the portfolio's shape mix away from shapes at their archive-high
field share, bounded and counted, feasibility floors untouched. Same players,
different architecture: construction contrarianism, which is the only kind
the archive supports outside supersats.

## C. New surfaces worth their own entries

**I8. Showdown captain-leverage ladder (new, S-M; report first).** The
measured gap is ours to close: tranche winners captained 9.1 median own vs
our 15.4, and dup share above 500 entries is 55.9%, so captain choice is
where a 6-entry Showdown portfolio is actually distinct or actually a copy.
Step 1 (report): captain own-tier histogram + predicted-dup per entry in the
Showdown brief (I2 carries it). Step 2 (control, decision): tier targets per
portfolio, e.g. at most N entries on the top-2 structural-own captains and a
floor on captains outside the top-5, enforced beside `max_cpt_exposure_pct`
with the same relax-then-count discipline. Caveat stated: the 64-contest
measurement says winners captain at-share overall; the 9.1-vs-15.4 read is
one 8-contest tranche. Showdown stays review-grade regardless.

**I9. Opponent-conditioned field profiles for recurring satellite families
(new, M; the creative one).** Satellite fields are 80-91% regulars, winners
were regulars 132/148, one username appears in all 270 archived contests, and
the rebuilt registry (3.19) holds 15,402 users with 2,211 regulars. For the
handful of contest families Ben re-enters nightly, the field is not an
abstraction; it is a recurring population whose construction habits are
archived per user. Proposal: a deterministic per-family profile from the
registry + mined decompositions (chalk share, shape mix, salary-leave, dup
propensity of THAT family's regulars), consumed as the reference distribution
for I6's dup budget and I7's shape tilt in that family, instead of a generic
field. "Different from the 40 people who actually show up" is a smaller,
better-measured target than "different from the field." Ledger 3.18 already
says this is what makes the Section 5 opponent work worth building. All data
is DK's own standings exports, manually pulled; no wall is touched.

**I10. Late-swap leverage pass (new, S).** After first lock, scratches and
posted lineups move the field's remaining chalk. A report-only mode on the
swap path: recompute the structural prior on the post-lock slate state and
list unlocked exposures now sitting in the top structural-own tier, with the
differentiated same-team/same-slot alternatives from the bank. Operator
decides; `run_late_swap` rails unchanged.

## D. Decisions that are Ben's (minutes, not sessions)

- **D1. Act on salary-leave or keep it recorded.** 3.17 explicitly holds it
  "recorded, not acted on." I2 reports it; acting on it (a portfolio
  distribution target over total-salary bands) is a strategy change. R118
  replay can price the ceiling cost before deciding.
- **D2. Supersatellite posture.** The one archetype where winners run
  anti-chalk (-13.2) and our weakest family. Once R10's satellite prior
  exists, does the supersat cell get its own ownership-budget tilt, or do we
  stop entering the family (R13 territory)?
- **D3. Captain ladder defaults (I8 step 2)** once the report has run for a
  few slates.

## Walls, restated so the merge inherits them

No pool reduction ever (all of this is objectives and counted, relaxable
constraints). No DK fetching; ownership inputs are structural priors and
manually pulled archives only. Exposure-cap raises stay Ben's. Truthful
labels on every surface: prior, proxy, observed outcome; never a probability
claim. Showdown ships review-grade.

Suggested order if it all survives: I1+I2 now (they feed everything and
gate nothing), I4 as a skill note, I3 when a slate is quiet, then B rides
Tier 2 as sequenced, I8-I10 behind them, D-items whenever Ben has minutes.
