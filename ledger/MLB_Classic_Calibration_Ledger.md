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

1. Macro: from the repo root, `python tools/audit.py --run-tests --terse` -> `PASS  v2.26.0  21 modules  285 tests`. If the audit fails on pins or inventory only while `python -m unittest tests.test_core` passes in full, proceed and flag; never repair infrastructure mid-slate. (Corrected 2026-07-24: this line still carried the pre-restructure claude.ai macro, naming a `/mnt/project` mount, a `/home/claude/work` copy, and a `project_audit.py` that do not exist in the v3.0.0-pre layout, plus stale counts. It is the mandated session-start read, so every session began by running a command that could not work.)
2. Pool: `build_slate_pool(salary_csv, lineups_feed, platoon_json, declared_pitchers)` is THE intake. Confirmed nine plus platoon nine plus probable/declared arms only; every other salary row is immaterial. Splat `pool["run_slate_kwargs"]` into `run_slate`.
3. Clock: T-5 delivery rule. `checkpoint["slate_clock"]` shows first lock, deadline, minutes remaining. T-20 skip optionals, T-10 approve on defaults, T-5 present the best certified file; refinements via `run_late_swap`.
4. Postures: pass explicit `contest_postures` by contest ID; never trust `infer_contest_archetype` on family names (Pocket Cup, Knuckleball, Relay Throw).
5. Feasibility: repetition, shared-players, and pct exposure caps auto-floor to slate minimums; explicit overrides win; applied floors surface under `controls_feasibility`. Review `checkpoint["feasibility"]` instead of rediscovering by hand.
6. Bank: the auto path is `build_diverse_candidate_bank`; hand-build `candidates_override` only when the checkpoint shows a coverage gap.
7. Enrichments, one call each through `run_slate`: `savant_batting_csv` + `savant_pitching_csv` (xwOBA plus xISO ceilings), `fangraphs_pitching_csv` (K-rate ceilings), `f4_by_player_id` from `compute_f4_factors(pool["team_by_player_id"], pool["opposing_probables"], pitching_table, pool["batter_hands"])`; the platoon map rides in `run_slate_kwargs`.
8. Report: gates, Run ID, provenance, promoted file, Blockers line, applied floors, enrichment counts. Opt-in only: tail scanner, mispricing screen, contested-slot audit, fill-depth narration, three-assumption kill list.
9. Ship rule: certified beats perfect. Deterministic review proxies only; never ROI, win-rate, or probability claims. Upload-ready only after all three gates.
10. Post-slate: attach the DK standings export, archive per 3.7, and only then does the full ledger read apply.

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
- Chalk (top-5 %Drafted): Logan Webb 45.15%, MacKenzie Gore 43.46%, Byron Buxton 42.62%, Dustin May 38.4%, Bryce Miller 34.6%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 0.42 pts; parse OK; DK %Drafted agrees.

#### Full-field decomposition — contest 192657350 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Entries 237 (237 complete lineups); winning score 139.75; multi-entry contest: True.
- Duplication: 214 distinct lineups; 13.1% of entries sat in a duplicated lineup; max copies 7; the winning lineup had 1 copy. Copies histogram: {1: 206, 2: 4, 4: 1, 5: 1, 7: 2}.
- Salary usage: 51.9% of entries within $100 of the cap. Salary-left bins: {'101-300': 53, '1-100': 67, '> 1500': 21, '<= 0': 56, '701-1500': 16, '301-700': 24}.
- Max-stack histogram: {1: 2, 2: 31, 3: 67, 4: 69, 5: 68}.
- SP-pair field share (top): Logan Webb/MacKenzie Gore 16.9%, Dustin May/MacKenzie Gore 11.0%, Bryce Miller/Logan Webb 11.0%, Bryce Miller/Dustin May 10.1%.
- Chalk (top-5 %Drafted): Logan Webb 46.41%, MacKenzie Gore 45.15%, Byron Buxton 39.66%, Dustin May 35.86%, Bryce Miller 35.86%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 0.42 pts; parse OK; DK %Drafted agrees.

