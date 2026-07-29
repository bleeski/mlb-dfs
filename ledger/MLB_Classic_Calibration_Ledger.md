# MLB Classic Calibration Ledger

Companion, untracked. Last updated: 2026-07-08.

Status: memory layer **LIVE**; calibration content **INERT**.

This file is intentionally not in `ACTIVE_FILES` and is not checksummed, on the
same footing as `MLB_Classic_Backlog.md` and `MLB_Classic_Integration_Contract.md`.
It is edited every slate, so checksumming it would break the audit gate on every
update by design. It will surface as a benign "non-active files in directory"
audit warning; the `--terse` session-start macro hides that warning.

---

## 0. Quick Card (session-start read; the full ledger is post-slate reading)

1. Macro: from the repo root, `python tools/audit.py --run-tests --terse` -> `PASS  v2.26.0  23 modules  437 tests`. If the audit fails on pins or inventory only while `python -m unittest tests.test_core` passes in full, proceed and flag; never repair infrastructure mid-slate. **Sandbox caveat (measured 2026-07-29):** with scipy present the four suites cost about 55s wall (test_core 30s, golden 20s), which exceeds a 45s Cowork tool call. Run suite-by-suite instead (`python -m unittest tests.test_core`, then `tests.test_showdown tests.test_upload_integrity`, then `tests.test_golden_replay`, then `python tools/audit.py --terse` for pins and inventory); the counts sum to 437 (330 + 98 + 9) and nothing about what the audit checks changes. Install deps first if `--terse` reports missing scipy: `python tools/env_probe.py` prints the exact pinned command. (Corrected 2026-07-24: this line still carried the pre-restructure claude.ai macro, naming a `/mnt/project` mount, a `/home/claude/work` copy, and a `project_audit.py` that do not exist in the v3.0.0-pre layout, plus stale counts. It is the mandated session-start read, so every session began by running a command that could not work.)
2. Pool: `build_slate_pool(salary_csv, lineups_feed, platoon_json, declared_pitchers)` is THE intake. Confirmed nine plus platoon nine plus probable/declared arms only; every other salary row is immaterial. Splat `pool["run_slate_kwargs"]` into `run_slate`.
3. Clock: T-5 delivery rule. `checkpoint["slate_clock"]` shows first lock, deadline, minutes remaining. T-20 skip optionals, T-10 approve on defaults, T-5 present the best certified file; refinements via `run_late_swap`.
4. Postures: pass explicit `contest_postures` by contest ID; never trust `infer_contest_archetype` on family names (Pocket Cup, Knuckleball, Relay Throw). This applies to late swap too as of 2026-07-27 (F16): `tools/late_swap.py --postures <id>=<posture>` resolves identity the way the build does and blocks on a contest that matches no archetype, where it used to stamp every entry `large_wta`.
4a. Platoon reference (F17, 2026-07-27): `data/reference/fangraphs_platoon_lineups.json` is now aged against the SLATE, not against its own `collected_date`. Past 7 days it raises a pool blocker when a TBD team is being filled from it; `build_slate.py` tiers that blocker SOFT, so it prints and the build ships. It was 27 days old on 2026-07-27. Refresh it before leaning on projected orders.
5. Feasibility: repetition, shared-players, and pct exposure caps auto-floor to slate minimums; explicit overrides win; applied floors surface under `controls_feasibility`. Review `checkpoint["feasibility"]` instead of rediscovering by hand.
6. Bank: the auto path is `build_diverse_candidate_bank`; hand-build `candidates_override` only when the checkpoint shows a coverage gap.
7. Enrichments, one call each through `run_slate`: `savant_batting_csv` + `savant_pitching_csv` (xwOBA plus xISO ceilings), `fangraphs_pitching_csv` (K-rate ceilings), `f4_by_player_id` from `compute_f4_factors(pool["team_by_player_id"], pool["opposing_probables"], pitching_table, pool["batter_hands"])`; the platoon map rides in `run_slate_kwargs`.
8. Report: gates, Run ID, provenance, promoted file, Blockers line, applied floors, enrichment counts. Opt-in only: tail scanner, mispricing screen, contested-slot audit, fill-depth narration, three-assumption kill list.
9. Ship rule: certified beats perfect. Deterministic review proxies only; never ROI, win-rate, or probability claims. Upload-ready only after all three gates.
10. Post-slate: attach the DK standings export, archive per 3.7, and only then does the full ledger read apply.
11. Factor ownership (F18, decided 2026-07-27, full text in 3.10): F5 owns the ballpark; F1's implied total is DIVIDED by the game's park run factor before the slate-mean ratio, so Base x F1 x F5 prices the park once. The de-park does not cap the product; F1's clip applies to F1 alone.

---

## 0.1 What this file is and how to use it

This is the project's persistent memory. At session start read the Quick Card
(section 0); the full ledger read is post-slate work. Either way the field model
and the projection model start from the standing corrections recorded here
rather than naive. It exists to defend against
the two ways a DFS operation quietly degrades: overfitting to the last result, and
losing the rules already paid for in earlier losses. It is sport-agnostic in
skeleton; the calibrated content below is MLB Classic specific.

The file has two halves, kept structurally separate on purpose so that editing a
soft rule never deletes a hard one:

1. **Invariants (Section 3).** Operational protocol that never gets dropped. Not
   evidence-gated. These are the parsing traps, the hygiene rules, the legality and
   certification gate, the thin-slate feasibility facts, and the bank and objective
   rules that have already cost something to learn.
2. **Calibration content (Section 4).** Field behavior, outcome magnitudes,
   slot-selection logic, and archetype memory. Evidence-gated and currently inert.

### Truthful labels (extends the project discipline)

Everything in the calibration half, and every number in the archive, is a
deterministic review proxy or an observed outcome. None of it is ROI,
profitability, win rate, cash rate, or Perfect%. An actual `%Drafted` or an actual
FPTS in an archived result is an observed outcome, not a graded prediction, until a
model that predicted it exists. The rule statuses and sample counts are bookkeeping,
not probabilities.

### The calibration gate

The Section 4 content moves no projection and changes no factor. It turns on only
when both conditions hold:

- a projected-ownership model (Section 5) emits a per-slate prediction that can be
  graded against the archived actuals, and
- enough archetype-conditioned slates exist for a pattern to repeat rather than
  appear once.

Until then this is institutional memory, not calibration. Say so plainly.

---

## 1. Regeneration discipline (how to maintain this file)

- **Edit in place.** When a new finding contradicts an existing line, reconcile the
  line. Do not append a second rule that competes with the first.
- **Never drop an invariant section.** Section 3 is append-and-refine only.
- **Diff the structure before saving.** If a section disappears, the commit note
  must say why.
- **Close the loop every slate.** Read, build, observe the result, run the
  post-mortem, reconcile the findings into this file, then reinstate the file for
  next time. The reconcile-and-reinstate step is the one that makes the thing learn.
  Skip it and the memory is write-only.
- **Single-file shape.** The living sections (0 through 5) sit above the archive
  delimiter. The archive below it is append-only, newest first. When the archive
  outgrows comfortable single-file editing, split the archive into a companion and
  leave the living sections here; that is a future call, not needed yet.

---

## 2. Rule-grading model

Every calibration line carries a status and a sample count. The count is the number
of **archetype-conditioned** slates that support it, not the number of contests.

| Status | Meaning | What moves it |
| --- | --- | --- |
| **firm** | repeats across conditioned slates; safe to act on once the gate opens | a confirmed pattern, never a single result |
| **provisional** | seen more than once, not yet confirmed | accumulating conditioned slates |
| **open** | a hypothesis with zero or one supporting slate | logged; not acted on |
| **record-only** | structurally uncalibratable at this volume | never promoted to a rule |

Two hard rules behind the table:

- **A single result never moves a magnitude prior.** One slate is one outcome draw.
  A 28-point game is not evidence a projection was wrong.
- **Condition every count on contest archetype and field size.** A 2-game satellite
  field and a 10-game GPP field are different populations. Pooling them manufactures
  false significance. The inaugural archive entry is the proof: the same player on
  the same slate drew ownership that swung 20 to 31 points across three contests
  (Konnor Griffin 38.3 to 69.0, Aaron Nola spread 26.5, Bryce Harper 17.6 to 37.9).
  If you log ownership without the archetype and field-size tag, the sample is
  already corrupt.

### Signal versus noise (what becomes calibratable, and in what order)

Data arrives at two rates.

- **Cross-sectional data accumulates fast.** Every player on a slate gives a
  (player, salary, value, actual `%Drafted`, actual FPTS) row. On these MLB Classic
  pools that is tens of rows per slate, not hundreds, so the accumulation is real
  but slower than a full main-slate GPP would give. This is what makes ownership
  modeling reachable.
- **Full-field construction data accumulates fastest of all (added 2026-07-04).**
  The standings export's `Lineup` column carries every entrant's complete lineup,
  so each archived contest yields N construction observations (stack shapes,
  salary usage, SP pairing, exact-lineup duplication), not one. A 222-entry
  contest is 222 rows of observed field behavior, and field behavior is stable in
  a way game outcomes are not. These are observed distributions, not graded
  predictions; no model is required to read them.
- **One-per-contest data accumulates at a crawl.** There is one winning lineup per
  contest. "Which shape won in which environment" yields a single point each time
  and will not converge at current volume.

Order of calibratability, therefore:

1. **Field construction and duplication frequencies** (Section 4.6): directly
   observable distributions, no prediction to grade. Usable as structural priors
   for the Tier A duplication screen only after patterns repeat across
   archetype-conditioned slates; a single contest never promotes one.
2. **Ownership-model error** (predicted vs actual `%Drafted`, cross-sectional,
   conditioned on archetype). First graded error to converge and the largest
   controllable edge.
3. **Projection-magnitude error** (Base x F1..F5 vs actual FPTS). Second and slower;
   one outcome draw per player per slate.
4. **Archetype / winning-lineup shape.** Record-only. Will not converge at current
   volume.

---

## 3. INVARIANTS (operational protocol, never dropped)

### 3.1 Data parsing and hygiene

- **Salary CSV is authoritative** for Player_ID, salary, team, game, opponent, and
  eligibility. Never correct names, teams, salaries, or eligibility against
  real-world rosters. Players with no salary row are unrosterable.
- **DKEntries export: parse only with `dk_entries_manager.parse_dk_entry_rows`**
  (positional, never `DictReader`). The embedded salary block breaks standard CSV
  parsing.
- **Standings export schema:** `Rank, EntryId, EntryName, TimeRemaining, Points,
  Lineup, , Player, Roster Position, %Drafted, FPTS`. The right-hand block
  (Player / Roster Position / %Drafted / FPTS) is the actual ownership and actual
  scoring table. Read with `encoding="utf-8-sig"` because exports may carry a BOM.
  `EntryName` of the form `name (4/4)` means entries used over max per user, so it
  flags a multi-entry contest. `Points` of 0.0 is a real zeroed, withdrawn, or late
  entry, not a parse error.
- **The `Lineup` column is the full-field construction record (added 2026-07-04).**
  Every entrant's complete lineup is in the export, so the raw file is the dataset,
  not just the winner rows. Retain it untrimmed and mine it with `field_miner.py`
  (untracked companion) at archive time. Lineup strings parse positionally by the
  slot tokens P/C/1B/2B/3B/SS/OF, never by splitting on names; a complete MLB
  Classic lineup carries the slot multiset 2P/1C/1B/2B/3B/SS/3OF.
- **The standings player table is grained per (player, roster position) (added
  2026-07-04).** A multi-position player appears once per drafted slot and the
  rows sum to his total field share. Any per-player read must aggregate across
  the split, or chalk is understated exactly where positional flexibility
  concentrates; `field_miner.mine_contest` aggregates to player grain and
  preserves the raw split in `player_table`. The ownership recompute self-check
  (3.7) caught this in production on A-001's 222-entry contest.
- **The standings export omits entry fee, payout structure, and the cash line.**
  Winning score is derivable from max `Points`; the cash line is not, because paid
  places are not in the file. Capture entry fee and payout structure from the
  contest page at archive time or the decomposition is incomplete.
- **Savant CSVs** (`expected_stats_batting.csv`, `expected_stats_pitching.csv`):
  read with `encoding="utf-8-sig"`, single combined `"Last, First"` header.
  MLBAM `player_id` must be crosswalked to DK Player_ID by name via the salary file
  inside `xwoba_base_correction.build_dk_keyed_corrections`, which keeps the
  higher-PA row on a name collision and reports the match rate; unmatched or
  sub-floor players fall back to a neutral 1.0 multiplier. As of v2.23.0 the
  front door wires this join itself and surfaces the match report under
  `projection_enrichment["xwoba"]`; a zero-match on a pool of at least ten
  raises as a wiring error, and a sub-50% match rate warns.
- **Lock state** is derived from the `(LOCKED)` suffix in the DKEntries export, not
  from the salary file.
- **F5** is computed from the audited park and weather tables via
  `slate_intake_manager.compute_f5_factor`. A manual F5 is an override and must be
  surfaced with a reason.
- **Park factor provenance must be recorded on every refresh (added 2026-07-07,
  v2.24.1).** `f5_park_factors.csv` raw factors are sourced from Baseball Savant
  Statcast park factors (paired batter/pitcher method, handedness-controlled):
  `Run_Factor_Raw` = R / 100, `HR_Factor_Raw` = HR / 100, applied =
  clip(raw, 0.94, 1.08), venue keys canonical per `team_to_venue.csv` (Savant's
  "UNIQLO Field at Dodger Stadium" maps to "Dodger Stadium"). The 2026-05-05
  predecessor carried no recorded source and diverged from the Statcast factors
  at 28 of 30 venues' applied values, several in the opposite direction (Angel
  Stadium run 1.00 vs 0.94, Chase 1.08 vs 0.98, Wrigley 0.94 vs 1.04). A factor
  file without recorded source, window, and pull date cannot be re-verified;
  refuse the refresh unless all three are recorded.

### 3.2 Legality and certification gate

- Never assert `workflow_valid`, `selection_certified`, or `allocation_certified`
  unless all three pass. The exported DKEntries file is the only certification
  source: re-read the candidate, copy to final, re-read final, recompute
  diagnostics, hash-bind, then promote or block.
- Blank reserved entries block. Export writing refuses pre-existing outputs and
  never deletes on failure.
- "Upload-ready" is a post-certification term only. Reserve it for builds where all
  three gates pass.
- Run status ends as promoted, blocked, or diagnostic, never building. Every run
  gets an immutable run directory with hashed inputs. Late-swap parents load only
  through the re-verified bundle path; tampered parents block. Late swap requires
  `authorized_entry_ids`; missing lock status fails closed.

### 3.3 Thin-slate feasibility

- Superseded 2026-07-08 (v2.26.0): on thin slates the pct exposure caps used to hit
  their floor counts via `_cap_count` (`floor(pct * entry_count)`) and required manual
  relaxation. The engine now auto-floors them (see below). Document any applied floor
  in the build report.
- When HiGHS returns Status 8, isolate the binding constraint by single-constraint
  relaxation in this order: player cap, pitcher cap, SP pair repetition, stack caps,
  shared players.
- Compute `C(n_eligible_SPs, 2)` and verify it covers the required SP-pair diversity
  **before** building, not after.
- As of v2.25.0 the engine automates the two facts above. `run_slate` floors
  `max_sp_pair_repetition` to `ceil(entries / viable_sp_pairs)` and `max_shared_players`
  to `min(9, max_stack + 2*(pair repeats) + 1)` before overrides (an explicit override
  still wins), and the `approve=False` checkpoint carries `checkpoint["feasibility"]`
  naming the binding constraint and required cap value. The auto-bank builds through
  `build_diverse_candidate_bank`, which forces coverage of every viable SP pair with
  legal, deduped lineups, so the standing thin-slate failure mode (bank collapses onto
  a couple of SP pairs, no cap can repair it) no longer requires a hand-built
  `candidates_override`. Verify the surfaced feasibility block and applied floors in the
  build report; they replace manual rediscovery, not the review itself.
- As of v2.26.0 the percentage exposure caps join the floors: `max_pitcher_exposure_pct`
  floors to the demand of `ceil(2*entries / viable_SPs)` appearances for some arm,
  `max_primary_stack_exposure_pct` to `ceil(entries / stackable_teams)`, and
  `max_player_exposure_pct` to the max of both, with matching capacity checks in the
  feasibility report naming the exact required cap value. Floors apply only to keys
  the posture merge produced (a floor may relax, never add a cap) and an explicit
  override still wins. The manual pct-cap relaxation this section used to require
  is retired.
- **Cap feasibility is a property of the BANK, not the pool or the entry grid**
  (correction, 2026-07-29, merged from the DEV fragment). Backlog R28 carried
  "today's engine cannot certify the archived 18-entry, three-contest grid under
  the postures production would assign", and any text resting on that reads too
  strong. That verdict is a property of the production golden replay's THIRTY-
  candidate sliced bank. Through `build_slate`'s auto-bank the same grid, same
  postures, same fixture certifies on a clean tree: three runs of three, about 26s
  each. Both measurements are real. The general invariant: the same caps proven
  jointly infeasible against a 30-lineup bank clear against the auto-bank built
  from the same pool, so pool arithmetic (the auto-floors) cannot predict a joint
  refusal. That is why the `approve=False` checkpoint now solves the bank it
  actually has (R28(1), `execution_pipeline` v1.15).
- **A stale bank cache can decide the verdict** (correction, 2026-07-29, same
  merge; this one touches a certified-path read). `runs/bank_cache_<date>_<poolsig>.json`
  is keyed by slate date and pool signature and is read by any build for that date.
  A stale or foreign cache does not merely waste a slice: an eight-candidate
  leftover short-circuited the bank build and the identical command refused in 4.6s
  where clean runs certify in about 26s. The eval harness was writing exactly such a
  file (fixed in R28: `RepoSurfaceGuard` restores `runs/bank_cache_*.json`
  byte-exactly). The standing rule: when a build refuses on a cap interaction, check
  the bank cache's candidate count before believing the refusal.

### 3.4 Posture and contest shape

- `infer_contest_archetype` misclassifies recurring-family contest names (for
  example Pocket Cup, Relay Throw) because the family pattern outranks the Satellite
  or Qualifier token, which causes satellites to mis-classify as `large_gpp` and
  under-fill. Pass explicit `contest_postures` keyed by contest ID to bypass it.
- A multi-seat satellite must carry its satellite shape (ticket_line) or it is
  priced as a GPP and under-fills. Verify the inferred shape for any recurring-family
  name and override when the inference is wrong.

### 3.5 Portfolio objective and bank construction

- **WTA satellites and GPPs: the objective is to maximize P(at least one entry
  wins),** which means ceiling and decorrelation, not floor, and not max expected
  score per lineup. Full SP correlation across entries means any single SP bust
  zeroes the portfolio. The certification gates will not catch this; it is a
  strategic error, not a workflow error.
- Build tight consecutive batting-order stacks (slots 1 to 4 or 1 to 5). A wide
  stack that reaches down the order for cheap salary-relief bats is worse than a
  tight one even at a small ceiling cost.
- **Break bank concentration before allocation.** A single dominant value bat or
  stack appearing in nearly every candidate binds the player cap and causes
  infeasibility. Mitigations: the value-sanity guard (cap a hitter's Base at the
  90th-percentile pts/$k times 1.08) and sub-bank construction with stack
  exclusions, pooled and deduplicated, then routed via `allowed_candidate_ids`.
- **Exposure caps cannot fix a player the bank never generated.** If the optimizer
  always prefers a more flexible player at a contested slot, the target never enters
  any candidate and no cap rescues it. `contested_slot_audit` and
  `audit_bank_player_coverage` surface this before and after bank construction; they
  never auto-apply an override.
- Deployed entry count scales with the bank-coverage gap, not with how many entries
  are available. On a thin slate dominated by one ace, donating seats to weak SP
  pairs is negative equity; concentrate.
- Cash and double-up are a weak architectural fit. Flag and confirm before building.

---

### 3.6 Integration wiring and no-op detection (added v2.23.0)

- **A passing unit suite does not certify an integration.** 86 tests were green
  while the front door's xwOBA correction was a silent no-op: the MLBAM-keyed
  map was applied to a DK-keyed frame, every player fell back to 1.0, and the
  docs claimed the join existed. Root cause was unit-tested parts joined by an
  untested path. Rule: every enrichment that claims to reach the projection
  frame gets a wiring test that drives synthetic fixtures through the REAL join
  and asserts a specific non-neutral value arrives
  (`ProjectionEnrichmentWiringTests` is the pattern).
- **Zero-applied enrichments fail loudly, never silently.** A supplied
  correction that matches nothing on a real pool raises; a degraded match rate
  or a skipped application is a surfaced warning, never a silent pass-through.
  Silence is reserved for features that were not requested.
- **Manual protocol steps are the same failure class.** The value-sanity guard
  lived outside the engine as a chat-protocol step and was exactly as skippable
  as the broken join. When a protocol step gates projection integrity, codify
  it in the engine with an explicit, reported opt-out
  (`apply_value_sanity_guard=False`), so skipping it is a decision on the
  record, not an omission.
- **Doc claims are audit surface.** The v2.22.0 manifest guaranteed a join the
  front door did not perform. When a release note or manifest guarantee names a
  code path, the wiring test for that path ships in the same release.

### 3.7 Full-field archive and duplication protocol (added 2026-07-04)

- **Per archived contest, the required capture set is four artifacts:** the raw
  standings export, the slate salary CSV, the contest-page trio (entry fee, payout
  structure with paid places, cash line) plus the satellite seat count when
  applicable, and Ben's own Entry IDs. The Cowork archival runbook
  (`cowork_archival_runbook.md`) owns the capture steps.
- **Run `field_miner.py` per contest at archive time:** full-field decomposition,
  duplication tables, the paste-ready archive block, and the opponent-registry
  update. The ownership recompute self-check (recomputed %rostered from parsed
  lineups vs the export's `%Drafted`) must land within 1.5 points or the parse is
  wrong; fix the parse before archiving anything downstream of it.
- **Duplication is exact-lineup and slot-agnostic** (sorted player set). Record
  winner copies and share-duplicated per contest; prize share divides by copies,
  so duplication belongs in every post-mortem readout. Labels: observed field
  behavior and deterministic descriptive statistics, never a probability.
- **The opponent registry** (`data/reference/field_opponent_registry.json`)
  accumulates EntryName usernames across contests: entries, average salary used,
  average max stack, average chalk score, duplicated-entry count. Small recurring
  fields have regulars. Record-only; never a prediction. As of 2026-07-26 there
  is exactly one registry at exactly that path; `--registry` defaults to it and
  should not be passed. It had forked into a second copy under `ledger/` (534
  users against 1986, 230 shared users disagreeing, neither a superset) because
  the flag took a bare cwd-relative path. Accumulation is idempotent per contest,
  so a re-mine is a genuine no-op rather than a silent double count, and the file
  is derived data: `python tools/rebuild_registry.py` reconstructs it from
  `data/archive/**/contest-standings-*.csv` deterministically.
- **Standings-only degraded tier (added 2026-07-04).** When the slate salary CSV is
  unrecoverable, run the miner without it. Duplication tables, winner copies,
  chalk scores, SP-pair concentration (the slot tokens identify pitchers), the
  ownership recompute self-check, and the opponent registry all survive;
  salary-usage and stack tables report unavailable and the archive block is tagged
  `standings_only`. A slate archived at this tier feeds Section 4.6 partially and
  cannot feed the ownership model's salary and value features or grade
  `ownership_prior`. Recovery path: the uploaded DKEntries file for that slate
  embeds the full salary block, so a retained DKEntries upload restores full
  coverage; re-run the miner if one surfaces.

### 3.8 Pre-lock kill list, T-minus clock, and override discipline (added 2026-07-04; amended 2026-07-08)

- **Status as of v2.26.0:** the default checkpoint review states a single Blockers
  line mapped to engine actions; the three-assumption kill list below is opt-in on
  request. The T-minus research clock below remains valid at the orchestration layer;
  inside a build session the engine's `slate_clock` T-schedule governs (T-20 skip
  optionals, T-10 approve on defaults, T-5 present). Override discipline is unchanged.

- **Every pre-build checkpoint review states the kill list:** the three assumptions
  whose failure most damages the portfolio, each with a verification action and a
  deadline. Typical members: opener risk on a declared SP (a `pitcher_role` flag
  triggers a targeted news check, not just a caveat), a projected order not yet
  posted (refresh deadline), a roof or wind call (F5 recompute deadline), a
  postponement candidate (exposure cap).
- **T-minus clock:** T-24h run the tail scanner and platoon orders; T-90m diff
  posted lineups against projected orders and flag scratches; T-45m verify every
  declared SP; T-20m refresh weather and roof calls; post-lock, the authorized
  late-swap window only. Research runs at the orchestration layer; the sandbox
  stays pure execution.
- **Every kill-list resolution maps to an engine action** (`refresh_confirmed_lineups`,
  `compute_f5_factor` recompute, pitcher role reassignment, a game exposure cap,
  `run_late_swap`), never a vibe adjustment.
- **Override discipline:** any discretionary variance injection (an F1 uplift, a
  posture override, an exposure relaxation) must name the specific non-consensus
  information with its source and timestamp, or it does not happen. One rule kills
  both chalk drift and contrarianism-for-its-own-sake.
- **Adversarial pass on material builds:** before approval, a fresh-context review
  with the single mandate "find the one event that zeroes this portfolio and the
  cheapest hedge." Fresh context matters because a reviewer anchored on the build
  narrative defends it. Output is constrained to engine actions.

### 3.9 Posture tier policy (bankroll policy, labeled; added 2026-07-04)

- **The waterfall is purchased in fee allocation, not lineup space.** No
  lineup-level floor exists in a top-heavy contest; floor-oriented construction
  there lowers P(first) and buys nothing. "Floor" means fees allocated to
  broad-payout shapes.
- **Tiers, per `posture_allocator.py` (untracked, review-only):** Tier F, payout
  breadth >= 0.20 or a multi-seat satellite (seats >= 3, breadth >= 0.10), takes
  the top-script, highest-median, chalk-primary archetype; a won ticket is a
  realized convertible asset. Tier A, paid places == 1 or breadth <= 0.05, takes
  the decorrelated ceiling set with SP-pair spread (3.5) and the duplication-risk
  screen on every candidate. Tier V, everything else, takes distinct near-best
  lineups under the concentration rule.
- **Concentration rule (the Priority 3 math):** expected win count is linear, so
  the top lineup duplicates across independent, linear-payout contests; diversify
  where wins are substitutes (entries in the same satellite family), where
  within-contest duplication splits the prize, or where model uncertainty argues
  for spreading across scenario-argmax lineups.
- **Fee-share targets** (default floor >= 25% of fees, apex 40 to 60%) are bankroll
  policy priors, adjustable per slate and stated in the build report, never
  cash-rate or win-rate claims. A contest with unknown paid places is UNRESOLVED
  and blocks allocation until the contest page is captured.
- **The allocator is review-only.** It emits an explicit `contest_postures` dict
  (invariant 3.4) for Ben to pass; nothing auto-applies.

### 3.10 Environment factor ownership (DATED DECISION, 2026-07-27, F18)

**The question.** A posted game total already prices the ballpark. F1 is built
from that total; F5's hitter factor is `park_run_factor x wind`. The two are
multiplied into the same projection, so an extreme park was paid for twice. On
the shipped park band (0.94 to 1.08) and F1's clip (0.85 to 1.15) the product
reached 1.242 against a factor whose own band tops out at 1.15. The error is
systematic and it concentrates exactly where stack decisions concentrate.

**The decision.** F5 owns the ballpark. F1 owns the rest of the run environment.
`build_f1_factors` divides each team's implied total by its game's
`park_run_factor` before the slate-mean ratio, and the denominator is the mean of
the same de-parked quantity. What reaches F1 is the market's view net of the
ballpark: pitching matchup, lineup quality, bullpen, altitude-independent
conditions. F5 is unchanged.

**Why this way and not the other way.** The alternative was to leave F1 on the
raw total and strip `park_run_factor` out of F5. Both price the park once. This
one prices it from `f5_park_factors.csv`, a measured multi-year table, instead of
inferring it from one night's line; and it keeps a park effect on a slate where
the odds fetch failed, which the alternative does not. The third option on the
table, de-parking F1 AND stripping park from F5, was rejected on inspection: it
removes tonight's ballpark from the projection entirely, and the xwOBA Base
correction only removes HISTORICAL park contamination from the base level, so
nothing else would have added it back.

