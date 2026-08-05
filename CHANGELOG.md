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

## 2026-08-05 — R74: three silent failures at the archival tooling's edges

### Fixed

- **R74(a) — a mine with no contest identity is refused, not placeholdered
  (P2).** `update_registry` resolved its dedupe key as
  `mined["contest_id"] or meta.get("winning_entry_id", "unknown")`, and
  `.get(key, default)` never returns the default when the key EXISTS as None —
  which is exactly what a mine with no winner produces. So the key came out None,
  `contests_mined` accumulated JSON nulls, and a SECOND identityless mine was
  silently skipped as already-mined because None was already in the list. A
  registry entry with no contest identity records nothing and cannot be deduped
  against anything, so it now raises naming `--contest-id` as the fix rather than
  folding in under a placeholder. A winner's entry id still identifies a mine that
  has no contest id, which is the case the fallback was written for.
- **R74(b) — the inbox contest-ID regex is anchored (P2).** `re.compile(r"(\d{9})")`
  used with `.search` matched the first nine digits of any longer run, so an entry
  id or a timestamp in a filename could yield a real entered contest ID and mark it
  pulled. That is the one direction `awaiting_standings` exists to prevent: a
  contest wrongly marked pulled is a contest nobody goes back for.
  `(?<!\d)(\d{9})(?!\d)` requires the run to be exactly nine digits.
- **R74(c) — `scan_entered` reads filled rows only, as its docstring always
  said (P2).** It harvested a Contest ID off every row that had one, including the
  blank reserved rows a DKEntries template carries, which enrolled never-entered
  contests into the pull list. A filled row now needs both a digit Entry ID and at
  least one non-empty roster cell. Two signals rather than one because either alone
  is weak, and a file with no recognizable roster columns falls back to the Entry ID
  alone so an unexpected DK template degrades to the previous behavior instead of
  silently emptying the pull list.

### Tests

- Six new tests in a new `MinerEdgeIntegrityTests`; the pin moves 699 → 705. The
  registry refusal, a winner id still identifying a mine, and two identityless
  mines being unable to collide because neither is accepted; the anchored regex
  against a real nine-digit id, three longer runs, and an id embedded in a longer
  name; a template carrying one entered row and two reserved ones (including the
  entry-id-but-no-roster shape) enrolling only the entered contest; and the
  unrecognized-header fallback.
- Mutation-checked three ways, one per part: restoring `.get(key, "unknown")` fails
  the refusal and collision tests, unanchoring the regex fails all three long-run
  cases, and harvesting every row again fails both scan tests.

### Verified

- `PASS  v2.26.0  26 modules  705 tests` on the pinned container stack.

---

## 2026-08-05 — R30(b) + R50: the two ends of the same lie about fees

### Fixed

- **R30(b) — money flags with no resolvable own entry ids now fail instead of
  no-opping (P1).** `--entry-fee`, `--winnings` and the new `--paid-places` are
  consumed only inside the own-results stage, which runs only when own entry ids
  resolve, and those are harvested from `outputs/<date>/upload_manifest.json` —
  which existed for 4 of the 10 backfilled dates. On the other 6 the mine printed
  no own-results line, exited 0, and left `entry_fee` null with nothing said. It
  cost ARCHIVE a full pass. Supplying money for a contest whose entries cannot be
  identified is a caller error, so it now exits
  `EXIT_MONEY_WITHOUT_OWN_ENTRIES` (7), names which flags were supplied, names the
  manifest path it looked for, and names the way out (`--my-entry-ids`, sourced
  from the entry history's `Entry_Key` column). A mine with no money flags is
  untouched, which is most of them.
- **R50 — the ledger block reports what it actually has (P2).** The block chose
  between two sentences on `net is not None`, so "fees and winnings not supplied"
  printed whenever the net line was absent — including when the fee WAS supplied
  and only the winnings were missing. That is the common case: every A-029 contest
  and all 94 of A-030..A-034, $35.87 of captured fees, each carrying the false half
  permanently in the archive. A later reader asking "which contests have a known
  cost" concluded wrongly. There are four states now and each gets its own
  sentence: both, fee only, winnings only, neither. Same class as R38 one layer
  down.
- **R30(a) follow-through: the paid line reaches the permanent block.** It shipped
  into `own_results.json` earlier today; what makes a rank-1 finish gradeable as a
  seat belongs in the archived block too, so the block now carries paid places, the
  observed breadth, and how many own entries finished inside the paid line.

### Tests

- Eight new tests in a new `MinerMoneyHonestyTests`; the pin moves 691 → 699.
  Three drive the CLI in a subprocess: a money flag with no resolvable own ids
  exits 7 and the message names the flag, the manifest and the remedy; every one of
  the four money flags is covered; and an ordinary no-money mine still exits 0, so
  the guard cannot fire on the common path. Five pin the block's wording state by
  state, including that a supplied fee is never reported as not supplied, and that
  the paid line reaches the block.
- Mutation-checked: restoring the old two-way sentence fails three of the wording
  tests; removing the guard fails all four CLI cases.

### Verified

- `PASS  v2.26.0  26 modules  699 tests` on the pinned container stack.

---

## 2026-08-05 — R30(a): the archive can record how many places a contest paid

### Fixed

- **R30(a) — `paid_places` reaches a mined record, and the allocator stops
  returning UNRESOLVED (P1).** Three things had to be true at once and none was:
  the miner had no flag, `own_results` had no field, and the only consumer,
  `posture_allocator.classify_tier`, reads `paid_places` off a contest dict the
  archival path never populated. So every archived contest classified UNRESOLVED,
  and the archive's first two rank-1 satellite finishes could not be graded as
  seats. Ben's entry-history export has carried the numbers since 2026-07-29,
  parked in `data/reference/dk_contest_paid_places.json` for 100 contests
  specifically because no CLI could read them.
  `summarize_own_entries` now takes `paid_places` and records it alongside
  `payout_breadth_observed` (only when both it and `field_size` are real) and
  `cashed_entries` (own entries finishing inside the paid line). The no-match
  early return carries the field too, so a contest whose own entry ids did not
  resolve no longer looks like a contest with no paid line.
  `--paid-places` sets it per contest and `--paid-places-from <json>` reads it in
  bulk, accepting both the flat `{contest_id: {...}}` shape and the `contests`-wrapped
  shape the parked export uses, so a 100-contest re-mine is one command instead of
  one hundred. An explicit flag wins over the file.
  The loader never raises and never goes quiet. A missing file, an unreadable one,
  a contest the export does not cover, a row with no `paid_places`, and a
  non-integer value each resolve to `(None, why)` and the miner prints the note.
  That distinction is the point: a file parked where nothing reads it is exactly
  the state this closes, so "the export did not carry this contest" and "the
  export was never read" have to be different sentences.

### Not this commit

- **The DATA half of R30(a) is still open and is Ben's.** `paid_places` coverage
  ends at the 2026-07-28 entry-history export, so none of the 94 contests mined on
  2026-08-04 carries a paid line and the 3.16 cash-line finding stays ungradeable.
  The tool half shipping means a fresh export now has somewhere to go: one
  `--paid-places-from` re-mine backfills the archive. Until that export lands, the
  100 already-parked contests are what can be backfilled. Noted on R30.
- **No re-mine was run.** This session is DEV and the archive is ARCHIVE's surface;
  nothing under `data/archive/`, `data/standings/` or `ledger/` was touched.

### Tests

- Seven new tests in a new `MinerPaidPlacesTests`; the pin moves 684 → 691. The
  item's done-when is driven end to end rather than asserted about: `classify_tier`
  is shown returning UNRESOLVED on a field-size-only contest and a real tier once
  the mined summary's `paid_places` is handed to it, with `paid_places == 1`
  resolving to winner-take-all, which is what a one-seat satellite is. Plus the
  observed breadth and cashed-entry count on a 53-entry one-seat contest, omission
  recording unknown rather than a guess, the no-match record keeping its paid line,
  both accepted file shapes, one assertion per unreadable case, and the real parked
  export resolving a real archived contest id, pinned against the file itself
  rather than a fixture.
- Mutation-checked: severing `paid_places` from the record fails the record test
  and the allocator done-when test; collapsing the loader's miss into a generic
  note fails the case-by-case test.

### Verified

- `PASS  v2.26.0  26 modules  691 tests` on the pinned container stack.

---

## 2026-08-05 — R58(a)(b): a doubleheader's legs stop collapsing onto one start

### Fixed

- **R58(a) — each pasted leg carries its own start (P1).** A DK draftgroup prices
  ONE leg of a doubleheader and `salary_game_times` is keyed on `AWAY@HOME`, so
  `resolve_paste_to_feed` stamped every pasted leg with the same start. Downstream
  `_select_slate_legs` tie-breaks on `game_date_utc` against that same salary
  start, so with both legs carrying an identical stamp it kept whichever leg was
  pasted FIRST. Reproduced end to end on a 9:38 PM night draftgroup: it confirmed
  the **1:05 PM leg's batting order**, the night-only starters were absent from the
  pool, the rested matinee bats were confirmed, and the whole thing exited 0.
  The date still comes from the salary file, which is authoritative for the slate
  and carries a full date. Only the TIME OF DAY comes from the paste, which is the
  one thing the paste knows per leg and the CSV cannot, and **only for a matchup
  pasted more than once** — a single-leg game keeps the salary start verbatim, so
  the existing "lock times come from the salary file, the paste's clock is a
  cross-check" contract is untouched.
  A matchup whose legs cannot be told apart by clock is a BLOCKER and writes no
  game, because two indistinguishable legs mean the selector has to pick
  arbitrarily, which is the failure being closed.
  The clock cross-check also stopped firing on the wrong leg. On a doubleheader the
  non-priced leg's clock differs legitimately, and the old single-leg wrong-slate
  warning fired on it while the real leg was silent. The multi-leg case now names
  which leg the salary file prices, and reserves a warning for the case that
  actually is a wrong-slate signal: no pasted leg matching the priced start at all.
- **R58(b) — the three team-keyed extractors leg-select, like the status map
  already did (P1).** `extract_opposing_probables`, `extract_batter_hands` and
  `extract_opp_throws_from_lineups` all write into a TEAM-keyed dict while
  iterating the feed's games, so two legs of one matchup were last-write-wins. The
  status map and the odds packet route through `select_one_leg_per_matchup` (F18)
  and these did not, so **the same feed produced a leg-correct status map and a
  leg-wrong platoon view**. Reproduced: a matinee draftgroup took the night
  starter's name, MLBAM id and throw hand, which flips the platoon view for every
  hitter on that side and feeds the wrong arm's quality into F4.
  All three now take an optional `salary_game_times` and route through one shared
  `_legs_for_extraction`, which delegates to `_select_slate_legs`. Omitting the
  argument is exactly the previous behavior. `build_slate_pool` passes it at all
  three call sites.
- **A dropped leg's reason now describes the dropped leg (P2, found by the
  reproduction).** `select_one_leg_per_matchup` built one `reason` explaining why
  the KEPT leg won and stamped it on every dropped record, so a matinee dropped in
  favour of a night leg carried `"matched salary start <night time>"` — a true
  sentence about a different leg and a false one about the record holding it. That
  exact text is quoted in R58's What line as evidence, which is how it surfaced. The
  reason is now per-dropped-leg and states how far off that leg is.

### Declined in this commit, with reasons

- **R58(c), the RotoWire per-leg order, is NOT built.** The filed fix is "key
  per-leg orders by (team, clock)", and the RotoWire schema carries no clock at
  all: `to_platoon_schema` emits `abbrev`, `status`, `page_updated`, `vs_RHP`,
  `vs_LHP`. Doing it means teaching the regex parser to capture a per-game clock,
  widening the emitted schema, and updating `build_projected_order` — in the same
  regex-over-live-HTML parser that still has no frozen real-page fixture (R65
  declined that half; it sits on R90 with the hand step named). Changing that
  parser's extraction surface without a fixture of the page it parses is how a
  silent-empty regression ships. It is scoped, dated and noted on R58.