#### Full-field decomposition — contest 192658268 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Entries 3567 (3454 complete lineups); winning score 145.95; multi-entry contest: True.
- Duplication: 3105 distinct lineups; 15.7% of entries sat in a duplicated lineup; max copies 16; the winning lineup had 1 copy. Copies histogram: {1: 2911, 2: 137, 3: 25, 4: 12, 5: 7, 6: 4, 7: 3, 9: 1, 10: 3, 11: 1, 16: 1}.
- Salary usage: 43.7% of entries within $100 of the cap. Salary-left bins: {'301-700': 630, '<= 0': 869, '1-100': 639, '> 1500': 200, '701-1500': 356, '101-300': 760}.
- Max-stack histogram: {1: 3, 2: 409, 3: 789, 4: 761, 5: 1492}.
- SP-pair field share (top): Logan Webb/MacKenzie Gore 18.0%, Dustin May/MacKenzie Gore 14.5%, Bryce Miller/Logan Webb 13.5%, Dustin May/Logan Webb 10.2%.
- Chalk (top-5 %Drafted): Logan Webb 47.27%, MacKenzie Gore 45.84%, Bryce Miller 37.01%, Dustin May 36.05%, Byron Buxton 34.65%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 0.01 pts; parse OK; DK %Drafted agrees.

#### Full-field decomposition — contest 192667458 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Entries 59 (58 complete lineups); winning score 110.8; multi-entry contest: False.
- Duplication: 57 distinct lineups; 3.4% of entries sat in a duplicated lineup; max copies 2; the winning lineup had 1 copy. Copies histogram: {1: 56, 2: 1}.
- Salary usage: 60.3% of entries within $100 of the cap. Salary-left bins: {'301-700': 8, '<= 0': 16, '1-100': 19, '701-1500': 4, '> 1500': 4, '101-300': 7}.
- Max-stack histogram: {2: 6, 3: 16, 4: 13, 5: 23}.
- SP-pair field share (top): Dustin May/Logan Webb 20.7%, Bryce Miller/Logan Webb 20.7%, Logan Webb/MacKenzie Gore 17.2%, MacKenzie Gore/Zebby Matthews 12.1%.
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
- Chalk (top-5 %Drafted): MacKenzie Gore 30.51%, Logan Webb 28.81%, Dustin May 27.12%, Royce Lewis 23.72%, Shane McClanahan 20.34%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 5.09 pts; parse OK; DK %Drafted table short 10.6 pts (DK omits multi-position rows; lineup-derived ownership used).

#### Full-field decomposition — contest 192701224 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Entries 59 (59 complete lineups); winning score 129.45; multi-entry contest: False.
- Duplication: 59 distinct lineups; 0.0% of entries sat in a duplicated lineup; max copies 1; the winning lineup had 1 copy. Copies histogram: {1: 59}.
- Salary usage: 45.8% of entries within $100 of the cap. Salary-left bins: {'<= 0': 17, '101-300': 19, '> 1500': 2, '301-700': 10, '1-100': 10, '701-1500': 1}.
- Max-stack histogram: {1: 1, 2: 11, 3: 10, 4: 8, 5: 29}.
- SP-pair field share (top): Dustin May/Logan Webb 10.2%, Logan Webb/MacKenzie Gore 8.5%, Dustin May/MacKenzie Gore 8.5%, Logan Webb/Shane McClanahan 5.1%.
- Chalk (top-5 %Drafted): Logan Webb 45.76%, Dustin May 30.51%, Byron Buxton 28.81%, Royce Lewis 27.11%, MacKenzie Gore 23.73%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 3.39 pts; parse OK; DK %Drafted table short 3.8 pts (DK omits multi-position rows; lineup-derived ownership used).

#### Full-field decomposition — contest 192701225 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Entries 59 (59 complete lineups); winning score 132.8; multi-entry contest: False.
- Duplication: 59 distinct lineups; 0.0% of entries sat in a duplicated lineup; max copies 1; the winning lineup had 1 copy. Copies histogram: {1: 59}.
- Salary usage: 57.6% of entries within $100 of the cap. Salary-left bins: {'301-700': 10, '1-100': 15, '<= 0': 19, '701-1500': 2, '> 1500': 2, '101-300': 11}.
- Max-stack histogram: {1: 1, 2: 7, 3: 10, 4: 11, 5: 30}.
- SP-pair field share (top): Dustin May/MacKenzie Gore 10.2%, Logan Webb/MacKenzie Gore 10.2%, Dustin May/Logan Webb 6.8%, Shane McClanahan/Trey Yesavage 6.8%.
- Chalk (top-5 %Drafted): Logan Webb 37.29%, MacKenzie Gore 32.2%, Shane McClanahan 28.81%, Dustin May 27.12%, Byron Buxton 23.73%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 3.39 pts; parse OK; DK %Drafted table short 7.2 pts (DK omits multi-position rows; lineup-derived ownership used).