**What this does not do, stated so it is not rediscovered as a bug.** De-parking
removes the double count. It does not cap `Base x F1 x F5`. The clip is applied
to F1 alone, so on a slate whose de-parked spread still exceeds the band, F1
saturates at 1.15 and the product reaches `1.15 x park` anyway. The F18
acceptance line in the backlog ("a Coors fixture's combined uplift stays inside
the F1 clip band") is therefore true of realistic slates and false in general;
the real 2026-07-25 four-game slate went from 1.242 to 1.131. A hard ceiling on
the product would require F1 to read F5, which is the boundary this decision
draws, and it would be its own decision at the composition site.

**One venue resolution.** `build_slate.resolve_slate_venues` is the single
resolver. F1 reads its park factor and F5 reads its venue, roof, azimuth and wind
threshold from the same record, because two resolutions of one fact is this
project's named no-op failure class.

### 3.11 Portfolio caps for the satellite family (DATED DECISION, 2026-07-27, R5)

**The question.** Two cap sets shipped and the strategy doc matched the one
production does not run. `execution_pipeline.STRATEGY_DEFAULTS`, which
`run_slate` merges by posture, gave `wta_satellite` a player cap of 0.60, a
pitcher cap of 0.70, a primary-stack cap of 0.60 and 7 shared players.
MLB_Classic section 8 published 0.45 / 0.43 / 0.35 / 5. Duplication is the main
enemy in a satellite-heavy portfolio, so this was a live strategy fact and not a
doc nit.

| control | STRATEGY_DEFAULTS wta_satellite (was) | MLB_Classic section 8 | adopted |
|---|---|---|---|
| max_player_exposure_pct | 0.60 | 0.45 | 0.45 |
| max_pitcher_exposure_pct | 0.70 | 0.43 | 0.43 |
| max_primary_stack_exposure_pct | 0.60 | 0.35 | 0.35 |
| max_sp_pair_repetition | 2 | ~12% of entries, min 2 | 2 |
| max_shared_players | 7 | 5 at 8+ entries | 5 |

**Two claims the draft of this entry carried were wrong, and correcting them
changed the answer.** First, it named `contest_allocator.plan_and_assign_entries`
as the path that already implements section 8. No such function exists on this
tree. The section 8 numbers live in `select_and_assign_portfolio`
(`contest_allocator.py:1873-1877`), which has zero production callers and one
test caller. Second, and decisive: inside that function the caps block is gated
on `tournament = bool(shapes) and all(x not in {"cash", "satellite"} ...)`, so a
satellite card turns the caps off entirely. Section 8's numbers were never
applied to a satellite anywhere, and section 8's own heading called them "Lean
WTA/GPP defaults." Tightening the satellite family is therefore a new strategy
choice, not a reconciliation, and it had to be argued rather than adopted.

**The decision.** Adopt section 8's numbers on the existing `wta_satellite`
posture. Do not split the posture.

The draft preferred a split: a new `satellite` posture at section 8's numbers,
with `wta_satellite` left concentrated at 0.70 / 0.60 / 7 for true winner-take-
all. Rejected, because the premise does not hold. Loose caps for a true WTA
assume concentration on the single best build is correct at any entry count, and
it is correct only at one entry, which is the `single_entry` posture and already
has caps of 1.0. At four or eight entries a WTA wants live independent shots at
first place for the same reason a satellite wants them at the line. The
objective difference between the two, first place versus clearing a cut, is real
and it is already carried at the shape level by `resolve_contest_shape` and the
0.58/0.42 ticket-line blend. It does not need a second expression in the caps
table. Adding a fifth caps row and a change to the posture fold would buy a
distinction for the contest type this portfolio enters least.

**What this compounds with.** R1b made satellite ranking floor-aware. Tighter
caps and a cut-line objective push the same direction: clear the line on shots
that do not fail together.

**The honest counterargument, unchanged from the draft.** Tighter caps buy
decorrelation by forcing the portfolio off its best play. Pitcher 0.43 on an
eight-entry portfolio means at least three entries take an arm the engine ranked
below the top one, and on a four-game slate the third-best arm can be materially
worse rather than marginally. `_slate_feasibility` derives the minimum feasible
caps, floors the merged caps up before the explicit override, and reports the
floor, so an infeasible slate degrades visibly. It does not protect against
quality dilution, which is invisible in the certified output. Nothing in the
archive measures this yet, which is why this is a judgment call and not a fit.

**The GPP half of the divergence is retired in the doc, not the code.** Section 8
published one flat row while `STRATEGY_DEFAULTS` ladders the GPP postures by
field size (`small_gpp` 0.50 / 0.60 / 0.55 / 6, `large_gpp` 0.40 / 0.55 / 0.50 /
6, `mme` 0.35 / 0.50 / 0.45 / 6). The ladder is the better reasoning and one flat
row cannot express it, so section 8 now names `STRATEGY_DEFAULTS` as the
production caps table and records the ladder as deliberate.

**Also settled here.** CLAUDE.md's Showdown block called the two portfolio
controls "non-negotiable and enforced in the solver", four lines above the
sentence describing the order in which they relax. Now "enforced in the solver,
not in review, and relaxed only in the stated order and counted" (RC 1.14, routed
here by R3d).

**What this does not do.** It sets caps for the `wta_satellite` posture only. It
does not touch `single_entry`, `small_gpp`, `large_gpp`, `mme` or `cash`, and it
does not change the feasibility floors, which may still relax any of these upward
on a thin slate and say so. The golden replay overrides every cap
(`LOOSE_CONTROLS`), so this change cannot move that baseline; R6(b)'s
production-controls replay is what will exercise it.

### 3.12 GPP ranks on ceiling, and the table stops saying otherwise (DATED DECISION, 2026-07-27)

**The question.** `score_lineup_candidate` blends a profile's ceiling and floor
weights for the `cash` and `ticket_line` families and takes raw ceiling for
everything else. Six `gpp` profiles advertised a split anyway: `small_field_gpp`
0.80/0.20, `single_entry_gpp` 0.78/0.22, `mid_field_gpp` 0.76/0.24,
`large_field_gpp` and `portfolio_gpp` 0.72/0.28, `mme_gpp` 0.70/0.30. None of it
reached the score. This is the same defect R1b fixed one family over, and R1b
deliberately left it because extending the blend reranks every GPP contest.

**Measured, not argued.** Patching the branch to include `gpp` and re-running the
golden replay moved the baseline: 3 of 18 entries changed candidate. All four GPP
entries sit in one contest (191047506), the same four candidates were selected
before and after, and exposure and SP-pair distribution were byte-identical, so
the change was a permutation of entry-to-lineup pairing inside one contest and
not a change to what would be entered. All three certification gates held.

**The decision.** Delete the pair from the six gpp profiles. GPP ranks on ceiling.

**Why delete rather than consume.** Two reasons, both independent of the
measurement. The advertised ladder ran backwards: floor weight RISES as the field
grows, 0.20 at small field to 0.30 at MME, while a bigger and more top-heavy
field is exactly where ceiling matters more and cashing matters less. In the same
profiles `field_pressure_weight` (0.40 to 0.82) and `salary_uniqueness_weight`
(0.25 to 0.62) ladder the right way, so the asymmetry is evidence the ceiling and
floor pair was never reasoned to. Turning it on would ship that error into every
GPP contest. Second, floor carries no enrichment signal. xISO hitter ceilings and
K-rate pitcher ceilings both land on `Ceiling`; `Floor` stays a flat 0.58 multiple
of Base unless something moves it. A 0.28 floor weight therefore discards 28% of
the signal the enrichment stack exists to produce, in the contests where ceiling
is the objective. The `wta` family already says the same thing in the table's own
vocabulary with 1.00/0.00.

**The honest counterargument.** Floor-awareness in a GPP is a normal commercial
default and 20-30% is a normal number. The reason not to adopt it today is that
under the emergency-proxy projections the golden replay runs, Floor is a fixed
0.58 multiple of Base and Ceiling a fixed 1.42, so any blend is rank-equivalent
to ceiling within the projection term and the measurement above cannot separate a
good version of this change from a bad one. If GPP floor-awareness is wanted, the
version to build is a corrected ladder, ceiling weight rising with field size,
landed against R6(b)'s enriched golden replay where the effect is observable.

**Rule restored.** A weight in `CONTEST_SHAPE_PROFILE_WEIGHTS` is consumed or it
is not in the table. The weight-consumption contract test now carries one
exemption, `wta`'s 1.00/0.00, instead of two.

### 3.13 The money backfill, and the two holes it closed and did not close (2026-07-29)

Source of record for every historical fee, own-entry count, and winnings figure is
Ben's DraftKings **contest entry history** export (`draftkings-contest-entry-history.csv`,
6,526 rows, 2023-10-29 to 2026-07-28). It joins the archive on `Contest_Key` ==
`contest_id`, and its `Entry_Key` column **is** the standings CSV's `EntryId`,
verified row-for-row. The export contains completed contests only: zero blank
`Place`, zero blank `Points`, no row dated past its last slate. That last fact is
load-bearing and is the reason the satellite ticket leg in 3.14 is partly
unresolvable.

- **Closed: fees and winnings.** All 97 archived contests whose standings CSV still
  exists on disk now carry an entry fee, own-entry count, winnings, and net.
  `tools/net_to_date.py` prints a real cumulative table where it used to print
  nothing. Reconciled exactly against the export: 76 inbox contests at $38.21 fees /
  $28.50 winnings / -$9.71 net over 241 matched entries, plus 21 previously
  unmatched archived contests at $13.25 / $1.50 / -$11.75 over 79 entries.
- **The trap that made the first attempt a silent no-op.** `--entry-fee` and
  `--winnings` are written only inside the miner's own-results stage, and that stage
  runs only when own entry IDs resolve. The miner harvests them from
  `outputs/<slate-date>/upload_manifest.json`, which exists for 4 of the 10 backfilled
  slate dates. On the other 6 the mine exits 0, prints no `own results:` line, and
  drops the fees on the floor. **Always pass `--my-entry-ids` explicitly when
  backfilling a historical slate**; the entry history is the only source for it.
  An exit code of 0 is not evidence that the fee landed. Check for the `own results:`
  line, or re-read the record.
- **Not closed: `paid_places`.** The export carries `Places_Paid` for every one of
  the 100 archived contests, and for satellites it is exactly the ticket count
  awarded. Nothing can write it: the miner has no `--paid-places` flag,
  `own_results.json` has no field for it, and the only consumer,
  `posture_allocator`, reads it off a contest dict that nothing populates.
  `contest_library.record_observation` accepts it but no CLI reaches it. The values
  are parked in `data/reference/dk_contest_paid_places.json` (ARCHIVE-owned, keyed by
  contest_id, with field_size and the observed name) so the flag, when DEV adds it,
  has nothing to re-derive. Backlog fragment filed.
- **Housekeeping.** A re-mine is idempotent, verified: `own_results.json` and
  `field_opponent_registry.json` are byte-identical after mining the same contest
  twice, and records update in place rather than appending. `--salary-dir
  data/slates/<date>` cuts a mine from 7-25s to under a second, because bare
  `--auto-salary` scores all 170 salary CSVs in the repo; the 100%-join check still
  guards correctness. The standings inbox is drained of CSVs (46 source .zip files
  remain, which is expected and harmless).

### 3.14 The satellite leg, measured end to end (DATED FINDING, 2026-07-29)

Observed outcomes over 4,201 MLB satellite entries (4,736 across all sports) that no
model predicted. Not ROI, not a win rate, not a probability claim. This grades the
operation, not the engine.

**Read the MLB column first. This is an MLB ledger and the source export is
all-sports** (`Sport` column: MLB 4,879 of 6,526 entries, then GOLF 737, NBA 432,
NHL 187, SOC 151, NFL 120, and a tail). Every all-sports figure below is labelled as
such and none of them belongs in an MLB decision.

**MLB only** (`Sport == 'MLB'`), and this is the line that matters:

| | entries | fees | cash | ticket face |
|---|---|---|---|---|
| all MLB | 4,879 | $563.36 | $251.05 | $216.00 |
| MLB satellites | 4,201 | $262.35 | **$3.90** | $216.00 |
| MLB non-satellite | 678 | $301.01 | **$247.15** | $0.00 |

MLB net cash of -$312.31 splits -$258.45 satellite and -$53.86 non-satellite on raw
columns. Attributing the $14.00 that ticket-funded Pocket Cup entries returned back to
the satellites that produced the tickets puts the satellite leg at **-$244.45**. Use
one view or the other; never sum them, because the $14 sits in the non-satellite
column too. Either way **the satellite block carries roughly four fifths of the MLB
loss on 86% of the MLB entries, and the engine's actual domain, MLB non-satellite
Classic and Showdown, is close to break-even on observed outcomes** ($301.01 against
$247.15, and May returned $66.24 on $63.55).

**Of the $216 in ticket face MLB satellites won, only $61 is a prize this engine can
play.** Decomposed by the sport of the *prize*, not the sport of the entry:

| prize sport | target | satellite entries | satellite fees | ticket face |
|---|---|---|---|---|
| MLB Best Ball | Midseason Best Ball $5 Knuckleball | 207 | $36.45 | $55.00 |
| **NFL** | NFL Best Ball $25 Millionaire | 380 | $65.45 | $50.00 |
| MLB | $15 Relay Throw | 215 | $30.20 | $30.00 |
| **NBA** | NBA Best Ball $20 Shootaround | 2 | $2.00 | $20.00 |
| **TEN** | TEN $20 French Slam | 4 | $1.50 | $20.00 |
| MLB | $2 Pocket Cup MEGA Qualifier | 2,915 | $29.15 | $18.00 |
| MLB | $5M FBWC $13 Qualifier | 193 | $19.30 | $13.00 |
| **NFL** | NFL $5 Fantasy Football Millionaire | 87 | $15.60 | $10.00 |

$61 MLB Classic/Showdown-playable, $55 MLB Best Ball (a season-long product, not this
engine), **$100 prizes in other sports entirely.** MLB DFS entries are the vehicle;
NFL, NBA and tennis prizes are a large part of the cargo. The Best Ball
classification is inferred from the contest name and is the one soft cell in the
table.

MLB satellite leg, cash only, end to end: **$262.35 fees out, $3.90 direct cash back,
$14.00 back through redeemed MLB-target tickets, $17.90 returned, -$244.45 observed
net.** No MLB satellite has ever produced a ticket that converted to more than $14 in
total. The single $40 conversion in the table further down was a GOLF satellite.

**All-sports context, for the ticket-chain mechanics only.** Satellite block across
every sport (name contains `satellite` **or** `supersat`): 4,736 entries, $391.35
fees, $3.90 direct cash, $325.00 ticket face won. Every satellite fee is fresh cash:
the entry-fee distribution tops out at $1.00 with a single $3.00 outlier, and the
smallest ticket ever won is $2.00 and is locked to a named target contest, so no
ticket can fund a satellite. Recycled ticket value into satellites is **zero
percent**; recycling happens strictly downstream. The chain table below is all-sports
because the chains themselves cross sports.

Of the $325 in ticket face, **$150 was redeemed and traceable, and it returned $54.00
in cash.** Six single-ticket chains matched a target entry on exact fee and consistent
date; the nine $2 Pocket Cup tickets reconcile to a running balance of exactly zero
against nine $2 target entries at two redemption dates.

| ticket won | face | target entry | finish | cash back |
|---|---|---|---|---|
| 2026-05-10 GOLF | $25 | 05-14 PGA $2.5M Millionaire | 14794/117647 | **$40.00** |
| 2026-05-20 MLB | $20 | 05-26 TEN $100K French Slam | 1425/5551 | $0.00 |
| 2026-06-04 GOLF | $34 | 06-11 Fantasy Golf WC Qualifier #180 | 68/725 (13 paid) | $0.00 |
| 2026-06-08 MLB | $15 | 06-09 MLB $60K Relay Throw | 1461/4705 | $0.00 |
| 2026-06-25 GOLF | $25 | 07-16 PGA $2.5M Millionaire | 110565/117647 | $0.00 |
| 2026-07-19 MLB | $13 | 07-20 Fantasy Baseball WC Qualifier #73 | 1316/4739 | $0.00 |
| 9 tickets, 05-27 to 06-21 | $18 | 06-01 x5 and 07-21 x4, $2 Pocket Cup MEGA | best 100/5251 | $14.00 |

**Yes, a chain has terminated in cash, twice, and both times it was small.** The
$0.25 GOLF satellite on 05-10 became a $25 ticket became $40. The penny Pocket Cup
satellites became $18 of tickets became $14. Nothing else has come back.

**$175 of ticket face is unaccounted for and $150 of that cannot be resolved from
this export.** $150 sits in Best Ball products (3 x $25 NFL Best Ball Millionaire,
11 x $5 Midseason Best Ball Knuckleball, 1 x $20 NBA Best Ball Shootaround) with zero
matching entries anywhere in the file. Best Ball entries *do* appear in this export
when they complete (two $1 drafts from 2024 and 2025 are present), so the absence
means either unspent or spent-and-still-scoring, and the completed-contests-only
limitation makes those two indistinguishable. Do not estimate this leg. The remaining
$25 is genuinely pending, not lost: 2 x $5 NFL Fantasy Football Millionaire tickets
target a 2026-09-13 contest, and a second $15 Relay Throw ticket was won 2026-07-28.

**MLB and GOLF satellites are not the same instrument.**

| | MLB | GOLF |
|---|---|---|
| entries | 4,201 | 377 |
| fees | $262.35 | $97.70 |
| fee per entry | $0.062 | $0.259 |
| direct cash | $3.90 | $0.00 |
| ticket face won | $216.00 | $109.00 |
| ticket face per $1 of fee | $0.823 | $1.116 |
| entries that won a ticket | 29 (0.690%) | 4 (1.061%) |
| median field | 357 | 133 |

GOLF costs 4x more per entry and returns more face per dollar into a field a third
the size. Both cash conversions in the table above trace to the two cheapest, thinnest
structures. Multi-ticket satellites (`Places_Paid` > 1) returned $1.325 of face per
$1 of fee against $0.798 for single-ticket, on 492 entries versus 4,244.

**Two bookkeeping corrections.** A `satellite` substring filter misses `SUPERSat`
and undercounts the block by 17 entries, $8.25 in fees, and $20.00 of ticket face
(the 05-20 French Slam chain). And the headline lifetime figures are not out-of-pocket
numbers: $150 of target-entry fees inside the $1,380.24 total were paid with tickets,
and DK's export shows a ticket-funded entry at full buy-in, indistinguishable from
cash. Lifetime net cash of -$631.66 is therefore an upper bound on the loss, not the
loss.

**Recurring satellite families, with observed ticket counts.** This is the curated
input R1(c) has been waiting on: name substring, sport, and the `Places_Paid` values
actually observed, which for a satellite is the ticket count awarded.

| target family (name substring) | sport | entries | fees | observed ticket_count | median field |
|---|---|---|---|---|---|
| `Pocket Cup` MEGA Qualifier | MLB | 2,915 | $29.15 | 1 (2,475), 5 (200), 10 (240) | 237 |
| `Knuckleball` (Midseason Best Ball $5) | MLB | 207 | $36.45 | 1 | 23 |
| `FBWC` Qualifier | MLB | 193 | $19.30 | 1 | 111 |
| `Best Ball $25 Millionaire` | MLB / GOLF | 380 / 115 | $65.45 / $31.50 | 1 (both), 5 (1 GOLF) | 149 / 118 |
| `Relay Throw` | MLB | 215 | $30.20 | 1 | 166 |
| `Fantasy Football Millionaire` | MLB | 87 | $15.60 | 1 (60), 2 (19), 5 (8) | 59 |
| `Golf Millionaire` | GOLF / MLB | 167 / 168 | $45.50 / $51.90 | 1, 4 (1 GOLF) | 118 |
| `Sand Trap` (PGA $25) | GOLF | 86 | $16.70 | 1 | 118 |
| `FGWC` Qualifier | GOLF | 8 | $3.00 | 1 | 63 |

A further 188 satellite entries and $43.30 in fees matched no family above (Grass
Swing Slam, Playoff Puck Drop) and won nothing.

## 4. CALIBRATION CONTENT (INERT until the Section 0 gate opens)

Populate these per slate from the archive. None of it moves a projection today.

### 4.1 Field model: how the crowd concentrates

**Status: INERT. No ownership prediction exists.** `Ownership_Tier` defaults to a
flat `Mid` in the build path, so there is currently no per-player ownership
assumption to nudge. This bucket is blocked on the homegrown ownership model in
Section 5, not on the standings, which now supply the actuals to grade against.

Expressed through this sport's structural drivers: salary, slate size, name
recognition, and the obvious-play magnets (chalk starting pitchers, cheap bats with
a confirmed top-of-order slot), modified by the contest's paid-band shape. Once the
model exists, the calibratable quantity is its cross-sectional error against
archived `%Drafted`, conditioned on archetype.

### 4.2 Outcome model: where scoring concentrates by role and matchup

**Status: INERT for auto-application.** The xwOBA base correction and the tail
scanner already route attention to contact-luck and game-environment signals, but
magnitude calibration of Base x F1..F5 against actual FPTS needs many conditioned
slates and is the second, slower thing to converge. Log per-slate magnitude misses
in the archive; do not adjust factors from them yet.

### 4.3 High-leverage slot heuristic

**Status: OPEN (hypothesis, one supporting slate).** Every format has one position
or decision where the field is weakest and variance is highest; in soccer it is
goalkeeper. The working hypothesis for MLB Classic is that the **starting-pitcher
decision is that slot**, and specifically the SP pairing on thin slates, because the
full-SP-correlation rule (3.5) makes a single bust catastrophic and the field herds
hardest on pitching. On deeper slates the highest-leverage decision shifts toward
the primary stack-game selection. Keep this keyed to context, not to a naive
favorite. It is a hypothesis, not a rule, until conditioned slates confirm it. The
inaugural archive entry is consistent with it (the two chalk SPs were the two
highest-owned players and appeared in all three winning lineups) but one slate
cannot promote it past open.

### 4.4 Archetype memory: which lineup shapes win in which environments

**Status: RECORD-ONLY.** Stored as concrete past winners in the archive, never as a
principle and never promoted to a rule at current volume. There is one winning
lineup per contest, so this never converges here. Read it in post-mortems; do not
calibrate from it.

### 4.5 Process rules

**Status: firm (operational, not magnitude).**

- Hold over rebuild: do not rebuild a portfolio from scratch when an incremental
  edit serves; set and record the hold-vs-rebuild threshold per slate.
- Do not enter a contest you did not build for. If a reserved contest's posture was
  not in the build, do not deploy into it.
- Late-swap discipline: only authorized Entry IDs mutate; unauthorized entries are
  preserved byte-for-byte and re-verified; fully locked entries are skipped and
  surfaced.

### 4.6 Field construction and duplication frequencies (added 2026-07-04)

**Status: RECORD, graduating to structural priors on the repeat gate.**
Per-contest tables emitted by `field_miner.py` at archive time: duplication
distribution (distinct lineups, share duplicated, max copies, winner copies),
at-cap salary share and salary-left histogram, max-stack histogram, SP-pair field
concentration, and chalk concentration (top-5 `%Drafted`). These are observed
distributions of field behavior, not graded predictions; no model is required to
read them. They become usable as structural priors for the Tier A duplication-risk
screen (3.9) only after the same patterns repeat across archetype-conditioned
slates. A single contest never promotes one, and nothing here auto-applies to
candidate selection, projections, or the optimizer. A-001 seeded these tables on
2026-07-04 (three contests, one slate, full coverage); the repeat gate needs more
conditioned slates before anything graduates to a structural prior.

---

## 5. Open dependency: the homegrown ownership model

This is the single gating dependency for Section 4.1 and the real next build.

The accumulating standings archive now supplies actual `%Drafted` every slate. That
removes the need to buy a projected-ownership feed (Stokastic was the candidate);
the cheaper path is to fit our own model from the archive. Inputs: archived
`%Drafted` joined back to the slate salary file (by name and team, the same
crosswalk used in `build_dk_keyed_corrections`) for salary and value, with every row
tagged by contest archetype and field size.

Sequence:

1. Archive every slate in the Section A schema below.
2. Capture the three fields the export omits (entry fee, payout structure, cash
   line) from the contest page.
3. Accumulate on the order of eight to fifteen of these small slates. The pools here
   are roughly 40 to 50 players, so this is the slower cross-sectional path, not an
   instant one.
4. Fit the ownership model. Only when it emits a per-slate prediction does Section
   4.1 turn on and the contrarian-value routing question (Backlog B-7) become
   answerable. Until then routing distributes coverage; it does not price value.

Instrumentation (added 2026-07-04): `field_miner.py` (untracked) is the archival
instrument for step 1. It parses the standings export, joins the slate salary CSV,
emits the full-field decomposition and the paste-ready archive block, updates the
opponent registry, and self-checks the parse by recomputing %rostered against
`%Drafted`. The Cowork archival runbook (`cowork_archival_runbook.md`) owns the
capture steps, including the step 2 contest-page trio. The cross-sectional rows
this sequence accumulates for the ownership model now arrive alongside the Section
4.6 field-construction tables at no extra capture cost. Per-slate ownership rows
accumulate as `ownership_rows_<slate_date>.csv` (long format: contest id, field
size, archetype, player, team, positions, salary, AvgPointsPerGame, actual FPTS,
value per $1k, actual `%Drafted`); the archetype column stays UNKNOWN until the
contest-page trio is captured. A-001's rows were regenerated 2026-07-04 at player
grain from the mined exports: 132 rows, including sub-0.5% players the curated
table omits, with drafted-position splits carried in a dedicated
`drafted_positions` column.

---

=== ARCHIVE (append-only; full decompositions, newest first) ===

**Aging test RESOLVED (2026-07-25):** the four 2026-07-24 night contests came
back fully populated on a next-day pull, one day after the same endpoint returned
zero bytes for the 07-19 contests on their third attempt. Age is the mechanism.
Standing rule: pull standings the night a contest settles or the next morning,
and check the file is non-zero before walking away. A zero-byte export is a
failed pull, not a pulled file.

**Backfill 2026-07-28 (A-013..A-026):** 59 contests across seven slate dates,
pulled after the fact and mined in one pass. Two standing notes come out of it.

First, the age rule needs widening. Contests from 2026-07-17 through 2026-07-27
all returned populated exports on a 2026-07-28 pull, so an eleven-day-old export
can still come back. Four came back zero-byte (191047506, 192345441, 192419758,
192420813) and are recorded unrecoverable. Age raises the failure rate; it is not
a clean cutoff. Pull the night of, still, but a missed pull is worth attempting.

Second, the 3.7 ownership self-check needs a small-field caveat. Thirteen
contests in this backfill report `ownership_recompute_ok: false` with a max diff
above 1.5 pts, and in every one of them the lineup recompute totals exactly
1000.0 pts for Classic or 600.0 for Showdown, meaning every entry carries a full
distinct roster and the parse is sound. DK's own `%Drafted` table is what sums
short, by 2.0 to 30.4 pts, which the miner attributes to DK omitting position
rows for multi-position players. In a 23-entry contest one omitted row is 4.35
pts, so the 1.5-pt tolerance is unreachable below roughly 100 entries. Treat the
lineup-derived ownership as authoritative when `recomputed_total_pct` is exactly
100 x roster_size and `parse_structural_ok` is true; the check as written
assumes DK's table is ground truth and in small fields it is not. Affected:
192707481, 192707520, 192707521, 192707612, 192744091, 192746313, 192747269,
192747982, 192748828, 192784673, 192784674, 192842358, 192851120, 192853093.

## A-013 — 2026-07-27 — 5 contests, Showdown (2145_1g_sd)

Salary basis: data/slates/2026-07-27/DKSalaries_showdown.csv (auto-resolved by field_miner, 100% join on every
contest in this group). Coverage tier: full.

Contests 192784475, 192784476, 192784479, 192798445, 192851120.

Mined 2026-07-28 from a delayed standings pull. Entry fee, payout structure,
paid places, and cash line were never captured from the contest page. Entry fee,
own-entry count, and winnings were backfilled 2026-07-29 from Ben's DraftKings
contest entry history export (Contest_Key join; Entry_Key == standings EntryId),
so the net line below is now populated; payout structure and cash line remain
uncaptured. paid_places is available in that export and is NOT yet written to
the archive: the miner has no --paid-places flag (see 3.13).


#### Full-field decomposition — contest 192784475 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound; DK %Drafted agrees with the lineup recompute

