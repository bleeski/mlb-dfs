# Final Consolidated Critique | MLB DFS Engine | 2026-07-25

**This document supersedes** `docs/2026-07-19_red_team_review.md`, `docs/2026-07-24_red_team_review.md`, `docs/2026-07-25_red_team_review.md`, and the independent critique of 2026-07-25. It is the single live backlog. When an item lands, mark it landed here; do not write a new review to say so.

Basis: tree at `e58b3ac` plus untracked files. Synthesis of two independent adversarial reviews (referenced below as **RT** for this session's review, **IC** for the independent critique), reconciled item by item. Every IC claim that changed a priority or a fix was re-verified against code this session before acceptance; one was rejected on evidence (see disposition). Claims marked **[executed]** were reproduced by running code against real production files. Nothing in the repo was modified to produce this document.

Priorities: **P0** corrupts what gets uploaded or lets an invalid file certify. **P1** silently degrades lineup quality or destroys evidence. **P2** wastes time or tokens. Effort: S under 30 min, M a few hours, L a day or more.

---

## Landed 2026-07-27 (Stage 3: F18)

**F18 LANDED.** projection_builder v1.6, live_data_adapters v1.6,
slate_intake_manager v1.10, audit v3.2. Suite 329 (core 254), 22 modules. Seven
sabotage reverts, seven failing gates.

Park ownership is decided and recorded as a dated ledger decision (invariant
3.10). F5 owns the ballpark; `build_f1_factors` divides each team's implied total
by its game's `park_run_factor` before the slate-mean ratio, and the denominator
is the mean of the same de-parked quantity, so `Base x F1 x F5` prices the park
once. The rejected alternatives and the reasoning are in the ledger, not here.
`implied_total_by_team` and `league_mean_implied_total` stay RAW, because the
brief and the ownership work mean the market's number by those names;
`deparked_implied_total_by_team`, `park_run_factor_by_team`,
`f1_ratio_denominator` and `f1_ratio_basis` are new. Omitting the park map keeps
the old behavior and sets `park_adjusted: False` with a note that says the park
is being counted twice in that build.

`select_one_leg_per_matchup` is now the one leg rule; `_select_slate_legs` is a
thin lineups-feed wrapper over it and `parse_the_odds_api_totals` calls it too,
so a doubleheader's two totals no longer collapse by last-write-wins. Pass
`slate_game_times` (from the new public `salary_game_times`) and the leg matching
the salary start wins; without it the earliest leg wins, which is a rule rather
than an accident of iteration order. The other leg is reported in
`doubleheader_legs_dropped` with its own total and `legs_by_game_id` keeps both.
`build_slate.load_odds_packet`, `showdown_moneyline` and `tools/stage_slate.py`
all pass the salary file.

`build_slate.resolve_slate_venues` is the single venue resolution both F1 and F5
read. It loads `game_venue_overrides.csv` keyed `(date, AWAY@HOME)`, which had a
loader, a resolver and zero callers outside its own module; a `manual_required`
row with no `Run_Factor_Applied` takes a NEUTRAL 1.0 park factor and is named on
the checkpoint, because an unapproved special venue is not a licence to reuse the
wrong park's number. A neutral site has no forecast under its own name in the
bundle, so wind stays neutral there and the venue is named rather than borrowing
another city's wind.

Delay and postponement risk are derived from the forecast's precipitation
probability instead of the hardcoded "none" that made both branches of
`compute_f5_factor` unreachable; the level comes from the WORST hour in the game
window, not the middle one the wind read uses. `risk_from_precip_probability` is
the mapping and it gained a "none" band below 15%, which changes no number (delay
low is a 1.000 factor and there is no postponement low row) and stops a 0%-rain
forecast printing "low delay risk". The wind gate uses `OUTDOOR_ROOF_TYPES`
instead of `== "outdoor"`, so Sutter Health Park (roof_type `temporary`,
sensitivity HIGH, threshold 8mph, the most wind-sensitive park on the schedule)
takes a wind adjustment for the first time.

**Two corrections, because the item did not hold as written.**

1. The acceptance line "a Coors fixture's combined uplift stays inside the F1
   clip band" is not achievable by de-parking, and asserting it failed. F1's clip
   is applied to F1 alone, so on a wide-enough slate F1 saturates at 1.15 and the
   product still reaches `1.15 x park`. De-parking removes the double count; it
   does not bound the product. The gate now asserts what is true (1.173 to 1.098
   on a realistic spread; 1.242 to 1.131 on the real 07-25 four-game slate) and a
   second test states the saturation limit in its own docstring so nobody reads
   the first as a bound.
2. "The legacy reader misreads the precip key" is true and was dead.
   `_legacy_risk_from_precip` is reachable only from `_normalized_weather`, whose
   only callers are `material_weather_adjustments` and
   `validate_slate_context_packet`, and neither has a production caller anywhere
   in the repo. So the key fix closed a latent defect, not a live one. It still
   belongs, because `build_f5_map` now feeds real precipitation and the mapping
   it calls is the same one.

One thing this deliberately did NOT do. `tools/fetch_slate_bundle.py` still
builds its venue list from `team_to_venue.csv` alone, so a neutral-site game's
forecast is fetched at the nominal home park's coordinates and filed under the
nominal home park's name. F5 refuses to use it and says so, which is the
fail-safe behavior; fetching the right coordinates is a separate change to a
network tool and belongs with F23 hygiene.

Open after this: F20 (caps, deferred by decision), F3b/F3c, F22, the F23
remainder, and Section 2 beyond G1 and G4. Cluster C is now clear.

---

## Landed 2026-07-27 (Stage 3: F16 and F17)

**F16 LANDED. F17 LANDED.** live_data_adapters v1.5, late_swap_manager v1.4,
audit v3.1 pins updated. Suite 312 (core 237), 22 modules. Every fix below was
verified by sabotage: ten reverts, ten failing tests.

F16, what changed. `tools/late_swap.py` resolves each contest's posture and shape
through `_resolve_contest_postures`, the same function the build uses, and passes
the resulting map into both `build_entry_requirements` and `run_late_swap`; a
name that matches no archetype exits 3 naming `--postures`, and
`--ignore-unresolved-postures` is the recorded override. `as_candidates` now gets
the projection frame and the shapes the reserved file actually contains, so a
cash entry is scored in cash mode instead of being ranked on a ceiling-max score
with floor_sum reading 0.0; the payload report's scored/failed counts print. The
disk feed is checked before anything else reads it: a feed whose `date` is not
the slate date blocks, a feed over 90 minutes old warns, and the `Z`-suffix
parse that Python 3.10 rejects is handled, without which the age check would have
reported "unknown" on every real feed. After the solve, the incumbent roster and
the chosen roster are scored under the entry's own shape and the per-entry delta
prints; a negative delta refuses to mirror to `outputs/` without
`--accept-downgrade`, and the run directory stays as the record either way.
`validate_late_swap_delta` now distinguishes `None` (unrestricted) from an
explicitly empty authorized set (nothing may change); it collapsed both to
"anything may change", while `validate_template_preservation` had always read the
empty set as fail-closed. The two now agree.

F17, what changed. A side the feed marks `partial` no longer has its hitters
stamped `Confirmed_Starter`; they are `Projected_Starter`, and the sides are
reported in `partial_lineup_teams` and named in the pool report.
`tools/fetch_slate_bundle.py` emits `partial` for any side with one to eight
hitters posted, and `build_slate.py`'s own feed writer, which collapsed that case
into `tbd`, now derives it the same way. The platoon reference is aged against
the slate date instead of against its own `collected_date`, warning past 3 days
and blocking past 7 when a TBD team is actually being filled from it
(`stale_platoon_policy='warn'` downgrades it; `build_slate.py`'s existing SOFT
tier already matches the blocker text, so it prints and the build ships). All
four platoon report keys reach the operator instead of only `zero_fill_teams`.
DK's `Starting=PO` maps to `viable_bulk_or_alt_sp` with a warning naming the
player, which keeps an opener rosterable but outside
`REQUIRED_SP_AUDIT_STATUSES`. The platoon file joins the tracked reference set in
`refresh_reference_data.TRACKED_JSON`, aged from its own payload rather than from
mtime, which a checkout resets.

**Three corrections, because the claims did not hold as written.**

1. F17 says `CONFIRMED_STARTER` sitting in `SAFE_UNLOCKED_STATUSES` is part of
   the defect. `SAFE_UNLOCKED_STATUSES` has zero readers anywhere in the repo.
   It is dead.
2. F17 says partial-as-confirmed "defeats the TBD policy check". The only
   consumers of `PlayerLineupStatus.status` are `validate_tbd_policy` and
   `_eligible_for_pivot`, and neither has a caller anywhere, including in tests.
   Every live consumer of the status map reads `is_locked()`, which is purely
   time-based. So the mis-stamp was a false label with no live consequence, not
   a defeated check. The fix still belongs (the field is wrong, it is cheap, and
   the moment anything reads it the lie becomes real) but it closed a labels
   violation, not a live hole. The observable win is the pool report line.
3. F16 says late swap "asserts all gates true (F4)". F4 already fixed that on
   2026-07-26: the tool derives three gates and names three assumed ones in
   `LATE_SWAP_ASSUMED_GATES`. Nothing to do. The same is true of the
   excluded-new-teams contradiction F16 inherits from F15, which F15 closed.

Two things this deliberately did NOT do. The downgrade refusal branch is guarded
by review, not by a test, because reaching it needs a promoted parent run and a
completed joint solve; the scoring it is computed from is tested under two
shapes. And `verify_export.py` still reports only `slots_changed`, because the
swap tool owns the score comparison and `verify_export` has no projection frame.

Open after this: F18 (factor ownership), F20 (caps, deferred by decision),
F3b/F3c, F22, the F23 remainder, and Section 2 beyond G1 and G4. Nothing left in
the backlog can cost a slate; what remains is lineup quality, test coverage,
hygiene, and G7.

---

## Landed 2026-07-26 (Stage 3: F21 and F19)

**F21 LANDED. F19 LANDED.** Engine v3.21, new module `mlb_engine/determinism.py`
v1.0, audit v3.1. Suite 294 (core 219), 22 modules.

F21, what changed. `excluded_flags` is the single reading of the Excluded
column and the four `df['Excluded'] == False` sites now call `_drop_excluded_rows`
instead. Only an affirmative token removes a player (`true/t/yes/y/1/x/exclude/
excluded/drop/out`); blank, NaN, None, `"False"` and every other false-ish token
keep them. An unrecognized token also keeps the player, is counted, and is named
in the checkpoint as a blocker, because the defect being closed is players
disappearing and guessing "exclude" on an ambiguous cell would reintroduce it in
a new costume. Counts land in `checkpoint["exclusions"]["excluded_column"]`
alongside the explicit exclusion set. The SP-cap denominator no longer shrinks on
a blank cell, which is the part that changed the auto anchor caps silently.

F19, what changed. `stable_union` and `stable_ids` in the new determinism module
replace every `list(set(...))` on the solver path: the two lock merges and the
exclude merge in `build_multi_lineup`, the lock merge in the augmentation pass,
`locked_ids` in `build_single_lineup`, the stack-core blocklist, and the capped
SP-pair combos (which were tuples unpacked from a frozenset, so their internal
order was hash-dependent too). `tools/audit.py` runs the suite with
`PYTHONHASHSEED=0`; `build_slate.py` and `tools/late_swap.py` re-exec once with
it pinned, guarded on `__name__ == "__main__"` so importing them does not replace
the importer's process. `runtime_preflight` now carries `hash_seed`, so a run
record states which footing the build ran on.

**A correction on F19, because the claim did not hold as written.** The review
says an unpinned seed means "identical inputs can certify different files across
processes". The mechanism is real and I confirmed half of it: set iteration order
over these player IDs does vary by seed, and those lists did become MILP
constraint rows. The consequence did not reproduce. With the sorting deliberately
removed and three different seeds, both the small pipeline fixture and a tie-rich
four-pitcher / six-SP-pair bank produced byte-identical exports every time; HiGHS
presolve absorbs the row-order difference at these pool sizes. So F19 removed a
real nondeterminism source, but no divergent export was ever observed, and the
"same inputs, same file" claim was probably true in practice before this change.

That distinction is reflected in the tests. `test_solver_inputs_are_identical_
across_hash_seeds` is the gate with teeth: it captures every locks/excludes/
forbidden-combo/stack-core list handed to the solver across three seeds, and it
was verified by sabotage (three digests unsorted, one digest sorted).
`test_two_processes_with_different_seeds_produce_one_file` is an end-to-end
regression guard whose docstring says plainly that it passes with or without the
fix on the fixtures available, so nobody later reads it as proof.

Open after this: F16 (late-swap identity), F17 (intake trust), F18 (factor
ownership), F20 (caps, deferred by decision), F3b/F3c, F22, the F23 remainder,
and Section 2 beyond G1 and G4. F16 is the recommended next: it is the only
permitted post-delivery path, it runs closest to lock with the least
verification, and F4 and F15 both left work parked in it.

---

## Landed 2026-07-26 (Stage 3 start: F13 and F15)

**F13 LANDED. F15 LANDED.** Engine v3.20, allocator v1.11, bank_cache v1.2,
pipeline v1.12. Suite 285 (core 210), audit pin updated.

F13, what changed. `SOLVER_TIME_LIMIT_S` replaces the hardcoded 30 and threads
through `run_slate(solver_time_limit_s=)` -> bank -> `build_multi_lineup` ->
`build_single_lineup(time_limit_s=)`. Every solve fills a caller-owned
`status_out` dict, so the module global that the next solve overwrote is no
longer the only record. A time-limited incumbent is verified against the same
constraint matrix the solver was handed (integrality plus every row within
bounds) and then accepted, tagged `optimality='time_limited'`; an incumbent that
fails verification is rejected and counted, because accepting an unverified one
into a certified export would be worse than the original bug. On a timeout the
caller does not climb the overlap ladder, does not step DU relaxation, does not
burn the DU penalty retries, and does not fold the solve's cost into the budget
reserve. It records the index in `solver_report.timed_out_lineup_indices` and
moves on. In `bank_cache.extend_bank` a timed-out job no longer enters
`attempted`, so a second slice retries it. In the allocator the single "infeasible
or timed out" string is gone: proven infeasible names the arithmetically binding
control (buckets x cap < entries) or says plainly that the interaction is
binding, and a time limit reports the gap and points at the clock. A candidate
prefilter caps K at ~6x entries, keeping forced-coverage candidates and one
representative per stack and SP pair, because the pairwise block is K-squared and
that is where the allocator's own time limit came from.

One correction to the review as written. It says the caller "breaks out of the
outer loop, so one slow solve ends the whole bank". The `failed_indices.append(i);
break` at optimizer_v3.py:1987 exits the inner `while accepted is None`, not the
outer `for`, so that specific mechanism was not there. The effect was real by
another route and is fixed: `per_lineup_cost`, `aug_cost['max']` and
`extend_bank`'s `worst` are all max-of-observed reserves, so one 30s timeout set
the reserve to 30s and every later iteration then read as unaffordable. One slow
solve did end the bank; it ended it through the budget reserve, not through a
loop break.

F15, what changed. Bank records emit `primary_stack` (and keep `sp_ids`), so the
primary-stack exposure cap adds real MILP rows instead of dying at the export
gate. `candidate_primary_stack` maps the DU signature's 'NONE' sentinel to "" at
the payload boundary and `_candidate_primary_stack` maps it again at the
allocator boundary, so stackless candidates stop forming a phantom cap bucket.
`BankCache.as_candidates` takes `contest_shapes` and scores each one in its own
mode, so a cash entry is no longer ranked on a ceiling-max score with a floor
weight applied afterwards; `build_slate.py` resolves those shapes from the
reserved CSV on the sliced path. Scoring failures are counted in
`cache.last_payload_report` and surfaced as a bank warning rather than swallowed
by `except: pass`; the candidate still allocates on raw objective, because a
short bank leaves a blank reserved row. `excluded_new_teams` without
`player_team_by_id` is now an error, matching the sibling game-cap check.
`run_slate` passes `excluded_player_ids` into the bank build both ways
(`Excluded=True` on the frame and the `excludes` kwarg) and the checkpoint
carries an `exclusions` block that blocks at `approve=False` when an excluded id
matches nobody in the pool.

Open after this: F16, F17, F18, F20 (deferred by decision), F3b/F3c, F22, the
F23 remainder, and Section 2 beyond G1 and G4. (Superseded by the Stage 3 block
above: F21 and F19 are now landed.)

---

## Landed 2026-07-26 (Stage 0, Stage 1, Stage 2, plus F14)

**Stage 2 LANDED.** F9, F10, F11, F12, G4. **F14 LANDED**, pulled forward from Stage 3 because it broke a real build during Stage 1 and its failure mode is invisible in the output.

Open after this (superseded by the Stage 3 block above; F13 and F15 are now LANDED): F16 (late-swap identity), F17 (intake trust), F18 (factor ownership), F19 (determinism pin), F20 (caps, deferred by decision), F21 (Excluded coercion), F3b/F3c, the F23 remainder, and Section 2 beyond G1 and G4.

**Recommended next: F13 and F15 together.** Both cost a slate rather than a few points of lineup quality, which is why they lead the rest of Cluster C. F13 is the compute-becomes-strategy inversion CLAUDE.md forbids: a timeout reads as infeasible, the caller climbs the overlap ladder and steps DU relaxation in response, then breaks out of the outer loop, so one slow solve ends the whole bank and surfaces as "no candidates available" pointing at the pool instead of at the clock. F15 carries two seams that convert into blocked runs at the worst moment: `run_slate` forwards `excluded_player_ids` to validation and feasibility but never into the bank build, so at T-10 the whole remaining budget goes into lineups built around a player who should have been dropped; and direct-path candidates return the literal `'NONE'`, which becomes a truthy phantom cap bucket and causes spurious infeasibility. F21 and F19 are the natural follow-on: both are small and both close holes that change the certified output invisibly.

**State of `outputs/2026-07-25/` (read this before trusting it).** The files there were rebuilt during the 2026-07-26 session while verifying F4, F7, F8, F11 and F14. They are internally consistent, the manifest verifies, and all five pass preflight, but `DKEntries_1605_4g.csv` is a rebuild rather than the bytes uploaded on the 25th. The promoted run directory under `runs/` is the authority for what was actually delivered; `outputs/` is a mirror and always was. `outputs/2026-07-25/_scratch/` holds the ad-hoc thesis scripts, logs and duplicate briefs moved aside during cleanup, including `DKEntries_showdown_theses.csv`, which has 0% embedded-pool overlap against every salary file on disk and must not be uploaded.

**G7 is now decidable.** `tools/net_to_date.py` reads `ledger/own_results.json`, which the miner fills as contests are archived. It starts empty by design: the record written while verifying G4 used the top three finishers rather than Ben's entries and was deleted rather than left in the ledger as fiction. The number arrives from the next archived slate onward, and the runbook now says to capture fee and winnings on the day, because DK exports age out.

Three defects the new tooling found on its own while Stage 2 landed:

- `preserve_prior_slate` took its tag from whatever salary file was staged at the moment of the rename rather than from the file being renamed, so the certified 10-game Classic export had been filed as `DKEntries_1915_1g.csv`, borrowing a one-game Showdown slate's tag, with one brief written under two names.
- Passing `--lineups` overwrote the staged feed unconditionally. A feed for the wrong day destroyed the good copy and left nothing to fall back to. It happened during this session.
- `data/slates/2026-07-25/` held the Showdown pair at the bare Classic names, live, exactly as the review described. The staging guard now refuses it and the files are back under honest names.

## Landed 2026-07-26 (Stage 0 + Stage 1)

**G1 LANDED** `tools/preflight_upload.py`. **F1 LANDED**. **F2 LANDED**. **F3a LANDED** (F3b shape enum and F3c ticket_line scoring still open). **F4 LANDED**. **F5 LANDED**. **F6 LANDED** as decided: the three holes are closed and CLAUDE.md records Showdown as review-grade with the cost stated; full gate integration stays open backlog. **F7 LANDED**. **F8 LANDED**. **F23 partial**: the untracked Showdown modules are committed and the stray feed files are ignored; the rest of the hygiene batch is open.

Two decisions taken on the record. **F20 deferred**: the caps divergence is real and unchanged, but a cap change alters lineup construction and does not belong bundled into an integrity fix; it needs its own dated ledger decision. **F6** resolved as above.

Three findings the new tools reproduced independently while landing this work, which should be read as confirming the review rather than as new items:

- The first rebuild of the 07-25 four-game slate failed on a pitcher with no role, served from a bank cache built before the F1 filter existed. That is **F13/F14**'s job-key defect (`_job_key` omits any projections signature) reproducing live, and it argues for moving F14 up.
- The golden replay had been silently broken by F4 and nothing caught it, because `tools/audit.py` gated `test_core` only. That is **F22** demonstrated, and the audit now gates four suites.
- `outputs/2026-07-25/DKEntries_showdown_theses.csv` shows 0% embedded-pool overlap against all seven salary files on disk. That is the hand-typed-roster defect named in **F23**, confirmed.

Nothing in Cluster B, Cluster C, or Section 2 beyond G1 is implemented. The backlog below stands as written for everything not marked LANDED above.

---

## The governing frame

Three facts govern everything below, in order.

**1. The stakes set the priorities.** Today's 82 delivered entries carry $9.37 in total fees, nearly all satellites and qualifiers at $0.01 to $0.25, against roughly 2,500 lines of governance prose and three red-team reviews in seven days **[IC, executed]**. Builds take 8 to 11 seconds; the solver is not the bottleneck and neither is projection quality. At these stakes the marginal dollar from a better projection is near zero and the marginal dollar from never uploading a broken, misrouted, or IL-carrying file is the whole game. Upload integrity outranks everything, evidence integrity second, lineup quality third, process last.

**2. The engine is hardened against the wrong attacker.** The certification spine defends against a lying caller (hashes, immutability, forbidden assertions) and is wide open to an absent check: six of eight pre-export gates are hardcoded `True`, contest identity is inferred from a six-pattern default list, the Classic path never reads DK's `Status` column, and the delivered-file layer has no manifest. Certification currently measures export legality, not input truth or destination truth.

**3. The review treadmill ends with this document.** Three reviews in seven days re-derived overlapping findings; the constraint is implementation, not analysis. The replacement is one executable pre-upload check (G1), one short artifact-level skeptic pass (G2), and this backlog. No more per-slate codebase reviews.

## Disposition of the independent critique

Accepted whole or merged: B1, B2, B3, B4, B5, B6, B7, B8, B9, B10, B11, B12, B13, B14, B15, B16, B17, B19, B20, B21, B23, B24, B25, I1, I2, I3, I4, I5, I6, I7, I8, I9. Where an IC item and an RT item cover the same defect (B12=RT N-7a, B21=RT N-5, B3=RT N-2, B1=RT N-3, I1=RT E-A, I2=RT E-B, I5=RT E-D, I6=RT N-4), the merged item below carries both anchors; independent double discovery raises confidence.

**Rejected as stated: B22** ("today's certified Classic deliverable cannot be re-verified"). **[executed]** `runs/20260725T212439Z_c2111186/inputs/DKSalaries.csv` exists (the engine already snapshots inputs per run) and contains all 55 delivered player IDs (55/55 overlap). The deliverable is verifiable from the run directory; only the `data/slates/` staged copy was clobbered afterward by the Showdown staging (F2). IC's proposed fix (snapshot inputs into `runs/<run_id>/inputs/`) already exists. The salvageable core is folded into F5: `verify_export.py` should resolve the salary file from the promoted run's snapshot by default, so a post-delivery staging clobber can never orphan verification again. B22's citation of `_feed2.json` as an untracked input source stands and is folded into F23.

**Modified: B18.** The `list(set(...))` lock-ordering claim is confirmed at `optimizer_v3.py:3275` [executed]; the :1899/:1910 anchors did not match a literal grep and should be re-located during implementation (the fix, sorting at every lock-merge site, is unaffected). `PYTHONHASHSEED` unpinned: confirmed. **Modified: I1** design merged with RT E-A: the core tool stays two-CSV and unblockable per IC, with optional flags adding manifest and feed checks per RT.

Dropped from RT's own list as below the value line at current stakes: portfolio decorrelation number (07-24 E-6), sim-decision ceremony beyond one ledger line, doc-only nits not on a read path. Carried silently into F23 hygiene: everything in RT N-17 not individually named below.

---

# Section 1: Issues and bugs

## Cluster A | Upload integrity (P0; fix before the next upload)

### F1. No injury/status filter anywhere on the Classic path (P0, S) | RT N-3 + IC B1/B17

- **What:** `parse_dk_salary_csv` never reads DK's `Status` column (`slate_intake_manager.py:218-236`); the platoon path keeps whatever it matched and the APPG fallback sorts shelved high-APPG bats to the top (`live_data_adapters.py:673-694`). The only production reader of `Status` is Showdown (`showdown.py:102-104`). **[executed, twice independently]** the real 07-24 main salary file yields projected orders seating 17 IL/OUT/DTD players (Seager, Rutschman); today's 4-game file under forced-TBD admits 7 flagged players with zero warnings. The `Confirmed_Out` machinery that exists (`late_swap_manager.py:35`, `slate_intake_manager.py:889`) is unreachable from the pipeline. DK's `Starting` column (confirmed slot 1-9, SP/PO tags) is also parsed by Showdown and ignored by Classic.
- **Why:** an IL bat is a dead roster slot, 10% of a Classic entry lost before first pitch, and the TBD/platoon path this hits is exactly the early-build path the fallback was written for. The platoon reference is 25 days old, so the window is wide open. MLB_Classic §2 lists confirmed-out exclusion as non-negotiable; nothing implements it. This is the cheapest large win in the codebase because the data is already in memory.
- **Fix:** in `build_slate_pool`, drop `Status in {IL, O, OUT, NA}` from pool eligibility before platoon and APPG fill; one warning line per player naming player and team; `DTD` stays eligible with a warning, escalating to a blocker if inside a chosen primary stack. Carry `Status` onto the projection row. Add an independent recheck in `validate_dk_entries_file` and in the preflight tool (G1) reading `Status` straight from the salary CSV so the gate does not depend on intake having run. Use `Starting` as a cross-check: a team with 9 `Starting` digits but under 5 feed matches is a proven crosswalk failure, and the authoritative order is in the authoritative file. Blocker if exclusions leave a team under 9 hitters. Done when: a fixture with one IL top-APPG bat on a TBD team excludes him, names him, and the export validator rejects a hand-built file containing him.

### F2. Entries-file geometry is never validated, the embedded pool is never read, and Showdown data sits at Classic filenames today (P0, M) | RT N-2 + IC B3/B4

- **What:** `parse_dk_entry_rows` validates header cols 0-3 only (`dk_entries_manager.py:215`), identical in both geometries. Parsing a Showdown file at the assumed Classic width pulls DK's Instructions text and embedded-pool IDs into roster cells, defeats `is_blank` (17 of 18 blank reserved rows read as filled **[executed]**), `write_candidate_from_template` pads 12-column rows to 14 and overwrites the Instructions column (`:427-430` **[executed]**), and `validate_template_preservation` exempts columns 4-13 unconditionally so the destruction passes (`:457-463`). The same width constant makes `detect_player_pool_start` unreachable on Showdown files, so `parse_embedded_player_pool` (`:245-271`), DK's own per-file fingerprint of the draftgroup, returns `{}` there and is used only for a count on Classic; `validate_dk_entries_file` builds `allowed_ids` from the same salary CSV that built the lineups, so a wrong-slate build validates against itself. This is live: `data/slates/2026-07-25/DKSalaries.csv` and `DKEntries.csv` are md5-identical to their `_showdown` twins **[executed]**, and `tools/late_swap.py:92`, `tools/solver_probe.py:52` default to exactly those names (late_swap reads `row[4:14]` from a 6-slot file).
- **Why:** the blank-row guardrail CLAUDE.md calls absolute is defeated at the reporting layer; a wrong-salary build is the single most expensive operator error; and the deadline path (late swap) is the consumer most likely to hit the clobbered names. Measured signal strength of the unread pool check: 386/387 overlap for the right pairing, 0 for a wrong-day pairing (IC).
- **Fix:** derive the roster window from the header: validate `header[4:4+width]` against contract slot names (`P,P,C,1B,2B,3B,SS,OF,OF,OF` or `CPT,UTIL×5`), reject on mismatch naming expected vs found (port the detection `verify_export.py:37-47` already has). Then require embedded-pool overlap with `allowed_ids` above 0.95 whenever a pool parses, warn when a pool that should exist does not. `detect_contest_type` runs at every consumer entry (`late_swap.py`, `solver_probe.py`, `verify_export.py`) and hard-fails on mismatch with the declared contest. `_stage` refuses to write a bare `DKSalaries.csv` whose first data row is `CPT`. Done when: parsing today's Showdown entries file as Classic raises; all 18 reserved rows read blank at correct width; late_swap against the clobbered pair exits non-zero; wrong-day pool pairing errors with the overlap ratio.

### F3. Contest identity and objective: cash/satellite contests route to GPP construction through three independent holes (P0, S+S+S) | RT N-1/N-11 + IC I4

- **What:** (a) The production script passes neither `archetypes_path` nor `contest_postures` (zero grep hits in `build_slate.py`), so identity comes from `DEFAULT_ARCHETYPES`, six patterns with no cash entries (`dk_entries_manager.py:278-290`); unknown names fall through `normalize_posture`'s unconditional `return "large_gpp"` (`execution_pipeline.py:626-646`). **[executed]** "MLB $5 Double Up" → unknown → `large_gpp`. The curated 22-row `data/reference/dk_contest_archetypes.csv` is dead on the production path, and longest-pattern-wins misroutes real names: today's "…Satellite to $2 MLB Pocket Cup MEGA Qualifier…" matches Pocket Cup over Satellite/Qualifier; "Single Entry Satellite" resolves single_entry over satellite. The ledger Quick Card already says never trust the inference; the paved road offers no way to obey. (b) The shape vocabulary is inconsistent across consumers: posture `mme` maps to `mme_top_heavy`, which `resolve_contest_shape_profile` raises on (**[executed]**, killing any "150-Max" build on the direct path) while `_candidate_shape_score` silently returns unscored `base` for it and for `mme_gpp`, `mid_field_gpp`, `portfolio_gpp`, `single_entry_gpp` (`contest_allocator.py:410-417`). (c) Even correctly routed ticket contests are scored wrong: `satellite` is `mode_family='ticket_line'` with only `== 'cash'` branches, so it silently takes pure ceiling; `single_entry_gpp` builds in `wta` mode (`execution_pipeline.py:2306`) but scores as `portfolio_ev` (`optimizer_v3.py:2970-2976`); `right_tail_weight`/`leverage_bonus_weight` are defined in all 12 profiles and read by nothing, and `right_tail_bonus` is computed and never added to `contest_fit` (`:2865` vs `:2837`).
- **Why:** the portfolio is almost entirely satellites and qualifiers. Satellites pay a ticket for clearing a cut line; a satellite built and scored as a generic GPP, or a Double Up built as `large_gpp`, is the wrong objective on the contests actually being entered, invisibly, every slate. This is the user's stated top fear plus IC's dollars-per-hour logic pointing at the same code.
- **Fix:** (a) `load_archetypes` resolves the reference CSV by default (module-relative search like `posture_allocator._find_archetypes_csv`); replace pattern-length with a priority column plus type precedence (satellite/cash beat generic families); `inferred_type=="unknown"` on a reserved contest becomes a blocker naming the contest; `build_slate.py` grows `--postures id=posture,...` and the checkpoint prints each contest's resolved posture and its source. (b) One canonical shape enum owned by one module; validate every `_posture_to_shape` output against it at import; a test enumerates posture → shape → profile key AND scored branch. (c) Give `ticket_line` a real branch (cash-style weighted component or an explicit ticket formula), align `single_entry_gpp` construction and scoring, and either consume `right_tail_weight` (one line: add `profile['right_tail_weight'] * right_tail['right_tail_bonus']` to `contest_fit`) or delete the keys. Done when: the Double Up / Pocket Cup Qualifier / Single Entry Satellite fixture routes cash/satellite/satellite; a 150-Max contest builds on both paths; satellite scoring provably weights floor differently from `large_wta` on one fixture.

### F4. Six of eight pre-export gates are hardcoded True; late swap asserts all eight (P0, S) | RT 07-24 I-5 carry + IC B2

- **What:** `execution_pipeline.py:2262-2270` defaults salary/entry_grid/lineup/pitcher_audit/weather/odds gates to `True` with a static `caller_asserted` label; no production caller supplies `workflow_gates`; `validate_upload_ready_gates` only fails present-and-falsy or absent gates, so the axis always passes and `workflow_valid` is computed from constants. `tools/late_swap.py:43-48` hardcodes all eight on the path closest to lock, with no weather/postponement validation at all.
- **Why:** "upload-ready" is defined as all three gates passing; if six inputs to that definition are constants, the label carries no information and the artifact lies about what the operator saw. This is the honest-labels rule violated at the front door, and it is why a 23-team 0/9 build could read "certified" on 07-22.
- **Fix:** default the six to `None`; `validate_upload_ready_gates` reports them as `missing_gates` and blocks. Derive cheap gates from work run_slate already does (salary schema validation → salary gate; reserved-grid parse → entry_grid gate; pool report → lineup gate). Add `assume_gates: list[str]` for the T-5 fast path, recorded verbatim in `diagnostics.json` so the artifact states which checks were skipped and why. `caller_asserted` derives from what was actually supplied. late_swap derives gates from the parent run's brief or passes them false. Done when: `run_slate(approve=True)` with no gates returns `workflow_valid=False` naming six missing gates; with `assume_gates=[...]` it certifies and diagnostics records the assumption.

### F5. verify_export.py, the named pre-upload verifier, silently narrows its own scope (P0, S) | RT N-10 part + IC B5 + B22 residue

- **What:** rows shorter than the expected width are skipped (`for row: if len(row) < end: continue`, `verify_export.py:50-61`), so a truncated file prints PASS (IC reproduced: 2 of 16 rows dropped, exit 0). Duplicate Entry IDs overwrite silently (`:60`). Contest Name/ID are never read, so wrong-contest assignment is invisible to it. Three Classic legality rules the engine enforces are absent (min 2 games, max 5 hitters/team, no hitter vs rostered opposing SP), stack sizes are reported without being asserted, `int(p["Salary"])` crashes on a blank, and the locked-teams check is a no-op unless the operator passes `--locked-teams`.
- **Why:** a verifier that quietly narrows scope and reports success is worse than none because it terminates inspection. It is also the tool that must catch F2-class staging accidents, and today it cannot.
- **Fix:** count Entry ID rows independently of parse success and fail on any unparsable row at the detected width; fail on duplicate Entry IDs; read cols 1-2 and diff contest assignment against the parent file and the manifest (F7); port the three legality rules; guard salary parsing; derive locked teams from `Game Info` + `parse_game_info_datetime` instead of a flag; resolve the salary file from the promoted run's `inputs/` snapshot by default (the snapshot exists and covered today's deliverable 55/55 **[executed]**). Done when: the truncated-row fixture and a 6-hitter-stack fixture exit non-zero; a contest-ID swap against the parent is named; running with no `--salary` finds the run snapshot.

### F6. Showdown delivery sits outside the certification spine and its certifier has three holes (P0, M) | RT N-6 + IC B23

- **What:** the majority of delivered volume now ships `review_grade_build` while: (a) the both-teams check is circular, deriving required teams from the pool handed in, so a single-team pool certifies a 6-man one-team lineup (**[executed]**; reachable via `melt_showdown_salary_csv(starters_only=True)`); (b) `lineup.get("salary", 0)` skips the cap check when the key is absent (**[executed]**) and salary is never recomputed from CPT/UTIL role columns, so the 1.5x captain price is trusted, never checked; (c) `write_showdown_entries` writes the delivered path directly with `"w"`, no tmp+`os.replace`, nothing re-reads the written file, and `zip(rows, bank)` with `n_entries = min(args.entries, len(rows))` leaves trailing reserved rows blank (`showdown.py:390-394, 475-476`; `build_slate.py:1097, 1160-1166`).
- **Why:** DK rejects an all-one-team lineup and a blank reserved row is the exact class the Classic gate exists to block; an interrupted write leaves a truncated file at the canonical upload name. Volume moved to Showdown faster than the gates did.
- **Fix:** derive required teams from the matchup (`Game_ID` both sides); refuse a single-team melt; recompute salary from role columns and error on a missing key; write to `DO_NOT_UPLOAD_…`, re-read, re-certify per row against the full pool, assert zero blank reserved rows, then `os.replace` and record in the manifest (F7). Then decide on the record: bring Showdown under the three gates, or state in CLAUDE.md that Showdown ships review-only and what that costs. Done when: both executed repros fail certification; an interrupted write never leaves a truncated file at the delivered name; entries > bank exits non-zero naming the shortfall.

### F7. No upload manifest; same-date builds overwrite each other's delivered files and briefs (P0, S) | RT N-4 + IC I6/B24 part

- **What:** the mirror always writes the same name per contest type, so today's three Showdown slates each recorded `delivered_path …/DKEntries_showdown.csv` and two briefs now cite a file holding another slate's lineups; `outputs/2026-07-25/` holds seven DKEntries files, ten briefs (three duplicate `_1` mints from `preserve_prior_slate` colliding with the tag-copy), and two files with identical contest names and different rosters. `delivered_path` values are absolute paths from a dead sandbox session. Nothing on disk answers "which file do I upload."
- **Why:** the upload is the one manual step, performed at T-5; filesystem ambiguity there is the highest-consequence operator trap left after F1-F6.
- **Fix:** one `outputs/<date>/upload_manifest.json` appended by every delivery path: `{delivered_file, sha256, contest_type, slate_tag, contest_ids, contest_names, entries, run_id, status, superseded_by}`. Delivered filenames always carry the slate tag. Briefs record the sha256. `preserve_prior_slate` skips files whose tag-copy already exists with identical content. Record repo-relative paths. Done when: after a Classic + two Showdown day the manifest lists every file exactly once with contest IDs; preflight (G1) cross-checks it; no `_1` duplicates mint.

### F8. Pool blockers do not block, and the brief can claim signal that reached zero rows (P0, S) | RT N-12

- **What:** the intake blockers landed (`live_data_adapters.py:636-643`) but `build_slate.py` reads `report["blockers"]` once, to print it into the brief; no exit fires on a non-empty list. `signal_applied` derives from input maps, not the engine's per-row `applied_count` (`build_slate.py:735-772` vs `execution_pipeline.py:1645`), so a stale-ID map reports enrichment that touched nothing; the brief still ships the stale sentence "F5 (weather) is not wired yet".
- **Why:** the 07-22 failure (23 teams matched 0/9, certified headline) replays today with prettier logging; and an honest-looking enrichment block that misreports is worse than none.
- **Fix:** `run_classic` exits 3 on pool blockers (HARD tier per G8; a 0/9 team blocks, a stale reference warns); derive `signal_applied` from applied counts with the xwOBA-style zero-application guard; delete the stale sentence; when `salary_cross_check` is false, print the two clocks and the adopted source. Done when: replaying 07-22 inputs exits 3; a stale-ID F1 map yields `signal_applied: false` with `degraded_reason`.

## Cluster B | Evidence integrity (P1; the ownership gate is near and corrupt evidence compounds)

### F9. The field-miner "fail-closed" gate computes and then archives anyway (P1, S) | RT N-5 = IC B21, independent double discovery

- **What:** `main()` (`field_miner.py:1127-1147`) calls `update_registry`, `emit_ledger_block`, `return 0` with no branch on `parse_structural_ok`; the only use of the flag selects a note string that `emit_ledger_block` then omits. **[executed]** a wrong-salary mine: join 0.0%, "PARSE FAILED" in diagnostics, exit 0, registry written, block tagged `coverage full` with a fabricated stack histogram. CLAUDE.md calls this gate hard and fail-closed.
- **Why:** the archive is the training data for the ownership model (the project's single gating dependency) and the scheduled task mines unattended. One bad mine poisons ownership rows, duplication tables, and the registry in one clean-looking run.
- **Fix:** branch before `update_registry`/`emit_ledger_block`: exit 3, write nothing; drop salary-dependent tables to `unavailable` on resolver mismatch; `verification_note` becomes line 1 of every emitted block; add `--force` that records the override verbatim. Done when: the executed repro exits 3 and writes nothing; exit codes pinned for zero-parse, >20% unparsed, type mismatch.

### F10. The field-opponent registry has forked into two diverging copies with double-count accumulation (P1, S) | RT N-15

- **What:** `ledger/field_opponent_registry.json` (534 users, newest 07-19) vs `data/reference/field_opponent_registry.json` (1986 users, newest 07-24); 230 shared users differ and neither is a superset **[executed diff]**. `--registry` is a bare cwd-relative path with no default, and `update_registry` increments with no `(contest_id, entry_id)` dedupe, so re-mining inflates aggregates.
- **Why:** the opponent model is half the leverage layer; two authorities for one fact is this project's named no-op failure class.
- **Fix:** one module-level default path (`data/reference/`); rebuild once from `data/archive/**/contest-standings-*.csv` (all inputs are on disk, deterministic); delete the loser; dedupe accumulation; update the runbook and MANIFEST. Done when: rebuild is idempotent and a re-mine changes nothing.

### F11. The immutable run record omits what the build actually did, and blocked runs read as tampered (P1, S) | IC B7/B8/B9 + RT N-16

- **What:** `build_multi_lineup` returns relaxation counts, DU/anchor validation, `failed_indices`; `run_slate` writes none of it into `diagnostics.json` (in-memory payload only, `execution_pipeline.py:2325-2331, 2365`), and `_blocked_result` reads a `warnings` key nothing sets. The augmentation note asserts "forced coverage across N pairs" even when budget exhaustion no-opped both phases (`optimizer_v3.py:3384-3387`), and the pair-coverage `soft_pass` shrinks its target to the lineups actually produced, so a truncated portfolio always passes while printing the unshrunk target (`:1295-1301`). Blocked-run diagnostics omit `status/blockers/errors` and carry empty hash-binding fields, so `verify_run_bundle` reports a false "missing export hash binding" on correctly blocked runs (**[executed]** on today's `c884a8a6`); an unpromoted-but-certified run keeps a fully formed `final/DKEntries.csv` at the canonical name (`runs/20260721T205552Z_e1d7294d` on disk).
- **Why:** the run record is the project's memory of what was shipped and why; relaxations are exactly the facts post-slate review needs; and a gate whose note moves its own goalposts makes automated checks on `pass` useless.
- **Fix:** write full `bank_diag` (including relaxations and `failed_indices`) into diagnostics with a `warnings` entry per relaxation; build the augmentation note from observed state and reserve a budget slice for augmentation; keep the coverage target fixed and report `pass=False, truncated_portfolio=True`; stamp `status/blockers/errors/pipeline_version` into every diagnostics doc and skip hash-binding when no export is declared; name pre-promotion exports `DKEntries.UNPROMOTED.csv`; add `tools/prune_runs.py`. Done when: a forced-relaxation build's diagnostics carry the counts; verify_run_bundle passes a blocked run stating the block reason.

### F12. The promoted-run pointer crashes across sessions; recorded paths are session-absolute (P1, S) | RT N-9

- **What:** `latest_valid_run.json` stores `run_dir` resolved against the sandbox mount; `get_latest_promoted_run` re-reads it with a bare `.exists()` and no `run_id` fallback. **[executed]** it raises `PermissionError` on the dead-session path rather than returning None; late swap dies at entry in any later session. Briefs and manifests share the disease.
- **Why:** every Cowork session gets a new mount path; the deadline-critical tool must not depend on the birth session's filesystem.
- **Fix:** resolve `Path(runs_root)/run_id` first, fall back to the recorded dir inside try/except OSError; write repo-relative paths. Done when: a pointer written under one mount resolves under another; `tools/late_swap.py --date` works in a fresh session.

## Cluster C | Lineup quality (P1; real, but sequenced after integrity at current stakes)

### F13. LANDED 2026-07-26. Solver timeout is read as infeasibility, triggers strategy relaxation, and one slow solve ends the bank (P1, M) | IC B6 + RT N-8d

- **What:** `time_limit: 30` is hardcoded with scipy `success=False` on limit-hit even with a feasible incumbent in `result.x`, which is discarded (`optimizer_v3.py:672-684`). The caller cannot distinguish timeout from infeasible: on None it climbs the overlap ladder toward 8-of-10, steps DU relaxation, then `failed_indices.append(i); break` exits the outer loop **[verified]**, ending the whole bank; `LAST_SOLVER_STATUS` is a module global overwritten by later solves. The allocator has the same blindness (single string "infeasible or timed out", `contest_allocator.py:1489-1495`, with K² pairwise constraints and no prefilter feeding it).
- **Why:** a compute problem becomes a recorded strategy change (the exact inversion CLAUDE.md forbids), surfaces as "no candidates available" pointing at the pool instead of the clock, and makes builds wall-clock dependent against the determinism claim.
- **Fix:** thread `time_limit` from run_slate; return structured status distinguishing `infeasible`/`time_limit`; accept feasible incumbents tagged `optimality='time_limited'`; never enter relaxation ladders on a timeout; `continue` instead of outer `break`; in the allocator, branch on `result.status`, name the binding constraint on proven infeasibility, and prefilter K to ~6x entries by shape score keeping forced-coverage representatives. Done when: a `time_limit=0.001` test yields a bank with `failed_indices` populated, no relaxations recorded; allocator fixtures distinguish "time limit at gap X" from "proven infeasible: <constraint>".

### F14. The resumable bank cache reuses stale work, discards unknown-game pairs, and blacklists timeouts (P1, M) | IC B11 + RT N-8

- **What:** `_job_key` omits excludes, target, stack bounds, and any projections signature (`bank_cache.py:224-225`), so a late-swap slice serves pre-exclusion candidates and an enriched rerun serves unenriched ones; `str(Game_ID)` makes two NaN games compare equal so the pair is discarded, the opposite of the optimizer's documented guard (`:276, 296-298` vs `optimizer_v3.py:1099-1103`); job keys enter `attempted` before the solve and persist, so a timed-out job is never retried on later slices (`:324-327, 360`); job ordering is rank-sum not ceiling-sum; save is non-atomic and load unguarded, so a kill mid-save poisons the cache file permanently. Phase-1/2 stack exclusion is inverted at both generation sites, aiming repeatedly at the pitchers' opponents' stacks the MILP forbids (`optimizer_v3.py:3253-3258, 3356`; `bank_cache.py:277-278`), and `resolve_sp_pair_coverage_plan` still counts and force-covers same-game pairs because the frame is never passed (`optimizer_v3.py:1170, 1241`).
- **Why:** the sliced path is the big-slate path; these defects waste exactly the budget that is scarce there and can quietly serve candidates built under superseded conditions.
- **Fix:** fold `(excludes, target, stack_min, stack_max, projections_signature)` into the job key and cache header, refuse mismatched loads; mirror the unknown-game guard and report dropped pairs; record attempts after completed solves or keep a retryable failed set; order by combined ceiling with ID tiebreak; tmp+`os.replace` on save, rebuild on corrupt load; exclude opponents not own-teams at both sites; pass the frame at `:1170`. Done when: an excluded-player slice regenerates affected jobs; a two-slice run retries a timeout; a NaN-game fixture keeps the pair; coverage plan counts cross-game only.

### F15. LANDED 2026-07-26. The bank-to-allocator payload drops the fields the portfolio controls need (P1, S) | RT N-7 + IC B12/B13/B14/B15

- **What:** `as_candidates` omits `primary_stack`/`sp_ids`, so the stack-exposure cap adds zero MILP rows and the run dies later at the export gate; direct-path candidates return the literal `'NONE'` which becomes a truthy phantom cap bucket causing spurious infeasibility (`optimizer_v3.py:751-752` **[verified]**, `contest_allocator.py:1429-1431`); `contest_fit_by_shape` is never populated (single `mode="wta"` score), so cash ranks on inverted weights; scoring failures degrade silently (`except: pass`, no counters); `excluded_new_teams` fails open when `player_team_by_id` is absent while the sibling game-cap check fails closed (`contest_allocator.py:1302-1307` vs `:1436-1444`); and `run_slate` forwards `excluded_player_ids` to validation and feasibility but never into the bank build itself (`execution_pipeline.py:2317-2323` **[verified]**), so at T-10 the entire remaining budget is spent building lineups around a player who should have been dropped, discovered only at the gate.
- **Why:** these are the seams through which this week's enrichment work fails to reach big-slate portfolios, and two of them convert into blocked runs at the worst moment.
- **Fix:** emit `primary_stack`/`sp_ids` in the payload matching the direct bank's record; map `'NONE'` to `""` at the allocator boundary; score once per requested shape (shapes are known from the reserved CSV); return scored/failed counts into `solve.bank`; error when `excluded_new_teams` is set without full team-map coverage; pass excludes into `build_diverse_candidate_bank` (set `Excluded=True` pre-build) with a checkpoint blocker at `approve=False`. Done when: a stack-concentrated bank + 0.34 cap yields binding MILP rows; a stackless-candidate fixture allocates without phantom-bucket infeasibility; `run_slate(excluded_player_ids=[...])` produces a bank already free of them.

### F16. LANDED 2026-07-27 (two sub-claims were already closed by F4 and F15; see the Stage 3 block). Late swap erases contest identity and has no downgrade guard (P1, S) | RT N-10 + IC B12 part

- **What:** `tools/late_swap.py` stamps every entry `large_wta`, calls `as_candidates()` with no projections (no scores at all), asserts all gates true (F4), has no incumbent-vs-chosen comparison, and reads the disk feed with no age check; `verify_export` reports only `slots_changed`. The excluded-new-teams contradiction (F15) lives here too. An explicitly empty `mutable_entry_ids` is read as "anything may change" (`late_swap_manager.py:350`).
- **Why:** the only permitted post-delivery refinement runs closest to lock with the least verification; a cash entry's high-floor build silently becomes a ceiling build and the only signal is `chg=6`.
- **Fix:** resolve postures/shapes as the build does (F3); pass projections; score the incumbent and refuse a negative delta without `--accept-downgrade`; age-check the feed; treat empty mutable set as "nothing mutable" (`None` = unrestricted). Done when: cash and WTA entries rank swap candidates differently; a downgrade requires the flag; before/after scores print per entry.

### F17. LANDED 2026-07-27 (the stated consequence of the partial-lineup stamp did not hold; see the Stage 3 block). Intake trust defects: partial lineups stamped confirmed, platoon staleness unobservable, opener token unmapped (P1, S) | IC B16/B17 + RT N-17a

- **What:** every hitter in a posted lineup is stamped `CONFIRMED_STARTER` even when `lineup_status == "partial"` (**[verified]** `live_data_adapters.py:333-346`; only `confirmed_hitter_ids` is gated), and `CONFIRMED_STARTER` sits in `SAFE_UNLOCKED_STATUSES`. The platoon file's staleness is measured against its own `collected_date` (25 days old today, reads 0 stale), `stale_teams` is computed and never read, and `refresh_reference_data.py` does not track the file. DK's `PO` (probable opener) tag maps to the same `declared_probable_sp` role as a true starter; `ALLOWED_PITCHER_ROLES` carries a `viable_bulk_or_alt_sp` value nothing assigns.
- **Why:** partial-as-confirmed defeats the TBD policy check; the stale platoon file is the mechanism that feeds F1; an opener projected as a starter is a material error on a two-pitcher roster.
- **Fix:** stamp `PROJECTED_STARTER` unless `lineup_status == "confirmed"`; compare `collected_date` to the slate date in `build_slate_pool` (warn past 3 days, block past 7 for TBD-dependent builds), forward all four platoon report keys, add the file to the tracked reference set; map `PO` to the bulk role or surface it as a blocker. Done when: a partial-lineup fixture yields projected status; today's file age produces a warning; a `PO` pitcher never enters as a plain probable.

### F18. LANDED 2026-07-27 (the Coors clip-band acceptance line does not hold as written, and the precip-key defect was dead code; see the Stage 3 block). Environment factors: park priced twice, doubleheaders collapsed, wind skipped at the most wind-sensitive park (P1, M) | RT N-13

- **What:** F1 (Vegas total, park-inclusive) multiplies F5's `park_run_factor` again; the odds packet keys `AWAY@HOME` with last-write-wins so a doubleheader's two totals collapse (the lineups feed got leg resolution, odds did not); `build_f5_map` hardcodes delay/postponement to "none" (and the legacy reader misreads the precip key), making the delay/exclusion branches unreachable; wind gates on `roof_type == "outdoor"` while the library's own set includes `temporary` (Sutter Health Park, high sensitivity, never adjusted); `game_venue_overrides.csv` (neutral sites) is never loaded on the production path.
- **Why:** these are the seams in this week's headline feature; the double count systematically overweights extreme parks, which is where stack decisions concentrate.
- **Fix:** decide park ownership on the record (recommended: F1 owns run environment, de-park the implied total; F5 keeps wind/roof/delay); port `_select_slate_legs` to the odds parser; map the precip key and feed real delay risk; use `OUTDOOR_ROOF_TYPES`; load overrides keyed `(date, away, home)` honoring `manual_required`. Done when: a Coors fixture's combined uplift stays inside the F1 clip band; two-leg fixtures carry two totals; ATH-home wind applies; a neutral-site row changes the venue.

### F19. LANDED 2026-07-26 (mechanism removed; predicted divergence did not reproduce, see the Stage 3 block). Determinism: unpinned hash seed feeds MILP row order (P1, S) | IC B18, modified

- **What:** lock merges via `list(set(...))` (confirmed at `optimizer_v3.py:3275`; re-locate IC's other two anchors during implementation) feed constraint rows in set order; `PYTHONHASHSEED` is pinned nowhere (**[verified]**); with the uniform 1.42 ceiling multiplier exact ties are routine, so identical inputs can certify different files across processes.
- **Why:** it quietly undermines the golden replay and makes "same inputs, same file" unclaimable.
- **Fix:** `sorted(set(...), key=str)` at every lock-merge site; sort `locked_ids` before constraint emission; pin `PYTHONHASHSEED=0` in `tools/audit.py` and the skill's entry commands. Done when: two fresh-process runs on one fixture produce byte-identical exports.

### F20. Doctrine and dead machinery: shipped caps looser than the strategy authority; a 156-line certification stage with zero callers; DU enforced nowhere (P1, decision) | IC B19/B20 + RT I-12 carry

- **What:** `STRATEGY_DEFAULTS` diverges from MLB_Classic §8 on the two most-used postures (pitcher cap 0.70/0.55 vs §8's 0.43; primary stack 0.60/0.50 vs 0.35; shared players 7/6 vs 5), with the honest caveat that §8 reads as qualified defaults; the overlap preset truncates 4 where §8 says 5. `select_final_portfolio_from_candidate_bank` (156 lines) has zero callers, and DU enforcement is disabled on both sides of the handoff it was deferred across, so portfolio decorrelation rests entirely on the allocator's player-overlap control.
- **Why:** duplication is the main enemy in a satellite-heavy portfolio, so cap looseness is not cosmetic; and every future tuning session reads dead knobs as live.
- **Fix:** pick a winner per control and edit the loser, recorded in the ledger (recommended: adopt §8's tighter caps for satellite postures, keep looser GPP caps only where feasibility floors demand); delete the uncalled stage and either enforce DU via `scope='bank'` or record that allocator overlap is the accepted control; delete `_default_candidate_bank_target`, the chatgpt relic, and the legacy allocator per the accepted 07-24 items. Done when: code and §8 agree or the divergence is a dated ledger decision; grep finds no uncalled certification stage.

### F21. LANDED 2026-07-26. A blank Excluded cell silently removes players from the legal pool (P1, S) | IC B10

- **What:** `df[df['Excluded'] == False]` at four sites (**[verified]** `optimizer_v3.py:477, 978, 1008, 3117`); NaN/None/"False" all fail the comparison and the row drops; the column is only defaulted when entirely absent, so an override frame or CSV round-trip with one blank cell loses that player and shrinks the SP-cap denominator.
- **Why:** this is the forbidden pool-reduction failure arriving from a data condition instead of a compute limit, invisible in the certified output.
- **Fix:** coerce once (`fillna(False)` + explicit string map) at a single chokepoint; count coerced/dropped rows into the pool report. Done when: a frame with NaN/"False"/True mix keeps exactly the True-excluded rows out and reports counts.

## Cluster D | P2 batch (waste and traceability; one cleanup session)

### F22. The test suite measures the wrong 90% (P2, M) | IC B25 + RT N-17f/g/h

- **What:** ~26-30 of 189 tests invoke an engine entry point; blocking scipy leaves 172/189 green (IC executed), so the suite mostly measures parsing while no lineup can be built. Untested behaviors include: blank reserved rows blocking Classic certification, over-cap rejection, the overlap cap being honored by a produced bank, posture/shape resolution, export geometry, `verify_export`, the late_swap CLI, and `build_slate.py`'s own F1/F5 map builders. The golden replay runs `LOOSE_CONTROLS` + `emergency_proxy`, so every factor shipped this week sits outside the only end-to-end gate, and its single `assertEqual` cannot distinguish a reshuffle from a drift. The audit runs `test_core` only, prints a hand-kept "13 modules" against 20 on disk, and its count pin is bumped in the same commit that makes it necessary.
- **Why:** the suite is the thing that lets an agent change this codebase quickly without re-deriving trust; today it is green in states where the product does not work.
- **Fix, priority order:** five solver-independent behavior tests from hand-built CSV fixtures (blank-row block, over-cap, overlap honored, posture resolution, geometry); a second golden replay with production controls and real enrichment, aggregates and assignment asserted separately; add `test_showdown` and `test_golden_replay` to the audit; derive the module list from the filesystem; split "suite failed" from "count mismatch" in the audit output since CLAUDE.md tells the operator to proceed on one and not the other. Done when: blocking scipy fails the suite loudly; the five behaviors have red-green tests; the audit gates all three files.

### F23. Hygiene batch (P2, S each)

Commit the untracked load-bearing modules (`showdown_theses.py`, `build_showdown_theses.py`; 14 of 27 Showdown tests fail on a fresh clone, and the unconditional import at `build_slate.py:1087` breaks the whole Showdown path); have `showdown_theses` read names/teams/hands/IDs from the salary CSV with a `--game` argument instead of hand-typed rosters (IC reproduced a delivered theses file with zero ID overlap against every staged salary file); treat `outputs/` as write-only for deliverables and delete the scratch scripts, logs, and `_1` briefs; delete `_scratch_20260722/`, the stray root `slate_bundle.json`, the stray `data/slates/_feed*.json`, and stale bank-cache renames; fix the RotoWire fallback (cap 9 slots, drop short teams, 0-parse is unavailable not success); apply the postponement guard to declared pitchers; fix the ladder's missing both-relaxed rung and relaxation undercount, and treat captain cap `0.0` as a real cap (`is None` test); scrub the URL-encoded key form and never interpolate URLs into errors; validate manual reference targets in `--check`; fix the tail scanner's Savant name-column read and the xwOBA `ID`-only fallback; reconcile exit-code tables across tools; fix the ledger header ("untracked", stale date) and the eval harness's stale version expectation; move MLB_Classic's ~310 lines of version history to `docs/legacy/`; remove the six references to the nonexistent `parked/` directory.

---

# Section 2: Ideas and features

### G1. One executable pre-upload gate: `tools/preflight_upload.py` (build first; the net under everything) | RT E-A + IC I1, merged

- **What:** a single fail-closed check run between "build finished" and "Ben uploads." Core invocation reads two files and nothing else: `--entries <delivered.csv> --salary <salary.csv>` (salary resolved from the promoted run's snapshot by default). No engine import, no solver, no network; target under two seconds. Five hard checks (exit 2): every rostered player has clean `Status` (names any IL/OUT/NA); header geometry matches the detected contest type and every reserved row is fully filled or fully blank at correct width; every rostered ID exists in the salary CSV and embedded-pool overlap exceeds 0.95 when a pool parses; per-lineup DK legality (cap, slots, 2 games, 5 hitters/team, no hitter vs rostered opposing SP, Showdown: exactly one CPT, both teams, recomputed 1.5x salary); row accounting (Entry ID count equals parsed count, all unique). Optional flags widen it without making it blockable: `--manifest` cross-checks contest IDs and sha256 (F7), `--feed` flags rostered players absent from their team's posted lineup/probables and `Starting`-column disagreements. Advisory prints (exit 0): exposure, overlap histogram, duplicate-lineup groups, ownership concentration when a prior exists. `--force` prints failures and exits 0 for when the clock beats the fix.
- **Why:** this is the requested QA process shaped so it can never prevent shipping: every hard check is a fact about the file, decidable from disk in seconds, and each one maps to a real defect found this week (F1, F2, F5, F6, F7). It also protects against the class of ad-hoc builds that bypass the pipeline, because it inspects the artifact, not the process that made it.
- **Fix/plan:** build it before the root fixes land; it is the net while F1-F8 are implemented. The generate-lineups skill runs it automatically at the end of every build and prints the one-line verdict; CLAUDE.md's pre-upload sentence points at it and nothing else. Done when: it passes today's real Classic file via the run snapshot, and catches, on fixtures: a Showdown file declared Classic, an inserted IL player, a swapped contest ID, a 6-hitter stack, a blank row, a truncated file.

### G2. A skeptic pass that reviews tonight's artifact, not the codebase | IC I2 + RT E-B, merged

- **What:** a `review-slate` step, chained after the build when more than ~20 minutes remain to lock: one fresh-context subagent reads only the delivered CSV, the manifest, the brief, and the preflight output, answers five questions, and stops. Which single player's scratch damages more than a third of entries; are any two lineups in one contest near-duplicates; does every entry sit in a contest matching its roster geometry; what did the engine relax (from diagnostics once F11 lands); the single most likely reason this portfolio misses, in one sentence. No auto-edits; challenges print on the checkpoint. Inside T-20 it is skipped by rule.
- **Why:** this is the adversarial view scoped to where it pays: the file being uploaded tonight. Three codebase reviews in seven days re-derived each other; that loop is a treadmill, and the verification-loop literature's answer is to encode checks as executable artifacts (G1) and keep the prose pass short, scoped, and fresh-eyed.
- **Fix/plan:** implement as a skill section or a small standing prompt; measure it stays under one minute on a clean slate. Done when: a planted wrong-contest assignment and a planted scratched pitcher are both named on a fixture slate; clean slates cost one PASS line.

### G3. Wire the ownership and duplication layer that already exists | IC I3 + RT E-C

- **What:** `ownership_prior.py` (archetype-conditioned prior with a grading loop) and `field_miner.score_duplication_risk` are written and unwired: nothing loads prior output into `Projected_Ownership_Pct`, which the optimizer already prefers over the flat tier defaults, and the dup screen is selftest-only. Also nearly free: `run_meta_lineup` failure is swallowed and zeroes the chalk-avoidance term silently, and its fallback chain degenerates to "similarity to the ceiling-max lineup"; record `meta_lineup_status` and surface it.
- **Why:** knowing what the field does is the one commercial-tool capability that materially changes satellite results, where clearing the cut line undduplicated is the whole game. The scoring machinery activates with zero engine changes the moment a graded prior beats flat-12.
- **Fix/plan:** fit per archetype from the archive (needs F9/F10 first so the archive is trustworthy), write `data/reference/ownership_prior_<archetype>.json`, load in `_assemble_projection_frame`, grade every slate with `grade_against_actuals` into the ledger, and persist each slate's prediction file now so grading is possible retroactively. Wire the dup screen into the Tier A checkpoint. Labels: priors, never probabilities. Done when: per-slate graded MAE/Spearman appear in the ledger with a stated go/no-go vs flat-12; checkpoints show expected-duplicates for satellite portfolios.

### G4. Record Ben's own results; the rank column is already parsed and discarded | RT E-G (absent from IC, and IC's own stakes logic makes it mandatory)

- **What:** `parse_standings_export` reads `rank` and the entries projection drops it; `grade_against_actuals` has never run; no archived contest carries the fee/paid-places/cash-line trio; the project cannot answer "are we winning."
- **Why:** G7's scale-or-freeze decision is the highest-value open item and it is currently undecidable for lack of a net-to-date number. This is bookkeeping, fully inside truthful labels (observed outcomes), and evidence decays: DK exports age out, proven by five unrecoverable contests.
- **Fix/plan:** field_miner grows `--my-entry-ids` (default harvested from the promoted run's `assignments.csv` and the upload manifest); per contest emit fees, winnings, finish percentile, and own-lineup duplication counts; one cumulative table at the top of the ledger archive; capture the payout trio at mining time. Done when: every newly archived contest carries the self-vs-field block and one line answers net-to-date.

### G5. Shrink the governance corpus with progressive disclosure | IC I5 + RT E-D

- **What:** ~2,500 lines of instruction prose for a 10-second build. CLAUDE.md (166 lines) is close to right. The waste is: MLB_Classic.md mixing doctrine with a 310-line changelog and six references to a `parked/` directory that does not exist; truthful-labels boilerplate repeated across dozens of module docstrings; contradictions a reader must reconcile (24 vs 150 candidate cap, v1.9 vs v1.11 header, ledger "untracked", 13 vs 20 modules); and per-slate procedure specified in two places.
- **Why:** this project's operating cost is agent-session tokens; every contradiction costs reasoning on every request, and the current guidance is explicit that models do better with light context plus on-demand references.
- **Fix/plan:** split MLB_Classic into a short numeric contract file plus an on-demand strategy reference; move the changelog to `docs/legacy/`; compress the labels rule to one CLAUDE.md sentence plus a docstring convention; fix the contradictions; adopt the rule that any MUST in CLAUDE.md/SKILL.md either cites the enforcing code path or is rewritten as guidance (F9 proved why); generate a 15-line `ENGINE_STATE.md` from `tools/audit.py --write-state` (audit line, archive count vs gate, last build's enrichment counts, untracked-file check, registry freshness) as the session-start read. Done when: session start reads CLAUDE.md + ENGINE_STATE + Quick Card only; the named contradictions are gone.

### G6. Loops on Cowork's actual primitives | RT E-E (absent from IC)

- **What:** three file-state-driven loops, none touching DraftKings: a morning scheduled task (reference freshness check, platoon staleness report, stage the slate if salaries are present, solver probe, checkpoint); a nightly standings task (sweep the inbox, mine and archive with F9 fixed, print the exact export URLs still owed with size checks); an in-session bank-deepening loop (the skill re-invokes the slice command until candidates reach 2x entries, the job list exhausts, or T-20, instead of returning exit 10 to Ben).
- **Why:** the repo already invented the right pattern (bank cache + exit-10 resume is a goal-loop with persistent state across ephemeral sessions); formalizing it converts operator attention into schedule. The loop guide's primitives map one-to-one: schedule, goal, stop condition.
- **Fix/plan:** two scheduled tasks plus one skill change; stop conditions written in the skill, not improvised. Done when: Ben wakes to a staged slate or a one-line "waiting on salaries"; thin slates reach the candidate floor without manual re-invokes.

### G7. Decide the stakes on the record | IC I9, elevated

- **What:** the engine is built to a standard that suits four-figure exposure and runs at $9.37. Two coherent paths: scale stakes to match the engineering, in which case Cluster A plus G1 are mandatory before the next upload and G3 becomes the highest-value feature; or freeze the engine as-is, in which case do Cluster A plus G1, skip everything in Cluster C that does not touch the upload, and stop building.
- **Why:** this gap explains most of what both reviews found: an over-built spine, a missing injury check, three review cycles. Either path is defensible; continuing to build features against unfixed upload-integrity bugs is not.
- **Fix/plan:** a dated decision in the ledger after G4 produces the first net-to-date number (target: within 10 graded slates). This is Ben's call alone; the reviews' job is to make it explicit.

### G8. The anti-paralysis doctrine, written once | RT E-F

- **What:** a 15-line CLAUDE.md block classifying every gate. HARD (illegal roster, wrong-contest identity, blank reserved row, IL starter, locked-game player, uncertified export) blocks at any T, no override, because DK or the bankroll enforces it anyway. SOFT (enrichment degraded, stale reference, cross-check drift, thin coverage, review challenges) prints, ships, and logs; at T-10 soft warnings collapse to one count. Meta-rules: every HARD gate decidable from disk in under a second, no network; every HARD failure names the one command that fixes it; anything failing twice in a week earns a fixture test.
- **Why:** the user's constraint is that process must never prevent lineups. The repo has the right instincts scattered (T-schedule, certified-beats-perfect, degrade-don't-raise); classifying them means every new gate, including everything in this document, inherits a defined failure mode instead of an improvised one.
- **Fix/plan:** write the block; tag each existing gate with its tier as F-items land. Done when: every gate greps to a tier and the T-5 path provably runs zero network and zero LLM calls.

---

# Implementation order

Each stage is shippable alone; nothing in any stage blocks a build while incomplete.

**Stage 0, the net (an hour):** G1 core (two-CSV mode). It catches most of Cluster A's consequences at the file level before the root fixes exist.

**Stage 1, before the next upload (about a day):** F1 status filter. F2 geometry + embedded pool + staging guards. F3a archetype resolution and unknown-blocks (F3b/c can trail by a day). F4 gates with `assume_gates`. F5 verify_export hardening. F6 showdown certifier and atomic write. F7 manifest. F8 blockers block. Commit the untracked modules (from F23) so none of this lands on files git can lose.

**Stage 2, evidence (half a day):** F9 miner fail-closed. F10 registry merge. F11 diagnostics honesty. F12 pointer portability. G4 own results, and persist per-slate ownership predictions from the next slate forward.

**Stage 3, quality (a day):** ~~F13 timeout semantics~~ (landed). ~~F14 cache correctness~~ (landed). ~~F15 payload seams~~ (landed). ~~F16 late-swap identity~~ (landed). ~~F17 intake trust~~ (landed). ~~F18 factor ownership decision + doubleheader odds~~ (landed). ~~F19 determinism pin~~ (landed). F20 doctrine decision (deferred); ~~F21 Excluded coercion~~ (landed). Stage 3 is complete apart from F20, which is deferred by decision.

**Stage 4, process and leverage (as time allows):** G2 skeptic pass. G3 ownership/dup wiring (after Stage 2, once the archive is trustworthy and at the 8-slate gate). G5 corpus split + ENGINE_STATE. G6 scheduled loops. G8 tier doctrine. F22 tests. F23 remainder. G7 stakes decision, dated, once G4 yields a number.

# Do not build (explicit, so effort does not leak here)

- **Full Monte Carlo contest simulation.** Weeks of work, needs a calibrated correlation model to beat the ceiling proxies, and at current stakes the expected return does not cover the build. Revisit only if G7 scales stakes by orders of magnitude; the cheap fallback then is a correlated bootstrap over archived box scores for stack-ceiling ranking.
- **A DU-deletion debate.** Decide once in F20 and execute; do not spend a session on it.
- **Vectorizing the scoring hot path.** Builds take 10 seconds. There is no problem.
- **Daily or per-slate codebase reviews.** Replaced by G1 + G2 + this backlog. This document is the last of its kind until the backlog is substantially landed.
- **New frameworks, orchestrators, or LLM calls in the certified path.** The spine is scipy-only and stays that way.

# Sources

- [The new rules of context engineering for Claude 5 generation models](https://claude.com/blog/the-new-rules-of-context-engineering-for-claude-5-generation-models) (Anthropic, 2026-07-24)
- [Building verification loops in Claude Code with skills](https://claude.com/blog/building-verification-loops-in-claude-code-with-skills) (Anthropic, 2026-07-22)
- [Getting started with loops (@ClaudeDevs)](https://x.com/ClaudeDevs/article/2074208949205881033); explainers: [explainx loops guide](https://explainx.ai/blog/claude-code-loops-official-guide-turn-goal-schedule-2026)
- Provider capabilities: [Stokastic](https://www.stokastic.com/), [V12 DFS comparison](https://www.v12dfs.com/best-dfs-optimizer), [DFS Only 2026 comparison](https://onlydfs.com/blog/best-mlb-dfs-optimizer-tools-2026.html), [SaberSim reviews (WinDaily](https://windailysports.com/reviews/sabersim/), [SportBot)](https://www.sportbotai.com/blog/tools/sabersim-review)
- DraftKings: [late swap](https://help.draftkings.com/hc/en-us/articles/4405224380051-Late-Swap-Overview-US), [MLB rules](https://www.draftkings.com/help/rules/mlb)