#### Full-field decomposition — contest 192705822 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Entries 118 (118 complete lineups); winning score 126.75; multi-entry contest: True.
- Duplication: 118 distinct lineups; 0.0% of entries sat in a duplicated lineup; max copies 1; the winning lineup had 1 copy. Copies histogram: {1: 118}.
- Salary usage: 66.1% of entries within $100 of the cap. Salary-left bins: {'<= 0': 51, '101-300': 20, '1-100': 27, '701-1500': 5, '301-700': 13, '> 1500': 2}.
- Max-stack histogram: {1: 3, 2: 22, 3: 18, 4: 24, 5: 51}.
- SP-pair field share (top): Dustin May/MacKenzie Gore 11.9%, Dustin May/Logan Webb 5.9%, Logan Webb/Shane McClanahan 5.9%, Bryce Miller/Logan Webb 5.1%.
- Chalk (top-5 %Drafted): Logan Webb 38.98%, MacKenzie Gore 31.36%, Dustin May 28.81%, Byron Buxton 22.03%, Jake Cronenworth 22.03%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 2.54 pts; parse OK; DK %Drafted table short 4.4 pts (DK omits multi-position rows; lineup-derived ownership used).

#### Full-field decomposition — contest 192709106 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Entries 59 (59 complete lineups); winning score 117.25; multi-entry contest: True.
- Duplication: 59 distinct lineups; 0.0% of entries sat in a duplicated lineup; max copies 1; the winning lineup had 1 copy. Copies histogram: {1: 59}.
- Salary usage: 52.5% of entries within $100 of the cap. Salary-left bins: {'701-1500': 3, '1-100': 15, '<= 0': 16, '101-300': 17, '301-700': 7, '> 1500': 1}.
- Max-stack histogram: {1: 1, 2: 7, 3: 6, 4: 14, 5: 31}.
- SP-pair field share (top): Dustin May/MacKenzie Gore 13.6%, Dustin May/Trevor Rogers 8.5%, Bryce Miller/Logan Webb 8.5%, Logan Webb/MacKenzie Gore 8.5%.
- Chalk (top-5 %Drafted): Logan Webb 42.37%, Dustin May 33.9%, MacKenzie Gore 30.51%, Byron Buxton 27.12%, Bryce Miller 25.42%.
- Diagnostics: salary join 100.0% of complete entries fully joined; ownership recompute max diff 6.78 pts; parse OK; DK %Drafted table short 8.9 pts (DK omits multi-position rows; lineup-derived ownership used).

#### Full-field decomposition — contest 192712196 (field_miner 0.5-review; coverage full; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Entries 237 (237 complete lineups); winning score 133.0; multi-entry contest: False.
- Duplication: 235 distinct lineups; 1.7% of entries sat in a duplicated lineup; max copies 2; the winning lineup had 1 copy. Copies histogram: {1: 233, 2: 2}.
- Salary usage: 67.9% of entries within $100 of the cap. Salary-left bins: {'1-100': 71, '<= 0': 90, '101-300': 47, '701-1500': 10, '301-700': 17, '> 1500': 2}.
- Max-stack histogram: {1: 12, 2: 70, 3: 37, 4: 46, 5: 72}.
- SP-pair field share (top): Logan Webb/MacKenzie Gore 9.3%, Dustin May/Logan Webb 8.4%, Dustin May/MacKenzie Gore 7.2%, Logan Webb/Trevor Rogers 3.4%.
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
- Chalk (top-5 %Drafted): Matthew Boyd 54.68%, Taj Bradley 52.71%, Elly De La Cruz 50.25%, Ernie Clement 43.84%, JJ Bleday 42.86%.
- Diagnostics: salary join n/a (standings_only); ownership recompute max diff 0.01 pts; parse OK; DK %Drafted agrees.

