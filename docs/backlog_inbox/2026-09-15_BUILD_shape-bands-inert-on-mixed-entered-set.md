# R37(2)'s two bands BOTH go inert on a MIXED entered set, which is the ordinary case

BUILD fragment, slate 1840_5g (2026-09-15, 5 games, 8 entries, 5 contests).
Not a backlog edit; DEV merges or discards. Filed the same date R340 landed.

## The premise, measured rather than reasoned

Ran `resolve_shape_bands` (`mlb_engine/pipeline/execution_pipeline.py:1841`)
against this slate's own posture map at `game_count=5`:

    195667598  wta_satellite  breadth 0.02  narrow  floor=5     quota=None
    195668414  single_entry   breadth 0.01  narrow  floor=5     quota=None
    195668415  large_gpp      breadth 0.12  mid     floor=None  quota=0.1928
    195700604  single_entry   breadth 0.01  narrow  floor=5     quota=None
    195703759  small_gpp      breadth 0.18  mid     floor=None  quota=0.1928

    floor_5_binds_portfolio: False
    quota_binds_portfolio:   False

Three of five contests (4 of 8 entries) declared floor 5; two of five (4 of 8
entries) declared the 19.28% quota. R34's merge requires unanimity in both
directions, so BOTH retire and the portfolio lands on the stage-1 floor of 4.

## What it cost on this slate

Default build (sha `b2c9c853`): `4-2-1-1` x4, `4-1-1-1-1` x2, `3-3-1-1`,
`3-2-2-1`. Zero five-stacks, zero 5-2-1. That reproduces ledger 3.21's "single
largest observed portfolio-vs-cohort gap" (ours 5-2-1 at 0.4% against field
25.7% and top cohort ~40%) on a 5-6g slate, the bucket where 3.21 puts the
5-2-1 lift at +15.6pp replicated across both halves.

Rebuilt identically plus `--controls-override '{"min_five_stack_share_pct":
0.50}'` (sha `13efc9af`): 6 of 8 entries take a five-man primary, 3 of 8 are
5-2-1, and the allocator placed a five on all four narrow-breadth entries
without being told which entries they were. Apex total 1157.02 -> 1165.12.
Washout proxy unchanged at 50% (`team_footprint`, PHI 4/8); entries untouched
by the binding game 0/8 -> 1/8; max pairwise overlap 5 -> 4 players. Both
builds certified on all three gates and passed `preflight_upload` at exit 0.

## Why this is not R340 again, and not a request to overturn R34

R340 (this date) wired the request to all three bank doors, and the override
above is the evidence it now reaches the solve: before R340 this same flag
produced `relaxed_off / no_qualifying_candidate_in_bank`. R34's unanimity is
deliberate and its docstring argues the case, which this fragment does not
dispute.

The gap is that NEITHER band has a path to a mixed entered set, and a mixed set
is what an ordinary night looks like: any portfolio holding one satellite and
one Jukebox is one. Two readings, for DEV to arbitrate rather than for a BUILD
session to pick:

(a) The merge is right and an operator override is the intended escape. Then
    the bands' inertness on mixed sets belongs in `skills/generate-lineups/
    SKILL.md`, so a build session reaches for the override deliberately instead
    of discovering it by re-running the resolver under a lock clock, which is
    what happened here.

(b) The bands should route per CONTEST at allocation rather than per PORTFOLIO
    at merge. The allocator already assigns entries to contests, and on this
    slate it independently put every five-stack on a narrow-breadth entry, so
    the per-contest intent survived without the portfolio-wide floor. That is
    one slate and one observation, not a result.

## One reporting gap noticed alongside

No `shape_bands` block appears in either brief. Searched both recursively for
`shape_band`, `five_stack`, `stack_min`, `primary_stack_min`, `breadth`,
`bank_stack`: the only hit on the v2 brief is
`controls_override_applied.min_five_stack_share_pct`, and the v1 brief has no
hit at all. The ledger Quick Card calls `floor_5_binds_portfolio` "the one-line
answer" for which floor bound and why, so on this path there is no way to see
that the bands went inert without re-deriving them by hand.

## Third item: `qa_portfolio.py` has no stack-shape axis at all

This is why the gap survived a passing certification AND a clean adversarial
pass on the same file, and why it took Ben asking. The QA pass ran on the v1
file, produced four findings, and said nothing about the portfolio carrying
zero five-stacks into a 5-6g slate.

Its four washout axes are `game`, `stack_team`, `team_footprint` and
`starting_pitcher`. `stack_team` counts each entry's HEAVIEST team and only at
3+, so it reported `CIN at 2/8` for v1 and `CIN at 2/8` for v2 identically,
while that stack went from four bats to five. Section 2 compares stacks to
market implied totals and arms to Savant. Nothing in the tool compares the
delivered shape distribution to the cohort shares the ledger measured.

Verified at this head rather than assumed:

* `grep -n "shape\|5-2-1\|five_stack\|stack_size\|primary_stack\|cohort\|FIVE_STACK" tools/qa_portfolio.py`
  returns 17 hits. Every one is CONTEST shape (the archetype-projection
  vocabulary) or the control-name legend at `:551`. None reads a roster stack
  size.
* The one candidate hit, `team_shape_spread` (`tools/qa_portfolio.py:224`), is
  SHOWDOWN-only: written at `mlb_engine/optimize/showdown_theses.py:757` as
  `len(splits)` over the six-man team split. It never touches a Classic roster.
* The number it would need is ALREADY IN THE TREE:
  `FIVE_STACK_FIELD_SHARE_MEASURED` (`execution_pipeline.py:1673`, 5-6g =
  0.257), with `read_five_stack_field_share` resolving it per slate-size bucket
  at `:1809`.
* The tool already carries a documented precedent for reaching into the engine
  for exactly this kind of read: R136's single import at
  `tools/qa_portfolio.py:59`, whose comment says the tool "reads rather than
  copies" the shape-to-archetype projection.

So this is ledger 3.20's own class, a fact the repo already holds and never
reads. Proposal: one line in section 3 putting the delivered shape distribution
beside the bucket's measured field share and the top-cohort share, labeled an
observed cohort share and never a probability. Whether it should ALSO raise a
section-2 finding when the five-stack share is 0 on a 3g+ slate is DEV's call.
The measurement is the part that is missing; the threshold is a separate
decision.

Note the ordering this implies for a BUILD session until it lands: the shape
check has to happen BEFORE the QA pass is trusted, because a clean QA pass
currently carries no information about shape either way.
