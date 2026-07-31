# Changelog

What changed in the engine, the tools and the contracts, when, and why.

**Scope.** Code and contract changes only, the DEV write set: `mlb_engine/`,
`tools/`, `tests/`, `docs/`, `skills/`, `CLAUDE.md`. Slate outcomes and
calibration belong in `ledger/MLB_Classic_Calibration_Ledger.md`; per-build
records belong in that run's brief. This file is not a review document and never
grows a "lessons" section.

**Writer.** DEV only, one entry per shipped change, newest first. Other roles
record by dropping a fragment in `docs/backlog_inbox/`.

**Unit.** The R-number already used in commit subjects and the backlog. An entry
says what moved and why it moved; the diff says how.

**Decided vs shipped.** A `Decided` entry records a call that has been made and
not yet built, because the reasoning is the part that gets lost and a decision
is a fact with a date. It names who decided and links the backlog item that
carries the work. When it ships it gets a normal entry; the `Decided` entry
stays where it is rather than being edited into the past.

**Truthful labels.** Entries describe deterministic behavior. Nothing here is a
performance claim.

---

## 2026-07-31 — Decided, not yet shipped

### Decided: remove the `reuse_penalty` term rather than invert it
Ben, on DEV's recommendation. Backlog R36 Finding 11.

`reuse_penalty` has always rewarded reuse. `milp` minimises, the used-candidate
indicator carries a positive coefficient, and minimising a cost per DISTINCT
candidate prefers fewer distinct lineups. The name says the opposite.

Removal over inversion because the term is redundant by construction: it is only
live when `max_shared_players` is set, so it duplicates a hard cap with a soft
nudge at a different scale. Nothing was tuned against its stated behaviour, and
no rationale for penalising reuse beyond the hard cap was ever written down.

One inherited claim withdrawn: inversion is not structurally unsafe. `y_k` is
pinned bidirectionally, so a sign flip would behave. It is unwarranted, not
broken. Blast radius is also smaller than previously stated, since the
coefficient is 0.02 against scores normalised to [-100, 0], so only near-ties
move. Expect the golden replay to shift on some fixtures.

### Decided: R10's gate conditions on the satellite archetype, and R10 is unblocked
Ben, on DEV's recommendation. Backlog R10.

The gate reads "N slates in the satellite archetype", not "N
archetype-conditioned slates" generally. Satellites are 4,201 of 4,879 of Ben's
MLB entries, the item's own justification is the satellite case, and CLAUDE.md
already forbids pooling ownership across archetype and field size, so
conditioning was already the house rule.

Scope is the safeguard, not breadth: the prior is fit and shipped for satellites
only, every other archetype stays on flat-12, the fit cell is (family, field-size
bucket), and thin buckets stay unmodeled rather than pooled. The bar is
unchanged, beat flat-12 in that cell before any production column flips.

---

## 2026-07-30 (later) — R32 round 2: paste intake, field feedback

Three defects from the 1910_6g build. R32 and R33 shipped the day before, so
this is that family's second round rather than a new topic.

### Fixed
- **A game with only one posted side attached that lineup to the WRONG TEAM.**
  `1. TBD` matched no rule, so it was not a block, so the posted nine became
  `block[0]` and `_assign` handed it to `headers[0]`, the away side. A TBD
  placeholder now opens an EMPTY block and holds its position. The same shift
  existed one field over: a bare `TBD` where a probable's name goes now appends
  a `None` that holds the pitcher slot, so the one announced starter stops
  sliding into the away side.
- **`_assign` guessed on a count of one instead of refusing.** Blocks and
  pitchers now attach only at a count of 0 or exactly 2, which is the rule the
  module docstring always claimed. Refusing is cheap now that DK backfills a
  probable.
- **Pitchers dropped from a link-free paste.** The pitcher path required the
  MLBAM id that only a markdown link carries, so a plain-text paste resolved 36
  hitters and zero pitchers, producing five hard pool blockers. A pasted line is
  now held and promoted by the `RHP`/`LHP` line after it; the venue is whatever
  bare line was displaced without being promoted.

### Added
- DK's `Starting` column (SP/P) is a first-class probable source, not a manual
  patch. On 2026-07-30 DK declared Robbie Ray for SF while mlb.com and the
  StatsAPI both still showed TBD, so the CSV was ahead of both feeds and
  CLAUDE.md already makes it authoritative. The paste still wins where both name
  someone; a disagreement is reported, never repaired.