#### Full-field decomposition — contest 192413147 (field_miner 0.4-review; coverage standings_only; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Entries 210 (208 complete lineups); winning score 142.25; multi-entry contest: True.
- Duplication: 187 distinct lineups; 14.4% of entries sat in a duplicated lineup; max copies 7; the winning lineup had 1 copy. Copies histogram: {1: 178, 2: 5, 3: 2, 7: 2}.
- Salary-usage and stack tables unavailable at this coverage tier (no salary file); re-run at full coverage if the slate salary CSV or the slate's DKEntries upload file (which embeds the salary block) surfaces.
- SP-pair field share (top): Davis Martin/Taj Bradley 19.2%, Matthew Boyd/Shane Bieber 16.3%, Matthew Boyd/Taj Bradley 16.3%, Davis Martin/Matthew Boyd 11.5%.
- Chalk (top-5 %Drafted): Taj Bradley 50.48%, Matthew Boyd 48.57%, Elly De La Cruz 42.38%, JJ Bleday 42.38%, Ernie Clement 42.38%.
- Diagnostics: salary join n/a (standings_only); ownership recompute max diff 0.01 pts; parse OK; DK %Drafted agrees.

#### Full-field decomposition — contest 192444379 (field_miner 0.4-review; coverage standings_only; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Entries 31 (31 complete lineups); winning score 140.6; multi-entry contest: False.
- Duplication: 31 distinct lineups; 0.0% of entries sat in a duplicated lineup; max copies 1; the winning lineup had 1 copy. Copies histogram: {1: 31}.
- Salary-usage and stack tables unavailable at this coverage tier (no salary file); re-run at full coverage if the slate salary CSV or the slate's DKEntries upload file (which embeds the salary block) surfaces.
- SP-pair field share (top): Matthew Boyd/Taj Bradley 32.3%, Davis Martin/Taj Bradley 29.0%, Matthew Boyd/Shane Bieber 12.9%, Davis Martin/Rhett Lowder 9.7%.
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
- Chalk (top-5 %Drafted): Chris Sale 54.92%, Max Meyer 40.41%, Wyatt Langford 37.82%, Ezequiel Duran 35.23%, Fernando Tatis Jr. 28.5%.
- Diagnostics: salary join n/a (standings_only); ownership recompute max diff 0.0 pts; parse OK; DK %Drafted agrees.

#### Full-field decomposition — contest 191506960 (field_miner 0.4-review; coverage standings_only; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Entries 23 (23 complete lineups); winning score 154.0; multi-entry contest: False.
- Duplication: 23 distinct lineups; 0.0% of entries sat in a duplicated lineup; max copies 1; the winning lineup had 1 copy. Copies histogram: {1: 23}.
- Salary-usage and stack tables unavailable at this coverage tier (no salary file); re-run at full coverage if the slate salary CSV or the slate's DKEntries upload file (which embeds the salary block) surfaces.
- SP-pair field share (top): Kyle Harrison/Max Meyer 21.7%, Chris Sale/MacKenzie Gore 17.4%, Chris Sale/Max Meyer 13.0%, Chris Sale/Ian Seymour 13.0%.
- Chalk (top-5 %Drafted): Chris Sale 52.17%, Kyle Stowers 47.83%, Max Meyer 43.48%, Jonathan Aranda 34.78%, Kyle Harrison 34.78%.
- Diagnostics: salary join n/a (standings_only); ownership recompute max diff 0.0 pts; parse OK; DK %Drafted agrees.

#### Full-field decomposition — contest 191507209 (field_miner 0.4-review; coverage standings_only; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Entries 150 (150 complete lineups); winning score 157.9; multi-entry contest: True.
- Duplication: 150 distinct lineups; 0.0% of entries sat in a duplicated lineup; max copies 1; the winning lineup had 1 copy. Copies histogram: {1: 150}.
- Salary-usage and stack tables unavailable at this coverage tier (no salary file); re-run at full coverage if the slate salary CSV or the slate's DKEntries upload file (which embeds the salary block) surfaces.
- SP-pair field share (top): Chris Sale/Will Warren 19.3%, Chris Sale/MacKenzie Gore 13.3%, Chris Sale/Max Meyer 10.0%, Kyle Harrison/Max Meyer 6.0%.
- Chalk (top-5 %Drafted): Chris Sale 58.67%, Paul Goldschmidt 34.0%, Jose Caballero 32.0%, Will Warren 31.33%, Amed Rosario 30.67%.
- Diagnostics: salary join n/a (standings_only); ownership recompute max diff 11.34 pts; parse OK; DK %Drafted table short 24.6 pts (DK omits multi-position rows; lineup-derived ownership used).

