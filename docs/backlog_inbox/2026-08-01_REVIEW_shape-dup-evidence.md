# Fragment: evidence updates for the stack-shape item, R10, and two small ones

Session: unassigned read-only review, 2026-08-01. For DEV. Full working in
`outputs/2026-08-01/mined_data_review_2026-08-01.md`. Deterministic review
statistics and observed outcomes only.

## 1. Stack-shape work (extends 2026-07-30_archive_stack-shape-gap.md — merge, don't fork)

Three additions to the existing fragment, none contradicting it:

- **The mechanism is also in bank generation, not only the objective.**
  `bank_cache.extend_bank` enumerates (SP pair, stack team) jobs at
  `stack_min=4, stack_max=5`; the mean-max solve settles at 4; nothing shapes
  the secondary. The scoring-side `stack_bonus` (max +2.75) can only rerank
  candidates that exist. An objective-only fix under-delivers: some share of
  jobs needs `stack_min=5` (or a secondary-pair job dimension) so 5-2-1
  candidates exist to be scored.
- **The "shape vs size" question the fragment left open now has an answer in
  the data: shape.** Win line, 53 eligible Classic contests: 5-2-1 takes
  34.5% of the 58 contest wins (field share 25.1%), 5-1-1-1 12.1% (share
  6.5%), while 5-3 under-wins (8.6% of wins on 16.5% share) and its
  top-decile and cash-line lifts both sit at zero. Target 5 primary + small
  secondary, not "any 5-stack."
- **Cash-line vs win-line split, and the near-misses.** At the paid line the
  shape lifts flatten to ±1pp (our 4-2-1-1 clears cuts at field rate); the
  entire deficit is top-decile and above — which is all that pays in the
  one-seat satellites that are 84% of archived volume. Zero seats in 234
  archived one-seat-sat entries, 8 top-3s; in 4 of the 8 the winner was a
  5-2-1. Also worth naming in the work: 4-2-2 (7.7% of our Classic mix) is
  reliably bad (−4.5pp [−7.1,−1.5], 26% positive replication).

## 2. R10 (unblocked, satellite-only): starting priors and a Showdown fact

- Observed duplication for the fit: satellite winners unduplicated in
  95–100% of contests per field bucket; field dup share median 0% (≤150) to
  19% (151–500).
- **Our field-duplicated copies are ~20 of 31 Showdown**, up to 15 copies of
  one build (192708059, our rank 58). No duplicated copy has finished near a
  seat yet, in either format. The duplication screen R10 wires into the
  checkpoint is currently Classic-pathed; Showdown is where our duplication
  actually occurs and Showdown bypasses `run_slate`. Worth scoping whether
  the screen lands somewhere Showdown can reach.

## 3. Miner: preserve the CPT slot (S)

`players_norm` is position-blind, so showdown captain choice — the largest
showdown construction decision — is invisible to every downstream analysis.
The raw standings Lineup cell carries the `CPT` marker (verified on
192344519). One parse change plus re-mine makes captain analysis possible
retroactively. Pairs with the existing R30 miner items.

## 4. Verify one-seat satellite profile routing (S, check before any change)

`wta_ticket_satellite` (ceiling 1.0, stack bonus 1.0, uniqueness 0.65) exists
for the 1-seat case; the `satellite` profile (floor 0.42, stack bonus 0.35)
is a min-cash shape for a contest where min-cash pays nothing. Briefs don't
record posture per contest, and `posture_allocator` reads `paid_places` off a
contest dict nothing populates (3.13, R30). If Pocket Cup builds have been
scoring on `satellite`, the floor blend has been pulling toward exactly the
construction the archive says does not win seats. One check, then decide.

## 5. Status note

`reuse_penalty` (decided removed 2026-07-31, R36 Finding 11) is still live at
`contest_allocator.py:732/798/1625` as of this review.