- **R58(d), the same-venue weather window, is NOT built.** Independent surface
  (`fetch_slate_bundle`'s fetch window), no interaction with (a) or (b), and it
  wants a decision about whether the second leg gets its own window or the first
  leg's window is widened to cover both. Noted on R58.
  Both remaining parts affect a DH slate only, and neither is in the
  wrong-lineup-reaches-the-pool class that (a) and (b) were.

### Tests

- Eight new tests; the pin moves 676 → 684. Five in a new
  `DoubleheaderPastedLegTests` drive the filed reproduction through the real paste
  path with a synthetic night draftgroup: each leg gets its own start and the
  9:38 PM file keeps the night batting order and the night arm, the doubleheader is
  named instead of a false wrong-slate warning, indistinguishable legs block and
  write no game, a paste where NO leg matches the priced start is still reported,
  and a single-leg game still takes its start from the salary file with its
  cross-check intact. Three in `DoubleheaderLegTests`: the extractors take the
  priced leg's arm and hand where the un-argumented call takes the wrong leg's, a
  call-graph pin that all three route through one `_legs_for_extraction` and that
  it routes through `_select_slate_legs` (extending F18's existing selector check,
  so a fourth extractor cannot be written the old way), and the dropped-leg reason.
- Mutation-checked four ways: re-stamping every leg with the salary start fails the
  per-leg test, dropping the inseparable-legs blocker fails the block test, making
  `_legs_for_extraction` ignore its argument fails the extractor test, and
  restoring the old dropped-leg wording fails the reason test.
- One regression caught mid-change and worth recording: deriving the start from the
  paste clock and then handing that derived value to `_cross_check_clock` compares
  the clock against a number computed from itself, which agrees by construction and
  silenced the wrong-slate detector entirely. The existing
  `test_a_clock_disagreement_is_reported_as_a_wrong_slate_signal` caught it. The
  cross-check reads the salary start, always.

### Verified

- `PASS  v2.26.0  26 modules  684 tests` on the pinned container stack. Golden
  replay digests unmoved.

---

## 2026-08-05 — R37 decision input: the feasibility gate is answered, and a probe that reproduces it

### Added

- **`tools/stack_shape_probe.py`.** The 2026-08-04 regrade of the field-shape
  analysis put one gate in front of any `primary_stack_min_size` decision: on thin
  slates, is our large "3 or fewer primary" share a FEASIBILITY outcome (the team
  cap crossed with `max_shared_players` leaving no room) or a solver CHOICE? That
  question is answerable by measurement and was being answered by reading the
  constraint set. The probe forces `stack_constraints` at min_size 3, 4 and 5
  against every team with at least five rostered hitters, reports how many teams
  admit a solution, and reports the best objective reachable under each floor
  against the unconstrained optimum on the same pool. It exists as a tool rather
  than a one-off script because the same measurement has to be re-run after any
  floor lands and on any slate whose width is unusual.
  It measures what the ENGINE can build and what a constraint costs, which is the
  half the archive cannot see. It says nothing about what a shape is worth in a
  contest; that evidence is in the archive analyses, conditioned on archetype.

### The gate, answered

Five staged Classic salary files at 3, 3, 4, 6 and 8 games:

- **It is choice, not feasibility.** A 5-primary lineup is feasible on 100% of
  stackable teams at every width, thin slates included (6/6, 6/6, 8/8, 12/12,
  16/16). Nothing in the constraint set produces the low-primary share.
- **The objective drifts away from stacking as the slate widens**, picking primary
  5, 3, 3, 3 and 2 across those five files. A correlation-free mean-max solve
  cherry-picks harder the more teams it has. On the two 3-game files it landed on
  5 once and 3 once, so even the thin-slate outcome is incidental.
- **A floor is cheap.** Floor-4 costs 0.00% to 0.76% of the unconstrained best;
  floor-5 costs 0.00% to 1.55%, worst case on the 6-game file.
- **The secondary shape may not need its own control, which shrinks R37.** Forcing
  floor-5 produces the shape the archive prefers for that archetype as a
  by-product of slate width: an even 5-1-1-1 / 5-2-1 split on the 6- and 8-game
  files (where mini-MAX lives, and where the archive's strongest shape is the
  lone-5 at +3.6pp), and mostly 5-2-1 on the 3- and 4-game files (where the WTA
  satellites live, and where 5-2-1 over-wins its share). 5-3, at-share everywhere
  in the archive, appears only on the thin files and never at 6 or 8 games.

Two caveats travel with every number: this is single-lineup feasibility, so a
portfolio floor still has to satisfy `max_primary_stack_exposure_pct` and
`max_shared_players` across N entries; and with no Savant CSVs supplied the
Floor/Ceiling multipliers are uniform, so the cost column is the constraint's
salary-and-position price rather than a variance-aware one. The probe takes the
enrichment CSVs for the second.

### Not decided, and not built

R37 stays open and stays Ben's. The dated note on that entry carries the
measurement above plus a recommendation on the table: a universal
`primary_stack_min_size = 4` baseline (breadth-independent, because the floor is
nearly free at the paid line and positive at the top end), raised to 5 only on the
narrow-breadth postures, with a partial five-stack quota rather than a hard floor
on cut-line satellites, and no cash-game claim at all because the archive holds
zero cash contests and no paid-places coverage since 2026-07-28. Nothing in this
commit changes a control, a default, or a posture. No `Decided` entry, because no
decision has been made.

### Verified

- `PASS  v2.26.0  26 modules  676 tests` on the pinned container stack. No test
  count change: the probe adds no behavior to the engine and its output is a
  measurement, not a gate.

---

## 2026-08-05 — R59: the feed merge speaks one team-code vocabulary, and fills fields instead of replacing sides

### Fixed

- **R59(a) — the merge key normalizes both sides to DK codes (P1).**
  `merge_feeds` keyed games as `f"{away}@{home}"` off raw `team_abbrev`. The paste
  is DK-coded, because the salary file is authoritative for identity; the MLB Stats
  API is not, and ships `AZ` for Arizona (plus FanGraphs' `WSN`/`TBR`/`CHW`/`KCR`/
  `SDP`/`SFG` on other paths). Reproduced on a pasted SD side of SD@ARI with the
  ARI side still TBD: the API's copy keyed `SD@AZ`, missed the merge, was
  **appended as a second game**, and `merge_report` reported that as
  `games_added_from_api` — a success. The pasted ARI side stayed at zero hitters
  while the API's nine sat in the phantom game. `_select_slate_legs` then
  normalized (it always did), saw one matchup twice, and dropped one as a
  doubleheader leg. A real confirmed lineup disappeared wearing the reason
  "leg selection". `merge_feeds` was the ONLY place in the pipeline not
  normalizing, and its own downstream consumer did.
  Both sides now go through `to_dk_abbrev`, the merged side keeps the paste's DK
  code, and `merge_report` gained `api_keys_normalized` so an operator can see
  `SD@AZ -> SD@ARI` happened rather than wondering why an expected game was not
  added.
- **R59(b) — a side fill merges fields; a pasted probable is kept and the
  disagreement is reported (P1).** The fill replaced the whole side dict. "The
  paste posted no batting order for this side" is not the same fact as "the paste
  said nothing about this side": a pasted probable with no order is the
  late-scratch-replacement case, and it is a fact Ben typed. Reproduced: a pasted
  `Replacement SP` was silently displaced by the API's stale `Scratched SP`, which
  is R32 paste-primacy inverted, and `merge_report` said only
  `sides_filled_from_api`.
  The fill is now per field. The API supplies the batting order and
  `lineup_status`; a paste-named `probable_pitcher` is kept; any other API field
  lands only in a slot the paste left empty. `merge_report` gained
  `fields_filled_from_api` (so a side that took only a probable is distinguishable
  from one that took an order) and `probables_kept_from_paste`, which names the
  kept arm and the API's disagreeing one, because the whole point of the case is
  that the operator needs to see the call was made.

### The team-code boundary moved, and why that was not optional

- **New module `mlb_engine/team_codes.py`,** holding `DK_ABBREV_REMAP`,
  `MLB_TEAM_NAME_TO_DK`, `to_dk_abbrev` and `team_name_to_dk_abbrev`.
  `live_data_adapters` re-exports all four, so every existing caller, import path
  and test is unchanged.
  The filed Fix says to "normalize both sides through `to_dk_abbrev` (the import
  already exists in the file)". **It does not** — that is a correction to the
  entry; `tools/lineups_from_paste.py` imported no such thing. And adding the
  obvious import would have broken a different contract: `live_data_adapters`
  imports `urllib.request` at module scope, so taking three lines of dict lookup
  from there pulls a live HTTP client into the import graph of a tool whose
  zero-network property is a stated contract with a test. Measured, not assumed:
  the import added `urllib.request`, `http.client`, `socket` and `ssl` to that
  graph. Normalizing a team code has nothing to do with fetching one, so the pure
  data and the two pure functions moved to the network-free side of the line.
  This is the first half of **R82** ("one team-code boundary with an unknown-code
  report"). R82 still owns the second half: a code that fails to normalize passes
  through unchanged and silently matches nothing, which is how WSH once filled 0
  of 9 hitters and reported success. A dated note says so on that entry.

### A guard that could not fail, found by mutation

- **`test_the_tool_reaches_no_network` is single-file and would not have caught
  this.** It parses `lineups_from_paste.py` and `paste_lineups.py` for imports in a
  forbidden set; `live_data_adapters` is not in that set, so the urllib-pulling
  import passes it. A transitive check was added — and the first version of that
  check was also wrong, in a way worth recording: it diffed `sys.modules` in-process,
  and by the time it runs the rest of the suite has already imported
  `urllib.request`, so the diff came back empty and it passed under the very
  mutation it existed to catch. It now runs the probe in a fresh interpreter via
  subprocess. Both failures were found by running the mutation, not by reading the
  code.

### Tests

- Nine new tests; the pin moves 667 → 676 and the module count 25 → 26 (counted off
  disk, so it moves on its own). `merge_feeds` had **no coverage of any kind**
  before this, which is how both halves shipped, and it is a pure function on two
  feed dicts so the tests drive it at that grain: the AZ/ARI case end to end with
  the report assertions, all seven remapped codes, a pasted probable surviving a
  fill with the disagreement reported, an uncovered side still taking the API
  probable, a covered side untouched, an API-only field filling an empty slot and
  being named, a never-mentioned game still added whole on a normalized key, and a
  missing team code skipped rather than crashing. Plus the transitive zero-network
  probe.
- Mutation-checked three ways: an unnormalized merge key fails 9 assertions,
  restoring the wholesale side replacement fails the pasted-probable test, and
  importing `to_dk_abbrev` from `live_data_adapters` fails the transitive probe.

### Verified

- `PASS  v2.26.0  26 modules  676 tests` on the pinned container stack.

---

## 2026-08-05 — R65: one ET calendar authority, and a RotoWire parser that refuses to fail empty

### Fixed

- **R65 — slate-date gating reads the calendar the schedule runs on (P1).**
  Baseball's day is an Eastern day; this container's day is a UTC day, and three
  callers computed slate dates from `date.today()` or an approximation. Confirmed
  by injecting instants rather than by reading the code:
  at 00:15 UTC — 8:15pm ET, mid-slate — `build_slate`'s RotoWire gate compared
  `args.date` against a local today that had already rolled over. A build for
  **tonight's** slate fell out of RotoWire's today/tomorrow window entirely and
  skipped the merge in silence, leaving the platoon staleness clock uncleared. A
  build for **tomorrow's** ET slate resolved to `"today"`, fetching the wrong ET
  day's page and stamping it `collected_date=args.date` — wrong-day batting orders
  wearing a fresh date, which defeats the staleness rule from the inside. Both
  fire every night between 8pm ET and midnight, which is a normal build window.
  `fetch_slate_bundle._today_et` approximated ET as a hardcoded UTC-4 under the
  comment "EDT covers the MLB season"; in EST months the offset is UTC-5, so any
  instant in the 04:00–05:00 UTC window returned tomorrow's date. Reproduced at
  2026-12-01T04:30Z: UTC-4 said 12-01, the tz database says 11-30.
  `mlb_engine/repo_env.py` is now the single ET authority — `now_et`, `today_et`,
  `et_day_offsets` — on `zoneinfo`, which is stdlib, so the file stays
  dependency-free and the tools that carry their own loaders can still import it.
  All three callers go through it. Each takes an injectable instant, so the
  rollover is pinnable without a clock; a naive datetime raises instead of being
  assumed into a zone, because guessing the zone is how this started.
  Two things beyond the filed line. `et_day_offsets` returns the pair from ONE
  clock reading: the gate called `date.today()` twice and could straddle midnight
  into a non-adjacent pair. And the out-of-window branch now prints why it
  declined — it was the silent one, indistinguishable in the build log from
  "RotoWire had nothing".
- **R65 — the RotoWire parser refuses to emit an empty document (P1).** It is
  regex over live third-party HTML, so a layout change surfaces as an empty parse,
  not an error, and an empty platoon file is worse than no file: the next build
  merges it, counts zero lineups, and reports a successful fetch. `parse_lineups`
  now fills a structural report (page bytes, raw blocks, games, teams with and
  without a posted order) and `check_parse_floor` raises `RotoWireParseFloor` on
  two collapse signals. `main()` exits 2 and writes nothing; `build_slate`'s
  existing handler turns it into "rotowire fetch unavailable (...); using FanGraphs
  reference only", which is the documented fallback rather than a new failure mode.
  `fetch_rotowire_platoon` also stops defaulting `collected_date` to the container's
  calendar, and carries the parse report on the document it returns.

### Where this diverges from the filed Fix, and why

- **The ≥24-team parse floor was NOT shipped as filed.** The entry asks for a
  "≥24-team parse floor and refuse to write an output below it". That number is a
  full slate with every lineup posted — the live page carries 30 on a 15-game day —
  and as an absolute floor it refuses correct parses routinely: `build_slate` runs
  hours before lock, when most clubs have not posted, and a light 9-game day is 18
  teams even after they all have. A floor that fails closed on good data gets
  turned off, and the RotoWire merge is the thing that clears the platoon
  staleness clock, so turning it off has a cost. What shipped instead are two
  signals that cannot fire on legitimately thin data: **zero game containers on a
  page with real bytes in it** (the containers exist whether or not lineups have
  posted, so this is regex drift and nothing else), and **zero teams with a parsed
  order** (nothing to merge). The two raise different messages on purpose — "the
  layout moved" sends the operator to the regexes, "nothing to merge" sends them
  to the slate — and a test pins which diagnosis each input gets. `min_teams`
  remains as the knob for a caller that genuinely knows the page should be full;
  `--min-teams 24` reproduces the filed behavior for anyone who wants it.
- **The frozen real-page fixture is NOT in this commit.** The other half of R65's
  Fix ("freeze one real RotoWire page as a fixture") cannot be built from a Cowork
  session: the web-fetch tool returns markdown, and this parser is regex over raw
  HTML, so a markdown rendering is useless as a fixture and the alternate fetch
  paths that would return raw bytes are closed to this session by policy. A
  hand-written page would test my reading of the regexes rather than the parser,
  which is precisely the false comfort the item exists to remove — so the report
  wiring is pinned with a page built from the module's own constants and labeled
  as exactly that, and the real-page freeze carries a dated note on R90, which
  already owns the fixture (its entry names this fixture as riding R65). Same
  class as the `mlb-game-odds` key residual already on the Do-not-build list: a
  thing that needs a hand step outside Cowork.

### Tests

- Sixteen new tests; the pin moves 651 → 667 in all three places. Five in a new
  `EasternCalendarAuthorityTests` pin the authority at the boundary that broke: the
  8:15pm-ET instant, EST being UTC-5 with the retired approximation's answer
  asserted alongside the correct one, the offsets pair being adjacent at every
  hour tried, a naive datetime raising, and `fetch_slate_bundle` agreeing with the
  authority. Eight in `RotoWireParseFloorTests` cover the floor: regex drift and
  nothing-to-merge each raise with their own diagnosis, an early fetch before
  lineups post and a light 9-game day both pass (the two cases an absolute floor
  would have refused), `min_teams` works in both directions, an empty response is
  not misdiagnosed as drift, the parser's report counts games and skips the
  template block, and `collected_date` defaults through the authority. Three in
  `BuildSlateScriptTests`: the pure window helper against both ET and the pre-fix
  UTC dates, the call site driven with an injected clock and a stubbed fetch, and
  an AST check that the script kept its stdlib-only top-level imports.
- Mutation-checked, and **two of the four mutations initially survived**, which is
  the part worth recording. Reverting the call site to `date.today()` stayed green,
  because the pure helper and the authority were each pinned and the join between
  them was not — the R92 class, one commit after filing R92. It now has a
  behavioral test, whose frozen instant is deliberately a past date far from any
  run date and asserts that it differs from the container's calendar, because a
  frozen instant near today makes the container-clock mutation produce identical
  answers and pin nothing. Dropping the drift check also stayed green, because
  "0 game containers" is an accidental substring of the other branch's message;
  the assertion now targets wording unique to each diagnosis. Both mutations fail
  correctly now.

### Verified

- `PASS  v2.26.0  25 modules  667 tests` on the pinned container stack.

---

## 2026-08-05 — R55: the solver's id boundary holds one dtype, and the bank cache only records jobs it answered

### Fixed

- **R55(a) — every id-keyed control binds regardless of the Player_ID column's
  dtype (P1).** `determinism.stable_union` returns sorted STRINGS by contract and
  the solver looked the results up against `df['Player_ID']` taken raw. On any
  frame whose Player_ID arrives int64 — `runs/<id>/inputs/projections.csv`
  reloaded with a plain `read_csv`, or a `projections_override` built from a
  numeric column — nothing matched, and all three filed failures reproduced on
  one pool solved twice:
  a lock on a player who is demonstrably in the pool came back
  `locked_player_unavailable` with `proven_infeasible=True`, a dtype artifact
  wearing the label reserved for a proof; excludes no-opped, so a player passed
  in as excluded was rostered; and `bank_cache.extend_bank`, which locks each SP
  pair, **built 0 of 16 jobs while marking all 16 attempted and reporting
  `job_list_exhausted: True`** — an empty bank that reads as completed work. The
  string control built 8 of 16.
  `Player_ID` is now normalized to a stripped string once, in
  `_prepare_single_lineup_df`, before any control is matched against it, so
  `pid_to_var_idxs` is keyed the way `stable_union` emits. Every incoming id
  iterable is stringified at its lookup for the same reason — locks, the exclude
  set, penalized players, overlap references, stack-core blocklists and forbidden
  combos — through one `_known_pids` helper rather than six spellings of the same
  filter. The stack-feasibility pre-check now runs on the normalized frame too.
  The dtype was deciding strategy and doing it invisibly: neither the lock
  refusal nor the ignored exclude appeared anywhere in the certified output as a
  reduced pool.
- **R55(b) — `attempted` means answered, and an exception is not an answer
  (P1).** `extend_bank`'s `except Exception` handler recorded the job key as
  attempted-forever under a comment reading "an infeasible combination is data,
  not an error". But `build_single_lineup` returns `(None, None)` for
  infeasibility and never raises for it, so everything that actually reaches that
  handler — a NaN objective, schema drift, the dtype case above — is a defect a
  later slice can retry once the cause is fixed. Recording them made a
  systematically broken bank indistinguishable from a genuinely dry pool, which
  is the misdiagnosis the module's own F13 note exists to prevent, and the slice
  report counted only timeouts so nothing said otherwise.
  A job now enters `attempted` on exactly two answers: a lineup came back, or the
  solver reported `proven_infeasible`. A raised exception is counted per exception
  type in `raised_by_reason` with up to three verbatim `raised_examples`, and an
  empty return that proved nothing (a rejected incumbent, a roster-size mismatch,
  a control that could not be matched) is counted per solver status in
  `unanswered_by_status`. Both are left retryable. Timeouts keep their existing
  F13 treatment. `0 built / 16 attempted / exhausted` cannot recur without the
  report saying which of the three things happened.
  `BankCache.clear_attempted(conditions_sig)` is the maintenance hatch for a
  record poisoned before that distinction existed: `drop_stale_jobs` cannot help,
  because the conditions signature of a poisoned bank is correct. It clears the
  attempt record for one signature (or all, with no argument) and never touches
  candidates — real lineups are real whatever poisoned the attempt record, and
  `add` dedupes rosters so a re-run cannot double-count. It also had to be
  subtracted inside `save()`: that method deliberately unions memory with disk to
  protect concurrent slices, which would have silently reinstated every cleared
  key on the very next save. The subtraction applies once and then resets, so a
  clear is a one-time operator action rather than a permanent suppression.

### Filed rather than fixed here

- **R92 (new, P2/S) — `build_slate.py`'s bank warning for failed cache jobs is a
  dead read.** Found while wiring R55(b)'s counters:
  `build_slate.py:1376` and `:1382` build `bank_warnings` from
  `bank_report.get('jobs_failed')` and `bank_report.get('budget_exhausted')`, and
  `extend_bank` has never emitted either key (verified against the full return
  dict; `budget_exhausted` exists only on optimizer_v3's unrelated augmentation
  report, which is presumably where the reader was copied from). Both lines are
  unreachable, so the sliced path's failures have never reached a warning — the
  R51 class, a guard that cannot fail. R55(b) now emits the counters that warning
  wanted, which is exactly why this is filed and not folded in: choosing which
  counters surface, and how they interact with R64's clean/unknown verdict, is a
  decision with its own test, not a line to slip into this commit.

### What the reproduction corrected about the filed diagnosis

- **The poisoning path is the normal one, not the exception handler.** R55(b)
  reads as though the `except Exception` recorded the 16 dtype-broken jobs. It did
  not: `build_single_lineup` returned `(None, None)` and the loop's ordinary
  `if not status.get("timed_out"): cache.attempted.add(key)` — which ran BEFORE
  the roster was even checked — is what recorded them. The entry's own reasoning
  is what caught this ("an exception is never data"), and the fix needed both
  halves: the exception handler stops recording, and the normal path stops
  recording an empty return that proved nothing. Fixing only the handler would
  have left the reproduced case fully intact.
- **Line numbers had drifted:** the filed `optimizer_v3.py:816,984` are the lock
  loop and `build_single_lineup`'s `stable_union` call; `bank_cache.py:560` is the
  `except Exception`.
- **`jobs_attempted` in the slice report now means "answered", which is what it
  always claimed.** It counts keys in `cache.attempted` carrying this slice's
  suffix, so it tightened along with the recording rule. `attempted_this_slice`
  still counts jobs this slice tried. The two were interchangeable only while
  everything non-timeout was recorded.

### Tests

- Ten new tests; the pin moves 641 → 651 in all three places. Five in
  `SolverIdDtypeBoundaryTests` drive the reproduced int64 frame: a lock binds, a
  locked slot assignment binds, excludes bind, the same pool at two dtypes
  produces the same lineup and objective and returns string ids either way, and
  `extend_bank` builds the same jobs on both (the filed 0-of-16 case). Five in
  `BankCacheAnsweredJobTests` cover the recording rule: a raised exception is
  counted per reason with its message, stays out of `attempted` on disk as well as
  in memory, and the same cache builds once the cause is gone; an empty return
  that proved nothing is counted by status and stays retryable; a proven-infeasible
  job IS recorded and a second slice re-pays for nothing; `clear_attempted`
  survives a save and keeps every candidate; and it scopes to one conditions
  signature, is idempotent, and clears everything when called bare.
- Mutation-checked four ways. Removing the Player_ID normalization fails all five
  dtype tests. Restoring `cache.attempted.add(key)` in the exception handler fails
  the exception test. Recording every non-timeout return again fails the
  unanswered test. Dropping the `_cleared` subtraction in `save()` fails the
  persistence test — that last one is the mutation that matters most, because the
  in-memory clear looks correct on its own.
- Golden replay digests unmoved, verified: the replay frames carry string
  Player_IDs already, so normalization is a no-op there, and its jobs all answer.

### Verified

- `PASS  v2.26.0  25 modules  651 tests` on the pinned container stack.

---

## 2026-08-05 — R56: salary suppression bounds the bonus it counts, not the set of legal lineups

### Fixed

- **R56 — the lineup cap stops removing legal, projection-optimal lineups
  (P1).** `_build_single_lineup_scipy` put the per-player suppression bonuses in
  the objective AND added `Σ bonus·x ≤ SUPPRESSION_LINEUP_CAP` (0.75) as a
  constraint row. That row is a hard feasibility constraint on the roster, not a
  bound on a tiebreaker. MLB_Classic is explicit — "Salary suppression is a
  bounded tiebreaker only" — and the per-player bonus caps at 0.25, so any four
  role-elevation-tagged players at the cap sum to 1.0 and the solver could roster
  at most three of them no matter what they projected. Reproduced before
  changing anything, on one pool solved twice: four tagged bats that belong in
  the DK-optimal lineup together came back at ceiling **220.0** with suppression
  on and **250.0** with it off, three of four rostered instead of four, on an
  identical legal pool with 8000 of salary headroom. Punt-heavy role-elevation
  slates are the feature's use case and are exactly where four or more tagged
  players cluster.
  The cap now rides on one auxiliary continuous variable z: `z − Σ bonus·x ≤ 0`
  holds z at or below the rostered bonus sum, z's own upper bound holds it at or
  below `SUPPRESSION_LINEUP_CAP`, and z enters the objective at weight 1.0. The
  solver therefore counts exactly `min(Σ bonus·x, 0.75)` and no lineup leaves the
  feasible set. This is not "delete the cap": four tagged players still earn 1.0
  of raw bonus and the objective still counts only 0.75 of it, which is pinned by
  its own test.
  Two consequences that had to move with it. The incumbent verification rounded
  every variable before checking it against the constraint matrix; z is
  continuous, so rounding it would fail the integrality test at 0.75 and feed the
  check a value the solver never proposed — which would have rejected every
  time-limited incumbent on any slate carrying a suppression tag. Only the binary
  variables are rounded and checked now. And the returned objective summed the
  RAW per-player bonuses, which agreed with the solver only while the old
  constraint made disagreement impossible; it now counts the capped total, so the
  number lineups are ranked by is the number the solver maximized. The per-row
  `Suppression_Objective_Bonus` column stays raw — that is what the player
  earned — and the lineup carries `suppression_bonus_raw`,
  `suppression_bonus_counted` and `suppression_bonus_capped` in `attrs` so the
  difference is legible rather than inferred.
- **The two docstrings that overstated activation are corrected (docs).** The
  module's v3.8 block claimed `SALARY_SUPPRESSION:<trigger>` activates for all
  four of `metric_disconnect`, `role_elevation`, `late_news`, `environment`, plus
  a legacy `DIVERGENCE_LEVERAGE:value` fallback. `_compute_suppression_bonus`
  reads `role_elevation` and nothing else, which is what MLB_Classic authorizes
  ("Only confirmed role_elevation ... may activate it"), and it has never checked
  the legacy tag at all. `_has_suppression_tag`'s docstring repeated the same
  false claim about a function other than itself. The code was right and the
  prose was wrong, so the prose moved: the trigger tuple is documented as a
  parsing/labelling inventory, activation is documented as role_elevation alone,
  and the correction is dated in place. A build reading the old docstring would
  have expected three tags to do something they have never done.

### Tests

- Six new tests in a new `SalarySuppressionBoundedTiebreakerTests`; the pin moves
  635 → 641 in all three places. Suppression had **no test of any kind** before
  this (R79f), so the filed reproduction is the test rather than a synthetic
  stand-in: four tagged bats keep the legal optimum at 250.0 and all four are
  rostered, with an explicit assertion that 220.0 — the pre-fix suppressed
  ceiling — is not what comes back; the counted bonus is capped at 0.75 while the
  per-player column still reports 1.0; three tagged players at exactly 0.75 still
  count their full bonus, so the boundary is a boundary and not an off-by-one; a
  single tagged bat priced and projected identically to its alternatives wins the
  tie without moving the lineup's ceiling; only `role_elevation` activates, with
  the other three triggers and the legacy tag each asserted inert; and an
  untagged pool adds no auxiliary variable and no constraint row.
- Mutation-checked. Restoring the old constraint row fails three of the six;
  removing the cap (z unbounded, uncapped counted total) fails the
  capped-objective test; widening activation to any `SALARY_SUPPRESSION:` prefix
  fails the trigger test on all three inert tags.
- The golden replays are unaffected and their digests did not move: emergency-proxy
  rows carry no `Notes` and no `Salary_Suppression`, so `_compute_suppression_bonus`
  returns empty and the solver builds the same model it always did, with no z and
  no extra row. Verified, not assumed.

### Verified

- `PASS  v2.26.0  25 modules  641 tests` on the pinned container stack.

---

## 2026-08-05 — R57: the xwOBA correction stops overwriting a Base it did not produce

### Fixed

- **R57 — an operator-supplied Base survives the correction, and the documented
  remedy stops crashing the build (P1).** `_assemble_projection_frame` resolves
  `Base` per row from the caller's explicit `Base` or, failing that, from
  `AvgPointsPerGame`. It then handed the whole frame to
  `apply_xwoba_correction(base_in="AvgPointsPerGame", base_out="Base")`, which
  rewrote `Base = APPG × factor` for EVERY row unconditionally. Both filed halves
  reproduced exactly before anything changed:
  (a) a row carrying an explicit operator `Base` of 12.0 alongside APPG 10.0 at a
  matched factor of 1.15 came out of the front door at 11.5. The operator's number
  was gone with no warning and no counter.
  (b) a row carrying an explicit `Base` and NO APPG — which is verbatim what
  `live_data_adapters` tells the operator to do when a kept row has no average
  ("supply Base before run_slate") — took `NaN × factor`, and
  `validate_projection_factors` then rejected it as `Base contains nonnumeric
  values`. An uncaught `ValueError` at both approve legs, reachable by following
  the project's own printed remedy.
  The correction now runs under a mask computed from the PRE-correction Base
  source, which is the only moment the two are still distinguishable: rows whose
  Base came from APPG are corrected, rows where the caller supplied Base keep it.
  `apply_xwoba_correction` gained an `apply_mask` argument for that, and
  independently refuses to correct any row whose `base_in` is null, because
  `base_in × factor` is NaN there and a NaN Base is a crash one call later rather
  than a correction. Skipped rows are audited `applied=False` at a 1.0 factor, so
  the audit's `xwoba_correction` column is what actually multiplied the Base and
  not what would have. `enrichment["xwoba"]` gained `rows_corrected` and
  `rows_skipped_operator_base`, because a masked correction that reports only
  "applied: true" is the same silent no-op the v1.6 wiring guard exists to block.

### What the reproduction corrected about the filed diagnosis

- **The trigger needs a Savant CSV, not just APPG.** The entry reads "applies the
  correction whenever ANY row has APPG"; that is the inner condition. The whole
  block sits under `if savant_batting_csv or savant_pitching_csv:`, so a build with
  no expected-stats CSV was never exposed to either half. Confirmed by
  reproduction: the same rows that crash with a batting CSV supplied come through
  clean without one. This narrows who was exposed; it does not change the fix.
- **Line numbers had drifted.** The filed `execution_pipeline.py:2447` is now
  2518, and `projection_builder.py:317` is inside `apply_xwoba_correction`.
- **A third case sat on the same line, and it is why "supplied" had to mean more
  than `in (None, "")`.** A blank `Base` cell in a `projections_override` CSV
  arrives from pandas as NaN. `base in (None, "")` is False for NaN, so that row
  was treated as carrying an explicit Base: the APPG fallback that exists for
  exactly that row was skipped, and the row survived only because the correction
  then overwrote the NaN. Reproduced both ways — with a Savant CSV the buggy
  overwrite accidentally rescued it, and with no Savant CSV it crashed on
  `Base contains nonnumeric values` today, unrelated to the correction. Masking on
  "explicit Base supplied" without fixing this would have converted the accidental
  rescue into a crash, so a new `_is_blank` (None, whitespace-only, NaN) now
  decides the question and is pinned by test in both directions. This is folded
  into R57 rather than filed separately because it is not incidental to the Fix
  line: "mask on the pre-correction Base source" is unanswerable until "supplied"
  is defined, and the two readings disagree on this row.
- **The production golden replay was relying on the clobber to exercise the
  enrichment it exists to pin.** `GoldenProductionReplayTests` built its rows with
  `r["AvgPointsPerGame"] = r["Base"]` — a copy, leaving both keys set — precisely
  so the correction would not be structurally inert. Under the mask that pool
  reads as operator-supplied for every row, the correction went inert, and the
  certified leg stopped certifying (`KeyError: 'assignments_path'` out of
  `setUpClass`). The fixture, not the mask, was the thing out of step: the real
  intake front door `live_data_adapters._pool_row` emits `AvgPointsPerGame` and no
  `Base` at all. The copy is now a MOVE (`r.pop("Base")`), which is what production
  hands in, and **the frozen baseline did not move** — aggregates, enrichment
  counters and the entry-to-lineup assignment are all byte-identical, because the
  numbers were the same either way. No golden regeneration, and R87's pending
  decision is untouched.

### Tests

- Seven new tests; the pin moves 628 → 635 in all three places
  (`tools/audit.py`, `CLAUDE.md`, `skills/generate-lineups/SKILL.md`). Four in
  `ProjectionEnrichmentWiringTests` drive the filed reproduction through the real
  front door: the operator Base survives while the rest of the pool is still
  corrected (so this is a mask, not a disabled correction), the explicit-Base
  no-APPG row does not crash and leaves no NaN, a blank Base cell still falls back
  to APPG with and without Savant CSVs, and a row with neither Base nor APPG still
  raises. Three in `TestXwobaBaselineCorrection` pin the helper itself: a null
  `base_in` is never corrected to NaN, `apply_mask=False` rows keep their Base, and
  a misaligned mask raises instead of silently truncating.
- Mutation-checked against the true pre-fix state. Removing the mask alone fails
  the operator-Base test; removing both the mask and the null guard fails the
  operator-Base test and errors the no-APPG test, which is the pair of failures
  the filed reproduction predicted. Neither half is pinned only by the other.

### Verified

- `PASS  v2.26.0  25 modules  635 tests` on the pinned container stack
  (numpy 2.2.6 / pandas 2.3.3 / scipy 1.15.3).

---

## 2026-08-04 — R53 + R64: the certification gate and the delivery record stop attesting to things they never checked

### Fixed

- **R53 — the workflow lineup gate no longer passes vacuously on fabricated
  evidence (P1).** `_derive_workflow_gates`' pool-report-absent branch read
  `elif projected_order:`, and `projected_order` is the four-key SUMMARY dict
  `run_slate` always builds — truthy even at `requested: 0, applied_count: 0`. So
  every call without a `pool_report` certified `lineup_gate_passed=True` and wrote
  `"4 players carry a batting order"` into the immutable diagnostics: the len of a
  dict's KEYS, not a count of players. The designed None-blocks branch was
  unreachable. This is the F4 class — the 07-22 "certified with 0/9 lineups
  posted" incident — reopened on the API leg of the sanctioned front door;
  `build_slate.py` supplies a pool_report, which is exactly why the
  fabricated-evidence leg stayed invisible.
  The gate now reads real per-team counts of rows carrying a batting order, taken
  off the assembled projection frame by a new `batting_orders_by_team`. An empty
  frame yields an empty map, falls through to None, and blocks. The evidence
  string states the actual counts per team and flags any team under nine, and it
  says plainly what it still cannot know: a team with zero orders does not appear
  in the map at all, and without a pool report nothing distinguishes "excluded on
  purpose" from "missing". Pitchers carry no order and are absent by
  construction; zero, blank, `TBD` and NaN cells do not count.
  **Three fixtures were certifying on this hole and now declare the assumption.**
  `RunSlateFrontDoorTests.UNEVIDENCED` and both golden replays are
  emergency-proxy builds — rows carry `Player_ID` and `Base` only, no batting
  orders, no pool report — so they add `lineup_gate_passed` to `assume_gates`,
  which is the sanctioned, recorded escape hatch and the mechanism they were
  silently outside of. That is the fix working on its first contact with the
  suite, not a test being bent around it: three end-to-end builds were reading
  certified with no lineup evidence of any kind.
- **R64(a) — a delivery record with no relaxation evidence reads "unknown", not
  "clean" (P1).** `manifest_strategy_state` read one key,
  `bank_diagnostics["relaxations"]`. It is real on the self-built-bank path and
  absent on the production sliced one: `run_slate` strips `bank_diag` to
  `candidate_count` when `candidates_override` is supplied (the caller's record
  wins) and build_slate's own `bank_diagnostics` never carried a `relaxations`
  key. Missing evidence therefore printed `"clean"`, and CLAUDE.md's "a portfolio
  is clean when the relaxation counts are zero" is read at T-5 off exactly this
  field. Now the union of the places relaxations are actually recorded is read —
  both diagnostics holders, the `relaxations` block in each, and the top-level
  `*relax*` counters Showdown keeps there instead (R54's `relaxed_slots` /
  `overlap_relaxed_slots`) — and absence of evidence is `"unknown"` with an
  explicit `evidence: absent`. An empty `relaxations` block still means clean,
  because that is a report saying nothing was relaxed. `bank_warnings`, where the
  sliced path's failed cache jobs and slice-not-full-search notes land, travels on
  the record as evidence without driving the verdict: reduced search effort is not
  a relaxed control, and conflating them would trade one false label for another.
- **R64(b) — a Savant-enriched build no longer records
  `projection_tier="proxy"` (P1).** `_applied` required a `requested` key that
  only `f1`/`f4`/`f5` and `projected_order` carry. The Savant-fed blocks report
  their own shapes — `xwoba` an explicit `applied` flag over considered/matched,
  `ceiling` and `pitcher_ceiling` matched/unmatched, `value_guard` an `applied`
  flag with `clipped_count` — so every one returned None and the tier fell through
  to `proxy` on a fully enriched build. `_applied` now reads all three shapes, in
  precedence order, and still distinguishes the three states that matter: reached
  rows, ran and reached nothing, never requested. An `applied: True` block that
  matched zero players counts as reaching nothing.

### Tests

- Nine new tests; the pin moves 619 → 628. A new `LineupGateEvidenceTests` (6)
  covers R53: an all-empty-order frame blocks with None, a frame with no
  `Batting_Order` column at all blocks, `projections=None` blocks, the evidence
  states real per-team counts, a team under nine fails the gate, a supplied
  pool_report still wins, and the counter ignores pitchers, zeros, `TBD` and NaN.
  One assertion pins the old fabricated string out of the evidence for good.
  Three in `UploadReadyIsReservedTests` for R64: the sliced-path record reads
  `unknown` with `evidence: absent`, strategy_state reads `candidate_bank` and
  Showdown's top-level counters and treats a warnings-only block as relaxed while
  `bank_warnings` stays non-verdict-driving, and each Savant block shape reads as
  enriched while a zero-match block and an opted-out guard stay proxy.

### Verified

- `PASS  v2.26.0  25 modules  628 tests` on the pinned container stack.

---

## 2026-08-04 — R46 + R72: the export gates re-derive slate truth, and the locked-game exclusion fails closed

### Fixed

- **R46 — the confirmed-lineup contradiction check now exists in
  `verify_export`, and an unconfirmed team is named instead of skipped in
  silence (P1).** The 2026-08-03 incident was reproduced from the retained
  artifacts before anything was changed, and the reproduction corrected the
  filed diagnosis in a way worth recording: preflight's `check_feed` was never
  missing and is strict by default. Run against the build-time feed
  (`lineups_feed.json`, ARI `lineup_status: tbd`, 0 players) the delivered file
  exits 0. Run against the feed from 29 minutes later
  (`lineups_feed_v2.json`, ARI confirmed) the same file exits 2 and names Tyler
  Locklear in both entries — and the swapped file exits 0. Preflight's feed
  auto-resolution picks the fresher file on its own, so a re-run before upload
  would have caught it. The check was correct; its INPUT was stale, and nothing
  said so.
  So two things changed, neither of them the check's logic. First, `check_feed`
  is imported into `verify_export` — the tool whose entire subject is a file
  changed close to lock had no confirmed-lineup check at all, against the same
  feed it already resolves for the lock derivation. It now reproduces the
  failure on the delivered file and passes the swapped one, which was R46's
  stated done-when. Second, a rostered team with no confirmed lineup in the feed
  is reported by name with its slot count (`feed_unconfirmed_teams`), because
  that branch was pure silence and the silence is the whole incident: on the
  build-time feed it now prints `ARI (6 slots), CHC (2 slots), COL (3 slots),
  HOU (31 slots), TB (4 slots)` — the slots the all-clear did not cover.
  It stays SOFT deliberately. An unposted team before lock is normal, R27 ships
  on warn by design, and hard-failing here would block legal builds; the fix is
  to make the coverage gap loud and name what to re-check, not to invent a
  blocker. `--feed-lenient` reaches verify_export too, matching preflight.
- **R72(i) — the locked-game exclusion fails closed on an unmapped player
  (P2).** `_entry_candidate_compatible` tested
  `team_by_player.get(pid) in excluded_new_teams`; `.get` returns None for a
  player the map does not cover and `None in excluded_new_teams` is False, so
  every uncovered player walked through the one test that keeps a locked game
  closed. F15's sibling guard fails closed only when the map is empty
  ENTIRELY, and partial coverage is the real case: a game absent from the
  lineups feed leaves its platoon-filled players with no `PlayerLineupStatus`,
  hence absent from `player_team_by_id`, and its team absent from
  `locked_teams`. Once a game has locked, "I cannot tell which team this player
  is on" must not resolve to "admit him". Locked players stay admissible on
  their own locked team, as before.
  Because failing closed can now starve an entry, the generic "no compatible
  candidate for Entry ID X" grew the cause: a new
  `uncovered_locked_team_players` names the bank players the entry's team map
  cannot classify and the error says to refresh the feed. A missing input that
  reads as a strategy dead end is how this class stays unfixed.
- **R72(ii) — the parent, and the manifest, stop being opt-in (P2).** The
  locked-game membership check lives inside `check_parent_slots`, which ran only
  `if args.parent`, so a refinement verified without that flag had nothing
  re-checking whether a changed entry introduced a player from a started game.
  `verify_export` now resolves the parent from the manifest's supersession chain
  (the superseded record names its successor in `superseded_by`, so the parent of
  a file is the record pointing at it) and finds the manifest next to the entries
  file, as preflight already did. Verified on the 2026-08-03 pair: with no
  `--parent` and no `--manifest`, the swap file resolves
  `parent_source: manifest supersession chain`, the locked-game check runs
  (`new_from_locked_games: 0`) and the two swapped entries report 6 changed slots
  each. Before, that run printed "2 team(s) have already started and no --parent
  was given; locked-slot preservation is unverified" and skipped it.
  **What was NOT built, deliberately:** R72 filed this as "add the independent
  locked-game gate (`lock_time_by_game_id` + `as_of`)". A gate with no parent has
  no baseline, so it cannot tell a newly introduced player from one entered
  before lock — it would either pass everything or block every legal late-swap
  upload of a locked team's frozen slots. The parent IS the baseline; making it
  resolve without a flag is what closes the gap the item describes.
  `validate_late_swap_delta` was left alone for the same reason.

### Tests

- Ten new tests; the pin moves 609 → 619. A new `VerifyExportSlateTruthTests`
  (8) covers R46 and R72(ii): a seated player contradicting a confirmed lineup
  fails, the same file passes once the posted nine holds him, `--feed-lenient`
  downgrades it, an unconfirmed team is named with its slot count in both the
  text and `feed_unconfirmed_teams`, a confirmed team stops appearing as
  uncovered, the parent resolves from the supersession chain, a player from a
  locked game is caught with no `--parent` flag, and the manifest is found beside
  the entries file. The feed fixture helper grew a `confirmed=` parameter — the
  old all-`tbd` feed exercised none of this.
- Two in `tests/test_core.EntryAndAllocationTests` for R72(i): a candidate
  carrying an unclassifiable pid loses to the fully covered one and
  `_entry_candidate_compatible` rejects it directly, and a starved entry names
  the uncovered players and says to refresh the feed.

### Verified

- `PASS  v2.26.0  25 modules  619 tests` on the pinned container stack.

---

## 2026-08-04 — R51 + R52: both upload gates stop returning a false clean

### Fixed

- **R51 — `preflight_upload` no longer passes a zero-parsed-entries file as
  `upload_ready` (P0).** `load_entries` incremented `entry_id_rows` and appended
  to `entries` inside the same `if not entry_id.isdigit(): continue` branch, so
  the two counters were equal by construction and hard check 5's row accounting
  was structurally dead code. A file whose Entry ID column an Excel or pandas
  round-trip had reformatted (`4.71059E+09`, `4710591235.0` — blank reserved rows
  float the column) therefore parsed to ZERO entries, the four other hard checks
  each iterated an empty list, and the tool printed `PASS  0 classic entries, all
  hard checks clean`, exit 0, verdict `upload_ready`. A header-only file passed
  the same way. Both reproduced on the documented ad-hoc path (`--no-manifest`)
  before the fix and both exit 2 after it.
  Two changes: a row now counts as an Entry-ID row when it STATES an entry —
  anything in the Entry ID cell, or a filled roster window — whether or not the
  ID still parses as digits, so the counters can actually disagree and a float
  round-trip reads as `2 Entry ID rows on disk, 0 parsed`; and zero parsed
  entries is itself a hard failure, because every other check iterates that list
  and an empty parse ran them all over nothing. The new counter was verified
  against three real DK exports (2026-07-25 classic, 2026-07-29 classic, the
  Showdown fixture): DK writes its player pool to the RIGHT of the roster window,
  so pool rows carry neither signal and the new counter matches the old one
  exactly on a healthy file. That is the regression risk in this fix and it is
  now pinned by test — a counter that read those rows would fail row accounting
  on every real export. The docstring claim that "row accounting can catch what
  parsing tolerates" is true for the first time.
  `verify_export` imports `load_entries` and `check_row_shape`, so it inherited
  both fixes without a second implementation.
  **The third item on R51's filed Fix line was deliberately not built.**
  "Default `--expect-entries` from the manifest's `entries` when a manifest
  resolves" is already implemented, at `preflight_upload.check_manifest:636`,
  for the only case in which the manifest's count is trustworthy — a record
  matching these bytes by sha256. Wiring it a second time through
  `--expect-entries` would fire a second FAIL line stating the same fact, which
  is the two-implementations-of-one-rule smell this repo names as a defect class
  (R34). Truncation of a *delivered* file is caught upstream of the count
  anyway: dropped rows change the sha256, and a name-matched record with a
  different digest already hard-fails as "the file changed after it was
  recorded". No coverage was given up.
- **R52 — `verify_export --force` exits 4, not 0 (P0).** `verify_export.py:477`
  returned 2 only `if rep.failures and not args.force` and then fell through to
  `return 0`, so a forced run with hard failures present reported clean to the
  one signal automation trusts — against the module's own header ("Exit 0 clean,
  2 on any failure, matching preflight_upload") and against R2's whole rationale
  on preflight, where `--force` prints the failures and exits 4 precisely so the
  operator is unblocked without the caller being misinformed. The late-swap
  verification path reads that code. The exit-code contract is now one shared
  function, `preflight_upload.verdict_exit_code`, imported by `verify_export`
  alongside the nine helpers it already took, because two copies of one rule
  diverge and the weaker one reports success — which is exactly how this
  happened. Only the verdict LABEL stays local to preflight. Three stale
  statements of the old contract went with it: the module header, the `--force`
  help text (which read "print failures and exit 0"), and the `FORCED` epilogue,
  now `ACKNOWLEDGED ... Exit 4.` matching preflight's wording.

### Tests

- Seven new tests in `tests/test_upload_integrity.py`; the pin moves 602 → 609
  (`tools/audit.py`, `CLAUDE.md` session-start line, `SKILL.md` audit line).
  R51: the float-formatted Entry ID fixture and the header-only fixture each
  exit 2, the float case also asserting the row-accounting counters disagree;
  plus the embedded-pool guard described above.
  R52: a new `BothFileCheckersShareOneExitContractTests` pins the two tools
  EQUAL rather than pinning `verify_export` to 4 on its own — the defect was a
  divergence, so pinning the pair is what stops either tool drifting alone. It
  covers forced failures (4, 4), unforced failures (2, 2) and a clean file
  (0, 0) forced or not, asserts both tools reached the *same* hard failure so an
  equal pair cannot come from two unrelated verdicts, asserts the two tools hold
  the identical function object, and fails if the old fall-through branch or the
  old help text returns to the file.

### Verified

- `PASS  v2.26.0  25 modules  609 tests` on the pinned container stack after the
  change.

---

## 2026-08-04 — full-project audit: R51–R91 filed, the session-start gate replicated off-machine, the backlog reconciled and reordered

### Verified

- **The audit macro was replicated in a clean cloud container for the first
  time.** On the pinned stack (numpy 2.2.6 / pandas 2.3.3 / scipy 1.15.3,
  Python 3.11): `PASS  v2.26.0  25 modules  602 tests` — the tree is sound on
  the tested stack, off this machine. Getting there measured the gap R62 now
  files: a tracked-files-only checkout runs 583 of 602 with 8 errors and 3
  failures (gitignored `data/slates/2026-07-25/-29/-30` files are
  load-bearing for 11 tests, and 29 more paste tests silently skip), and
  golden replay skips entirely without `data/archive/2026-06-03`, at which
  point the audit's own stale-pin advice is to lower the pin.
- **The floors break the guard tests.** The same suite on a floor-satisfying
  stack (numpy 2.4.4 / pandas 3.0.2 / scipy 1.17.1) fails 4 tests in
  `ExcludedColumnCoercionTests` — pandas-3 strict setitem versus the
  fixtures' `"False"`-into-bool writes — so the class guarding the
  forbidden-pool-reduction rule errors before asserting anything (R78).
- **Backlog reconciliation: nothing on the open board has silently shipped.**
  Checked in code before reordering: R17 (strip intact at
  `contest_library.py:116`), R30(a) (no `--paid-places` anywhere in
  field_miner), R31 (both false signals intact at `claim.py:115,121`), R36
  Finding 10 (prefilter unchanged — and the starvation is now reproduced,
  note appended), R38 (`graded` denominator still at `net_to_date.py:85`),
  R39 (no captain preservation in `players_norm`), R44 (no mined-skip in
  extract_inbox_zips), R45 (both Showdown-paste breaks intact), R46 (no
  confirmed-lineup check in verify_export). No entry migrates out of the
  backlog; the open list was accurate.
- **One prior record corrected by observation:** the delivery manifest's
  `strategy_state` has read "clean" structurally on the production sliced
  path since R3(c) wired it — `manifest_strategy_state` reads a
  `relaxations` key the `candidates_override` path deliberately strips and
  build_slate's cache record never carries. Filed as R64; the R3(c) entry
  below stands as written for the self-built path.

### Added

- **R51–R80 filed in Section 1 and R81–R91 in Section 2 of the backlog** —
  thirty-one items from six independent whole-tree review passes (intake;
  solver; pipeline/projections; allocation/entries/swap/field;
  showdown/safety tools; tests/skill/docs; plus a cross-cutting hygiene
  sweep), every finding verified against this tree before filing per R36's
  practice, reproductions run in the pinned container venv. The two P0s are
  the upload gates themselves: preflight's row-accounting hard check is
  structurally dead code and the tool passes a zero-parsed-entries file as
  `upload_ready` (R51), and `verify_export --force` exits 0 with hard
  failures present, against its own header and R2's rationale (R52). The P1
  families: certification and record honesty (R53 vacuous lineup gate, R64
  strategy_state/projection_tier); solver correctness (R55 dtype no-ops that
  poison the bank cache, R56 suppression-as-constraint, R57 xwOBA Base
  clobber); intake calendar and leg integrity (R58 doubleheaders, R59
  merge_feeds keying, R60 partial sides, R65 ET gating); late-swap
  subset-vs-whole-file (R61); the audit gate's own evidence (R62); the
  approve=False contradiction (R63); and Showdown counted-relaxation honesty
  (R54). Dated notes appended to R17 (missing type precedence, reproduced),
  R31 (new part (c): `WRITE_SETS["DEV"]` omits CHANGELOG.md), R36 Finding 10
  (starvation reproduced live), and R46 (build together with R72's
  locked-game gate). Two reviewer claims did not survive verification and
  were not filed: a dangling-docs-paths claim that was an artifact of the
  audit's partial snapshot (`docs/legacy/` exists), and a lock-vs-runtime
  claim refiled in corrected, evidence-honest form as R78(b). Items not
  reproduced live are labeled PLAUSIBLE inline (R66c, R67, R72, R74b).
- **"What do we tackle next" reordered**, reasons stated inline: the
  upload-gate P0 pair leads; R46+R72 second (one verify_export pass, two
  slate-truth checks); certification/record honesty third; then R37's
  decision, the solver trio, the intake calendar family, the miner batch
  (now carrying R74), R10, R61, R62, R63, and R40. The do-not-build list
  gains one paragraph: no module-split program off line counts alone — the
  accepted forms are cross-pin tests, single-helper consolidations, and the
  documented roster_contracts rewire, under the golden gate.

## 2026-08-04 — backlog merge: R37 regraded, R46–R50 filed, seven fragments consumed, `paste_cache/` gitignored

### Changed

- **R37's decision input is regraded before the decision is made.** The
  A-030..A-034 mine (94 contests; working in ledger 3.17 and
  `ledger/2026-08-04_field_shape_ownership_analysis.md`) moved the shape
  evidence: the 5-2-1 top-decile lift decayed from +3.1pp to +0.2pp on the new
  tranche while the shape's field share rose five points, the win-line
  concentration did not repeat, and the repeatable results are the negative
  families (<=3-primary in every slice, now firm-as-observation; 4-2-x
  negative combined). R37's queue line and entry now read floor-first
  (eliminate the confirmed-negative families via `primary_stack_min_size`)
  with the 5-family push second, sized per posture, plus a thin-slate
  feasibility-versus-choice diagnostic before the floor is sized. Rationale:
  confirming a target off the 07-30 numbers alone would chase a shape the
  field already crowded into. Dated notes also appended to R10 (priors
  extended; R48 as grading target), R30 (paid-line urgency; R49 extends (c)),
  and R40 (two live rank-1 cases to check profile routing against).
- **Five items filed from seven consumed `docs/backlog_inbox/` fragments**
  (two BUILD 2026-08-03, three ARCHIVE 2026-08-03/04, two ARCHIVE 2026-08-04
  operational): R46 — a confirmed-lineup contradiction reached a certified,
  nearly-uploaded file past every gate (P1; R36 Finding 2's failure mode,
  reproduced); R47 — late_swap gives both-pitchers-locked entries zero
  targeted candidates, plus an unexplained candidate-scoring count; R48 —
  the miner should emit the per-contest leverage table the 3.17 measurement
  had to derive bespoke; R49 — manifest-first salary resolution
  (`runs/<run_id>/inputs/DKSalaries.csv`) and the false "DKEntries embeds the
  salary block" recovery-path claim; R50 — the miner block's "fees and
  winnings not supplied" wording when only winnings are missing. Consumed
  fragments moved to `_to_delete/`; deletions recorded in this commit.
- **`.gitignore`: `data/reference/paste_cache/` added.** A BUILD byproduct
  cache (paste raw + derived feed) was tripping every ARCHIVE session's
  `claim.py dirt` gate as foreign dirt inside the write set. Shipped directly
  from the fragment rather than filed — one line, no behavior change
  (fragment `2026-08-04_ARCHIVE_paste-cache-dirt-gate.md`, consumed).

## 2026-08-04 — R42(a): `env_probe.py` and `audit.py` check `.pylibs` before touching pip

### Fixed

- **The dependency probe now uses a vendored `scipy`/`numpy`/`pandas` before
  ever recommending, or running, an install.** Filed 2026-08-01 as R42 on one
  incident (sandbox overlay full, `env_probe --install` died with `[Errno 28]
  No space left on device`, no headroom check, no reclaim path). Recurred
  twice more on 2026-08-03: an ARCHIVE session proactively diagnosed the real
  gap mid-afternoon (`.pylibs/scipy` already sits in the repo, complete, from
  a 2026-07-30 session, but `env_probe.py`/`audit.py` only ever checked the
  interpreter's default import path); a 3-game night slate most likely lost
  two games unbuilt to three failed install attempts across 17 of a 20-minute
  window; a Showdown build an hour later hit the identical wall and was saved
  only by a 26-minute-to-lock handoff to Ben's local machine. All three
  same-day incidents, plus the original, are installation failures in an
  ephemeral sandbox — `scipy.optimize.milp` itself was never reached in any
  of them. Full incident detail: `docs/2026-07-27_backlog_v2.md`, R42.
- **`tools/env_probe.py`** (v1.0 -> v1.1): new `vendored_pylibs(root)` finds
  `<root>/.pylibs` when it holds at least one entry; new
  `ensure_vendored_on_path(root)` puts it at the front of `sys.path` (vendored
  wins over ambient site-packages, the same resolution-authority argument
  that already makes the lock file win over PyPI's latest) and returns what
  it found. `main()` calls this before evaluating warmth, so a populated
  `.pylibs` makes the probe warm with zero installs and prints which path it
  used; a genuine miss still falls through to the locked install path
  unchanged.
- **`tools/audit.py`** (v3.3 -> v3.4): `check_dependencies` imports
  `env_probe` and calls the same `ensure_vendored_on_path` before its
  `importlib` checks, and records the path used (or `None`) as
  `vendored_pylibs` in its returned dict. Separately, and easy to miss: the
  `--run-tests` test-runner subprocess does not inherit this process's
  `sys.path`, only environment variables, so `run_audit` now threads
  `deps["vendored_pylibs"]` into that subprocess's `PYTHONPATH` explicitly —
  without this, a clean dependency PASS could still be followed by a test run
  that cannot import `scipy` at all.

### Added

- **`tests.test_core.VendoredPylibsTests`** (7 tests): pure filesystem checks
  for `vendored_pylibs`/`ensure_vendored_on_path` (absent, empty, populated,
  idempotent insertion, real import through the inserted path), one
  integration check against this checkout's own `.pylibs` (skipped if a
  checkout has none), and one mocked check that the `--run-tests` subprocess
  actually receives the vendored `PYTHONPATH`. `EXPECTED_TEST_COUNT`: 595 ->
  602 (`core 381 -> 388`, others unchanged). Synced the three docs that quote
  the count: `CLAUDE.md`, the ledger Quick Card, `skills/generate-lineups/SKILL.md`.

### Verified

- All 602 tests pass. The sandbox that produced this fix could not run
  `audit.py --run-tests` as one command (same slow-mount pattern R42 itself
  describes — confirmed unrelated to this change: `tests.test_showdown` +
  `test_upload_integrity` + `test_golden_replay` + `test_paste_lineups` (214)
  and `test_core` chunked by class (66 classes, 388) each ran clean within a
  single call at least once, just never all 602 in the same subprocess
  inside one 45s window. `python tools/audit.py --run-tests --terse` on a
  normal machine is the one-command confirmation this entry could not
  produce directly.

### Not done here

- **R42(b)**, the genuine-miss install path (headroom check, named shortfall,
  reclaim, `TMPDIR`-to-persistent-mount, `wheel_fetch.py` version pinning),
  stays open and lower-priority now that (a) makes it a rare path instead of
  a common one. `docs/2026-07-27_backlog_v2.md`'s R42 entry is rewritten to
  R42(b) only and points back here for (a)'s history; the shipped "check
  `.pylibs` first" item is removed from "what do we tackle next" (it was
  briefly #1 there, in the prior commit below, while still open).
- **A second solver (PuLP or otherwise) was asked about live and is not
  built.** Two prior external critiques proposed one; both were already
  rejected on factual grounds (see `docs/2026-07-27_backlog_v2.md`, "Do not
  build," and the 2026-08-01 changelog entry). Nothing in this incident
  changes that: every occurrence was an installation failure, and a second
  solver would face the identical `$HOME`-is-full wall on its own install,
  since this repo has never used PuLP and it is not pre-vendored the way
  scipy now demonstrably needs to be and is.

## 2026-08-04 — R42/R45: consolidate three same-day scipy-sandbox fragments into R42; file R45 (docs only)

Ben, live: "this is the second time a lineup failed to generate... document
what happened and how we fix it... add this to the backlog." This is that
documentation and filing step; the fix itself is the separate, newer entry
above (commits are `b9bf147` here, `62415fb` above — same session, backlog
first, code second, same order CLAUDE.md's contract expects).

### Changed

- **R42** (`env_probe`/`audit.py` call the sandbox cold while a working
  `scipy` sits in `.pylibs`): rewritten from a single 2026-08-01 filing into
  four consolidated data points, priority raised P2 -> P1, and given a
  sequenced three-part fix. Two fragments merged and deleted in this commit:
  `docs/backlog_inbox/2026-08-03_ARCHIVE_env-probe-misses-vendored-scipy.md`
  (proactive diagnosis, ~16:10, filed before either live incident below) and
  `docs/backlog_inbox/2026-08-03_build_sdari-sd-sandbox-handoff.md` (this
  session's own SD@ARI Showdown incident, ~20:59-21:15). A third fragment,
  `docs/backlog_inbox/2026-08-03_build_scipy-install-blocked-a-live-slate.md`
  (a 3-game night slate, LAD@CHC/SF@TEX/TOR@HOU, that most likely lost two
  games unbuilt to the same wall an hour before this session's own), was
  read and folded in but was never committed by the session that wrote it,
  so its deletion here carries no separate git record — its content is fully
  captured in R42's rewritten "What" all the same.
- **"What do we tackle next" reordered**: the not-yet-shipped `.pylibs`-check
  fix placed at #1, ahead of R37, on the argument that it is S-effort,
  touches no surface R37/R41 need, and has now cost a live build twice in
  one day. (Shipped a few minutes later the same session; see the entry
  above, which also removes this ordering line.)
- **R42(b)** demoted to the opportunistic tier once (a) is filed, since a
  populated `.pylibs` was expected to make it the rare path rather than the
  common one — confirmed true once (a) actually shipped, above.

### Added

- **R45** (`tools/lineups_from_paste.py` can't resolve a Showdown salary
  file): filed new, P2. `POSITION_FIELD_CANDIDATES` prefers `Roster Position`
  (CPT/UTIL) over `Position` when a Showdown file has both, so every
  player's parsed position set comes back empty and the pitcher index is
  silently empty for everyone; separately, `_resolve_one` doesn't dedupe a
  Showdown player's CPT/UTIL row pair, so every hitter reads as ambiguous
  too. Pool construction is unaffected (`showdown.py` reads `Position`/
  `Starting` straight off the CSV), so this degrades paste-derived enrichment
  quality on the margin, not a build. Live workaround (filter the salary CSV
  to `Roster Position == 'UTIL'` before it reaches the paste tool, patch
  pitcher hand/id into the output feed by hand) is recorded in the R45 entry
  for whoever picks it up.

### Rejected (again)

- **A PuLP or other solver fallback**, asked live after the SD@ARI incident.
  Two prior external critiques already proposed this and were rejected on
  factual grounds before tonight (see "Do not build" and the 2026-08-01
  entry). Recorded here first, before the code fix existed, on the same
  reasoning repeated in the entry above once the fix shipped: every incident
  on this thread is an installation failure, and the solver itself was never
  reached in any of them.

## 2026-08-03 — R43: the standings-pull scan is a tool now, not a fourth hand-written pass

### Added

- **`tools/awaiting_standings.py`** (`scan` / `mark-unrecoverable` /
  `mark-placeholder`). Three sessions (2026-07-28, 08-02, 08-03) each
  hand-wrote the same scan — every Contest ID on a filled entry row in
  `outputs/*/DKEntries*.csv`, minus what's archived, minus what's already in
  the inbox — because nothing in `tools/` ran it. Filed as item 2 of
  `docs/backlog_inbox/2026-08-03_ARCHIVE_inbox-refill-and-scan-tooling.md`;
  this closes it. `scan` writes both
  `data/standings/CONTESTS_AWAITING_STANDINGS.md` and a clickable
  `data/standings/standings_pulls_<date>.html`; the HTML's export links check
  their own row's box on click, so working the list is one click per contest.
- **`data/standings/recorded_exceptions.json`** replaces the hand-maintained
  "do not pull" prose at the bottom of `CONTESTS_AWAITING_STANDINGS.md` with
  a file the tool reads and `mark-unrecoverable` / `mark-placeholder` append
  to. Seeded with the 9 contests already recorded dead (2026-06 tranche plus
  the 2026-07-28 zero-byte four) and the one known placeholder (`199000001`,
  synthetic entry ID, not a real DK contest).
- **`skills/mlb-standings-pull-checklist/SKILL.md`**, the Cowork-facing
  wrapper: take the inbox claim, run `scan`, present the HTML. Registered to
  Ben's skill profile the same session so it actually triggers.

### Fixed

- **The scan now filters to 9-digit Contest IDs.** The 08-03 hand-written
  pass found that accepting any non-empty value picks up non-DK placeholders
  on manual/test entry rows (`0` for a hand-built Showdown entry, `900` for a
  test fixture) and emits a dead `exportfullstandingscsv/0` link. The tool
  filters on the pattern instead of hardcoding the two values seen so far,
  and reports whatever it filtered out by name so a future one gets noticed
  instead of silently dropped.
- **The pull list now sorts oldest slate date first, matching its own
  instructions.** Every hand-written version said "prioritize oldest first"
  (DK's export is understood to age out some days after a contest settles,
  so the oldest unpulled contests are nearest that cliff) while still
  rendering newest-first. The tool sorts the section order to match the
  prose.

### Filed

- **R44** — `extract_inbox_zips.py` re-extracts contests already archived,
  refilling the inbox forever. Item 1 of the same fragment; not fixed here,
  filed in `docs/2026-07-27_backlog_v2.md`.

---

## 2026-08-01 — R36 Finding 11: the joint allocator's reuse term is removed

### Changed

- **`objective[y_offset:] = reuse_penalty * 0.01` is deleted from
  `select_and_assign_entries`** (`mlb_engine/allocate/contest_allocator.py:1625`).
  The joint objective now carries assignment terms only: every nonzero
  coefficient is a negated shape score on `[-100, 0]`, and the `y` block stays
  at `0.0`. `y_k` itself remains, because it carries the hard
  `max_shared_players` overlap rows (`:1743-1752`), and it now carries nothing
  else. Cross-lineup diversity is `max_shared_players` and `max_candidate_reuse`
  alone, both hard rows, which is the point: two controls at different scales
  governing one property was the redundancy.
- **The `reuse_penalty` controls key is named and ignored, not obeyed and not
  fatal.** This was the open sub-decision and the reasoning belongs on the
  record. Silently accepting a dead control is worse than the original bug,
  because the next reader assumes it works. Rejecting it through the allocator's
  error dict was rejected on a truthful-labels ground: `_plan_joint_allocation`
  renders any allocator refusal as `proven_infeasible`, and a dead control key
  is not an infeasible constraint system, so that route either mislabels the
  verdict or forces a fourth verdict category into the checkpoint for a control
  whose only effect was a defect. Raising was rejected because it can stop a
  build at T-5 over an input that changes no coefficient. So the key is reported
  in the allocator's `warnings`, which persist in
  `runs/<run_id>/final/diagnostics.json`, and the build proceeds. Nothing in the
  tree sets the key today, verified by grep across `mlb_engine`, `tools`,
  `tests`, `data` and the contest library.
- **`docs/MLB_Classic_Integration_Contract.md` no longer advertises
  `reuse_penalty` as a `portfolio_controls` key**, and says where the name does
  still live: as a keyword parameter on the legacy `assign_lineups_to_contests`
  (`:732`, applied at `:797-800`), where it weights an EXCESS variable and is
  correctly signed. The key was not dead everywhere, and the contract now says
  which of the two things it is. `MLB_Classic.md` and `SKILL.md` never described
  the parameter and needed no correction.
- **Two tests the file never had**, both verified against the old code by
  restoring the term and watching them fail:
  `JointObjectiveNoReuseTermTests` in `tests/test_core.py`. The coefficient
  snapshot spies on the `c` vector handed to `milp` and pins the block sizes,
  the `[-100, 0]` bound, the absence of any positive coefficient anywhere, and
  the all-zero `y` block; with the old term restored it failed on
  `[0.02, 0.02, 0.02]`. The behavioural test puts two candidates `0.01` apart on
  the 100-point scale, each the better fit for one of two entries in different
  contests, so the distinct pair is the unique optimum by `0.01`; with the old
  term restored it returned `['B', 'B']`, the collapse onto one reused lineup,
  exactly as predicted. A third test pins the ignored-control warning and that
  the objective vector is bit-identical with and without the key.
- **Test count re-pinned 591 to 595** in `tools/audit.py`, `CLAUDE.md` and
  `skills/generate-lineups/SKILL.md` (core 377 to 381).
- **`tests/golden/golden_replay_production_2026-06-03.json` re-pinned, one key
  only.** `assignments` was replaced; `aggregates`, `meta` and `pure_verdict`
  are byte-identical, and the diff is a balanced 178/178 inside the assignments
  block.

### What the golden diff actually shows

The prediction was near-tie churn on some fixtures. The headline number looks
much worse than that and the detail confirms the prediction, so both facts are
recorded here.

17 of 18 entries changed their assigned lineup. The portfolio-wide multiset of
`lineup_signature` is IDENTICAL: zero lineups added, zero removed, the same 18
rosters entered. `test_aggregates_match_baseline` passed untouched, so bank
composition, the exposure summary and the SP-pair distribution did not move.
Per contest, exactly two lineups traded places between contests `191020573` and
`191020574`, one BOS-stack and one BAL-stack; contest `191047506` is unchanged.
Every other apparent move is one of two non-facts: an Entry ID permutation
within a single contest, which the portfolio does not distinguish, or
`bank21` to `bank0`, which are duplicate signatures under different bank indices
and therefore the same roster.

So the answer to "cleanup or portfolio change" is cleanup. Two of eighteen
entries changed which contest they sit in, which is the only thing the removed
term could ever have biased, since `y_k` is a portfolio-wide indicator and the
coupling it created was cross-contest by construction.

One observation worth keeping, because it cost this session real time.
`test_assignment_matches_baseline` pins entry-to-lineup mapping, and Entry ID
assignment within a contest is a free permutation the solver has no reason to
hold stable once any coefficient changes. The test therefore reports a
17-of-18 diff for a 2-of-18 change. That is a property of the golden's
granularity, not of the engine. Not filed as an item; raised for Ben.

### The adjudication and the decision, migrated verbatim from R36 Finding 11

Migrated out of `docs/2026-07-27_backlog_v2.md` in this commit, per the
2026-08-01 backlog/changelog contract. Tense and line numbers are as written at
the time; the shipped state is the section above. The separate
`2026-07-31 — Decided, not yet shipped` entry stays where it is.

- **Finding 11 (P1, XS, but it reranks lineups so it is Ben's call).** `reuse_penalty` genuinely rewards reuse. `scipy.optimize.milp` minimises; the used-candidate indicator `y_k` gets a POSITIVE coefficient (`reuse_penalty * 0.01`, default 2.0), and the linking rows make `y_k` mean "candidate k is used by at least one entry". Minimising a positive cost per DISTINCT used candidate prefers fewer distinct lineups, which is the opposite of the parameter's name. The legacy `assign_lineups_to_contests` puts the same penalty on an EXCESS variable and is correctly signed. **This was already accepted in `docs/2026-07-19_red_team_response.md` and then lost — it never reached a backlog item.** That is the more troubling fact. Not flipped tonight because changing it reranks every multi-contest portfolio, which makes it a strategy change needing a dated decision, per the same rule that parked the satellite `ticket_count` rows. Recommendation: remove the term rather than invert it, since no bankroll rationale for cross-contest reuse has ever been written down.

- **DECIDED 2026-07-31 by Ben, on DEV's recommendation: REMOVE the term. Not shipped yet; it is the first item of the next DEV session.** The reasoning was re-derived rather than inherited, and one inherited claim was wrong and is withdrawn. **Withdrawn:** that inversion would be structurally unsafe. `y_k` is pinned bidirectionally at `contest_allocator.py:1724-1725`, so it cannot float free and a sign flip would in fact behave. Inversion is safe; it is just not warranted. **The actual case for removal.** The term is redundant by construction: `use_y` is true only when `max_shared_players` is set, so the soft nudge is live only when the hard overlap cap is already enforcing diversity, and two controls at different scales governing one property is how a portfolio stops being explainable. Nothing was ever tuned against its stated behaviour, since it never had that behaviour, so there is no calibration to preserve. And no rationale has been written down for penalising reuse BEYOND the hard cap either, so with no stated case in either direction the honest default is no term. **The blast radius is smaller than "reranks every multi-contest portfolio" implies, and that is worth stating before the work starts:** the coefficient is `reuse_penalty * 0.01` = 0.02 against x coefficients normalised to [-100, 0], so it is a tiebreaker that only moves a selection when two candidates sit within 0.02 of each other on a 100-point range. Expect the golden replay to move on some fixtures and not others; goldens are re-pinned deliberately, with the diff read, never regenerated blind. **Addition (2026-08-01, GF spec F-07):** the removal commit ships with two tests the file never had — an objective-coefficient snapshot on the joint MILP (every term named, signed, bounded) and a near-tie behavioral test proving two candidates inside the old 0.02 tiebreaker band no longer collapse onto one reused lineup.

## 2026-08-01 — R41/R42: adjudication of the 2026-08-01 external critique pair (docs only)

### Changed

- **Adjudicated two new external critiques** against the tree at 48b4e7e, per
  the R36 method (every new line cite verified before ruling). Both archived:
  `docs/2026-08-01_critique_greenfield_spec.md` and
  `docs/2026-08-01_critique_gemini.md`.
- **The Gemini document: rejected, nine of nine.** It did not read the tree.
  It attributes roster construction to the LLM (`optimizer_v3` +
  `scipy.optimize.milp` has been the source of truth throughout), proposes the
  PuLP migration already on the do-not-build list, gets the DK Classic roster
  size wrong (says 8; it is 10), and proposes automated DK scraping plus
  automated lineup upload, which the DK wall and the money wall forbid
  categorically. Its two non-violating ideas already exist as R9 and R10.
- **The greenfield spec: read the tree, high quality, mostly prior art.** Of
  its 30 flaws, roughly 20 map to standing dispositions — R36's accepted
  findings, the R9/R10/R12/R13 gates, and the do-not-build list — and its
  Phase 0 independently re-derives the current what-next ordering. Its
  compliance stance (no DK automation, manual upload boundary) confirms
  existing policy. Newly accepted and filed:
  - **R41** — bring Showdown under the three certification gates (F-15).
    Filing also closes a contract drift: CLAUDE.md promised this backlog item
    and it never existed.
  - **R42** — `env_probe --install` disk-headroom check and reclaim path
    (F-22 narrow); bit this session live (sandbox ENOSPC, audit unrunnable).
  - **R36 extensions in place:** F11's removal ships with a coefficient
    snapshot and near-tie behavioral test (F-07); F1m's staleness constant
    becomes time-to-lock policy (F-11); F6m adds corrupt-manifest-is-not-empty
    (`read_manifest`, `upload_manifest.py:85-93`, verified) and
    `salary_sha256` in delivery records (F-14 plus the recordable sliver of
    F-25); Finding 7 ships with the exactly-50% coverage boundary test (A-29).
  - **R10 extension:** the satellite prior is graded on duplication
    distribution, not ownership error alone (A-12).
  - **Do-not-build additions, dated:** no greenfield rebuild program while
    R13 is undecided; no DB state machine, HMAC manifests, CP-SAT migration,
    evidence-policy engine, or async acquisition service. Reasons in the
    backlog section.
- **Rejected with a factual correction:** F-24/F-29's "no prediction ledger"
  is partially false — every run persists `final/projections.csv` immutably;
  the missing piece is a player-actuals grading harness, which inherits
  Finding 15's disposition as a named dependency of R13.
- **Doc-drift fixes riding this commit:** `docs/next_session_prompts.md` test
  pin 589 → 591 (core 375 → 377; `EXPECTED_TEST_COUNT` in `tools/audit.py` is
  the source of truth). The Quick Card's stale 546 goes through ARCHIVE via
  `ledger/inbox/2026-08-01_DEV_quick-card-count-591.md`, because the ledger is
  not DEV's to edit.

## 2026-08-01 — the backlog/changelog contract: every change carries its entry; completed items migrate

### Changed
- **The changelog's scope is now every change, code or otherwise.** Ben's
  directive: he and any session must be able to see when a thing changed and
  the rationale, from this one file. `audit.changelog_debt` now watches the
  full DEV write set — `mlb_engine/`, `tools/`, `tests/`, `skills/`, `docs/`,
  `CLAUDE.md` — instead of engine and tools only. The two inbox dirs
  (`docs/backlog_inbox/`, `ledger/inbox/`) are exempt: fragments are inputs
  addressed to an owning role, and the owner's merge commit is the change the
  log records. Tests 589 → 591 (one renamed, three added).
- **Completed backlog items now MIGRATE here.** The backlog holds open work
  only; when an item lands, its entry moves into this file in the completing
  commit. Everything closed before today moved in one pass to the "Imported
  record" section at the bottom of this file, verbatim, amendments included —
  26 R-items plus the v2 validation and critique-disposition sections.
- **The backlog is restructured so "what do we tackle next" has one answer.**
  `docs/2026-07-27_backlog_v2.md` (same file, header renamed to the live
  backlog) now opens with an ordered "What do we tackle next" section any
  session can read. Item numbers are preserved forever; no renumbering.
- CLAUDE.md's pointer lines updated to carry both rules and to name this
  entry's enforcing path; audit pin 589 → 591.

### Added
- Backlog items R37 (primary-stack shape control; merges the 2026-07-30
  stack-shape fragment with the 2026-08-01 review's win-line and
  bank-generation evidence), R38 (net_to_date TOTAL line, from the 2026-07-30
  fragment), R39 (miner preserves the CPT marker), R40 (verify one-seat
  satellite profile routing). The three consumed DEV fragments are deleted per
  the fragment protocol.

### Why
Ben asked whether every instance and session would keep a change log. The
honest answer was "only for code, and only DEV": the changelog's declared
scope already included docs and CLAUDE.md, but enforcement watched
`mlb_engine/` and `tools/` alone, completed items accreted in the backlog with
their history in a fourth place (Amendments), and "what next" required reading
a 414-line file against a memory of what had landed. One rule, one enforcing
path, one migration: change → changelog with rationale, open work → backlog,
next action → the backlog's first section.

---

## 2026-07-31 (later) — the changelog rule gets an enforcing path

### Added
- `audit.changelog_debt`. Counts commits touching `mlb_engine/` or `tools/`
  since `CHANGELOG.md` was last written and reports them as a WARNING on the
  audit's PASS line, using the same bracket mechanism as the stale test pin.
  Six tests, each against a throwaway git repo.

### Changed
- CLAUDE.md's DEV role now says a change is not shipped until the changelog
  carries its entry, in the same commit, and names the code that enforces it.

### Why
Ben asked whether new sessions would know to update this file. They would not
have. It existed in exactly one line, inside a pointer list, with nothing
checking it. The 07-25 review already named documented-but-unenforced as a
proven failure class in this repo and adopted the rule that any MUST either
cites its enforcing path or is rewritten as guidance, so a changelog rule
resting on one sentence was that failure class with the ink still wet.

The check is a warning and never an error, and it reads committed history, so
it surfaces the previous session's omission at the next session's start. It
cannot see the session currently running. That is the honest limit: this
narrows the gap, it does not close it. It degrades to silence without git,
outside a work tree, or before a `CHANGELOG.md` exists, because an audit that
fails on its own bookkeeping is worse than one that stays quiet.

Tests 583 → 589.

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

---

# Imported record — items closed before 2026-08-01

Moved from `docs/2026-07-27_backlog_v2.md` on 2026-08-01 under the
migration rule above. Text verbatim from the backlog at migration time;
dates and rationale as originally recorded. Newest-first does not apply
inside this block; it preserves the backlog's own order.

## The v2 backlog's original header and execution order (2026-07-27, superseded 2026-08-01)

# Backlog v2 | MLB DFS Engine | 2026-07-27

**Supersedes** the remaining-work section of `docs/2026-07-25_red_team_final.md` and disposes of two new external critiques (`DFS_SYSTEM_REDTEAM_CRITIQUE.md`, referenced as **RC**, and `DFS_SYSTEM_CONSOLIDATED_CRITIQUE.md`, referenced as **CC**). This is the single live backlog. Same structure as before: Section 1 issues/bugs, Section 2 ideas/features, each item with What, Why, and Fix. Nothing in the repo was modified to produce this document.

Priorities: **P0** corrupts what gets uploaded or lets an invalid file certify. **P1** silently degrades lineup quality or destroys evidence. **P2** wastes time or tokens. Effort: S under 30 min, M a few hours, L a day or more.

---

# Execution order

1. **R1** (contest objective): the P0 tail and the most-likely-wrong-objective item on contests entered tonight. Land (a) and (b) first; (c) and (d) can trail.
2. **R2 + R3 + R4** as one preflight-and-manifest honesty pass, about half a day: exit codes, manifest binding, feed-by-default. All three are file-level and cannot block a build.
3. **R6** (tests), with the R1 contract test landing alongside R1.
4. **R5** (caps): Ben's dated ledger call; five minutes once decided.
5. **R9a + R8** as one text-only pass. It touches no code, so it can land any time, including before item 1; observe the two holds (the `--force` sentence rides R2, the "non-negotiable" wording rides R5).
6. **R9b** after R6, since ENGINE_STATE generation touches audit.py.
7. **R10** the slate the archive hits the gate; **R13** when the sample exists. As of 2026-07-29 R10's depth gate is met at the payout-shape level (12 slates in the satellite cell) and what stands between it and open is one conditioning definition, which is Ben's.
8. **R11 + R12** opportunistically; neither blocks anything.
9. **R15** (DU) with R5, since both change construction and both are Ben's call.
10. **R29** is landed except item (5)'s skill-side residual, which needs a hand edit outside Cowork.
11. **R30** (miner gaps) whenever ARCHIVE next mines; (b) first, because it is the one that fails at exit 0.

## The v2 backlog's validation and critique dispositions (2026-07-27)

## Validation of current state (verified this session)

Tree is clean at `c9c3e6f`, 22 commits past `e58b3ac`, every commit mapping to a backlog ID (F1 through F19, F21, G4, plus the verification suite). `python tools/audit.py --run-tests --terse` prints exactly `PASS  v2.26.0  22 modules  329 tests`; the audit now gates four suites including the new `tests/test_upload_integrity.py`.

The six-item remaining list is confirmed accurate, with evidence:

| Item | Claimed | Verified |
|---|---|---|
| F22 test suite | open | Confirmed. Fixture suite and four-suite audit landed (`fb9e8ac`); the behavior-test and production-controls-golden halves remain. RC 2.8 adds a skill-eval leg, folded in below (R6). |
| F20 caps decision | open, Ben's call | Confirmed at `execution_pipeline.py:610-637`: wta_satellite pitcher 0.70 / stack 0.60 / shared 7 vs MLB_Classic §8's 0.43 / 0.35 / 5. Now R5, with one addition from RC 1.14. |
| F3b/F3c shape enum + ticket scoring | open | Confirmed, and RC 1.1 sharpens it: `execution_pipeline.py:697-698` folds `satellite` and `ticket_line` into `wta_satellite`, `:906` maps that to `large_wta`, so the optimizer's satellite profile (0.58/0.42) is unreachable and its floor weight would be dead anyway (cash-only blend branch). Dead `right_tail_weight`/`leverage_bonus_weight` still defined at `optimizer_v3.py:2653-2666`. Now R1, elevated. |
| F23 + G5 hygiene/corpus | open | Confirmed: `SKILL.md:449` still says "13 modules, 189 tests"; `evals.json` still expects "v0.1-review"; `parked/` appears 6x in MLB_Classic.md; `_scratch_20260722/` still on disk; no `ENGINE_STATE.md`. Now R8/R9. |
| G3 ownership/duplication | open, gated | Confirmed: zero `ownership_prior` or `Projected_Ownership_Pct` wiring in `build_slate.py` or the pipeline. Now R10. |
| G7 stakes decision | open, needs data | Confirmed unblocked mechanically: G4 landed (`field_miner.py:927-987` takes `my_entry_ids`, emits fees/winnings/net); the number arrives with archived slates. Now R13. |

Not in the handoff list but still open from the 07-25 final: G2 (skeptic pass), G6 (loops/scheduled tasks), G8 (tier doctrine). Carried below at low priority (R11, R12, and R14 folded into R9); drop them if the omission was deliberate.

## Disposition of the two new critiques

**RC (DFS_SYSTEM_REDTEAM_CRITIQUE.md): substantive and current.** Its line anchors check out against today's tree. Accepted or merged: 1.1 and 1.2 (into R1, with sharper evidence than the prior backlog had), 1.4 (R4), 1.5 (R2), 1.7 (R3), 1.8 and 2.5 and 2.10 (into R10), 1.9 and 2.1 (into R9), 1.10 (into R12, minimal form), 1.11 (R7), 2.3 (confirms landed G1; Stage-B constraints into R11), 2.8 (into R6), 2.9 and 1.13 (framing only, no engineering), 2.12 (merged into the execution order). Modified: 1.3 (reject the three-tier machinery; accept one `projection_tier` manifest field derived from `enrichment.signal_applied`, folded into R3); 1.6 (reject the rename-plus-promote ceremony as process weight; accept a manifest `status` stamp and preflight verdict recording, folded into R3); 1.14 (reject the bounded clean-subset search ceremony; accept a `strategy_state` manifest field plus a CLAUDE.md wording fix, folded into R3 and R5); 2.4 (reject live payout parsing, which would require DK lobby access the DK wall forbids; accept objective columns in the curated archetype CSV, folded into R1); 2.7 (reject watcher daemons, which Cowork cannot host; accept a feed-diff print in late swap, folded into R12); 1.12 (reject four-contract extraction as over-engineering; accept the objective enum, which is R1, and the weight-consumption contract test, which is in R6); 2.2 (reject a new state machine; accept the minimal manifest status enum in R3); 2.6 and 2.11 (already deferred or already true operationally).

**CC (DFS_SYSTEM_CONSOLIDATED_CRITIQUE.md): rejected almost entirely, on evidence.** Its central claims are false against this tree: it says the solver is "iterative PuLP CBC" taking "3-10 minutes" (zero PuLP references exist in the repo; `scipy.optimize.milp` is the documented sole backend at `optimizer_v3.py:86`; certified builds measure 8-11 seconds); it proposes "deploying" `execution_pipeline.py`, `build_state_manager.py`, a deterministic preflight, and a candidate bank cache, all of which exist and are landed; its Showdown claim (string-name-keyed variables producing dual-slot players) is unsupported and contradicted by the certifier's dual-slot check, the preflight identity check, and the test suite; its blanket fix "zero out every unconfirmed player once lineups release" would destroy the platoon fallback that is a designed feature for TBD teams; `bank_cache.parquet` adds a dependency for nothing; and its Phase 3 (Monte Carlo field ROI engine, play-by-play simulator) ignores both the stakes gate and the truthful-labels rule. What survives from CC is corroboration only: context slimming (R9), ownership/duplication value (R10), and a fast deterministic preflight (landed). No CC item generates new work that RC or the existing backlog does not already cover more accurately.

---

## Closed items R1–R35 (as recorded at closure)

### R1. Contest objective: satellite and ticket contests still score as WTA (P0 tail, M) | was F3b/F3c, sharpened by RC 1.1/1.2

- **What:** three layers of the same defect. Routing: `normalize_posture` folds `satellite` and `ticket_line` into `wta_satellite` (`execution_pipeline.py:697-698`) and `_posture_to_shape` maps that to `large_wta` (`:906`), so even the curated-CSV archetypes landed in F3a get flattened to a WTA objective, and the optimizer's `satellite` profile (`ticket_line` mode family, 0.58/0.42 ceiling/floor) is unreachable. Scoring: `score_lineup_candidate` blends ceiling/floor only for the `cash` mode family, so `ticket_line` would take pure ceiling even if reached. Dead knobs: `leverage_bonus_weight` and `right_tail_weight` are defined in every profile (`optimizer_v3.py:2653-2666`) and consumed nowhere; `right_tail_bonus` is computed and never added to the score.
- **Why:** the portfolio is almost entirely satellites and qualifiers. A satellite pays for clearing a cut line; ranking its candidates by pure ceiling with WTA weights is the wrong objective on most of the entries actually submitted, silently, every slate. This is the highest-EV item left on the board, and both independent critiques converged on it.
- **Fix:** (a) One canonical shape enum in one module; every `_posture_to_shape` output validated against it at import; `satellite`/`ticket_line` survive as their own values instead of folding into `wta_satellite`. (b) A real ticket branch in `score_lineup_candidate`: use the profile's ceiling/floor blend for `ticket_line` (0.58/0.42 as documented) as the v1 proxy for P(score >= cutline); label it a proxy, never a probability. (c) Extend `data/reference/dk_contest_archetypes.csv` with `objective_class` and, where known, `ticket_count` columns (single-ticket vs multi-ticket qualifiers behave differently; RC 2.4's payout parsing is rejected because of the DK wall, but the curated CSV is exactly where recurring contest knowledge belongs). (d) Decide each dead weight: consume it (right_tail is one line) or delete it, and add the contract test in R6 so no knob can go decorative again. Done when: a satellite fixture's candidate ranking provably differs from a WTA fixture's on the same bank; every profile key is consumed or gone; changing `ticket_count` on a fixture changes ranking or is explicitly documented as v2.
- **(b) + (d) LANDED 2026-07-27.** (b) `score_lineup_candidate` blends ceiling and floor for the `ticket_line` mode family as well as `cash`, so the satellite profile's 0.58/0.42 is applied instead of advertised; the metric is emitted as `Ticket_Line_Advance_Proxy` and `_mode_for_contest_shape` returns `ticket_line` for a satellite, so nothing labels a ticket contest `Portfolio_EV_Proxy` any more. Labelled a deterministic review proxy for clearing the line, explicitly not P(score >= cutline), which needs the field distribution R10 builds. (d) Decided **delete, not consume**: `leverage_bonus_weight` and `right_tail_weight` are gone from all twelve profiles. Consuming right_tail is one line, but it reranks candidates on every shape at once and that reach belongs beside the caps decision in R5, not in an integrity pass; the signal still ships as `right_tail_bonus` / `right_tail_volatility_counts` and the allocator already spends it. RC 1.2's contract test landed with it: each weight on each shape is perturbed against a fixed lineup and the score must move. **One limitation, stated so it is not rediscovered as a bug:** the golden replay did not move on (b), because under the emergency-proxy path Floor is 0.58*Base and Ceiling is 1.42*Base, which makes the blend a fixed 0.7515 multiple of ceiling and rank-equivalent to it. The ticket objective only separates candidates once Floor carries information independent of Ceiling, so R6(b)'s enriched golden replay is what will actually exercise it. Pinned as a test. **Still open and now visible:** the `gpp` family advertises 0.72/0.28 and takes pure ceiling, the same defect one family over. Extending the blend there reranks every GPP contest, so it is its own decision, not a follow-on; recommend folding it into R5's dated entry.
- **(a) LANDED 2026-07-27.** Evidence re-verified before the change: the anchors had drifted by about ten lines (fold at `:697-698` confirmed, `_posture_to_shape` at `:903` not `:906`, dead weights at `:2653-2666` confirmed) but every claim held. `mlb_engine/contest_shapes.py` is the vocabulary (12 shapes, `OBJECTIVE_CLASS_BY_SHAPE`, `WTA_CONSTRUCTION_SHAPES`); `optimizer_v3` asserts its profile table matches it at import, including `mode_family` against the declared objective class; `execution_pipeline` validates `_POSTURE_TO_SHAPE` at import and routes through a new `resolve_contest_shape(posture, inferred)` that keeps the satellite family out of `large_wta`. Three things the item did not predict: `_posture_to_shape("mme")` returned `mme_top_heavy`, which is a payout token and not a profile key, so `resolve_contest_shape_profile` raised on every 150-Max contest on the direct path (now `mme_gpp`); the payout-breadth fallback table was missing every canonical shape name, so a satellite would have taken the 0.12 global default; and the ` SE` row of `dk_contest_archetypes.csv` carried unquoted commas in `notes`, which put `" POSE"` in `payout_breadth` and the rest of the line in the csv restkey (harmless today because the float parse fails closed onto the identical in-code prior, fatal the moment (c) adds a column). All three fixed with tests. **Deliberately not changed:** the posture stays `wta_satellite`, because a `satellite` posture means a new `STRATEGY_DEFAULTS` caps row and caps are R5; and `WTA_CONSTRUCTION_SHAPES` carries the satellite family so MILP construction mode, and therefore the DU threshold row, is byte-identical to before. The golden baseline was re-frozen: 14 satellite entries moved `large_wta` to `satellite`, 7 of 18 lineups changed, the 4 GPP entries are identical, all three certification gates unchanged. That re-freeze is the evidence for the item's first "Done when".

- **(c) LANDED 2026-07-27, schema and wiring; the curated values are Ben's to supply.** `objective_class` and `ticket_count` are on `data/reference/dk_contest_archetypes.csv`, on `ContestArchetype`, through `load_archetypes`, and out of `infer_contest_archetype`. `objective_class` is populated for all 22 rows, derived from each row's `payout_shape_default` through the new `contest_shapes.objective_class_for_payout_token`, and it is a **cross-check, not a router**: the live objective still comes from the resolved shape, and a row naming a class its own payout token contradicts fails the load rather than picking a winner. `ticket_count` is wired end to end and **blank on every row**, which is the honest state: the file is keyed on name patterns and the three satellite rows (`Satellite`, `Qualifier`, `Ticket`) are generic families whose ticket count varies per contest, so no value belongs on them. A curated count reaches `resolve_contest_shape` immediately, where 1 routes to `wta_ticket_satellite` and anything else to the ticket-line blend, and a known count drops `ticket_count` from `decision_critical_gaps`. Three tests (the commit message says four, counting the four bad-cell cases inside one of them): the count reaching the shape at 1, at 6 and at blank; the four ways a bad curated cell fails the load; and the shipped file loading with every implied class agreeing. **The open input:** recurring satellite or qualifier contests Ben actually enters, by the name substring that identifies them, with the ticket count each awards. Each one is a new CSV row, not an edit to the generic three.

### R2. preflight `--force` converts hard failures into exit 0 (P1, S) | new, RC 1.5

- **What:** `tools/preflight_upload.py` documents "Exit 0 clean (or --force)" (`:44`); with `--force` the failures print and the process exits 0 (`:793` prints "this file is being uploaded against the check"). CLAUDE.md repeats the semantics.
- **Why:** exit 0 is the one signal automation trusts. The skill, a scheduled task, or a future wrapper cannot distinguish "upload-ready" from "the clock beat the fix." The original design goal (the tool must never be the reason a slate is not entered) does not require lying to the caller; it requires the operator to stay unblocked.
- **Fix:** `--force` becomes exit 4 ("acknowledged, not ready"), still printing everything and still never blocking the upload Ben chooses to make; the skill branches on 4 by presenting the file with blockers stated rather than reporting clean; the manifest records `status: acknowledged` with the failure list (see R3); CLAUDE.md's preflight sentence is updated to the four-code table (0 clean, 2 hard fail, 3 IO, 4 acknowledged). Done when: no code path with a non-empty failure list returns 0, and the skill's final message on exit 4 names the overridden failures.
- **LANDED 2026-07-27, engine half.** Anchors re-verified (the `--force` return-0 is at `:797` now, not `:793`). Exit 4 with an `ACKNOWLEDGED` line, `verdict` on the JSON payload, and the manifest stamped `acknowledged` with the failure list. CLAUDE.md's preflight sentence updated in this commit, per the R9a hold. **Still open:** the SKILL.md half. The skill must branch on 4 and name the overridden failures rather than reporting clean, and that edit was not in this session's scope. Until it lands, exit 4 is honest at the tool and unread by the caller.
- **SKILL half LANDED 2026-07-27, R2 now closed.** The false block was `SKILL.md:299-311`: it documented three exit codes, said `--force` "prints the failures and exits 0", and described the manifest as a cross-check with no mention that a delivered file without a row now hard-fails. Replaced with the three self-resolving inputs (`--salary`, `--manifest` with the delivered-vs-ad-hoc split and `--no-manifest`, `--feed` with the CONFIRMED-absence hard fail, `--feed-lenient`, and the 90-minute age warning) and a four-row exit table, each row saying what the agent says. Exit 4 gets its own paragraph: name every overridden failure, quoted, and never report clean, upload-ready, or certified, because the manifest records `acknowledged` and the reply has to match the record. **One defect this item did not name, found and fixed here:** `--force`'s argparse help still read "print failures and exit 0", and CLAUDE.md points agents at `--help` as the authority for a tool's flags, so the tool was still shipping the false contract at the one surface the docs delegate to. Three tests pin all of it (help text, docstring exit table, and the SKILL.md section against the four codes and the two waiver flags), so the doc cannot drift off the tool again silently. Test pin 360 to 363 in `audit.py` and the three docs that quote it.

### R3. Manifest binding fails open, and the manifest carries no status or strategy state (P1, S) | new, RC 1.7 + minimal pieces of 1.3/1.6/1.14/2.2

- **What:** `mirror_to_outputs` and `_record_upload_manifest` swallow all exceptions by design ("a mirror must never fail a certified build", `execution_pipeline.py:2816`, `:2867`), so a certified file can land in `outputs/` with no manifest row and nothing says so; preflight checks the manifest only when one is present. The manifest also records no preflight verdict, no projection tier, and no strategy-relaxation state, so "review-grade", "clean", and "acknowledged" live only in prose.
- **Why:** the manifest was built (F7) to make "which file do I upload" answerable in one second; a silently missing or stale row re-opens exactly that hole. The Showdown relax-before-truncate behavior and the review-grade label are fine as decisions, but they should be machine-readable on the artifact record, not adjectives in a brief.
- **Fix:** keep generation fail-open, make promotion honest: (a) manifest write failure prints one loud line in the build output and sets the run payload's `manifest_recorded: false`; (b) preflight hard-fails a delivered file whose manifest row is missing or whose sha256 mismatches, with `--no-manifest` as the explicit waiver; (c) add three fields to each manifest row: `status` (candidate | upload_ready | blocked | acknowledged | superseded, stamped by preflight), `projection_tier` (enriched | proxy, derived from `enrichment.signal_applied`), and `strategy_state` (clean | relaxed with the relaxation counts, from the brief's existing counters); (d) fix the CLAUDE.md wording RC 1.14 flagged: the Showdown controls are "enforced in the solver, relaxed only in stated order and counted", not "non-negotiable". Done when: preflight refuses a manifest-less delivered file by default; a relaxed Showdown portfolio's manifest row says so; the wording contradiction is gone.
- **(a)(b)(c) LANDED 2026-07-27; (d) deliberately held for R5.** (a) `mirror_to_outputs` prints `MANIFEST NOT RECORDED` and sets `manifest_recorded: false`; generation stays fail-open. (b) Preflight hard-fails a **delivered** file (one resolving under `outputs/`) with no manifest row or a sha mismatch, `--no-manifest` waives it; a hand-built file elsewhere still only warns, because the tool covers ad-hoc exports on purpose and those have no record to miss. That "delivered" qualifier is the item's own word and it is what keeps the ad-hoc path usable. (c) `status` is a closed enum (`candidate` from the build, `upload_ready`/`blocked`/`acknowledged` stamped by preflight onto the record whose sha256 matches the bytes it hashed, `superseded` by a later delivery), plus `projection_tier` and `strategy_state`. **One claim in the item was wrong:** there is no `enrichment.signal_applied` key on this tree. The enrichment blocks carry `requested`/`applied_count` and `_applied` already reads them, so `projection_tier` is derived from those instead: `enriched` when any map reached rows, `proxy` otherwise. (d) not done: session rule holds the "non-negotiable" wording for R5's ledger entry, which is where R5 already says it belongs.

### R4. A benched player in a confirmed lineup passes default preflight (P1, S) | new, RC 1.4

- **What:** the landed preflight hard-fails shelved DK statuses (IL/O/OUT/NA, plus IL10/IL60/PUP/SUSP, `preflight_upload.py:73`), but the posted-lineup cross-check runs only when `--feed` is passed, and a rostered player missing from his team's confirmed lineup is a warning unless `--feed-strict` is also passed (`:594`, `:724`, `:743`). A 3:55pm bench with a blank salary-file Status passes the default check.
- **Why:** the scratch-after-build window is the classic DFS zero, it is the one the commercial tools all built alerting for, and the repo already fetches the feed; the gap is only that the strongest check is opt-in twice.
- **Fix:** preflight auto-resolves the freshest `lineups_feed.json` for the slate date when `--feed` is not passed, printing the feed age it used; a rostered hitter absent from his team's CONFIRMED lineup becomes a hard fail by default (`--feed-lenient` restores warning behavior); TEAM_UNCONFIRMED stays soft; a feed older than 90 minutes prints its age next to the verdict so a stale all-clear is visibly stale. No new evidence artifact, no network in preflight: the feed on disk is the evidence, per the existing design. Done when: a fixture with a confirmed-team bench passes only with the lenient flag; default runs print feed age; a missing feed degrades to today's behavior with one warning line.
- **LANDED 2026-07-27.** Anchors re-verified. `resolve_feed_for_slate` reads the slate date off the entries file's own Game Info cells and takes the freshest `data/slates/<date>/lineups_feed*.json`; a file spanning two dates resolves nothing rather than a wrong one, and says which. Absence from a CONFIRMED lineup is a hard fail; `--feed-lenient` demotes it; `--feed-strict` is kept as a hidden no-op so an existing invocation does not die. Feed age prints on the verdict line and warns past 90 minutes. All three "Done when" clauses have tests.

### R5. The caps decision (P1, decision, unchanged) | was F20, plus RC 1.14's wording

- **What:** `STRATEGY_DEFAULTS` is looser than MLB_Classic §8 on the two most-used postures: wta_satellite pitcher 0.70 / primary stack 0.60 / shared players 7, large_gpp 0.55 / 0.50 / 6, vs §8's 0.43 / 0.35 / 5 (`execution_pipeline.py:610-637`).
- **Why:** duplication is the main enemy in a satellite-heavy portfolio, so cap looseness is a live strategy fact, not a doc nit; and a cap change alters construction, so it deserves its own dated decision rather than riding an integrity commit. Deferred deliberately by the implementation session; this is Ben's call.
- **Fix:** one ledger entry, same shape as 3.10: either adopt §8's tighter caps for satellite-family postures (recommended: R1 makes satellite scoring floor-aware, and tighter caps compound with it) or amend §8 to the shipped values with a reason. Fold in the R3d wording fix so the "non-negotiable" contradiction dies in the same entry. Done when: code and §8 agree or the divergence is a dated ledger decision with the numbers side by side.

- **LANDED 2026-07-27. Ben's call: adopt section 8 on `wta_satellite`, no posture split.** `STRATEGY_DEFAULTS["wta_satellite"]` moved from 0.60 player / 0.70 pitcher / 0.60 stack / 7 shared to 0.45 / 0.43 / 0.35 / 5; SP-pair stays a flat 2. The dated entry is ledger 3.11 and the draft below is superseded by it. **Two claims in the draft were false and correcting them changed the recommendation:** `contest_allocator.plan_and_assign_entries` does not exist on this tree (the section 8 numbers live in `select_and_assign_portfolio`, `contest_allocator.py:1873-1877`, zero production callers, one test caller), and inside that function the caps block is gated on `tournament = ... all(x not in {"cash", "satellite"})`, so a satellite card turns the caps off entirely. Section 8 never applied its numbers to a satellite anywhere and its own heading scoped them to "Lean WTA/GPP defaults", which makes this a new strategy choice rather than a reconciliation. The draft's preferred posture split was rejected on its premise: loose caps for a true WTA assume concentration on one build is right at any entry count, and that holds only at one entry, which is `single_entry` at caps of 1.0. The `large_gpp` half of the divergence was retired in the doc instead: section 8 now names `STRATEGY_DEFAULTS` as the production caps table and records the GPP ladder as deliberate. R3d's "non-negotiable" wording change landed here as scheduled. **Golden baseline did not move, and could not:** the replay passes `LOOSE_CONTROLS` (every cap 1.0, shared 9), so no caps change can reach it; R6(b)'s production-controls replay is what will exercise this. One existing test moved with the decision rather than around it: on the 2-team 6-entry fixture in `test_run_slate_pct_floor_and_clock_end_to_end` the feasibility floor now lifts the 0.35 stack cap to 0.50 and records it in `floors_applied`, where the old 0.60 cap cleared the minimum unaided. Test pin 363 to 365.

#### R5 DRAFT ledger entry, superseded by ledger 3.11. Kept for the record of what was proposed and why it changed.

> **### 3.11 Portfolio cap ownership for the satellite family (DATED DECISION, 2026-07-__, R5)**
>
> **The question.** Two code paths carry two different cap sets and the strategy doc matches the one production does not use. `execution_pipeline.STRATEGY_DEFAULTS`, which `run_slate` merges by posture, gives `wta_satellite` a pitcher cap of 0.70, a primary-stack cap of 0.60, and 7 shared players; `large_gpp` gives 0.55 / 0.50 / 6. `contest_allocator.plan_and_assign_entries`, the contest-cards path, applies MLB_Classic §8's numbers directly: 0.45 player, 0.43 pitcher, 0.35 stack, 5 shared at eight-plus entries. §8 is therefore already implemented, on the path production does not take. Duplication is the main enemy in a satellite-heavy portfolio, so this is a live strategy fact and not a doc nit.
>
> | control | STRATEGY_DEFAULTS wta_satellite | STRATEGY_DEFAULTS large_gpp | MLB_Classic §8 |
> |---|---|---|---|
> | max_player_exposure_pct | 0.60 | 0.40 | 0.45 |
> | max_pitcher_exposure_pct | 0.70 | 0.55 | 0.43 |
> | max_primary_stack_exposure_pct | 0.60 | 0.50 | 0.35 |
> | max_sp_pair_repetition | 2 | 3 | ~12% of entries, min 2 |
> | max_shared_players | 7 | 6 | 5 at 8+ entries |
>
> **What R1a changed underneath this question.** The `wta_satellite` posture covers two different objectives: a winner-take-all, which pays one spot and rewards concentration on the single highest-ceiling build, and a multi-ticket qualifier, which pays for clearing a cut line and rewards clearing it undUplicated. Loose caps are right for the first and wrong for the second. That is the same conflation R1a just removed at the shape level, where `resolve_contest_shape` now routes a satellite to the `satellite` profile and a WTA to `large_wta`. The caps question is the second half of one defect, not a separate tuning argument.
>
> **Recommendation, in order of preference.**
>
> 1. **Split the posture, then set each half.** Add a `satellite` posture at §8's numbers (pitcher 0.43, stack 0.35, shared 5, player 0.45) and leave `wta_satellite` concentrated at the shipped 0.70 / 0.60 / 7 for true winner-take-all. `resolve_contest_shape` already distinguishes them from `inferred_type` and `payout_shape_default`, so the routing work is done and this is a STRATEGY_DEFAULTS row plus a one-line posture branch. It ends the divergence, removes the conflation, and compounds with R1b's floor-aware satellite scoring: tighter caps and a cut-line objective push the same direction, which is the reason to do them together rather than one at a time.
> 2. **Adopt §8 for the whole `wta_satellite` posture.** Simpler, one row. It also tightens true WTA, where concentration is correct, so it trades a known conflation for a known cost.
> 3. **Amend §8 to the shipped values.** Cheapest, and defensible only with a stated reason. There is none on the record today.
>
> **The honest counterargument.** Tighter caps buy decorrelation by forcing the portfolio off its best play. A pitcher cap of 0.43 on an eight-entry satellite portfolio means at least three entries take an arm the engine ranked below the top one, and on a four-game slate the third-best arm can be materially worse rather than marginally. `_slate_feasibility` protects against infeasibility (it derives the minimum feasible pct caps and floors the merged caps up before the explicit override, and reports the floor) but it does not protect against quality dilution, which is invisible in the certified output. Nothing in the archive measures this yet, which is why it is a judgment call and not a fit.
>
> **Also settled here.** CLAUDE.md's Showdown block says the two portfolio controls are "non-negotiable and enforced in the solver", four lines above the sentence describing the order in which they relax. Replace "non-negotiable and enforced in the solver, not in review" with "enforced in the solver, not in review, and relaxed only in the stated order and counted" (RC 1.14, routed here by R3d so one entry retires the contradiction).
>
> **What this does not do.** It sets caps for the satellite family only. It does not touch `single_entry`, `small_gpp`, `mme`, or `cash`, and it does not change the feasibility floors, which may still relax any of these upward on a thin slate and say so.

### R16. The gpp ceiling/floor contradiction (P1, S, decision) | new 2026-07-27, generated by R1b

- **What:** six `gpp` profiles advertised a ceiling/floor split (`small_field_gpp` 0.80/0.20, `single_entry_gpp` 0.78/0.22, `mid_field_gpp` 0.76/0.24, `large_field_gpp` and `portfolio_gpp` 0.72/0.28, `mme_gpp` 0.70/0.30) while `score_lineup_candidate` blended only for `cash` and `ticket_line`, so all six took pure ceiling. R1b named it and left it because extending the blend reranks every GPP contest. The prior note said five profiles; it is six.
- **LANDED 2026-07-27. Ben's call: delete the weights, dated ledger entry 3.12.** Measured before recommending: patching the branch to include `gpp` moved the golden baseline by 3 of 18 entries, all four GPP entries sit in one contest, the same four candidates were selected before and after, exposure and SP-pair distribution were byte-identical, and all three gates held, so the change was a within-contest permutation rather than a change to what gets entered. Deleted on two grounds independent of that measurement: the ladder ran backwards, giving more floor weight as the field grew while `field_pressure_weight` and `salary_uniqueness_weight` in the same profiles ladder correctly, which is evidence the pair was never reasoned to; and floor carries no enrichment signal, since xISO and K-rate land on Ceiling while Floor stays a flat 0.58 multiple of Base, so a 0.28 floor weight discards 28% of the enrichment stack's output in the contests where ceiling is the objective. The weight-consumption contract test drops from two exemptions to one. Zero behavior change and no re-freeze: the code already took raw ceiling. **If GPP floor-awareness is wanted later**, the version to build is a corrected ladder with ceiling weight rising with field size, landed against R6(b)'s enriched replay, because under proxy projections no measurement can separate a good version from a bad one.

### R6. The test suite still measures the wrong 90% (P1, M) | was F22 remainder, plus RC 2.8 and RC 1.2's contract test

- **What:** roughly 30 of 329 tests invoke an engine entry point; blocking scipy leaves most of the suite green; the golden replay still runs loosened controls, so the enrichment stack and portfolio controls sit outside the one end-to-end gate. The skill's evals are three prose scenarios with stale expectations (`evals.json` still expects "v0.1-review"; `SKILL.md:449` still expects "13 modules, 189 tests").
- **Why:** the suite is what lets an agent change this codebase quickly without re-deriving trust, and every remaining backlog item (R1 especially) is a behavior change that needs a harness that would notice a regression nobody is looking for.
- **Fix, in order:** (a) the five solver-independent behavior tests from the 07-25 final (blank-row block, over-cap rejection, overlap honored by a produced bank, posture/shape resolution, export geometry); (b) a second golden replay with production controls and real enrichment, aggregates and assignment asserted separately; (c) the weight-consumption contract test from RC 1.2: perturb each profile weight against a fixed fixture and assert the score moves or the key is deleted (lands with R1); (d) convert the three skill evals to fixtures with expected exit codes, artifact states, and forbidden claims, adding the adversarial cases RC 2.8 lists (stale manifest, absent confirmed starter, multi-ticket satellite, past lock, missing scipy); (e) update the stale counts in SKILL.md and evals.json while touching them. Done when: blocking scipy fails the suite loudly; the golden gate covers production controls; every profile weight is provably live; the skill evals pin exit codes instead of prose.
- **LANDED 2026-07-29, Ben's order: (b) then (a) then (d) then (e); (c) had landed with R1.** Test pin 410 -> 425. **(b)** is `GoldenProductionReplayTests` in test_golden_replay.py, two scenarios over the archived 06-03 slate, one candidate bank, frozen enrichment fixtures (`tests/fixtures/enrichment/`, copies because data/reference/ refreshes between sessions and a golden gate may not read moving inputs). PURE scenario: explicit production postures (wta_satellite x2 + large_gpp; the archived contest names are 'Pocket Cup MEGA Qualifier' family names, so inference is exactly what the Quick Card forbids), zero overrides, and the frozen verdict is **proven jointly infeasible** — that is today's engine truth on this grid and it is pinned error-text-and-all (see R28). CERTIFIED scenario: one recorded operator action (`max_player_exposure_pct` 0.4 -> 0.5, the thin-slate contract's own "explicit overrides win" path), everything else production-merged and visibly binding in the frozen output (exposure max exactly floor(0.5x18)=9, no SP pair above 2). Aggregates and assignment are separate baselines with separate failure messages. The bank builds in-test through the sliced production path: `build_diverse_candidate_bank` at n=18 exceeds 40s on this pool while `bank_cache.extend_bank` exhausts all 64 (pair, team) jobs in ~1.2s; `job_list_exhausted` is asserted so a slow box fails loudly instead of freezing a partial bank. Cross-machine solver determinism leans on R7's scipy pin; two full passes produced sha-identical payloads. Two findings the item did not name: the LOOSE replay's xwOBA leg was structurally inert the whole time (the correction applies to `AvgPointsPerGame`, base_in, and the loose replay's rows never carried it — the enriched replay's rows do, so the correction is now live inside a gate for the first time: 62 non-neutral rows, 62 ceiling-differentiated, 5 pitcher-ceiling, 4 value-guard clips, all frozen); and the approve=False checkpoint said plan-fine for a grid the build then proved infeasible, which is R28(1). **(a)** is `SolverIndependentBehaviorTests` in test_core.py, seven tests, each at the highest solver-free production surface: blank-row block at `validate_dk_entries_file` + `derive_workflow_certification`; over-cap rejection at the post-export validator (`portfolio_caps_passed` with the violation named); the `_cap_count` floor/epsilon/max(1) contract asserted across BOTH copies (dk_entries_manager's docstring promises it can never disagree with contest_allocator's; nothing had ever held them together); overlap arithmetic on fixture rosters including the same-signature cross-contest reuse exemption, plus the first direct coverage of the DU primitives R15 kept (its correction note records they had zero direct references); posture/shape/floor resolution at the run_slate approve=False boundary (explicit postures resolve, satellite pair cap survives the merge, auto-floors fire and say so, no run directory is created); export geometry via `validate_template_preservation` (drift named by row and column, completed-row changes need the explicit mutable grant); and missing scipy is loud at `runtime_preflight`/`_select_solver_backend`. One self-correction: the first version also asserted `optimizer_provenance_line()`, which reports solve HISTORY, not availability, so it is order-dependent under the full suite; the assert was removed with a comment saying why. **(d)** is evals.json fixture/v2 plus `evals/run_evals.py`: eight evals, every one pinning an exit code, artifact states, and forbidden claims; offline by construction (fixture feed, --no-rotowire, THE_ODDS_API_KEY stripped). Fixtures: a lineups-feed template generated once from the archived salary, a date-shifting materializer so lock clocks read live (and `shift='past'` IS the past-lock fixture), a probable-name mutator for absent-confirmed-starter, a wrong-sha manifest builder, and a scipy import shim. The three prose scenarios converted on observed truth: showdown pins `review_grade_build` at exit 0; the two classic-grid scenarios pin the LOUD REFUSAL (exit 3, "proven infeasible", "interaction of the active controls", no brief, no partial file) because that is what the engine does today, with re-pin instructions tied to R28 — pinning the wished-for exit 0 would have been a lie the runner exposes. Adversarials: stale manifest exit 2 at preflight; absent starter fails closed naming the starter; multi-ticket satellite CERTIFIES end-to-end through the explicit posture (the one green certifying path in the eval set, 3 entries, one contest); past-lock pins a KNOWN GAP (the build path says nothing about a slate whose locks passed weeks ago — the pin breaks in either future that fixes it, see R28(3)); missing scipy pins the unhandled-RuntimeError-at-exit-1 reality rather than a wished-for front-door refusal (R28(4)). The forbidden-claims regexes needed one honesty pass of their own: the first versions matched the truthful-labels DISCLAIMER ("never ROI, win-rate..."), so they now forbid affirmative formulations only. One correction to the item's own text: the old evals referenced `inputs/DKSalaries_classic.csv` files that never existed anywhere in the repo; the phantom paths are gone. **(e)** landed with the touches: 425 in audit pin, CLAUDE.md, SKILL.md; SKILL.md gained the one-line eval-runner pointer; the ledger Quick Card line rides the standing inbox fragment (updated in place per its own precedent). Done-when audit: blocking scipy fails the suite loudly (audit dependency gate, eval 7, and the behavior test) — yes; the golden gate covers production controls (both verdicts frozen) — yes; every profile weight provably live — that was (c), landed with R1; evals pin exit codes instead of prose — yes.

### R7. Runtime dependencies are unpinned and re-resolved per session (P2, S) | new, RC 1.11

- **What:** `requirements.txt` carries lower bounds only (`numpy>=2.0, pandas>=2.2, scipy>=1.13`); every fresh Cowork sandbox resolves whatever is current, and the skill reinstalls on session start.
- **Why:** MILP behavior and CSV handling can shift under the engine between slates without any repo change, which quietly undermines the determinism work (F19) and burns deadline seconds on installs; backlog B-4 has flagged the upper-bound question since the migration.
- **Fix:** add a lock file (exact versions plus hashes) for the supported Python; the skill's preflight becomes probe-then-install (import and version check first, install only on failure); record Python/NumPy/pandas/SciPy versions in the run manifest. Done when: a warm session skips pip entirely; the manifest names the versions; two sessions on one lock file resolve identically.
- **LANDED 2026-07-29, folded in at session start per Ben, and the session opened on the exact failure the item describes: a fresh sandbox with no scipy.** `requirements.lock` pins the seven-distribution closure (numpy 2.2.6, pandas 2.3.3, scipy 1.15.3, dateutil, pytz, six, tzdata) with a sha256 wheel hash per line for the supported runtime (Python 3.10, linux x86_64, the Cowork sandbox); requirements.txt stays as the cross-platform floor and the audit's import-name source. `tools/env_probe.py` is probe-then-install: warm prints `env warm ... pip skipped` and exits 0 in about a second; cold prints the one locked install command (exit 2) or runs it under `--install` with `--require-hashes` and re-probes in a fresh interpreter; a missing lock is exit 3 with regenerate instructions, never a silent fall-back to an unpinned resolve. SKILL.md's preflight instructs the probe and explicitly forbids hand-pip around a failed one; the audit's dependency remedy names the probe. `build_state_manager` v1.4: every manifest carries an `environment` block (python version, engine package versions from live imports, lock sha256 when the lock sits beside runs/), so a result can always be tied to the resolver state that produced it. Four tests (EnvLockTests): lock pins with hashes satisfying the floors, the probe decision table tested pure, the manifest block against live imports plus the no-lock None case, and a doc pin that SKILL.md instructs the probe and never the raw unpinned install. Done-when: warm skips pip (evidenced in-session), the manifest names the versions, and identical resolution is what `--require-hashes` over a fully pinned closure buys (the cold path was verified offline against the downloaded wheels). Two facts worth keeping: the transitive pins exist for cold installs while warmth is judged on the engine deps alone, so a sandbox carrying a newer pytz is warm, not dirty; and with scipy actually installed the four suites cost ~55s wall here, so the one-call session-start macro can exceed a 45s tool box — suite-by-suite plus `audit.py --terse` is the fallback (noted in the ledger fragment; not repaired mid-session per the standing rule).

### R8. Hygiene batch (P2, S each) | was F23, re-verified today; CLAUDE.md contradiction added 2026-07-27

**LANDED 2026-07-27.** All of it except two items, both flagged rather than forced. Done: the stale audit sentence deleted with the CLAUDE.md rewrite; SKILL.md:449 now reads `23 modules, 360 tests`; the ledger Quick Card's audit line updated to match; evals.json's showdown expectation cites the three certification gates instead of the dead `v0.1-review` string; `_scratch_20260722/` deleted; the four live `parked/` references in MLB_Classic.md rewritten as "retired and not present in this repo" (the two inside the v2.20.0 section travelled to the legacy file as historical record, which is correct); MLB_Classic.md sections 0.0 through 0.6 (266 lines) moved to `docs/legacy/MLB_Classic_version_history.md` with a pointer, taking the file from 839 to 573 lines; section 13's `project_audit.py`, which does not exist, replaced with `tools/audit.py`; and the three module docstrings that restated a drifted version (`optimizer_v3` said v3.18 against v3.23, `execution_pipeline` v1.9 against v1.14, `contest_allocator` v1.10 against v1.11) now name the VERSION constant as authoritative instead of restating a number that can drift again. **Not done, flagged:** `MLB_Classic.md:53` still reads `project_audit v2.2` inside the v2.26.0 change list, which is a historical module-version record rather than an instruction; and the candidate-cap contradiction the item names as "24 vs 150" does not exist on this tree, the only cap reference is `DEFAULT_CANDIDATE_BANK_CAP` 80 to 150 at `MLB_Classic.md:60`, so the claim is wrong rather than unfixed.

Original item: fix the stale audit sentence at `CLAUDE.md:230-231` ("tools/audit.py runs tests.test_core only, so the Showdown suite sits outside the audit gate"), which contradicts line 42 of the same file and the shipped four-suite gate; delete it or replace with one line saying the audit covers the Showdown suite. Fix the stale counts at `SKILL.md:449` and the stale showdown-version text in `evals.json` (all three are the exact doc-drift class the MUST-claims rule exists for); delete `_scratch_20260722/` and remaining scratch litter; remove the six `parked/` references from MLB_Classic.md; move the ~310-line version-history block to `docs/legacy/`; reconcile the remaining contradictions the corpus carries (candidate-cap 24 vs 150, module header versions). Small, and every item is a token tax on sessions until it lands.

### R15. DU is enforced nowhere on the production path (P1, S, decision) | new 2026-07-27, from the independent-critique session

- **What:** verified against HEAD. `build_candidate_lineup_bank` defaults `bank_constraint_scope='selection'` (`optimizer_v3.py:3495`) and on that default sets `bank_du = None`, so `build_multi_lineup`'s `_resolve_du_threshold_row` (`:2118`) receives an explicit None and returns None, which is "DU disabled". The deferred-to selection stage is `select_final_portfolio_from_candidate_bank` (`:4119`), which holds the DU resolution (`:4161`), the relaxation ladder, and the right-tail quota, **and has zero callers**: the only other mention in the repo is its own changelog line at `:68`. Production selects through `contest_allocator.select_and_assign_entries`, which contains no reference to `du_threshold`, `du_signature`, `matched_units`, or `distinct_unit`. `run_slate` never passes `du_threshold_row` and never sets the scope. So DU is off during generation, deferred to a stage that does not run, and unknown to the stage that does.
- **Why:** the corpus treats DU as a live portfolio control. CLAUDE.md's timeout guardrail promises a timeout "never steps DU relaxation", which is currently true only because nothing steps it. Roughly 500 lines of DU machinery ship, and the 07-24 review already flagged them as dead in the production path; this is the same finding arriving with the call-graph evidence. Either it is a control, in which case something has to enforce it, or it is not, in which case it should stop appearing in the contracts. Straddling is the state that produced this.
- **Fix:** decide, and it is a decision, not a cleanup. **Wire:** `run_slate` passes a resolved DU row and the allocator gains the pairwise DU constraint, which changes construction on every portfolio and therefore belongs beside R5's caps entry. **Delete:** remove `select_final_portfolio_from_candidate_bank`, the DU relaxation ladder, and the DU threshold table, and strike DU from CLAUDE.md's guardrails and from MLB_Classic section 8. Recommend **delete**, on the same reasoning as R1d: nothing consumes it, the diversity job is already done by `max_shared_players`, the overlap preset, and the exposure caps, and a control that exists only in prose is worse than no control because it is budgeted for. If Ben wants it wired instead, it should ride R5. Done when: DU either has an enforcing call site named in the docs, or appears nowhere in the docs.
- **Correction this item forces:** `contest_shapes.py`'s R1a note cited "moving them would silently move the DU threshold row" as the reason satellites stay in `WTA_CONSTRUCTION_SHAPES`. On the production path the DU row is None either way, so that specific consequence is not live. The comment is corrected. The decision to pin construction mode in a scoring commit stands on its own, and `mode` still feeds the live `mode == 'wta'` scenario-family branch at `optimizer_v3.py:2234`.
- **LANDED 2026-07-27. Ben's call: delete the dead stage and the false claim, keep the enforcement primitive.** Every anchor in this item re-verified against HEAD before the change and all of them held. Deleted: `select_final_portfolio_from_candidate_bank` and its three private helpers (`_solve_candidate_subset_milp`, `_selection_pairwise_incompatible`, `_candidate_explicit_right_tail`), 327 lines, referenced by nothing outside each other. Kept: `du_distance`, `validate_du_portfolio`, `DU_THRESHOLD_TABLE`, `_resolve_du_threshold_row` and `build_multi_lineup`'s enforcement path. The reason for keeping rather than full-deleting: R5 landed in the same session tightening caps to buy decorrelation, and DU signature distance is the stronger version of that same control, so removing the primitive while paying for the weaker one is incoherent. The harm was the claim, not the code. **Correction, and it cuts against this decision:** the R15 commit message and the first version of this bullet both said the kept primitive is covered by 11 tests. That is false. `du_distance`, `validate_du_portfolio` and `DU_THRESHOLD_TABLE` have **zero** direct references anywhere in the suite; the 11 was a count of `build_multi_lineup` call sites, most of which route through the bank wrapper and cannot enforce DU, and none of which assert anything about it. The only DU assertions in the repo are the two R15 added, and both assert the DISABLED path. So the kept surface is roughly 200 lines of enforcement machinery with no direct coverage, which is a real cost and makes a future full delete a live option rather than a closed one. The decision stands on its other leg only. **Three findings this item did not name, all fixed here:** (1) `build_multi_lineup` returned `du_validation = {'pass': True, ...}` when DU was disabled and `execution_pipeline:2774` carries that dict into every run payload, so every certified build on record contains a DU pass for a check that never ran. It now reports `enforced: False`, `pass: None`, and a summary saying nothing was checked; the enforced path stamps `enforced: True`. That was the live truthful-labels defect and it was invisible in the item's framing. (2) `tools/solver_probe.py:102` called `build_multi_lineup` with the default `_DU_AUTO`, so the probe CLAUDE.md mandates before every build enforced DU while the build did not, which inflated its estimate and could raise exit 3 on a constraint production never applies; it now passes `du_threshold_row=None` to match. (3) MLB_Classic.md contains zero DU references, so the item's "strike DU from section 8" was already vacuous; `CLAUDE.md:96` was the only live claim and its DU clause is gone. Golden baseline unmoved, as expected from deleting an uncalled function and renaming a diagnostic field. Test pin 365 to 367.

### R18. Multi-session contract for uncoordinated Cowork sessions (P1, S, process) | new 2026-07-28

- **What:** multiple Cowork sessions can point at this folder with no locks, no registry, and no messaging, and every shared surface is last-writer-wins. The class is live, not hypothetical: the 2026-07-23 staging clobber (`build_slate.py:2033-2040`), the 2026-07-25 concurrent critique that read another session's uncommitted edits and reported `FAIL (ran 344)` against a 24-commit-stale tree (reconciled in the 07-27 amendment), and `runs/latest_valid_run.json` carrying a dead session mount path today.
- **Why:** the highest-value shared artifacts (calibration ledger, upload manifest, staged slate inputs, outputs mirror, bank cache) all clobber silently, and the human upload step is the merge point with no way to tell which certified file is which.
- **Fix:** partition by role with a write-ownership map (BUILD per slate; ARCHIVE for ledger/archive/standings/reference; DEV for code and docs), mkdir-based advisory claims in `claims/`, a foreign-dirt git rule replacing the clean-tree gate, create-only fragment inboxes for the ledger and this backlog, and one-slate-one-session as a structural rule: portfolio caps bind the whole entered set and certification is per run, so a cross-session union is uncertified by construction.
- **LANDED 2026-07-28, text and structure only.** CLAUDE.md multi-session contract v1 (roles, claims, foreign-dirt rule, fragments, one-slate-one-session, sha256 in every brief), session-start step 1 rewritten to the foreign-dirt rule, scheduled tasks declared ARCHIVE and claim-aware; `claims/` created with keep-and-ignore rules; `ledger/inbox/` and `docs/backlog_inbox/` created; SKILL.md gained the claim-before-staging check and an Identity (path plus sha256) line in the report; the runbook gained ARCHIVE claims and the fragment-merge step. Code enforcement is R19 through R23; until those land, the contract binds only sessions that read it.

### R19. `tools/claim.py` (P2, S) | new 2026-07-28

- **What:** the claim protocol is four hand-typed steps, and a protocol that is a procedure gets skipped at T-20.
- **Why:** one command is what a contract can reliably instruct, and scheduled tasks need a check they can run before writing.
- **Fix:** `take`/`check`/`release`/`sweep` subcommands over the same mkdir semantics, plus a foreign-dirt classifier that maps `git status --porcelain` against a role's write set. Scheduled tasks call `check` first and turn a held claim into a report. Done when: SKILL.md and the runbook each instruct one command; a held claim exits nonzero and prints the owner.
- **LANDED 2026-07-28.** All five subcommands plus `dirt` with a `--porcelain` test seam; six tests in test_core against a temp root. Design decisions worth knowing: slate resources are used verbatim (`slate_<date>_<tag>` carries its date) while ledger/inbox/engine get the UTC date suffix; release writes `released_utc` into owner.json AND touches a RELEASED marker, so releasing never needs the delete grant that removing a file does; re-take of a released claim is check-then-write and the tool says so, because the atomic mkdir only guards the first take. `dirt` exempts the fragment inboxes (pending fragments are the protocol working) and tells BUILD plainly that its surfaces are gitignored, so the slate claim is its protection, not the git gate. Still open from the Done-when: pointing SKILL.md and the runbook at the one command instead of the raw mkdir procedure; the raw procedure stays correct either way.
- **Done-when CLOSED 2026-07-29.** SKILL.md's multi-session check now instructs `claim.py take --beacon` and `claim.py release` with the raw-mkdir aside removed, and the archival runbook's step 6 instructs `claim.py take`/`release` for ledger and inbox, stating that a held claim exits nonzero and prints the owner. CLAUDE.md's contract text keeps the raw primitive on purpose: it defines the protocol the tool implements. A ninth ClaimToolTests test pins both docs to the tool (each names `tools/claim.py`, neither instructs `mkdir claims/`, release is one command) so they cannot drift back silently.

### R20. Staleness tripwires on the certified path (P1, M) | new 2026-07-28

- **What:** certification proves internal consistency, not freshness. Staged inputs can be clobbered mid-build (the 07-23 incident); `promote_run` is last-writer-wins on `runs/latest_valid_run.json` with no compare-and-swap; late swap refines whatever parent the pointer names at read time and `current_matches_parent_export` records a mismatch without blocking; and nothing ties the file Ben uploads to the run that certified it.
- **Why:** stale-read failures are the quiet ones, and every one of these can be made loud with machinery that already exists: input sha256s are recorded at intake, and the pointer already carries `manifest_sha256`.
- **Fix:** (a) print the delivered sha256 in every brief and add `--expect-sha256` to preflight; (b) certification re-hashes the staged inputs and feed against the intake manifest and fails `workflow_valid` with "inputs moved underneath the run" on mismatch; (c) `promote_run` records the pointer sha it read and refuses to overwrite a pointer that changed, and late swap hard-blocks on a parent-export mismatch instead of noting it. Done when: a mid-build clobber of `data/slates/<date>/` fails the gate by name; two racing promotions produce one winner and one loud refusal.
- **(a) LANDED 2026-07-28; (b) and (c) open.** `--expect-sha256` takes the full hex or a prefix of 12+ chars; anything shorter is a usage error (exit 3), not a match, because a check that can pass by accident is not a check. Mismatch is a hard failure naming both hashes. Four tests. One claim in the item was already true and is corrected here rather than rebuilt: briefs have carried `delivered_sha256` (and `delivered_path_repo`) since the 07-25 manifest work, so (a)'s brief half was found landed, not built; the flag is what was missing.
- **(b) + (c) LANDED 2026-07-28.** (b) is `build_state_manager.verify_inputs_unmoved`, wired into `promote_run`: at promotion every recorded input's `source_path` must still hash what intake recorded; a clobbered source blocks with "inputs moved underneath the run: <name>", a deleted one with "vanished", and the run is marked blocked. Deliberately NOT wired into `verify_run_bundle`, because re-verifying an old run's sources after a legitimate same-date restage would false-block late swap's parent resolution; the check is meaningful exactly once, at promotion inside the building session, and that is the only place it runs. (c) `promote_run` gains `expected_pointer_sha256` (compare-and-swap; the sentinel default keeps the unconditional write as the manual-recovery path), `execute_portfolio` captures `read_pointer_sha256` at `create_run` and passes it at promotion, and a refused promotion returns `pointer_conflict` without mutating the run, which stays `building` and valid. The swap half: `_assert_parent_lineage` raises on a false `current_matches_parent_export`, `run_late_swap` gains `allow_parent_mismatch=False`, and `tools/late_swap.py` gains `--allow-parent-mismatch`. Eight tests. One consequence worth knowing: a second same-date draftgroup that promotes after a first delivery makes a swap of the first file block by design, because the pointer no longer names its parent; the flag is the reviewed path through.

### R21. File-layer concurrency defects (P1, S) | new 2026-07-28

- **What:** three known-defect writes. `preflight_upload.py:643` stamps the manifest through the fixed tmp name `.upload_manifest.json.preflight.tmp`; `net_to_date.py:56` uses the fixed `.own_results.json.tmp`; `late_swap.py:455` delivers to a fixed `DKEntries_lateswap.csv` with a bare `write_bytes`, no slate tag, no run id, and no manifest row, which default preflight then hard-fails.
- **Why:** two concurrent writers interleave into one tmp file and either can rename partial bytes over the real manifest; the late-swap name silently overwrites a prior swap and lands unrecorded.
- **Fix:** pid/uuid tmp names like the rest of the repo; late swap adopts `DKEntries_lateswap_<tag>_<runid8>.csv` and calls `record_delivery`. Done when: no fixed tmp name greps anywhere; a late-swap delivery passes default preflight with a manifest row.
- **LANDED 2026-07-28.** uuid tmp names in `stamp_manifest_status` and `net_to_date.append_record`, pinned by a regression test that greps both sources. Late swap: the delivered name is `DKEntries_lateswap_<tag>_<runid8>.csv` (tag from `_slate_tag`, so the manifest supersession key matches the build's and the swap becomes "the" delivery for the slate), the write is staged then `os.replace`d, `record_delivery` writes the row (`projection_tier='proxy'`, parent named in notes), a bookkeeping failure prints `MANIFEST NOT RECORDED` loud instead of passing silently, and the tool prints the delivered sha256 with the exact `--expect-sha256` invocation to verify it at upload. Two naming tests.

### R22. Bank cache merge-on-save (P1, M) | new 2026-07-28

- **What:** `extend_bank` loads once at init and saves once at the end by whole-file `os.replace` (`bank_cache.py:138`, `:572`), so the later of two concurrent slices discards the earlier one's candidates and `attempted` keys; and `drop_stale_jobs` purges every entry whose `conditions_sig` differs, so two sessions with slightly different enrichment each erase the other's work and persist the erasure.
- **Why:** the exit-10 resume contract ("run the same command again, the bank persists") is false under any interleaving, and the discarded solve time is invisible.
- **Fix:** reload the file at save time and union candidates and attempted before replacing; keep the stale-purge but scope it to the writer's own signature. Done when: two interleaved `extend_bank` runs leave the union on disk; a resume after an interleaved write re-solves nothing it already solved.
- **LANDED 2026-07-28.** `save()` reloads the file and writes the union of disk and memory (candidates deduped on the ordered roster, attempted keys unioned). Memory deliberately keeps the writer's own view: `as_candidates` serves it and the report counts are suffix-filtered, so entries built under another session's conditions signature stay on disk for that session's resume without ever being served to this one. `drop_stale_jobs` is unchanged in memory and no longer leaks to disk, which resolves the purge question the item raised: the file keeps everyone's work, each session serves only its own. Cost accepted and stated: truly dead conditions accumulate in the file until the date-scoped cache is retired, which it is, per slate. Three tests.

### R23. The miner owns the inbox move; ledger blocks become fragments (P1, S/M) | new 2026-07-28

- **What:** nothing in code moves a mined CSV out of `data/standings/inbox/`; the documented move to `data/archive/<date>/` is a manual step, and today 122 CSVs sit in the inbox while their `mined_*.json` siblings exist in the archive. `--emit-ledger` prints to stdout and the paste is a human step that double-counts on a double paste.
- **Why:** the registry and `own_results.json` dedupe per contest id; the ledger paste does not, and archetype-conditioned counts feed the R10 gate, so a double paste poisons the prior weeks later with no attributable cause.
- **Fix:** the miner moves the CSV to `data/archive/<date>/` on a successful mine (fail-closed runs leave it in place), and `--emit-ledger` writes `ledger/inbox/<date>_miner_<contest_id>.md` instead of stdout, so the paste becomes ARCHIVE's merge step. Done when: a re-run finds an empty inbox instead of relying on dedupe; a ledger block cannot land twice because the fragment is consumed on merge.
- **LANDED 2026-07-28.** `archive_mined_standings` moves a mined CSV only when it actually lives in the repo's inbox, so fixtures, selftest tmp files, and ad-hoc paths never move; fail-open on OSError, because a mount without the delete grant can refuse the rename and housekeeping must not fail a completed mine; `--no-archive-move` opts out. `--emit-ledger` writes the fragment and deliberately does not print the block, so it cannot be pasted twice; a re-mine overwrites its own fragment. Runbook step 6 now describes the merge instead of the paste. The 122 already-mined CSVs sitting in the inbox today are ARCHIVE's to drain: each re-mine now ends with the move, and the registry and own_results dedupes make the re-runs no-ops. Four tests.

### R24. Builds never block builds: slate claims become beacons (P1, S, contract) | new 2026-07-29, Ben's call

- **What:** contract v1 made the slate claim a mutex and defaulted unassigned sessions to read-only whenever claims/ was non-empty, so a second session in the same Cowork instance refused to generate lineups. Ben's directive: err on the side of generating lineups; only DEV needs exclusivity.
- **Why it is safe:** Entry IDs are fixed by the DK template, so two certified files for one contest are alternatives, not a union; the manifest's supersession and the sha256 in every brief name the delivery; R20(b) catches a staged-input clobber at promotion; R20(c) turns a promotion race into one winner and one loud refusal. The structural ban narrows to what is actually structural: never split one entry bank across sessions by Entry ID ranges.
- **LANDED 2026-07-29, contract v1.1.** CLAUDE.md: mutex/beacon split (engine, ledger, inbox stay mutexes), unassigned sessions may always build, the one-slate paragraph replaced. SKILL.md: light the beacon, note a parallel build, never stop and never wait. `claim.py take --beacon`: a held claim prints the owner and exits 0. Two tests. Residual risk accepted and stated: a beacon drops when its owner delivers, so DEV's builds-live signal can gap while a second build still runs; DEV during live windows stays Ben-arbitrated.

### R25. late_swap.py could not finish a three-entry, one-slot refinement (P1, M) | new 2026-07-29, from a BUILD fragment

- **What:** four defects chained on the 2026-07-28 night slate (fragment merged here). The feed path was hardcoded to the shared per-slate cache, so an hours-old feed read five posted teams as TBD and tripped the stale-platoon block. `--budget` was per extend_bank call, one general plus one per pinned entry, so three pinned entries cost four budgets before the joint solve began. The joint MILP's 30s limit was reachable only through the undocumented `controls['time_limit']` key. And the long stages printed nothing, so every timeout looked identical.
- **LANDED 2026-07-29, the bounded parts.** `--lineups` (read-only, mirrors build_slate.py, never touches the shared cache); `--budget` is now the TOTAL slicing budget with the bank cache as the resume; `--solver-budget` maps to `controls['time_limit']`, an explicit `--controls-override` still wins; the swap passes `stale_platoon_policy='warn'`, because a post-lock swap blocked on reference age is the process preventing the lineup; a pre-solve line names entries, candidates, and the time limit. Two tests. The arithmetic that now fits one warm 45s call: ~15s import + `--budget 8` + `--solver-budget 15`.
- **Still open, the item's second half:** the minimal-repair fast path (the fragment's fix 1): when only authorized entries change, verify the untouched portfolio's caps arithmetically and solve per entry, falling back to the full joint MILP when the check fails. It changes construction on the certified path, so it is a designed decision with tests, not a flag. The fragment's hand-patched delivery this night was honestly labeled `certified_with_manual_patch`; the fast path is what retires that category.
- **Second round, 2026-07-29 evening, from a BUILD fragment: same pain, four more causes, and one of them shipped a bad file.** A three-batting-order refinement took ~75 minutes and 30+ invocations across three correction rounds. The four new causes are siblings of this item, not a new topic, and they landed as **R29(1) through R29(4)** rather than being restated here: the stale `--locked-teams` list that let DK reject 7 of 16 entries, the downgrade-refused run that still promoted the pointer, the flat portfolio controls stricter than the build's, and the missing `--salary` override. The two that are still R25's own:
  - **Open, and the fragment's bug 2:** the joint multi-entry re-solve still does not fit a 45s call. Fourteen pinned entries never finished in one call even with loose controls; one Entry ID per call worked first try, twelve times out of twelve. That points at the joint compatibility check across simultaneously-changing entries, not at candidate generation. The fragment asks for one of: a supported single-entry-at-a-time mode for n>1 under a tight budget, a reliable 2-4 entry batch, or a `solver_probe`-style pre-flight feasibility probe for swaps so the binding constraint is known before a call is spent on a doomed solve. The last is the cheapest and is the one that would also have told the session which of the two Bug-1 stories it was in.
  - **The fragment's bug 3 is a sandbox quirk, not repo code**, and Ben's call was to land it as an operating note: merged stdout+stderr swallowed the real error text, so several calls were re-run against output that had already reported the reason on stderr. Landed in `skills/generate-lineups/SKILL.md`, not as engine work.

### R26. Postponed game leaks into the pool as live players (P0, M) | new 2026-07-29, from a BUILD fragment

- **What:** DK marks a postponed game's Game Info as the literal string `Postponed`. `build_slate_pool`'s exclusion path matches `team_game` values against feed-derived game ids, and the literal never matches, so ATL and NYM fell into `tbd_teams`, took platoon-projected orders, and a postponed-game pitcher (Chris Sale) reached the bank as P1 in several entries before a manual catch. The `excluded_postponed` bucket stayed empty; nothing printed.
- **Why P0:** it is shelved-player leakage arriving through the game-status path, invisible to every existing warning, and it reached candidate lineups on a real slate.
- **Fix:** in `build_slate_pool`, treat a salary row whose Game Info fails to parse as a matchup (`Postponed` included) as an exclusion, matched by team against the feed's own postponed games; report the teams in `excluded_postponed`; fixture test with literal `Postponed` rows asserting the players never reach keep. NOT fixed this pass; this is the next DEV item on the board.
- **LANDED 2026-07-29.** Two independent exclusion signals, either alone sufficient, because the incident was exactly their disagreement. Signal 1, the salary file: a non-blank Game Info that fails the same matchup predicate `infer_opponent_and_game_id` applies (the literal `Postponed` included) excludes the team, on the CSV's eligibility authority. Signal 2, the feed: a game marked postponed/cancelled/suspended excludes its teams by team name rather than game-id equality, so the match survives the salary side carrying a literal instead of an id. Excluded teams land in `teams_report` as `excluded_postponed`, a new `pool_report["excluded_postponed_teams"]` key makes the bucket one read deep, and each exclusion warning names which signal fired. Two closures the item did not spell out: `declared_pitchers` gained the excluded-team guard probables already had, so an explicit declaration is not a back door into a postponed game; and when every salary row's Game Info fails to parse at once, Signal 1 stands down and a blocker names a DK format change or wrong file instead, because excluding the whole slate under a weather label would relabel a parser failure as postponement. A blank Game Info still excludes nothing, because a blank cell never removes a player; it warns, and Signal 2 can still fire. Four tests: the incident shape (literal plus feed status, players never reach keep), salary-literal alone against a stale feed still saying Scheduled, the declared-pitcher back door, and the all-rows-unparsed blocker. Golden baseline unmoved; its fixtures carry no postponed games.

### R27. build_slate.py printed SOFT while the gate blocked (P1, S) | new 2026-07-29, from a BUILD fragment

- **What:** `build_slate.py` inherited `stale_platoon_policy='block'` from the engine default while its own print layer labeled the same condition `pool (soft):`, so the build failed `lineup_gate_passed` with no cause on screen, directly contradicting CLAUDE.md's "prints and the build ships." The session had to rebuild the pool by hand to find the blocker text.
- **LANDED 2026-07-29, half.** `build_slate.py` and `late_swap.py` now pass `stale_platoon_policy='warn'`, so reality matches the stated contract; the age still prints, a RotoWire merge still clears it, and CLAUDE.md's build-contract item 2 now says exactly what holds. **Open half:** when a pre-export gate fails, print the pool report's blockers to stdout (the fragment's fix 2), so no session ever again reproduces the pool by hand to learn why a gate failed.
- **Open half LANDED 2026-07-29; R27 closed.** `gate_failure_detail` in `build_slate.py` collects, from evidence the engine already records, the failed and missing pre-export gate names off the result's errors, each named gate's `workflow_gate_evidence` line (with a stated `no evidence recorded` fallback), and the pool report's blockers. `run_classic`'s not-certified branch prints them (`gate <name>: <evidence>`, `pool blocker: <text>`) and merges the same keys (`failed_gates`, `gate_evidence`, `pool_blockers`) into the `not_certified` JSON payload on stdout, so the cause rides the failing command's own output in both channels. One test through the script harness pins extraction, duplicate collapse, the non-gate-error filter, the fallback, and the empty-input no-op.

### R28. Thin-slate certification landmines: the checkpoint promises what the build cannot deliver (P1, M, decision) | new 2026-07-29, from R6(b)'s replay evidence

- **What:** five related facts, every one reproduced on the archived 2026-06-03 slate through both front doors (run_slate and build_slate.py) and now pinned by the production golden replay and the fixture evals. (1) `_slate_feasibility`'s auto-floors are POOL-keyed, so the approve=False checkpoint passes a plan whose approve=True build then proves jointly infeasible: on the eval fixture the floors visibly fired (player 0.4→0.5, pitcher 0.43→0.5, shared 5→8, pair 2→5) and the entry-level joint MILP still returned "no single control is arithmetically binding against this bank, so the interaction of the active controls is". The interaction lives in the BANK; pool arithmetic cannot see it, so on a live thin slate this sequence is checkpoint-green at review, proven-infeasible at T-minus-minutes. (2) Concretely: today's engine cannot certify the archived 18-entry, three-contest grid (satellite x2 + gpp) under the postures production would assign. R5's satellite caps demand portfolio breadth a 2-game bank cannot serve. The golden's certified scenario needed one recorded override (player pct 0.4→0.5); whether that stays an operator action or becomes an engine-computed bank-aware floor is the decision this item carries. (3) The build path performs no lock-clock check at all: a slate whose every lock passed weeks ago builds (and today, refuses on the unrelated interaction error) without one word about the clock; eval 6 pins the absence and breaks in either future that changes it. (4) build_slate.py has no front-door dependency check, so a missing scipy is an unhandled RuntimeError at exit 1 AFTER staging and pool work, where the audit and the skill preflight would have said so in one line before any work; eval 7 pins that reality. (5) The not-certified refusal path writes no brief even when `--brief` is passed: the R27 cause detail rides stdout only, so a session that captured only the brief file learns nothing; eval 0 pins the absence.
- **Why P1:** (1) is the quiet-failure class this project keeps paying for, and it books the T-minus-minutes slot, which is the most expensive minute there is. (2) means every thin slate with satellite entries is a coin-flip between certifying and a proven-infeasible wall the checkpoint did not predict.
- **Fix directions, decisions for Ben where they change strategy:** for (1)+(2), either the feasibility block gains a bank-aware leg (cheap once the sliced bank exists: extend_bank is ~1s on a thin pool, and the checkpoint could solve the same joint MILP in plan mode and report the verdict as the plan), or the floors gain the interaction case some other way, or the thin-slate contract states plainly that pct floors are pool-keyed and the operator override is the designed remedy (in which case the checkpoint should SAY "bank interaction unchecked until approve"). Wiring the checkpoint to pre-solve is the honest version and retires (1) entirely; it costs a plan-time solve. For (3): a build whose first lock is already past should require an explicit flag naming what it is (`--past-slate-replay` or similar), because the only legitimate reasons are replays and evals. For (4): build_slate runs the same import check the audit runs, first, one line. For (5): the not_certified JSON payload writes to the `--brief` path too; the brief schema gains `status: not_certified` with `failed_gates`/`pool_blockers`, which R27 already collects. Done when: a thin-slate plan either predicts the joint verdict or says it cannot; eval 0/2/6 get re-pinned deliberately; a past-lock build without the flag refuses naming the clock; a missing solver refuses before staging; every refusal leaves a brief.
- **LANDED 2026-07-29, Ben's call: wire the pre-solve (option 1), do not paper it with prose.** Test pin 425 -> 437; `execution_pipeline` v1.14 -> v1.15. **(1)** is `_plan_joint_allocation`, called from `run_slate` inside the `not approve` branch, so approve=True is byte-identical. It builds a bank through the sliced path into a TEMPORARY `BankCache` (never the shared per-slate cache: a plan's conditions signature is its own, and a speculative solve must not seed a build's bank), then calls the same `select_and_assign_entries` the build calls, and emits exactly one of three verdicts. `would_certify` names the allocation leg only, because `workflow_valid` is derived post-export and plan mode cannot evaluate it; `proven_infeasible` carries the build's error string verbatim; `unchecked` names the budget it ran out of. `plan_solve_budget_s` (default `PLAN_SOLVE_BUDGET_S` 25.0) sets it and 0 disables the solve loudly. Placed after the schema gate so a blocked plan never pays for a solve; still creates no run directory; a predicted refusal warns and returns `passed=True`, because the checkpoint is the review and not a gate. Two honesty decisions inside it. The verdict states its own exactness: with `candidates_override` it solved the build's own candidates (`exact_for_this_build: True`), and on the auto-bank path the sliced plan bank is NOT `build_diverse_candidate_bank`'s bank and the summary says so rather than implying an identity. And an allocator time limit is reported `unchecked`, never `proven_infeasible`, because collapsing the clock into a proof is the exact mislabel this item exists to remove. Verified on the 06-03 fixture through both scenarios: PURE plan and PURE build return the identical error string, CERT plan says would-certify and the build certifies, plan cost 0.03s and 0.48s. Four golden tests pin the agreement (as an agreement, not a frozen value, so the baseline did not move) plus eight in test_core for the sliced-bank labelling, the zero budget, the never-blocks rule, the time-limit branch, the empty-entries case, and the degrade-on-raise path. **(2)** all three legs landed: `check_dependencies` (the audit's own) runs at build_slate's front door before staging, exit 4 `missing_dependencies`; a first lock in the past refuses before staging with exit 4 `past_slate_locks_passed` naming the hours and the `--past-slate-replay` way through; and the not-certified path returns its payload as the brief instead of `{}`, so `--brief` finally produces a file on the one path that most needs one, carrying `status`, `failed_gates`, `pool_blockers`, gates and run_id. Exit 4 rather than 3 for the first two on purpose: 3 is a build that ran and refused, 4 is a precondition never met.
- **CORRECTION, and it inverts this item's headline claim.** Fact (2) above — "today's engine cannot certify the archived 18-entry, three-contest grid under the postures production would assign" — is FALSE for the build path. It was measured off the production golden replay, whose sliced bank freezes at 30 candidates; through `build_slate`'s larger auto-bank the same grid, same postures, same fixture CERTIFIES, 3 of 3 clean runs at about 26s. So R5's satellite caps do not demand breadth a 2-game bank cannot serve; they demand breadth a THIRTY-LINEUP bank cannot serve, and the auto-bank clears it. Both measurements are real and they do not conflict, which is itself the argument for (1): feasibility here is a property of the bank, so a checkpoint that solves the bank it has is the only thing that can predict it, and pool arithmetic never could. Eval 0 is re-pinned exit 3 -> **exit 0, certified**, and the golden's PURE pin keeps its refusal with a docstring saying plainly that it pins the sliced-bank verdict only.
- **Why the old measurement looked stable, which is the more valuable finding.** `RepoSurfaceGuard` snapshotted `data/slates/` and `outputs/` but not `runs/`, and `build_slate` writes `runs/bank_cache_<date>_<poolsig>.json`. Every eval run therefore left a per-slate bank cache behind, and a later run read it: an eight-candidate leftover short-circuited the bank build so the identical command refused in 4.6s where clean runs certify in ~26s. That is a pinned exit code decided by whether someone ran the eval before. The worse half is not about evals at all: that file is keyed by slate date and pool signature, so an eval run could leave a bank that a REAL build for the same date would read, which is the R20/R22 staleness family arriving through the test harness. Fixed in this session at Ben's call: the guard gained a `FILE_GLOBS` leg covering `runs/bank_cache_*.json` and restores them byte-exactly. `runs/` is deliberately NOT guarded wholesale — it holds live run directories and the promotion pointer, and snapshotting those would fight a concurrent BUILD session.
- **(3) re-pins, all eight evals green individually.** Eval 0 to exit 0 with the brief pinned `status: certified` (and `"status": "certified"` removed from its own forbidden-claims list, where it had been left over from the refusal pin — it was simultaneously required and forbidden). Eval 2 keeps exit 3: same grid under `--max-seconds 25`, which is a bank too small to satisfy the caps, so the deadline contract still reads true; its brief flips to must-exist. Eval 6 to exit 4 with the lock message, closing the KNOWN GAP it was pinned open against. Eval 7 to exit 4 at the front-door dependency check, re-pinned deliberately alongside the three Ben named because leg (4) moved it. Eval 1 (Showdown) needed `--past-slate-replay` added to its command: `materialize_showdown` copies the archived 2026-07-18 fixture unshifted, so the new guard correctly refuses it, and declaring the replay is right where carving a Showdown exception into the guard would not be. Golden replay green twice consecutively.
- **Still open from this item, flagged not fixed:** eval 2's 25s budget sits near the boundary where the bank becomes big enough to certify (clean runs need ~26s), so its exit-3 pin is marginal and will flake on a materially faster or slower box. The fix is a deterministic bank for that eval rather than a wall-clock budget, and it is a fixture design change, not a re-pin.

### R29. The false-PASS cluster: every defect that made a gate lie or shipped a wrong file (P0 head, M) | new 2026-07-29 evening, from two BUILD fragments

- **What:** six defects from one evening's two builds, grouped by what they have in common rather than by which file they live in. None of them changes construction; all of them made an output say something that was not true. Four are siblings of R25 and are cross-referenced there. Ben's framing, and it is the right one: a tool that can go stale mid-use is not a tool that verifies, and a bug that teaches the operator to switch off a safety is worse than the bug.
- **Why P0 at the head:** (1) shipped a bad file to DraftKings. (2) trains the operator to disable R20(c). The rest each converted a specific cause into a generic message, and a generic message is what sends a session chasing the wrong fix under a clock.
- **(1) LANDED. `verify_export.py --locked-teams` was a static list that went stale mid-use.** The swap chain ran 7:23-8:02 PM ET against a list passed once at 7:23; two more games locked underneath it (KC@MIN and NYY@CWS at 7:40, CHC@STL at 7:45), the tool printed PASS, and DK rejected 7 of 16 entries. The "introduced a player whose game has already started" logic was already in the file and would have caught every one; it was handed the wrong list. Now the derivation always runs and `--locked-teams` is UNIONED in rather than substituted: it can add a team the clock calls open, it can never remove one the clock calls started, and a list omitting a started team is reported STALE with the derived set used anyway. The clock source is the lineups feed via `build_status_map_from_lineups_feed`, the same fact `late_swap.py` reads internally, so the tool that swaps and the tool that verifies no longer read lock state off two sources; the feed also knows a postponed game has not locked, which Game Info cannot, so Game Info is the named fallback. `--as-of` replaces `--now` (alias kept) and the report prints the clock and the source. Feed resolution imports preflight's `resolve_feed_for_slate` rather than restating it. 13 tests, including the rejection reproduced end to end and its same-file-one-hour-earlier counterpart, which must still pass.
- **(2) LANDED. A downgrade-refused run still promoted `runs/latest_valid_run.json`.** `execute_portfolio` promoted at certification time; `late_swap.py`'s downgrade check runs after that, so a refused swap mirrored nothing and still owned the pointer. The next swap then failed on a parent-mismatch `ValueError` that reads like a multi-session collision, and the documented workaround was `--allow-parent-mismatch` on every later call, which is exactly the R20(c) protection switched off because a bug taught the operator to distrust it. Certification and delivery are two facts and the pointer is a claim about delivery: `defer_promotion=True` returns the certified run unpromoted carrying `pointer_sha_at_create`, and `promote_deferred_run` completes it after the accept-downgrade decision resolves and the mirror is written. R20(c) is not weakened by the longer window; the compare half travels with the result. A promotion refused after the mirror leaves the file with no manifest record, which default preflight hard-fails, and says so. 6 tests including a source-order pin, because the ordering IS the fix.
- **(3) LANDED, R25 sibling. `late_swap.py`'s flat `PORTFOLIO_CONTROLS` were stricter than the build that produced the file.** `max_sp_pair_repetition: 1` against STRATEGY_DEFAULTS' 2-3, applied to every contest regardless of shape. A swap re-certifies the WHOLE portfolio, so a legally-built file violated the swap's own caps before the swap did any work, and the message was a bare "no compatible candidate" — indistinguishable from a thin bank. That cost the first ~20 minutes and a dozen calls growing a bank that was never the problem. Controls now come from `_merged_controls_for_build` against the file's own resolved postures: the build's function, the same tightest-cap-wins merge, so they cannot drift. The flat dict is DELETED rather than kept as a fallback, because a default that can disagree with the build is a second source of truth for the same number. Second half: the controls in effect print before the solve, a control violation names the binding control and its value, and "no compatible candidate" says explicitly that it is not a portfolio control and points at `--budget` and the entry's pins. 12 tests.
- **(4) LANDED, R25 sibling. `late_swap.py` had no `--salary` and hardcoded the shared staging path.** A concurrent Showdown build for the same date overwrote `data/slates/<date>/DKSalaries.csv` mid-swap and every entry failed with "embedded player pool overlaps the salary file at 0.0% (0/744)"; the only route around it was swapping staged files in and out around each of ~19 remaining calls. `--salary` is read-only and points anywhere, including `runs/<id>/inputs/DKSalaries.csv` and the `DKSalaries_<tag>.csv` a draftgroup collision already preserves. `_slate_tag` and `pool_signature` both derive from CONTENTS, so a tagged copy yields the same delivery name and the same bank-cache key and the swap still shares the build's cache. Both overridable inputs resolve in one `resolve_swap_inputs` so they cannot acquire different rules, and the run prints which path it used and whether that path is shared. 7 tests. **No `--entries-source`, deliberately:** every entries read already comes from `--parent-entries`, so there is no staged entries file to route around, and a second entries path would only let the reserved grid disagree with the file being refined with nothing checking that.
- **(5) LANDED. Showdown odds reported "no moneyline matched" on a game that had odds.** Two stacked silent bugs ended in `win_share_basis = even_split_no_market_input` and a 50/50 thesis allocation on TEX@TB, which the market had at TB -144 / TEX +122 all night. **(a)** the key: `load_odds_packet` read `os.environ` alone, empty in a Cowork bash call, with the real key in `REPO/.env`; `tools/fetch_slate_bundle.py` had a loader and was the only thing using it. `mlb_engine/repo_env.py` is now the one place that knows where this repo keeps secrets and both callers use it, environment still winning over the file. **(b)** the shape: the recognised wrapper keys did not include `games`, which is the skill's DEFAULT output, so it fell through silently. `normalize_odds_payload` reverses the skill's per-book flattening exactly for h2h/spreads/totals so both shapes feed one parser, and an unrecognised payload raises naming the keys it found. The caller's one sentence covered four causes and now says which: unrecognised shape, unresolvable key, a payload that parsed to zero games, or a market genuinely not posted. At n=20 the corrected 56.5/43.5 split rounded to identical lineup counts, so nothing shipped wrong — by luck, not by design. 15 tests.
- **(5) residual, and it cannot be fixed from a Cowork session:** the `mlb-game-odds` skill's own `load_api_key` checks `/mnt/project/.env` and `/mnt/user-data/uploads/.env`, neither of which exists in this mount layout, then the env var. Its script lives on a read-only filesystem and `save_skill` replaces only `SKILL.md`, keeping other files, so the script cannot be updated from here. Its failure is at least loud (it exits naming where it looked), and the repo side no longer depends on it: a build's auto-fetch resolves the key itself, and `--odds` now accepts the skill's default output. The operator-side workaround is in SKILL.md. Ben's call whether to edit the skill by hand.
- **(6) VERIFIED CORRECT, not fixed, plus a durable pin.** The mini-MAX row a BUILD session added to `dk_contest_archetypes.csv` resolves end to end: pattern `mini-MAX` -> payout token `mme_top_heavy` (a valid `payout_shape_default` token, precedented by the `150-Max` and `MME` rows) -> posture `mme` (in STRATEGY_DEFAULTS) -> shape `mme_gpp` (in CONTEST_SHAPES) -> profile `mode_family: gpp`, matching the row's own curated `objective_class`. It does not shadow the 150-Max family: `[150 Entry Max]` and `[150-Max]` are disjoint strings and both land on `mme_gpp` anyway, so the routing outcome is identical either way. The R1(a) confusion Ben was watching for is not present. The test walks the LIVE csv so a row added later is covered, and it pins that every row resolves to a real posture/shape/profile, that each curated `objective_class` agrees with its payout token, and that the payout-token / shape-name collisions are exactly the two longstanding ones (`portfolio_gpp`, `single_entry_gpp`) — that last pin is the R1(a) ambiguity held still, so a new collision has to be decided rather than inherited. 8 tests. The CSV itself is untouched: it is ARCHIVE's path and that row is another session's uncommitted work.

### R32. A pasted mlb.com lineup is the primary source; the API feed is fallback (P1, M) | new 2026-07-30, Ben's directive

- **What:** Ben pastes https://www.mlb.com/starting-lineups into the prompt. That paste is what he is looking at and it came from the source of record, so re-fetching it over the network to learn what he just typed spends a call and creates a second answer that can disagree with the first. The API feed becomes fallback for what the paste does not cover, and nothing else.
- **Ben's three calls, taken as recommended:** partial paste is projected-and-reported rather than a blocker or a feed-filled gap; the paste enters as a normal `lineups_feed.json` rather than a new front-door branch; and handedness was to come from a cached reference. **The third was answered on a false premise of mine and is moot:** batter handedness IS on the page as `(R)/(L)/(S)`, so a pasted team needs no handedness lookup at all. No reference file was built.
- **LANDED 2026-07-30.** `mlb_engine/intake/paste_lineups.py` parses the real paste and `tools/lineups_from_paste.py` writes the feed. Both are network-free, asserted on the import graph rather than on a substring search, because the docstrings name mlb.com. Downstream is untouched: `build_status_map_from_lineups_feed` reads the result as an ordinary feed, and every side carries `source: operator_paste`.
- **The trap that made this more than a regex, and the reason it is tested against the real paste.** mlb.com emits BOTH `<TEAM> Lineup` headers before EITHER lineup block. The pre-existing `parse_confirmed_lineups_text` tracks "the last header seen", which against this layout puts all eighteen hitters on the home team: the Astros' nine silently become Angels. That is a wrong answer with no error, the build stacks the wrong side, and every gate passes. Blocks are therefore split on the batting-order number resetting to 1, the Nth block belongs to the Nth header, and any other shape attaches NO lineup to either side rather than risk the wrong one.
- **The matching problem, and the measured answer.** mlb.com abbreviates first names, so `J Peña` never equals `Jeremy Pena` under the exact normalized match the existing reconciler uses -- it would fail on every hitter in a real paste. Matching is on `(first initial, surname, team)`, verified unique against that team's salary hitters, and the resolved DK CANONICAL name is what lands in the feed, which is why nothing downstream changed. On Ben's 2026-07-29 paste: 60 of 60 names resolved, including a Dodgers roster carrying both Teoscar and Kike Hernandez, which the initial separates.
- **An ambiguity appeared on the first real paste, which is the argument for refusing rather than guessing.** SEA's `W Wilson` matches both `Will Wilson` and `Weston Wilson`. The tool exits 2, writes NO feed, and names both candidates WITH their DK Status -- Will Wilson is IL, which is the fact that decides it. It is deliberately not auto-resolved: an IL row is strong evidence, not identity. `--resolve "W Wilson=Weston Wilson"` states the answer. A blocker writing a partial feed is the failure this refuses: it would arrive downstream indistinguishable from a lineup mlb.com posted short.
- **Distinctions the report keeps apart, because collapsing them is how a pool thins invisibly.** A side short because a NAME would not resolve is a blocker and says so; a side short because mlb.com posted eight is `partial`, which the status builder already reads as projected. A resolved starter with no row in the DK salary file is reported and is NOT fatal, because the CSV is authoritative for eligibility and a player DK did not list is unrosterable whatever the paste says. A paste/salary team disagreement is reported and never repaired, per the authority rule.
- **Lock times come from the salary file, not the paste.** The paste carries a bare `9:38 PM` with no date and no stated zone; Game Info carries a full dated Eastern start. The paste's clock becomes a cheap wrong-slate detector instead: a disagreement is reported as exactly that.
- **The consequence that removes standing friction:** a fully pasted slate has no TBD team, so the platoon reference is never read and the 7-day staleness blocker (build contract item 2) has nothing to gate. Verified by building the pool at `stale_platoon_policy='block'` with zero blockers and `platoon_source` None. One conversion call, then build, zero lineup fetches.
- **Not built, deliberately.** I had planned an MLBAM-id crosswalk and dropped it: DK Player_IDs are draftgroup-specific, so caching MLBAM to DK_ID would be wrong across slates. What is stable is MLBAM id to DK canonical NAME, and since the initial-plus-surname key resolved 60 of 60 with one honest ambiguity, a cross-session cache is speculative against a problem that has not occurred. The MLBAM ids ARE captured in the feed (they are the Savant join key). If ambiguity recurs often enough to be a nuisance, the crosswalk is the fix and `data/reference/` is ARCHIVE's path to write it in.
- **26 tests, in a new gated suite** (`tests.test_paste_lineups`, added to `AUDITED_SUITES`), every one running against Ben's actual paste and that slate's real DKSalaries.csv. Pin 510 -> 536; modules 24 -> 25.

### R33. The paste's team code was used verbatim, so seven clubs would have dropped a game (P0, XS) | new 2026-07-30

- **What:** R32 took the `<TEAM> Lineup` header as the DK abbreviation with no normalization, while `DK_ABBREV_REMAP` exists because the two vocabularies disagree on seven clubs (AZ/ARI, WSN/WSH, TBR/TB, CHW/CWS, KCR/KC, SDP/SD, SFG/SF). A paste rendering any of those produced a `game_id` matching nothing in the salary file, the game was SKIPPED with a warning, and a Classic build proceeded one game short. Ben's first paste contained none of the seven, which is exactly why 26 tests passed. Found by reviewing my own commit 90 minutes after shipping it.
- **LANDED 2026-07-30.** Header codes go through `to_dk_abbrev`, and the club nickname from the matchup link is a genuine second read: `MLB_TEAM_NAME_TO_DK` gained the 30 unique nicknames mlb.com actually renders (`Astros`, `White Sox`), so the two reads cross-check and the CLUB LINK WINS on disagreement, because a nickname is unambiguous while a three-letter code is the thing in question. A header that disagrees with its own link warns and is corrected. Three tests, covering all seven remapped codes. One existing test had to be corrected rather than the code: it mutated headers to simulate an off-slate game and left the club links saying Astros/Angels, which the new cross-check correctly caught as a self-contradictory paste.

### R32b. Paste intake, round 2: the placeholder is positional information (P0, S) | new 2026-07-31, from the 1910_6g BUILD fragment

Field feedback on R32/R33 from the first slate that ran them, so this is R32's family rather than a new topic. Three defects, one of which is the class R33 half-closed.

- **The P0, and the only one of the three that could have put a lineup on the wrong team in an uploaded file.** A game with only one posted side attached that lineup to the WRONG TEAM. mlb.com renders both headers, then `1. TBD` for the unposted side, then the posted side's nine. `1. TBD` matched no rule, so it was not a block, so the posted nine became `block[0]` and `_assign` gave it to `headers[0]`, the away team. On the 1910_6g slate both PIT@CIN and SF@SD hit it. It failed safe only because all nine CIN names missed the PIT roster and both sides ended `tbd` -- safe by luck of the crosswalk, not by design, and two same-division teams sharing a surname would have resolved onto the wrong side silently. R33 closed the team-code half of this cross-check; this was the block-alignment half.
- **LANDED 2026-07-31.** A TBD placeholder opens an EMPTY block and holds its position, so the block count matches the header count and positional assignment works as designed. Verified against the pre-fix parser on the same fixture: `E De La Cruz` and CIN's nine attached to PIT, `F Tatis Jr.` and SD's nine attached to SF. **The same shift existed one field over and was not in the fragment:** with SF's probable unannounced, mlb.com renders a bare `TBD`, that was ignored too, and the one named arm (`JP Sears`, SD's) slid into the away slot and became SF's probable. A bare `TBD` now appends a `None` that holds the pitcher slot. A wrong probable is worse than a missing one: it feeds the opposing side's platoon view a hand nobody threw.
- **And `_assign` stopped guessing at a count of one.** Blocks and pitchers attach at 0 or exactly 2, otherwise nothing attaches and it says so -- the rule the module docstring always claimed and the headers already had. Refusing is cheap now that DK backfills a probable. Without this, the next page-shape change reopens the same wrong-team path.
- **Pitchers silently dropped from a link-free paste (P1).** Line 263 read `if ids and not blocks:`, so the pitcher path required the MLBAM id that only a markdown link carries, while `_HITTER` resolves fine without one. Ben's real plain-text paste resolved 36 hitters across four teams and ZERO pitchers, producing five hard pool blockers (ATL/MIA/NYM/WSH/SF: no probable or declared starter). A pasted line is now held and promoted by the `RHP`/`LHP` line after it; the venue is whatever bare line was displaced without being promoted. The same fixture now resolves 75 names where it resolved 63, which is every hitter plus all twelve probables.
- **DK's `Starting` column is a first-class probable source.** DK declared Robbie Ray for SF while mlb.com and the StatsAPI both still showed TBD, so the CSV was ahead of both feeds and CLAUDE.md already makes it authoritative. It fills a side the paste left unnamed; the paste wins where both name someone and the disagreement is reported, because CLAUDE.md's authority covers identity, salary, team and eligibility, not who is on the mound. The DK-derived probable states no handedness rather than inventing one.
- **The `NOT IN DK POOL` contradiction, decided (P2).** The tool wrote a feed despite 18 of them, against CLAUDE.md build-contract item 1 and SKILL.md, which both said an unresolvable name blocks and no feed is written. The implementation deliberately treated resolved-but-absent-from-DK as reported-not-fatal, because DK owns eligibility. Both positions are defensible per name and neither survives 18, which is one wrong-slate signal rather than 18 independent facts. **Decision, per Ben's recommendation: a threshold, not a per-name rule.** Per name it stays non-fatal so a genuine call-up ships; it blocks past half of one posted side (`SIDE_ABSENT_BLOCK_RATIO`) or a quarter of the paste with at least six (`SLATE_ABSENT_BLOCK_RATIO`, `SLATE_ABSENT_BLOCK_FLOOR`). Code, CLAUDE.md and SKILL.md now agree, and the thresholds are in the report rather than only in the source. Worth recording: the 18 were CAUSED by the P0 above, since nine CIN names against a PIT roster is nine absences twice over, so the threshold is a second, independent detector of the same misfiling.
- **27 tests, 29 -> 56 in `tests.test_paste_lineups`. Pin 556 -> 583.** Two new fixtures. `mlb_com_2026-07-30_1910_6g_plaintext.txt` is Ben's real link-free 6-game paste, verbatim. `mlb_com_2026-07-30_home_side_only.txt` is labelled RECONSTRUCTED in its own header and says exactly why: the content is verbatim from that slate's artifacts, but the interleaving is restored from `paste_home_sides.txt`, which was hand-reordered during the build so the posted club led. The existing fixture is a three-game paste where every side posted, which is precisely why 29 tests passed over a wrong-team bug.

### R34. "upload_ready" was stamped onto review-grade Showdown files, and it already happened (P0, S) | new 2026-07-30, from the 07-29 red-team critique (its Finding 4)

- **What, verified on disk, not theorised:** `outputs/2026-07-29/upload_manifest.json` currently holds two Showdown records at `status: upload_ready` beside `certification: review_grade`, and a third at `status: delivered`, which is not in `STATUS_VALUES` at all. Three separate failures compounded. `preflight_upload.py` never read the `certification` field (zero occurrences), so a mechanically clean review-grade file passed every byte check and got handed the one label CLAUDE.md reserves for a run where all three certification gates passed. `STATUS_VALUES` was documentation only, referenced by its own definition and two tests but never validated against, so `record_delivery` accepted `delivered`, and `current_deliveries` filters only on `!= "superseded"` — an unknown status therefore reads as CURRENT in the artifact that answers "which file do I upload".
- **Why P0:** it is the truthful-labels rule broken in the one file whose entire purpose is to be trusted at upload time, and it had already produced two wrong labels on live Showdown deliveries.
- **LANDED 2026-07-30.** Preflight reads the recorded certification and returns a new `review_ready` verdict at exit 0 when it is anything other than `certified`: the file is still a usable artifact, it just is not upload-ready, and the note says why. An unknown recorded status is now a hard failure. `record_delivery` validates against `STATUS_VALUES` and raises, which fails closed because both callers already wrap it in a try/except that degrades to "MANIFEST NOT RECORDED" and default preflight hard-fails an unrecorded delivery. The Showdown path now records `candidate`, which is the honest status for a file that has not been through the gates. `STATUS_VALUES` is mirrored into preflight (which imports nothing from the engine by contract, the same reason `parse_game_info_datetime` is mirrored) and the two are pinned in sync by a test. Seven tests.
- **Not fixed, and it is a data question for Ben:** the three wrong records still sit in the 07-29 manifest. Rewriting history in a provenance file is not something a DEV session should do unasked. The code can no longer produce them.

### R35. A corrupt manifest passed where a missing one failed (P0, XS) | new 2026-07-30, from the critique (its Finding 5)

- **What:** an ABSENT manifest for a delivered file was `rep.fail`; an UNREADABLE one was `rep.warn` and returned. The weaker evidence state passed, which is a provenance gate exactly backwards. Corruption is also the one state in which the next `record_delivery` silently overwrites the history, because `read_manifest` converts unparseable JSON into an empty manifest.
- **LANDED 2026-07-30.** An unreadable manifest blocks for a delivered file (a file under `outputs/`) and still only warns for an ad-hoc check of a scratch file, which is not a provenance claim. Two tests. **Open, and deliberately separate:** `read_manifest` still returns an empty manifest on corrupt JSON, so the overwrite path is intact. Quarantining the bytes before rewriting is the fix and it belongs with the append-only rework in R36 rather than being bolted on here.

## The v2 Amendments section (session-by-session landing record)

# Amendments

- 2026-07-29 evening, false-PASS cluster session (DEV, engine claim `engine_2026-07-30`). Filed R29 and R30; landed R29(1) through R29(6) as five commits, one per logical fix, explicit paths only. Audit pin 437 to 498. The scope Ben set held: every item was a defect that made a gate lie or shipped a wrong file, and none changed construction. R25's minimal-repair fast path was explicitly out of scope and is untouched. **The one that would have caught the DK rejection on its own is R29(1), and only R29(1)**: the seven rejected entries were mechanically detectable by logic already present in `verify_export.py`, which was handed a list that had gone stale during a 39-minute chain. The other five each cost time or told a lie; none of them was between that file and DraftKings.
  - **Merged and deleted four fragments**, two from ARCHIVE and two from tonight's BUILDs. Tonight's late-swap defects went into R25's family as its second round with pointers to R29(1)-(4) rather than opening a separate late-swap topic, per Ben's instruction. The fragment's bug 3 (merged stdout+stderr swallowing the real error) landed as an operating note in SKILL.md, not as engine work, also per Ben's call. ARCHIVE's two fragments updated R10 and R13 in place and produced R30; the `--paid-places` flag, the satellite `ticket_count` rows, and R10's prior all stayed unbuilt as instructed.
  - **Two things I did not do, and why.** No `--entries-source` on `late_swap.py`: Ben scoped it "if it falls out cleanly" and it does not, because every entries read on that path already comes from `--parent-entries`, so a second entries path would only let the reserved grid disagree with the file being refined with no gate checking it. And the `mlb-game-odds` skill's own key resolution is unfixed: its script sits on a read-only filesystem and `save_skill` replaces only `SKILL.md` while keeping other files, so it cannot be changed from a Cowork session at all. The repo side no longer depends on it either way.
  - **A fresh-context adversarial review of the six commits found seven real defects, all fixed in a seventh commit before the session closed.** Two were serious and both were the cluster's own failure class arriving through its fix. First, R29(1) made the lineups feed the PREFERRED lock source and a feed is not guaranteed to cover the slate: a single-game Showdown feed at the shared date-keyed name, or one for the wrong date, parsed cleanly and reported an EMPTY locked set at a clock where two games had started. That is the 07-29 false PASS reachable through the fix for it. The salary file is now the coverage floor and the two are UNIONED; the only thing the feed may REMOVE is a game it affirmatively reports postponed, cancelled or suspended, which is the one fact Game Info cannot carry. A feed covering fewer games than the salary file warns and does not shrink the set. Second, two of the mini-MAX tests hard-pinned ARCHIVE's uncommitted CSV row, so a clean checkout would have failed the suite, and CLAUDE.md makes a failing suite a live-slate block; they now skip when the row is absent and assert when it is present, which is the honest shape for a test whose data another session owns. Also fixed: `normalize_odds_payload` could raise AttributeError/TypeError where the Classic caller catches only ValueError (a traceback out of a live build, now shape-specific errors); the swap inherited the build's posture merge but NOT its `_slate_feasibility` floors, so on a thin slate it was still tighter than the build it refines (the floors extraction is now one shared `feasibility_floors_from` that both callers use); the deferred-promotion refusal left `passed` and `workflow_valid` True where the inline path sets both False; verify_export's "lock state is underivable" warning was unreachable and the no-Game-Info case printed "every game has started" against an empty set; and two assertions were brittle (a forward-slash path check vacuous on Windows, a source pin on a reworded string). Twelve more tests, 498 -> 510.
  - **Two review findings recorded rather than fixed, because they are correct as they stand.** A `cash`-only swap now enforces no portfolio controls at all, and a `single_entry` swap keeps `max_sp_pair_repetition: 1`. Both match the build exactly, which is the entire point of R29(3); the docstring that called the old default "stricter than every posture" was overclaiming and is corrected, and the tests now cover both counterexamples explicitly instead of looping past them.
  - **Item (6) came back clean.** The mini-MAX row's `payout_shape_default` of `mme_top_heavy` is a payout token, not a contest shape, and `normalize_posture` has handled it since before the row existed; it resolves to `mme` then `mme_gpp` with a real profile, exactly as the `150-Max` and `MME` rows do. Nothing was mis-routed on the contests Ben entered. The R1(a) family is now pinned by a test that walks the live CSV, including a pin on which payout tokens collide with shape names, so the ambiguity is held still rather than asserted away.
  - **Two session-start facts worth the record.** The beacon `slate_2026-07-29_sealad_sd` read HELD and STALE and is neither: its owner wrote the `RELEASED` marker at 00:24:01Z, four minutes after taking it, but `claim.py`'s `_is_held` prefers `owner.json`'s null `released_utc` over the marker, and `_is_stale` compares the claim name's date against the UTC date, which after 8 PM ET is already tomorrow. So every evening slate flags its own same-night claims stale, and a released claim can read held. Filed as R31 below; nothing was released or deleted, because the marker is what CLAUDE.md defines release AS and the claim was not mine. Second, `.git/index.lock` was 154 minutes old and zero bytes, mtime `22:16:26Z` matching the `ledger_2026-07-29` claim's own release to the second, so ARCHIVE's mini-MAX commit died mid-write. That is why `dk_contest_archetypes.csv` and `contest_library.json` are still uncommitted: not a BUILD session writing an ARCHIVE path, but ARCHIVE's own claimed write that never landed. Dead lock removed per git's own remedy (delete grant required); the two files left untouched for their owner.

- 2026-07-29, R26/R27/R19 session (DEV, engine claim re-taken after the beacon session's release). R26 landed as the two-signal postponement exclusion recorded on its entry, closing the P0; R27's open half landed as `gate_failure_detail` plus the not-certified print, closing R27; R19's done-when closed by pointing SKILL.md and the runbook at `tools/claim.py`, with a doc-pin test so neither can drift back to the raw mkdir. One commit, six tests, audit pin 404 to 410; CLAUDE.md and SKILL.md quoted lines updated in the same commit; the pending ARCHIVE fragment updated in place to 410 rather than filing a second instruction that could be applied out of order (precedent: 07-28's 385-to-400). Two operational notes. First, the session-start suite failed with the same eight-teardown-error signature the 07-28 amendment recorded, because the Cowork mount ships without a delete grant, so `test_upload_integrity` cannot unlink the `outputs/_test_r3` fixtures it itself writes; cleared with the delete grant, and the fixed-path fixture stays R6/R8's to retire. Second, the full `--run-tests` audit still exceeds one sandbox bash call, so the static checks and the four suites ran as separate calls per the 07-27 note; backgrounding the audit does not survive the call boundary either, which is worth knowing before waiting on one.

- 2026-07-29, beacon-and-late-swap session. Ben's two calls, both landed. First: builds never block builds (R24, contract v1.1); the slate claim is a beacon, engine/ledger/inbox stay mutexes, unassigned sessions may always build, and the surviving structural ban is bank-splitting by Entry ID ranges, not same-slate parallelism. Second: the late-swap timeout chain (R25), fixed in its bounded parts (`--lineups`, total `--budget`, `--solver-budget`, swap-side platoon `warn`, a pre-solve progress line) with the minimal-repair fast path filed as the decision half. The fragment protocol completed its first full cycle: three BUILD sessions filed field reports overnight, DEV merged them today as R25, R26, and R27 and deleted the consumed fragments; ARCHIVE had separately mined, merged the Quick Card fragment, and released its claims, all visible in claims/. R26 (postponed-game leakage, Chris Sale as P1 from a rained-out game) is filed P0 and is the next DEV item. R27's half-fix makes build_slate.py's `warn` match CLAUDE.md's stated contract. Audit pin 400 to 404; the Quick Card copy routed to ARCHIVE as a fresh fragment.

- 2026-07-28, multi-session contract session. Analyzed three uncoordinated Cowork instances sharing this folder; filed R18 through R23 and landed R18, text and structure only, one commit, explicit paths. Evidence the failure class is live rather than hypothetical: the 07-23 staging clobber, the 07-25 concurrent-critique reconciliation below, `runs/latest_valid_run.json` still carrying a dead session mount path, and one incident inside this very session: the session-start audit printed `FAIL test suite FAILED (ran 372)` because the interrupted 07-27 run had leaked `outputs/_test_r3/` fixtures that a later session cannot unlink through the Cowork mount without an explicit delete grant, so `test_upload_integrity`'s teardown errored eight times and the no-manifest test read the leaked manifest and asserted 0 != 2. Cleared with Ben's delete grant; the audit printed `PASS v2.26.0 23 modules 372 tests` before any edit and again after all of them. Found in passing, filed not fixed: `SKILL.md` (Showdown section, near line 415) still claims the audit runs `tests.test_core` only, the same stale sentence R8 deleted from CLAUDE.md, and `outputs/_test_r3` is a fixed shared path any two concurrent audits collide on; both ride R6/R8's doc-and-test discipline. `ledger/MLB_Classic_Calibration_Ledger.md` and `data/standings/CONTESTS_AWAITING_STANDINGS.md` were already modified before this session and were left untouched as foreign dirt. A second incident surfaced at the Phase 0 commit: a 74-minute-old zero-byte `.git/index.lock` whose mtime matches the ledger and CONTESTS modifications exactly, meaning whatever ran at 10:36 died mid-commit and its work sits uncommitted; the dead lock was removed per git's own remedy, the uncommitted edits were left for their owner. Phase 1 landed the same day, second commit: R19, R20(a), and R21 as recorded on their entries, thirteen tests, audit pin 372 to 385, CLAUDE.md and SKILL.md quoted lines updated, and the ledger Quick Card's copy of the audit line routed to ARCHIVE as `ledger/inbox/2026-07-28_dev_audit-pin-385.md`, the fragment protocol's first live use. Phase 2 landed the same day, third commit: R20(b) the inputs-unmoved gate at promotion, R20(c) the pointer compare-and-swap plus the late-swap parent-lineage block, R22 bank-cache merge-on-save, R23 the miner-owned inbox move with ledger blocks as fragments. Fifteen more tests; audit pin 385 to 400, with CLAUDE.md, SKILL.md, and the pending ARCHIVE fragment updated in place. The multi-session board R18 through R23 is now fully landed; what remains from the original analysis is process, not code: pointing SKILL.md and the runbook at `tools/claim.py` instead of the raw mkdir procedure (R19's done-when), draining the 122 mined-but-present inbox CSVs (ARCHIVE), and the DEV-worktree recommendation for engine work concurrent with live slates.

- 2026-07-27, construction-surface session. Six commits, one item each, audit PASS before the first and after each: `9a6196b` R2's skill half, `409900a` R5, `ca80b0f` R15, `4572afb` R16 (the gpp contradiction, new this session), `54b36ff` R1c, `32b6259` the self-review fixes. Audit moved from `PASS v2.26.0 23 modules 360 tests` to `PASS v2.26.0 23 modules 372 tests`. **All three decisions went to Ben with a recommendation and he took all three.** R5: adopt section 8 on `wta_satellite`, no posture split. R15: delete the dead stage and the false claim, keep the primitive. R16: delete the gpp weights.
  - **Claims in this document that the tree contradicted, corrected rather than forced through:** R5's draft named `contest_allocator.plan_and_assign_entries`, which does not exist (it is `select_and_assign_portfolio`), and missed that its caps block excludes satellite and cash outright, which turned the item from a reconciliation into a strategy choice and changed the recommendation away from the draft's preferred option. R15's fix said to strike DU from MLB_Classic section 8; that file has no DU references and the instruction was already vacuous. The prior note on the gpp contradiction said five profiles; it is six, and the range is 0.80/0.20 to 0.70/0.30, not 0.78/0.22 to 0.70/0.30.
  - **Defects found that no item named:** `--force`'s argparse help still promised exit 0, at the surface CLAUDE.md delegates flag documentation to; `du_validation` reported `pass: True` on every production build for a control that never ran; `solver_probe` enforced DU while the build did not, so the mandated pre-build probe measured a harder solve than the one it estimates; and R15's own delete orphaned `_candidate_selection_score` and left four result keys describing a handoff to the deleted stage. All fixed with tests. R17 filed, not fixed.
  - **Two claims I wrote in this session were overstated and are corrected above:** the DU primitive is not covered by 11 tests, it has no direct coverage at all, which cuts against keeping it; and R1c landed three tests, not four.
  - **New for the board:** R17 (the ` SE` strip in `contest_library`, plus that module having no production caller, a third zero-caller surface). Also worth knowing operationally: the full audit with tests now takes about 45 seconds in one process, which exceeds a Cowork bash call's ceiling, so a Cowork session may have to run the four suites and the static checks as separate calls even though the command works normally on Ben's machine.
  - **Golden baseline never moved this session, and three of the four construction items could not move it.** R5 is overridden by the replay's `LOOSE_CONTROLS`; R16 was a zero-diff delete; R1c leaves `ticket_count` blank. The one that would have, extending the blend to `gpp`, was measured before the decision rather than after: 3 of 18 entries changed candidate, all four GPP entries sit in one contest, the same four candidates were selected before and after, exposure and SP-pair distribution byte-identical, all three certification gates unchanged. The re-freeze the session rules anticipated did not come due, and R6(b)'s production-controls replay is the gate that will actually see these changes.
- 2026-07-27, concurrent-session reconciliation. A second session ran against this repo at the same time as the implementation session below and produced `docs/2026-07-25_independent_critique.md`. Checked and no action needed: that file was already committed at `d9a428e` before the implementation session started, it appears in none of that session's six commits, and `outputs/` and `runs/` are gitignored with nothing tracked under either, so its audit run left no trace in git. The `FAIL test suite FAILED (ran 344)` it observed was a read of the implementation session's uncommitted R2+R3+R4 edits, not a fact about the engine; the same tree prints `PASS v2.26.0 23 modules 360 tests` committed. That critique reviewed the tree at `e58b3ac`, 24 commits stale, and its own accounting says essentially all of its P0 and P1 list was already closed. **One additive finding survived and is now R15**, verified independently against HEAD and sharper than reported: DU is enforced nowhere on the production path. It also forced a correction to a comment in `contest_shapes.py`. This is the fourth critique against a list that had already disposed of two; the do-not-build line about per-slate codebase reviews holds, and this document remains the live answer.
- 2026-07-27, implementation session. Landed in execution order, one item per commit, audit PASS before the first and after each: `48ba15a` R1a, `9f2a4ca` R1b+R1d, `b83e553` R2+R3+R4, `283bba7` R9a+R8. Audit moved from `PASS v2.26.0 22 modules 329 tests` to `PASS v2.26.0 23 modules 360 tests`. **R5 was not started, per instruction; the draft ledger entry sits under R5 above with a recommendation and its counterargument.** Corrections to this document made from the tree rather than forced through: R3's `enrichment.signal_applied` does not exist (tier derived from `requested`/`applied_count` instead), and R8's "candidate-cap 24 vs 150" contradiction does not exist. Three defects found that no item named, all fixed with tests: `_posture_to_shape("mme")` returned a non-profile key and raised on every 150-Max contest on the direct path; `PAYOUT_BREADTH_BY_SHAPE` had no row for any canonical shape name; and the ` SE` row of `dk_contest_archetypes.csv` carried unquoted commas that put `" POSE"` in `payout_breadth`. **New work this session generated, for the board:** R1b's blend is provably inert under proxy projections, so R6(b)'s enriched golden replay is what will exercise it; the `gpp` family advertises 0.72/0.28 and takes pure ceiling, the same defect R1b fixed one family over, and correcting it reranks every GPP contest so it needs its own decision; R2's skill half (branch on exit 4, name the overridden failures) is unlanded; and reaching R9a's 110-line target needs the approve-gate, platoon-staleness and late-swap-authorization contracts moved into SKILL.md first, which pairs naturally with R2's skill half.
- 2026-07-27, second pass: measured CLAUDE.md section by section against the context-engineering guidance at Ben's request. R9 split into R9a (immediate text-only CLAUDE.md slim, 232 to ~100 lines, with two sequencing holds) and R9b (corpus split, ENGINE_STATE, tier doctrine, unchanged schedule). The CLAUDE.md:230-231 audit contradiction (stale "test_core only" sentence vs the shipped four-suite gate at line 42) added to R8. Execution order renumbered.