#### Full-field decomposition — contest 191507213 (field_miner 0.4-review; coverage standings_only; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Entries 242 (242 complete lineups); winning score 155.0; multi-entry contest: True.
- Duplication: 242 distinct lineups; 0.0% of entries sat in a duplicated lineup; max copies 1; the winning lineup had 1 copy. Copies histogram: {1: 242}.
- Salary-usage and stack tables unavailable at this coverage tier (no salary file); re-run at full coverage if the slate salary CSV or the slate's DKEntries upload file (which embeds the salary block) surfaces.
- SP-pair field share (top): Chris Sale/Max Meyer 14.5%, Chris Sale/MacKenzie Gore 10.3%, Chris Sale/Will Warren 9.5%, Max Meyer/Will Warren 7.4%.
- Chalk (top-5 %Drafted): Chris Sale 49.17%, Max Meyer 39.67%, Will Warren 28.93%, Seiya Suzuki 28.1%, Nico Hoerner 26.45%.
- Diagnostics: salary join n/a (standings_only); ownership recompute max diff 9.51 pts; parse OK; DK %Drafted table short 9.5 pts (DK omits multi-position rows; lineup-derived ownership used).

#### Full-field decomposition — contest 191507220 (field_miner 0.4-review; coverage standings_only; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Entries 110 (110 complete lineups); winning score 155.25; multi-entry contest: True.
- Duplication: 110 distinct lineups; 0.0% of entries sat in a duplicated lineup; max copies 1; the winning lineup had 1 copy. Copies histogram: {1: 110}.
- Salary-usage and stack tables unavailable at this coverage tier (no salary file); re-run at full coverage if the slate salary CSV or the slate's DKEntries upload file (which embeds the salary block) surfaces.
- SP-pair field share (top): Chris Sale/Will Warren 20.0%, Chris Sale/MacKenzie Gore 15.5%, Chris Sale/Max Meyer 10.9%, MacKenzie Gore/Max Meyer 7.3%.
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
- Chalk (top-5 %Drafted): Jacob Misiorowski 55.37%, Cam Schlittler 30.51%, Jacob deGrom 28.25%, Jo Adell 21.47%, Marcell Ozuna 20.34%.
- Diagnostics: salary join n/a (standings_only); ownership recompute max diff 3.96 pts; parse OK; DK %Drafted table short 6.8 pts (DK omits multi-position rows; lineup-derived ownership used).

#### Full-field decomposition — contest 191488366 (field_miner 0.4-review; coverage standings_only; deterministic review proxy / observed outcome; not ROI, win rate, or a probability claim; never auto-applied)

- Entries 297 (297 complete lineups); winning score 189.4; multi-entry contest: True.
- Duplication: 297 distinct lineups; 0.0% of entries sat in a duplicated lineup; max copies 1; the winning lineup had 1 copy. Copies histogram: {1: 297}.
- Salary-usage and stack tables unavailable at this coverage tier (no salary file); re-run at full coverage if the slate salary CSV or the slate's DKEntries upload file (which embeds the salary block) surfaces.
- SP-pair field share (top): Jacob Misiorowski/Jacob deGrom 12.8%, Cam Schlittler/Jacob Misiorowski 12.1%, Jacob Misiorowski/Ranger Suarez 6.4%, Jacob deGrom/Ranger Suarez 5.4%.
- Chalk (top-5 %Drafted): Jacob Misiorowski 55.56%, Jacob deGrom 31.31%, Cam Schlittler 27.95%, Jo Adell 21.21%, Logan O'Hoppe 18.86%.
- Diagnostics: salary join n/a (standings_only); ownership recompute max diff 2.02 pts; parse OK; DK %Drafted table short 3.4 pts (DK omits multi-position rows; lineup-derived ownership used).

### Gaps to backfill for A-005

- Slate date: inferred, not confirmed via a salary file.
- Entry fee, payout structure, paid places, cash line, seats, Ben's own Entry IDs: not captured.