- Entries 237 (235 complete lineups); winning score 78.85; multi-entry contest: True.
- Duplication: 197 distinct lineups; 25.5% of entries sat in a duplicated lineup; max copies 7; the winning lineup had 1 copy. Copies histogram: {1: 175, 2: 15, 3: 4, 4: 1, 7: 2}.
- Salary usage: 45.5% of entries within $100 of the cap. Salary-left bins: {'> 1500': 12, '1-100': 49, '701-1500': 24, '101-300': 50, '<= 0': 58, '301-700': 42}.
- Max-stack histogram: {3: 55, 4: 98, 5: 82}.
- **Self vs field**: 7 own entries; best rank 37/237 (84.81th pct), median 40.08th pct; best 51.75 pts against a winning 78.85; 1 own lineup(s) duplicated by the field (max 2 copies); fees $0.07, winnings $0.00, net $-0.07. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Brandon Sproat 55.7%, Brice Turang 41.35%, Jackson Chourio 40.51%, Cooper Pratt 38.39%, Tyler Mahle 37.13%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 0.42 pts; parse OK; DK %Drafted agrees.


#### Full-field decomposition — contest 192784476 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound; DK %Drafted agrees with the lineup recompute

- Entries 237 (224 complete lineups); winning score 78.85; multi-entry contest: True.
- Duplication: 188 distinct lineups; 23.7% of entries sat in a duplicated lineup; max copies 7; the winning lineup had 1 copy. Copies histogram: {1: 171, 2: 8, 3: 6, 5: 1, 7: 2}.
- Salary usage: 48.2% of entries within $100 of the cap. Salary-left bins: {'1-100': 52, '> 1500': 9, '301-700': 41, '<= 0': 56, '101-300': 37, '701-1500': 29}.
- Max-stack histogram: {3: 54, 4: 97, 5: 73}.
- **Self vs field**: 7 own entries; best rank 13/237 (94.94th pct), median 65.82th pct; best 61.6 pts against a winning 78.85; 0 own lineup(s) duplicated by the field (max 1 copies); fees $0.07, winnings $0.00, net $-0.07. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Brandon Sproat 51.47%, Brice Turang 38.4%, Jackson Chourio 37.55%, Cooper Pratt 34.6%, Tyler Mahle 33.76%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 0.01 pts; parse OK; DK %Drafted agrees.


#### Full-field decomposition — contest 192784479 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound; DK %Drafted agrees with the lineup recompute

- Entries 59 (56 complete lineups); winning score 78.85; multi-entry contest: False.
- Duplication: 56 distinct lineups; 0.0% of entries sat in a duplicated lineup; max copies 1; the winning lineup had 1 copy. Copies histogram: {1: 56}.
- Salary usage: 46.4% of entries within $100 of the cap. Salary-left bins: {'1-100': 13, '301-700': 13, '<= 0': 13, '101-300': 10, '> 1500': 3, '701-1500': 4}.
- Max-stack histogram: {3: 14, 4: 22, 5: 20}.
- **Self vs field**: 1 own entries; best rank 46/59 (23.73th pct), median 23.73th pct; best 17.1 pts against a winning 78.85; 0 own lineup(s) duplicated by the field (max 1 copies); fees $0.10, winnings $0.00, net $-0.10. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Cooper Pratt 47.46%, Brandon Sproat 45.76%, Jackson Chourio 44.06%, Brice Turang 38.98%, Tyler Mahle 37.29%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 0.01 pts; parse OK; DK %Drafted agrees.


#### Full-field decomposition — contest 192798445 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound; DK %Drafted agrees with the lineup recompute

- Entries 2378 (2353 complete lineups); winning score 80.85; multi-entry contest: True.
- Duplication: 1312 distinct lineups; 61.5% of entries sat in a duplicated lineup; max copies 26; the winning lineup had 2 copies. Copies histogram: {1: 907, 2: 204, 3: 84, 4: 42, 5: 24, 6: 18, 7: 10, 8: 4, 9: 2, 10: 4, 12: 2, 13: 2, 14: 2, 17: 1, 19: 1, 20: 1, 21: 1, 24: 1, 25: 1, 26: 1}.
- Salary usage: 38.0% of entries within $100 of the cap. Salary-left bins: {'301-700': 527, '1-100': 433, '> 1500': 147, '701-1500': 268, '<= 0': 462, '101-300': 516}.
- Max-stack histogram: {3: 518, 4: 860, 5: 975}.
- **Self vs field**: 1 own entries; best rank 537/2378 (77.46th pct), median 77.46th pct; best 50.75 pts against a winning 80.85; 1 own lineup(s) duplicated by the field (max 4 copies); fees $1.00, winnings $1.50, net $0.50. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Brandon Sproat 54.04%, Tyler Mahle 41.93%, Rafael Devers 40.63%, Cooper Pratt 40.54%, Brice Turang 37.38%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 0.01 pts; parse OK; DK %Drafted agrees.


#### Full-field decomposition — contest 192851120 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound (every complete entry carries 6 distinct players); DK's %Drafted table sums 30.4 pts short, which is DK omitting position rows for multi-position players. Lineup-derived ownership is authoritative for this contest.

- Entries 23 (23 complete lineups); winning score 78.85; multi-entry contest: False.
- Duplication: 22 distinct lineups; 8.7% of entries sat in a duplicated lineup; max copies 2; the winning lineup had 1 copy. Copies histogram: {1: 21, 2: 1}.
- Salary usage: 34.8% of entries within $100 of the cap. Salary-left bins: {'1-100': 4, '301-700': 5, '101-300': 4, '<= 0': 4, '701-1500': 4, '> 1500': 2}.
- Max-stack histogram: {3: 9, 4: 4, 5: 10}.
- **Self vs field**: 1 own entries; best rank 3/23 (91.3th pct), median 91.3th pct; best 63.75 pts against a winning 78.85; 0 own lineup(s) duplicated by the field (max 1 copies); fees $0.25, winnings $0.00, net $-0.25. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Tyler Mahle 52.17%, Cooper Pratt 47.83%, Rafael Devers 43.47%, Drew Gilbert 39.13%, Jackson Chourio 39.13%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 21.74 pts; parse OK; DK %Drafted table short 30.4 pts (DK omits multi-position rows; lineup-derived ownership used).


---


## A-014 — 2026-07-27 — 8 contests, Classic (2138_3g)

Salary basis: data/slates/2026-07-27/DKSalaries.csv (auto-resolved by field_miner, 100% join on every
contest in this group). Coverage tier: full.

Contests 192784653, 192784672, 192784673, 192784674, 192798437, 192842358, 192853093, 192853339.

Mined 2026-07-28 from a delayed standings pull. Entry fee, payout structure,
paid places, and cash line were never captured from the contest page. Entry fee,
own-entry count, and winnings were backfilled 2026-07-29 from Ben's DraftKings
contest entry history export (Contest_Key join; Entry_Key == standings EntryId),
so the net line below is now populated; payout structure and cash line remain
uncaptured. paid_places is available in that export and is NOT yet written to
the archive: the miner has no --paid-places flag (see 3.13).


#### Full-field decomposition — contest 192784653 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound; DK %Drafted agrees with the lineup recompute

- Entries 118 (117 complete lineups); winning score 113.0; multi-entry contest: True.
- Duplication: 115 distinct lineups; 3.4% of entries sat in a duplicated lineup; max copies 2; the winning lineup had 1 copy. Copies histogram: {1: 113, 2: 2}.
- Salary usage: 38.5% of entries within $100 of the cap. Salary-left bins: {'> 1500': 16, '1-100': 24, '<= 0': 21, '701-1500': 11, '301-700': 18, '101-300': 27}.
- Max-stack histogram: {2: 6, 3: 25, 4: 40, 5: 46}.
- SP-pair field share (top): Payton Tolle/Tatsuya Imai 36.8%, Payton Tolle/Walbert Urena 16.2%, Brandon Sproat/Payton Tolle 7.7%, Brandon Sproat/Tatsuya Imai 7.7%.
- **Self vs field**: 3 own entries; best rank 2/118 (99.15th pct), median 85.59th pct; best 109.9 pts against a winning 113.0; 0 own lineup(s) duplicated by the field (max 1 copies); fees $0.75, winnings $0.00, net $-0.75. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Payton Tolle 68.64%, Tatsuya Imai 54.24%, William Contreras 42.37%, Wilyer Abreu 42.37%, Willson Contreras 40.68%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 0.01 pts; parse OK; DK %Drafted agrees.


#### Full-field decomposition — contest 192784672 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound; DK %Drafted agrees with the lineup recompute

- Entries 59 (57 complete lineups); winning score 102.5; multi-entry contest: False.
- Duplication: 56 distinct lineups; 3.5% of entries sat in a duplicated lineup; max copies 2; the winning lineup had 1 copy. Copies histogram: {1: 55, 2: 1}.
- Salary usage: 40.4% of entries within $100 of the cap. Salary-left bins: {'1-100': 12, '301-700': 13, '> 1500': 5, '<= 0': 11, '101-300': 12, '701-1500': 4}.
- Max-stack histogram: {2: 5, 3: 16, 4: 17, 5: 19}.
- SP-pair field share (top): Payton Tolle/Tatsuya Imai 35.1%, Payton Tolle/Walbert Urena 14.0%, Brandon Sproat/Payton Tolle 8.8%, Brandon Sproat/Tatsuya Imai 7.0%.
- **Self vs field**: 1 own entries; best rank 19/59 (69.49th pct), median 69.49th pct; best 79.6 pts against a winning 102.5; 0 own lineup(s) duplicated by the field (max 1 copies); fees $0.10, winnings $0.00, net $-0.10. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Payton Tolle 62.71%, Tatsuya Imai 52.54%, William Contreras 47.46%, Yordan Alvarez 44.07%, Jeremy Pena 38.98%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 0.01 pts; parse OK; DK %Drafted agrees.


#### Full-field decomposition — contest 192784673 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound (every complete entry carries 10 distinct players); DK's %Drafted table sums 12.0 pts short, which is DK omitting position rows for multi-position players. Lineup-derived ownership is authoritative for this contest.

- Entries 59 (56 complete lineups); winning score 121.9; multi-entry contest: False.
- Duplication: 56 distinct lineups; 0.0% of entries sat in a duplicated lineup; max copies 1; the winning lineup had 1 copy. Copies histogram: {1: 56}.
- Salary usage: 39.3% of entries within $100 of the cap. Salary-left bins: {'> 1500': 8, '101-300': 10, '301-700': 10, '<= 0': 11, '701-1500': 6, '1-100': 11}.
- Max-stack histogram: {2: 6, 3: 19, 4: 13, 5: 18}.
- SP-pair field share (top): Payton Tolle/Tatsuya Imai 32.1%, Payton Tolle/Walbert Urena 19.6%, Brandon Sproat/Tatsuya Imai 8.9%, Brandon Sproat/Payton Tolle 7.1%.
- **Self vs field**: 1 own entries; best rank 17/59 (72.88th pct), median 72.88th pct; best 84.9 pts against a winning 121.9; 0 own lineup(s) duplicated by the field (max 1 copies); fees $0.10, winnings $0.00, net $-0.10. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Payton Tolle 64.41%, Jeremy Pena 49.15%, Tatsuya Imai 47.46%, William Contreras 44.07%, Yordan Alvarez 42.37%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 10.17 pts; parse OK; DK %Drafted table short 12.0 pts (DK omits multi-position rows; lineup-derived ownership used).


#### Full-field decomposition — contest 192784674 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound (every complete entry carries 10 distinct players); DK's %Drafted table sums 6.9 pts short, which is DK omitting position rows for multi-position players. Lineup-derived ownership is authoritative for this contest.

- Entries 59 (57 complete lineups); winning score 103.5; multi-entry contest: False.
- Duplication: 57 distinct lineups; 0.0% of entries sat in a duplicated lineup; max copies 1; the winning lineup had 1 copy. Copies histogram: {1: 57}.
- Salary usage: 38.6% of entries within $100 of the cap. Salary-left bins: {'> 1500': 6, '701-1500': 9, '101-300': 15, '1-100': 13, '<= 0': 9, '301-700': 5}.
- Max-stack histogram: {2: 5, 3: 19, 4: 16, 5: 17}.
- SP-pair field share (top): Payton Tolle/Tatsuya Imai 35.1%, Payton Tolle/Walbert Urena 19.3%, Brandon Sproat/Tatsuya Imai 8.8%, Brandon Sproat/Payton Tolle 7.0%.
- **Self vs field**: 1 own entries; best rank 57/59 (5.08th pct), median 5.08th pct; best 40.9 pts against a winning 103.5; 0 own lineup(s) duplicated by the field (max 1 copies); fees $0.10, winnings $0.00, net $-0.10. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Payton Tolle 64.41%, Tatsuya Imai 54.24%, William Contreras 45.76%, Brice Turang 44.07%, Jeremy Pena 42.37%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 6.78 pts; parse OK; DK %Drafted table short 6.9 pts (DK omits multi-position rows; lineup-derived ownership used).


#### Full-field decomposition — contest 192798437 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound; DK %Drafted agrees with the lineup recompute

- Entries 11890 (11781 complete lineups); winning score 136.9; multi-entry contest: True.
- Duplication: 10257 distinct lineups; 20.3% of entries sat in a duplicated lineup; max copies 37; the winning lineup had 1 copy. Copies histogram: {1: 9393, 2: 612, 3: 129, 4: 48, 5: 26, 6: 15, 7: 8, 8: 5, 9: 6, 10: 7, 11: 2, 12: 1, 13: 1, 19: 1, 20: 1, 22: 1, 37: 1}.
- Salary usage: 28.0% of entries within $100 of the cap. Salary-left bins: {'> 1500': 2789, '701-1500': 1709, '1-100': 1534, '301-700': 1998, '101-300': 1990, '<= 0': 1761}.
- Max-stack histogram: {2: 739, 3: 2614, 4: 3269, 5: 5159}.
- SP-pair field share (top): Payton Tolle/Tatsuya Imai 24.5%, Brandon Sproat/Tatsuya Imai 12.2%, Payton Tolle/Walbert Urena 12.0%, Brandon Sproat/Payton Tolle 10.7%.
- **Self vs field**: 1 own entries; best rank 7939/11890 (33.24th pct), median 33.24th pct; best 58.6 pts against a winning 136.9; 0 own lineup(s) duplicated by the field (max 1 copies); fees $1.00, winnings $0.00, net $-1.00. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Payton Tolle 54.47%, Tatsuya Imai 50.93%, William Contreras 45.01%, Yordan Alvarez 40.87%, Willson Contreras 36.28%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 0.01 pts; parse OK; DK %Drafted agrees.


#### Full-field decomposition — contest 192842358 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound (every complete entry carries 10 distinct players); DK's %Drafted table sums 4.3 pts short, which is DK omitting position rows for multi-position players. Lineup-derived ownership is authoritative for this contest.

- Entries 23 (22 complete lineups); winning score 102.6; multi-entry contest: False.
- Duplication: 22 distinct lineups; 0.0% of entries sat in a duplicated lineup; max copies 1; the winning lineup had 1 copy. Copies histogram: {1: 22}.
- Salary usage: 36.4% of entries within $100 of the cap. Salary-left bins: {'301-700': 3, '701-1500': 5, '<= 0': 6, '1-100': 2, '101-300': 3, '> 1500': 3}.
- Max-stack histogram: {3: 6, 4: 8, 5: 8}.
- SP-pair field share (top): Payton Tolle/Tatsuya Imai 40.9%, Payton Tolle/Tyler Mahle 9.1%, Payton Tolle/Walbert Urena 9.1%, Brandon Sproat/Payton Tolle 9.1%.
- **Self vs field**: 1 own entries; best rank 21/23 (13.04th pct), median 13.04th pct; best 46.6 pts against a winning 102.6; 0 own lineup(s) duplicated by the field (max 1 copies); fees $0.25, winnings $0.00, net $-0.25. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Payton Tolle 69.57%, Tatsuya Imai 56.52%, Brice Turang 47.83%, Yordan Alvarez 43.48%, Christian Yelich 39.13%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 4.35 pts; parse OK; DK %Drafted table short 4.3 pts (DK omits multi-position rows; lineup-derived ownership used).


#### Full-field decomposition — contest 192853093 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound (every complete entry carries 10 distinct players); DK's %Drafted table sums 4.3 pts short, which is DK omitting position rows for multi-position players. Lineup-derived ownership is authoritative for this contest.

- Entries 23 (22 complete lineups); winning score 89.9; multi-entry contest: False.
- Duplication: 22 distinct lineups; 0.0% of entries sat in a duplicated lineup; max copies 1; the winning lineup had 1 copy. Copies histogram: {1: 22}.
- Salary usage: 40.9% of entries within $100 of the cap. Salary-left bins: {'<= 0': 4, '301-700': 6, '101-300': 4, '1-100': 5, '> 1500': 2, '701-1500': 1}.
- Max-stack histogram: {2: 3, 3: 7, 4: 4, 5: 8}.
- SP-pair field share (top): Payton Tolle/Walbert Urena 36.4%, Payton Tolle/Tatsuya Imai 27.3%, Brandon Sproat/Payton Tolle 9.1%, Tatsuya Imai/Walbert Urena 4.5%.
- **Self vs field**: 1 own entries; best rank 7/23 (73.91th pct), median 73.91th pct; best 73.9 pts against a winning 89.9; 0 own lineup(s) duplicated by the field (max 1 copies); fees $0.25, winnings $0.00, net $-0.25. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Payton Tolle 69.57%, Brice Turang 52.17%, Walbert Urena 52.17%, William Contreras 47.83%, Jeremy Pena 39.13%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 4.35 pts; parse OK; DK %Drafted table short 4.3 pts (DK omits multi-position rows; lineup-derived ownership used).


#### Full-field decomposition — contest 192853339 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound; DK %Drafted agrees with the lineup recompute

- Entries 23 (22 complete lineups); winning score 102.6; multi-entry contest: False.
- Duplication: 22 distinct lineups; 0.0% of entries sat in a duplicated lineup; max copies 1; the winning lineup had 1 copy. Copies histogram: {1: 22}.
- Salary usage: 36.4% of entries within $100 of the cap. Salary-left bins: {'301-700': 5, '701-1500': 1, '<= 0': 5, '101-300': 6, '1-100': 3, '> 1500': 2}.
- Max-stack histogram: {2: 2, 3: 8, 4: 5, 5: 7}.
- SP-pair field share (top): Payton Tolle/Walbert Urena 31.8%, Brandon Sproat/Payton Tolle 22.7%, Payton Tolle/Tatsuya Imai 18.2%, Brandon Sproat/Walbert Urena 4.5%.
- **Self vs field**: 1 own entries; best rank 9/23 (65.22th pct), median 65.22th pct; best 75.0 pts against a winning 102.6; 0 own lineup(s) duplicated by the field (max 1 copies); fees $0.25, winnings $0.00, net $-0.25. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Payton Tolle 69.57%, Brice Turang 52.17%, William Contreras 47.83%, Jake Bauers 47.82%, Walbert Urena 43.48%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 0.01 pts; parse OK; DK %Drafted agrees.


---


## A-015 — 2026-07-25 — 5 contests, Showdown (1915_1g_sd)

Salary basis: none. The resolver declined rather than join against another
slate, so this group is the **standings_only** degraded tier: ownership,
duplication, chalk, and SP pairs are present; salary and stack tables are not.

Contests 192708093, 192708094, 192708096, 192708097, 192754543.

Mined 2026-07-28 from a delayed standings pull. Entry fee, payout structure,
paid places, and cash line were never captured from the contest page. Entry fee,
own-entry count, and winnings were backfilled 2026-07-29 from Ben's DraftKings
contest entry history export (Contest_Key join; Entry_Key == standings EntryId),
so the net line below is now populated; payout structure and cash line remain
uncaptured. paid_places is available in that export and is NOT yet written to
the archive: the miner has no --paid-places flag (see 3.13).


#### Full-field decomposition — contest 192708093 (field_miner 0.5-review; coverage standings_only; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound; DK %Drafted agrees with the lineup recompute

- Entries 237 (234 complete lineups); winning score 79.3; multi-entry contest: True.
- Duplication: 181 distinct lineups; 33.3% of entries sat in a duplicated lineup; max copies 11; the winning lineup had 1 copy. Copies histogram: {1: 156, 2: 14, 3: 7, 5: 1, 6: 1, 7: 1, 11: 1}.
- Salary-usage and stack tables unavailable at this coverage tier (no salary file); re-run at full coverage if the slate salary CSV or the slate's DKEntries upload file (which embeds the salary block) surfaces.
- **Self vs field**: 7 own entries; best rank 7/237 (97.47th pct), median 47.68th pct; best 72.7 pts against a winning 79.3; 1 own lineup(s) duplicated by the field (max 2 copies); fees $0.07, winnings $0.00, net $-0.07. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Yoshinobu Yamamoto 72.99%, Brett Baty 64.98%, Jorge Polanco 45.15%, Nolan McLean 44.73%, Shohei Ohtani 29.12%.
- Diagnostics: salary join n/a (standings_only); ownership recompute max diff 0.01 pts; parse OK; DK %Drafted agrees.


#### Full-field decomposition — contest 192708094 (field_miner 0.5-review; coverage standings_only; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound; DK %Drafted agrees with the lineup recompute

- Entries 237 (227 complete lineups); winning score 79.3; multi-entry contest: True.
- Duplication: 173 distinct lineups; 33.9% of entries sat in a duplicated lineup; max copies 8; the winning lineup had 1 copy. Copies histogram: {1: 150, 2: 10, 3: 5, 4: 5, 7: 2, 8: 1}.
- Salary-usage and stack tables unavailable at this coverage tier (no salary file); re-run at full coverage if the slate salary CSV or the slate's DKEntries upload file (which embeds the salary block) surfaces.
- **Self vs field**: 7 own entries; best rank 134/237 (43.88th pct), median 23.63th pct; best 51.15 pts against a winning 79.3; 1 own lineup(s) duplicated by the field (max 2 copies); fees $0.07, winnings $0.00, net $-0.07. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Yoshinobu Yamamoto 66.67%, Brett Baty 54.86%, Nolan McLean 43.04%, Jorge Polanco 34.6%, Marcus Semien 31.64%.
- Diagnostics: salary join n/a (standings_only); ownership recompute max diff 0.01 pts; parse OK; DK %Drafted agrees.


#### Full-field decomposition — contest 192708096 (field_miner 0.5-review; coverage standings_only; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound; DK %Drafted agrees with the lineup recompute

- Entries 23 (23 complete lineups); winning score 74.3; multi-entry contest: False.
- Duplication: 23 distinct lineups; 0.0% of entries sat in a duplicated lineup; max copies 1; the winning lineup had 1 copy. Copies histogram: {1: 23}.
- Salary-usage and stack tables unavailable at this coverage tier (no salary file); re-run at full coverage if the slate salary CSV or the slate's DKEntries upload file (which embeds the salary block) surfaces.
- **Self vs field**: 1 own entries; best rank 23/23 (4.35th pct), median 4.35th pct; best 30.0 pts against a winning 74.3; 0 own lineup(s) duplicated by the field (max 1 copies); fees $0.25, winnings $0.00, net $-0.25. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Yoshinobu Yamamoto 82.61%, Brett Baty 78.26%, Nolan McLean 65.22%, Jorge Polanco 43.48%, A.J. Ewing 34.78%.
- Diagnostics: salary join n/a (standings_only); ownership recompute max diff 0.0 pts; parse OK; DK %Drafted agrees.


#### Full-field decomposition — contest 192708097 (field_miner 0.5-review; coverage standings_only; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound; DK %Drafted agrees with the lineup recompute

- Entries 59 (59 complete lineups); winning score 75.05; multi-entry contest: False.
- Duplication: 49 distinct lineups; 30.5% of entries sat in a duplicated lineup; max copies 3; the winning lineup had 1 copy. Copies histogram: {1: 41, 2: 6, 3: 2}.
- Salary-usage and stack tables unavailable at this coverage tier (no salary file); re-run at full coverage if the slate salary CSV or the slate's DKEntries upload file (which embeds the salary block) surfaces.
- **Self vs field**: 1 own entries; best rank 54/59 (10.17th pct), median 10.17th pct; best 28.0 pts against a winning 75.05; 0 own lineup(s) duplicated by the field (max 1 copies); fees $0.10, winnings $0.00, net $-0.10. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Brett Baty 77.97%, Yoshinobu Yamamoto 77.97%, Nolan McLean 52.54%, Jorge Polanco 45.76%, Francisco Alvarez 42.37%.
- Diagnostics: salary join n/a (standings_only); ownership recompute max diff 0.01 pts; parse OK; DK %Drafted agrees.


#### Full-field decomposition — contest 192754543 (field_miner 0.5-review; coverage standings_only; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound; DK %Drafted agrees with the lineup recompute

- Entries 142 (142 complete lineups); winning score 78.7; multi-entry contest: True.
- Duplication: 108 distinct lineups; 36.6% of entries sat in a duplicated lineup; max copies 6; the winning lineup had 1 copy. Copies histogram: {1: 90, 2: 8, 3: 7, 4: 1, 5: 1, 6: 1}.
- Salary-usage and stack tables unavailable at this coverage tier (no salary file); re-run at full coverage if the slate salary CSV or the slate's DKEntries upload file (which embeds the salary block) surfaces.
- **Self vs field**: 2 own entries; best rank 73/142 (49.3th pct), median 27.46th pct; best 55.300003 pts against a winning 78.7; 0 own lineup(s) duplicated by the field (max 1 copies); fees $0.50, winnings $0.00, net $-0.50. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Brett Baty 77.46%, Yoshinobu Yamamoto 77.46%, Nolan McLean 54.93%, Jorge Polanco 49.29%, Marcus Semien 29.57%.
- Diagnostics: salary join n/a (standings_only); ownership recompute max diff 0.01 pts; parse OK; DK %Drafted agrees.


---


## A-016 — 2026-07-25 — 4 contests, Showdown (1610_1g_sd)

Salary basis: data/slates/2026-07-25/DKSalaries_showdown_1610_1g.csv (auto-resolved by field_miner, 100% join on every
contest in this group). Coverage tier: full.

Contests 192708059, 192708060, 192708062, 192708063.

Mined 2026-07-28 from a delayed standings pull. Entry fee, payout structure,
paid places, and cash line were never captured from the contest page. Entry fee,
own-entry count, and winnings were backfilled 2026-07-29 from Ben's DraftKings
contest entry history export (Contest_Key join; Entry_Key == standings EntryId),
so the net line below is now populated; payout structure and cash line remain
uncaptured. paid_places is available in that export and is NOT yet written to
the archive: the miner has no --paid-places flag (see 3.13).


#### Full-field decomposition — contest 192708059 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound; DK %Drafted agrees with the lineup recompute

- Entries 182 (181 complete lineups); winning score 134.275; multi-entry contest: True.
- Duplication: 125 distinct lineups; 42.0% of entries sat in a duplicated lineup; max copies 15; the winning lineup had 1 copy. Copies histogram: {1: 105, 2: 8, 3: 4, 4: 4, 5: 2, 7: 1, 15: 1}.
- Salary usage: 40.3% of entries within $100 of the cap. Salary-left bins: {'301-700': 53, '<= 0': 32, '701-1500': 12, '101-300': 33, '1-100': 41, '> 1500': 10}.
- Max-stack histogram: {3: 68, 4: 78, 5: 35}.
- **Self vs field**: 7 own entries; best rank 8/182 (96.15th pct), median 53.3th pct; best 116.275 pts against a winning 134.275; 1 own lineup(s) duplicated by the field (max 15 copies); fees $0.07, winnings $0.00, net $-0.07. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Sonny Gray 75.83%, Dylan Cease 71.98%, Masataka Yoshida 52.2%, Anthony Seigler 51.1%, Nathan Lukes 45.06%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 0.01 pts; parse OK; DK %Drafted agrees.


#### Full-field decomposition — contest 192708060 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound; DK %Drafted agrees with the lineup recompute

- Entries 193 (191 complete lineups); winning score 137.275; multi-entry contest: True.
- Duplication: 139 distinct lineups; 39.3% of entries sat in a duplicated lineup; max copies 15; the winning lineup had 1 copy. Copies histogram: {1: 116, 2: 14, 3: 4, 4: 2, 5: 1, 7: 1, 15: 1}.
- Salary usage: 41.9% of entries within $100 of the cap. Salary-left bins: {'101-300': 35, '<= 0': 40, '301-700': 49, '701-1500': 16, '1-100': 40, '> 1500': 11}.
- Max-stack histogram: {3: 58, 4: 82, 5: 51}.
- **Self vs field**: 7 own entries; best rank 32/193 (83.94th pct), median 35.75th pct; best 97.85 pts against a winning 137.275; 2 own lineup(s) duplicated by the field (max 2 copies); fees $0.07, winnings $0.00, net $-0.07. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Sonny Gray 68.4%, Dylan Cease 63.21%, Masataka Yoshida 47.67%, Anthony Seigler 46.11%, Daulton Varsho 43.53%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 0.01 pts; parse OK; DK %Drafted agrees.


