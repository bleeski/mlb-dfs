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

## 2026-08-17 — R143 + R144: the salary file is the first source for batting order, and session start reads what changed

DEV, claim `engine_2026-08-17`, plus a `ledger` claim for the pin line only.
Two asks from Ben the same day.

### R143 — DKSalaries first, a paste second, an API pull third, per side

Ben's instruction: "the first source of truth for starting lineups / batting
orders should be the DraftKings salary CSV, second anything I paste, third an
API call. If all lineups are posted in the CSV we don't need my paste, and if
the paste handles everything don't spend time or tokens on an API call."

**The fact that made this worth doing.** DK publishes the batting order in the
salary file. The `Starting` column carries 1-9 per posted side, beside the
Player_ID this repo already calls authoritative. Classic read that column only
as a CROSSWALK CHECK (`live_data_adapters` blocker: DK marks nine, pool holds
under five) and sourced its hitters from the feed. Measured on
`data/slates/2026-08-16/DKSalaries.csv`: **15 of 16 sides carried a complete
1-9** in the authoritative file while the build went to a paste or a 25-second
API call for the same fact. Only Showdown had ever read it as a source.

**What landed.** `merge_dk_starting_into_feed` runs inside `build_slate_pool`,
before the status map, so no caller can bypass the ranking — the front door is
the only place a precedence rule holds. It only ever ADDS or UPGRADES a
confirmed side; a side DK has not posted still comes from whatever the caller
supplied, which is what makes the ranking per SIDE rather than per slate. Games
absent from the feed entirely are synthesized from `Game Info`, which is what
lets a fully posted slate build with an empty feed. `match_dk_id` now
short-circuits on a supplied DK id, so a DK-sourced side cannot fail the name
crosswalk at all. `dk_order_coverage` is the single definition of "covered",
shared by the pool and by `build_slate.py`, which skips the fetch outright when
it reports every side covered.

**Measured, salary file only, empty feed:** 15 confirmed sides, 8 games
synthesized, 144 hitters and 14 pitchers kept, `sides_left_to_feed: ['DET']`
(DK had not posted Detroit), remaining blockers all legitimate — PIT's PLR arm
awaiting Ben's explicit call, and DET with no probable.

**Three limits, chosen rather than discovered.** Only a COMPLETE 1-9 counts; a
partial DK side is a projection and falls through untouched, same reasoning as
R60. DK ships no handedness, so the merge keeps `bat_side` from a feed that has
it and names the sides where none does in `f4_handedness_unavailable`, because
a silently zeroed F4 is a failure this repo has already paid for. And DK's
probables are SP/P only: R104 settled that a PO opener is not a declared
starter, and CLAUDE.md makes a PLR an explicit call, so neither is promoted by
a merge acting on a team's behalf.

**Where DK and a paste disagree on the same posted side,** DK wins per Ben's
ranking and the difference is NAMED in `dk_batting_order.disagreements`. It is
not silently resolved: the CSV is a point-in-time download and a paste carries
no timestamp, so neither can be proven fresher, and the operator gets the fact
instead of a guess. R32's "the paste is the primary source" is narrowed to
"outranks any API pull," which is what it always meant against the API.

### R144 — session start reads the newest CHANGELOG headings

Ben asked every session to review the changelog at start so nothing acts on
stale information. Adopted, bounded. The file is 5,864 lines and roughly
119,000 tokens; reading it whole would spend most of a context window before
any work and would be dropped under deadline within a week. Session start now
reads the newest fifteen HEADINGS (~400 tokens) and reads a full entry only
before touching an area a heading names.

Pushed back on one half of the ask and said so in CLAUDE.md: "nothing gets
overwritten" is step 1 plus the claims mutex, not a changelog job. The
changelog step is about STALENESS, which is the half it does serve — a session
that sees R142's heading knows not to paste a full skill copy back in.

Tests: nine in `tests.test_core.DkBattingOrderPrecedenceTests`; `test_core`
667 -> 676, total 1025 -> 1034. All five gated suites re-run green
(676 / 56 / 218 / 9 / 75).

## 2026-08-17 — R142: the installed skill stops being a copy, and the audit says when a snapshot has fallen behind

DEV, claim `engine_2026-08-17`, plus a `ledger` claim for the pin line only.
Ben: if we update the skill in the future, how do we make sure you have the
latest version.

**The failure.** Cowork installs a skill by COPYING its SKILL.md. The copy
never re-reads the repo and nothing warns when they diverge. Measured
2026-08-16: the installed `generate-lineups` was the 2026-07-24 snapshot, 85
commits and 351 lines behind, missing the autobuild path, projection
enrichment, R32 paste intake, the preflight-before-presenting section and the
Showdown thesis ladder outright, with a trigger description that still called
Showdown certified. A session following it would have shipped a Showdown file
labeled upload-ready. Nothing in the repo could see this, because the repo copy
was fine.

**Fix one: the installed body is now a pointer.** `generate-lineups` and
`mlb-standings-pull-checklist` were re-saved as ~50-line files that name the
repo path, say to read `CLAUDE.md` and the repo SKILL.md in full, and carry
only the handful of walls that must hold even if the repo is unreachable (never
automate DK, truthful labels, never reduce the pool, run the preflight; for the
checklist, never fetch DK, take the inbox claim, the inbox is flat). Drift
becomes structurally impossible: there is no second copy to go stale. The full
copy bought nothing, because every command in it is `<repo>/tools/...` and its
first instruction is to read CLAUDE.md, so it was never usable without the
mount anyway.

**Fix two: `skill_cache_drift` in `tools/audit.py`.** The pointer cannot carry
the TRIGGER DESCRIPTION, which lives in the save_skill argument, decides
whether a prompt reaches the skill at all, and is invisible to a session
reading only the repo. So the audit compares it at session start. Modeled on
`changelog_debt`: WARNING only, never an error, and it degrades to silence
rather than to a false clean. A cached body carrying the `skill-cache: pointer`
sentinel is not compared, because a difference that is by design would make the
check permanently yellow and a permanently yellow gate is one nobody reads.
Cowork's JSON re-quoting of the description is normalized for the same reason.

**What the check found on its first live run.** `mlb-standings-pull-checklist`
was drifted on both body and description, and the description drift had a root
cause worth its own guard: the repo's was 1073 characters against Cowork's
1024-character install limit, so it could never be installed as written and had
been shortened by hand at install. That is drift created at birth that never
converges. The repo description is rewritten to 993 and the audit now warns
when any repo skill exceeds the limit. That half reads only the repo, so unlike
the cache comparison it still reports from Ben's own PowerShell.

**The honest limit.** The cache is a sibling of the repo inside a Cowork
sandbox and reachable there. From Ben's PowerShell it sits under an AppData
path keyed by session GUIDs and is not derivable from the repo, so
`skill_cache_dir` returns None and the comparison stays quiet. It fires where
the drift matters, which is where the skill loads.

Tests: ten in `tests.test_core.SkillCacheDriftTests`; `test_core` 657 -> 667,
total 1015 -> 1025. `MLB_SKILL_CACHE_DIR` overrides the cache path for tests.
Pin line updated in CLAUDE.md, the ledger Quick Card, and
`skills/generate-lineups/SKILL.md`.

## 2026-08-16 — SKILL.md's audit pin corrected (928 → 1015) and its pin instruction pointed at the per-suite dict (docs only)

DEV, claim `engine_2026-08-17`, docs only, no code. Ben: review the
generate-lineups skill and confirm the installed copy is current.

**Two stale facts in `skills/generate-lineups/SKILL.md`, Session hygiene.** The
expected audit line read `PASS, 26 modules, 928 tests`. `EXPECTED_SUITE_COUNTS`
in `tools/audit.py` sums to 1015 (657 / 56 / 218 / 9 / 75), so the skill was
five moves stale: R114+R67 (928 → 942), the false-signal batch (→ 962), R116
(→ 975), R129+R36 F6m(1) (→ 1000), R128 (→ 1015). CLAUDE.md and the ledger
Quick Card both already carried 1015, so the skill was the one doc of the three
its own paragraph names that had not been updated. Corrected to
`PASS v2.26.0, 26 modules, 1015 tests`.

The same paragraph told a session to bump `EXPECTED_TEST_COUNT`, which R62
demoted to a derived sum on 2026-08-10; bumping it does nothing, since the
audit reads the per-suite dict. Rewritten to name `EXPECTED_SUITE_COUNTS` as
the source of truth and to carry the state-word rule already in CLAUDE.md and
the Quick Card: only `grew` is a stale pin, and `shortfall`,
`skipped_in_place` and `absent` are lost coverage. A session reading this file
alone under deadline could have lowered a pin to clear a shortfall, which is
how the golden replay's nine tests leave the gate for good.

**Not fixed here, and it is not a repo defect.** The Cowork-installed copy of
this skill is a snapshot taken 2026-07-24 and is 85 commits behind the repo:
351 lines shorter, missing the multi-session check, the scipy preflight, the
autobuild fast path, the qa_portfolio pass, projection enrichment, R32 paste
intake, the preflight-before-presenting section with its four exit codes, and
the Showdown thesis ladder, and its frontmatter still calls Showdown
certified. Its bundled `scripts/build_slate.py` is 522 lines against the
repo's 2822. Nothing in the repo invokes that copy (SKILL.md calls
`<repo>/skills/generate-lineups/scripts/build_slate.py` by absolute path), so
the stale script is inert as long as a session follows the current text. The
snapshot was refreshed from this file the same session, outside the repo.

## 2026-08-16 — Fragment-merge and queue re-order: R135–R141 filed from the leverage ideation bundle, R11's double listing resolved, R132 split on the autonomy boundary

DEV, claim `engine_2026-08-16`, docs only, no code. Ben: review the fragment
inbox, slot what survives, then re-order the queue on impact, difficulty and
critical path.

**The bundle.** The one unmerged fragment
(`docs/backlog_inbox/2026-08-16_unassigned_leverage-and-contrarian-ideation.md`)
enters as seven numbered items and three riders, every cited measurement
re-verified against the ledger and the tree first, per the R36 discipline:
`ownership_prior.py` v0.1 exists untracked and unwired with
`grade_against_actuals` at `:219` and a header that says "start the
predict-then-grade loop on slate one"; 3.17's 104/116 sub-10% carry, 51%-vs-13%
winner rate, chalk splits (+4.9/+9.5/+8.6/+1.1/−13.2) and $250/$200/$100
salary-leave medians; 3.18's 9.1-vs-15.4 captain tranche with the 64-contest
at-share caveat carried onto the entry; 3.19's 15,402 users, 2,211 regulars,
132/148 winners-were-regulars. Filed: **R135** (ownership shadow loop, Tier 2
beside R118 — every slate without a prediction file is a slate that can never
grade anything), **R136** (qa_portfolio leverage panel, Tier 1's QA batch
directly behind R126, same report block), **R137** (market-vs-crowd divergence
screen, Tier 5, with MLB_Classic.md 14's quota arithmetic priced on the
entry), **R138** (one-stack-family-per-game SKILL.md practice, XS, rides
R131's session), **R139** (Showdown captain-leverage ladder — report rides
R136, control waits on D3), **R140** (opponent-conditioned field profiles for
recurring satellite families, Tier 2 tail, behind R118+R48 whose outputs it
consumes), **R141** (late-swap leverage pass, Tier 5, behind R135). Riders,
not numbers: R10 gains its two control halves (leverage-carry inside the
primary stack; replay-calibrated duplication budget — both wait on the prior
beating flat-12, unchanged); R37(2)(b) gains the field-share-adaptive
generalization, gated on R48; Tier 4 gains **D1–D3** (salary-leave
act-or-record; supersatellite posture, the one measured anti-chalk cell;
captain ladder defaults). The fragment's frame is the board's own — broad
contrarianism stays rejected on 3.17 — and nothing jumps the Tier 2 spine.
The fragment is retained on disk until its items land, per the sweep rule.

**The re-order.** R134 landed after the queue's last note, so three entries
were corrected against it rather than left describing a tree that no longer
exists. **R126:** qa_portfolio now computes the frontier proxies at review
time, so the remainder is the pipeline/brief half plus the per-game zeroing
histogram — unchanged in kind, cheaper in practice. **R11:** moved to Tier
1's tail and its Tier 5/Tier 6 double listing collapsed to one entry; the
Tier 5 note's claim that its R114/R116/R117 gate had fully cleared was false
on R117, which is open — corrected on the entry (the R133 lesson: a note
asserting a state it did not check). The move stands on the chassis R134
built, the six items two hand-runs found, and Ben's R134 directive naming an
adversarial QA pass the standing follow-up to unattended builds. **R132:**
split on the 2026-08-16 autonomy contract — the small-slate-defaults S
variant and ladder rungs over engine-derived floors and guesses are
DEV-ready (the R37/R116 precedent); any rung raising an exposure cap is
R125(c)'s Tier 4 decision, which the supervisor's landing makes the
highest-leverage minutes on the board. One order swap inside Tier 1: **R117
ahead of R133** — selection impact over label truth, and R117's parse half is
R122's Showdown handedness input. Everything else holds its 2026-08-12
adjudicated position; the full reasoning is the queue note of this date.

Not merged, deliberately: the two 2026-08-13 ledger fragments and the
2026-08-15 audit-macro fragment are ARCHIVE's (their backlog asks were
already carried as R115/R116); the 08-09 curated-archetypes fragment stays
ARCHIVE's to execute. Gate this session, per-suite: 657 + 56 + 218 + 9 + 75
= 1015, zero skips; `audit.py --terse` PASS v2.26.0 26 modules; and
DeterminismTests fit a single call at 20.2s — the load-dependent ceiling the
08-15 ledger-inbox fragment describes, measured from the green side.

## 2026-08-16 — R134: a supervisor takes the retries a human was taking by hand

DEV, claim `engine_2026-08-16`. Ben, this date: "I want you to have the freedom
to use your intelligence to override, relax and constrain to generate lineups
without my intervention," then an adversarial QA pass over the result, no more
than two iterations, time permitting.

The 1335_8g build stopped twice for a human and neither stop needed one. The
first was a pool blocker: DET showed 8 rosterable hitters because DK never
priced a called-up starter, which is the `unrostered_starters` case CLAUDE.md
already calls non-fatal. The second was a feasibility floor the engine itself
labels ARITHMETIC, printing `remedy: raise max_shared_players to >= 7` next to
the sentence "raising the control to the named floor removes an impossibility
and changes nothing else." The engine had classified both. Nothing was missing
except something willing to act on the classification.

**`tools/autobuild.py`.** Policy, not mechanism; `build_slate.py` stays one
deterministic build that certifies or refuses with reasons. The supervisor reads
the reasons, decides, records why in `outputs/<date>/autobuild_decisions.json`,
and stops on anything it cannot classify. It grows the bank on exit 10, applies
a feasibility remedy only when the engine named it AND classified it structural,
and overrides a pool blocker only when its shape matches a benign pattern. It
will not touch an exposure cap (no engine-named floor, so raising one
concentrates the entered set and is a strategy change), will not reduce the
player pool, and will not override a blocker it cannot classify, a
name-crosswalk failure under 5 of 9 included. `assert_classification_in_sync`
reads `STRUCTURAL_FEASIBILITY_CHECKS` off `build_slate.py` at startup and
refuses to run on drift, because the whole policy rests on that split.

**`tools/build_asserted.py`.** `--assume-gates` only fills a gate that is
undetermined; `execution_pipeline` honours it where `gates.get(name) is None`,
so a gate that evaluated False keeps its evidence. Correct, and it left the
verified-benign case with no instrument. `run_slate` already had one:
caller-supplied `workflow_gates` override derived values and land in
`caller_asserted_gates`, so the artifact states that a human asserted the gate
rather than implying the check ran. This wrapper supplies them and changes
nothing else. Because `lineup_gate_passed` derives from the pool report, the
supervisor asserts it on the same evidence as the pool override, or not at all.

**`tools/qa_portfolio.py`.** Adversarial review of a delivered portfolio,
report and never a gate. Section 1 prints what the build actually applied from
the brief's own enrichment self-report; it exists because a session this date
claimed F1 was neutral, having inferred it from a `--odds` help string, and
rebuilt under deadline while the brief in hand read
`f1_league_mean_implied_total: 4.125`. Section 2 checks stacks against market
implied totals and arms and bats against Savant expected stats. Section 3
reports the dual-objective frontier as two deterministic review proxies:
washout exposure is the largest share of the entered set materially exposed to
one axis, apex concentration is the heaviest primary stack, and they move
together by construction, so a build picks a point on that frontier rather than
maximizing both. Counting any game a lineup merely touched read 100% on an
8-game slate, which is arithmetic, not a finding; material exposure is 3+
players.

**`build_slate.py`: a replay is not a delivery.** `--past-slate-replay` wrote
the live delivered filename, so re-running a locked slate to exercise the build
overwrote a certified export already handed to a human. Found by testing the
supervisor against 1335_8g, which clobbered that afternoon's delivery; the
`runs/` copy survived and the delivery path did not. Replays now carry a
`_replay` suffix and cannot land on the delivery path.

Suites: golden_replay 9, upload_integrity 218, showdown 56, paste_lineups 75,
and 653 of test_core's 657 all pass. `DeterminismTests` exceeds a single sandbox
call, which the ledger Quick Card already documents; unverified here, not
suspected.

## 2026-08-16 — R128: duplicate-lineup reporting gets contest context

DEV, claim `engine_2026-08-16`. Head of Tier 1's QA-hardening batch after R129
closed, taken in the batch's stated order. Gate 1000 -> 1015 (`test_core` 653
-> 657, `test_upload_integrity` 207 -> 218); CLAUDE.md's session-start line and
the ledger Quick Card pin moved with it, the latter on a `ledger` claim, pin
line only.

**What.** The preflight printed `duplicate lineup groups: 9` on the delivered
2026-08-15 `2138_2g` file and BUILD nearly rejected a good portfolio over it
with no time at T-5 to go write a script. Zero of those nine were inside a
contest: seven were the same seven lineups mirrored across two identical Pocket
Cup satellites, and the other two were pairs among five single-entry contests.
`advisory()` counted duplicate lineup signatures across the whole file with no
contest partition, and the print site said the number without saying what kind
of duplication it was.

**Why it is a defect and not a display quibble.** Duplication inside one
contest is waste: two entries pay twice into one prize pool for one outcome,
and it is exactly what the allocator's `no_duplicates_within_contest` exists to
prevent. Duplication across contests is free, frequently deliberate, and the
allocator permits it by default under `allow_cross_contest_reuse`. The engine
has held both of those names since well before this entry; the preflight was
reporting their union under a third name that reads as a finding. It fires on
the one surface the project calls the pre-upload rule, at the moment the
operator has the least time to check it by hand.

**Fix.** One helper, `preflight_upload.partition_duplicate_lineups`, takes
`(contest_key, lineup_signature)` per filled entry and returns
`duplicates_within_contest`, `duplicates_across_contests`, `distinct_lineups`,
`contests_in_file`, and the flat `duplicate_lineup_groups`. `advisory()` calls
it, so `verify_export.py` inherits the split through the shared call it already
made rather than growing a second implementation. `build_slate.portfolio_
exposure` imports the same helper for the brief instead of restating the
partition, because two readers of one delivered file that disagree about how
much of it duplicates would be worse than either number alone. The Entry ID row
already carries its contest, so the partition took no new input; the key is
contest ID with the name as fallback, since identical satellites share a name
and a name-keyed partition collapses them.

**A split, not a filter.** The across-contest number is reported, not
suppressed: it is the number that says whether a satellite bank is being reused
deliberately. It reads as information and says so in the line itself. The two
numbers do NOT sum to the flat count and nothing may present them as if they
did — a signature held twice by each of two contests is two within-contest
groups, one signature crossing a boundary, and one flat group. All three
readings are correct about different questions, which is why one number could
not answer the operator's.

**Retained.** `duplicate_lineup_groups` stays in both tools' JSON. Nothing in
tree reads it (checked this session), but it is a published key and dropping one
to save a line is not a trade worth making.

**What the work corrected about the entry as filed.** The entry cited
`preflight_upload.py:1426` and `:1655`; both moved when R129 landed earlier the
same day, and the real sites were `advisory()` at 1468, the flat count at
1486-1487, and the unqualified print at 1716-1717. The entry also scoped the fix
to the preflight and the brief without noting that `verify_export.py:574` calls
the same `advisory()`, which is what made this one fix rather than two.

**The test that could not fail, caught in this session's own suite.** The
2138_2g shape's honest answer for `duplicates_within_contest` is 0, so the
headline reproduction test asserting `within == 0` passed against a mutation
that hardwired the value to 0. Hand mutation-checking found it; the test now
appends one duplicated entry to one satellite on the same fixture and asserts
the number moves to 1, which is what makes the zero mean anything. Seven
mutations were run by hand against the finished guard (contest-blind `within`,
`within` counting copies instead of groups, `across` mirroring the flat count,
`across` firing on every signature, a name-keyed partition, the dropped flat
key, and the return of the unqualified print line) and all seven were caught.

## 2026-08-16 — R129 + R36 F6m(1): supersession gets a way back, and a corrupt manifest stops erasing itself

DEV, claim `engine_2026-08-16`. Head of Tier 1's QA-hardening batch, taken in
tier order, with F6m(1) landed first because R129's entry says the new row has
to survive the corrupt-manifest handling and never lands before it. Gate 975 ->
1000 (`test_upload_integrity` 182 -> 207); CLAUDE.md's session-start line and
the ledger Quick Card pin moved with it, the latter on a `ledger` claim, pin
line only.