- Bulk-absence blockers for NOT IN DK POOL, with the thresholds in the report.

### Changed
- **NOT IN DK POOL policy, and the docs now match the code.** A feed was written
  despite 18 of these. Per name it stays non-fatal, because DK owns eligibility
  and a player DK did not list is unrosterable anyway. In bulk it blocks: past
  half of one posted side, or a quarter of the whole paste with at least six.
  Eighteen of them is one wrong-pairing fact, not eighteen call-ups. CLAUDE.md
  build-contract item 1 and the skill both said "no feed is written" without
  qualification, which the implementation never did.

### Tests
29 → 56 in `tests.test_paste_lineups`; pin 556 → 583. Two fixtures added: the
real link-free 6-game paste verbatim, and a half-posted-game file labelled
RECONSTRUCTED in its own header, because its content is verbatim but its line
order is restored rather than captured. The old fixture had every side posted,
which is why 29 tests passed over a wrong-team bug.

### Why it matters
Only the first of these could put a lineup on the wrong team in a file Ben would
upload. It failed safe on the live slate by luck of the crosswalk, not by design.
The 18 absences that drove the third defect were caused by the first, so the new
threshold is a second, independent detector of the same misfiling.

---

## 2026-07-30 — R33, R34, R35

- **R33** — the paste's `<TEAM> Lineup` header is cross-checked against the club
  link. `DK_ABBREV_REMAP` exists because the two vocabularies disagree on seven
  clubs (AZ/ARI, WSN/WSH, TBR/TB, CHW/CWS, KCR/KC, SDP/SD, SFG/SF), so a paste
  rendering any of them produced a `game_id` matching nothing and the game was
  silently skipped. The club name wins, being the unambiguous read.
- **R34** — primary-stack SIZE control, shipped off by default.
- **R35** — `upload_ready` stops being a label anyone can earn. Reserved for a
  certified export where all three gates pass.

## 2026-07-29 — R32, R29, R28, R26, R27, R19, R6, R7

- **R32** — a pasted mlb.com lineup is the PRIMARY source and is never
  re-fetched; the API feed is fallback for uncovered sides only, via
  `--merge-feed`. Re-fetching what Ben just typed wastes a call and invites the
  two to disagree.
- **R29** — seven defects from a review pass over that session's own six
  commits; four fragments merged; test pin 437 → 498. Includes: `verify_export`
  re-derives locked teams from the clock every run; the latest-run pointer is
  promoted at delivery rather than certification; a swap inherits the build's
  portfolio controls and says which cap binds; `late_swap` takes `--salary` so a
  swap never depends on shared staging; the odds fetch stops reporting a parsing
  bug as an absent market.
- **R28** — bank-aware checkpoint pre-solve, three refusal legs.
- **R26/R27** — postponed-game exclusion; gate-failure narration; stale-platoon
  policy warns rather than blocks on the script path.
- **R6/R7** — production-controls golden replay, solver-independent behavior
  tests, fixture evals, pinned runtime.

## 2026-07-28 — R18 through R25, multi-session work

- **R18** — multi-session contract v1: roles, claims, the foreign-dirt rule,
  fragments.
- **R24/R25/R27** — contract v1.1: builds never block builds, beacons added.
  `late_swap --lineups`, total `--budget`, `--solver-budget`.
- **R19/R20/R21/R22/R23** — claim tool; preflight `--expect-sha256`; unique tmp
  names; late-swap delivery identity; inputs-unmoved gate; pointer CAS;
  parent-lineage block; bank merge-on-save; miner inbox move.

## 2026-07-27 — F18, R1 through R16

- **F18** — the ballpark is priced once. F1's implied total is divided by the
  game's park run factor before the slate-mean ratio, so `Base x F1 x F5` does
  not double-count the park.
- **R1a/R1b/R1c/R1d** — a satellite stops being scored as a winner-take-all; the
  ticket line is scored as a ticket line; `objective_class` and `ticket_count` on
  the curated archetype CSV.
- **R2/R3/R4** — the preflight stops telling the caller a comfortable story.
- **R5** — the satellite family takes section 8's caps.
- **R15** — DU stops claiming an enforcement it does not perform.
- **R16** — the gpp profiles stop advertising a split they do not apply.
- **R8/R9a** — the instructions stop restating the procedures they point at.

Two adversarial passes in the same period fixed seven further defects in that
session's own work.

---

Anything before 2026-07-27 lives in `git log` only. This file starts where the
R-numbering became the unit of work.