#### Full-field decomposition — contest 192708062 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound; DK %Drafted agrees with the lineup recompute

- Entries 23 (23 complete lineups); winning score 130.28; multi-entry contest: False.
- Duplication: 22 distinct lineups; 8.7% of entries sat in a duplicated lineup; max copies 2; the winning lineup had 1 copy. Copies histogram: {1: 21, 2: 1}.
- Salary usage: 34.8% of entries within $100 of the cap. Salary-left bins: {'<= 0': 3, '301-700': 9, '701-1500': 2, '1-100': 5, '101-300': 4}.
- Max-stack histogram: {3: 11, 4: 7, 5: 5}.
- **Self vs field**: 1 own entries; best rank 19/23 (21.74th pct), median 21.74th pct; best 28.0 pts against a winning 130.28; 0 own lineup(s) duplicated by the field (max 1 copies); fees $0.25, winnings $0.00, net $-0.25. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Sonny Gray 78.26%, Dylan Cease 69.57%, Nathan Lukes 56.52%, Masataka Yoshida 52.17%, Anthony Seigler 47.83%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 0.0 pts; parse OK; DK %Drafted agrees.


#### Full-field decomposition — contest 192708063 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound; DK %Drafted agrees with the lineup recompute

- Entries 45 (45 complete lineups); winning score 130.28; multi-entry contest: False.
- Duplication: 34 distinct lineups; 33.3% of entries sat in a duplicated lineup; max copies 5; the winning lineup had 1 copy. Copies histogram: {1: 30, 3: 2, 4: 1, 5: 1}.
- Salary usage: 42.2% of entries within $100 of the cap. Salary-left bins: {'<= 0': 7, '701-1500': 3, '301-700': 18, '101-300': 5, '1-100': 12}.
- Max-stack histogram: {3: 10, 4: 24, 5: 11}.
- **Self vs field**: 1 own entries; best rank 35/45 (24.44th pct), median 24.44th pct; best 37.25 pts against a winning 130.28; 0 own lineup(s) duplicated by the field (max 1 copies); fees $0.10, winnings $0.00, net $-0.10. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Sonny Gray 77.78%, Dylan Cease 73.33%, Nathan Lukes 62.22%, Masataka Yoshida 51.11%, Anthony Seigler 46.67%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 0.0 pts; parse OK; DK %Drafted agrees.


---


## A-017 — 2026-07-25 — 8 contests, Classic (1805_10g)

Salary basis: runs/20260725T212243Z_c884a8a6/inputs/DKSalaries.csv (auto-resolved by field_miner, 100% join on every
contest in this group). Coverage tier: full.

Contests 192707612, 192710507, 192744091, 192746313, 192747269, 192747982, 192748828, 192753671.

Mined 2026-07-28 from a delayed standings pull. Entry fee, payout structure,
paid places, and cash line were never captured from the contest page. Entry fee,
own-entry count, and winnings were backfilled 2026-07-29 from Ben's DraftKings
contest entry history export (Contest_Key join; Entry_Key == standings EntryId),
so the net line below is now populated; payout structure and cash line remain
uncaptured. paid_places is available in that export and is NOT yet written to
the archive: the miner has no --paid-places flag (see 3.13).


#### Full-field decomposition — contest 192707612 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound (every complete entry carries 10 distinct players); DK's %Drafted table sums 6.9 pts short, which is DK omitting position rows for multi-position players. Lineup-derived ownership is authoritative for this contest.

- Entries 118 (118 complete lineups); winning score 141.6; multi-entry contest: True.
- Duplication: 118 distinct lineups; 0.0% of entries sat in a duplicated lineup; max copies 1; the winning lineup had 1 copy. Copies histogram: {1: 118}.
- Salary usage: 54.2% of entries within $100 of the cap. Salary-left bins: {'301-700': 15, '<= 0': 34, '101-300': 32, '701-1500': 7, '1-100': 30}.
- Max-stack histogram: {1: 1, 2: 9, 3: 13, 4: 21, 5: 74}.
- SP-pair field share (top): Paul Skenes/Yoshinobu Yamamoto 12.7%, Hunter Greene/Yoshinobu Yamamoto 11.9%, Hunter Greene/Paul Skenes 5.9%, Shota Imanaga/Yoshinobu Yamamoto 4.2%.
- **Self vs field**: 3 own entries; best rank 32/118 (73.73th pct), median 67.8th pct; best 92.15 pts against a winning 141.6; 0 own lineup(s) duplicated by the field (max 1 copies); fees $0.75, winnings $0.00, net $-0.75. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Yoshinobu Yamamoto 39.83%, Paul Skenes 36.44%, Hunter Greene 28.81%, Jonah Heim 23.73%, Byron Buxton 22.88%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 3.39 pts; parse OK; DK %Drafted table short 6.9 pts (DK omits multi-position rows; lineup-derived ownership used).


#### Full-field decomposition — contest 192710507 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound; DK %Drafted agrees with the lineup recompute

- Entries 891 (881 complete lineups); winning score 161.5; multi-entry contest: False.
- Duplication: 848 distinct lineups; 5.3% of entries sat in a duplicated lineup; max copies 9; the winning lineup had 1 copy. Copies histogram: {1: 834, 2: 8, 3: 1, 4: 3, 7: 1, 9: 1}.
- Salary usage: 61.2% of entries within $100 of the cap. Salary-left bins: {'301-700': 117, '1-100': 184, '<= 0': 355, '101-300': 193, '701-1500': 28, '> 1500': 4}.
- Max-stack histogram: {1: 30, 2: 221, 3: 178, 4: 153, 5: 299}.
- SP-pair field share (top): Hunter Greene/Yoshinobu Yamamoto 11.9%, Paul Skenes/Yoshinobu Yamamoto 9.1%, Hunter Greene/Paul Skenes 9.0%, Robert Gasser/Yoshinobu Yamamoto 5.7%.
- **Self vs field**: 1 own entries; best rank 345/891 (61.39th pct), median 61.39th pct; best 83.4 pts against a winning 161.5; 0 own lineup(s) duplicated by the field (max 1 copies); fees $1.00, winnings $0.00, net $-1.00. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Hunter Greene 41.53%, Yoshinobu Yamamoto 37.71%, Christian Yelich 30.42%, Brice Turang 29.97%, Paul Skenes 28.51%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 0.11 pts; parse OK; DK %Drafted agrees.


#### Full-field decomposition — contest 192744091 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound (every complete entry carries 10 distinct players); DK's %Drafted table sums 3.5 pts short, which is DK omitting position rows for multi-position players. Lineup-derived ownership is authoritative for this contest.

- Entries 118 (118 complete lineups); winning score 148.0; multi-entry contest: True.
- Duplication: 113 distinct lineups; 7.6% of entries sat in a duplicated lineup; max copies 3; the winning lineup had 1 copy. Copies histogram: {1: 109, 2: 3, 3: 1}.
- Salary usage: 54.2% of entries within $100 of the cap. Salary-left bins: {'701-1500': 10, '301-700': 18, '1-100': 33, '101-300': 26, '<= 0': 31}.
- Max-stack histogram: {1: 3, 2: 20, 3: 8, 4: 21, 5: 66}.
- SP-pair field share (top): Paul Skenes/Yoshinobu Yamamoto 10.2%, Hunter Greene/Yoshinobu Yamamoto 9.3%, Hunter Greene/Shota Imanaga 5.9%, Hunter Greene/Paul Skenes 5.1%.
- **Self vs field**: 3 own entries; best rank 81/118 (32.2th pct), median 27.97th pct; best 66.5 pts against a winning 148.0; 0 own lineup(s) duplicated by the field (max 1 copies); fees $0.30, winnings $0.00, net $-0.30. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Yoshinobu Yamamoto 35.59%, Hunter Greene 32.2%, Paul Skenes 30.51%, Royce Lewis 27.97%, Robert Gasser 22.88%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 2.54 pts; parse OK; DK %Drafted table short 3.5 pts (DK omits multi-position rows; lineup-derived ownership used).


#### Full-field decomposition — contest 192746313 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound (every complete entry carries 10 distinct players); DK's %Drafted table sums 2.0 pts short, which is DK omitting position rows for multi-position players. Lineup-derived ownership is authoritative for this contest.

- Entries 59 (59 complete lineups); winning score 141.0; multi-entry contest: False.
- Duplication: 59 distinct lineups; 0.0% of entries sat in a duplicated lineup; max copies 1; the winning lineup had 1 copy. Copies histogram: {1: 59}.
- Salary usage: 55.9% of entries within $100 of the cap. Salary-left bins: {'301-700': 10, '<= 0': 21, '101-300': 13, '1-100': 12, '> 1500': 1, '701-1500': 2}.
- Max-stack histogram: {1: 2, 2: 7, 3: 6, 4: 15, 5: 29}.
- SP-pair field share (top): Paul Skenes/Yoshinobu Yamamoto 15.3%, Hunter Greene/Yoshinobu Yamamoto 8.5%, Hunter Greene/Nathan Eovaldi 5.1%, Hunter Greene/Sean Burke 5.1%.
- **Self vs field**: 1 own entries; best rank 5/59 (93.22th pct), median 93.22th pct; best 104.6 pts against a winning 141.0; 0 own lineup(s) duplicated by the field (max 1 copies); fees $0.10, winnings $0.00, net $-0.10. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Yoshinobu Yamamoto 40.68%, Hunter Greene 33.9%, Paul Skenes 32.2%, Jonah Heim 27.12%, Byron Buxton 23.73%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 1.7 pts; parse OK; DK %Drafted table short 2.0 pts (DK omits multi-position rows; lineup-derived ownership used).


#### Full-field decomposition — contest 192747269 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound (every complete entry carries 10 distinct players); DK's %Drafted table sums 5.5 pts short, which is DK omitting position rows for multi-position players. Lineup-derived ownership is authoritative for this contest.

- Entries 59 (59 complete lineups); winning score 141.0; multi-entry contest: False.
- Duplication: 59 distinct lineups; 0.0% of entries sat in a duplicated lineup; max copies 1; the winning lineup had 1 copy. Copies histogram: {1: 59}.
- Salary usage: 54.2% of entries within $100 of the cap. Salary-left bins: {'301-700': 8, '<= 0': 20, '1-100': 12, '701-1500': 5, '101-300': 13, '> 1500': 1}.
- Max-stack histogram: {1: 2, 2: 7, 3: 6, 4: 14, 5: 30}.
- SP-pair field share (top): Paul Skenes/Yoshinobu Yamamoto 18.6%, Hunter Greene/Yoshinobu Yamamoto 10.2%, Nathan Eovaldi/Yoshinobu Yamamoto 5.1%, Shota Imanaga/Yoshinobu Yamamoto 5.1%.
- **Self vs field**: 1 own entries; best rank 50/59 (16.95th pct), median 16.95th pct; best 64.15 pts against a winning 141.0; 0 own lineup(s) duplicated by the field (max 1 copies); fees $0.10, winnings $0.00, net $-0.10. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Yoshinobu Yamamoto 49.15%, Jonah Heim 30.51%, Paul Skenes 30.51%, Hunter Greene 23.73%, Robert Gasser 22.03%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 3.39 pts; parse OK; DK %Drafted table short 5.5 pts (DK omits multi-position rows; lineup-derived ownership used).


#### Full-field decomposition — contest 192747982 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound (every complete entry carries 10 distinct players); DK's %Drafted table sums 7.2 pts short, which is DK omitting position rows for multi-position players. Lineup-derived ownership is authoritative for this contest.

- Entries 59 (59 complete lineups); winning score 141.0; multi-entry contest: False.
- Duplication: 59 distinct lineups; 0.0% of entries sat in a duplicated lineup; max copies 1; the winning lineup had 1 copy. Copies histogram: {1: 59}.
- Salary usage: 55.9% of entries within $100 of the cap. Salary-left bins: {'301-700': 11, '<= 0': 19, '101-300': 9, '1-100': 14, '701-1500': 5, '> 1500': 1}.
- Max-stack histogram: {1: 3, 2: 11, 3: 4, 4: 12, 5: 29}.
- SP-pair field share (top): Paul Skenes/Yoshinobu Yamamoto 22.0%, Hunter Greene/Yoshinobu Yamamoto 10.2%, Shota Imanaga/Yoshinobu Yamamoto 5.1%, Hunter Greene/Sean Burke 5.1%.
- **Self vs field**: 1 own entries; best rank 3/59 (96.61th pct), median 96.61th pct; best 108.65 pts against a winning 141.0; 0 own lineup(s) duplicated by the field (max 1 copies); fees $0.10, winnings $0.00, net $-0.10. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Yoshinobu Yamamoto 50.85%, Hunter Greene 37.29%, Paul Skenes 28.81%, Royce Lewis 27.11%, Jonah Heim 25.42%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 1.7 pts; parse OK; DK %Drafted table short 7.2 pts (DK omits multi-position rows; lineup-derived ownership used).


#### Full-field decomposition — contest 192748828 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound (every complete entry carries 10 distinct players); DK's %Drafted table sums 2.1 pts short, which is DK omitting position rows for multi-position players. Lineup-derived ownership is authoritative for this contest.

- Entries 59 (59 complete lineups); winning score 141.0; multi-entry contest: False.
- Duplication: 59 distinct lineups; 0.0% of entries sat in a duplicated lineup; max copies 1; the winning lineup had 1 copy. Copies histogram: {1: 59}.
- Salary usage: 62.7% of entries within $100 of the cap. Salary-left bins: {'301-700': 6, '<= 0': 23, '1-100': 14, '101-300': 12, '701-1500': 3, '> 1500': 1}.
- Max-stack histogram: {1: 2, 2: 9, 3: 6, 4: 16, 5: 26}.
- SP-pair field share (top): Paul Skenes/Yoshinobu Yamamoto 16.9%, Hunter Greene/Yoshinobu Yamamoto 8.5%, Hunter Greene/Sean Burke 6.8%, Shota Imanaga/Yoshinobu Yamamoto 5.1%.
- **Self vs field**: 1 own entries; best rank 19/59 (69.49th pct), median 69.49th pct; best 90.25 pts against a winning 141.0; 0 own lineup(s) duplicated by the field (max 1 copies); fees $0.10, winnings $0.00, net $-0.10. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Yoshinobu Yamamoto 44.07%, Paul Skenes 32.2%, Christian Yelich 28.81%, Hunter Greene 28.81%, Jonah Heim 28.81%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 1.7 pts; parse OK; DK %Drafted table short 2.1 pts (DK omits multi-position rows; lineup-derived ownership used).


#### Full-field decomposition — contest 192753671 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound; DK %Drafted agrees with the lineup recompute

- Entries 23 (23 complete lineups); winning score 141.0; multi-entry contest: False.
- Duplication: 23 distinct lineups; 0.0% of entries sat in a duplicated lineup; max copies 1; the winning lineup had 1 copy. Copies histogram: {1: 23}.
- Salary usage: 52.2% of entries within $100 of the cap. Salary-left bins: {'301-700': 3, '701-1500': 3, '1-100': 5, '<= 0': 7, '101-300': 5}.
- Max-stack histogram: {1: 1, 2: 1, 3: 2, 4: 3, 5: 16}.
- SP-pair field share (top): Hunter Greene/Yoshinobu Yamamoto 17.4%, Sean Burke/Yoshinobu Yamamoto 13.0%, Paul Skenes/Yoshinobu Yamamoto 8.7%, Robert Gasser/Sean Burke 8.7%.
- **Self vs field**: 1 own entries; best rank 3/23 (91.3th pct), median 91.3th pct; best 100.65 pts against a winning 141.0; 0 own lineup(s) duplicated by the field (max 1 copies); fees $0.25, winnings $0.00, net $-0.25. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Yoshinobu Yamamoto 52.17%, Hunter Greene 26.09%, Sean Burke 26.09%, Yordan Alvarez 26.09%, Jonah Heim 26.09%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 0.0 pts; parse OK; DK %Drafted agrees.


---


## A-018 — 2026-07-25 — 11 contests, Classic (1605_4g)

Salary basis: data/slates/2026-07-25/DKSalaries.csv (auto-resolved by field_miner, 100% join on every
contest in this group). Coverage tier: full.

Contests 192707473, 192707481, 192707519, 192707520, 192707521, 192707522, 192707523, 192710479, 192738861, 192740560, 192741308.

Mined 2026-07-28 from a delayed standings pull. Entry fee, payout structure,
paid places, and cash line were never captured from the contest page. Entry fee,
own-entry count, and winnings were backfilled 2026-07-29 from Ben's DraftKings
contest entry history export (Contest_Key join; Entry_Key == standings EntryId),
so the net line below is now populated; payout structure and cash line remain
uncaptured. paid_places is available in that export and is NOT yet written to
the archive: the miner has no --paid-places flag (see 3.13).


#### Full-field decomposition — contest 192707473 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound; DK %Drafted agrees with the lineup recompute

- Entries 67 (67 complete lineups); winning score 172.1; multi-entry contest: True.
- Duplication: 66 distinct lineups; 3.0% of entries sat in a duplicated lineup; max copies 2; the winning lineup had 1 copy. Copies histogram: {1: 65, 2: 1}.
- Salary usage: 43.3% of entries within $100 of the cap. Salary-left bins: {'101-300': 16, '<= 0': 20, '1-100': 9, '701-1500': 6, '301-700': 14, '> 1500': 2}.
- Max-stack histogram: {2: 7, 3: 8, 4: 13, 5: 39}.
- SP-pair field share (top): Dylan Cease/Eury Perez 23.9%, Dylan Cease/Robbie Ray 11.9%, Dylan Cease/Sonny Gray 10.4%, Eury Perez/Foster Griffin 10.4%.
- **Self vs field**: 2 own entries; best rank 36/67 (47.76th pct), median 28.36th pct; best 108.149994 pts against a winning 172.1; 0 own lineup(s) duplicated by the field (max 1 copies); fees $0.50, winnings $0.00, net $-0.50. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Dylan Cease 58.21%, Eury Perez 47.76%, Sonny Gray 35.82%, Dylan Crews 32.84%, Heriberto Hernandez 32.84%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 0.01 pts; parse OK; DK %Drafted agrees.


#### Full-field decomposition — contest 192707481 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound (every complete entry carries 10 distinct players); DK's %Drafted table sums 6.3 pts short, which is DK omitting position rows for multi-position players. Lineup-derived ownership is authoritative for this contest.

- Entries 112 (112 complete lineups); winning score 177.55; multi-entry contest: True.
- Duplication: 112 distinct lineups; 0.0% of entries sat in a duplicated lineup; max copies 1; the winning lineup had 1 copy. Copies histogram: {1: 112}.
- Salary usage: 47.3% of entries within $100 of the cap. Salary-left bins: {'101-300': 30, '301-700': 23, '701-1500': 5, '<= 0': 29, '1-100': 24, '> 1500': 1}.
- Max-stack histogram: {2: 2, 3: 20, 4: 37, 5: 53}.
- SP-pair field share (top): Dylan Cease/Eury Perez 22.3%, Dylan Cease/Robbie Ray 10.7%, Eury Perez/Sonny Gray 10.7%, Eury Perez/Robbie Ray 8.0%.
- **Self vs field**: 3 own entries; best rank 14/112 (88.39th pct), median 48.21th pct; best 133.55 pts against a winning 177.55; 0 own lineup(s) duplicated by the field (max 1 copies); fees $0.75, winnings $0.00, net $-0.75. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Dylan Cease 50.0%, Eury Perez 49.11%, Robbie Ray 33.04%, Heriberto Hernandez 32.14%, James Wood 31.25%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 6.25 pts; parse OK; DK %Drafted table short 6.3 pts (DK omits multi-position rows; lineup-derived ownership used).


#### Full-field decomposition — contest 192707519 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound; DK %Drafted agrees with the lineup recompute

- Entries 59 (59 complete lineups); winning score 177.55; multi-entry contest: False.
- Duplication: 59 distinct lineups; 0.0% of entries sat in a duplicated lineup; max copies 1; the winning lineup had 1 copy. Copies histogram: {1: 59}.
- Salary usage: 40.7% of entries within $100 of the cap. Salary-left bins: {'101-300': 19, '301-700': 11, '1-100': 8, '<= 0': 16, '> 1500': 2, '701-1500': 3}.
- Max-stack histogram: {2: 4, 3: 14, 4: 17, 5: 24}.
- SP-pair field share (top): Dylan Cease/Robbie Ray 16.9%, Dylan Cease/Eury Perez 15.3%, Dylan Cease/Foster Griffin 13.6%, Eury Perez/Sonny Gray 13.6%.
- **Self vs field**: 1 own entries; best rank 44/59 (27.12th pct), median 27.12th pct; best 78.0 pts against a winning 177.55; 0 own lineup(s) duplicated by the field (max 1 copies); fees $0.10, winnings $0.00, net $-0.10. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Dylan Cease 55.93%, Eury Perez 45.76%, Dylan Crews 35.59%, Heriberto Hernandez 33.9%, Foster Griffin 33.9%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 0.01 pts; parse OK; DK %Drafted agrees.


#### Full-field decomposition — contest 192707520 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound (every complete entry carries 10 distinct players); DK's %Drafted table sums 3.5 pts short, which is DK omitting position rows for multi-position players. Lineup-derived ownership is authoritative for this contest.

- Entries 59 (59 complete lineups); winning score 177.55; multi-entry contest: False.
- Duplication: 59 distinct lineups; 0.0% of entries sat in a duplicated lineup; max copies 1; the winning lineup had 1 copy. Copies histogram: {1: 59}.
- Salary usage: 45.8% of entries within $100 of the cap. Salary-left bins: {'101-300': 14, '301-700': 16, '1-100': 10, '<= 0': 17, '701-1500': 1, '> 1500': 1}.
- Max-stack histogram: {2: 6, 3: 16, 4: 14, 5: 23}.
- SP-pair field share (top): Dylan Cease/Eury Perez 18.6%, Dylan Cease/Robbie Ray 16.9%, Dylan Cease/Foster Griffin 13.6%, Eury Perez/Foster Griffin 10.2%.
- **Self vs field**: 1 own entries; best rank 52/59 (13.56th pct), median 13.56th pct; best 71.5 pts against a winning 177.55; 0 own lineup(s) duplicated by the field (max 1 copies); fees $0.10, winnings $0.00, net $-0.10. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Dylan Cease 57.63%, Eury Perez 45.76%, Foster Griffin 35.59%, Dylan Crews 33.9%, Rafael Devers 32.2%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 3.39 pts; parse OK; DK %Drafted table short 3.5 pts (DK omits multi-position rows; lineup-derived ownership used).


#### Full-field decomposition — contest 192707521 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound (every complete entry carries 10 distinct players); DK's %Drafted table sums 10.3 pts short, which is DK omitting position rows for multi-position players. Lineup-derived ownership is authoritative for this contest.

- Entries 59 (59 complete lineups); winning score 150.05; multi-entry contest: False.
- Duplication: 59 distinct lineups; 0.0% of entries sat in a duplicated lineup; max copies 1; the winning lineup had 1 copy. Copies histogram: {1: 59}.
- Salary usage: 44.1% of entries within $100 of the cap. Salary-left bins: {'<= 0': 16, '101-300': 15, '1-100': 10, '301-700': 14, '> 1500': 2, '701-1500': 2}.
- Max-stack histogram: {2: 6, 3: 13, 4: 15, 5: 25}.
- SP-pair field share (top): Dylan Cease/Eury Perez 18.6%, Dylan Cease/Foster Griffin 13.6%, Dylan Cease/Robbie Ray 11.9%, Eury Perez/Foster Griffin 11.9%.
- **Self vs field**: 1 own entries; best rank 43/59 (28.81th pct), median 28.81th pct; best 76.05 pts against a winning 150.05; 0 own lineup(s) duplicated by the field (max 1 copies); fees $0.10, winnings $0.00, net $-0.10. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Dylan Cease 52.54%, Eury Perez 50.85%, Heriberto Hernandez 45.76%, Foster Griffin 37.29%, Dylan Crews 33.9%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 10.17 pts; parse OK; DK %Drafted table short 10.3 pts (DK omits multi-position rows; lineup-derived ownership used).


#### Full-field decomposition — contest 192707522 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound; DK %Drafted agrees with the lineup recompute

- Entries 59 (59 complete lineups); winning score 173.55; multi-entry contest: False.
- Duplication: 59 distinct lineups; 0.0% of entries sat in a duplicated lineup; max copies 1; the winning lineup had 1 copy. Copies histogram: {1: 59}.
- Salary usage: 45.8% of entries within $100 of the cap. Salary-left bins: {'1-100': 13, '101-300': 18, '301-700': 10, '701-1500': 2, '<= 0': 14, '> 1500': 2}.
- Max-stack histogram: {2: 5, 3: 14, 4: 18, 5: 22}.
- SP-pair field share (top): Eury Perez/Sonny Gray 20.3%, Dylan Cease/Eury Perez 16.9%, Dylan Cease/Robbie Ray 11.9%, Dylan Cease/Foster Griffin 11.9%.
- **Self vs field**: 1 own entries; best rank 58/59 (3.39th pct), median 3.39th pct; best 49.45 pts against a winning 173.55; 0 own lineup(s) duplicated by the field (max 1 copies); fees $0.10, winnings $0.00, net $-0.10. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Dylan Cease 52.54%, Eury Perez 50.85%, Dylan Crews 37.29%, Heriberto Hernandez 37.29%, Rafael Devers 35.59%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 0.01 pts; parse OK; DK %Drafted agrees.


#### Full-field decomposition — contest 192707523 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound; DK %Drafted agrees with the lineup recompute

- Entries 118 (118 complete lineups); winning score 186.55; multi-entry contest: True.
- Duplication: 116 distinct lineups; 3.4% of entries sat in a duplicated lineup; max copies 2; the winning lineup had 1 copy. Copies histogram: {1: 114, 2: 2}.
- Salary usage: 38.1% of entries within $100 of the cap. Salary-left bins: {'1-100': 21, '301-700': 17, '701-1500': 16, '101-300': 35, '<= 0': 24, '> 1500': 5}.
- Max-stack histogram: {2: 6, 3: 29, 4: 32, 5: 51}.
- SP-pair field share (top): Dylan Cease/Eury Perez 18.6%, Eury Perez/Sonny Gray 11.9%, Dylan Cease/Robbie Ray 11.0%, Dylan Cease/Foster Griffin 9.3%.
- **Self vs field**: 3 own entries; best rank 74/118 (38.14th pct), median 10.17th pct; best 96.75 pts against a winning 186.55; 0 own lineup(s) duplicated by the field (max 1 copies); fees $0.30, winnings $0.00, net $-0.30. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Dylan Cease 53.39%, Eury Perez 43.22%, Heriberto Hernandez 36.44%, Sonny Gray 32.2%, Foster Griffin 31.36%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 0.01 pts; parse OK; DK %Drafted agrees.


#### Full-field decomposition — contest 192710479 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound; DK %Drafted agrees with the lineup recompute

- Entries 891 (887 complete lineups); winning score 182.55; multi-entry contest: False.
- Duplication: 858 distinct lineups; 5.7% of entries sat in a duplicated lineup; max copies 6; the winning lineup had 1 copy. Copies histogram: {1: 836, 2: 19, 3: 1, 4: 1, 6: 1}.
- Salary usage: 51.5% of entries within $100 of the cap. Salary-left bins: {'1-100': 177, '301-700': 146, '<= 0': 280, '101-300': 209, '701-1500': 54, '> 1500': 21}.
- Max-stack histogram: {2: 134, 3: 264, 4: 220, 5: 269}.
- SP-pair field share (top): Dylan Cease/Eury Perez 18.4%, Eury Perez/Sonny Gray 13.6%, Dylan Cease/Robbie Ray 9.8%, Eury Perez/Foster Griffin 8.7%.
- **Self vs field**: 1 own entries; best rank 769/891 (13.8th pct), median 13.8th pct; best 58.9 pts against a winning 182.55; 0 own lineup(s) duplicated by the field (max 1 copies); fees $1.00, winnings $0.00, net $-1.00. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Eury Perez 50.28%, Dylan Cease 44.0%, Sonny Gray 37.6%, Heriberto Hernandez 35.35%, Dylan Crews 31.43%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 0.01 pts; parse OK; DK %Drafted agrees.


#### Full-field decomposition — contest 192738861 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound; DK %Drafted agrees with the lineup recompute