**R129 — the one-way door.** Manifest supersession was correct in both
directions and had no legal transition between them. A session that built five
variants on 2026-08-15 `2138_2g` and picked the third had, by the time it
picked, marked the third superseded, and `preflight_upload.py` correctly
hard-failed it. The only escapes were `--no-manifest`, which waives the
cross-check on a file that DOES have a record and therefore misrepresents it,
and rebuilding, which could not reproduce because the bank had grown underneath
(R130). The effect was worse than one lost delivery: it penalized exploring
alternatives, since the more variants a session builds the more certainly its
best one is superseded. Filed twice from opposite directions — a better variant
that could not be delivered, and an earlier certified run that could not be
restored (R98(3)'s restore remainder, which this closes) — one missing
operation.

`tools/promote_run.py --run-id <id>` is that operation. It copies the run's
immutable `runs/<id>/final/DKEntries.csv` and APPENDS an ordinary delivery row
carrying `re_promoted_from`, through the same `upload_manifest.deliver` door
every build uses, so the DO_NOT_UPLOAD_ ordering and the supersession of
whatever was current both come for free. No waiver, no status outside the closed
set, no prior row edited beyond the supersession any delivery performs. Three
things the entry asked for, all in: the preflight refusal now names the `run_id`
and the command rather than only the path that beat the file; the default
destination is run-scoped (`DKEntries_<tag>_<run8>.csv`) so the canonical path
is not the only place a certified file can live, with `--canonical` opt-in; and
it sits after F6m(1). Refusals: a run with no `final/` export, a `final/` export
whose sha256 no longer matches the run manifest (promoting that would launder a
mutated "immutable" artifact), and a run no manifest row names without an
explicit `--date`/`--tag`. An UNCERTIFIED run promotes as `not_certified` with a
loud line rather than being refused, because refusing there puts this tool back
in the business of process preventing a lineup.

**One correction to the entry as filed.** It specifies `status: current`. There
is no `current` in `STATUS_VALUES`, and writing one would trip R34's own guard
and hard-fail the next read — the exact defect R34 exists to prevent. The row
lands `candidate`, which is precisely "the file exists and nothing has checked
it yet"; preflight stamps `upload_ready` on those bytes afterward.

**Two defects found while testing the fix, both caused by it.** Re-promotion
makes two manifest rows for one sha256 ORDINARY, and both readers in
`preflight_upload.py` took the FIRST row matching the digest — adequate only
while bytes and rows were one-to-one. On a copy of the real 2026-08-15 manifest:
(1) `check_manifest` read the OLD superseded row and reported the re-promoted
file, which is current, as superseded, so the escape hatch tripped the block it
was built to escape; (2) `stamp_manifest_status` wrote `upload_ready` onto that
same superseded row — an obsolete record resurrected to the answer to "which
file do I upload", which is the lost-supersession failure R36 F6m names,
arriving through a door that is not the concurrency one it was filed for. It
also overwrote `superseded` with `blocked` on a repeat preflight, after which
the supersession check could never fire for that file again. Both now go through
one `match_manifest_record` (prefer this path, then prefer a live row, then take
the newest, since rows are appended in order), and a `superseded` row keeps its
status while the verdict is recorded beside it. One matcher for both readers,
because two implementations of one rule is this project's named no-op failure
class.

**R36 F6m(1) — corrupt is now its own state.** `read_manifest` answered ABSENT
and CORRUPT with the same empty manifest, and the next `record_delivery`
os.replaced the unreadable original away with every prior record's supersession
history. Reproduced before the fix on a two-row manifest holding one superseded
record: one row survived, the history did not. An absent file still reads empty,
which is true; a file that exists and does not parse (bad JSON, bad UTF-8, valid
JSON of the wrong shape, or unreadable) reads empty plus a `corrupt` block
naming the path, the error and the byte count, so every existing reader is
unchanged and a reader that cares now has the difference.
`record_delivery` quarantines the bytes to `upload_manifest.corrupt.<utc>.json`
first — a copy, never a move, because this mount grants create and truncate but
not unlink (R109) — and stamps `recovered_from_corrupt` on the fresh manifest
saying where they went and that no prior record survives in it. A quarantine
that fails raises `CorruptManifestError`, which the delivery path already
degrades to "MANIFEST NOT RECORDED" with the file keeping its DO_NOT_UPLOAD_
name: nothing is written over bytes that could not be preserved.
`verify_manifest` stops returning `passed: True, checked: 0` on a corrupt
manifest, which read as "nothing recorded, nothing wrong" on the one file
preflight cross-checks against.

**Not done here.** F6m's append-only-plus-derived-index redesign and its
concurrency half, and F6m(2)'s `salary_sha256`; R36 F3m; and R128, the batch's
second item, which shares the preflight surface but adds a brief-side change.
F6m's entry stays on the board rewritten to hold only those. R129's dependency
on R36 F6m's corrupt handling is now discharged either way.

**Five hand-run mutations, and one of them earned its keep.** Reverting the
matcher to first-wins, dropping the live-row preference, dropping the
same-path preference, skipping the quarantine, collapsing corrupt back into
empty, and letting the stamp overwrite `superseded`. The same-path preference —
the guard that fixes the live bug — initially SURVIVED its mutation: the fixture
happened to order rows so the newest same-bytes row was also the right one, so
both branches agreed and the assertion could not fail. That is R65's shape again
(a guard split across two pinned units with an unpinned join) and it was written
down as a fix that could not fail until the mutation was actually run. The test
it produced is the sharper one anyway, because it states the case the path
filter uniquely buys: identical bytes at two paths, one current and one
superseded and still on disk, where matching on bytes alone hands the obsolete
file the live row and preflight PASSES it at T-5.

## 2026-08-16 — Fragment-merge pass: R126–R133 filed, two false merge claims corrected, four fragments swept

Docs only, no code touched. DEV, claim `engine_2026-08-16`. Session-start gate
per-suite at every pin: `test_core` 653, `test_showdown` 56,
`test_upload_integrity` 182, `test_golden_replay` 9, `test_paste_lineups` 75,
summing to the 975 the contract pins. The one-call `--run-tests` macro was
killed past 178s and produced no verdict, which per the Quick Card is not a red
gate.

**What moved.** BUILD's 2026-08-15 `2138_2g` fragment enters as the
QA-hardening batch at the head of Tier 1, at Ben's direction — R129
(re-promote path), R128 (duplicate reporting split by contest), R127
(neutral-default enrichment naming plus the split `signal_applied`), R126
(apex and washout as first-class metrics), R130 (bank growth reporting), R131
(four smalls). Two 2026-08-14 fragments that no session had ever picked up
enter as R132 (control self-escalation, Tier 3 behind R115 and ahead of R124)
and an R42(b) extension. The 2026-08-12 partial-side fragment enters as R133
in Workstream 3, which stops claiming no open P1. R98(3) gains the two
remainders the 08-14 floored-bank fragment had left partially merged.

**Why it is filed this way, and the one remedy that is declined.** Every claim
in the 08-15 fragment was checked in tree before filing. Four held exactly:
Dobnak is in none of the 212 rows of `fangraphs_season_pitching.csv`;
`signal_applied` is a single `any()` over both sides
(`build_slate.py:1270-1278`); `duplicate_lineup_groups` is a flat count with no
contest partition (`preflight_upload.py:1426`); `superseded` hard-fails at
`preflight_upload.py:874` with `--no-manifest` the only escape and no promote
tool on disk. One did not. P4 reads the bank cache as keyed on date and
proposes keying it on the resolved controls; the cache is keyed on date plus a
pool signature and already carries R101's conditions signature over
projections, exclusions and stack bounds, while the controls that were varied
are allocator-side and applied after the bank exists. The non-reproducibility
came from the bank GROWING across seven builds on one date, which the
fragment's own P7 says without connecting it to P4. Keying on controls would
mint a thin bank per control change — the second failure that same night,
`entry-level joint MILP proven infeasible`. R130 is therefore a reporting item
and the proposed remedy is declined on the entry, because the wrong fix here
is the attractive one and a later session would otherwise re-derive it.

**Two of this board's own merge claims were false, and that is the part worth
carrying.** The 2026-08-15 queue note says seven 08-14 fragments were merged;
five were, and the two filed at 20:35 that evening arrived after the merge
session finished. The 2026-08-14 note says the 08-12 partial-side fragment
"stays consumed by R60" and was re-affirmed inside the 08-15 sweep note — it
cannot be, because R60 closed on 08-12 and the fragment reports a defect in
what R60 shipped, which this file's own R46-round-2 entry of the same day
states in plain text. A closed item's number is not a lid on later reports
against it, and "checked, still consumed" is not a check. Both notes are left
as written history with a dated inline correction. R13's "Awaiting Ben ... NOT
written" paragraph is corrected the same way: Ben decided on 2026-08-09, two
other entries already said so, and only that paragraph was stale.

**Swept, and what was deliberately kept.** Four fragments deleted after
verifying their substance reached the board: adversarial-QA (R11's rewrite),
delivery-guarantee (R124/R125/R117 and the Tier 4 FanGraphs decision),
fabricated-clock (R121), Showdown platoon (R122/R123). Five stay on disk as the
sole carrier of something — the four merged here keep their evidence until
their items land, and the 08-09 curated-archetypes fragment holds Ben's dated
decision, the nine-family table and four cautions that exist nowhere else, and
is ARCHIVE's to execute. The mount refuses `unlink`; the Cowork delete grant
lifted it, per R109's dated note.

**Not done.** No code, no test-count change, no ledger edit. The three
`ledger/inbox/` fragments remain ARCHIVE's, including the 08-15 DEV note asking
for a Quick Card item 1 amendment on the audit macro being load-conditional
rather than permanently unfittable — this session's own macro kill is a third
data point for it.

## 2026-08-15 — R116: the production allocator gets a candidate-reuse default

Tier 1's head, migrated out of `docs/2026-07-27_backlog_v2.md`. CLOSED, both
halves.

**The gap.** `select_and_assign_entries` added a reuse constraint only when
`max_candidate_reuse` was explicitly set (`contest_allocator.py:2282-2283`, `if
max_reuse is not None`, else no row at all). `STRATEGY_DEFAULTS` sets it on no
posture and nothing outside tests passed `reuse_strategy`, so the MILP
legitimately spent a whole file on its best few candidates: the first certified
2207_2g build put 4 distinct lineups across 11 apex entries, and the rebuild
with the cap at 2 delivered 7 distinct for 0.98% of aggregate fit. Nothing
certified wrong. Nothing in the brief said `distinct_lineups`, and preflight's
duplicate-groups line arrives after certification.

**Fix 1, the default.** `default_candidate_reuse_cap(entries, distinct
lineups)` is the legacy path's `minimum_cap` arithmetic (`:1062`) promoted from
a feasibility floor to the production default, keyed on distinct SIGNATURES
rather than candidate objects because the reuse rows are signature-keyed: two
candidate dicts holding the same roster are one lineup to DraftKings and share
one budget. It is feasible by construction (`distinct * ceil(total/distinct) >=
total`, and a round-robin deal never repeats inside a contest whose entry count
is at most `distinct`, which is the per-contest uniqueness rule's own
precondition). One entry returns 1, so `single_entry` is untouched. R98(2)'s
warning is noted in the comment block and explicitly does NOT generalize here,
because the direction is opposite: an engine-computed floor on an EXPOSURE cap
raises a ceiling and concentrates, while the same arithmetic on the REUSE cap
is the smallest budget that seats every entry and therefore spreads them.

**Cash is the one family that skips it,** read off
`contest_shapes.OBJECTIVE_CLASS_BY_SHAPE` rather than a local list. A cash
objective is a floor against a fixed cut line, so the second-best lineup is
strictly worse in every seat. One non-cash entry makes the whole file a GPP
portfolio, because the portfolio is one file.

**The all-or-nothing first cut was falsified by the golden grid, in the same
run.** 18 entries against 29 distinct lineups defaults to a cap of 1; that
proved infeasible against the production exposure caps on a 4-game bank, and
dropping straight to no cap handed back exactly the unbounded solve the item
exists to remove — the fix degrading silently to the status quo whenever its
most aggressive rung does not fit. So the default relaxes down a two-rung
ladder (`c`, `2c`, then nothing), each step counted and named, and the archived
06-03 grid now lands on rung 2 with a cap of 2 enforced and 11 distinct lineups
across 18 entries. Two rungs and not `log2(n)` because every rung is a full
MILP solve and the T-schedule prices that; a rung at or above the entry count
binds nothing and is dropped rather than solved as a duplicate.

**The ladder relaxes the engine's guess and nobody else's.** An operator-typed
cap is used verbatim, including one looser than the default, is never
recomputed, and still REFUSES when the bank cannot satisfy it — naming itself
in the error. Same two rules the R37 floor ladder follows: never on a timeout,
and the step is counted. The reuse step runs BEFORE the floor ladder, because
a primary-stack floor is a decision Ben made on archive evidence and this cap
is a number the allocator computed thirty lines earlier from the bank it
happened to be handed.

**Fix 2, the brief.** `candidate_reuse` (distinct lineups, cap, `cap_source`,
the rungs, relaxation steps) and the `candidate_reuse_counts` that has been in
the allocation result since v1.9 and no caller could reach now ride
`execute_portfolio`'s return on both the promoted and the deferred paths, and
land in the brief's `exposure` block. `portfolio_exposure` independently counts
`distinct_lineups` and `max_lineup_repeat` off the DELIVERED bytes on the same
sorted-roster signature, so the brief carries a check of the cap and not just
the allocator's word for it; DK writes rosters in slot order, so the tuple is
sorted or a duplicate reads as diversity. The refusal payload carries the reuse
block too: a refusal that does not say which cap was active, and how many rungs
the engine already spent, reads as a fact about the slate when it is a fact
about the engine's last guess.

**The golden baseline moved and the move was measured before it was
re-frozen.** `test_assignment_matches_baseline` failed on the production
replay. Total fit is identical at 2555.9321, the multiset of delivered lineups
is identical, distinct (11) and max repeat (2) are identical, and `aggregates`,
`meta` and `pure_verdict` are unchanged; 15 of 18 entries are re-dealt across
the same eleven lineups. That is a tie-break vertex change from adding a
constraint row, not a portfolio change, which is what made re-freezing the
right call rather than a way to make a red gate green.

Gate 962 -> 975 (`tests.test_core` 640 -> 653). Eight mutations were run by
hand against the new tests: never applying the default, deleting the ladder's
middle rung, relaxing on a timeout, making an operator cap relaxable, counting
the denominator on candidate objects, giving cash the default, keeping DK slot
order in the delivered-file key, and dropping the brief block. The first cut of
the distinct-lineups test survived its mutation because with identical rosters
the candidate ids are interchangeable by construction and no fixture can force
them apart; it was rewritten to pin the per-signature BUDGET, which can fail.
Fragment asks 3-5 still ride R84. **R117 is the new head of Tier 1.**

## 2026-08-15 — The false-signal batch closes: R113 + R112 + R103 + R99 + R92 + R71(a) + R119

Tier 1's false-signal batch, migrated out of `docs/2026-07-27_backlog_v2.md`.
Six items CLOSED in full (R113, R112, R103, R99, R92, R119); R71 closes only
its part (a), and its entry stays open on (b)(c)(d), rewritten to hold just
the remainder. One theme across all seven: the underlying computation was
already correct, but the line reporting it either couldn't fire, blamed the
wrong control, or pointed at a key that didn't exist. Five real builds since
2026-08-01 burned on this family, which is why it batched as one session
instead of landing pointwise.

**R99, the salary/feed clock cross-check.** The stderr disagreement gate read
`pool_report.get("salary_cross_check")`; no producer in this codebase has ever
written that key onto `pool_report`, so the gate returned `None` and could
never fire, on a clean slate or a genuinely disagreeing one. The brief's
`slate_clock.salary_cross_check` field was already reading the right object
(`clock`, from `slate_intake_manager.slate_clock`). Extracted
`salary_cross_check_note(clock)` as a pure helper so both sites read the same
object, and rewrote the message off the cross-check's real fields
(`feed_first_lock_game_id`/`salary_first_lock_game_id`/`drift_minutes`)
instead of `first_lock_local`/`feed_first_lock_local`, two keys that never
existed on this dict either.

**R92, the bank_warnings dead reads.** `build_slate.py` guarded two warnings on
`bank_report.get("jobs_failed")` and `bank_report.get("budget_exhausted")`;
`extend_bank` has never returned either key (`budget_exhausted` exists only on
`optimizer_v3`'s unrelated augmentation report), so both guards were `None`
and neither warning has ever fired. Replaced with the keys R55(b) actually
added for this: `jobs_raised`/`raised_by_reason` (the solve raised and proved
nothing, a defect) and `jobs_unanswered`/`unanswered_by_status` (returned no
lineup and proved no infeasibility, also retryable). Left as warnings, not
escalated to a checkpoint blocker: the entry raised that as an open decision
and this session did not have grounds to make it strategy rather than
reporting.

**R71(a) only, the pct>1 units slip.** `_cap_count` clamped `pct > 1` to 1.0 in
both the solver's copy (`contest_allocator.py`) and the export validator's
(`dk_entries_manager.py`): a `--controls-override` typo like
`max_player_exposure_pct: 45` (45 for 0.45) silently disabled the cap in both
places at once, consistently and invisibly. Both copies now raise `ValueError`
on `pct > 1.0` instead of clamping. Parts (b) (`reuse_strategy` inert on the
production path), (c) (a wrong-draftgroup error misclassified by string
prefix), and (d) (legacy signature-extraction exceptions degrading to unique
ids) are unchanged and the entry stays open on them, rewritten below to drop
(a) from its own text.

**R119, the ed4 adoptions still owed.** Adoption (a) (`objective_differentiation`,
recording only) and (c) (the `value_guard` pointer) land; (b) already landed
with the audit's own commit. `objective_differentiation.cash_and_gpp_selection_identical`
is `not signal_applied` -- a corollary, not a lineup-by-lineup diff: Floor is a
uniform 0.58 of `Base_Projection` (no per-row path), so ranking by Floor always
equals ranking by Base_Projection, and Ceiling only diverges from Base_Projection
where enrichment moved a `Ceiling_Multiplier` off its uniform neutral default.
`summarize_enrichment`'s returned dict never had a `value_guard` key even though
its own `warnings` list (copied verbatim from the raw enrichment dict) could say
"see enrichment['value_guard']" -- the raw dict had the key, the summarized one
the brief actually carries did not. Now it does.

**R113, the Showdown cap/lock conflation.** `captain_cap_relaxed` (thesis
apportionment running out of eligible captains under the exposure cap) and
`captain_lock_relaxed` (the solver dropping a thesis's assigned captain because
no feasible lineup existed with it locked) were summed into one `relaxed_slots`
number and reported as "captain cap relaxed" regardless of which one fired,
always pointing at `captain_exposure.by_player` -- a table that cannot show a
lock substitution, because a lock event is not an exposure event.
`solve_ladder` now records `lock_relaxation_detail` (thesis, requested captain,
substituted captain) at both sites `captain_lock_relaxed` increments, and
`build_slate.py` gained `showdown_relaxation_caution`, a pure helper that
writes one clause per counter that actually fired -- the cap clause keeps the
`by_player` pointer, the lock clause names the thesis and the substitution
instead. `captain_exposure` in the brief now also carries `cap_relaxed_slots`
and `lock_relaxed_slots` split out; `relaxed_slots` (the sum) is unchanged,
because the "clean when the relaxation counts are zero" contract only cares
whether either fired.

**R112, the bank blamed as a control.** Both halves of the entry, plus its
2026-08-14 rider. `_diagnose_binding_constraints` now takes an optional
`feasibility_inputs` (the slate-level `viable_sp_pairs`/`viable_sp_count`
`_slate_feasibility` already computes) and appends a same-line `BANK-LIMITED`
clause to the `max_sp_pair_repetition`/`max_pitcher_exposure_pct` findings when
the slate itself supports more than this bank sampled -- the bank-observed
count and `feasibility.inputs`' count now sit in the one string a truncated
read would still see. Threaded from `run_slate`, which already computes
`_slate_feasibility` for the checkpoint, through `run_initial_build` ->
`execute_portfolio` -> `select_and_assign_entries` -> both call sites of
`_diagnose_binding_constraints` (the `errors` list and
`solver_report["binding_constraints"]`), including the one re-entry on a
proven-infeasible primary-stack floor. Late-swap's `execute_portfolio` call is
untouched (the parameter defaults to `None`), so its refusals do not yet carry
this; that is a disclosed scope narrowing, not an oversight. **The rider**:
the "job list not exhausted" flag now rides EVERY binding-constraint line in
`errors`, not only a remedy trailing the whole list -- two findings in one
solve used to bury the caveat after both arithmetic lines, where a reader
taking only `errors[0]` (T-5's "present with zero diagnostic narration")
would never reach it. `_infeasibility_remedies`'s trailing remedy text is
unchanged; the per-line flag is a short bracketed tag, not a duplicate of it.
Considered and declined: R112's fix (2) (flooring the auto-bank's own SP-pair
coverage at `n_entries`). The entry's own "Done when" is an OR --
either the bank reaches that coverage, or the refusal is honest about why it
didn't -- and fix (1) alone satisfies the second branch, so (2) is a genuine
strategy change (raising the bank's construction target) left for a session
that wants to spend it deliberately, not folded in here.

**R103, the pinned same-game pair.** `bank_cache.extend_bank` derives its
same-game filter to keep a FRESH bank from spending jobs on an
anti-correlated pair. When both P slots are pinned (`locked_slot_assignments`),
`pair_space` is already narrowed to that one pair -- a fact about a file DK
already accepted, not a candidate for diversity -- but the filter ran anyway
and dropped it whenever the two pitchers shared a `Game_ID`, leaving
`usable_pairs` empty and the slice reporting `+0 targeted candidates` on an
entry that was never repairable for a pool reason. The filter now short-circuits
to keep the pair whenever both P slots are pinned, and the report carries a
new `pinned_pair_same_game_kept` flag so a `+0` slice names the pin instead of
reading as a dry pool. The one-pin case is untouched: an open second slot
still needs the filter, so it cannot pair the pinned arm with his own
opponent, which is a real diversity concern and not a fixed fact.

Gate: `PASS v2.26.0 26 modules 962 tests` (`tests.test_core` 621 -> 640,
`tests.test_showdown` 55 -> 56). Nineteen new tests in `test_core` plus one in
`test_showdown`, covering all seven items; the R103 same-game bypass and the
R71(a) rejection were each mutation-checked by hand (reverting the change
reddened exactly the test written for it, restored immediately after).
`CLAUDE.md`'s session-start line moves with the pin, as `AuditSkipHonestyTests`
requires.

## 2026-08-15 — R114 + R67 close: the upload gate stops failing arms the build legally rostered

Backlog R114 (P1, S, Workstream 5) and R67 (P2, S), Tier 1's head, both
migrated out of `docs/2026-07-27_backlog_v2.md`. Batched because they are one
mistake wearing two hats: reading a posted BATTING lineup as evidence about
pitching. Reproduced against the archived artifact before anything was touched.

**The live case.** 2026-08-12, slate 2210_2g, run `20260813T005233Z_1b5d3a4a`.
The build rostered Mason Black on an explicit declaration
(`viable_bulk_or_alt_sp`, the R104 vocabulary), all three certification gates
passed, and `preflight_upload.py` exited 2 twelve times on "Mason Black (KC) is
not in KC's confirmed lineup or probables". `verify_export.py` failed
identically, because it imports this check rather than reimplementing it. The
only way through was `--force`, which is exit 4 on a failure the operator knew
was spurious. That is the part that matters: CLAUDE.md makes this the one
pre-upload rule, and a gate that hard-fails legal, certified files teaches the
operator to force past it. The habit is what transfers to the night the failure
is real.

**R114, the declared arm.** `declared_pitchers` reached the optimizer and the
brief and stopped there, so the gate re-derived "absent" from a feed that never
carried the fact. Both tools now read it and report a declared arm as an
acknowledged WARN naming the role. An **undeclared** missing arm still exits 2,
unchanged; no other check moved, and the 0/2/3/4 contract is untouched.

R114's own falsifier turned out to be the right one — "if declarations already
reach an input preflight reads, the fix collapses to reading it." They do: the
brief has recorded `declared_pitchers` all along. No engine change was needed
and none was made.

Three decisions inside that are not obvious from the diff:

- **The brief is matched by `delivered_sha256`, not by name or mtime.**
  `outputs/2026-08-12/` holds eight briefs for four deliveries, and both the
  newest and the alphabetically first belong to a different slate whose
  declarations are empty. Any resolution weaker than the hash reads the wrong
  slate's facts and the check goes quiet again — the same class of failure as
  the original blindness, arriving through the fix.
- **The acknowledgement applies to a pitcher-position row only.** Pointed at a
  hitter, a declaration is reported and NOT applied. Otherwise
  `--declare-pitcher` becomes an off switch for R4, which is the scratch-zero
  this check exists to catch, and the gate would ship its own bypass.
- **Disagreeing briefs resolve to their intersection.** Every id dropped there
  restores a hard failure and every id kept removes one, so a contradictory
  record resolves toward the closed gate.

`--declare-pitcher <id>[=role]` states the fact by hand where there is no run to
read, deliberately the same grammar as `build_slate.py`'s flag of the same name,
bare-id default (`declared_probable_sp`) included.

**R67, the bullpen game.** `confirmed_teams` keyed off `lineup_status` alone, so
a confirmed nine with a null `probable_pitcher` evidenced the arm too and any
pitcher rostered off DK's `Starting` column failed. Those teams are now
bats-only: their hitters bind exactly as before — pinned, because a second way
to skip R4 is the obvious way to get this wrong — and the arm is named soft.
`--feed-lenient` was the only prior escape and it loosened everything.

**Truthful labels.** Both paths WARN rather than pass in silence, and each names
its evidence class, because the two facts are not equally strong. A posted
lineup is observed; a declaration is the operator's own statement, so it reads
`Evidence: operator_declared`. R114's live case had a hand-patched probable
alongside the declaration, which made the check pass on operator-supplied input:
the right fact that night, and still not independent confirmation. The warning
says which one it has.

**One correction to the filing,** found by reproducing it first. R114's entry
described KC as running a bullpen game. The feed on disk says otherwise —
`lineup_status: confirmed`, probable Daniel Lynch IV — so the live case is the
DECLARED case, and the null-probable case R114 described is R67, which had been
sitting open since the 2026-08-04 audit. The mechanism and the failure text the
fragment reported were exactly right; only the cause was misattributed. The two
entries were already batched, so the fix set does not change.

Gate: `PASS v2.26.0 26 modules 942 tests` (`tests.test_upload_integrity` 168 ->
182, `grew`). The 2210_2g replay pair is the acceptance evidence — as delivered,
exit 0 with the named WARN; identical bytes with the declaration unreachable,
exit 2 with the original twelve failures. Each new test was mutation-checked:
disabling the acknowledgement reddens five, disabling bats-only reddens one.
`CLAUDE.md`'s session-start line and `EXPECTED_SUITE_COUNTS` move together, as
`AuditSkipHonestyTests` requires; the `EXPECTED_TEST_COUNT` comment was stale at
901 against a dict summing to 928 and is now the sum it claims to be.

## 2026-08-14 — Portfolio-edge audit: R114-R125 filed, eight BUILD fragments merged, ed4 adjudicated

Record of two commits (`29d87c9`, `94db2af`) that shipped without one, which is
the debt `audit.changelog_debt` flagged at the next session's start. Written now
rather than backdated: the rule is that a change is not shipped until its entry
exists, and the honest repair is an entry that says what happened and when it
was written, not one pretending to have been there.

Docs-only both times — `docs/2026-07-27_backlog_v2.md` and `.audit/` — on claims
`engine_2026-08-14_edge_audit_2026-08-14` and `engine_2026-08-14_edge_audit2`.
No code, tests, or contracts moved.

**Filed R114-R120,** then R121-R125 on the continuation, twelve new numbers
against the audit's stated cap of twelve. **Merged eight BUILD fragments** filed
by concurrent build sessions, with four mechanisms re-verified in tree before
filing (`build_slate.py:1837-1838`; `showdown_theses.py:62/70/109`;
`execution_pipeline.py:387`; `solve_ladder` at `showdown_theses.py:484`) —
diagnoses corrected in the tree where the fragment's reading did not survive
the read. **Adjudicated the ed4 greenfield review:** R119 adopted, a sim-gate
variance precondition added, everything else declined.

**Tiers reordered** R118 -> R48+R83 -> R10, on the audit's central finding: the
miner computes each archived contest's player->FPTS map and strips it at the
archive boundary (`field_miner.py:1961`), so the learning loop discards the one
artifact that would grade it. Retaining it and shipping a deterministic
counterfactual replay converts a 271-contest archive of real fields into the
substrate the board's three open strategy questions currently wait on live
tranches for. The verdict was "do not rebuild; instrument, default the reuse
cap, fix the two gate blindnesses, and grade" — R114 above is one of those two
gate blindnesses.

Full record, including verification levels and the pre-audit backlog snapshot:
`.audit/AUDIT.md`.

## 2026-08-14 — R70 closes: the slate dir stops picking a draftgroup for you, and the clock reads its own keys

Backlog R70 (P2, S, Workstream 3), Tier 1's head, migrated out of
`docs/2026-07-27_backlog_v2.md`. Filed by the 2026-08-04 audit, reproduced
against the real `data/slates/2026-07-30/` layout before anything was touched.
Same family as R69 above and the reorder's argument for adjacency held: R69 left
the intake surface warmer than it found it, and this is the last pointwise
wrong-slate patch before R81's design pass generalizes the family.

**(a) Content-sniffing kept the LAST schema-passing file per role.** Both
branches of the loop in `_find_salary_and_entries` assigned into one variable,
so the winner was whichever file sorted last. Against the real 07-30 dir that
is `DKSalaries_showdown_1415_1g_sd.csv` + `DKEntries_showdown_1415_1g_sd.csv`,
a 1-game showdown pair, staged on a 6-game Classic day with no warning.

This is not an edge case and the fix is sized for that: 17 of the dirs under
`data/slates/` carry more than one salary export, because a day routinely has
two Classic draftgroups plus its showdowns and they all land in the same folder.
Neither filename convention nor sort order nor mtime is authority over which
slate the operator is building — DK writes the bare `DKSalaries.csv` name for
whichever slate was clicked last, so preferring the conventional name would be
the same wrong-draftgroup bug in a nicer hat. Every match is now collected and
more than one per role RAISES `AmbiguousSlateInput`, naming every candidate and
the flag that resolves it.

A block with no way through teaches the operator to write a driver script that
bypasses the tool, which is R106's lesson, so the block ships with its channel:
`--salary-csv`, `--entries-csv`, `--bundle-json`, `--platoon-json`, plus exit 4
so a driver can tell "name the file" from exit 2's "go download the file". An
override naming a file that does not exist hard-gates rather than degrading to a
warning, on R69(c)'s precedent: it is an operator-typed identifier and one
argument fixes it. `slate_bundle.json` still wins outright when present, because
`fetch_slate_bundle.py` writes that exact name and a conventional hit is
unambiguous by construction.

**The platoon half cost more than it looked like.** The fallback took the first
remaining JSON in the dir with no validation, which on the 07-30 layout is
`_home_sides_feed.json`, a lineups feed. That fills nothing —
`build_projected_order` iterates `platoon['teams']` and a feed has `games` — and
it also suppresses `DEFAULT_PLATOON_REFERENCE`, which `build_slate_pool` loads
only when `platoon_json is None`. A bad guess is strictly worse than no guess.
Candidates are now checked for a non-empty `teams` list, a rejected guess falls
through to `None` so the reference file still loads, and the rejection is named
in the pool warnings. A file the operator named explicitly blocks instead, same
precedent as above.

**(b) `--checkpoint` printed `first_lock=None deadline=None
minutes_remaining=None` on every run.** It read `first_lock_et`,
`delivery_deadline_et` and `minutes_remaining`; `slate_clock()` emits
`first_lock_utc`, `deadline_utc` and `minutes_to_deadline`. Three keys, none of
them real, on the T-schedule's one budgeting instrument, blank exactly when the
operator reads it at T-20 / T-10 / T-5. Worse, the blank was indistinguishable
from the one case that genuinely has no clock, a slate with no parseable game
datetimes, which now says so in words. The line reads the real keys, converts to
ET on the file's existing UTC-4 convention because the T-schedule is stated in
ET, and calls out `past_deadline`.

**Two corrections to the filing,** both found by reproducing it first. The entry
said the 07-30 dir "stages the wrong draftgroup end-to-end"; on that dir
specifically it does not reach the end, because there is no `slate_bundle.json`
and staging dies at the bundle check. The end-to-end path needs a dir with a
bundle AND two Classic pairs, which `data/slates/2026-07-19/` is. The defect and
its blast radius are unchanged; the reproduction is narrower than the words. The
entry's other clause, that the platoon pick "suppresses the default
platoon-reference load", is exactly right — the default load is in
`build_slate_pool`, not in `stage_slate`, which is why a first read of the tool
does not show it.

**One rider taken on the way past,** unplanned and recorded as such: the
"no platoon JSON found" warning promised that TBD teams "will fall back to top-9
AvgPointsPerGame". That stopped being true when `build_slate_pool` began loading
`DEFAULT_PLATOON_REFERENCE` for a `None` platoon_json. APPG is the fallback only
when the reference is absent too, so the warning told the operator their TBD
teams had no projected order when they had a real one. Same steers-you-wrong
class as the two defects above and one line away from them, so it is fixed here
rather than filed. The text is now the module constant
`NO_PLATOON_IN_DIR_NOTE` so the claim is pinnable.

**Round two, same day: the first cut of this fix shipped a blocker and an
adversarial pass caught it before any slate used it.** Three findings, all real,
all fixed here.

`_resolve_override` resolved a relative path against the CWD before the slate
dir, and then flattened the fallback to `.name`. The repo root holds a stray
`DKSalaries.csv` and `DKEntries.csv` from 2026-07-27 beside a `slate_bundle.json`
from 07-21, so run from the repo root — where the tool is documented to run —
`--date 2026-07-19 --salary-csv DKSalaries.csv --entries-csv DKEntries.csv`
staged the JULY 27 files against the 07-19 bundle and printed
`salary=DKSalaries.csv`, a line byte-identical to a correct in-dir resolution.
57 rows and 51 hitters where the real slate has 40 and 36, surfacing downstream
as "cannot fill a stack" blockers that read like ordinary IL noise. That is
R70's own defect re-entering through R70's remedy, on the 17 dirs where the
flags are now mandatory. The resolution order is therefore part of the fix:
slate dir first, the typed directory preserved, and `_provenance` prints the
FULL path plus a warning whenever an input sits outside the slate dir, because
an out-of-dir file wearing a bare filename is how the wrong draftgroup travels
unnoticed.

The ET conversion hardcoded UTC-4, citing this file's own `_today_et` as the
convention — but that helper was the last un-migrated copy of the exact bug
`repo_env` was built for (R65 names it in `fetch_slate_bundle`). Verified: a
2026-11-04 first lock of 19:08 ET printed as 20:08, an hour late on the
T-schedule's one budgeting instrument, while `minutes_to_deadline` stayed
correct — so the wall clock and the numeric budget disagreed by 60 minutes. Both
helpers now go through `repo_env`, and the July fixture that could never catch
this is joined by an EST case. `_et` also returned `None` on an unparseable
timestamp, which reproduced R70(b)'s all-Nones symptom on an `available: True`
clock; it returns a label now.

Third, an interaction the platoon fix created rather than found. Before it, a
dir holding only a lineups feed had that feed mistaken for the platoon file, so
`DEFAULT_PLATOON_REFERENCE` never loaded and R27's age gate never fired at this
door at all. Now it loads — and `stage_slate` was inheriting the engine default
`stale_platoon_policy='block'` while `late_swap.py:578` and
`build_slate.py:1325` both pass `'warn'`. That would have made a review-only
checkpoint STRICTER than the build door it previews, as a side effect of fixing
something else, and the reference is routinely several days old. It now passes
`'warn'` explicitly to match its siblings, with `--stale-platoon-policy` to ask
for the engine default.

Smaller, same pass: an override is checked against the role it claims, so
swapped flags are named instead of staged (`--entries-csv <a salary file>` used
to sail through); the dir is not scanned at all when both roles are named, so an
undecodable CSV elsewhere cannot fail a resolution that never read it; and the
sniff loop skips an unreadable file per role rather than letting a codec error
escape with no filename.

27 tests, pin 901 to 928 (`tests.test_core` 594 to 621), and CLAUDE.md's quoted
session-start line moves with it — `AuditSkipHonestyTests` exists to make that
pair impossible to split, and it caught the omission on the first full run. The
ambiguity and shape tests build their dirs from R62's vendored frozen exports
rather than the untracked 07-30 dir, so the suite still runs on a
tracked-files-only checkout. The first 18 were mutation-checked against restored
pre-fix implementations: 12 fail, and the 6 that pass both ways are doing that
deliberately — the happy-path regression guard, the over-strict-validation
guard, the `_is_platoon_shaped` unit, and the pin asserting `slate_clock`'s own
key names, which is the test that would have caught (b) at write time.

Not touched: `stage_slate` remains a review-and-checkpoint door, not a
production build door. `build_slate.py` and `run_slate` are unchanged.

**One thing this leaves open,** filed rather than fixed because it is a design
question and not a bug: the block forces the operator to name salary and entries
independently, and nothing at stage time checks the two are the same draftgroup.
That is how 2026-08-13's cross-draftgroup pair
(`DKSalaries_2207_2g.csv` + `DKEntries_1507_3g.csv`) was born. `preflight_upload`
catches it, but this is the checkpoint door and it should. It belongs to R81's
fingerprint contract, whose entry now carries the requirement.

---

## 2026-08-13 — Decided, not yet shipped

### Decided: apex over cash is the standing priority for GPP-shaped contests
Ben. Backlog R37(2), R10, R40.

Ben: "the only way this makes money over the long term is big wins." GPP-shaped
contests are built for the apex outcome (WTA-style ceiling), not for cash-line
frequency. Recorded as riders on the three items it actually touches rather
than as a new number, because it reframes priority on standing work; it does
not add work.

Not a gap closed: every non-cash, non-satellite shape already scores on pure
ceiling (`score_lineup_candidate`, `optimizer_v3.py:3453-3456`), so there was
no floor-seeking bias in GPP/WTA scoring to strip out. What the directive
actually elevates is R37(2)'s narrow-breadth floor-5 work (the concrete
apex-construction lever, already scoped to the shapes where the payout sits
at rank 1) and reaffirms R10 (duplication modeling, the only thing that says
whether an apex-shaped build actually clears the field) at the top of Tier 2.

One thing the directive does not license: raising `salary_uniqueness_weight`
or `field_pressure_weight` on the GPP ladder (`CONTEST_SHAPE_PROFILE_WEIGHTS`,
`optimizer_v3.py:2813-2874`) to chase more differentiation. Ledger 3.17 found
the opposite, blanket contrarianism does not win; chalk-positive cores plus
one or two sub-10% pieces do, everywhere except supersatellites, and Ben's own
measured posture already runs more contrarian than winners in exactly
single_entry_gpp and satellites. R40 is unmoved for the same reason a standing
preference is not new evidence: the routing recommendation stays no-not-yet
until more finishes exist to grade.

---

## 2026-08-13 — R69 closes: three intake reads that failed OPEN now fail loud

Tier 1's head, and it inherits R60's argument directly: each of these three
degraded to SILENCE rather than to a signal, so a disarmed guard and a healthy
slate produced byte-identical output. All three were reproduced before they were
touched, and all three matched what the entry filed.

**(a) A renamed or absent `Status`/`Starting` column disarms the IL drop.**
`parse_dk_salary_csv` reads both by exact key and neither is in
`REQUIRED_SALARY_FIELDS`, so a file without them passes the schema gate with
`missing_columns: []` and then returns `""` for every row. Every player reads the
clean tier. Three mechanisms disarm at once: shelved players stay in the legal
pool and can be taken by the platoon and APPG fallbacks (the F1 defect arriving
as a DATA condition, which is R60's class by another route), opener detection
loses its signal, and DK's own `Starting` column stops naming probables — the
first-class probable source CLAUDE.md's build contract names.

New `slate_intake_manager.salary_status_coverage()` reports what the file
carries; `build_slate_pool` calls it and its warnings lead the pool report, which
is the surface CLAUDE.md already requires be read before approving. It also lands
as `pool_report["salary_status_coverage"]`. Three signals: column absent, column
present but not one row of a slate-sized file non-blank
(`STATUS_COVERAGE_MIN_ROWS = 40`, because a two-game Showdown pool really can
carry no shelved player), and the near-miss headers named, since identifying
`Injury Status` is the whole fix on the operator's side.

It WARNS, it does not block, and it never drops anyone. This is not hypothetical
and not contrived: 3 of the 75 real `DKSalaries*.csv` files under `data/slates/`
ship without both columns, most recently 2026-08-01 (192 rows). Refusing those
would be the forbidden pool reduction wearing a schema hat.

**(b) A platoon reference with no parseable `collected_date` bypassed the
staleness gate entirely.** The age came out `None`, `None` compares against no
threshold, and the gate that exists to stop a stale reference was silent at its
strictest setting. Age unknown is not age zero. Verified across all three
variants — unparseable string, empty string, key absent — each producing
`platoon_age_days: None` with the build still leaning on the reference
(`platoon_dependent_teams: ['T4']`) and zero blockers, zero warnings.

Now reported at the POLICY's own severity: a blocker under
`stale_platoon_policy='block'`, a warning under `'warn'` (what `build_slate.py`
and `late_swap.py` pass, so the build still ships). Conditioned on
`platoon_dependent_teams` exactly like the days-old branch beside it, which
preserves F17 and R60's rule that the gate follows what the projection SUPPLIED:
a fully posted side takes all nine seats, so an unageable reference supplied
nothing and stays silent.

**(c) Exclusion "blockers" only ever warned.** `_exclusion_block`'s docstring has
said since F15 that an exclusion matching nobody is "a blocker at approve=False";
the code appended to `checkpoint["warnings"]` and the only approve=True hard gate
was contest identity. So `approve=True` sailed past a typo'd ID and built a
portfolio around a player the operator had asked to drop.

Decided as a SPLIT, because the key pooled two findings that are not the same
kind of fact and the shared label made both of them lies:

- **Unmatched exclusion ids → hard gate on `approve=True`,** beside contest
  identity and on the identical argument: an operator-supplied identifier that
  resolves to nothing, decidable from disk in under a second, invisible in the
  certified output, and fixed by correcting one argument on the same command. No
  override, for the same reason — an override would cost more than the fix. There
  is no standing cross-slate exclusion list to false-positive against:
  `excluded_player_ids` has no CLI surface in `build_slate.py` and reaches
  `run_slate` only as a per-build argument.
- **Unrecognized `Excluded` cells → relabelled to `warnings`.** Keeping those
  players is the DOCUMENTED reading of that column (CLAUDE.md: "blank, NaN,
  'False' and unrecognized cells keep them"), so filing it under a key that now
  gates would refuse builds for behaving as specified, and its remedy is a file
  edit rather than a flag correction. That is the line the split is drawn on.

Both findings still reach the plan-mode report with the same text, so
`approve=False` output is unchanged in content.

`tests.test_core` 582 -> 594: nine pinning (a) and (b) in a new
`IntakeFailOpenTests`, three pinning the (c) split. Every one is paired with a
HEALTHY control, because a guard that fires on everything is the same defect
wearing the other sign — the healthy salary file warns about nothing, the
sub-floor pool stays quiet, the fully posted side says nothing, and a matched
exclusion still approves. `test_checkpoint_names_unrecognized_cells` was
rewritten: it pinned the mislabel, asserting the message appeared in `blockers`.
Pin line updated in `tools/audit.py` (889 -> 901), `CLAUDE.md`, the ledger Quick
Card, and `skills/generate-lineups/SKILL.md`.

Audit evidence: the single-line `--run-tests` macro does not fit this sandbox's
per-call ceiling (killed at ~178s twice, and a background run reached ~935s
without landing output), so the Quick Card's documented per-suite fallback
produced it — `test_core` 594, `test_showdown` 55, `test_upload_integrity` 168,
`test_golden_replay` 9, `test_paste_lineups` 75, each `state=clean passed=True
skipped=0` through `audit.classify_suite` itself, summing to 901, with
`audit.py --terse` PASS on pins and inventory. That per-call ceiling is now
recorded on the Quick Card line, since the previous session hit the same wall and
left it as a one-off note.

## 2026-08-12 — R46 round 2: preflight names the player, and a PARTIAL side stops skipping the check

R46 made the posted-lineup blind spot loud. It did not make it a finding, and on
the `1840_3g` slate that cost six of eighteen certified entries.

The chain. The operator paste held all nine DET slots; the ninth, Corey Julks,
has no DK salary row, so `lineups_from_paste.py` wrote `lineup_status: partial`
with `reason: "mlb.com posted a partial lineup"` — which is false, mlb.com posted
a complete one. R60's TBD routing then seeded a ninth DET hitter from a 7.9-day
platoon reference and picked Eduardo Valencia, the bench catcher, who is $1,100
cheaper and 0.44 APPG better than the posted catcher. The optimizer took him in a
third of the portfolio on value. `workflow_valid`, `selection_certified`,
`allocation_certified` and `preflight_upload` all passed, because DK lists him as
active: he is rosterable, just not playing.

`check_feed` had the evidence. `posted[team]` is populated for every side before
the confirmed test, so DET's eight observed names were in memory when
`team not in confirmed_teams` threw them away. What the operator saw instead was
`DET (32 slots)`, a team name and a slot count, which is a pointer to an analysis
nobody runs at T-40. Second occurrence of the same mechanism in nine days;
Locklear on 2026-08-03 was the first.

Three changes, all in `tools/preflight_upload.py`:

- **Three sides, not two.** A side with posted hitters under a non-confirmed
  status is now PARTIAL and is cross-checked against its posted names. The bound
  is `0 < posted < 9` deliberately: a side listing all nine under a non-confirmed
  status is most likely a projected nine, and a projection is a labeled prior, so
  a rostered player outside it is contradicted by a guess rather than an
  observation. That distinction is what R4's `test_a_team_that_has_not_posted_stays_soft`
  was protecting, and it still passes untouched.
- **Name the player, every time.** Every rostered player absent from a posted
  lineup is reported by name with the entry count carrying him and his team's
  posted count, for the partial and the unposted case alike:
  `Eduardo Valencia (DET) in 6 of 18, DET posted 8 of 9`. Soft, for R46's stated
  reason. New info keys `feed_projected_players` and `feed_partial_teams`; the
  R46 slot-count warning stays for genuinely unposted teams.
- **One arithmetic hard fail.** An entry rostering more absent hitters than its
  side has un-posted slots cannot be right whatever the projection said. Strict
  by default, warn under `--feed-lenient`. It would NOT have fired on Valencia
  (one absent bat against one unknown slot), which is the point: naming does the
  work and this is the floor. A declared probable pitcher is a stated fact on a
  partial side too, so a different arm is a contradiction; an arm on a side that
  declared no probable is an unknown and never consumes a hitter slot.

Verified against the two real files from the slate. The superseded build
(`fadcd669...`) now prints
`WARN 1 rostered player(s) absent from a posted lineup, each filling a projected slot: Eduardo Valencia (DET) in 6 of 18, DET posted 8 of 9`.
The delivered build (`df7cd44e...`) is clean.

`tests.test_upload_integrity` 162 -> 168, six tests pinning the partial side, the
naming, the arithmetic fail, its lenient downgrade, and the declared probable.
`write_three_game_feed` grew `partial=` and `probables=`. Pin line updated in
`tools/audit.py` (883 -> 889), `CLAUDE.md`, the ledger Quick Card, and
`skills/generate-lineups/SKILL.md` — which read 829, stale across two moves.

Not fixed here, and filed as
`docs/backlog_inbox/2026-08-12_BUILD_partial-side-lets-a-bench-bat-into-the-pool.md`:
the false `reason` string in `lineups_from_paste.py`; R60 costing a partial side
its posted batting order (DET's F2 came from the platoon projection, so Malgeri
priced 9th while batting 6th); the pool blocker that refuses a confirmed side
with eight rosterable hitters on a `< 9` test when CLAUDE.md's stated bar is five,
and whose message lists IL pitchers as reasons a team is short of hitters; and
`--ignore-pool-blockers` plus `--assume-gates lineup_gate_passed` both failing to
get past that blocker, which burned two build cycles at T-21. This entry treats
the symptom at the last gate before upload. Those four are the disease.

## 2026-08-12 — R110 closes: the claim round trip is closed, `sweep --release` exists, and the ten stale held claims are cleared

Sixth DEV session of 2026-08-12, engine claim `engine_2026-08-12`, ledger claim
`ledger_2026-08-12`, at Ben's instruction after he was shown the ten. Write
set: `tools/claim.py`, `tests/test_core.py`, `tools/audit.py`, `CLAUDE.md`,
`docs/2026-07-27_backlog_v2.md`,
`ledger/MLB_Classic_Calibration_Ledger.md` (Quick Card pin line only), this
entry.

### R110(a): the tool printed a command that did not work

`check` and `sweep` print the DATED directory name, and `_incomplete_note`
interpolates it into the release command they instruct the operator to run.
`release` then re-derived the name and appended today's date again, so the
printed command failed on every claim whose directory is not exactly
`<resource>`:

```
$ python tools/claim.py release engine_2026-08-04_full_audit
ERROR  no claim at claims/engine_2026-08-04_full_audit_2026-08-12
```

That is the loop. A session in exactly the state the note describes runs the
note's command, gets exit 3, and hand-writes a `RELEASED` marker instead,
which does not release. Seven claims sat HELD-with-a-marker because of it.

Fixed by resolving a READ or a RELEASE against disk: an existing
`claims/<resource>` directory is unambiguous, so it wins, and only when none
exists does the date get appended. `take` deliberately does NOT use the
resolver, because its whole guarantee is that the mkdir collides. `_claim_name`
also stopped appending a date to a name that already ends in one, which is
what minted `engine_2026-08-10_2026-08-10`. R110(b), `take` clearing a stale
marker on re-take, was already in the tree.

### `sweep --release`

`sweep` already found stale held claims with the right rule and could not
complete one, so clearing ten meant ten hand commands. It now takes
`--release`. Plain `sweep` stays read-only, because releasing is Ben's call
under the multi-session contract and a session-start report should not mutate
anything.

Staleness moved off the NAME and onto `owner.json`'s `taken_utc`. The two
disagree in one direction that costs something: a BUILD session past UTC
midnight working the previous ET slate holds a live claim whose name reads
yesterday, and sweeping on the name would clear a live mutex while printing
that nothing taken today was touched. owner.json is authoritative everywhere
else in this tool and is now authoritative here; the name is the fallback when
`taken_utc` is missing or unparseable.

One existing test moved with it. `test_sweep_reports_a_stale_held_claim_and_
deletes_nothing` built its fixture with `take --date 2020-01-01`, which writes
`taken_utc=now` and so produced a claim that only LOOKED stale. It now
backdates `owner.json`, which is what a real abandoned claim looks like. The
test's intent is unchanged; its fixture stopped being fictional.

### The ten

Cleared at Ben's instruction on 2026-08-12: `engine_2026-08-04_full_audit`,
`engine_2026-08-10_2026-08-10`, `ledger_2026-08-09_r37_pin_2026-08-09`,
`ledger_2026-08-09_r37_pin_b_2026-08-09`, `slate_2026-07-29_sealad_sd`,
`slate_2026-07-30_1910_6g`, `slate_2026-07-30_sealad_sd`,
`slate_2026-08-01_2010_2g`, `slate_2026-08-01_stltor_sd`,
`slate_2026-08-03_7g`. Seven carried a marker, three were beacons with none.
Each scope was checked against the tree before release rather than assumed:
R51/R91 are filed in both the backlog and the changelog, R101 appears in the
changelog seven times, and the `r37` pin those two ledger claims were taken for
has been superseded four times since. No uncommitted work sat in any of their
write sets. Afterwards the only HELD claims are this session's two, neither
stale.

### Sequencing deviation, stated rather than buried

R110's entry said it rides R31, on the reasoning that fixing one without the
other means touching `claim.py` twice. It landed without R31 because Ben
approved the sweep release and `sweep --release` is useless while the release
path cannot resolve the names `sweep` prints. R31(b)(c) stays open and will
touch this file again; that second pass is the known cost of this order.

### Ledger Quick Card

Line 19 read `871 tests` after R60 moved the gate to 877 and this change moved
it to 883. It is the mandated session-start read, so a stale pin there is a
shortfall the next session would chase. Corrected under a `ledger` claim, pin
line only, with the correction noted in the line's own style. No ledger
sections touched.

### Gate

`tests.test_core` 576 → 582, total 877 → 883. All five gated suites run
individually and pass at exactly their pins: core 582, showdown 55,
upload_integrity 162, golden_replay 9, paste_lineups 75. The single-line
`--run-tests --terse` gate did NOT complete in this session's sandbox: suite
wall time reached ~144s against a per-call ceiling near 170s that also has to
cover five subprocess spawns and the static checks, and repeated attempts were
killed at the cap. That is the case the Quick Card's own sandbox caveat
prescribes a fallback for, and the fallback is what was run: per-suite, then
`python tools/audit.py --terse` for pins and inventory, which passed
(`PASS  v2.26.0  26 modules  ? tests`). Recorded rather than smoothed over,
because "the gate printed PASS" and "every suite the gate runs passed at its
pin" are different claims.

---

## 2026-08-12 — R60: a partial side's posted starters are seeded into the pool ahead of both priors, and "team excluded" now means excluded

Fifth DEV session of 2026-08-12, engine claim `engine_2026-08-12`. Tier 1 item
1 off the queue rebuilt earlier the same day, and the last open P1 in
Workstream 3. Write set: `mlb_engine/intake/live_data_adapters.py`,
`tests/test_core.py`, `tools/audit.py`, `CLAUDE.md`,
`docs/2026-07-27_backlog_v2.md`, `docs/backlog_inbox/` (one fragment
consumed), this entry. Gate before: `PASS  v2.26.0  26 modules  871 tests`.
Gate after: `PASS  v2.26.0  26 modules  877 tests`.

### What was wrong

A side the feed marks `partial` is not confirmed, so it routes through the TBD
path. That path built its nine from the platoon projection and then filled the
remainder by ranking the team's whole roster on `AvgPointsPerGame`, and it
never read the status map's posted `Projected_Starter`s. A posted starter with
a worse season average than a bench bat therefore lost his seat to the bench
bat.

Reproduced before the fix, on the four-team pool fixture with T4 posting eight
hitters at 2.0 APPG against its own bench at 9.0:

```
T4 hitters in pool: Bench1 Bench2 Bench3 Bench4 Hitter1..Hitter5
POSTED STARTERS LEFT OUT: T4 Hitter6, T4 Hitter7, T4 Hitter8
teams_report T4: {'status': 'fallback_top9_appg', 'hitters': 9}
warnings naming a left-out starter: []
```

Three posted starters unrosterable, four bench bats in, and a team report that
reads like a clean nine. This is the defect class the build contract exists to
prevent: it certifies, and it is invisible in the certified output. The APPG
spread is not synthetic — a call-up or a defensive starter carries a low season
average on the night he is in the lineup, and the regular he replaced carries
the higher one.

A second half surfaced while reading the same block. Under
`tbd_fallback='exclude'`, the platoon-seeded rows were already in `keep` when
the exclude branch fired, so the blocker said "team excluded" while five of
that team's hitters sat in the pool. The report and the pool disagreed at the
exact moment the operator reads the blocker to decide.

### What shipped

Posted starters on a partial side are collected from the status map, scoped to
slate teams and ordered by posted slot for determinism, and seeded into the
TBD fill ahead of the platoon projection, which is ahead of APPG. The ordering
is the point and it is an ordering of evidence: a posted slot is OBSERVED, the
two fills below it are PRIORS, and a prior never displaces an observation.
Team report words moved with it — `posted_partial`,
`posted_partial_plus_platoon`, `posted_partial_plus_appg_fallback` — because a
report that calls a mixed nine "platoon" hides which seats were posted. Any
posted starter that still fails to reach the pool is named with his DK ID.
Under `exclude`, the seeded rows are dropped and the blocker says how many.

After, same inputs: all eight posted starters in, exactly one bench bat filling
the ninth seat, status `posted_partial_plus_appg_fallback`.

What deliberately did NOT ship: F2 stamped from the posted slot. The confirmed
path stamps F2 from batting order; whether an incomplete lineup's slot earns
the same treatment is a strategy question for MLB_Classic.md, and answering it
inside a pool-membership fix is how a strategy change ships invisibly. Posted
seeds carry `batting_order=None`, exactly as the platoon path does.

### The rule, not just the fix

CLAUDE.md build-contract item 1 covered the confirmed nine and the TBD nine
only, so the partial side had no rule to be wrong against — which is why the
entry called the rule undefined rather than unimplemented. Item 1 now states
the partial case: the fill order, that a posted starter is never displaced,
that omissions are named, that `exclude` means excluded, and that F2 is out of
scope.

### The staleness gate followed

`platoon_dependent_teams` was derived from which teams the platoon reference
COVERS. Seeding makes that the wrong question: posted starters can take all
nine seats, and the covered-but-unused team would then drag a stale-reference
blocker onto a build whose nine were entirely posted. It now follows what the
projection actually SUPPLIED, which is the same reasoning item 1 already
applies to a fully pasted slate reading no reference at all. An excluded team
is removed from the list with its rows.

### Tests

Six in `tests.test_core.PartialSidePoolTests`, pin 570 → 576. Teeth verified
by disabling the seeding and the exclude-drop in place: four of the six fail,
the two that do not being the over-reach guards — a fully confirmed slate is
untouched, and a side that DOES lean on the projection still blocks on a
39-day-old reference. Both are supposed to pass either way; that is what makes
them guards.

One existing assertion moved rather than being deleted:
`IntakeTrustTests.test_partial_team_is_named_in_the_pool_report` asserted the
team status word `platoon` on a side where four seats were posted and five came
from the projection. It now asserts `posted_partial_plus_platoon` and the nine
count, which is the more truthful statement and the reason the word changed.

### Also in this commit

**R109 gained a dated note** that qualifies its own title: a fourth stale
`.git/index.lock` blocked this commit, and `rm` cleared it, because the
session already held Cowork's `allow_cowork_file_delete` for this folder. The
mount's unlink refusal is the default, not an absolute, and the grant lifts it
folder-wide for the session — so the remedy reorders to "ask for the grant,
`mv` only as fallback", and R109's residue sweep is no longer blocked on a
hand step. No code changed; the note is on the entry.

**R113 filed** in Workstream 4 from BUILD's 2026-08-12 fragment, and the
fragment consumed: the Showdown caution text reports `captain_lock_relaxed` as
if it were `captain_cap_relaxed`, on a MIL@SD build where the realized captain
maximum was 5 of 19 against a cap count of 6 and nothing about the cap was
relaxed. It joins the false-signal batch at Tier 1 item 4, whose reporting
surface it shares. Queue updated: R60 struck from Tier 1, R69 named its
successor and the head of the tier.

## 2026-08-12 — the what-next queue rebuilt as a six-tier development order: impact against lift, with waits-on-whom as the third axis (docs only)

Fourth DEV session of 2026-08-12, engine claim `engine_2026-08-12_order`, at
Ben's instruction: order the open board by impact against technical lift —
high-impact/low-lift first, high-lift items adjudicated individually,
high-lift/limited-impact deprioritized. No code, no tests, no pins moved.
Write set: `docs/2026-07-27_backlog_v2.md` (the what-next section only;
every workstream entry untouched), this entry. Gate before the edits:
`PASS  v2.26.0  26 modules  871 tests`.

### Method

Impact reads off the project's own hierarchy: pool and upload truth, then
evidence and grading substrate, then false signals that steer the operator
(the R51/R92 family, the board's most recurrent burn shape), then
lineup-quality controls, then operator time, then hygiene. Lift reads off
each entry's carried effort letter. The third axis is stated rather than
implied: an item waiting on measurement, Ben's data, a decision, or a hand
step outside Cowork holds no DEV slot whatever its score, so the old queue's
#1 and #3 (R37(2), R40) move to an explicit externally-gated section with
their gating facts intact rather than being ranked as if buildable.

### The order it produced

- **Tier 1** (S/XS, DEV-ready): R60 leads — intake truth at one session of
  lift — followed by R69 and R70 (same class), the false-signal batch
  (R112+R103+R99+R92+R71, one reporting surface, four burned builds since
  08-01), the swap-rails batch (R66+R68+R67), R36's F3m+F6m, the claim.py
  batch (R31(b)(c)+R110+R86), and R80(a)+R88 (key scrub, DK-wall test).
- **Tier 2**: R48+R83 then R10 — the grading substrate lands before the
  funded model so the model's result is a graded fact.
- **Tier 3** (the M-lift adjudications): R98(3)+(4)-tail first (high impact,
  loudness already landed, absorbs R112's deeper half), R81's armed design
  pass second (one S pass retires the wrong-slate family R70 patches
  pointwise), R36 Finding 10's floor + R84 third (truth defect at the money
  boundary, but its late-swap sizing is UNSIZED pending the owed
  re-measure).
- **Tier 4**: the decisions, mostly Ben's, each listed with what it unlocks —
  R41's two decisions foremost, since they unlock the board's one L build
  (Showdown certification, roughly a third of entered volume).
- **Tier 5**: prevention and hygiene, batched between tiers, never instead
  of them.
- **Tier 6**, deprioritized by name with the reason: R87 (M plus golden
  regen for throughput no measurement says we lack), R42(b), R9b, R12, R11,
  R58(c)(d), R61-tail. The do-not-build list is unchanged and is not a tier.

### One standing hold amended, deliberately

R36's F3m and F6m leave the trip-only pull rule for Tier 1. Both are P1/S,
both were verified on a real delivery record (a `certified` stamp with the
odds assumption invisible; a corrupt manifest reading as empty and then
being replaced away with its supersession history), and both are
recording-only fixes. Under the impact-lift lens Ben asked for, "wait until
a build trips it" was mis-pricing the manifest — the file that answers
"which file do I upload." The other six accepted findings (F8, F7, F12,
F1m, F14, F2) stay on their trip rule: F1m and F2 are M, F12 is a rare
path, F8 is bounded by Showdown's review-grade label, and F7's live-burn
path is already closed by R32's paste-primary rule.

### Why

The old queue answered "what is most valuable"; three of its four items were
waiting on someone other than a DEV session, so the practical answer every
session actually needed — what do I build tonight — took reading forty
entries. The tiers separate score from availability, keep every hold's
substance (R87's no-ride rule, R13's park, the trip rule for R36's
remainder), and put the deprioritizations on the record with reasons, so
pulling one costs a named measurement instead of a mood.

## 2026-08-12 — Gemini pair adjudicated: both rejected wholesale, zero adoptions; the PuLP premise dies a third time (docs only)

Third DEV session of 2026-08-12, engine claim `engine_2026-08-12_gemini`, at
Ben's request to give two more uploaded critiques the same treatment as the
GF third edition. No code, no tests, no pins moved. Write set:
`docs/2026-07-27_backlog_v2.md` (what-next note, do-not-build paragraph,
sources), `docs/2026-08-12_critique_gemini_spark.md` and
`docs/2026-08-12_critique_gemini_pro.md` (new, archived copies, sha256
`ced1581e…` and `f28640be…` matching the uploads byte for byte), this entry.
Gate at this tree before the edits: `PASS  v2.26.0  26 modules  871 tests`,
no debt warning. Three stale slate BEACONS from 2026-07-30/08-01 are still
HELD with no RELEASED marker (`slate_2026-07-30_1910_6g`,
`slate_2026-07-30_sealad_sd`, `slate_2026-08-01_2010_2g`); beacons never
block and a stale claim is Ben's to arbitrate, so they are reported and left
alone.

### What the two documents are

**Pro** (6,110 bytes) is a regeneration of
`docs/2026-08-01_critique_gemini.md` (6,972 bytes, rejected wholesale in the
R41/R42 entry for not reading the tree): same structure, same PuLP
microservice, same Playwright/Redis polling pipeline, same Stokastic-style
field sim, retitled from "Critical Flaws" to the GF spec's "Greenfield
Audit" section template. **Spark** (33,299 bytes) is the 07-25 CC program
re-argued: the iterative PuLP-CBC-loop premise, `bank_cache.parquet`, the
<25-line CLAUDE.md, the watcher daemon, and the Phase-3 play-by-play sim
plus duplicate-penalized field-ROI stack, now with sample code.

### Dispositions — rejected wholesale, with the checks that decided it

- **The shared premise is false, third time on the record.** Both diagnose
  (and Pro also PRESCRIBES) PuLP. `grep -ri pulp` over
  `mlb_engine tools tests skills` matches nothing; the only repo mentions
  are the do-not-build line that has said "the repo has never used PuLP"
  since 07-25 and the archived 08-01 Gemini critique.
  `scipy.optimize.milp` is CLAUDE.md's pinned authority.
- **Both cross the absolute walls; rejected categorically.** Pro polls
  "DraftKings endpoints every 60 seconds" and auto-uploads via headless
  browser with "No human review step"; Spark's Phase 3 ships a
  "Playwright / Claude in Chrome live slate watcher & auto-uploader."
  Scripted DK access and automated entry are the DK wall and the
  money-and-entry wall, and the GF third edition — adjudicated hours
  earlier — independently documents DraftKings' terms prohibiting exactly
  this (its F-01/F-28). Pro's "burn down the local CSV archive structure"
  would delete the append-only calibration substrate; even the GF spec's
  migration rule is "no historical input is deleted."
- **Spark's tree claims, checked.** `session_handoff.md` never existed (no
  file, no `git log --all` trace). Four of its proposals already exist at
  the exact paths it names as greenfield work:
  `mlb_engine/pipeline/build_state_manager.py`,
  `mlb_engine/optimize/bank_cache.py`, the deterministic
  `tools/preflight_upload.py`, and the swap-from-bank late path
  (`run_late_swap` + R101). Its Showdown finding names a slot DK MLB
  Showdown does not have (FLEX) and a string-keying defect the parser does
  not exhibit — `showdown.py:120-122` requires the DK integer ID at parse,
  and the underlying-player collapse is the repaired R45 work the GF third
  edition conceded the same day. Its Finding 4 mechanism (NaN merge →
  Statcast baseline keeps benched players in lineups) misnames the layer:
  the pool is gated at intake (confirmed nine + platoon nine; every other
  salary row absent, not excluded), `projection_builder.py`'s fillna sites
  are ceiling multipliers and flag coercions, and its proposed
  `'Expected'`-admitting mask is WEAKER than the shipped contract. The true
  kernel of the scratch concern is R60 — P1, queue position 4, filed
  2026-08-04 with a reproduction.
- **Spark's sample code un-ships the P0 gates.** Its export writes
  `portfolio.to_csv` with no reserved-Entry-ID mapping, no contest
  identity, no manifest, no certification; its "sub-10ms bank swap" is
  `bank.iloc[:len(portfolio)]`; its Phase-2 "portfolio selection" returns
  `candidate_pool.iloc[:num_lineups]`, which is not a solve. That is the
  R51/R52 false-clean family offered as the remedy.
- **Standing without new argument:** the sim/field-ROI/duplicate-penalty
  stack stays gated on R13/R10 per the do-not-build list;
  `bank_cache.parquet`, <25-line CLAUDE.md absolutism, and watcher daemons
  stay rejected on their 07-25/08-01 reasoning (Cowork's primitive is the
  scheduled task).
- **Convergences recorded as data points, not adoptions:** Spark's headless
  single-command build with atomic JSON state describes `build_slate.py` +
  `build_state_manager.py` as shipped (R63's direction), and both
  critiques' LLM-out-of-the-math rule restates CLAUDE.md's
  "optimizer_v3.py is the lineup source of truth."

### Why

Ben asked for the same treatment the GF third edition got, and these two
earned less: that document read the tree at HEAD and conceded findings when
its facts failed; this pair repeats premises the board falsified on 07-25
and 08-01 without checking either, and its only new content crosses walls
that are not open to argument. Zero adoptions. The record is the rejection
with its evidence, archived beside the prior editions, so the next
regeneration can be diffed against these copies the way today's GF edition
was diffed against 08-10's.

## 2026-08-12 — greenfield spec, third edition: adjudicated as a delta; five concessions recorded, F-35/A-43 rejected on standing grounds, one rider on R41 (docs only)

Second DEV session of 2026-08-12, engine claim `engine_2026-08-12_gf3`, at
Ben's request to adjudicate the re-dated root upload element by element and
adopt what is worth adopting. No code, no tests, no pins moved. Write set:
`docs/2026-07-27_backlog_v2.md` (what-next note, R41 rider, do-not-build
paragraph, sources), `docs/2026-08-12_critique_greenfield_spec.md` (new, the
archived copy, sha256 `ae3ac30e…` matching the root upload byte for byte),
`DFS_SYSTEM_GREENFIELD_SPEC.md` (Ben's root upload, committed as received),
this entry. Session-start gate before the edits:
`PASS  v2.26.0  26 modules  871 tests`, carrying one changelog-debt warning
that names 6c96474 — the ARCHIVE commit that added
`tools/fetch_fangraphs_platoon.py` without an entry, which is R107(a)'s open
adopt-or-delete and is reported here, not repaired. Untracked ARCHIVE
leavings (standings zips under `data/archive/`, one pulls html, one
reference `.bak`) sit outside this write set and were left alone.

### Method

The upload's review date is 2026-08-12 and its reviewed commit is 6c96474,
which is this HEAD — like the 08-10 edition, it read the actual current
tree, so every cite was checkable. It is the third edition of the document
adjudicated on 2026-08-01 (R41/R42 entry) and 2026-08-10 (R103–R106 entry),
so it was adjudicated as a DELTA: diff against the tracked 08-10 copy shows
78 sections against 76 (new: F-35, A-43), five findings rewritten to concede
prior rejections or landed repairs (F-02, F-05, F-16, F-20, F-21, plus
softenings in F-13, F-30, F-31), a new audit-method-and-module-disposition
front matter, and otherwise label renames around textually identical bodies.
Everything textually unchanged keeps its R103–R106 disposition without
re-argument; every NEW claim against this tree was verified in code before
ruling, per the R36 method.

### Dispositions

- **Concessions recorded, no action.** F-02 now grants the
  `Portfolio_EV_Proxy` label discipline it previously said was missing;
  F-05 grants the retirement banners are truthful; F-16 grants the
  `review_ready`/status repair (R105) and F-20 the paste identity repair
  (R45 batch); F-21 grants the PO/PLR policy (R104); F-13 grants the
  coverage floor; F-30 grants the current pins; F-31 grants that no scenario
  bank exists to leak and re-centers on the prospective ledger, which is
  R83 plus R10's persist-before-lock clause, both open on the board. The new
  method section labels the reviewer's runtime claims environment-limited
  (cold Windows 3.13, no scipy — the same concession the 08-10 adjudication
  extracted under F-27).
- **The bulk, standing.** F-01/F-03/F-04/F-06..F-15/F-17..F-19/F-22..F-34
  and A-01..A-42 are textually the prior edition; the R103–R106 map carries
  over unchanged, and the rebuild program (dfs_vnext, five planes,
  SQLite/WAL authority, persisted FSM, signed manifests, provider client,
  scenario/economics stack) stays rejected per the do-not-build list, gated
  on R13 and R10. F-33's supersession demand was answered 2026-08-10 and the
  answer stands.
- **F-35 (new): rejected, already on the board.** It cites this repo's own
  2026-08-11 incident (the sibling-claim restore that destroyed three
  uncommitted files) — recorded here first as R31(d), with R110 carrying the
  release-loop half and CLAUDE.md carrying the commit-early mitigation as of
  this morning's doc-truth pass. Its remedy (database leases, fencing
  tokens, read-only checkout during builds) is the rejected transactional
  program; making the mutex refuse a held sibling stays R31(d), Ben's call.
- **A-43 (new): rejected as the program's operating procedure.** Its one
  hard wall — the system never opens, logs into, pastes into, or submits to
  DraftKings — restates CLAUDE.md's money-and-entry wall. Its fourteen steps
  map onto existing mechanisms where they are sound (runs/ input snapshots,
  the approve gate, preflight, the T-schedule, the archival runbook), and
  onto rejected infrastructure everywhere else (inbox watcher, FSM,
  generation-numbered invalidation, DecisionPackage ceremony). "Budget
  normal critical-path LLM calls at zero" is R63's one-command direction.
- **F-20's rewritten residual: verified, adopted as a rider on R41.** The
  claim — `showdown.py` falls back from an empty `Starting` signal to an
  `all_healthy` pool — is true and is not silent: the fallback is documented
  in the docstring, stamps `Pool_Basis` on every row
  (`showdown.py:109-175`), is pinned by `test_showdown.py:111/141`, and
  reaches the checkpoint via `build_slate.py:1912/2069`. Honest at review
  grade, which is all Showdown ships. The binding point is certification,
  so R41 gains the rider: when Showdown comes under the gates, pool basis
  joins the certification evidence beside the relaxation counts, and an
  `all_healthy` pool can certify only as what it is.
- **F-12's new `--no-manifest` sentence: verified true and by design.** The
  flag is an explicit waiver that WARNS ("nothing on disk states this file
  is the one to upload", `preflight_upload.py:1212-1215`), and the
  unwaived default for a delivered file is a HARD FAILURE (R3(b),
  `:842-844`, `:1224-1227`). Missing, stale, and unreadable feeds warn
  loudly with the unchecked slots NAMED (`:1042`, `:1044-1050`,
  `:1092-1096`, `:1235-1237`) while a rostered player absent from a
  CONFIRMED lineup hard-fails (R4). That asymmetry is the ruled-on policy —
  absence of evidence is not a scratch, and hard-failing a missing feed
  would block legitimate pre-post uploads — so the standing F-12
  disposition holds unchanged.
- **F-14's `assume_gates` sentence: standing.** The hatch is the sanctioned,
  artifact-recorded escape from the F4 doctrine (gates are None when nothing
  checkable says otherwise, and None blocks), not a silent conversion;
  Finding 2/Finding 3 dispositions and R66/R68 cover the swap-side
  staleness.
- **Fact check on the new front matter.** 724 tracked files exact, 267
  archived standings CSVs exact, 6 test files exact; "56 production files"
  counts 60 by this session's find (definition-dependent), "19 slate dates"
  is 21 archive dirs today. The MANIFEST.md staleness claim remains true and
  remains filed (R76(a)). First edition of this document to substantially
  survive its own fact check.
- **R107(c) premise updated:** the root `DFS_SYSTEM_GREENFIELD_SPEC.md` now
  pairs byte-identical with `docs/2026-08-12_critique_greenfield_spec.md`
  rather than the 08-10 archive. Whether a root copy should exist at all
  stays inside R107(c), Ben's.

### Why

Ben asked for accept/reject/modify on every element and the backlog updated
with anything worth adopting. The third edition's value, like the second's,
is convergence rather than architecture: it concedes the facts the last
adjudication checked, its two new sections describe an incident and a wall
this repo recorded first, and its one verifiable new residual (F-20's
`all_healthy` fallback) was worth exactly one rider on the item that already
owns the decision it touches. The queue is unchanged: R37(2) waits on
ARCHIVE and slates, R10/R40/R60 hold their order, and no rebuild-program
work is funded while R13 is undecided.

## 2026-08-12 — doc-truth pass: the contract states its own write set, the mutex admits it is nominal, and two fragments become items

DEV, engine claim `engine_2026-08-12`, at Ben's request to review what the last
several sessions changed and update whatever went stale behind them. Write set:
`CLAUDE.md`, `docs/cowork_sync_protocol.md`, `docs/2026-07-27_backlog_v2.md`,
`.gitignore`, one comment in `tools/audit.py`, this entry. No behavior changed;
`PASS  v2.26.0  26 modules  871 tests` before and after.

### What was actually stale, and what was not

The pin line was current, which is worth saying because it usually is not: R96
moved it to 871 in the same commit that moved the constant, and the audit
prints exactly that. The staleness was elsewhere, in three places where a fact
had been learned in one session and written down in another session's file.

**CLAUDE.md's DEV write set omitted the two files DEV most owns.** It read
`mlb_engine/, tools/, tests/, docs/, skills/` while the same document, forty
lines up, says every DEV change carries a CHANGELOG entry and calls this file
part of the write set. The foreign-dirt rule is evaluated against that list, so
the list was licensing a session to treat another session's uncommitted
changelog edit as none of its business. Now stated, with the pointer that
`claim.py`'s own `WRITE_SETS` still omits `CHANGELOG.md` and
`requirements.lock` — R31(c), open, code rather than prose.

**The claims paragraph described a mutex that does not exist as described.**
"plain mkdir (atomic, fails when held)" is true only of the identical name, and
R31(d) has recorded since 2026-08-10 that `take engine_myslug` blocks nobody.
On 2026-08-11 that stopped being a design question: a second DEV session took
`engine_branchfix_2026-08-11` beside a held `engine_2026-08-11` and its
working-tree restore destroyed three uncommitted files in the first session's
write set. The contract now says the mutex is nominal, says to take the bare
resource name and glob `claims/<resource>*` before writing, and names the
mitigation that does not need Ben's decision: the blast radius is uncommitted
work, so commit early. Making `take` refuse a held sibling stays R31(d) and
stays his call, because it starts blocking sessions that today proceed.

**The sync protocol's write-back loop was documented in the form that broke
it.** It said to extract to the device VM's `$HOME` and then
`cat $STAGE/$f > $REPO/$f`. On 2026-08-11 `/sessions` hit 100%, the extraction
`mkdir` failed, and the loop truncated seven tracked files before discovering
there was nothing to copy, because `cat >` opens the destination before it
reads the source. All seven came back from HEAD and no uncommitted edit was
lost, this time. The step now extracts to the mount and guards each file on
`[ -s "$STAGE/$f" ]`. Two more limits landed in the same section: GitHub's
default branch is a stale `master` 43 commits behind `main`, so a plain clone
silently checks out the 2026-08-04 tree, and `sync_check.py` hardcodes `main`
at three sites and therefore answers about a branch the caller may not be on.

### R111 and R112 filed; R107 extended, part (b) landed

Two fragments had been sitting unconsumed in `docs/backlog_inbox/`, which is
the fragment protocol working right up until nobody merges. **R111** carries
the `sync_check` branch resolution and the `master` default, including the
warning that `_to_delete/r103.tar.gz` — a working implementation of the fix,
written in a container against HEAD `89ca350` — must not be applied wholesale,
because it predates R103-R110 and carries `EXPECTED_TEST_COUNT = 816` as a
literal that would undo R62's per-suite dict. **R112** carries the BUILD
finding from the 2026-08-11 1840_3g slate: at 6 entries the auto-bank reached
the allocator with 3-4 distinct SP pairs where the sliced bank reached it with
12, and the refusal then named `max_sp_pair_repetition` and
`max_pitcher_exposure_pct` on a slate whose own feasibility check had just
passed `pitcher_exposure_capacity` with 12 viable pairs. The scarcity was the
bank's and the message blamed a control, which is R98's ordering failing to
apply because the auto-bank had no growth left to offer. Same false-signal
family as R31 and R99: the operator relaxes a cap that did not need relaxing.

**R107** gained part (c) — `DFS_SYSTEM_GREENFIELD_SPEC.md` in the repo root is
byte-identical to the tracked `docs/2026-08-10_critique_greenfield_spec.md`,
verified by sha256, so it is a second copy of a document that already has a
home — and its part (b) landed: `_stage_repo*.tar.gz` is gitignored. Part (a),
adopt-or-delete for `tools/fetch_fangraphs_platoon.py`, is still Ben's and is
now a week old while the ledger Quick Card names the tool as the sanctioned
platoon-refresh path.

### R109's liveness check reported LIVE on a ten-hour-dead lock

Found by hitting it: `git add` in this session failed on a zero-byte
`.git/index.lock` and `HEAD.lock`, both stamped 09:43 that morning, which is
R109's third-and-fourth incident and the reason the remedy is written down. The
remedy's first step is `pgrep -f "git "`, and it reported a live git process.
It was reporting the calling shell: the sandbox runs each call as
`bash -c <command>`, so any `-f` pattern matches the command line containing
it, and the check that exists to stop a session from clearing a live lock can
never say no. Now `pgrep -x git`, with the reason stated so nobody reverts it
to the friendlier-looking form. The locks were then moved aside under a
timestamped suffix per the documented remedy and the commit went through.

### Two numbers this entry got wrong on the first pass

Both caught by a verification pass over the commit rather than by review of the
source fragments, which is where they came from. **"33 commits behind"** was
`43` at 11ffd55: the fragment's number was measured at `3d343a3` on 2026-08-08
and was eight commits stale by the time it was filed, and the fragment says
"roughly 33 hours" nine lines below it, which is probably the conflation. The
corrected text carries the as-of date, because that count grows every session
and a bare number will be wrong again next week. **"nine skip guards"** was
eight of nine: R62's audit-honesty half added four guards before the vendoring
half deleted the eight salary-file ones, and the ninth is a Showdown guard that
a tracked fixture already satisfies. Both numbers were repeated across files
before being checked, which is the argument for checking a borrowed figure at
the point it is copied rather than at the point it is written down.

### The ledger pin line, corrected off-changelog

Three DEV fragments in `ledger/inbox/` had asked for the same one-line fix
since 2026-08-10 and the newest was itself stale by the time it was written.
The Quick Card's macro line read `782` against a dict summing to 871, and it
cited `EXPECTED_TEST_COUNT`, which R62 demoted to a sum. Corrected on a bare
`ledger` claim, that line and nothing else, with the retired paste-suite
staging precondition recorded next to it and the four per-suite numbers
brought current. The ledger is untracked and its calibration content is
ARCHIVE's; this entry records the edit because a DEV session made it, not
because the ledger belongs here.

## 2026-08-11 — R96 closes: a delivery file has a manifest row or it says it does not

Same DEV session as the 2026-08-10 entries below, continued past midnight UTC on
engine claim `engine_2026-08-11`. The investigation there stopped on two decisions;
Ben made both and steps 2-4 landed. Audit pin 850 to 871 (`test_upload_integrity`
141 to 162), a `grew` verdict, which is the one case where moving a pin is right.

### R96(2)(3)(4). All six paths, closed by ordering rather than by another guard

**The shape of the fix.** Every delivery path already wrapped `record_delivery` in
a try/except so bookkeeping could never break a certified build. That is correct
and it stays. What was wrong is that the ARTIFACT stayed silent: the file landed
under its uploadable name with nothing on it saying the row was missing, so
ARCHIVE, `awaiting_standings`, and the next session all read a normal delivery.
R3(a) had already made the failure loud on stdout; a terminal line is not a
property of the file.

So the order changed instead of the guard. `upload_manifest.deliver` writes to
`DO_NOT_UPLOAD_<name>`, records the row naming the final path, then promotes the
name. A raising writer, a raising recorder, a crash between them, or a caller that
returns early all leave the DO_NOT_UPLOAD_ name. `record_delivery` grew
`hash_source` so the row can name the path the file is about to wear while hashing
the provisional bytes; a rename preserves bytes, so the hash is the same either
way. `showdown.write_showdown_entries` already staged under that exact prefix for
truncated writes, so this generalizes a pattern the tree had rather than inventing
one.

**Per path.** P1 `mirror_to_outputs` routes through `_deliver_mirror`. P2 late
swap writes provisionally BEFORE `promote_deferred_run`, which keeps R29(2)'s
invariant intact (something is in `outputs/` before the pointer moves) while making
the refusal self-labelling — that refusal returning 3 with an uploadable unrecorded
file was R29(2)'s predicted window and the one R96 was filed on. P3 the same
caller's promotion now sits INSIDE the try, so a raising recorder skips it. P4 the
Showdown path passes `promote=False` and promotes after recording. P5
`build_showdown_theses.py` is DELETED (Ben, 2026-08-11) in favour of
`run_showdown`, which is R31(e)'s own alternative remedy: it wrote a filled
DKEntries to an operator-chosen `--out` with no `record_delivery` anywhere in the
file, so it was unrecorded by construction, and it appeared in no test, eval or
doc. Nothing imports it. P6 `preserve_prior_slate` now calls
`rename_recorded_delivery`, so the row follows the rename instead of being orphaned
(Ben, 2026-08-11: refusing the rename was the alternative and was rejected, because
it would block a build mid-slate over bookkeeping and `preserve_prior_slate` fires
exactly when a second draftgroup is being built under time pressure). The sha256 is
deliberately not recomputed on a rename: rehashing would mask a file that changed
underneath.

**The reverse check (3), and what it found immediately.**
`upload_manifest.unrecorded_deliveries` plus `awaiting_standings`'
`scan_unrecorded_deliveries`, reported in the standings markdown and loudly on
stdout. Run against the live tree it names 11 files, which is R36's three from
2026-07-29 and R96's `DKEntries_1910_4g.csv` as expected, plus two nobody had
counted: `outputs/2026-08-05/DKEntries_showdown_1905_1g_sd.csv` and
`outputs/2026-08-09/DKEntries_1410_5g.csv`. A date with NO manifest file reports
nothing, deliberately — the manifest did not exist before 2026-07-25 and eleven
such dates are on disk, so listing them would put 23 permanent entries in a report
whose whole value is being normally empty. This project has already paid twice for
a warning the operator learns to scroll past (R31's STALE line, R3(a)'s print), and
an absent manifest is a different fact from a manifest that omits a file.

**Salary staging (4).** `stage_salary_for_delivery` runs on every recorded
delivery, writing `data/slates/<date>/DKSalaries_<tag>.csv` — tagged, because DK
runs several draftgroups a date and a bare name from one silently answers for
another. `build_slate` already staged; the engine mirror and the late-swap path
never did, which is why the 2026-08-06 1910_4g contests can only ever be
`standings_only`. That evidence is not recoverable; what this prevents is the next
one.

**Tests: 21, one per path, not one for the class.** The six paths differ in HOW
they reach the state, and a single test over the shared helper would pass while any
individual caller still wrote its file under an uploadable name — which is the
"makes the remaining path look closed" failure R96 warned about. Eleven behavioural
tests exercise the shared door (promotion only after the row, a raising recorder
leaving the self-labelled name, the row naming the upload path while hashing the
provisional file, a writer that produces nothing, tagged staging, the reverse check
including its two deliberate silences, and P6 both ways). Ten more pin each caller
at its own call site. Those ten read source, with the limitation stated in the
docstring rather than hidden: R79(b) already records that a source-text pin un-pins
itself under a helper-extraction refactor, so they assert routing, not behaviour,
and the behavioural half is the eleven above.

**One test amended, not deleted.** `test_late_swap_defers_and_promotes_only_after_the_mirror`
indexed `os.replace(tmp, dest)`, which no longer exists. It now indexes
`os.replace(tmp, provisional)` and its docstring says why: R29(2)'s invariant is
unchanged and is still what that test pins; which name the mirrored file wears is
R96's business and is pinned separately.

### Filed, not fixed

**R31(d) acquired a price, and R110 grew a part (b).** Both from one incident in
this session, both recorded on their existing entries rather than given new
numbers. While this session held `engine_2026-08-11`, a second DEV session took
`engine_branchfix_2026-08-11`; the scoped name means `mkdir` succeeded and the
mutex reported nothing, which is exactly the nominal-mutex defect R31(d) has
carried as an open decision since 2026-08-10. That session's working-tree restore
wiped three uncommitted edits from this one (`tests/test_core.py`, `tools/audit.py`,
`CLAUDE.md`). Recovery was cheap and the committed work was untouched, so nothing
is lost — but this is the first overlap that destroyed work rather than merely
failing to prevent contention, and it happened with both sessions inside the letter
of the contract. R31(d)'s note now says so; the decision is still Ben's, and the
question is better read as "what does an overlap cost" than "how likely is one".
Separately, `claim.py take` does not clear a stale `RELEASED` marker when
re-taking a released directory, so this session's legitimate release-then-retake
made `check` report a correctly-held claim as HELD-with-a-marker — R102's own
diagnostic firing on a false positive. Filed as R110(b), same one-line class as
R110(a).

**An environment condition, not an item.** `/sessions` (the mount holding the
repo) reached 100% with 844K free during this session. Tests were unaffected
because `TMPDIR=/tmp` sits on a different volume with headroom, which is the
R42(b) remedy working as intended, but writes to the mount itself are now at risk
and `rm` reclaims nothing there (R109's asymmetry). One transient symptom worth
recording because it looked alarming and was not: `skills/generate-lineups/SKILL.md`
read as 0 bytes for one command and was intact and byte-identical to HEAD
immediately after, which is consistent with the concurrent session's restore being
observed mid-write rather than with any corruption. Verified by sha256 against
HEAD, not assumed.

---

## 2026-08-10 — R62 closes, and R96's investigation stops the session rather than half-closing six paths

Third DEV session of 2026-08-10, engine claim `engine_2026-08-11`, scope "R96
delivery path + R62 vendoring". R62 completes and its entry migrates here. R96
does NOT: its step 1 is the investigation half by design, the investigation found
six paths where the entry's stop condition allowed two or three, so steps 2-4 did
not start and R96 stays on the board rewritten in place. Audit pin unchanged at
850 per-suite; the paste suite's count did not move because the coverage behind it
was what was missing, which is the whole point of R62(b).

### R62(c). The paste suite's fixtures are vendored, and the pin stops being satisfiable without the coverage

**What moved.** `data/slates/2026-07-29/DKSalaries.csv` and
`data/slates/2026-07-30/DKSalaries_1910_6g.csv` are vendored byte-identical to
`tests/fixtures/slates/DKSalaries_frozen_2026-07-29.csv` and
`DKSalaries_1910_6g_frozen_2026-07-30.csv` (28389 and 55855 bytes, md5
`f9cc3757…` and `cc660f55…`), on the `tests/fixtures/enrichment/` precedent.
`tests/test_paste_lineups.py` points its two constants at them and its nine skip
guards are DELETED, not repointed. `tools/audit.py` drops
`tests.test_paste_lineups` from `SUITE_PRECONDITIONS`, because the suite now has
no precondition beyond the checkout itself.

**Why the guards go rather than move.** A `skipUnless` on a tracked fixture lets a
genuinely missing one skip silently, which is the exact coverage debt R62(b) was
built to expose. Vendored and guarded is strictly worse than vendored. The
`TestDataDependenciesAreVendoredOrGuardedTests` meta-test still passes and is
unweakened: it walks `REPO / "data" / ...` paths, and these are no longer data
paths at all, so the guard requirement continues to bind every future
`data/slates/` reader.

**The number that justifies this, measured not assumed.** Replaying the
pre-change suite against absent salary files — the tracked-files-only condition,
simulated in `/tmp` so no real surface was touched — gives `Ran 75 ... OK
(skipped=62)`. Sixty-two of seventy-five tests asserted nothing while the total
matched `EXPECTED_SUITE_COUNTS` exactly. R62's own entry said 29; that figure
predated the five unguarded classes getting guards earlier the same day, which
converted five errors into thirty-three more silent skips. After the change the
same suite runs 75 with zero skips off tracked files alone. The pin never moved
in either direction, which is why a count alone could never have caught this.

**One test changed rather than deleted.** `AuditSkipHonestyTests.
test_skips_that_keep_the_count_are_still_reported` asserted that the paste
suite's `skipped_in_place` advice names `data/slates/2026-07-29`. That
precondition no longer exists, so the assertion is inverted — the advice must now
NOT name a gitignored slate — and the names-its-precondition coverage moves onto
`tests.test_golden_replay`, which still has one. Deleting the assertion would
have dropped the coverage along with the precondition.

**Sequencing note, retired.** The 2026-08-04 filing deferred this behind the
GitHub PAT because it sized the vendoring at ~2.4MB. That was wrong twice over,
as R62's rewritten entry recorded on 2026-08-10: the real cost is 84 KB in two
files. Nothing on the board waits on the PAT now.

### R96. Step 1 only: six paths, three classes, and a stop instead of a fix

**What moved.** Nothing in the engine. This is the investigation half, and the
finding is written into R96's entry in the backlog with the full table; the entry
stays open holding steps 2-4.

**What was found.** Into `outputs/<date>/` there are three write sites and one
rename site: `execution_pipeline.mirror_to_outputs` (:3479),
`late_swap.py` (:816-817), `showdown.write_showdown_entries` (:688, reached by
`build_slate.py:1958` and `build_showdown_theses.py:154`), and
`build_slate.preserve_prior_slate` (:420). They reach a filled DKEntries file
with no manifest row six ways, in three structural classes: the record raised and
was swallowed (P1 `mirror_to_outputs`, P3 `late_swap`, P4 Showdown — one helper
closes all three); control left the function between the write and the record (P2,
R29(2)'s predicted window, which that helper does not close); and the record is
never attempted or is orphaned afterwards (P5 `build_showdown_theses --out`, P6
the `preserve_prior_slate` rename).

**Why this stopped the session.** R96's own fix note says to stop past two or
three paths, because a partial fix makes the remaining path look closed. Six
qualifies, and the two uncounted paths are the ones that need decisions rather
than code: P5 is the script R31(e) already flags as fail-open and out of every
test, eval and doc, whose filed remedy is "gate it **or delete it in favor of
`run_showdown`**", and deleting a tracked script is not a DEV call; P6 is a policy
choice between updating an orphaned row and refusing the rename, which behave
differently for a BUILD mid-slate.

**Two facts the investigation added.** `tools/awaiting_standings.py` contains no
reference to the manifest at all, so step 3 is greenfield and the scanner today
enrolls contests off unrecorded files without saying they are unrecorded. And
`outputs/2026-08-06/` holds a sixth unrecorded file nobody had counted,
`DKEntries_showdown_2140_1g_sd_cptcap6.csv` (23792 bytes, sha256 `68ee815fcb57…`),
content-distinct from the recorded `…_2140_1g_sd.csv` (`8650744968c6…`). No
writer in the tree emits a `_cptcap6` name, so it arrived by operator copy or by
P5 — a real delivery file in the directory this item was filed from, from a path
that is not in the code.

**No new R-number for the delivery finding.** Every part of it belongs inside R96.

### Filed, not fixed

**R110 — `claim.py`'s own remediation advice is not a runnable command.** Found at
this session's claim release, then reproduced. `_claim_name` appends today's date
to whatever `release` is given, so the argument must be the BARE resource
(`release engine`). But `check` prints the DATED directory name, and
`_incomplete_note` (`tools/claim.py:141-144`) interpolates that dated name into
the command it tells the operator to run. Pasting it verbatim gives
`ERROR  no claim at claims/ledger_2026-08-09_r37_pin_2026-08-09_2026-08-11`, exit
3. That note is the fix R102 added so a hand-written RELEASED marker gets
completed properly — and it is the one instruction a session in that state will
copy. Seven claims sit HELD-with-a-RELEASED-marker right now, counted off
`claim.py check`, which is the shape of an operator who ran the advice, got exit
3, and wrote the marker by hand instead; they are all stale, so they are Ben's to
arbitrate and this session left them alone. The same asymmetry explains the doubled names
in `claims/`: `engine_2026-08-10_2026-08-10` is what `take` produces when it is
handed an already-dated name. Filed at XS in Workstream 6 next to R31, which is
the same tool's other reporting defect; whoever takes one should take both.

---

## 2026-08-10 — R62 (two halves of three) and R85: the gate stops lying about skips, and preflight reads the contest name

Second DEV session of 2026-08-10, engine claim `engine_2026-08-10`, scope
"R62 audit honesty + R85". R85 completes and its entry migrates here. R62 is
partial by design — the fixture vendoring was sequenced out of this session —
so its entry stays on the board, rewritten in place to hold only that
remainder. Audit pin 829 to 850, and the pin is now per-suite.

### R62(b). The audit could advise its own weakening, and did

**What moved.** `tools/audit.py` ran all five audited suites in ONE subprocess
and parsed one number out of the footer, `Ran N`. A shortfall was therefore
unattributable, and the tool's response to any shortfall on a green suite was
a single unconditional sentence: "the suite passed, so this is a stale pin.
Update EXPECTED_TEST_COUNT." It now runs each suite in its own subprocess
against its own pin (`EXPECTED_SUITE_COUNTS`, from which the total is
derived), parses `skipped=`, and classifies each suite into one of five
states. Only `grew` is called a stale pin. `shortfall`, `skipped_in_place` and
`absent` say LOST COVERAGE, name the suite, name the precondition to stage,
and say do not lower the pin. All four remain WARNINGS, so a live slate still
proceeds; a failing suite still blocks.

**Why.** The session-start gate is the project's evidence that the tree is
sound, and its advice could permanently remove coverage from it. The R101 dev
cycle reconfirmed this the same day from the other side of the mount: a
matched-dependency copy of the tree ran `Ran 783` against a pin of 792, the
nine missing were `tests.test_golden_replay` in full and silent, and the
audit said "stale pin". Following that advice once writes the golden replay
out of the gate for good, and nothing would ever say so.

**The measurement that shaped the fix.** Two unittest behaviours make a
shortfall unreadable without per-suite pins, both measured on 3.10 in a
scratch repro before any code changed, and both now recorded in
`parse_unittest_report`'s docstring. A class-level `skipUnless` keeps every
one of its tests in `Ran` AND adds them to `skipped`, so the count holds
while coverage drops. A `setUpClass` that raises SkipTest removes the whole
class from `Ran` and adds exactly ONE to `skipped` — so nine lost tests
report as "skipped=1", and `skipped` alone can never explain the gap. Parsing
`skipped=` was the filed fix and would not have been sufficient on its own.

**Two decisions worth stating.** First, one subprocess per suite rather than
one for all five. It costs four extra interpreter startups (~15s on top of
~155s) and buys a shortfall attributable to a named suite, a `skipped` count
that belongs to something, and numbers an operator reconciles by hand with
the exact command the audit ran; it also isolates the suites that assert on
process state, which R59 showed can pass under a combined run purely because
an earlier suite dirtied the interpreter. Second, the clean PASS line is
byte-identical to what it was, because CLAUDE.md's session-start step quotes
it exactly and a gate that changes its own green output trains the operator
to stop reading it. Skips, and a `{suite ran/pinned state}` breakdown for any
suite off its pin, print only when there is something to say; the full
per-suite record is always in the JSON output. The filing asked for per-suite
counts on the PASS line unconditionally, and this is a deliberate departure
from it. A test pins the clean line against CLAUDE.md's copy in both
directions.

**Also closed, one level up.** The audit filtered `AUDITED_SUITES` by file
existence, so a renamed or missing suite file ran zero tests, shrank the
total, and produced the stale-pin advice with nothing naming the missing
file. An absent suite is now its own named state.

### R62(a). Five test classes read gitignored data with no skip guard

**What moved.** `SinglePostedSideAlignmentTests`,
`LinkFreePitcherResolutionTests`, `DkStartingColumnTests` and
`AbsentFromDkPoolPolicyTests` in `tests/test_paste_lineups.py` read
`data/slates/2026-07-29/DKSalaries.csv` and
`data/slates/2026-07-30/DKSalaries_1910_6g.csv` — both gitignored — with no
guard, so a tracked-files-only checkout ERRORED on them rather than skipping.
They now carry `skipUnless` guards naming the files. Guards do not change the
count: a class-level skip keeps its tests in `Ran`, which is why the pin moved
only for tests actually added.

**The part that holds.** Fixing four classes once does not hold; the fifth
gets written next month. `TestDataDependenciesAreVendoredOrGuardedTests` walks
every file in `tests/` with `ast`, finds module-level constants and inline
expressions rooted at `REPO`/`REPO_ROOT` that point under `data/`, and fails
unless each is vendored (git tracks it) or guarded (a skip decorator names the
constant, or the class raises SkipTest from setUp/setUpClass), naming
file:line:class:constant. It also asserts it inspected more than a handful of
references, because R51's class — a walk that passes by finding nothing — is
the way this test would rot. Mutation-checked by hand: removing one guard
reddens it with the right file, line and class named.

**What the walk corrected in the filing.** R62 named
`test_upload_integrity.py:617` as an unguarded site; at those line numbers
today there is no data dependency, and the walk finds none anywhere in that
suite. It also named `data/slates/2026-07-25` and `data/archive/2026-06-03` as
part of the load-bearing gitignored set. Neither is: no test references
2026-07-25 any more, and all seven files under `data/archive/2026-06-03/` are
TRACKED and have been since the golden replay was written. The golden replay's
inputs were never the gitignored half — its disappearance on 2026-08-10 was a
partial copy of the tree through the tarball bridge. The deferred vendoring is
therefore two files totalling 84 KB, not ~2.4MB, which is recorded on the
rewritten backlog entry because it undercuts that entry's own reason for
sequencing behind the GH PAT.

**Not done here, deliberately.** The fixture vendoring itself. Ben scoped it
out of this session; it stays on the board as the whole of R62.

### R85. Preflight reads the contest name and refuses a file pointed at the wrong family

**What moved.** `tools/preflight_upload.py` gains `check_contest_identity`,
running before row shape. Every entry row's Contest Name is read for the
Showdown token and compared against the header geometry. Two hard failures:
all entries naming one family while the header says the other, and entries
naming BOTH families in one file, which no single upload can satisfy and
which means two draftgroups have been mixed. `data/reference/dk_contest_archetypes.csv`
is joined for the archetype and objective class, reported as evidence; a
contest name matching no pinned pattern warns and never fails.

**Why.** A Showdown-geometry file whose entries belong to Classic contests
passed every hard check, because nothing read the Contest Name column —
geometry came off the header, legality off the roster, and the manifest
cross-check only fires when a manifest resolves, which is exactly the state
R96 records as able to go missing. The name is DK's own statement of what the
contest is, it sits in column 2 of every row, and it was free to read.

**Measured before it was allowed to fail anything.** Across all 871 entry rows
in the repo's archived DKEntries exports, slate files and fixtures: 446
classic-geometry rows, none carrying the Showdown token or a single-game
"(A @ B)" suffix; 425 showdown-geometry rows, every one carrying the token.
The separation is total in both directions, which is what makes the token's
ABSENCE evidence rather than silence and justifies failing in both directions
rather than one. If DK ever ships a Showdown contest without the token this
reads classic and fails; `--force` (exit 4) is the operator's way past it,
because preflight is never allowed to be the reason a slate is not entered.

**The archetype table is not the geometry signal, and the filing implied it
was.** Its patterns are objective families — Jukebox, Satellite, Double Up —
and every one of them ships in BOTH geometries; "MLB Showdown $20 Quarter
Jukebox (CHC @ STL)" and "MLB $30 Quarter Jukebox" are both real and both
archived here. So the CSV supplies the archetype join and the
is-this-a-recognized-family signal, and the geometry discriminator is the
name's own token. Stated in the code rather than left for the next reader to
rediscover.

**One duplication, guarded rather than hoped for.** Preflight cannot import
the engine, so `ARCHETYPE_TYPE_PRECEDENCE` is a second copy of
`dk_entries_manager`'s table. Longest-pattern-wins was the obvious rule and is
wrong: it resolves "Satellite to $2 MLB Pocket Cup MEGA Qualifier" on "Pocket
Cup", turning a ticket_line contest into a generic GPP — the engine had
already found and fixed exactly this, so preflight mirrors its ranking instead
of inventing a second one. Two implementations of one rule is this project's
named no-op failure class (R79(d)), so a test pins the copies equal and
cross-checks both resolvers against real archived contest names, and another
test pins the misrouting that motivates the table.

### Filed, not fixed

**R109 — `.git/index.lock` goes stale on this mount and `rm` cannot clear it.**
Three incidents that had never carried a number: 2026-07-28, 2026-07-29 (both
sitting in this file's imported record as incident narrative) and 2026-08-10,
where `rm` returned "Operation not permitted" and `mv` worked. The mount
grants create and truncate but not unlink, so git's own documented remedy is
the one operation that fails, and the improvised workarounds have accumulated
into eight residue files in `.git/` — `index.lock.bak`, `.stale`, `.stale2`,
`.stale3`, `HEAD.lock`, `deadlock_*`, `tmp_probe_dead` — each a previous
session's fixed-name attempt that the next session's identical attempt then
collided with. The remedy is now written into
`docs/cowork_sync_protocol.md` under "Known limits": confirm the lock is dead,
then `mv` it aside under a TIMESTAMPED suffix, and check `HEAD.lock` the same
way. Two more faces of the same asymmetry were hit while landing R62 and are
recorded on the entry: `rm -rf` on `__pycache__` reclaimed nothing, and `cp`
over an existing file returned "Invalid argument" mid-mutation-check, leaving
a test file mutated until `cat > file` restored it (sha256 verified).

**One live environment condition, no item.** The sandbox volume holding
`TMPDIR` reached 100% (196 KB free) mid-session, which fails every test that
builds a throwaway git repo — six of `ChangelogDebtTests` — and cannot be
reclaimed, because `rm` on this mount refuses. Two consecutive `test_core`
runs disagreed on their error count, which is what surfaced it. Running with
`TMPDIR=/tmp` (a different volume, 2.9 GB free) is clean and is how this
session's verification ran. That is R42(b)'s named scenario arriving live
again, with R109's asymmetry underneath it.

### Verification

Suite counts reconciled by suite, not just in total, because this session
edited the counting machinery. By hand and through the audit's own per-suite
code path, both with `PYTHONHASHSEED=0`: core 570, showdown 55, upload 141,
golden 9, paste 75, total 850 against a pinned 850, zero skips, every suite
`clean`. `terse_output` returns `PASS  v2.26.0  26 modules  850 tests`, which
is the line CLAUDE.md quotes, pinned in both directions by test. CLAUDE.md's
session-start step is updated for the per-suite pin and the state vocabulary.
R108 was deliberately excluded from this session: it moves the module count,
and the counting machinery is what changed here.

## 2026-08-10 — R104, R45, R105, R54: the Workstream 1 Showdown batch

Queue position 1, four entries in one session, migrated here from
`docs/2026-07-27_backlog_v2.md`. Write set: `mlb_engine/intake/`,
`mlb_engine/optimize/`, `tools/preflight_upload.py`, `tools/audit.py`,
`tests/`, `skills/generate-lineups/`, `CLAUDE.md`, `ledger/inbox/`, this entry.
Audit `PASS  v2.26.0  26 modules` before and after; the pin moved 810 -> 829.
Showdown stays REVIEW-GRADE throughout: none of this brings it under the three
gates, which is R41 and remains open and decision-first.

### R104. DK `Starting` token policy: PO is never startable, PLR is surfaced

DK's `Starting` column was parsed in two modules with two token sets and two
meanings, and both readings were wrong in the same direction.

- **PO is now barred from pitcher slots outright.** F17 routed a probable
  opener to `viable_bulk_or_alt_sp`, which took him out of
  `REQUIRED_SP_AUDIT_STATUSES` but left him ROSTERABLE:
  `ALLOWED_PITCHER_ROLES`, `OPTIONAL_SP_AUDIT_STATUSES` and
  `ALLOWED_PITCHER_ROLES_FOR_GATE` all hold that role, so the optimizer could
  put a one-or-two-inning arm in a P slot priced on a starter's workload and
  the build certified with nothing downstream flagging it. The asymmetry
  decides it: excluding an opener costs an option, rostering one costs a P slot
  on a certified build. He now carries `BARRED_OPENER_ROLE`
  (`'declared_opener'`), which is in no allowed-role set anywhere, and is
  absent from the projection frame — "absent, not excluded", the pool
  contract's own words.
- **The barred role never enters `pitcher_roles`.** That mapping's three
  consumers all read it as "the arms that may be rostered"; putting a barred
  arm there would fail the pitcher-audit gate on every slate carrying an
  opener. Barred arms ride the pool report's new `non_rosterable_arms`
  instead, so the arm stays visible without being legal, and a side whose only
  declared arm was an opener gets a blocker that NAMES him rather than the
  generic "no probable or declared starter", which reads as a feed gap.
- **`viable_bulk_or_alt_sp` survives; PO stopped producing it.** That is the
  answer to the entry's open question. The role is now reachable only by
  explicit operator declaration, which is what it always meant.
- **PLR is surfaced, never auto-resolved.** `live_data_adapters` documented PLR
  as "DK's generic listed-player tag [carrying] no role claim", which is false
  — it is a projected long reliever, and `showdown.py` documented it correctly
  in the same repo. Because Classic intake attached no meaning to it, a PLR arm
  who was not also the feed probable never entered the pool at all: DET Ty
  Madden, `Starting=PLR`, $5,800, DK 43755567, outside the 2026-08-05 pool
  while DK's own ID allocation put him inside the declared-starter block.
  Intake now emits one named blocker per such arm, tiered SOFT by
  `build_slate.py`, because it is a decision the operator owes and not a
  statement that the pool is of the wrong slate. Confirming the role is a web
  search, which is non-deterministic and must not live inside a replayable
  build, so the engine surfaces and stops.
- **`build_slate.py --declare-pitcher <id>[=<role>]`, repeatable.** The engine
  has accepted `declared_pitchers` since the pool contract was written; only
  the CLI surface was missing, so the operator's answer had no way to reach the
  build. Bare `<id>` means `declared_probable_sp`. It is the documented way
  past the PO bar as well, and the brief records the declaration verbatim next
  to `non_rosterable_arms`, so the decision is a recorded input rather than a
  hidden fetch.
- **Showdown: PO is no longer a declared starter.** `showdown.py`'s
  `_is_declared` and `Is_Declared_Starter` returned True for PO, so on a
  `declared_starters` basis an opener was a declared starter outright. He stays
  ROSTERABLE in Showdown, where every slot is a UTIL slot and none is priced on
  a starter's workload; he is simply not declared. A new `Is_Declared_Opener`
  column keeps the reason visible instead of leaving a bare False.
- **Not done, filed as R108:** consolidating the token vocabulary into one
  module, the `mlb_engine.team_codes` treatment the entry's scope note asks
  for. It adds a module mid-batch and the proportionate interim is the one this
  repo already uses for preflight's mirrored status set: named constants on
  both sides, pinned in sync by test. The GF spec's F-21 typed-role apparatus
  stays rejected; the policy fix needed none of it.

### R45. `lineups_from_paste.py` resolves a Showdown salary file

Two independent breaks on one file shape, neither of them a name-matching bug,
and `test_paste_lineups` covered Classic only so nothing caught either.

- **Position column.** `POSITION_FIELD_CANDIDATES` is Roster-Position-first
  deliberately, which is right for Classic and exactly wrong for Showdown,
  where that column holds CPT/UTIL. `parse_positions('CPT')` matches neither
  the pitcher aliases nor the hitter slots, so every player came out with an
  empty `positions` tuple, the pitcher index was empty for everyone, and both
  probables were reported as `unrostered_starters` while DK's own `Starting`
  column named them. New `_showdown_aware_position_column` prefers `Position`
  only when `Roster Position` is ENTIRELY roster slots — a branch, not a
  reorder, because a reorder breaks Classic.
- **Identity dedupe.** Every Showdown player has two salary rows, CPT and UTIL,
  identical name and team, and `_resolve_one`'s ambiguity check counted them as
  two people, so a fully-confirmed zero-ambiguity paste came back "matches 2
  salary rows" on every hitter and was refused. `_dedupe_by_dk_identity` now
  collapses candidates by EXACT normalized full name before the count, keeping
  the UTIL row. The exactness is the safety property: two roster variants of
  one person collapse, while Will Wilson and Weston Wilson — the real ambiguity
  this module exists for, hit on the first live paste — do not, and still
  block.
- **Elevated to P1 on the recurrence record.** Three live burns in six days:
  SD@ARI 2026-08-03, STL@NYY 2026-08-05 (16 blockers), HOU@SD 2026-08-09 (18
  blockers), each ending with a hand-written feed at roughly T-18 and no
  provenance line, on the intake R32 calls the PRIMARY source. Pool
  construction was never affected, which is why the original filing was P2, but
  a primary intake that fails an entire contest family is a contract violation
  and not a degraded enrichment.
- **The test the entry asked for.** A new class runs against the real 188-row
  `DKSalaries_showdown_MIN_CHC.csv` fixture with the paste built FROM it so the
  two cannot drift, and pins the ambiguity that must still block. The spec's
  F-20 `UnderlyingPlayer`/`RosterVariant` type system stays rejected: identity
  dedupe plus a fixture test was the whole job.

### R105. The Showdown manifest records a status, not the preflight verdict

`stamp_manifest_status` wrote preflight's VERDICT straight into the record's
`status`. R34 had grown the verdict vocabulary a fifth value, `review_ready`,
without the manifest growing one, so every CLEAN Showdown delivery stamped a
status outside `STATUS_VALUES` and the next read hard-failed. Two writers of
one field disagreeing about its allowed values is the condition
`contest_shapes.py` exists to prevent for shapes; the behavioral cost is worse
than the bookkeeping one, because a red FAIL on every clean Showdown export
trains the operator to ignore the FAIL that is someday real.

- New `status_for_verdict` maps the verdict into the closed set —
  `review_ready` becomes `candidate`, because a review-grade file is a
  candidate and a byte checker must not promote it past that — and the mapped
  value is asserted against `STATUS_VALUES` before the write. The verdict is
  not lost: it was already recorded beside the status under
  `preflight.verdict`, which is where it belongs. `manifest_status_stamped` now
  reports the STATUS that landed rather than the verdict that produced it,
  which is what made the divergence invisible.
- `build_slate.py`'s own Showdown export path was already correct and writes
  `candidate` (R34); the defect was entirely on the preflight side, which is
  worth stating because the entry located it at the build.
- **The exit-code discrepancy is settled.** The two BUILD fragments disagreed
  (08-05 reported 2, 08-06 reported 3). Measured 2026-08-10: the vocabulary
  failure is exit **2** on both `preflight_upload.py` and `verify_export.py`,
  and it is pinned by test. Exit 3 in `verify_export` is the setup path — an
  unreadable file or no resolvable salary — reached before any check runs, so
  the 08-06 report was a different failure.
- Adjacent and deliberately not merged: R34-tail (the three
  `status: upload_ready` Showdown records from 07-29) and R96 (unmanifested
  deliveries). The spec's F-16 four-enum apparatus stays rejected.

### R54. Showdown counted-relaxation honesty, all four parts

The Showdown contract is explicit — every relaxation counted, clean means zero
— and three of these made the counts lie while the fourth manufactured a
blank-row blocker at the worst minute.

- **(a) The uncounted overlap drop.** `build_showdown_bank`'s captain-relax
  rung re-solved without `max_shared_players` as well as without the captain
  cap, while incrementing only the captain counter. Reproduced 2026-08-10 on a
  purpose-built pool: old code delivered max pairwise overlap 5-of-6 reporting
  `overlap_relaxed_slots: 0`; the bound is passed through now and the same
  solve delivers overlap 4 with the counter honestly at 0.
- **(a) The fourth rung.** Both bounds dropped at once now exists, is counted,
  and is counted in EVERY place it is true: `overlap_relaxed_slots` and
  `relaxed_slots` answer "how many lineups were built without this control",
  not "which rung fired", and `both_relaxed_slots` is the subset that dropped
  both. Clean is all three at zero.
- **(b) The thesis ladder had three rungs where the bank ladder had four**, so
  a thesis solvable only under both relaxations returned None and left a blank
  reserved row — write-blocked at T-5 — on a pool the bank path fills. Two
  ladders over one solver disagreeing about how far they will bend is the same
  defect class as two readers of one token set. `solve_ladder` gains the fourth
  rung and the matching counters.
- **(c) Silently ignored locks.** A lock naming a key the melted pool does not
  carry — a typo, a stale key, a player the melt dropped on Status — used to
  no-op in total silence: the whole bank built without the player and the
  ladder's `cpt_counts` accounted against captains that were never enforced.
  `build_showdown_lineup` returns `ignored_locks`, both ladders aggregate it,
  and the brief prints it as the loudest of the four notes, because it is not a
  relaxation the solver chose — it is an instruction that did not arrive.
  Reported rather than raised: a lock that lost its player at T-5 must not be
  the reason there is no file.
- **(d) One OUT vocabulary.** The melt shelved IL/O/OUT/NA while preflight also
  shelved IL10/IL15/IL60/PUP/SUSP, so an IL60 player built into the bank and
  died at preflight. `showdown.OUT_STATUSES` now mirrors preflight's set and is
  pinned in sync by test — a mirror rather than a shared import, because
  preflight's "no engine import" contract is what makes it run when the engine
  does not, which is exactly the state in which a pre-upload check matters
  most.
- **The brief gains a `counted_relaxations` block** carrying all three counts,
  `ignored_locks`, and a single `clean` boolean. A portfolio is not clean
  because the gates passed; it is clean when these are zero.
- **The test gap was structural and is closed.** `test_showdown.py` asserted
  that the counter KEYS existed, so deleting both `+= 1` lines stayed green
  (R79c). The new assertions are biconditionals between the counters and the
  delivered bank, so they fail in both directions: a counter that under-counts
  a real relaxation and one that claims a relaxation that did not happen. The
  pre-fix code was run against them and fails, which is recorded here because
  a teeth claim nobody executed is a guess.

### Also

- `EXPECTED_TEST_COUNT` 810 -> 829 (core 559, showdown 55, upload 131, golden
  9, paste 75). `CLAUDE.md` session-start step 2 and
  `skills/generate-lineups/SKILL.md` corrected to match in this commit; the
  ledger Quick Card is ARCHIVE's, so it gets a fragment.
- Fixed in passing, unnumbered: the Showdown brief's overlap NOTE was a plain
  string inside an f-string concatenation, so it printed a literal
  `{share_cap}` rather than the bound.

## 2026-08-10 — R107 filed; the backlog reorganized by workstream; next-session prompts rewritten (docs only)

No code, no tests, no pins moved. Write set: `docs/2026-07-27_backlog_v2.md`,
`docs/next_session_prompts.md`, this entry. Second docs commit of the date,
at Ben's instruction: "update the backlog with any items and reorganize them
so it's in a logical order for the development," with the session prompts
carrying the backlog/changelog contract explicitly.

### Changed

- **The backlog's open board is now organized by workstream, entries
  verbatim.** The old layout accreted by filing date (Section 1, Section 2,
  then four dated "additions" tranches), so related open work was scattered:
  the four Showdown items sat in three different sections, and the solver
  family in four. The new layout after the unchanged what-next queue: seven
  workstreams (Showdown correctness and certification; strategy controls and
  their evidence; intake and pool truth; solver/allocator/swap/brief truth;
  delivery/manifest/preflight evidence; infrastructure, tests, environment,
  coordination, docs; archival and ledger tooling), then closed number
  stubs, open tails and awaiting-Ben, do-not-build, and a new "Board
  history" section holding the amendment record and the original dated
  tranche introductions verbatim. Mechanics worth recording: the move was
  performed by a script that treated every `### R` entry as an atomic block
  and REFUSED to write unless all 55 open-entry bodies survived
  byte-identically with none lost or duplicated — wording, priorities,
  dates, and provenance lines are untouched, and each entry's header still
  names when and where it was filed. The old opportunistic-tier paragraph is
  replaced by pull rules that preserve every standing hold (R36 findings
  slot in when tripped; R85 rides the Showdown batch; R87 holds for the
  golden regen; R81 is armed; R13 stays parked on 3.14; R31 carries R86).
  Nothing parses the backlog programmatically (verified by grep across
  tools/, mlb_engine/, tests/, skills/ before restructuring), and CLAUDE.md's
  pointer to the file and to "What do we tackle next" is unchanged.
- **Filed R107** (P2, XS-S): untracked residue on DEV surfaces.
  `tools/fetch_fangraphs_platoon.py` has been untracked since 2026-08-05
  while the Quick Card names it as the sanctioned platoon-refresh path, and
  `_stage_repo.tar.gz` sits in the repo root from the sync tarball bridge.
  Adopt-or-delete is Ben's call for the tool (adopting is an engine-claim
  change with VERSION and audit pin, not a drive-by `git add`); the tarball
  gets a gitignore pattern or a bridge cleanup step. Both are session-start
  noise that trains the foreign-dirt check to be skimmed.
- **`docs/next_session_prompts.md` rewritten.** The stale ARCHIVE prompt
  from 2026-07-31 (its pending-work list had been done for a week) is
  replaced by three prompts matched to the queue: Prompt A, DEV, the
  Showdown batch (R104 + R45 + R105 + R54, R85 as the named rider); Prompt
  B, ARCHIVE, executing Ben's 2026-08-09 curated-archetypes decision plus
  the Quick Card pin merge and an inbox sweep; Prompt C, DEV, R10 under its
  decided scope and grading bar. Per Ben's instruction, every DEV prompt
  carries the closing contract in the prompt text itself: completed entries
  MIGRATE from the backlog to this file in the completing commit, the
  changelog entry rides the same commit, the queue is updated, and the next
  free R-number comes from scanning both files. The ARCHIVE prompt carries
  the role-correct version: ledger in place, fragments for DEV surfaces,
  never the backlog or changelog directly. A standing rule is written into
  the file header: when a prompt and the backlog disagree, the backlog wins.
- **One defect of this date's earlier commit corrected and disclosed:** the
  R104–R106 section insert consumed the `# Do not build (updated)` header
  line without restoring it, so the do-not-build body read as part of the
  new section in 07a33c6. The reorganization script's anchor check caught
  it; the header is restored. Cheap lesson in the R91 spirit: a structural
  edit that a verifier would have caught in one grep shipped without one,
  and the fix arrived only because the next tool refused to parse the
  result.

### Why

A board organized by filing date answers "when was this found"; a DEV
session asks "what do I touch tonight." The queue already answered that for
the next session; the workstreams answer it for every session after, and the
prompts make the backlog/changelog migration contract impossible to miss at
the exact moment it applies.

## 2026-08-10 — R103–R106: adjudication of the greenfield spec revision; six fragments merged; the R102 collision corrected (docs only)

No code, no tests, no pins moved. Write set: `docs/2026-07-27_backlog_v2.md`,
`docs/2026-08-10_critique_greenfield_spec.md` (new, the archived copy of Ben's
root upload `DFS_SYSTEM_GREENFIELD_SPEC.md`, which stays his), seven consumed
`docs/backlog_inbox/` fragments deleted, and this entry.

### Changed

- **Adjudicated the 2026-08-10 revision of the greenfield spec** (34 flaws
  F-01..F-34, 42 architecture items A-01..A-42) against the tree at 89ca350,
  which is this HEAD — the spec read the current tree, so every line cite was
  checkable, per the R36 method. It is a revision of the 2026-08-01 spec
  disposed in the R41/R42 entry; the disposition map:
  - **Already on the board, no new item (the bulk):** F-09 = R36 Finding 10
    (+ R101's landed upstream half and the owed re-measure); F-11 = Finding 3
    + Finding 21's design pass; F-12 = Finding 1 as modified (R34's verdict
    mechanism, UNKNOWN routing, minutes-to-lock staleness policy); F-13 =
    Finding 7 + the exactly-50% boundary test; F-14 = Finding 2 (+ R66/R68);
    F-15 = Finding 6 as modified (+ corrupt-is-not-empty, salary_sha256,
    append-only records); F-17 = R81 (armed) + R85; F-18 = R41 (decision
    first, through the EXISTING three gates); F-19's relaxation-integrity
    half = R54 (reproduced); F-24 = R9a landed / R9b open, absolutism stays
    rejected; F-25/F-26 = R63's one-command door + R12's loop state, daemons
    stay rejected; F-27 = R42(b) + R78 + R62 (the reviewer's own cold Windows
    run is an environment-limited result, as it concedes); F-28 = the DK wall
    + R88; F-29 = rejected engine, accepted slivers already filed; F-30 =
    Finding 14 + R62 + R79 + R91, and its MANIFEST.md claim is true and
    already filed as R76(a); F-31 = premature, no sim exists to leak; F-32 =
    R13, parked on Ben's own promo-channel call; F-34 = rejected 2026-08-01,
    threat model unchanged. Architecture: A-04≈R81, A-07's ladder≈the
    T-schedule + counted relaxations + `time_limited` tagging, A-10≈runs/
    input snapshots + R49 + the R81 fingerprint, A-26≈`run_late_swap`'s
    frozen-slot contract, A-27≈R63/R98's refusal-with-brief shape, A-28≈
    preflight/verify_export (no engine import, no network) + R91 mutation
    tests, A-32≈R9b, A-33≈R12's stop rule, A-36≈R84 + briefs, A-37≈R88,
    A-38≈R62/R79/R90/R91, A-39≈R10's grading bar + R13's ledger target.
  - **Rejected on re-verified facts:** F-05 ("phantom" `slate_sim.py` /
    `calibration_engine.py` / post-slate evaluator) — MLB_Classic.md banners
    all three "Retired as of v2.20.0 and not present in this repo" at lines
    520/547/563; the doc is truthful and the residual (retired prose weight)
    is R9b's split. F-02's premise — `contest_allocator.py:35-36` already
    says verbatim "All scores are deterministic review/selection proxies. Do
    not label them ROI, profitability, win rate, cash rate..."; the label
    discipline the spec demands as its fix is the shipped posture, and the
    honest-label closing sentence of the spec's A-42 restates CLAUDE.md's own
    truthful-labels section back at it.
  - **Rejected unchanged, no new evidence since 2026-08-01:** the greenfield
    program itself (A-02/A-03/A-05/A-06/A-40/A-41/A-42 — the `dfs_vnext`
    package, fifteen epics, SQLite/WAL authority, persisted FSM, signed
    manifests A-30, CP-SAT benchmarking A-21, evidence-policy resolver A-08,
    provider client A-09, event-driven refresh A-31, latency SLOs A-34, cost
    instrumentation A-35) and the economics stack it feeds (F-07/F-10,
    A-12..A-20, A-22/A-23/A-25's clustering half), all gated behind R13 and
    R10 per the do-not-build list, which gains a dated 2026-08-10 paragraph
    stating this and answering F-33's demand to supersede the anti-goals:
    DEV recommends no, because the gate funds the EV prerequisites (archive
    integrity, R10's graded satellite prior, R48, curated contest truth)
    while refusing the infrastructure until the stakes decision makes it
    rational. Noted for the record: A-25's Showdown "defaults" (captain
    ≤ floor(0.33·n), overlap ≤ 4) are the currently shipped values.
  - **Accepted where the tree and the fragments confirm it:** F-21 → R104,
    F-16 → R105, F-20 → the R45 elevation. In all three cases the BUILD
    fragments predate the spec and carry the sharper evidence.
- **Filed R104** (P1, S-M): DK `Starting` token policy — PO is rosterable in
  Classic (`viable_bulk_or_alt_sp`, `live_data_adapters.py:1073-1074`) and a
  declared starter in Showdown (`showdown.py:136,150`) against Ben's stated
  2026-08-05 policy, and Classic intake documents PLR falsely as "no role
  claim" (`live_data_adapters.py:78-79`) so a PLR arm never enters the pool
  (live case: DET Ty Madden, 2026-08-05). Fix shape per the fragment: PO
  barred deterministically via a new non-rosterable role; PLR surfaced as a
  named soft blocker with a new `--declare-pitcher` CLI flag reaching the
  `declared_pitchers` mapping the engine already accepts, so the web-search
  confirm step stays an operator act recorded in the brief, never a hidden
  fetch inside a replayable build.
- **Filed R105** (P1, S): the Showdown export path stamps the manifest status
  from preflight's verdict string (`review_ready`,
  `preflight_upload.py:1078`), which is outside `upload_manifest.py:36`'s
  closed vocabulary, so every clean Showdown delivery fails `verify_export`
  red (burned 2026-08-05 and 2026-08-06) and supersession cannot be reasoned
  about for Showdown. Fix: the manifest writes `candidate`; verdict and
  status stay separate facts; pinned by test.
- **Filed R106** (P2, S): `--postures` cannot express `ticket_count`, so the
  operator's deciding fact could not reach `resolve_contest_shape` on
  2026-08-08 and a per-slate driver script was the workaround. Fix: JSON
  form or `--postures-file`. The fragment's second half (minimum-feasible
  relaxation hint on jointly-infeasible defaults) was folded into R98's
  remainder.
- **Elevated R45 to P1** and folded in the 2026-08-05 and 2026-08-09 burns:
  three live Showdown builds in six days ran on hand-written feeds because
  the sanctioned paste tool refuses every Showdown salary file. R32 names the
  paste the PRIMARY source; a primary intake failing an entire contest
  family is a contract violation, not a degraded enrichment. One fix detail
  added from the 08-09 fragment: resolve probables off `Starting`, not
  Roster Position, on Showdown files.
- **Reordered "What do we tackle next":** new position 1 is the Showdown
  intake-and-bookkeeping batch — R104 + R45 + R105 in one DEV session, with
  R54 riding per its own "schedule it with, or ahead of, any Showdown-heavy
  week" rule. Rationale: three-to-five live burns in six days, every one
  hand-worked-around at T-minus, and the batch is the cheapest half of R41's
  remaining gap. R37(2), R10, R62, R40, R96 hold their relative order behind
  it (R37(2) is waiting on ARCHIVE and slates, not on a DEV slot).
- **Corrected the R102 collision.** The backlog item filed 2026-08-09 as
  R102 (pinned same-game pitcher pair) is renumbered **R103**: the
  2026-08-10 sync commit took R102 in its commit subject, this changelog,
  `tests/test_core.py`, `tools/claim.py`, `tools/sync_check.py`, and
  CLAUDE.md, and shipped history is immutable, so the open backlog item is
  the thing that moves. The three historical amendment references are
  annotated in place rather than rewritten. Lesson recorded on the R103
  entry: the next free R-number comes from scanning BOTH the backlog and
  this file; the backlog alone is not the counter.
- **Merged the sync fragment's remainder:** the GH PAT is filed as
  **Sync-tail (Ben)** with the token-transport rule preserved verbatim;
  fixture vendoring is sequenced behind it on the R62 entry; the
  engine-mutex-is-nominal finding is **R31(d)**, decision-first because
  making the mutex real starts blocking sessions that today proceed.
- **Fragment consumption:** six BUILD/DEV fragments deleted per the
  protocol (po-plr, paste-double-row 08-05, verify-export-status 08-05,
  manifest-vocab 08-06, postures 08-08, paste-rejects 08-09, three-way-sync
  08-10 — seven files, six logical fragments after the two paste burns).
  `2026-08-09_DEV_ben-decision-curated-satellite-archetypes.md` stays in the
  inbox: it is ARCHIVE's work order, already referenced by R40.

### Why

Ben asked for the revised spec to be adjudicated element by element with
every claim validated, and for the backlog to put the priority items first.
The revision's value was not its architecture, which re-argues settled
rejections without new evidence; it was convergence — three of its flaws
were things this project's own builds had already hit live and filed as
fragments, which is exactly the evidence standard this board files on. The
queue now leads with the batch that stops the recurring operator burns.

## 2026-08-10 — R102: the sync state is measurable, and a marker-only release is loud

Test pin 792 -> 810. New tool `tools/sync_check.py`. No engine module, no
projection, no MILP constraint, and no control moved.

### R102 — three locations, two filesystems, and one link that does not exist

**What prompted it.** Ben asked how cloud sessions and local files stay in
sync. Measuring it turned up that the question has a false premise and a real
gap. The Windows folder and the `device_bash` mount are the SAME files and
cannot drift; only the container is separate. And the container cannot reach
GitHub at all: `bleeski/mlb-dfs` is private, `GH_TOKEN` and `GITHUB_TOKEN` in
the container are 14-character placeholders, and `gh` is not installed.
github.com itself is reachable, so this is an auth gap and not a network one.

**`tools/sync_check.py`.** One command, exit 0 in sync and 2 on drift. Two
things it deliberately refuses to do. It never calls an unread GitHub head
"agreement": with no token it reports the remote as unmeasured and says why,
because the mount has never fetched and its `origin/main` moves only when Ben
pushes. And it never reports the mount's stat noise as a change: every path it
calls dirty is confirmed against `git diff HEAD --name-only`, which compares
content, with the mtime-only paths counted separately. It reads refs off the
filesystem rather than through git, which is one fewer `index.lock` this mount
cannot unlink.

**Which of those two sources is the authority is the whole design, and the
first cut had it backwards.** Deriving modifications from porcelain and
subtracting the content diff makes any path porcelain MISSES vanish from every
bucket. That is not hypothetical: running the tool on the mount seconds after a
write-back, this mount served a stale stat and porcelain omitted a CHANGELOG.md
that `git diff HEAD` scored at +51 lines. Content is now the authority and
porcelain only adds context, because a sync tool that under-reports drift is
worse than no sync tool. Pinned by
`test_content_wins_when_porcelain_misses_a_file`.

**A hand-written `RELEASED` marker never released a claim, and CLAUDE.md said
it did.** `_is_held` reads `released_utc` from owner.json and consults the
marker only when owner.json is unreadable. So the contract's instruction
produced a claim that reads HELD forever. It cost three hours on this date:
an engine claim was arbitrated as orphaned, released by hand, and `check` kept
reporting it held.

The precedence is NOT flipped, and that is the decision rather than an
oversight. `take` clears the marker with unlink, which fails on this mount, so
a marker-authoritative rule would report a live claim as free — failing open on
a held claim, where the current bug fails closed on a released one. Instead
`take`, `check` and `sweep` now name any claim carrying a marker with
`released_utc` still null and print the command that completes it. Six existing
claims are in that state and the warning names them all. CLAUDE.md's release
sentence is corrected to match the tool.

**Also corrected.** `skills/generate-lineups/SKILL.md` carried the audit pin at
773 while the real pin was 792, so the third of the three pin locations had
been drifting through at least two changes. All three move together here.

**Filed, not built.** Two limits are written down in the new
`docs/cowork_sync_protocol.md` rather than fixed: the engine mutex is nominal,
because `take engine_myslug` gets its own directory and blocks nobody, and a
fresh clone still cannot run the suite green because the fixtures it needs are
untracked.

## 2026-08-10 — R101: the late swap stops discarding the bank it just built

Test pin 784 -> 792. `bank_cache` v1.2 -> v1.3, and its stored document gains a
field. No projection, no MILP constraint, and no control moved.

### R101 — one conditions signature was doing two different jobs

**The mechanism, verified in the tree before anything changed.**
`tools/late_swap.py` calls `extend_bank` once for the general bank (`:613`) and
then once per pinned entry (`:635`), each with an `excludes` list computed from
that entry's own `excluded_new_teams` minus its own current roster.
`extend_bank` folded the excludes, the stack bounds and the projection values
into ONE `conditions_signature` and opened with
`drop_stale_jobs(conditions_sig)`, which deletes from memory every candidate
whose job key does not end in that signature. `as_candidates` serves the memory
view, so each targeted slice wiped the previous slices and the general bank with
them, and the joint solve received whatever the LAST slice happened to leave
behind. `save()` unions with disk, which is why the file kept growing while the
solve did not.

**The second-order finding in the item held, and it is the sharper half.**
`extend_bank` relaxes `stack_min`/`stack_max` to the free hitter slots BEFORE
computing the signature (`bank_cache.py:496-509`), so two pinned entries with
identical exclude sets still land in different buckets when they pin different
numbers of hitter slots. The blast radius was wider than "one bucket per exclude
set", and it is visible in the 2026-08-03 record: five distinct signatures over
one slate's swap.

**Decision: bucket by conditions signature (option (a)). Option (b), one exclude
set for the whole solve, is rejected.** (b) is the union of every entry's
`excluded_new_teams`, and for an entry that never held those locks it removes
legal players from the search as a convenience, invisibly, inside a certified
artifact. That is the pool reduction CLAUDE.md's guardrail forbids, and it
changes swap semantics on top of it. (a) is safe for a reason that was checked
rather than assumed: `contest_allocator._entry_candidate_compatible`
(`contest_allocator.py:1654`) tests every candidate against that entry's
`allowed_candidate_ids`, its `locked_slot_assignments`, its `locked_player_ids`,
its `excluded_player_ids`, and its `excluded_new_teams` with R72(i)'s
fail-closed treatment of an unmapped pid; `full_compatible` is built across all
E x K at `:2024` before the MILP is written. A candidate built under another
entry's excludes cannot be assigned to an entry it violates. **The bank is a
superset, the allocator is the filter**, and that guard now has its own test
rather than riding on the bucketing tests.

**What moved.** `conditions_signature` is split into the two facts it was
carrying, and only one of them still destroys.

- `projection_digest(projections_df)` is new: the pool and projection truth
  alone. A change here means every stored candidate answers a different
  question, and `drop_stale_jobs` purges on a mismatch. This is the half that
  exists because of 2026-07-26, when a rebuild after the DK Status filter landed
  certified a pitcher with no role out of a cache built before the filter.
- `conditions_signature` keeps its exact byte stream and therefore its exact
  values, deliberately: the signatures already written into live cache files are
  a compatibility surface. It is now the BUCKET key, not the liveness test.
- `BankCache.conditions_index` maps a conditions signature to the projection
  digest it was built under. Persisted, unioned across writers on `save()` the
  same way candidates and attempts already were, and written sorted. A signature
  the index cannot place fails CLOSED — dropped, not served — which is what
  stops a cache file written before this change from resurrecting
  pre-invalidation candidates.
- `drop_stale_jobs(conditions_sig, projection_digest="")` keeps every job under
  the current projection digest and every job under this exact request.
  Omitting `projection_digest` reproduces v1.2 byte for byte, which is what the
  maintenance callers and the concurrency tests rely on.
- `as_candidates` serves the union of live buckets, emits one payload per
  distinct ordered roster, and reports `stored`, `duplicate_rosters_dropped` and
  `conditions_buckets` alongside the scoring counts. `_load` dedupes on the
  ordered roster too, because memory now legitimately holds several buckets and
  a roster stored twice would double-count in every exposure denominator the
  allocator computes.

**Report truth, which is the half the operator actually reads.**
`bank: N candidates` and `candidate scoring: N scored` were the two numbers that
sent the operator hunting for a scoring failure for twenty minutes on
2026-08-03, and nothing on either line said they were describing different
banks. `tools/late_swap.py` now prints `bank after the general slice:` (that
slice, named as such), one line per targeted entry carrying the running total,
`bank the joint solve will see: N candidates across K conditions bucket(s)`
after the loop, and a `candidate scoring:` line that leads with the count the
solve receives and names the two ways it can differ from the stored count —
collapsed duplicate rosters and scoring failures — on the line itself. A
non-zero `superseded_jobs_dropped` now prints with the projection digest that
caused it, because post-split it can only mean the projections moved.

**Counts. Deterministic candidate counts, never a performance claim.**

Replayed against the stored 2026-08-03 bank
(`runs/bank_cache_2026-08-03_8b239b254b.json`, read-only, on a copy) using the
signatures that file actually contains, in the order the swap used them, with no
solve budget so no MILP runs and no clock enters the numbers:

| | HEAD | after R101 |
|---|---|---|
| stored in the file | 1,180 across 6 conditions buckets | same |
| after the general slice's drop | 1,006 | 1,152 |
| after every targeted slice's drop | 0 | 1,152 |
| served to the joint solve | 0 | 1,152 |

The 1,152 is 1,006 general + 90 + 25 + 20 + 11 targeted. The 28 not in it are a
second no-locks bucket built under a different projections frame; it is still
purged, which is the invalidating half doing its job. End to end through the
certified MILP path on the synthetic slate the suite uses, one general slice
capped at 8 plus two targeted slices with different exclude sets: 8 + 2 + 2 = 12
served across 3 buckets with 0 superseded, where HEAD served the last slice's 2.

**What could NOT be reproduced, stated rather than restated.** The item's
headline number — cache 1,007, solve 8 — is not reproducible from the
2026-08-03 inputs today. Rebuilding that slate's projections frame from
`data/slates/2026-08-03/DKSalaries.csv` and `lineups_feed_v2.json` yields
conditions signature `d192d9a6a2df3415` against the `02a23bbd1b190ab8` the cache
stores, because `data/reference/` has moved since (the FanGraphs platoon
reference was refreshed 2026-08-05). Every candidate in that file therefore
reads as built under a different projection truth, and both code paths correctly
serve 0 from a re-run. The 8/9/10-and-90 figures stay what they always were: an
observed record read out of `outputs/2026-08-03/_swap1..9.log`, not something
this commit reproduced.

**One consequence to hold onto, because it is not obvious from the call site.**
Since the stack bounds are relaxed before the signature is computed, the union a
heavily pinned swap serves can contain candidates carrying a smaller primary
stack than the general slice asked for. Generation bounds were never the
enforcement point; the allocator's `primary_stack_min_size` floor is, it is 4 on
every posture as of R37 stage 1, it is applied to whatever bank it is handed,
and every relaxation of it is counted. Named in `extend_bank`'s docstring so the
next reader does not have to rediscover it.

**Tests, written failing first against the real shape.**
`BankCacheBucketingTests` (`tests/test_core.py`) runs the real call sequence
through `extend_bank` — general, then two targeted slices with different exclude
sets — and asserts `as_candidates` serves general plus both; asserts the report
counts the union it will serve; asserts two buckets holding one roster serve one
candidate; asserts an enrichment pass still purges destructively; and asserts,
on its own, that the allocator refuses to assign an entry a candidate its
excludes forbid. `BankCacheCorrectnessTests` (`tests/test_upload_integrity.py`)
gains the storage-contract half: the pool digest ignores excludes and stack
bounds while the conditions signature does not, sibling buckets survive under
one pool digest while a foreign one is purged, an unindexed signature fails
closed, and the index survives a save and unions two writers. Four of the five
core tests and all three integrity tests fail on HEAD.

**Not done here, on purpose.** `--budget` was not widened: the candidates were
being discarded after they were built, so a bigger budget bought more of what
was about to be thrown away. The initial build path is untouched (R61-tail,
unchanged by decision). R102 — the pinned same-game pitcher pair — is a
different filter with a different fix and stays open.

---

## 2026-08-09 — R40 archaeology answered; the routing it was going to license is NOT written

Test pin 782 -> 784. `build_slate.py` records the resolved objective per
contest in the brief. No routing, weight, or profile changed.

### R40 — which profile scored the two rank-1 satellite builds

**Answered, from `runs/` and the run diagnostics rather than the miner, as the
item specifies.**

| contest | archive | slate | field | finish | resolved shape | profile that scored it |
|---|---|---|---|---|---|---|
| 192892126 ($15 Relay Throw) | A-034 | 2026-07-28 | 53 | 1 of 53 | `satellite` | floor 0.42 / ceiling 0.58, stack 0.35, uniqueness 0.10, field pressure 0.25 |
| 192973047 ($5 FFM) | A-032 | 2026-07-30 | 23 | 1 of 23 | `large_wta` | floor 0.00 / ceiling 1.00, stack 1.10, uniqueness 1.00, field pressure 1.15 |

Neither is `wta_ticket_satellite`, which is the profile the item was written to
route toward. The record: the run promoted for 192892126 is
`20260728T221859Z_7567b76a` (three earlier runs that evening are `blocked`);
192973047 has TWO runs marked `promoted` with no supersession between them
(`20260730T153239Z_4ec8f869` and `20260730T154316Z_226d98ea`) and they assign
different lineups to the same entry — that is R96's unmanifested-delivery
problem showing up in the record, and it does not affect which PROFILE scored
either one, because both runs resolved the same shape.

**The routing change is NOT written, and the reason is the evidence rather than
the plumbing.** Ben's instruction was conditional: write the `paid_places == 1`
routing to `wta_ticket_satellite` if the answer is the `satellite` floor-blend
profile. It is, for one of the two. Three things say do not act on that yet.

1. **The floor blend WON.** The item's premise is that "the floor blend has been
   pulling toward exactly the construction the archive says does not win seats."
   The one contest that cleanly instantiates the floor blend finished first of
   53. That is n=1 and proves nothing on its own — but it is evidence against
   the premise, not for it, and it is the only direct evidence there is.
2. **The 2026-08-08 cash-line anatomy already complicated the premise
   independently**, and grading on both required statistics keeps it
   complicated. On PERCENTILE, satellite winners and last-paid seats look alike
   (~31, sub-median chalk, looser salary, 4-primary median) and the band just
   OUTSIDE the line is more 5-stacked and chalkier, so a floor blend pulling
   toward 4-primary sub-median chalk is pulling toward what actually got paid.
   On MEAN-delta, 3.17's +4.9 cumulative-ownership-over-field still holds. Both
   are true at once in a left-skewed chalk distribution; neither alone settles
   this, and the profile difference the routing would make (floor 0.42 -> 0.00,
   field pressure 0.25 -> 0.80) moves construction on exactly the axis the two
   statistics disagree about.
3. **The routing key is null for both contests.** `paid_places` is absent from
   both mined records and from `contest_library` for both contest names, so a
   `paid_places == 1` rule would not have fired on either build even if it had
   existed. Writing a router keyed on a field that is empty where it matters
   most produces no change and a false sense that one was made. That is
   downstream of the curated-archetypes decision now sitting in
   `docs/backlog_inbox/` for ARCHIVE, which is what would populate the key.

Reranking lineups on contests entered tonight is a strategy change and Ben's
dated decision. The archaeology is done and the finding is the opposite shape
from the one the conditional anticipated, so it goes back to him rather than
into the engine.

### R40 — the "either way" half, which is unconditional and is shipped

`build_slate.py` writes a `contests` block into `build_brief.json`: one row per
contest carrying contest_id, name, posture, posture_source, matched pattern,
resolved contest shape, and the full scoring profile including its weights. It
printed to stderr and stopped there, which is precisely why answering this
question three months later meant reading `runs/` and cross-referencing a
weights table by hand.

The weights are copied in rather than referenced by name: a profile name is only
meaningful against the version of `CONTEST_SHAPE_PROFILE_WEIGHTS` current when
the build ran, and that table has moved. The block is built through a deferred
import so `build_slate`'s stdlib-only top level survives, an unresolvable shape
is recorded as an error rather than as a missing profile, and bookkeeping never
breaks a delivery.

---

## 2026-08-09 — R37 stage 1: the primary-stack floor lands at 4 on every posture

Test pin 773 -> 782 (core 521 -> 530). `contest_allocator` gains
`primary_stack_min_size` with a counted relaxation ladder; `bank_cache` emits
the field that control reads; `execution_pipeline` declares the floor on all six
postures and corrects `mme`'s stack-plan label.

### R37(1) — universal `primary_stack_min_size = 4`

**Decided by Ben 2026-08-09**, accepting DEV's 2026-08-05 floor-first
recommendation as written, amended by the 2026-08-08 third-tranche input. Stage
1 only. Explicitly deferred by the same decision: floor 5 at breadth <= 0.02
waits for one measured tranche, the 4-2-x cap is sized separately after this
lands, no contrarian push, salary-left untouched. Any future five-stack quota
reads the shape's CURRENT field share rather than a pinned lift constant.

**Shipped.** `primary_stack_min_size` is a portfolio control, declared at 4 by
every posture in `STRATEGY_DEFAULTS` and enforced in
`select_and_assign_entries`: a candidate whose primary stack carries fewer
hitters is not selectable. It is the first LOWER bound among the per-candidate
controls, and it merges under R34's floor rule rather than the ceiling rule --
least demanding wins, and one posture going silent retires the floor for the
whole portfolio. `cash` therefore declares it too, and that is the only control
`cash` carries; a single cash contest in a mixed file would otherwise switch the
floor off for every other contest in that file.

**The evidence, and its label.** Three tranches put `<=3-primary` negative every
time (-2.8pp [-3.8,-1.8] combined over the first two, -9.8pp [-18.0,-1.6] on the
third) while our own share of that family climbed 7.0% -> 21.5% -> 26.3%. The
2026-08-05 probe priced the floor at 0.00-0.76% of the unconstrained objective
across 3-to-8-game slates and found a 5-primary lineup feasible on 100% of
stackable teams at every width. Observed outcomes and deterministic review
proxies. Nothing here is a win rate, a cash rate, or a probability.

**Relaxations are counted, Showdown-style, and the ladder is 4 -> 3 -> off.**
The reason is the one CLAUDE.md already gives for the Showdown controls: a short
bank leaves a blank reserved row and a blank row blocks certification, so a
floor that refuses is worse than a floor that steps down and says so. It steps
on two triggers, both recorded with a `from`, a `to` and a reason:
`entry_starved_before_solve` when an entry retains no compatible candidate at
the current rung, and `proven_infeasible_with_floor` after the MILP proves
infeasibility with the floor active. It NEVER steps on a timeout — the rule that
a compute limit may not move a strategy control is the same rule the DU ladder
already follows, and a slow solve must not quietly buy a looser portfolio. The
ladder stops at 3 because below `PRIMARY_STACK_MIN_HITTERS` the bucket rule
reports no stack at all, so a "floor of 2" would exclude every candidate while
looking like the loosest setting available.

`primary_stack_floor` on the result carries requested, applied, status, the
relaxation count and steps, the bank's size histogram, how many candidates were
excluded, the histogram of what was actually ASSIGNED, and
`assigned_below_requested` — counted from the delivered assignments rather than
asserted from the constraint. A portfolio is not clean because it certified; it
is clean when that count and the relaxation count are both zero.

**This is not the pool trimming CLAUDE.md forbids.** That rule is about reducing
the legal PLAYER set to fit a COMPUTE limit, invisibly. This reduces the
CANDIDATE set to fit a stated strategy, is decided before the solve rather than
discovered during it, and names every rung it lands on. Same distinction the
fixed-exposure blocking already draws two hundred lines above it.

### R37(1) — the plumbing it rides on was broken, and R34 was broken with it

**Found while building, reproduced on the real 2026-08-08 1910_9g delivery.**
`bank_cache.as_candidates` emitted `primary_stack` and not
`primary_stack_size`. The allocator reads the size through
`_candidate_primary_stack_size`, which returns 0 for a missing key — and 0 is
also the honest encoding of a genuinely stackless lineup. So every sliced-path
candidate reported "no stack" regardless of what it held: seven candidates
carrying real four-man stacks all read 0.

That is not a weakened control, it is an inverted one. R34's
`min_five_stack_share_pct` would have refused a bank that satisfied it ("the
bank contains 0 such candidates"), and R37's floor would have excluded every
candidate it was handed. The quota shipping at 0.0 is the only reason this never
fired. The team was emitted and the count was not, which is the shape of bug
that reads as working.

**Shipped.** `as_candidates` emits `primary_stack_size`, pinned by a test at the
producer. And because a missing field and a stackless lineup remain
indistinguishable per candidate, the floor treats a bank in which NO candidate
reports a size as `unmeasurable`: it does not enforce, and it says in a warning
that the producer is the thing to fix. A Classic bank of genuinely stackless
lineups is not realistic; excluding everything on the strength of an unwritten
field is the worst available reading of that ambiguity.

### R37(1) — `mme`'s stack-plan label said something the archive contradicts

**Shipped.** `five_three_with_diversification` -> `tight_5_with_diversification`.
The archive has 5-3 at-share on both the win line and the top decile in every
slice measured, and the mini-MAX slice this posture serves prefers the lone five
(5-1-1-1, +3.6pp [+1.4,+5.6] over 73,343 entries). Only `_STACK_SIZE_BY_PLAN`
reads the string, for the size 5, which is unchanged — so this is a label
correction with no behavioural effect, which is exactly why it was worth doing
before something got wired to it. The retired name stays in the size map:
archived build records still carry it, and a plan string that map does not know
drops silently out of the max-stack computation.

### Fixture moves, both deliberate

**`tests/golden/golden_replay_2026-06-03.json` regenerated.** The floor bound on
the replay: 14 candidates in, one 3-primary excluded, 13 eligible, zero
relaxations, zero assigned below 4. Worth stating precisely what moved, because
"the golden baseline changed" invites the wrong reading — the DELIVERED
PORTFOLIO DID NOT CHANGE. Per contest the multiset of lineups is identical, and
`exposure_summary`, `sp_pair_distribution`, the stack distribution (BOS 12, PHI
5, SD 1) and the eight distinct signatures are all byte-identical to the old
baseline. What permuted is which entry_id received which candidate_id: removing
one candidate shifts the MILP's variable indices and therefore its tie-breaks.
Verified deterministic across two consecutive runs before regenerating.

**`test_a_cash_only_file_enforces_nothing_and_matches_the_build` renamed to
`..._enforces_no_cap_...`.** It asserted `cash`'s controls were literally empty.
The assertion that carried its meaning was always "cash contributes no cap", so
that is what it now says, and it now also asserts no key starting `max_` appears.

**Mutation-checked by hand.** The first version of the floor's headline test
passed against a mutant with enforcement disabled, because the ineligible
candidate was also the lowest-scoring one and the solver skipped it anyway — the
test was measuring the report, not the constraint. The fixture now puts the
3-stack on top with the best score and asserts it wins without the floor, so
removing the enforcement turns the test red. Both mutants (enforcement disabled,
payload field dropped) are caught.

---

## 2026-08-09 — R61 shipped whole; R47 investigated, mechanism found, fix repriced

Test pin 758 -> 773 (core 506 -> 521). `contest_allocator` and
`dk_entries_manager` gain `fixed_exposure` / `fixed_portfolio_exposure`;
`execution_pipeline` wires it on the late-swap path only.

### R61 — the swap solved a subset and was graded on the whole file

**Shipped.** `select_and_assign_entries` resolved every exposure cap against the
entries it was HANDED (`total = E`); `validate_dk_entries_file` resolves them
against every complete row in the exported file. `build_entry_requirements`
drops unauthorized and fully-locked rows, so on a late swap those are different
sets and a legal swap died at the gate closest to lock.

Reproduced first, and the filed numbers held exactly: a 20-row file with 8 rows
the solve cannot touch and `max_player_exposure_pct=0.45` gives the solve
floor(12x0.45)=5 while 6 exposures sit fixed in the untouchable rows, and the
validator then judges floor(20x0.45)=9 against a count of 11 and blocks. With
the fix the same file resolves one cap of 9 against one denominator of 20, the
solve takes 3 rather than 5, and `portfolio_caps_passed` is True.

**Correction to the filed diagnosis: SEVEN controls shared the asymmetry, not
one.** The entry named `max_player_exposure_pct` and the same-contest duplicate
rule. Measured, the list is `max_player_exposure_pct`,
`max_pitcher_exposure_pct`, `max_primary_stack_exposure_pct`,
`max_sp_pair_repetition`, `max_game_exposure_pct_by_game`, the same-contest
duplicate signature rule, and `max_shared_players`. Fixing the filed two would
have left five instances of one defect live, so all seven are in.
`min_five_stack_share_pct` is deliberately NOT in: it is a floor on the lineups
being constructed and the export validator does not check it, so `E` is its
correct denominator.

Five are count caps and take arithmetic: `cap_k - fixed`. Two are pairwise and
cannot, because the pairs that were never formed are the ones crossing into the
untouchable rows — a candidate duplicating an untouched row of its own contest,
or overlapping one past `max_shared_players`, is now unselectable, with the same
identical-roster exemption the validator applies. That enforces a control the
export gate already enforces; it is not the pool trimming CLAUDE.md forbids,
which is a reduction made to fit a COMPUTE limit and invisible in the output.
Every exclusion is named in `fixed_exposure_report`.

**Decision 1, `cap_k - fixed <= 0`: a refusal, not a relaxation, and the
boundary is `>` not `>=`.** `fixed == cap` is NOT a conflict — it is zero
headroom, an ordinary constraint the solve satisfies by selecting none of that
key. Only `fixed > cap` refuses, because no assignment of the authorized rows
can bring a whole-file count under a cap the untouchable rows already exceed.
It is decided before the MILP and carries its own label,
`refusal: untouchable_rows_exceed_cap`, and the sentence "rows you are not
authorized to change already hold N of a cap of M" — never CLAUDE.md's reserved
"proven infeasible: <constraint>", which is a proof about a constraint system
the solver was handed, not a fact about rows nobody asked it to touch.

Not a relaxation, because widening a portfolio cap on the operator's behalf at
T-minutes because the rows behind it happen to be frozen is a strategy change
made invisibly — the move R98(2) closed one layer up. The remedies are ordered
accordingly: authorize the offending rows with `--entry-ids` first (a SCOPE
change, no strategy change at all), restate the parent build's own cap second
(R29(3): a swap re-deriving a tighter cap than the build shipped is the common
cause), and a genuinely new value last, as the strategy decision it is. Bank
growth is deliberately NOT offered — the bank is irrelevant to a count the
untouchable rows carry alone, and naming it would be the guess R98(2) removed.

**Decision 2, absent means byte-identical.** `fixed_exposure` defaults to None
and `execute_portfolio` supplies it only when `mode == "late_swap"`, so the
initial build does not move (the R28 precedent). `fixed_exposure_report` is
added to the result ONLY when offsets were supplied, which is why
`test_golden_replay`'s frozen payloads did not shift — the key set is unchanged
without it. Pinned by `test_absent_offsets_leave_the_result_untouched` across
omitted / explicit None / `{}` / `row_count: 0`.

**A bug in the first cut of this fix, found by that test.** The headroom
subtraction read the count dicts unconditionally while the conflict check sat
behind `if fixed_rows`. A stray `{"row_count": 0, "player_counts": {...}}` then
spent headroom with the refusal skipped: HOT's cap went to zero and both hot
candidates vanished with nothing in the output saying so — an invisible cap
change, arriving through the code written to remove invisible cap changes. There
is now ONE gate: the four count dicts stay empty unless there is at least one
untouchable row.

**Where the derivation lives, and why there.** `fixed_portfolio_exposure` is in
`dk_entries_manager`, beside the validator, and reuses the same parser, the same
`roster[:2]` pitchers, the same `_primary_stack`, the same per-lineup game set,
and the same `"/"`-joined SP-pair key the validator publishes. A second
derivation next to the solver would be a second definition of the same number,
which is the defect one layer up.
`test_derivation_matches_the_validator_on_the_whole_file` holds them together
the way the `_cap_count` contract is held.

**Corrosive half, `classify_swap_failure`.** Every cap violation used to end
"pass it with --controls-override", teaching cap-loosening as the fix. It now
reuses `contest_allocator.STRUCTURAL_FLOOR_CONTROLS` / `STRATEGY_CAP_CONTROLS`
and orders remedies as `build_slate.infeasibility_hint` does: bank growth first
where `job_list_exhausted is False`, then arithmetic, then the strategy
decision, then a reminder to check the parent's own cap before inventing a
value. Two prefixes were also missing from `_CONTROL_BY_ERROR_PREFIX` —
`"entries "` (`max_shared_players`) and `"game "`
(`max_game_exposure_pct_by_game`) — so the two controls that most often bind on
a swap fell through with no control named at all.

**A guard written and then deleted, because it could not be made red.** An
explicit `_SELF_EXPLAINING_REFUSALS` branch was added to stop the trailer being
appended under an allocator refusal. Mutating it to `if False:` left the suite
green, and inspection said why: no refusal string starts with any prefix in the
map, and `execute_portfolio` returns on `not allocation["passed"]` before any
export gate, so allocator errors never arrive beside validator errors. The
branch could not change the output of any reachable input. It is gone;
`test_an_allocator_refusal_is_not_re_steered` now asserts the two facts that
actually hold the invariant, against the real strings, and goes red if a prefix
is added to the map or a refusal is renamed to lead with one.

Twelve guards mutated by hand, one at a time; all twelve red.

### R47 — investigated, both mechanisms found, both filed diagnoses corrected

Not shipped as a fix. The item was filed with the mechanism unfound, and the
mechanism is now found for both halves — neither is what the entry proposed.

**(a) The 8-10 scoring band across bank sizes 33 -> 1,007 is not a scoring
failure.** The entry's leading hypothesis was a silent exception path in
`score_lineup_candidate`, and asked for the failure counter to be instrumented.
That instrumentation already exists (F15) and `tools/late_swap.py` already
prints it: all nine of `outputs/2026-08-03/_swap1..9.log` report `0 failed`.

The cause is `bank_cache.drop_stale_jobs`, called at the top of every
`extend_bank`. It discards every stored candidate whose job key does not end
with the current conditions signature, and the conditions signature includes the
exclude set. `late_swap.py` computes `excludes` per entry from that entry's own
roster, so each targeted slice discards the candidates the previous slices built.
The cache genuinely reached 1,007 while the joint solve was handed 8; scoped to
the 2 entries that needed a change — which shared one exclude set, so nothing
was discarded between them — it was handed 90. A larger `--budget` cannot close
that gap, because the candidates are discarded after they are built.

**(b) "+0 targeted candidates" is the same-game pair filter, not the targeted
builder.** `extend_bank` builds its job list from `usable_pairs`, which drops any
pair whose two pitchers share a `Game_ID`. Each job passes its pair as `locks` on
top of the entry's `locked_slot_assignments`, so a job whose pair is not the
pinned pair needs four pitchers in two slots. Entry 5207638174 had both P slots
pinned to one game, its pair is therefore absent from every job, and every solve
was infeasible. The "zero-open-pitcher-slots shape" reading in the entry is the
right observation with the wrong cause; entries with one P pinned are fine
because pairs containing that pitcher survive the filter.

**Shipped from R47:** the documentation half, which the entry asked for
regardless of the fix. `skills/generate-lineups/references/late_swap.md` now
carries tight `--entry-ids` scoping as the recommended pattern WITH its
mechanism, says to read `candidate scoring: N scored` rather than
`bank: N candidates`, states that a larger budget does not help, and documents
the both-pitchers-one-game zero-candidate case. `classify_swap_failure`'s
"no compatible candidate" line no longer leads with `--budget`, because on the
one case this was reproduced on the bank was never the cause.

The remainder is repriced in the backlog as R101 (the discard) and R102 (the
pinned same-game pair). R47 is closed.

### Premises undermined elsewhere

- **R61-tail (new, P3).** `execute_portfolio` writes the initial build with
  `preserve_completed=True`, so a build from a template that already holds
  completed rows outside its requirements has the same dual denominator. Not
  changed here, deliberately: the initial build is byte-identical by decision,
  and no reproduction of that shape exists. Filed rather than fixed silently.
- **Finding 10 in the backlog** (prefilter starvation, "that 2+-options-but-all
  -filtered shape is exactly the late-swap pinned-entry case") rests on targeted
  candidates existing and scoring below the keep line. R47(a) shows the swap's
  targeted candidates were mostly being discarded before the prefilter ever ran,
  so the late-swap half of that reasoning is measured against a bank the solve
  never saw. Dated note added to the item; the single-entry coverage floor it
  proposes is unaffected.

---

## 2026-08-08 (evening) — R63 decided and contracted; R98(1)(2) shipped; R98(4) half-landed

### Decided

- **R63 — build_slate does NOT run a plan leg first, and CLAUDE.md item 3 now
  says which door gets which review.** The contradiction was real:
  `build_slate.py`'s only `run_slate` call passes `approve=True`, so R28's
  `_plan_joint_allocation` — written to predict a proven-infeasible thin slate
  before staging — never fired on the primary path, while item 3 read
  "`run_slate(approve=False)` first, always."

  The two candidate fixes are not symmetric and the cost decides it. On
  build_slate's sliced path the plan leg would call
  `select_and_assign_entries(candidates, entries, controls)` — literally the
  same call the build then makes, on the same candidates, under the same
  controls. That is not an approximation of duplicated work, it is duplicated
  work by construction. On the direct path the plan builds its OWN temporary
  sliced bank, which `_plan_joint_allocation` itself documents as "not the
  build's `build_diverse_candidate_bank` bank" and marks
  `exact_for_this_build: False` — so it would spend the window the real bank
  needs, to answer a question about a different problem. R98 had just measured
  that window bottoming out on a 5-second floor, so the plan-then-approve path
  would have made the defect shipping in the same commit strictly worse.

  The deciding argument is what a refusal would have meant on 1910_9g. The plan
  would have proved infeasible against the same 38 candidates, and under
  "refuse on `verdict == proven_infeasible`" build_slate would have refused —
  on a bank explored to 1.8%, where the correct answer was another slice.
  Wiring a hard refusal to that signal institutionalises the exact
  misdiagnosis R98 exists to correct. Note also that `run_slate(approve=False)`
  returns `passed=True` even when its plan predicts refusal, and says so in
  code: "this is the review checkpoint, not a gate." Option A would have
  converted a self-described non-gate into a gate, which is a larger contract
  change than the one taken.

  So the contract moved instead, and it moved without losing anything. Item 3
  now distinguishes the two doors: at the engine API `approve=False` still comes
  first, always, and remains the only place the bank-interaction verdict exists;
  at `build_slate.py` the review is the script's own on its single `approve=True`
  call — slate clock, pool report, postures, stack plan, caps, feasibility, and
  one Blockers line, with a refusal at exit 3 carrying all of it in the brief.
  What build_slate does not have is the plan verdict, and the contract says so
  in words rather than implying an equivalence it does not have. What it has
  instead is the refusal itself, which is the same MILP's answer, and which as
  of this commit names bank growth before any control change.

### Changed

- **R98(1) — a bank budget bounded by a constant now says so.**
  `resolve_bank_budget()` replaces both bare `max(..., 5.0)` expressions in
  `build_slate.py` and returns `(budget, floored)`. A floored budget prints
  `BANK BUDGET FLOORED (<label>)` on stderr naming the remedy (re-run, exit 10
  resumes) rather than merely the condition, sets `budget_floored: true` inside
  `solve.bank`, adds a `bank_warnings` line, and surfaces
  `solve.bank_budget_floored` at the level a reader reaches first — because
  `solve.bank` is None on the direct path, which is the one path where
  `run_slate` builds the bank.

  **A correction to the filed item, found by reproducing it.** R98(a) named
  `build_slate.py:1453` (`run_slate`'s `bank_time_budget_s`), but the observed
  `time_budget_s: 5.0` came from `:1346`, `extend_bank`'s budget on the sliced
  path — the bank report's `time_budget_s` is `extend_bank`'s own parameter, and
  `:1453` is inert whenever `candidates_override` is supplied. Both are the same
  silent floor and both are now audible; `:1346` is the one the live evidence
  hit. The floor value itself is unchanged and named once, as
  `BANK_BUDGET_FLOOR_S`.

- **R98(2) — the infeasibility path names bank growth first, and stops calling
  two different levers by one name.** `select_and_assign_entries` takes an
  advisory `bank_report` (contest_allocator v1.12); `run_initial_build` passes
  its merged `bank_diagnostics` (execution_pipeline v1.16). On a PROVEN
  infeasibility with `job_list_exhausted is False`, the allocator appends
  ordered remedies: grow the bank, with the attempted/total counts and the
  percentage, then `--controls-override`. The solver's own arithmetic is
  untouched and still leads `errors`, so `_plan_joint_allocation`'s summary
  keeps reading `errors[0]`.

  The second half is the classification. `max_shared_players` and
  `max_sp_pair_repetition` reach an engine-named structural floor — no two
  lineups sharing a five-man stack CAN overlap less — so raising one to that
  floor is arithmetic and changes nothing else. The exposure caps have no such
  floor: the number the engine computes is the minimum that clears the bank it
  was handed, not a property of the slate, and adopting it concentrates the
  entered set. The old `build_slate.py` hint called both "not a strategy or
  player-pool change," which is how the 1910_9g operator moved three exposure
  caps from 0.35/0.43 to 0.56 against a 1.8%-explored bank. `infeasibility_hint()`
  now orders them — bank, then arithmetic, then strategy decision — and fires
  whenever any of the three is true, instead of only on a feasibility failure.

  Two things it deliberately does not do. A time limit gets no remedies, because
  the allocator says "time limit at gap X" or "proven infeasible", never both,
  and a remedy list attached to a clock is the same conflation. And a missing
  `bank_report` produces no bank sentence at all: absence of evidence is not
  evidence that the search completed, and the classification half — true of the
  controls whatever the bank did — survives on its own.

- **R98(4), refusal path only.** The not_certified payload carries
  `bank_exploration` (`jobs_attempted`, `jobs_total`, `job_list_exhausted`,
  `total_candidates`, `budget_floored`) beside the hint derived from it, so a
  refusal reads without re-deriving the counts. Carrying them into the
  CERTIFIED brief beside `controls_override_applied` — the half that lets a
  reader tell a deliberate cap from a starved one after a build succeeds — is
  still open and stays in the backlog with (3).

- **13 tests, and the pin moves 745 -> 758.** `BankBudgetFloorTests` (3):
  above-floor is silent and unfloored, below-floor is raised, flagged and
  announced with its remedy, and the boundary value is not "bounded by" the
  floor. `InfeasibilityRemedyOrderTests` (8) reproduces the 1910_9g shape — 47
  of 2592 jobs, `job_list_exhausted: false`, `budget_floored: true`, an
  exposure cap binding — and asserts remedy ORDER, not just presence:
  `--controls-override` never precedes bank growth. It also pins the three
  silences (exhausted bank, missing report, time limit) and the composite hint
  where a structural floor and an exposure cap fail together.
  `BuildContractCheckpointTests` (2) pins R63 from both sides: build_slate makes
  exactly one `run_slate` call and it approves, and `run_slate`'s not-approve
  branch still carries `_plan_joint_allocation`, so the engine-API leg of the
  contract is not hollowed out by build_slate's exemption.

- **Pins and versions.** `contest_allocator` v1.11 -> v1.12, `execution_pipeline`
  v1.15 -> v1.16, both mirrored in `tools/audit.py`. `EXPECTED_TEST_COUNT`
  745 -> 758 (core 493 -> 506). The PASS line moved in all three documents that
  quote it: `CLAUDE.md`, `skills/generate-lineups/SKILL.md`, and the ledger
  Quick Card (a one-line pin edit under a DEV-held `ledger` claim, at Ben's
  explicit instruction; no ledger section was touched).

### Still open

- **R98(3)** — derive the bank budget from entry count and job-list size rather
  than from whatever is left of `--max-seconds`. Repriced in the backlog: making
  the floor audible removes the invisibility, not the bad budget, and five
  seconds for 2592 jobs and 9 entries still could never have supported the
  defaults. **R98(4)**'s certified-brief half rides with it.

---

## 2026-08-08 — backlog merge: R98–R99 filed from the 1910_9g build, one BUILD fragment consumed

### Changed

- **Two items filed after Ben asked for a self-diagnostic on a portfolio that
  "seemed weird and different."** It was, and the delivered file was not the
  problem — all three gates passed, preflight was clean, and the manifest and
  sha256 were correct. The problem was that a 9-entry portfolio shipped with 7
  distinct lineups and one pitcher at 5/9, and every honest report in the run
  record still pointed the operator at the wrong cause. **R98** (P1, S then M) —
  `build_slate.py:1453` derives the bank budget as
  `max(deadline - now - 6.0, 5.0)`; under the Cowork 45s call ceiling
  `--max-seconds` runs low enough that the subtraction goes negative and the
  budget lands silently on the `5.0` floor. Observed: `time_budget_s: 5.0`,
  `jobs_attempted: 47` of `2592`, `job_list_exhausted: false`, 38 candidates for
  9 entries. Against a bank that thin the default portfolio controls are
  arithmetically impossible, so `contest_allocator.py:1886` proves the joint MILP
  infeasible and `build_slate.py:1497` offers `--controls-override` as the only
  remedy — correct for `max_shared_players` reaching an engine-named floor, wrong
  for the exposure caps, which have none and are a strategy decision. The
  operator relaxed the caps and certified. Fourth instance of the pattern in
  eight days; the three earlier ones each recorded it as a "small multi-contest
  slate" property and generalised the wrong variable. **R99** (P2, XS) — the
  brief reports `slate_clock.salary_cross_check: false` on a slate whose clock
  agrees, because `:1556` reads a `.get("agrees")` sub-key that the stderr check
  at `:1209` does not; a field the skill's reporting checklist tells the operator
  to explain should not cry wolf on a clean slate.
- **Why both are the R51/R92 family.** Neither is a false claim. R64 already made
  the relaxation record honest, and it was honest here: `controls_override_applied`
  says exactly what was relaxed. What it cannot say is that the bank was 1.8%
  explored when the relaxation was chosen, which is the fact that would have
  changed the decision. Filed, not fixed; R98(1) is the small part that would have
  caught all four instances.
- **Consumed:** `docs/backlog_inbox/2026-08-08_BUILD_thin-bank-drove-control-relaxation.md`.
  Still open in the inbox: the 08-08 postures/ticket-count fragment.

---

## 2026-08-08 — R97: one question, one salary-resolution policy, and `--restart` stops crashing on the mount it was written for

### Fixed

- **R97 — `tools/rebuild_registry.py` resolves salary the way the miner does (P2, S).**
  It called `resolve_salary_file(standings, default_salary_candidates(REPO))`:
  repo-wide pooled scoring over all 289 candidates, for every one of the 267
  archived contests. That is exactly the policy R49 replaced in the miner earlier
  the same day with `resolve_salary_tiered` — manifest, then in-date, then
  repo-wide, first usable tier wins — because pooling is what lets a same-type
  superset outrank the authoritative file. Two resolution policies answering one
  question is the defect, and the registry is derived from the same archive the
  miner reads, so the two disagreeing means the registry and the mined records
  could be built off different salary files. Both inputs the tiered resolver
  needs were already in hand at the call site: the slate date the tool derives
  from the archive path, and the contest id it parses from the filename.
- **`--restart` could not run at all on the device mount (found while preparing
  the rebuild, fixed here).** It called `staged.unlink()`, and the Cowork device
  mount raises `PermissionError` on unlink, so the one flag whose whole job is to
  start clean crashed before mining anything. It is also precisely the flag a
  resolution-policy change forces you to use, so the bug sat directly in front of
  the only run that needed it. `discard_staged()` now unlinks where it can and
  otherwise truncates the staged file to `{}`, which is equivalent for every
  reader in this tool: `contests_mined` reads back empty so nothing resumes, and
  `update_registry` setdefaults the whole structure from `{}` exactly as it does
  from a missing file. It reports which mechanism it used rather than leaving the
  operator to infer it, and the "resuming" line no longer prints at zero.
- **The summary says which tier answered.** A rebuild that fell through to the
  repo-wide scan is now visibly different from one the manifest resolved
  (`tiers  manifest=5, None=7` on the 08-05 slice), which is the entire point of
  tiering and was otherwise invisible in a run that prints only `mined`.
- **`--max-seconds` help corrected.** It claimed the Cowork sandbox caps a call at
  45s. It is roughly 170-180s. `docs/cowork_archival_runbook.md` carried the same
  wrong number in operational form (`--max-seconds 35`) and is corrected to 150 in
  this commit, with the `--restart` requirement stated.

### Measured, before claiming anything

Five real archived contests, resolve step only, parse done once and reused so the
number is the resolver and not the CSV read:

| contest | type | pooled | tiered | tier |
|---|---|---|---|---|
| 2026-08-06/193296906 | showdown | 4.80s | 4.03s | in_date |
| 2026-08-05/193253036 | classic | 4.59s | 2.41s | manifest |
| 2026-07-29/192896278 | classic | 2.72s | 1.79s | manifest |
| 2026-07-25/192707473 | classic | 2.02s | 1.55s | manifest |
| 2026-06-20/191506958 | classic | 2.67s | 3.36s | none resolved |

Mean 3.36s → 2.63s, total 16.80s → 13.14s, 22% faster. **A large speedup is not
established and this entry does not claim one.** The saving is real but modest
and it is not uniform: it appears only where an early tier hits, and the fifth
row is a SLOWDOWN, because a contest no tier resolves pays for all three tiers
where the pooled path paid for one scan. Contests with no salary source in the
repo are common in this archive (7 of 12 on the 08-05 slice), so that case is
not a curiosity. On runtime alone this is close to a wash; **the change lands on
the consistency argument** — one question should have one policy, and the miner's
is the one R49 validated by hand across 31 contests.

The five-contest sample also disagreed on WHICH FILE three times (pooled took
`data/slates/<date>/DKSalaries.csv`, tiered took the manifest's
`runs/<run_id>/inputs/DKSalaries.csv`). Checked rather than assumed: all three
pairs are byte-identical, both mines return `parse_structural_ok=True` and
`coverage=full`, so on this sample the aggregates do not move. That is a
five-contest observation, not a guarantee across 267.

### Consequence for the rebuild that follows

The registry rebuild is run with `--restart` rather than resumed. The 11 contests
already staged were folded in under the pooled policy; resuming would leave the
file half under one resolution policy and half under the other, which is the same
defect this entry closes, expressed as data instead of code. Restarting is
cheap — the archive is the source and the mine is deterministic. Separately,
R49(3)'s salary-join floor (`MIN_SALARY_JOIN_RATE`, 0.50) is part of
`parse_structural_ok`, which this tool enforces, so contests whose pooled
resolver previously picked a same-type wrong-slate file under 50% join now SKIP
instead of folding in. Skips are expected to rise against pre-08-08 behaviour and
each one is a finding, not noise. The rebuild's OUTCOME — counts, skip list,
reasons — is a ledger record under section 3 and is deliberately not in this file.

### Tests

- Three new tests in a new `RebuildRegistryResolutionTests`; the pin moves
  742 → 745 (`tools/audit.py`, CLAUDE.md, SKILL.md in this commit). The policy
  test asserts on the tool's NAMESPACE, not its source: `resolve_salary_tiered`
  is present and both `resolve_salary_file` and `default_salary_candidates` are
  absent, so the tool cannot drift back to the pooled policy because the name is
  not there to call. Both `discard_staged` branches are pinned separately, the
  refused-unlink one by patching `Path.unlink` to raise, since the container's
  own tmpdir allows deletion and the mount's behaviour would otherwise be
  untestable where it matters.

## 2026-08-08 — R39: the captain survives the parse, and the captain table becomes a standing per-contest measurement

### Fixed

- **R39 — `captain_norm` is captured per entry at parse time (P2).**
  `parse_lineup_string` already returned `[(slot, name), ...]` with `CPT`
  intact, and the very next line threw it away: `players_norm` is a SORTED,
  position-blind tuple and it was the only thing carried forward. Captain choice
  is the single largest Showdown construction decision, and no downstream
  analysis could see it — the 2026-08-08 review had to re-parse 64 archived
  standings CSVs directly to measure it at all. `captain_norm` now rides every
  parsed entry and appears in the per-entry archived projection, so **a re-mine
  backfills the whole archive** with no other change.
- **The measurement is now emitted, not derivable.** `construction` gained
  `captain_table` (top captains with `captain_count`, `captain_share_pct` and the
  player's overall `pct_drafted` on the same row, because 3.18's comparison is
  captain-share against roster-share and splitting them across two structures
  just makes the reader recompute it) and `winner_captain` (the winner's captain,
  its ownership, its share of captains, and `was_top_owned_captain` — recorded
  per contest rather than inferred from table order, since the top-owned captain
  won 22 of 85 in the 3.18 sample and both branches are live). The ledger block
  gained two lines, the Showdown counterpart of the existing SP-pair line. No
  branch on contest type is needed anywhere: Classic entries have no `CPT` slot,
  so the table is empty and the lines do not render.
- **Absence stays absence.** `_captain_norm` returns None for a Classic lineup and
  None for a Showdown cell that parsed without a captain, because both are the
  same absence to any aggregate and neither is worth inventing a value for. It
  returns the FIRST `CPT` slot; the roster contract admits exactly one, and a cell
  carrying two is malformed input the structural gate already rejects on slot
  counts, so choosing between them here would only hide that.
- **Verified against the archive.** Re-mined contest 193034899 (205-entry
  Showdown): Kevin Gausman 30.7% of captains against 30.58% rostered, the winner
  captained him, `was_top_owned_captain` true — the shape of measurement 3.18 had
  to derive by hand, now emitted by the mine.

### Tests

- Eight new tests in a new `MinerCaptainTests`; the pin moves 734 → 742
  (`tools/audit.py`, CLAUDE.md, SKILL.md in this commit). Both winner branches are
  pinned separately — a winner captaining the 25% option and a winner captaining
  the 75% one — so `was_top_owned_captain` cannot be satisfied by a constant. The
  Classic test asserts the empty table and the None winner rather than only
  asserting nothing crashes, since "no captains here" is the case that would
  otherwise pick up a junk value from a position-blind read. Also pinned: that
  `captain_norm` reaches the per-entry archived projection, which is what makes
  the backfill a re-mine rather than a migration.

## 2026-08-08 — R49(1)(2) + R30(c): the miner resolves salary manifest-first, and stops naming a file that never had a salary block

### Fixed

- **R49(2) — salary resolution is TIERED, and the first tier that answers wins
  (P2).** `--auto-salary` scored every salary CSV in the repo against the
  standings and took the best. That cannot find the right file when a same-family
  SUPERSET exists: a 9-game slate's players all sit inside the 10-game file, so
  several candidates join 100%, differ in content, and the resolver correctly
  DECLINES rather than guessing. Eleven of 94 contests needed manual resolution on
  2026-08-04 for exactly this reason. New `resolve_salary_tiered` tries, in order:
  **(1) MANIFEST** — `outputs/<date>/upload_manifest.json` names each delivery's
  `run_id`, and `runs/<run_id>/inputs/DKSalaries.csv` is by construction the file
  that build used for every contest in that delivery; **(2) IN-DATE** —
  `data/slates/<date>` then `data/archive/<date>`; **(3) REPO-WIDE** — the old
  behaviour. **The tiers are tried in sequence, not pooled and scored together**,
  because pooling is precisely what lets a superset tie with the authoritative
  file. Within the manifest tier a live delivery outranks a superseded one (the
  surviving delivery is the file that was entered) and superseded runs stay as
  fallbacks rather than being dropped, since a superseded run for the same slate
  staged the same slate's salary. The resolved `tier` is printed and returned, so
  a mine that fell through to the wide scan is visibly different from one the
  manifest answered.
- **R30(c) — the repo-wide scan is now the last resort, which is the speed fix
  (P2).** It ran first on every mine. The repo currently holds **289** salary
  CSVs, not the 170 the item recorded, so the saving grew rather than shrank; the
  join-and-team-coverage guards still sit in front of every tier. R30(c) is closed
  by the same change and its (a) data half — a fresh entry-history export from Ben
  — remains the only open part of R30.
- **R49(1) — a delivered `DKEntries_*.csv` is not a salary source, and two places
  said it was.** The runbook's step 3 and `emit_ledger_block`'s standings_only
  line both told the reader to recover coverage from "the slate's DKEntries upload
  file, which embeds the full salary block". That is true of DK's downloaded
  template and false of the engine's delivered file, which carries no Name or
  Salary column at all and makes `load_salary_map` raise. Both now name the real
  recovery path (the run inputs the manifest points at, or the staged slate file)
  and say in as many words that a delivered DKEntries is not a salary source.
- **Verified against the live tree, including the case it does NOT fix.** On
  2026-08-05 contest 193253036 the manifest tier resolves to
  `runs/20260805T214233Z_6f18cb6c/inputs/` at 100% join without scoring 289 files.
  On the 1910_4g five (193297994 and siblings) all three tiers correctly return
  nothing and the contest stays `standings_only` — matching what ARCHIVE reached
  by hand — because that delivery has no manifest row at all and therefore no
  `run_id` to follow. **That residue is R96, still open**, and it is worth stating
  plainly: manifest-first resolution is only as good as the manifest, so R96 is
  now the binding constraint on archive coverage rather than the resolver.

### Tests

- Eight new tests in a new `MinerManifestFirstSalaryTests`; the pin moves
  726 → 734 (`tools/audit.py`, CLAUDE.md, SKILL.md in this commit). The
  load-bearing one asserts BOTH halves: pooled scoring over the same two files
  returns None with "ambiguous" in the reason, and the tiered resolver returns the
  manifest file — so the test would still fail if the fix stopped mattering.
  Building that fixture corrected an assumption worth recording: the first version
  used a superset with eight new teams, and the 2026-07-24 team-coverage asymmetry
  separated them on its own (9 drafted of 17 priced = 0.53, below the 0.80 floor),
  so the test passed for the wrong reason. The superset is now one extra GAME —
  two new teams, coverage 0.82 — which clears the floor and lands in the ambiguity
  branch, which is the decline that actually happened. Also pinned: the tier order
  as a list, a delivery naming other contests being skipped, and the corrected
  wording in both the ledger block and the runbook.

## 2026-08-08 — R95: the pull list stops asking for exports DK cannot serve, and an empty file stops counting as a pull

### Fixed

- **R95(a) — a contest whose slate has not settled is held back (P1).** The scan
  enrolled a contest the moment its delivered DKEntries file existed, which is
  hours before the games are played. On 2026-08-08 four 1505_3g contests appeared
  on the pull list and in the clickable HTML at 12:43, before the slate locked.
  Ben clicked all four, DK served zero-byte exports, and those files then read as
  pulled. `compute_open` now takes `today` and skips any slate dated **>= today**
  — inclusive, because a slate dated today has not finished settling whatever
  hour it is read at, and the cost of waiting a day is a day while the cost of a
  premature pull is a lost contest. A new `compute_unsettled` reports what was
  held back under a "Not yet settled — do not pull yet" heading, deliberately
  unlinked, because silently omitting tonight's contests leaves the reader
  wondering whether the tool saw them at all.
- **`_today` now reads the ET calendar, not UTC, and that is load-bearing here.**
  It was `datetime.now(timezone.utc)`. `today` is the value that decides whether
  a slate has settled, and the container runs on UTC, so after 8pm ET the UTC
  date is already tomorrow — which is precisely when a night slate is mid-flight.
  On a UTC clock tonight's unsettled contests satisfy `slate_date < today` and get
  listed. It now delegates to `repo_env.today_et`, the one ET authority R65
  established. R31(b) is this same mistake in `claim.py`'s staleness check and is
  still open.
- **R95(b) — a zero-byte inbox file counts as not-pulled (P1).** Inbox membership
  was by filename alone. A new `_scan_inbox` returns `(pulled, failed)` and
  stats each file, so an empty export leaves its contest ON the list and is named
  under a "Failed pulls" heading with the offending filename. `inbox_ids` is now a
  thin wrapper over it, so every existing caller inherits the fix. A real export
  sitting beside a stray empty file still counts as pulled. **Both halves are
  kept rather than either alone:** (a) stops the tool asking for an export DK
  cannot serve, and (b) catches the case (a) cannot — a pull made between lock and
  settle, which still produces an empty file.
- **Why P1 rather than P2.** Every other item in this batch wastes time. This one
  destroyed evidence: a contest that reads as pulled is never mined and never
  reappears on the list, and the only reason the four were recovered is that a
  human noticed four zero-byte files. Verified against the live tree — the scan
  now holds those exact four contests (193403851, 193403935, 193405185,
  193405226) under "not yet settled" instead of linking them.

### Tests

- Seven new tests in a new `AwaitingStandingsSettlementTests`; the pin moves
  719 → 726 (`tools/audit.py`, CLAUDE.md, SKILL.md in this commit). The
  partition test asserts `compute_open` and `compute_unsettled` together account
  for every entered contest exactly once, so a future edit cannot drop a contest
  into neither bucket — which would be the original defect in a new costume. The
  boundary test pins `>=` by checking both sides of it. The ET test pins the
  delegation AND the property that makes it matter: at 01:30 UTC on 08-09 the ET
  date is still 08-08, and the UTC clock's answer is the bug.

## 2026-08-08 — R94: the registry accumulates on every mine, so the runbook's own instruction is finally true

### Fixed

- **R94 — `main` no longer gates the registry update on the `--registry` flag
  (P2).** The archival runbook says, in words, "Do not pass `--registry`. It
  defaults to `data/reference/field_opponent_registry.json`." `field_miner.main`
  ran `if args.registry: update_registry(...)`, and `update_registry`'s internal
  `registry_path or default_registry_path()` was unreachable unless the flag had
  been passed with some value. **A runbook-compliant mine therefore never touched
  the registry, and said nothing about it.** All 31 mines of the 2026-08-08
  tranche skipped opponent accumulation; it was caught only by comparing registry
  `contests_mined` (236) against `own_results` (267), by hand, by someone who
  thought to.
- **The code moved, not the runbook, and the reason is in the runbook itself.**
  Its instruction not to pass a path is load-bearing: passing a bare relative one
  had already forked the registry into two diverging copies, and an earlier
  version of the runbook telling people to do that is what kept it forked. "One
  registry, resolved by the tool" is the intent, so `main` now calls
  `update_registry(args.registry or None, mined)` unconditionally and the flag
  only overrides the location. Its `--help` text says so. The runbook gained a
  dated note recording that the sentence is now true, plus the operator-visible
  contract: **every mine prints either `registry updated: <path>` or a
  `NOTICE: registry NOT updated` line naming the reason, and if you see neither,
  the mine did not do what the step says.**
- **R74(a) still refuses a null identity, and that refusal no longer kills the
  mine.** With the call unconditional, the `ValueError` R74(a) raises for a mine
  with no `contest_id` and no winning entry id would have taken down an
  otherwise-good mine (reachable on a header-only standings export, where
  `parsed_nothing` does not fire because `n_all` is 0). It is now caught and
  reported as a named NOTICE: the invariant holds, nothing null reaches the
  registry, and the JSON, ledger block and own-results row are still written.

### Tests

- Five new tests in a new `MinerRegistryDefaultTests`; the pin moves 714 → 719
  (`tools/audit.py`, CLAUDE.md, SKILL.md in this commit). The regression test
  runs **the runbook's invocation** — no `--registry` — because running the
  flagged form is precisely what hid this for a whole tranche; it patches
  `default_registry_path` and asserts the redirected file gained the contest, so
  the test proves the tool resolves its own path without writing the real
  `data/reference` registry. `MinerMoneyHonestyTests._run` gained `--registry`
  into a temp directory for the same reason: accumulation is now the default, and
  a bare mine from a test would write the live registry — which ARCHIVE happens
  to be mid-rebuild on. **One test was written and then thrown away**, and the
  replacement is the point: the first version asserted `"if args.registry:" not
  in inspect.getsource(fm.main)` and failed against its own explanatory comment,
  which is exactly R91's "assertion satisfied by the wrong text" class. The
  behavioural pin — `update_registry(None, mined)` resolving the default — cannot
  be fooled that way.

## 2026-08-08 — R49(3): a salary file that prices under half the field is the wrong slate, not "full" coverage

### Fixed

- **R49(3) — the structural gate gained a salary join floor (P2).** The gate
  already refused a contest-type mismatch, which is the Showdown-file-on-a-
  Classic-export case. Nothing refused the SAME-TYPE wrong slate. On 2026-08-08
  five 1910_4g contests were mined against the 1235_5g Classic file: join 0.0%,
  every `stack_pattern` empty, every `salary_left` null, record archived
  `coverage: "full"`, exit 0. **`full` with an empty join is worse than
  `standings_only`**, which is honest: downstream shape aggregation reads an
  empty pattern as an 'other' bucket rather than as missing data, so the defect
  presented as a shape finding and survived four days until the tranche analysis
  noticed five winners with no stack pattern. `mine_contest` now computes the
  join rate before the gate rather than after it, sets
  `salary_join_collapsed` below `MIN_SALARY_JOIN_RATE`, and includes it in
  `parse_structural_ok`; `structural_exit_code` maps it to the existing
  `EXIT_WRONG_SALARY_FILE` (4) deliberately, because from the caller's side a
  type mismatch and a wrong slate mean the same thing and have the same remedy,
  and a separate code would imply a different fix. The verification note names
  both ways out: supply this slate's file, or omit `--salary` for the honest
  `standings_only` tier. `emit_ledger_block` suppresses the salary tables on this
  condition too, which is only reachable under `--force`, so a forced archive
  cannot carry a plausible-looking histogram.
- **Why the floor is 0.50 and not 0.95.** `MIN_AUTO_JOIN_RATE` is a SELECTION
  threshold, picking the best of many candidates; this is a SANITY threshold,
  asking whether the file describes this slate at all. A wrong-slate file joins
  near 0% and a correct file with name collisions or withdrawn players joins
  high, so a floor between the two catches the gross case without second-
  guessing a legitimately imperfect file. Recorded limit, in the code comment
  and here: **this does not catch a partial overlap** — a 5-game file against a
  4-game contest sharing 3 games could clear 50% and still archive partly-empty
  patterns. Picking the right file is R49(1)/(2)'s manifest-first resolution;
  this gate is only its backstop, and it is deliberately landed first so the
  backstop exists before the mechanism it backs up.

### Tests

- Five new tests in a new `MinerSalaryJoinFloorTests`; the pin moves 709 → 714
  (`tools/audit.py`, CLAUDE.md, SKILL.md in this commit). The fixture is the one
  the item asks for: two Classic salary files, one naming the players the
  standings drafted and one naming ten different players, so the wrong-slate
  case is same-type-and-0%-join by construction rather than by mocking. Two
  independent guards are pinned separately (`parse_structural_ok` goes false,
  and `structural_exit_code` returns 4), because dropping either clause alone
  must redden something — checked by hand against both mutations. The
  right-slate test pins that the floor does NOT fire at 100% join and that the
  block keeps its salary tables, since a gate that also rejects good input is a
  worse defect than the one being fixed.

## 2026-08-08 — R93: the miner refuses an unwritable `--json` path before it touches anything shared

### Fixed

- **R93 — the mine's last write can no longer fail after its side effects have
  landed (P2).** `open(args.json_out, "w")` was the final statement in `main`,
  so a nonexistent `data/archive/<date>/` raised `FileNotFoundError` at the very
  end — after the `own_results` append, the ledger fragment and the registry
  update had all completed. All 30 mines of the 08-05/08-06 tranche hit it. The
  operator saw a traceback and a nonzero exit saying the mine had not happened,
  while the durable records said it partly had, and re-running after a manual
  `mkdir -p` appended a second row. **The defect was ordering, not a missing
  `mkdir`**, which is why the fix is not a one-liner at the write site: a new
  `check_output_path` runs immediately after argument validation, before
  `parse_standings_export`, and returns a named reason for each way the
  destination is unusable (the path is itself a directory; a FILE sits where the
  parent must be; the parent cannot be created; the parent is not writable). A
  refusal exits the new `EXIT_OUTPUT_PATH_UNUSABLE = 8` and says in as many
  words that nothing was written, so there is nothing to undo before retrying.
  Materializing the parent directory in the check rather than at write time is
  deliberate and noted in the docstring: the directory is the part that fails
  for reasons the caller must fix, and a successful mine's archive move creates
  `data/archive/<date>/` anyway, so the check adds no state the mine would not
  have written. Exit 8 is distinct from all six existing codes, pinned by a test,
  because a scheduled task has to tell "I cannot write there" from "this is the
  wrong salary file" without parsing prose.

### Tests

- Four new tests in a new `MinerOutputPathTests`; the pin moves 705 → 709
  (`tools/audit.py`, CLAUDE.md, SKILL.md in this commit). The load-bearing one
  is `test_an_unusable_json_path_fails_before_any_side_effect`: it plants a FILE
  where the parent directory would go and asserts the registry was never
  created, no ledger fragment was written and no own-results row was appended —
  the ordering property, not the `mkdir`. `test_check_output_path_names_each
  _refusal` pins each reason string, and the distinct-exit-code test pins the
  code separation by value. Every invocation in the new class passes
  `--registry` into a temp directory: a bare mine accumulates by default once
  R94 lands, and a test must never write the real registry.

## 2026-08-08 — backlog merge: R93–R96 filed, R49 gains its zero-join gate, R37/R39/R40 decision inputs appended, eight fragments consumed

### Changed

- **Four items filed from ARCHIVE's five 2026-08-08 tooling fragments, and one
  fold.** All five came out of mining A-035..A-037 (31 contests, ledger 3.18),
  none touches the certified path, and every one of them is a tool that
  reported success while doing nothing or did work in an order that left side
  effects behind a failure — the archival-side view of the R51/R92 family.
  **R93** — `field_miner` raises `FileNotFoundError` on its own `--json` path
  when the archive date folder does not exist, AFTER the `own_results` append
  and the fragment write have already landed, so the operation is not
  retry-safe (all 30 mines of the 08-05/06 tranche hit it). **R94** — a
  runbook-verbatim mine never touches the opponent registry: the runbook says
  omit `--registry`, `main` gates the call on the flag, and
  `update_registry`'s internal path default is unreachable without it; 31
  mines skipped accumulation silently, caught only by comparing registry
  `contests_mined` (236) against `own_results` (267). **R95** (P1) —
  `awaiting_standings` enrolls contests whose slate has not settled, DK serves
  a zero-byte export pre-settle, and a zero-byte inbox file then satisfies the
  by-filename "pulled" test, which is the R74(b) direction: four contests were
  lost this way on 08-08 and recovered only because a human noticed the file
  sizes. **R96** (P1) — a filled, entered `DKEntries` file exists in
  `outputs/2026-08-06/` with no manifest row, no `runs/` directory and no
  staged salary; it fails closed at preflight but sits outside supersession
  tracking and the sha256-at-upload check, and it permanently caps those five
  contests at `standings_only`. R96 absorbs the unnumbered R36 finding (three
  such files under `outputs/2026-07-29/`, plus R29(2)'s refused-promotion
  window) because the state has now recurred across three months and two
  contest families, which makes it a defect in the delivery path rather than
  an incident. The fifth fragment was folded rather than numbered: **R49(3)**,
  an explicit wrong `--salary` joining 0.0% archiving as `coverage: "full"` at
  exit 0 — it belongs behind R49's manifest-first resolution as the backstop
  for a resolution that picked wrong, not as the primary mechanism.
- **Three decision inputs appended, no decisions taken.** **R37** gains the
  third tranche: `<=3-primary` negative a third consecutive time (-9.8pp
  [-18.0,-1.6]) while our own share of it climbed 7.0% -> 21.5% -> 26.3%, and
  the 08-04 "5-2-1 decayed under crowding" read did not survive (+13.6pp
  [5.6,21.6] on a 21.6% field share; lift has moved opposite to field share
  all three tranches). Net: the floor-first leg strengthens, the
  narrow-breadth floor-5 leg is restored, and one build requirement is added —
  a five-stack quota should read the shape's current field share rather than a
  pinned lift constant. **R39** gains a measured payoff and leaves the
  opportunistic tier: the 3.18 review had to re-parse 64 archived showdown
  CSVs by hand to see captain choice at all (winner CPT own 14.8 vs field
  13.0; top-owned captain won 22/85; our tranche captains chalkier than the
  winners), so landing `captain_norm` converts a session-sized one-off into a
  standing table and makes a captain-spread policy decidable. **R40** gains
  the first cash-line anatomy, which complicates its own premise — in
  satellites the winner and the last seat look alike (chalk percentile ~31,
  4-primary median) while the band just outside the line is chalkier and more
  5-stacked — plus a method requirement: grade candidate profiles against both
  the mean-delta and the percentile statistic, never either alone.
- **"What do we tackle next" amended, no R-numbers reassigned.** Two order
  changes, both argued in the entry: the archival-tooling trio (R95 + R93 +
  R94) moves to position 2 because R95 is the only open item losing evidence
  on a recurring basis, and R39 moves from the opportunistic tier into the
  numbered queue on 3.18's measurement. R37 stays at 1 and stays Ben-gated.
  Eight consumed fragments moved to `_to_delete/`; deletions recorded in this
  commit.

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