- Entries 23 (23 complete lineups); winning score 177.55; multi-entry contest: False.
- Duplication: 23 distinct lineups; 0.0% of entries sat in a duplicated lineup; max copies 1; the winning lineup had 1 copy. Copies histogram: {1: 23}.
- Salary usage: 26.1% of entries within $100 of the cap. Salary-left bins: {'101-300': 8, '1-100': 1, '<= 0': 5, '301-700': 7, '> 1500': 1, '701-1500': 1}.
- Max-stack histogram: {3: 5, 4: 6, 5: 12}.
- SP-pair field share (top): Dylan Cease/Robbie Ray 26.1%, Dylan Cease/Foster Griffin 17.4%, Eury Perez/Sonny Gray 13.0%, Eury Perez/Foster Griffin 8.7%.
- **Self vs field**: 1 own entries; best rank 11/23 (56.52th pct), median 56.52th pct; best 100.05 pts against a winning 177.55; 0 own lineup(s) duplicated by the field (max 1 copies); fees $0.25, winnings $0.00, net $-0.25. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Dylan Cease 60.87%, Robbie Ray 39.13%, Eury Perez 34.78%, Foster Griffin 30.43%, Mike Trout 30.43%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 0.0 pts; parse OK; DK %Drafted agrees.


#### Full-field decomposition — contest 192740560 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound; DK %Drafted agrees with the lineup recompute

- Entries 23 (23 complete lineups); winning score 177.55; multi-entry contest: False.
- Duplication: 23 distinct lineups; 0.0% of entries sat in a duplicated lineup; max copies 1; the winning lineup had 1 copy. Copies histogram: {1: 23}.
- Salary usage: 43.5% of entries within $100 of the cap. Salary-left bins: {'101-300': 5, '1-100': 4, '301-700': 6, '701-1500': 2, '<= 0': 6}.
- Max-stack histogram: {2: 1, 3: 4, 4: 8, 5: 10}.
- SP-pair field share (top): Dylan Cease/Robbie Ray 21.7%, Eury Perez/Foster Griffin 17.4%, Eury Perez/Robbie Ray 13.0%, Dylan Cease/Foster Griffin 8.7%.
- **Self vs field**: 1 own entries; best rank 23/23 (4.35th pct), median 4.35th pct; best 33.6 pts against a winning 177.55; 0 own lineup(s) duplicated by the field (max 1 copies); fees $0.25, winnings $0.00, net $-0.25. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Dylan Cease 52.17%, Dylan Crews 47.83%, Eury Perez 43.48%, Foster Griffin 34.78%, Robbie Ray 34.78%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 0.0 pts; parse OK; DK %Drafted agrees.


#### Full-field decomposition — contest 192741308 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound; DK %Drafted agrees with the lineup recompute

- Entries 23 (23 complete lineups); winning score 177.55; multi-entry contest: False.
- Duplication: 23 distinct lineups; 0.0% of entries sat in a duplicated lineup; max copies 1; the winning lineup had 1 copy. Copies histogram: {1: 23}.
- Salary usage: 21.7% of entries within $100 of the cap. Salary-left bins: {'101-300': 10, '701-1500': 4, '<= 0': 5, '301-700': 4}.
- Max-stack histogram: {3: 5, 4: 5, 5: 13}.
- SP-pair field share (top): Dylan Cease/Robbie Ray 21.7%, Eury Perez/Sonny Gray 21.7%, Eury Perez/Foster Griffin 13.0%, Dylan Cease/Mitch Bratt 8.7%.
- **Self vs field**: 1 own entries; best rank 4/23 (86.96th pct), median 86.96th pct; best 110.9 pts against a winning 177.55; 0 own lineup(s) duplicated by the field (max 1 copies); fees $0.25, winnings $0.00, net $-0.25. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Dylan Cease 52.17%, Eury Perez 47.83%, Dylan Crews 39.13%, Robbie Ray 34.78%, Zach Neto 34.78%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 0.0 pts; parse OK; DK %Drafted agrees.


---


## A-019 — 2026-07-21 — 1 contest, Classic

Salary basis: data/slates/2026-07-21/DKSalaries.csv (auto-resolved by field_miner, 100% join on every
contest in this group). Coverage tier: full.

Contests 192529275.

Mined 2026-07-28 from a delayed standings pull. Entry fee, payout structure,
paid places, and cash line were never captured from the contest page. Entry fee,
own-entry count, and winnings were backfilled 2026-07-29 from Ben's DraftKings
contest entry history export (Contest_Key join; Entry_Key == standings EntryId),
so the net line below is now populated; payout structure and cash line remain
uncaptured. paid_places is available in that export and is NOT yet written to
the archive: the miner has no --paid-places flag (see 3.13).


#### Full-field decomposition — contest 192529275 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound; DK %Drafted agrees with the lineup recompute

- Entries 4670 (4668 complete lineups); winning score 214.9; multi-entry contest: True.
- Duplication: 4461 distinct lineups; 7.2% of entries sat in a duplicated lineup; max copies 8; the winning lineup had 1 copy. Copies histogram: {1: 4331, 2: 87, 3: 26, 4: 8, 5: 4, 6: 3, 7: 1, 8: 1}.
- Salary usage: 54.7% of entries within $100 of the cap. Salary-left bins: {'301-700': 809, '<= 0': 1577, '1-100': 975, '101-300': 959, '701-1500': 297, '> 1500': 51}.
- Max-stack histogram: {1: 45, 2: 276, 3: 284, 4: 756, 5: 3307}.
- SP-pair field share (top): Kumar Rocker/Luis Castillo 8.4%, David Peterson/Luis Castillo 6.4%, Framber Valdez/Luis Castillo 4.2%, Brandon Sproat/Luis Castillo 4.1%.
- **Self vs field**: 4 own entries; best rank 431/4670 (90.79th pct), median 81.81th pct; best 139.1 pts against a winning 214.9; 0 own lineup(s) duplicated by the field (max 1 copies); fees $8.00, winnings $7.00, net $-1.00. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Luis Castillo 39.51%, James Wood 32.51%, Daylen Lile 25.87%, CJ Abrams 24.22%, Kumar Rocker 22.91%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 0.02 pts; parse OK; DK %Drafted agrees.


---


## A-020 — 2026-07-19 — 2 contests, Classic

Salary basis: none. The resolver declined rather than join against another
slate, so this group is the **standings_only** degraded tier: ownership,
duplication, chalk, and SP pairs are present; salary and stack tables are not.

Contests 192442890, 192500593.

Mined 2026-07-28 from a delayed standings pull. Entry fee, payout structure,
paid places, and cash line were never captured from the contest page. Entry fee,
own-entry count, and winnings were backfilled 2026-07-29 from Ben's DraftKings
contest entry history export (Contest_Key join; Entry_Key == standings EntryId),
so the net line below is now populated; payout structure and cash line remain
uncaptured. paid_places is available in that export and is NOT yet written to
the archive: the miner has no --paid-places flag (see 3.13).


#### Full-field decomposition — contest 192442890 (field_miner 0.5-review; coverage standings_only; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound; DK %Drafted agrees with the lineup recompute

- Entries 297 (285 complete lineups); winning score 156.85; multi-entry contest: True.
- Duplication: 273 distinct lineups; 6.3% of entries sat in a duplicated lineup; max copies 8; the winning lineup had 1 copy. Copies histogram: {1: 267, 2: 5, 8: 1}.
- Salary-usage and stack tables unavailable at this coverage tier (no salary file); re-run at full coverage if the slate salary CSV or the slate's DKEntries upload file (which embeds the salary block) surfaces.
- SP-pair field share (top): Casey Mize/Logan Gilbert 23.9%, Foster Griffin/Logan Gilbert 14.7%, Logan Gilbert/Robbie Ray 10.5%, Casey Mize/Robbie Ray 7.4%.
- **Self vs field**: 8 own entries; best rank 13/297 (95.96th pct), median 49.49th pct; best 139.85 pts against a winning 156.85; 0 own lineup(s) duplicated by the field (max 1 copies); fees $0.80, winnings $0.00, net $-0.80. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Logan Gilbert 60.94%, Casey Mize 43.1%, Riley Greene 35.02%, James Wood 34.34%, Kevin McGonigle 28.96%.
- Diagnostics: salary join n/a (standings_only); ownership recompute max diff 0.33 pts; parse OK; DK %Drafted agrees.


#### Full-field decomposition — contest 192500593 (field_miner 0.5-review; coverage standings_only; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound; DK %Drafted agrees with the lineup recompute

- Entries 35 (35 complete lineups); winning score 141.85; multi-entry contest: False.
- Duplication: 35 distinct lineups; 0.0% of entries sat in a duplicated lineup; max copies 1; the winning lineup had 1 copy. Copies histogram: {1: 35}.
- Salary-usage and stack tables unavailable at this coverage tier (no salary file); re-run at full coverage if the slate salary CSV or the slate's DKEntries upload file (which embeds the salary block) surfaces.
- SP-pair field share (top): Casey Mize/Logan Gilbert 31.4%, Logan Gilbert/Robbie Ray 22.9%, Foster Griffin/Logan Gilbert 17.1%, Casey Mize/Foster Griffin 8.6%.
- **Self vs field**: 1 own entries; best rank 25/35 (31.43th pct), median 31.43th pct; best 97.1 pts against a winning 141.85; 0 own lineup(s) duplicated by the field (max 1 copies); fees $1.00, winnings $0.00, net $-1.00. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Logan Gilbert 80.0%, Curtis Mead 45.71%, Riley Greene 45.71%, Andres Chaparro 45.71%, Casey Mize 42.86%.
- Diagnostics: salary join n/a (standings_only); ownership recompute max diff 0.0 pts; parse OK; DK %Drafted agrees.


---


## A-021 — 2026-07-19 — 3 contests, Classic

Salary basis: data/slates/2026-07-19/DKSalaries.csv (auto-resolved by field_miner, 100% join on every
contest in this group). Coverage tier: full.

Contests 192464310, 192464354, 192464355.

Mined 2026-07-28 from a delayed standings pull. Entry fee, payout structure,
paid places, and cash line were never captured from the contest page. Entry fee,
own-entry count, and winnings were backfilled 2026-07-29 from Ben's DraftKings
contest entry history export (Contest_Key join; Entry_Key == standings EntryId),
so the net line below is now populated; payout structure and cash line remain
uncaptured. paid_places is available in that export and is NOT yet written to
the archive: the miner has no --paid-places flag (see 3.13).


#### Full-field decomposition — contest 192464310 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound; DK %Drafted agrees with the lineup recompute

- Entries 1486 (1470 complete lineups); winning score 151.55; multi-entry contest: True.
- Duplication: 1147 distinct lineups; 33.3% of entries sat in a duplicated lineup; max copies 18; the winning lineup had 1 copy. Copies histogram: {1: 981, 2: 102, 3: 20, 4: 22, 5: 14, 6: 3, 7: 2, 8: 1, 9: 1, 18: 1}.
- Salary usage: 42.2% of entries within $100 of the cap. Salary-left bins: {'301-700': 319, '101-300': 328, '<= 0': 374, '1-100': 246, '701-1500': 163, '> 1500': 40}.
- Max-stack histogram: {2: 10, 3: 220, 4: 484, 5: 756}.
- SP-pair field share (top): Sean Burke/Yoshinobu Yamamoto 22.7%, Cam Schlittler/Yoshinobu Yamamoto 22.5%, Cam Schlittler/Sean Burke 21.0%, Trey Yesavage/Yoshinobu Yamamoto 14.9%.
- **Self vs field**: 1 own entries; best rank 1410/1486 (5.18th pct), median 5.18th pct; best 60.85 pts against a winning 151.55; 1 own lineup(s) duplicated by the field (max 2 copies); fees $1.00, winnings $0.00, net $-1.00. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Ernie Clement 62.38%, Yoshinobu Yamamoto 59.42%, Cam Schlittler 53.16%, Sean Burke 51.82%, Colson Montgomery 44.41%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 0.01 pts; parse OK; DK %Drafted agrees.


#### Full-field decomposition — contest 192464354 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound; DK %Drafted agrees with the lineup recompute

- Entries 223 (220 complete lineups); winning score 134.55; multi-entry contest: True.
- Duplication: 207 distinct lineups; 9.5% of entries sat in a duplicated lineup; max copies 7; the winning lineup had 1 copy. Copies histogram: {1: 199, 2: 7, 7: 1}.
- Salary usage: 41.4% of entries within $100 of the cap. Salary-left bins: {'1-100': 36, '<= 0': 55, '701-1500': 25, '301-700': 43, '101-300': 54, '> 1500': 7}.
- Max-stack histogram: {2: 2, 3: 56, 4: 57, 5: 105}.
- SP-pair field share (top): Cam Schlittler/Yoshinobu Yamamoto 24.5%, Sean Burke/Yoshinobu Yamamoto 23.2%, Cam Schlittler/Sean Burke 19.1%, Trey Yesavage/Yoshinobu Yamamoto 13.6%.
- **Self vs field**: 7 own entries; best rank 3/223 (99.1th pct), median 50.67th pct; best 129.55 pts against a winning 134.55; 3 own lineup(s) duplicated by the field (max 2 copies); fees $0.07, winnings $0.00, net $-0.07. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Yoshinobu Yamamoto 60.54%, Ernie Clement 57.4%, Sean Burke 52.47%, Cam Schlittler 51.57%, Sam Antonacci 43.05%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 0.01 pts; parse OK; DK %Drafted agrees.


#### Full-field decomposition — contest 192464355 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound; DK %Drafted agrees with the lineup recompute

- Entries 237 (233 complete lineups); winning score 134.55; multi-entry contest: True.
- Duplication: 216 distinct lineups; 12.9% of entries sat in a duplicated lineup; max copies 4; the winning lineup had 1 copy. Copies histogram: {1: 203, 2: 11, 4: 2}.
- Salary usage: 44.2% of entries within $100 of the cap. Salary-left bins: {'1-100': 43, '<= 0': 60, '301-700': 42, '101-300': 57, '701-1500': 23, '> 1500': 8}.
- Max-stack histogram: {2: 1, 3: 66, 4: 69, 5: 97}.
- SP-pair field share (top): Cam Schlittler/Yoshinobu Yamamoto 26.2%, Sean Burke/Yoshinobu Yamamoto 24.9%, Trey Yesavage/Yoshinobu Yamamoto 18.0%, Cam Schlittler/Sean Burke 12.4%.
- **Self vs field**: 7 own entries; best rank 3/237 (99.16th pct), median 44.3th pct; best 129.55 pts against a winning 134.55; 2 own lineup(s) duplicated by the field (max 2 copies); fees $0.07, winnings $0.00, net $-0.07. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Yoshinobu Yamamoto 67.93%, Ernie Clement 64.98%, Sean Burke 46.84%, Cam Schlittler 45.99%, Sam Antonacci 40.51%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 0.0 pts; parse OK; DK %Drafted agrees.


---


## A-022 — 2026-07-19 — 3 contests, Classic

Salary basis: data/slates/2026-07-19/DKSalaries_live.csv (auto-resolved by field_miner, 100% join on every
contest in this group). Coverage tier: full.

Contests 192443599, 192443606, 192454586.

Mined 2026-07-28 from a delayed standings pull. Entry fee, payout structure,
paid places, and cash line were never captured from the contest page. Entry fee,
own-entry count, and winnings were backfilled 2026-07-29 from Ben's DraftKings
contest entry history export (Contest_Key join; Entry_Key == standings EntryId),
so the net line below is now populated; payout structure and cash line remain
uncaptured. paid_places is available in that export and is NOT yet written to
the archive: the miner has no --paid-places flag (see 3.13).


#### Full-field decomposition — contest 192443599 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound; DK %Drafted agrees with the lineup recompute

- Entries 178 (178 complete lineups); winning score 235.85; multi-entry contest: True.
- Duplication: 177 distinct lineups; 1.1% of entries sat in a duplicated lineup; max copies 2; the winning lineup had 1 copy. Copies histogram: {1: 176, 2: 1}.
- Salary usage: 31.5% of entries within $100 of the cap. Salary-left bins: {'<= 0': 37, '> 1500': 10, '101-300': 43, '301-700': 42, '1-100': 19, '701-1500': 27}.
- Max-stack histogram: {1: 2, 2: 14, 3: 20, 4: 43, 5: 99}.
- SP-pair field share (top): Hunter Brown/Paul Skenes 9.6%, Paul Skenes/Shota Imanaga 7.9%, Joey Cantillo/Paul Skenes 6.7%, Nathan Eovaldi/Paul Skenes 6.7%.
- **Self vs field**: 5 own entries; best rank 2/178 (99.44th pct), median 73.6th pct; best 229.45 pts against a winning 235.85; 0 own lineup(s) duplicated by the field (max 1 copies); fees $0.50, winnings $0.00, net $-0.50. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Paul Skenes 45.51%, Carter Jensen 27.53%, Jac Caglianone 27.52%, Hunter Brown 24.72%, Fernando Tatis Jr. 24.16%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 1.13 pts; parse OK; DK %Drafted agrees.


#### Full-field decomposition — contest 192443606 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound; DK %Drafted agrees with the lineup recompute

- Entries 297 (296 complete lineups); winning score 255.25; multi-entry contest: True.
- Duplication: 293 distinct lineups; 2.0% of entries sat in a duplicated lineup; max copies 2; the winning lineup had 1 copy. Copies histogram: {1: 290, 2: 3}.
- Salary usage: 45.9% of entries within $100 of the cap. Salary-left bins: {'101-300': 65, '<= 0': 80, '1-100': 56, '301-700': 63, '701-1500': 22, '> 1500': 10}.
- Max-stack histogram: {1: 2, 2: 38, 3: 45, 4: 60, 5: 151}.
- SP-pair field share (top): Hunter Brown/Paul Skenes 11.1%, Paul Skenes/Shota Imanaga 7.4%, Nathan Eovaldi/Paul Skenes 7.4%, Nolan McLean/Paul Skenes 6.4%.
- **Self vs field**: 8 own entries; best rank 4/297 (98.99th pct), median 63.8th pct; best 229.45 pts against a winning 255.25; 0 own lineup(s) duplicated by the field (max 1 copies); fees $0.80, winnings $0.00, net $-0.80. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Paul Skenes 47.81%, Carter Jensen 37.37%, Jac Caglianone 26.26%, Fernando Tatis Jr. 24.92%, Nathan Eovaldi 23.91%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 0.01 pts; parse OK; DK %Drafted agrees.


#### Full-field decomposition — contest 192454586 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound; DK %Drafted agrees with the lineup recompute

- Entries 1189 (1183 complete lineups); winning score 255.25; multi-entry contest: False.
- Duplication: 1132 distinct lineups; 6.3% of entries sat in a duplicated lineup; max copies 12; the winning lineup had 3 copies. Copies histogram: {1: 1108, 2: 13, 3: 6, 4: 1, 5: 3, 12: 1}.
- Salary usage: 50.4% of entries within $100 of the cap. Salary-left bins: {'101-300': 275, '1-100': 226, '<= 0': 370, '301-700': 201, '> 1500': 34, '701-1500': 77}.
- Max-stack histogram: {1: 32, 2: 287, 3: 295, 4: 220, 5: 349}.
- SP-pair field share (top): Paul Skenes/Shota Imanaga 12.0%, Hunter Brown/Paul Skenes 11.6%, Paul Skenes/Sonny Gray 5.9%, Nolan McLean/Paul Skenes 5.1%.
- **Self vs field**: 1 own entries; best rank 8/1189 (99.41th pct), median 99.41th pct; best 229.45 pts against a winning 255.25; 0 own lineup(s) duplicated by the field (max 1 copies); fees $1.00, winnings $20.00, net $19.00. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Paul Skenes 51.64%, Carter Jensen 33.05%, Francisco Lindor 25.15%, Jac Caglianone 23.89%, Yordan Alvarez 23.21%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 0.09 pts; parse OK; DK %Drafted agrees.


---


## A-023 — 2026-07-18 — 2 contests, Showdown

Salary basis: data/slates/2026-07-18/DKSalaries.csv (auto-resolved by field_miner, 100% join on every
contest in this group). Coverage tier: full.

Contests 192413131, 192413132.

Mined 2026-07-28 from a delayed standings pull. Entry fee, payout structure,
paid places, and cash line were never captured from the contest page. Entry fee,
own-entry count, and winnings were backfilled 2026-07-29 from Ben's DraftKings
contest entry history export (Contest_Key join; Entry_Key == standings EntryId),
so the net line below is now populated; payout structure and cash line remain
uncaptured. paid_places is available in that export and is NOT yet written to
the archive: the miner has no --paid-places flag (see 3.13).


#### Full-field decomposition — contest 192413131 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound; DK %Drafted agrees with the lineup recompute

- Entries 222 (220 complete lineups); winning score 100.1; multi-entry contest: True.
- Duplication: 185 distinct lineups; 26.8% of entries sat in a duplicated lineup; max copies 5; the winning lineup had 1 copy. Copies histogram: {1: 161, 2: 17, 3: 4, 4: 2, 5: 1}.
- Salary usage: 31.4% of entries within $100 of the cap. Salary-left bins: {'101-300': 61, '<= 0': 57, '1-100': 12, '301-700': 54, '701-1500': 26, '> 1500': 10}.
- Max-stack histogram: {3: 65, 4: 76, 5: 79}.
- **Self vs field**: 7 own entries; best rank 30/222 (86.94th pct), median 33.33th pct; best 70.0 pts against a winning 100.1; 1 own lineup(s) duplicated by the field (max 2 copies); fees $0.07, winnings $0.00, net $-0.07. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Taj Bradley 60.36%, Matthew Boyd 53.15%, Josh Bell 49.55%, Austin Martin 42.34%, Ryan Kreidler 40.09%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 0.01 pts; parse OK; DK %Drafted agrees.


#### Full-field decomposition — contest 192413132 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound; DK %Drafted agrees with the lineup recompute

- Entries 237 (233 complete lineups); winning score 86.65; multi-entry contest: True.
- Duplication: 200 distinct lineups; 23.6% of entries sat in a duplicated lineup; max copies 7; the winning lineup had 1 copy. Copies histogram: {1: 178, 2: 17, 3: 2, 4: 2, 7: 1}.
- Salary usage: 41.6% of entries within $100 of the cap. Salary-left bins: {'<= 0': 74, '1-100': 23, '701-1500': 25, '301-700': 54, '101-300': 47, '> 1500': 10}.
- Max-stack histogram: {3: 59, 4: 86, 5: 88}.
- **Self vs field**: 7 own entries; best rank 20/237 (91.98th pct), median 48.52th pct; best 71.65 pts against a winning 86.65; 0 own lineup(s) duplicated by the field (max 1 copies); fees $0.07, winnings $0.00, net $-0.07. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Taj Bradley 58.65%, Matthew Boyd 48.94%, Josh Bell 43.46%, Austin Martin 41.35%, Ryan Kreidler 35.02%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 0.01 pts; parse OK; DK %Drafted agrees.


---


## A-024 — 2026-07-17 — 2 contests, Showdown

Salary basis: none. The resolver declined rather than join against another
slate, so this group is the **standings_only** degraded tier: ownership,
duplication, chalk, and SP pairs are present; salary and stack tables are not.

Contests 192344519, 192344520.

Mined 2026-07-28 from a delayed standings pull. Entry fee, payout structure,
paid places, and cash line were never captured from the contest page. Entry fee,
own-entry count, and winnings were backfilled 2026-07-29 from Ben's DraftKings
contest entry history export (Contest_Key join; Entry_Key == standings EntryId),
so the net line below is now populated; payout structure and cash line remain
uncaptured. paid_places is available in that export and is NOT yet written to
the archive: the miner has no --paid-places flag (see 3.13).


#### Full-field decomposition — contest 192344519 (field_miner 0.5-review; coverage standings_only; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound; DK %Drafted agrees with the lineup recompute

- Entries 237 (226 complete lineups); winning score 95.125; multi-entry contest: True.
- Duplication: 166 distinct lineups; 39.4% of entries sat in a duplicated lineup; max copies 13; the winning lineup had 1 copy. Copies histogram: {1: 137, 2: 21, 3: 3, 4: 1, 6: 1, 7: 1, 8: 1, 13: 1}.
- Salary-usage and stack tables unavailable at this coverage tier (no salary file); re-run at full coverage if the slate salary CSV or the slate's DKEntries upload file (which embeds the salary block) surfaces.
- **Self vs field**: 7 own entries; best rank 89/237 (62.87th pct), median 25.32th pct; best 58.25 pts against a winning 95.125; 2 own lineup(s) duplicated by the field (max 3 copies); fees $0.07, winnings $0.00, net $-0.07. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Bryce Miller 66.24%, J.P. Crawford 57.8%, Landen Roupp 51.9%, Cole Young 46.83%, Drew Cavanaugh 40.93%.
- Diagnostics: salary join n/a (standings_only); ownership recompute max diff 0.01 pts; parse OK; DK %Drafted agrees.


#### Full-field decomposition — contest 192344520 (field_miner 0.5-review; coverage standings_only; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound; DK %Drafted agrees with the lineup recompute

- Entries 237 (221 complete lineups); winning score 95.125; multi-entry contest: True.
- Duplication: 169 distinct lineups; 33.5% of entries sat in a duplicated lineup; max copies 9; the winning lineup had 1 copy. Copies histogram: {1: 147, 2: 14, 3: 3, 6: 1, 7: 2, 8: 1, 9: 1}.
- Salary-usage and stack tables unavailable at this coverage tier (no salary file); re-run at full coverage if the slate salary CSV or the slate's DKEntries upload file (which embeds the salary block) surfaces.
- **Self vs field**: 7 own entries; best rank 7/237 (97.47th pct), median 38.4th pct; best 84.75 pts against a winning 95.125; 0 own lineup(s) duplicated by the field (max 1 copies); fees $0.07, winnings $0.00, net $-0.07. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Bryce Miller 60.76%, J.P. Crawford 54.0%, Landen Roupp 46.84%, Cole Young 42.19%, Victor Robles 38.82%.
- Diagnostics: salary join n/a (standings_only); ownership recompute max diff 0.01 pts; parse OK; DK %Drafted agrees.


---


## A-025 — 2026-07-17 — 3 contests, Classic

Salary basis: none. The resolver declined rather than join against another
slate, so this group is the **standings_only** degraded tier: ownership,
duplication, chalk, and SP pairs are present; salary and stack tables are not.

Contests 192344257, 192344259, 192369212.

Mined 2026-07-28 from a delayed standings pull. Entry fee, payout structure,
paid places, and cash line were never captured from the contest page. Entry fee,
own-entry count, and winnings were backfilled 2026-07-29 from Ben's DraftKings
contest entry history export (Contest_Key join; Entry_Key == standings EntryId),
so the net line below is now populated; payout structure and cash line remain
uncaptured. paid_places is available in that export and is NOT yet written to
the archive: the miner has no --paid-places flag (see 3.13).


#### Full-field decomposition — contest 192344257 (field_miner 0.5-review; coverage standings_only; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound; DK %Drafted agrees with the lineup recompute

- Entries 118 (118 complete lineups); winning score 244.05; multi-entry contest: True.
- Duplication: 118 distinct lineups; 0.0% of entries sat in a duplicated lineup; max copies 1; the winning lineup had 1 copy. Copies histogram: {1: 118}.
- Salary-usage and stack tables unavailable at this coverage tier (no salary file); re-run at full coverage if the slate salary CSV or the slate's DKEntries upload file (which embeds the salary block) surfaces.
- SP-pair field share (top): Bryce Miller/Troy Melton 26.3%, Bryce Miller/Reid Detmers 10.2%, Reid Detmers/Troy Melton 8.5%, Cade Cavalli/Troy Melton 6.8%.
- **Self vs field**: 3 own entries; best rank 22/118 (82.2th pct), median 76.27th pct; best 159.75 pts against a winning 244.05; 0 own lineup(s) duplicated by the field (max 1 copies); fees $0.75, winnings $0.00, net $-0.75. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Troy Melton 53.39%, Bryce Miller 50.0%, James Wood 45.76%, Alec Burleson 35.59%, Reid Detmers 35.59%.
- Diagnostics: salary join n/a (standings_only); ownership recompute max diff 0.01 pts; parse OK; DK %Drafted agrees.


#### Full-field decomposition — contest 192344259 (field_miner 0.5-review; coverage standings_only; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound; DK %Drafted agrees with the lineup recompute

- Entries 101 (101 complete lineups); winning score 244.05; multi-entry contest: True.
- Duplication: 98 distinct lineups; 5.0% of entries sat in a duplicated lineup; max copies 3; the winning lineup had 3 copies. Copies histogram: {1: 96, 2: 1, 3: 1}.
- Salary-usage and stack tables unavailable at this coverage tier (no salary file); re-run at full coverage if the slate salary CSV or the slate's DKEntries upload file (which embeds the salary block) surfaces.
- SP-pair field share (top): Bryce Miller/Troy Melton 17.8%, Reid Detmers/Troy Melton 16.8%, Bryce Miller/Reid Detmers 10.9%, Landen Roupp/Reid Detmers 6.9%.
- **Self vs field**: 4 own entries; best rank 28/101 (73.27th pct), median 60.4th pct; best 156.85 pts against a winning 244.05; 0 own lineup(s) duplicated by the field (max 1 copies); fees $0.40, winnings $0.00, net $-0.40. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Troy Melton 52.48%, James Wood 44.55%, Bryce Miller 44.55%, Alec Burleson 40.59%, Reid Detmers 38.61%.
- Diagnostics: salary join n/a (standings_only); ownership recompute max diff 0.99 pts; parse OK; DK %Drafted agrees.


#### Full-field decomposition — contest 192369212 (field_miner 0.5-review; coverage standings_only; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound; DK %Drafted agrees with the lineup recompute

- Entries 29 (29 complete lineups); winning score 204.05; multi-entry contest: False.
- Duplication: 29 distinct lineups; 0.0% of entries sat in a duplicated lineup; max copies 1; the winning lineup had 1 copy. Copies histogram: {1: 29}.
- Salary-usage and stack tables unavailable at this coverage tier (no salary file); re-run at full coverage if the slate salary CSV or the slate's DKEntries upload file (which embeds the salary block) surfaces.
- SP-pair field share (top): Bryce Miller/Troy Melton 31.0%, Reid Detmers/Troy Melton 10.3%, Bryce Miller/Reid Detmers 10.3%, Cade Cavalli/Reid Detmers 10.3%.
- **Self vs field**: 1 own entries; best rank 28/29 (6.9th pct), median 6.9th pct; best 79.7 pts against a winning 204.05; 0 own lineup(s) duplicated by the field (max 1 copies); fees $1.00, winnings $0.00, net $-1.00. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): James Wood 55.17%, Bryce Miller 51.72%, Troy Melton 51.72%, Reid Detmers 44.83%, Curtis Mead 37.93%.
- Diagnostics: salary join n/a (standings_only); ownership recompute max diff 0.0 pts; parse OK; DK %Drafted agrees.


---


## A-026 — 2026-06-03 — 2 contests, Classic (1840_2g)

Salary basis: data/archive/2026-06-03/DKSalaries_2026-06-03.csv (auto-resolved by field_miner, 100% join on every
contest in this group). Coverage tier: full.

Contests 191020573, 191020574.

Mined 2026-07-28 from a delayed standings pull. Entry fee, payout structure,
paid places, and cash line were never captured from the contest page. Entry fee,
own-entry count, and winnings were backfilled 2026-07-29 from Ben's DraftKings
contest entry history export (Contest_Key join; Entry_Key == standings EntryId),
so the net line below is now populated; payout structure and cash line remain
uncaptured. paid_places is available in that export and is NOT yet written to
the archive: the miner has no --paid-places flag (see 3.13).


#### Full-field decomposition — contest 191020573 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound; DK %Drafted agrees with the lineup recompute

- Entries 237 (235 complete lineups); winning score 154.65; multi-entry contest: True.
- Duplication: 195 distinct lineups; 25.5% of entries sat in a duplicated lineup; max copies 8; the winning lineup had 1 copy. Copies histogram: {1: 175, 2: 12, 3: 4, 4: 1, 5: 1, 7: 1, 8: 1}.
- Salary usage: 37.9% of entries within $100 of the cap. Salary-left bins: {'701-1500': 29, '<= 0': 48, '101-300': 42, '301-700': 50, '1-100': 41, '> 1500': 25}.
- Max-stack histogram: {2: 3, 3: 39, 4: 90, 5: 103}.
- SP-pair field share (top): Cristopher Sanchez/Payton Tolle 63.4%, Chris Bassitt/Cristopher Sanchez 19.6%, Payton Tolle/Walker Buehler 5.1%, Cristopher Sanchez/Walker Buehler 4.7%.
- **Self vs field**: 7 own entries; best rank 11/237 (95.78th pct), median 59.49th pct; best 140.85 pts against a winning 154.65; 1 own lineup(s) duplicated by the field (max 2 copies); fees $0.07, winnings $0.00, net $-0.07. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Cristopher Sanchez 86.92%, Payton Tolle 72.15%, Kyle Schwarber 59.49%, Mickey Gasper 51.05%, Bryce Harper 50.63%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 0.42 pts; parse OK; DK %Drafted agrees.


#### Full-field decomposition — contest 191020574 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound; DK %Drafted agrees with the lineup recompute

- Entries 224 (221 complete lineups); winning score 154.85; multi-entry contest: True.
- Duplication: 183 distinct lineups; 24.0% of entries sat in a duplicated lineup; max copies 10; the winning lineup had 1 copy. Copies histogram: {1: 168, 2: 8, 3: 2, 4: 1, 5: 2, 7: 1, 10: 1}.
- Salary usage: 34.4% of entries within $100 of the cap. Salary-left bins: {'1-100': 33, '> 1500': 30, '<= 0': 43, '101-300': 32, '301-700': 52, '701-1500': 31}.
- Max-stack histogram: {2: 1, 3: 29, 4: 87, 5: 104}.
- SP-pair field share (top): Cristopher Sanchez/Payton Tolle 61.1%, Chris Bassitt/Cristopher Sanchez 19.0%, Cristopher Sanchez/Walker Buehler 7.7%, Payton Tolle/Walker Buehler 5.0%.
- **Self vs field**: 7 own entries; best rank 45/224 (80.36th pct), median 19.64th pct; best 130.65 pts against a winning 154.85; 2 own lineup(s) duplicated by the field (max 3 copies); fees $0.07, winnings $0.00, net $-0.07. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Cristopher Sanchez 86.61%, Payton Tolle 68.75%, Kyle Schwarber 52.23%, Trea Turner 52.23%, Mickey Gasper 49.11%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 0.01 pts; parse OK; DK %Drafted agrees.


---


Two archive entries below, kept separate because they are different draftgroups
on the same date and pooling them would blur two different fields.

## A-006 — 2026-07-24 — 4 contests, night slate (4 games: ATH@MIN, CIN@STL, LAA@SF, SEA@TEX)

Salary basis: runs/20260724T233609Z_8f32ac45/inputs/DKSalaries.csv (16 entries
delivered). All four passed the field_miner v0.5 structural gate at 100% salary
join. Contests 192657349, 192657350, 192658268, 192667458.


#### Full-field decomposition — contest 192657349 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Entries 237 (228 complete lineups); winning score 118.9; multi-entry contest: True.
- Duplication: 216 distinct lineups; 8.3% of entries sat in a duplicated lineup; max copies 7; the winning lineup had 1 copy. Copies histogram: {1: 209, 2: 6, 7: 1}.
- Salary usage: 55.7% of entries within $100 of the cap. Salary-left bins: {'1-100': 63, '> 1500': 18, '301-700': 26, '<= 0': 64, '701-1500': 22, '101-300': 35}.
- Max-stack histogram: {2: 26, 3: 55, 4: 71, 5: 76}.
- SP-pair field share (top): Dustin May/MacKenzie Gore 16.7%, Logan Webb/MacKenzie Gore 16.2%, Bryce Miller/Logan Webb 11.8%, Bryce Miller/Dustin May 11.0%.
- **Self vs field**: 7 own entries; best rank 21/237 (91.56th pct), median 83.12th pct; best 97.75 pts against a winning 118.9; 0 own lineup(s) duplicated by the field (max 1 copies); fees $0.07, winnings $0.00, net $-0.07. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Logan Webb 45.15%, MacKenzie Gore 43.46%, Byron Buxton 42.62%, Dustin May 38.4%, Bryce Miller 34.6%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 0.42 pts; parse OK; DK %Drafted agrees.

#### Full-field decomposition — contest 192657350 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Entries 237 (237 complete lineups); winning score 139.75; multi-entry contest: True.
- Duplication: 214 distinct lineups; 13.1% of entries sat in a duplicated lineup; max copies 7; the winning lineup had 1 copy. Copies histogram: {1: 206, 2: 4, 4: 1, 5: 1, 7: 2}.
- Salary usage: 51.9% of entries within $100 of the cap. Salary-left bins: {'101-300': 53, '1-100': 67, '> 1500': 21, '<= 0': 56, '701-1500': 16, '301-700': 24}.
- Max-stack histogram: {1: 2, 2: 31, 3: 67, 4: 69, 5: 68}.
- SP-pair field share (top): Logan Webb/MacKenzie Gore 16.9%, Dustin May/MacKenzie Gore 11.0%, Bryce Miller/Logan Webb 11.0%, Bryce Miller/Dustin May 10.1%.
- **Self vs field**: 7 own entries; best rank 17/237 (93.25th pct), median 83.12th pct; best 97.75 pts against a winning 139.75; 0 own lineup(s) duplicated by the field (max 1 copies); fees $0.07, winnings $0.00, net $-0.07. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Logan Webb 46.41%, MacKenzie Gore 45.15%, Byron Buxton 39.66%, Dustin May 35.86%, Bryce Miller 35.86%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 0.42 pts; parse OK; DK %Drafted agrees.

#### Full-field decomposition — contest 192658268 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Entries 3567 (3454 complete lineups); winning score 145.95; multi-entry contest: True.
- Duplication: 3105 distinct lineups; 15.7% of entries sat in a duplicated lineup; max copies 16; the winning lineup had 1 copy. Copies histogram: {1: 2911, 2: 137, 3: 25, 4: 12, 5: 7, 6: 4, 7: 3, 9: 1, 10: 3, 11: 1, 16: 1}.
- Salary usage: 43.7% of entries within $100 of the cap. Salary-left bins: {'301-700': 630, '<= 0': 869, '1-100': 639, '> 1500': 200, '701-1500': 356, '101-300': 760}.
- Max-stack histogram: {1: 3, 2: 409, 3: 789, 4: 761, 5: 1492}.
- SP-pair field share (top): Logan Webb/MacKenzie Gore 18.0%, Dustin May/MacKenzie Gore 14.5%, Bryce Miller/Logan Webb 13.5%, Dustin May/Logan Webb 10.2%.
- **Self vs field**: 1 own entries; best rank 728/3567 (79.62th pct), median 79.62th pct; best 86.6 pts against a winning 145.95; 0 own lineup(s) duplicated by the field (max 1 copies); fees $1.00, winnings $1.50, net $0.50. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Logan Webb 47.27%, MacKenzie Gore 45.84%, Bryce Miller 37.01%, Dustin May 36.05%, Byron Buxton 34.65%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 0.01 pts; parse OK; DK %Drafted agrees.

#### Full-field decomposition — contest 192667458 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Entries 59 (58 complete lineups); winning score 110.8; multi-entry contest: False.
- Duplication: 57 distinct lineups; 3.4% of entries sat in a duplicated lineup; max copies 2; the winning lineup had 1 copy. Copies histogram: {1: 56, 2: 1}.
- Salary usage: 60.3% of entries within $100 of the cap. Salary-left bins: {'301-700': 8, '<= 0': 16, '1-100': 19, '701-1500': 4, '> 1500': 4, '101-300': 7}.
- Max-stack histogram: {2: 6, 3: 16, 4: 13, 5: 23}.
- SP-pair field share (top): Dustin May/Logan Webb 20.7%, Bryce Miller/Logan Webb 20.7%, Logan Webb/MacKenzie Gore 17.2%, MacKenzie Gore/Zebby Matthews 12.1%.
- **Self vs field**: 1 own entries; best rank 9/59 (86.44th pct), median 86.44th pct; best 89.55 pts against a winning 110.8; 0 own lineup(s) duplicated by the field (max 1 copies); fees $0.10, winnings $0.00, net $-0.10. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Logan Webb 64.41%, Byron Buxton 40.68%, MacKenzie Gore 40.68%, Jacob Wilson 37.29%, Bryce Miller 35.59%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 3.39 pts; parse OK; DK %Drafted table short 5.3 pts (DK omits multi-position rows; lineup-derived ownership used).

### Gaps to backfill for A-006

Entry fee, payout structure, and cash line for all four contests (the export
omits the archetype trio). Ben's own entries are identifiable from the promoted
run's assignments but are not yet recorded; that is E-3 and remains unbuilt.

## A-007 — 2026-07-24 — 6 contests, main slate (10 games)

Salary basis: runs/20260724T224327Z_e80d2ada/inputs/DKSalaries.csv (9 entries
delivered). All six passed the structural gate at 100% salary join. Contests
192701222, 192701224, 192701225, 192705822, 192709106, 192712196.


#### Full-field decomposition — contest 192701222 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Entries 59 (59 complete lineups); winning score 123.6; multi-entry contest: False.
- Duplication: 59 distinct lineups; 0.0% of entries sat in a duplicated lineup; max copies 1; the winning lineup had 1 copy. Copies histogram: {1: 59}.
- Salary usage: 52.5% of entries within $100 of the cap. Salary-left bins: {'301-700': 9, '<= 0': 18, '1-100': 13, '101-300': 13, '> 1500': 3, '701-1500': 3}.
- Max-stack histogram: {1: 1, 2: 11, 3: 10, 4: 8, 5: 29}.
- SP-pair field share (top): MacKenzie Gore/Roki Sasaki 6.8%, Dustin May/MacKenzie Gore 6.8%, Bryce Miller/Dustin May 5.1%, Logan Webb/Shane McClanahan 5.1%.
- **Self vs field**: 1 own entries; best rank 16/59 (74.58th pct), median 74.58th pct; best 94.25 pts against a winning 123.6; 0 own lineup(s) duplicated by the field (max 1 copies); fees $0.10, winnings $0.00, net $-0.10. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): MacKenzie Gore 30.51%, Logan Webb 28.81%, Dustin May 27.12%, Royce Lewis 23.72%, Shane McClanahan 20.34%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 5.09 pts; parse OK; DK %Drafted table short 10.6 pts (DK omits multi-position rows; lineup-derived ownership used).

#### Full-field decomposition — contest 192701224 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Entries 59 (59 complete lineups); winning score 129.45; multi-entry contest: False.
- Duplication: 59 distinct lineups; 0.0% of entries sat in a duplicated lineup; max copies 1; the winning lineup had 1 copy. Copies histogram: {1: 59}.
- Salary usage: 45.8% of entries within $100 of the cap. Salary-left bins: {'<= 0': 17, '101-300': 19, '> 1500': 2, '301-700': 10, '1-100': 10, '701-1500': 1}.
- Max-stack histogram: {1: 1, 2: 11, 3: 10, 4: 8, 5: 29}.
- SP-pair field share (top): Dustin May/Logan Webb 10.2%, Logan Webb/MacKenzie Gore 8.5%, Dustin May/MacKenzie Gore 8.5%, Logan Webb/Shane McClanahan 5.1%.
- **Self vs field**: 1 own entries; best rank 4/59 (94.92th pct), median 94.92th pct; best 103.55 pts against a winning 129.45; 0 own lineup(s) duplicated by the field (max 1 copies); fees $0.10, winnings $0.00, net $-0.10. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Logan Webb 45.76%, Dustin May 30.51%, Byron Buxton 28.81%, Royce Lewis 27.11%, MacKenzie Gore 23.73%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 3.39 pts; parse OK; DK %Drafted table short 3.8 pts (DK omits multi-position rows; lineup-derived ownership used).

#### Full-field decomposition — contest 192701225 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Entries 59 (59 complete lineups); winning score 132.8; multi-entry contest: False.
- Duplication: 59 distinct lineups; 0.0% of entries sat in a duplicated lineup; max copies 1; the winning lineup had 1 copy. Copies histogram: {1: 59}.
- Salary usage: 57.6% of entries within $100 of the cap. Salary-left bins: {'301-700': 10, '1-100': 15, '<= 0': 19, '701-1500': 2, '> 1500': 2, '101-300': 11}.
- Max-stack histogram: {1: 1, 2: 7, 3: 10, 4: 11, 5: 30}.
- SP-pair field share (top): Dustin May/MacKenzie Gore 10.2%, Logan Webb/MacKenzie Gore 10.2%, Dustin May/Logan Webb 6.8%, Shane McClanahan/Trey Yesavage 6.8%.
- **Self vs field**: 1 own entries; best rank 21/59 (66.1th pct), median 66.1th pct; best 89.2 pts against a winning 132.8; 0 own lineup(s) duplicated by the field (max 1 copies); fees $0.10, winnings $0.00, net $-0.10. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Logan Webb 37.29%, MacKenzie Gore 32.2%, Shane McClanahan 28.81%, Dustin May 27.12%, Byron Buxton 23.73%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 3.39 pts; parse OK; DK %Drafted table short 7.2 pts (DK omits multi-position rows; lineup-derived ownership used).

#### Full-field decomposition — contest 192705822 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Entries 118 (118 complete lineups); winning score 126.75; multi-entry contest: True.
- Duplication: 118 distinct lineups; 0.0% of entries sat in a duplicated lineup; max copies 1; the winning lineup had 1 copy. Copies histogram: {1: 118}.
- Salary usage: 66.1% of entries within $100 of the cap. Salary-left bins: {'<= 0': 51, '101-300': 20, '1-100': 27, '701-1500': 5, '301-700': 13, '> 1500': 2}.
- Max-stack histogram: {1: 3, 2: 22, 3: 18, 4: 24, 5: 51}.
- SP-pair field share (top): Dustin May/MacKenzie Gore 11.9%, Dustin May/Logan Webb 5.9%, Logan Webb/Shane McClanahan 5.9%, Bryce Miller/Logan Webb 5.1%.
- **Self vs field**: 3 own entries; best rank 13/118 (89.83th pct), median 87.29th pct; best 108.95 pts against a winning 126.75; 0 own lineup(s) duplicated by the field (max 1 copies); fees $0.75, winnings $0.00, net $-0.75. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Logan Webb 38.98%, MacKenzie Gore 31.36%, Dustin May 28.81%, Byron Buxton 22.03%, Jake Cronenworth 22.03%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 2.54 pts; parse OK; DK %Drafted table short 4.4 pts (DK omits multi-position rows; lineup-derived ownership used).

#### Full-field decomposition — contest 192709106 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Entries 59 (59 complete lineups); winning score 117.25; multi-entry contest: True.
- Duplication: 59 distinct lineups; 0.0% of entries sat in a duplicated lineup; max copies 1; the winning lineup had 1 copy. Copies histogram: {1: 59}.
- Salary usage: 52.5% of entries within $100 of the cap. Salary-left bins: {'701-1500': 3, '1-100': 15, '<= 0': 16, '101-300': 17, '301-700': 7, '> 1500': 1}.
- Max-stack histogram: {1: 1, 2: 7, 3: 6, 4: 14, 5: 31}.
- SP-pair field share (top): Dustin May/MacKenzie Gore 13.6%, Dustin May/Trevor Rogers 8.5%, Bryce Miller/Logan Webb 8.5%, Logan Webb/MacKenzie Gore 8.5%.
- **Self vs field**: 2 own entries; best rank 6/59 (91.53th pct), median 88.98th pct; best 107.9 pts against a winning 117.25; 0 own lineup(s) duplicated by the field (max 1 copies); fees $0.50, winnings $0.00, net $-0.50. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Logan Webb 42.37%, Dustin May 33.9%, MacKenzie Gore 30.51%, Byron Buxton 27.12%, Bryce Miller 25.42%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 6.78 pts; parse OK; DK %Drafted table short 8.9 pts (DK omits multi-position rows; lineup-derived ownership used).

#### Full-field decomposition — contest 192712196 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Entries 237 (237 complete lineups); winning score 133.0; multi-entry contest: False.
- Duplication: 235 distinct lineups; 1.7% of entries sat in a duplicated lineup; max copies 2; the winning lineup had 1 copy. Copies histogram: {1: 233, 2: 2}.
- Salary usage: 67.9% of entries within $100 of the cap. Salary-left bins: {'1-100': 71, '<= 0': 90, '101-300': 47, '701-1500': 10, '301-700': 17, '> 1500': 2}.
- Max-stack histogram: {1: 12, 2: 70, 3: 37, 4: 46, 5: 72}.
- SP-pair field share (top): Logan Webb/MacKenzie Gore 9.3%, Dustin May/Logan Webb 8.4%, Dustin May/MacKenzie Gore 7.2%, Logan Webb/Trevor Rogers 3.4%.
- **Self vs field**: 1 own entries; best rank 225/237 (5.49th pct), median 5.49th pct; best 48.25 pts against a winning 133.0; 0 own lineup(s) duplicated by the field (max 1 copies); fees $5.00, winnings $0.00, net $-5.00. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Logan Webb 37.55%, Byron Buxton 32.07%, Royce Lewis 27.84%, MacKenzie Gore 25.74%, Dustin May 24.05%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 2.11 pts; parse OK; DK %Drafted table short 3.5 pts (DK omits multi-position rows; lineup-derived ownership used).

### Gaps to backfill for A-007

Same trio gap as A-006. Note that all six missed the 1.5-point DK-table advisory
band (max diff 2.1 to 6.8 pts) while passing the structural gate at a 100% join
rate, which is the multi-position-row pattern first recorded on 2026-07-22.

### Archive count after this session

12 contests across 7 slate-entries (A-001..A-007). The ownership-model gate in
section 5 counts SLATES, not contests: this session took the archive from 5
slates to 7. Both of tonight's entries are Classic. The three 07-24 and four
07-23 Showdown contests are pullable but were deliberately held back until
field_miner v0.5 (this session) taught the miner the Showdown roster contract;
they are now minable and remain uncaptured.


**Evidence loss (2026-07-25, recorded so no future session proposes a re-pull):**
Five standings exports are unrecoverable and their slates will never enter the
archive: contests **191489664, 191513240, 191520890, 191521489, 191542451**. All
five landed in `data/standings/inbox/` at zero bytes on 2026-07-19. Ben re-pulled
them two different ways on 2026-07-24 and both attempts returned zero bytes
again. The working theory is that DK's `exportfullstandingscsv/<id>` endpoint
ages out and stops serving a populated file some days after a contest settles;
the files sat for five days before anyone noticed they were empty. The five
zero-byte files were deleted from the inbox on 2026-07-25 with this note as their
only record.

Two consequences, both standing:

1. **The pull window is same-night or next-morning.** Treat a standings export as
   perishable. Pull it the night the contest settles, or the following morning at
   the latest, and check the file size before walking away. A zero-byte export is
   a failed pull, not a pulled file.
2. **The archive stays at 5 slates (A-001..A-005) against the 8-15 gate in
   section 5.** These five would have taken it to 10. The ownership-model
   dependency is therefore further out than the raw contest count suggested, and
   the next five settled slates all have to land cleanly.

Aging is a theory, not a finding. The test that would confirm it is the four
2026-07-24 night contests (**192657350, 192657349, 192667458, 192658268**), still
unpulled as of this note. If those come back populated, age is confirmed and rule
1 above is the fix. If they come back empty too, the export path itself is broken
and the failure is not about timing at all. Record the result here either way.

**Session note (2026-07-22, mlb-standings-archive scheduled task):** A-002
through A-005 below were mined this session. `field_miner` v0.4 splits the
ownership recompute self-check into a hard structural gate
(`parse_structural_ok`, blocks archiving on failure) and an advisory DK-table
agreement check (`dk_table_agrees`, the 1.5-pt band) — see the module
docstring's "v0.4 verification split." Ledger invariant 3.7 still reads the
1.5-pt band as a hard "the parse is wrong, fix before archiving" gate. All 12
mining runs this session (11 contests plus one re-run) passed the structural
gate; 7 missed the 1.5-pt advisory band, in every case attributed by
`verification_note` to DK's own `%Drafted` table omitting multi-position rows,
not a parse defect. Archived all of them on the structural gate rather than
blocking on the advisory band. Flagging the invariant-text/code drift for
Ben to reconcile 3.7's wording rather than resolving it unilaterally.

## A-008 — 2026-07-24 — 3 contests, Showdown (tranche 2 leftover, same night slate as A-006)

Salary basis: `outputs/2026-07-24/DKEntries_showdown.csv` player pool block
(no standalone DKSalaries CSV recovered for this draftgroup; the DKEntries
upload embeds the full salary block per the runbook fallback). All three
passed the field_miner v0.5 structural gate at 100% salary join. Contests
192657334, 192657335, 192667460.

#### Full-field decomposition — contest 192657334 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound (every complete entry carries 6 distinct players); DK's %Drafted table sums 18.1 pts short, which is DK omitting position rows for multi-position players. Lineup-derived ownership is authoritative for this contest.
- Entries 188 (187 complete lineups); winning score 109.825; multi-entry contest: True.
- Duplication: 144 distinct lineups; 32.6% of entries sat in a duplicated lineup; max copies 8; the winning lineup had 1 copy. Copies histogram: {1: 126, 2: 10, 3: 2, 4: 2, 5: 1, 7: 2, 8: 1}.
- Salary usage: 42.2% of entries within $100 of the cap. Salary-left bins: {'<= 0': 49, '101-300': 40, '701-1500': 22, '1-100': 30, '301-700': 32, '> 1500': 14}.
- Max-stack histogram: {3: 59, 4: 68, 5: 60}.
- **Self vs field**: 7 own entries; best rank 98/188 (48.4th pct), median 40.43th pct; best 66.125 pts against a winning 109.825; 0 own lineup(s) duplicated by the field (max 1 copies); fees $0.07, winnings $0.00, net $-0.07. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Roki Sasaki 66.49%, A.J. Ewing 47.34%, Miguel Rojas 46.81%, Shohei Ohtani 46.27%, Jared Young 38.83%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 18.08 pts; parse OK; DK %Drafted table short 18.1 pts (DK omits multi-position rows; lineup-derived ownership used).

#### Full-field decomposition — contest 192657335 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound; DK %Drafted agrees with the lineup recompute
- Entries 203 (200 complete lineups); winning score 109.825; multi-entry contest: True.
- Duplication: 152 distinct lineups; 33.5% of entries sat in a duplicated lineup; max copies 7; the winning lineup had 1 copy. Copies histogram: {1: 133, 2: 9, 3: 2, 4: 1, 5: 5, 7: 2}.
- Salary usage: 38.0% of entries within $100 of the cap. Salary-left bins: {'<= 0': 50, '101-300': 50, '701-1500': 22, '301-700': 35, '> 1500': 17, '1-100': 26}.
- Max-stack histogram: {3: 62, 4: 70, 5: 68}.
- **Self vs field**: 7 own entries; best rank 102/203 (50.25th pct), median 38.42th pct; best 63.75 pts against a winning 109.825; 0 own lineup(s) duplicated by the field (max 1 copies); fees $0.07, winnings $0.00, net $-0.07. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Roki Sasaki 58.62%, A.J. Ewing 48.77%, Tommy Edman 41.87%, Shohei Ohtani 41.87%, Miguel Rojas 39.9%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 0.01 pts; parse OK; DK %Drafted agrees.

#### Full-field decomposition — contest 192667460 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound; DK %Drafted agrees with the lineup recompute
- Entries 49 (49 complete lineups); winning score 100.83; multi-entry contest: False.
- Duplication: 45 distinct lineups; 16.3% of entries sat in a duplicated lineup; max copies 2; the winning lineup had 1 copy. Copies histogram: {1: 41, 2: 4}.
- Salary usage: 42.9% of entries within $100 of the cap. Salary-left bins: {'301-700': 11, '1-100': 9, '701-1500': 8, '101-300': 8, '<= 0': 12, '> 1500': 1}.
- Max-stack histogram: {3: 14, 4: 23, 5: 12}.
- **Self vs field**: 1 own entries; best rank 23/49 (55.1th pct), median 55.1th pct; best 65.75 pts against a winning 100.83; 0 own lineup(s) duplicated by the field (max 1 copies); fees $0.10, winnings $0.00, net $-0.10. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Roki Sasaki 44.9%, Sean Manaea 44.9%, Tommy Edman 44.9%, Shohei Ohtani 42.86%, Andy Pages 38.78%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 0.0 pts; parse OK; DK %Drafted agrees.

### Gaps to backfill for A-008

Entry fee, payout structure, field size context, and cash line for all three
contests (contest-page trio not manually captured). Ben's own entries are
recorded via `--my-entry-ids` harvested from the DKEntries upload files, so
self-vs-field is populated; net $ line is not, since winnings were not supplied.

## A-009 — 2026-07-23 — 4 contests, Showdown (KC @ DET)

Salary basis: `outputs/2026-07-23/DKEntries_showdown.csv` player pool block
(no standalone DKSalaries CSV recovered for this draftgroup). All four passed
the field_miner v0.5 structural gate at 100% salary join. Contests 192630776,
192652559, 192652560, 192652561.

#### Full-field decomposition — contest 192630776 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound; DK %Drafted agrees with the lineup recompute
- Entries 2378 (2360 complete lineups); winning score 92.025; multi-entry contest: True.
- Duplication: 1240 distinct lineups; 63.5% of entries sat in a duplicated lineup; max copies 31; the winning lineup had 3 copies. Copies histogram: {1: 861, 2: 182, 3: 69, 4: 42, 5: 20, 6: 12, 7: 8, 8: 9, 9: 8, 10: 11, 11: 5, 12: 1, 13: 2, 14: 2, 15: 1, 17: 1, 18: 4, 22: 1, 31: 1}.
- Salary usage: 33.9% of entries within $100 of the cap. Salary-left bins: {'101-300': 506, '301-700': 555, '<= 0': 640, '> 1500': 157, '1-100': 160, '701-1500': 342}.
- Max-stack histogram: {3: 376, 4: 795, 5: 1189}.
- **Self vs field**: 1 own entries; best rank 748/2378 (68.59th pct), median 68.59th pct; best 52.775 pts against a winning 92.025; 1 own lineup(s) duplicated by the field (max 8 copies); fees $1.00, winnings $0.00, net $-1.00. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Troy Melton 81.66%, Riley Greene 43.65%, Spencer Torkelson 37.85%, Kevin McGonigle 36.21%, Andrew Velazquez 34.65%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 0.01 pts; parse OK; DK %Drafted agrees.

#### Full-field decomposition — contest 192652559 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound; DK %Drafted agrees with the lineup recompute
- Entries 118 (118 complete lineups); winning score 92.025; multi-entry contest: True.
- Duplication: 101 distinct lineups; 24.6% of entries sat in a duplicated lineup; max copies 3; the winning lineup had 1 copy. Copies histogram: {1: 89, 2: 7, 3: 5}.
- Salary usage: 38.1% of entries within $100 of the cap. Salary-left bins: {'101-300': 26, '301-700': 24, '<= 0': 33, '> 1500': 9, '1-100': 12, '701-1500': 14}.
- Max-stack histogram: {3: 32, 4: 49, 5: 37}.
- **Self vs field**: 3 own entries; best rank 16/118 (87.29th pct), median 30.51th pct; best 61.1 pts against a winning 92.025; 2 own lineup(s) duplicated by the field (max 3 copies); fees $0.30, winnings $0.00, net $-0.30. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Troy Melton 82.2%, Andrew Velazquez 46.61%, Kevin McGonigle 46.61%, Dillon Dingler 44.92%, Spencer Torkelson 42.37%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 0.01 pts; parse OK; DK %Drafted agrees.

#### Full-field decomposition — contest 192652560 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound; DK %Drafted agrees with the lineup recompute
- Entries 118 (118 complete lineups); winning score 80.025; multi-entry contest: True.
- Duplication: 104 distinct lineups; 22.0% of entries sat in a duplicated lineup; max copies 3; the winning lineup had 1 copy. Copies histogram: {1: 92, 2: 10, 3: 2}.
- Salary usage: 30.5% of entries within $100 of the cap. Salary-left bins: {'301-700': 27, '701-1500': 23, '101-300': 23, '<= 0': 27, '1-100': 9, '> 1500': 9}.
- Max-stack histogram: {3: 24, 4: 52, 5: 42}.
- **Self vs field**: 3 own entries; best rank 26/118 (78.81th pct), median 66.95th pct; best 56.85 pts against a winning 80.025; 2 own lineup(s) duplicated by the field (max 2 copies); fees $0.75, winnings $0.00, net $-0.75. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Troy Melton 79.66%, Andrew Velazquez 49.16%, Riley Greene 46.61%, Spencer Torkelson 44.07%, Dillon Dingler 39.83%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 0.01 pts; parse OK; DK %Drafted agrees.

#### Full-field decomposition — contest 192652561 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound; DK %Drafted agrees with the lineup recompute
- Entries 29 (29 complete lineups); winning score 70.03; multi-entry contest: False.
- Duplication: 29 distinct lineups; 0.0% of entries sat in a duplicated lineup; max copies 1; the winning lineup had 1 copy. Copies histogram: {1: 29}.
- Salary usage: 24.1% of entries within $100 of the cap. Salary-left bins: {'701-1500': 9, '101-300': 5, '<= 0': 5, '301-700': 5, '> 1500': 3, '1-100': 2}.
- Max-stack histogram: {3: 4, 4: 11, 5: 14}.
- **Self vs field**: 1 own entries; best rank 2/29 (96.55th pct), median 96.55th pct; best 65.1 pts against a winning 70.03; 0 own lineup(s) duplicated by the field (max 1 copies); fees $1.00, winnings $0.00, net $-1.00. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Troy Melton 82.76%, Riley Greene 51.72%, Kevin McGonigle 48.28%, Zach McKinstry 44.83%, Dillon Dingler 37.93%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 0.0 pts; parse OK; DK %Drafted agrees.

### Gaps to backfill for A-009

Entry fee, payout structure, field size context, and cash line for all four
contests (contest-page trio not manually captured). Self-vs-field populated
via harvested Entry IDs; net $ line not populated (winnings not supplied).

## A-010 — 2026-07-23 — 3 contests, Classic main slate

Salary basis: `outputs/2026-07-23/DKEntries.csv` player pool block (no
standalone DKSalaries CSV recovered for this draftgroup). All three passed
the field_miner v0.5 structural gate at 100% salary join. Contests 192623314,
192623315, 192656508.

#### Full-field decomposition — contest 192623314 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound; DK %Drafted agrees with the lineup recompute
- Entries 297 (295 complete lineups); winning score 122.95; multi-entry contest: True.
- Duplication: 252 distinct lineups; 23.1% of entries sat in a duplicated lineup; max copies 8; the winning lineup had 1 copy. Copies histogram: {1: 227, 2: 19, 3: 2, 4: 1, 5: 1, 7: 1, 8: 1}.
- Salary usage: 22.7% of entries within $100 of the cap. Salary-left bins: {'> 1500': 73, '301-700': 55, '101-300': 59, '<= 0': 37, '1-100': 30, '701-1500': 41}.
- Max-stack histogram: {2: 3, 3: 51, 4: 99, 5: 142}.
- SP-pair field share (top): Michael McGreevy/Troy Melton 42.0%, Brandon Pfaadt/Troy Melton 26.8%, Brandon Pfaadt/Michael McGreevy 12.5%, Randy Dobnak/Troy Melton 10.5%.
- **Self vs field**: 8 own entries; best rank 26/297 (91.58th pct), median 54.71th pct; best 100.1 pts against a winning 122.95; 2 own lineup(s) duplicated by the field (max 4 copies); fees $0.80, winnings $0.00, net $-0.80. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Troy Melton 79.46%, Kevin McGonigle 63.97%, Riley Greene 62.96%, Michael McGreevy 58.92%, Corbin Carroll 48.15%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 0.01 pts; parse OK; DK %Drafted agrees.

#### Full-field decomposition — contest 192623315 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound (every complete entry carries 10 distinct players); DK's %Drafted table sums 6.8 pts short, which is DK omitting position rows for multi-position players. Lineup-derived ownership is authoritative for this contest.
- Entries 118 (118 complete lineups); winning score 118.1; multi-entry contest: True.
- Duplication: 113 distinct lineups; 8.5% of entries sat in a duplicated lineup; max copies 2; the winning lineup had 1 copy. Copies histogram: {1: 108, 2: 5}.
- Salary usage: 25.4% of entries within $100 of the cap. Salary-left bins: {'> 1500': 26, '301-700': 24, '101-300': 18, '701-1500': 20, '<= 0': 18, '1-100': 12}.
- Max-stack histogram: {2: 1, 3: 14, 4: 48, 5: 55}.
- SP-pair field share (top): Michael McGreevy/Troy Melton 47.5%, Brandon Pfaadt/Troy Melton 28.0%, Randy Dobnak/Troy Melton 12.7%, Brandon Pfaadt/Michael McGreevy 7.6%.
- **Self vs field**: 3 own entries; best rank 10/118 (92.37th pct), median 63.56th pct; best 100.1 pts against a winning 118.1; 0 own lineup(s) duplicated by the field (max 1 copies); fees $0.75, winnings $0.00, net $-0.75. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Troy Melton 88.14%, Kevin McGonigle 72.04%, Riley Greene 66.1%, Michael McGreevy 55.93%, Jordan Walker 46.61%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 6.78 pts; parse OK; DK %Drafted table short 6.8 pts (DK omits multi-position rows; lineup-derived ownership used).

#### Full-field decomposition — contest 192656508 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound; DK %Drafted agrees with the lineup recompute
- Entries 594 (590 complete lineups); winning score 122.95; multi-entry contest: True.
- Duplication: 528 distinct lineups; 16.9% of entries sat in a duplicated lineup; max copies 15; the winning lineup had 1 copy. Copies histogram: {1: 490, 2: 28, 3: 7, 4: 2, 15: 1}.
- Salary usage: 20.5% of entries within $100 of the cap. Salary-left bins: {'> 1500': 152, '701-1500': 105, '301-700': 116, '101-300': 96, '1-100': 51, '<= 0': 70}.
- Max-stack histogram: {2: 2, 3: 95, 4: 196, 5: 297}.
- SP-pair field share (top): Michael McGreevy/Troy Melton 39.0%, Brandon Pfaadt/Troy Melton 29.3%, Randy Dobnak/Troy Melton 12.9%, Brandon Pfaadt/Michael McGreevy 9.0%.
- **Self vs field**: 1 own entries; best rank 539/594 (9.43th pct), median 9.43th pct; best 60.35 pts against a winning 122.95; 0 own lineup(s) duplicated by the field (max 1 copies); fees $1.00, winnings $0.00, net $-1.00. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Troy Melton 80.64%, Kevin McGonigle 63.97%, Corbin Carroll 56.73%, Riley Greene 54.55%, Michael McGreevy 53.87%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 0.0 pts; parse OK; DK %Drafted agrees.

### Gaps to backfill for A-010

Entry fee, payout structure, field size context, and cash line for all three
contests (contest-page trio not manually captured). Self-vs-field populated
via harvested Entry IDs; net $ line not populated (winnings not supplied).

## A-011 — 2026-07-22 — 3 contests, night slate (MEGA Qualifier draftgroup)

Salary basis: `outputs/2026-07-22/DKEntries.csv` player pool block (no
standalone DKSalaries CSV recovered for this draftgroup). All three passed
the field_miner v0.5 structural gate at 100% salary join. Contests 192591926,
192591927, 192627933.

#### Full-field decomposition — contest 192591926 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound; DK %Drafted agrees with the lineup recompute
- Entries 237 (233 complete lineups); winning score 131.9; multi-entry contest: True.
- Duplication: 214 distinct lineups; 12.4% of entries sat in a duplicated lineup; max copies 7; the winning lineup had 1 copy. Copies histogram: {1: 204, 2: 6, 3: 2, 4: 1, 7: 1}.
- Salary usage: 44.6% of entries within $100 of the cap. Salary-left bins: {'<= 0': 54, '301-700': 40, '1-100': 50, '> 1500': 36, '101-300': 40, '701-1500': 13}.
- Max-stack histogram: {2: 39, 3: 74, 4: 73, 5: 47}.
- SP-pair field share (top): Colin Rea/Peter Lambert 20.6%, Peter Lambert/Sandy Alcantara 20.2%, Colin Rea/Sandy Alcantara 11.6%, Keider Montero/Peter Lambert 10.7%.
- **Self vs field**: 7 own entries; best rank 26/237 (89.45th pct), median 56.12th pct; best 100.15 pts against a winning 131.9; 0 own lineup(s) duplicated by the field (max 1 copies); fees $0.07, winnings $0.00, net $-0.07. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Peter Lambert 62.03%, Wyatt Langford 44.73%, Sandy Alcantara 41.77%, Colin Rea 40.93%, Yordan Alvarez 35.86%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 0.01 pts; parse OK; DK %Drafted agrees.

#### Full-field decomposition — contest 192591927 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound; DK %Drafted agrees with the lineup recompute
- Entries 237 (236 complete lineups); winning score 133.9; multi-entry contest: True.
- Duplication: 220 distinct lineups; 10.2% of entries sat in a duplicated lineup; max copies 7; the winning lineup had 1 copy. Copies histogram: {1: 212, 2: 4, 3: 3, 7: 1}.
- Salary usage: 47.0% of entries within $100 of the cap. Salary-left bins: {'701-1500': 28, '101-300': 36, '301-700': 33, '1-100': 41, '> 1500': 28, '<= 0': 70}.
- Max-stack histogram: {2: 29, 3: 80, 4: 84, 5: 43}.
- SP-pair field share (top): Peter Lambert/Sandy Alcantara 22.5%, Colin Rea/Peter Lambert 18.2%, Colin Rea/Sandy Alcantara 14.4%, Keider Montero/Peter Lambert 9.7%.
- **Self vs field**: 7 own entries; best rank 22/237 (91.14th pct), median 78.06th pct; best 100.15 pts against a winning 133.9; 0 own lineup(s) duplicated by the field (max 1 copies); fees $0.07, winnings $0.00, net $-0.07. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Peter Lambert 59.92%, Sandy Alcantara 48.95%, Wyatt Langford 48.1%, Colin Rea 40.08%, Ezequiel Duran 34.17%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 0.42 pts; parse OK; DK %Drafted agrees.

#### Full-field decomposition — contest 192627933 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound (every complete entry carries 10 distinct players); DK's %Drafted table sums 2.8 pts short, which is DK omitting position rows for multi-position players. Lineup-derived ownership is authoritative for this contest.
- Entries 594 (586 complete lineups); winning score 149.9; multi-entry contest: True.
- Duplication: 521 distinct lineups; 16.2% of entries sat in a duplicated lineup; max copies 17; the winning lineup had 1 copy. Copies histogram: {1: 491, 2: 18, 3: 5, 4: 4, 5: 1, 6: 1, 17: 1}.
- Salary usage: 41.3% of entries within $100 of the cap. Salary-left bins: {'<= 0': 119, '101-300': 118, '1-100': 123, '701-1500': 56, '301-700': 125, '> 1500': 45}.
- Max-stack histogram: {2: 47, 3: 161, 4: 148, 5: 230}.
- SP-pair field share (top): Peter Lambert/Sandy Alcantara 24.9%, Colin Rea/Sandy Alcantara 17.2%, Colin Rea/Peter Lambert 15.2%, Keider Montero/Peter Lambert 7.5%.
- **Self vs field**: 1 own entries; best rank 170/594 (71.55th pct), median 71.55th pct; best 79.75 pts against a winning 149.9; 0 own lineup(s) duplicated by the field (max 1 copies); fees $1.00, winnings $0.00, net $-1.00. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Peter Lambert 55.56%, Sandy Alcantara 54.55%, Wyatt Langford 46.3%, Colin Rea 40.91%, Yordan Alvarez 36.87%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 2.86 pts; parse OK; DK %Drafted table short 2.8 pts (DK omits multi-position rows; lineup-derived ownership used).

### Gaps to backfill for A-011

Entry fee, payout structure, field size context, and cash line for all three
contests (contest-page trio not manually captured). Self-vs-field populated
via harvested Entry IDs; net $ line not populated (winnings not supplied).

## A-012 — 2026-07-22 — 4 contests, early slate

Salary basis: `outputs/2026-07-22/DKEntries_upload.csv` player pool block
(no standalone DKSalaries CSV recovered for this draftgroup). All four passed
the field_miner v0.5 structural gate at 100% salary join. Contests 192591443,
192591459, 192591504, 192593054.

#### Full-field decomposition — contest 192591443 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound; DK %Drafted agrees with the lineup recompute
- Entries 178 (178 complete lineups); winning score 186.95; multi-entry contest: True.
- Duplication: 176 distinct lineups; 1.7% of entries sat in a duplicated lineup; max copies 3; the winning lineup had 1 copy. Copies histogram: {1: 175, 3: 1}.
- Salary usage: 50.0% of entries within $100 of the cap. Salary-left bins: {'<= 0': 51, '101-300': 34, '1-100': 38, '301-700': 34, '701-1500': 16, '> 1500': 5}.
- Max-stack histogram: {1: 1, 2: 11, 3: 25, 4: 37, 5: 104}.
- SP-pair field share (top): Gerrit Cole/Reid Detmers 6.7%, Logan Henderson/Reid Detmers 6.2%, Brady Singer/Reid Detmers 5.1%, Gerrit Cole/Logan Henderson 4.5%.
- **Self vs field**: 5 own entries; best rank 62/178 (65.73th pct), median 10.11th pct; best 108.8 pts against a winning 186.95; 0 own lineup(s) duplicated by the field (max 1 copies); fees $0.50, winnings $0.00, net $-0.50. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Gerrit Cole 32.58%, Reid Detmers 30.34%, CJ Abrams 29.21%, Jazz Chisholm Jr. 28.65%, James Wood 28.09%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 0.01 pts; parse OK; DK %Drafted agrees.

#### Full-field decomposition — contest 192591459 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound (every complete entry carries 10 distinct players); DK's %Drafted table sums 8.6 pts short, which is DK omitting position rows for multi-position players. Lineup-derived ownership is authoritative for this contest.
- Entries 118 (118 complete lineups); winning score 186.95; multi-entry contest: True.
- Duplication: 118 distinct lineups; 0.0% of entries sat in a duplicated lineup; max copies 1; the winning lineup had 1 copy. Copies histogram: {1: 118}.
- Salary usage: 57.6% of entries within $100 of the cap. Salary-left bins: {'<= 0': 41, '1-100': 27, '301-700': 22, '101-300': 21, '701-1500': 6, '> 1500': 1}.
- Max-stack histogram: {1: 1, 2: 16, 3: 24, 4: 24, 5: 53}.
- SP-pair field share (top): Emerson Hancock/Gerrit Cole 5.9%, Gerrit Cole/Reid Detmers 5.1%, Brady Singer/Landen Roupp 4.2%, Brady Singer/Jake Bennett 4.2%.
- **Self vs field**: 3 own entries; best rank 6/118 (95.76th pct), median 32.2th pct; best 131.95 pts against a winning 186.95; 0 own lineup(s) duplicated by the field (max 1 copies); fees $0.75, winnings $0.00, net $-0.75. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Gerrit Cole 31.36%, Jazz Chisholm Jr. 27.12%, Emerson Hancock 26.27%, CJ Abrams 26.27%, Ben Rice 24.58%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 5.09 pts; parse OK; DK %Drafted table short 8.6 pts (DK omits multi-position rows; lineup-derived ownership used).

#### Full-field decomposition — contest 192591504 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound; DK %Drafted agrees with the lineup recompute
- Entries 15 (15 complete lineups); winning score 140.15; multi-entry contest: False.
- Duplication: 15 distinct lineups; 0.0% of entries sat in a duplicated lineup; max copies 1; the winning lineup had 1 copy. Copies histogram: {1: 15}.
- Salary usage: 66.7% of entries within $100 of the cap. Salary-left bins: {'<= 0': 6, '1-100': 4, '301-700': 2, '101-300': 3}.
- Max-stack histogram: {2: 3, 3: 7, 4: 2, 5: 3}.
- SP-pair field share (top): Emerson Hancock/Logan Henderson 13.3%, Gerrit Cole/Reid Detmers 13.3%, Brady Singer/Gerrit Cole 6.7%, Christian Scott/Gerrit Cole 6.7%.
- **Self vs field**: 1 own entries; best rank 3/15 (86.67th pct), median 86.67th pct; best 136.25 pts against a winning 140.15; 0 own lineup(s) duplicated by the field (max 1 copies); fees $1.00, winnings $0.00, net $-1.00. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Gerrit Cole 53.33%, Caleb Durbin 40.0%, CJ Abrams 33.33%, Wilyer Abreu 33.33%, Logan Henderson 26.67%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 0.0 pts; parse OK; DK %Drafted agrees.

#### Full-field decomposition — contest 192593054 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Verification: parse structurally sound; DK %Drafted agrees with the lineup recompute
- Entries 594 (591 complete lineups); winning score 178.6; multi-entry contest: False.
- Duplication: 583 distinct lineups; 2.4% of entries sat in a duplicated lineup; max copies 4; the winning lineup had 1 copy. Copies histogram: {1: 577, 2: 5, 4: 1}.
- Salary usage: 52.6% of entries within $100 of the cap. Salary-left bins: {'101-300': 166, '1-100': 125, '<= 0': 186, '701-1500': 26, '301-700': 76, '> 1500': 12}.
- Max-stack histogram: {1: 13, 2: 121, 3: 130, 4: 114, 5: 213}.
- SP-pair field share (top): Emerson Hancock/Gerrit Cole 7.1%, Gerrit Cole/Logan Henderson 6.4%, Gerrit Cole/Reid Detmers 4.7%, Emerson Hancock/Logan Henderson 4.4%.
- **Self vs field**: 1 own entries; best rank 441/594 (25.93th pct), median 25.93th pct; best 85.45 pts against a winning 178.6; 0 own lineup(s) duplicated by the field (max 1 copies); fees $1.00, winnings $0.00, net $-1.00. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Gerrit Cole 36.2%, Jazz Chisholm Jr. 34.34%, James Wood 29.8%, CJ Abrams 29.46%, Emerson Hancock 23.4%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 0.84 pts; parse OK; DK %Drafted agrees.

### Gaps to backfill for A-012

Entry fee, payout structure, field size context, and cash line for all four
contests (contest-page trio not manually captured). Self-vs-field populated
via harvested Entry IDs; net $ line not populated (winnings not supplied).

## A-002 — 2026-07-19 — 1 contest, afternoon4 sub-slate

Archived 2026-07-22 via the standings-archive scheduled task. Contest 192464820
was pulled from the inbox alongside a same-day-looking 2026-07-18 batch by
contest-ID proximity; that grouping was wrong. Resolved to 2026-07-19 (the
afternoon4 4-game sub-slate: DET@LAA, SF@SEA, STL@AZ, WSH@ATH) by a 100.0%
salary join against `data/slates/2026-07-19-afternoon4/DKSalaries.csv` (a 0.0%
join against the main 2026-07-19 slate and against every 2026-07-18 candidate
tested — see A-003). Salary CSV archived alongside as
`DKSalaries_2026-07-19-afternoon4.csv`. Full coverage. A stale
`data/archive/2026-07-18/mined_192464820.json` from the initial misdated run
could not be deleted (workspace files are delete-protected without manual
approval) and has been overwritten with a superseded marker pointing here; safe
for Ben to remove by hand. Entry fee, payout structure, paid places, cash line,
and Ben's own Entry IDs: not in the export, not backfilled this run.

#### Full-field decomposition — contest 192464820 (field_miner 0.4-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Entries 31 (31 complete lineups); winning score 183.6; multi-entry contest: False.
- Duplication: 30 distinct lineups; 6.5% of entries sat in a duplicated lineup; max copies 2; the winning lineup had 1 copy. Copies histogram: {1: 29, 2: 1}.
- Salary usage: 96.8% of entries within $100 of the cap. Salary-left bins: {'<= 0': 29, '1-100': 1, '> 1500': 1}.
- Max-stack histogram: {3: 10, 4: 10, 5: 11}.
- SP-pair field share (top): Grayson Rodriguez/Tarik Skubal 41.9%, Tarik Skubal/Zack Littell 29.0%, J.T. Ginn/Tarik Skubal 25.8%, Grayson Rodriguez/Zack Littell 3.2%.
- **Self vs field**: 1 own entries; best rank 22/31 (32.26th pct), median 32.26th pct; best 93.75 pts against a winning 183.6; 0 own lineup(s) duplicated by the field (max 1 copies); fees $1.00, winnings $0.00, net $-1.00. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Tarik Skubal 96.77%, James Wood 67.74%, Keibert Ruiz 51.61%, Tyler Soderstrom 51.61%, Riley Greene 48.39%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 22.58 pts; parse OK; DK %Drafted table short 22.6 pts (DK omits multi-position rows; lineup-derived ownership used).

### Gaps to backfill for A-002

- Entry fee, payout structure, paid places, cash line, seats, Ben's own Entry IDs: not captured.
- Ownership recompute misses the 1.5-pt advisory band by 22.6 pts, the largest in this batch. Structural check passed; DK's own table is short, not our parse; still worth a manual glance given the size of the gap.

---

## A-003 — 2026-07-18 — 3 contests, one slate

Archived 2026-07-22. Slate date inferred, not confirmed: contest-standings zip
export timestamps for 192413146/192413147 read 2026-07-18 22:31 (server-side
export time). 192444379 has no zip but shares the same top SP names (Matthew
Boyd / Taj Bradley / Davis Martin) and opponent-registry cross-reference as the
other two. No salary CSV or DKEntries file for 2026-07-18 exists anywhere in
this repo, so all three ran `standings_only` (duplication, chalk, SP pairs,
ownership recompute, and the opponent registry populated; salary usage and
stack tables unavailable). Entry fee, payout structure, paid places, and cash
line: not in the export, not backfilled.

#### Full-field decomposition — contest 192413146 (field_miner 0.4-review; coverage standings_only; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Entries 203 (203 complete lineups); winning score 144.6; multi-entry contest: True.
- Duplication: 181 distinct lineups; 15.8% of entries sat in a duplicated lineup; max copies 7; the winning lineup had 1 copy. Copies histogram: {1: 171, 2: 6, 3: 2, 7: 2}.
- Salary-usage and stack tables unavailable at this coverage tier (no salary file); re-run at full coverage if the slate salary CSV or the slate's DKEntries upload file (which embeds the salary block) surfaces.
- SP-pair field share (top): Matthew Boyd/Shane Bieber 20.2%, Matthew Boyd/Taj Bradley 19.2%, Davis Martin/Taj Bradley 17.7%, Davis Martin/Matthew Boyd 10.8%.
- **Self vs field**: 7 own entries; best rank 24/203 (88.67th pct), median 49.26th pct; best 112.25 pts against a winning 144.6; 0 own lineup(s) duplicated by the field (max 1 copies); fees $0.07, winnings $0.00, net $-0.07. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Matthew Boyd 54.68%, Taj Bradley 52.71%, Elly De La Cruz 50.25%, Ernie Clement 43.84%, JJ Bleday 42.86%.
- Diagnostics: salary join n/a (standings_only); ownership recompute max diff 0.01 pts; parse OK; DK %Drafted agrees.

#### Full-field decomposition — contest 192413147 (field_miner 0.4-review; coverage standings_only; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Entries 210 (208 complete lineups); winning score 142.25; multi-entry contest: True.
- Duplication: 187 distinct lineups; 14.4% of entries sat in a duplicated lineup; max copies 7; the winning lineup had 1 copy. Copies histogram: {1: 178, 2: 5, 3: 2, 7: 2}.
- Salary-usage and stack tables unavailable at this coverage tier (no salary file); re-run at full coverage if the slate salary CSV or the slate's DKEntries upload file (which embeds the salary block) surfaces.
- SP-pair field share (top): Davis Martin/Taj Bradley 19.2%, Matthew Boyd/Shane Bieber 16.3%, Matthew Boyd/Taj Bradley 16.3%, Davis Martin/Matthew Boyd 11.5%.
- **Self vs field**: 7 own entries; best rank 26/210 (88.1th pct), median 51.9th pct; best 112.25 pts against a winning 142.25; 0 own lineup(s) duplicated by the field (max 1 copies); fees $0.07, winnings $0.00, net $-0.07. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Taj Bradley 50.48%, Matthew Boyd 48.57%, Elly De La Cruz 42.38%, JJ Bleday 42.38%, Ernie Clement 42.38%.
- Diagnostics: salary join n/a (standings_only); ownership recompute max diff 0.01 pts; parse OK; DK %Drafted agrees.

#### Full-field decomposition — contest 192444379 (field_miner 0.4-review; coverage standings_only; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Entries 31 (31 complete lineups); winning score 140.6; multi-entry contest: False.
- Duplication: 31 distinct lineups; 0.0% of entries sat in a duplicated lineup; max copies 1; the winning lineup had 1 copy. Copies histogram: {1: 31}.
- Salary-usage and stack tables unavailable at this coverage tier (no salary file); re-run at full coverage if the slate salary CSV or the slate's DKEntries upload file (which embeds the salary block) surfaces.
- SP-pair field share (top): Matthew Boyd/Taj Bradley 32.3%, Davis Martin/Taj Bradley 29.0%, Matthew Boyd/Shane Bieber 12.9%, Davis Martin/Rhett Lowder 9.7%.
- **Self vs field**: 1 own entries; best rank 15/31 (54.84th pct), median 54.84th pct; best 81.4 pts against a winning 140.6; 0 own lineup(s) duplicated by the field (max 1 copies); fees $1.00, winnings $0.00, net $-1.00. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Taj Bradley 70.97%, Elly De La Cruz 54.84%, Matthew Boyd 51.61%, Ernie Clement 48.39%, Davis Martin 45.16%.
- Diagnostics: salary join n/a (standings_only); ownership recompute max diff 0.01 pts; parse OK; DK %Drafted agrees.

### Gaps to backfill for A-003

- Slate date: inferred from zip export timestamp and registry cross-reference, not confirmed via a salary file. Re-run at full coverage and confirm if a 2026-07-18 DKSalaries or DKEntries file ever surfaces.
- Entry fee, payout structure, paid places, cash line, seats, Ben's own Entry IDs: not captured.

---

## A-001 — 2026-06-29 — 3 contests, one slate

Uploaded 2026-06-30; slate date confirmed 2026-06-29 on 2026-07-04 via the
recovered salary file (`DKSalaries__2026-06-29.csv`): all 38 table players and all
30 winner slots join it, and every Game Info entry is dated 06/29/2026. A 2-game,
4-team slate (CWS@BAL, PIT@PHI; 180-player pool), so the thin-slate rules (3.3)
apply to this archetype. Mixed-roster slate with several rebuild and call-up-heavy
lineups (Pirates, White Sox prospects alongside Phillies and Orioles regulars). One
outcome draw, observed across three contest shapes. The two zipped uploads of
contest 191787184 were byte-identical, so this is three distinct contests, not
four.

### Contest meta

| Contest | Entries | Winning score | Median | Min | Shape (observed) |
| --- | --- | --- | --- | --- | --- |
| 191787184 | 222 | 176.7 | 92.8 | 0.0 | larger GPP (wide winner-to-median gap) |
| 191787186 | 23 | 145.7 | 107.5 | 73.65 | small field |
| 191823035 | 29 | 154.7 | 106.7 | 56.65 | small field |

Entry fee, payout structure, paid places, and cash line: NOT in the export. Backfill
required. `EntryName (4/4)` tags in 191787184 confirm at least 4 entries per user.

### Winning lineups

- **191787184:** 1B Ryan O'Hearn, 2B Bryson Stott, 3B Miguel Vargas, C Endy
  Rodriguez, OF Bryan Reynolds, OF Brandon Marsh, OF Esmerlyn Valdez, P Braxton
  Ashcraft, P Sean Burke, SS Konnor Griffin.
- **191787186:** 1B Miguel Vargas, 2B Chase Meidroth, 3B Colson Montgomery, C Endy
  Rodriguez, OF Ryan O'Hearn, OF Sam Antonacci, OF Braden Montgomery, P Braxton
  Ashcraft, P Sean Burke, SS Konnor Griffin.
- **191823035:** 1B Miguel Vargas, 2B Brandon Lowe, 3B Colson Montgomery, C Endy
  Rodriguez, OF Ryan O'Hearn, OF Sam Antonacci, OF Esmerlyn Valdez, P Braxton
  Ashcraft, P Sean Burke, SS Konnor Griffin.

All three winners rostered the same two pitchers (Ashcraft, Burke) plus Endy
Rodriguez, Konnor Griffin, Miguel Vargas, and Ryan O'Hearn.

**Winner construction (salary join, added 2026-07-04; record-only):**

- **191787184:** $49,900 used ($100 left, inside the $100 at-cap band); hitter
  stack 5-2-1 (PIT 5, PHI 2, CWS 1); zero min-salary players.
- **191787186:** $48,200 used ($1,800 left); hitter stack 5-3 (CWS 5, PIT 3); zero
  min-salary players.
- **191823035:** $50,000 used ($0 left, exact cap); hitter stack 5-3 (PIT 5,
  CWS 3); zero min-salary players.

### Player table (actual FPTS, with actual %Drafted per contest)

FPTS are identical across the three contests, confirming one slate. Spread is the
range of `%Drafted` across the three contests for that player. Sal and Val (FPTS
per $1k) joined 2026-07-04 from the recovered salary file; the salary file is
authoritative for salary and team. Deterministic descriptive statistics, never
value or edge claims.

**Corrected 2026-07-04 (full-field mining):** the DK player table is grained per
(player, roster position); a multi-position player appears once per drafted slot
and the rows sum to his total. The original transcription understated three
players: Miguel Vargas is 46.4 / 52.2 / 65.5 across the three contests (was
21.2 / 21.7 / 20.7), Colson Montgomery 41.0 / 43.5 / 51.7 (was 17.6 / 17.4 / 6.9),
Ryan O'Hearn 30.2 / 43.5 / 31.0 (was 14.4 / 21.7 / 31.0). In 191787184 the cause
was taking one row of a position-split player; the 191787186 and 191823035
corrections are transcription errors in the original entry. All three pct columns
are now regenerated from the mined exports and validated by the ownership
recompute self-check (max residual 0.9 pts, on Rafael Flores Jr. in 191787184,
under the 1.5-pt tolerance). The raw position splits are preserved in the mined
JSONs.

| Player | Pos | FPTS | Sal | Val | 184% | 186% | 035% | spread |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Brandon Marsh | OF | 28.0 | 5000 | 5.6 | 24.8 | 26.1 | 24.1 | 1.9 |
| Esmerlyn Valdez | OF | 27.0 | 2700 | 10.0 | 14.4 | 13.0 | 34.5 | 21.4 |
| Endy Rodriguez | C | 27.0 | 3900 | 6.9 | 7.7 | 13.0 | 10.3 | 5.4 |
| Braxton Ashcraft | P | 19.9 | 8700 | 2.3 | 65.8 | 78.3 | 58.6 | 19.6 |
| Sean Burke | P | 19.8 | 7500 | 2.6 | 43.7 | 69.6 | 62.1 | 25.9 |
| Trea Turner | SS | 19.0 | 5500 | 3.5 | 6.8 | 4.3 | 10.3 | 6.0 |
| Shane Baz | P | 18.9 | 7700 | 2.5 | 38.7 | 30.4 | 31.0 | 8.3 |
| Bryce Harper | 1B | 18.0 | 6000 | 3.0 | 17.6 | 13.0 | 37.9 | 24.9 |
| Jacob Gonzalez | 1B | 18.0 | 2200 | 8.2 | 5.0 | 4.3 | - | 0.6 |
| Konnor Griffin | SS | 15.0 | 3500 | 4.3 | 38.3 | 56.5 | 69.0 | 30.7 |
| Jared Triolo | SS | 14.0 | 2400 | 5.8 | 4.5 | 4.3 | 3.5 | 1.0 |
| Chase Meidroth | 2B | 13.0 | 3800 | 3.4 | 14.4 | 34.8 | 27.6 | 20.4 |
| Justin Crawford | OF | 13.0 | 3000 | 4.3 | 5.9 | 4.3 | 3.5 | 2.4 |
| Gunnar Henderson | SS | 12.0 | 5100 | 2.4 | 27.9 | 17.4 | 10.3 | 17.6 |
| Miguel Vargas | 3B | 12.0 | 4600 | 2.6 | 46.4 | 52.2 | 65.5 | 19.1 |
| Ryan O'Hearn | OF | 12.0 | 4700 | 2.6 | 30.2 | 43.5 | 31.0 | 13.3 |
| Sam Antonacci | OF | 11.0 | 4100 | 2.7 | 38.3 | 47.8 | 37.9 | 9.9 |
| Bryan Reynolds | OF | 11.0 | 5300 | 2.1 | 25.2 | 26.1 | 20.7 | 5.4 |
| Colson Montgomery | SS | 9.0 | 4500 | 2.0 | 41.0 | 43.5 | 51.7 | 10.7 |
| Colton Cowser | OF | 9.0 | 2800 | 3.2 | 10.8 | - | 10.3 | 0.5 |
| Braden Montgomery | OF | 7.0 | 2900 | 2.4 | 12.2 | 17.4 | 20.7 | 8.5 |
| Jake Mangum | OF | 7.0 | 3700 | 1.9 | 9.5 | 4.3 | 3.5 | 6.0 |
| J.T. Realmuto | C | 7.0 | 3600 | 1.9 | 6.8 | 13.0 | 6.9 | 6.3 |
| Kyle Teel | C | 5.0 | 3400 | 1.5 | 36.5 | 43.5 | 55.2 | 18.7 |
| Bryson Stott | 2B | 5.0 | 4000 | 1.2 | 24.3 | 21.7 | 20.7 | 3.6 |
| Randal Grichuk | OF | 5.0 | 3300 | 1.5 | 16.2 | 30.4 | 10.3 | 20.1 |
| Tristan Peters | OF | 5.0 | 2500 | 2.0 | 8.6 | 13.0 | 10.3 | 4.5 |
| Kyle Schwarber | OF | 4.0 | 6500 | 0.6 | 30.6 | 39.1 | 41.4 | 10.8 |
| Adley Rutschman | C | 4.0 | 4000 | 1.0 | 23.9 | 17.4 | 17.2 | 6.6 |
| Blaze Alexander | 3B | 4.0 | 2900 | 1.4 | 17.6 | 21.7 | 10.3 | 11.4 |
| Samuel Basallo | C | 3.0 | 3500 | 0.9 | 18.5 | 13.0 | 10.3 | 8.1 |
| Jackson Holliday | 2B | 3.0 | 3200 | 0.9 | 14.4 | 17.4 | 6.9 | 10.5 |
| Brandon Lowe | 2B | 2.0 | 5800 | 0.3 | 41.9 | 26.1 | 44.8 | 18.7 |
| Tyler Callihan | OF | 2.0 | 2600 | 0.8 | 14.9 | 13.0 | 10.3 | 4.5 |
| Pete Alonso | 1B | 0.0 | 5600 | 0.0 | 35.6 | 39.1 | 17.2 | 21.9 |
| Taylor Ward | OF | 0.0 | 4400 | 0.0 | 34.2 | 26.1 | 27.6 | 8.1 |
| Alec Bohm | 3B | 0.0 | 3500 | 0.0 | 23.0 | 13.0 | 20.7 | 9.9 |
| Aaron Nola | P | -0.2 | 7000 | -0.0 | 41.9 | 21.7 | 48.3 | 26.5 |

(Players below 0.5% in all contests omitted from the table; full export retained in
the raw archive.)

### Full-field decompositions (field_miner, added 2026-07-04)

#### Full-field decomposition — contest 191787184 (field_miner 0.3-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Entries 222 (211 complete lineups); winning score 176.7; multi-entry contest: True.
- Duplication: 198 distinct lineups; 10.4% of entries sat in a duplicated lineup; max copies 4; the winning lineup had 1 copy. Copies histogram: {1: 189, 2: 6, 3: 2, 4: 1}.
- Salary usage: 37.4% of entries within $100 of the cap. Salary-left bins: {'1-100': 35, '701-1500': 38, '101-300': 40, '301-700': 51, '<= 0': 44, '> 1500': 3}.
- Max-stack histogram: {2: 1, 3: 44, 4: 84, 5: 82}.
- SP-pair field share (top): Braxton Ashcraft/Sean Burke 28.9%, Braxton Ashcraft/Shane Baz 22.7%, Aaron Nola/Braxton Ashcraft 17.5%, Aaron Nola/Shane Baz 13.7%.
- Chalk (top-5 %Drafted): Braxton Ashcraft 65.77%, Miguel Vargas 46.4%, Sean Burke 43.69%, Aaron Nola 41.89%, Brandon Lowe 41.89%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 0.9 pts (OK).

#### Full-field decomposition — contest 191787186 (field_miner 0.3-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Entries 23 (23 complete lineups); winning score 145.7; multi-entry contest: False.
- Duplication: 23 distinct lineups; 0.0% of entries sat in a duplicated lineup; max copies 1; the winning lineup had 1 copy. Copies histogram: {1: 23}.
- Salary usage: 34.8% of entries within $100 of the cap. Salary-left bins: {'> 1500': 1, '<= 0': 4, '301-700': 6, '1-100': 4, '101-300': 3, '701-1500': 5}.
- Max-stack histogram: {3: 6, 4: 13, 5: 4}.
- SP-pair field share (top): Braxton Ashcraft/Sean Burke 52.2%, Braxton Ashcraft/Shane Baz 21.7%, Aaron Nola/Sean Burke 13.0%, Sean Burke/Shane Baz 4.3%.
- Chalk (top-5 %Drafted): Braxton Ashcraft 78.26%, Sean Burke 69.57%, Konnor Griffin 56.52%, Miguel Vargas 52.17%, Sam Antonacci 47.83%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 0.0 pts (OK).

#### Full-field decomposition — contest 191823035 (field_miner 0.3-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Entries 29 (29 complete lineups); winning score 154.7; multi-entry contest: False.
- Duplication: 27 distinct lineups; 13.8% of entries sat in a duplicated lineup; max copies 2; the winning lineup had 1 copy. Copies histogram: {1: 25, 2: 2}.
- Salary usage: 48.3% of entries within $100 of the cap. Salary-left bins: {'<= 0': 7, '701-1500': 3, '101-300': 4, '301-700': 8, '1-100': 7}.
- Max-stack histogram: {3: 9, 4: 16, 5: 4}.
- SP-pair field share (top): Braxton Ashcraft/Sean Burke 34.5%, Aaron Nola/Sean Burke 20.7%, Aaron Nola/Shane Baz 13.8%, Aaron Nola/Braxton Ashcraft 13.8%.
- Chalk (top-5 %Drafted): Konnor Griffin 68.97%, Miguel Vargas 65.52%, Sean Burke 62.07%, Braxton Ashcraft 58.62%, Kyle Teel 55.17%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 0.0 pts (OK).

### Observations (single-slate, record-only, uncalibrated)

These earn no rule. They are logged to make the next post-mortem concrete and to
anchor the conditioning argument.

- **Ownership is contest-conditional, and the spread is large.** Same players, same
  slate, ownership swinging 20 to 31 points across the three contests (Konnor
  Griffin 38.3 to 69.0, Aaron Nola spread 26.5, Pete Alonso spread 21.9, Bryce
  Harper 17.6 to 37.9). This is the empirical basis for the Section 2 rule: do not
  pool `%Drafted` across archetypes.
- **The SP slot behaved as pure chalk.** The two highest-owned pitchers (Ashcraft 59
  to 78%, Burke 44 to 70%) were two of the highest scorers and were in all three
  winning lineups. Consistent with the 4.3 hypothesis; not enough to promote it.
- **The leverage hits were at C and OF, not P.** Endy Rodriguez (27 FPTS, 8 to 13%)
  and Esmerlyn Valdez (27 FPTS, 13 to 34%) were the underweighted scorers the
  winning lineups caught.
- **Popular bats busted:** Pete Alonso (17 to 39% owned, 0.0), Taylor Ward (26 to
  34%, 0.0), Kyle Schwarber (31 to 41%, 4.0).
- **All three winners built tight 5-stacks and spent to the cap or near it.** Two
  of three finished within $100 of the cap and none used a min-salary bat.
  Consistent with the 3.5 tight-stack rule and a first at-cap duplication
  datapoint for 4.6; single-slate, earns no rule.
- **Duplication was thin and all three winners were unique.** Every winning
  lineup had exactly one copy. 191787184: 198 distinct lineups over 211 complete
  entries, 10.4% of entries sat in a duplicated lineup, max 4 copies. 191787186:
  23 of 23 distinct. 191823035: 13.8% duplicated, max 2 copies. At-cap
  construction (within $100 of the cap): 37.4% / 34.8% / 48.3% of the field.
  5-stacks were a field minority everywhere (38.9% / 17.4% / 13.8% of complete
  entries) yet all three winners were 5-stacks. The chalk SP pair
  (Ashcraft/Burke) carried 28.9% / 52.2% / 34.5% of the field. Observed field
  behavior; single slate; earns no rule.

### Gaps to backfill for A-001

- ~~Slate date.~~ RESOLVED 2026-07-04: confirmed 2026-06-29 via the recovered
  salary file (full pool join; every Game Info entry dated 06/29/2026).
- ~~The slate salary CSV.~~ RESOLVED 2026-07-04: recovered
  (`DKSalaries__2026-06-29.csv`) and joined. Sal and Val columns added to the
  player table above; ownership rows emitted to `ownership_rows_2026-06-29.csv`
  (112 rows, long format, archetype UNKNOWN pending the contest-page trio).
- Entry fee, payout structure, paid places, and cash line: capture from DK
  contest history. Required to tag the ownership rows with archetype, to tier the
  three contests through the posture allocator retroactively, and to unblock the
  archetype-conditioned `ownership_prior` grade for this slate.
- Ben's own Entry IDs, to add the selection-by-selection self-vs-winner
  decomposition. Only the winning entries are decomposed above.
- Full-field mining: RESOLVED 2026-07-04. All three raw exports mined at full
  coverage (decomposition blocks above); opponent registry seeded; ownership
  recompute passed on all three (max residual 0.9 pts, under the 1.5-pt
  tolerance). The mining surfaced the (player, roster position) grain of the
  standings player table (now an invariant in 3.1) and corrected three players'
  ownership in the table above.

---

## A-004 — 2026-06-20 — 5 contests, one slate

Archived 2026-07-22. Slate date inferred, not confirmed: zip export timestamps
for 191506958/191507209/191507213/191507220 read 2026-06-21 00:03 (server-side
export time). 191506960 has no zip but shares the same dominant chalk SP (Chris
Sale, 40-59% owned in every contest of this group, absent from A-005 below) and
opponent-registry cross-reference. Corroborating signal, not proof: a web check
found Chris Sale placed on the 15-day injured list on 2026-06-21 with a
fractured rib, consistent with a start the evening before. No salary CSV or
DKEntries file for 2026-06-20 exists anywhere in this repo, so all five ran
`standings_only`. Entry fee, payout structure, paid places, and cash line: not
in the export, not backfilled.

#### Full-field decomposition — contest 191506958 (field_miner 0.4-review; coverage standings_only; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Entries 193 (188 complete lineups); winning score 149.55; multi-entry contest: True.
- Duplication: 164 distinct lineups; 19.1% of entries sat in a duplicated lineup; max copies 7; the winning lineup had 1 copy. Copies histogram: {1: 152, 2: 8, 3: 1, 4: 1, 6: 1, 7: 1}.
- Salary-usage and stack tables unavailable at this coverage tier (no salary file); re-run at full coverage if the slate salary CSV or the slate's DKEntries upload file (which embeds the salary block) surfaces.
- SP-pair field share (top): Chris Sale/Max Meyer 20.7%, Chris Sale/MacKenzie Gore 10.1%, Kyle Harrison/Max Meyer 9.6%, Chris Sale/Ian Seymour 8.5%.
- **Self vs field**: 7 own entries; best rank 37/193 (81.35th pct), median 47.67th pct; best 112.7 pts against a winning 149.55; 0 own lineup(s) duplicated by the field (max 1 copies); fees $0.07, winnings $0.00, net $-0.07. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Chris Sale 54.92%, Max Meyer 40.41%, Wyatt Langford 37.82%, Ezequiel Duran 35.23%, Fernando Tatis Jr. 28.5%.
- Diagnostics: salary join n/a (standings_only); ownership recompute max diff 0.0 pts; parse OK; DK %Drafted agrees.

#### Full-field decomposition — contest 191506960 (field_miner 0.4-review; coverage standings_only; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Entries 23 (23 complete lineups); winning score 154.0; multi-entry contest: False.
- Duplication: 23 distinct lineups; 0.0% of entries sat in a duplicated lineup; max copies 1; the winning lineup had 1 copy. Copies histogram: {1: 23}.
- Salary-usage and stack tables unavailable at this coverage tier (no salary file); re-run at full coverage if the slate salary CSV or the slate's DKEntries upload file (which embeds the salary block) surfaces.
- SP-pair field share (top): Kyle Harrison/Max Meyer 21.7%, Chris Sale/MacKenzie Gore 17.4%, Chris Sale/Max Meyer 13.0%, Chris Sale/Ian Seymour 13.0%.
- **Self vs field**: 1 own entries; best rank 14/23 (43.48th pct), median 43.48th pct; best 93.15 pts against a winning 154.0; 0 own lineup(s) duplicated by the field (max 1 copies); fees $0.25, winnings $0.00, net $-0.25. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Chris Sale 52.17%, Kyle Stowers 47.83%, Max Meyer 43.48%, Jonathan Aranda 34.78%, Kyle Harrison 34.78%.
- Diagnostics: salary join n/a (standings_only); ownership recompute max diff 0.0 pts; parse OK; DK %Drafted agrees.

#### Full-field decomposition — contest 191507209 (field_miner 0.4-review; coverage standings_only; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Entries 150 (150 complete lineups); winning score 157.9; multi-entry contest: True.
- Duplication: 150 distinct lineups; 0.0% of entries sat in a duplicated lineup; max copies 1; the winning lineup had 1 copy. Copies histogram: {1: 150}.
- Salary-usage and stack tables unavailable at this coverage tier (no salary file); re-run at full coverage if the slate salary CSV or the slate's DKEntries upload file (which embeds the salary block) surfaces.
- SP-pair field share (top): Chris Sale/Will Warren 19.3%, Chris Sale/MacKenzie Gore 13.3%, Chris Sale/Max Meyer 10.0%, Kyle Harrison/Max Meyer 6.0%.
- **Self vs field**: 5 own entries; best rank 19/150 (88.0th pct), median 75.33th pct; best 123.7 pts against a winning 157.9; 0 own lineup(s) duplicated by the field (max 1 copies); fees $0.50, winnings $0.00, net $-0.50. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Chris Sale 58.67%, Paul Goldschmidt 34.0%, Jose Caballero 32.0%, Will Warren 31.33%, Amed Rosario 30.67%.
- Diagnostics: salary join n/a (standings_only); ownership recompute max diff 11.34 pts; parse OK; DK %Drafted table short 24.6 pts (DK omits multi-position rows; lineup-derived ownership used).

#### Full-field decomposition — contest 191507213 (field_miner 0.4-review; coverage standings_only; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Entries 242 (242 complete lineups); winning score 155.0; multi-entry contest: True.
- Duplication: 242 distinct lineups; 0.0% of entries sat in a duplicated lineup; max copies 1; the winning lineup had 1 copy. Copies histogram: {1: 242}.
- Salary-usage and stack tables unavailable at this coverage tier (no salary file); re-run at full coverage if the slate salary CSV or the slate's DKEntries upload file (which embeds the salary block) surfaces.
- SP-pair field share (top): Chris Sale/Max Meyer 14.5%, Chris Sale/MacKenzie Gore 10.3%, Chris Sale/Will Warren 9.5%, Max Meyer/Will Warren 7.4%.
- **Self vs field**: 8 own entries; best rank 24/242 (90.5th pct), median 56.4th pct; best 124.149994 pts against a winning 155.0; 0 own lineup(s) duplicated by the field (max 1 copies); fees $0.80, winnings $0.00, net $-0.80. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Chris Sale 49.17%, Max Meyer 39.67%, Will Warren 28.93%, Seiya Suzuki 28.1%, Nico Hoerner 26.45%.
- Diagnostics: salary join n/a (standings_only); ownership recompute max diff 9.51 pts; parse OK; DK %Drafted table short 9.5 pts (DK omits multi-position rows; lineup-derived ownership used).

#### Full-field decomposition — contest 191507220 (field_miner 0.4-review; coverage standings_only; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Entries 110 (110 complete lineups); winning score 155.25; multi-entry contest: True.
- Duplication: 110 distinct lineups; 0.0% of entries sat in a duplicated lineup; max copies 1; the winning lineup had 1 copy. Copies histogram: {1: 110}.
- Salary-usage and stack tables unavailable at this coverage tier (no salary file); re-run at full coverage if the slate salary CSV or the slate's DKEntries upload file (which embeds the salary block) surfaces.
- SP-pair field share (top): Chris Sale/Will Warren 20.0%, Chris Sale/MacKenzie Gore 15.5%, Chris Sale/Max Meyer 10.9%, MacKenzie Gore/Max Meyer 7.3%.
- **Self vs field**: 4 own entries; best rank 17/110 (85.45th pct), median 80.91th pct; best 122.45 pts against a winning 155.25; 0 own lineup(s) duplicated by the field (max 1 copies); fees $0.40, winnings $0.00, net $-0.40. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Chris Sale 56.36%, MacKenzie Gore 37.27%, Will Warren 36.36%, Max Meyer 27.27%, Pete Crow-Armstrong 22.73%.
- Diagnostics: salary join n/a (standings_only); ownership recompute max diff 3.63 pts; parse OK; DK %Drafted table short 3.5 pts (DK omits multi-position rows; lineup-derived ownership used).

### Gaps to backfill for A-004

- Slate date: inferred, not confirmed via a salary file.
- 191507209 and 191507213 miss the 1.5-pt ownership-recompute advisory band (11.34 and 9.51 pts respectively); DK-table-short, structural check passed (see the session note above the archive).
- Entry fee, payout structure, paid places, cash line, seats, Ben's own Entry IDs: not captured.

---

## A-005 — 2026-06-19 — 2 contests, one slate

Archived 2026-07-22. Slate date inferred, not confirmed: zip export timestamps
for both contests read 2026-06-20 05:35 (server-side export time, consistent
with a slate the previous evening). Both share the same dominant chalk SP
(Jacob Misiorowski, 55%+ owned in both, absent from A-004 above). No salary CSV
or DKEntries file for 2026-06-19 exists anywhere in this repo, so both ran
`standings_only`. Entry fee, payout structure, paid places, and cash line: not
in the export, not backfilled.

#### Full-field decomposition — contest 191488360 (field_miner 0.4-review; coverage standings_only; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Entries 177 (177 complete lineups); winning score 179.0; multi-entry contest: True.
- Duplication: 176 distinct lineups; 1.1% of entries sat in a duplicated lineup; max copies 2; the winning lineup had 1 copy. Copies histogram: {1: 175, 2: 1}.
- Salary-usage and stack tables unavailable at this coverage tier (no salary file); re-run at full coverage if the slate salary CSV or the slate's DKEntries upload file (which embeds the salary block) surfaces.
- SP-pair field share (top): Cam Schlittler/Jacob Misiorowski 15.3%, Jacob Misiorowski/Jacob deGrom 12.4%, Jacob Misiorowski/Ranger Suarez 6.8%, Jacob Misiorowski/Roki Sasaki 4.5%.
- **Self vs field**: 5 own entries; best rank 36/177 (80.23th pct), median 24.86th pct; best 134.55 pts against a winning 179.0; 0 own lineup(s) duplicated by the field (max 1 copies); fees $0.50, winnings $0.00, net $-0.50. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Jacob Misiorowski 55.37%, Cam Schlittler 30.51%, Jacob deGrom 28.25%, Jo Adell 21.47%, Marcell Ozuna 20.34%.
- Diagnostics: salary join n/a (standings_only); ownership recompute max diff 3.96 pts; parse OK; DK %Drafted table short 6.8 pts (DK omits multi-position rows; lineup-derived ownership used).

#### Full-field decomposition — contest 191488366 (field_miner 0.4-review; coverage standings_only; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Entries 297 (297 complete lineups); winning score 189.4; multi-entry contest: True.
- Duplication: 297 distinct lineups; 0.0% of entries sat in a duplicated lineup; max copies 1; the winning lineup had 1 copy. Copies histogram: {1: 297}.
- Salary-usage and stack tables unavailable at this coverage tier (no salary file); re-run at full coverage if the slate salary CSV or the slate's DKEntries upload file (which embeds the salary block) surfaces.
- SP-pair field share (top): Jacob Misiorowski/Jacob deGrom 12.8%, Cam Schlittler/Jacob Misiorowski 12.1%, Jacob Misiorowski/Ranger Suarez 6.4%, Jacob deGrom/Ranger Suarez 5.4%.
- **Self vs field**: 8 own entries; best rank 19/297 (93.94th pct), median 61.62th pct; best 151.55 pts against a winning 189.4; 0 own lineup(s) duplicated by the field (max 1 copies); fees $0.80, winnings $0.00, net $-0.80. Observed outcomes, never a graded prediction.
- Chalk (top-5 %Drafted): Jacob Misiorowski 55.56%, Jacob deGrom 31.31%, Cam Schlittler 27.95%, Jo Adell 21.21%, Logan O'Hoppe 18.86%.
- Diagnostics: salary join n/a (standings_only); ownership recompute max diff 2.02 pts; parse OK; DK %Drafted table short 3.4 pts (DK omits multi-position rows; lineup-derived ownership used).

### Gaps to backfill for A-005

- Slate date: inferred, not confirmed via a salary file.
- Entry fee, payout structure, paid places, cash line, seats, Ben's own Entry IDs: not captured.
