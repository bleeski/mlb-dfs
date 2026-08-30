# Backlog | MLB DFS Engine | live

**This is the single live backlog, and it holds OPEN work only.** The contract
(Ben, 2026-08-01): when an item is completed, its entry — What/Why/Fix and the
landing record — MOVES to `CHANGELOG.md` in the completing commit, so the
changelog is the one place that says when a thing changed and why, and this
file stays the one place that answers "what do we tackle next." Enforcement is
`audit.changelog_debt`, which now watches the full DEV write set (engine,
tools, tests, skills, docs, CLAUDE.md; inbox fragments exempt). Everything
closed before 2026-08-01 was migrated in one pass and lives under "Imported
record" at the bottom of CHANGELOG.md, amendments included.

Same item grammar as v2: What, Why, Fix; priorities P0 (corrupts what gets
uploaded or lets an invalid file certify), P1 (silently degrades lineup
quality or destroys evidence), P2 (wastes time or tokens); effort S/M/L.
Supersedes the v1 board (`docs/legacy/MLB_Classic_Backlog.md`, the B-1..B-14
era) and, from 2026-07-27, its own open remainder in place — item numbers
preserved (no renumbering, ever; R-numbers are cited in commits, tests, and
the ledger). **Renamed `docs/2026-07-27_backlog_v2.md` -> `docs/backlog.md` on
2026-08-17**, R127's commit: the dated name read as a July artifact three
weeks of amendments later, and a file whose whole job is answering "what
next" should not be named after the day it was opened. Same file, same
numbers, `git log --follow` carries the history.

Organized by WORKSTREAM as of 2026-08-10 (Ben's instruction): after the queue,
every open entry sits in the workstream whose surface a DEV session would
touch, entries verbatim, filing provenance on each header line. The old dated
tranche wrappers live under "Board history". Completing an item still
migrates its entry to CHANGELOG.md in the completing commit, and the next
free R-number comes from scanning this file AND the changelog, never this
file alone (the R102/R103 lesson).

---

# What do we tackle next

Any session may read this; only DEV edits it. The full amendment history
lives under "Board history" near the bottom of this file.

Ordered, with the reason:

*2026-08-30 (third note this date), DEV, claim `engine` (`engine_2026-08-30`,
re-taken): **backlog inbox merged. Three 08-30 BUILD fragments consumed, TWO new
numbers (R276, R277), FOUR riders on existing entries, and ONE item half-closed.
The queue gains a slot at 13; only the old 13 and 14 renumber.**

**Why only two numbers for four fragments.** Three of the fragments' findings
already had a class on this board and the R167/R159 lesson says a second number
for one class is how the two copies start disagreeing. The measured cost of
Showdown's APPG ranking (three confirmed starters at 0 of 10 entries, all three
with POSITIVE xwOBA-minus-wOBA gaps) is R249's first MEASUREMENT, not a new item;
the missing Showdown `enrichment` block is R237's NOT_APPLICABLE clause seen from
the brief side rather than the qa side, and it goes there as a third sighting
plus a Fix addendum; the $10,300 salary-left Classic lineup is R247's first
non-Showdown sighting. Only the standing QA step and the `qual=y` condition had
no home.

**R277 is the finding worth reading twice.** `refresh_reference_data.py:83` builds
the FanGraphs pitching export with `&qual=y`, so the file holds 211 arms against
Savant's 831. Verified on disk at this head: Kikuchi 0 hits in
`fangraphs_season_pitching.csv`, 1 hit in `expected_stats_pitching.csv`. He took
the neutral K-rate default, which ranked him SECOND of four arms on
`Ceiling_Multiplier` (1.420) above two measured arms, while Savant puts him
between the two of them on contact suppression. He was in 4 of 7 entries. **This
corrects a verified claim already on this board:** the 2026-08-16 merge pass
recorded Dobnak's absence from the same file and attributed it to the 30.2-day
staleness the warning reports. The absence was real, the attribution was never
checked, and it is wrong for this class. Every non-qualified starter takes the
neutral default all season and no refresh changes it, so the warning's printed
remedy provably cannot fix the case it fires on.

**R196 is half closed and its Fix line was wrong.** The Solo Shot and Micro
Booster rows were written to `dk_contest_archetypes.csv` on 08-30 (both verified
in the file at this head), which closes the "no row" half after six sightings.
But R196's Fix specified shape `single_entry_gpp`, and `single_entry_gpp` is
inside `WTA_CONSTRUCTION_SHAPES` (`contest_shapes.py:96-99`), which
`execution_pipeline.py:4562` reads to pick max-concentration construction. The
entered contest paid 350 of 1486, breadth 0.235, against that shape's curated
0.01. Writing the row exactly as R196 specified would have PINNED WTA
construction onto a broad-curve contest on every future slate, where the refusal
at least forces a human to name a posture. The remainder is renamed: the table
cannot express "single entry, broad curve," because posture inference reads
`inferred_type` and nothing reads `payout_shape_default`.

**Board corrections.** `ledger/inbox/` is ARCHIVE's and this session wrote nothing
there. Its `_CONSUMED_2026-08-22_DO_NOT_REMERGE.md` says all 108 miner fragments
and four of the five dated fragments were merged on 08-22 and only the DELETION is
outstanding, blocked then because the mount refused `rm`. **That blocker is gone:
`_to_delete/` now exists and is gitignored (`.gitignore:85`), so an ARCHIVE session
can finish the close-out with `mv`.** The one genuinely unconsumed file there,
`2026-08-28_DEV_3-21-five-stack-line-now-stale.md`, is a Quick Card reconciliation
and its backlog half is already R37(2)(c); no board change was owed.
`docs/backlog_inbox/2026-08-09_DEV_ben-decision-curated-satellite-archetypes.md`
is RETAINED, unchanged, for the fourth inbox pass: three entries cite it as the
sole carrier of the nine-family table and the four cautions.*

*2026-08-30 (second note this date), DEV, claim `engine` (`engine_2026-08-30`,
re-taken): **slot 1 is CLOSED and REFILLED, not vacated. All four of R228, R172,
R173 and R176 shipped, in that order, as four separate commits with the gate run
between each.** Gate 1461 -> 1489 (`test_upload_integrity` 269 -> 297, `grew`).
The CHANGELOG entries of this date carry the migrated text and the R233
enumerations. **The queue is still FOURTEEN slots and nothing below moved.**

**Why the slot did not vacate.** Its four items' own R233 enumerations produced
two replacements of the same class, both P1/S, both a file from the money
boundary: R273 (filed 08-30 from R158's enumeration; the Classic joint allocator
records a clock expiry as `direct_constraint_failure`) and R275 (filed here; the
preflight skips its contest cross-check on an empty `contest_ids`, and a row with
no `certification` still earns `upload_ready`, the one label CLAUDE.md reserves).
Promoting slot 2 over those would put a weaker claim at the head, and vacating
would renumber thirteen entries for no gain. R273 was deliberately NOT folded into
this batch: it is on the Classic certified path, it needs its own coverage, and
four items was the commit's limit.

**What this batch is, in one line each.** R228: an absent artifacts row promoted a
run in silence where a hash MISMATCH refused loudly, at the one boundary CLAUDE.md
calls immutable; fail-closed, with a `--force-unbound` that exits 4 and writes the
unverified bind onto the row. R172: the value guard is an internal Base cap, not
enrichment, so every default build stamped `projection_tier: "enriched"` on a
permanent record including builds with zero external data. R173: `if report:` was a
truthiness test doing a content check's job, so a metadata-only stub certified the
lineup gate while `pool_report=None` correctly blocked — the weaker input
certified. R176: the salary gate read the PROJECTION schema under an evidence
string naming a salary validation that never ran, two assertable gates went
unrecorded, a certification key was a literal, two excepts were silent, and the
preflight's exit code was computed before the stamp that makes it durable.

**The finding worth carrying forward: two of the four defects had a PASSING TEST
over them.** R172's `guard-only == "enriched"` was pinned by R64(b); R176(a)'s
`assertIn("salary CSV schema validation", ...)` pinned the exact string the item
filed as false, on the exact path the item says never opens the salary file. This
board already knows a test can stop guarding what its docstring claims (R223,
08-30). This is the harder version: a test that guards the defect itself, green,
for weeks. Both are now inverted with the reason written beside them. A third
case is adjacent and different — `GateAssumptionVersusOverrideTests._merge`'s
precondition moved underneath the R176(a) fix and quietly converted a REFUSAL
test into an assumption test; the precondition was restored rather than the
assertion relaxed. **Neither greenfield review nor R233's grep finds this class:
the enumeration counts SITES, and a test pinning a site reads as coverage.**

**Board corrections.** `claims/engine_2026-08-20` and `engine_2026-08-28` are both
still HELD with `released_utc: null`; unchanged, Ben's to arbitrate. R274 (the
suite appends to `outputs/2026-06-03/` and `outputs/2026-06-11/` manifests on every
run) is untouched here and is ARCHIVE's. The `tools/_scratch_*` directories from
closed slates are still on disk; this session swept its own.*

*2026-08-29 (second note this date), DEV, claim `engine` (`engine_2026-08-29`,
re-taken): **one more BUILD fragment, from the `1305_12g` repair slate, and it
is the first this month to force a RESEQUENCING rather than a rider. Six new
numbers, R267–R272, and a new slot 3; everything below moved down one and
nothing jumped.** The fragment is the post-mortem of a live repair: COL's
probable moved from Feltner to Agnos after delivery, putting a dead arm in 10
of 31 entries with 45 minutes on the clock.

**The defect that earns the slot.** `late_swap` matches WHOLE-LINEUP candidates
out of the bank against an entry's pins. Late in a slate an entry has 3 to 9
slots frozen in locked games and no generic bank lineup reproduces that exact
prefix, so the refusal is structural and **growing the bank cannot touch it** —
566 → 1425 candidates across six invocations, message unchanged. One entry had
9 of 10 slots locked, only P2 open, $5,300 of cap: a one-slot search over ~1100
salary rows, which the engine spent 13 minutes failing to find because it was
searching the wrong object. The repair was hand-built and the hand-built file is
what shipped. R267 is that filter; R272 is Ben's dated instruction that makes
running it unattended legitimate, and they land together because neither is
much use alone.

**Ben's instruction, quoted, because it is the reason this fragment exists:**
*"you made me intervene by answering questions and I want you to make those
changes autonomously."* BUILD raised two questions inside the lock window and
both came back "recommended option" — the tell that the question was the
session's to decide. R272 adds the category CLAUDE.md's Autonomy section does
not have: **repair is not strategy.** Replacing a player who will not play,
choosing among the mechanically legal replacements, and taking the minimum-loss
collateral downgrade are all autonomous; what stays Ben's (exposure and stack
changes with no dead player behind them, `--force`, a failing gate, any pool
reduction, the money wall) is unchanged and the entry says so, so the edit
cannot overreach.

**Two shipped fixes whose symptom never closed, and that is a check this board
does not run.** R268 pairs them deliberately: R29(3) unified control resolution
into one function and the swap still derived 0.50 against a parent that shipped
0.55, which when most rows are frozen is unsatisfiable by construction; R29(2)
deferred promotion to kill the `--allow-parent-mismatch` habit and the flag was
still needed on every call. Both fixes were correct about their mechanism. **A
fix that eliminates a documented workaround is not done until the workaround
stops being typed**, and neither was verified that way.

**One correction to this project's own documentation, measured three ways.**
CLAUDE.md and SKILL.md say a Cowork bash call dies at 45 seconds and build a
25-to-33-second budgeting rule on it. The real ceiling is ~180 s. BUILD measured
it (`Command timed out after 177999ms`, 150-165 s calls completing); this
session re-measured it independently (`sleep 100` under an explicit budget,
19:29:12 → 19:30:52); and the project's operating memory has said ~178 s for
some time. It is filed P1 despite being a text edit because sessions ACT on it:
a feasible joint MILP on this slate needed 53-156 s and could never have fit in
45, so the pre-lock build looked unsolvable when it was not. R152's other two
claims — backgrounding does not survive the call, and a killed `audit.py`
strands the next commit on a zero-byte lock — are independent of the number and
still hold.

**The remaining two.** R269: re-promoting a superseded run mints a second
filename for identical bytes and leaves the first blocked, same sha256, one
current and one superseded, during a repair sequence. R270: the doubleheader leg
matcher exists on the odds path and not the lineups path (four teams read as
"zero starters," indistinguishable from "not posted" — R237's conflation
arriving through a different door), and separately the schedule hydrate drops a
game's lineup once it starts, so "confirmed" silently degrades to "not posted"
for exactly the games whose answer is certain; the boxscore is the authority
after first pitch and belongs in the intake ranking.

**Three riders, no new numbers.** R204 gains its sharper half: the grow-the-bank
hint fires after `max_candidates = max(n_entries * 12, 60)` has already capped
growth, which is the one remedy CLAUDE.md makes always-permitted being
recommended when it cannot work. R193 gains the stale-apex column, its own class
one column over. And "Kept as-is" gains three components that each caught a real
failure on this slate — the preflight caught both live ones unaided,
`verify_export` caught the session's own repair bug (a hitter opposing its own
rostered SP), and qa's frontier correctly rejected two attempted improvements —
recorded so a future refactor does not weaken a working check while "fixing" the
item filed against it.*

*2026-08-29, DEV, claim `engine` (`engine_2026-08-29`, bare mutex): **the
backlog inbox is consumed — three fragments merged, one KEPT by design, and
the only structural change is that a sequencing note this board printed twice
was WRONG and is corrected.** One new number, **R266** (the preflight can
catch per-contest captain duplication today), into slot 2. The queue's
thirteen slots are otherwise unchanged; nothing was resequenced.

**The correction, because it is the reading worth keeping.** R239 has said
since 08-27 that its round-robin dealing half "can land first and alone," and
slot 5 repeated it. The 08-29 fragment disproves it arithmetically rather than
by argument: on `2215_1g_sd` the bank's captain multiset was (5,5,4,4,1,1,1)
against contest sizes (7,7,2,2,1,1,1), which fails Gale-Ryser at k=3 (14 > 13),
so NO permutation of that bank could have produced a clean file. Dealing cannot
create diversity the bank does not contain. The consequence is that (b) stops
being "evaluate the caps per contest" — evaluation after the ladder runs can
only report a bind it is too late to satisfy — and becomes a binding value at
construction plus a feasibility precondition on the apportionment. (a) now
depends on (b), and (c) — which costs nothing and is what makes the other two
measurable — goes first. **This is R153's lesson one level up:** R153 said a
cap enforced anywhere other than where the roster spots are spent is not a cap;
this says the same sentence with POPULATION substituted for enforcement point.

**Second reading: the sighting reached Ben, not the artifact.** A 2-entry
contest shipped both entries on one captain and a 7-entry satellite shipped one
captain on three, while `captain_exposure.realized_max_pct` read 23.8 under a
0.25 cap, `cap_relaxed_slots 0`, and `counted_relaxations.clean true`. Every
one of those is true and none describes what was entered. That is why R266
exists and why it is filed as P1 despite being an S on a reporting surface: the
engine fix is months of queue away, the preflight already holds both halves of
the check six lines apart, and it is the only surface that can catch a
hand-permuted file — which R239 records has happened twice.

**Fragment disposition.** Three consumed and deleted:
`2026-08-29_BUILD_r239_fourth_sighting_captain_axis.md` and
`2026-08-29_BUILD_per_contest_captain_duplication_fix.md` (both into R239 plus
new R266 plus two Tier 4 decisions),
`2026-08-28_BUILD_showdown_postures_and_qa_shape.md` (three items, ALL of them
second sightings of already-filed numbers: §1 upgrades R210(c) from "may be a
silent no-op" to verified-by-grep, §2 is R237's Showdown face recurring, §3 is
R248 hitting a second slate). **Nothing in that fragment needed a new number,
and that is the healthy reading, not a wasted filing** — three independent
recurrences inside two days of items filed 08-23 and 08-27 is the board
working. The 08-09 curated-archetypes fragment is KEPT for the third
consecutive inbox pass and now carries a RETAINED header saying so, because
this board names it as the sole carrier of the nine-family table and the
inbox's own contract is "the owning role merges and deletes consumed
fragments." It has survived on a reader noticing; the header is the cheap fix.

**Board corrections.** `claims/engine_2026-08-20` is STILL HELD with
`released_utc: null`, nine days old, alongside the stale `slate_*` beacons and
`slate_2026-08-13_1310_6g`'s hand-written RELEASED marker (R102). Unchanged,
Ben's to arbitrate. The three `tools/_scratch_*` directories from closed slates
are still on disk, still gitignored, still not swept.*

*2026-08-28 (third note this date), DEV, claim `engine` (bare mutex, re-taken):
**the queue head is CLOSED. R205 landed and is migrated; R236 landed in part and
its entry is REWRITTEN as R236(b) to hold only the remainder.** Gate 1331 -> 1351
(`test_core` 902 -> 911 and `test_paste_lineups` 87 -> 98, both `grew`), and the
MODULE count moved for the first time in this file's history, 26 -> 27, on
`mlb_engine/intake/paste_odds.py`. The CHANGELOG entry of this date carries the
record, the migrated R205 text, and the R233 enumeration. The list below is
RENUMBERED rather than annotated, so it is thirteen slots and slot 1 is R172 +
R176 + R173 + R228; every slot moved up one and nothing jumped.

**Two readings, and the first is about batching.** R205 and R236 were filed as
"one rides the other" and that was RIGHT for once, in the direction the fragment
argued: a paste tool emitting N book columns into the old parser would have
reintroduced the averaging bug through a new door, so the fragment asked for one
named book until R205 landed. Landing R205 first made the second half emit every
book instead, which is strictly better input. That is the opposite of the last
three sessions' batching lesson (R234's "one shared helper" that was two, R167's
"third copy" that was a fourth): a batch justified by an ORDERING dependency held,
where the ones justified by a shared surface did not.

**Second, and it is the reason R236 did not close.** The item's fix list is an
acceptance list, and one line of it — "the Action Network odds table text" —
could not be built honestly, because the real captured text is not on disk and a
parser for a pasted format has to be pinned against the format as it arrives
(R32's founding rule for that suite). What shipped is the tool, its refusals, the
round trip and the SKILL.md lines; what stayed is one capture and one fixture.
The entry was rewritten to hold that remainder rather than migrated whole, per
the partial-landing practice.

**Two new numbers, both P2/XS, both into the smalls slot: R264** (three
independent American-odds -> probability implementations, the R159 class on the
rule R205 just made load-bearing) **and R265** (the paste tools' zero-network
contract is asserted at module scope while both reach the fetchers lazily at call
time). They are one move — the `team_codes` boundary again — and are filed to be
landed together. **One rider on R10**, carrying forward R205's own observation
that F1 accuracy and lineup-source confidence interact; it was always Ben's and
was never the parser's to fix.

**Board corrections.** `claims/engine_2026-08-20` is STILL HELD with
`released_utc: null`, eight days old, alongside four stale `slate_*` beacons and
`slate_2026-08-13_1310_6g`, whose hand-written RELEASED marker does not release
it (R102). Unchanged, still Ben's to arbitrate; this session took the bare
`engine` mutex, which re-took the released dated name rather than minting a
sibling. `tools/_scratch_1835_9g/`, `_scratch_archive0822/` and `_scratch_r159/`
are still on disk from closed slates — gitignored, so they block nobody, but the
sweep rule says a patch that outlives its slate is a hazard rather than clutter.
Not this session's to delete; named so the next DEV session does not rediscover
them.*

*2026-08-28 (second note this date), ARCHIVE, claims `ledger`+`inbox`, backlog
write under Ben's dated scoped exception for this session: **the greenfield
standings mine is in — 610 contests (361 Classic / 249 Showdown, 2026-06-03 →
2026-08-27, a strict superset of the root doc's 422), filed as ledger 3.21, and
the root `STANDINGS_GREENFIELD_FINDINGS_2026-08-28.md` is adjudicated
finding-by-finding: zero rejects, three modifies** (paid-place coverage is
97/610 via the parked reference json, not 0/422; "ours already much chalkier"
holds on the punt-count metric only, while cumulative ownership runs −7→−21pp
vs field and drifting down; the Showdown-prediction DATA BLOCKED call is stale
post-R235 — 34 contests grade at rho 0.542). Board changes: dated riders on
R37(2) (the floor-4 tranche measurement its (a) gate asked for now EXISTS),
R10 (fit unblocked at 610 contests; compression is the error shape; SD fits
post-R235 only; satellite temperatures drift), R254 (captain chalk FLIPS sign
with field size), R258 (seed threshold table; the satellite threshold IS the
win line), R225 (third independent confirmation, interim role-aware counts),
R30 (97 parked contests backfillable today); one new item, R263 (Tier 4
decision + S shadow-report build). No queue resequencing; the lane gains
evidence, not new spine slots.*

*2026-08-28, DEV, claim `engine` (`engine_codex_lev_synthesis_2026-08-28`):
**the ninth outside edition (Codex, this time reviewing the R251–R262 lane
itself, zero drift at `0a83cac`) is adjudicated: zero new numbers, twelve
dated riders/amendments on the lane's own entries, one retitle (R252), and
the ninth rejection of the rebuild program.** The queue's fifteen slots and
Tier 2's spine order are untouched; what changed is the SPECS of unbuilt
items, corrected in place before anyone builds them. The one that changes
math: R258's predict half is now the CONDITIONAL threshold `T[s,c]` — own
scores and the top-1% line co-move because they come from the same slate,
so a threshold predicted independently of our outcomes biases P(own ≥ T) —
and its covariate columns are named into the one R48+R83+R258 mining batch
BEFORE that batch runs. The rest: R262's weighted sum is replaced by an
epsilon-constraint frontier (Ben picks the operating point once, Tier 4
unchanged); R261 gains slate-wide shared scenarios, an MC-error line on
every P̂, DESIGN/SELECT/REFEREE bank purposes, and the CPT/UTIL
one-outcome guard; R255 gains the tail-axis grade and
predeclare-the-metric discipline; R260 the pitcher↔opposing-hitter
negative-dependence row plus shrinkage and per-cell SEs; R253 the
market-total ablation; R254 a captain-OPTIMALITY stage 2 behind R261; R252
the vector interface and the both-markets sentence; R256, R259, R10 and
R141 one sentence each. Rejections in "Do not build (updated)", ninth
paragraph: the field/settlement ordering again, contest routing (the money
wall), ensembles/CVaR before any model grades, §2.4's signal shopping list
(enters only through R255 residuals), the register ceremony, and the
"module cap" misread (it is an inventory pin). Edition archived at
`docs/2026-08-28_critique_leverage_portfolio_codex.md`. Full reasoning:
this date's CHANGELOG entry.*

*2026-08-27 late, second note (UTC 2026-08-28), DEV, claim `engine`
(`engine_backlog_greenfield_2026-08-28`): **Ben opened a greenfield lane, by
dated instruction: find data-driven leverage (skill signals the salary file
and the field have not priced, Showdown especially), and get materially
better at the dual objective — which he refined to "maximize P(top ~1% of
field) per contest; minimize P(total washout) per portfolio." Filed:
R251–R262, twelve items, all in Tier 2's lane.** The design in one breath:
the mispricing machine is one score per player against TWO anchors (salary →
value, projected ownership → leverage), component-attributed and graded every
slate like the ownership prior already is; and the dual objective stops
requiring a field simulator, because the archive's standings hold every
contest's realized score curve — predict the THRESHOLDS (top-1% line, cash
line, ticket line) per archetype, model our own portfolio's joint outcomes
against them, and the two goals become one scenario-coverage solve. The
sim-gate's four clauses become the roadmap's acceptance criteria rather than
a wall: R259 is the variance basis, R260 the correlation structure (minable
from archived FPTS today), R261 designs in separate banks and joint
own-entry settlement, and R10 + R13 still gate anything field-conditioned
and the production switch (R262, Tier 4 decision). Truthful labels hold
throughout: everything ships as a labeled prior or a pre-lock prediction
graded in the ledger BEFORE it is allowed to steer selection.

**The defect queue's fifteen slots are unchanged**, with two rides: R257
(kill-matrix extension to teams, arms, and the Showdown script axis) rides
slots 6–7's sessions, same surfaces; and R251's CAPTURE half — the morning
odds snapshot and the per-slate expected-stats freeze — rides the next
session that touches a slate, because every slate that passes uncaptured is
grading data lost forever (R135's own argument; `data/odds_history/` holds
two files, both July, measured this session). Tier 2's spine is resequenced
in place; the do-not-build section gains the dated scope paragraph narrowing
the sim line. Full reasoning: this date's second CHANGELOG entry.*

*2026-08-27 late (UTC 2026-08-28), DEV, claim `engine`
(`engine_backlog_resync_2026-08-28`): **the eighth greenfield edition is
adjudicated and the inbox is consumed. Docs only — no code moved.** The outside
spec (Codex) re-reviewed at exactly this HEAD (`245de51`), the first external
review with zero drift against the live tree: 50 findings (F-01..F-50), a
target architecture, and a DO_NOT_UPLOAD-as-EV verdict that is this project's
own Truthful-labels rule restated. Filed: **R236–R250, fifteen numbers**, most
of them carrying BUILD fragment evidence the spec independently confirmed.
Twelve inbox fragments consumed (every one except the 08-09 curated-archetypes
fragment, KEPT by design); scope riders added to R216, R174, R176, R118, R196,
R229, R230; rejections recorded in "Do not build (updated)". The audit line
this session: `PASS v2.26.0 26 modules` WITHOUT the test gate — deliberately
not run, because this landing touches `docs/` and `CHANGELOG.md` only and the
next code landing must run it regardless. The spec file itself replaces the
ed7 edition at `docs/DFS_SYSTEM_GREENFIELD_SPEC_CODEX.md` (git history carries
the old one).

**The synthesis, in three sentences.** Twenty-nine of the fifty findings are
already on this board (the corroboration list below), eleven are the week's own
BUILD fragments read back with line numbers, and the genuinely new matter is
five smalls plus one good idea adopted as a rider (settle R118's replays at the
archived payout curve, so counterfactuals read in dollars — exact accounting
over observed fields, not simulation). The rebuild program is rejected for the
eighth consecutive time on the same ordering argument: it builds the
scenario/field/settlement stack first and measures second, while Tier 2 reaches
the same destination from the archive that already exists. Section 1.9 of the
spec deserves naming: it maintained a resolved-defects list instead of
re-reporting repaired work, which no prior outside edition did.

**What the week's field evidence changes: Showdown moves up.** Eight of the
twelve consumed fragments are Showdown, from three builds in four days, and
they converge on one fact — the format Ben now plays daily has no contest
awareness (no shapes, no per-contest caps, positional entry assignment,
no projection input) and its caps hold while inverting captain leverage and
degrading the bank tail invisibly. The 08-26 fragment PROVED controls cannot
reach a contest slice (identical 20-entry Dime Time under two control sets),
and two live deliveries have now shipped via hand-permutation with waived
identity checks, which is a money-boundary hazard, not a style problem. The
Showdown cluster therefore runs directly behind the money-boundary batch
instead of at slot 10.

**Fourteen slots as of 2026-08-29** (thirteen when this paragraph was written on
08-27; slot 3, the repair path, was inserted that date and everything below it
moved down one). **Dependencies bind where stated.**

*Amendment 2026-08-29, DEV, claim `engine` (scope `r239_captain_partition`):
**R266 and R239(b)+(c) all SHIPPED.** Gate `1386 -> 1443`
(`tests.test_showdown` 91 -> 133, `tests.test_upload_integrity` 254 -> 269).
Four commits, each landed and gated on its own: R266 the preflight guard, the
R239 partition seam, R239(c) the per-contest slice, R239(b) the cap that binds.
Reasoning and the R233 enumerations are in CHANGELOG.md.*

***The queue did NOT resequence and is still fourteen slots.*** Nothing moved
up or down; two slots lost members. **Slot 2** drops R266 and is now
R174 + R175 + R248 + R242 — it landed alone exactly as its own note said, and
its landing changed nothing about the other four. **Slot 6** keeps its position
behind the money-boundary batch and its R238-first order, but the R239 half of
it is now **R239(a) alone**, the round-robin deal, which still consumes R238.
**Slot 3, the repair path, is untouched and remains slot 3.*

*Three corrections R239's own text needed, all made in its entry: its R233
enumeration claimed all six `exposure_cap_count` call sites "take the same
correction" and in fact all six are deliberately kept (they are the PORTFOLIO
caps, correct against the entered total; the defect was that no per-contest cap
existed); `max_cpt_per_contest` is a named control at 2 rather than the 1 the pct
would derive; and a FLAT cap of 2 does not kill the 2-entry-at-100% case it was
chosen to kill, so the bar is `max(1, min(m, n - 1))`. **One open decision for
Ben, already in Tier 4:** whether that control becomes 1 (fully distinct captains
in any contest up to seven entries). It is a one-value change, and the realized
per-contest counts now ship in every brief so it can be priced against R247's
frontier. R240 (punt-captain template) becomes load-bearing if the answer is 1.*

*Amendment 2026-08-28, DEV, claim `engine` (`engine_2026-08-28`): slot 1 is
CLOSED. R212, R213, R214 and R215 all landed in that order, entries migrated to
CHANGELOG.md, gate 1313 -> 1331. The list is RENUMBERED rather than annotated,
per the standing rule, so it is fourteen slots and slot 1 is R205 + R236.
**R203's precondition is met**: R214 landed, so the supervisor now preserves an
operator's `--controls-override` instead of dropping it, and slot 10's R207 +
R244 pair is unchanged. R216 (slot 7 now) still lands alone.*

*Amendment 2026-08-30, DEV, claim `engine` (`engine_2026-08-30`, scope
`r250_captain_budget`): **slot 5 is DRAINED of its first three items.** R158,
R223 and R250 all landed, in that order and in three separate commits, entries
migrated to CHANGELOG.md. Gate **1443 -> 1461** (R158 +6, R223 +5, R250 +7);
CLAUDE.md's quoted session-start line moved with it each time.*

*Slot 5 KEEPS its position and is now **R247 + R237 + R224**. It does not move up:
the three that closed were the ones with a dependency argument for going first
(solver status before anything trusting a solve result, the fourth counter before
`clean` was recomputed from realized caps), and what remains is visibility and
smalls — R247 reports a trade it does not change, R237 is a factor split for two
qa reads, R224 is XS. Nothing above slot 5 gained or lost evidence this date, so
renumbering would be churn. Still fourteen slots.*

*Two items FILED this date, both found by the R233 enumerations rather than by
review, and both deliberately left rather than fixed: **R273** (the Classic joint
allocator at `contest_allocator.py:1276` files a clock expiry as
`direct_constraint_failure` — R158's inversion with a worse label, on the
certified Classic path behind the golden replay) and **R274** (the test suite
appends to `outputs/2026-06-03/` and `outputs/2026-06-11/` manifests on every
run; ~1400 fixture deliveries now sit in the tree the archival miner globs).
Neither belongs in a Showdown stage. R273 is DEV's and wants Classic coverage
written for it; R274's cleanup half is ARCHIVE's.*

*One correction to the record, in the R239(b) family: its guard
`test_the_floor_rung_keeps_the_per_contest_cap_when_it_drops_the_others` was a
SOURCE-TEXT grep for a literal. R223 moved that literal to a different rung and
the test kept passing while its docstring went false. Rewritten behavioural.*

1. **R273 + R275** — the false-evidence slot, REFILLED 2026-08-30 rather than
   vacated. **R172, R176 (with ed8's F-34 rider), R173 and R228 all SHIPPED
   2026-08-30** (see CHANGELOG.md), in that order and as four separate commits.
   What replaces them is the same class found by their own R233 enumerations,
   both P1 and both S: **R273**, the Classic joint allocator discarding a
   time-limited incumbent and recording `direct_constraint_failure: True` for a
   clock event (found by R158's enumeration at `00f0995`, and R158's fix for the
   Showdown face of it is the template); and **R275**, the preflight's own
   fail-open pair, where an empty `contest_ids` skips the contest cross-check and
   a row with no `certification` still earns `upload_ready`.
   **The slot keeps its position and the queue stays at fourteen.** Both
   replacements meet this tier's stated criterion (verified P1 silent-wrong-output
   at S lift) and both sit one file from the money boundary, so promoting slot 2
   over them would put a weaker claim first; and refilling costs no renumbering
   where vacating would move thirteen entries for no gain. R273 is the heavier of
   the two: it is on the Classic certified path, it needs its own Classic coverage,
   and the 08-30 batch deliberately did not fold it in on the grounds that four
   items was already the commit's limit.
2. **R174 + R175 + R248 + R242** — the money-boundary batch, grown by
   two field hits from this week: the preflight's feed matcher has no AZ→ARI
   crosswalk and silently demotes ten hard checks to warnings (R248, F-33,
   and it hit a SECOND slate 08-28), and the salary auto-resolve still reaches
   across draftgroups before refusing (R242, F-11's surviving sliver). F-31
   rides R174: `late_swap.py` prints the preflight command and returns success
   without running it. **R266 SHIPPED 2026-08-29 and is out of this slot**; it
   landed alone as its own note said it would, and its landing changed nothing
   about the other four.
3. **The repair path: R267 + R272, then R268, R204's ceiling half rides** —
   **INSERTED 2026-08-29, the one resequencing this date; everything below
   moved down one and nothing else changed.** The argument is the same one that
   moved the Showdown cluster on 08-27, field evidence rather than review:
   `late_swap` structurally cannot repair a heavily-pinned entry, and on
   `1305_12g` that cost ~13 minutes of a 45-minute lock window, six bank
   invocations that could not have worked, and a hand-built delivered file.
   R267(a)'s one-slot filter and R272's repair-is-not-strategy rule land
   TOGETHER — the policy is only safe because the filter touches no portfolio
   control, and the filter is only useful unattended because the policy says it
   may run. R268 follows because both its halves are workarounds this same
   sequence typed reflexively. R204's ceiling half rides here rather than in
   the smalls: it prints the one remedy CLAUDE.md makes always-permitted, at a
   moment when it cannot work, which is a live hazard for an unattended
   supervisor and not a wording fix. **R270(b) is a hard dependency of
   R267(a)** — the filter's "confirmed starter" test has no source after first
   pitch, which is exactly when a repair runs, so the boxscore reader lands
   with it or the filter is guessing. **R271 rides R272's quiet window**, not
   the smalls: both edit CLAUDE.md, contract edits are allowed only with no
   other session live, and two edits to one contract file in one window is an
   ordering argument rather than a shared-surface convenience.
4. **R165 + R163** — unchanged content, down one: its evidence is unchanged
   while the Showdown slot gained two live hits.
5. **Showdown ladder truth: R247 + R237 + R224** — **R158, R223 and R250 all
   SHIPPED 2026-08-30** (see CHANGELOG.md), in that order and separately; what
   is left in this slot is the visibility half. The solver-status precondition
   (F-08) is met, so anything here may now trust a solve result and read a
   timeout as a timeout. Remaining: cap-cost visibility (R247, F-35/F-37: a
   tightened cap moved twelve slots from the four best players to the four
   worst, and a $6,100-left tail lineup shipped with every counter clean), the
   uncomputed-vs-neutral factor split (R237, F-38/F-43) that both qa reads
   need, and R224's two XS cap-resolver smalls. **R247 gains a rider from
   R250's landing**: `clean` now excludes the apportionment shortfall and
   includes `captain_budget_inversions`, so R247's "every counter read clean
   over a degraded tail" is measured against a different verdict than the one
   it was filed against — re-verify its premise before building it, per the
   standing rule that a backlog entry's premises are checked against the tree
   rather than taken from the entry.
6. **Showdown contest awareness: R238 first, then R239 + R249, R245 rides** —
   shapes before assignment (R239's shape-aware half consumes R238).
   **R239(b) and (c) SHIPPED 2026-08-29** (see CHANGELOG.md); what is left in
   this slot is **R239(a) alone**, the round-robin deal, and it still consumes
   R238 for its shape conditioning. The old note that "its round-robin dealing
   half can land first and alone" was corrected on 08-29 and remains false: (b)
   landing does not license it either, because dealing cannot create diversity
   the bank does not contain. (a) must now READ the Gale-Ryser verdict (b)
   shipped rather than assume a deal is available. R249 gives the path a
   projection input so the salary file stops being the injection point
   (F-40). R245 fixes the one file two same-date builds both write. The
   standing batch tail keeps its members and order: R208, R122-rider, R123,
   R189(3), R210, R211. R240 (punt-captain template) is Tier 4,
   decision-first — and becomes LOAD-BEARING if Ben answers the new
   distinct-captains decision "distinct," since a 7-entry contest would then
   need 7 captains and the ladder constructs none below $5,800.
7. **R216** — unchanged reason: lands alone at a session boundary because it
   resets in-flight gate state. Gains F-01's widening as a rider: the
   behavior manifest should also cover the lock files and
   `reference_manifest.json`, and record runtime identity (R217(d)'s half).
8. **R195 + R181 + R179** — unchanged; R195 before R181.
9. **R180 + R217 + R218** — audit hardening, unchanged (F-02, F-22).
10. **R207 + R244** — the R203 feeder pair, now explicit: R207 makes the
    refusal name the binding cap, R244 makes the rescue open ONLY that cap
    and bisect downward (the 08-27 container fragment measured 0.43
    dominating 0.50 outright — the first value that certifies is not the
    value to ship). R203's R214 precondition is MET (landed 2026-08-28), so
    this pair is all that stands between the board and R203; its entry gains
    R244's design.
11. **R164 + R246** — convenience batch, both S, both `build_slate`-adjacent:
    the bank job grid (F-29) and the `--leverage` passthrough that makes
    R154's two constraints reachable from the slate's own prediction file
    (F-15's narrow accept; Ben has now asked for leverage twice in-slate and
    the answer was "built but not connected").
12. **R225 + R226 + R227** — archive integrity, unchanged; R225 still gates
    R10's Showdown cells. F-16/F-17/F-19/F-21/F-23 all corroborate this
    batch; R227's existing riders already carry the zip quotas and the
    atomic-writer copy, so ed8 adds no scope.
13. **R276 + R277** — **INSERTED 2026-08-30 (third note), the only resequencing
    this date; the old 13 and 14 move down one and nothing else changed.** Ben's
    dated standing-QA instruction and the first finding it produced, and they
    land together because neither is worth much alone: R276's panel (a) is
    exactly the check that surfaces R277 with no cleverness, and R277 without a
    panel is one arm on one slate. Positioned HERE and not higher for a stated
    reason: R276 changes no delivered byte (it is report-only, on the surface
    CLAUDE.md already calls a report and never a gate), and it reads brief fields
    that slots 5 and 6 are about to rewrite, so building the panels first would
    aim them at a moving target. Positioned here and not lower because Ben dated
    the instruction and R277 degrades pitcher ranking on every slate until it
    lands. **R276's panel (b) has a hard dependency on R196's remainder:** the
    breadth-vs-construction comparison needs the archetype table to carry a
    truthful breadth for the shape it resolves, which is the thing R196 cannot
    currently express.
14. **Smalls, batched opportunistically:** R264 + R265 (one move, see both), R236(b) (one Action Network capture, then the fixture), R221 **+ R270(a)** (the
    two sides of one doubleheader-leg boundary — the write side stamps the
    wrong leg's order, the read side has no leg filter at all, and the odds
    path already holds the matcher both should use), R222, R229 (+F-24's severity
    note on the (b) half), R230 (+(d), the game-cap test that passes with the
    constraint deleted, F-28), R231, R232, R241, R243. R269 lands here or with
    R245, whichever moves first; they are the same manifest object.
15. **The pre-existing Tier 1 remainder from R121**, standing order,
    unchanged.

**Tier 2 keeps its order and gains one rider:** R118 → R48 + R83 → R10 (still
gated on R225) → R140, with R13 the funding gate. The rider (from F-48,
adopted): the replay tool settles counterfactual portfolios at the archived
contest's own payout curve — ties split the occupied payout slots per DK's
rule, duplicates stay separate entries — so a replay reads in dollars against
an OBSERVED field. That is accounting, not simulation; the four sim-gate
preconditions are untouched.

**Corroborated at HEAD, no new number (ed8 → board):** F-01→R216, F-02→R218,
F-03→R215, F-04→R212, F-05→R214, F-06→R221, F-07→R222, F-08→R158, F-09→R223,
F-10→R228, F-12→R205, F-13→R172, F-14→R173, F-15→R209/R154, F-16→R225,
F-17→R226, F-19→R227, F-21→R227(b), F-22→R217, F-23→R227(a), F-24→R229(b),
F-25→R229(a), F-28→R230(d), F-29→R164, F-30→R206, F-32→R176(c), F-44→R232+R76,
F-45→R231/R77/R107/R188, F-49→Tier 2's own predict-then-grade loop, F-50→
CLAUDE.md's money-and-entry wall. Twenty-nine prior findings independently
re-confirmed is the strongest external validation this board has had.

**Rejected, with the reasons in "Do not build (updated)":** the phased rebuild
(Sections 3.1–3.24 as a program), F-26 (the roster-contract deferral is
documented and tested, D29's re-file), F-27 (monolith decomposition, no named
measurement), F-46 (the runtime lock is scoped by its own header, C04's
re-file; R217(d) carries the surviving sliver), F-49 as a gate artifact, and
every joint-scenario-portfolio replacement inside F-30/F-35/F-36/F-37/F-41 —
the operational halves of those findings are accepted as R239/R247/R250.

**Board corrections.** The previous note's "four unconsumed fragments" line is
spent: twelve consumed this session, one kept. `claims/engine_2026-08-20` is
STILL HELD with `released_utc: null`, eight days old now, alongside the stale
`slate_*` beacons; unchanged, Ben's to arbitrate. The Solo Shot family got its
FOURTH occurrence (08-25's "$100 Solo Shot (Turbo)"), recorded on R196.*

*2026-08-27, DEV, claim `engine` (`engine_2026-08-27`): **the queue head is
CLOSED. R219 and R220 are landed and migrated.** Gate 1305 -> 1313 (`test_core`
876 -> 884, `grew`); the CHANGELOG entry of this date carries the record and the
R233 enumeration. Ten mutations, ten caught. The numbered list below is
RENUMBERED rather than annotated, so it is thirteen slots and slot 1 is R212 +
R213 + R214 + R215.

**Nothing jumped the queue. Two readings, and the first is a rule about filed
fixes.** R219's Fix line said "defer only on `len(lineup) >= DK_ORDER_SLOTS` or
`lineup_status == "confirmed"`", and taken literally that would have ranked DK's
degraded eight above an operator paste's eight — extending R32 and R143 into a
case neither covers, silently, inside a fix aimed at a mid-repost API partial. A
paste is short for its own reasons (`1. TBD` holds, R133's starter DK never
listed), so `source == "operator_paste"` defers at any length and the DK-vs-paste
question for two incomplete sides stays Ben's. **A filed Fix line is a proposal,
not a decision: when it would move a ranking Ben wrote, it needs his ruling or a
narrower fix, and the narrower fix is usually available.** This is the fourth
consecutive landing to correct something in the item it closed, and the first
where the correction was in the REMEDY rather than the diagnosis.

**Second, the report defect and the code defect were the same defect.** The guard
asserted "nothing else has the side" from a nonempty list; the pool warning
asserted "the surviving N are seeded" from a record that never said what the merge
did. Both are a consumer inferring a fact its producer did not supply, which is
R159/R160's "two components answering one question" shape with the second
component being a HUMAN reading a report. The remedy was the same in both halves:
one derived value, named at the boundary. Worth carrying into slot 1, where R212's
decision log has the same shape.

**Four unconsumed fragments, and the inbox is a DIRECTORY — listed, not inferred
from `git status`.** `docs/backlog_inbox/` holds
`2026-08-24_BUILD_actionnetwork-odds-fallback.md` (F1 silently neutral behind a
proxy-gated odds API, with `factors_inert` conflating "computed to neutral" with
"never computed"), `2026-08-24_BUILD_showdown_contest_assignment.md` item 1
(thesis-to-contest assignment is sequential, so a multi-entry contest inherits
one side — the washout axis binding one level below the portfolio; item 2 closed
with R234), `2026-08-25_BUILD_posture-vocab-and-solo-shot.md` (two intake
frictions, one of them `build_slate.py --postures` validating against a
vocabulary that is not `contest_shapes.CONTEST_SHAPES`) and
`2026-08-26_BUILD_contest_aware_allocation_at_onset.md` (contest-slice blindness,
second sighting). All four want numbers at the next merge pass; the 08-26 one is
R206's class (portfolio controls counting the wrong thing at the wrong level) and
belongs with it in Tier 2's neighbourhood, not in a Tier 5 smalls batch. The
08-09 curated-archetypes fragment is KEPT by design and is not a missed consume.

**One board note retired, one kept.** `claims/engine_2026-08-20` is still HELD
with `released_utc: null`, now seven days old, alongside four stale `slate_*`
beacons; per the contract that is Ben's to arbitrate and sessions keep working
around it by taking the dated name. The disk-vs-GitHub note stays struck:
`sync_check.py` measures it in one call, and this landing puts disk one commit
ahead again, which is the normal state.*

*2026-08-25 (slot 2, same day), DEV, claim `engine`: **the queue head is CLOSED
again. R194 and the 08-23 dedupe fragment merged into it are landed as R235 and
migrated.** Gate 1292 -> 1305 (`test_core` 863 -> 876, `grew`); the CHANGELOG
entry of this date carries the record, and the numbered list below is
RENUMBERED rather than annotated, so it is fourteen slots and slot 1 is
R219 + R220. Ten mutations, ten caught.

**Nothing jumped the queue, and the closed item cost less than the board
thought because the batching claim had already been struck.** R191's landing
struck "one helper serves all four"; what was left here was one file, and it
stayed one file. Two readings worth carrying forward.

First, **the item's Why named the wrong mechanism and its What was right.** It
said "two parsers for one fact that can disagree" — `build_slate_pool`'s and
`ownership_pred`'s own. There is one parser: R143 pointed the tool at the
engine's readers before this item was filed, and that shared reader is
person-blind, which is the whole defect. The 08-20 disagreement the item cites
was between two SOURCES (a feed against DK's `Starting` column), not two
implementations. Three consecutive entries have now corrected a filed cause
while confirming its symptom, which is an argument for repro-before-fix and
not for distrusting the board.

Second, **the fix broke a consumer and the enumeration is what caught it.**
Keying the prediction by person removes the CPT id from the file, and
`qa_portfolio`'s Showdown captain panel looks a captain up BY the CPT id — so
the surviving Showdown panel would have read "not in the prior" for every
entry. Landed together, with the rejoin and a fallback for pre-R235 files.
That is the N-versus-N+1 shape arriving from the other direction: not a fix
that misses a member of its class, but a fix that ADDS one. R233's grep answers
both if it is run over consumers and not only over the defect.

**One board correction, and it retires a standing note.** "Commits on `main`
are still not on `origin/main`" has led this section for four days. Ben pushed:
`python tools/sync_check.py` reports `disk main 5f533df / GitHub main 5f533df
(measured via GH_PAT) / ok disk and GitHub agree`. Struck, not repeated — the
backlog is the wrong place for it, because sessions commit and Ben pushes, so
disk running one commit ahead is the NORMAL state and not a finding. This
landing puts it one ahead again. `sync_check.py` measures it in one call; a
board note can only go stale between them.

**One stale claim for Ben to arbitrate, unchanged from this morning:**
`claims/engine_2026-08-20` is still HELD with `released_utc: null`, five days
old, alongside four stale `slate_*` beacons. Per the contract a stale claim is
Ben's call; sessions have been working around it by taking the dated name.*

*2026-08-25, DEV, claim `engine` (bare mutex): **the queue head is CLOSED. R191
and R192 are landed as R234 and migrated.** Gate 1276 -> 1292
(`test_upload_integrity` 238 -> 254, `grew`); the CHANGELOG entry of this date
carries the record. Eight mutations, eight caught.

**Slot 1 is now R194 + the 08-23 dedupe fragment, and it shrank rather than
moved.** Nothing jumped it. What changed is that the batching argument that put
four items in one slot does not survive contact: "one shared helper (Showdown
CPT/UTIL -> person) serves all four" is FALSE across the boundary, because the
preflight cannot import the engine and `melt_showdown_salary_csv` was therefore
never available to it. The two halves share a defect CLASS and no code. That is
the second time in three sessions a batching claim on this board has been wider
than the code allows, after R167's "third copy" that was a fourth — **a batch
note asserting shared code is a claim about imports, so check the import wall
before believing it.**

**Two readings from the landing.** First, **R191's class had two members and the
item named one.** `verify_export.py` imports the same resolver and had the same
unguarded call; by R175 it is the weaker checker on exactly the files it exists
for, so it would have inherited the wrong-slate answer in silence after its
sibling was fixed. R233 asked for the enumeration in the changelog entry and the
enumeration is what found it — the discipline paid on its first use. Second,
**the one surviving mutation was pre-existing debt the unification exposed, not
debt it created.** Dropping the team half of the person key passed all 251 tests;
that property had never been asserted at any of the four hand-written copies
either. Unifying N copies makes one testable thing out of N untestable ones, and
the test it then asks for is a test the class always owed.

**One fragment note for the next merge pass, so a fixed defect is not re-filed:**
`docs/backlog_inbox/2026-08-24_BUILD_showdown_contest_assignment.md` item 2 is
R191's third field occurrence and is CLOSED by this commit. Item 1 of that
fragment (thesis-to-contest assignment is sequential, so a multi-entry contest
inherits one side — the washout axis binding one level below the portfolio) is
open and unnumbered, as is
`docs/backlog_inbox/2026-08-24_BUILD_actionnetwork-odds-fallback.md` (F1 silently
neutral behind a proxy-gated odds API, with `factors_inert` conflating "computed
to neutral" with "never computed"). Both want numbers at the next merge.

**One thing for Ben, unchanged and now four days old:** commits on `main` are
still not on `origin/main`. Sessions commit and Ben pushes; until he does, no
clone sees this week's work.*

*2026-08-24 (slot 3, same day), DEV, claim `engine` (bare mutex): **two independent
greenfield reviews adjudicated together — the seventh edition (`docs/2026-08-24_critique_greenfield_spec_ed7.md`,
Claude, five lanes) and an outside spec written against the same commit
(`docs/DFS_SYSTEM_GREENFIELD_SPEC_CODEX.md`, Codex, 5 core findings + 36 defects).
Both reviewed `a49bd610` and HEAD did not move. Filed: R212–R233. Six riders, five
board corrections, eight rejections with reasons, and the queue moves.**

**Why two documents is the interesting part.** They were written independently and
they agree on twenty-one defects, which is the first time this project has had a
second reader at the same head. Every one of the twenty-one was re-verified HERE
before filing, by exact-line read against the tree; the disagreements are where the
value is, and there are three worth naming.

**The outside spec is wrong three times, and each error has the same shape: a
deliberate decision read as a defect.** Its C04 calls the runtime lock a Blocker
because `requirements.lock` would not install on the reviewer's Windows/3.13
machine — but the file's own header names its scope ("the supported runtime: Python
3.10, linux x86_64") and names `requirements.txt` as the cross-platform floor. Its
D29 calls `roster_contracts.py` incompletely centralized — the module docstring
states that deferral in full, names the golden-replay condition, and a test asserts
CLASSIC against the engine's constants. Its D35 calls `latest_valid_run.json` a
cross-session race with two consumers — there is one, and `build_state_manager.py:5`
already carries the spec's own doctrine verbatim ("only a pointer; it is not an
artifact"). A reader who cannot run the tests reads scoping as sloppiness. That is
worth remembering the next time this repo is reviewed from outside, and it is worth
remembering that the same reader found D02, D19's real size, and D21's cheap fix,
none of which five internal lanes saw.

**The rebuild program is rejected for the seventh consecutive time, and this time
the rejection is cheap to state.** The outside spec's C01/C02/C05 say the objective
is a proxy and not expected value. That is not a finding; it is this project's own
Truthful-labels rule, written into CLAUDE.md before either review existed. What is
rejected is the ORDERING: the spec builds the scenario/field/settlement stack first
and measures second. Tier 2 reaches the same destination from the archive that
already exists, and ed7 just made its head cheaper — `player_table` with FPTS
SURVIVES into every archived `mined_*.json`, the `:1982` strip drops only the
derived maps, so **R118 needs no miner change and no re-mine backfill**, and the
replay tool re-derives `fpts_by_norm` from the archive as it sits. Building the
machine that would measure the rebuild, before the rebuild, is the only sequence
that can tell you whether the rebuild was worth it. Everything downstream of that —
SQLite run DB, content-addressed artifact store, FSM orchestrator, signed manifests,
OCI image, CP-SAT migration — is rejected unchanged, and two of the three concrete
harms cited to justify the artifact store are filed here as one-function fixes
(R227) while the third is R191.

**The most repeated finding shape got a fix, and it is one sentence of discipline.**
Four of ed7's sharpest findings are the same event: a fix that closed N named sites
of a class shipped while the class had N+1 members. R167 unified four copies of the
units rule and the fifth still clamps (R215(a)). R169(a) saved the decision log on
the timeout path and the sibling wall-clock stop eight lines above still destroys it
(R212). R153 made both Showdown caps bind "on every rung" and the floor rung still
drops the captain cap (R223). R159 unified two components answering one question and
minted a new disagreement between its own comment and its own guard (R219). The
board already carries the half-sentence ("when an item says the Nth copy, count the
copies before believing N", the 08-24 slot-2 note). **R233 is the mechanical half:
a landing that claims a rule now lives in one place carries, in its CHANGELOG entry,
the grep that enumerates the class at that head.** Filed and closed in this commit;
CLAUDE.md's changelog contract carries it.

**The one defect found INSIDE the archive outranks its severity class.** R225: the
miner's Showdown duplication counting is captain-blind at all three sites, so two
entries with the same six people and different captains count as copies. Both reviews
found it independently. Every Showdown duplication number in ledger 3.17 that R10's
entry cites is inflated by construction. The archive is this project's only asset no
vendor publishes, and R10 would read its bar against those counts — so **R225 is a
precondition on R10**, not a Tier 5 tidy. `captain_norm` already rides every parsed
entry, so the recount is re-derivable from the archived JSONs: no re-mine.

**Resequenced on impact against technical challenge, with the dependencies made
explicit.** Thirteen slots as of 2026-08-27, the head having closed twice since;
every new item is S or XS except where marked.

1. **R212 + R213 + R214 + R215** — the lost-window remainder, same surfaces the
   08-24 batch just left open. **R214 is a precondition on R203** (Tier 3): the
   supervisor discards the operator's R157 rescue it is being taught to perform.
   **R212 is a precondition on the whole supervisor batch** — the decision log has
   to survive the window to be worth writing.
2. **R205** — down two slots since it was filed, otherwise unchanged. Fix note
   corrected: the code is
   `statistics.median(sorted(...))`, which on the two-book production fetch IS the
   arithmetic mean, so the entry's "median with a sign guard" option is not a fix
   and is struck. Probability-space de-vig (D16's consensus form) survives any book
   count and is the fix.
3. **R172 + R176 + R173 + R228** — the false-evidence batch, now carrying the
   promotion fail-open. R228 belongs here and not with R174: absent evidence
   promoting silently is the same "presence mistaken for evidence" class, one
   boundary later.
4. **R165 + R163** — unchanged. R165 and R164(c) are one normalization class two
   files apart; R55's shared normalizer closes both, so take R164 near this if the
   window allows.
5. **R174 + R175** — money-boundary parity, minus R228 which moved up.
6. **R216, alone.** The gate's tree fingerprint omits `skills/` while ~20 gated
   tests exec `build_slate.py`, so a split-gate green line can cover records that
   never tested the file that changed three times last week. Both reviews rank it
   High. It sits at 6 rather than 1 for one reason: fixing it resets in-flight gate
   state, and every slot above it wants a warm gate. Land it at a session boundary.
7. **R195 + R181 + R179** — **R195 lands FIRST or together with R181**: they share
   `execution_pipeline.py:1325`, and R181's regex scoping would mask R195's mapping
   defect behind a green eval. R179 rides the same gate-hygiene surface.
8. **R180 + R217 + R218** — audit hardening, now absorbing the gate-operational
   smalls (`--gate-report --output` never writes; `.audit_gate/` is claimless
   shared state; the complete branch ignores the age the report enforces; no
   runtime identity in the record, on a tree whose `__pycache__` proves two
   interpreters have run against it) and the last two unbounded subprocesses.
9. **R164** — bank job-grid waste. Corroborated by the outside spec (D32).
10. **Showdown batch: R158 + R223 + R224 + R122-rider + R123 + R189(3) + R208 +
    R210 + R211.** R223 joins because it is R153's founding defect recurring on a
    rung no test drives: the delivered brief reads "0 relaxations" over a breached
    25% captain cap, which is the washout axis reading clean.
11. **R225 + R226 + R227** — archive integrity, new, and placed AHEAD of the
    pre-existing Tier 1 remainder rather than in Tier 5. R225 gates R10; R226 is
    cheap now that rank is known to be parsed and stored; R227 is the registry's
    kill vector, which its own sibling was already hardened against.
12. **R221 + R222 + R229 + R230 + R231 + R232** — the smalls and hygiene, batched
    opportunistically between slots, never instead of them. R231 needs Ben's mv
    grant (1,778 litter directories); R232 is doc truth (MLB_Classic.md names a
    retired manifest as its version authority; MANIFEST.md still reports 12 modules
    and 119 tests).
13. **The pre-existing Tier 1 remainder from R121**, standing order, unchanged.

**Tier 2 keeps its order and its head got cheaper**: R118 (no miner change, no
re-mine) -> R48 + R83 -> R10 (now gated on R225 for any Showdown duplication cell)
-> R140, with R13 the funding gate and the four sim-gate preconditions untouched.
**Tier 3**: R203 is blocked by R214, and R207's drop-one binding table should land
before R203(b) because it feeds the detection. **Tier 5** absorbs R229 through R232.
**Do not build** gains four rejections and keeps everything it had; the four-clause
sim gate is untouched.

**Corroborated at HEAD, no new number.** The outside spec independently reached
six items already on this board, which is worth recording because it is the first
external confirmation any of them has had: **R41** (unify the Showdown
certification lifecycle = its C03), **R158** (a solver time limit is LIMIT, not
INFEASIBLE, and only INFEASIBLE may advance a relaxation ladder = D11, with the
SciPy status contract cited), **R164** (the bank job grid repeats equivalent and
provably impossible solves = D32, adding job canonicalisation after locks and
excludes as the shape), **R174** (no independent post-export re-derivation of the
locked-team ban = D34), **R206** (every portfolio control counts entries, not
dollars = D33, adding the sharper framing that the configuration does not DECLARE
which policy it serves, and that both bases should be reported), and **R191** (=
D14). Ed7 additionally re-verified queue slots 1-9 and nine adjacent items against
this head: nineteen HOLD, one PARTIALLY OVERTAKEN (R202, rewritten in place),
zero WRONG.

**Line moves, verified, so the next session does not re-derive them:** R172
`:4202` -> `:4221`/`:4231`; R173 `:1168` -> `:1171-1172`; R176(a) `:1153` ->
`:1154-1155`; **R176(c) lives in `late_swap_manager.py:377`/`:385`, not
`execution_pipeline`**; R179's seed guard is `build_slate.py:46-50` (main entry
`:3324`); R180 `audit.py:1378` -> `:1497` and `:1917` -> `:2036`; R197's writer
sites are `execution_pipeline.py:3099`, `:3412-3413`, `:3689`. The 08-09
curated-archetypes fragment in the inbox is KEPT by design (it carries a Ben
decision) and is not a missed consume.

**Method and provenance.** Ed7 ran five parallel reviewer lanes plus a coordinator
re-read: 6 VERIFIED-repro (pre-outage), 30 VERIFIED-read of which 13 coordinator
re-read, 3 PLAUSIBLE, and it discloses that the Cowork workspace bridge died
mid-review so its /tmp repro scripts did not survive for this session. The Codex
spec parsed all 73 Python files with the stdlib AST and could not run the suite at
all (no NumPy/pandas/SciPy in its interpreter; its audit stopped after 91 tests),
which is why its dynamic claims are labelled ENVIRONMENT-BLOCKED and why it
misread three deliberate decisions. **This session re-verified every finding it
filed by exact-line read at `a49bd610` before filing it** — the tree fingerprint
did not move, the working tree stayed ARCHIVE-dirty and was left alone, and the
gate line at this head is the one this morning's DEV session left:
`PASS v2.26.0 26 modules 1276 tests`.*

*2026-08-24 (slot 2, same day), DEV, claim `engine` (bare mutex): **the queue head
is CLOSED again. R167, R168 and R169 are landed and migrated.** Gate 1252 -> 1276
(`test_core` 841 -> 863, `test_showdown` 77 -> 79, both `grew`); the CHANGELOG
entry of this date carries the record and the ledger Quick Card pin line moved
under a DEV-held `ledger` claim, that line and nothing else. Sixteen mutations,
sixteen caught.

**Slot 3 is now slot 1: R191 + R192, the preflight pair.** Nothing jumped it. They
were inserted on 2026-08-23 explicitly "beside the lost-window batch, because they
are lost-window defects", and that is still what they are: the `--salary`
auto-resolve grabbing a concurrent session's promoted run at the money boundary's
last check, and the showdown `top exposure` line counting the ROLE so it hides the
two most concentrated players from the one operator reading it before upload. Then
R205 (American-odds averaging), then R172 + R176 + R173 (the false-evidence
batch), and the rest of the ed6 sequence unchanged.

**Three readings from the landing.** First, **the "one rule, N copies" count was
wrong on the board and it is worth distrusting the next one.** R167 was filed as a
third copy of a units rule R71(a) had fixed in two places; there were FOUR, and the
fourth — `showdown.exposure_cap_count` — validated nothing at all, which is worse
than the clamp the item was about. It was fixed here rather than filed, because the
fix is one line and closing R167 with the rule enforced in three of four places
would have reproduced R167. When an item says "the Nth copy", count the copies
before believing N.

Second, **the defect class here is different from slot 1's and both are worth
naming.** R159/R160/R189 were two components answering one question differently.
These three are failures that arrive after the window that could have absorbed
them: minutes of bank spend before the raise, a refusal shaped like a crash, a
decision log deleted by the timeout it was written to explain. The remedies differ
accordingly — the first class wants one definition, this one wants the check moved
EARLIER, which is why R167 landed at the control merge and at `build_slate`'s
front door rather than only at the arithmetic.

Third, **`autobuild.py` had zero tests and its four rails were untestable by
assertion.** Every one of them lives inside `main()`'s retry loop, so nothing could
be checked without running the loop; the file now has seven tests that drive
`main()` with a patched `subprocess.run` and a private `REPO`. That is the fixture
lesson's seventh consecutive appearance and its narrowest form: a branch no fixture
can reach does not merely go unasserted, it makes the whole file look untestable
and stay untested.

**One thing for Ben, unchanged and now three days old:** commits on `main` are
still not on `origin/main` (2 as of this commit, and the audit says so on every
session-start line). Sessions commit and Ben pushes; until he does, no clone sees
this week's work.*

*2026-08-24 (slot 1), DEV, claim `engine` (bare mutex): **the queue head is
CLOSED. R159 and R160 are landed and migrated; R189 loses layers (1) and (2) and
survives as R189(3).** Gate 1236 -> 1252 (`test_core` 825 -> 841, `grew`); the
CHANGELOG entry of this date carries the record and the ledger Quick Card pin
line moved under a DEV-held `ledger` claim, that line and nothing else.

**Slot 2 is now slot 1: R167 + R168 + R169, the lost-window batch.** Nothing
jumped it. The only candidate was R161(a), which sits in the same function R159
rewrote (`build_slate_pool` deriving `slate_date` from the UTC clock on exactly
this no-fetch path) and would have cost one line — and it stayed out for the
reason R190's own note gives about R161(b): a clock fix inside an intake fix is
two changes in one commit, and R161's whole entry is the argument that a clock
residue deserves its own. It is XS and it is the cheapest thing on the board.

**Three readings from the landing, none of which change the order.** First, the
defect class was consistent across all three items and it is not "wrong answer",
it is **two components answering one question differently**: coverage vs the
merge on what "covered" means (R159a), the status map vs the merge on whether a
game exists (R160), `sp_quality_available` vs whether the term applied
(R189(2)). Each disagreement was invisible because both halves reported clean.
That is the same shape as R172's `projection_tier` and R176's vacuous gates,
which are slot 3 — evidence for keeping that batch where it is. Second, R189(2)
was worth more than its S-lift suggested once R159(b) landed: DK ships no MLBAM
id, so making the DK-declared probable VISIBLE to F4 would have handed it
straight to the silent-1.0 path. Two items that read independent on the board
were one item in the code. Third, the mutation survivors this time were a
FIXTURE gap and not an assertion gap — every test in the class handed the merge
an empty feed, so the in-feed branch was never executed by anything. Six
consecutive items have now paid for a fixture lesson; the pattern worth writing
down is that a branch no fixture reaches is invisible to any number of
assertions about it.

**One thing for Ben, unchanged and now two days old:** commits on `main` are
still not on `origin/main` (2 as of this commit, and the audit says so on every
session-start line). Sessions commit and Ben pushes; until he does, no clone
sees this week's work.*

*2026-08-23 (fragment merge + R190), DEV, claim `engine` (bare mutex): the ed6
landing left twenty-two fragments in `docs/backlog_inbox/` explicitly unconsumed
and named the next fragment-merge session as their owner. That is this session.
**The inbox held 38 fragments; 37 are consumed and deleted, one is kept. R190 is
FILED AND CLOSED in this commit, R191–R211 are filed, and six riders land on R44,
R118, R10, R78, R149 and R161.** The one kept is
`2026-08-09_DEV_ben-decision-curated-satellite-archetypes.md`, which records a
Ben DECISION rather than a finding and is cited three times on the board. Gate
1221 -> 1236 (`test_core` 821 -> 825, `test_showdown` 66 -> 77, both `grew`).

**38, not 22, and the gap is worth naming.** `git status` showed **22 UNTRACKED**
fragments, which is the number the ed6 note counted. **16 more were sitting in
the same directory already COMMITTED** — BUILD sessions have been committing
their fragments since 08-19 (`ec832cf`, `9a48ce7`, `bdc89a6` and others carry
"backlog fragment" subjects), so they never appeared as dirt and a session
building its work list from `git status` could not see them at all. **Five of the
sixteen carried findings that were not on the board, and three of those five are
the sharpest items in the whole pile** (R205, R206, R208, plus R210 and R211).
**The inbox is a DIRECTORY, not a diff: list it, never infer it from
`git status`.** The rest of the sixteen were merged long ago and never deleted
(R60's, R121's, R127-R131's, R132's, R135-R141's and R156's sources), which is
the other half of the same confusion — a consumed fragment left in place is
indistinguishable from an unconsumed one, and the contract already says the
owning role deletes. All of them are deleted now.

**The queue moves once, and the reason is a recurrence count.** Slot 1 was
"intake truth, one surface" (R159 + R160 + R189 + the R122 rider), and three
independent BUILD sessions on three slates had filed the ROOT CAUSE under those
symptoms without it being on the board: F4's platoon term needs a hitter's bat
side AND the opposing probable's hand, and `fetch_slate_bundle.fetch_lineups_feed`
fetched only the first. Measured 30 of 30 probables at `hand: None` on 08-18 and
again on 08-19, against `bat_side` populated on 270 of 270 hitters. So the whole
platoon half of F4 was inert on every slate whose feed came from the bundle, the
brief read `f4_platoon_applied: 0` beside `signal_applied: true`, `degraded:
false` and `factors_inert: []`, and each of the three sessions worked around it
by hand with a second `/people` call. That is R190 and it landed here rather than
being filed, because it is XS and it is the cause of a symptom already sitting at
the head of the queue. **Slot 1 keeps its position, minus the root cause: R159 +
R160 + R189 + R122-rider is still next**, and R189's remaining layers now run
against a feed that actually carries hands.

**One insertion, on evidence of the same kind.** **R191 + R192 enter at slot 2**,
beside the lost-window batch, because they are lost-window defects: the
preflight's `--salary` auto-resolve grabbed a concurrent session's promoted run
on TWO different Showdown slates the same day, exit 2 with "0.0% embedded pool
overlap" against a delivered file that was clean, and the recount that recovered
it cost a round trip at the money boundary's last check (R191). R192 is the same
file and the same operator: the showdown `top exposure` line counts the ROLE and
not the PLAYER, so it drops the CPT column, hides the two most concentrated
players outright, and contradicts R153 — written the same day, for the express
reason that the washout axis is the PLAYER — in the one place a pre-upload
operator looks. Both are informational-or-recoverable and neither shipped a wrong
file; both are S, both recurred, and both make the final check disagree with the
artifact it is checking.

**One more insertion, from the committed nine.** **R205 enters at slot 3**:
`parse_the_odds_api_totals` averages moneylines in AMERICAN-ODDS space, so -104
and +100 average to -2.0, a 98% favorite, and everything below the parser
faithfully propagates a price no book ever posted. It is S, the root cause is
confirmed with a repro, and the blast radius is INVERTED — the closer a game is
to a coin flip the more wrong F1 gets, so the games with no real edge receive the
largest fabricated split, up against F1's own 0.85/1.15 clip. That belongs ahead
of the false-evidence batch because it corrupts an INPUT rather than a record.
Read its second half before touching it: the filing session fixed it, rebuilt,
and then rejected the corrected build, because the correction promoted the one
team with no posted lineup. The number got more honest and the portfolio got
worse. That interaction is Ben's and it is filed as an observation, not a
proposal.

**Nothing else jumps.** R201 (`MIN_AUTO_TEAM_COVERAGE` is a false negative on a
3-game slate and overrides the manifest tier the code's own docstring calls
authoritative) is P1 and is the head of the Workstream 7 remainder, not of this
tier: it damages archived evidence, which is Tier 2's input, so it sits with the
measurement loop rather than ahead of it. **R207 rides R203** — it is the same
call site and it is the cheaper, more actionable version of what R203 and R204
both want, so whoever takes R203 should read R207 first. R203 itself is M and
goes to Tier 3. R206 (every portfolio control counts entries while one $15 entry
carried 84.5% of the money) is M with a real decision inside it and lands in
Tier 2's neighbourhood, reporting both denominators before any cap binds on
dollars. R209 (replace the objective's leverage proxy) stays GATED behind 3-5
more graded slates, per its own fragment. R208 goes to the next Showdown session
with R158/R122/R123. R195, R197, R202, R204 are Tier 5 smalls. R196 (the Solo
Shot archetype row, now hit **three** times in four days) is **XS and not DEV's
to fix** — `data/reference/` is ARCHIVE's write set, so it is filed with the role
that owns it rather than sitting in a DEV queue where it cannot land, and the
write-set boundary is precisely why it keeps recurring.

**Three things for Ben, none of them code.** (1) 11 commits on `main` are not on
`origin/main`; sessions commit and Ben pushes, so no clone can see this week's
work until he does. (2) The DK contest entry-history export ends 2026-07-28, so
`paid_places` is null on all 89 own-results records in the 08-22 tranche and
`classify_tier` returns UNRESOLVED for every one of them, permanently — that is a
manual DK download and nothing on the tool side fixes it (R200). (3) Is the
`[2x]` in "MLB SUPERSatellite to NFL 9-13 … [2x]" the ticket count? R1c's gap
still has no curated value and the guess is not DEV's to make. **And a fourth,
larger than the other three: should the portfolio controls bind on ENTRIES or on
DOLLARS (R206)?** An equal-weight cap is the right instrument for "don't lose
every entry at once" and a dollar-weighted one for "don't lose the bankroll at
once"; those are different objectives and the dual objective in CLAUDE.md does
not say which the controls serve. R206's recommendation is to report both
denominators first so the answer comes from evidence rather than from one slate.*

*2026-08-22 (ed6 landing), DEV, claim `engine` (bare mutex): **the SIXTH
greenfield edition — commissioned by Ben on 2026-08-17 against this repo at
`ac8ac05`, reviewed that day by seven parallel container reviewers, and
interrupted at delivery by the device bridge — lands now, re-adjudicated
against THIS head (`ec832cf`) because the tree moved 22 commits in between.**
The five-day delta both validated and collided with the review: R117, R133 and
R136 CLOSED (the R117 fix covers one of the four paste hand shapes the review
found; the rest are R189), the numbers R152–R157 were TAKEN by other items (the
review's filings are renumbered R158–R189), and every finding was re-verified
against this head before filing — the three sharpest by fresh repro HERE
(R159's scratch-discards-a-posted-nine, R160's front-door crash, R172's
`enriched` manifest tier), the rest by exact-line re-read; one review finding
was OVERTAKEN by the week's work and is NOT filed (the DH leg-blind DK merge:
the merge now leg-selects via `_salary_game_times`/`_select_slate_legs` with a
`doubleheader_legs_dropped` counter). Method, dispositions and all repro
output: `docs/2026-08-22_critique_greenfield_spec_ed6.md` (reviewed base
ac8ac05, suite there `PASS v2.26.0 26 modules 1120 tests`; landing base
ec832cf at the 1221 pins) and the CHANGELOG entry of this date. Headline
unchanged from the review: every module KEEPS — 32 verified defects, zero
rebuild arguments, Do-not-build untouched, the sim gate keeps its four
preconditions, and the benchmark's one keeper is that the archive is the moat
(ownership MAE by bucket, dupes-vs-ownership fits, realized rake/payout tables
are computable from `data/archive/` and published by no vendor — independent
validation of Tier 2's ordering, adopted as data).

**Filed: R158–R189.** **Five riders in place** (R122, R98(3), R76, R83, R149)
and **two false board notes corrected** (R66's eval-5 coupling claim, disproven
by a harness run; R79's stale (a)/(c) status). **Resequenced per Ben's
instruction (impact against technical challenge), and the queue MOVES:** the
verified P1 truth-and-delivery batches run ahead of the pre-existing Tier 1
remainder, all S or XS:

1. ~~**R159 + R160 + R189 + R122-rider**~~ — **R159 and R160 CLOSED
   2026-08-24**, entries migrated to CHANGELOG.md, along with R189's layers (1)
   and (2) (the F4 quality term dying silently on id-less probables — every
   plain-text paste slate, and since R159(b) every DK-declared probable too).
   **What is left of this slot is R189(3)** (the two paste hand shapes R117's
   fix did not cover) **and the R122 rider** (the Showdown thesis prior
   claiming factors an `all_healthy` pool never applied). Both are handedness
   reaching the build, both are Showdown-or-paste rather than the Classic
   no-fetch path, and they batch with R158/R123 for the next Showdown session
   at item 9 rather than holding slot 1.
2. ~~**R167 + R168 + R169**~~ — **CLOSED 2026-08-24**, entries migrated to
   CHANGELOG.md, along with a fourth `_cap_count`-class copy found at landing
   (`showdown.exposure_cap_count` validated nothing, so a slipped Showdown cap
   returned a count of 25n and left every R153 relaxation counter reading
   clean). **R191 + R192 is now the head of this tier**, per the 2026-08-23
   insertion that placed it beside this batch as lost-window work.
3. **R172 + R176 + R173** — the false-evidence batch: every default build
   records `projection_tier: "enriched"` off the value guard (R172, repro'd
   at THIS head, truthful labels on a money-adjacent record); the vacuous
   salary gate, unrecorded assertable gates, the constant
   `forced_swap_validation_passed`, the silent delivery-evidence excepts
   (R176); the truthy-stub lineup gate on the API leg (R173, the R53 class).
4. **R165 + R163** — solver truth: excludes silently ignored by the cap
   denominator and viable-SP helpers on int64 frames (R165, R55's class two
   sites over); a relaxation recorded that no accepted lineup used, final DU
   validation at unearned thresholds (R163).
5. **R174 + R175** — money-boundary parity: no post-export re-derivation of
   the locked-team ban (R174); verify_export missing the contest-identity and
   delivered-manifest checks preflight has (R175).
6. **R179 + R181** — determinism and gate-hygiene minutes: the asserted-gate
   path skips the F19 hash-seed pin on exactly the builds autobuild routes
   through it (R179); eval 5's standing red is misattributed and its regex
   matches canonical vocabulary (R181).
7. **R180** — the audit-hardening batch (changelog_debt blind to
   MLB_Classic.md/MANIFEST/requirements, the amnesty window, suite-discovery
   reconciliation, four smalls — the pin-sum comment now reads `# 1000`
   against an actual 1221, the file's own staleness class, fourth instance).
8. **R164** — bank job-grid waste (identical re-solves on pinned late-swap
   entries; provably infeasible opponent-team jobs): T-window recovery.
9. **R158 + R189(3)** — the Showdown time-limit-as-infeasibility inversion,
   batched with R122/R123 for the next Showdown session (WS1); R189(3) joins
   them as of 2026-08-24 because it is the paste-side half of the same
   handedness question the R122 rider asks.
10. Then the pre-existing Tier 1 remainder in its standing order from **R121**
   (still the head of that remainder), R11, the swap-rails batch, R36 F3m +
   F6m-remainder + R120 (with ed6's evidence that mapless builds auto-assume
   two gates and record plain "certified"), the claim.py batch, R80(a) + R88
   (sharpened: the scrub loses to percent-encoding), R149 (rider realigned
   with its new (d)), R150. **R166** (post-R61 fixed-row denominators; R116's
   reuse default inert on scoped swaps) sits at the tier boundary, S-M, and
   lands beside R115 in Tier 3 if not taken here.

**Tier 2 deliberately untouched** — R118 head, then R48+R83 (R83 gains its
golden-schema rider), R10, R140; the week's own R154 (ownership prior into the
optimizer as constraints) and the first graded prediction moved that loop
forward mid-review, which strengthens the ordering. **Tier 3** gains R166
after R98(3), whose rider records that the direct path never persists a bank.
**Tier 4** gains R188 (the 1.24MB tracked workspace residue; disk delete is
Ben's grant). **Tier 5** absorbs R161, R162, R170, R171, R177, R178, R182,
R183 (CLAUDE.md regrowth: measured 12.6KB on 08-12, 25.9KB on 08-17, 33.9KB
today — the byte-budget warning prices itself), R184 (partially applied in
this commit), R185 (SKILL.md now 52.2KB), R186, R187. Unmerged BUILD/DEV
fragments from 08-19..08-22 in `docs/backlog_inbox/` are NOT consumed here —
they are the next fragment-merge session's, per the standing rule.*

*2026-08-19 (skill review), DEV, claim `engine_2026-08-19_skillreview`: Ben
asked whether the repo, the memories or the installed lineup skill needed
updating. **R155 is FILED AND CLOSED in the same commit** (stub below, entry in
CHANGELOG.md) and **R149 gains (d) while its "Also" half closes**. **R121
remains the head of Tier 1**, untouched: this session spent no tier slot. Three
things to read before the numbers. **First, the session-start gate was RED in a
fresh clone and green on Ben's disk**, on one test that read a gitignored slate
file, which is exactly why nobody saw it -- every session that ran the gate ran
it where the file existed. **Second, the container-to-GitHub link works.**
`GH_PAT` from `.env`, staged as a file and sourced, clones the private repo, and
with R155 the clone runs the pinned 1217 in about 40s, which retires "container
runs start from a tarball" for anything committed. **Third, the drift check is
name-blind and not only path-blind**: the repo directory is `generate-lineups`,
the skill a cloud session loads is `mlb-generate-lineups`, so a cache it CAN
read still reports `checked: 0`. That is R149(d), and it is a design question
about what a check should assert about a ROUTER, not a lookup bug.*

*2026-08-18 (fourth session), DEV, claim `engine_2026-08-18`: **R148(a) is
CLOSED and migrated**, **R152 is FILED AND CLOSED in the same commit** (number
reserved in the stubs below, entry in CHANGELOG.md), and the R111(b) doc-truth
tail is done — the five corrected surfaces now cite the COMMAND, its date and
its output instead of "Ben, 2026-08-18", because a correction that fixes a
stale reading by attaching a name repeats the defect it is correcting. **R121
remains the head of Tier 1**, untouched: this session was Ben's three  named
infrastructure items and it did not spend a tier slot. **R148(b) survives in
Tier 5** and is what is left of that number. Four things worth reading before
the R-numbers. **First, R148(a)'s premise was already dead and the mechanism was
the item.** The trap (a fresh clone landing on a stale default) was retired when
Ben changed the setting; what remained was a check that returned `null` whether
or not GitHub agreed and would be equally silent if the default moved again. It
now reads the remote and says which source answered, and the fix as filed was
corrected in one place: the fallback does NOT compare against the local cache,
because a comparison against a cache presented as "the default branch" is the
original defect wearing a label. **Second, a test CLASS is not a small enough
unit for the split gate.** `DeterminismTests` did not finish in a 42-second
call, so a cut-off class is re-run as its individual METHODS and a method that
still cannot finish is REFUSED by name rather than skipped. **Third, the device
VM is not a constant and no fixed chunk plan survives it**: the same class
measured 24.5s at 19:50 and did not finish in 42s at 20:15, same code, same
machine. That is why the ledger Quick Card's hand-measured boundaries are
replaced by a runner that learns its own times rather than re-measured into the
next staleness. **Fourth, the fixture lesson landed for the fifth consecutive
item.** Eighteen mutations by hand, all eighteen caught, but the stale-tree
guard survived its first mutation because the test pinned the REFUSAL and never
the counts — the loud half of the behaviour without the quiet half. Gate
1182 -> 1199 (`test_core` 792 -> 809, `grew`); CLAUDE.md, SKILL.md and the
ledger Quick Card pin line moved with it, the last under a DEV-held `ledger`
claim, that line and nothing else.*

*Amendment notes older than the two above were relocated VERBATIM to "Board
history" on 2026-08-22 (ed6 adjudication commit; R184's discipline applied at
filing): the queue keeps the current order and the newest sessions' notes,
and the narrative history accumulates at the bottom, not here.*

## Tier 1 — pool truth, swap rails, and surfaces that steer the operator wrong. All S or XS, all DEV-ready, in order; adjacent items batch where they share a surface.

0. **Resequenced 2026-08-22 (ed6 landing, Ben's instruction).** The working
   order for this tier is the ed6-landing note's numbered list in "What do we
   tackle next": the ed6 insertions R159+R160+R189 (with the R122 rider),
   R167+R168+R169, R172+R176+R173, R165+R163, R174+R175, R179+R181, R180,
   R164, and R158 run AHEAD of the pre-existing remainder (R121 onward),
   because every one is a verified P1 silent-wrong-output or lost-window
   defect at S/XS lift. Entries live in their workstreams below; the numbered
   items under this line are the tier's landing record and hold their
   positions. **Advanced 2026-08-24: the first entry is spent. R159 and R160
   are closed and R189 is down to layer (3), so R167+R168+R169 is the head of
   this tier and the leftovers (R189(3) + the R122 rider) moved to the
   Showdown batch at item 9.**
   **SUPERSEDED 2026-08-24 (ed7 + Codex double adjudication, Ben's
   instruction: reprioritise on impact, technical challenge and
   dependencies).** The working order for this tier is now the FIFTEEN-slot
   list in the newest note at the top of "What do we tackle next", not the
   ed6 list above, which is kept as the landing record it became. Three
   things changed and one did not. R159+R160 and R167+R168+R169 are both
   spent, so the ed6 list's first two entries are history. The insertions
   R212-R232 are interleaved by SURFACE rather than appended, because eleven
   of them sit in files the standing batches already open. And three hard
   dependencies now bind the order rather than merely suggesting it: R214
   before R203, R212 before the supervisor batch, R195 before R181, R225
   before R10's Showdown cells. What did not change is the tier's own
   criterion — verified P1 silent-wrong-output or lost-window defects at S/XS
   lift run ahead of the pre-existing remainder from R121.

1. **R60 — CLOSED 2026-08-12**, migrated to CHANGELOG.md. Both halves landed
   with the partial-side rule written into the build contract.
2. **R69 — CLOSED 2026-08-13**, migrated to CHANGELOG.md. All three halves
   landed: the salary-status coverage read, the un-ageable platoon reference
   reporting at the policy's severity, and the exclusion split (unmatched ids
   hard-gate `approve=True`, unrecognized `Excluded` cells relabel to
   warnings).
3. **R70 — CLOSED 2026-08-14**, migrated to CHANGELOG.md. Both halves landed:
   more than one file matching an intake role now blocks with the named
   candidate list and four flags to resolve it, the platoon candidate is
   validated for a `teams` list before it can suppress the reference file, and
   the checkpoint clock reads the keys `slate_clock()` actually emits. **The
   false-signal batch is now the head of this tier**, which keeps the family
   argument intact rather than restating it: R69 and R70 both closed
   surfaces that degraded to silence, and the batch below is the same defect
   class on the refusal-and-brief surface instead of the intake surface.
4. **R114 + R67 — CLOSED 2026-08-15**, both migrated to CHANGELOG.md. The
   preflight-evidence batch landed: declared pitchers reach
   `preflight_upload.py` and `verify_export.py` off the brief matched by
   `delivered_sha256` (or `--declare-pitcher` by hand), a declared arm is an
   acknowledged WARN naming its role and evidence class, an undeclared one
   still exits 2, and a confirmed side with no probable evidences bats only.
   One correction landed with it: the live 2210_2g case was the DECLARED case,
   not the bullpen game R114's fragment described — R67 was the bullpen game,
   which is why the batch was already the right shape. **The false-signal
   batch is now the head of this tier.**
5. **The false-signal batch — CLOSED 2026-08-15**, migrated to CHANGELOG.md.
   Six of seven landed: R113 (the caution text names captain-LOCK vs
   captain-CAP and the substituted captain, not `by_player`); R112 (fix 1
   only — bank-observed SP counts now ride every refusal beside
   `feasibility.inputs`; fix 2, flooring the auto-bank's own SP-pair
   coverage, is declined, and `run_late_swap` stays unthreaded); R103 (a
   pinned same-game pair no longer starves the job list; the exclusion
   applies only to the unpinned remainder); R99 (the stderr gate and the
   brief field read one object); R92 (the two dead reads are replaced with
   `jobs_raised`/`jobs_unanswered`); R119 (`objective_differentiation` ships
   in the brief and `value_guard` is written). R71 closed only its (a): a
   cap fraction over 1.0 now raises instead of silently disabling both the
   solver and the validator. **R71(b)(c)(d) is the batch's one remainder**
   and keeps its own entry in Workstream 4. Gate moved 942 -> 962 tests.
   **R116 is now the head of this tier.**
6. **R116 — CLOSED 2026-08-15**, migrated to CHANGELOG.md. Both halves
   landed: `max_candidate_reuse` now defaults from the allocator's own
   `minimum_cap` arithmetic on every portfolio that is not entirely cash, and
   `distinct_lineups`, the cap, its source and its relaxation steps reach the
   brief's exposure block beside a count taken off the delivered bytes. The
   default relaxes down a two-rung ladder before it costs a delivery and
   refuses to move on a timeout; an operator's own cap is used verbatim and
   still refuses. Gate moved 962 -> 975 tests. **The QA-hardening batch is now
   the head of this tier.**
7. **The QA-hardening batch: R127 + R126 + R136 + R130 + R131** (2026-08-16,
   from BUILD's 2026-08-15 `2138_2g` fragment; Ben directed it in as the #1
   item) — six entries off one slate that delivered clean, filed in the
   fragment's own suggested order with P6 moved ahead of P4. **R129 — CLOSED
   2026-08-16**, migrated to CHANGELOG.md with R36 F6m(1), which its entry named
   as a precondition: `tools/promote_run.py` appends a truthful re-promotion row,
   the preflight refusal names the run to re-promote, one shared matcher stops
   the first-digest-wins read that the fix itself made dangerous, and a corrupt
   manifest is quarantined rather than overwritten. R98(3)'s restore remainder
   closed with it. **R128 — CLOSED 2026-08-16**, migrated to CHANGELOG.md, taken
   next while the preflight surface R129 touched was still fresh, which is the
   reason the previous note gave for ordering it there and it held: duplicate
   reporting now splits into `duplicates_within_contest` and
   `duplicates_across_contests`, one helper serving the preflight, verify_export
   and the brief. **R127 — CLOSED 2026-08-17**, migrated to
   CHANGELOG.md, taken in batch order as the batch's head and the only entry in
   it carrying a selection defect. Both halves landed. Three things the work
   corrected about the entry as filed. The entry proposed keying the named list
   off `pitcher_ceiling.unmatched_rows`, and that list is computed over the
   WHOLE SALARY FILE: most of its arms are absent from the pool and
   unrosterable, so the shipped list is resolved against the assembled FRAME
   instead, which per build-contract step 1 is exactly the declared-starter set.
   Second, the generalization has a boundary and it is now stated on the record
   rather than discovered: an absent input file reports `applied: false` with a
   count and NO list, because "the file is missing" is one fact about the build
   and not one fact per player — the same reasoning the paste intake uses at
   `SLATE_ABSENT_BLOCK_RATIO`. Third, (b)'s `signal_applied` was left a bool
   rather than split into a dict: every truthiness consumer of a dict reads True
   the moment the key exists, which is a worse failure than the one being fixed.
   The per-side answer ships beside it as `signal_applied_by_side`, and the
   DISAGREEMENT raises its own warning, since the disagreement is what BUILD got
   wrong. **R126 — CLOSED 2026-08-17**, migrated to CHANGELOG.md, taken
   in batch order as the batch's and the tier's head because it is the objective
   itself and the only item on this board that measures what Ben said he is
   optimizing for. Apex and washout are computed in the pipeline off the run's
   own `Ceiling` column, written to `diagnostics.json` and both success return
   paths, and carried into the brief inside R116's exposure block with one review
   line at build time. Four things the work established. The histogram is not
   garnish and the retained percent is nearly useless alone: on the fixture
   reproducing 2138_2g the concentrated and spread portfolios post the SAME apex
   and the SAME retained percent, differing only in `entries_fully_intact`, 0
   against 3 — and retained percent is a slate-size artifact that is not
   comparable across slates, which is one of the two problems the item existed to
   fix. `qa_portfolio` was about to shadow the block with a share-count number of
   its own, so it now reads the artifact and leads with it (the R128 lesson on a
   new surface) — and that surfaced R150, because the two game counts genuinely
   differ (16/18 against 18/18 on the archived 06-03 grid) over whether an arm in
   a game is washout exposure or a hedge. R127's boundary applied in BOTH
   directions: a missing `Ceiling` column reports one fact and no list, a missing
   PLAYER is named per player. Gate 1074 -> 1101 (`test_core` 716 -> 743);
   twelve mutations run by hand, all twelve caught, and one guard rewritten
   because a naive label sweep failed on the block's own disclaimer.
   **R136 — CLOSED 2026-08-18**, migrated to CHANGELOG.md, taken in tier order
   as the head of the batch and of the tier, with R135's prior file in hand.
   Four things the work established, two of which changed the entry. The
   sub-10% carry column as FILED is a constant: 3.17's threshold is an absolute
   10% on actual %Drafted and the v0.1 prior spreads 800% over every priced
   hitter row, so on 1905_7g the top hitter reaches 8.9% and the literal count
   returned 8-of-8 on every entry — it ships as the prior's own within-pool
   TIER, a rank, which does separate entries, and the absolute count returns
   with R10's fitted model. The chalk-sum's field-mean reference needs no model:
   the field's own mean cumulative ownership is exactly sum(own_p^2), an
   accounting identity, pinned against an explicit field built the long way. The
   magnitude of a delta is NOT readable (the prior under-concentrates by a
   measured 10.44 points) so the section closes on the cross-contest order
   within one file, which is the comparison the prior does support. And Showdown
   gets the captain RANK and no chalk-sum, because the prior budgets 800/200
   over a ten-seat Classic roster while a Showdown salary file lists every
   player twice — 186 rows for 93 players on the 2026-08-14 NYY@TOR file — which
   is a defect in the prior and now rides R139. Gate 1120 -> 1139 (`test_core`
   762 -> 781, `grew`); fifteen mutations run by hand, all fifteen caught, one
   only after the FIXTURE was fixed (identical shares across archetypes let a
   test assert the LABEL while the DATA came from the wrong block, which is
   exactly the defect the entry named). **The batch's three substantive entries
   are now all closed and its remainder is R130 + R131, both P2 and XS-S with
   one half of R131 being Ben's rather than DEV's; sweep them opportunistically
   rather than as a tier slot. R117 is the new head of Tier 1**, on the tier's
   own ordering: it is the only P1 left above it and it changes SELECTION where
   the remainder changes labels. What R136 left behind for
   the two smalls: `_leverage_legend` and `section_leverage` are the read-once
   pattern to extend, and `tools/qa_portfolio.py` now has 24 tests rather than
   five, all on sections 3 and 4 — sections 1 and 2 are still unpinned and R11
   owns them. The entry as filed said
   "one session takes both" of R126 and itself; that was WITHDRAWN when R126
   landed, and correctly — R126 landed in the pipeline and the brief while R136
   is a qa_portfolio panel, so they were never one surface. **R135 CLOSED
   2026-08-17**, migrated to CHANGELOG.md, taken later the same day on that
   sequencing note rather than in tier order, and it paid: R136 entered with its
   input specified rather than assumed. **R130** (P2, S, WS4) is reporting only; its proposed
   remedy is declined on the entry. **R131** (P2, XS, WS6) is the smalls, one
   of which is Ben's rather than DEV's. The batch shared two surfaces with work
   already here — R129 with R98(3)'s restore remainder, which closed with it on
   2026-08-16, and R127 with the Tier 4 FanGraphs decision — and both are
   cross-referenced rather than duplicated.
8. **R117 — CLOSED 2026-08-18**, migrated to CHANGELOG.md, taken in tier order
   as the tier's head. Both halves landed and three things about the entry as
   filed are corrected on the record. The CONTINUATION LINE was never the
   problem: `_HAND` anchored on `$`, and mlb.com renders the hand two ways — alone
   on its line (Ben's 07-29 paste, which always parsed) and with the record
   trailing it on ONE line (the 08-13 paste), which fell into the `_STATLINE`
   branch and was consumed as decoration. The module docstring carried the first
   render as the only one, which is how the assumption survived three slates. The
   silence had THREE faces where the entry named one: zero probables attached
   with no warning, `_assign` reading a pitcher count of 0 as "nothing was
   pasted" by design, and `_flush_pending` writing the held name into
   `game.venue` (a venueless paste came back `venue='Hayden Wesneski'`). And the
   loudness half generalized past F4 to F1 and F5, because all three carry the
   identical "every value is neutral" condition — with the distinction that
   carries it being INERT (scored rows, moved none) against ABSENT (scored
   nothing), which are different facts with different remedies. The falsifier was
   checked and did not fire: the salary header carries no handedness column, so
   the parse half stands. Gate 1139 -> 1157 (`test_paste_lineups` 75 -> 82,
   `test_core` 781 -> 792, both `grew`); fourteen mutations run by hand, all
   fourteen caught, one only after the FIXTURE was fixed — dropping the held name
   survived because the fixture carries a venue BEFORE the pitcher block, so it
   could not distinguish the two behaviours, and the venueless paste is the only
   shape that can. The entry's rider (derive the slate tag before lighting the
   beacon) did NOT land with it and moves to R131's smalls. **R133 is the new
   head of Tier 1**, on the ordering this tier already recorded: R117 was ahead
   of it because R117 changed SELECTION where R133 changes labels and overrides,
   and that reason is now spent. What R117 leaves for R133: the pool report's
   `opposing_probables_incomplete` is the two-list pattern to follow, and
   `factors_inert` is the precedent for a review key that sits BESIDE the gates
   rather than inside them.
9. **R133 — CLOSED 2026-08-18**, migrated to CHANGELOG.md, taken in tier order
   as the tier's head. Parts (1), (3) and (4) landed; (2), the equal-weight
   seeded ninth, is filed to MLB_Classic.md as a selection question and is
   Ben's. Four things about the entry as filed are corrected on the record, and
   three of them changed the work. **The contract's 5-of-9 bar was already
   implemented and the blocker CONTRADICTED it**: the confirmed path in
   `live_data_adapters` has always blocked at `n < 5` as a crosswalk failure and
   warned from 5 to 8, twenty lines above the loop that then blocked at `< 9` on
   the same team and the same fact. So the filed fix, "move the blocker to the
   contract's 5-of-9 bar", would have produced two blockers on one team; what it
   needed was for the later loop to stop re-deciding a decided question. CLAUDE.md
   and SKILL.md both scope their 5-of-9 sentence to a name-crosswalk failure and
   always did. **There was a THIRD reader and it was the one that decided
   certification**: `_derive_workflow_gates` recomputed `thin` at `< 9`
   independently of the blockers list, so a confirmed team at 8 with no
   status-dropped rows produced NO blocker at all and still could not certify —
   `--ignore-pool-blockers` had nothing to override and the gate failed anyway.
   **The paste module's docstring claimed the opposite of the code on the exact
   point**, ending "the team stays confirmed" where `lineup_status` has never
   been `confirmed` below nine rostered rows; the source fragment quoted the
   paragraph above that sentence and missed it. Corrected in place. And what the
   work established that the entry did not carry: the crosswalk bar and
   `MAX_HITTERS_PER_TEAM` are the same number for different reasons — five fills
   a maximum DK stack — so the new bar reads the solver constant rather than
   copying a doc, and `assumed_gates` was recording a request that had no effect,
   which is a truthful-labels problem and not only a broken flag. (4) was checked
   by RUNNING both overrides rather than reading them, as instructed, and both
   reproduced. Gate 1157 -> 1182 (`test_upload_integrity` 218 -> 238,
   `test_paste_lineups` 82 -> 87, both `grew`); seventeen mutations by hand, all
   seventeen caught — but TWO survived the first pass because the test had COPIED
   run_slate's gate merge instead of calling it, which is the fourth consecutive
   item with a green test over a fixture that pinned nothing and the first where
   the remedy was to make the code testable (`resolve_gate_assertions` extracted)
   rather than to fix the data. One more read SURVIVED off a stale `__pycache__`
   and was a harness artifact; the harness now clears it between runs.
   **R121 is the new head of Tier 1**, on the ordering already recorded here: it
   is the next P1 in the queue, it is S, and it is the only remaining item that
   changes what a session BELIEVES at decision time rather than what a report
   says afterward — a decremented mental countdown read 24.7 real minutes as "~5"
   and cost a five-control relaxation against a floored 34-candidate bank. What
   R133 leaves for it: nothing shared: R121 is `tools/slate_clock.py` plus a
   SKILL.md rule, no intake or gate surface in common.
10. **R121** (P1, S, WS6) — the clock is a measurement, not an estimate: two
   sessions in one day carried a decremented mental countdown, erred in the
   expensive direction (24.7 real minutes read as "~5"), and the second
   instance caused a five-control relaxation against a floored 34-candidate
   bank. `tools/slate_clock.py` (<2s, no engine import), a `T-minus` stderr
   line at build START, and the SKILL.md same-turn-measurement rule.
11. **R11, moved up from Tier 5 on 2026-08-16** (P2, S, WS5) — the
   deterministic QA delta on the chassis R134 landed: qa_portfolio already
   reports enrichment self-claims, market/Savant cross-checks and the
   frontier proxies, and what remains of R11's Tier 1 design is the
   known-problem-names registry, per-player exposure flags (>=90%),
   relaxation-count surfacing beside the findings, and small-sample APPG
   flags. The hand-run version found six items across two slates in one day,
   and Ben's R134 directive names an adversarial QA pass as the standing
   follow-up to every unattended build. Its four walls stand verbatim on the
   entry; the Tier 5/Tier 6 double listing is resolved there too.
12. **The swap-rails batch: R66 + R68** (P2, S each, WS4/WS5) — silent
   `large_wta` scoring on the swap API, and a downgrade guard inert on
   DK-redownloaded parent files (a strictly worse swap ships without
   `--accept-downgrade`). R67 moved up into the preflight-evidence batch.
13. **R36 F3m + F6m-remainder** (P1, S + M, WS5; elevated off the trip-only
   rule by this reorder) — `assumed_gates` reaches neither the brief nor the
   manifest while the record stamps `certified` (verified on a real 07-29
   delivery). **F6m's corrupt-manifest half (1) CLOSED 2026-08-16** with R129,
   which named it a precondition: corrupt is now its own read state, the bytes
   are quarantined before any write, and an unquarantinable manifest refuses
   instead of overwriting. What remains of F6m is the append-only-plus-derived-
   index redesign with its unlocked read-modify-replace concurrency half, and
   (2)'s `salary_sha256` on the record; that remainder is M, not S, and no
   longer blocks anything. The manifest is the answer to
   "which file do I upload"; both fixes are recording-only, no gate change.
   **R120 rides this batch** (same manifest surface): a delivered
   upload-ready file names a `runs/` dir that does not exist on the mount.
14. **The claim.py batch: R31(b)(c), R86 rides** (XS-S, WS6) — one file.
   **R110 left this batch by landing early on 2026-08-12**, out of order and
   knowingly: Ben approved clearing the ten stale claims, and `sweep
   --release` is useless while the release path cannot resolve the names
   `sweep` prints. The batch's own argument therefore already cost what it
   predicted, a second pass over `claim.py`, and what remains is (b)(c): (c)
   under-reports foreign dirt on the one file the contract most wants
   serialized. R31(d) stays Ben's and is NOT in this batch.
15. **R80(a) + R88** (XS + S, WS6) — the scrub fork that can persist a key
   into `slate_bundle.json` warnings, and the allowlist test that mechanizes
   the DK wall. Minutes of lift against the two failure classes this repo
   treats as absolute.
15b. **R150, new 2026-08-17** (P2, XS + one decision, WS6) — not a tier slot
   of its own. Two surfaces now count one lineup's exposure to one game and
   disagree by construction, and the decision is Ben's because it is a
   correlation belief. Rides R11, now that R136 has shipped without
   resolving it: R136's panel restates the gap in words beside the two counts
   rather than closing it.
15a. **R149, new 2026-08-17** (P1, S, WS6) — the installed skill is six moves
   behind and the drift check that exists to catch that is structurally blind
   in a cloud session. Enters the tier rather than Tier 5 on the same
   reasoning R142 used: a session that loads the stale body builds without the
   supervisor and without R143 and has nothing telling it so, which is a
   surface steering the operator wrong at the moment it costs most. Sits here
   rather than at the head because the pointer re-save mitigates it today
   without any code.

## Tier 2 — the measurement loop. The strategy payoff everything else is gated on, in this order.

0. **Resequenced 2026-08-27 (Ben's greenfield instruction: data-driven
   leverage, and the dual objective as P(top ~1%) per contest / P(washout)
   per portfolio).** The tier absorbs R251–R262 and its working order is:
   **R118** (+the settle rider — now load-bearing twice, since R258 mines
   thresholds off the same standings and R262 eventually optimizes against
   them) → **R48 + R83 + R258's mining half + R254's share prior** (ONE
   mining batch: leverage table, factor-audit persist, contest thresholds,
   captain shares) → **R251** (input freeze; capture half rides the next
   slate session, ahead of this position) → **R252** (+R137 riding) →
   **R255** (grade it) → **R10** (unchanged: the fitted ownership model,
   still gated on R225 for Showdown cells, now also feeding R254 and R262's
   eventual prize-share reading) → **R258's predict half** → **R260** →
   **R259** → **R261** → **R262 (gated, Tier 4)** → **R140**. Hanging off
   with named conditions: R253 (after R252 grades a cycle), R254 (after
   R225 + R238), R256 (only on R255-measured residual). R13 stays the
   umbrella decision and now has a defined evidence stream: R258's
   threshold-vs-construction table and R261's graded tail predictions are
   what make the stakes decision decidable on data. **Amended 2026-08-28
   (ed9):** R258's predict half is the conditional threshold `T[s,c]` and
   its mining covariates ride the one batch (rider on the entry, landed
   before the batch ran); R262's solve is epsilon-constraint, not a
   weighted sum.

16. **R118** (P1, M, WS7/WS2) — retain the per-player FPTS map the miner
    already computes and strips (`field_miner.py:1961`), and ship the
    counterfactual replay tool. This moves to the head of the tier because
    it multiplies everything under it: it converts the 271-contest archive
    into the grading substrate R10's duplication bar, R37(2)'s floor-5
    question, and R40's routing question currently wait on live tranches
    for — same frozen inputs, alternate construction policy, scored against
    the REAL archived field, deterministically. Self-validating: replaying
    every archived own entry must reproduce its recorded points and rank.
17. **R135 — CLOSED 2026-08-17**, migrated to CHANGELOG.md. Taken out of
    Tier 2 and ahead of its slot on R136's own sequencing note (two of R136's
    four columns are ABSENT until it lands), which is the one case where
    jumping the tier is the tier's own instruction. `tools/ownership_pred.py`
    emits the pre-lock prediction and grades it against an archived standings
    export; the module is tracked and pinned under R107(a)'s discipline, and
    the two skill steps are in SKILL.md and the archival runbook. **The
    finding that mattered is the join:** `grade_against_actuals` keys on DK
    Player_ID and a standings export has no such column, so the prediction
    now records the salary file's own name crosswalk at emit time or the
    grade silently joins nobody. Two baselines ship rather than one, because
    flat-12 is a constant 12% against a 1000% budget and beating it is nearly
    free. First graded slate (archived 06-03): prior MAE 14.35 against
    flat-12's 14.53 and flat-budget's 15.64, arms bucket 46.95. **R48 + R83
    is the next item in this tier after R118.**
18. **R48 + R83** (S each, WS2) — the per-contest leverage table and the
   per-run factor-audit persist plus hash-bound enrichment inputs: the
   grading substrate R10's bar reads against. R48's backfill re-mine is the
   same idempotent pass R118's retention backfill runs; land them together.
19. **R10** (P1, M, WS2) — the funded modeling item, unblocked
    satellite-only, graded on duplication as well as ownership, live builds
    consuming precomputed artifacts only. The one M-lift item whose impact
    lands in the cell that is 4,201 of 4,879 of Ben's MLB entries. Gained
    its two control halves 2026-08-16 as riders on the entry (leverage-carry
    inside the primary stack; replay-calibrated duplication budget) — built
    only after the prior beats flat-12 in the cell, which is unchanged.
20. **R140** (P2, M, WS7; 2026-08-16, from the leverage fragment) — the
    opponent-conditioned field profiles for the recurring satellite
    families, deliberately last in the tier: it consumes R118's replay
    substrate and R48's persisted tables, and its own consumers are R10's
    control halves. The registry it reads already exists (3.19: 15,402
    users, 2,211 regulars; satellite fields are 80.8-91.3% regulars).

## Tier 3 — funded M-lift build-integrity work, adjudicated individually per Ben's 2026-08-12 instruction, in order.

21. **R115** (P1, M, WS4) — SP-pair coverage: the bank freezes at
    `requested_n`, exit-10 cannot engage past the 2x heuristic, ceiling-
    ordered job truncation concentrates arms, and no control can floor arm
    diversity — the 08-13 slate lost its whole window to this and the
    1507_3g session monkey-patched the engine mid-slate for want of the
    control. Lands beside R98(3), which owns the budget half of the same
    failure; R112's reporting sliver rides the false-signal batch.
22. **R132** (P1, M with a cheap S variant, WS4; 2026-08-16, from the 08-14
    fragment this board wrongly recorded as merged) — the build refuses instead
    of escalating its own controls. On 2026-08-14 `2138_4g` that cost a
    delivery: five refusals over twenty minutes from T-15 to T-8, each naming
    one more control, while the operator relaxed them one at a time by hand.
    Sits directly behind R115, which owns the bank-composition half of the same
    "the build produced nothing" family, and ahead of R124 because those two are
    the same
    failure at two stages — R132 is the delivery that never got built, R124 is
    the delivery that got built and was not shipped — and R132's is the harder
    half to recover from, since an infeasible MILP writes no export for
    `--deliver-always` to mirror. Split 2026-08-16 on the autonomy boundary,
    see the entry: the small-slate-defaults S variant and the engine-guess
    rungs are DEV-ready; the exposure-cap rungs are R125(c)'s Tier 4 decision.
23. **R124** (P1, M with an S first half that can land alone, WS5) — the
    delivery guarantee: three `verify_export`-clean files existed 6.5
    minutes before the 1810_3g lock and the slate was nearly skipped because
    the only copy was named `DO_NOT_UPLOAD_`. Mirror a legal-but-uncertified
    candidate as `UNCERTIFIED_<tag>_<run>.csv` named in the refusal (the S
    half); `--deliver-always`; R89's single-pass blocker collection rides.
24. **R98(3) + (4)-tail** (P1, M, WS4) — derive the bank budget from entry
    count and job-list size instead of leftover clock; let a CERTIFIED brief
    distinguish a deliberate cap from a starved one; absorb R112's deeper
    half (bank-observed vs `feasibility.inputs` counts in the refusal) here.
    Adjudication: high impact — fourth recorded instance of the starved-bank
    family, and it certifies — but (1)/(2) already made the failure loud,
    so it follows Tier 1 rather than preceding it. **Gained two remainders
    2026-08-16** from the 08-14 floored-bank fragment, both partially merged
    before: the restore-an-earlier-run case (R129 owned the fix and **CLOSED it
    the same day** — `tools/promote_run.py` restores a certified run to a
    run-scoped delivery path with an appended manifest row, so restoring no
    longer makes preflight fail against itself) and the past-limit-reference
    brief line, which is the one still open here.
25. **R81** (M, WS3; the design pass is S and ARMED) — the slate-fingerprint
    contract at every intake boundary. Adjudication: one S-lift design pass
    retires the wrong-slate FAMILY that Tier 1's R70 patches pointwise; run
    the pass next session that touches intake, size the build from its
    output.
26. **R36 Finding 10's floor + R84** (P1 M + S, WS5/WS4) — top-K compatible
    candidates per entry, never diagnose from post-filter sets, name any
    entry the prefilter emptied; R84's per-entry compatible-in/kept counts
    land with it as the visibility half. Adjudication: "proven infeasible"
    about a reduced problem is a truth defect at the money boundary, but the
    late-swap sizing is UNSIZED pending the owed re-measure, so it sits
    third in the tier.

## Tier 4 — decisions owed, mostly Ben's. Minutes of decision that unblock sessions of work; each listed with what it unlocks.

- ~~**R263's three bands, and R37(2)'s (a) with them**~~ — **ANSWERED
  2026-08-28 by Ben and OFF this list.** His dated go-live instruction took
  R37(2)(a), R37(2)(b) and R263's shadow half live in the same session; the
  `Decided` entry and the shipped entry are both in CHANGELOG.md. What is still
  owed from R263 is narrower than this line described and now lives in R263
  itself: the three HARD bands, which he deferred to the R238/R239
  contest-awareness cluster, and the satellite chalk floor, which waits on the
  R10 fit. R37(2)'s floor-5 question is CLOSED, not deferred.
- **R41's two decisions** (sequencing vs R37; relaxation policy, now
  carrying the Pool_Basis rider) — unlocks the one L build on the board,
  Showdown certification, roughly a third of entered volume. The build slots
  after Tier 3 unless the sequencing decision says otherwise.
- **R31(d)** — the engine mutex, priced by the 2026-08-11 incident.
- **R17's wire-or-delete** — DEV's standing recommendation is DELETE (no
  production caller; `dk_entries_manager` stays the one reader), after which
  the strip fix is moot.
- **R107(a)** — adopt-or-delete `tools/fetch_fangraphs_platoon.py`, a week
  old with the Quick Card naming the tool the whole time.
- **Quick Card split (ARCHIVE, S; adopted 2026-08-14 from ed4 §5)** — item 1
  of the Card is one 900-word paragraph carrying four dated self-corrections;
  split the command-and-pin line from the correction history (a `0a` section
  read only when the gate misbehaves). It is the most-read paragraph in the
  project and the hardest to read; ARCHIVE's file, ledger claim required.
- **The FanGraphs automation decision (dated, from the 08-14
  delivery-guarantee fragment)** — the two stale references are exactly the
  two MANUAL ones (platoon 9.9d/limit 7, season pitching 29.1d/limit 14; the
  HTTP-fetched Savant pair was current), and the stale platoon file
  fabricated a TEX order that took 19 roster slots across 15 lineups on a
  team that never posted. Reverse the manual-by-decision rule (Chrome-driven
  pre-slate refresh in the morning prestage, Savant stays HTTP, staleness
  becomes a build-time line) or reaffirm it with the cost now priced. This
  decision also settles R107(a).
- **R125's two decision halves** — posture fallback-with-record for
  unmatched contest names (today an unmatched name hard-blocks; falling back
  reranks contests entered tonight, so it is a strategy change), and a
  counted Classic relaxation ladder mirroring Showdown's (auto-relaxation of
  exposure caps is exactly what R98(2) warns concentrates). Its (a) half,
  the bullpen-day PO/PLR auto-declaration with the inference recorded, is
  DEV-ready the day Ben approves the policy. **Urgency raised 2026-08-16:**
  R134's supervisor now takes every classified stop, so the infeasible-caps
  refusal R132 names is most of what still ends a window early, and the (c)
  ladder decision is what unlocks R132's full version — the
  highest-leverage minutes on this list.
- **The `Solo Shot` archetype row (R131(a); dated, from the 08-15 QA
  fragment)** — two contests on the 2138_2g slate ("MLB $2.5K Solo Shot
  (Night)", "MLB $500 Solo Shot (Night)") matched no row in the 24-row
  `dk_contest_archetypes.csv` and blocked the build until postures were passed
  by hand. They are single-entry GPPs and the family recurs. This is listed
  here rather than as ARCHIVE work because the 08-09 curated-archetypes
  fragment already settled the principle for exactly this row: a curated row
  reaches `resolve_contest_shape` immediately and reranks lineups on contests
  entered that night, which makes it a strategy change and Ben's dated
  decision. Decide it with **R1c-tail** — same write, same file, same
  reasoning — and ARCHIVE executes both in one pass. Interacts with R125's
  posture-fallback half: a fallback would have made this slate not block at
  all, so deciding that first may make this row a convenience rather than an
  unblock.
- **D1 (dated 2026-08-16, from the leverage fragment) — salary-leave: act or
  keep recorded.** 3.17 holds it "recorded, not acted on" (winners leave $250
  median, field $200, us $100). R136 reports it; ACTING on it — a portfolio
  distribution target over total-salary bands — is a strategy change and
  Ben's. R118's replay can price the ceiling cost of leaving more salary
  before deciding, which is the cheap way to decide.
- **D2 (dated 2026-08-16, same fragment) — the supersatellite posture.** The
  one archetype where winners run anti-chalk (3.17: -13.2) and our weakest
  family (3.18: 12.8 median percentile vs 28.2 archive). Once R10's satellite
  prior exists: does the supersat cell get its own ownership-budget tilt, or
  does the family stop being entered (R13 territory)? Decide from the cell's
  own data, not before it exists.
- **D3 (dated 2026-08-16, same fragment) — captain ladder defaults (R139 step
  2)**, once R139's report half has run for a few slates. The control shape
  and its falsifier are on the entry.
- **R240 (dated 2026-08-27, from the 08-26 contest-awareness fragment) — the
  punt-captain template.** Whether the Showdown ladder carries a
  bottom-salary-captain thesis family and at what weight. It is a
  construction class no cap value can produce (measured: 16 forced-distinct
  captains at cap 0.08 still never captained anyone under $5,800), so the
  decision is whether the portfolio should reach it at all. Same class as
  R156's pitchers-duel rework: template changes are strategy.
- **R247(d) (dated 2026-08-27, from the skill-blind cap fragment) — what the
  player cap should measure.** The flat cap demotes exactly the players the
  build liked most (measured: twelve slots moved from the four best to the
  four worst on 2145_1g_sd). Options on the entry: scale the cap by the
  build's own Base rank, or cap correlated BLOCKS (k-subset sharing) instead
  of persons. Either is a strategy change and Ben's; R247(a-c) lands the
  measurements that price this decision first. Note R262 is the structural
  resolution of this same question — if coverage selection ships, the cap
  reverts to a guardrail and (d) may not need deciding at all.
- **The per-contest captain target (dated 2026-08-29, from the captain-
  duplication fix spec) — is distinct-captains-per-contest the right target
  at all?** It is the mechanical consequence of applying today's 0.25 to a
  7-entry contest (`floor(0.25 x 7) = 1`), not a chosen policy, and forcing
  seven distinct captains means captaining the bank's worst options. R247
  already MEASURED that tightening a cap moves slots from the best-graded
  players to the worst-graded ones with every counter clean, so the cost of
  full distinctness should be priced against R247's frontier before it is
  adopted as a default. **A per-contest cap of 2 is the obvious weaker
  alternative and is not obviously worse.** If the answer is "distinct," R240
  (punt-captain template) stops being optional — a 7-entry contest needs 7
  captains and the ladder constructs none below $5,800, so the deep captains it
  would be forced onto are exactly the class R240 says no cap value can reach.
  **STATUS 2026-08-29: this question is now a ONE-VALUE change, not a rebuild.**
  R239(b) shipped `max_cpt_per_contest` as a NAMED control defaulting to **2**,
  deliberately not derived from the pct, precisely so this decision stays yours
  and stays cheap. R239(c)'s report and R266's warning both shipped, so realized
  per-contest captain counts are in every brief and the cost of moving to 1 can
  be priced against R247's frontier instead of guessed. Two things to know
  before answering: the effective bar is `max(1, min(m, n - 1))`, so **2 already
  forces distinct captains in any 2-entry contest** (a flat 2 did not, which is
  a defect found and fixed on 08-29); and the 08-28 delivered bank was
  INFEASIBLE at 1 and feasible at 2 by the Gale-Ryser precondition, so answering
  "distinct" makes captain-pool widening the normal path rather than the
  exception.
- **R266's severity (same date, same fragment) — does the per-contest captain
  check ever BLOCK, and at what per-contest share?** It ships WARN by default
  because a deliberate double-up is a legitimate play and CLAUDE.md reserves
  concentration to Ben. **SHIPPED 2026-08-29 as specified:** WARN by default,
  with the hard failure behind `--strict-contest-diversity`, which is wired to
  nothing. Turning it on is a flag, not a default change. Costs one sentence to
  answer and nothing waits on it.
- **R262's production switch (dated 2026-08-27, from the greenfield
  instruction) — when scenario-coverage selection replaces the
  Ceiling-proxy objective.** The instruction funds the WALK (R251–R261:
  capture, grade, model, predict — all measurement, none of it changes what
  gets built); switching SELECTION to optimize P(top-1%)/P(washout) changes
  every delivered file and lands only after R261's predictions grade
  adequately across a stated number of slates, with the threshold Ben's to
  set. Reads the same evidence R13 wants, so decide them together or in
  sequence — but the walk does not wait on either.
- **R34-tail** (three wrong `upload_ready` records in a provenance file),
  **R25-tail** (minimal-repair fast path), **R111(b)** (one GitHub setting:
  default branch to `main`), **Sync-tail** (the PAT; nothing blocks on it,
  worth doing for the container alone), **R30's data half** (one fresh
  entry-history export makes the two rank-1 satellite finishes gradeable),
  **R1c-tail** (ARCHIVE executes the curated `ticket_count` rows, which is
  also what R40's routing decision is waiting on).

## Tier 5 — prevention and hygiene. S-lift, real but bounded impact; batch opportunistically between tiers, never instead of them.

**R91 + R79(a-d)** (the mutation harness and the coverage batch, one theme;
R79(e) died with R96's deletion decision); **R90**'s property half (the
RotoWire fixture stays blocked on its hand step); **R82** (unknown-code
report); **R106** (ticket_count reaching the resolver; feeds R40's evidence
trail); **R108** (the `dk_tokens` module; moves the module-count pin);
**R111(a)** (sync_check resolves the real branch); **R76** (doc-truth batch —
MANIFEST.md's stale seed keeps being cited by every external review, cheap to
retire); **R77** (dead code carrying the forbidden pool reduction one call
site away; the two named residents `tools/_operator_patch_20260813_crossgame.py`
+ `tools/_run_patched_build.py` were SWEPT 2026-08-18 to
`_to_delete/tools_residue_20260818/`, so what remains under R77 is the in-tree
dead code proper); **R75** (Savant same-name collapse); **R109**'s
sync_check half (the residue sweep waits on Ben's delete grant); **R78**
(remainder only — the floor cap landed 2026-08-17 under R147; what is left is
the fixture dtypes, the cp310-only lock hashes, and installed-vs-lock in the
dependency gate); **R148(b)** (handedness is reported per side while the data is per hitter;
(a) closed 2026-08-18 and migrated, and Ben's decision half died with the
premise);
**R229** (wind-band seam threading to no band while `wind_applies` is True; the
slate clock dropping unparseable rows uncounted — the (b) half lands with R121,
not here); **R230** (three assertion seams that survive mutation; rides R91 above
and should be taken in the same session); **R231** (1,778 leaked `_test_r3_*`
directories plus the session-residue inventory — the sweep needs Ben's mv grant,
same grant R109 and R77 wait on, so all three go in one ask); **R232** (doc truth:
MLB_Classic.md names a RETIRED checksum manifest as its version authority and
MANIFEST.md still reports 12 modules/119 tests — this is R76's own subject
sharpened, so merge the two rather than working them apart; ed8's F-44
corroborates and its generate-the-counts fix shape — a small script emitting
the module/test facts that docs then cite — is the recorded fix option);
**R241** (the `--postures` vocabulary mismatch, XS-S, rides any build_slate
session); **R243** (the container-build recipe into the sync protocol, docs
only, rides any DEV session that has run one);
**R44** and **R38** (archival
operator time); **R89** (consolidated blockers line, chmod final/ — gained
the single-pass rider 2026-08-14 and now rides R124); **R137** (the
market-vs-crowd divergence screen, quota-priced on its entry — a
quiet-slate item by the fragment's own sequencing); **R141** (the late-swap
leverage pass, behind R135 whose prior it recomputes); **R138** (the
one-stack-family-per-game SKILL.md practice, XS — rides R131's SKILL.md
session, never instead of a tier item).
R117 left this tier 2026-08-14 evening, elevated P1 into Tier 1 on its
third recurrence.

**R11 left this tier 2026-08-16, moved to Tier 1's tail**, and its double
listing (this tier plus Tier 6) is resolved to that one entry. The 2026-08-16
note that had sat here claimed its R114/R116/R117 gate fully cleared; that was
false on R117, which is open in Tier 1, and the correction is recorded on
R11's entry. What moved it anyway: R134 landed qa_portfolio, which is R11's
deterministic tier half-built, and the hand-run pass found six items across
two slates in one day.

## Tier 6 — deprioritized: high lift or unmeasured impact, explicitly per Ben's 2026-08-12 instruction. Not deleted; the bar to pull one is a named measurement.

**R87** (M plus a golden regen, for throughput no measurement says we lack;
its own no-ride rule stands); **R42(b)** (M on a path R42(a) and `.pylibs`
made rare); **R9b** (M; R9a already took the always-loaded win); **R12**
(operator-time class; R11 left this tier 2026-08-16, moved to Tier 1 — the
double listing is resolved); **R58(d)** (one weather window on DH slates
only); **R58(c)** (same scope, and blocked on R90's fixture besides);
**R61-tail** (P3, no reproduction exists). The do-not-build list is unchanged
and is not a tier. This tier is the board's DEFERRED list: everything here
is explicitly low impact relative to lift, and the bar to pull one remains a
named measurement.

## Kept as-is (2026-08-14 audit): components verified worth their place

Recorded so the next review does not re-litigate them. `scipy.optimize.milp`
with the three-gate certification chain (V1: 928/928 at every per-suite pin;
golden replay green on a tracked-files-only checkout). The paste-primary
intake and `build_slate_pool` front door (R32; the paste suite's 75 tests run
real since R62). The enrichment stack as the projection layer's
differentiation: F1 devigged-and-de-parked implied totals with clip and named
degradation, F4 opposing-SP xwOBA x platoon priors, F5 park/weather, xwOBA
Base correction, xISO/K-rate ceiling multipliers — all wired and non-neutral
on the newest delivered run (V2: 37/36/35/4 non-neutral counts in its brief),
which matters because enrichment is the only GPP/cash differentiator (R119).
`preflight_upload` as the sole pre-upload rule (V1 exit 0 on the newest
delivery; its two blind spots are R114/R67, fixes not replacements).
`field_miner` and the append-only archive discipline (271 mined contests
with self-checked ownership recomputes). The claims protocol with R31(d)
open. The workstream board itself: five external critiques adjudicated
without a rebuild, and the one reviewer who ran the gate (ed4) converged on
the board's own priorities — that record is working.

**Added 2026-08-29, from the `1305_12g` repair slate — three components that
caught a live failure and are named here so a future refactor does not quietly
weaken them.** `preflight_upload.py` caught BOTH live failures on its own, with
no session insight involved: Amador when COL posted, and all ten Feltner slots
when the probable changed after delivery. It is the reason that slate did not
go up with dead players in it, and it is the reason R266 was filed onto this
surface rather than the brief. `verify_export.py` caught the session's OWN
repair bug — a CLE bat placed in an entry rostering KC's starter, a hitter
opposing its own SP — which would otherwise have shipped; that constraint is
load-bearing and is carried forward into R267(a)'s filter by name.
`qa_portfolio.py`'s frontier section correctly rejected two attempted
improvements as regressions, once pre-lock and once post-lock, on its own
numbers. Three tools, three real catches, one slate. The open items against
each of them (R266 on the preflight, R175 on verify_export, R193 on qa) are
additions to working checks, never replacements.

## Externally gated — holds no DEV slot; unchanged in substance from the old queue.

- **R37(2)** (P1, M, WS2) — stage 2 is a MEASUREMENT: floor 5 and the quota
  wait on one tranche archived with the floor-4 portfolio in it. Waits on
  ARCHIVE and slates being played, not a DEV slot. The 4-2-x cap is sized
  after that.
- **R40** (S, decision, WS2) — waits on the curated-archetypes execution
  (R1c-tail) and on more than n=2 one-seat finishes, graded on BOTH the
  mean-delta and percentile statistics.
- **R13** — the umbrella decision, after graded slates accumulate; it still
  governs the do-not-build gate, and nothing above waits on it by design.

**Pull rules, restated for the tiers:** a live build that trips any filed
item pulls it into the current session regardless of tier — that is how
R36's remaining accepted findings (F8, F7, F12, F1m, F14, F2) enter, per
their standing rule. **R87** never rides another change. A Tier 5 item that
a Tier 1-3 session is already touching rides that session. Nothing in Tier 6
is pulled without naming the measurement that changed its standing.
Priorities and efforts sit on each entry; the workstream intros carry the
per-surface logic.

---

# The open board, by workstream

Reorganized 2026-08-10 (DEV, Ben's instruction): entries are grouped by the
surface a DEV session actually works, not by filing date. Every entry moved
VERBATIM — wording, priorities, dates, and provenance lines untouched — and
each entry's header still names when and where it was filed. The dated
tranche introductions that used to wrap these entries live under "Board
history" near the bottom. Item numbers are never reused; the next free
R-number comes from scanning this file AND CHANGELOG.md.

## Workstream 1 — Showdown correctness and certification

R104, R45, R105 and R54 landed 2026-08-10 as one session and their entries
migrated to CHANGELOG.md. R41 stays the destination and stays decision-first;
R122 and R123 joined 2026-08-14 from the NYY@TOR BUILD fragment, both
verified in tree, and both are exactly the kind of review-grade honesty work
R41's certification question will inherit. What the batch changed about it: the
bookkeeping R41 was going to have to fix first is fixed. Showdown relaxation
counts are honest and cover the both-relaxed rung, ignored locks are reported
rather than swallowed, the OUT vocabulary is shared with preflight, the
manifest records a status from the closed set instead of a preflight verdict,
and the paste tool can produce a Showdown feed at all. R85 (Workstream 5) was
the batch's named rider and did not get pulled.

### R41. Bring Showdown under the three certification gates (P1, L, decision first) | new 2026-08-01, from the GF-spec adjudication (F-15)

- **What:** CLAUDE.md's Showdown section has promised this item since it was written — "Bringing Showdown under the three gates is open backlog, not a decision left implicit" — and no numbered item has ever existed. Filing it is itself a contract fix: the contract said "open backlog" while the board said nothing. Today Showdown ships review-grade by design: it does not enter `run_slate`, passes none of workflow_valid / selection_certified / allocation_certified, `run_late_swap` cannot refine it, and the honest label plus preflight are the entire safety story.
- **Why P1:** roughly a third of archived contest volume is Showdown-side and growing, and the certified path's guarantees — front-door intake, checkpoint review, promoted-run refinement — do not exist for a product family entered routinely. The review-grade label is honest, but it is a label, not a gate.
- **Fix, decision first:** the accepted shape is Showdown through the EXISTING three gates — a Showdown-aware front door beside or inside `run_slate` — not the GF spec's unified roster-contract rewrite (A-16, rejected; see do-not-build). Two decisions before code: (1) sequencing, because this competes with R37's build work for the same DEV slots and touches the same solver surfaces; (2) relaxation policy, because Showdown's counted relaxations (overlap, then captain lock, then thesis) currently ship review-grade, and certification must state whether a nonzero relaxation count blocks the certified label or rides it as a named warning. Done when: a Showdown build produces a certified artifact through the same three gates Classic passes, `run_late_swap` can refine a promoted Showdown run, and CLAUDE.md's Showdown section retires the review-grade carve-out.
- **Rider 2026-08-12, from the GF spec third edition's F-20 residual, verified in tree:** the empty-`Starting` fallback to an `all_healthy` pool (`showdown.py:109-175`) is deliberate, stamped `Pool_Basis` on every row, pinned by `test_showdown.py:111/141`, and reaches the checkpoint via `build_slate.py:1912/2069` — honest at review grade, which is all Showdown ships today. When this item brings Showdown under the gates, pool basis joins the certification evidence beside the relaxation counts: a pool built on `all_healthy` can certify only as what it is, never as starter-restricted, the same shape as decision (2)'s nonzero-relaxation question and decidable in the same pass.

### R122. The Showdown prior_note claims a platoon factor the build never applied, and handedness dies at two intakes (P1, S) | new 2026-08-14, merged from BUILD fragment `2026-08-14_BUILD_showdown-platoon-inert-and-no-per-player-cap.md` finding 1; verified in tree

- **ed6 rider (2026-08-22, VERIFIED-read at ac8ac05; `showdown_theses.py`
  edited since by R156, and it still reads no `Pool_Basis`):** the same
  claim-vs-applied gap has a second, larger face on the `all_healthy` pool
  (nothing posted yet). Every hitter then has `Batting_Order=None`, so
  `apply_base_prior` leaves the ENTIRE thesis prior inert, the order bands
  come back empty so ladders/locks/mults are mostly empty and the templates
  converge to near-identical points-max solves, and `describe_slate` names
  the highest-APPG arm — possibly a closer — as "the starter", while
  `portfolio_report.prior_note` still asserts the full factor chain. Only the
  melt frame's `Pool_Basis` carries the truth. Fix with this item: read
  `Pool_Basis` in `build_thesis_ladder` and either refuse on `all_healthy` or
  stamp the report and prior_note "order/platoon factors INERT: no posted
  lineups".

- **What:** `apply_base_prior` documents and `portfolio_report` emits
  "salary-regressed APPG x batting-order PA factor x platoon factor"
  (`showdown_theses.py:62,603`) while on 1915_1g_sd the platoon component
  contributed nothing to any of 18 hitters: `showdown_handedness` only
  accepts a hand the feed carries (`build_slate.py:1837-1838`, `if ... and
  pitcher.get("hand")`), and a probable sourced from DK's `Starting` column
  arrives `"hand": ""` — so `teams_with_hand` was 0 and every hitter took
  the flat 1.00. The condition WAS disclosed (`platoon_unresolved_teams`),
  in a nested construction block, while the headline note asserted the
  opposite — and the in-code comment at `apply_base_prior` (`:70`) records
  this exact bug from a previous round; that fix made it reportable, not
  visible. This is a truthful-labels violation, the class CLAUDE.md calls
  non-negotiable. Measured impact: recomputing with hands moved Ben Rice
  9.27→9.64 and Okamoto 6.64→6.24, and the rebuild moved Rice 10→12 of 19
  lineups.
- **Fix, in the fragment's preference order, adopted:** (1) `prior_note`
  states what was actually applied — an all-flat platoon says so. (2)
  resolve handedness before falling back flat: the MLB Stats API `people`
  endpoint returns `pitchHand` for an id in one allowlisted call (statsapi
  is already in R88's allowlist), and **R117 LANDED 2026-08-18** and fixed the
  paste side of the same hole — read its changelog entry before wiring (2): what
  was broken was not a continuation line but `_HAND`'s `$` anchor against
  mlb.com's second render, and `_match_hand` is the function to consume rather
  than re-derive. R117's loudness half also shipped the surface (3) should
  match rather than duplicate: `factors_inert` beside the gates, and one named
  pool warning per slate rather than one per side. (3) an all-flat platoon
  factor is LOUD at
  the `stale_platoon_policy` precedent's severity: `'block'` engine default,
  `'warn'` from build_slate.
- **Audit fields.** Moves: robustness (label truth). Evidence: V2 (fragment
  with measured rebuild + guard line verified this session). Acceptance: a
  fixture feed with `hand: ""` produces a prior_note that names the flat
  platoon and a loud warning; supplying hands restores the full note.
  Falsifier: none — recording and resolution only. FOSS: stdlib + statsapi
  (already allowlisted). Owner: none. Rollback: severity knob.

### R123. The Showdown ladder has no per-player exposure cap, relaxes the captain cap untargeted, and deals contests in ladder order (P1, S-M) | new 2026-08-14, merged from the same fragment, findings 2-4

- **(a) Per-player exposure cap + small-sample guard.** `solve_ladder`
  (`showdown_theses.py:484`) accepts no per-player cap; the only lever is
  `max_shared_players`, a blunt instrument. Live: Brett Bateman in 17 of 19
  lineups (89.5%) on an APPG resting on ~25 PA, .110 Triple-A ISO —
  cheapest-bat-at-leadoff is a structural magnet the controls cannot answer.
  Same request as the Classic fragment's Jackson Jobe at 100%: a per-player
  cap expressible through `--controls-override`, relaxing and counting like
  the existing two, PLUS a sample-size guard (APPG on fewer than N games/PA
  takes a default exposure ceiling unless explicitly overridden — the guard
  is a labeled prior, never a projection change).
- **(b) Captain relaxation names its beneficiary.** Lowering
  `max_cpt_exposure_pct` to trim the weakest arm (Bieber, 5.94 FIP) instead
  cut the best captain (Cole 5→3) and left Bieber at 5, because the
  relaxation is untargeted and unreported. Prefer relaxing toward the
  higher-prior captain, or at minimum report which captain absorbed it —
  the count is visible today, the beneficiary is not (R113's adjacent
  surface, one item over).
- **(c) Stakes-aware contest assignment, or surface the mapping.** Lineups
  deal into contests in ladder order; the $1 Solo Shot (100x the satellite
  fee) received ladder slot 19 in both v1 and v3. Order assignment by
  contest stakes/shape, or print thesis→contest in the brief before upload.
- **Rider 2026-08-17, from the GF fifth edition's F-009, verified in tree:**
  the captain-cap arithmetic has two silent behaviors nothing reports.
  `showdown.py:408` computes `cap = max(1, floor(pct * n_target)) if
  max_cpt_exposure_pct else None`, so an explicit `0.0` is falsy and aliases
  to UNCAPPED — `None` is the documented disable, so `0.0` deserves a refusal
  naming the infeasibility (every lineup needs a captain), never a silent
  no-cap. And at small n the floor lands on 0 and is silently raised to 1, an
  event the brief never states: diagnostics carry the requested pct (`:461`)
  but never the effective integer cap. Fold into (a)/(b)'s acceptance: the
  brief and diagnostics state the effective cap beside the pct, a raised-to-1
  event is named, and `0.0` is refused with the reason.
- **Audit fields.** Moves: portfolio quality, leverage. Evidence: V2
  (fragment; signature verified; captain counts from the delivered brief).
  Acceptance: synthetic ladder test pinning the cap + its counted
  relaxation; a caution naming the absorbing captain; mapping line in the
  brief. Falsifier for (a)'s guard: R118 replays showing extreme-exposure
  small-sample players matching field top-decile rates. FOSS: existing.
  Owner: none. Rollback: controls default off.

### R139. Showdown captain-leverage ladder: report first, tier targets on decision (P2, S report / M control, decision-gated on step 2) | new 2026-08-16, from the leverage ideation fragment; measurements verified in ledger 3.18

- **What:** captain choice is where a small Showdown portfolio is actually
  distinct or actually a copy: duplicated-entry share runs 27.5% median in
  151-500 fields and 55.9% above 500 (3.18), and the one tranche measured had
  winners captaining at 9.1 median own against our 15.4 (0/8 top-owned).
  Caveat carried from the fragment and the ledger both: the 64-contest read
  says winner captains are AT-SHARE overall (14.8 vs 13.0 field median;
  the top-owned captain won 26%), so 9.1-vs-15.4 is one 8-contest tranche,
  not a law — which is why the report comes first.
- **Fix, two steps:** (1) report — captain own-tier histogram and
  predicted-dup per entry in the Showdown brief. **PARTLY LANDED 2026-08-18
  with R136, and the remainder is bigger than this line assumed.** R136's panel
  does report a captain own-TIER histogram per contest, and it is a RANK
  because the percentage is not available: the v0.1 prior budgets 800% across
  hitters and 200% across pitchers for a 2-P-plus-8-hitter Classic roster,
  while a Showdown salary file lists every player TWICE (a CPT row and a UTIL
  row, different ids and different salaries), so one budget is spread over
  roughly double the rows and split across two rows per person, against a
  roster that seats six — 186 rows for 93 players on the 2026-08-14 NYY@TOR
  file. The tier is computed over those same doubled rows, so even the rank is
  distorted: one player's CPT row and UTIL row land in different tiers.
  **A Showdown-native ownership prior is therefore this item's real step 1**,
  and it is a prior change (one budget of 600% over six seats, captain and
  flex priced as one player) rather than a report change. Predicted-dup per
  entry did not land and is unaffected. (2) control, D3 in Tier 4 — tier targets per
  portfolio (at most N entries on the top-2 structural-own captains, a floor
  on captains outside the top-5), enforced beside `max_cpt_exposure_pct` with
  the same relax-then-count discipline, and only after the report has run for
  a few slates. Showdown stays review-grade throughout; certification is
  R41's, untouched here.
- **Audit fields.** Moves: leverage, portfolio quality (Showdown). Evidence:
  V2 (3.18 re-read this session; fragment). Acceptance: (1) the histogram
  appears in a Showdown brief off a fixture ladder; (2) a synthetic ladder
  test pinning the tier target and its counted relaxation. Falsifier for (2):
  more tranches showing winner captains at-share at every field size — the
  control half dies, the report stands. FOSS: existing. Owner: D3. Rollback:
  report is additive; control defaults off.

### R211. `pitchers_duel` gets one slot and the ladder never rotates a captain, so Ben's stated rule is unreachable at any entry count (P1, S-M) | new 2026-08-23, merged from BUILD fragment `2026-08-22_BUILD_pitchers-duel-needs-both-captain-variants.md`; Ben's rule stated 2026-08-22, both gaps traced to the line

- **Ben's rule (2026-08-22), quoted:** "When we think of a 'pitchers duel' game
  thesis for showdown we need to include both pitchers, and if we have enough
  lineup slots in our portfolio we should have at least 2: one where each P is
  captain and the other is UTIL. We can have more if it makes sense, but two
  lineups (one with each as captain and the other as util) should be the
  minimum."
- **What already works:** R156's `duel()` hard-locks both starters into every
  `pitchers_duel` lineup regardless of who captains, unfiltered by `cpt` and
  surviving every rung of `solve_ladder`'s relaxation ladder. Both-pitchers-
  rostered is solid. **What is missing is the second lineup with the captain
  flipped**, and it is two independent gaps, both in `build_thesis_ladder`
  (`showdown_theses.py` ~415). **(1) No allocation floor.** `pitchers_duel` is
  one row among 13 templates, weighted 0.45 inside the 18% `NEUTRAL_SHARE`
  slice and apportioned by `_largest_remainder` like everything else; on the
  08-22 1335_1g_sd build it landed on exactly **1 slot out of 19 entries**.
  R156's own comment already flags this. Nothing forces a second slot when both
  starters are live, at any portfolio size. **(2) Repeated occurrences of one
  thesis do not rotate captains.** The selection loop (~462) skips a candidate
  only once he is at the GLOBAL exposure cap (4 of 19 that night), with no
  memory of "already captained for THIS thesis id" — so a second
  `pitchers_duel` occurrence would walk the same 2-element `cpt_ladder =
  list(both_sp)`, find the first starter still under cap (true after one use),
  and pick him AGAIN. Two occurrences of one template differ today only because
  `solve_ladder`'s overlap bound forces different filler hitters, and the
  `(variant 2, … captain)` label at ~481 names whatever the loop picked rather
  than a guaranteed-different one. **Proven on the same delivery:** entries 1
  and 14, "TOR win big - starter carries it" and "… (variant 2, Dylan Cease
  captain)", both captained Dylan Cease — the variant was entirely in the four
  supporting hitters.
- **Why:** with one slot, the captain was whichever starter sorts first in
  `shape["teams"]` (Weathers, NYY < TOR) — **a team-name-ordering artifact, not
  a scored choice.** Getting the Cease-captain / Weathers-UTIL lineup into the
  portfolio took a manual post-hoc `build_showdown_lineup` with
  `cpt_lock=Cease, locks=[Weathers]`, hand-patched into an entry, because
  nothing in the ladder produces it on its own even at higher `n_entries`.
- **Fix, matching the two gaps.** **Allocation floor:** after `counts =
  _largest_remainder(weights, n_entries)`, if the `pitchers_duel` spec is live
  (`duel()` returned non-None, i.e. both starters declared) and the portfolio
  can afford it without zeroing a template that would otherwise get a slot,
  raise that index to at least 2, borrowing from wherever the remainder ranked
  lowest. **"Can afford it" needs a real threshold and that threshold is DEV's
  call** — Ben's own phrasing ("if we have enough lineup slots") makes it
  conditional, and a 1-entry Solo Shot obviously keeps today's single slot.
  **Per-thesis captain rotation:** give the selection loop a second piece of
  state beside the global `cpt_counts` — which captains have already been used
  for THIS thesis id — and on a second or later occurrence of the same template
  skip a candidate already captained for it, in addition to the cap check,
  before falling back to allowing a repeat. That second half fixes the
  false-`variant` label on every directional template, not just this one.

### R210. Three Showdown tool gaps: the probe errors out, QA section 1 reads Classic-shaped fields, and `--postures` IS a silent no-op (P2, S) | new 2026-08-23, merged from BUILD fragment `2026-08-21_BUILD_showdown-tool-gaps.md`; (c) upgraded from "may be" to VERIFIED 2026-08-29, second sighting

- **What:** **(a)** `tools/solver_probe.py` errors on a Showdown salary CSV —
  `_assemble_projection_frame` raises `ValueError: projection_rows is empty` on
  a melted CPT/UTIL file, so the probe assumes Classic's pool shape. CLAUDE.md's
  session-start step 3 calls for the probe "before any build" with no
  Classic-only carve-out, so a Showdown session either skips a mandated check or
  believes the tool is broken. **(b)** `qa_portfolio.py` section 1 printed
  `controls relaxed: none` and `gates: {}` for a Showdown brief that actually
  carried `counted_relaxations.captain_relaxed_slots: 1` and
  `counted_relaxations.clean: false` — one captain-lock substitution (Sale →
  Misiorowski) that the adversarial tool reported as clean. It reads a
  Classic-shaped relaxation/gates field and does not know Showdown's
  `counted_relaxations` / `captain_exposure` / `player_exposure` blocks.
  **(c)** section 4 reported all 7 contest ids as "archetype UNRESOLVED … the
  brief carries no contest_shape for this id" even though `--postures` was
  passed for all 7, because Showdown's thesis-ladder construction does not
  appear to branch by contest at all: one 19-lineup ladder was built across the
  whole entries file regardless of which contest each blank row belonged to.
- **Why:** (b) is the sharpest — R153's whole discipline is that a portfolio is
  clean when the relaxation counts are ZERO, and the tool that exists to check
  that printed `none` against a real relaxation. (c) is a question before it is
  a defect: whether Showdown is MEANT to read postures. If it is not, the flag
  should warn rather than silently accept, since the operator passed it
  believing it did something.
- **Fix:** (a) teach the probe the Showdown melt, or state Classic-only in
  CLAUDE.md and the skill and have the probe say so on a Showdown file rather
  than raising. (b) read Showdown's own brief blocks in section 1. (c) answer
  the design question first, then either branch or warn. Rides R41 and R202.
- **(c) upgraded to VERIFIED, second sighting 2026-08-29** (from BUILD fragment
  `2026-08-28_BUILD_showdown_postures_and_qa_shape.md` §1, slate
  `2215_1g_sd`): it is not "does not appear to branch," it is that nothing
  reads the flag at all. `grep -n 'postures|contest_shape|contest_postures'
  mlb_engine/optimize/showdown.py` returns NOTHING, re-run at this head and
  empty again. `build_slate.py` accepts the flag, the Showdown branch never
  reads it, and no warning says so. **The cost is now concrete:** the Quick
  Card's item 4 tells every session to pass explicit postures and never trust
  name inference on family names, and this slate carried "Pocket Cup" — the
  exact named trap. The operator passed all seven ids believing the Card;
  nothing read them. Silent acceptance is the worst of the three available
  behaviors, so the refuse-or-warn half of the fix is worth landing even if
  the design answer (should Showdown read postures at all — R238's question)
  is still open. **(b) gains one line from the same fragment:** section 1 also
  printed `F1 NEUTRAL: no implied totals reached the projections` on this
  build, which is R237's Showdown face; what section 1 should report for a
  Showdown brief is the win-share basis it actually used
  (`win_share_basis: moneyline_no_vig`).

### R208. Showdown never merges a confirmed batting order from `--lineups`: R143 has no Showdown equivalent, and the fallback bank has its own ceiling (P1, S-M) | new 2026-08-23, merged from BUILD fragment `2026-08-22_BUILD_showdown-batting-order-not-merged-from-feed.md`; both halves observed on 1335_1g_sd

- **What:** `Pool_Basis` and `Batting_Order` in `melt_showdown_salary_csv`
  (`showdown.py` ~160-209) are derived ONLY from the DK salary file's own
  `Starting` column — there is no Showdown equivalent of R143's
  `merge_dk_starting_into_feed`. On 2026-08-22 `1335_1g_sd` (TOR @ NYY) DK had
  flagged both probables (`Dylan Cease` → `P`, `Ryan Weathers` → `SP`) and left
  `Starting` BLANK for all 18 hitters, while mlb.com carried a full confirmed
  1-9 for both sides that Ben pasted and `lineups_from_paste.py` resolved
  cleanly against this draftgroup's ids. Effect: `declared` held only the two
  pitcher rows, so `basis` still read `declared_starters` **misleadingly** while
  `Batting_Order.notna().sum()` was 0, and `run_showdown`'s `use_ladder =
  (basis == "declared_starters" and posted >= 18)` evaluated False with a
  perfectly good `--lineups` feed sitting right there. `showdown_handedness`
  reads that feed for `bat_side` and pitcher hand only; it never touches
  `Batting_Order` or `Pool_Basis`.
- **Why:** it is DK-FILE-DEPENDENT and a build cannot assume either shape —
  contrast 2026-08-19 ARI@BOS, where DK's own file DID carry 1-9 for both
  sides. So the same slate type silently takes the good path or the fallback
  depending on how DK filled one column, and `basis: declared_starters` reads
  identically in both cases. Second half, filed as an observation because it
  needs `build_showdown_bank` context: losing the ladder routed to
  `sd.build_showdown_bank`, which returned `{"status": "bank_short", "built":
  11, "needed": 19}` IDENTICALLY across two attempts at 14s and 18s
  `--max-seconds` — the built count did not move, which smells structural
  rather than search-bounded, and means "grow the bank" (the standing autonomy
  default) did nothing. Worth checking whether it has its own version of the
  ceiling R204 describes for the joint MILP.
- **Fix:** give the Showdown melt the same source ranking the Classic front door
  has — DK's `Starting` first, the `--lineups` feed second — so a resolved paste
  or feed can supply `Batting_Order` and lift `Pool_Basis` when DK's column is
  blank. The shipping workaround was a derived salary file with `Starting`
  written onto both CPT and UTIL rows from the resolved feed, which is exactly
  the merge, done by hand, outside the engine. And make `basis:
  declared_starters` unable to coexist with `posted_hitters: 0`: that pair is
  the misleading half and it is a one-line assertion.

### R273. The Classic joint allocator files a clock expiry as a constraint failure (P1, S) | new 2026-08-30, found by R158's R233 enumeration at `00f0995`; VERIFIED-read | **POSITIONED 2026-08-30 into slot 1**, with R275, when the false-evidence batch closed: same class, Classic certified path, and R158's Showdown fix is the template to follow rather than re-derive

- **What:** `contest_allocator.py:1276-1290`. The joint MILP reads
  `if not result.success or result.x is None:` and, on any non-success, falls
  back to `_assign_lineups_greedy_fallback` while setting
  `direct_constraint_failure: True` and `selection_certified: False`. A status-1
  time limit holding a feasible incumbent is therefore discarded AND recorded as
  a CONSTRAINT failure. That is R158's inversion with a worse label: the fallback
  is correct behaviour for an infeasible model and wrong for a slow one, and the
  operator reading `direct_constraint_failure` is told the controls are
  impossible when the clock simply ran out.
- **Why it was left on 2026-08-30:** R158 fixed the Showdown twin the same day
  and named this site rather than touching it. It sits on the CLASSIC certified
  path behind the golden replay, and changing what `selection_certified` reports
  is not a change that belongs in a Showdown stage with no Classic coverage
  written for it.
- **Fix:** the pattern is already in this same file at `:2745`, which verifies
  its incumbent and emits a `solver_report` — port that, not `optimizer_v3`'s,
  since it is the nearer neighbour. Then the fallback fires on a proven
  infeasibility and a verified time-limited incumbent is accepted and tagged,
  with the timeout counted separately from `direct_constraint_failure`.
  Note `:2745` carries its own inline `{0: "optimal", 1: "time_limit", ...}`
  dict, a second copy of `optimizer_v3.SCIPY_MILP_STATUS`; unify to the import
  while here, which makes the vocabulary one definition across all four `milp`
  call sites.
- **Cost of leaving it:** a Classic build whose joint MILP times out ships
  through the greedy fallback uncertified, with a diagnostic naming the wrong
  cause. Nobody currently reads it as a timeout, so the misdiagnosis is silent.

### R224. Two Showdown cap-resolver smalls, both on surfaces R157 sends operators to read (P2, XS) | new 2026-08-24, from the greenfield seventh edition (GF7-E4, GF7-E5); VERIFIED-read, re-read here

**What.** (a) `showdown.py:423-437`. `player_cap_structural_floor(pool_size,
n_entries, contract)` accepts `n_entries` and never uses it; it returns the
un-quantized `roster_size / pool_size`. Because the caps quantize with `floor()`,
that bound can be insufficient at small n: pool 20, n 19 reports 0.30, and
`floor(0.30 * 19) = 5` covers 100 seats against 114 needed. (b)
`showdown.py:419`. `exposure_cap_count` computes
`max(1, math.floor(assert_fraction_cap(pct) * max(1, int(n))))` with no `+ 1e-9`,
while all three sibling resolvers carry it (`contest_allocator.py:911`, `:1065`,
`:2544`; `execution_pipeline.py:2574`) — and this one sits outside the
copy-agreement test.

**Why.** CLAUDE.md's R157 delegation tells the operator to "re-derive it from that
slate's structural floors (`player_exposure_floor` etc. in the feasibility
report), never hardcode a number forward". (a) is that number, and it can be
wrong low on exactly the thin-pool Showdown slates the rescue exists for. (b) is
binary-float drift on a cap, biting in the stricter direction, on the one resolver
no test compares to the others.

**Fix.** (a) Return the quantized floor, or relabel it `necessary_lower_bound` and
say in the report that it is necessary and not sufficient. (b) Add the epsilon, or
share the helper and bring it under
`test_cap_count_arithmetic_is_floor_and_both_copies_agree`.

### R238. Showdown resolves no contest shape: every archetype reads UNRESOLVED, the ownership companion has nothing to condition on, and the Showdown half of the archive accumulates with no archetype key (P1, S-M) | new 2026-08-27, merged from BUILD fragments `2026-08-27_BUILD_showdown_f1_and_archetype_gaps.md` §2 and `2026-08-27_BUILD_showdown_entry_to_contest_assignment_is_positional.md`; corroborated by the outside spec ed8 (F-39)

**What.** `run_showdown` never calls `_resolve_contest_postures`, so the brief
carries no `contest_shape`, `qa_portfolio` section 4 prints `archetype
UNRESOLVED` for every contest id (9 of 9 on 1905_1g_sd, 8 of 8 on texcws_sd),
and R10's conditioning key is absent from every Showdown build the archive
accumulates. Two of the nine names on 1905_1g_sd are also absent from
`dk_contest_archetypes.csv`, so name inference would not have covered them.

**Why.** A top-heavy single-entry contest and a one-ticket satellite want
different things from the same bank, and today the build cannot tell them
apart. This is the INPUT for R239's shape-aware half and for any per-contest
review surface; it is also why the washout axis binds invisibly one level below
the portfolio. The intake fact to state rather than discover:
`dk_contest_paid_places.json` covers 0 of 108 (3.19), so field size and paid
places per contest ride the archetypes CSV and the DKEntries file, not a feed.

**Fix.** Call the Classic posture resolver on the Showdown path with the same
CLI override (`--postures <id>=<shape>`), write `contest_shape` per contest
into the brief, and give qa section 4 its key. Unmatched names keep Classic's
behavior (block with the named row, per the Quick Card rule). No solver change.

### R239(a), remainder. Entry-to-contest assignment is still POSITIONAL: theses are not dealt to contests (P1, S-M; depends on nothing further, but see the warning below) | new 2026-08-27, FOUR sightings; (b) and (c) SHIPPED 2026-08-29, see CHANGELOG.md; **this entry rewritten that date to its remainder**

**What SHIPPED on 2026-08-29, so the next reader does not rebuild it.**
- **(c)**, the per-contest slice: `per_contest` in the brief on both build paths,
  `counted_relaxations.clean` answering to it, `qa_portfolio` refusing a clean
  verdict without it.
- **(b)**, the cap that binds where the slot is spent: `max_cpt_per_contest`, a
  named control defaulting to 2, enforced in BOTH `build_thesis_ladder`'s
  apportionment and `solve_ladder`'s exclusion list, on every rung including the
  floor. Plus the Gale-Ryser precondition (b)(ii), which R239 did not have.
- The seam that both needed: the entry-to-contest partition threaded from
  `run_showdown` into both ladder functions.

**Three corrections to this entry's own text, made while building it.**
1. **The R233 enumeration was wrong.** This entry said of the six
   `exposure_cap_count` call sites: "No copy is deliberately kept; all six take
   the same correction in (b)." All six are deliberately KEPT. They compute the
   PORTFOLIO captain and player caps, which R153 established and which are
   correct against the entered total. The defect was never a wrong denominator
   in those six; it was that no per-contest cap existed. The fix is a fourth
   control beside them.
2. **`max_cpt_per_contest` is a named control, not `max(1, floor(pct * n))`.**
   Deriving it gives 1 for every contest up to seven entries, which is full
   distinctness arriving as an accident of arithmetic. R247 measured what
   tightening a cap costs. Ben set it at 2; whether it becomes 1 is his Tier 4
   call and is a one-value change.
3. **A FLAT cap of 2 does not kill the 100% case it was chosen to kill.** In a
   2-entry contest `min(2, 2) = 2` permits both entries on one captain. The bar
   is `max(1, min(m, n - 1))`.

**What REMAINS: (a), the round-robin deal.** `run_showdown` still assigns with
`zip(rows, bank)`, so which CONSTRUCTION lands in which contest is still an
artifact of two orderings that know nothing about each other. The per-contest
captain cap now stops the worst consequence (one contest's entries sharing the
highest-leverage slot), but it does not make the deal deliberate: team shape,
game script and thesis family are still distributed by position. Deal theses to
contests round-robin across game states so every multi-entry contest carries
entries live under either script; until shapes resolve, order reserved rows so
the largest buy-in draws from the most differentiated end of the bank.

**The warning that survives, restated.** (a) was once noted as able to "land
first and alone". That is still wrong, and (b) landing does not make it right:
dealing cannot create diversity the bank does not contain. The Gale-Ryser
precondition now shipped is the test for exactly that, and the 08-28 bank failed
it at k=3 (14 > 13) with fully distinct captains required. (a) must read the
feasibility verdict rather than assume a deal is available. Its shape
conditioning still consumes R238.

**Measured evidence for (a), still open.** texcws_sd's two 7-entry satellites
each inherited one side (CWS 5/2 and TEX 5/2); hounyy_sd's $1 Solo Shot drew bank
#21 while the $0.10 Dime Time pair drew #1 and #2; and the 08-26 proof, where two
different control sets produced an IDENTICAL 20-entry Dime Time slice with all
diversification landing on entries 21-39. None of those is a captain finding, so
none is closed by (b).

### R240. No punt-captain template: below $5,800 the ladder never captains anyone, so a whole class of broad-field finish is unreachable at any cap value (P2, S-M; decision-first, Ben's) | new 2026-08-27, from `2026-08-26_BUILD_contest_aware_allocation_at_onset.md` §4(d)

**What.** At `max_cpt_exposure_pct` 0.08 — forcing 16 distinct captains across
39 entries — the ladder still never captained Wells ($3,400), Trammell
($3,800), Vazquez ($4,200) or Jones ($5,400). No thesis template constructs a
roster around a bottom-order captain, so no cap value can produce one.

**Why.** In a broad-field Showdown the punt captain is a standard construction
the field runs and this portfolio cannot reach; cap tightening is not the
lever. Adding a template class changes what gets built, which is strategy:
Ben decides whether the ladder carries it and at what weight, same as R156's
pitchers-duel rework.

**Fix.** One `punt_captain` thesis family (CPT below a salary bar, both game
scripts), weight decision-gated; measured against the archive's captain-salary
distribution before any weight above minimal.

### R247. Cap cost is invisible: tightening a cap moved twelve slots from the four best players to the four worst, degraded one lineup to $6,100 salary-left, and every counter read clean (P1, S for (a)–(c); (d) is Ben's) | new 2026-08-27, merged from BUILD fragments `2026-08-27_BUILD_player-exposure-cap-is-skill-blind.md` and `2026-08-27_BUILD_showdown_tightened_cap_degrades_bank_tail_uncounted.md`; corroborated by the outside spec ed8 (F-35, F-37)

**What.** Two measured faces of one fact. On 2145_1g_sd, tightening
`max_player_exposure_pct` 0.50→0.40 moved 12 roster slots off the four
BUY-graded players onto the four FADE-graded ones (roster leverage 55.9→25.4
against a labeled prior). On 1905_1g_sd the same tightening landed its whole
cost on the last lineup off the ladder: $6,100 salary left (archive medians
$200-$300), proxy 38.19 against a portfolio median of 54.87, label naming a
captain the cap had reassigned away — and `counted_relaxations.clean` was
true throughout, correctly, because nothing relaxed.

**Why.** R153's own lesson one level up: a portfolio is not clean because the
counters read zero. The cap binds at the top of the exposure distribution,
which is where a working build concentrates, so its first-order effect is to
demote the players the projection liked most; whether that is protection or
damage depends on whether the concentration was right, and nothing currently
shows the operator the trade.

**Fix.** (a) Brief flags any lineup whose proxy falls a stated margin below
the portfolio median or whose salary-left exceeds a bar (archive medians are
the reference); (b) `cap_reassignments` records the proxy DELTA (thesis before
and after substitution), not just that the label moved; (c) a correlated-block
line: worst k-subset sharing count and "entries carrying at most one of the
top trio" — the fragment's measured example (worst triple 7 of 23, 11 of 23
with at most one) is the actual washout answer no counter reports. (d) The
skill-aware-cap DIRECTION (scale the cap by the build's own Base rank, or cap
correlated blocks instead of persons) is a strategy change and Ben's decision;
it goes to Tier 4 with (a)–(c)'s numbers as its evidence.

**First CLASSIC sighting, 2026-08-30** (from BUILD fragment
`2026-08-30_BUILD_standing-data-driven-qa.md` §C, slate `1605_2g`, 7 entries on
2 games). Both filed sightings were Showdown, which left open whether this is a
Showdown-ladder artifact. It is not. A certified Classic build carried a lineup
with **$10,300 salary left**, against the $6,100 the 1905_1g_sd sighting
reported, with the same signature exactly: `counted_relaxations` zero,
`relaxations: 0`, all three gates green, every counter clean because nothing
relaxed. This strengthens R247(a): the flag belongs on the delivered brief for
both formats, and the salary-left bar is the cheaper of the two triggers.

**And one consequence that changes what R247(c) has to measure: the degraded
entry INFLATED the washout proxy.** Comparing two builds of that slate, the
weaker one showed "2 of 7 entries untouched" against the stronger one's 1 of 7,
and its second untouched entry WAS the $10,300 lineup. It survived a zeroed
BAL@ATH because it was cheap and weak, not because it was a designed hedge. A
washout count that cannot tell a hedge from a dead entry will keep scoring the
defect as protection, so R247(c)'s correlated-block line needs a second axis:
survival attributed to design (low overlap with the failed block) versus
survival attributed to a lineup that had nothing at stake anywhere.

### R249. Showdown has no projection input, so the operator's only lever is rewriting the salary file, invisibly (P1, S) | new 2026-08-27, merged from BUILD fragment `2026-08-27_BUILD_showdown-has-no-projection-input.md`; corroborated by the outside spec ed8 (F-40)

**What.** `run_showdown` builds from `melt_showdown_salary_csv` and `Base` is
`AvgPointsPerGame`, no override anywhere on the path; the module docstring
anticipates "a richer projection" that cannot be supplied. On 2145_1g_sd the
operator's workaround was a modified salary CSV whose only changed column was
APPG — it worked (captains on BUY-graded players 6→11) and NOTHING in the
file, brief, or preflight records that Base was substituted, which is the
pool-trimming class of invisibility CLAUDE.md names.

**Why.** APPG cannot know the opposing arm (a measured ~12% team-wide swing on
this slate) or the platoon; and an invisible input substitution on a delivered
file is worse than the gap it works around.

**Fix.** `--projections <csv>` (`Player_ID,Base`, the columns
`ownership_pred.py --base` already reads); brief records source path, sha256,
count of players whose Base differs from APPG, min/median/max ratio. The
long-term answer (Showdown through the Classic enrichment stack) is R41's and
unchanged; this is the cheap intermediate that also serves operator priors
after R41 lands.

**Second sighting, 2026-08-30, and the first MEASUREMENT of what the gap costs**
(from BUILD fragment `2026-08-30_BUILD_showdown-ranks-on-raw-appg.md`, slate
`1920_1g_sd`, CIN@CHC, 10 entries). The build certified review-grade with
`counted_relaxations.clean: true` and zero adversarial findings, so nothing that
ran could have caught this. Savant expected stats for the 18 confirmed bats
against delivered exposure: **three confirmed starters drew ZERO of 10 entries
and all three carry POSITIVE xwOBA-minus-wOBA gaps**, results trailing contact
quality, which is the exact correction the xwOBA Base step exists to make.
Bleday (CIN, .350 xwOBA, +.017), Hoerner (CHC, .324, +.025), McLain (CIN, .311,
+.028). Bleday ties the second-best CIN bat by xwOBA; Hoerner outranks three
CHC bats that each drew 3 or 4 entries. The mirror holds: the two bats pinned at
the 50% player cap carry the largest NEGATIVE gaps on the board (Crow-Armstrong
-.037, Suzuki -.035).

**State the mechanism so the fix can be aimed, because it is not a batting-order
artifact.** Amaya bats 9th with the worst xwOBA of the 18 and still drew 3 of 10
because he is cheap. The starved band is the 6-7 hole at mid salary: too
expensive to be a punt, short of the top bats on APPG alone. APPG plus salary is
the entire ranking, so a bat whose season results lag its contact quality has
nothing that can lift it. Verified at this head: `showdown.py:223` reads
`AvgPointsPerGame` for Base, and `grep -icE 'enrich|est_woba|xwoba|expected_stats'`
over that module returns **0** against 23 `def` in the same file, so the absence
is real and not a silent-grep failure. `build_slate.py:3441-3442` routes
`contest == "showdown"` into `run_showdown` before the enrichment block at
`:733`, and `run_showdown` touches none of it. Both Savant reference files were
FRESH on the day (fetched 19:52Z; **636 and 831 data rows**, not the 637/832 the
fragment reports, which are `wc -l` counts carrying the header). The inputs were
on disk and current; nothing consumed them. `showdown.py:238` (`if base and not
rec.get("Base"): rec["Base"] = base`, quoted exactly at this head) suggests a
pre-seeded Base already survives the pool build, so
the `--projections` seam may be narrower than R249's Fix assumes; check that
before scoping. The truthful-label half of that fragment is filed on R237, not
here. **R233 note for whoever takes this:** enumerate every `contest ==
"showdown"` branch and every consumer of `reference_manifest.json` before
claiming the class is closed. The fragment named two sites and did not count
them.

### R274. The test suite appends to two REAL-dated slate manifests on every run (P1, S) | new 2026-08-30, found by R250's slate-isolation check at `442ed6e`; VERIFIED-read

- **What:** `outputs/2026-06-03/upload_manifest.json` and
  `outputs/2026-06-11/upload_manifest.json` are written by the test suite on
  every run. They now carry **393** and **1025** deliveries respectively. Today's
  run appended 16 and 27; rows are also dated 08-27, 08-28 and 08-29, so this is
  long-standing rather than new. Both directories also hold test-built
  `DKEntries_*.csv` files. `outputs/2026-06-11` is unambiguously fixture output
  (contest id `900`, contest name `Test WTA`); `outputs/2026-06-03` carries
  real-looking contest names and ids but its `run_id` values are July timestamps,
  so it is fixture output living in a real-looking date directory.
- **Why it matters:** the archival miner reads `outputs/<date>/upload_manifest.json`.
  Nothing has ingested these yet, but the tree it globs contains roughly 1400
  fixture deliveries presented in exactly the shape a real delivery takes. This
  is the same class as the 2026-08-29 incident where an end-to-end run dropped a
  fixture file into `outputs/2026-08-29/` and appended a row to that date's
  manifest -- with the difference that these two dates are old enough that nobody
  has noticed.
- **Why it was not fixed on 2026-08-30:** `outputs/` is gitignored, so none of it
  reaches the repo and no commit is carrying it. Deciding which rows are fixture
  and which (if any) are history is ARCHIVE's call, not DEV's, and this mount
  cannot unlink so a cleanup is a `mv` that wants its own session.
- **Fix:** point the fixtures at a temp directory or at the `_test_r3_*` sandbox
  convention the rest of the suite already uses -- twenty other manifests under
  `outputs/_test_r3_*/` show the pattern exists and these two escaped it. Then
  have ARCHIVE arbitrate the two accumulated files. A test that writes into the
  tree the miner reads is the defect; the accumulated rows are its symptom.


## Workstream 2 — Strategy controls and the evidence that moves them

Measurement-gated by design: nothing here moves a control without a graded
tranche behind it. R37(2) waits on ARCHIVE and slates, not a DEV slot; R10
is the funded modeling item; R48 is its grading substrate (an archival
emission, kept here because its purpose is this stream); R13 is the umbrella
decision the do-not-build list keys on. R126, R135, R136 and R137 joined
2026-08-16 as the review-and-evidence layer: none of them moves a control,
and each makes the next control decision gradeable instead of argued. **R126
CLOSED 2026-08-17** and migrated; R150 was filed off its landing and is Ben's
decision, not a control move either.

### R37(2)(c). The five-stack half, remainder: the 4-2-x secondary cap (P1, M) | stages 1, (a) and (b) all landed; (c) is the whole of what is left

**(a) and (b) SHIPPED 2026-08-28 and their text MIGRATED to CHANGELOG.md.** Ben's
dated go-live instruction took both live in one session, against ledger 3.21 as
the measured tranche (a) had gated on since 08-09. Do not re-litigate either half
from this entry; the reasoning, the measured numbers, and the R233 enumerations
are in the changelog entry, and only (c) is open. In brief, so this entry is
readable without leaving it: (a) is `primary_stack_min_size = 5` routed on
`payout_breadth <= 0.02` per contest with 1-2g slates exempt; (b) is
`min_five_stack_share_pct` derived as 0.75x the measured five-stack field share
clamped to 15-25%, on breadth 0.10-0.22, and the R34-vs-R37 reconciliation the
item demanded landed with it -- the quota now relaxes and counts on a ladder
instead of hard-failing the delivery.

**Stage 1 is DONE and is in the CHANGELOG, not here.** Ben decided this on
2026-08-09, accepting DEV's 2026-08-05 floor-first recommendation as written and
amended by the 08-08 third-tranche input. The evidence behind all of it lives in
`ledger/2026-07-30_field_shape_analysis.md`,
`ledger/2026-08-04_field_shape_ownership_analysis.md` (3.17),
`ledger/2026-08-08_tranche31_analysis.md` (3.18),
`outputs/2026-08-01/mined_data_review_2026-08-01.md`, and now ledger 3.21.

**Review checkpoint and revert conditions on the two live bands (Ben,
2026-08-28).** Both bands grade as FINISH COHORTS over **~12 conditioned
slates** before either tightens further; conditioned means family x field-size
bucket x slate size, per the ledger's own rule, never pooled. That grading is
ARCHIVE's, off the standings archive, and it is the gate on any change to either
number -- including a change proposed by a session that only saw one slate.
Each band reverts on its own condition, stated now so the revert is a
measurement and not an argument later:

- **(a), floor 5, reverts to 4** if narrow-breadth deliveries over the review
  window show the primary-stack floor relaxing (`primary_stack_floor.relaxations`
  nonzero) on more than a third of builds, or if the top-cohort 5-2-1 lift on
  3g+ slates loses its sign in the next tranche. A relaxation-heavy floor is a
  floor the bank cannot carry, and 3.21's own label is STABLE DIRECTIONAL rather
  than replicated, so one sign flip is enough to reopen it.
- **(b), the quota, reverts to 0.0** if `five_stack_quota.relaxations` is nonzero
  on more than a third of mid-breadth builds, or if `reuse_dependent` fires
  routinely -- either says the bank cannot supply five-stacks at the requested
  share and the honest fix is the bank build, not the quota. It also reverts if
  the measured field share falls far enough that 0.75x it sits at the band floor
  on most slates, because a quota pinned to its own clamp has stopped reading
  the share and is the constant the build requirement forbids.

**Open remainder that (b) created, and it is ARCHIVE's, not DEV's.** The quota
prefers a rollup at `data/reference/stack_shape_field_shares.json`, schema
`{"computed_at": <iso>, "five_stack_share_by_slate_bucket": {"1-2g": f,
"3-4g": f, "5-6g": f, "7g+": f}}`, and falls back to 3.21's dated values with
`source: ledger_measured` when it is absent -- which is the state today, so every
build is currently reading a 2026-08-28 measurement and SAYING so. Nothing
aggregates `stack_pattern` from `data/archive/*/mined_*.json` into that file yet:
`field_miner.mine_contest` writes the per-entry string and its `construction`
block carries only `max_stack_histogram`, the scalar primary size, not the
partition. The only code that has ever computed the share was a throwaway in
`tools/_scratch_archive0822/`. Done when a producer emits the rollup, it is
registered in `refresh_reference_data.py`'s `TRACKED_JSON` (registering it in
`reference_manifest.json` alone is not enough -- `reference_status()` iterates
`REQUIRED_COLUMNS`, which is exactly the hole that let
`fangraphs_platoon_lineups.json` age unmeasured), and a build reports
`source: archive_rollup`.

- **(c) Cap 4-2-x rather than banning it, sized after (a).** It is -2.2pp
  [-3.6,-0.8] and PROVISIONAL, it was 35.5% of our mix, and the floor of 4 does
  not touch it (4-2-2 and 4-2-1-1 both satisfy floor-4). It needs a
  SECONDARY-size cap, which is a control that does not exist yet. Ben deferred
  the sizing explicitly so the floor''s effect can be measured on its own first.
  The 2026-08-05 probe suggests a secondary cap earns its keep on thin slates or
  nowhere: 5-3 appears only on the 3-4 game files (2 of 6, then 1 of 8) and
  never on 6 or 8 games.

- **Constraints that travel with every part of this item.** No contrarian push:
  winners run chalk-POSITIVE cumulative ownership everywhere except
  supersatellites, and the differentiation that pays is one or two sub-10%
  pieces, not a contrarian portfolio (3.17, strengthened). Leave the salary-left
  gap alone; it is recorded, not acted on. Do not target 5-3. And the feasibility
  question that used to gate this item is ANSWERED and closed: the `<=3-primary`
  share was solver CHOICE, not a constraint artifact, at every width probed
  (`tools/stack_shape_probe.py`, 2026-08-05), and the 08-08 tranche agreed by
  putting its own `<=3-primary` entries on 4-7 game slates.

- **What is NOT claimed, carried forward unchanged:** not that we underperform
  (we finish indistinguishable from field median in every archetype); not that
  the +3.73pp mix arithmetic survives us building the shape at volume — that
  arithmetic no longer holds at face value; and not that the salary-left gap is
  independent, since a 5-2-1 costs differently than a 4-2-1-1.

- **Note 2026-08-13 (Ben, standing directive):** "the only way this makes
  money over the long term is big wins" — apex construction over cash-rate
  optimization for GPP-shaped contests. This item is already the concrete
  mechanism: (a)'s narrow-breadth set (WTA, one-seat satellites, solo shots,
  mme_gpp/mini-MAX, single_entry_gpp) is exactly where the payout sits at rank
  1, and floor-5 is what builds toward it. The directive elevates this item
  inside Tier 2; it does not change the gate. It also sharpens the reading of
  the constraint two paragraphs up: "no contrarian push" is not a hedge
  against this item, it is the shape of the apex outcome itself — chalk-positive
  core, one or two sub-10% differentiators, bigger primary stacks. Pushing
  broad ownership-fading instead of stack size would be optimizing the wrong
  knob for what Ben is actually asking for.

- **Note 2026-08-16 (leverage ideation fragment), a rider on (b), gated on
  R48:** once R48's per-contest tables persist, (b) generalizes — a rolling
  field share for 5-stack / 4-2-x / SP-pair concentration lets the stack plan
  tilt the portfolio's shape mix away from shapes at their archive-high field
  share, bounded and counted, feasibility floors untouched. Same players,
  different architecture: construction contrarianism, the only kind the
  archive supports outside supersatellites. Reads the share, never assumes
  the lift, exactly as (b) already mandates; sized and built only after (a)'s
  tranche measurement, like everything else in this item.

### R40. One-seat satellite profile routing: archaeology DONE, the routing decision is Ben's (S, decision) | new 2026-08-01; answered 2026-08-09

**The archaeology is finished and is in the CHANGELOG.** Both rank-1 satellite
builds were traced through `runs/` and their diagnostics. 192892126 ($15 Relay
Throw, A-034, 1 of 53) resolved to the `satellite` shape and was scored by the
floor blend (floor 0.42, stack 0.35, uniqueness 0.10, field pressure 0.25).
192973047 ($5 FFM, A-032, 1 of 23) resolved to `large_wta` (floor 0.00, ceiling
1.00, stack 1.10, uniqueness 1.00, field pressure 1.15). **Neither was
`wta_ticket_satellite`.** The brief now records resolved posture, shape and
profile weights per contest, so this is a lookup rather than archaeology from
here on.

**What is left is one decision, and it is Ben''s, because it reranks lineups on
contests entered tonight.** Should `paid_places == 1` route to
`wta_ticket_satellite`? DEV''s recommendation as of 2026-08-09 is NO, not yet,
on three grounds set out in full in the CHANGELOG entry: the floor blend
produced one of the two rank-1 finishes, so the item''s premise that it pulls
toward construction that does not win seats has its only piece of direct
evidence pointing the other way; the 08-08 cash-line anatomy graded on BOTH
mean-delta and percentile leaves the two statistics disagreeing on exactly the
axis this routing moves (floor 0.42 -> 0.00, field pressure 0.25 -> 0.80); and
`paid_places` is null for both contests in both the mined records and
`contest_library`, so the rule could not have fired on either build.

**What would make this decidable, in order:**

1. ARCHIVE executes Ben''s 2026-08-09 curated-archetypes decision (fragment in
   `docs/backlog_inbox/`), which populates `ticket_count` for the nine recurring
   satellite families and gives the routing key real values.
2. More than n=2 one-seat finishes to grade, on both statistics.
3. Then the routing is a one-line change against a real field, and the profile
   difference can be attributed rather than assumed.

**Do not treat this as blocked-and-forgotten.** The code side has been unblocked
since R30(a) landed on 2026-08-05; what is missing is evidence and a decision,
not a mechanism.

**Note 2026-08-13 (Ben, standing directive):** apex-over-cash is now the named
priority for GPP-shaped contests generally, and this item is the literal
routing decision it would flip for single-ticket satellites specifically.
Unmoved by the directive: a standing preference is not new evidence, and the
one piece of direct evidence on file (the floor-blend satellite win) still
argues the current routing has not cost a seat yet, on a sample of two. DEV's
no-not-yet stands; what would change it is still more finishes to grade, not
a restated priority.

### R10. Ownership and duplication, wired and graded (P1, M, gated) | was G3, absorbing RC 1.8/2.5/2.10

**Rider 2026-08-28 (DEV, carried forward from R205 at its landing rather than
closed with it): F1 accuracy and lineup-source confidence interact, and nothing
in the build reconciles them.** R205's filing session corrected the ATL@MIN
moneyline, rebuilt, and then REJECTED the corrected build and delivered the
original: correcting MIN 3.14 -> 4.25 moved the portfolio hard into MIN bats,
but MIN had not posted a lineup, so those bats came off a 14.6-day-old platoon
reference — 17 projected-order hitters against 8, the slate's weakest arm in 4
of 8 entries against 2, apex ceiling 149.9 -> 133.4. The number got more honest
and the portfolio got worse, because the team the correction promoted is the team
with the least reliable roster data. A confirmed-lineup team and a
platoon-projected team are currently equally knowable once F1 has spoken.
**Whether a TBD team should carry a confidence discount F1 cannot override is
Ben's**, and it belongs here rather than on the parser: it changes what every
projection means. The parser fix landed 2026-08-28 and did not touch this.

**Rider 2026-08-28 (ARCHIVE, ledger 3.21): the accumulation bar is met at
scale** — 610 parsed contests, 86 Classic + 88 Showdown carrying a graded
pre-lock prediction. Four facts the fit inherits: (1) the v0.1 error is
COMPRESSION — median per-contest Spearman 0.454 Classic, drafted-join signed
−6.5pp, the root doc's full-pool band view −9 to −17pp in the 10%+/20%+ bands —
so magnitude calibration by archetype × field size is the job, not re-ranking;
(2) SD fits use post-R235 emits ONLY (pre-fix artifacts grade WORSE than a
flat-budget null, rho ≈ 0; post-fix rho 0.542 over 34 contests); (3) satellite
field concentration DRIFTED +20-44pp top-5 within one season, so archetype
temperatures need a time term or a stated refit cadence; (4) the grading null
changes with the join population (drafted-only vs full-pool MAEs differ ~2×),
so the fit declares its null per 3.21 rather than inheriting flat-12.

- **Rider added 2026-08-18, landing R136:** the fitted model owes a column
  back. R136's low-owned-carry column wanted ledger 3.17's absolute sub-10%
  bar and could not use it, because the v0.1 prior spreads its 800% budget
  over every priced hitter row and puts EVERY hitter under 10% (measured on
  1905_7g: 284 rows, top hitter 8.9%, mean 2.8%). It ships as a within-pool
  tier instead. When a fitted prior lands on the actual %Drafted scale, the
  absolute count becomes meaningful and the column should switch back —
  `_leverage_legend` in `tools/qa_portfolio.py` recomputes and prints that
  arithmetic on every run, so the moment it stops reading "every row" is
  visible without anyone remembering this bullet.

- **Rider added 2026-08-23, from ARCHIVE fragment `2026-08-22_ARCHIVE_r10-evidence-two-dead-terms.md` (verified in tree by direct call):** the premise still holds — every writer of `Ownership_Tier` writes `"Mid"`, `DEFAULT_OWNERSHIP_PCT_BY_TIER['Mid'] = 12.0`, so a 10-man Classic lineup's `ownership_sum_pct` is exactly 120.0, and R154's `attach_projected_ownership` deliberately never touches `Ownership_Tier`. Two specifics this item does not name, and the second is the sharper one. **WHICH terms are dead:** of the five in `field_pressure_score = 0.70*meta_overlap + 0.035*ownership_total + 0.75*salary_band_penalty + 0.40*high_owned_one_offs + 0.35*(primary_count >= 5)`, `ownership_total` is a constant 120.0 and `high_owned_one_offs` requires `Ownership_Tier == 'High'` and is identically 0. **And the constant one is RANK-NEUTRAL by construction, not merely uninformative:** in an additive score compared across candidates a constant 4.20 contribution cannot change any selection, ever, while looking like a live term in every output. The score's stated job, penalizing duplicate-prone constructions, is carried entirely by `meta_overlap`, `salary_band_penalty` and the `primary_count >= 5` bump. Downstream, `has_duplication_signal = bool(meta_lineup_ids) or field['ownership_sum_pct'] > 0` is permanently True because 120.0 > 0, so the field-pressure penalty is always subtracted, `duplication_risk_proxy` is never None, and the `else None` branch at `optimizer_v3.py:3565` is unreachable — a reviewer asking "is the duplication signal on?" gets Yes on every candidate on every slate, including slates where no meta-lineup ids were supplied and the honest answer is No. When R10's prior lands on the production path, `_ownership_pct_for_row` already prefers `Projected_Ownership_Pct` so `ownership_total` comes alive with no further wiring; `high_owned_one_offs` will NOT, because it reads the tier. See also R197, the same class on the low-owned diagnostic.

- **What:** `ownership_prior.py` and `field_miner.score_duplication_risk` exist and remain unwired; nothing populates `Projected_Ownership_Pct`, so the optimizer's field-pressure term runs on flat tier defaults; meta-lineup failure degrades silently.
- **Why:** field behavior is the one commercial capability that materially changes satellite results (clearing the cut line unduplicated is the whole game), and it is the highest-value modeling work available once the archive is trustworthy, which F9/F10 made true. Gate unchanged: roughly eight archetype-conditioned slates; G4 means every new slate now also grades the operator, not just the field.
- **Fix:** per the 07-25 final plus RC's refinements: fit per archetype from the archive; model stack ownership separately from player ownership (stack popularity is not a product of independents); write versioned `data/reference/ownership_prior_<archetype>.json` artifacts and load them in `_assemble_projection_frame`; persist each slate's prediction file before lock so grading is never retroactive; grade with `grade_against_actuals` into the ledger against the flat-12 baseline with a stated go/no-go; wire the duplication screen into the checkpoint for satellite postures; surface `meta_lineup_status` instead of the silent empty list; label everything a prior, mark duplication `unmodeled` when ownership is absent rather than substituting silently. Live builds consume precomputed artifacts only; nothing trains at T-10. Done when: per-slate graded MAE/Spearman appear in the ledger; the prior beats flat-12 across the gate count before any production column flips; checkpoints show expected duplicates on satellite portfolios.
- **DECIDED 2026-07-31 by Ben, on DEV's recommendation. The gate reads "N slates in the satellite archetype", and R10 is UNBLOCKED, satellite-only.** The conditioning question below is answered yes. Three reasons. Ben's portfolio is 4,201 of 4,879 MLB entries in satellites, so the deep cell is the cell he actually plays and the archive is faithful rather than badly shaped. This item's own justification is "clearing the cut line unduplicated is the whole game", which is the satellite case, so a gate demanding breadth across archetypes measures something the item never claimed to care about. And CLAUDE.md already forbids pooling ownership across archetype and field size, so conditioning is the house rule and the old gate wording was the outlier, not the change. **The scope limit is the part that makes this safe and it is not optional:** the unblocked work fits and ships a prior for the satellite family ONLY, every other archetype stays on flat-12 until its own cell fills, and the fit cell is (satellite family, field-size bucket) with thin buckets left unmodeled rather than pooled. The bar is unchanged: beat flat-12 in that cell, graded into the ledger, before any production column flips. Breadth was never the safeguard; scope is. **Grading addition (2026-08-01, GF spec A-12):** the satellite fit is graded on duplication as well as ownership — predicted duplicates per lineup against the observed duplication distribution in the cell (`own_lineups_duplicated_by_field` is populated for every mined contest) — because duplication is the quantity the satellite case actually trades on. A prior that wins MAE/Spearman but mis-ranks duplication risk has not met the bar.
- **The definition question, now answered (2026-07-29, from an ARCHIVE fragment; ledger 3.15).** The `paid_places == 1` satellite cell holds **77 contests across 12 distinct slate dates with 286 of Ben's own entries**, against a gate asking for roughly eight archetype-conditioned slates. ARCHIVE's first pass read the archive as badly shaped (76 contests in 15 (paid_places, field-bucket) cells with 58 in one) and then withdrew that: the archive is FAITHFUL, because MLB satellites are 4,201 of 4,879 of Ben's MLB entries, so the deep cell is the relevant cell. This item's own justification agrees, "clearing the cut line unduplicated is the whole game," which means a gate demanding archetype BREADTH measures the wrong thing. **The open question is Ben's, and it is not depth, it is conditioning: should the gate read "N slates in the satellite archetype" rather than "N archetype-conditioned slates" generally?** If yes, R10 is unblocked today. If no, it stays shut until the contest mix changes, which is a portfolio decision rather than a modeling one. Do not start fitting priors before this is settled, because the answer changes what "per archetype" means in the fit. Two limits carried forward: "archetype" is undefined at this depth (8 contest families, 25 distinct field sizes from 15 to 297, so conditioning on family AND field bucket thins it fast), and meeting the slate count is not meeting this item's bar, which is beating flat-12 before any production column flips.
- **R10 is orthogonal to the parked satellite question, correcting an earlier reading.** It was carried as gated behind R13 and it is not: reducing duplication on a one-paid WTA satellite at a 118-median field does not require knowing whether the satellite leg is +EV on cash after promotions. That leaves R10 the only major board item waiting on no parked measurement, only on the conditioning decision above. `own_lineups_duplicated_by_field` is populated for all 97 mined contests, so the grading substrate exists. R30(a) is worth doing but is NOT this item's blocker.
- **Note 2026-08-04 (ledger 3.17):** starting priors extended by the A-030..A-034 mine — own Showdown lineups field-duplicated 27/109 vs 4/93 Classic; Showdown duplicated-entry share 27.2% median in 151-500 fields and 53.4% above 500, where the winning lineup itself is duplicated 40% of the time. R48's per-contest leverage table, once it lands, is the natural grading target for the satellite prior: a prior that cannot rank tomorrow's sub-10% top-scorers has not met the bar.
- **Note 2026-08-13 (Ben, standing directive):** reaffirmed, not changed, by
  apex-over-cash. "Clearing the cut line unduplicated is the whole game" (this
  item's own Why, above) already IS the apex claim for the satellite family:
  an apex-shaped lineup that is also the field's most-duplicated lineup has
  not actually won anything. This item stays the top of Tier 2 on that logic,
  unchanged in scope (satellite-only) and unchanged in gate (beat flat-12,
  graded, before any production column flips).
- **Note 2026-08-14 (audit), the flat-tier mechanism is sharper than "flat
  tier defaults":** `Ownership_Tier` is unconditionally defaulted to `"Mid"`
  (`slate_intake_manager.py:1353`; `execution_pipeline.py:2603,2776,3053`)
  and never set from data, so `ownership_sum` is a constant 120.0 for every
  10-man lineup — the field-pressure ownership term cancels in ranking,
  `has_duplication_signal` is ALWAYS true (the penalty always applies), and
  `high_owned_one_offs` / `low_owned_hitter_count` are structurally zero
  (`optimizer_v3.py:2763,2951-2956,3370-3408`). The only live duplication
  signals today are meta-lineup overlap, the >=49800 salary band, and the
  5-stack term. Two consequences: the `Projected_Ownership_Pct` seam this
  item fills is real and single (`:2952-2955`), and R118's replay gives this
  item its duplication grading target from the archive without waiting on
  new tranches.
- **Note 2026-08-16 (leverage ideation fragment): the two control halves this
  item owns once its bar is met, filed as riders so nobody builds them
  early.** (1) Leverage-carry — a counted, relaxable per-lineup rule for
  narrow-breadth postures: at least one hitter under 10% PREDICTED own INSIDE
  the primary stack. Inside matters: 3.17's paying pattern is low-owned
  pieces within chalk-positive correlated lineups, not dangling one-offs,
  and `high_owned_one_offs` already penalizes the dangling kind once real
  tiers exist. (2) Duplication budget — a per-portfolio cap on lineups in
  the top predicted-dup decile for satellite postures, calibrated against
  R118's exact dup counts and A/B-able in replay for free (same bank,
  control on/off, scored against the real field). Both relax-and-count,
  never a pool edit; both wait on the prior beating flat-12 in the cell,
  which is unchanged.
- **PRECONDITION added 2026-08-24: R225 lands before this item grades
  duplication in any SHOWDOWN cell.** The bar here reads duplication from the
  miner, and the miner's Showdown duplication is captain-blind at all three
  counting sites, so every Showdown duplication figure in ledger 3.17 that this
  entry cites is inflated by construction (the 27.2% median duplicated share,
  the "winning lineup duplicated 40% of the time", the own 27/109). Classic
  cells are unaffected — `players_norm` is a complete identity there — and the
  currently unblocked satellite cell is Classic, so this precondition does not
  hold the item as a whole. The recount needs no re-mine: `captain_norm` is
  already on every parsed entry. ARCHIVE carries a one-sentence caveat on
  ledger 3.17's Showdown rows until it lands.
- **Rider 2026-08-28 (ed9 §6.2, one sentence made explicit):** duplication
  is never estimated as a product of player ownerships at any level — the
  Fix above already says stack popularity is not a product of independents,
  the same holds for exact lineups, and the grade that enforces it is
  duplicate-count calibration by predicted band, which the duplication bar
  above already implies.

### R48. `field_miner` emits a per-contest leverage table (P2, S) | new 2026-08-04, from ARCHIVE fragment `2026-08-04_ARCHIVE_miner-leverage-table.md`, merged 2026-08-04

- **What:** the 3.17 leverage measurement — in 104 of 116 Classic contests (>= 40 entries) at least one player finished top-5 in contest FPTS under 10% drafted (mean 2.19 per contest); winners carried >= 1 in 51% against a 13% field base rate — was a bespoke pass over the mined JSONs. Nothing persists it per contest, so every regrade re-derives it and no build-time surface can ever cite it.
- **Why:** it operationalizes the one differentiation channel the archive shows paying (low-owned pieces inside chalk-positive lineups) and is the natural grading target for R10's satellite prior. R39 was the Showdown half of the same blindness and landed 2026-08-08: `captain_norm` now rides every parsed entry and the miner emits a per-contest captain table, so the leverage table's Showdown counterpart has its input.
- **Fix:** a `leverage` block per mined contest (players under 10% drafted with top-5 FPTS: name, %drafted, FPTS; carry rates for winner / top decile / field), same truthful labels as the rest of the block — deterministic descriptive statistics, never a probability claim. Backfill is one idempotent re-mine of the archive (~10 minutes in the cloud container per the 2026-08-04 registry-rebuild pattern). Pairs with the R30 miner batch.

### R206. Every portfolio control counts ENTRIES, and the money is not distributed that way (P1, M + one Ben decision) | new 2026-08-23, merged from BUILD fragment `2026-08-19_BUILD_portfolio-controls-count-entries-not-dollars.md`; surfaced by an external red team that three internal passes missed

- **What:** `max_player_exposure_pct`, `max_primary_stack_exposure_pct`,
  `max_pitcher_exposure_pct` and `max_shared_players` all measure share of
  ENTRIES, and the washout/apex proxies in `execution_pipeline` do the same.
  Every one uses an equal-weighted denominator. The 2026-08-19 `1235_4g`
  entered set was not equal-weighted: 8 entries across 6 contests, $17.75
  total, with a single $15 entry carrying **84.5% of the money** (the rest being
  $1.00, $0.50 and five $0.25 satellites). On the count denominator the
  heaviest exposures read 4 of 8, a comfortable 50%. On dollars: Drake Baldwin
  and Jackson Merrill 94.4%, Paul Skenes 91.5%, Michael King 88.7%, **Matt
  Olson 25% by count and 84.5% by dollars** — he appears in a quarter of the
  entries and carries five sixths of the bankroll, because one of those two
  entries is the $15 one.
- **Why:** this is not "the caps are too loose." The caps are enforcing a
  constraint nobody chose, and the cost runs both ways: diversifying entries 2
  through 8 away from entry 1 spends real ceiling in those entries and buys
  almost no dollar diversification, because entries 2 through 8 are $2.75
  combined. A control reading 25% is describing a different portfolio than the
  one that exists. Worth noting who caught it: an external red-team review of
  the delivered file, not the build, not `qa_portfolio.py`, and not the
  session's own adversarial pass — three passes over a portfolio whose headline
  risk number was off by a factor of three.
- **Fix, and the decision inside it:** the mechanism is a weighted denominator
  — entry fee per Entry ID is in the DKEntries template, so the weights are
  already on disk and need no new input. **What is Ben's is whether the caps
  SHOULD be dollar-weighted, and that is not obvious**: an equal-weight cap is
  the right instrument for "don't lose every entry at once" (the washout axis
  R153 names, which is about correlated failure across entries and genuinely
  counts entries), while a dollar-weighted cap is the right instrument for
  "don't lose the bankroll at once." Those are two different objectives and the
  dual objective in CLAUDE.md does not currently say which one the controls
  serve. Recommended shape: REPORT both denominators first (cheap, S, no
  behaviour change) so the divergence is visible on every mixed-stakes
  portfolio, and only then decide whether any cap binds on dollars. Reporting
  first is also what makes the decision answerable with evidence rather than
  from one slate.

### R209. The objective's leverage proxy measures nothing, and the first graded prediction says ordering is usable while level is not (P1, M, gated) | new 2026-08-23, merged from BUILD fragment `2026-08-19_BUILD_apex-means-leverage-adjusted-not-points-max.md`; its parts A and B SHIPPED as R154 the same day, this is part C plus the calibration reading

- **What:** `salary_uniqueness_weight` (0.62 on `large_field_gpp`) is the
  engine's current stand-in for uniqueness, and on the 2026-08-19 `1235_4g`
  apex contest it measured nothing: the delivered entry spent exactly $50,000
  and was the **97.6th percentile chalkiest lineup** in a 7,833-entry field
  (95.6th on realized ownership). Salary uniqueness is not ownership
  uniqueness. Ben's own formulation is the replacement — a leverage-adjusted
  value term weighted by contest shape, zero for cash and largest for a
  top-heavy large field.
- **The evidence, and it cuts two ways.** The pre-lock prediction file was
  graded against the standings for 112 priced players. **Ordering is usable:**
  Spearman +0.581 on `large_field_gpp` and +0.505 to +0.660 across archetypes,
  and since flat-12 carries ZERO rank information by construction, +0.581
  clears R10's bar on this cell. **Level is not:** every archetype
  under-predicts (`large_field_gpp` predicted sum 610 against a real 909, a
  third short), and rescaling to the known slot total makes it WORSE (MAE 5.71
  → 5.92), so it is not a normalization error. A leverage objective needs only
  the ordering — you do not need to know a player will be owned 30%, only that
  he will be owned more than the alternative — which is exactly why R154 shipped
  two linear CONSTRAINTS rather than an objective term. The realized
  ownership/finish relation was monotone across every finish band (1st 167.0%
  cumulative and 4.00 sub-10% bats; whole field 187.5% and 3.33; our entry
  254.7% and 2).
- **Why it is gated, and by what:** one contest cannot size a coefficient that
  changes what every player is worth, and on this slate the CHALK BUSTED, which
  is what makes the relation look so clean — on a slate where chalk hits, the
  ordering inside the cashing bands inverts. The structural case for leverage
  does not rest on chalk busting, it rests on duplication splitting a top-heavy
  prize, but the MAGNITUDE above is one observation and is not a calibration.
  The fragment is explicit that the delivered entry finished 5287th and scored
  56.35 against a field mean of 64.74, so it lost on POINTS as well as on
  leverage and the two cannot be separated from one result.
- **Fix:** after 3-5 more graded slates, replace `salary_uniqueness_weight` with
  the leverage-adjusted value term, weighted by contest shape. **Before that,
  the smaller and unblocked prerequisite: nothing calls
  `attach_projected_ownership` on the production path**, so R154's constraints
  reach no build until a caller sets values — wiring it into `run_slate` with
  per-contest-shape numbers is a separate, smaller item and it comes first. The
  target band from this one contest, stated as a band derived from one contest
  and never a calibration: roughly 160-170% cumulative ownership and at least 4
  low-owned bats for a top-heavy large field. Grades belong in the ledger,
  which is ARCHIVE's write.

### R197. `_low_owned_hitter_count` reads a key no writer writes, so it is identically 0 while R154's constraint counts the real thing (P2, XS) | new 2026-08-23, merged from ARCHIVE fragment `2026-08-22_ARCHIVE_low-owned-diagnostic-false-signal.md`; VERIFIED-repro by the filing session

- **What:** `optimizer_v3._low_owned_hitter_count` counts rows where
  `Ownership_Tier == 'Low'`. Every writer of `Ownership_Tier` in the tree
  writes the literal `"Mid"` and that is the complete set
  (`slate_intake_manager.py:1353`, `execution_pipeline.py:3070`, `:3384`,
  `:3661`), so `low_owned_hitter_count` in every candidate record is 0. R154
  (landed 08-19) added the REAL low-owned test as a MILP constraint on
  `Projected_Ownership_Pct` against `DEFAULT_LOW_OWNED_THRESHOLD_PCT = 10.0`,
  and left the old diagnostic standing beside it. Repro'd directly: a frame of
  five hitters at 4.0% ownership gives 5 by the constraint's measure and 0 by
  the diagnostic's.
- **Why:** the 2026-08-15 false-signal batch closed on the stated theme that
  "the underlying computation was already correct, but the line reporting it
  either couldn't fire, blamed the wrong control, or pointed at a key that
  didn't exist." This is that, and it arrived four days AFTER the batch closed.
  A build satisfying a `min_low_owned_hitters` floor of 4 reports 0 low-owned
  hitters in its own record. Nothing calls `attach_projected_ownership` on the
  production path yet, so the disagreement is latent rather than live — the
  cheapest possible moment to fix it, and also the moment at which it is
  easiest to ship a build whose counters lie.
- **Fix:** read the diagnostic off the same quantity the constraint reads
  (`_ownership_pct_for_row(row) < DEFAULT_LOW_OWNED_THRESHOLD_PCT`), hitters
  only, keyed on the slot's required POSITION and not the slot name — R154's
  own bring-up already found `slot != 'P'` is true for P1/P2. One definition of
  low-owned in the module, the way R154 put one definition of the threshold in
  it. Then decide whether `Ownership_Tier` should exist at all now that
  `Projected_Ownership_Pct` is the live column; if it stays, a guard that fails
  loudly when a behaviour-bearing read finds only the default would have caught
  this and R10's original inertness both.
- **RIDER 2026-08-24, and the class is FOUR reads, not one (Codex spec D19,
  every site re-verified here).** This entry names one dead read. The tree has
  four, all downstream of the same never-written column, and one of them is not
  a diagnostic. `optimizer_v3.py:3043` (`== 'Low'`, the filed one, identically
  0); `:3454` (`== 'High'` in the field-pressure score, identically False, so
  the off-primary chalk term never fires); `:1354` and `:2010`
  (`_ownership_priority` over the tier, a constant ordering key that therefore
  breaks no ties); and **`:3018`,
  `DEFAULT_OWNERSHIP_PCT_BY_TIER.get(row.get('Ownership_Tier', 'Mid'), 12.0)`,
  which returns a flat 12.0 for every player on the slate** and feeds the
  ownership-total contribution the field-pressure score is built from. That
  last one is the reason this rider matters: the filed item reads as "one
  counter says 0", and the actual condition is that a scoring term has a
  constant input while `has_duplication_signal` can still read True. Writer
  line numbers in the What have also moved (`execution_pipeline.py:3099`,
  `:3412-3413`, `:3689`; `slate_intake_manager.py:1353` unchanged). This is
  ed7 §1.2's finding shape applied to this board's own entry: when an item
  names one site, count the sites before believing one. Fix scope grows
  accordingly — decide `Ownership_Tier`'s existence FIRST, because three of the
  four reads want deleting rather than repointing.

### R83. Per-run calibration provenance: persist the factor audit, hash-bind enrichment inputs, golden-replay one real manifest row (S) | audit 2026-08-04

- **ed6 rider (2026-08-22, VERIFIED-read):** the golden gate's blind spot is
  wider than the manifest row. Both golden scenarios run the ARCHIVED
  2026-06-03 salary schema — whose header predates DK's `Status`/`Starting`
  columns — and both inject `projection_rows` directly, so `build_slate_pool`
  and the R143 DK-order merge are never on the golden path. A regression in
  the current-schema intake ships with the full suite green; coverage there
  is unit-level only. When a post-`Starting` slate is archived with its feed,
  add a third golden scenario THROUGH the front door — it rides this item's
  slot.

`run_slate` discards the per-player Base/F1–F5/Floor/Ceiling audit table `build_projections` returns (`execution_pipeline.py:2571`, `projections, _audit = ...`); writing it to `runs/<run_id>/final/projection_factor_audit.csv` gives post-slate grading the exact join the ledger currently lacks — direct support for R10's grading bar. Pass the Savant/odds/archetype files through `additional_input_paths` so `verify_inputs_unmoved` covers everything that moved the numbers. Add one golden-replay assertion over a REAL run's manifest row so result-shape drift cannot silently recur: this is the residual guard R64 asked for and did NOT ship when R64 landed 2026-08-04, and it is the only part of that item still open. R64 fixed the two readers; nothing yet pins the result SHAPE they read.

### R13. The stakes decision (decision, after data) | was G7

- **What:** unchanged: scale the stakes to match the engineering, or freeze the engine and run it. Now mechanically unblocked: G4 landed, so net-to-date accumulates from the next archived slate onward.
- **Why:** it remains the item that dominates the rest of this list, and it remains undecidable without the number. Nothing above blocks on it, by design.
- **Fix:** a dated ledger entry once a meaningful sample exists (the 07-25 target was within ten graded slates). If the answer is scale, R10 becomes the top of the board and the sim ladder question reopens under its stage gates; if freeze, R1/R2/R3/R4 still land (they protect uploads at any stakes) and the rest of this list stops.
- **This item has less decidable surface than it looks, and Ben has parked the missing half (2026-07-29, from an ARCHIVE fragment; ledger 3.14).** The entry-history export carries only `Entry_Fee`, `Winnings_Non_Ticket` and `Winnings_Ticket`. A third channel exists that the export cannot see: DK promotional benefits tied to ticket acquisition and to contest-entry volume, which plausibly runs OPPOSITE to the cash result, because a $0.01 satellite is the cheapest available unit of "contest entered" and any promotion keying on entry or ticket counts is served far better by 4,201 penny satellites than by 678 dollar contests. **Ben's call on 2026-07-29: leave it unmeasured; no promotional record gets pulled for now.** Consequences to respect: the satellite leg's -$244.45 is a CASH-ONLY figure and must never be quoted as the result of the strategy; any earlier reading that "the satellites are the loss" is withdrawn; and since the satellite block is 86% of MLB entries and is now explicitly ungraded, what remains is 678 non-satellite entries at $301.01 fees against $247.15 cash, a small sample of observed outcomes that is not evidence of an edge in either direction. R13 stays open and the next thing that moves it is graded non-satellite slates accumulating, not another pass over this export. Separately, the $175 of unresolved ticket face is **held inventory, not a loss**: several of those Best Ball contests have not commenced (NFL from September 2026, NBA from October), so a re-export after they settle resolves it in the record and nobody needs to chase it before then.
- **[Corrected 2026-08-16 (DEV): Ben DECIDED this on 2026-08-09 and this line never caught up.** The decision is recorded in `docs/backlog_inbox/2026-08-09_DEV_ben-decision-curated-satellite-archetypes.md`, which is retained on disk as its sole carrier — it holds the nine-family table, the observed `ticket_count` values, and four cautions that exist nowhere else (three families are multi-valued and must not be written single-valued; the `SUPERSat` matcher gap worth 17 entries; check `competing_patterns` before adding nine patterns at once; two rows are GOLF-only and are not this engine's domain). Two other entries on this board already say Ben decided — R10's step 1 and Tier 4's R1c-tail — so only this paragraph was stale. What remains is ARCHIVE executing it, not Ben deciding it. The text below is left as written history.]
- **Awaiting Ben, carried from the same fragment and NOT written:** nine recurring satellite/qualifier families Ben demonstrably enters, by name substring, with the `Places_Paid` values actually observed (for a satellite, `Places_Paid` IS the ticket count awarded). The table is in ledger 3.14. ARCHIVE did not add them to `dk_contest_archetypes.csv` because a curated `ticket_count` reaches `resolve_contest_shape` immediately, where 1 routes to `wta_ticket_satellite` and anything else takes the ticket-line blend: that reranks lineups on contests entered tonight, which makes it a strategy change and Ben's dated decision rather than an archival write. Same reasoning for BUILD's suggested `Solo Shot` row. What DID land is the pure observed-history half, in `data/reference/contest_library.json` (`mlb $1.25k solo shot (early)|1.00`, field 1486, paid 350, breadth 0.2355), which is trust-order-2 and outranks name inference the next time that exact contest and fee recurs without changing any shape mapping. Given that the satellite volume is now an open question rather than something to cut, this input is more likely to matter than it looked: if the satellites are staying, routing them to the right objective is exactly the work that pays.

### R137. Market-vs-crowd divergence screen (P2, S; quota-priced) | new 2026-08-16, from the leverage ideation fragment

- **What:** the classic leverage screen from two inputs already licensed:
  hitters whose HR-implied percentile (the per-event props tier MLB_Classic.md
  14 names Optional and quota-expensive) exceeds their structural-own
  percentile (v0.1 prior, then R10's) by a stated margin. Deterministic,
  review-only, per slate; feeds candidate review under section 7's "credible
  duplication/ownership inputs" and never touches the solver or the pool.
- **Cost stated up front, from MLB_Classic.md 14's own arithmetic:**
  per-event prop markets run ≈13 credits per 12-game slate per market against
  the free 500/month — a nightly screen spends most of the budget. Run it on
  decision slates or on odds-api.io's flat quota; budget before pulling, and
  the report prints what it spent.
- **Audit fields.** Moves: leverage. Acceptance: fixture odds packet + prior
  file → ranked divergence list with the margin stated. Falsifier: if
  HR-implieds and structural own rank-correlate too tightly to separate
  (plausible — both read the same Vegas totals), the screen returns empty and
  says so; that result is informative and ends the item. FOSS: existing
  adapters. Owner: none. Rollback: delete the tool.

### R246. R154's leverage constraints have no production caller: a `--leverage` passthrough makes them reachable and gradeable (P2, S) | new 2026-08-27, merged from BUILD fragment `2026-08-27_BUILD_container-bank-and-r157-single-cap.md` §4, second sighting of the Quick Card's 08-19 Relay Throw reading; corroborated by the outside spec ed8 (F-15)

**What.** `max_cumulative_ownership_pct` and `min_low_owned_hitters` exist at
`optimizer_v3.py:778-779` and are wired through `build_single_lineup`; grepped
at this head, no caller in `build_slate.py`, `execution_pipeline.py`, or any
tool, and `attach_projected_ownership` likewise. On 1905_5g qa priced all 14
entries chalk-positive (+11.1 to +46.0 pp) and Ben's in-slate ask was
explicitly to increase leverage; the honest answer was "the lever is built but
not connected," and connecting it mid-slate means editing the engine, which
the contract forbids.

**Why.** R154 shipped the constraints deliberately OFF pending calibration;
what was not intended is that no path can turn them ON. The distinction that
keeps this truthful-labels-safe: the passthrough forwards numbers the CALLER
chooses, defaults unchanged, prior still labeled.

**Fix.** `--leverage` on `build_slate.py`: read the slate's own
`ownership_pred_<tag>.json` (emitted pre-lock since R135, already resolved by
brief date + tag in qa), call `attach_projected_ownership`, forward the two
numbers when given. Brief records the prediction file's sha and the two
values. The caveat rides the entry verbatim: within-file ORDER is what the
prior supports, and ledger 3.17 has supersatellites chalk-NEGATIVE for
winners, so this is a direction to test, never a number to apply. R209 owns
the objective/calibration half, unchanged.

### R252. The mispricing score: two anchors, components attributed, reported as a vector (P1, M; S with components (a)–(c) only) | new 2026-08-27, from Ben's greenfield instruction; the 2145_1g_sd session's hand-built BUY/FADE model (consumed into R247/R249) is the prototype; retitled 2026-08-28 (ed9)

**What.** The enrichment stack adjusts the projection and nothing states the
DIVERGENCE. Two anchors, because they are different markets: salary-implied
points (a salary→realized-FPTS regression per format and role, fit on the
archive's 29,921 player-contest rows) answers "is this player mispriced by
DK," and the ownership prior answers "is this player underpriced by the
FIELD." The honest expectation, stated up front: DK prices skill well on
average, so the salary anchor mostly catches NEWS (components (d)–(e)); the
ownership anchor is the softer market and is where leverage actually lives.
Components, each attributed in the output: (a) opposing-arm and platoon delta
(F4 already computes both), (b) park delta (F5 today, R253's refinement
later), (c) the xwOBA−wOBA gap and its recent trend — skill leads results,
salary and field ownership chase results, and Savant carries both columns,
(d) line movement since salary post (needs R251's morning capture), (e)
batting-order promotion against the slot expectation APPG embeds. (f) is
R137's HR-implied-vs-structural-own screen, which RIDES here unchanged,
quota note intact.

**Why.** This is Ben's thread-1 ask made mechanical. The operator lever
already exists (R249 `--projections`, R246 `--leverage`) and the LIST feeding
it is hand-built per session; the 2145_1g_sd build proved both the value and
the cost of that.

**Fix.** One module emitting the ranked list (BUY and FADE ends) with per-
component attribution, into the brief and qa as a review surface. LABELED
PRIOR; no solver input until R255 grades it. Showdown reach through R249's
flag. Feeds R209's part C and R254. Late-swap application cross-refs R141.

**Rider 2026-08-28 (ed9 §1.3/§2.1–2.2, accepted; title amended from "one
number per player").** The interface is the VECTOR: salary edge and field
edge stay separate named fields with their component attributions, never
collapsed into one blended rank — one number hides whether an edge is
performance or mere inattention. One sentence of doctrine adopted with it:
leverage requires BOTH a positive skill edge and an unreacted field; low
ownership alone is never leverage. Two columns deliberately NOT here, so
nobody re-files them: duplication edge is lineup-level and lives in R10;
marginal portfolio coverage lives in R261/R262. And when R259's buckets
land, the salary anchor gains a TAIL delta (P(Y ≥ q) against the
salary-implied distribution, q salary/role-conditioned) beside the mean
delta — mean-only mispricing misses the spike this lane hunts.

### R253. Park factor conditioned on handedness and profile: the F5 refinement that reprices power for tonight's venue (P2, M) | new 2026-08-27, from Ben's greenfield instruction (his own example: xwOBA that plays up in a specific park)

**What.** F5 is a global park/weather run environment. The example Ben named
needs park×handedness at minimum (the short-porch LHH case), and Statcast
publishes the direct instrument: per-park expected HR ("a HR in N of 30
parks"), which reprices a batter whose season line is suppressed or inflated
by home park the moment tonight's venue differs.

**Why.** Power is where the spike in nightly FPTS lives (R259's shape
finding), so park×hand mispricing concentrates exactly where top-1% scores
come from.

**Fix.** A per-park×hand factor table (S), an optional profile term
(pull-rate × porch geometry) after; applies as an F5 refinement and R252
component (b). **Sequenced AFTER R252 grades a cycle:** add components where
R255's residuals say they matter, not on principle.

**Rider 2026-08-28 (ed9 §2.3, accepted).** The park component is graded
with an ablation against the market anchor: team totals already price the
public run environment, so a park term that adds to a projection the total
has already moved counts the same information twice and mints fake edge.
R255's grade for component (b) therefore reports attribution with and
without the total anchor. The full batted-ball venue transform (§2.3's
six-step chain) stays the L-shaped refinement behind the existing pull
condition; the v1 instrument is unchanged.

### R254. Captain mispricing screen: the Showdown apex lever (P1, S-M once deps land) | new 2026-08-27, from Ben's greenfield instruction; depends R225 (captain-truth), R238 (archetype key), R252

**Rider 2026-08-28 (ARCHIVE, ledger 3.21): the captain-share prior must
condition on FIELD SIZE, not archetype alone.** Winners in <100-entry satellite
fields captain a 45.1%-CPT-owned player against a 36.3 field mean (chalk captain
wins micro fields); winners at 1k-10k captain 11.3 vs a 14.8 field mean
(leverage captain). A pooled CPT-leverage rule has the SIGN wrong in one of the
two cells we actually play. The mismatch this screen should price first: our
pitcher-CPT share is 40% against 65.5% of winners (field 46.0, replicated both
halves), and we over-index the replicated-NEGATIVE 5-10% CPT-ownership band
(root doc: ours 19.65% vs field 17.48%).

**What.** In Showdown the top-1% question is mostly "right captain, right
script." The field's captain share concentrates on the top APPG names; the
archive holds realized captain ownership per contest (countable correctly
once R225 lands). Join R252's skill list to a captain-share prior by
archetype and rank CAPTAIN leverage — the BUY-graded mid-salary bat with a
platoon+park edge at a 2% captain share is the play the ladder should be
able to name.

**Why.** The 1.5x slot is the highest-leverage seat on the card and the one
place mispricing pays double; today the ladder captains by thesis template
and APPG with no attention model at all.

**Fix.** `captain_share_prior` mined by archetype (rides the R48/R258 mining
batch), joined to R252, output feeding R139's step-2 ladder targets and
R250's reservation pass. R10's fitted prior upgrades the share model when it
lands; this ships on the archive's observed shares first.

**Stage 2, filed 2026-08-28 (ed9 §1.3/§3.3, accepted as the upgrade path;
dep R261).** The decision quantity this screen ultimately wants is captain
OPTIMALITY against captain ownership, not skill × low share: once R261's
Showdown bank exists, score each scenario, solve the top lineups, record
each player's CPT-inclusion share, and rank by the gap against the field's
captain share (logit scale, shares shrunk off 0/1), with the resulting
lineups' duplication read beside it. A 2%-owned captain who never captains
a top lineup is not leverage; a 20%-owned one optimal in a third of
scenarios can be. Stage 1 — archive-observed shares joined to R252 — ships
first, unchanged.

### R255. Grade the skill signal the way the ownership signal is graded (P1, S) | new 2026-08-27, from Ben's greenfield instruction; the R135 pattern on the projection side

**What.** R135 wired predict-then-grade for ownership; nothing grades the
projection or R252's mispricing list. Per slate: persist the pre-lock list
(immutable under R251's freeze), and at archive time grade realized FPTS by
BUY/FADE bucket and by COMPONENT against the salary-implied baseline —
counts and deltas on observed outcomes, n stated, never a probability claim.
Rolling table in the ledger's calibration section; the archival runbook
gains the step beside the ownership grade (ARCHIVE's half).

**Why.** This is the bar R209 set: a signal earns objective weight by
grading, and it is what licenses R252 to ever leave review-only. It also
prices R253/R256's pull conditions instead of arguing them.

**Fix.** `mispricing_grade` beside `ownership grade` in the mine pass; ledger
section extends 3.17's leverage table with the skill axis.

**Riders 2026-08-28 (ed9 §1.3/§2.5/§9, accepted in the lightweight form).**
(a) The grade carries a TAIL axis from birth: BUY/FADE hit-rates at
predeclared tail cutoffs (realized p90+ of the salary/role baseline),
counted beside the mean deltas — bucket means alone are confounded and
tail-blind, and this lane's objective is tails. (b) Each component's
primary metric is declared on this entry BEFORE its first grade, and the
ledger table reports every graded component including the failures — the
anti-overfitting half of the spec's register idea, without the ceremony.
(c) Any holdout split is by slate DATE, never player-row or contest-row:
one slate is one joint outcome. (d) When R259 lands, the grader grows
distribution metrics (stated-quantile coverage counts first; CRPS/log
score as labeled diagnostics), replacing nothing.

### R256. Arsenal-vs-profile matchup layer — explicitly NOT raw BvP (P2, L; gated on R255 residuals) | new 2026-08-27, from Ben's greenfield instruction, filed with its pull condition

**What.** Batter run values by pitch class (Statcast) crossed with the
opposing arm's arsenal mix, shrunk empirical-Bayes toward season skill. Raw
batter-vs-pitcher stays banned — the samples are noise and the archive's own
truthful-labels rule applies to inputs too.

**Why/Gate.** Highest-variance idea in the lane, most expensive, and only
worth building if R255's grading shows matchup-shaped residual AFTER
(a)–(c) land. Pull condition named per Tier 6 discipline: a measured
residual, not an argument. **Method note 2026-08-28 (ed9 §2.3):** when
pulled, the shrinkage family is synthetic comparables (SEAM-style: pool
over similar batters and similar arsenals), never raw cell splits; the
pull condition is unchanged.

### R257. Extend the kill matrix: teams, arms, and the Showdown script axis (P1, S; rides queue slots 6–7) | new 2026-08-27, from Ben's greenfield instruction; extends R126's shipped washout block

**What.** R126's washout proxy zeroes a GAME's hitters. The events that
actually kill portfolios are finer: one TEAM quiet (kills its stacks, not
the game's other side), one of OUR arms blowing up, and in Showdown the
game SCRIPT — favorite-runaway / close / underdog / duel — which the thesis
labels already encode, so per-contest script coverage is nearly free once
R239(c) reports slices.

**Why.** These are the deterministic halves of Ben's washout goal,
buildable now with no distributions and no gate: the readout is "which
single event zeroes how many entries in this CONTEST," which is exactly the
question the 08-24/08-26 fragments kept answering by hand.

**Fix.** Add team-zero and own-arm-blowup rows to R126's kill matrix; map
thesis labels → script axis and print per-contest script coverage in the
R239(c) block. Proxies, labeled as such, in the brief beside apex/washout.

### R258. The threshold model: mine what top-1% and cashing REQUIRED, then predict it pre-lock and grade it (P1; mining half S rides the R48+R83 batch, predict half M) | new 2026-08-27, from Ben's greenfield instruction; the load-bearing idea of the dual-objective lane

**Rider 2026-08-28 (ARCHIVE, ledger 3.21): a seed threshold table exists, and
the satellite cell simplifies.** Mean winning / top-decile scores by slate size:
Classic 138.9/116.2 (1-2g), 144.6/116.4 (3-4g), 161.1/127.3 (5-6g), 162.8/128.8
(7g+); Showdown winners 83-98 by field bucket, top-decile bar ~72. One
structural fact collapses T[s,c] where most of our volume sits: observed
satellites pay ONE seat in 75 of 81 paid-known rows
(`data/reference/dk_contest_paid_places.json`), so the satellite threshold IS
the win line and "cash" is not a separate target there — the washout axis stays
portfolio-level, per the dual objective. Paid-place coverage is 97 of 610
(16%, all ≤07-29), not zero; R30's data half is what extends it.

**What.** Every archived contest's standings hold the full realized score
curve. Mine per-contest: winning score, p99 / p95 / p90 lines, cash line,
ticket line for satellites, and duplicate count at the top, into a
per-archetype × field-size table (preconditions: R226's rank truth; R118's
draftgroup keying caveat). Then the predict half: pre-lock, predict
tonight's thresholds from slate features (implied-run environment, field
size, archetype, format) and grade the prediction per slate in the ledger,
R135-style.

**Why.** This converts "maximize P(top 1%)" from a field-simulation problem
into a scalar prediction problem: P(top 1%) = P(own score ≥ p99 line), no
opponent-lineup generator required — the archive already watched the field
so we do not have to simulate it. Prize SHARE still needs duplication (R10's
lane, unchanged). The same table prices contest SELECTION — which archetypes
post thresholds our construction actually reaches — which is evidence R13
and D2 have been waiting on, and R40's routing reads it too. A threshold is
an observed outcome; a predicted threshold graded per slate is exactly the
label discipline the ledger already runs.

**Fix.** Mining pass emits `contest_thresholds` beside R48's leverage table
(one batch, one re-mine); predict half is a small model with two baselines
(archetype median; environment-scaled) so beating naive is demonstrated, not
asserted.

**Rider 2026-08-28 (ed9 §4.3, accepted — the edition's sharpest point,
landed before the mining batch could bake the biased version in).** A
threshold predicted independently of our own outcomes is biased for exactly
the quantity this lane wants: our scores and the top-1% line CO-MOVE
because they arise from the same slate (a high-scoring night raises both; a
pitchers'-duel Showdown lifts our pitcher-heavy entries while the absolute
line falls). P(top 1%) = P(own ≥ T) only when T is the threshold in the
SAME world as the own score. So the predict half is a CONDITIONAL model,
`T[s,c] ~ P(T_c | X_c, Z_s)`: `X_c` the pre-lock contest/slate context the
Fix already names, `Z_s` scenario-state features computed from the same
draw R261 scores our entries on (realized run environment at minimum;
optimal/chalk-score proxies as they become available), compared inside each
scenario, never against one frozen point. Three consequences now: (i) the
mining half's ONE batch also captures per-contest realized slate covariates
(the run environment per archived date is reconstructable), so the
conditional fit has its columns without a re-mine — this rider exists so
the batch runs once; (ii) the predict half gains a third named baseline,
the environment-blind marginal threshold, and the conditional model must
beat all three on held-out slate DATES; (iii) the pre-lock per-archetype
table stays the human-readable summary R13 and contest selection read — the
conditional form is R261's consumption path, and both forms are graded.

### R259. The variance basis: per-player nightly FPTS distribution priors, graded distributionally (P1, M) | new 2026-08-27, from Ben's greenfield instruction; satisfies the sim gate's third clause, and is buildable from what the archive already holds

**What.** The sim gate's own text: reopening the ladder without a variance
basis reproduces the v2.20.0 retirement (sigma as a constant multiple of mu
is structurally wrong). The basis exists in-house: 29,921 archived
player-contest FPTS rows bucketed by role, salary band, batting slot,
implied team total and platoon, with Statcast HR/K rates supplying the spike
shape — hitter nightly FPTS is zero-heavy and HR-spiked, not Gaussian.

**Why.** Both of Ben's quantities are tail statements; tails come from
distributions, not point estimates. This is the piece that makes
P(own ≥ threshold) computable at all.

**Fix.** Empirical bucket distributions + parametric spike overlay; graded
on held-out slates as stated-quantile coverage COUNTS (a distribution prior,
graded, never a per-player probability claim until the ledger's n says so).
R260's bucket findings inform the design, so R260 lands first.

**Rider 2026-08-28 (ed9 §1.3/§5.1, noted with its pull condition).** The
named refinement axis is explicit opportunity modeling — PA/BF, starter
exit, pinch-hit risk — pulled only if the stated-quantile grades show the
slot/implied-total buckets underfitting opportunity variance (those buckets
already carry most of the PA signal implicitly). Not built on principle;
the spec's Level-1 event ladder stays behind the gates. Holdout splits by
slate DATE, never player-row (R255 rider (c), same reason).

### R260. The correlation structure, mined from the archive (P1, S-M; do this FIRST in the modeling trio) | new 2026-08-27, from Ben's greenfield instruction; pure observed outcomes, no gate interaction

**What.** Teammate co-movement of realized FPTS by batting-slot distance,
same-team, same-game — measurable today across 26+ slate dates and 5,926
(slate, player) observations. Nothing in the repo states how correlated
slots 1–2 versus 1–6 actually are, while every stack rule assumes an answer.

**Why.** Correlation is the washout objective's whole mechanism (entries
fail TOGETHER through shared factors), the sim gate's joint-structure
requirement, and — free side effect — the first empirical grading of
MLB_Classic's stack-shape beliefs (4-2 vs 5-x carry assumptions this table
confirms or reprices).

**Fix.** One mining pass; a small table in the ledger's calibration
section (team factor, slot-distance decay, game factor); feeds R259's
buckets and R261's sampler.

**Rider 2026-08-28 (ed9 §1.3/§5.1, accepted into the same mining pass).**
The table gains the row the washout math needs most and the filing lacked:
pitcher↔opposing-hitter NEGATIVE dependence — no lineup holds both sides
of a game, but a portfolio does, across entries. And the cells gain
honesty guards: shrinkage toward the pooled factor plus a block-bootstrap
SE per cell, blocks by slate DATE — ~26 dates is the effective n, not
5,926 rows, and a sparse cell must read as a prior, not a fact.

### R261. The own-portfolio scenario bank: predict P(top-1%) and P(washout) pre-lock, grade at archive time, steer nothing until graded (P1, M-L; gated only by its own inputs R258–R260) | new 2026-08-27, from Ben's greenfield instruction; designed inside the sim gate's clauses, not around them

**What.** Sample joint player outcomes (R259 marginals, R260 team/game
factors), score OUR candidates only, and emit two pre-lock predictions per
delivery: per-entry P̂(score ≥ its contest's R258 threshold) and portfolio
P̂(no entry clears its floor). Grade both in the ledger every archived slate
(predicted vs realized frequency, n stated). NOT a field simulator: no
opponent lineups, no ROI, no prize-share claims — those stay behind R10
(dupes/ownership) and R13. The gate's fourth clause is designed in from
birth: selection and grading run on separate seeded banks, and all own
entries in one contest settle jointly.

**Why.** This is the direct computation of both quantities Ben named, at a
tenth the cost of the spec's field-simulation program, and gradeable
immediately because the archive supplies the answer key every night. The
Showdown degenerate case is nearly free — one game collapses the scenario
space to the script grid the thesis ladder already enumerates — so R257
delivers the format's washout half while this item is still being built.

**Fix.** `scenario_bank` module + two brief fields, both labeled
predictions-under-grading; ledger gains the rolling calibration table. The
day its grades are adequate is the day R262 becomes decidable.

**Riders 2026-08-28 (ed9 §§4.2/4.5/5.2/5.3/8.6, accepted; one clause
modified).** (a) One draw = one SLATE: every contest and every entry on
the slate settles against the same scenario outcome — the filed
joint-settlement clause extends slate-wide, because two contests on one
slate are not independent bets. (b) Every P̂ ships with its Monte Carlo
standard error and effective sample size — truthful labels applied to
sampling noise — and the bank expands adaptively only when that error
could change a decision. (c) Bank purposes are DESIGN / SELECT / REFEREE
(development, frozen selection, untouched grading): one seed more than the
filed two-bank clause, same sim-gate-clause-4 discipline, REFEREE
untouched until a decision is frozen. (d) The threshold is consumed as
R258's `T[s,c]` inside each scenario, never as one frozen point. (e)
Stratify by run environment — by script for Showdown — with likelihood
weights retained so estimates stay unbiased; importance sampling beyond
that has a named pull condition: an MC error that binds a decision at a
bank size the budget cannot grow. (f) Implementation notes, adopted:
scenario×player array with a sparse lineup-incidence matmul for scoring;
bit-packed top/floor hit vectors; Showdown CPT and UTIL incidence share
ONE person-outcome with the 1.5x applied exactly once at the captain
seat — also a double-count guard. (g) The archive-time grade reports
realized washout three ways — literal zero-return, near-total net loss
(dollars from `own_results`, promo channel named as unmeasured per the
ledger's own caveat), no-floor-hit — while the PREDICTED quantity stays
Ben's: P(no entry clears its floor). (h) Showdown: when this bank grades,
the thesis weights at `showdown_theses.py:273-277` become measured script
frequencies; the hand values remain attribution labels, which is all they
ever were.

### R262. Scenario-coverage selection: the dual objective as one solve (P1, L; PRODUCTION SWITCH GATED — Tier 4 decision, interacts with R13) | new 2026-08-27, from Ben's greenfield instruction

**What.** With R261's hit matrix (candidate × scenario indicators for
clearing the top threshold and the floor), portfolio assembly becomes:
maximize scenarios where ≥1 entry clears the TOP line (apex end), plus a
weighted term for scenarios where ≥1 entry clears its FLOOR (anti-washout),
subject to the existing legality and cap guardrails — a set-cover-shaped
MILP `scipy.optimize.milp` expresses directly. Selection then optimizes
Ben's two stated quantities instead of Ceiling-proxy points, and R247's
finding becomes structural: coverage replaces flat caps as the washout
mechanism, caps remain as guardrails.

**Why.** Exposure caps are crude covariance controls (R247 measured them
demoting the four best players); coverage is the actual objective. Kept
LAST deliberately: it changes what gets built, so it lands only after
R261's predictions grade adequately across a stated number of slates AND
Ben flips the switch (Tier 4; the R13 stakes decision reads the same
grades).

**Amended 2026-08-28 (ed9 §4.4, accepted; the weighted sum in the What
above is replaced).** An arbitrary apex-vs-floor weight has no units and
can flip the portfolio on an opaque change — the failure the dual
objective's "one frontier, not two maxima" sentence exists to prevent. The
solve becomes epsilon-constraint: maximize apex coverage subject to
floor-coverage ≥ bound (equivalently minimize washout subject to
per-contest apex retention ≥ ρ), sweep the bound over a small grid, and
emit the nondominated frontier — per-contest `A*_c` (that contest's
standalone best achievable), retention `R_c = A_c/A*_c`, the three washout
readings, and which guardrail binds with its coverage cost (R247's
finding, made structural). Same `scipy.optimize.milp`, same gates, same
Tier 4 switch: Ben picks the operating point from the frontier once, as
policy, never mid-run per slate. Two guards from the same section: an
`A*_c` of zero on the REFEREE bank is never divided by — that contest
reads UNKNOWN and probability-based selection for it is blocked; and
max-min retention (maximize the minimum `R_c`) is the named alternative
when one contest's retention must not buy another's. Stage 2, only after
the base solve grades: coverage-driven column generation — a high-weight
scenario no candidate covers becomes an ask to the bank generator for a
legal lineup that covers it — the candidate-bank contract extended, not
replaced.

### R263, remainder. The Showdown captain/split HARD bands and the satellite chalk floor (P1, gated on R238/R239 and on R10) | filed 2026-08-28; decision answered and shadow build SHIPPED the same day

- **What.** Three measured mismatches between what we deliver into satellites
  and what their top cohorts look like, none owned elsewhere as a DECISION:
  (1) our satellite entries run chalk-NEGATIVE cumulative ownership (−7.6pp
  disc → −21.4pp val Classic; −4.0 → −10.8 SD, vs each contest's own field
  mean) while satellite top cohorts are chalk-POSITIVE in both halves (+16.0/
  +10.0 Classic top-decile; SD winners +4.3/+8.2) and the fields themselves
  drifted 20-44pp chalkier over the season; (2) our SD pitcher-CPT share is
  40% against 65.5% of winners (field 46.0), replicated in both halves;
  (3) our SD 5-1 team-split share is 73.4%, above even the top-1% cohort's
  50.2% — the one axis where we are OVER-concentrated. Classic five-man share
  is R37(2)'s and stays there; this item cites 3.21 as that gate's evidence
  and does not re-own it.
- ~~**The decision owed (Ben).**~~ **ANSWERED 2026-08-28.** Ben's dated
  instruction adopted the three bands as SHADOW bands and deferred all three as
  HARD bands to the R238/R239 contest-awareness cluster, on R153's ground that a
  cap enforced anywhere other than where roster spots are spent is not a cap. The
  satellite chalk-stance band is separately deferred to the R10 fit. The
  `Decided` entry is in CHANGELOG.md.
- ~~**The build (S, after the decision).**~~ **SHIPPED 2026-08-28**, text
  MIGRATED to CHANGELOG.md. `showdown_theses.construction_shadow` prints
  pitcher-CPT share, the team-split mix as canonical pattern strings, and the
  three-band check into `brief["construction_shadow"]`, between the two exposure
  caps and the diversity block, on every Showdown delivery. Counted off solved
  lineups, `steers: False` in the artifact.
- **What the shipped shadow added that this item did not ask for, and which the
  hard-band half now has to reckon with: `pitcher_cpt_ceiling_pct`.** On a slate
  with two declared arms, pitcher-CPT share cannot exceed
  `2 * floor(cpt_cap * n) / n`, because the captain cap is per PLAYER and only
  two players are eligible for that slot. At the shipped 0.25 cap that is 42.1%
  at n=19, 36.4% at n=11, 50.0% at n=20, averaging **45.0%** over n=9..24. **So
  the proposed 48-52% hard band is above the reachable maximum at most entry
  counts and cannot be adopted as written.** Whoever picks this up owes one of
  three things, not a band: condition the band on n, raise `max_cpt_exposure_pct`
  (Ben's, and a washout-axis change R153 built the cap to prevent), or change the
  order in which the ladder spends captain slots across the two arms. That last
  one is the cheap one and it is diagnosed: `win_big`, `win_close` and
  `ace_loses` all lead their `cpt_ladder` with the SAME arm, so pitcher-captain
  demand piles onto one capped player instead of spreading across two.
- **The coarse weight lever is SPENT, measured 2026-08-28.** Ben asked for a
  thesis-weight bump to move the delivered share ~40% -> ~50% on R156's
  precedent. Built and measured over 96 apportion-and-solve checks (six
  moneylines x n=9..24 on the tracked MIN@CHC fixture, R156's own standard), then
  DECLINED: mean realized share 43.66% -> 44.91%, mean ceiling 45.01% unchanged,
  builds at ceiling 75/96 -> 94/96, captain-cap relaxations **37 -> 56**. Four
  alternative weight sets were searched and all were worse. Do not re-run this
  search; the numbers and the reasoning are in the changelog entry and the
  declined weights are recorded in a comment at the site. Reversing it is a
  five-number edit if a later measurement changes the picture.
- **Review checkpoint and revert condition (Ben, 2026-08-28).** The shadow bands
  grade as FINISH COHORTS over **~12 conditioned slates** before any band
  tightens or goes hard, conditioned on family x field-size bucket x slate size
  and never pooled (the root doc's promotion gate, adopted as written). The
  shadow itself has no revert condition, because it steers nothing: the thing
  that can go wrong with it is being READ as a gate, which `steers: False` and
  `band_reachable` are there to prevent. The 5-1 band is the one to watch on the
  real population -- our delivered 73.4% is above even the top-1% cohort's 50.2%,
  and the fixture reads 89.5%, so expect `above_band` on nearly every delivery
  until something steers.
- **Why.** The dual objective binds washout at the PORTFOLIO level; 73% on one
  team split is the correlated-failure shape R153's caps were built against
  arriving through construction rather than exposure, and the chalk-stance gap
  is the compounding kind — it widened exactly while the fields moved the
  other way. Observed cohort shares and deterministic review proxies
  throughout; never a probability claim.

## Workstream 3 — Intake and pool truth

The pool is the strategy surface the contract defends hardest. R60 CLOSED
2026-08-12; **R133 CLOSED 2026-08-18** and its entry moved to CHANGELOG.md, so
this stream has no open P1 again. R133 was the partial-side remainder R60 did not
close, filed from a fragment this board twice recorded as consumed by R60 and
which was in fact a report of a defect in what R60 shipped. Its remainder is (2),
the equal-weight seeded ninth, which is a SELECTION question filed to
MLB_Classic.md rather than carried here — and note precisely, because this board
has been imprecise about it: R60's deferral covered F2-from-a-posted-slot only,
so the equal-weight question has never actually been asked of anyone. What R60 leaves behind is the
partial-side rule now written into the build contract, which is the thing to
check a new intake path against. R81 is the armed design pass that retires a
whole wrong-slate family; R82's unknown-code report and R90's fixtures are its
supporting pieces. R17 and R106 are contest-truth edges of the same boundary. R108 is
the same shape as R82 one vocabulary over — a second reader of DK's `Starting`
tokens, held in sync by a test pin rather than a single definition — and the
two are the natural pair for one session.

### R81. Slate fingerprint contract at every intake boundary (prevention, M; design pass first) | audit 2026-08-04

Derive `{game_id -> ET start, slate_date}` from the salary CSV once, embed it in every artifact the intake layer writes (paste feed, bundle, odds packet, staged kwargs), and have `build_slate_pool` verify artifact-vs-salary fingerprints before use. One mechanism retires a whole family: the wrong-date paste (a same-series stale paste currently resolves cleanly because the only cross-check compares clock hour/minute, `paste_lineups.py:809`, and pastes carry no date), the yesterday's-bundle class, the mixed-draftgroup staging class (R70a), and the DH-collision class (R58). Schedule the design pass when any two of R58/R59/R70 have landed individually — the right shape will be visible by then. **All three have now landed (2026-08-14), so the trigger is fully satisfied and every input this entry named is in hand.**

**Note 2026-08-05 (DEV):** R59 has landed, and R58(a)(b) landed the same day, so the trigger is SATISFIED (two of three) and the design pass is armed. Its shape is already informative for this item: the failure was a same-game pair keyed under two vocabularies surviving as two games, and the fix was normalizing the key at the merge — a fingerprint would have caught it at a different layer, by noticing the artifact did not match the salary file's game set. R65 also landed and moved the ET calendar to one authority (`repo_env.today_et`/`et_day_offsets`), which is a prerequisite this entry's `{game_id -> ET start, slate_date}` derivation can now build on instead of re-deriving. R58's remainder is (c)(d) only, both repriced P2. What R58(a) adds for this item specifically: the fix had to derive a per-leg start from the salary DATE plus the paste's own clock, because the salary file is keyed on AWAY@HOME and cannot name a leg. A slate fingerprint that carried {game_id -> ET start} per LEG would have made that derivation unnecessary, which is a concrete requirement for the design pass rather than a general argument for one.

**Note 2026-08-14 (DEV), what R70 hands this entry:** R70(a) closed the mixed-draftgroup class by REFUSING to choose — more than one file matching an intake role blocks with the named candidate list and four flags resolve it. That is the right patch and it is deliberately not the design. A fingerprint is what would let the tool CHOOSE correctly instead of asking: the entries file names its contests, the salary file's game set and ET starts identify the draftgroup, and the two either agree or they do not. So the upgrade path is specific — keep R70's block as the failure mode, and let the fingerprint reduce how often it fires rather than replacing it, because "these two DK files are not the same slate" must still be a refusal and not a repair. R70 also priced the operator channel: any fingerprint that can reject a pairing needs a way for Ben to overrule it at T-10, or it becomes the flag he learns to force past. And it left one concrete gap for this entry to close, filed rather than patched because it is the design question: R70's block makes the operator name salary and entries INDEPENDENTLY, and nothing at stage time checks the two are the same draftgroup — which is exactly how 2026-08-13's cross-draftgroup pair (`DKSalaries_2207_2g.csv` + `DKEntries_1507_3g.csv`) was produced. `preflight_upload` catches it at the end; the checkpoint door should catch it at the start, and a fingerprint is the thing that can. Related and cheap either way: ambiguity is reported one role at a time, so a two-role dir costs two round trips at T-10.

### R82. One team-code boundary with an unknown-code report (S) | audit 2026-08-04

Route every inbound abbrev through `to_dk_abbrev` at parse time (merge_feeds, RotoWire, odds, paste) and validate results against the canonical 30-team DK set, reporting unknowns at fetch time. Today an unmapped vocabulary degrades to "filled 0 hitters" or "absent from the platoon reference" long after the fetch. Companion to R59; kills the class, not the instance.

**Note 2026-08-05 (DEV):** the BOUNDARY half landed with R59. `mlb_engine/team_codes.py` now holds `DK_ABBREV_REMAP`, `MLB_TEAM_NAME_TO_DK`, `to_dk_abbrev` and `team_name_to_dk_abbrev`; `live_data_adapters` re-exports all four so no caller changed, and the module is network-free on purpose (see that CHANGELOG entry: importing the adapters module for the normalizer pulled `urllib.request` into `lineups_from_paste`, whose zero-network contract is pinned by test). It carries a VERSION and an audit pin, which also closes its share of R76(e). What remains, and is still the item: the UNKNOWN-code report. A code that fails to normalize passes through unchanged and silently matches nothing downstream — the WSH 0-of-9 failure — and the natural place for the report is now this module rather than each ingest boundary.

### R108. One DK `Starting` token boundary, the `team_codes` treatment (P2, S) | new 2026-08-10, deferred out of R104's scope note

- **What:** DK's `Starting` column vocabulary is parsed in two modules. `mlb_engine/intake/live_data_adapters.py` owns the Classic reading (`DK_STARTING_OPENER_TOKENS`, `DK_STARTING_LONG_RELIEVER_TOKENS`, `BARRED_OPENER_ROLE`) and `mlb_engine/optimize/showdown.py` owns the Showdown reading (`DK_STARTING_OPENER_TOKENS`, `DK_STARTING_DECLARED_TOKENS`). R104 landed the POLICY on both sides and replaced the two tuple literals with named constants pinned in sync by test, which is the interim this repo already uses for preflight's mirrored `STATUS_VALUES`. It did not merge them.
- **Why P2, not higher:** the divergence that caused R104 is closed and a test now fails if either set moves alone, so this is prevention of a recurrence rather than a live defect. It is filed because "two readers of one vocabulary" is this project's named no-op class and a pinned mirror is a weaker guarantee than a single definition — the pin catches a changed constant, not a third reader that never imports either.
- **Fix:** the R59/R82 treatment. A leaf module (`mlb_engine/dk_tokens.py` or equivalent) holding the token sets and the role names, imported by both readers, network-free and import-graph-free for the same reason `mlb_engine/team_codes.py` is — `tools/lineups_from_paste.py` carries a pinned zero-network contract and must be able to reach the vocabulary without pulling `urllib` in behind it. Carry a VERSION and an audit pin, as team_codes does. Note that adding a module moves the audit's filesystem-derived module count off 26, so the CLAUDE.md session-start line and `skills/generate-lineups/SKILL.md` move in the same commit; that cost is why it was deferred out of a four-item batch rather than done inside one. Done when one module defines every DK `Starting` token, both readers import it, and the R104 sync-pin test is replaced by an identity assertion rather than an equality one.
- **Explicitly NOT this item:** the GF spec's F-21 typed-role apparatus (`role_confidence`, `expected_batters_faced`, workload models) stays rejected, on the same grounds R104 rejected it — that is Finding 15's projection stack, gated on R13.

### R58(c)(d). Doubleheader legs, remainder: RotoWire per-leg orders and the same-venue weather window (P2, S each) | audit 2026-08-04; (a) and (b) landed 2026-08-05

- **(a) and (b) LANDED 2026-08-05** and their full What/Why/Fix plus the landing record moved to CHANGELOG.md per the backlog contract. In short: the paste path now derives a per-leg start from the salary DATE plus each pasted leg's own clock (single-leg games keep the salary start verbatim), blocks a matchup whose legs cannot be told apart by clock, and names the priced leg instead of firing a wrong-slate warning on the other one; and the three team-keyed extractors (`extract_opposing_probables`, `extract_batter_hands`, `extract_opp_throws_from_lineups`) route through one `_legs_for_extraction` so they leg-select exactly as the status map already did. A dropped leg's reason also stopped describing the kept leg.
- **What remains, (c):** `platoon_order_adapter.build_projected_order` writes `{Player_ID: slot}` while iterating `platoon["teams"]`, so a DH team listed twice has its first leg's order overwritten by the second. The filed fix is "key per-leg orders by (team, clock)" and the RotoWire schema carries NO clock: `to_platoon_schema` emits `abbrev`, `status`, `page_updated`, `vs_RHP`, `vs_LHP`. So this needs the regex parser to capture a per-game clock, a widened emitted schema, and a consumer change.
- **Why (c) is blocked rather than just unbuilt:** that parser is regex over live third-party HTML with no frozen real-page fixture (R65 shipped the parse FLOOR but declined the fixture; it sits on R90 with the hand step named). Changing its extraction surface without a fixture of the page it parses is how a silent-empty regression ships, and silent-empty is the exact failure R65's floor exists to catch. Do (c) after R90's RotoWire fixture, or accept the risk deliberately.
- **What remains, (d):** `fetch_slate_bundle.py:278` — the second same-venue game reuses the first leg's weather window, unmarked. Independent surface, no interaction with (a) or (b). Carries a small decision: give the second leg its own window, or widen the first leg's window to the latest same-venue start (the filed fix says the latter). Either way, mark it rather than leaving the reuse silent.
- **Scope of the remainder:** both affect a doubleheader slate only, and neither is in the wrong-lineup-reaches-the-pool class (a) and (b) were, which is why the priority drops from P1 to P2. (c) degrades a TBD team's projected order on a DH; (d) degrades one game's weather input.

### R270. The doubleheader leg matcher exists on the odds path and not on the lineups path, and after first pitch the feed's "confirmed" silently becomes "not posted" (P1, S-M; two independent halves) | new 2026-08-29, merged from BUILD fragment `2026-08-29_BUILD_late-swap-repair-gaps-and-autonomy.md` §D; field-forced on slate `1305_12g`, both halves observed

**(a) One rule, two implementations, and only one of them exists.**
`schedule?...&hydrate=lineups,probablePitcher` returns BOTH legs of a split
doubleheader. Iterating without filtering leaves the LATER leg in the dict. On
`1305_12g` BOS@NYY and ARI@SF were both splits (`gameNumber == 1`,
`doubleHeader == 'S'` for the DK slate in both cases) and the first sweep
reported BOS, NYY, ARI and SF as having ZERO starters. **That reads exactly like
"these teams have not posted" and is indistinguishable from it downstream** —
the same conflation R237 is filed on, arriving through the leg filter instead of
the factor report. The odds path already solves this, benignly, on the same
slate: F1 reported "2 doubleheader odds leg(s) dropped" for these same two
games, matching the salary file's start time to within 10 minutes. **The
lineups path should use that matcher.** Per R233, the landing entry carries the
grep enumerating every reader that iterates the hydrated schedule without a leg
filter. Cross-ref R221 (the DK merge stamps the slate leg's order onto every
feed leg — the same seam, the write side) and R58(c) (per-leg orders, blocked
on R90's fixture); R221 and this are the two sides of one boundary and should
be read together even if they land apart.

**(b) The pool contract has no post-first-pitch source, and this one is new.**
Once a game is in progress the schedule hydrate stops carrying its lineup, so a
"confirmed" check against the feed **silently degrades to "not posted" for
exactly the games whose answer is now certain.** The authoritative source after
first pitch is the boxscore:

    https://statsapi.mlb.com/api/v1.1/game/<gamePk>/feed/live
      -> liveData.boxscore.teams.<side>.battingOrder   (who actually hit)
      -> liveData.boxscore.teams.<side>.pitchers[0]    (who actually started)

This is what found the one genuinely dead player left in the delivered file
(Nootbaar, 1 entry) while `preflight_upload.py` was still reporting that side as
unposted from the feed. It is the observed-fact source for late swap and for the
preflight's feed check, and it belongs in the intake contract's source ranking
beside R143's DK-then-paste-then-API line, as the tier that outranks all three
once the game is underway.

**One implementation note that already cost a pass.** Names need
accent-normalising to join to the DK salary file (`Acuña/Acuna`, `Díaz/Diaz`,
`Peña/Pena`, `Rodríguez/Rodriguez`, `Pérez/Perez`, `Dubón/Dubon`); a first pass
without it produced eight false positives. `preflight_upload.py` already
normalises correctly — `unicodedata.normalize("NFKD")` plus combining-mark strip
at lines 181-182 — so the logic exists and is to be SHARED, not reimplemented.
Reimplementing it is how the R248 crosswalk got two copies.

### R75. The DK↔Savant crosswalk joins on normalized name only; same-name players collapse to one row (P2, S) | audit 2026-08-04, verified in tree

- **What:** `xwoba_base_correction.py:144` resolves mlbam by normalized name — suffixes stripped, highest-PA row wins, team read but never used: both Luis Garcías receive the same correction and ceiling multiplier, and when only one is in the Savant table no collision is even reported. Impact bounded by the clip bands (0.85–1.15 / 1.25–1.60) but systematic and silent.
- **Fix:** flag DK-side duplicate normalized names in the match report; disambiguate by team when the pool holds two.

### R90. Frozen-fixture and property-based intake tests (S-M) | audit 2026-08-04

Hypothesis-generated mlb.com renders (random posted-side subsets, `1. TBD` placeholders, missing pitcher lines, repeated headers) asserting the invariant "every attached nine belongs to the header block that posted it, else nothing attaches" — the R32 class, currently pinned to two hand-frozen renders. Plus the RotoWire frozen-HTML fixture with a ≥24-team parse floor (rides R65).

**Note 2026-08-05 (DEV):** the RotoWire half no longer rides R65 — R65 landed without it and this item now owns it outright. R65 shipped the parse FLOOR (`check_parse_floor`, two structural collapse signals, `--min-teams` knob) and its report wiring, pinned with a page built from the module's own regex constants. What is still missing is a frozen REAL page, and it is not obtainable from a Cowork session: the web-fetch tool returns markdown and this parser is regex over raw HTML, while the alternate fetch paths that would return raw bytes are closed by policy. It needs one hand step outside Cowork — save `https://www.rotowire.com/baseball/daily-lineups.php` as raw HTML into `tests/fixtures/` — after which the parser can be pinned against the layout it actually parses. Also note R65 declined the ≥24-team absolute floor this entry still names; see that CHANGELOG entry for why (it refuses correct parses before lineups post and on light schedule days). Same class as the `mlb-game-odds` key residual on the Do-not-build list: blocked on a hand step, not on a decision. **R58(c) now waits on this fixture too** (noted 2026-08-05): keying RotoWire's per-leg orders by (team, clock) means teaching this parser to capture a clock it does not read today, and changing its extraction surface without a fixture of the page it parses is the silent-empty regression R65's floor exists to catch.

### R17. `contest_library` strips the ` SE` guard space, and has no production caller (P2, S) | new 2026-07-27, found by this session's adversarial pass

- **What:** `mlb_engine/field/contest_library.py:116` does `pattern = str(r.get("pattern") or "").strip()` when loading the archetype CSV, and `infer_from_name` at `:156` matches with `r["pattern"].lower() in low`. The ` SE` row's leading space is the guard against substring false positives, and its own `notes` cell says so in words: "prevents false-positive matches on titles containing USE, POSE, or similar substrings." Stripped, the pattern is `SE` and it matches any title containing those two letters. Verified live: `infer_from_name("MLB $5 Baseball Bonanza [20 Entry Max]", rows)` returns `inferred_type='se_gpp'`, `inferred_max_entries=1`, `payout_breadth=0.01`, on the strength of the "se" in "Baseball". `dk_entries_manager.load_archetypes` preserves the space correctly, so the two readers of one file disagree.
- **Why it is P2 and not P1:** the module has no production caller. `contest_library` is referenced only by itself and by `tests/test_core.py`, so the wrong tier is currently unreachable from a build. That is also the second half of the finding and arguably the larger one: this is a third zero-caller surface of the same kind R15 just closed, and R1a's payout-breadth work happened in `execution_pipeline` while an independent breadth reader sat here.
- **Fix:** decide the module first, wire or delete, and only then fix the strip. If it is wired, the strip becomes a live defect and the fix is to preserve the pattern exactly as curated and match on the raw string, with a test using a title that contains "se" inside an ordinary word. If it is deleted, the CSV keeps one reader and the disagreement cannot recur. Do not fix the strip alone: that leaves a corrected reader nothing calls.
- **Note 2026-08-04 (audit):** a second confirmed divergence in the same module. `infer_from_name` ranks matches confidence-then-length with no `ARCHETYPE_TYPE_PRECEDENCE` (`contest_library.py:161`), so "MLB $4 Single Entry Satellite to the Chin Music [1 Ticket]" resolves `se_gpp` (breadth 0.01) where `dk_entries_manager.infer_contest_archetype` resolves Satellite — the exact trap the `dk_entries_manager.py:387` comment fixed, reproduced live. The paste-ready waterfall would tier a satellite A instead of F/V. Strengthens the wire-or-delete decision; whichever way it goes, the precedence import rides the same commit as the strip fix.

### R106. `build_slate.py --postures` cannot express ticket_count, so the operator's deciding fact cannot reach the resolver (P2, S) | new 2026-08-10, from BUILD fragment 2026-08-08 (1505_3g); not in the spec

- **What:** `--postures` takes `<contest>=<posture>` strings only and
  `parse_postures_arg` returns `dict[str, str]`. `satellite_shape_for()`
  routes ticket_count 1 to `wta_ticket_satellite` and anything else to
  `satellite`, and `_resolve_contest_postures` already honours a Mapping
  override with an explicit `contest_shape` — the capability exists; only the
  CLI cannot reach it. Live case 2026-08-08: Ben supplied the ticket
  structure for two satellites (193403851 one ticket, 193403935 five), both
  resolved `satellite`/ticket_line, wrong for the one-ticket Relay Throw,
  which is a first-place path. Workaround was a per-slate `drive_build.py`
  driver importing `build_slate` and replacing `parse_postures_arg` — legal
  (BUILD write set) but a driver script per slate is the tool teaching the
  operator to bypass it.
- **Fix:** let `--postures` accept a JSON object, or add `--postures-file
  <path>`, so a ticket count reaches the resolver without a driver. The
  archetypes CSV is not the home: it is keyed by name pattern and ticket
  counts vary between instances of the same family (the 2026-08-09 curated
  table shows Pocket Cup at 1, 5, and 10), so the per-slate operator channel
  is correct. Feeds R40's evidence trail (the brief already records
  `operator_supplied` routing). The fragment's second item (minimum-feasible
  relaxation hint) was folded into R98's remainder, not here.

### R159 + R160. CLOSED 2026-08-24 -- intake truth on the no-fetch path, entries migrated to CHANGELOG.md

Both landed together because they are one surface and one session.
R159's four halves: coverage and the merge now read ONE input (`dk_side_readings`), a shelved player inside a posted 1-9 makes the side
DEGRADED rather than invisible and its surviving eight are seeded as a partial
through R60's path, the merged probable carries a NAME so `extract_opposing_probables` can see it, every team DK declares an arm for gets
one (not only teams with a complete order), and `f4_handedness_partial` reports
hands present per side instead of firing only when a side loses all nine.
R160: a game whose salary Game Info parses as a matchup but not a time is no
longer synthesized, `_parse_utc` is guarded at the status-map read as well, and
the blocker names the cause rather than the "no probable" consequence.
**Numbers reserved; the record is the 2026-08-24 CHANGELOG entry.**

### R161. Two R65-class clock residues: slate_date falls back to the UTC clock, and the bundle's display time hardcodes UTC-4 (P2, XS) | new 2026-08-22, from the greenfield sixth edition; VERIFIED-read at ec832cf

- **What:** (a) `build_slate_pool` derives `slate_date` from
  `datetime.now(timezone.utc).date()` when the feed is empty or date-less
  (`live_data_adapters.py:1099-1100`) — routine on the R143 no-fetch path —
  so after 8pm ET the platoon file ages one extra day (can tip the 7-day
  block) and `pool_report.slate_date` records tomorrow. The repo owns the
  right pattern in `ownership_pred.slate_date_from_salary`. (b)
  `fetch_slate_bundle.py:151-154` hardcodes UTC-4 for `game_time_et` and uses
  `%-I` (throws on Windows, swallowed) — display-only, silently blank on
  Ben's machine.
- **Fix:** (a) salary Game Info date first, feed date second, `repo_env`
  ET-today last. (b) `repo_env` ET conversion plus `%I`-lstrip.
- **(b) re-confirmed 2026-08-23** while landing R190 in the same function:
  `fetch_slate_bundle.py:152` still reads `(utc_dt - timedelta(hours=4))`. R190
  deliberately did not touch it — a clock fix inside a handedness fix is two
  changes in one commit — so (b) stays exactly as filed, one line, with the
  file already open next time.

### R162. A FanGraphs pitching CSV with neither TBF nor IP silently neutralizes every arm (P2, XS) | new 2026-08-22, from the greenfield sixth edition; PLAUSIBLE (read only — verify by repro before fixing)

- **What:** `load_fangraphs_pitching` requires only Name plus one K-rate
  column; `_tbf` then derives from an absent column (all-NaN after index
  misalignment), `qualified` goes empty, and every multiplier lands neutral
  with no error — a truncated manual export silently turns the feature off.
  The refresh tool's schema floor only covers files it fetched, and FanGraphs
  is manual by decision.
- **Fix:** raise (mirroring the K-rate guard) or report `qualified=0` loudly.

### R264. Three independent American-odds -> probability implementations, on a rule R205 has just made load-bearing (P2, XS) | new 2026-08-28, found while landing R205; VERIFIED by grep, no field incident

**What.** The conversion from an American price to an implied probability, and
the two-way normalization on top of it, exist three times:

```
$ grep -rn "def .*american.*prob\|def _american_to_prob\|def _no_vig\|def devig_two_way\|def vig_free_probabilities\|def implied_prob_to_american" --include=*.py mlb_engine tools skills
mlb_engine/intake/live_data_adapters.py:2555  american_to_implied_prob
mlb_engine/intake/live_data_adapters.py:2564  vig_free_probabilities
mlb_engine/intake/live_data_adapters.py:2571  implied_prob_to_american
mlb_engine/intake/live_data_adapters.py:2678  _finite_american_to_prob   (wraps the first)
mlb_engine/optimize/showdown_theses.py:126    _no_vig                    (arithmetic inlined)
mlb_engine/projections/projection_builder.py:569  devig_two_way
mlb_engine/projections/projection_builder.py:588  _american_to_prob
```

Three of those are the same four lines written three times:
`american_to_implied_prob`, `projection_builder._american_to_prob`, and the
expression inside `showdown_theses._no_vig`. They agree today, checked.

**Why.** The R159 class -- two components answering one question -- and R205 is
what makes it matter rather than untidy. The packet's moneyline is now a DERIVED
vig-free consensus whose correctness depends on the de-vig being the same
operation at the producer and at both consumers; the whole point of
de-vig-then-average is that the second de-vig downstream is identity, and
identity is a property of two implementations agreeing. Three copies is where
R167's units family started (`_cap_count`, "both copies" that were four).

**Fix.** One owner. `american_to_implied_prob` and `vig_free_probabilities` are
the obvious ones and already sit together, but `live_data_adapters` imports
`urllib.request` at module scope, so a network-free consumer cannot take them
from there -- which is exactly the move `team_codes` made in R59/R82 and the
precedent to follow. Land it with R265, same reasoning, same boundary.

### R219 + R220. CLOSED 2026-08-27 -- the degraded-side merge deferred to any
nonempty feed lineup, and three reports on the same surface named something
other than what was true; entries migrated to CHANGELOG.md

The predicate is now `_side_is_complete` (the order SET equals 1-9, plus the
feed's own `confirmed` label and R32's operator paste at any length), each
`degraded_sides` record carries a `resolution`, and all four of the pool's
blocker loops over an intake report are scoped to the slate. The CHANGELOG
entry of that date carries the R233 enumeration and the one kept sibling.

### R221. The DK merge stamps the slate leg's batting order onto every feed leg of a doubleheader and mints wrong-leg disagreements (P2, S) | new 2026-08-24, from the greenfield seventh edition (GF7-E8) and independently from the outside spec (D08); VERIFIED-read mechanism, PLAUSIBLE occurrence

**What.** `live_data_adapters.py:622-674`. The confirmed-merge loop walks the raw
feed before leg selection; leg selection runs later, in
`build_status_map_from_lineups_feed`. On a DH day, a team-keyed DK order merges
over the OTHER leg's posted lineup and mints `dk_batting_order.disagreements` rows
sourced from a leg the build then drops.

**Why.** The pool outcome is unaffected — the kept leg is correct — but the
operator-facing report is not, and R143 made that report the mechanism by which
DK-vs-paste conflicts reach a human instead of being silently resolved. A
disagreement row from a dropped leg is a fact about nothing. Ed6 filed a DH-merge
finding that was dropped at landing as overtaken by `_select_slate_legs`; this is
the narrower mechanism that survives, at the merge stage, upstream of the
selection that closed the ed6 version.

**Fix.** Leg-select against `_salary_game_times` before the merge loops, or
suppress disagreement and upgrade rows for legs whose start time does not match
the salary time. The outside spec's `choose_event` (D08) raises on an ambiguous
leg; that is stricter than this repo wants at the merge — an ambiguous leg is
already handled downstream — so take the suppression, not the raise.

### R222. The Savant name-join discards its collision report, so a colliding probable takes the other pitcher's quality silently (P2, XS) | new 2026-08-24, from the greenfield seventh edition (GF7-E9) and independently from the outside spec (D10); VERIFIED-read at `projection_builder.py:892`

**What.** `sp_id_by_name, _ = _build_name_to_mlbam(table, sp_row_by_id)`. The
helper returns collision counts for exactly this purpose and the caller throws
them away. An id-less probable whose normalized name collides in the Savant
pitching table resolves to one MLBAM row by the highest-PA rule, with no warning,
while the xwOBA and xISO joins on the same table DO report their collisions.

**Why.** R189(2) added this join precisely because DK ships no MLBAM id, so the
join now carries every DK-declared probable and every plain-text paste slate —
which is to say the collision path is no longer rare. The whole point of R189(2)
was that an unrecoverable probable is NAMED rather than scored neutral in silence;
a recoverable-but-ambiguous one is a third state and it currently reads as clean.

**Fix.** Keep the second return. Mark joined collisions in
`sp_quality_name_joined`, or route them to `sp_quality_unavailable` with reason
`ambiguous_savant_name` and drop them from the map. Identity ambiguity is
CONFLICTED, not a highest-PA fact.

### R229. Two slate-intake silences: a wind-band seam threads to no band while `wind_applies` is True, and the slate clock drops unparseable rows uncounted (P2, XS) | new 2026-08-24, from the greenfield seventh edition (GF7-S4, GF7-S5) and independently from the outside spec (D28, D27); VERIFIED-read. **Severity note 2026-08-27 (ed8 F-24, accepted):** the (b) half is not only a count — a clock that reads "available" while one game's lock is unparseable can authorize a late-swap edit against an unknown lock, so the fix is a per-game state and an incomplete clock reads UNKNOWN for swap-authority purposes, not merely "the games it managed to read." Still lands with R121, unchanged.

**What.** (a) `slate_intake_manager.py:1455`, `:1496-1500`. The wind bands are
closed intervals read from `data/reference/f5_weather_adjustments.csv`, so the
seams (12.999-13.0, 17.999-18.0) and any sub-8 value from a caller with a lower
threshold return `""` and silently no-op while `wind_applies` was True. A
reference-table gap becomes a neutral factor instead of a named defect. (b)
`:1686-1687`. `slate_clock` drops rows whose `Game Info` will not parse and emits
no `unparsed_game_info_rows` count, so a partial clock reports fewer games than
the salary file carries — and a malformed EARLIER lock makes the delivery deadline
read late.

**Why.** (b) rides R121 and is the same defect R121 exists for: the clock is a
measurement, and a measurement that silently covers a subset is an estimate
wearing a measurement's label. (a) is small but it is a reference-data defect that
can only ever present as "F5 did nothing".

**Fix.** (a) Contiguous half-open bands with a validation pass at load
(`low <= speed < high`, adjacency asserted), or a named `no_band` note carried to
the report. (b) Count and name the unparsed rows; any incomplete clock says so
rather than answering with the games it managed to read. (b) lands with R121.

### R236(b). The odds paste tool reads its own long table, not a raw Action Network capture (P2, S) | REWRITTEN 2026-08-28 to hold only the remainder; the tool, its refusals, and the SKILL.md lines LANDED that date and are migrated to CHANGELOG.md

**What.** `tools/odds_from_paste.py` and `mlb_engine/intake/paste_odds.py` ship
and are the supported fallback when the odds API is proxy-gated. What they
accept is the tool's OWN format -- a delimiter-tolerant, header-driven table,
one row per game per book -- so an operator reading
`https://www.actionnetwork.com/mlb/odds` transcribes the page's rows into it
rather than pasting the page. Transcription is where a hand error lives, and the
per-book columns bound it (nothing is averaged, and every price is attributed),
but they do not remove it.

**Why it stopped here.** A parser for a pasted format has to be pinned against
the format as it really arrives -- that is R32's founding rule for this suite,
not a preference, and the failure mode is not an exception but a plausible-looking
number attached to the wrong game. The real captured table text is not on disk:
the fragment recorded four browser facts about the page and the artifact it left
(`data/slates/2026-08-24/odds_actionnetwork_1940_7g.json`) is a hand-built v4
payload, not the page text. Writing a parser for a format nobody can show it is
the fabrication CLAUDE.md forbids, so the tool's fixture
(`tests/fixtures/paste/odds_table_2026-07-30_1910_6g.txt`) says CONSTRUCTED in
its own first line and its prices are not a record of any book.

**Fix.** Capture one real Action Network odds table as text (Chrome, not
`web_fetch` -- the page is client-rendered; the market selector is the SECOND
`<select>` and needs the native value setter plus a bubbling `change` event, then
~3s; `__NEXT_DATA__` carries no prices), commit it as a fixture, and teach
`parse_odds_paste` that shape beside the long table. The slate filter, the leg
stamping, the refusals and the round-trip check are already built and do not
change. **[BEN: one capture, any slate, pasted as text is enough.]**

### R241. `--postures` rejects the canonical shape vocabulary its own authority file defines (P2, XS-S) | new 2026-08-27, merged from BUILD fragment `2026-08-25_BUILD_posture-vocab-and-solo-shot.md` §1; the outside spec's F-47 names the same duplication class

**What.** `contest_shapes.CONTEST_SHAPES` is the closed set CLAUDE.md names as
the vocabulary authority, and `build_slate.py --postures` validates against a
different short list, rejecting `single_entry_gpp` with `valid: cash,
wta_satellite, single_entry, small_gpp, large_gpp, mme`. Reading the authority
file first produced an exit-1 usage error inside a build window.

**Why.** Two spellings of one closed set is the R159 class (two components
answering one question) at the CLI; the cost is a wasted call at exactly the
moment calls are priced. Cross-refs: R210(c) (Showdown `--postures` may be a
silent no-op), R106 (ticket_count expressiveness), both unchanged.

**Fix.** Accept both spellings through one mapping owned beside
`CONTEST_SHAPES`, or have the error name the mapping. Fragment §2 (Solo Shot
Turbo) is recorded on R196 as the family's fourth occurrence, not here.

### R251. Freeze the skill and market inputs per slate, or every slate is grading data lost forever (P1, S-M; the capture half rides the NEXT session that touches a slate) | new 2026-08-27, from Ben's greenfield instruction; the R135 argument applied to inputs; lands with R83, same discipline

**What.** Grading any skill or mispricing signal needs the inputs AS OF LOCK,
and two of three input classes are not captured: the expected-stats reference
tables are mutable latest-files refreshed in place, and the odds exist only
as the build-time packet — `data/odds_history/` holds two files, both July
(measured this session), so "the line moved since DK priced the slate" (R252
component (d)) is currently unmeasurable. The per-slate feed freeze
(`data/slates/<date>/`) already does this correctly for lineups; extend the
same discipline.

**Why.** R135's own argument: the emit step exists so the grade step can. A
backtest on today's season-cumulative Savant file against June slates is
leakage; the leakage-SAFE retrospective path exists (Statcast queries accept
date bounds, so season-to-date as-of any past date is reconstructable) and
should be named in the item so nobody rediscovers or ignores it.

**Fix.** (a) The slate bundle gains dated, hashed copies (or content hashes)
of every reference table enrichment read — R83's hash-bind is this same
discipline, land together. (b) A morning odds capture near salary post,
timestamped, beside the build-time packet; both retained under
`data/slates/<date>/`. (c) The backtest note: date-bounded Statcast pulls
for anything retrospective; forward-going, the snapshots are the record.

### R277. The FanGraphs pitching export is `qual=y`, so every non-qualified starter takes the neutral K-rate default all season, and the staleness warning names a remedy that provably cannot reach him (P1, S) | new 2026-08-30, merged from BUILD fragment `2026-08-30_BUILD_standing-data-driven-qa.md` §B; VERIFIED on disk at this head; **corrects a verified claim already on this board**

**What.** `tools/refresh_reference_data.py:83` builds the FanGraphs pitching URL
as `?pos=all&stats=pit&lg=all&qual=y&type=8`, qualified pitchers only. Counted at
this head: `fangraphs_season_pitching.csv` holds **211** rows;
`expected_stats_pitching.csv` holds **831**. Roughly three quarters of the arms a
slate can hand the engine are structurally absent from the file that supplies the
K-rate side of `Ceiling_Multiplier`, and they take the neutral default instead.

**Measured on `1605_2g`, 2026-08-30.** `Ceiling_Multiplier` off the run's own
`final/projections.csv`, against Savant for the same four arms:

| Arm | Ceiling_Multiplier | Source | Savant xwOBA / xwOBAcon |
|---|---|---|---|
| Zack Wheeler | 1.497 | measured | 0.213 / 0.209 |
| **Yusei Kikuchi** | **1.420** | **neutral default** | 0.294 / 0.267 |
| Jeffrey Springs | 1.381 | measured | 0.273 / 0.255 |
| Chris Bassitt | 1.294 | measured | 0.301 / 0.281 |

The neutral default ranked the one unmeasured arm SECOND of four, above both
measured arms, while Savant places him BETWEEN Springs and Bassitt on contact
suppression, below the arm the multiplier puts him above. His Base is 8.95
against Bassitt's 9.50, so the unmeasured multiplier is the whole of what lifts
his Ceiling to 12.70, the highest of the three non-Wheeler arms. He was rostered
in 4 of 7 entries, tied for most-used. Kikuchi: **0** grep hits in
`fangraphs_season_pitching.csv`, **1** in `expected_stats_pitching.csv`, verified
this session after a same-day Savant refresh. He has faced 165 batters against
Wheeler's 499 and Springs' 527. He is not qualified.

**Why P1, and why this is not the staleness item it was filed as.** The
2026-08-16 DEV merge pass recorded, on this board, that "Dobnak is absent from
all 212 rows of `fangraphs_season_pitching.csv` (file dated 2026-07-16, which is
the 30.2 days the warning reports)." **The absence was verified correctly; the
attribution to staleness was never checked and is wrong for this class.** The
warning prints an export URL ending `&qual=y&type=8` as its remedy, so a fresh
export re-fetches the same qualified subset and adds nobody. This is a STANDING
condition, not an aging file: every non-qualified starter is unmeasured on every
slate for the whole season, and the surface an operator reads under a clock tells
him to fix it by re-downloading. Silently degrading lineup quality while naming
an impossible remedy is the P1 definition twice over.

**Fix.** (a) Decide the source question rather than the URL question first: the
Savant file already carries 831 arms including this one, so the cheapest correct
answer may be to derive the K-rate side from `expected_stats_pitching.csv` and
retire the qualified-only dependency, not to widen the FanGraphs pull. If the
pull is widened instead (`qual=0`), check what downstream assumes qualified rates
before shipping it, because a 30-batter sample and a 500-batter sample are not
the same input. (b) Whatever (a) decides, the warning stops claiming staleness
for an arm that is absent by QUALIFICATION and names the real condition; this
half is R237's typed-state discipline applied to a reason string, and it can ship
alone. (c) Cross-ref R237: a `not_computed` state whose reason reads "not
qualified, structural" is a different fact from one reading "provider failed,"
and this is the first named instance where the difference changes what the
operator should do.

## Workstream 4 — Solver, allocator, swap, and brief truth

The R51/R92 family lives here: reports that are honest line by line while
the composite steers wrong. R98's remainder is the P1. R36's Finding 10
(prefilter starvation) belongs to this stream and lives inside the R36
entry in Workstream 5; its re-measure is owed on the next live pinned-entry
swap.

### R207. The infeasibility hint names the active SET and makes the operator binary-search it, four builds at a time (P1, S) | new 2026-08-23, merged from BUILD fragment `2026-08-20_BUILD_infeasibility-hint-does-not-name-the-minimum-cap.md`; measured on 1240_6g

- **What:** on 2026-08-20 `1240_6g` (6 entries, 4 contests, 6-game Classic)
  `build_slate.py` refused three times at the posture/auto-floored defaults
  against a bank grown 25 → 68 candidates with 61 distinct SP pairs and 12
  distinct stacks. Each refusal printed only "no single control is
  arithmetically binding against this bank, so the interaction of the active
  controls is." Bank growth first, per the autonomy policy: did not clear it.
  Both STRUCTURAL remedies (`max_shared_players` 6→8, `max_sp_pair_repetition`
  1→2): did not clear it either. What cleared it was **one cap, alone**:
  `max_player_exposure_pct` 0.4 → 0.5, i.e. `floor(pct*n)` 2 → 3. Locating that
  cost **four full builds at ~35s each**, because the hint names the active set
  and not which member to move, so the only way to find the minimum change is
  to re-run the whole build once per candidate control. The delivered portfolio
  then posted 6 distinct primary stacks, 6 distinct SP pairs, 0 candidate-reuse
  relaxations, and a realized max player exposure of exactly 3/6 — so the
  binding cap was genuinely that one and every other control had slack.
- **Why:** this is the concrete, cheap answer to the gap R203 and R204 both
  describe, and it is cheaper than either. Raising an exposure cap is
  explicitly Ben's call outside R157's feasibility-rescue case, and the current
  hint gives him no way to see how far the raise has to go — so the cost is not
  only the four builds, it is that the escalation to Ben carries no number.
- **Fix:** when the joint MILP proves infeasible, re-solve once per active
  control with that control ALONE dropped — five solves against the in-memory
  bank, cheap next to four bank rebuilds — and name the controls whose removal
  restores feasibility, each with the smallest pct step that changes
  `floor(pct*n)`. That turns a four-build search into one line. Smaller
  alternative worth checking first: an IIS from HiGHS would say it directly if
  that backend exposes one. **Lands with R203 and R204's second half — same
  message, same call site, and this is the version that produces an actionable
  number rather than a named set.**

### R203. Teach `autobuild.py` the R157 exposure-cap rescue (P1, M; Tier 3) | new 2026-08-23, merged from DEV fragment `2026-08-22_DEV_autobuild-exposure-cap-rescue.md`, which traced the design in full

- **What:** CLAUDE.md's Autonomy section (R157, commit `fb4b03c`, 2026-08-22)
  delegates loosening `max_pitcher_exposure_pct` / `max_player_exposure_pct` /
  `max_primary_stack_exposure_pct` to rescue a proven-infeasible joint MILP,
  under two conditions. `tools/autobuild.py` implements none of it: its
  docstring still lists exposure caps under "WHAT IT WILL NOT DO, EVER", it has
  no branch touching those three controls, and on exactly this refusal it falls
  through to `dec.add(attempt, "stop", "refused with no remedy this supervisor
  may take", ...)` at line 265. The policy is delegated in prose and the
  supervisor still stops.
- **Where the trigger comes from, traced:** `contest_allocator.py`, inside the
  entry-level joint MILP solve (~2570-2633). `_diagnose_binding_constraints`
  runs first; when its `binding` list is NON-empty each fact becomes its own
  error line. When `binding` is EMPTY (the `else:` at ~2614) the code emits the
  bare sentence this hinges on — "no single control is arithmetically binding
  against this bank, so the interaction of the active controls is. Active:
  …" — and `_infeasibility_remedies(bank_report, binding)` then returns `[]`,
  because its own logic only emits text for controls it finds named in
  `binding` and there is nothing to find. That is why the 1335_3g refusal was
  one bare sentence with no `--controls-override` guidance, unlike the
  `shared_players_floor` case, which gets it because the diagnostic names it.
  The taxonomy already exists as code in the same file (~687-691):
  `STRUCTURAL_FLOOR_CONTROLS` and `STRATEGY_CAP_CONTROLS`.
- **The near-miss the design must not repeat:** `contest_allocator.py` 684-686
  records that "raise the cap to the named floor" is what taught the 1910_9g
  operator to move three exposure caps from 0.35/0.43 to 0.56 **against a bank
  explored to 1.8%** — loosening caps when the real problem was an unexhausted
  bank. `_infeasibility_remedies`' own docstring states the ordering that exists
  to prevent it: bank growth FIRST, `--controls-override` second, never relax a
  control against a bank that is still a slice. autobuild's loop already gets
  this right by construction — it checks `job_list_exhausted is False` and grows
  the bank (230-236) BEFORE the structural-checks block — so the new branch
  belongs strictly after both, and the commit should say so explicitly, since
  that ordering is the only thing making the 1910_9g mistake structurally
  impossible rather than merely unlikely.
- **Fix, in the file's own engine-diagnoses / supervisor-acts split.**
  **Engine:** at the `binding`-empty call site (where `controls` is already in
  scope — do NOT thread `controls` through `_infeasibility_remedies`, that is a
  bigger and riskier change), when the bank is also exhausted, append one
  explicit greppable line naming the diffuse interaction across
  `STRATEGY_CAP_CONTROLS`, so the supervisor matches a signal instead of
  parsing prose. It still names no FLOOR, because there isn't one, which keeps
  the engine's state-only-what-I-can-prove discipline intact. **Supervisor:** a
  new branch after the existing bank-growth and structural blocks that (i)
  detects the signal, (ii) confirms neither `STRUCTURAL_FLOOR_CONTROLS` entry is
  the current reason for refusal, (iii) re-runs once with the exposure caps
  fully open at 1.0 purely as a can-this-bank-certify-at-all check — if that
  still fails, STOP, because the pool or bank has a deeper problem and that is a
  real human question — and (iv) on success searches DOWN for a delivered target
  rather than hardcoding one. Recommended search: step down through a few
  decreasing values inside the existing `--max-attempts` /
  `--stop-after-minutes` budget and ship the first that still certifies. A
  cheaper alternative is deriving the target from the realized exposure in the
  certified-at-1.0 brief, but that has one data point behind it and no formula
  worth standing on; a fixed 0.55 is a last-resort fallback only, never the
  first thing tried. **Never leave the delivered file at 1.0.** Record
  before/after for all three controls plus the triggering diagnostic in
  `autobuild_decisions.json` — that is what lets a post-slate read confirm the
  delegation was used correctly rather than as a blank check. Sync whatever
  constant the branch needs against `STRATEGY_CAP_CONTROLS` at runtime the way
  `assert_classification_in_sync()` (autobuild.py:69) already does for
  `STRUCTURAL_FEASIBILITY_CHECKS`, never a fourth hand-copied literal.
- **Coverage bar:** a `test_core` fixture reproducing the "binding empty, bank
  exhausted, exposure caps the only remaining active controls" shape, the way
  `test_slate_feasibility_derives_floors` and
  `test_feasibility_relaxes_the_quota_downward_not_upward` reproduce the
  structural cases. A live-slate confirmation is not evidence for this one.
- **Grounding, stated as one data point:** 1335_3g (2026-08-22, 9 entries / 6
  pitchers / 3 games, mixed wta_satellite+single_entry+mme) was infeasible at
  the posture-merged defaults 0.43/0.35/0.35, still infeasible after both
  structural remedies (`max_sp_pair_repetition` 1→2, `max_shared_players` 6→7),
  certified at 1.0, and delivered at 0.55 with pitcher exposure topping out 4/9
  and no in-contest duplicate lineups. Treat 0.55 as evidence that *a* number
  exists for that shape of slate, never as the number. Lands with R204's second
  half, which is the same message on the same surface.
- **BLOCKED BY R214, filed 2026-08-24 (ed7 GF7-T5, Codex D05, both verified
  here).** The supervisor cannot currently PRESERVE an operator's R157 rescue,
  let alone perform one: its own `--controls-override` is appended after the
  passthrough and argparse last-wins drops the operator's dict entirely
  (`autobuild.py:184`, `:218-219`). So attempt 1 honours a hand-passed
  `{"max_player_exposure_pct": 0.55}` and the first structural floor erases it
  for every later attempt, while the decision log records only the floors. Land
  R214 first or this item's rescue fights the passthrough it is modelled on.
  **Two more sequencing facts for this batch.** R212 first as well — the
  wall-clock exit writes no `autobuild_decisions.json` at all, and this item's
  whole design is "record every step in that file". And R207's drop-one
  binding table (five solves against the in-memory bank, a per-control table
  into the refusal) is the cheaper diagnostic and should land BEFORE this
  item's detection half, because the detection reads exactly that signal.

### R98(3) + R98(4)-tail. The bank budget is still derived from leftover clock, and the CERTIFIED brief still cannot distinguish a deliberate cap from a starved one (P1, M) | new 2026-08-08; (1) and (2) landed the same evening, (4) half-landed

- **ed6 rider (2026-08-22, VERIFIED-read at ac8ac05; build_slate edited since,
  mechanism unchanged):** the direct-vs-sliced boundary is characterized.
  Strategy flips to sliced iff `projected_direct > remaining`, where
  `remaining` is measured AFTER staging, fetches, enrichment and a probe
  solve, and `projected_direct` is quadratic in the bank size — the same
  command can flip strategies run to run on probe noise. On the DIRECT path
  the `BankCache` is never opened: nothing persists, exit-10 resume is
  STRUCTURALLY unreachable, a killed call loses all work, and a refusal
  carries no `bank_exploration` block, so the grow-the-bank hint cannot fire.
  The direct budget floor fires by construction once the prefix eats the
  window (observed live: `BANK BUDGET FLOORED ... -1.7s remained`). Cheap
  rider for whoever lands this: persist the direct path's auto-built bank
  into the same cache — resume then survives the strategy choice and
  direct-path refusals get the same evidence block.

**Parts (1) and (2) LANDED 2026-08-08 (evening); full record in CHANGELOG.md.**
Shipped: `resolve_bank_budget()` making both floored budgets audible on stderr,
in `bank_warnings`, as `solve.bank.budget_floored` and `solve.bank_budget_floored`;
`select_and_assign_entries(bank_report=...)` appending ordered remedies that name
bank growth before `--controls-override` and separate a structural floor from an
exposure cap that has none; `infeasibility_hint()` doing the same in the refusal
payload; 13 tests reproducing the 1910_9g shape and pinning remedy ORDER and the
three silences. **One correction to the filing:** (a) named `build_slate.py:1453`,
but the observed `time_budget_s: 5.0` came from `:1346` — the bank report's
`time_budget_s` is `extend_bank`'s own parameter, and `:1453` is inert whenever
`candidates_override` is supplied. Both floors are now audible.

- **What remains, part (3):** the bank budget is still whatever is left of
  `--max-seconds` minus a reserve. Making the floor audible removed the
  INVISIBILITY, not the bad budget: five seconds for 2592 jobs and 9 entries
  could never have supported the defaults, and a build that now announces its
  floor still builds a 1.8% bank. Derive it from entry count and job-list size
  instead, and signal the exit-10 resume loop as the intended answer rather than
  as an exception path.
- **What remains, part (4):** `bank_exploration` (`jobs_attempted`,
  `jobs_total`, `job_list_exhausted`, `total_candidates`, `budget_floored`) now
  travels in the not_certified payload beside the hint derived from it. The
  CERTIFIED brief is the open half: `solve.bank` carries the counts on the
  sliced path only and never sits beside `controls_override_applied`, so after a
  build SUCCEEDS a reader still cannot tell a deliberate cap from a starved one
  without opening the bank block. That is the 1910_9g case exactly — it
  certified.
- **Extension 2026-08-10 (from the consumed postures fragment, part 2):** when
  the default portfolio controls are JOINTLY infeasible, the refusal correctly
  says no single control is binding but not which relaxation is smallest, so
  the operator guesses. Live case 2026-08-08 (1505_3g): certified on the
  second run at 0.6/0.55/0.5/7/2 after guessing. A hint naming the minimum
  feasible value per control turns two builds into one; it belongs with (3)'s
  remedy work because both are the refusal teaching the operator the exact
  move instead of the direction.
- **Repriced M, and the priority holds.** (1) was the part worth landing alone
  and it is landed, which is why this drops out of the numbered queue's position
  8 and into the opportunistic tier: the failure is now loud. What is left is
  the actual budgeting work plus one brief field, and neither is urgent while
  the floor announces itself. Done when: the budget is a function of the job
  list rather than of the clock, and a certified build that relaxed an exposure
  cap against an unexhausted job list says so in its brief.
- **Why this family is P1 (carried from the filing).** This is the R51/R92
  family seen from the strategy side: every individual report was honest and the
  composite steered wrong. The delivered portfolio's concentration was the shape
  of an under-explored search presented as a considered set of caps. It is the
  fourth recorded instance of the same two-round pattern (2026-08-01, 08-03,
  08-04, 08-08); the three earlier ones all ran short bank budgets too and were
  each filed as "small multi-contest slate," so the operator-side note had
  generalised the wrong variable three times running before the 08-08 pass
  corrected it.
- **Adjacent, do not merge.** R87's closing note ("Classic defers diversity to
  the allocator and discovers the shortfall at selection time") is the
  architectural statement of the same problem and is the right home for any
  in-solver overlap work; this is the budgeting half and does not need R87's
  golden regen. R73(f) budgets `solver_probe`, a different entry point. R92 is
  the same "report that cannot inform" family on the bank's warning lines.
- **Extension 2026-08-14 (audit, from BUILD fragment
  `2026-08-14_BUILD_floored-bank-hint-names-the-wrong-remedy.md`, fifth
  recorded instance of the family):** when `budget_floored` is true, the
  JSON `hint` leads with "re-run the SAME command" — the one remedy that
  cannot converge on a floored budget (measured: three re-runs at
  `--max-seconds` 14/20/22 bought ONE job and ONE candidate, 39→40 of
  3600), while the stderr line correctly says raise `--max-seconds` and
  forbids relaxing controls. The JSON is the channel the operator reads;
  the session obeyed it, relaxed five controls against a 34-candidate bank,
  and shipped 7 unique lineups across 15 entries. A 145s window then took
  the DIRECT path and certified twice (single lineup 0.14-0.35s) — there
  was never a bank problem, only budget arithmetic (`remaining - 8.0` going
  negative). Adopted asks: (i) when floored, "raise `--max-seconds`" is the
  FIRST remedy in the JSON hint, with the arithmetic stated; re-run advice
  only when NOT floored. (ii) refuse the loop outright when floored and
  `jobs_attempted` grew by less than a small N against the cached run —
  non-convergence named, not re-invited. (iii) SKILL.md stops teaching
  `--max-seconds 14` / `timeout 33`: on any slate taking the sliced path
  that guidance floors the budget BY CONSTRUCTION, and its 45s-ceiling
  premise is stale (`timeout 155` ran clean twice under the ~180s call
  ceiling; this audit's own suite runs agree). Measure the ceiling once,
  prefer a long window.

### R115. SP-pair coverage: the bank freezes at `requested_n`, the resume path cannot engage, and no control can floor arm diversity (P1, M) | new 2026-08-14, merged from BUILD fragment `2026-08-13_BUILD_bank-cache-freezes-at-first-slice.md` + ledger fragments 2026-08-13 (1507_3g); mechanisms verified in tree by the audit

- **What, three verified mechanisms behind the 08-13 1310_6g lost window (11
  blocked runs, `runs/20260813T162034Z_40da1d56` onward):** (1)
  `build_diverse_candidate_bank`'s growth target collapses to `requested_n`
  (`optimizer_v3.py:3863`: `coverage_target or candidate_bank_size_requested
  or requested_n`), so a bank already holding >= requested_n candidates never
  grows — the cache file's size and mtime sat unchanged across runs 2-7 at
  `--max-seconds 30` while the job list read 75/720. (2) `build_slate.py:1534`
  gates exit-10 on `len(candidates) < n_entries*2`; at 66 candidates against
  13 entries the documented resume path is unreachable however unexhausted
  the jobs. (3) jobs are ceiling-ordered (`bank_cache.py:744-750`) and
  budget-truncated, so a truncated slice concentrates in the top pairs by
  combined pitcher ceiling — 4 distinct starters on a 6-game slate. The
  fragment's "jobs vary stacks, not arms" diagnosis is CORRECTED: pairs are
  the primary job axis (`bank_cache.py:752-756`); truncation is the cause.
  Downstream the joint MILP reports slice properties as slate properties
  (R112's family), and on 1507_3g the operator monkey-patched the engine
  mid-slate (`cross_game_only` forced off in `enumerate_sp_pairs` and
  `bank_cache`, plus a synthesized per-pair LOWER bound no engine control
  expresses).
- **The patch's floor, kept here 2026-08-18 because the file it lived in was
  swept and this entry was its only other reader.** The mechanism is three
  lines and the diagnosis in it is the part worth having: EVERY pair control in
  `contest_allocator` is a CEILING, `pair_cap` adding one row per distinct pair
  as `add({x_idx(e, k): 1.0 ...}, -np.inf, headroom(...))`, so "each pair at
  least twice" is not expressible by relaxing anything that exists. The floor
  is the mirrored row on the same index set — `add({x_idx(e, k): 1.0 for e in
  range(E) for k in range(K) if sp_pairs[k] == pair}, float(minimum), np.inf)`,
  one per pair, immediately after the `pair_cap` block. Two consequences to
  design around rather than discover: a floor of `m` over `d` distinct pairs is
  infeasible on its face when `d * m > entries`, which is the closed-form check
  the sibling fragment already asks the refusal to name; and a floor cannot
  relax the way a ceiling does, so it needs its own place on the relaxation
  ladder or it converts a delivery into a refusal — which is R132's failure
  arriving through the control meant to prevent R115's. The bank-side half is
  separate and cheaper: `bank_cache` filters `if ga != gb` on `usable_pairs`
  and `enumerate_sp_pairs` defaults `cross_game_only=True`, which on a 2-game
  slate leaves 4 of 6 combinations before the allocator sees anything.
  Body archived at `_to_delete/tools_residue_20260818/` (gitignored) with a
  WHY.md; the two ledger fragments carry the slate's own record.
- **Why P1:** one whole slate window lost (the fragment's own cost line), and
  a run-scoped engine patch is the operator routing around a missing control
  — both silent-quality shapes, on the surface R98 and R112 already name.
- **Fix, ordered:** (a) bank growth honors an explicit coverage target above
  `requested_n` while the job list is unexhausted, or the exit-10 gate reads
  `job_list_exhausted` rather than the 2x heuristic — one of the two, so
  "grow the bank, re-run, it resumes" is true again. (b) a distinct-SP-pair
  coverage floor as a real control (the ledger fragment's
  `min_sp_pair_representation` ask), and `cross_game_only` exposed as a
  stated control carrying its anti-correlation warning, retiring the
  monkey-patch. (c) per-pair bank candidate counts in the brief beside
  `feasibility.checks` (rides the false-signal batch with R112), and — the
  sp_pair_floor ledger fragment's closed-form ask — when
  `job_list_exhausted` is true and `distinct_sp_pairs x
  max_sp_pair_repetition < entries`, the refusal NAMES that inequality: it
  is decidable arithmetic available before the MILP runs, and three
  relaxation rounds went to bisecting it under a T-20 clock while realized
  exposure sat exactly at the untouched default cap. Absorb
  R98(3)'s budget derivation where the two meet; they are halves of one
  failure. Done when: replaying the 1310_6g inputs either reaches
  `n_entries` distinct SP pairs in the bank or refuses in words that name
  the bank, and exit-10 engages on an unexhausted job list.
- **Audit fields.** Moves: portfolio quality, robustness, speed. Evidence:
  V2 (blocked-run manifests; fragment; the three mechanism lines read in
  tree). Falsifier: if a 30s budget genuinely cannot push that pool past 66
  candidates, (a)'s premise fails and the remedy is R98(3)'s budget work
  alone. FOSS basis: existing vendored scipy/numpy, stdlib; $0. Owner
  action: none. Rollback: new control defaults off; gate change is one
  conditional.

### R125. Autonomy defaults: bullpen-day auto-declaration, posture fallback, and a counted Classic relaxation ladder (P2, S-M, decision-first on two of three) | new 2026-08-14, merged from the delivery-guarantee fragment's autonomy section

- **What, three parts, all "act then report, never act silently":** (a) a
  bullpen-day policy — when a side carries a `PO` and a `PLR` and no `SP`,
  treat the `PLR` as the declared bulk arm automatically, record the
  inference in the brief, and let the optimizer decide on merit (live case:
  the engine demanded a web confirm for an arm Ben's own message had already
  named as a bullpen day; the arm then appeared in 0 of 17 entries). (b) an
  unmatched contest NAME falls back to a stated default posture with the
  fallback recorded, instead of hard-blocking ("MLB $200 Solo Shot (Turbo)"
  blocked a build; the Solo Shot family is in `contest_library` observed
  history). (c) a fixed, counted relaxation ladder for Classic — exposure,
  then stack share, then overlap, then SP-pair repetition — mirroring the
  Showdown contract, every step counted in the brief.
- **Why decision-first on (b) and (c):** (b) reranks contests entered
  tonight (the Quick Card's item 4 exists because family names mislead),
  and (c) automates exactly the relaxations R98(2) warns concentrate
  portfolios — both are strategy changes wearing convenience clothes, so
  they are Ben's, listed in Tier 4. (a) is a pool-policy change with the
  inference recorded and is DEV-ready the day Ben approves it.
- **Audit fields.** Moves: autonomy, speed. Evidence: V2 (fragment; the
  six-attempt sequence in its table). Acceptance for (a): fixture side with
  PO+PLR+no-SP auto-declares, brief records the inference, an explicit
  declaration still wins. Falsifier: any bullpen-day where the PLR read is
  wrong and an explicit channel would have caught it — the recording line
  exists to make that visible. FOSS: none. Owner: two dated decisions.
  Rollback: policy flags default off.

### R66. Silent shape/posture defaults on the API paths (P2, S) | audit 2026-08-04, verified in tree

- **What:** (a) `run_late_swap(contest_shapes=None)` scores every entry's candidates on the pure-ceiling `large_wta` profile (`late_swap_manager.py:311`) — tools/late_swap.py documents and works around it; the engine API neither warns nor records the substitution. (b) operator-supplied posture strings are never validated (`execution_pipeline.py:874`): an unknown token silently builds as `large_gpp` while `posture_source="operator_supplied"` suppresses the unresolved-contest blockers (reproduced with `{"123": "wta"}` — a token `normalize_posture` itself accepts). (c) `run_late_swap` accepts a naive `as_of` and reinterprets it as UTC (`late_swap_manager.py:73`): an ET wall-clock reads 4-5h early and every lock-derived gate shares the same wrong map (PLAUSIBLE as a live event — the shipped tool passes aware UTC; the API is the exposed leg).
- **Fix:** default swap shapes from the parent run's recorded postures or refuse when unmapped; validate posture strings against `STRATEGY_DEFAULTS` (mirror `validate_shape`'s discipline); raise or warn on naive datetimes at the swap boundary.
- **This item is a STANDING RED in the skill evals, recorded 2026-08-17 so the
  next session does not re-derive it.** `skills/generate-lineups/evals/run_evals.py`
  eval 5 (`adversarial-multi-ticket-satellite`) fails with `forbidden claim
  present: /large_wta/`, and it fails identically on a pristine checkout — a DEV
  session that changes anything else and then runs the evals will see one FAIL
  and has to prove it is not theirs. It was verified pristine on 2026-08-17 while
  landing R135. **Correction 2026-08-22 (ed6, VERIFIED-repro):** the coupling
  claim that stood here — "Closing (a) closes the eval" — is FALSE. The
  harness was re-run on a pristine copy (7 PASS, eval 5 FAIL) and eval 5's two
  `large_wta` hits are the CHECKPOINT's canonical contest-shape vocabulary
  (`"posture": "wta_satellite"` mapping to `"contest_shape": "large_wta"`);
  eval 5 never invokes a swap, so R66(a) cannot clear it. The eval-side fix is
  R181 (scope the forbidden regex). Until R181 lands, eval 5 red remains the
  expected state and 7 of 8 passing is a clean run — but do not expect R66(a)
  to change that.

### R68. late_swap operator rails: downgrade guard inert on "Name (ID)" cells; hostile flag and feed parsing at T-minutes (P2, S) | audit 2026-08-04, verified in tree

- **What:** (a) `_load_entry_rosters` (`tools/late_swap.py:229`) never normalizes roster cells, unlike every other reader on the path: a DK-redownloaded or hand-edited parent file ("Jose Ramirez (12345678)") makes `_score_roster` return None for every entry, every changed entry prints "not comparable", and the net-downgrade refusal silently never triggers — a strictly worse swap ships without `--accept-downgrade`. (b) `--entry-ids 4711612345,` (trailing comma) raises a raw ValueError traceback (`:508`). (c) the `--lineups` feed is `json.loads`-ed unguarded (`:451`; same at `build_slate.py:2209` and `solver_probe.py:85`) — a truncated file prints a JSONDecodeError instead of the mapped-blocker style the odds files get.
- **Fix:** normalize cells with `normalize_player_id`; filter empty tokens; wrap the three parses in the "unreadable feed: <exc>" pattern.
- **The name-fold half of (a) is no longer hypothetical (R151, 2026-08-17).** The
  same family — a reader on the intake path comparing raw strings while the rest
  of the intake normalizes — cost ten hitters their MLBAM id and bat side on a
  real slate through `merge_dk_starting_into_feed`, and produced seven false
  disagreement reports on top. This entry's "Jose Ramirez (12345678)" example is
  that defect one function over. Take the two together if either is taken.

### R267. `late_swap` matches WHOLE lineups against an entry's pins, so it structurally cannot repair a heavily-pinned entry — and this is not a search-effort problem (P1, M; the repair filter itself is S and is the whole value) | new 2026-08-29, merged from BUILD fragment `2026-08-29_BUILD_late-swap-repair-gaps-and-autonomy.md` §B and §E; field-forced on slate `1305_12g`

**What.** The swap matches whole-lineup candidates out of the bank against an
entry's pins. Late in a slate an entry has 3 to 9 slots frozen in locked games,
and no generic bank lineup will ever reproduce that exact 9-player prefix. The
refusal reads as a pin/exclusion problem and is accurate about the symptom:

    no compatible candidate for Entry ID 5234627043
      [not a portfolio control: this entry's pins and excluded_new_teams admit
       none of the bank's candidates]

**Why it is not search effort, measured.** On `1305_12g` (COL's probable moved
from Feltner to Agnos after delivery, putting a dead arm in 10 of 31 entries
with 45 minutes on the clock) the bank was grown from 566 to 1425 candidates
across six invocations, 1176 of 5304 jobs attempted. The message never changed,
**because more whole lineups do not make a 9-pin prefix more likely.** Worked
example, entry `5234627043`: 9 of 10 slots locked, only P2 open, $5,300 of cap
for the replacement. That is a one-slot search over the salary file. The engine
spent roughly 13 minutes of wall clock across attempts and never found it,
because it was searching the wrong object. The repair was hand-built, and the
hand-built file is what shipped.

**Fix. (a) A single-slot repair mode** — `late_swap.py --repair-slot`, or
`tools/repair_entry.py` — that for each named dead player enumerates the legal
replacements for THAT slot directly rather than through the bank: slot
eligibility parsed from `Roster Position` against the DK column the player
occupies; salary cap after removing the dead player; game not yet locked, from
the feed clock the way `verify_export` already derives it; confirmed starter
(R270's boxscore source after first pitch); not already in the entry; **not on
a team opposing any SP rostered in that entry** — `verify_export` caught
exactly that bug in the hand-built repair, so the constraint is load-bearing,
not decorative. Rank survivors by projection (APPG where no Base exists), take
the best, record the diff. A deterministic filter over ~1100 salary rows, well
under a second. **(b) The tool picks the mode on pin count, not the caller.**
The whole-lineup solve still belongs to any swap with meaningful freedom —
early in a slate, or entries whose open slots outnumber their pins; the repair
mode is for the tail. **(c) It touches no portfolio control**, which is what
makes it safe to run autonomously under R272 and is the reason to build it that
way rather than as a relaxation of the existing solve. **(d) A build-time
repair-feasibility count** (filed as an observation by BUILD, not a proposal):
Feltner was $5,200 and used as salary relief in 10 entries; when he was
scratched, the entire set of confirmed starters in still-open games that fit
the $5,200-$5,400 headroom was TWO arms — Sousa at $4,000 (a declared opener
the engine bars from P slots) and Lynch IV at $5,400. Eleven of 31 entries
finished at exactly $0 salary left. Leaning on a sub-$5.5k arm carries a
replacement risk nothing in the build measures: not the probability of a
scratch, but the fact that if one happens there is no legal repair. A
deterministic count — "arms in this price band on this slate: N" — makes the
exposure visible at build time. Report only, no gate, no control.

### R268. Two shipped fixes whose SYMPTOM never closed, both on the swap path, both of which taught the operator to switch a protection off (P1, S) | new 2026-08-29, merged from BUILD fragment `2026-08-29_BUILD_late-swap-repair-gaps-and-autonomy.md` §C(2) and §C(4); both verified in tree

**What.** Two halves, filed as one number because the class is the finding.

**(a) R29(3) unified control resolution and the swap still derives tighter than
the parent shipped.** On `1305_12g` the parent shipped
`max_player_exposure_pct=0.55` (an R157 rescue value, re-derived from that
slate's structural floors); the swap derived 0.50 and refused with *"player
43965130 already appears in 16 of the 29 row(s) this solve cannot change,
against a whole-file cap of 15."* **When most rows are frozen, a cap derived
tighter than the parent's is unsatisfiable by construction** — the frozen rows
already breach it and no legal swap can unbreach them. R29(3)'s "one function
both the build and the swap resolve controls through" is in CHANGELOG.md and is
real; what it did not do is make the swap INHERIT the parent run's realized
`portfolio_controls`. It re-resolves from postures, and a posture default is not
what shipped. Fix: inherit the parent run's `portfolio_controls` from its
diagnostics by default, print that it did, and require a flag to re-derive.

**(b) R29(2) deferred promotion and `--allow-parent-mismatch` is still needed on
every invocation.** `tools/late_swap.py:845-853` carries R29(2)'s own comment
saying the workaround "was `--allow-parent-mismatch` on every later call, which
is switching off the R20(c) protection because a bug taught the operator to
distrust it." The 08-29 slate needed the flag on every call anyway, for a
different reason: once any later run is promoted, the parent a given file
actually came from is no longer the promoted one, **which is the normal state
during a repair sequence.** The flag became reflexive again. Fix: accept a
parent matching ANY run in the manifest, and reserve the hard error for a file
matching none.

**Why one number.** Both are fixes that landed, were correct about their
mechanism, and left the operator's workaround in place — so both read as closed
on this board while still costing calls in the field. That is the reading worth
keeping, and it is lost if these are two entries. The check the class implies:
**a fix that eliminates a documented workaround is not done until the workaround
stops being typed.** Neither of these was verified that way.

### R141. Late-swap leverage pass: post-lock, report-only (P2, S) | new 2026-08-16, from the leverage ideation fragment

- **What:** after first lock, scratches and posted lineups move the field's
  remaining chalk, and the swap path today optimizes projection under rails
  with no leverage view at all.
- **Fix:** a report-only mode on the swap path: recompute the structural
  prior on the post-lock slate state, list unlocked exposures now sitting in
  the top structural-own tier, and show the differentiated
  same-team/same-slot alternatives already in the bank. Operator decides;
  `run_late_swap` rails unchanged; locked games stay closed (build contract
  item 5).
- **Sequencing:** behind R135 — it recomputes R135's prior, and without one
  it has nothing to recompute. **R135 CLOSED 2026-08-17**, so this is unblocked:
  the file is `outputs/<date>/ownership_pred_<tag>.json` and the recompute is
  `predict_ownership` again on the post-lock state. Tier 5, opportunistic.
- **Audit fields.** Moves: leverage (swap window). Acceptance: fixture
  post-lock state → tier list plus alternatives, zero engine mutation.
  Falsifier: none — reporting. FOSS: existing. Owner: none. Rollback: flag
  off.
- **Rider 2026-08-28 (ed9 §4.8, accepted as the gated upgrade):** once
  R261 grades, this pass can also re-emit P̂(top) / P̂(washout)
  CONDITIONAL on locked scores and remaining games (re-simulate unresolved
  games only; locked points fixed) — still report-only, same rails.
  "Ahead plays safe, behind plays narrow" arrives from those conditionals
  or not at all, never as a hard-coded rule.

### R71(b)(c)(d). Allocator/entries counted-honesty batch, remainder (P2, S) | audit 2026-08-04, verified in tree; (a) CLOSED 2026-08-15, migrated to CHANGELOG.md

**(a) landed 2026-08-15** (both `_cap_count` copies now reject `pct > 1`
instead of clamping it to 1.0): see the CHANGELOG entry of that date. What
remains is (b)(c)(d), unchanged from the original filing.

- **What, three parts.** (b) `reuse_strategy` is inert on the production entry-level path (`contest_allocator.py:1940`: the key is stored and never read; nothing maps "diversified" to `max_candidate_reuse=1` as the legacy solve did) while the module header still advertises the knob. (c) a wrong-draftgroup file's "embedded player pool overlaps…" error is misclassified by string prefix as a portfolio error (`dk_entries_manager.py:952`), leaving `roster_legality_passed=True` in diagnostics on a wrong-slate file — blocked overall by `errors`, but the flags lie to forensics. (d) the legacy `assign_lineups_to_contests` path degrades signature-extraction exceptions to unique per-candidate ids (`contest_allocator.py:390`), neutering its same-contest duplicate constraint.
- **Fix:** map or warn on `reuse_strategy`; classify errors by tagged origin lists, not prefixes; let signature extraction raise (mirror `_candidate_ordered_roster`).

### R73. Solver budget and diagnostics waste (P2, S) | audit 2026-08-04, verified in tree

- **What, six parts.** (a) two unbudgeted meta-lineup MILP solves run outside `time_budget_s` on every diverse-bank build (`optimizer_v3.py:3812` duplicating `:3580`; `run_meta_lineup` passes no time limit) — up to ~60s past a "respected" budget on the machine class the budget exists to protect, and per-candidate shape scoring runs after exhaustion, unbounded. (b) the DU relaxation path re-solves an identical, provably infeasible 5-rung ladder up to 4 extra times and appends the same index repeatedly to `proven_infeasible_lineup_indices` (`:2348`; reproduced — 26 solver calls where 6 suffice, indices `[1,1,1,1,1]`). (c) `_DU_AUTO` is dead code: the default is None-disables while the docstring and sentinel comment promise AUTO-enforcement (`:2072` vs `:301`). (d) `_check_stack_feasibility` early-returns whenever locks exist (`:497`), so lock-tightened stack infeasibility surfaces as a generic MILP infeasible instead of the named `StackInfeasibleError` guidance. (e) augmented candidates derive `lineup_id` from `len(existing)+1` (`:3900`), colliding with request-index ids after any failed base index — two different lineups named "L10" in the redundancy report. (f) `solver_probe` runs unbudgeted probe solves (up to 5 lineups × 5 rungs × 30s default on the ~43s-kill machine it exists to protect), skips the Classic-geometry check when `--salary/--lineups` are explicit (`tools/solver_probe.py:48,108`), and is the one solver entry point without the PYTHONHASHSEED re-exec pin; relatedly the bank's redundancy/exposure summaries are dropped by bare `except: pass` (`optimizer_v3.py:3981`; also `execution_pipeline.py:221`) instead of the house "unavailable: <exc>" note.
- **Fix:** compute meta ids once and thread `resolve_solver_time_limit` through `run_meta_lineup`; break the ladder on proven-infeasible-without-DU-cause and dedupe indices; delete or honor `_DU_AUTO`; run the stack check with locks as committed salary; `max(existing id)+1`; budget the probe, move the geometry check after both input paths, add the re-exec guard; record notes instead of passing.

### R84. Allocation observability: per-control slack and per-entry coverage counts (S) | audit 2026-08-04

On every successful solve, emit achieved-vs-bound per control ("max_player_exposure: 8/9, binding on pid X") in `allocation_solver_report`; record per-entry compatible-in/kept counts from the prefilter (makes R36 Finding 10's starvation impossible to miss); and have tools/late_swap.py print the whole-file achieved exposures pre-solve so near-binding caps are visible before they block rather than only through `classify_swap_failure` after.

**Riders 2026-08-14 (audit, from the 2207_2g fragment's asks 3-5, this
item's exact surface):** mark each resolved control BINDING or SLACK beside
its realized value (an echoed override that changed nothing currently reads
exactly like one that shaped the build — verified: the second 2207_2g build
passed five tightened controls and delivered identical constructions);
print the structural exposure floors beside realized exposure
(`ceil(2*entries/distinct SPs)` and the hitter equivalent — the machinery
exists in `_feasibility_findings`/`STRUCTURAL_FLOOR_CONTROLS`; a full review
round went to treating an arithmetic floor as a control failure); and rank
zero-exposure bats by ceiling per dollar, not raw ceiling, so a dominated
absence stops reading as a defect.

### R130. Seven builds on one date share one bank, and the brief never says the bank grew underneath them (P2, S) | new 2026-08-16, from BUILD's 2026-08-15 2138_2g fragment — remedy revised, see below

- **What:** BUILD ran seven builds on the 2138_2g slate, several under different `--controls-override` values, and the results stopped being reproducible: v1 and v3 each produced 19/19 distinct lineups at max overlap 5, then a rerun of v3's EXACT config produced 7/19 at overlap 10, and later reruns on auto-floors produced 10/19. Three of seven builds were spent discovering this. Rebuilding on a cleared bank then failed the other way with `entry-level joint MILP proven infeasible`, because the fresh bank was too thin for the auto-floor caps.
- **Why:** the observation is real and it cost half a slate's build budget, but **the fragment's diagnosis and its proposed remedy are both wrong, and the remedy would make things worse** — recorded here because the wrong fix is the attractive one. The fragment reads the cache as "keyed on date" and proposes keying it on a hash of the resolved controls. Verified 2026-08-16: the cache is keyed on date PLUS a pool signature (`bank_cache.pool_signature`, so two DK exports sharing a calendar date do not collide), and it already carries a conditions signature from R101 over projections, exclusions and stack min/max. The controls BUILD varied — pitcher exposure .85, shared players 9, stack weight .55 — are ALLOCATOR-side, applied to a bank after it exists, so the bank is correct not to key on them. Keying on them would mint a thin fresh bank on every control change, which is precisely the second failure BUILD hit that same night. What actually produced 19/19 then 7/19 on an identical command is the bank GROWING across seven builds on one date and pool: the allocator selected from a larger candidate set each time, and a larger set is not automatically a better one under fixed caps. The fragment's own P7 says this ("each rebuild grows the bank and changes results"); it just did not connect it to P4.
- **Fix:** reporting, not keying. Record in the brief the bank's size and its conditions-signature set at the moment the delivered portfolio was selected, and warn when the bank grew between the first build of a slate and the delivered one — the operator's question is "am I comparing two builds against the same candidate set," and today nothing answers it. `distinct_lineups` and the reuse cap already reach the exposure block since R116, so this is the missing third number in a block that exists. **The key-on-controls remedy is DECLINED** with the reason above; if a future session wants bank isolation per control set it needs to price the thin-bank failure first, and R115 and R98(3) both own pieces of that argument. R131(c)'s SKILL.md iteration discipline is the operator-facing half of the same finding.

### R132. The build refuses instead of escalating its own controls, and a delivery was lost to it (P1, M with a cheap S variant) | new 2026-08-16, from BUILD's 2026-08-14 fragment — filed late, this board had recorded it as merged

- **What:** on 2026-08-14 `2138_4g` (8 entries) the build refused five times over twenty minutes, from T-15 to T-8, each refusal naming one more binding control, while the operator relaxed them one at a time by hand. The slate went undelivered. Nothing in the engine escalates its own controls when the MILP proves infeasible; the refusal names a control and stops. The fragment self-assesses this as the highest-value change on the board and carries the arithmetic that explains the shape of the failure: `player_exposure_floor` PASSED at equality, cap 2 against a structural floor of 2, and a check that passes exactly at its floor is a check about to fail in interaction with the next constraint. That is why relaxing one control at a time converged nowhere — each pass moved one binding constraint and re-bound on the next.
- **Why:** this is the failure the project's own operating memory already names ("open every binding control at once; incremental relaxation cost a delivery") and it is the harder half of the delivery-guarantee family. R124 covers the delivery that got BUILT and was not shipped, and its `--deliver-always` mirrors an export that exists. Here the MILP is infeasible and no export is ever written, so there is nothing to mirror — R124's remedy cannot reach this case, which is why the two are separate items sitting adjacent. It is also the concrete instance of Ben's 2026-08-15 framing that process should not stand in the way of a portfolio: five truthful refusals produced no lineups, and one escalation with the relaxations counted would have produced a portfolio the operator could accept or reject.
- **Fix:** a four-step escalation ladder that opens every binding control at once rather than one per pass, with escalation as the DEFAULT and `--no-auto-escalate` for the operator who wants today's behaviour. Every step counted in the brief exactly the way R116's reuse ladder and R37's precedent already do — never on a timeout, always counted, relax the engine's own guess before anyone's decision — so the ordering rule this project already uses carries over unchanged and no new policy is invented. Concentration becomes a headline risk line in the brief, since a portfolio produced by an escalated ladder is by construction more concentrated than one produced by the caps as written and the operator has to see that in the same place they see the lineups. **The cheap variant that can land alone:** better small-slate control DEFAULTS, which does not need the ladder at all and would have covered this slate. **Named acceptance test, from the fragment:** replay 2026-08-14 `2138_4g` at 8 entries and expect exit 0 on the FIRST invocation, where it exits 3 today.

- **Note 2026-08-16 (DEV), the autonomy contract draws a line through this
  entry.** CLAUDE.md's 2026-08-16 autonomy section makes engine-named
  structural remedies auto-applicable and reserves exposure-cap raises to Ben
  (no engine-named floor; raising one concentrates the entered set). R134's
  supervisor now takes every classified stop, so what still ends a window
  early is mostly this item's case: a joint infeasibility whose remedy set
  includes caps. Split accordingly. DEV-READY: the small-slate-defaults S
  variant, and ladder rungs over engine-derived floors and guesses — the
  R37/R116 precedent, never on a timeout, always counted. BEN'S (= R125(c),
  Tier 4): any rung that raises an exposure cap, which is exactly the
  auto-relaxation R98(2) warns concentrates. The named acceptance test
  stands and is achievable by the DEV-ready half alone if the defaults
  variant covers the 2138_4g shape; if it does not, that measurement is the
  evidence R125(c)'s decision should be made on.

### R87. Solver throughput under the golden gate (M, decision first) | audit 2026-08-04

Three scipy-native levers, each of which moves golden bytes and therefore sequences behind a deliberate golden regen — do not let any of them ride another change: `mip_rel_gap` on bank solves only (candidates need diversity, not proven optimality; final and meta solves stay exact); build the base constraint matrix once per pool and append per-solve rows instead of re-running `df.iterrows()` per rung per lineup; aggregate the per-(SP, hitter) opposing rows into one row per SP (`8·Σx_sp + Σx_opp ≤ 8` — same feasible set, far fewer rows). Also worth weighing there: optional portfolio-overlap rows in the bank MILP for thin slates (Showdown already enforces overlap in-solver; Classic defers diversity to the allocator and discovers the shortfall at selection time).

### R163. Solver-infeasible lineup indices "earn" DU relaxation: the final portfolio validates at relaxed thresholds and the record claims a relaxation nobody used (P1, S) | new 2026-08-22, from the greenfield sixth edition; VERIFIED-repro at ac8ac05, mechanism re-read at ec832cf (`optimizer_v3.py:2501-2506`)

- **What:** on a DU-enforced multi-lineup build, a lineup index that proves
  infeasible on the overlap ladder still steps `relaxation_idx` and bumps
  `du_relaxation_high_water` although DU never entered the solver; the retry
  re-solves the identical ladder (R73(b)'s waste, measured 51 solves where 11
  suffice), and `validate_du_portfolio` then validates every ACCEPTED pair at
  the maximally relaxed thresholds while stamping `relaxation_applied` with
  `relaxations['du_relaxed_lineups']: 0` — a recorded relaxation no accepted
  lineup used, and a weakened final validation. Repro output in the archived
  edition.
- **Fix:** bump the high-water only when a lineup is ACCEPTED at
  `relaxation_idx >= 0`; on `proven_infeasible` without DU violations, break
  instead of stepping.

### R164. The bank job grid wastes solves two ways, hardest on the pinned late-swap path (P1, S) | new 2026-08-22, from the greenfield sixth edition; (a) VERIFIED-repro, (b)(c) VERIFIED-read (`bank_cache.py` unchanged since the review)

- **What:** (a) when pins relax `stack_min` below 2 the stack constraint is
  nulled but the job grid still fans out one job per team, so the IDENTICAL
  pins+pair MILP is solved `len(teams)` times per SP pair — measured 15 jobs,
  15 solver calls, 3 distinct candidates on a 7-pinned-slot entry; on a
  12-game slate ~96% of that entry's slice budget is duplicate re-solves,
  exactly at T-minus. (b) the grid pairs every SP pair with stack teams that
  OPPOSE one of the pair's arms — provably infeasible before the solve;
  `build_diverse_candidate_bank` already skips these via `_teams_of_pair`, so
  the two subsystems disagree (~528 wasted solves of 6,336 jobs on 12 games,
  in the FIRST slices). (c) exact `Position == "P"` instead of the
  `_parse_positions` treatment.
- **Fix:** (a) collapse the team axis when `stack_min < 2`. (b) skip
  `(pair, team)` when `team` opposes either arm. (c) parse positions. Sits
  beside R115 (same file, same session).

### R165. Excludes match an unnormalized Player_ID in the cap-denominator and viable-SP helpers: R55's class on two more sites (P1, S) | new 2026-08-22, from the greenfield sixth edition; VERIFIED-repro at ac8ac05, raw `isin(excludes)` re-confirmed at ec832cf (`optimizer_v3.py:1432,1461`)

- **What:** `_eligible_sp_ids_for_anchor_caps` and `resolve_viable_sp_pool`
  filter with `df['Player_ID'].isin(excludes)` and no `astype(str)`. On an
  int64 frame — a `read_csv` reload of `runs/<id>/inputs/projections.csv`,
  R55's own motivating artifact — string excludes no-op THERE while the
  solves honor them: auto SP caps computed against a pool including excluded
  arms (repro: denominator 7 where 20 is correct), and SP-pair coverage plans
  seed pairs whose locks then die as `locked_player_unavailable`.
- **Fix:** normalize once in each helper (or route both through R55's shared
  normalizer).

### R166. The post-R61 controls never got fixed-row denominators: the reuse default is inert on scoped swaps, an operator's whole-file reuse cap is breachable, and the five-stack floor counts solve entries only (P1, S-M) | new 2026-08-22, from the greenfield sixth edition; VERIFIED-repro (default-inert leg) + VERIFIED-read (`contest_allocator.py` unchanged since the review)

- **What:** the engine-default `max_candidate_reuse` rungs are sized from
  `total = E + fixed_rows` but constrain only the E solve entries — measured:
  10 fixed rows loosen the cap from 1 to 6 and it binds nothing, so R116's
  de-concentration default silently does not act on exactly the swap path. An
  operator cap documented as whole-file never subtracts fixed rows' usage of
  the same signature (unlike every exposure cap's `headroom()`), so 15 of 20
  file rows can share one lineup while the solve certifies. The five-stack
  floor computes `need` on E while every ceiling resolves against `total`.
  No post-export gate grades reuse, so nothing file-derived can see any of it.
- **Fix:** derive the default from E; give reuse rows the R61 headroom shape
  (`ub = max(0, cap - fixed_signature_counts[sig])`); compute the floor's
  `need` on `total` minus fixed qualifiers; mirror a whole-file reuse count
  into `validate_dk_entries_file` when the control is set. Lands beside
  R115/R98(3) in Tier 3 if not taken at the Tier 1 boundary.

### R167 + R168 + R169. CLOSED 2026-08-24 -- the lost-window batch, entries migrated to CHANGELOG.md

All three landed together because they are one defect class: a failure that
arrives AFTER the window that could have absorbed it, or in a shape no
documented consumer can read.
R167: the units rule for a fractional exposure control now lives in ONE function
(`contest_allocator.assert_fraction_cap`) called by the solve, by the checkpoint
closure that used to clamp, and by `_merged_controls_for_build` on the override
-- the boundary the build and the swap share. `build_slate` also refuses at exit
4 before staging, which is the only check Showdown reaches. A FOURTH copy was
found and fixed while landing it: `showdown.exposure_cap_count` validated
nothing, so a slipped cap returned a count of 25n and left every R153 relaxation
counter reading clean.
R168: `main()` no longer returns a tuple on the supplied-feed-rejected path, and
the first lineups fetch of the day is guarded like the refetch leg -- it degrades
to an empty feed with `lineups_feed_unavailable` instead of a raw traceback.
R169: a `TimeoutExpired` records `build_timed_out` and exits 5 instead of losing
the whole decision log; the log dates from the brief, then the salary file, then
`today_et`, and the pre-brief payloads carry `date`; a structural remedy may move
only the control its check is about; `--passthrough` is `shlex.split` and ordered
before supervisor-owned flags. `autobuild.py` had zero tests and has seven.
**Numbers reserved; the record is the 2026-08-24 CHANGELOG entry.**

### R170. build_slate smalls: the preserve-fallback re-mints the borrowed tag, and a missing --odds path silently becomes a live fetch (P2, XS) | new 2026-08-22, from the greenfield sixth edition; VERIFIED-read at ec832cf (`build_slate.py:428`, `:772`)

- **What:** (a) `preserve_prior_slate`'s collision fallback names the dest
  `{stem}_{tag}_{n}` with the CALLER's tag, not the file's own — the exact
  borrowed-tag mislabel the function's docstring records fixing, reachable on
  same-date rebuild churn. (b) `--odds` naming a nonexistent file skips the
  file silently; with a key resolvable the build fetches live odds instead of
  the operator's curated packet, and without one the warning falsely says no
  file was named. Contrast stage_slate's R70 discipline.
- **Fix:** (a) use `own or tag` in the fallback name. (b) named-but-missing
  `--odds` exits 4 (or warns with the path).

### R171. qa_portfolio can read clean when it is not: a CWD-relative reference dir and a signal line printed only when good (P2, XS) | new 2026-08-22, from the greenfield sixth edition; (b) VERIFIED-repro at ac8ac05, both re-confirmed at ec832cf (`qa_portfolio.py:893`, `:144`)

- **What:** (a) `--reference-dir` defaults to the relative string
  `"data/reference"`; run from anywhere but the repo root, `read_savant`
  returns `{}` with no warning and section 2 prints "none of the checks
  fired" — indistinguishable from clean, in the adversarial tool. (b)
  `section_applied` prints `signal_applied` only when truthy, so the headline
  ("APPG in a ceiling costume") is silent exactly when bad, and R127's
  `signal_applied_by_side` is never surfaced.
- **Fix:** anchor on `REPO / "data/reference"` + warn when Savant files are
  absent; always print `signal_applied: true|false` plus the by-side split.
  Rides R11 (same tool).

### R193. qa_portfolio reads whatever brief it is handed, so a stale one reported false gates on a certified delivery at T-13 (P1, S) | new 2026-08-23, merged from BUILD fragment `2026-08-19_BUILD_qa-portfolio-read-a-stale-brief.md`; field-reproduced on the 1835_9g slate

- **What:** `qa_portfolio.py --entries outputs/2026-08-19/DKEntries_1835_9g_f64a2b1e.csv
  --brief outputs/2026-08-19/build_brief_1835_9g.json` printed `gates:
  workflow_valid false` and `F1 NEUTRAL: no implied totals reached the
  projections`. Both were false for the delivered file:
  `runs/20260819T221042Z_f64a2b1e/manifest.json` carries all three gates true,
  `status: promoted`, `front_door: run_slate v1.17`, and the ownership
  prediction file reads `implied_totals applied`. The brief on disk was from
  that day's FAILED 15:28-15:33 attempts (`_b1.err`..`_b8.err`), tag-matching
  and carrying `delivered_sha256: null`. Two defects, and they compound:
  (a) QA accepts a brief by NAME and never checks it against `--entries`,
  where the preflight already matches on `delivered_sha256`; (b) the 22:10
  certified run wrote no brief into `outputs/<date>/` at all, so the only
  `build_brief*_1835_9g.json` on disk was the wrong one and the nearest wrong
  file won.
- **Why:** this ran the OPPOSITE direction from R142's cost — the artifact said
  certified and the adversarial diagnostic said failed, at T-13 on a live
  slate. A promoted run with no brief also means SKILL.md's "diagnose from the
  artifact" has no artifact, which is the more structural half.
- **Fix:** (a) refuse a brief whose `delivered_sha256` does not equal the
  sha256 of `--entries` — null included — and say which two files disagreed,
  rather than reporting its fields as this portfolio's. (b) Write the brief
  from `run_manager` at promotion so a promoted run always has one, or have QA
  fall back to `manifest.json` when no matching brief exists. (a) is the
  cheaper half and it is the one that makes a stale brief harmless.
- **Rider 2026-08-29, the same class one COLUMN over** (from BUILD fragment
  `2026-08-29_BUILD_late-swap-repair-gaps-and-autonomy.md`, slate `1305_12g`):
  qa's `APEX (run's own Ceiling column)` reads the Ceiling computed for the
  ORIGINAL rosters, so on a hand-corrected or swapped file it is stale and
  **reported identical across two genuinely different portfolios** (4404.1 in
  both). The washout and stack proxies on the same pass are computed off the
  delivered bytes and stay live, so one section mixes a live reading with a
  frozen one under no label. Fix with (a)'s own remedy: recompute apex from the
  salary file, or label the column stale whenever the entries do not hash to
  the brief's `delivered_sha256` — the check (a) already builds. Landing (a)
  first makes this a two-line addition.
- **Recorded so it does not get "fixed" by accident:** on the same slate the
  frontier section did its job twice, correctly rejecting both attempted
  improvements on its own numbers — pre-lock, cutting the binding SP axis 32% →
  23% pushed the game axis 32% → 42% for zero apex gain; post-lock, swapping a
  flagged arm only relocated the flag to a worse one (+1.04 → +1.36) at a cost
  of 8.7 APPG. The frontier report is working as designed; this rider is about
  one stale column beside it, not about the section.

### R195. An explicit `--postures <id>=wta_satellite` reintroduces the pre-R1a `large_wta` mapping for a satellite contest (P1, XS) | new 2026-08-23, merged from BUILD fragment `2026-08-20_BUILD_postures-satellite-shape-bug.md`; mechanism traced to the line

- **What:** `_resolve_contest_postures` in `execution_pipeline.py` builds
  `inferred = {"inferred_type": "wta_satellite", ...}` from a plain-string CLI
  override. `resolve_contest_shape` tests `itype in SATELLITE_TYPE_TOKENS`, and
  `SATELLITE_TYPE_TOKENS = frozenset({"satellite"})` — the literal
  `"wta_satellite"` is not a member, the check fails, and the call falls
  through to `_posture_to_shape("wta_satellite")`, which is exactly the mapping
  to `large_wta` that `contest_shapes.py`'s own docstring calls dead and wrong.
  The AUTOMATIC path is fine: `infer_contest_archetype` reads
  `inferred_type="satellite"` off the archetype row, which IS a member.
- **Why:** the ledger Quick Card's standing instruction — pass explicit
  postures by contest id, never trust name inference on family names — is the
  thing that reintroduces the bug, because `wta_satellite` is the only
  CLI-accepted posture string for that family (`VALID_POSTURES`). The 08-20
  `1835_3g` build worked around it by deliberately NOT passing `--postures` for
  two SUPERSatellite ids and letting inference run, confirmed correct via the
  brief's `contest_shape: "satellite"`. So the documented-safe move is the
  unsafe one, silently, for one family.
- **Fix:** route the string-override path through the same satellite detection
  the automatic path reaches — treat `wta_satellite` as a `SATELLITE_TYPE_TOKENS`
  member, or have `_resolve_contest_postures` set
  `payout_shape_default="ticket_line"` for that override. If neither, document
  that an explicit `wta_satellite` override is WTA-ONLY and a satellite must be
  left to inference, and make `VALID_POSTURES` say so. Related, and Ben's:
  `dk_contest_archetypes.csv` carries no `ticket_count` for the
  Satellite/Qualifier/Ticket rows (R1c), so `satellite_shape_for(None)` used a
  default here — the `[2x]` in "MLB SUPERSatellite to NFL 9-13 … [2x]" may be
  the count.

### R202. `solver_probe.py` reads the staged slate, not the one being uploaded, and cannot be given a salary path (P2, XS) | new 2026-08-23, merged from BUILD fragment `2026-08-19_BUILD_pitchhand-missing-and-bank-solve-ceiling.md` item 3

- **What:** `--date 2026-08-19` resolved `data/slates/2026-08-19/DKSalaries.csv`,
  which still held the `1235_4g` draftgroup from an earlier session that day,
  and reported "pool 79 players, 7 SP" for a 9-game slate. `build_slate.py`
  detects a draftgroup change and moves prior inputs aside; the probe has no
  such check and no `--salary` flag.
- **Why:** harmless here because the probe is advisory, and that is exactly why
  it is worth fixing cheaply: its numbers were for a different slate and
  nothing said so, and the probe is what a session runs to decide a time
  budget. A wrong pool size gives a wrong budget with no warning.
- **Fix:** accept `--salary`, and when resolving by date, cross-check the
  resolved file's draftgroup against the entries file or print the draftgroup
  it read. Naming the file and the draftgroup in the output is most of the fix.
- **PARTIALLY OVERTAKEN 2026-08-24; the entry above is half wrong and is
  rewritten here (ed7 §2.4, verified at `a49bd610`).** `solver_probe.py` HAS
  `--salary` (`:71`) and additionally refuses a non-Classic geometry by name
  (`:58-64`, via `detect_salary_contract`), so "cannot be given a salary path"
  is no longer true and the title is stale. **What survives, unchanged:**
  date-resolution still reads the shared staged `data/slates/<date>/DKSalaries.csv`
  with no draftgroup cross-check, and NEITHER output names the salary file or
  the draftgroup it read — so the filed wrong-draftgroup silence stands in
  full, and it is the whole of the remaining item. Two notes for the landing
  session. The surviving half is smaller than XS: it is a print statement plus
  one comparison. And no CHANGELOG entry mentions the `--salary` flag, which
  makes this a probable `changelog_debt` instance worth checking while R180 is
  open.

### R204. "Grow the bank" is unbounded advice against a solve cost that is not, and the diffuse-infeasibility message names no set (P2, S) | new 2026-08-23, merged from BUILD fragment `2026-08-19_BUILD_pitchhand-missing-and-bank-solve-ceiling.md` item 2; measured on the 1835_9g slate

- **What:** measured on a 14-entry 9-game slate, following the engine's own
  first remedy while `job_list_exhausted` was False: 168 candidates refused
  and the solve completed in ~33s; 413 refused, 37.2s; 573 did not finish
  inside a 45s call; 601 the same. The refusal never changed between 168 and
  413 because the binder was a control INTERACTION, not coverage — so growing
  was the wrong remedy for 245 candidates' worth of clock, and past roughly
  500 candidates a bounded environment can no longer read the answer at all.
- **Why:** the hint repeats "grow the bank" with no price attached, and it is
  the correct FIRST remedy (R98(2), and the 1910_9g near-miss is why it is
  first), so this is not an argument to demote it. It is an argument that the
  hint should carry the cost curve the caller needs to know when to stop
  following it.
- **Fix:** name the solve time the last slice took beside its coverage
  percentage, so a caller can see the curve rather than infer it. And have the
  bank-aware capacity check that prints "no single control is arithmetically
  binding" name the SET it proved binding rather than only that no singleton
  was — a caller can act on a named pair. That second half is the same surface
  R203 needs and lands with it. Ben's open question from the same fragment,
  not DEV's: should a ONE-entry contest set a portfolio-wide exposure cap for
  12 entries it has no stake in? The mixed-portfolio merge floors
  `max_sp_pair_repetition` and `max_shared_players` via `_slate_feasibility`
  and does not floor the pct caps, which is how 0.35 and 1 arrived on a
  `wta_satellite` slate whose own defaults are 0.45 and 2.
- **Second sighting and a sharper half, 2026-08-29** (from BUILD fragment
  `2026-08-29_BUILD_late-swap-repair-gaps-and-autonomy.md` §C(1), slate
  `1305_12g`): the hint is not merely unpriced, **it is asserted after growth
  has become impossible.** `build_slate.py:1784` caps the bank at
  `max_candidates=max(n_entries * 12, 60)` — 372 for 31 entries. Once that cap
  is hit, re-running the identical command adds nothing, and the refusal still
  printed *"FIRST REMEDY, grow the bank: the job list was NOT exhausted (408 of
  6336 jobs attempted, 6.4%)"*. It was re-run; the candidate count did not move,
  372 → 372. The job-list percentage is true and irrelevant, because jobs
  remaining and candidates admissible are different quantities and only the
  hint's reader conflates them. **This is the first remedy CLAUDE.md's Autonomy
  section names as always-permitted, so a hint that recommends it when it cannot
  work sends an unattended supervisor into a loop.** Fix: read the cap and say
  so — `bank at its ceiling for this entry count (372 = n_entries * 12);
  growing is not available, the remedies below are`. Per R233 the landing entry
  carries the grep enumerating every site that prints a grow-the-bank remedy;
  measured at this head it is three real sites —
  `mlb_engine/allocate/contest_allocator.py`,
  `skills/generate-lineups/scripts/build_slate.py`, and
  `skills/generate-lineups/SKILL.md` — plus `tools/_scratch_1835_9g/grow_bank.py`,
  which is closed-slate residue and named here only so the next session does not
  count it as a fourth.

### R212. CLOSED 2026-08-28 -- the supervisor's wall-clock exit flushes its
decision log, and so does the drift exit the entry did not enumerate; entry
migrated to CHANGELOG.md

Ten exits from `autobuild.main()`, ten `_write` calls, no kept sibling. The
CHANGELOG entry of that date carries the R233 enumeration and the tenth site
(the classification-drift refusal, which returned 4 before `dec` existed). The
test is the property, not the pair: every `ast.Return` in `main()` must sit
immediately after a `_write(...)` in its own block.

### R213. CLOSED 2026-08-28 -- a named feed that cannot be read is bad input at
exit 4, an unreadable staged cache is ABSENT and falls through to the guarded
fetch leg; entry migrated to CHANGELOG.md

`supplied_feed_unreadable` carries the path and the parse error; the staged read
moved above the branch chain so the `elif` tests a value rather than a file's
existence, and a discarded cache is named in `feed_note.staged_feed_unreadable`.
R168(b)'s AST test was widened in place from one function name to the call
SHAPE, `fetch_lineups` plus `read_text`. The CHANGELOG entry of that date
carries the four-site enumeration and the one shape deliberately left out
(`write_text`).

### R214. CLOSED 2026-08-28 -- "supervisor-owned flags win" is enforced per KEY
instead of by replacing the operator's whole dict, and the log carries three
fields; entry migrated to CHANGELOG.md

`lift_controls_override` pulls the operator's override out of the tokenized
passthrough (both spellings), so exactly one `--controls-override` reaches
build_slate: `{**user, **derived}`. Duplicate, non-JSON, non-object and
value-less occurrences refuse at exit 4. `user_controls` / `derived_controls` /
`effective_controls` ride every record that touches controls and sit once at
the top of `autobuild_decisions.json`.

**Note for R203.** This was R203's precondition and it is now met; R203 is still
OPEN and unstarted. The supervisor can now preserve the manual R157 rescue it
will eventually be taught to perform.

### R215. CLOSED 2026-08-28 -- (a)(b)(c) landed together: the sixth fraction
control is validated per game id, NaN/inf/bool no longer clear the rule, and
both boundaries store the coerced float; entry migrated to CHANGELOG.md

`FRACTION_CONTROL_DICT_KEYS` and `fraction_or_problem` are build_slate's half;
`_fraction_control_dict_keys` and `coerced_override` are the merge's;
`assert_fraction_cap` rejects a bool before the `float()` and a non-finite after
it. The CHANGELOG entry of that date carries the R233 enumeration of all
thirteen fraction-control sites and names the four clamps deliberately kept with
the reason each survives.

### R237. An uncomputed factor and a computed-neutral factor are different facts, and three surfaces conflate them (P1, S) | new 2026-08-27, merged from BUILD fragments `2026-08-24_BUILD_actionnetwork-odds-fallback.md` §1 and `2026-08-27_BUILD_showdown_f1_and_archetype_gaps.md` §1; corroborated by the outside spec ed8 (F-38, F-43)

**What.** Three faces of one conflation. `factors_inert` printed "none inert:
every computed factor moved at least one row" on a build whose F1 never
computed at all (true and misleading — R117 defined inert as scored-and-moved-
none, and never-computed is in no bucket). `qa_portfolio` printed `F1 NEUTRAL:
no implied totals reached the projections` on a Showdown build whose path
never runs enrichment and writes no block for qa to read. And the engine fills
missing factor columns with 1.0 plus notes, so "provider failed," "not
computed," and "not applicable" become identical model inputs downstream.

**Why.** The 08-16 failure class the "diagnose from the artifact" rule was
written for: a session reading `F1 NEUTRAL` literally spends a pre-lock window
rebuilding, and a session reading `signal_applied: true` ships a dead F1. The
distinction already half-exists (R117's INERT vs ABSENT); this finishes it.

**Fix.** `factors_inert` gains the never-computed state by name
(`not_computed`, with the reason: no odds packet, path runs no enrichment);
the brief's counts block carries it; qa renders typed states — NOT_COMPUTED /
NOT_APPLICABLE (path never runs it, the Showdown case) / PASS_NO_EFFECT /
APPLIED — instead of one NEUTRAL. Engine numeric fills stay (posture defaults
are real fallbacks) but the STATE rides beside the value in the report, per
the truthful-labels rule. No gate change.

**Second field sighting of the qa face, 2026-08-29** (from BUILD fragment
`2026-08-28_BUILD_showdown_postures_and_qa_shape.md` §2, slate `2215_1g_sd`):
`F1 NEUTRAL: no implied totals reached the projections` printed again against
a Showdown brief, and the module has no F1 at all — `grep -n
'f1|enrich|implied_total' mlb_engine/optimize/showdown.py` returns nothing.
Odds DID apply on that build, as `win_share_basis: moneyline_no_vig`, so the
line is wrong twice: it names a factor the path never runs, and it hides the
one that did. This is the NOT_APPLICABLE state in the fix list, and the
Showdown rendering should print the win-share basis in its place. Recurrence
is the point — the class was filed 08-27 and shipped a misleading line again
the next build, on the surface a session reads under time pressure.

**Third field sighting, 2026-08-30, and it adds the BRIEF half this entry did
not have** (from BUILD fragment `2026-08-30_BUILD_showdown-ranks-on-raw-appg.md`,
slate `1920_1g_sd`). Same line, third build: `F1 NEUTRAL: no implied totals
reached the projections` printed against a brief carrying
`construction.win_share_basis: moneyline_no_vig`. The moneyline reached the
entry ALLOCATION across game states and never reached a projection, so the qa
line is wrong in both directions again.

**What is new: the Showdown brief carries no `enrichment` key at all.** Not a
false value, an absent one. `signal_applied`, `counts` and `factors_inert` are
the three fields SKILL.md instructs the operator to read before presenting
anything, and on this path they do not exist. There is nothing to read and no
statement that there is nothing to read, so the operator's only signal is a
MISSING field, which is the weakest possible one and the failure R172 fixed
pointed the other way (there, a value guard wrote `projection_tier: "enriched"`
onto a permanent record for a build with zero external data).

**Fix addendum, and it is a precondition of the Fix above, not a parallel item.**
qa cannot render a typed state the brief does not carry, so the Showdown brief
writes `enrichment: {applied: false, reason: "showdown path ranks on
AvgPointsPerGame", ...}` and qa's NOT_APPLICABLE reads it rather than
special-casing the format. Ship this half FIRST if the rest of R237 waits: it is
close to one dict key, and a truthful label that says "unenriched" is worth more
than a missing one. The measured cost of the ranking itself is R249's second
sighting, filed there and deliberately not duplicated here.

### R244. R157's rescue opens three caps when the 1.0 sanity check already names the one that binds, and the first value that certifies is not the value to ship (P1, S; the CLAUDE.md half needs a quiet window) | new 2026-08-27, merged from BUILD fragment `2026-08-27_BUILD_container-bank-and-r157-single-cap.md` §§2-3; feeds R203's design

**What.** On 1905_5g the R157 trigger fired and the delegated remedy says move
all three exposure caps; the 1.0/1.0/1.0 sanity check's REALIZED exposures
already showed pitcher and stack inside their posture caps, naming
`max_player_exposure_pct` as the only possible bind without a search. Opening
that one cap certified first try. Bisecting downward afterward on the same
bank: 0.43 DOMINATED 0.50 outright (higher apex total, better washout
retention, ten stack shapes against eight), and tightening the SP cap BELOW
its posture default bought 7 washout points for 0.8% of ceiling with apex-best
unchanged — a measured knee, ledger 3.5's maxim arriving as data.

**Why.** The delegated remedy as written ships more concentration than the
same certification requires. Also measured for the record: `mme`'s 0.35 at 14
entries is `floor(0.35*14)=4`, a much harder constraint than the same fraction
at 150 entries — whether caps should ladder by entry count is a question the
entry carries for Ben.

**Fix.** (a) CLAUDE.md's R157 paragraph gains: read the sanity check's
realized per-axis exposures, open ONLY the cap it names, then bisect downward
from the first certifying value (one extra build on a warm bank) and record
the frontier row chosen. Contract edit, no other session live. (b) The
feasibility report prints the per-axis realized-vs-cap table on the sanity
run so the reading is mechanical. (c) R203 implements the same loop when the
supervisor takes this class; noted on its entry via this number.

## Workstream 5 — Delivery, manifest, and preflight evidence

What reaches outputs/ and what the record claims about it. R96 CLOSED and
migrated 2026-08-11 — every delivery path now records or self-labels, the
reverse check exists, and the salary file is staged — so this stream carries
no P1. R36 is the standing adjudication container: its
still-open findings map F1m/F3m/F6m/F14 here, F2 to the swap side of
Workstream 4, F10 to Workstream 4, F8 to Workstream 1's family, F7 to
Workstream 3, F12 to Workstream 6.

### R36. Adjudication of the 2026-07-29 red-team critique: what is real, what is not, and what is already on the board | new 2026-07-30

Every line-number claim was verified against the tree before ruling, because this repo has been burned three times by critiques citing stale lines. Findings 3-14 were checked in code; 15-23 are strategy and were checked against this backlog.

**ACCEPTED and LANDED this session:** Finding 4 (R34), Finding 5's first half (R35), Finding 13's two specific contradictions (SKILL.md frontmatter promised "certified ... for both Classic and Showdown"; a paragraph still claimed the audit runs `test_core` only, stale since 07-28 — both corrected, and CLAUDE.md's own suite list was one behind too).

**LANDED since:** Finding 11 (2026-08-01, the `reuse_penalty` term removed from the joint allocator). The adjudication, Ben's decision and the test requirement migrated to `CHANGELOG.md` under that date, per the backlog/changelog contract.

**ACCEPTED, filed, NOT built:**
- **Finding 10 (P1, M).** The candidate prefilter keeps one representative per primary stack and per SP pair up to `max(6*E, 40)`, and there is NO retry on the full bank: the single `milp()` call is the only one, and both production callers return on first failure. Worse than the critique states: on `scipy_status == 2` the error reads `"entry-level joint MILP proven infeasible"` and the binding-constraint diagnosis is computed from the FILTERED sets, so "N distinct lineups x cap < entries" can be a fact about the reduced problem only. That is CLAUDE.md's reserved "proven infeasible: <constraint>" label attached to a proof about a problem nobody asked to solve. The time-limit branch already names the prefilter; the infeasible branch must too. Fix: one bounded expansion pass on the full bank before the word "infeasible" is used, and never diagnose from post-filter sets. **Reconfirmed 2026-08-04 (audit) with a live reproduction of the starvation itself:** coverage is guaranteed ONLY for single-option entries (`contest_allocator.py:680`, `if len(options) == 1`) — a 60-candidate bank where an entry's only 2 compatible candidates score below the keep line drops both and reports "proven infeasible … Active:" with an empty controls list, on a problem that is feasible unfiltered. That 2+-options-but-all-filtered shape is exactly the late-swap pinned-entry case (targeted candidates built around locked players score below the general bank). The fix gains a floor: keep the top-K (K>=2) compatible candidates per entry, and name any entry whose compatible set the prefilter emptied. R84's per-entry compatible-in/kept counts are the visibility half. **Premise note, 2026-08-09 (R47), updated 2026-08-10:** the late-swap half of the reasoning above is measured against a bank the solve never saw. The swap's targeted candidates were mostly being DISCARDED before the prefilter ran (`drop_stale_jobs`), so "targeted candidates score below the general bank and get filtered" describes a starvation that had a second, larger cause upstream. **R101 landed 2026-08-10 and the upstream cause is gone; the re-measure is still owed.** It was not done in that commit and could not have been: the 2026-08-03 inputs no longer rebuild that run's projections frame (`data/reference/` has moved since), so the shape has to be measured on the next live swap that produces a pinned entry with 2+ compatible candidates, against the union bank the solve now actually receives. Until that measurement exists, treat this item's late-swap justification as UNSIZED rather than as reproduced. The single-entry coverage floor it proposes is unaffected either way.
- **Finding 8 (P1, S).** `melt_showdown_salary_csv` flips the whole pool to `declared_starters` on ANY declared row, with no per-team completeness test. A one-sided partial does hard-error on the `len(teams) < 2` guard, so the critique slightly overstates the worst case, but a partial covering both sides yields a tiny biased pool and `build_slate.py` then falls back to the generic bank on that pool rather than refusing. Per-team completeness, projected candidates labelled for incomplete teams, block promotion not generation.
- **Finding 7 (P1, S).** The supplied-feed acceptance threshold is `covered * 2 < len(slate_teams)` — strictly under half rejects, so exactly 50% is ACCEPTED and overwrites the shared `data/slates/<date>/lineups_feed.json`, and the write is a bare `write_text`, not atomic, unlike every other durable write in the repo. Both true. R32 removes the need for this path whenever Ben pastes, and R29(4) added `--salary`; what remains is keying the staged feed by pool signature and snapshotting it into the run. **Addition (2026-08-01, GF spec A-29):** the fix ships with the boundary test the suite lacks — a feed covering exactly half the slate's teams, which today is ACCEPTED by `covered * 2 < len(slate_teams)`.
- **Finding 12 (P1, S).** `wheel_fetch.py` reads no lock file, resolves the latest release for a bare name, has no `hashlib` at all, decides completion from `os.path.getsize`, and never checks for `206`/`Content-Range`. A server ignoring `Range` returns 200, the full body is APPENDED to the partial, size then exceeds the target, and it prints `done` and exits 0 on a corrupt wheel. The critique's doc quote is slightly off (SKILL.md attributes hash verification to `env_probe --install`, which really does pass `--require-hashes`) but it introduces the fallback in the same breath and never says the fallback drops both the pin and the hash.
- **Finding 1 (P1, M) — accepted in MODIFIED form.** The factual claim is true: a missing, unreadable or five-hour-old feed still returns `upload_ready` at exit 0, and two tests pin it by name. **Rejected:** blocking on a missing feed. At T-5 that stops a legal file over an absent input, which is the process preventing the lineup. **Accepted:** an unverified roster must not be LABELLED `upload_ready`. R34 built the mechanism (a distinct verdict at exit 0), so the remaining work is to route missing/stale/unreadable live evidence into it as `UNKNOWN` rather than a warning. That is the honest version and it costs no build. **Addition (2026-08-01, GF spec F-11):** when that routing is built, the staleness constant (`FEED_STALE_MINUTES = 90`, `preflight_upload.py:758`) becomes policy scaled by minutes-to-lock — a 90-minute-old feed is one fact at T-180 and a different one at T-10 — with the constant kept as fallback when no lock time is known.
- **Finding 3 (P1, S) — accepted in MODIFIED form.** True that a missing odds or weather map is auto-added to `assume_gates` and an assumed `None` becomes `True`, after which `workflow_valid` passes. But the assumption IS recorded, in `diagnostics.json` and on stderr, so it is disclosed rather than hidden. The real defect is narrower and the critique missed it: `assumed_gates` reaches neither the operator brief's `gates` block nor the upload-manifest record, and `certification` is stamped `"certified"` off `workflow_valid` alone. Verified on a real 07-29 delivery: the record says `certified` with the odds assumption invisible. Fix: carry `assumed_gates` into the brief and the manifest record. Renaming the boolean scheme is Finding 21's job, not this one's.
- **Finding 6 (P1, S) — accepted in MODIFIED form, and the critique's diagnosis is wrong on half of it.** The bank-cache half is FALSE: `bank_cache.save()` already does R22 reload-and-union, and `tests/test_core.py` does model load-before-write, just sequentially rather than with threads. The manifest half stands: `record_delivery` and `stamp_manifest_status` are both unlocked read-modify-replace. And the dangerous lost update is not a lost record, which fails closed, but a lost SUPERSESSION: an obsolete file left sitting at `upload_ready` as the apparent answer to "which file do I upload". Append-only per-delivery records plus a derived index is the fix. **Two additions (2026-08-01, GF spec F-14 second half plus the recordable sliver of F-25, both verified):** (1) **CLOSED 2026-08-16 with R129, migrated to CHANGELOG.md** — `read_manifest` turned an unreadable or corrupt manifest into an empty one, erasing the difference between 'never existed' and 'corrupt', and the next `record_delivery` os.replaced the corrupt original away with every prior record's supersession history. Corrupt is now its own read state, the bytes are quarantined to `upload_manifest.corrupt.<utc>.json` before any write, an unquarantinable manifest refuses rather than overwrites, and `verify_manifest` stops passing on one. **Landed with it, and it belongs to this finding rather than to R129:** the lost-supersession failure this entry names arrived through a second door nobody had looked at — `stamp_manifest_status` matched the first row with a given sha256 and overwrote its `status`, so a SUPERSEDED row came back as `upload_ready` (and as `blocked`, after which the supersession check could never fire for that file again). Not a concurrency race at all; one writer, one process. Both readers now share `match_manifest_record` and a superseded row keeps its status. (2) `record_delivery` hashes only the delivered file; the salary CSV that produced it is unbound. Add `salary_sha256` to the record so provenance names the exact pool snapshot — pure recording, no gate change. **Still open here:** the append-only-plus-derived-index redesign, its unlocked read-modify-replace concurrency half, and (2).
- **Finding 14 (P1, S) — accepted, and it is the sharpest thing in the document.** The 546-test suite does pin permissive behaviour by name (`test_a_missing_feed_degrades_to_one_warning_and_never_blocks`). A large green count is not safety when the asserted contract is wrong. Those tests were written by earlier sessions of mine, which is precisely why the observation lands. What it argues for is a promotion-state matrix (fresh / stale / missing / corrupt / wrong-slate / partial / waived), and that is Finding 21's state machine plus R34's verdict split.
- **Finding 2 (P1, M).** Late swap prints every pool blocker and proceeds, and its lineup gate is `bool(confirmed_teams)`, so one confirmed club passes that axis for a whole slate. Both true. Note the deliberate exception this must not undo: R27 made the platoon-staleness blocker print-and-ship on purpose, because blocking a T-minus swap on reference age is the process preventing the lineup. So the fix is per-blocker-class, not "blockers block": R26's postponed-game exclusions must stop a swap; platoon age must not. Derive lineup evidence per rostered team.

**REJECTED:**
- **Finding 13's general thesis** (compress the instruction layer). Already disposed as R9, twice. R9a landed deliberately at 145 lines with two sequencing holds, and this backlog explicitly rejects under-30-line absolutism because CLAUDE.md carries the money wall, the DK wall and the labels rule, which should not be softened into judgment at a money boundary. The byte counts are accurate (CLAUDE.md 12.6 KB, SKILL.md 36 KB, MLB_Classic.md 47 KB, this file 139 KB) and I made SKILL.md longer today, knowingly, to document the paste path. The specific contradictions were real and are fixed; the size argument is not new information.
- **Finding 17** (correlated scenario engine) and the sim ladder generally. Already on the do-not-build list until R13 scales the stakes and R10's ownership is calibrated. Unchanged.
- **Finding 15** (replace APPG with an event-rate projection foundation) is **not rejected but deliberately not filed as actionable yet.** It is correct that APPG is the foundation and that no amount of multiplicative correction makes it a forecast. It is also the largest project on any version of this list, it competes directly with R10 for the same scarce thing (archived slates to grade against), and R10 has a met gate while this has no baseline to beat. Filed as a named dependency of R13's scale-or-freeze decision rather than as work.

**ALREADY ON THE BOARD, no new item:** Finding 16 = R10. Finding 18 = R1(c) plus the parked `ticket_count` rows. Finding 19 = R22 plus R25's shard question. Finding 20 = R25's minimal-repair fast path, still open and explicitly out of scope on 07-29. Finding 21 = the honest frame for Findings 1/3/14 and worth its own design pass before any of them is built piecemeal. Finding 22 = R12's `loop_state.json`. Finding 23 = R10 plus the archival runbook.

**Two things the critique found that no prior review named, both mine:** three files under `outputs/2026-07-29/` have no manifest row at all, and R29(2) introduced a fourth path to that state — a promotion refused after the mirror returns 3 before `record_delivery`. Default preflight hard-fails an unrecorded file, so it fails closed, but leaving a file in `outputs/` that looks like a delivery is untidy at best. It should be written as `DO_NOT_UPLOAD_*` or removed. Filed here, not fixed.

### R120. A delivered upload-ready file names a run directory that does not exist on the mount (P2, S) | new 2026-08-14, audit session

- **What:** `outputs/2026-08-13/upload_manifest.json`'s 1310_6g row is
  `upload_ready` with `run_id 20260813T164738Z_8ca54fa4` — no such directory
  exists under `runs/` (302 run dirs checked). Separately, the 2207_2g run's
  `manifest.json` records `inputs.*.source_path` under a DIFFERENT session's
  container mount. Build-contract item 4 makes `runs/<run_id>/final/` the
  immutable certified artifact; this delivery's diagnostics, projections and
  inputs are unrecoverable from the mount. Related record fact for ARCHIVE:
  the 1507_3g ledger fragment names `b8a3ef7c…` as the delivered file while
  the manifest shows it superseded by `59a69f4a…` four minutes later — the
  manifest wins.
- **Fix:** the mirror/record step verifies `runs/<run_id>` exists under the
  repo root at delivery time and refuses (or copies the run dir in) when it
  does not; manifest paths recorded repo-relative. Recording only, no gate
  semantics change. Rides the R36 F3m/F6m manifest batch.
- **Audit fields.** Moves: robustness (evidence integrity). Evidence: V2
  (manifests read; runs/ enumerated). Falsifier: if the run dir surfaces
  under an archival move the audit missed, downgrade to a doc note. FOSS:
  stdlib. Owner: none. Rollback: drop the check.

### R124. Guaranteed delivery: a legal-but-uncertified file is mirrored and named, never hidden behind `DO_NOT_UPLOAD_` (P1, M; the mirror+rename half is S and lands alone) | new 2026-08-14, merged from BUILD fragment `2026-08-14_BUILD_delivery-guarantee-autonomy-enrichment.md`

- **What:** on 1810_3g, six build attempts failed a DIFFERENT gate each,
  serially (~40s per round trip); runs 4, 5 and 6 each wrote a file
  `verify_export.py` passes clean — "17 classic entries, all checks clean" —
  and a DK-uploadable file existed 6.5 minutes before lock. It sat at
  `candidate/DO_NOT_UPLOAD_DKEntries.csv` (`execution_pipeline.py:387`), so
  the session reported "no certified file" and proposed skipping the slate;
  Ben had to ask. `DO_NOT_UPLOAD` conflates two facts: FAILED THE THREE
  GATES and IS NOT A LEGAL DK FILE. Only the first was true. Ben's own
  framing carries the priority: "the worst possible scenario is you not
  building any portfolio."
- **Fix, in the fragment's value order, adopted:** (a) when gates fail but
  the export passes `verify_export`, mirror it to `outputs/<date>/` as
  `DKEntries_<tag>_UNCERTIFIED_<run>.csv` and NAME it in the refusal
  payload; reserve `DO_NOT_UPLOAD_` for files that fail `verify_export`.
  (b) `--deliver-always`: never exit without either a certified file or a
  labeled uncertified legal one, stating which. (c) R89's single-pass
  blocker collection rides this item — pool, posture, feasibility, and
  pre-export blockers reported as a set, because six serial round trips is
  most of a T-10 window. **Boundary the fragment states and this entry
  keeps:** the label bends, the gates do not — a gate failure downgrades
  the label, never withholds the file, and never relabels it upload-ready.
  Truthful labels are exactly what make this safe; "upload-ready" stays
  reserved for the certified export, per CLAUDE.md.
- **Audit fields.** Moves: robustness, autonomy, speed. Evidence: V2 (three
  verify_export PASSes in the fragment; candidate path verified in tree).
  Acceptance: a fixture build failing one gate mirrors an `UNCERTIFIED_`
  file, names it in the refusal, and preflight still refuses it as
  unrecorded/uncertified unless Ben forces — the money wall unmoved.
  Falsifier: if `verify_export`-clean-but-uncertified files turn out to
  carry defect classes verify_export cannot see (beyond the gates' own),
  the rename half survives and `--deliver-always` is re-scoped. FOSS:
  stdlib. Owner: none (labels only; upload remains Ben's manual act).
  Rollback: revert the naming; gates unchanged throughout.

### R89. Checkpoint and artifact UX (S) | audit 2026-08-04

One consolidated, ordered `checkpoint["blockers"]` list — contest identity, exclusions, feasibility binding-constraints, and joint-allocation verdicts live in four payload keys today, only some reaching warnings, against the contract's "one Blockers line where every blocker maps to an engine action". Chmod `runs/<run_id>/final/*` read-only at promotion so the immutability contract survives a stray shell, not just convention. (The lineup-gate half of this item shipped with R53 on 2026-08-04: the evidence is now per-team batting-order counts off the assembled frame.)

**Rider 2026-08-14 (audit, from the delivery-guarantee fragment; rides
R124):** the collection is not just consolidated but SINGLE-PASS across
pool, posture, feasibility, and pre-export — on 1810_3g six sequential
blocker round trips at ~40s each consumed most of a T-10 window, one gate
per attempt. Nothing about these checks requires them to be serial.

### R11. The bounded skeptic pass (P2, S) | was G2, constraints tightened by RC 2.3

- **What:** one fresh-context review of tonight's artifact (delivered CSV, manifest, brief, preflight JSON only), answering five fixed questions (most-exposed player and scratch damage; near-duplicates within one contest; geometry vs contest type; what was relaxed; the one most likely way this portfolio misses) and stopping.
- **Why:** it is the adversarial view scoped to where it pays, and it is the LLM-shaped complement to the deterministic gate: preflight checks facts, the skeptic checks sense. RC 2.3 independently specified the same two-stage design, which is confirmation the shape is right.
- **Fix:** implement as a skill section chained after the build when T > 20 minutes; it may downgrade the manifest status to `blocked` with a stated reason, it may never edit lineups, and it is skipped by rule inside T-20. Cap it at one pass. Done when: a planted wrong-contest fixture and a planted scratch are both named; clean slates cost one PASS line and under a minute.
- **Rewritten 2026-08-14 (audit, from BUILD fragment
  `2026-08-14_BUILD_adversarial-qa-pass.md`; the entry above stands as
  history, this note is the current shape).** Two tiers, and the cheap one
  is not the weaker one — both of that day's certified-clean holes (F4
  inert on 54 hitters; Jackson Jobe at 100% exposure on a 1-start sample)
  were detectable from the build's own artifacts with no network: (1)
  **Tier 1, `tools/portfolio_qa.py`, deterministic, always runs after
  delivery, never gates it** — inert enrichment factors, exposure
  concentration (any player >= 90%; single point of failure), known-problem
  names (a small registry seeded from fragments and the ledger: Valencia
  recurred within 48 hours of being filed), nonzero relaxation counts,
  small-sample APPG flags; findings written into the brief beside the
  portfolio. (2) **Tier 2, browser, time-permitting**, descending the
  exposure ranking with a floor at 50% (ten page loads, not twenty-seven),
  for what Tier 1 raises but cannot answer: workload/innings limits, injury
  returns, bullpen usage, venue weather. **Four constraints adopted
  verbatim as the design's walls:** QA never gates delivery (the failure
  mode designed against is "no portfolio"); at most 2 remediation
  iterations and a finding earns one only by naming a player and a
  falsifiable reason (that day's whack-a-mole ran 6 builds + 6 swaps
  converging nowhere); DKSalaries always wins (external data informs an
  exclude, never overrides eligibility); truthful labels — a clean pass
  says clean and stops, and no finding is ever "raises win probability".
  Tier 1 does not depend on the Tier 4 FanGraphs decision; it can land now.
  The `weather_gate_passed`-is-assumed observation feeds R36 F3m's
  assumed-gates recording. Priority unchanged pending R114/R116/R117 —
  the gate-truth fixes come first so QA audits a build that is already
  honest about itself.
- **Moved to Tier 1's tail 2026-08-16, and the double listing resolved** —
  this entry had been named in Tier 5 AND Tier 6, and the Tier 5 note
  claiming its R114/R116/R117 gate fully cleared was false on R117, which is
  open in Tier 1 (a note asserting a state it did not check; the R133
  lesson). The move stands on three facts: `tools/qa_portfolio.py` (R134) is
  this item's deterministic tier half-built — enrichment self-claims,
  market/Savant cross-checks, and the frontier proxies already run after
  delivery, gate nothing, and stop; the hand-run version of this pass found
  six items across two slates in one day (the 08-15 QA fragment IS this
  design executed manually); and Ben's R134 directive names an adversarial
  QA pass as the standing follow-up to every unattended build. What remains
  on the landed chassis: the known-problem-names registry seeded from
  fragments and the ledger, per-player exposure flags (>=90%),
  relaxation-count surfacing beside the findings, and small-sample APPG
  flags. The four walls above stand verbatim; the browser tier stays
  time-permitting and unchanged.

### R172. CLOSED 2026-08-30 -- the value guard no longer counts as enrichment; entry migrated to CHANGELOG.md

Key dropped from the tier list rather than made to produce richer evidence: an
internal Base cap cannot become enrichment on any evidence. The comment that
caused it (value_guard listed among "the Savant-fed blocks") is corrected in the
same commit. R172's citation was stale by ~460 lines (`4202`; the function is at
4661); its substantive claims all re-verified. What it missed: a test PINNED the
defect, so the wrong behaviour had a green guard. Gate 1468 -> 1469.

### R173. CLOSED 2026-08-30 -- a truthy pool report no longer stands in for a checkable one; entry migrated to CHANGELOG.md

`checkable = "teams" in report or "blockers" in report` guards the branch, and
both fall-through branches name a supplied-but-uncheckable report rather than
calling it absent, so the fix does not swap one false evidence string for another.
Citation was close (`1168`; the function opens at 1120, the assignment sat at
1170). One premise stale: the entry quotes "0 team(s) under NINE hitters" and
R133(3) moved that bar to `MAX_HITTERS_PER_TEAM` on 2026-08-18, so the string had
already become "under 5 hitters"; the defect was unaffected. R233 scan found one
remaining site of the shape, `if roles:` ten lines below, deliberately kept because
its keys ARE the content. R177/F16 stays open as the same family. Gate 1469 -> 1473.

### R174. The locked-team introduction ban is enforced only pre-solve; no post-export gate re-derives it from the exported file (P1, S) | new 2026-08-22, from the greenfield sixth edition; VERIFIED-read (`late_swap_manager.py`/`dk_entries_manager.py` unchanged since the review). **Rider 2026-08-27 (ed8 F-31), same batch, same argument:** `tools/late_swap.py` writes, records and promotes the swap CSV, then PRINTS the preflight command and returns success — the independent referee is optional human follow-up on exactly the path with the least time to follow up. Have the tool run the preflight (or `verify_export`) on its own final bytes and report the verdict before claiming success; the T-minutes case is where a skipped check ships.

- **What:** build-contract item 5 lives entirely in
  `_entry_candidate_compatible` against in-memory candidates;
  `validate_dk_entries_file` never receives `excluded_new_teams`, and
  `validate_late_swap_delta` checks entry-level authorization only. R72(i)
  proves this exact function class has failed open in practice — a future
  regression ships a certified file rostering a player whose game already
  started, and every post-export gate passes.
- **Fix:** extend `validate_late_swap_delta` (it already diffs rosters) to
  reject introduced player IDs whose team is in `excluded_new_teams` — one
  file-derived check closing the doctrine gap at the money boundary.

### R175. verify_export is the weaker checker on exactly the files it exists for: no contest-identity check, delivered-manifest failures downgraded (P1, S) | new 2026-08-22, from the greenfield sixth edition; VERIFIED-read (`verify_export.py` unchanged since the review)

- **What:** the swap-side checker never calls `check_contest_identity` and
  calls `check_manifest` without `delivered=`, so for a file in outputs/: no
  manifest sibling → NO check at all (preflight hard-fails), corrupt manifest
  → warn (preflight fails), no record for these bytes → warn (preflight
  fails). A swap file whose contest names contradict its geometry passes
  verify_export while preflight blocks — the R52 divergence class, on the
  multi-draftgroup Saturday, in the tool used closest to lock. Its own
  docstring claims parity.
- **Fix:** import and call `check_contest_identity`; pass
  `delivered=is_delivered_file(path)`; replicate the
  no-manifest-for-delivered fail. Durable form (both reviewers converged):
  fold verify_export into preflight as a `--parent` mode — it already imports
  20 preflight symbols.

### R176. CLOSED 2026-08-30 -- all four parts and the 2026-08-27 rider; entry migrated to CHANGELOG.md

(a) the salary gate reads the salary file via a new `validate_salary_export`, and
the entry-grid evidence drops a claim about a conjunct that cannot fail (verified
at `dk_entries_manager.py:303-305`, not assumed). (b) `caller_asserted_gates` is
extracted and derived from the merge RESULT, not a fourth list of names; the live
consequence is `tools/late_swap.py`, which has been recording two of its own four
assertions. (c) the forced-swap key is deleted, `MLB_Classic.md` with it. (d)
`mirror_error` and `delivered_sha256_error` replace two silent excepts. Rider: the
preflight re-reads the committed row and a verdict that would exit zero without
being durably recorded is now a hard failure.

Citation was stale (`1153`; the gate sat at 1154 pre-change). A test pinned the
exact false string the item filed, and a neighbouring test's precondition moved
underneath the fix. R233: three classes, 23 sites, 4 fixed, 1 named for a later
look (`contest_allocator.py:2295-2296`), the rest kept with reasons. Thirteen
mutations, one survivor that was an unreachable combination, killed at the
function. Gate 1473 -> 1489.

### R177. Empty `confirmed_hitter_ids` and None are conflated fail-open — the F16 class on a sibling check (P2, XS) | new 2026-08-22, from the greenfield sixth edition; VERIFIED-read (`dk_entries_manager.py` unchanged since the review)

- **What:** `confirmed = {...} or []` then `if confirmed:` skips the whole
  unconfirmed-hitter check, so `confirmed_teams={"NYY"}` with a contradictory
  EMPTY id set checks NO NYY hitter instead of failing every one. F16
  established None=unrestricted, explicitly-empty=nothing-allowed for the
  delta gate; this sibling reads both as "off".
- **Fix:** track suppliedness (`is not None`); confirmed team + empty set
  fails every hitter on that team.

### R178. Checker exit-contract smalls: csv.Error escapes as a raw traceback, and the declared-arm acknowledgment is Classic-only (P2, XS) | new 2026-08-22, from the greenfield sixth edition; (a) VERIFIED-repro, (b) VERIFIED-read (`preflight_upload.py`/`verify_export.py` unchanged since the review)

- **What:** (a) both checker mains catch `(OSError, ValueError)` only;
  `_csv.Error` (field-limit overflow from a corrupted export) exits 1 with a
  traceback — safe direction, wrong contract, worst presentation at T-5.
  (b) declared-arm acknowledgment keys on `Roster Position == "P"`, so on
  Showdown geometry (CPT/UTIL) every declaration lands "misdeclared" and the
  contradiction still hard-fails — R114's loop reopened on one geometry.
- **Fix:** add `csv.Error` to both except tuples; derive pitcher-ness from
  the salary `Position` column when Roster Position is CPT/UTIL.

### R191 + R192. CLOSED 2026-08-25 as R234 -- the preflight pair at the money boundary, entries migrated to CHANGELOG.md

The `--salary` auto-resolve is scoped to the file being checked and refuses rather than reaching past it; the showdown exposure line counts the PERSON and prints the captain distribution on its own line. Landed with `verify_export.py`'s copy of the same unguarded resolve, which R191 had not named, and with `person_key` unifying four hand-written copies of one identity rule. Gate 1276 -> 1292.

### R228. CLOSED 2026-08-30 -- absent evidence refuses at the promotion boundary; entry migrated to CHANGELOG.md

Fail-closed was the option taken, because the comment above the guard already
promised it. `--force-unbound` promotes, writes the unverified bind onto the
manifest row, and exits 4. Landed with the second site of the same class,
`verify_manifest`, which counted a row it had not checked. R233 found 14 sites in
the class against the one the entry named; two more are filed as R275 below. Gate
1461 -> 1468.

### R275. The preflight's own fail-open pair: an empty `contest_ids` skips the contest cross-check, and a row with no `certification` still earns `upload_ready` (P1, S) | new 2026-08-30, found by R228's R233 enumeration at this head; VERIFIED-read

**What.** Two sites, same shape as R228, one boundary later.

    tools/preflight_upload.py:1012   if recorded and recorded != actual:
    tools/preflight_upload.py:2014   if certification and certification != "certified":

(a) `recorded` is the manifest row's `contest_ids`. An EMPTY set skips the
contest-assignment cross-check entirely rather than failing it, so a row that
never recorded which contests it was for reads exactly like a row that agrees.
(b) `certification` is the row's recorded certification. Absent, the verdict stays
`upload_ready` — the one label CLAUDE.md reserves for a run where `workflow_valid`,
`selection_certified` and `allocation_certified` all passed — awarded on missing
evidence. The reachable case is a row written by an older writer or by a path that
omits the field; a delivered file with NO row already hard-fails separately, so
this is thin records rather than absent ones.

**Why.** Same argument R228 closed, at the checker Ben runs immediately before
uploading, and (b) hands out the reserved label rather than merely skipping a
check.

**Fix.** Both fail closed on absence and say which evidence was missing.
(b) needs care and its own coverage: turning currently-passing preflights into
`review_ready` changes what Ben sees at T-5, so land it with the count of existing
rows in `outputs/` that carry no `certification` and state whether any is live.
Deliberately NOT folded into R228's commit for that reason.

### R242. The preflight's salary auto-resolve reaches across dates and draftgroups before refusing; it should find the slate's own file (P2, S) | new 2026-08-27, merged from BUILD fragments `2026-08-24_BUILD_showdown_contest_assignment.md` §2 and `2026-08-26_BUILD_contest_aware_allocation_at_onset.md` §6; corroborated by the outside spec ed8 (F-11's surviving sliver)

**What.** A Showdown build promotes no run, so the resolver walks to the most
recent CLASSIC promoted run. R234 made that refuse loudly (geometry + rostered
ids) instead of hard-failing a clean file, and the 08-26 recurrence confirms
the refusal works — exit 3, message names the flag. Still a call spent at the
money boundary, twice in three days, and both times this slate's own salary
file sat in `data/slates/<date>/`.

**Why.** The boundary check should not depend on the operator hand-passing a
path the tree already holds; and "refuses correctly" is the floor R234 built,
not the ceiling.

**Fix.** Before refusing, resolve by the entries file's own evidence: match
`Game Info` date and contest geometry against `data/slates/<date>/` salary
files (both are already parsed), take a unique match, name it in the output;
ambiguity or no match keeps R234's refusal. Also from the 08-24 sighting: a
feed named `lineups_feed_<tag>.json` was on disk while the tool warned `no
lineups feed resolved` — same resolver, same fix, tag-suffixed names join the
candidate set.

### R245. `upload_manifest.json` is one file per date across concurrent builds, and a whole-file restore is not a merge (P1, S) | new 2026-08-27, merged from BUILD fragment `2026-08-27_BUILD_container-bank-and-r157-single-cap.md` §2 (a live near-miss between two same-date sessions, self-corrected); corroborated by the outside spec ed8 (F-20); cross-ref R36 F6m(2), which keeps the M-lift redesign

**What.** Two builds delivered into `outputs/2026-08-27/` from parallel
sessions; one restored a container package with `tar x --overwrite` over the
shared manifest and believed for an hour it had destroyed the other's row (it
had merged on the second pass; the first overwrite was rewritten by the other
session — a near miss, not a loss). A delivered file whose manifest row is
gone re-checks as a hard preflight failure.

**Why.** Two builds on one date is now the normal state, the manifest is the
answer to "which file do I upload," and last-writer-wins on it is the exact
concurrency class the contract serializes everywhere else.

**Fix.** Either per-tag manifests (`upload_manifest_<tag>.json`), which
removes the shared file entirely and is the fragment's own preference, or
merge-by-key on every write and restore (keep any row whose
`(delivered_file, sha256)` the incoming set lacks). The working merge recipe
is in the fragment; the sync protocol's restore section points at it either
way. R36 F6m(2)'s append-only redesign stays separate and M.

### R248. The preflight's feed matcher has no team-code crosswalk, so AZ≠ARI silently demoted ten hard checks to warnings that read as "team not posted" (P1, XS-S) | new 2026-08-27, merged from BUILD fragment `2026-08-27_BUILD_preflight-az-ari-crosswalk.md`; corroborated by the outside spec ed8 (F-33); cross-ref R82, the engine-side single boundary

**What.** On 2145_1g_sd the feed carried ARI as `team_abbrev: "AZ"` (the
documented crosswalk fact the intake front door applies); `preflight_upload.py`
has no `AZ` anywhere, reported `ARI has not posted` plus ten spurious
projected-slot WARNs, and exited 0. Verified spurious by hand-diffing DK's
`Starting` column against the feed: 10 of 10 slots match.

**Why.** The feed check is the one preflight rule that is HARD on a confirmed
lineup and soft on an unposted team, so an unresolvable abbreviation silently
buys the weaker rule on exactly the slates where the posted lineup and the
roster genuinely disagree — the case the check exists for. R175's class: the
independent checker weaker than production on its own subject.

**Fix.** The preflight cannot import the engine, so: a generated, versioned
alias artifact both implementations consume (ed8's F-33 shape), or a vendored
copy asserted equal to `team_codes.py`'s mapping by a test. Separate the two
sentences — "team not posted" and "team abbreviation did not resolve against
the feed," the second loud. Per R233, the landing entry carries the grep
enumerating every site that reads `team_abbrev` off a feed (this was the
second copy; expect a third).

**Second field sighting, 2026-08-29** (from BUILD fragment
`2026-08-28_BUILD_showdown_postures_and_qa_shape.md` §3, slate `2215_1g_sd`):
same defect, new slate, unchanged. The feed carried `away.team_abbrev=AZ
status=confirmed` with 9 hitters and the DK salary file carried `Starting`
tokens 1-9 plus SP for `ARI`; preflight reported `ARI (65 slots)` as having no
confirmed lineup and raised a 10-player "absent from a posted lineup" WARN
against a fully posted side. Hard checks clean, exit 0, so noise rather than a
wrong verdict — but noise on the one surface whose job is to be believed at
T-5, and SKILL.md already names this crosswalk as a known fact. Filed as
recurrence, not new scope: the item is unchanged and stays in slot 2.

### R266. CLOSED 2026-08-29 — shipped; see CHANGELOG.md

The preflight now counts captains per contest and warns above
`max(1, floor(pct * n))`, with the hard failure behind
`--strict-contest-diversity` and wired to nothing. Severity WARN was kept as
specified. What did NOT come with it, and is not open scope: the strict flag's
threshold and whether it ever blocks stay the Tier 4 decision this entry
always named. Reasoning, the R233 enumeration, and the two things found while
building it (the units rule, and the report-dict ordering that made `passed`
read stale) are in the changelog entry.

### R269. Re-promoting a superseded run mints a SECOND filename for identical bytes, and the old path stays blocked (P2, S) | new 2026-08-29, from BUILD fragment `2026-08-29_BUILD_late-swap-repair-gaps-and-autonomy.md` §C(3); mechanism verified at `tools/promote_run.py:191,194`

**What.** After rejecting a QA iteration on `1305_12g` the earlier run was
re-promoted. `promote_run.py` writes run-scoped by default
(`DKEntries_<tag>_<run8>.csv`, line 194; the canonical `DKEntries_<tag>.csv` at
191 needs a flag), so it minted `DKEntries_1305_12g_ef6e904b.csv` while the
IDENTICAL bytes already sitting at `DKEntries_lateswap_1305_12g_ef6e904b.csv`
stayed marked superseded and the preflight kept refusing them. Same sha256, two
paths, one blocked, under a lock clock.

**Why.** The manifest keys the delivery on FILENAME while the thing that
identifies a delivery is its sha256 — every brief states the sha and CLAUDE.md's
multi-session contract makes the sha the name of the delivery. A supersession
that survives a re-promotion of the same bytes is the manifest disagreeing with
itself about what was superseded. It fires precisely during a repair sequence,
when the operator is iterating and least able to spend a call on it.

**Fix.** Either re-promote in place (a re-promotion of a run already in the
manifest updates the existing row rather than minting a path), or key
supersession on sha256 so identical bytes cannot be simultaneously current and
superseded. Cross-ref R245 (one manifest file per date across concurrent
builds) and R120 (a delivered file naming a run directory that is not there):
the three are the same object seen from three sides, and whichever lands first
should say which of the other two it makes cheaper.

### R276. Ben's standing data-driven QA step, built as three `qa_portfolio` panels and a `--compare` flag rather than a prose checklist (P1, S-M; report-only, changes no delivered byte) | new 2026-08-30, merged from BUILD fragment `2026-08-30_BUILD_standing-data-driven-qa.md`; **Ben's dated instruction, 2026-08-30**

**The instruction, and its second half is the load-bearing one.** Ben, after the
`1605_2g` build had already certified and delivered: run the QA pass that ran on
that slate on **any** lineup build, time permitting. His own bound, stated twice
on the same slate: *"we don't want to force a change for change's sake, but if
there is something notable that we find that would change it let's do a bit of
research to uncover it."* Run the checks. Change the build on a FINDING, never on
the fact that a check ran.

**What "this level" concretely was.** Five checks on `1605_2g`. Four produced
findings, one produced a correction to the session's own work, and exactly ONE
changed the delivered file. That ratio is the argument: the value is in the
clean checks being CHEAP, not in every check moving something. The four findings
are already filed (R196's corrected Fix line, R277's neutral default, R247's
first Classic sighting, and the archetype-row validation below), so this entry is
the surface, not the findings.

**Why a tool and not a checklist.** A checklist that depends on a session being
curious will decay, and `qa_portfolio.py` is already the adversarial surface: it
already reads the brief and the delivered bytes, already prints section 1 from
the artifact, and CLAUDE.md already calls it a report and never a gate, so
nothing here can block a delivery.

**Fix, three panels and one flag.** (a) **Neutral-default RANK check.** The brief
already carries `enrichment.neutral_default` with `in_pool` and `at_neutral`
counts and the named players (`execution_pipeline.py:3864-3883`). It does not say
where the neutral value RANKS among the MEASURED members of the same pool. Print
the multiplier distribution and flag when a neutral default lands above the
median measured peer. This is the panel that surfaces R277 with no cleverness
required, and it is the one to build first. (b) **Payout-breadth vs
construction-mode consistency.** The archetype table already carries
`payout_breadth`; `WTA_CONSTRUCTION_SHAPES` already decides the MILP mode;
nothing compares them. Flag any contest whose resolved shape takes WTA
construction while its own `payout_breadth` exceeds a bar. On `1605_2g`
`single_entry_gpp` carries 0.01 and the entered contest ran 0.235, a 23x gap, and
no surface said so. **This panel depends on R196's remainder:** it can only be
truthful once the table can express a single-entry contest with a broad curve.
(c) **Remedy-validity check**, lowest value of the three and listed last for that
reason: at minimum the FanGraphs warning stops claiming staleness for an arm
absent by qualification (this is R277(b) seen from the review side; whichever
ships first makes the other cheaper). (d) **`--compare <other_brief.json>`.**
`qa_portfolio` already prints the frontier and both proxies; what is missing is
comparing TWO briefs in one invocation. On `1605_2g` that comparison was a
hand-written grep across two `_qa.out` files, which is exactly the kind of cost
that stops a check from being run under a clock. Verified at this head:
`tools/qa_portfolio.py` takes seven arguments and none of them is `--compare`.

**Time-boxing, which decides whether this survives contact with a slate.** The
T-schedule in CLAUDE.md governs and this does not amend it; what it needs is an
explicit precedence rule, because on `1605_2g` the checks ran AFTER delivery and
that was the right order. A certified, preflight-clean file is delivered FIRST;
the QA pass never sits between a passing preflight and Ben's hands. Inside T-20,
panels (a) and (b) only, both reads, no rebuild. Inside T-10, no checks at all,
per the existing instruction to approve on posture defaults. **A finding
discovered after delivery is REPORTED as a finding, not acted on, unless the
clock genuinely allows a rebuild AND a re-preflight.** On that slate the R277
finding arrived near T-10 and was deliberately not acted on, and the call was
stated in the delivery report rather than buried, which is the behaviour to keep.

**One thing this entry does not do:** check 5 of the five (re-run the inference a
reference-table edit is supposed to drive, with no `--postures`) needs no code. It
is one re-run and it belongs in whatever procedure owns archetype-row additions,
which is R196's. Filed there, not here.

## Workstream 6 — Infrastructure, tests, environment, coordination, and docs

The gate that proves the tree is sound, and the hygiene that keeps sessions
from colliding. R62 is CLOSED and migrated — its honesty halves landed
2026-08-10 and the fixture vendoring landed the same evening, so the paste suite
now runs off tracked fixtures and the stream no longer carries a P1. R109 is the
new entry — the mount's unlink refusal, which is one fact wearing several
faces (stale git locks, `rm` reclaiming nothing, `cp` failing over an existing
file) and worth reading once before improvising against it. R91 is the
systematic form of half this stream; R79 is its worked example list. R9 and
R12 are the context and process ideas; they slot in opportunistically.

### R265. The paste tools' zero-network contract is asserted on the module-scope import graph while both reach the fetchers at call time (P2, XS) | new 2026-08-28, found while landing R236; VERIFIED-read, no field incident

**What.** `test_paste_lineups.test_the_zero_network_contract_holds_TRANSITIVELY`
imports the paste tools in a fresh interpreter and asserts that no
connection-capable module is in `sys.modules`. Both tools pass, and both import
`live_data_adapters` -- which pulls `urllib.request` at module scope -- LAZILY
inside a function: `paste_lineups.py:721` for `salary_game_times`, and
`paste_odds._slate_games` for the same helper. So a paste RUN does load a live
HTTP client; nothing calls it, and the test cannot see it.

**Why.** The claim is true in the sense that matters (nothing fetches) and
imprecise in the sense the test asserts (the graph is clean). That gap is the
thing R59 wrote this test to close, arriving one level down, and the test's own
docstring says the contract "is about the whole graph and not one file". A
future reader trusting the test would be trusting a weaker fact than it states.

**Fix.** Either state the claim precisely -- the test asserts no network import
at MODULE scope, and the run-time graph is a separate question -- or move
`salary_game_times` and the two helpers it needs (`_record_get`,
`_load_salary_players`) to the network-free `slate_intake_manager`, re-exporting
from `live_data_adapters` so all eight existing callers are unchanged. The
second is the `team_codes` precedent and is what R264 wants anyway; land them
together.

### R78. Environment floors and lock brittleness: pandas 3 breaks the Excluded guard tests today (P2, S) | audit 2026-08-04, reproduced in container

- **What:** (a) `requirements.txt` floors admit pandas 3.x, and on 3.0.2 the suite fails 4 tests in `ExcludedColumnCoercionTests` — the fixtures write `"False"` into a bool-dtype column (`test_core.py:4816,4846,4867`; pandas-3 strict setitem, already a FutureWarning on the pinned stack) — so the class guarding the forbidden-pool-reduction rule ERRORs before asserting anything, at the same moment the engine's own pandas behavior shifts underneath it. Reproduced in this audit's container on numpy 2.4.4 / pandas 3.0.2 / scipy 1.17.1, a floor-satisfying stack. The engine's own migration surface swept small and fixture-dominated (no iteritems/applymap/append/chained-assignment hits; `.copy()` discipline held; one latent Notes-append at `execution_pipeline.py:2474`). (b) `requirements.lock` hashes are cp310-only while the repo demonstrably runs under multiple interpreters (`__pycache__` holds cpython-310 AND cpython-313 artifacts; this audit's container ran 3.11): on any non-3.10 interpreter, `pip install --require-hashes` hard-fails with a hash error rather than a named interpreter mismatch — mid-T-minus if it happens live. (c) the audit's dependency gate is import-only (`audit.py:113`), never versions-vs-lock, so a wrong-pandas env reaches the test run before anything says so.
- **Fix:** cap the floors (`numpy>=2.0,<3`, `pandas>=2.2,<3`, `scipy>=1.13,<2`); make the three fixture sites dtype-object first; add cp311/cp312 wheel hashes per pin or an env_probe interpreter assertion ("wrong interpreter: 3.13 vs lock 3.10"); have the audit report installed-vs-lock versions. Optional canary: a monthly scheduled ARCHIVE task resolves the floors into a throwaway venv, runs the audit, and drops a `docs/backlog_inbox/` fragment on failure.
- **Rider added 2026-08-23, from BUILD fragment `2026-08-14_BUILD_cowork-sandbox-disk-full-blocks-scipy.md` (swept with the merge; its content survives here because nothing else records it).** The skill's preflight (`pip install -r requirements.txt --break-system-packages`) failed at T-18 on the 08-14 2138_4g slate with `OSError: [Errno 28] No space left on device: '/sessions/<session>/.local'` — `/sessions` at 100% (9.8G used, 0 available) with the session's own home holding only 288K of it, so nothing was reclaimable and clearing pip caches freed nothing. Cost about 3 minutes of a 20-minute window. **The workaround is now the standing practice and it is documented NOWHERE in the repo:** every session in this file's history runs `TMPDIR=/tmp PYTHONPATH=.pylibs`, `.pylibs` EXISTS on the mount, and `grep -c pylibs skills/generate-lineups/SKILL.md CLAUDE.md` returns **0 and 0** (measured 2026-08-23). So the recovery lives only in operator memory, which is exactly the shape that costs a T-18 window twice. Two lines in SKILL.md's sandbox section — the install target and the two environment variables — close it, and that half is XS and independent of the version pinning above.
- **The floor cap LANDED 2026-08-17 under R147**, migrated to CHANGELOG.md; all three caps are in `requirements.txt`. Re-measured on the same stack that day: FIVE tests error, not four, since `RunSlateExclusionSeamTests` grew one after this entry was written. **(b), (c) and the fixture-dtype half stay OPEN and this item keeps its tier slot** — the cap makes a compliant install safe and does nothing about a non-3.10 interpreter hard-failing `--require-hashes`, or about the dependency gate that still checks imports rather than installed-vs-lock.

### R149. The installed skill is six moves behind and the drift check cannot see the cache a cloud session loads (P1, S) | new 2026-08-17, measured in session

- **Rider added 2026-08-23, from DEV fragment `2026-08-19_DEV_r149-pointer-round-trip-verified-checklist-installed.md` (measured on a device Cowork session, read-only).** Four things, and the first is the input (a) was missing. **A THIRD cache root exists**, distinct from both this item names: a DEVICE session loads
  `…/local-agent-mode-sessions/skills-plugin/<plugin-guid>/<session-guid>/skills`, mounted read-only in the sandbox, which is neither the repo's sibling `.claude/skills` that `skill_cache_dir` derives nor the container's `/root/.claude/skills/synced/`. It is **not derivable from the repo**, since two session GUIDs sit in the middle of it. Pointed at explicitly via `MLB_SKILL_CACHE_DIR`, the check returned `{"available": true, "checked": 2, "drifted": [], "oversized": []}`. **(b) is SATISFIED, and this is the first confirmation of the round trip:** `generate-lineups` in that cache is the 59-line pointer, sentinel present, trigger description byte-identical to the repo's at 815 of 1024 chars, so the R149 re-save DID reach it and R149's own 730-line no-sentinel measurement is superseded for this path. **mtime in that cache is not the save time** — the cached file read `2026-08-16 22:16`, two days BEFORE the re-save landed and one day before R142's commit — so read the sentinel and the description and ignore the timestamp. **A stale number in two places:** `mlb-standings-pull-checklist`'s repo description now measures **993** chars, under `SKILL_DESCRIPTION_LIMIT`, so the 1073-char figure in the `tools/audit.py` comment and in this entry is stale (the shortening appears to have ridden 189de4f, R142, with no separate commit); both need the one-line DEV pass. And the standing ask for (a): **record `cache_dir` in the terse output**, because a clean `skill_cache` line currently cannot be distinguished from one that checked a cache nobody loads. The "Also" half is closed — the checklist skill is installed in that cache as a POINTER per (c), round trip verified in-session, and the drift check moved `checked: 1` → `checked: 2` with `drifted: []`.

- **ed6 rider (2026-08-22, VERIFIED-read from a live cloud container on
  2026-08-17, realigned with (d)):** the router IS deployed — that container's
  synced cache carried a 155-line / 8,363B pointer body — but it contains no
  `skill-cache: pointer` sentinel, and `audit.py`'s `POINTER_SENTINEL` expects
  exactly that string. Today (d)'s name-blindness hides this (a cache the
  check cannot FIND reports `checked: 0`, silent-not-clean); the day (d) is
  fixed, the missing sentinel turns the deployed router into a standing
  drifted-snapshot false positive. Fix them together: teach the check that a
  body opening with the router's first content line is pointer-shaped (or
  re-save the router with the sentinel), and have it REPORT which cache root
  and which NAME it read. Also measured: `mlb-standings-pull-checklist` is
  absent from the synced cache entirely, and the router body is versioned
  nowhere in git — worth a tracked copy the account entry points at.

- **What.** Ben asked whether the loaded skill was current. It is not, and both
  halves of R142 missed this shape. The copy this session loads is a 730-line
  FULL snapshot, not the pointer R142 re-saved, and it carries no
  `skill-cache: pointer` sentinel. Its audit pin reads `928 tests`, which the
  2026-08-16 entry names as the value BEFORE that date's correction, so the
  snapshot predates R142 itself. Missing outright: the `tools/autobuild.py`
  fast path, the `qa_portfolio` adversarial pass ("Then poke holes in it"),
  the "diagnose from the artifact, never from documentation" rule and its
  read-the-clock half, and R143's lineup-source ranking. Current and correct:
  the trigger description (byte-identical to the repo's, so triggering is not
  affected), R32 paste intake, the preflight exit codes, and the Showdown
  review-grade labelling — which is the 2026-07-24 snapshot's worst failure
  already fixed.
- **Why nothing warned, and this is the part worth the P1.**
  `audit.skill_cache_dir` resolves `root.resolve().parent / ".claude" /
  "skills"`, which assumes the repo and the cache are siblings. In a cloud
  Cowork session the repo is on the Windows mount and the cache is in the
  CONTAINER at `/root/.claude/skills/synced/`, so the device-side audit
  reports `available: false` and goes quiet. That is its silent-rather-than-
  false-clean rule working exactly as designed, and it is still blind in the
  one session shape where the drift matters. Pointed at the real path with
  `MLB_SKILL_CACHE_DIR` it fires on the first try:
  `drifted: [{skill: generate-lineups, reasons: ["body"]}]`.
- **Also:** `mlb-standings-pull-checklist` is absent from that cache entirely,
  so its half of R142 cannot be verified from here at all.
  **HALF CLOSED 2026-08-19.** A device session installed it as a POINTER and
  verified the round trip in-session (sentinel survived, description identical,
  the drift check moved from `checked: 1` to `checked: 2`, `drifted: []`), and
  its repo description measures 993 characters, not the 1073 this entry read on
  2026-08-17 -- the shortening rode R142's own commit, 189de4f, unremarked. It
  is still ABSENT from the CLOUD container's cache
  `/root/.claude/skills/synced/` (read 2026-08-19 23:38Z, an hour after that
  install), so the bullet is closed for the desktop and open for a cloud
  session.
- **Fix:** (a) `skill_cache_dir` tries a short ordered list of known cache
  roots instead of one derived path, and REPORTS which it read, keeping the
  silent-not-clean rule where none match; (b) re-save the installed body as
  the pointer and confirm the sentinel survives the round trip, since R142's
  re-save demonstrably did not reach this cache; (c) the design question
  underneath both: there is more than one cache, so a re-save is a thing that
  can miss one and the pointer is the only shape that is safe by construction.
  If that holds, the audit check is a backstop and the pointer is the
  mechanism, which is the reverse of how R142 wrote it up.
- **(b) IS DONE, 2026-08-19,** and the round trip is confirmed for the first
  time. The device plugin cache
  (`AppData/Roaming/Claude/local-agent-mode-sessions/skills-plugin/<plugin>/<session>/skills`,
  a THIRD root, not derivable from the repo because two session GUIDs sit in the
  middle of it) holds the 59-line pointer, sentinel present, description
  byte-identical. Two things came with it. That cache's mtime is NOT the save
  time -- it read two days BEFORE the save that produced the file -- so it is
  not a freshness signal: read the sentinel and the description, ignore the
  timestamp. And (a) is untouched: `skill_cache_dir` still derives one path and
  still reports `available: false` from a device session.
- **(d) NEW 2026-08-19, and it is the sharper half of (a).** Even pointed at a
  cache it CAN read, the check matches nothing. It looks up `cache/<repo dir
  name>`; the repo directory is `generate-lineups`; the account skill a cloud
  session actually loads is `mlb-generate-lineups`. Against
  `/root/.claude/skills/synced/` it returns `available: true, checked: 0,
  drifted: []`, which is indistinguishable from a clean check. Two decisions sit
  under it and neither is a lookup fix. FIRST, the installed name has to come
  from somewhere the repo controls; an `installed_as:` key in the repo skill's
  own frontmatter is the cheap version. SECOND, and the real question: the
  account skill is a ROUTER, so its description and body differ from the repo BY
  DESIGN and comparing them reports permanent drift. Decide what the check
  should ASSERT about a router -- sentinel present? the three carried hard rules
  present? the path resolution still resolves? -- before making it able to see
  one. Until then `checked` and `cache_dir` belong in the terse output, which is
  (a)'s ask and the one piece of this that is purely reporting. Measured beside
  it: the installed router is now 155 lines / 8.4KB, not the ~3.5KB R142
  installed, and it has grown operational content of its own (a lock-clock
  preflight, GitHub and PAT facts, a hand-built fallback procedure) that no repo
  file governs and no check watches.

### R148(b). Handedness is reported per side while the data is per hitter (P2, XS) | new 2026-08-17, from the R142-R146 review; **(a) CLOSED 2026-08-18, migrated to CHANGELOG.md**

- **(a) IS DONE.** The default branch is read from the remote through
  `ls-remote --symref` when the fetch reaches it, `default_branch_source` says
  which source answered, and an unreadable default carries R147's classified
  reason instead of a null that read as agreement. Ben's decision half was
  already retired when the premise was corrected: the setting is changed and
  there is nothing left for him to decide. Entry and landing record in
  CHANGELOG.md. What follows is the filed text, kept because the SHAPE it
  names — a check that returns the same answer whatever the world does — is
  the thing to recognize elsewhere.
- **(a, as filed) `default_branch_mismatch` reads a LOCAL cache, so the trap it was built
  for is invisible from any existing clone.** R145 reports it off this clone's
  `origin/HEAD`, which is a copy of GitHub's default from whenever `set-head`
  last ran. On this disk that ref points at `main`, so the check returns `null`
  and always will, while R145's entry and CLAUDE.md both promised the audit
  would keep naming the trap until Ben changed the setting. The trap is a FRESH
  clone landing on GitHub's server-side default, which is `master` and stale
  since 08-04, and no existing clone can read that without a credentialed
  `ls-remote --symref` — the one call that cannot run on the device VM at all
  (R147). CLAUDE.md now states the limit honestly, which is the interim.
  **Premise CORRECTED 2026-08-18: the trap is gone.** GitHub's default is
  `main` and `master` is deleted (Ben), so a fresh clone lands on the right
  tree and R111(b) is closed. What SURVIVES is the mechanism, and it is the
  half worth fixing: `default_branch_mismatch` reads a local cache, so it
  returns `null` whether or not GitHub agrees, and it would be equally silent
  if the default were changed AGAIN tomorrow. The item is therefore no longer
  "the audit cannot see a known trap" but "the audit reports a check it does
  not perform", which is the false-signal family and argues for either doing it
  properly off `ls-remote --symref` when a fetch succeeds, or deleting the
  field and saying so. Ben's decision half is RETIRED: there is no setting
  left for him to change.
  **Fix:** take the default off `ls-remote --symref HEAD` when a fetch
  succeeded, fall back to the local ref and SAY which was read, and keep the
  check silent rather than clean when neither is available. **Or decide it is
  not worth code:** Ben changing the default in GitHub Settings → Branches
  retires the trap outright, which makes this a Tier 4 decision as much as a
  Tier 5 fix. Sequence the decision first.
  **Landed as the first half of that, with one correction to the fix as
  filed:** the fallback does NOT report a mismatch off the local ref. The cache
  is reported beside the reading under its own name, because a comparison
  against a cache presented as "the default branch" is the original defect
  wearing a label, and a cache the remote disagrees with is its own finding
  (`origin_head_cache_stale`).
- **(b) `f4_handedness_unavailable` is per-SIDE while the data is per-HITTER.**
  R143 names a side only when NO hitter on it carries `bat_side`, so a MIXED
  side is silent. It is reachable through R143's own disagreement path: DK's
  order wins, a hitter DK names and the feed did not has no prior to inherit
  from, and he gets `bat_side: ""` on a side that is not reported. The cost is
  bounded — `platoon_hand_factor` returns a neutral 1.0 for an unknown hand, so
  it is a missing prior and never a wrong one, on the handful of players a
  disagreement swaps. It is still the thing R143's own entry says this repo has
  already paid for once, named at the wrong grain. **Fix:** report the count of
  hitters without a hand per side rather than an all-or-nothing team list, and
  keep the existing key's meaning by deriving it from `count == 9`.

### R150. Does an arm in a game belong in a washout count? (P2, XS + one decision) | new 2026-08-17, measured while landing R126

- **What:** two surfaces now count a lineup's exposure to one game and they
  disagree by construction. `execution_pipeline.compute_portfolio_frontier`
  counts BATS only, because R126's definition zeroes a game's hitters and keeps
  the arms deliberately. `qa_portfolio.section_frontier`'s `game` axis
  increments once per roster spot before its pitcher check, so it counts arms
  too. Measured on the archived 06-03 grid the day R126 landed: the run reports
  16/18 entries materially exposed to SD@PHI, the axis reports 18/18. Both are
  right about what they count and the printed section now says so, which is the
  interim rather than the answer.
- **Why it is a real question and not a bug:** the two readings encode different
  beliefs about correlation. "Keep the arms" says an arm can BENEFIT from the
  script that kills the bats in its game (a pitcher's duel is exactly one game
  going cold for hitters), so counting him as washout exposure double-counts a
  hedge as a risk. "Count every spot" says a rainout, a postponement or a lineup
  scratch takes the whole game including the arm, and those are the events a
  washout count is really about. The honest reading may be that they are two
  different axes with two different names, not one axis with a bug.
- **Fix, once decided:** either qa_portfolio's `game` axis drops its arms and
  the two numbers agree, or the axis is RENAMED to what it measures (roster
  footprint) and the run's stays the bat exposure. One of the two; leaving both
  named "washout" is what this entry exists to stop.
- **Ben's, not DEV's,** because it is a correlation belief and not an
  implementation detail. Cheap either way; the cost is the decision.
- **Rides:** R11 (same tool). R136 was the other host and it shipped
  2026-08-18 without touching this: it added a THIRD count to the same screen
  (roster footprint, bat exposure, and now field share), so the case for naming
  the two washout numbers apart got stronger, not weaker. Never its own session.

### R131. Five smalls, four DEV and one Ben's (P2, XS each) | new 2026-08-16, from BUILD's 2026-08-15 2138_2g fragment; (e) added 2026-08-18 off R117

- **(a) `Solo Shot` is missing from `dk_contest_archetypes.csv`.** Two contests on the slate ("MLB $2.5K Solo Shot (Night)", "MLB $500 Solo Shot (Night)") matched no row in the 24-row file and blocked the build until postures were passed by hand. They are single-entry GPPs and the family recurs. **This is not DEV's and it is not simply ARCHIVE's:** the 2026-08-09 curated-archetypes fragment already settled the principle for this exact row — a curated row reaches `resolve_contest_shape` immediately and reranks lineups on contests entered that night, which makes it a strategy change and Ben's dated decision, not an archival write. Listed in Tier 4 beside R1c-tail so both are decided and executed in one pass.
- **(b) `fetch_slate_bundle.py --venues` takes a FILE PATH, not a venue list.** Verified 2026-08-16: the flag defaults to `data/reference/team_to_venue.csv` and the failure path warns `weather skipped: venue file not found at <value>`, so passing `Sutter Health Park,Angel Stadium` produced an empty weather block under a message that reads like a missing file rather than a misused flag. Fix either end — one line in SKILL.md, or accept both forms and say which was parsed. Accepting both is slightly better because the error message is the thing that misled, and a flag that names what it parsed cannot mislead the same way twice.
- **(c) SKILL.md should carry the iteration discipline.** Each rebuild grows the bank and changes results; past two rebuilds expect collapse and non-reproducibility; the delivery must be the newest certified run, so decide before rebuilding rather than after. All three cost time on this slate. This is the operator-facing half of R130, which owns the reporting half.
- **(d) SKILL.md should carry the dual objective** so R126's apex/washout definition survives outside a chat prompt. Sequence it after R126 lands, not before, or the skill documents a metric the pipeline does not emit. **Unblocked 2026-08-17: R126 has landed**, so the definitions to document are `portfolio_frontier`'s own keys, in the brief's exposure block, plus the `frontier:` review line. Two things the landing means this half must say rather than paraphrase: the retained percent is NOT comparable across slates and the intact count is, and the histogram is what separates two builds the gates and the retained percent cannot.
- **(e) Derive the slate tag BEFORE lighting the beacon, so claims and artifacts agree.** Arrived 2026-08-18 as R117's rider and filed here rather than landing with it: R117 was a paste parser and a brief key, and this is a claims-naming fact that shares no surface with either. The ask (BUILD fragment 2026-08-13, ask 7) is that the tag in `claims/slate_<date>_<tag>` and the tag in `outputs/<date>/` come from one derivation, because a session that lights the beacon first and names the artifacts afterwards produces two names for one slate and nothing reconciles them. Note the mutex is nominal (CLAUDE.md), so a mismatched beacon name blocks nobody and the cost is archaeology later, which is why this is XS and P2 rather than a contract change.

### R138. Bank scenario coverage: one stack family per game, stated as standing practice (P2, XS) | new 2026-08-16, from the leverage ideation fragment

- **What:** section 7 seeds scenario families from totals/park/wind, and the
  field concentrates on the top totals — the same feature every structural
  prior weights highest. When caps bind, the allocator can only choose
  mid-total coverage if the bank contains it, and today nothing states that
  as practice.
- **Fix:** one SKILL.md standing-practice line: the bank always contains at
  least one stack family per GAME, not per top-ranked game. Bank growth is
  already the always-permitted remedy under the autonomy contract; this aims
  it. R126's game-split histogram is the check that it happened; R140's
  per-family profiles sharpen the target where they exist.
- **Rides:** any session already touching SKILL.md — R131(c)(d) is the named
  carrier. Never instead of a tier item. Genuine-miss install path still has no headroom check or reclaim (P2, M) | new 2026-08-01, (a) shipped 2026-08-04 — see CHANGELOG for the four incidents and full detail

**Note 2026-08-16 (DEV), the working remedy, from BUILD's 2026-08-14 fragment (merged late; this board had recorded it as merged on 08-14 and it was not):** a live Cowork build hit `[Errno 28] No space left on device` installing scipy and the fix is now known and cheap, which changes this item from "design a headroom check" to "write down what already works." The root filesystem is a DIFFERENT DEVICE from the one that filled, and it has room: `pip install --target /tmp/pylibs` with `TMPDIR=/var/tmp`, then `export PYTHONPATH=/tmp/pylibs`, took 19 seconds and carried across every later bash call in the session. Two things this adds to the entry as filed. The Errno 28 text names `/sessions/<session>/.local`, a directory holding 288K, so the message points at the wrong place and a session reading it hunts for space in a directory that is not the problem — the shortfall this entry asks to be "named" has to name the DEVICE, not the path pip mentions. And `env_probe.py`'s ask sharpens: not just "check headroom" but "pick a writable device that has room and print the exact `PYTHONPATH` export," because printing a runnable line is the difference between a diagnosis and a fix. The SKILL.md half is a copy-paste fallback block next to the preflight. This does not by itself pull the item out of Tier 6 — the bar there is a named measurement — but it does mean the M sizing is now wrong: the remedy above is S and most of it is documentation.

- **What:** `env_probe.py` and `audit.py` now check `.pylibs` before declaring anything missing (R42(a), landed 2026-08-04 — the four data points that motivated it, one filing plus three same-day 2026-08-03 recurrences, are recorded in `CHANGELOG.md` under that date, not here, per the backlog/changelog contract). That makes the case this item was filed for — a session opening with `.pylibs` empty or genuinely short something — rare instead of common, but the remaining path is unchanged: no headroom check before installing, no named shortfall, no reclaim, and `pip` can still die with `[Errno 28] No space left on device` mid-install with nothing actionable printed.
- **Fix:** before installing, check free bytes on the overlay and the install target and name the shortfall ("need ~180 MB, have 12 MB"); on shortfall, perform the safe reclaims (pip cache purge, stale `.tmp/` contents) and retry once; point pip's `TMPDIR` at the persistent mount (confirmed the right direction 2026-08-03, but confirmed insufficient alone against a live clock — tens of KB/s extracting onto a remote-backed mount, ~12MB of scipy's 100MB+ footprint in one 45-second call). Fold in: pin every `wheel_fetch.py` call site and doc example to an explicit version (`scipy==1.15.3`, never bare `scipy`) — the bare form resolves PyPI's *latest* release and can silently lack a wheel for the running interpreter even when the pinned version has one.
- **Scope guard:** still the narrow, evidenced core of GF-spec F-22. The rest of F-22 — pyproject, CI matrix, application images — stays rejected: the audit is the CI and the sandbox is not a production platform.
- **On a solver fallback:** see the CHANGELOG entry's "Not done here." Rejected a third time on the same reasoning as the prior two — every incident so far, including this one, is an installation failure, never a `scipy.optimize.milp` solving failure.

### R91. Mutation smoke for the counted guards (S) | audit 2026-08-04

A harness applying single-line mutations — drop preflight's blank-row check, swap the showdown relax branches, delete the relax counters, invert `_cap_count`'s floor — and asserting the suite goes red for each. R54 and R79 are exactly the mutations that survive today; this is the systematic form of "a guard that cannot fail is not a guard." R51 was the founding example and landed 2026-08-04: its row-accounting check was dead code no mutation could kill, because the two counters it compared were equal by construction. Worth adding its shape to the harness — a guard whose two inputs cannot differ — since that class is invisible to line-level mutation.

**Note 2026-08-05 (DEV):** five more mutations were run by hand while landing R56 and R57, and each is a harness candidate with a known-red target. R57: drop `apply_mask=base_sources` at the correction call site (reddens the operator-Base front-door test); replace `eligible = raw.notna()` with all-True in `apply_xwoba_correction` (reddens the helper's NaN test, and reddens the front-door no-APPG test only in combination with the first, which is itself worth encoding — the two guards are independent and neither is pinned solely by the other). R56: restore `add_constraint(suppression_coefs, -inf, SUPPRESSION_LINEUP_CAP)` in place of the z row (reddens 3 of 6 suppression tests); unbound z and drop the `min()` on the counted total (reddens the capped-objective test); widen activation from `SALARY_SUPPRESSION:role_elevation` to the bare prefix (reddens the trigger test on all three inert tags). Doing these by hand is what proved they are real mutations rather than assumed ones; the point of the item is that nobody has to remember to. R55 added four more with known-red targets: drop the `Player_ID` str normalization in `_prepare_single_lineup_df` (reddens all five dtype-boundary tests); restore `cache.attempted.add(key)` in `extend_bank`'s exception handler; record every non-timeout return as attempted again; and drop the `_cleared` subtraction in `BankCache.save()` — that last one is the shape worth generalizing, because the in-memory clear looks correct on its own and only the round trip through disk shows the union reinstating it. R92, filed the same day, is another instance of R51's class: a guard reading a report key its producer never emits. R65 then produced the sharpest example yet, and it is the one to build the harness around: TWO of its four hand-run mutations initially SURVIVED. Reverting `build_slate`'s gate to `date.today()` stayed green because the pure window helper and the ET authority were each pinned while the join between them was not, and dropping the parse floor's drift branch stayed green because the message it asserted on was an accidental substring of the other branch's message. Both are invisible to a reviewer and to a green suite; only running the mutation showed them. Two harness shapes fall out: a guard split across two pinned units with an unpinned join, and an assertion whose regex is satisfied by the wrong branch. R59 added a third, and it is the nastiest: a check that measures process state the rest of the suite has already dirtied. Its transitive zero-network check diffed `sys.modules`, which is empty of `urllib.request` only in a fresh interpreter — under the full suite the diff came back clean and the check passed under its own mutation. Anything asserting on import graphs, warning registries, environment variables or module-level caches has to run in a subprocess to mean anything, and the harness should treat in-process state assertions as suspect by default.

### R79. Test-coverage batch: the guards that cannot fail (P2, S-M) | audit 2026-08-04, verified in tree

- **What:** (a) preflight exit 3 (IO/usage: "the check did not run") has zero behavioral coverage — 0/2/4 are pinned by subprocess tests, 3 is not. (b) no test performs a successful swap through `late_swap.main()` — every main() test exercises a refusal path — and the mirror-before-promote invariant is pinned by source-text `index()` order (`test_core.py:6256`), which any helper-extraction refactor silently un-pins; the score-downgrade refusal branch is self-admittedly review-only (`test_core.py:5198`). (c) the Showdown relax counters are asserted key-present only (`test_showdown.py:308`) — deleting both increments stays green (R54's enabler). (d) the DK-legality constants exist in three unpinned copies (`build_slate.py:88`, `preflight_upload.py:91`, `optimizer_v3.py:232`/`roster_contracts.py:51`); `_cap_count` earned a both-copies-agree test after exactly this class of drift, the legality trio has none. (e) `skills/generate-lineups/scripts/build_showdown_theses.py` is fail-open — it ignores `write_showdown_entries`' returned report, records `lineup_certified: False` without gating exit 0, and then `verify_template_preserved` runs against whatever sits at `--out` (a stale prior file verifies clean) — and it appears in no test, eval, or doc. (f) suppression (R56) has no test at all.
- **Fix:** one test each — exit-3; a real end-to-end swap through main() with a recorder asserting runtime call order; counter-value asserts on the synthetic showdown pool; a three-way legality-constants cross-pin; exit-3-on-failure gating plus a smoke test for build_showdown_theses (or delete it in favor of run_showdown); a suppression objective test. R91's mutation smoke is the systematic form.
- **Note 2026-08-05 (DEV):** (f) is CLOSED. R56 shipped `SalarySuppressionBoundedTiebreakerTests` (6 tests) with its fix, so suppression is no longer untested: the objective's capped counted total, the feasible-set property, the 0.75 boundary, tiebreak behavior, role_elevation-only activation, and the no-tag no-variable case are all pinned. (a)-(e) are untouched and remain the item.
- **Note 2026-08-22 (ed6, VERIFIED-read as of ac8ac05):** the line above is
  stale on two parts. (a) is PARTIALLY closed: exit 3 has two behavioral
  subprocess pins in test_upload_integrity (short `--expect-sha256`; malformed
  `--declare-pitcher`); the pure IO leg (missing file) remains unconfirmed.
  (c) was closed by R54's fix (test_showdown says so), though counter
  MAGNITUDES are still unpinned — the zero/nonzero biconditional would miss an
  under-count. (b)'s source-text `index()` pin and review-only downgrade
  branch were re-confirmed. What remains: (a)-IO-leg, (b), (d), (e), plus
  magnitude asserts on (c).

### R80. Shared-helper hygiene: forked scrub, non-atomic reference writes, BOM-blind paste reads (P2, XS-S) | audit 2026-08-04, verified in tree

- **What:** (a) `fetch_slate_bundle._scrub` (`:92`) lost the percent-encoded variant its parent covers (`live_data_adapters.py:144`), and error text containing the full odds URL persists into `slate_bundle.json` warnings — latent for hex keys, real for any key that URL-quotes differently. (b) `refresh_reference_data` and `fetch_rotowire_lineups` write validated-good files non-atomically: a mid-write crash truncates the exact file `_validate` was built to protect. (c) `lineups_from_paste` reads paste files without `utf-8-sig`, so a BOM can blind the first game's club-name cross-check.
- **Fix:** one `_scrub` in `repo_env` imported everywhere; tmp+rename writes; `utf-8-sig` on paste reads.

### R271. The documented Cowork bash ceiling is 45 seconds and the real one is ~180, and the understatement costs solve budget on every slate (P1, XS; two files) | new 2026-08-29, from BUILD fragment `2026-08-29_BUILD_late-swap-repair-gaps-and-autonomy.md`; independently re-measured by the filing DEV session

**What.** `CLAUDE.md:311` (R152's paragraph) says a Cowork `device_bash` call
"dies at 45 seconds," and `skills/generate-lineups/SKILL.md:443` builds a whole
budgeting rule on it: "one 45-second window per call... Budget the inner timeout
at 25 to 33 seconds... That leaves roughly 15 to 20 seconds of real work per
call." The real ceiling on this machine is **~180 seconds**, and `timeout_ms`
must be passed explicitly to get more than the default.

**Evidence, three independent readings.** BUILD measured it on 08-29: a request
for 450000 ms was capped and reported `Command timed out after 177999ms`, and
calls of 150-165 s completed normally. The filing DEV session re-measured the
same day with a bare `sleep 100` under an explicit 160000 ms budget: completed,
19:29:12 → 19:30:52. And this project's own operating memory has carried
"~178s" since before either.

**Why it is P1 despite being a two-file text edit.** It is not a stale number,
it is a rule sessions ACT on. A feasible joint MILP on `1305_12g` needed 53 s to
156 s and could never have finished inside a 45 s budget, so the pre-lock build
looked unsolvable when it was not — a session following the documented rule
reaches a wrong conclusion about its own slate. Same class as R76(c): the doc
that causes a wrong action rather than a wrong belief.

**Fix.** Correct both sites to the measured ceiling, state that `timeout_ms` is
explicit and defaults lower, and keep the two claims R152 got RIGHT, which are
independent of the number and still hold: backgrounding does not survive the
call (`nohup`/`setsid` both die, the log comes back empty, which reads as a
silent pass), and a killed `audit.py` strands the next commit on a zero-byte
`.git/index.lock`. Per R233 the landing entry carries the grep enumerating every
site that states a Cowork time budget. **Both files carry uncommitted foreign
edits as of 2026-08-29**, and CLAUDE.md is a contract surface, so this needs the
quiet window the multi-session contract requires rather than an opportunistic
edit.

**(b) The number is also compiled into `audit.py`'s own defaults, and that is
the site with a measurable cost.** `--gate-budget` defaults to 28 and
`--gate-ceiling` to 39, both help strings citing the 45-second figure by name
("a Cowork device_bash call dies at 45"). Measured this date: at the defaults
the split gate spends a whole call on 30 of `test_core`'s 126 units; at
`--gate-budget 130 --gate-ceiling 165` it completes all 126 in ONE call and the
entire five-suite gate in five. **The gate designed to work around the ceiling
is itself throttled by the wrong ceiling**, which is R152's own remedy paying
the cost of R152's own number. Raise both defaults with the text, and read
`MLB_GATE_CEILING_S` first where it is set.

**(c) The remedy line is unreachable on the host that owns the folder, and this
one is not cosmetic (found 2026-08-29 when Ben ran session-start step 2
himself).** `python tools/audit.py --run-tests --terse` on his Windows machine
prints `FAIL dependencies: missing ['scipy'] ... test suite FAILED in
tests.test_core, tests.test_golden_replay, tests.test_showdown (ran 1378)` and
directs the reader to `python tools/env_probe.py --install`. The vendored
`.pylibs/scipy` that makes `env_probe`'s zero-install fast path work is a
**Linux** build; it lives in the Windows folder only because that folder is what
the sandbox mounts. So on his host the fast path can never warm, and the printed
remedy means a real pip install of the locked scipy. **CLAUDE.md's session-start
step 2 is written as if the host running it is always the sandbox**, and it is
the one step in the whole start sequence that cannot be handed to Ben. Fix:
`env_probe` detects that `.pylibs` is built for a different platform and says so
by name instead of recommending an install as if the vendored copy were merely
absent; CLAUDE.md's step 2 states which host it is for. Cheap, and it stops a
recurring dead end on a command the contract tells every session to run.

### R272. Repair is not strategy: Ben's 2026-08-29 autonomy instruction, and the CLAUDE.md section that does not name the distinction (P1, S; DECIDED, needs the quiet window) | new 2026-08-29, from BUILD fragment `2026-08-29_BUILD_late-swap-repair-gaps-and-autonomy.md` §A; Ben's dated instruction, quoted

**The instruction, 2026-08-29, in Ben's words:** *"you made me intervene by
answering questions and I want you to make those changes autonomously."*

**What happened.** With a dead pitcher in 10 of 31 entries and locks at 16:05
and 16:10, BUILD raised an `AskUserQuestion` at 15:16 with two questions: which
arm goes in the six entries that could not take the obvious replacement, and
whether to ship a hand-corrected file the engine could not produce. Both were
answered "recommended option." **That is the tell: when the recommendation is
the answer, the question was the session's to decide, and asking it spent Ben's
clock inside a lock window.**

**What CLAUDE.md's Autonomy section is missing.** It classifies by *what the
engine named* (structural feasibility remedies, bank growth, pool blockers) and
by *strategy vs feasibility*. It has no REPAIR category, so a scratched player
falls through to "ask." The proposed additions, all four autonomous:

- **Replacing a player who will not play is a REPAIR, not a strategy change.**
  A scratched arm, a bat absent from a posted lineup, an IL/OUT status. The
  entered set already contains a zero; leaving it there is not the conservative
  choice, it is the damaging one.
- **Choosing among the legal replacements is autonomous.** Legality is
  mechanical and enumerable: DK slot eligibility, salary cap, game not yet
  locked, confirmed starter, not already rostered, not opposing a rostered SP.
  Rank survivors by the build's own projection (APPG where no Base exists) and
  take the top one. This is R267(a)'s filter, which is why the two land
  together.
- **A collateral downgrade needed to afford a repair is autonomous when it is
  the minimum-loss one.** Four entries needed $200 freed to fit Lynch IV; pick
  the open-game hitter swap costing the least projection and record it.
- **Shipping a hand-corrected file is autonomous when the engine cannot produce
  one and both `verify_export.py` and `preflight_upload.py` exit 0.** Labeled
  review-grade, never certified; full diff against the parent reported; sha256
  stated. A preflight-clean repair beats an engine-certified file carrying ten
  dead slots.

**What stays Ben's, unchanged, and the entry states it so the edit cannot
overreach:** any exposure or stack change with no dead player behind it;
anything needing `--force` or leaving a gate failing; anything reducing the
legal player pool; the money-and-entry wall. None of those is touched.

**Why write it down rather than rely on judgment.** Under a lock clock the cost
of asking is not one round trip, it is the remaining window. This is the same
argument CLAUDE.md's Autonomy section already makes for feasibility remedies,
extended to the case the section did not anticipate — and the reason it is a
contract edit rather than a habit is that the next session has no memory of this
slate.

**Sequencing.** DECIDED, not owed: it is Ben's instruction, so nothing waits on
a decision. It is a CLAUDE.md contract change, which the multi-session contract
allows only with no other session live, and CLAUDE.md currently carries
uncommitted foreign edits. Land it with R267(a) so the policy and the tool that
makes it mechanical arrive together; a `Decided` CHANGELOG entry carries it
until then.

### R76. Doc-truth batch: the strategy authority and the pinned references have drifted from the shipped tree (P2, S) | audit 2026-08-04, verified in tree

- **ed6 rider (2026-08-22, re-verified at ec832cf), and a re-price:** (c) is
  the one instance in this batch that causes a wrong ACTION, not a wrong
  belief — its advised workaround (pre-drop projection rows) is the forbidden
  pool reduction — so take (c) out of Tier 5 batching and land it in the next
  docs-only commit. The MANIFEST trap (a) is now PRICED: the fifth greenfield
  edition audited the WRONG TREE off exactly this scent, and three earlier
  external reviews quoted the stale seed; the 3-line banner fix costs ~150
  bytes. New instances, re-confirmed present at ec832cf: MLB_Classic.md §13
  still asserts the RETIRED checksum-manifest audit mechanism
  (`checksums_sha256_v2_24_0.json covers every active file`) and names
  `Project_Version (v2.24.0)` against the file's own v2.26.0 title; §7's
  bank-size tiers contradict `resolve_candidate_bank_size` (2x capped at 150;
  the hard-40 retired); §8 verified CLEAN against `STRATEGY_DEFAULTS`, so the
  drift is localized. Also: `docs/cowork_migration_handoff.md` is a dead doc
  (zero inbound references) that claims "read this file, in full" second in
  the session read order and instructs the R7-forbidden
  `pip install --break-system-packages` — banner it or move it to
  docs/legacy/; `docs/next_session_prompts.md` violates its own
  delete-once-used contract; the ledger header's "untracked / not in
  ACTIVE_FILES" self-description is three facts stale — that one is ARCHIVE's
  file, left for an ARCHIVE session.

- **What:** (a) MANIFEST.md still opens `PASS v2.26.0 12 modules 119 tests` with a 2026-07-16 layout table 1–9 minor versions stale per module, presented as current repo description — a fresh session grounding on root docs inherits wrong expectations (its "Still open" items shipped weeks ago). (b) MLB_Classic.md:4 cites `optimizer_v3.py v3.18`; shipped is v3.23. (c) `docs/MLB_Classic_Integration_Contract.md:36` asserts the pre-F15 exclusion seam — "excluded_player_ids … does NOT propagate to the bank. The bank will build lineups around excluded players" — the exact opposite of shipped behavior (`execution_pipeline.py:1823`, pinned by `test_excluded_players_never_enter_the_bank`), and its portfolio_controls list omits `five_stack_min_size`, `min_five_stack_share_pct`, `max_game_exposure_pct_by_game`. (d) docstring stamps trail VERSION constants in live_data_adapters (v1.2 vs v1.6), late_swap_manager (v1.3 vs v1.4), projection_builder (v1.4 vs v1.6), and dk_entries_manager's header still says "for MLB Classic v2.16.0". (e) `paste_lineups.py` — the R32 PRIMARY intake source — carries no VERSION constant and no audit version pin at all (repo_env, upload_manifest, roster_contracts, showdown* likewise unpinned).
- **Fix:** stamp MANIFEST.md "historical seed record, superseded — see CHANGELOG"; fix the MLB_Classic header line; rewrite the contract's exclusion paragraph and regenerate its controls list from `STRATEGY_DEFAULTS`; sync the three docstrings and the v2.16.0 stamp; give paste_lineups a VERSION and an audit pin.

### R77. Dead code carrying live hazards (P2, S) | audit 2026-08-04, verified in tree

- **What:** (a) the legacy paste-parsing stack (`slate_intake_manager.py:1101`: `parse_confirmed_lineups_text`, `reconcile_lineups_to_salary`, `build_player_status_table`, `pre_prune_player_pool`, `parse_declared_pitchers_text`, `emit_slate_preflight_report`) has zero callers — not even tests — yet the module docstring still advertises it as the operator intake surface; against the real mlb.com layout it assigns all 18 hitters to the last header (the exact R32 bug), `build_player_status_table` marks unparsed hitters `Confirmed_Out`, and `pre_prune_player_pool` is the forbidden pool reduction one future call site away. (b) `build_state_manager.py:485`'s snapshot trio (`snapshot_inputs`/`compare_states`/`update_build_state`) has no callers. (c) `emit_contest_routing`/`apply_script_routing=True` and `generate_positional_variant_candidates` are test-only despite being documented as operator tools.
- **Fix:** delete or deprecation-guard (a), naming paste_lineups as the replacement; delete (b); make (c) a wire-or-mark decision.

### R88. Mechanize the DK wall and key hygiene as tests (S) | audit 2026-08-04

A unit test walking mlb_engine/ + tools/ asserting every fetched URL host is in the allowlist ({statsapi.mlb.com, the-odds-api.com, open-meteo.com, rotowire.com, fangraphs.com, baseballsavant.mlb.com, pypi.org} — verified clean in this audit) and that draftkings.com occurs only in non-fetching URL emission; plus a scrub round-trip test feeding a URL-quotable secret (pairs with R80a). Runs inside the existing audit gate; no hook infrastructure needed.

### R31. `claim.py` reports a released claim as HELD, and calls tonight's claims STALE (P2, XS) | new 2026-07-29 evening, found at session start

- **What:** two independent false signals in the coordination tool, both hit at the start of the R29 session. (a) `_is_held` treats `owner.json`'s `released_utc` as authoritative and only falls back to the `RELEASED` marker when `owner.json` is unreadable. CLAUDE.md's contract says release IS writing the marker ("Release by writing a RELEASED file inside your own claim"), so a session that follows the contract by hand rather than through `claim.py release` leaves a claim that reads HELD forever. `slate_2026-07-29_sealad_sd` is exactly that: marker written 00:24:01Z, `released_utc` still null. (b) `_is_stale` compares the dates in a claim's NAME against `_today()` in UTC. After 8 PM ET the UTC date is already tomorrow, so every claim a late slate lights reads STALE within minutes of being taken, which is the one signal reserved for "Ben arbitrates."
- **Why it matters despite being XS:** this is the false-PASS family in the coordination layer. A stale-and-held reading on a claim that is neither is a tool telling an operator to stop and arbitrate when there is nothing to arbitrate, and the habit that forms is ignoring the STALE line, which is the line that matters on a genuinely abandoned claim. Same shape as R29(2) teaching `--allow-parent-mismatch`.
- **Fix:** (a) a claim is free when EITHER `released_utc` is set or the `RELEASED` marker exists, since both are contract-defined release acts and neither can be forged by accident; keep `owner.json` authoritative for who and when. (b) stale-ness should be measured from `taken_utc` against a real age threshold, or from the slate date in ET rather than UTC; a claim taken twenty minutes ago is never stale whatever the calendar rolled over to. Done when: the current `sealad_sd` claim reads free without anything being deleted, and a claim taken at 9 PM ET does not read STALE.
- **Note 2026-08-04 (audit), part (c):** `WRITE_SETS["DEV"]` (`tools/claim.py:70`) omits `CHANGELOG.md` and `requirements.lock`, both DEV-owned by contract ("DEV writes it"; every DEV change carries an entry). Another session's uncommitted changelog edit therefore classifies as foreign-dirt-outside-the-write-set, `dirt --role DEV` exits 0, and this session proceeds to write over the one file the contract most wants serialized. Add both paths in the same commit as (a)/(b). R86 (claim ownership token) rides this item when it lands.
- **Note 2026-08-10 (from the consumed sync fragment), part (d), decision first:** the engine mutex is nominal. `claim.py take engine` mutexes correctly, but `take engine_myslug` gets its own directory and blocks nobody, and sessions have routinely done the latter (2026-07-29 alone carries three `engine*` claims). Not fixed in R102 because making it real starts BLOCKING sessions that today proceed, which is a behaviour change Ben should approve rather than inherit. Options weighed in the fragment: collapse any `engine*` claim to one mutex key, or keep per-scope directories and have `take` refuse when any sibling is held. Note (a) landed inside R102's claim-sweep work in modified form (`sweep` names marker-only releases and prints the completing command; precedence deliberately NOT flipped — see that CHANGELOG entry); (b) and (c) remain as filed.
- **Note 2026-08-11, part (d) has now COST something, which changes it from a design question to a priced one.** While the R96 session held `engine_2026-08-11`, a second DEV session took `engine_branchfix_2026-08-11` — a scoped name, so `mkdir` succeeded and the mutex reported nothing — and its working-tree restore wiped three uncommitted edits from the first session (`tests/test_core.py`, `tools/audit.py`, `CLAUDE.md`). Recovery was cheap because the edits were small and re-derivable; nothing was lost that a re-run could not reproduce, and the committed work was untouched. But this is the first time the nominal mutex has silently destroyed another session's work rather than merely failing to prevent overlap, and it did it while both sessions believed they were following the contract. Two consequences worth carrying into the decision. The blast radius is UNCOMMITTED work only, which argues for a commit-early discipline as a cheap partial mitigation independent of the mutex decision. And the contract's "no checkout, reset, stash, restore, or clean while any claim you do not own is live" was not violated by the letter — the second session held *an* engine claim — which is precisely the ambiguity part (d) names. The sequencing note stands: making the mutex real starts blocking sessions that today proceed, so it is still Ben's call, but it should be re-read as "what does an overlap cost" rather than "how likely is one".

### R86. Claim ownership token (XS) | audit 2026-08-04

Write a random `session_token` into owner.json at take and echo it; `release` refuses (exit 2) on token mismatch, printing the owner's role and scope. Makes "never release another session's claim" enforced rather than advisory, pure-filesystem. Rides R31.

### R12. Loop state and the two scheduled tasks (P2, S) | was G6, minimal form of RC 1.10

- **What:** the exit-10 rerun contract and the bank cache already form a resumable goal-loop; what is missing is a small `loop_state.json` per slate (input hashes, candidates so far, entries allocated, remaining jobs, no-progress count) and the stop rule (two consecutive zero-progress slices end the loop with the best artifact and a blocker list). Plus the two scheduled tasks from the 07-25 final: the morning stage (reference freshness, platoon age, stage if salaries present, solver probe, checkpoint) and the nightly standings sweep (mine the inbox fail-closed, print the export URLs still owed with size checks). Late swap gains a feed-diff print (what changed since the parent build's feed) in place of RC 2.7's rejected watcher architecture.
- **Why:** converts operator attention into schedule using the primitives Cowork actually has, and the no-progress stop is the cheap insurance against the one loop failure mode the current prose contract cannot see.
- **Fix:** one JSON artifact written per slice; two scheduled tasks; one diff print in late_swap. Done when: a killed-and-resumed session duplicates no work; a two-slice zero-delta run stops itself with a usable portfolio; Ben wakes to a staged slate or one line saying what is missing.

### R9. Progressive disclosure: slim CLAUDE.md now (R9a), split the corpus next (R9b) (P1 for token cost, S then M) | was G5 + G8, absorbing RC 1.9/2.1; split 2026-07-27

- **What:** roughly 2,500 lines of always-loaded instruction prose for a build that takes 10 seconds, with the drift bugs to show for it (R8's stale lines). Measured against the context-engineering guidance section by section, CLAUDE.md (232 lines) splits cleanly: the Hard guardrails (40 lines), context wall, truthful labels, and authority pointers are exactly the "spend tokens on gotchas and worst-case boundaries" content the guidance says to keep; against that, the Per-slate loop (52 lines) duplicates SKILL.md down to flag-level late_swap documentation, Post-slate (27 lines) duplicates the archival runbook, Session start (26 lines) is procedure that collapses once ENGINE_STATE exists, the two Showdown sections (~45 lines) duplicate references/showdown.md and carry implementation detail, and the v3.0.0-pre seed note plus the communication-contract block restate things that are stale or already global. Duplication is what produced the line-230 contradiction: procedure living in two places means one goes stale. No generated state file exists; changing facts live in prose in three places.
- **Why:** the operating cost of this project is agent-session tokens, and the guidance is explicit: lightweight repo instructions, gotchas over restatement, progressive disclosure, generated facts over hand-maintained ones. RC targets a 50% always-loaded reduction; CC's under-30-lines target is rejected as absolutism since CLAUDE.md carries binding contracts (the money wall, DK wall, truthful labels, the preflight rule) that belong exactly there and should not be softened into judgment at a money boundary.
- **Fix, R9a (text-only, pulled forward; can land any time):** slim CLAUDE.md from 232 to roughly 100 lines. Keep: context wall, truthful labels, authority, hard guardrails, T-schedule, scheduled-task rules, the Showdown review-grade label rule and two-controls contract, and one-line pointers naming where each procedure lives (SKILL.md for the per-slate loop, the archival runbook for post-slate, references/showdown.md for mechanics, `--help` for tool flags, preflight as the sole pre-upload rule). Cut: the duplicated procedure blocks, flag-level tool documentation, Showdown implementation detail, the seed note, and the communication-contract lines that duplicate global preferences. Two holds so no line goes false early: the `--force` exits-0 sentence stays until R2 lands, and the "non-negotiable" wording change rides R5. Done when: CLAUDE.md is at or under ~110 lines, carries zero internal contradictions, and every removed procedure is reachable through one named pointer.
- **R9a LANDED 2026-07-27, at 145 lines rather than 110.** Both holds observed: the `--force` sentence changed in the R2 commit and only there, and "non-negotiable" survives verbatim on the Showdown controls for R5 to retire. Zero internal contradictions; all six pointer targets verified to exist. The 35-line overshoot is one deliberate block. Before cutting the per-slate loop I checked what SKILL.md actually carries, and three contracts were not in it: the `approve=False` checkpoint gate, the 7-day platoon staleness pool blocker, and `run_late_swap` with `authorized_entry_ids`. Cutting a contract that lives nowhere else is not progressive disclosure, it is deletion, so those became a 17-line "Build contract" block stating the five facts that hold whatever path a build takes, with the steps still pointed at SKILL.md. Reaching 110 from here means moving those three into SKILL.md first, which is a SKILL.md edit and belongs with R2's skill half. Also kept against the cut list, both on the guidance's own "gotchas" rule: the FLAT standings inbox (nowhere in the archival runbook) and the archetype-conditioning rule for ownership counts (also nowhere in it). The communication contract and the v3.0.0-pre seed note are gone as specified.
- **Fix, R9b (after R6, since ENGINE_STATE needs audit.py work):** (a) split MLB_Classic.md into a short numeric-contract file and an on-demand strategy reference; (b) `tools/audit.py --write-state` generates a ~15-line `ENGINE_STATE.md` (audit line, archive count vs the 8-slate gate, last build's enrichment counts and tier, registry freshness, untracked-file check) and session start reads CLAUDE.md + ENGINE_STATE + Quick Card only; (c) adopt the MUST-claims rule: any MUST in CLAUDE.md or SKILL.md either cites the enforcing code path or is rewritten as guidance; (d) write the 15-line HARD/SOFT tier block (was G8): HARD gates (illegal roster, wrong-contest identity, blank row, IL starter, locked game, manifest mismatch) block at any T and are all decidable from disk in under a second; SOFT gates print, ship, and collapse to one count at T-10. Done when: always-loaded tokens drop materially (measure before/after on one Classic build transcript); no MUST without an enforcement pointer; every gate greps to a tier.

### R107. Untracked residue on DEV surfaces: `tools/fetch_fangraphs_platoon.py` and the root sync tarball (P2, XS-S) | new 2026-08-10, filed during the board reorganization

- **What, two parts.** (a) `tools/fetch_fangraphs_platoon.py` has sat
  untracked since 2026-08-05 while the ledger Quick Card (4a) names it as
  the sanctioned platoon-refresh path (`--from-dir` parses a browser-saved
  page; `--fetch` is refused because FanGraphs 403s scripted pulls). A tool
  the operating docs rely on exists only as local state: a fresh clone loses
  it silently, `git status` reports it as dirt every session, and it carries
  no VERSION constant or audit pin (the R76(e) class). (b) `_stage_repo.tar.gz`
  sits in the repo root — residue of the disk-to-container tarball bridge the
  sync protocol documents — untracked and unignored, so every session reads
  it as unexplained dirt.
- **Why P2:** nothing here corrupts a build; both are recurring session-start
  noise that trains the foreign-dirt check to be skimmed, which is the R31
  failure shape applied to git state.
- **Fix:** (a) is adopt-or-delete, deliberately: adopting means reading the
  file, giving it a VERSION and an audit pin, tracking it, and carrying a
  changelog entry — an engine-claim DEV change, not a drive-by `git add`;
  deleting means the Quick Card 4a sentence moves to naming the manual
  browser-save step alone. Ben's call which, and it is STILL OPEN as of
  2026-08-12 — the file has now sat untracked for a week while the Quick Card
  keeps naming it. (b) LANDED 2026-08-12: `_stage_repo*.tar.gz` is in
  `.gitignore`. (c) NEW, same class, found 2026-08-12:
  `DFS_SYSTEM_GREENFIELD_SPEC.md` sits untracked in the repo ROOT and is
  byte-identical (sha256 `7527371d...`) to the tracked
  `docs/2026-08-10_critique_greenfield_spec.md`, so it is a second copy of a
  document that already has a home and a date in its name. Deleting the root
  copy loses nothing; it is left in place only because deletion is Ben's
  grant on this mount. Done when: `git status` at session start reports only
  genuinely foreign dirt.
- **Rider on (a), 2026-08-30, and it changes what "adopt" would even mean**
  (from `ledger/inbox/2026-08-22_BUILD_wsh-platoon-refresh-build-scoped-only.md`,
  merged to the ledger Quick Card 4a on 08-22; this half is DEV's and had no
  board entry). The tool's bare-URL default assumes the **'Projected'** stat set,
  matching the reference file's global `stat_set`. As of 2026-08-22 FanGraphs
  RosterResource gates 'Projected' behind membership, so a logged-out browser
  save returns the free **'Current Year'** table instead. Same vs_RHP/vs_LHP
  shape, different meaning. The 08-22 BUILD session refreshed WSH from 'Current
  Year' and labeled that team's own `stat_set` and `collected_via` rather than
  overwriting the file's global 'Projected' label, which is the right move and
  also means the canonical file can now hold two stat sets under one global
  label. So: adopting the tool requires deciding whether refreshes are
  member-authenticated (and where that session lives), or whether the file's
  schema carries `stat_set` per team as the 08-22 write already does in
  practice. Deleting it makes the question the manual step's instead of the
  tool's; it does not answer it. **Also still true and separately owed to
  ARCHIVE:** that refresh was BUILD-scoped to
  `data/slates/2026-08-22/reference/`, so `data/reference/fangraphs_platoon_lineups.json`
  is untouched and remains 17.7+ days old for all 30 teams, WSH included.

### R109. `.git/index.lock` goes stale on this mount and `rm` cannot clear it (P2, XS-S) | new 2026-08-10, filed from three incidents that never had a number

- **RIDER 2026-08-25, and it is R233's pattern on a hygiene item: the class is
  `.git/*.lock`, not `index.lock`.** Landing R234 cost four wasted git calls to a
  stale `.git/HEAD.lock`, zero bytes, dated 18:25 the previous evening and left by
  the ed7 session. Every git write refused with the SAME message
  `index.lock` produces — "Another git process seems to be running" — so the
  documented remedy was applied to the documented file, correctly, and did not
  work, because the lock blocking the commit was a different one. Two things this
  entry should carry. **First, the diagnosis is `ls -la .git/ | grep -iE
  "\\.lock$"` and not a check of `index.lock`;** the mount held `HEAD.lock` plus a
  `deadlock_1785618418816161105` from 2026-08-01 that nothing has ever been able
  to remove. **Second, `mv` and the commit must be ONE call:** a failed `git
  commit` recreates `index.lock` on its way out and cannot unlink it, so
  `mv`-then-look-then-commit re-loses the race every time. Fold both into whatever
  this item ships; CLAUDE.md's session-start note names only `index.lock` and
  should name the class.
- **THIRD SIGHTING 2026-08-29, and it is the argument for where the fix has to
  live.** Ben's `git commit` died on `fatal: cannot lock ref 'HEAD': Unable to
  create ... .git/HEAD.lock: File exists` — a zero-byte lock left at 14:26 by the
  BUILD session's own commit, alongside an 86KB `next-index-5.lock` from the same
  minute and the 2026-08-01 `objects/maintenance.lock` that has outlived
  everything. **The session handing him the commands read CLAUDE.md's
  session-start note, which names `index.lock`, wrote `Remove-Item
  .git\index.lock`, and cost him a round trip** — the identical failure the
  08-25 rider above describes, committed by a session that had this entry
  available and did not open it. That is the finding: **a hygiene fix recorded
  only in a backlog rider does not reach the session that needs it, because the
  moment it is needed is the moment nobody is reading the backlog.** The
  remedy is not another rider. It is one sentence in CLAUDE.md's session-start
  note naming the CLASS and carrying the sweep, which is where a session under
  a clock actually looks. Sweep, for the entry to ship verbatim:
  `Get-ChildItem .git -Recurse -Force -Filter *.lock | Remove-Item -Force`
  on Windows, `find .git -name '*.lock' -delete` on a host that can unlink.
  **Re-price: this is no longer XS-S hygiene at P2.** It has now blocked a
  commit three times across three sessions, twice after being documented, and
  the third time it blocked BEN rather than a session, which is the one reader
  who cannot route around it. Rides R271/R272's CLAUDE.md quiet window, since
  it is the same file and the same class of correction: an environment fact
  this project wrote down in a form that does not reach its reader.

- **What:** the Cowork mount grants create and truncate but not unlink, so an
  interrupted git write leaves a zero-byte `.git/index.lock` that blocks every
  later commit — and git's own documented remedy, deleting the file, is the
  single operation this mount refuses. Three incidents, none previously
  filed as an item: **2026-07-28** (74-minute-old zero-byte lock, mtime
  matching uncommitted ledger edits, cleared only with Ben's delete grant),
  **2026-07-29** (154-minute-old lock whose mtime matched the
  `ledger_2026-07-29` claim's release to the second — ARCHIVE's mini-MAX
  commit died mid-write), both recorded in CHANGELOG.md's imported record as
  incident narrative rather than as work, and **2026-08-10**, where `rm`
  returned "Operation not permitted" and `mv` worked.
- **Note 2026-08-12 (DEV, while committing R60): the premise in this entry's
  title now has a condition on it.** A fourth incident, same shape — a
  zero-byte lock dated 11:36, matching the `engine_2026-08-12_order` session,
  no git process alive. What is new is that `rm .git/index.lock` SUCCEEDED,
  because this session had already been granted Cowork's
  `allow_cowork_file_delete` for this folder (requested minutes earlier to
  consume a backlog_inbox fragment). So the mount's unlink refusal is not
  absolute; it is the default, and the delete grant lifts it for the whole
  folder for the rest of the session. That makes the practical remedy
  two-step and worth reordering when this item is built: ask for the delete
  grant, which a session usually wants anyway for fragment cleanup, and fall
  back to the timestamped `mv` only when the grant is unavailable. It also
  means the `.git/` residue this entry lists can actually be swept by a
  session holding the grant, which is the half of R109 that was blocked on a
  hand step.
- **The asymmetry is general to the mount, not specific to git.** Confirmed
  again while landing R62 on 2026-08-10: `rm -rf` on `__pycache__` returned
  "Operation not permitted" and reclaimed nothing, and `cp` over an existing
  file returned "Invalid argument" mid-mutation-check, leaving a test file
  mutated until `cat > file` restored it (sha256 verified). Anything that
  unlinks or replaces fails; anything that creates or truncates works. That
  is one fact with many faces, and it is worth stating once here rather than
  rediscovering per tool.
- **Why P2 and not higher:** it never corrupts a build or an upload — it
  blocks a commit, loudly, at the end of a session. What it costs is the
  worst moment to spend it, and the failure mode when a session improvises is
  worse than the block: `.git/index.lock.bak`, `.stale`, `.stale2`, `.stale3`,
  `deadlock_1785618418816161105` and `tmp_probe_dead` are all sitting in
  `.git/` right now, each one a previous session's fixed-name workaround that
  the next session's identical workaround then collided with.
- **Fix:** the remedy is now written down — `docs/cowork_sync_protocol.md`,
  "Known limits", landed with this entry: verify the lock is dead (zero bytes,
  old mtime, no live `git` process), then `mv` it aside under a TIMESTAMPED
  suffix, never a fixed one, and check `HEAD.lock` the same way. What is left
  as work: fold the same check into `tools/sync_check.py` so session start
  reports a stale lock before a session spends an hour earning one, and sweep
  the eight residue files with Ben's delete grant. Done when: `sync_check`
  names a stale lock and prints the `mv` command, and `.git/` holds no
  `*.lock.*` residue.

### R121. The clock is a measurement, not an estimate: a fabricated countdown changed a deliverable, twice in one day (P1, S) | new 2026-08-14, merged from BUILD fragments `2026-08-14_BUILD_fabricated-deadline-countdown.md` + `..._floored-bank-hint...` item 3

- **What:** two sessions, same day, same defect. The NYY@TOR session opened
  a critique with "~5 minutes to lock. Nothing below is fixable in a
  rebuild" at 26 real minutes — it had not re-read the clock across ~7
  minutes of tool calls, decrementing a mental estimate ("~15…~10…~7…~5")
  that compounded monotonically in the expensive direction; Ben's
  correction bought three rebuilds and a materially better portfolio
  (platoon fixed, 89.5% exposure trimmed). Hours later the main-slate
  session believed 18:55 when a shell `date` said 18:43 and told Ben "6
  minutes to T-5" at 27 — and that mis-estimate is the proximate cause of
  its five-control relaxation against a floored 34-candidate bank. The
  T-schedule turns a bad guess into a wrong PROCEDURE, which is what makes
  this an engine-adjacent item rather than a shrug: the schedule lent the
  fabricated number authority, and a contradicting `minutes_to_deadline`
  was on screen and read past because nothing tracked the claim.
- **Fix, the fragments' items 1-3 adopted:** (1) SKILL.md rule — never
  state minutes-to-lock without a measurement taken in the same turn; never
  carry a time estimate across a tool call; the T-schedule may only be
  invoked against a same-turn reading. (2) `tools/slate_clock.py --salary
  <csv>` printing first lock and remaining minutes, no engine import, no
  network, under two seconds, on the preflight model — removes the last
  deadline-pressure excuse for guessing. (3) `build_slate.py` prints
  `T-minus N.N min to first lock` to stderr AT RUN START, not only in the
  JSON at the end — the number exists; it arrives after the decision it
  should inform. (The fragments' item 4, a staleness guard in the brief, is
  noted and deferred: lower value, only if free.)
- **Audit fields.** Moves: robustness, autonomy (the expensive direction is
  suppressed work that looks like prudence). Evidence: V2 (both fragments'
  measured clock tables; the v3 brief contradiction). Acceptance:
  slate_clock runs <2s against a fixture salary and matches
  `slate_clock()`'s keys; the stderr line appears on every invocation; the
  SKILL.md rule present. Falsifier: none — instrumentation. FOSS: stdlib.
  Owner: none. Rollback: remove tool and line.

### R111(a). `sync_check.py` hardcodes `main` (P2, S) | new 2026-08-11, from DEV fragment `2026-08-11_DEV_sync-check-branch-and-default-branch.md`, merged 2026-08-12; **(b) CLOSED 2026-08-18**

- **(b) IS DONE AND WAS DONE BEFORE THIS ENTRY NOTICED.** Verified 2026-08-18
  from Ben's Windows machine, the command being the citation rather than the
  person who ran it:

  ```
  git ls-remote --symref origin HEAD  ->  ref: refs/heads/main   HEAD
  git fetch --prune                   ->  - [deleted]  (none) -> origin/master
  ```

  GitHub's default is `main` and `master` is deleted. Ben did exactly what the
  Fix line below asked for, and no document was updated, so CLAUDE.md, this
  entry, `docs/cowork_sync_protocol.md`, `tools/audit.py`'s `git_freshness`
  docstring and R148(a) all kept asserting `master` — until a session on
  2026-08-18 repeated it back to him as a to-do and he asked why. **The
  generalizable defect is not the stale value, it is that the value carried a
  VERIFICATION DATE, which made it read as more trustworthy rather than less.**
  A dated reading is evidence about the moment it was taken; treating it as a
  standing fact is the same error R145-R147 fixed for refs, arriving on a
  SETTING that no local command can re-read. Corrective rule now in CLAUDE.md
  and the sync protocol: trust the method (`ls-remote --symref origin HEAD`
  from a machine holding the credential), never the recorded number. **The
  five corrected surfaces were re-cited 2026-08-18** to name that command, its
  date and its output instead of "Ben, 2026-08-18": a document that fixes a
  stale reading by attaching a NAME repeats the defect it is correcting, since
  the reader still cannot tell what was read or when. R148(a) closed the same
  day made the audit run the command itself, so the reading in
  `checks.git_freshness` is now taken rather than quoted. Note the
  local `origin/master` ref persists after the branch is deleted, because a
  push never prunes, so it is not evidence either way — `git fetch --prune`
  clears it. **(a) remains open and is what this entry is now about.**

- **What, two halves, one of them not code.** (a) `tools/sync_check.py` reads
  `refs/heads/main` at three sites (`:142`, `:159`, `:184`) regardless of what
  is checked out, verified still present at HEAD. Inside a clone — which lands
  on `master` — it prints `disk main ?` and then hands the caller remedies for
  a branch they are not on, and it tells every caller to "push from Windows",
  which is wrong for a container holding a working credential. (b) GitHub's
  DEFAULT branch is `master`, verified against the live remote on 2026-08-11
  with `git ls-remote --symref`: `master` = `d0212c2` (2026-08-04), fully
  contained in `main`, 43 commits behind as of 2026-08-12 and growing. A plain
  `git clone` therefore checks
  out the August 4 tree silently and the repo's landing page shows it.
- **Why it matters now:** a PAT exists and containers can clone, so (b) turned
  from a curiosity into a live trap the moment that became true, and (a) is the
  tool that would otherwise catch it. Both are the false-signal family: a sync
  gate that answers about the wrong branch is worse than no gate, because it
  reads clean.
- **Fix:** (a) resolve the branch from `.git/HEAD`, detect detached HEAD,
  compute ahead/behind against that branch's own remote-tracking ref, read the
  remote's default via `ls-remote --symref` and report a mismatch as a HAZARD,
  and branch the remedy text on whether the remote is reachable. (b) is one
  repo setting for Ben: Settings, Branches, default to `main`, then delete
  `master`; until then clone with `-b main`. The hazard text landed in
  `docs/cowork_sync_protocol.md` with this filing. Done when: `sync_check` run
  on a `master` checkout names the branch it is actually on and flags the
  default-branch mismatch.
- **DO NOT apply `_to_delete/r103.tar.gz`.** A working implementation with 6
  tests was written in a container on 2026-08-11 and delivered as that
  tarball, but it was built against HEAD `89ca350` (2026-08-10) after roughly
  33 hours of idle wall clock, so it predates R103-R110 and would revert
  several sessions. It carries `EXPECTED_TEST_COUNT = 816` as a literal, which
  would undo R62's `EXPECTED_SUITE_COUNTS` dict, and its own changelog entry is
  numbered R103, which is taken. Re-derive against current HEAD; the tarball is
  a reference for intended behaviour and test names, nothing more.
- **Filed alongside, already recorded elsewhere:** the session that produced
  this fragment is the one that took `engine_branchfix_2026-08-11` beside a
  held `engine_2026-08-11` (R31(d)'s 2026-08-11 note) and the one whose
  write-back loop truncated seven tracked files (remedy now in the sync
  protocol's write-back section). Neither is re-filed here.

### R179. build_asserted bypasses the F19 hash-seed pin, and autobuild routes every pool-override build through it (P1, XS) | new 2026-08-22, from the greenfield sixth edition; VERIFIED-read at ec832cf (guard at `build_slate.py:3186`; wrapper unchanged)

- **What:** build_slate's re-exec guard is `if __name__ == "__main__"`;
  `build_asserted.py` loads it via
  `spec_from_file_location("build_slate_mod", ...)`, so the guard is False by
  construction and the wrapper sets no seed — while autobuild switches to
  build_asserted for every classified-benign pool override. The builds that
  already carry an asserted gate also silently run unpinned, on files Ben
  uploads.
- **Fix:** set `PYTHONHASHSEED=0` in autobuild's subprocess env AND pin in
  the wrapper — or fold `--assert-gate` into build_slate proper and delete
  the exec_module hack (the greenfield verdict; kills the class).

### R180. Audit-hardening batch: the debt check is blind to the highest-authority files, one changelog commit amnesties older debt, and no reconciliation catches an unregistered suite (P1, S) | new 2026-08-22, from the greenfield sixth edition; (a)(b) VERIFIED-repro at ac8ac05, (a)(e)(g) re-confirmed at ec832cf (`audit.py:1378`, `:1917`, `:350`)

- **What:** (a) `CHANGELOG_TRACKED_PATHS` omits `MLB_Classic.md`,
  `MANIFEST.md`, `requirements.txt`, `requirements.lock`, `.gitignore`,
  `.gitattributes` — a commit changing the strategy authority with no
  changelog entry reports `unrecorded_commits: 0` (repro'd in a throwaway
  repo). (b) the measurement window is "since the last commit touching
  CHANGELOG.md", so any later changelog-touching commit permanently hides
  earlier unrecorded commits (repro'd). (c) nothing reconciles
  `tests/test_*.py` on disk against `AUDITED_SUITES` — a new suite file sits
  outside the gate forever, the exact failure the header comment narrates.
  (d) `EXPECTED_VERSION_TEXT` is substring-matched anywhere in the file. (e)
  the terse line truncates warnings to two with no "+N more" — with the
  R142/R145-R147 warning families all live, three-plus is routine and
  skill-drift can hide indefinitely. (f) `parse_unittest_report` searches
  stdout before stderr and takes the FIRST "Ran N tests". (g) the pin-sum
  comment reads `# 1000` against an actual 1221 — the file's own narrated
  staleness class, fourth instance.
- **Fix:** extend the tuple + one ChangelogDebtTests case per path; measure
  per-commit or document the window honestly; one meta-test globbing tests/
  against AUDITED_SUITES; anchor the version pin to the header line; append
  `; +N more`; parse stderr first; delete the numeric comment.

### R181. Eval 5's standing red is misattributed: the forbidden /large_wta/ regex matches the checkpoint's canonical vocabulary, and R66(a) will not clear it (P2, XS) | new 2026-08-22, from the greenfield sixth edition; VERIFIED-repro (harness run: 7 PASS, 1 FAIL, both grep hits in the contests block; evals unchanged since)

- **What:** eval 5 fails on `forbidden claim present: /large_wta/`, but the
  two matches are `"contest_shape": "large_wta"` — the engine's canonical
  mapping for an operator-supplied `wta_satellite` posture — and eval 5 never
  invokes a swap, so R66(a)'s late-swap default is not the cause. The board
  note claiming "Closing (a) closes the eval" was corrected on R66's entry
  this date; left alone, R66(a) lands, the eval stays red, and "7 of 8 is
  clean" hardens into ignoring the gate.
- **Fix:** scope the assertion (forbid `large_wta` only in `posture` fields
  and prose, or assert `contests[0].posture == "wta_satellite"`); re-run the
  harness; update the eval's notes line.

### R182. The eval harness's surface guard has a crash window that leaves eval caches on live surfaces (P2, XS) | new 2026-08-22, from the greenfield sixth edition; byproducts VERIFIED-repro on a copy, crash half PLAUSIBLE

- **What:** `run_evals.py` snapshots and restores `data/slates/`, `outputs/`,
  `runs/bank_cache_*.json` in a `finally:` — which covers exceptions, not a
  killed process. A SIGKILL mid-eval leaves a staged next-day slate dir, an
  eval `upload_manifest.json`, and an eval bank cache in place, and a real
  next-day build would read that cache — the R20/R22 staleness family the
  guard exists to prevent.
- **Fix:** write an `EVAL_RUN_IN_PROGRESS` marker at guard start, remove it
  in the restore; the audit warns when one exists.

### R183. CLAUDE.md has regrown 12.6KB → 25.9KB → 33.9KB in ten days; the trims are free and a byte budget prices itself (P2, S) | new 2026-08-22, from the greenfield sixth edition; VERIFIED-read (re-measured at ec832cf: 33,975B)

- **What:** R9a landed at 145 lines (07-27); the 08-12 adjudication measured
  12.6KB; the ed6 review measured 25,927B on 08-17; today it is 33,975B —
  every session pays the regrowth, and the curve is steepening. Measured at
  the review: build-contract item 1 carried 4,468B of flag-level mechanics
  and dated measurements that SKILL.md carries in parallel and the Quick Card
  carries a third time (~12KB total for one ranking rule plus one paste
  procedure, against the file's own "each procedure lives once" law);
  session-start carried 4,529B, half incident narrative whose rationale lives
  in the same-date CHANGELOG entries.
- **Why:** not a re-argument of the rejected under-30-line position — the
  contracts stay verbatim; this trims duplicated procedure and relocated
  rationale only.
- **Fix:** shrink the duplicated procedure blocks to their contract facts
  with pointers; add a one-line audit warning when CLAUDE.md exceeds a byte
  budget (16KB) so the fourth R9 round never needs filing. Full outline with
  per-section budgets in the archived edition.

### R184. The queue section carries tens of KB of session narratives answering a 2KB question (P2, S; PARTIALLY APPLIED this commit) | new 2026-08-22, from the greenfield sixth edition; VERIFIED-read (measured 51,320B/16 paragraphs at the review; 21 note-paragraphs at landing)

- **What:** "What do we tackle next" accumulates dated session paragraphs
  largely retelling same-date CHANGELOG entries, while its own header says
  the amendment history lives under Board history. Every DEV session pays
  ~12K tokens to learn an ordered list.
- **Applied this commit:** notes older than the two newest sessions moved
  VERBATIM to Board history (the 2026-08-10 relocation precedent); the queue
  keeps the current order plus the newest notes.
- **Remainder (the standing rule):** on each future amendment, the displaced
  paragraph MOVES to Board history in the same edit — the same
  move-on-completion discipline entries already follow. One sentence in this
  file's header when next touched.

### R185. SKILL.md reorder: sandbox mechanics out of the build path, war stories compressed to morals (P2, S) | new 2026-08-22, from the greenfield sixth edition; VERIFIED-read (re-measured at ec832cf: 52,192B)

- **What:** the skill is ONE skill by cohesion (correctly, given the router)
  but ~6.7KB of Cowork-sandbox mechanics sit MID-file between the paste path
  and slate-identity confirmation, and ~13KB of dated incident narrative
  rides inline; measured duplication vs CLAUDE.md ~7KB at the review, and the
  file has grown 4.4KB since. Its pins are maintained; the stale copy was the
  installed snapshot (R149).
- **Fix:** move the sandbox section to `references/sandbox.md` (the router
  already tells cloud sessions which world they are in); compress the five
  inline war stories to one-line morals plus CHANGELOG date pointers. ~10KB
  (~2,500 tokens) per BUILD, zero contract loss. Rides R131's SKILL.md
  session.

### R186. Claims hygiene: an archive mode for sweep, since unlink never comes (P2, S) | new 2026-08-22, from the greenfield sixth edition; VERIFIED-read

- **What:** the mount grants no unlink (R109) and `sweep` deletes nothing by
  design, so every claim ever taken stays in the glob path and in sweep's
  output forever — 100+ dirs; the live-signal channel accumulates noise by
  construction, and R31(b)'s UTC-staleness already trains sessions to skim
  the one output reserved for arbitration.
- **Fix:** `sweep --archive` that `mv`s RELEASED claims into
  `claims/archived/<yyyy-mm>/` (rename is permitted where unlink is not),
  keeping the live glob O(active); or emit a one-paste PowerShell cleanup
  script for Ben, who holds the delete grant. R31(b)(c) stay the filed
  halves; R31(d) stays Ben's decision, untouched.

### R188. `skills/generate-lineups-workspace/` is 1.24MB of tracked skill-creator eval residue (P2, XS + one decision) | new 2026-08-22, from the greenfield sixth edition; VERIFIED-read (still present at ec832cf)

- **What:** 47 tracked files, 1,244,179B: iteration-1 eval outputs from
  2026-07-22, duplicate DK input CSVs, a 539KB review HTML, and a benchmark
  table of all zeros (the harness run never produced results). The live
  harness moved to `skills/generate-lineups/evals/` weeks ago; nothing
  references this tree. It inflates every skills glob a session runs and is
  3x the size of the entire documented session-start read.
- **Fix:** `git rm -r --cached` + `.gitignore` line is DEV's; the disk delete
  is Ben's grant (mount refuses unlink) — listed in Tier 4 as the decision.
  Any wanted fixture already exists under `evals/inputs/`.

### R189(3). Two mlb.com paste render shapes still drop both probables — R117's remainder, now R189's (P1, XS-S) | new 2026-08-22, from the greenfield sixth edition; layer (3) re-scoped at ec832cf. **(1) and (2) CLOSED 2026-08-24, migrated to CHANGELOG.md**

- **Landed 2026-08-24 and not repeated here:** (1) the paste module's "every
  player carries an MLBAM id in the URL" premise was false for Ben's browser
  copies (verified on `paste_1910_6g.txt`: all six games `mlbam_id=None`) and
  the docstring now says so; (2) a NAMED probable with an empty id scored a
  silent 1.0 in `compute_f4_factors` with `sp_quality_available: True` and no
  bucket, so F4's SP-quality term was dead on every plain-text-paste slate —
  now recovered by the Savant `last_name, first_name` join and, where it still
  cannot join, named in `sp_quality_unavailable` with a per-team reason. Both
  rode the R159 + R160 commit, which is why this item keeps its number and
  loses two thirds of its scope.
- **What (open):** R117's fix landed `_HAND_WITH_STATS`, so the
  hand-plus-stats render now parses. Two shapes still drop BOTH probables with
  zero warnings: the one-line `"Name RHP"` render (promotion still requires
  the hand on its OWN line after a held name), and a clock the `_CLOCK` regex
  misses (`"7:10 PM CT"` — the regex admits only an optional ET suffix), which
  also loses the venue.
- **Why it did not ride with (2):** the F4 half is a REPORTING fix in the
  projection builder and this is a PARSER change in `paste_lineups.py`, needing
  real paste fixtures in both shapes to verify. Landing them together would
  have put an unverified regex beside a mutation-tested report. It stays P1
  because a dropped probable is still the F4-dead path, and (2) only softens
  the cost: the quality term now resolves by name IF a name arrives, and these
  two shapes are exactly the case where no name arrives at all.
- **Fix:** accept name+hand on one line; widen `_CLOCK`, or warn per game when
  two headers parse and pitchers == 0. Batches with the R122 rider (both are
  handedness reaching the build).

### R216. The gate's tree fingerprint omits `skills/`, while ~20 gated tests exec `build_slate.py` (P1, XS; lands alone) | new 2026-08-24, from the greenfield seventh edition (GF7-T1) and independently from the outside spec (D01); VERIFIED-read at `tools/audit.py:1016`, coordinator-re-read, re-read here. **Rider 2026-08-27 (ed8 F-01):** while the manifest is open, include `requirements.txt`/`requirements.lock` and `data/reference/reference_manifest.json` in the fingerprint — behavior-changing inputs the same reuse argument covers — and stamp the record with the runtime identity R217(d) defines, so a reused unit is provably same-tree AND same-interpreter.

**What.**

    for folder in ("mlb_engine", "tools", "tests"):

against `test_core.py:4212` `spec_from_file_location("build_slate_under_test",
path)` — also `:7291`, `:12790`, the R167-169 batch's new units and exit-contract
tests, and `test_upload_integrity`'s reads of the same file.

**Why.** R152's honesty rule 3 (`audit.py:937-939`) says "every record carries a
fingerprint of the tree it ran against, and the report refuses a mixed set". That
sentence is false for the one 3,325-line file that changed three times last week.
Edit `build_slate.py` between `--gate-run` calls: the fingerprint does not move, no
reset fires, and `--gate-report` prints the byte-pinned clean line over records
whose build_slate assertions ran against the previous file. The single-call
`--run-tests` path is immune; the SPLIT path is exposed, and the split path is the
documented Cowork path (R152). First bad moment: a DEV session lands a build_slate
edit mid-gate and quotes a green line that never tested it — which is the shape of
every stale-reading incident this repo has recorded.

**Fix.** Add `"skills"` to the folder tuple; the existing rglob already skips
`__pycache__` and `_scratch_*`. Accept the one-time reset of in-flight gate state,
which is why this item **lands alone, at a session boundary** rather than inside a
batch. The outside spec (D01) additionally proposes fingerprinting
`data/reference/**` and the requirements files; take that as a SEPARATE decision,
because an ARCHIVE reference refresh would then redden DEV's gate mid-session, and
that trade has to be made deliberately rather than as a side effect of this fix.

- **RIDER 2026-08-25, R233's own pattern, observed live rather than read.
  `skills/` is not the only omission: CLAUDE.md is gated too and is not in the
  fingerprint either.** `tree_fingerprint` (`tools/audit.py:1031`) hashes `.py`
  under `mlb_engine`, `tools` and `tests` and nothing else, and TWO gated tests
  read CLAUDE.md as data —
  `test_core.AuditSkipHonestyTests.test_the_clean_pass_line_is_the_one_CLAUDE_md_quotes`
  and `test_core.SplitGateTests.test_a_complete_clean_gate_prints_the_line_claude_md_quotes`,
  both asserting that the pinned PASS line appears verbatim in CLAUDE.md. Seen
  in the R234 session: those two failed on the new count, CLAUDE.md was
  corrected, both passed when run directly, and `--gate-report` went on serving
  the recorded FAIL because the fingerprint had not moved (`423a727fb78749e6`
  before and after). That is the same defect in the more dangerous direction —
  `skills/` means a green line can cover an untested change, this means a RED
  line can outlive its own fix, and a session that trusts the report re-runs a
  whole gate for nothing or, worse, edits code to chase a failure that is
  already repaired. Fold CLAUDE.md into the same fix; it is one more entry in
  the same tuple and it costs the same one-time reset. Count the class before
  believing the count: `MLB_Classic.md`, `MANIFEST.md` and the requirements
  files are read by gated tests too and want the same check.

### R217. Four audit-gate operational holes, and the gate record does not say which interpreter produced it (P2, S) | new 2026-08-24, from the greenfield seventh edition (GF7-T6, GF7-T7, GF7-T9) and, for (a) and (b), independently from the outside spec (D25); (d) is what survives adjudication of the outside spec's C04

**What.** (a) `audit.py:1036-1047`. `.audit_gate/` is claimless shared state: two
interleaved `--gate-run` sessions double-record a suite, `ran > pinned` classifies
as `grew`, and the operator is told a pin is stale when nothing moved. (b)
`:2095-2103`. `--gate-report --output <path>` never writes the file; the non-gate
branch does, at `:2113-2114`. (c) `:1345` vs `:1446`. `--gate-run` prints "complete:
run --gate-report" on state that `--gate-report` will refuse for age
(`GATE_MAX_AGE_H`). (d) No gate record stamps runtime identity — interpreter
version, platform, package versions. This tree carries `__pycache__` from
`cpython-310` AND `cpython-313`, so two interpreters have demonstrably run against
it, and the pinned clean line does not say which one produced any record.

**Why.** (a) is the multi-session contract's one unnamed shared surface: every
other contended resource has a claim, this one has none. (b) and (c) are a tool
telling the operator it did something it did not. (d) is the honest remainder of
the outside spec's C04, whose Blocker framing is REJECTED below — but the
underlying point survives in a narrow form: a fingerprint proves code equivalence
and cannot prove runtime equivalence, and R152's honesty rules are about exactly
that distinction.

**Fix.** (a) A freshness check on `started` records, or name `.audit_gate/` in
CLAUDE.md's multi-session contract and give it a claim. (b) Write the file. (c) Add
the age check to gate_run's complete branch. (d) Record `sys.version`,
`platform.platform()` and the three pinned package versions per unit, and refuse a
mixed-runtime assembly the same way a mixed-fingerprint assembly is refused. Rides
R180 (same file, same class of hardening).

### R218. The last two unbounded subprocesses, one of which is a package install (P2, XS) | new 2026-08-24, from the outside spec (D02); VERIFIED-read here, and the class is smaller than the spec states

**What.** `tools/audit.py:849` (`subprocess.run([sys.executable, "-m", "unittest",
name], ...)` on the `--run-tests` path) and `tools/env_probe.py:139` (`_reprobe_subprocess`)
and `:192` (`subprocess.run(_install_command(lock_path))`, a `pip install`) carry no
`timeout=`. Correction to the filing: the spec implies the class is open; it is
nearly closed. The other five sites already bound themselves — `audit.py:1383`
(`timeout=ceiling`), `:1525` and `:1910` (`timeout=15`), `:1773` and `:1829`
(`timeout=timeout`, with classified failure reasons per R147).

**Why.** `env_probe.py:192` is the one that can cost a slate: it runs at session
start, it is a network operation against a package index, and a stalled index hangs
the session with no deadline and no message. `audit.py:849` is bounded in practice
by the Cowork call cap, which kills the parent and, per R109, can strand the next
commit on a zero-byte `.git/index.lock` — so the unbounded child is how a hang
becomes a second failure.

**Fix.** A `run_bounded` helper with an explicit timeout per call site and a named
TimeoutError, per the outside spec's shape (D02). Give the install a generous
bound and the reprobe a short one. Rides R217 and R180.

### R230. Three assertion seams that survive mutation: a vacated solver pin, an unpinned strategy dial, and a bank-membership blind spot (P2, S) | new 2026-08-24, from the greenfield seventh edition (GF7-X1, GF7-X2, GF7-X3); (a) independently from the outside spec (D31); VERIFIED-read, (a) re-read here. **(d) added 2026-08-27 (ed8 F-28):** the game-cap allocation test (`tests/test_core.py:1278-1293`) uses two entries/candidates while the default reuse rule independently forces diversification, so it passes with the game-exposure constraint deleted; neutralize the competing constraint, use enough entries to expose the bound, and assert the counterfactual (the F-28 sketch is the shape). Rides R91's mutation session like the other three.

**What.** (a) `tests/test_core.py:1293`.
`test_game_exposure_cap_solver_and_validator` asserts `chosen == ["X", "Y"]` on two
candidates and two entries — an outcome the post-R116
`default_candidate_reuse_cap(2, 2) = 1` now forces with no game-cap rows present at
all. Deleting the game-exposure rows from the MILP survives the suite, and the
suite-wide sweep found no other solver-enforcement pin for game caps. (b)
`test_core.py:2799`. The value guard's clip arithmetic is pinned once and well
(8.64 pins headroom, pool and pitcher exemption), but `VALUE_GUARD_PCTL` is
unpinned DOWNWARD: the fixture's distribution returns the same quantile for every
`q <= 0.933`, so mutating `0.90 -> 0.5` survives. A strategy dial with no assert
watching it. (c) `BankCacheAnsweredJobTests` pins skip-answered and
`clear_attempted` integrity, but every cross-condition fixture changes locks and
excludes TOGETHER, so loosening only the membership comparison to ignore the
conditions-signature component survives — answered jobs would then suppress new
work after a projection or exclusion change under identical locks, which is the
2026-07-26 incident class.

**Why.** All three are the fixture lesson in its assertion form: a test that
constrains the outcome by accident rather than by the constraint under test. (a) is
the worst because game caps have exactly one solver pin and it is this one.

**Fix.** (a) Pin the cap on a fixture where reuse does not force the outcome (three
or more candidates), or assert the constraint rows exist; add a mutation test that
deletes the game-cap row and requires failure. (b) A second fixture with a spread
distribution, or assert the emitted `"percentile"` field. (c) One fixture that
changes conditions ONLY. Rides R91 (mutation smoke for the counted guards).

### R231. 1,778 leaked test directories in `outputs/`, plus the session-residue inventory (P2, XS; the sweep needs Ben's grant) | new 2026-08-24, from the greenfield seventh edition (GF7-H1, GF7-H2); count re-measured here at 1,778

**What.** (a) `outputs/` holds 1,778 `_test_r3_*` directories (~2,274 files).
Cause: `test_upload_integrity.py:606` deliberately fixtures inside the real
`outputs/` because `preflight_upload.is_delivered_file` resolves against
`REPO/outputs` (`:815`), and tearDown's `unlink` fails open on this no-unlink
mount, so every mount-side gate run leaks one directory per test in the class —
roughly one gate's worth per day. Contained, not harmless: `outputs/` is gitignored
and both scanners skip `_`-prefixed dirs (`awaiting_standings.py:167` names "the R3
leak" explicitly). (b) Inventoried residue: root logs `_audit.log`,
`audit_out.log`; outputs logs `_chunkA-D.log`, `_paste.err/out`,
`_audit_final.log`, `_build_sd1.log`, `_perm_probe.txt`, `_test_core*.log`,
`_test_rest*.log` (13 files, ~39KB, no in-repo writer — session shell redirects);
root tarballs `_changes.tar.gz` and the gitignored `_stage_repo*` class; an EMPTY
untracked `upload_hou_sd/`; and `DFS_GREENFIELD_REVIEW_2026-08-12_ed4.md` still
untracked at root while all its adoptions are landed.

**Why.** None of it is hazard-class — the 08-18 `_scratch_*` rule already closed
the one that was. It is `git status` noise, and the 08-23 fragment-census lesson is
that noise on that surface is how a live fragment goes unread for a week.

**Fix.** Sweep with `mv outputs/_test_r3_* _to_delete/r3_litter_<date>/` (this mount
grants create and truncate but not unlink, so `mv` works where `rm` does not); same
for the residue. Prevent by having tearDown rename into a gitignored `.tmp/` when
unlink refuses. **Do NOT move the fixture to a tmpdir** — the fixture's own comment
is right that it would then exercise a different `is_delivered_file` path than
production. Ed4's review file gets `git add`ed beside the other editions or moved
to `docs/`.

### R232. Two documents read as authoritative and are not: MLB_Classic.md names a RETIRED manifest as its version authority, and MANIFEST.md still reports 12 modules and 119 tests (P2, XS) | new 2026-08-24, from the outside spec (D36 / §1.6); VERIFIED-read here, and worse than the spec states

**What.** (a) `MLB_Classic.md:1` heads the file "v2.26.0" while its Versioning
convention section (`:512`) says "The authoritative project version is the manifest
`Project_Version` field (`v2.24.0`)" — and the checksum manifest that field lives in
was RETIRED (`MANIFEST.md`: "commit as 'v3.0.0-pre: package restructure, checksum
manifest retired'"). So the strategy authority points its version authority at a
file that no longer governs. The spec filed this as two numbers disagreeing; it is a
pointer to a retired artifact, which is the worse condition. (b) `MANIFEST.md:8-17`
is a 2026-07-16 Cowork migration seed still reporting `PASS v2.26.0 12 modules 119
tests` and listing "Still open" work that has shipped, while every active
instruction expects 26 modules and 1,276 tests. (c) The Classic prose says probable
pitchers join Savant directly by MLBAM id; `projection_builder.py:883-905` has had a
name fallback since R189(2) (see R222).

**Why.** R183/R184/R185 price the always-loaded surface; this is the other half —
surfaces that are not always loaded but ARE cited as authority when they are read.
A retired file quoted as the version authority is the exact stale-reading class that
cost this project a session on 2026-08-18.

**Fix.** (a) State the authoritative version in one place and have MLB_Classic.md
name it, or delete the Versioning-convention paragraph now that the manifest it
describes is retired. (b) MANIFEST.md is a completed migration seed: mark it
historical at the top or move it to `docs/legacy/`. Note `audit.changelog_debt`
already watches MANIFEST.md per R180, so whichever is chosen, do it there. (c) One
sentence in MLB_Classic.md section 6. Rides R183/R184 (same trimming pass).

### R233. FILED AND CLOSED 2026-08-24 — a landing that claims a rule now lives in one place carries the enumeration that proves it. Entry in CHANGELOG.md.

### R243. The container-build recipe is proven and lives in one session's memory: put it in the sync protocol (P2, S, docs only) | new 2026-08-27, merged from BUILD fragment `2026-08-27_BUILD_container-bank-and-r157-single-cap.md` §1

**What.** The device VM cannot build a 14-entry Classic bank at all
(~18.6s setup per invocation against a 45s call ceiling left ~7s of search per
call; three runs accumulated 4 SP pairs against 40 viable). The same build in
the cloud container certified in 69.4s. The fragment carries the working
recipe: tar the engine+reference+slate surface (~1.9MB), stage, build long,
tar `outputs/<date>` + `runs/<run_id>` back, extract on the mount — and the
trap: extraction on the mount needs `tar xzf --overwrite` or R109's no-unlink
fails on every pre-existing file, EXCEPT over `outputs/<date>/` where
`--overwrite` on the shared manifest is R245's hazard; stage-and-copy
selectively there.

**Why.** Each session rediscovering this against the clock is the cost; the
sync protocol is the named home for mount/container movement rules.

**Fix.** `docs/cowork_sync_protocol.md` gains the recipe as a first-class path
for a Classic slate whose bank does not fit the device VM, with the
`--overwrite` line and the R245 caveat. Docs only; no code.

## Workstream 7 — Archival and ledger tooling

Everything here feeds the evidence loop that Workstream 2 grades against.
None of it touches the certified path; all of it decides how much of what
was played can ever be learned from.

### R118. Retain the per-player FPTS map and replay portfolios against archived fields (P1, M) | new 2026-08-14, audit session; the audit's one strategic filing

- **Rider added 2026-08-27 (adopted from the outside spec ed8, F-48 — the one
  piece of its economic core this board's own sequence can use now):** the
  replay tool SETTLES each counterfactual portfolio at the archived contest's
  own payout curve — a tie occupying ranks `r..r+k-1` splits the sum of those
  payout slots across the k tied entries, duplicates stay separate entries in
  the tie group, fees subtract — so a replay reads in DOLLARS against the
  observed field instead of points and ranks. This is exact accounting over
  archived outcomes, not simulation: truthful-labels clean, no new gate, and
  it is what makes R37(2)'s floor-5 question and R40's routing question
  answerable in the unit Ben actually optimizes. Paid-places/payout columns
  already ride the mined records where DK exported them; a contest without a
  parseable curve settles as UNKNOWN, never approximated. The ~20-line
  reference settle (spec §F-48) matches the miner's rank/tie facts and is the
  oracle to pin the implementation against.

- **Rider added 2026-08-23, from ARCHIVE fragment `2026-08-22_ARCHIVE_r118-step-1-is-already-done.md`. Fix (1) is ALREADY SATISFIED and the re-mine backfill is unnecessary.** The strip is real (`field_miner.py:1982`), but both stripped maps are pure functions of `player_table`, which IS retained, and the miner itself builds them from exactly that list at `field_miner.py:703-710`; `own_by_player_norm` takes `player_table` as its only argument and `tools/ownership_pred.py:688` already calls it that way against an archived record. Measured across the archive: 379 mined records carry a `player_table`, 29,921 player-contest rows, **100% with a non-null `fpts`** (0 nulls), 5,926 distinct `(slate_date, player)` realized-scoring observations over 26 slate dates. **Verified rather than asserted:** twelve contests with internal position-row disagreements — the hardest reconstruction case — had their `{player → FPTS}` map rebuilt both ways, from the archived `player_table` and by re-parsing the raw standings CSV with `parse_standings_export`, and came back **12 of 12 identical, 0 mismatches.** So this item's M-lift shrinks to the replay tool: no backfill, no re-mine, no sidecar. Two caveats a replay tool MUST carry, both measured. **(i)** 1,076 of 29,921 rows (3.6%) are one player holding two DIFFERENT `fpts` values across roster-position rows inside a single contest; the engine's collapse is FIRST-WINS over the ordered list, so any reconstruction must be first-wins over the same order or it will silently disagree on those — the same DK multi-position row-splitting that produces `dk_table_deficit_pts`. **(ii)** 125 `(slate_date, player)` pairs disagree across contests on the same date, so **`slate_date` alone is not a valid key for a realized-FPTS table; the draftgroup is** — and the archive does not currently record the draftgroup on a mined record, which is a prerequisite this item now owns.

- **What:** every mined contest computes `fpts_by_norm` — the exact
  {player → realized DK FPTS} map for that contest's whole field — and the
  archive step strips it (`field_miner.py:1961`; `fpts`/`FPTS` appears in no
  other module). The raw standings export carries per-player `%Drafted` and
  `FPTS` for the entire field (verified: `data/archive/2026-08-06/contest-standings-193296906.csv`
  header), so the 271-contest, 21-date archive can already answer "how did
  the field construct" but not "what would THIS lineup have scored and
  finished" — despite holding every input required. No tool joins
  `runs/<run_id>` candidates or delivered CSVs to archived standings
  (verified absent; the only `runs/<id>/final` consumers are verify_export
  and late_swap).
- **Why P1 ("destroys evidence" clause, plus the substrate everything in
  Tier 2 waits on):** the strip discards evidence on every mine. Retained,
  one deterministic replay tool converts the archive into the grading
  substrate the board's three open strategy questions currently wait on live
  tranches for: R37(2)(a)'s floor-5 question, R40's routing question, and
  R10's duplication bar. `runs/` holds frozen inputs and
  `final/projections.csv` for 302 runs, so policy A/B is leakage-free —
  same information, different construction policy, scored against the REAL
  archived field: realized FPTS sum, rank and percentile in that field,
  seat-cleared where `paid_places` is known, and EXACT duplicate count
  against the field's actual lineups (no field model needed — the field is
  archived).
- **Fix:** (1) stop stripping `fpts_by_norm`/`own_by_norm` — a sidecar
  `fpts_<contest_id>.json` beside each `mined_*.json`, or keep the keys; one
  idempotent re-mine backfills (~10 min in the container, the R48 pattern,
  and R48's leverage table rides the same pass). (2) `tools/replay_portfolio.py`:
  inputs a lineup set (delivered DKEntries CSV, `final/assignments.csv`, or a
  candidate bank) plus contest id(s); outputs per lineup the realized sum,
  field rank/percentile, would-have-cleared where paid line is known,
  duplicate count vs field lineups; a coverage report NAMES any player absent
  from the slate's union player table, and a lineup with an unresolved
  player is reported partial, never guessed (union across same-slate
  contests covers most; the residual is named). (3) Self-validation gate:
  replaying every archived own entry reproduces its recorded points and
  rank exactly (`entries[]` already carries points + players_norm, so the
  join is closed-loop).
- **Truthful labels, non-negotiable on this item:** a replay is an observed-
  outcome counterfactual conditioned on ONE archived field. It is never ROI,
  win rate, or a probability claim, and a policy that wins replays is graded
  "supported in the shapes replayed", not proven — the field it beat is last
  slate's field. Conditioning follows the house rule: by contest archetype
  and field-size bucket, never pooled.
- **Audit fields.** Moves: edge, leverage, portfolio quality — via evidence
  rather than via a new objective. Evidence: V2 (`field_miner.py:1961`;
  archive contents; absence of any replay consumer — all verified
  2026-08-14). Acceptance: self-validation exact on >= 95% of own entries
  with the remainder named (unparsed rows exist in the mine), plus one
  worked policy A/B — the 2207_2g reuse-cap pair — with duplicates counted
  against the real field. Falsifier: if union player tables cannot resolve
  >= 90% of a typical replay lineup's players, exact replay narrows to
  entered slates only and the item is re-scoped. FOSS basis: stdlib +
  vendored pandas/numpy (BSD-3), local, $0. Owner action: none (the fresh
  entry-history export that would light up `paid_places` stays R30's
  separate data half). Rollback: sidecars are additive; the tool is
  read-only over the archive.
- **RE-PRICED 2026-08-24 (ed7 §3.1, verified against a real artifact before the
  reviewer's sandbox died), and it is cheaper than this entry says.** The entry
  prices this as retaining the per-player FPTS map the miner "computes and
  strips" — implying a miner change and a re-mine backfill. Neither is needed.
  The strip point moved (`field_miner.py:1982`) and it removes only the DERIVED
  maps, `own_by_norm` and `fpts_by_norm`. **`player_table` SURVIVES into every
  archived `mined_*.json` and already carries `{player, player_norm,
  roster_position, pct_drafted, fpts}` per row** — verified on
  `data/archive/2026-06-03/mined_191020573.json`, 52 rows, e.g.
  `{'player': 'Cristopher Sanchez', ..., 'fpts': 30.75}`. So the replay tool
  re-derives `fpts_by_norm` with the same three-line first-wins comprehension
  the miner uses (`:704-709`), from the archive exactly as it sits: **no miner
  change, no re-mine, no backfill.** That matters beyond this item, because
  R118 is the head of the EV path and its price is the number the rebuild
  arguments are compared against. Two conditions the spec keeps: verify the
  Showdown CPT-row convention (base points vs 1.5x already applied) against ONE
  archived Showdown contest before grading any, and classify a lineup
  containing a player DK's table omits as non-replayable-from-table
  (`diagnostics.dk_table_deficit_pts`), never approximate it silently.

### R140. Opponent-conditioned field profiles for the recurring satellite families (P2, M; behind the Tier 2 spine) | new 2026-08-16, from the leverage ideation fragment; registry facts verified in ledger 3.19

- **What:** the satellite field is not an abstraction; it is a recurring
  population whose construction habits are archived per user. Verified in
  3.19: the rebuilt registry holds 15,402 users with 2,211 at the
  5+-contest "regular" threshold; regulars are a median 91.3% of Classic
  satellite fields and 80.8% of Showdown; satellite winners were regulars
  132/148 and 83/92; one username appears in all 270 archived contests.
  "Different from the forty people who actually show up" is a smaller,
  better-measured target than "different from the field," and 3.18 already
  says this is what makes the Section 5 opponent work worth building.
- **Fix:** a deterministic per-family profile from the registry plus the
  mined decompositions — chalk share, shape mix, salary-leave, duplication
  propensity of THAT family's regulars — consumed as the reference
  distribution for R10's duplication budget and R37(2)'s shape tilt in that
  family, instead of a generic field. All data is DK's own standings
  exports, manually pulled; no wall is touched.
- **Sequencing:** deliberately behind the Tier 2 spine — it consumes R118's
  replay substrate and R48's persisted tables, and its consumers are R10's
  control halves. Building it first would be a profile nothing reads.
- **Audit fields.** Moves: leverage, portfolio quality (satellite family).
  Evidence: V2 (3.19 re-read this session). Acceptance: a per-family profile
  artifact for one recurring family, reproduced deterministically from the
  archive, with every column labeled observed-outcome. Falsifier: if
  family-level profiles do not separate from the pooled field distribution
  (chalk share and dup propensity within noise), the item collapses to R48's
  generic tables and says so. FOSS: existing. Owner: none. Rollback:
  read-only artifacts.

### R30. Miner gap the money backfill exposed — DATA half only (P2, XS) | new 2026-07-29, from an ARCHIVE fragment; (a) tool half and (b) landed 2026-08-05, (c) landed 2026-08-08

**Rider 2026-08-28 (ARCHIVE, ledger 3.21):** the parked
`dk_contest_paid_places.json` covers 97 of the 610-contest corpus (all ≤07-29)
and the backfill re-mine is still one `--paid-places-from` command. The Ben-side
half — a fresh entry-history export past 2026-07-29 — is what moves coverage off
16%, and R258's threshold model now consumes it directly, which raises this
item's effective priority without changing its label.

- **What:** three archival-path defects, ordered by what blocks what. None of them touches the certified path, which is why none was taken in the 07-29 evening DEV session.
- **(a) TOOL HALF LANDED 2026-08-05; the DATA half is open and is Ben's.** The full What/Why/Fix and the landing record moved to CHANGELOG.md. Shipped: `--paid-places`, `--paid-places-from <json>` (both file shapes), `paid_places` / `payout_breadth_observed` / `cashed_entries` on the `own_results` record, and `posture_allocator.classify_tier` resolving instead of returning UNRESOLVED, pinned end to end. **What remains is not code:** `paid_places` coverage still ends at the 2026-07-28 entry-history export, so none of the 94 contests mined 2026-08-04 carries a paid line and the 3.16 cash-line finding stays ungradeable. A fresh export from Ben now has somewhere to go — one `--paid-places-from` re-mine backfills the archive, and the 100 already-parked contests can be backfilled today. **This is no longer what gates R10.**
- **(b) LANDED 2026-08-05.** Full record in CHANGELOG.md. A money flag (`--entry-fee`, `--winnings`, `--paid-places`, `--paid-places-from`) with no resolvable own entry ids now exits 7 naming the flags, the manifest path and the remedy, instead of exiting 0 having silently consumed nothing.
- **(c) LANDED 2026-08-08 with R49; full record in CHANGELOG.md.** `--auto-salary` no longer opens the repo-wide scan first: the tiers are manifest -> in-date (`data/slates/<date>` then `data/archive/<date>`) -> repo-wide, and the wide scan runs only when the first two find nothing. The repo now holds 289 salary CSVs, not 170, so the saving grew rather than shrank.
- **Note 2026-08-04:** urgency on (a) up again — none of the 94 A-030..A-034 contests carries a paid line, so the archive's first two rank-1 satellite finishes cannot be graded as seats and the 3.16 cash-line finding stays ungradeable until a fresh entry-history export lands. (c) was extended by R49 (manifest-first beats in-date-first, because whole slates were never staged in-date) and both landed 2026-08-08.

### R44. `extract_inbox_zips.py` re-extracts contests already archived, refilling the inbox forever (P2, S) | new 2026-08-03, filed by ARCHIVE (`docs/backlog_inbox/2026-08-03_ARCHIVE_inbox-refill-and-scan-tooling.md`), item 1 of that fragment (item 2 landed the same day as R43)

- **What:** a successful mine moves the standings CSV out of `data/standings/inbox/` into `data/archive/<slate_date>/`, per the contract. The zip that CSV came from does not move, so it sits in the inbox forever, and the next run of `extract_inbox_zips.py` re-extracts the CSV the miner just archived, refilling the queue with contests that are already done. Measured at the filing session's start: 91 CSVs in the inbox, 83 already mined, 46 byte-identical to the archived copy. The 8 that actually needed work were invisible in the pile, and finding them meant diffing inbox IDs against `data/archive/*/mined_*.json` by hand — the same shape of problem R43 fixed for the awaiting-standings scan, one layer earlier in the pipeline.
- **Why now, not before:** R43 (`tools/awaiting_standings.py`) reads `data/archive/*/mined_*.json` directly and is immune to this, since a stale re-extracted CSV in the inbox does not change what has actually been mined. So this is a real operator-time cost, not a correctness risk to the archive — hence P2, not P1.
- **Fix:** `extract_inbox_zips.py` skips a zip whose contest ID already has a `data/archive/*/mined_<id>.json`, and a successful mine relocates the zip the same way it already relocates the CSV (`--no-archive-move` should opt both out together, not just the CSV). Done when a mine leaves neither a stale CSV nor a stale zip behind in the inbox.
- **Rider added 2026-08-23, from ARCHIVE fragment `2026-08-22_ARCHIVE_extract-zips-never-moves-r44-evidence.md`.** The missing call is now named rather than inferred: `grep -n "processed_zips\|shutil.move\|os.replace\|rename" tools/extract_inbox_zips.py` returns NOTHING. The tool extracts and returns; it has never relocated a zip. `data/standings/processed_zips/` holds 127 files and every one was moved there **by hand**, which means the hand-move IS this item's mechanism — the loop is not "the mine forgets the zip", it is "nothing in the tooling has ever moved one." The 08-22 pass added 60 more hand-moves, the 128th through 187th in the archive's history. Two constraints on the fix, both already recorded elsewhere: on this mount `rm` is refused and `mv` works (R109), so the fix must MOVE to `processed_zips/` and can never delete; and the cheap independent second guard is to skip a zip whose contest id already has a `data/archive/*/mined_<id>.json`, which is the same exclusion `awaiting_standings.py` already computes.

### R196, remainder. The archetype table cannot express "single entry, broad curve": the Solo Shot row is WRITTEN and posture inference still needs a hand override (P2, XS-S) | **RETITLED 2026-08-30** when the row half closed after six sightings; the rows exist, the tax does not go away, and this entry's own Fix line was wrong. Original title: "`dk_contest_archetypes.csv` has no Solo Shot row" | new 2026-08-23, merged from THREE BUILD fragments (`2026-08-19_BUILD_solo-shot-archetype.md`, `..._-recurred.md`, `2026-08-22_BUILD_solo-shot-archetype-3rd-occurrence.md`); THREE occurrences in four days. **FOURTH occurrence 2026-08-27, from `2026-08-25_BUILD_posture-vocab-and-solo-shot.md` §2:** "MLB $100 Solo Shot (Turbo)" matched no row and name-inferred to `large_gpp` — wrong for a single-entry contest — until `--postures <id>=single_entry` was passed by hand; and a FIFTH sighting the same week, "MLB Showdown $1K Solo Shot" absent on 1905_1g_sd (the R238 fragment). The family recurs on both formats; the Tier 4 decision this waits on is unchanged.

- **What:** `MLB $2.5K Solo Shot (Night)` (08-19, `2005_3g`) matched no archetype
  row, so `preflight_upload.py` warned that no archetype could be inferred.
  Recurred 08-20 on `MLB $500 Solo Shot (Late Night)` (`2005_2g`), where
  `autobuild.py` REFUSED on attempt 1: "matched no archetype; it would build as
  large_gpp by fallback, not by identification." Same family, different dollar
  amount, so the pattern is the family name and not the price.
- **Why:** the 08-19 instance cost nothing because the posture was supplied
  explicitly, which is what the ledger Quick Card asks for anyway. The 08-20
  instance cost a full autobuild round trip on a super-late slate with ~24
  minutes to first lock. A pattern hit twice under a tightening clock is worth
  the one row.
- **Fix:** add the `Solo Shot` family to `data/reference/dk_contest_archetypes.csv`
  — a Solo Shot is single-entry per DK, so posture `single_entry`, shape
  `single_entry_gpp`, pattern likely the bare string `Solo Shot`. **This is
  ARCHIVE's file per the multi-session contract, so it cannot land from a DEV
  claim; it needs an ARCHIVE session or Ben's explicit grant.** Second, smaller
  question from the same fragment: `qa_portfolio.py` printed `large_wta ->
  wta_satellite [COLLAPSED]` for three satellites, so the field model priced
  them at a coarser shape than the one entered — worth deciding whether the
  satellite family deserves its own archetype row rather than collapsing.
- **Third occurrence, 2026-08-22 (`1335_3g`, `MLB $2.5K Solo Shot (Early)`):**
  `--postures 194183875=single_entry` supplied by hand again, third time paying
  the same one-line tax on three price points in four days ($2.5K Night, $500
  Late Night, $2.5K Early). The write-set boundary is the whole reason this
  keeps recurring: the fix is one CSV row and the role that reads it cannot
  write it. Worth Ben granting a standing DEV exception for
  `dk_contest_archetypes.csv` ADDITIONS, or an ARCHIVE session picking it up in
  the next tranche — either closes it, and nothing else will.

**ROW HALF CLOSED 2026-08-30, and the Fix line above is CORRECTED** (from BUILD
fragments `2026-08-30_BUILD_contest-archetype-gaps.md` and
`2026-08-30_BUILD_standing-data-driven-qa.md` §A and §D, slate `1605_2g`).
`build_slate.py` refused at exit 3 on contest identity for two names; Ben
supplied both real payout tables and instructed the rows be written, which is
the standing exception the third-occurrence bullet asked for, granted per
contest rather than standing. Both rows verified present in the file at this
head, each carrying its observed field size and full prize curve in `notes` so a
later session can re-derive `payout_breadth` instead of trusting it:

- **`Micro Booster`** | `wta` | `winner_take_all` | breadth **0.021** | objective
  `wta`. Observed on contest 194681833: 237 entrants, top 5 win $10 flat on a
  $0.25 entry, 6th pays what 237th pays. The `40x` in the title is the payout
  multiple, not the field size.
- **`Solo Shot`** | `se_gpp` | `broad_micro_gpp` | breadth **0.235** | objective
  `gpp`. Observed on contest 194686507: 1486 entrants, paid to 350th, top 10
  hold 43% of the pool and ranks 51-350 hold another 43%.

**The correction, which is the part worth reading.** This entry's Fix specified
posture `single_entry`, shape `single_entry_gpp`. `single_entry_gpp` is inside
`WTA_CONSTRUCTION_SHAPES` (`contest_shapes.py:96-99`), and
`execution_pipeline.py:4562` reads that set to choose `mode = "wta"`,
max-concentration construction. Its curated `payout_breadth` is 0.01; the
entered contest ran 0.235, a 23x gap, and no surface said so. **Writing the row
exactly as this entry specified would have made the build WORSE than the manual
override it replaces**, silently pinning WTA construction to a broad curve on
every future slate, where today the refusal at least forces a human to name a
posture. The row as actually written sets `payout_shape_default:
broad_micro_gpp` deliberately for that reason.

**The remainder, verified by re-running the inference the row is supposed to
drive.** Re-ran `build_slate.py` with NO `--postures`: `Micro Booster` resolved
`wta_satellite (name_inference)`, which LANDS; `Solo Shot` resolved
`single_entry (name_inference)`, which does NOT. Posture inference reads
`inferred_type`, and `se_gpp` is the truthful value there because the entry cap
really is 1, so it routes back to `single_entry_gpp` and back into WTA
construction. Nothing reads `payout_shape_default` for posture. **Until the
table can carry both facts, every Solo Shot still needs `--postures
<contest_id>=small_gpp` by hand, which is this entry's original tax unchanged
after six sightings.** Fix: make posture inference consult
`payout_shape_default` (or add an explicit construction-mode column) so a
single-entry contest with a broad curve is expressible. That half is DEV's, not
ARCHIVE's, which is why this entry stops being blocked on a write-set boundary.

**Three riders.** (a) Measured cost on this slate was near zero and that is worth
recording rather than generalizing: rebuilt under `small_gpp` and the frontier
did not move (apex 796.47 to 796.56, washout equal on both). **One number in the
source fragment does not reconcile and is left unresolved rather than picked:**
its §A reports the washout proxy for these two builds at 71% and its own §C table
reports the same two builds at 63.1%. Whichever reading is right, both builds
carry the SAME value, which is the claim this rider rests on; anyone acting on
the level rather than the equality should re-derive it from the run. A 2-game slate
gave the allocator `distinct_lineups_available: 13` for 7 entries and
construction mode had almost no room. **Do not read the null result forward:**
13 candidates is a 2-game artifact and the same defect on a 12-game slate has
far more room to express itself. (b) FIFTH data point for this entry's second,
smaller question: the Micro Booster printed `large_wta -> wta_satellite
[COLLAPSED]` on a 237-entrant field. The posture vocabulary exposes only
`wta_satellite`, mapping to `large_wta`, while `contest_shapes.py` also defines
`small_wta` and `mid_wta` that no posture can reach, so a 237-person field and a
six-figure field get identical construction. **(c) Not done, and owed:** the
`dk_contest_paid_places.json` companion was not touched. Both contests now have
an observed paid-place count (5 of 237, 350 of 1486) that belongs there if that
file is still what `--paid-places-from` reads. ARCHIVE's.

### R201. `MIN_AUTO_TEAM_COVERAGE` is a false negative on a small slate, and it overrides the tier the code's own docstring calls authoritative (P1, S) | new 2026-08-23, merged from ARCHIVE fragment `2026-08-22_ARCHIVE_team-coverage-floor-false-negative.md`; head of this workstream's remainder

- **What:** `field_miner.py:491-494` computes `result["team_coverage"] =
  len(drafted_teams) / len(salary_teams)` and requires it `>= 0.80` for a salary
  file to be usable. `team_coverage` measures how many of the salary file's
  teams THIS CONTEST'S FIELD happened to draft — a property of the contest, not
  of the file. A file can be the exactly correct one, join 100% of the contest's
  player references, and still be rejected because the field ignored two teams.
- **Why P1:** it destroys evidence, on the tier that cannot be wrong. Measured
  on slate `1507_3g` (ledger A-038, 2026-08-13, three games / six teams), where
  six contests share one manifest row, one `run_id` and one `DKSalaries.csv`:
  four resolved via the manifest and joined 100%, and two — 193662864 (23
  entries) and **193707894 (142 entries)** — were declined `standings_only` on
  `joined 100% with 67% team coverage`, losing their salary, stack and
  cheap-count tables against a file that is provably right. 142 entries rules
  out "tiny field". Two things make this worse than a badly chosen threshold.
  **It fires on the MANIFEST tier**, whose own docstring says it "is the
  authoritative tier and it exists because scoring cannot find it" — the
  manifest already knows which file the build used, by construction, and the
  resolver then scores that answer and throws it away. And **on a small slate
  the metric cannot land near the threshold**: with six teams the only reachable
  values are 4/6 = 0.667 and 5/6 = 0.833, so there is nothing between fail and
  pass and the floor is effectively "the field must touch five of six teams."
- **Fix:** three, in the order ARCHIVE would take them. (1) **Exempt the
  manifest tier from `team_coverage` entirely** — the tier exists because
  scoring is the wrong instrument, so applying a scoring criterion to it
  reintroduces the problem it was built to avoid; keep the join-rate floor
  there as a corruption check. (2) Floor `len(salary_teams)` before the metric
  is meaningful — under eight or ten teams the ratio is too coarse to carry a
  0.80 threshold and the check should report "not applicable" rather than a
  plausible-looking 0.67. (3) Report the decline reason distinctly, since
  `standings_only` currently covers both "no salary file for this slate exists"
  and "a salary file was found and scored below a floor", which are different
  facts with different remedies.

### R198. A mine costs 39s and 96% of it is avoidable; the registry rewrite makes a tranche quadratic (P2, S + M) | new 2026-08-23, merged from ARCHIVE fragment `2026-08-22_ARCHIVE_mine-cost-is-quadratic-in-the-archive.md`; cProfile-measured, not estimated

- **What:** `cProfile` on one mine on the Cowork mount with `--auto-salary
  --emit-ledger`: `field_miner.main` 39.444s cumulative, of which
  `resolve_salary_tiered` is 27.919 and `default_salary_candidates` alone is
  27.643 (1,121 `posix.stat` calls, 559 `pathlib.glob`), and `update_registry`
  is 10.421 with `_write_registry`'s `json.dump` at 10.161 for 6.8 MB. Two
  independent structural costs. **(1)** `default_salary_candidates(root)`
  re-globs three patterns and stats ~1,000 paths on EVERY mine, the list is
  identical across mines in one pass (no `DKSalaries*.csv` is created by
  mining), and it is computed UNCONDITIONALLY — including when the manifest
  tier is about to answer without ever looking at it, because
  `resolve_salary_tiered` evaluates it eagerly before it knows if it needs it.
  **(2)** `_write_registry` rewrites the whole registry per mine, so a tranche
  of N contests costs O(N × archive_size); at 271 archived contests that was
  10.4s per mine and it keeps rising.
- **Why:** a run-scoped memoization of `default_salary_candidates` (verified
  behaviour-preserving against an uncached call first) took the 108-contest pass
  from ~39s to ~12-22s per contest — ~70 minutes down to ~25, and on a sandbox
  with a ~178s call ceiling the difference between 4 mines per call and 8-17.
  The patch lived in `tools/_scratch_archive0822/` and was swept with the pass,
  so nothing in the tree improved.
- **Fix:** make `default_salary_candidates` LAZY inside `resolve_salary_tiered`
  (that alone removes 27.6s from each of the 47 contests the manifest tier
  answered in this tranche), and `lru_cache` it per resolved root with the
  invariant stated in the docstring: no salary file is created during a mining
  pass. Those two are S and independent. The registry is the M half: the honest
  fix is an append or keyed update rather than a whole-file `json.dump`, and if
  that is too large, a bulk-mode flag deferring the registry write to the end of
  a batch collapses N rewrites into one — `tools/rebuild_registry.py` already
  proves the batch shape is safe. Price the M half against how often a
  100-contest tranche actually happens.
- **RIDER 2026-08-24 (ed7 GF7-S3, Codex D22, both VERIFIED-read): the registry
  rework must split its aggregates by `contest_type`.** `field_miner.py:1348-1375`
  pools Classic and Showdown per-user construction stats into one record, and
  the quantities are not commensurable: `max_stack` tops out at 6 in Classic and
  5 in Showdown, salary geometry differs, and `dup_entries` inherits R225's
  captain-blind grouping outright. A pooled average over two roster contracts is
  not a number about anything. Cheap while the file is open for the rewrite;
  expensive later, because the pooled history has to be re-derived either way.

### R199. `rebuild_registry.py` sources standings CSVs, so three archived contests can never enter the registry (P2, XS-S) | new 2026-08-23, merged from ARCHIVE fragment `2026-08-22_ARCHIVE_registry-rebuild-cannot-see-three-archived-contests.md`

- **What:** ledger 3.19 established, after the R97 rebuild, that `contests_mined`
  equals the archive's contest ids exactly in both directions. After the 08-22
  pass: registry 375, distinct archive ids 378 (379 mined files; 192464820 is
  double-foldered under 07-18 and 07-19 per 3.16), none in the registry absent
  from the archive, and **three in the archive absent from the registry**:
  191787184, 191787186, 191823035. All three are 2026-06-29, all schema
  `0.3-review`, and all three carry BOTH a `contest_id` and a
  `meta.winning_entry_id`, so R74(a)'s legitimate "no contest identity" decline
  does not explain them.
- **Why:** structural, not a bug in the decline logic.
  `tools/rebuild_registry.py:98` globs `contest-standings-*.csv` — the rebuild's
  source of truth is the raw export, not the mined record — and
  `data/archive/2026-06-29/` holds three `mined_*.json` and an
  `ownership_rows_*.csv` with **no standings CSV at all**. The A-001 seed
  tranche's raw exports were never retained under that name, so re-running the
  rebuild can never close the gap, and the exports are 54 days old, which on
  this tranche's age evidence makes them unrecoverable from DK.
- **Fix:** two options, not equivalent. (1) Have the rebuild fall back to
  `mined_*.json` where no standings CSV exists — the mined record carries
  `entries[]` with `username` and `entry_id`, which is what the registry
  accumulates, so the fallback is real rather than a stub, and the invariant
  holds again. (2) Record the three as a known permanent exclusion and restate
  3.19's invariant as `contests_mined == archive_ids - retained_exclusions`.
  ARCHIVE recommends (1): the registry is derived data and the archive is the
  source, and right now the archive holds a source the rebuild declines to
  read. Three contests of 378 does not justify jumping the queue.

### R200. Three archival mechanisms the docs mandate have run zero, zero, and once (P2, S; one half is Ben's, not code) | new 2026-08-23, merged from ARCHIVE fragment `2026-08-22_ARCHIVE_runbook-mechanisms-that-never-ran.md`

- **What:** **(a)** `ls data/archive/*/contest_*.json | wc -l` → **0**. Runbook
  Job 1 step 2 mandates a per-contest JSON carrying entry fee, field size, paid
  places, cash line, payout structure, seats and Ben's own entry ids, and calls
  `paid_places` "required for the posture allocator (an UNRESOLVED tier blocks
  allocation)." In 379 archived contests it has never been produced once. The
  consequence is measured: **all 89 own-results records in this tranche carry
  `paid_places`, `entry_fee` and `winnings_total` null**, so
  `posture_allocator.classify_tier` returns UNRESOLVED for every one of them,
  permanently. There are now TWO mechanisms for the same fact and neither is
  fed — the per-contest JSON (never written) and
  `--paid-places-from data/reference/dk_contest_paid_places.json`, the parked
  export, dated 2026-07-29 and covering **0 of these 108 contests**; that file's
  own `_label` is stale too, claiming "the miner has no `--paid-places` flag,"
  which was true when it was parked and is not true now. **(b)** Ledger Section
  5 describes `ownership_rows_<slate_date>.csv` accumulating per slate as step 1
  of the ownership model's sequence. Exactly one exists,
  `data/archive/2026-06-29/ownership_rows_2026-06-29.csv`, from the A-001 seed
  on 2026-07-04; no mine since has written one and no code path does. **(c)** is
  filed as the R44 rider above.
- **Why:** a runbook step that has never executed in 379 contests is not a step,
  and leaving it in makes every archival session believe the field is capturable
  when it isn't.
- **Fix:** (a) pick ONE mechanism and retire the other from the runbook — the
  `--paid-places-from` path has a working CLI and a bulk shape, so the cheap
  answer is to delete step 2's JSON schema, replace it with "refresh the DK
  contest entry-history export into
  `data/reference/dk_contest_paid_places.json`", and say plainly that the export
  is the only source of `paid_places` and `seats`. **This half has a Ben-side
  blocker and no code fix: the entry-history export is a manual DK download and
  the current one ends 2026-07-28.** (b) either delete the claim from Section 5
  or make the miner emit it — but note first that it may be REDUNDANT now:
  `player_table` carries player, `pct_drafted` and realized `fpts` per contest
  and the salary join is available at `coverage: full`, so the long-format table
  is derivable from what is already archived. Decide that before building an
  emitter. Related: the R118 rider filed the same day.

### R38. `tools/net_to_date.py` prints an inconsistent TOTAL (P2, XS) | from ARCHIVE fragment 2026-07-30, merged 2026-08-01

Consumed fragment, verbatim:

> # Fragment: net_to_date TOTAL row uses a different denominator than the date rows
> 
> Session: ARCHIVE, 2026-07-30. For: DEV.
> 
> `python tools/net_to_date.py` now prints a table whose date column does not sum
> to its own TOTAL:
> 
>     date rows sum to   $64.21 in fees
>     TOTAL row prints   $51.46 in fees
> 
> Cause, in `tools/net_to_date.py`:
> 
> - line 109-110, per-date rows: `sum(... for r in rows)`, every row for that date
> - line 86-87, TOTAL row: `sum(... for r in graded)`, where `graded` requires
>   both a fee and winnings to be present
> 
> The 37 contests mined on 2026-07-30 (A-027, A-028) carry an entry fee harvested
> from the delivered DKEntries `Entry Fee` column but a null winnings, because the
> contest-page trio was not captured. They therefore appear in the date rows and
> vanish from the TOTAL.
> 
> The date rows are the correct ones. A contest with a known fee and unknown
> winnings has a known cost.
> 
> Suggested fix: compute the TOTAL from the same set as the date rows, and print
> the incomplete-money count as a separate note rather than by silently changing
> the denominator. The existing footer already says how many contests carry no
> fee/winnings; that sentence is now also wrong, since it reports 37 contests with
> "no fee/winnings" when all 134 rows in `ledger/own_results.json` carry a fee.
> 
> Not urgent and not a labelling problem. The output is still an observed outcome,
> it just does not add up.

### R187. ownership_pred buries an unreadable feed inside the JSON while the CLI prints "batting_order applied" (P2, XS) | new 2026-08-22, from the greenfield sixth edition; VERIFIED-read (`tools/ownership_pred.py` unchanged since the review)

- **What:** a supplied `--feed` that fails to read (the PowerShell UTF-16
  redirect trap is the live path) records its reason only at
  `inputs.batting_order.feed`; when DK covers some sides the CLI still prints
  `batting_order applied (N)` and the operator never learns the feed dropped.
  R127's missing-FILE-is-one-loud-fact doctrine is honored for odds and base,
  not for the feed.
- **Fix:** when `feed_note.read == False` and a path was supplied, one stderr
  line plus a top-level input reason. Rides any R135-family session.

## Closed number stubs

Numbers reserved forever; the records live in CHANGELOG.md.

### R190. FILED AND CLOSED 2026-08-23 -- F4's platoon hand died at three boundaries, entry migrated

Filed and landed in one session, so it never sat on the open board. The number
is reserved. Three sites, one term: `fetch_slate_bundle.fetch_lineups_feed`
fetched `batSide` and not `pitchHand`, so every probable left the bundle at
`hand: None` (30 of 30 on 08-18 and again on 08-19) and the platoon half of F4
was inert for every hitter while `bat_side` sat populated on all 270;
`build_slate.showdown_handedness` keyed the hand by the feed's raw team abbrev
against DK's `Opponent`, so `AZ` never matched `ARI` and one whole side's
platoon factor collapsed to 1.00; and the brief's `pool` block carried the
symptom (`f4_platoon_applied: 0`) while dropping both structured pool_report
facts a reader would join it to. **One mutation SURVIVED and changed the fix
rather than the test:** normalizing DK's own column as well passed every
fixture, because no honest fixture can put a non-DK code in a DK column, so
the symmetric half was dropped and the fix is one-sided — which is also the
shape of the defect. Merged from three BUILD fragments (08-18, 08-19 ×2) plus
the 08-19 Showdown fragment's item 1. Gate 1221 -> 1236. Full reasoning in
CHANGELOG.md.

### R47. CLOSED 2026-08-09 -- investigated, both mechanisms found, entry migrated

Neither mechanism was the one this entry proposed. The 8-10 scoring band is
`bank_cache.drop_stale_jobs` discarding candidates built under a different
exclude set, not a silent exception in `score_lineup_candidate` (all nine
2026-08-03 logs report `0 failed`, and the counter the entry asked for already
existed from F15). The `+0 targeted candidates` case is the same-game pair
filter in `usable_pairs`, not the targeted builder. The documentation half
shipped. Remainders refiled as **R101** (queue position 3) and **R102**
(opportunistic; renumbered **R103** on 2026-08-10). Full reasoning in CHANGELOG.md.

### R155. FILED AND CLOSED 2026-08-19 -- a fresh clone passes the gate, entry migrated

Filed and landed in one session, so it never sat on the open board. The number
is reserved. One test read a gitignored runtime file
(`data/slates/2026-07-25/lineups_feed.json`) off the disk that built that slate,
so it passed there and FAILED RED in every fresh clone: the only hard failure in
the 1217, printing `do not build` at the session-start gate and naming a feed
resolver rather than a missing fixture. It now builds its own repo skeleton and
runs a copy of the tool from it. Consequence worth the number: a container can
clone from GitHub with `GH_PAT` and run the pinned suite green in about 40s,
where the sync protocol previously sent it to a tarball of the working tree.
Remainder left open on purpose: two `test_core` tests still skip on an unstaged
2026-08-16 salary file, and vendoring a DK export to close them is a separate
decision. Full entry in CHANGELOG.md.

### R152. FILED AND CLOSED 2026-08-18 -- the split-run session gate, entry migrated

Filed and landed in one session at Ben's instruction, so it never sat on the
open board. The number is reserved. `python tools/audit.py --run-tests --terse`
cannot finish inside a Cowork `device_bash` call (hard-capped at 45s;
`tests.test_core` alone needs ~89s and one of its tests 35.8s), and the obvious
workaround is worse than the problem: a backgrounded run dies with the call,
its log comes back empty — which reads like a silent pass — and the killed
process strands the next commit on a zero-byte `.git/index.lock` (R109). The
gate now runs across calls (`--gate-run` until complete, then `--gate-report`),
and only a complete assembly may print the pinned clean line. Full entry and
the two findings that outlived the item in CHANGELOG.md.

### R104, R45, R105, R54. LANDED 2026-08-10 -- the Workstream 1 Showdown batch, all four entries migrated to CHANGELOG.md

Four numbers, one session, queue position 1. Numbers recorded so they are never
reused. Three things worth carrying forward that are not obvious from the
changelog entry's headline.

- **R104's open question is answered:** `viable_bulk_or_alt_sp` SURVIVES. PO
  stopped producing it, so it is now reachable only by explicit operator
  declaration, which is what the role always meant.
- **R105's exit-code discrepancy is settled by measurement, not by choosing a
  fragment.** The 08-05 and 08-06 fragments reported 2 and 3. It is **2** on
  both `preflight_upload.py` and `verify_export.py`, pinned by test; exit 3 in
  `verify_export` is the setup path, reached before any check runs, so the
  08-06 report was a different failure.
- **The R104 scope-note consolidation was DECLINED for this commit** and refiled
  as **R108** (Workstream 3). The token vocabulary is still read in two modules;
  what changed is that both sides now use named constants pinned in sync by
  test instead of two tuple literals.

### R61. LANDED 2026-08-09 -- entry migrated to CHANGELOG.md

Shipped whole, and wider than filed: SEVEN controls shared the two-denominator
asymmetry, not the one this entry named. Number recorded so it is never reused.
The open tail is **R61-tail** below.

## Open tails and items awaiting Ben

### Open tails from migrated items (full history in CHANGELOG.md, Imported record)

- **R61-tail (P3, XS):** `execute_portfolio` writes the initial build with
  `preserve_completed=True`, so a build from a template that already holds
  completed rows outside its own requirements has the same dual denominator R61
  fixed for the swap. Left unchanged deliberately on 2026-08-09: the initial
  build is byte-identical by decision (the R28 precedent) and no reproduction of
  that shape exists. Passing `fixed_portfolio_exposure` on the build path is a
  one-line change once someone produces a template that does it.
- **R1c-tail (data, Ben/ARCHIVE):** enter the curated satellite `ticket_count`/`objective_class` rows into `data/reference/dk_contest_archetypes.csv`; the observed table is ledger 3.14's recurring-families table. Schema and wiring landed 2026-07-27.
- **R25-tail (decision, Ben):** the late-swap minimal-repair fast path, filed as the decision half when the bounded parts landed 2026-07-29.
- **R34-tail (decision, Ben):** the three `status: upload_ready` Showdown records still sitting wrong in `outputs/2026-07-29/upload_manifest.json`; rewriting history in a provenance file is Ben's call, not DEV's.
- **Sync-tail (Ben, blocked on him alone):** `bleeski/mlb-dfs` is private and the container has no credential, so the disk-to-container path stays the tarball bridge. One fine-grained PAT scoped to that repo (Contents read/write), stored as `GH_PAT=` in the gitignored `.env`, lights up `sync_check.py`'s GitHub leg with no code change. Transport rule from the fragment, non-negotiable: stage `.env` as a FILE and source it; never `cat`, `grep`, or `echo` the token, because tool output is transcript. R62's fixture vendoring used to be sequenced behind this and no longer is: it landed 2026-08-10 at 84 KB, which is smaller than fixtures already tracked, so the size premise that deferred it was simply wrong. Nothing on the board is waiting on the PAT now; the sync-tail is worth doing for the container's sake alone.

---

### R225. Showdown duplication counting is captain-blind at all three miner sites, and Tier 2's grading substrate inherits it (P1, S; PRECONDITION ON R10) | new 2026-08-24, from the greenfield seventh edition (GF7-S1) and independently from the outside spec (D20); VERIFIED-read at all three sites, coordinator-re-read, re-read here

**Rider 2026-08-28 (ARCHIVE):** independently confirmed twice more — the root
greenfield standings doc re-derived the defect from DK lineup semantics without
reading this board, and ledger 3.21's code read pins it (`players_norm` keys
`dup_groups` at :770 while `captain_norm` rides every entry unused by the key).
3.21's own duplication tables hash the raw Lineup string (CPT-aware) and serve
as interim corrected counts: SD 1k-10k fields run 49% of entries duplicated,
mean max copies 32, winner duplicated in 16-28% of contests — versus ~1% and
1% in the <100 Classic satellites we mostly enter.

**What.** `field_miner.py:770`, `:1244`, `:1343`. `players_norm` is a sorted,
position-blind tuple by design (`:264`, and the R39 comment says so). All three
duplication computations key on it alone:

    dup_groups[e["players_norm"]].append(e["entry_id"])          # :770
    groups[tuple(entry["players_norm"])].append(...)             # :1244
    groups[tuple(e["players_norm"])].append(e["entry_id"])       # :1343

so two Showdown entries with the same six PEOPLE and different CAPTAINS count as
copies. They are not copies: different captain, different salary, different score.
Classic is unaffected — `players_norm` is a complete identity there.

**Why this outranks its severity class.** It is the first defect found INSIDE the
archive, and the archive is the one asset in this project no vendor publishes.
Every Showdown duplication number in ledger 3.17 that R10's entry cites is inflated
by construction: the 27.2% median duplicated share, the "winning lineup duplicated
40% of the time", the own 27/109. R10's bar READS duplication from the miner, so
grading any Showdown cell against these counts grades against a construction
artifact. R10's currently unblocked satellite cell is Classic, which bounds the
damage to Showdown cells and to `dup_entries` in the opponent registry (R226's
neighbour, and R198's rework inherits it).

**Fix.** One identity function used at all three sites: key Showdown groupings on
`(players_norm, captain_norm)` and Classic on `players_norm`, with a contest-type
switch and a refusal when a Showdown entry carries no `captain_norm`.
**`captain_norm` already rides every parsed entry, so the corrected counts are
re-derivable from the archived `mined_*.json` files with NO re-mine.** ARCHIVE adds
a one-sentence caveat to ledger 3.17's Showdown duplication rows at the next pass,
and removes it when the recount lands. R10 gains "Showdown cells blocked until R225"
in its gating line.

### R226. The contest "winner" is the max-points complete entry, not the verified rank-1 row (P2, XS) | new 2026-08-24, from the greenfield seventh edition (GF7-S8) and independently from the outside spec (D21); VERIFIED-read, and cheaper than the outside spec assumes

**What.** `field_miner.py:775-779`:

    winner = min((e for e in complete if e["points"] is not None),
                 key=lambda e: (-(e["points"] or 0.0)), default=None)

`complete` excludes entries whose lineup would not parse. So an unparseable
WINNING lineup silently shifts `winning_points` and `winner_copies` to second
place, and the winner-construction statistics that flow from it describe the runner
up.

**Why.** Winner construction is a Tier 2 input and it is labelled as an observed
outcome. An observed outcome that is silently the second-best observation is the
truthful-labels rule broken inside the archive, same family as R225 and worth
landing with it.

**Fix.** Cheaper than the outside spec's remediation assumes: **rank is already
parsed at `:256` and already stored at `:1025`** (`parse_standings_export` reads the
rank column; the comment at `:1021` records that it "was parsed and then dropped
here" and that G4 restored it), and `:1234` already coerces it. So verify rank 1
rather than reconstruct it: select the rank-1 row, take max points among ties, and
emit a winner state — `OBSERVED`, `TIED`, or `UNKNOWN_NO_RANK_ONE` — instead of
silently substituting. No re-mine: the archived JSONs carry rank.

### R227. `contest_library`'s registry is a naked truncate-write with a crashing load, on a file its own sibling was hardened to protect (P2, XS) | new 2026-08-24, from the greenfield seventh edition (GF7-S2) and independently from the outside spec (D23); VERIFIED-read at `contest_library.py:177-189`. Absorbs two adjacent hardening notes from the outside spec.

**What.** `save_registry` (`:185-189`) is
`Path(path).write_text(json.dumps(...))` — direct truncate, no temp file, no
replace. `load_registry` (`:177-182`) is a bare `json.loads` that raises on a
malformed file with no quarantine. `field_miner.py:1385-1392`'s `_write_registry`
was hardened for exactly this kill vector; this sibling was not.

**Why.** A kill mid-write, a full disk, or a concurrent session destroys the
registry, and the next load crashes rather than quarantining. The outside spec (D23)
calls this inconsistent with the helper already in the repo, which is the right
framing: the fix is a copy, not a design.

**Fix.** Copy `_write_registry`'s tmp-plus-`os.replace` body (with `fsync`);
quarantine on decode error rather than raising. **Two riders adopted here from the
outside spec, both severity-reduced at adjudication:** (a) D26, `extract_inbox_zips.extract_zip`
reads each CSV member fully with no member-count, size, ratio or basename-collision
limit. Filed as prevention, NOT as Security: these zips are DK exports Ben
downloads himself, so the threat is a corrupt or oversized export, not an
adversary. Add a member cap, a byte cap and a duplicate-basename refusal. (b) D24,
`execution_pipeline._write_json` and `_write_assignments` (`:202-221`) are direct
truncate-writes. Bounded: these are run-directory DIAGNOSTICS; the certified
`final/DKEntries.csv` is written on a different path (`:461`) and is hash-bound by
the manifest. Route them through the same atomic writer while it is open.

# Do not build (updated)

Everything on the 07-25 list stands, with the CC review adding urgency to two of them: no Monte Carlo field-ROI engine or play-by-play simulator until R13 scales stakes and R10's ownership is calibrated (CC's Phase 3 proposes both now, on top of a projection base it misidentified); no PuLP migration or remediation (the repo has never used PuLP; CC's central performance claim is false against this tree); no `bank_cache.parquet` (a dependency for no measured problem); no promote-command ceremony or dual-track state machine beyond R3's manifest fields; no watcher daemons (Cowork's primitive is the scheduled task); no under-30-line CLAUDE.md absolutism (the contracts stay); no four-contract module extraction beyond R1's enum (RC 1.12's own caveat agrees); no live payout-table parsing (the DK wall is absolute; the curated archetype CSV is the vehicle for contest knowledge); no per-slate codebase reviews (this file is the live backlog; the next review-shaped document should be written when this list is substantially landed, not before).

- The `mlb-game-odds` skill's own key resolution (R29(5) residual): unfixable from a Cowork session; needs a hand edit outside Cowork.

**Sim-gate precondition, adopted 2026-08-14 from the ed4 review (§3), one
sentence so the gate cannot mislead the session that eventually opens it:**
the sim ladder additionally requires a per-player variance basis. Uniform
Floor and enriched-Ceiling marginals give CV in [0.26, 0.40] driven by power
alone; `slate_sim.py`'s static tail was structural — sigma a constant
multiple of mu — not a volume artifact, so reopening the ladder without a
variance basis reproduces the v2.20.0 retirement. R13 and R10 remain the
funding gates; this is the third, technical precondition. A fourth clause,
adopted 2026-08-17 from the fifth edition's §3.10, same one-sentence class:
when the ladder opens, selection and grading run on SEPARATE scenario banks
with logged seeds — a portfolio graded on the worlds that selected it has
not been graded — and settlement ranks all own entries in the same simulated
contest JOINTLY, because summed standalone lineup values overstate a
portfolio whose entries compete with one another.

The 2026-08-01 GF-spec adjudication (R41/R42 changelog entry) adds, same
logic: no greenfield parallel package or phased rebuild program while R13 is
undecided — the spec's premise, a calibrated EV core, is exactly the
investment R13 decides whether to fund; no transactional-DB run-state machine
and no HMAC-signed manifests (the threat model is operator error, not
adversaries; sha256-in-brief plus preflight already binds the file); no
CP-SAT migration (`scipy.optimize.milp` is pinned authority and no measured
problem exists); no machine-readable evidence-policy engine beyond R9b's
MUST-claims rule; no async acquisition service (the six-file urllib
duplication is real and has produced zero measured lock-window failures, and
R32 made paste primary exactly so live fetches stop mattering); no
per-player-actuals grading harness yet (it inherits Finding 15's disposition
as a named dependency of R13, and note the "no prediction ledger" claim was
partially false — every run already persists `final/projections.csv`
immutably). The spec's Phase 0 is, for the record, a subset of this file's
what-next list: external confirmation of the ordering, not new work.

The 2026-08-10 greenfield-revision adjudication adds nothing new to this
list, and that is the finding: the revised spec re-argues the greenfield
program (a `dfs_vnext` package, fifteen ordered epics, SQLite/WAL authority,
a persisted FSM, signed promotion manifests, CP-SAT benchmarking, an
evidence-policy resolver, scenario banks, a contest settlement engine) with
no new evidence since 2026-08-01, and every prior rejection stands on its
prior reasoning. Two of its factual premises were re-checked and failed: the
"phantom simulation modules" claim (F-05) is false — MLB_Classic.md banners
all three "Retired ... not present in this repo" at lines 520/547/563 — and
the "score mistaken for EV" framing (F-02) demands the exact label discipline
`contest_allocator.py:35-36` already carries verbatim. Its F-33 asks Ben to
supersede these anti-goals outright; DEV's recommendation is no. The gate is
not protecting proxies from economics, it is refusing to fund an EV core
before R13 makes the stakes rational, while the prerequisites any future EV
system needs are exactly what IS funded: archive integrity (R93–R97, landed),
the satellite ownership-and-duplication prior (R10, unblocked and graded on
the duplication distribution), the leverage table (R48), and curated contest
truth (Ben's 2026-08-09 archetypes decision). The one thing the revision
does earn is recorded in this file's numbered items: where it named defects
your own BUILD fragments had already hit live (F-16, F-20, F-21), the items
were filed on the fragments' evidence (R104, R105, the R45 elevation). Its
A-25 Showdown "defaults" (captain ≤ floor(0.33·n), pairwise overlap ≤ 4) are
the values this engine already ships, cited here because a critique
endorsing the current controls as its recommendation is a data point on the
controls.

The 2026-08-12 re-audit (third edition of the same spec, reviewed at 6c96474
= this HEAD) again adds nothing to this list. Its delta against the
adjudicated 2026-08-10 edition is two new sections and five concessions:
F-02, F-05, F-16, F-20 and F-21 are rewritten to grant the facts the 08-10
adjudication rejected them on (the label discipline, the truthful retirement
banners, the repaired manifest vocabulary, paste identity, PO/PLR policy),
F-30 and F-31 now grant the current pins and that no scenario bank exists to
leak, and a new method section labels the reviewer's own runtime claims
environment-limited. Both new sections are rejected on standing grounds.
F-35 (the claims protocol is advisory) cites this repo's own 2026-08-11
incident back at it: the accepted work is already filed as R31(c)(d) and
R110, the adopted mitigation — commit early, because the blast radius is
uncommitted work — went into CLAUDE.md the morning this edition arrived, and
the proposed remedy (database leases, fencing tokens, a read-only checkout
during builds) is the transactional program this list already rejects. A-43
(the "exact zero-touch execution contract") is that program's operating
procedure; its one hard wall, that the system never touches DraftKings,
restates CLAUDE.md's money-and-entry wall, and its steps map onto mechanisms
that exist (runs/ input snapshots, the approve gate, preflight, the
T-schedule, the archival runbook), while its "budget normal critical-path
LLM calls at zero" is R63's one-command direction, already the board's. The
new audit-method counts were spot-checked and are substantially accurate
(724 tracked files exact, 267 archived standings CSVs exact, 6 test files
exact), which is the first edition of this document to survive its own fact
check — and the convergence cuts the other way: a re-audit that concedes
five findings and whose two new sections describe an incident and a wall
this repo recorded first is evidence the board's record is current, not that
the rebuild program got stronger.

The 2026-08-12 Gemini pair (Spark and Pro, adjudicated the same day as the
GF third edition) adds nothing and re-argues two documents this list already
answers. Spark is the 07-25 CC program again — the iterative-PuLP premise,
`bank_cache.parquet`, the <25-line CLAUDE.md, watcher daemons, the
play-by-play sim and duplicate-penalized field-ROI stack, now with sample
code that un-ships the Entry-ID and certification contracts. Pro is the
2026-08-01 Gemini critique again, now recommending PuLP as the greenfield
engine as well as misdiagnosing it as the current one. Every prior
rejection stands on its prior reasoning and R13/R10 still gate the
sim/economics stack. The only new elements die on the walls: scripted DK
polling and auto-upload with "no human review step" are the DK wall and the
money-and-entry wall (and prohibited by DK's terms per the GF third
edition's own compliance section), and Pro's "burn down the local CSV
archive structure" would delete the append-only calibration substrate.
Convergences kept as data points, not adoptions: Spark's headless
single-command build with atomic JSON state describes `build_slate.py` +
`build_state_manager.py` as shipped, and both critiques' LLM-out-of-the-math
rule is CLAUDE.md's own.

The 2026-08-17 fifth edition (a 1,912-line, 50-finding static audit plus
target architecture, uploaded and adjudicated the same day, archived at
`docs/2026-08-17_critique_greenfield_spec.md`) adds one rider and one
sim-gate clause, recorded above, and its headline fact is about itself: it
audited the WRONG TREE — `C:\Users\benja\Documents\MLB_DFS_Workbench` at
`28aeaa8`, the pre-migration workspace whose engine lineage this repo
superseded when MANIFEST.md's 2026-07-16 seed left `legacy/v2_15_1` behind.
Every load-bearing path in its defect log (an `engines/adapters/` Showdown
adapter that never reads its rules file, `metric_projection.py`,
`portfolio_waterfall.py`, `stack_adjacency.py`, PowerShell certifiers,
`prompts/*.md`) has zero references in this tree, and its "no results
history, no calibration corpus" premise is answered by the 271-contest
archive and R135's first graded slate. Where its findings map onto live
surfaces the board already holds them: bounded solves and
`optimality='time_limited'` shipped, neutral defaults NAMED (R127), corrupt
manifests QUARANTINED (R129), override flags into the brief (R36 F3m, Tier
1), Showdown certification R41, caps and captain reporting R123, bank
honesty R115/R130/R132, test depth R79/R90/R91, intake identity R75/R81.
The rebuild program it re-argues — CP-SAT as default (the fifth
solver-migration proposal against a pinned authority with no measured
problem), a content-addressed artifact store, an SQLite DAG orchestrator
with leases, signed Merkle manifests, model cards, CI/SBOM, a
requirement-to-test register — is rejected on the standing grounds above,
unchanged since 08-01 and re-affirmed 08-10 and 08-12. Its compliance
boundary (stop at a certified file, never automate DraftKings, Fair Play
Commitment cited) restates CLAUDE.md's walls minus this repo's stricter
no-DK-reads rule, and its label taxonomy (`DIAGNOSTIC`, never
`EV_CERTIFIED`) is the truthful-labels law reinvented; both kept as
convergence data points. Its own strongest recommendation — do not promote
the workbench engines, preserve inputs as fixtures, build the successor
beside them behind an independent check — is a description of the migration
this repo already is.

The 2026-08-04 audit adds, same logic: no module-split program and no engine
rewrite argued from the giant-file line counts alone — the audit found the
size is only now starting to produce divergent copies (the scrub fork, five
independent Classic-geometry constants, three odds clients), and the accepted
forms are R79(d)'s cross-pin equality tests, R80-style consolidations into
one imported helper, and the roster_contracts rewire already documented in
that module's own SEQUENCING note, each under the golden gate. Extraction for
its own sake stays rejected.

The 2026-08-24 double adjudication (ed7 + the outside Codex spec) adds four
rejections and, for the first time, one of them is a rejection of a review's
reading of an existing DECISION rather than of a program:

- **The rebuild program, seventh rejection, unchanged.** The Codex spec's
  Section 3 re-argues the whole family: SQLite run database with WAL, a
  content-addressed artifact store, a persisted FSM/DAG orchestrator with
  leases, signed release manifests, an OCI production image, a CP-SAT-capable
  solver backend, and a seven-phase migration. Standing grounds hold and no
  lane in either review found a measured problem those programs solve. Two of
  the three concrete harms the artifact store is justified by are filed here as
  one-function fixes (R227's registry write and its D24 rider); the third
  (`latest_valid_run.json` as a cross-session race, D35) is REJECTED on the
  facts: it has ONE consumer (`preflight_upload.py:369`, which is R191), the
  spec's second cited consumer in `late_swap_manager` does not exist, and
  `build_state_manager.py:5` already carries the spec's own doctrine verbatim
  ("`latest_valid_run.json` is only a pointer; it is not an artifact").
- **The EV diagnosis is accepted and is not new; the ORDERING is rejected.**
  C01, C02 and C05 say the objective is a proxy, the field is not
  contest-conditioned, settlement is not exact, and scenarios used to tune are
  reused to report. Every one of those is this project's own Truthful-labels
  rule, written into CLAUDE.md before either review existed, and the sim gate's
  four clauses already carry C05's separation. What is rejected is building the
  scenario/field/settlement stack FIRST: Tier 2 reaches the same destination
  from the archive that already exists, R118's head just got cheaper (the
  `player_table` FPTS rows survive the strip, so no miner change and no
  re-mine), and R13 is the funding gate for precisely this decision. Building
  the machine that would measure the rebuild, before the rebuild, is the only
  sequence that can say whether the rebuild was worth it.
- **C04 (the runtime lock is a Blocker because it will not install on
  Windows/3.13) is rejected as filed.** `requirements.lock`'s own header names
  its scope — "the supported runtime: Python 3.10, linux x86_64 (the Cowork
  sandbox the engine runs in)" — and names `requirements.txt` as the
  cross-platform floor and the audit's import-name source. A deliberate,
  documented scoping decision was read as a portability defect by a reviewer
  whose environment lacked the packages. What survives is small and is filed as
  R217(d): the gate record does not stamp runtime identity, and this tree's
  `__pycache__` proves two interpreters have run against it.
- **D29 (roster contracts "not truly centralized") is rejected.**
  `roster_contracts.py`'s module docstring states the deferral in full, names
  the golden-replay condition it is waiting on, and a test asserts CLASSIC
  against the shipped engine's constants. A documented deferral under test is
  not a defect. The spec's proposed additions (`effective_from`,
  `template_schema`, `validate_extra`) are the rebuild program arriving as a
  dataclass; the accepted form remains the 2026-08-04 audit's: the rewire
  documented in that module's own SEQUENCING note, under the golden gate.
- **D30 (monolithic functions, 500-939 lines) is rejected as a program**, on
  the 2026-08-04 grounds, restated: no defect in either review is attributed to
  function length that is not already filed as itself. The cheaper form of the
  same insight is ed7 §1.2 and it is adopted as R233 — enumerate the class at
  the fix, in the CHANGELOG entry — which converts the most-repeated finding
  shape in seven editions into a diff-time check for one sentence and no code.
- **D26's Security severity is rejected; the fix is adopted as prevention.**
  The inbox zips are DraftKings standings exports Ben downloads himself. The
  threat is a corrupt or oversized export, not an adversary, and framing it as a
  ZIP-bomb vector would put a security label on the one surface the DK wall
  guarantees is operator-supplied. Filed as a rider on R227.

Both reviews' compliance boundaries — no DK login, scraping, upload, entry
submission, credential storage or browser automation; the two manual clicks as
constraints rather than friction — restate CLAUDE.md's walls, the Codex spec
additionally citing DK's Terms of Use, Fair Play Commitment and bulk-upload
help page. Kept as convergence data points, as ed3-ed6's were. Neither review
proposed automating DraftKings and neither is treated as having asked.

The 2026-08-27 adjudication (Codex ed8, reviewed at `245de51` = the live HEAD,
zero drift) adds the eighth consecutive rejection of the rebuild program and
three re-rejections, each on standing reasons with the new edition's framing
answered. **The program (spec §§3.1-3.24: contracts package, content-addressed
artifact store, FSM orchestrator, probabilistic player model, contest-
conditioned field sampler, exact settlement engine, joint package-MILP
portfolio, OCI-pinned runtime, phased burn-down):** rejected on the ordering
argument, unchanged since 2026-08-01 — it builds the machine first and
measures second, R13 is the funding gate, and Tier 2 reaches the measuring
substrate from the archive that already exists. What the edition earns is
recorded where it belongs: fifteen numbered items on its and the week's
fragments' shared evidence (R236-R250), twenty-nine corroborations, and ONE
adopted architectural idea — F-48's exact settlement, taken as a RIDER on R118
because settling replays at archived payout curves is accounting over observed
outcomes, not simulation; the sim gate's four clauses are untouched. **F-26
(roster-contract centralization):** re-rejected; D29's answer stands — the
deferral is stated in the module docstring with its golden-replay condition
and a test asserting CLASSIC against the engine's constants; ed8 cites the
docstring itself, so this is now a judgment difference, and the judgment
stays: drift risk priced, unification deferred to the named condition. **F-27
(decompose the monoliths):** re-rejected, Tier 6's bar unchanged — no named
measurement. **F-46 (certification runtime not reproducible on the reviewer's
host):** C04's re-file, re-rejected on the lock's own header naming its scope
(Python 3.10/linux) and `requirements.txt` as the cross-platform floor;
R217(d)'s runtime-identity-in-the-gate-record remains the accepted sliver, and
R78 keeps the environment-floors remainder. **F-49 as a gate artifact:**
rejected as filed — a CalibrationGate dataclass without the model it gates is
scaffolding; the direction it wants IS Tier 2's predict-then-grade loop, which
R135 wired and R154 graded first. **The joint-portfolio replacements inside
F-30/F-35/F-36/F-37/F-41** ("delete the thesis ladder, solve all entries
jointly against scenario returns"): rejected as build-first ordering; the
operational halves — round-robin dealing, per-contest caps and reporting,
captain-budget reservation, cap-cost visibility — are accepted as R239, R247
and R250, which reach the named harms without the settlement stack. F-50
restates the money-and-entry wall and is convergence data, treated as ed3-
ed7's compliance paragraphs were.

The 2026-08-27 greenfield instruction (Ben, dated, in-session) NARROWS one
line of this list rather than deleting it. "No Monte Carlo field-ROI engine
or play-by-play simulator until R13 scales stakes and R10's ownership is
calibrated" now reads with a carve-out: **own-portfolio outcome banks whose
outputs are pre-lock predictions graded in the ledger (R259–R261) are in
scope**, because they simulate OUR lineups against archive-mined thresholds,
not the field — no opponent lineups, no ROI arithmetic, no prize-share
claims. What stays behind R10 + R13, unchanged: opponent-lineup/field
simulation, duplication-conditioned prize-share estimates, and any ROI
statement. The four sim-gate clauses are unchanged in substance and become
the lane's acceptance criteria: the variance basis is R259 (clause 3),
separate seeded banks for selection vs grading and joint settlement of own
entries are R261's design requirements (clause 4), and R13/R10 gate R262's
production switch (clauses 1–2). Reopening the sim ladder is therefore a
sequence of graded steps, not an event, and the v2.20.0 retirement's cause
(sigma as a constant multiple of mu) is the first thing the lane replaces.

The 2026-08-28 adjudication (Codex ed9, the leverage/portfolio spec,
reviewed at `0a83cac` = the live HEAD — the second consecutive edition with
zero drift, and the first aimed at the R251–R262 lane itself) adds the
ninth consecutive rejection of the rebuild program and five targeted
rejections; its accepted matter landed as dated riders on the lane's own
entries, and zero new numbers were minted. **The program (§5's Level 1–2
event/field simulation, §6's field-construction models, §8's module
tree/contracts package/zero-touch pipeline, §10's Phases 0–6):** rejected
on the ordering argument, unchanged since 2026-08-01. Its own Phases 0–4
map onto the funded lane as corrected (snapshot freeze = R251, salary
baseline = R252(a) + R259's buckets, threshold bridge = R258, scenario
banks and columns = R259–R261, Pareto shadow = R262) — convergence on the
sequence, not new work — and everything field-conditioned (opponent
lineups, duplication-conditioned prize share, exact field settlement, any
ROI statement) stays behind R10 + R13 per the 2026-08-27 narrowing
paragraph above, which this edition does not move. **Contest routing
(§4.7):** rejected — choosing and funding contests is Ben's manual action
behind the money-and-entry wall; the evidence half it wants (which
archetypes post thresholds our construction reaches) is already R258's
table, named there for R13. **Model-ensemble robust optimization and CVaR
(§4.6):** machinery with no graded model to ensemble; revisit only after
R261's grades exist, and the spec itself ranks CVaR tertiary. **The §2.4
signal families (bullpen availability/fatigue, stolen-base opportunity,
bat-tracking, PA distribution, times-through-order, umpires, defense,
public-attention residual):** not filed — each enters only through R255's
residual-priced pull condition (R253's sequencing rule, generalized), and
the table is kept as the reference list in the archived edition. **The
§2.5 REGISTER ceremony** (machine-readable hypothesis files,
multiple-testing families): the one-line form is adopted as R255's rider
(predeclare the metric, report failures); the ceremony is not. **§8.1's
"remove the artificial module cap":** rejected as a misread — the audit's
module count is an inventory pin read off the filesystem, not a cap, and
no architecture decision here has ever been gated on file count
(2026-08-04 grounds). **§7.3's cap demotion as a present-tense control
change:** the end state is R262's own design, but it arrives only behind
R261's grades and the Tier 4 switch; until then R153's caps stand as
shipped. What the edition earns is on the entries it reviewed: the
conditional-threshold correction (R258/R261, accepted in full — the one
correction that changes math), the epsilon-constraint frontier replacing
R262's weighted sum, slate-wide shared scenarios and the MC-error line on
R261, the tail-axis and predeclared-metric grades on R255, the
market-total ablation on R253, the negative-dependence row on R260, and
captain OPTIMALITY as R254's stage 2.

# Board history

Relocated 2026-08-10, verbatim: the what-next amendment record and the
dated tranche introductions that used to wrap the entries above.

## Relocated 2026-08-22 (ed6 adjudication): queue amendment notes, verbatim

*2026-08-18 (third session), DEV, claim `engine_2026-08-18`: **R133 is CLOSED
and migrated** to CHANGELOG.md, taken in tier order as Tier 1's head. Parts (1),
(3) and (4); (2), the equal-weight seeded ninth, is filed to MLB_Classic.md as a
selection question and is Ben's. **R121 is the new head of Tier 1** — it is the
next P1 in the queue, it is S, and it is the only remaining item that changes
what a session BELIEVES at decision time rather than what a report says
afterward. Four things worth reading before the R-number, and three of them
changed the entry as filed. **First, the contract's 5-of-9 bar was already in
the code and the blocker CONTRADICTED it.** The entry read as though no such bar
existed; `live_data_adapters`' confirmed path has always blocked at `n < 5` as a
crosswalk failure and warned from 5 to 8, twenty lines above the loop that then
blocked at `< 9` on the same team and the same fact. The filed fix, "move the
blocker to the contract's 5-of-9 bar", would have produced two blockers on one
team; the fix it needed was for the later loop to stop re-deciding a decided
question. CLAUDE.md and SKILL.md both scope their 5-of-9 sentence to a
name-crosswalk failure and always did — one bar was read as governing the other
check. **Second, there was a THIRD reader and it decided certification.**
`_derive_workflow_gates` recomputed `thin` at `< 9` from the same teams dict and
independently of the blockers list, so the sharpest case is one the entry did not
have: a confirmed team at 8 with no status-dropped rows produced NO blocker at
all, and the build still could not certify. `--ignore-pool-blockers` had nothing
to override. **Third, the paste module's docstring claimed the opposite of the
code on the exact point**, ending "the team stays confirmed" where `lineup_status`
has never been `confirmed` below nine rostered rows; the source fragment quoted
the paragraph above that sentence and missed it. Corrected in place. **Fourth,
the fixture lesson landed for the FOURTH consecutive item, and this time the
fixture was a copy of the code.** Seventeen mutations by hand and all seventeen
caught, but two survived the first pass because the test helper had copied
run_slate's fifteen-line gate merge instead of calling it — a test over a copy of
the logic pins the copy. The remedy was extracting `resolve_gate_assertions` so
both call one thing, which is the first time in this run of four that the answer
was to make the code testable rather than to fix the data. R117, R136 and R128 are
the same shape one layer out. One mutation also read SURVIVED off a stale
`__pycache__` and was a harness artifact rather than a weak guard; the harness now
clears it between runs, and a mutation harness that can lie in the reassuring
direction is worse than none. What the work established that the entry did not
carry: the crosswalk bar and `MAX_HITTERS_PER_TEAM` are the same number for
different reasons (five fills a maximum DK stack), so the new bar reads the solver
constant instead of copying a doc; and `assumed_gates` was recording a request
that had no effect, which is a truthful-labels problem and not only a broken flag,
which is why the override is a separate key carrying the evidence it contradicts.
(4) was verified by RUNNING both overrides rather than reading them and both
reproduced. Gate 1157 -> 1182 (`test_upload_integrity` 218 -> 238,
`test_paste_lineups` 82 -> 87, both `grew`); CLAUDE.md, SKILL.md and the ledger
Quick Card pin line moved with it, the last under a DEV-held `ledger` claim, that
line and nothing else. CLAUDE.md's autonomy and hard-guardrail bullets and
SKILL.md's pool-warning section also moved, because both described behaviour this
item changed.*

*2026-08-18 (second session), DEV, claim `engine_2026-08-18`: **R117 is CLOSED
and migrated** to CHANGELOG.md, taken in tier order as Tier 1's head. **R133 is
the new head of Tier 1** — the tier already recorded why R117 outranked it (R117
changed SELECTION, R133 changes labels and overrides), and that reason is spent.
Four things worth reading before the R-number, and three of them changed the
entry as filed. **First, the entry named the wrong line.** There is no dropped
continuation line: `_HAND` was anchored on `$`, and mlb.com renders the
probable's hand two ways — alone on its own line (Ben's 07-29 paste, which always
parsed correctly) and with the record trailing it on ONE line as
`RHP 8-7, 3.87 ERA, 144 SO` (the 08-13 paste), which fell into the `_STATLINE`
branch and was consumed as decoration. The module docstring carried the first
render as though it were the only one, and that is how the assumption survived
three slates; corrected in place. **Second, the silence had three faces and the
entry named one.** Measured on the real fixture re-rendered the joined way:
both pitchers `None`, `parse_paste` warnings `[]`, both hitter sides resolving
perfectly. `_assign`'s "0 or exactly 2" rule then reads a pitcher count of ZERO
as "no pitcher lines were pasted" and by design does not warn, and
`_flush_pending` writes the held name into `game.venue` — a venueless paste came
back `venue='Hayden Wesneski'`. The DK `Starting` fallback's null id plus empty
hand is the fourth face and the one the entry had. **Third, the loudness half
generalized past F4 without being asked to.** F1 and F5 carry the identical
"every value is neutral" condition, so the classification is factor-general, and
the load-bearing distinction is INERT (scored rows, moved none) against ABSENT
(scored nothing) — different facts, different remedies, and folding them together
is how "F4 is off for this build" came to read as routine enrichment noise.
`factors_inert` sits BESIDE `gates` and not inside it: those three keys are the
certification vocabulary, an inert factor certifies nothing and blocks nothing,
and a review proxy among them reads as a gate. **Fourth, the fixture lesson
landed for the third consecutive item.** Fourteen mutations were run by hand and
fourteen caught, but dropping the held name SURVIVED until a seventh test was
added, because the fixture carries `Angel Stadium` before the pitcher block and
`_flush_pending` only writes a venue when there is not one — that fixture cannot
distinguish the two behaviours, so the guard read green while pinning nothing.
R136 and R128 are the same shape. Gate 1139 -> 1157 (`test_paste_lineups`
75 -> 82, `test_core` 781 -> 792, both `grew`); CLAUDE.md and SKILL.md pin lines
moved with it, and SKILL.md's paste section grew a sixth item naming the
symptom (`DK STARTING` on every side of a paste that clearly named pitchers).
The falsifier on the entry was checked and did NOT fire: the frozen salary
header carries no handedness column, so the parse half stands rather than
shrinking to the loudness half. The entry's rider — derive the slate tag before
lighting the beacon so claims and artifacts agree — did not land here and moves
to R131's smalls; it is a claims-naming fact and shares no surface with the
paste or the brief.*

*2026-08-18, DEV, claim `engine_2026-08-18`: **R136 is CLOSED and migrated** to
CHANGELOG.md, taken in tier order as the head of Tier 1 and of its QA batch,
which R135 had unblocked the day before. **R117 is the new head of Tier 1**: the
batch's three substantive entries (R127, R126, R136) are all closed and its
remainder is R130 + R131, both P2 and XS-S with one half of R131 being Ben's, so
they sweep opportunistically rather than holding a tier slot. R117 is the only
P1 above them and it changes SELECTION where they change labels. Four things
worth reading before the R-number, and the first two changed the entry as filed.
**First, the sub-10% carry column as specified is a constant.** Ledger 3.17's
threshold is an absolute 10% on ACTUAL %Drafted; the v0.1 prior spreads its 800%
hitter budget over every priced hitter row, which on 1905_7g is 284 rows with a
mean of 2.8% and a top hitter of 8.9%, so all 284 are "sub-10%" and the literal
column returned 8-of-8 on every entry of every contest. That is R126's
retained-percent finding in a new place: a metric that cannot separate the two
things it was filed to separate. It ships as the prior's own within-pool TIER, a
rank, which does separate them, and the absolute count comes back with R10's
fitted model (rider filed there). **Second, the chalk-sum's reference needs no
model.** The field's own mean cumulative ownership is exactly sum(own_p^2) — an
accounting identity, the same count taken along the other axis, assuming nothing
about how the field builds — so the panel prints a comparison rather than a
naked number, and the identity is pinned against an explicit field built the
long way rather than restated from the docstring. What is NOT readable is the
magnitude: the prior under-concentrates by a measured 10.44 points (R135), so
the section closes on the cross-contest ORDER within one file, which is the
comparison the same prior on the same slate does support. **Third, Showdown got
smaller, not bigger.** The captain column ships as a RANK and the chalk-sum is
ABSENT there, because the prior budgets 800/200 over a ten-seat Classic roster
while a Showdown salary file lists every player twice (186 rows for 93 players
on the 2026-08-14 NYY@TOR file). That is a defect in the PRIOR, and R139's step
1 is now a Showdown-native prior rather than a report change; its entry carries
the correction. **Fourth, the fixture lesson landed again.** Fifteen mutations
were run by hand and fifteen were caught, but one — replacing the resolved
archetype with the prediction file's first key, which is the exact pooling
defect the entry was written to prevent — SURVIVED until the fixture stopped
giving every archetype identical shares. A test asserting the LABEL passes while
the DATA comes from the wrong block. Gate 1120 -> 1139 (`test_core` 762 -> 781,
`grew`); CLAUDE.md, SKILL.md and the ledger Quick Card pin line moved with it,
the last under a DEV-held `ledger` claim, that line and nothing else. **Swept the same
session, after Ben asked:** `tools/_operator_patch_20260813_crossgame.py` and
`tools/_run_patched_build.py` had been untracked inside the DEV write set since
08-13, so `claim.py dirt --role DEV` opened every DEV session BLOCKED on two
files with no owner left to name. The runner hardcoded a container path that no
longer exists and could not have run; the patch's two string anchors STILL match
the tree exactly once, so it was a live hazard rather than dead weight — any
import of it drops the same-game SP-pair filter for that whole process. Both
moved to `_to_delete/tools_residue_20260818/` with a WHY.md, and R115 keeps the
per-pair FLOOR mechanism the patch was the only copy of. `dirt --role DEV` is
clean for the first time since 08-13. **The .gitignore question that went with
it is CLOSED, and the answer was that no .gitignore change was needed:**
`_scratch_*/` (line 17) already matches at ANY depth, verified by
`git check-ignore -v` on a probe at `tools/_scratch_probe_.../patch.py`, which
`git status` and `dirt` both ignore. The gap was never the ignore file, it was
that nothing told a session under a clock where to put a run-scoped patch, so
the 08-13 session wrote a bare `tools/_operator_patch_*.py` that no rule covers.
One paragraph in CLAUDE.md's multi-session git section now names
`tools/_scratch_<tag>/` as the home and the sweep as the close-out. A broader
rule (`tools/_*.py`) was rejected: it would hide a genuinely new tool someone
names with an underscore, and it silences the warning rather than the residue.*

*2026-08-17 (fifth session), DEV, claim `engine_greenfield_spec_2026-08-17`:
**the fifth greenfield edition arrived and was adjudicated the same day; the
queue does not move.** Its controlling fact is its own header: it audited
`C:\Users\benja\Documents\MLB_DFS_Workbench` at `28aeaa8` — the pre-migration
workspace whose engine lineage froze at `legacy/v2_15_1` when MANIFEST.md's
2026-07-16 seed left it — so its 50 findings name paths with zero references
in this tree, and its "no results history, no calibration corpus" premise is
answered by the 271-contest archive and R135's first graded slate, both of
which predate it. Yield, consistent with the series (ed4 §0's table): one
rider on R123 (F-009's zero-cap trap, verified live: `showdown.py:408`'s
falsy check turns an explicit `0.0` captain cap into UNCAPPED, and the
effective integer cap never surfaces beside the pct), and one clause on the
sim-gate precondition (§3.10's scenario-bank separation plus joint own-entry
settlement). Everything else is shipped here, open here under existing
numbers (R41, R71, R75, R76, R81, R84, R87, R90, R91, R115, R118, R123,
R124, R130, R132, R149), or rejected on the standing grounds under
Do-not-build, where this adjudication's paragraph now sits. Edition archived
at `docs/2026-08-17_critique_greenfield_spec.md`; full reasoning in
CHANGELOG.md's entry of this date. **R136 remains this tier's head.***

*2026-08-17 (fourth session), DEV, claim `engine_2026-08-17`: **R135 is CLOSED
and migrated** to CHANGELOG.md, and **R151 was filed and closed in the same
session**, which is the one thing here worth reading before the R-number. R135
was taken out of Tier 2 rather than in tier order, on R136's own instruction: two
of R136's four columns are ABSENT on every build until R135 lands, so taking the
tier head first would have shipped a panel that was mostly empty. **R136 is
still this tier's head and its blocker is now gone**, and its entry gained the
schema, the archetype rule and the one trap: a chalk-sum computed off a
prediction whose implied-total tilt was INERT is a salary-and-order number
wearing a market label, so the emitter's `applied`/`INERT` state belongs beside
the column. Four things carried forward. **First, the load-bearing finding, and
the entry as filed could not have worked without it.** `grade_against_actuals`
joins on DK Player_ID; a DK standings export has no Player_ID column at all,
because the miner keys ownership on a normalized NAME. Wired as filed, the join
returns zero and the grade prints "no overlapping Player_IDs" while every other
number looks fine, which is the acceptance criterion failing silently. The
prediction file therefore records the salary file's own `name_norm -> Player_ID`
map at emit time, keyed with `field_miner`'s normalizer and NOT the intake's,
because the two disagree on an apostrophe ("Ryan O'Hearn" -> `ryan ohearn` one
way, `ryan o hearn` the other) and the actuals side is the miner's. **Second, R10's
named bar is nearly free and the report says so.** flat-12 is a constant 12% for
every player, which spends 2160% of a 1000% roster budget on a full slate, so
`flat_budget` (800/200 spread evenly) ships beside it as the null worth arguing
with. Reporting only flat-12 would have presented a free win as the gate cleared.
**Third, the first graded slate is not flattering and that is the point:** on the
archived 06-03 grid the prior posts MAE 14.35 points against flat-12's 14.53 and
flat-budget's 15.64, mean signed -10.44, Spearman 0.266, and an arms bucket at
46.95 because that salary file predates DK's `Starting` column so `probable_sp`
was inert. The record starting is the deliverable; the number is not a result to
defend. **Fourth, R151.** The emitter surfaces `merge_dk_starting_into_feed`'s
disagreement list to the operator, and on the 2026-08-16 1335_8g slate that list
read 7 of 15 posted sides with all 7 false: the merge compared `.strip().lower()`
while the MLB Stats API ships diacritics and DK does not. Underneath the noise,
the same key drove the carry-forward lookup, so ten hitters silently lost the
feed's MLBAM id and bat side — both F4 terms, R117's defect on the merge surface,
invisible to `f4_handedness_unavailable` because it only fires when a side loses
all nine. Fixed with the module's own `normalize_name`, and the disagreement list
now prints each source's SPELLING rather than the comparison key. Gate 1101 ->
1120 (`test_core` 743 -> 762, `grew`); CLAUDE.md, SKILL.md and the ledger Quick
Card pin line all moved with it, the last under the DEV-held `ledger` claim its
seven same-date predecessors used. Thirteen mutations run by hand, all thirteen
caught — two only after the FIXTURES were fixed, which is worth repeating: a
guard that survives its mutation is sometimes a weak fixture rather than a weak
assertion, and both here were (an odds fixture with no off-slate game cannot
test a slate restriction; a standings fixture with one row per player cannot
tell a sum from a maximum).*

*2026-08-17 (third session), DEV, claim `engine_2026-08-17`: **R126 is CLOSED
and migrated** to CHANGELOG.md, taken in tier order as the head of Tier 1 and of
the QA-hardening batch. **R136 is the new head of this tier**, with its
sequencing note corrected on the entry. Four things worth carrying forward, and
the first is the one that changes how the metric is read. **The retained percent
cannot separate the two builds this item was filed to separate.** On the fixture
reproducing 2138_2g's shape, the concentrated and spread portfolios post the
SAME apex (792.0) and the SAME retained percent (65.2%) and differ only in
`entries_fully_intact`, 0 against 3. Retained percent is bounded below by the
arms plus the other games' bats, so it falls as the slate shrinks and a 2-game
number is not comparable to a 10-game one — which is one of the two problems the
entry names in its own "Why". The histogram and the intact count are the
comparable half, the block's note says so, and a test pins that sentence. This
is not a correction to the entry so much as a reordering of its own emphasis:
BUILD wrote "the histogram is the part that earned its place, so it is not
optional garnish" and building it showed that claim was stronger than it read.
**Second, a landed tool was about to shadow the new block.** R134's
`qa_portfolio` already prints a "DUAL-OBJECTIVE FRONTIER" from share-of-portfolio
counts, because it reads a delivered CSV and a salary file and neither carries a
`Ceiling`. Two numbers under one word on one screen with nothing saying which the
build used is the R128 lesson on a new surface, so `frontier_from_brief` now
reads the artifact and leads with it and the structural axes are relabelled the
independent check. Worth noting for any session that touches that file: it had
ZERO tests before this one. **Third, the reconciliation surfaced a real
question, filed as R150 rather than answered on this claim.** The two game counts
differ — 16/18 against 18/18 on the archived 06-03 grid — because qa_portfolio's
axis counts every roster spot in a game and the run counts bats only. Both are
right, and whether an arm belongs in a washout count at all is a correlation
belief (an arm can benefit from the script that kills the bats) and therefore
Ben's. **Fourth, R127's boundary generalized in BOTH directions and the split is
now on the record:** a missing `Ceiling` COLUMN is one fact about the build and
reports a reason with no list, a missing rostered PLAYER is one fact per player
and is named, because a silent zero there reads as a low-ceiling portfolio rather
than a missing join. Also carried: one guard was wrong on its first cut in R65's
shape from the other direction — the label sweep asserted no banned word appears
anywhere in the block and failed on the block's own disclaimer ("neither is a
probability, a win rate") — and twelve hand-run mutations all caught, including
the sort whose fixture had to be rebuilt because the worst game was also the
alphabetically first, which made dropping the sort invisible. Gate 1074 -> 1101
(`test_core` 716 -> 743, `grew`). `skills/generate-lineups/SKILL.md`'s PASS line
was separately stale at 1056, two moves behind since R127 moved the count and
did not carry it; both it and CLAUDE.md moved here, and the ledger Quick Card's
pin line moved under the same DEV-held `ledger` claim its five same-date
predecessors used.*

*2026-08-17 (second session), DEV, claim `engine_2026-08-17`: **R127 is CLOSED
and migrated** to CHANGELOG.md, taken as the head of Tier 1 in tier order. Its
landing record and the three corrections the work made to the entry as filed
are in the queue's item 7 above and in the changelog entry. Gate 1056 -> 1074
(`test_core` 698 -> 716, `grew`), CLAUDE.md's quoted clean line moved with it —
`AuditSkipHonestyTests` pins those two together and caught the drift in the same
run, which is that guard working. **Housekeeping in the same commit, at Ben's
instruction, and it is the reason this note is longer than the R-number
warrants.** This board carried three files a session could mistake for it.
`docs/2026-07-27_backlog_v2.md` is now **`docs/backlog.md`**; the dated name was
three weeks stale as a description of the file and there is no second live board
to disambiguate it from. `.audit/BACKLOG.before-audit.md` is RETIRED (moved to
`_to_delete/`, untracked in the same commit): a 2026-08-13 pre-audit snapshot,
100 KB behind the live file, whose own first line read "This is the single live
backlog" — two tracked files claiming that is the exact confusion the rename
exists to end, and `.audit/AUDIT.md` already records what the snapshot was for.
`docs/MLB_Classic_Backlog.md` moves to **`docs/legacy/`** beside the other
2026-07-27 split artifacts; it is KEPT rather than deleted because it is the
only record of B-1 through B-14 anywhere in the repo (verified: zero B-item
references in CHANGELOG.md, whose Imported record starts at the R-numbers), and
B-8's ownership-model reasoning is the direct ancestor of R10. Pointers updated
in the same commit: CLAUDE.md, `docs/next_session_prompts.md`,
`docs/cowork_archival_runbook.md` (whose rule 2 named the v1 backlog as an
UNTRACKED companion Cowork may edit — stale on both counts since 2026-07-27),
and a dated addendum in `.audit/AUDIT.md` rather than an edit to its body, which
is a record of what was true on 2026-08-14. One pointer NOT updated and it is
ARCHIVE's: `ledger/MLB_Classic_Calibration_Ledger.md` line 10 cites
`MLB_Classic_Backlog.md` for its "same footing" comparison. The claim is still
true and the file still exists; only ARCHIVE edits the ledger, so it is left for
the next ARCHIVE session rather than taken on a DEV claim.*

*2026-08-16 (fifth session), DEV, claim `engine_2026-08-16`, fragment-merge and
full queue re-order at Ben's instruction (impact, difficulty, critical path), no
code touched: **R135-R141 are new**, all from the 2026-08-16 unassigned
leverage-and-contrarian ideation fragment, every measurement it cites
re-verified against the ledger and the tree before filing (`ownership_prior.py`
v0.1 and `grade_against_actuals` exist as claimed, and the module's own header
says "start the predict-then-grade loop on slate one"; 3.17's 104/116 sub-10%
carry, 51%-vs-13% winner rate, chalk splits and $250/$200/$100 salary-leave;
3.18's 9.1-vs-15.4 captain tranche with its own 64-contest at-share caveat;
3.19's 15,402 users, 2,211 regulars, 132/148 winners-were-regulars). The
fragment's frame survives adjudication because it is the board's own: broad
contrarianism stays rejected (3.17), and the levers are sub-10% carry,
duplication, construction shape, and archetype conditioning. **Filed:** R135
(ownership shadow loop, Tier 2 beside R118 — the cheapest evidence-per-session
item on the board; every slate without a prediction file is a slate that can
never grade anything); R136 (qa_portfolio leverage panel, into Tier 1's QA
batch directly behind R126 — same report block, one session takes both); R137
(market-vs-crowd divergence screen, Tier 5, quota arithmetic on the entry);
R138 (one-stack-family-per-game SKILL.md practice, XS, rides R131's SKILL.md
session); R139 (Showdown captain-leverage ladder, WS1 — report half rides
R136, control half waits on D3); R140 (opponent-conditioned field profiles for
recurring satellite families, Tier 2 tail, behind R118+R48 whose outputs it
consumes); R141 (late-swap leverage pass, Tier 5, behind R135 whose prior it
recomputes). **Riders, not numbers:** R10 gains the two control halves it owns
the day its prior beats flat-12 (leverage-carry inside the primary stack;
replay-calibrated duplication budget); R37(2) gains the field-share-adaptive
generalization of its own (b); Tier 4 gains D1-D3 (salary-leave
act-or-record; supersatellite posture, the one measured anti-chalk cell;
captain ladder defaults). Nothing in the bundle jumps the Tier 2 spine, which
the fragment itself states.*

*Same session, the re-order and what R134 changed under it. R134 (the
supervisor, qa_portfolio, build_asserted, the replay suffix) landed after the
last queue note, and three entries were written before it existed. **R126**
gains a note: qa_portfolio now computes the frontier proxies at review time,
so R126's remainder is the pipeline/brief half plus the per-game zeroing
histogram — unchanged in kind, cheaper in practice. **R11's double listing is
resolved** (Tier 5 and Tier 6 both carried it, and the Tier 5 note's claim
that its R114/R116/R117 gate had fully cleared was FALSE on one of three —
R117 is open in this very tier. A note asserting a state it did not check is
the R133 lesson again.) R11 moves to one entry and Tier 1's tail:
qa_portfolio is its deterministic tier half-built, the hand-run version found
six items across two slates in one day, and Ben's R134 directive names an
adversarial QA pass as the standing follow-up to every unattended build.
**R132 gains the autonomy boundary:** its ladder as filed escalates EVERY
binding control, and the 2026-08-16 autonomy contract draws a line through
that set — engine-derived floors and defaults may relax counted (the R37/R116
precedent); an exposure cap may not (no engine-named floor; raising one is
Ben's). So R132 splits: the small-slate-defaults S variant and the
engine-guess rungs are DEV-ready, the cap rungs are R125(c)'s Tier 4
decision — and R134 just made that decision the highest-leverage minutes on
the board, because the supervisor now takes every classified stop and the
unclassifiable infeasible-caps refusal is most of what still ends a window
early. **One order swap inside Tier 1:** R117 moves ahead of R133 — both
P1/S intake truth, but R117 changes SELECTION (F4 dead moved primary stacks
onto the second-worst HR park in MLB) where R133 changes labels and
overrides, and R117's parse half is also R122's Showdown handedness input.
Everything else holds its 2026-08-12 adjudicated position. Fragments: the
ideation fragment is retained on disk as evidence until its items land (the
standing rule); the two 2026-08-13 ledger fragments and the 2026-08-15
audit-macro fragment remain ARCHIVE's to merge, their backlog asks already
carried (R115, R116). Gate this session: five suites per-suite at their pins,
657 + 56 + 218 + 9 + 75 = 1015, zero skips, `--terse` PASS v2.26.0 26
modules — and DeterminismTests fit a single call at 20.2s, the load-dependent
ceiling the 08-15 ledger-inbox fragment describes, measured from the green
side.*

*2026-08-16 (third session), DEV, claim `engine_2026-08-16`: **R128 is CLOSED
and migrated** to CHANGELOG.md, taken in tier order as the QA-hardening batch's
head. One helper in `preflight_upload.py` partitions lineup duplication into
`duplicates_within_contest` (the finding) and `duplicates_across_contests`
(information), `advisory()` calls it so `verify_export.py` inherits the split
through the call it already made, and `build_slate.portfolio_exposure` imports
the same helper for the brief. Cost: XS as filed, one working session. Pin 1000
to 1015 (`test_core` 653 -> 657, `test_upload_integrity` 207 -> 218). **R127 is
the new head of Tier 1** by the batch's stated order, and it is the batch's only
P1 carrying a selection defect, so it deserves its own reproduction rather than
a tail-end pass.

Three things the work corrected about the entry as filed. First, **both cited
line numbers were stale**: R129 landed earlier the same day and moved them, so
`:1426` and `:1655` are now `advisory()` at 1468, the flat count at 1486-1487
and the print at 1716-1717. An entry citing a line in a file another entry is
about to touch is worth re-verifying rather than trusting, which is what the R36
and R70 discipline already says and what this pair demonstrates twice in one
day. Second, **the entry scoped the fix to two surfaces and it was three, which
made it smaller rather than larger**: `verify_export.py:574` calls the same
`advisory()`, so fixing the shared function fixed both tools and the only real
decision was to resist forking a second implementation. Third, and the one
worth carrying, **a mutation caught a guard that could not fail, again**: the
2138_2g shape's honest answer for `duplicates_within_contest` is 0, so the
headline reproduction test asserting `within == 0` passed against a mutation
that hardwired the value to 0. This is R65's shape for the second consecutive
session and it is not a coincidence — a test built from a bug report inherits
the report's numbers, and when one of those numbers is zero the assertion is
satisfied by absence. The test now appends one duplicated entry to one satellite
on the same fixture and asserts the number moves. Seven mutations were run by
hand against the finished guard and all seven were caught.*

*2026-08-16 (second session), DEV, claim `engine_2026-08-16`: **R129 is CLOSED
and migrated** to CHANGELOG.md, taken in tier order as the QA-hardening batch's
head, and **R36 F6m's corrupt-manifest half (1) closed with it** because R129's
own entry says the new row has to survive it and never lands before it. F6m's
entry stays on the board rewritten in place, holding only the append-only
redesign, the concurrency half and (2)'s `salary_sha256`; F3m is untouched and
the pair is now F3m + F6m-remainder. `tools/promote_run.py` is the missing
operation, and R98(3)'s restore remainder is closed by it as the entry
predicted. Four things worth carrying forward. First, **the entry's own spec was
wrong in one place and the tree said so**: it asks for `status: current`, there
is no `current` in `STATUS_VALUES`, and writing one would hard-fail the next
read through R34's guard — the row lands `candidate`. Second, **the fix created
two defects and finding them was the work**: re-promotion makes two manifest
rows for one sha256 ordinary, and both readers in `preflight_upload.py` took the
first digest match, so the re-promoted file reported as superseded and
`stamp_manifest_status` resurrected a SUPERSEDED row to `upload_ready` — F6m's
named lost-supersession failure arriving through a door that is not the
concurrency one it was filed for. Both now share one matcher. Third, **a
mutation caught a guard that could not fail**: the same-path preference, which
is the guard that fixes the live bug, survived its mutation because the fixture
ordered rows so both branches agreed; that is R65's unpinned-join shape and only
running the mutation showed it. Fourth, an environment gotcha now on the Quick
Card: `python -m unittest` by hand does not put `.pylibs` on `sys.path` the way
`audit.py` does, so the documented per-suite fallback goes red with `scipy MILP
backend unavailable` until `PYTHONPATH=$PWD/.pylibs` is exported — 21 errors in
test_showdown and 8 of 9 golden-replay tests missing, none of them a real
failure. Pin 975 to 1000. **R128 is the new head of this tier**, unchanged in
substance and now the batch's first open item.*

*2026-08-16 (2026-08-15 ET), DEV, claim `engine_2026-08-16`, fragment-merge
pass, no code touched: **R126-R133 are new** and **two of this board's own
merge claims were false**. Ben directed the 2026-08-15 `2138_2g` QA fragment in
as the #1 item, and it enters as **the QA-hardening batch at the head of Tier
1** (R129 re-promote, R128 duplicate context, R127 enrichment labels, R126
apex/washout, R130 bank reuse, R131 smalls), keeping the fragment's own
suggested order with one swap stated below. Every claim in it was checked in
tree before filing, per the R36 discipline, and four held exactly: Dobnak is
absent from all 212 rows of `fangraphs_season_pitching.csv` (file dated
2026-07-16, which is the 30.2 days the warning reports); `signal_applied` is a
single `any()` over hitter AND pitcher counts (`build_slate.py:1270-1278`), so
one boolean genuinely covers both sides; `duplicate_lineup_groups` is a flat
count with no contest partition (`preflight_upload.py:1426`); and `superseded`
hard-fails at `preflight_upload.py:874` with `--no-manifest` as the only escape
and no promote tool on disk. **One diagnosis is corrected, and the correction
matters because the proposed remedy would have hurt:** P4 reads the bank cache
as "keyed on date," so its fix is to key it on the controls. The cache is keyed
on date PLUS a pool signature, and it already carries a conditions signature
(R101) over projections, exclusions and stack min/max — the controls the
fragment varied (pitcher .85, shared 9, stack .55) are ALLOCATOR-side, applied
after the bank, so the bank is right not to key on them. What actually produced
19/19 distinct once and 7/19 on the identical command is the bank GROWING across
seven builds on one date, which the fragment's own P7 already says. Keying on
controls would mint a thin fresh bank per control change — the second failure
that same night, `entry-level joint MILP proven infeasible`. R130 is therefore
filed as a REPORTING item, and the key-on-controls remedy is declined with the
reason on the entry. **The order swap:** P6 moves ahead of P4 because it is the
only item that measures the objective Ben actually stated, and on this slate it
was the only thing that separated two builds that both passed every gate (apex
2365 with every lineup drawing 4-5 bats from one game, against the delivered
build's spread). `washout` appears nowhere in the engine, tools or skills;
`apex` exists only as a posture-tier name. **Two board corrections, both
verified against the tree and the changelog:** the 2026-08-15 note below claims
seven 08-14 fragments merged — FIVE did, and the two filed at 20:35 that
evening (self-escalation, sandbox disk) were never picked up by any session;
they enter now as R132 and an R42(b) extension. And the 2026-08-14 note below
says the 08-12 partial-side fragment "stays consumed by R60" — it cannot be,
because R60 closed on 08-12 and the fragment is a report of a defect in R60's
SHIPPED behaviour, which `CHANGELOG.md`'s R46-round-2 entry says in plain text
the same day ("Not fixed here ... Those four are the disease"). It enters as
R133 and Workstream 3 stops claiming no open P1. **R98(3) gains the two
remainders** the 08-14 floored-bank fragment had left partially merged: restoring
an earlier certified run to the canonical path makes preflight fail against
itself (same defect as R129, two independent filings), and a past-limit
reference feeding a team that then lands a primary stack earns a brief line.
**R13's "Awaiting Ben ... NOT written" line is corrected** — Ben decided on
2026-08-09 and two other entries on this board already say so; only R13 never
caught up. **Swept:** four genuinely consumed fragments deleted (adversarial-QA
→ R11, delivery-guarantee → R124/R125/R117, fabricated-clock → R121, Showdown
platoon → R122/R123). Five fragments stay on disk because they are the only
carrier of something: the four merged here keep their evidence until their items
land, and the 08-09 curated-archetypes fragment is ARCHIVE's to execute. Gate at
session start: five suites at their pins per-suite, 653 + 56 + 182 + 9 + 75 =
975. The one-call macro was killed past 178s again and produced no verdict,
which is not a red gate.*

*2026-08-15 (fourth session), DEV, claim `engine_2026-08-15`: **R116 is CLOSED
and migrated** to CHANGELOG.md, taken in tier order as Tier 1's head. Both
halves landed. Three things worth carrying forward. First, the fix's first cut
was falsified by the project's own golden grid inside the same run, and the
falsification was structural rather than numeric: the all-or-nothing version
(default, else drop the cap entirely) degrades to the exact unbounded solve the
item exists to remove whenever its most aggressive rung does not fit, which on
the archived 06-03 grid is always — 18 entries against 29 distinct lineups
defaults to a cap of 1 and the production exposure caps refuse it. A two-rung
ladder lands that grid on a cap of 2 with 11 distinct lineups. The general
lesson: a default whose only fallback is "no default" is not a default, it is a
default plus a silent opt-out. Second, the R37 precedent carried further than
expected — never on a timeout, always counted, relax the engine's own guess
before anyone's decision — and the ORDER of the two ladders is the part worth
stating, because a primary-stack floor is Ben's archive-backed decision and
this cap is arithmetic off whatever bank arrived. Third, re-freezing a golden
baseline is only honest with the measurement in hand: total fit identical at
2555.9321, the multiset of delivered lineups identical, aggregates unchanged,
15 of 18 entries re-dealt across the same eleven lineups. That is a tie-break
vertex change from a new constraint row, and saying so is the difference
between a baseline update and making a red gate green. Also carried: one new
test survived its mutation and was rewritten rather than kept, because with
identical rosters candidate ids are interchangeable by construction and the
assertion could not fail. **R117 is the new head of Tier 1.** The seven
`docs/backlog_inbox/` fragments from 2026-08-14 are merged and still on disk;
the sweep is still owed. [**Corrected 2026-08-16:** five were merged, not seven.
The two filed at 20:35 on 08-14, after the merge session had finished, were
never picked up and are now R132 and the R42(b) extension.]*

*2026-08-15 (third session), DEV, claim `engine_2026-08-15_devsession`: **the
false-signal batch is CLOSED**, six of its seven items in full and R71 on its
(a) alone, migrated to CHANGELOG.md. R113 now names captain-LOCK vs
captain-CAP and the substituted captain instead of pointing at
`by_player`. R112 rides the bank-observed SP count beside
`feasibility.inputs` on every refusal (fix 2, flooring the auto-bank's own
coverage, is declined — R115 owns the mechanism, so a second floor here
would fight it rather than help, and the decision is recorded on R112's
entry rather than left silent). R103 stops the same-game filter from
starving a job list whose pair is already pinned by the file; the filter now
runs on the unpinned remainder only. R99 and R92 each had a brief or stderr
line reading a key nothing ever set — one dead guard replaced with the real
`jobs_raised`/`jobs_unanswered` fields, one field made to read the same
object its own stderr check reads. R119 lands `objective_differentiation` in
the brief and writes the `value_guard` key its own warning already pointed
at. R71(a) makes a cap fraction over 1.0 raise instead of silently
disabling the cap in both the solver and the validator; (b)(c)(d) is the
one remainder and keeps its own entry in Workstream 4. Every fix landed with
a test, two of the riskiest (R103's same-game bypass, R71(a)'s reject) were
mutation-checked by hand. Gate moved 942 -> 962 tests
(`tests.test_core` 621 -> 640, `tests.test_showdown` 55 -> 56); CLAUDE.md's
session-start line moved with it. **Tier 1's head is now R116.***

*2026-08-15, DEV, claim `engine_2026-08-15_r114`: **R114 and R67 are CLOSED**
and migrated to CHANGELOG.md, which also carries the entry the two audit
sessions deferred — that debt is now clear. Tier 1's head is the false-signal
batch. Two things worth carrying forward. R114's falsifier held exactly as
written ("if declarations already reach an input preflight reads, the fix
collapses to reading it"): the brief had recorded `declared_pitchers` all
along, so no engine change was needed, and the whole fix was two tools
learning to read one field. And the fragment's diagnosis was wrong about the
cause while being right about the mechanism — it called the live 2210_2g case
a bullpen game, and the feed on disk says confirmed with a named probable.
Reproducing before fixing caught it, again. The gate moved 928 -> 942;
`EXPECTED_TEST_COUNT`'s comment had been stale at 901 since R70 and is now the
sum it claims to be.*

*2026-08-14 (third session, continuation of the audit), DEV, claim
`engine_2026-08-14_edge_audit2`: **the five 2026-08-14 BUILD fragments are
MERGED** — three concurrent build sessions (1810_3g Classic, 1915_1g_sd
Showdown, 1910_10g main) filed them while the audit ran, and Ben directed the
sweep. Four mechanisms were re-verified in tree before filing
(`build_slate.py:1837-1838` hand guard; `showdown_theses.py:62/70/109`
prior_note; `execution_pipeline.py:387` DO_NOT_UPLOAD candidate path;
`solve_ladder` signature at `showdown_theses.py:484`). **New: R121-R125**,
which brings this audit's new numbers to twelve (R114-R125), its stated cap.
R121 is the fabricated-clock pair (two sessions, same day, same defect — a
decremented mental clock instead of a measurement, and the second instance
CAUSED a five-control relaxation against a 34-candidate floored bank); R122
and R123 are the Showdown pair (a prior_note that claims a platoon factor the
build never applied — a truthful-labels violation — and a ladder with no
per-player exposure cap, Bateman 89.5% on ~25 PA); R124 is the delivery
guarantee (three verify_export-clean files existed 6.5 minutes before a lock
that nearly went undelivered because the only copy was named
`DO_NOT_UPLOAD_`); R125 is the autonomy-defaults batch, decision-first.
**Extended in place:** R117 (elevated P2→P1 and into Tier 1: the paste
probable/F4-inert defect recurred on a third slate with the root cause found —
null id + empty hand kill BOTH F4 terms — and repairing it moved primary
stacks off the second-worst HR park in MLB); R98(3) (the floored-bank JSON
hint leads with the one remedy that cannot converge — three re-runs bought
one candidate — while stderr names the right one; plus SKILL.md's
`--max-seconds 14` guidance floors the budget by construction and the 45s
ceiling premise is stale, `timeout 155` ran twice); R115 (the sp_pair_floor
fragment's closed-form inequality joins the fix); R11 (rewritten around the
two-tier QA design from the adversarial-pass fragment: a free deterministic
tier that would have caught both of tonight's certified-clean holes, then an
exposure-ranked browser tier, two-iteration cap, never gating delivery);
R114 (a declared/self-supplied confirmation earns a distinct preflight label);
R89 (single-pass blocker collection — six serial ~40s round trips ate most of
a T-10 window). **Tier 4 gains two dated decisions for Ben:** the FanGraphs
manual-by-decision rule (reverse or reaffirm; the two stale references are
exactly the two manual ones, and one fabricated a TEX order that took 19
roster slots), and R125's posture-fallback and Classic-relaxation-ladder
halves. Fragment files again left in place marked consumed (write scope);
sweep owed. The 08-12 partial-side fragment was checked and stays consumed by
R60 [**Corrected 2026-08-16: it is not.** R60 closed on 08-12 and the fragment
reports a defect in what R60 SHIPPED, so R60 cannot consume it; `CHANGELOG.md`'s
R46-round-2 entry of the same day names all four findings and says they are not
fixed. Filed as R133.]; the two ledger fragments remain ARCHIVE's to merge into
the ledger, their backlog asks now all carried (R115, R116).*

*2026-08-14 (second session), DEV, claim `engine_2026-08-14_edge_audit`:
**portfolio-edge audit** at Ben's directive, write scope deliberately this file
plus `.audit/` only — no code, no CHANGELOG edit (that entry is owed by the
next DEV session; the audit trail is `.audit/AUDIT.md`, the queue for the next
session is `.audit/NEXT_IMPLEMENTATION_RUN.md`). Session-start gate: all five
suites at their pins, 928/928 (V1; the one-call macro dies at the sandbox
ceiling ~178s, the Quick Card's per-suite fallback produced the evidence).
Preflight on the newest delivery exits 0 (V1). **The three unmerged fragments
are MERGED as R114, R115, and R116+R117** — fragment files left in place and
marked consumed (the audit's write scope excludes deleting them; sweep owed).
Two fragment diagnoses were corrected against the tree before filing, per the
R36 discipline: the candidate-reuse default the 08-13 fragment cites lives on
the LEGACY allocator path only, and production adds NO reuse row at all when
the control is unset (`contest_allocator.py:2232-2233`); and the 1310_6g
bank's arm poverty is ceiling-ordered budget truncation plus a growth target
that collapses to `requested_n` (`optimizer_v3.py:3863`), not a missing arm
axis — the jobs do vary pairs. **The ed4 root review
(`DFS_GREENFIELD_REVIEW_2026-08-12_ed4.md`) is ADJUDICATED**: first external
review to actually run the gate; its §2 scale-invariance finding verified in
tree (Floor is uniform 0.58 of Base with no per-row path,
`projection_builder.py:103`; the objective is linear in one column,
`optimizer_v3.py:714-723`; so `target='floor'` IS mean-maximization and
enrichment is the only GPP/cash differentiator) and adopted as R119; its §3
variance-basis sentence is added to Do-not-build this commit; everything else
it declines itself in its own §6. **R118 is the audit's one strategic filing:**
`field_miner` computes each contest's {player → realized FPTS} map and strips
it at the archive boundary (`field_miner.py:1961`), which is the
counterfactual-replay substrate discarded on every mine. Retained, plus one
deterministic replay tool, the 271-contest archive grades construction policy,
duplication, and the floor-5/routing questions against REAL fields without
waiting on live tranches. Tier 2 is reordered R118 → R48+R83 → R10 on that
logic; Tier 1's head is now R114 beside the false-signal batch (which gains
R119); R115 heads Tier 3 beside R98(3). R120 (a delivered upload-ready file
whose `runs/` dir does not exist on the mount) and R117 (paste drops the
probable's continuation line; F4 neutral for 100% of hitters is silent) are
filed small. No R-numbers moved; no items closed (nothing landed as code, so
nothing migrates). V-tags, method, three greenfield designs, and the target
architecture are in `.audit/AUDIT.md`.*

*2026-08-14, DEV, engine claim `engine_2026-08-14`: **R70 is CLOSED and
migrated** to CHANGELOG.md, taken in tier order as Tier 1's head. Both halves
landed. Three things worth carrying forward. First, the fix needed a CHANNEL,
not just a refusal: making ambiguity a block without `--salary-csv` and its
three siblings would have made `stage_slate.py` unusable on 17 of the dirs
under `data/slates/`, which is R106's lesson arriving on a different tool, and
the block exits 4 so a driver can tell "name the file" from "download the file."
Second, reproducing first corrected the filing twice — the 07-30 dir does NOT
stage wrong end-to-end because it has no `slate_bundle.json` and dies at the
bundle check (07-19 is the dir that would), while the "suppresses the default
platoon-reference load" clause is exactly right and reads as wrong only until
you look in `build_slate_pool` rather than in the tool. Third, one unplanned
rider was taken and is recorded as such: the "no platoon JSON" warning promised
a top-9 APPG fallback that stopped being true when the reference default
landed. Pin 901 to 928, and `AuditSkipHonestyTests` caught the CLAUDE.md
session-start line on the first full run, which is the pair working as designed.
**The first cut of the fix shipped a blocker and an adversarial pass caught it
the same day**, which is the part most worth carrying: resolving a bare
`--salary-csv` against the CWD before the slate dir let the repo root's stray
07-27 DK files stage against the 07-19 bundle under a provenance line that
looked correct — R70's defect returning through R70's remedy. Two more came
with it: the ET conversion hardcoded UTC-4 while `repo_env` exists to kill
exactly that (an hour wrong in EST, on the T-schedule's instrument), and making
the platoon reference actually load meant this door inherited
`stale_platoon_policy='block'` while both sibling scripted doors pass `'warn'`,
so the checkpoint would have been stricter than the build it previews. The
lesson generalizes past this item: a fix that adds an operator escape hatch
needs the hatch reviewed as carefully as the hole, and a fix that makes a
dormant code path live inherits every default on it.
**The false-signal batch is the new head of Tier 1.** Three fragments in
`docs/backlog_inbox/` are still UNMERGED and this session deliberately did not
merge them: the 08-12 preflight/declared-pitcher note, the 08-13 bank-cache
note, and the 08-13 candidate-reuse note, the last of which is long and carries
seven numbered asks. Merging them is a doc-truth pass of its own and folding it
into a code session would have buried it.*

*Second session of 2026-08-13, DEV, engine claim `engine_2026-08-13` plus a
`ledger` claim for the Quick Card pin line: **R69 is CLOSED and migrated** to
CHANGELOG.md, taken in tier order as Tier 1's head. All three halves landed.
Two things worth carrying forward. First, the (c) decision the entry left open
("decide block-or-relabel") was decided as BOTH, split by remedy: an unmatched
exclusion id is an operator-typed identifier fixed by correcting one argument,
so it hard-gates `approve=True` beside contest identity, while an unrecognized
`Excluded` cell is the documented reading of that column and its remedy is a
file edit, so it relabels to a warning. Second, (a) ships as a WARNING rather
than a block on evidence: 3 of the 75 real `DKSalaries*.csv` files in
`data/slates/` carry neither `Status` nor `Starting`, most recently 2026-08-01,
so blocking would refuse legal DK files. Pin 889 to 901. The single-line audit
macro again did not fit the sandbox's per-call ceiling and the per-suite
fallback produced the evidence; that ceiling is now recorded on the Quick Card
line itself rather than left as a per-session note. **R70 is the new head of
Tier 1.***

*2026-08-13, Ben, standing directive, docs only, claim `engine_2026-08-13_apex_priority`:
**apex over cash is now the named priority for GPP-shaped contests.** Ben's own
words: "the only way this makes money over the long term is big wins," so
WTA-style ceiling construction is preferred over cash-rate optimization. This
is not a new gap: every non-cash, non-satellite shape already scores on pure
ceiling (`score_lineup_candidate`, `optimizer_v3.py:3453-3456` — the
projection component is `ceiling` alone for every `mode_family` except `cash`
and `ticket_line`), so there is no floor-seeking bias in GPP/WTA scoring to
strip out. What varies between the GPP ladder and the WTA rows is
`stack_bonus_weight`, `batting_order_cluster_weight`, `salary_uniqueness_weight`,
and `field_pressure_weight` (`CONTEST_SHAPE_PROFILE_WEIGHTS`,
`optimizer_v3.py:2813-2874`), and the WTA rows already push all four harder
than the GPP ladder does. Riders added below to **R37(2)** (elevated: its
narrow-breadth floor-5 work is the concrete apex-construction lever, already
scoped to the shapes where the payout sits at rank 1) and **R10** (reaffirmed:
duplication modeling is what tells you whether an apex-shaped build actually
clears the field). **One thing this directive does NOT license by itself:
raising `salary_uniqueness_weight`/`field_pressure_weight` on the GPP ladder.**
The 3.17 ledger finding this rides on found the opposite of blanket
contrarianism wins — chalk-positive cores plus one or two sub-10% pieces,
everywhere except supersatellites — and Ben's own measured posture already
runs more contrarian than winners in exactly single_entry_gpp (21.4 vs winner
54.3 chalk percentile) and satellites (40.0 vs 54.5). Any session reopening
those weights grades against that finding first. **R40 is unmoved**: the
directive is a standing preference, not new evidence, and the n=2 problem and
the floor-blend win are still the reason DEV's routing recommendation stays
no-not-yet.*

*Sixth session of 2026-08-12, DEV, engine claim `engine_2026-08-12` plus a
`ledger` claim for the Quick Card pin line: **R110 is CLOSED and migrated** to
CHANGELOG.md, out of its batch and knowingly (see Tier 1 item 7 for what that
cost). Ben was shown the ten stale HELD claims and said clear them, which
needs R110(a) to work at all: `sweep` and `check` print dated directory names
and `release` re-derived them, so every command the tool printed failed. Also
landed: `claim.py sweep --release`, with staleness moved off the name and onto
`owner.json`'s `taken_utc` so a BUILD session past UTC midnight cannot have a
live claim swept. All ten released; the only HELD claims now are live ones.
Pin 877 to 883. The single-line audit gate did not fit the sandbox's per-call
ceiling this session and the Quick Card's documented per-suite fallback was
run instead; every gated suite passes at its pin. **R113 was filed earlier the
same day** and is unchanged by this.*

*Fifth session of 2026-08-12, DEV, engine claim `engine_2026-08-12`: **R60 is
CLOSED and migrated** to CHANGELOG.md, the last open P1 in Workstream 3. A
partial side's posted starters are seeded into the pool ahead of the platoon
projection and APPG, `tbd_fallback='exclude'` now drops the rows it says it
drops, and `platoon_dependent_teams` follows what the projection supplied
rather than what it covers. The partial-side rule is written into CLAUDE.md's
build contract, which is the half the entry called undefined. F2 from the
posted slot deliberately did NOT ship and stays a strategy question for
MLB_Classic.md. Pin 871 to 877. **R113 is new**, merged from BUILD's
2026-08-12 fragment into Workstream 4 and joining the false-signal batch:
the Showdown caution reports a captain-LOCK relaxation as a captain-CAP
relaxation. **R109 gained a dated note**: the Cowork delete grant lifts the
mount's unlink refusal, so `rm` cleared a stale `.git/index.lock` and the
entry's residue sweep is no longer blocked on a hand step.*

*Fourth session of 2026-08-12, DEV, engine claim `engine_2026-08-12_order`: the
queue below is REBUILT as a full development order at Ben's instruction —
impact against technical lift, high-impact/low-lift first, high-lift items
adjudicated individually, high-lift/limited-impact explicitly deprioritized.
Method: impact reads off this project's own hierarchy (pool and upload truth,
then evidence and grading substrate, then false signals that steer the
operator, then lineup-quality controls, then operator time, then hygiene);
lift reads off each entry's carried effort letter; and a third axis the
two-axis instruction implies but this board needs stated: WHO an item waits
on. An item waiting on measurement, Ben's data, a decision, or a hand step
outside Cowork holds no DEV slot whatever its score, so those are listed
separately rather than ranked as if buildable. Entries stay verbatim in their
workstreams; this section is the order. One standing hold is deliberately
amended by the new lens: R36's F3m and F6m leave the trip-only pull rule for
Tier 1, because both are P1/S, verified on a real delivery record, and
recording-only. No R-numbers moved or reassigned; the old four-item queue's
substance survives inside the tiers (R60 leads Tier 1; R48/R83 then R10 are
Tier 2; R37(2) and R40 hold their externally-gated truth at the bottom).*

*Third session of 2026-08-12, DEV, engine claim `engine_2026-08-12_gemini`:
two more uploaded critiques adjudicated, both REJECTED WHOLESALE with zero
adoptions, archived as `docs/2026-08-12_critique_gemini_spark.md` and
`docs/2026-08-12_critique_gemini_pro.md`. Pro is a regeneration of the
2026-08-01 Gemini critique (rejected wholesale then for not reading the
tree), retitled into the GF-spec template; Spark is the 07-25 CC program
re-argued. Both stand on the premise this list falsified in July — an
iterative PuLP solver this repo has never contained (`grep -ri pulp`
matches nothing in code) — and both recommend crossing the absolute walls:
scripted DraftKings fetching and automated upload with "no human review
step," which the GF spec's third edition, adjudicated earlier today,
independently documents as prohibited by DK's own terms. Spark proposes
four things that already exist at the exact paths it names
(`build_state_manager.py`, `bank_cache.py`, the deterministic preflight,
the swap-from-bank late path) and cites one file that never existed
(`session_handoff.md`, no file, no git history). The scratch-leakage
concern's true kernel is R60, already P1 at queue position 4. Nothing
enters the board; the full map with the verification evidence is in the
CHANGELOG entry of this date. Three stale slate beacons from 07-30/08-01
were observed still HELD and left for Ben to arbitrate.*

*Second session of 2026-08-12, DEV, engine claim `engine_2026-08-12_gf3`,
adjudication of the greenfield spec's THIRD edition (Ben's re-dated root
upload, reviewed at this exact HEAD 6c96474; archived to
`docs/2026-08-12_critique_greenfield_spec.md`, which updates R107(c)'s
premise — the root copy now pairs byte-identical with the 08-12 archive, not
the 08-10 one). Adjudicated as a DELTA on the 2026-08-10 edition: the diff
shows two new sections (F-35, A-43), five findings rewritten to CONCEDE what
the R103–R106 adjudication rejected them on or what R104/R45/R105/R54/R62/R96
landed (F-02, F-05, F-16, F-20, F-21, with softenings in F-13/F-30/F-31), and
label renames; everything else is textually the prior edition, so every
standing disposition carries over unchanged and **nothing enters the numbered
queue**. **R41 gains one rider** (F-20's rewritten residual, verified at
`showdown.py:109-175`): the `all_healthy` fallback is deliberate, stamped,
and reaches the brief, so it binds at certification, not before. **F-35 and
A-43 are rejected on standing grounds**: F-35 cites this repo's own
2026-08-11 incident back at it (R31(c)(d) and R110 already carry the accepted
work; DB leases and fencing tokens are the rejected transactional program),
and A-43 is that program's operating procedure, its one hard wall a
restatement of CLAUDE.md's money-and-entry wall. Full map in the CHANGELOG
entry of this date. The queue below is untouched.*

*2026-08-12 (2026-08-11 ET), DEV, engine claim `engine_2026-08-12`, doc-truth
pass at Ben's request, no code touched: **R111 and R112 are new**, both merged
from inbox fragments that had been sitting unconsumed — `sync_check.py`
hardcodes `main` while GitHub's default branch is a stale `master`
(Workstream 6), and the auto-bank is thinner than the sliced bank at low entry
counts while the refusal blames a control (Workstream 4). Neither enters the
numbered queue; both are P2 and wait on the pull rules. **R107 gained part (c)**
(the root `DFS_SYSTEM_GREENFIELD_SPEC.md` is a byte-identical copy of the
tracked `docs/2026-08-10_critique_greenfield_spec.md`) and **its part (b)
landed** (`_stage_repo*.tar.gz` gitignored); part (a), adopt-or-delete for
`tools/fetch_fangraphs_platoon.py`, is still Ben's and is now a week old with
the Quick Card naming the tool the whole time. Also landed: CLAUDE.md now
states the DEV write set including CHANGELOG.md and carries R31(d)'s
nominal-mutex gotcha with its 2026-08-11 cost, and the sync protocol carries
the `master` default-branch hazard plus a guard for the write-back loop that
truncated seven tracked files. One fragment is deliberately NOT merged:
`2026-08-09_DEV_ben-decision-curated-satellite-archetypes.md` is ARCHIVE's to
execute against `data/reference/dk_contest_archetypes.csv` and stays where it
is.*

*Third session of 2026-08-10, DEV, engine claim `engine_2026-08-11`: **R62 is
CLOSED and migrated** to CHANGELOG.md — the two salary files are vendored under
`tests/fixtures/slates/`, the nine skip guards are gone rather than repointed,
and the paste suite runs 75 real tests on a tracked-files-only checkout where it
previously ran 75 with 62 of them skipped. **R96 is CLOSED and migrated** to
CHANGELOG.md. Its step 1 investigation tripped the entry's own stop condition —
six paths in three structural classes, not the two or three one fix closes — so
the session stopped and asked; Ben decided both gating questions on 2026-08-11
(delete `build_showdown_theses.py` in favour of `run_showdown`; the manifest row
follows a `preserve_prior_slate` rename) and all four steps then landed with 21
tests, one per path. The reverse check immediately named two unrecorded
deliveries nobody had counted, on 2026-08-05 and 2026-08-09. Pin 850 to 871.
**R110 is new**, filed below in Workstream 6 next to R31:
`claim.py`'s own remediation advice is not a runnable command, which is the loop
that has left seven claims HELD with a hand-written RELEASED marker. Nothing from
the R96 investigation was numbered separately; all of it belongs inside R96.*

*Second session of 2026-08-10, DEV: **R85 LANDED and migrated** to
CHANGELOG.md, and **R62's two honesty halves LANDED** — its entry stays on the
board rewritten in place, holding only the deferred fixture vendoring, now
sized at 84 KB in two files rather than the 2.4MB the original note assumed
(read that entry before re-deciding its GH-PAT sequencing; both halves of the
size premise turned out wrong). **R109 is new**, filed below in Workstream 6:
`.git/index.lock` goes stale on this mount and `rm` cannot clear it, three
incidents across 07-28, 07-29 and 08-10 that had never carried a number, with
the remedy folded into the sync protocol.*

*Earlier that day, the Showdown intake-and-bookkeeping batch (R104 + R45 +
R105 + R54) landed and its four entries migrated. **R108 is new** from that
session, filed in Workstream 3: the DK `Starting` token vocabulary is still
parsed in two modules, now with named constants pinned in sync by test rather
than two tuple literals, and the consolidation R104's scope note asked for is
deferred rather than done. R41's gap is measurably smaller: honest relaxation
counts and honest manifest statuses both exist now, so what remains is the
sequencing and relaxation-policy decision, not the bookkeeping.*

*One live environment condition, not an item: the sandbox volume holding
`TMPDIR` hit 100% (196K free) mid-session, which fails every test that builds
a throwaway git repo and reclaims nothing, because `rm` on this mount returns
"Operation not permitted". Running with `TMPDIR=/tmp` cleared it. That is
R42(b)'s named scenario arriving live for the fifth time and R109's asymmetry
underneath it.*


Any session may read this; only DEV edits it. Reordered 2026-08-04 by the
full-project audit that filed R51–R91 (method and runtime evidence in the
CHANGELOG entry of the same date). Eighteen items have landed since that
reorder and migrated to CHANGELOG.md per the backlog contract: R51 + R52 (the two
P0 upload gates returning a false clean), R46 + R72 (the export gates' slate-truth
checks and the allocator's fail-open locked-game exclusion), R53 + R64 (the
vacuous lineup gate and the delivery record's structural "clean"), and the
R57 + R56 + R55 solver-and-projection correctness trio (the xwOBA correction
overwriting an operator-supplied Base, the suppression cap acting as a hard
feasibility constraint, and the id-dtype boundary that silently no-opped every
control while the bank cache recorded the wreckage as done), and R65 + R59 (the
ET calendar authority, and the feed merge's team-code vocabulary and
field-level side fill), and R58(a)(b) (the doubleheader paste path and the
team-keyed extractors, with (c)(d) left open and repriced) and R30(a)'s tool
half (paid_places reaching a mined record, so an archived contest can be
classified at all), and R30(b) + R50 (the two ends of the same lie about
fees) and R74 (three silent failures at the archival tooling's edges). The
queue
below is renumbered with no R-numbers reassigned.

**Amended 2026-08-08** by the merge of ARCHIVE's eight 08-08 fragments (ledger
3.18, 31 contests): four new numbered items (**R93–R96**, archival tooling),
one fold (**R49(3)**), three decision-input appends (**R37, R39, R40**). The
archival-tooling trio was slotted at position 2 because **R95 was the only open
item losing evidence on a recurring basis**. **R93, R94, R95, R49 (all three
parts) and R30(c) then landed the same day**, which is why the queue below is
shorter than the amendment implies: what remains of the archival batch is R96
alone, and R30's open half is a data pull from Ben rather than code. **R39 left
the opportunistic tier** because 3.18 turned it from bookkeeping honesty into a
measured payoff, **and then landed the same day too**. **R97 was filed and
landed the same day and never sat open here**: R49 left
`tools/rebuild_registry.py` still resolving salary by the repo-wide pooled
policy it had just replaced in the miner, so it is a direct consequence of that
commit rather than independent work. Its entry is in CHANGELOG.md per the
migration contract, and the number is recorded here so it is never reused.

**Amended again 2026-08-08 (evening)** by a BUILD tranche, **R98–R99**, filed
from the 1910_9g nine-game Classic build after Ben asked why the portfolio
looked wrong. It was wrong, and the cause was a candidate bank explored to 1.8%
against a budget that had silently bottomed out on a hardcoded floor. R99 is a
reporting-truth XS in the opportunistic tier. Both belong to the R51/R92 family
— an honest report that still produces a wrong decision — which is now the most
frequently recurring shape on this board.

**Amended a fourth time 2026-08-09** by the DEV commit that took **R61 whole and
closed R47**. R61 shipped all seven of its asymmetries, not the one it was filed
on, and leaves the queue. R47 was an investigation and both mechanisms are now
found; neither was what the entry proposed, so R47 closes and its remainder is
refiled as **R101** (position 3, the cache discard) and **R102** (opportunistic,
the pinned same-game pair; renumbered **R103** on 2026-08-10 after the sync
commit took R102 — see that entry). One new P3 tail, **R61-tail**, is filed in section 1.
The reasoning and the corrections are in CHANGELOG.md; no R-numbers were
reassigned.

**Amended a fifth time 2026-08-10** by the DEV commit that took **R101**. It
leaves the queue and its entry is in CHANGELOG.md per the migration contract.
Ben's decision, taken on the item's own terms: bucket by conditions signature,
not one exclude set for the whole solve — the second would have removed legal
players from an entry's search as a convenience, invisibly, inside a certified
artifact, which is the pool reduction CLAUDE.md forbids. The item's second-order
suspicion held and was the sharper half: the stack bounds are relaxed before the
signature is computed, so entries pinning different numbers of hitter slots
bucketed apart even on identical exclude sets, and the 2026-08-03 record carries
five distinct signatures over one swap. The numbered queue below is now five
items; no R-numbers were reassigned. **R102** (now **R103**) stays open in section 1, and the
headline 1,007-versus-8 measurement is NOT reproducible from the 2026-08-03
inputs any more — `data/reference/` has moved since — which the changelog states
rather than papering over.

**Amended a sixth time 2026-08-10** by the DEV adjudication of the revised
greenfield spec (`docs/2026-08-10_critique_greenfield_spec.md`, read the tree
at 89ca350 — this HEAD — so every line cite was checkable; the root copy
`DFS_SYSTEM_GREENFIELD_SPEC.md` is Ben's upload and stays his). It is a
revision of the 2026-08-01 spec already disposed in the R41/R42 changelog
entry, and roughly four fifths of its 34 flaws and 42 architecture items map
to standing dispositions; the full mapping is in the CHANGELOG entry of this
date. What survived as new work, all of it independently confirmed by live
BUILD fragments before the spec arrived: **R104** (PO/PLR starting-token
policy, spec F-21), **R105** (Showdown manifest status vocabulary, spec F-16),
**R106** (`--postures` cannot express ticket_count; not in the spec, fragment
only), an elevation of **R45** to P1 with two new burn records folded in (spec
F-20), **R31(d)** (the engine mutex is nominal), and one sequencing note on
**R62** (fixture tracking rides the GH PAT). Rejected with evidence: F-05
(the "phantom" sim modules are bannered "Retired ... not present in this
repo" at MLB_Classic.md:520/547/563 — the doc is truthful), F-02 (the label
discipline it demands is verbatim in `contest_allocator.py:35-36`), and
F-33's demand to supersede the do-not-build anti-goals, which stays governed
by R13. Six consumed fragments were deleted; the 2026-08-09
curated-archetypes fragment stays for ARCHIVE. **One collision corrected: the
backlog's same-game-pair item filed 2026-08-09 as R102 is renumbered R103**,
because the 2026-08-10 sync commit took R102 in the changelog, tests,
tools/claim.py, tools/sync_check.py, and CLAUDE.md — the tree wins, and the
one-writer lesson is recorded on the R103 entry. The numbered queue below is
six items; no other R-numbers moved.

**Amended a third time 2026-08-08 (evening)** by the DEV commit that took **R63 and
R98(1)(2)**. Both leave the numbered queue. R63 resolved as a CONTRACT change,
not a code change: build_slate does not run a plan leg first, deliberately, and
CLAUDE.md item 3 now names which door gets which review (reasoning in
CHANGELOG.md; pinned by `BuildContractCheckpointTests` from both sides). R98's
parts (1) and (2) shipped and part (4) half-landed; **what is left of R98 is
repriced M and moves to the opportunistic tier**, because part (1) made the
failure loud and that was the urgent half. The numbered queue below is six items
and no R-numbers were reassigned.

## Section 1 additions — 2026-08-04 full-project audit (R51–R80) — original tranche introduction

Filed by the 2026-08-04 DEV audit session: six independent whole-tree review
passes plus a clean-container replication of the session-start gate (runtime
evidence in the CHANGELOG entry of the same date). Every item was verified
against this tree before filing, per R36's practice; the few the audit could
not reproduce live are labeled PLAUSIBLE inline. Two reviewer claims did not
survive verification and were not filed (a dangling-docs-paths claim that was
an artifact of the audit's partial snapshot — `docs/legacy/` exists — and a
lock-vs-runtime claim refiled in corrected form as R78(b)).

## Section 1 additions — 2026-08-08 ARCHIVE tranche (R93–R96) — original tranche introduction

Filed 2026-08-08 by DEV from the five archival-tooling fragments ARCHIVE left
while mining A-035..A-037 (31 contests; ledger 3.18). The fifth fragment, the
explicit-`--salary` zero-join gate, extends an existing item and was folded
into **R49(3)** rather than numbered. Common thread across all five: none of
them touches the certified path, and every one of them is a tool that reported
success while doing nothing, or did work in an order that left side effects
behind a failure. That is the same family as R51/R92 (a guard that cannot
fail), seen from the archival side.

## Section 1 additions — 2026-08-08 BUILD tranche (R98–R99) — original tranche introduction

Filed 2026-08-08 by DEV from the 1910_9g nine-game Classic build, after Ben
asked for a self-diagnostic on a portfolio that "seemed weird and different."
It was: 7 distinct lineups across 9 entries with one pitcher at 5/9. The
diagnostic found the cause was a 1.8%-explored candidate bank, and that both
the engine's guidance and the operator's saved notes pointed at the wrong
lever. Common thread with R92 and R51: the surface reported the truth
(relaxation counts were recorded honestly, per R64) while the *cause* of that
truth stayed invisible, so the honest record still produced a wrong decision.

## Section 1 additions — 2026-08-10 greenfield-revision adjudication and fragment merge (R104–R106) — original tranche introduction

Filed by DEV from six consumed `docs/backlog_inbox/` fragments (BUILD sessions
2026-08-05 through 2026-08-09, plus the 2026-08-10 sync remainder), each
independently confirming a claim in the revised greenfield spec or standing
beside it. Every line cite below was verified against this tree (89ca350)
before filing. R106 is a feature gap rather than a bug and would sit in
section 2 by grammar; it lives here so the three fragment-born items stay
together with their shared provenance.

# Sources

- RC and CC: the two uploaded critiques disposed above, archived alongside this file.
- The 2026-08-01 pair, adjudicated in the R41/R42 changelog entry:
  `docs/2026-08-01_critique_greenfield_spec.md` (read the tree at 48b4e7e;
  line cites verified before ruling) and `docs/2026-08-01_critique_gemini.md`
  (did not read the tree; rejected wholesale).
- The 2026-08-10 revision of the greenfield spec, adjudicated in the
  R103–R106 changelog entry: `docs/2026-08-10_critique_greenfield_spec.md`
  (read the tree at 89ca350; 34 flaws + 42 architecture items; three accepted
  onto this board via the fragments that independently confirmed them, F-05
  and F-02 rejected on re-verified facts, the rebuild program rejected
  unchanged).
- The 2026-08-12 third edition, adjudicated as a delta in the changelog
  entry of that date: `docs/2026-08-12_critique_greenfield_spec.md` (read
  the tree at 6c96474 = its own HEAD; 35 flaws + 43 architecture items; five
  concessions recorded, F-35/A-43 new and rejected on standing grounds, one
  rider adopted onto R41).
- The 2026-08-12 Gemini pair, adjudicated in the changelog entry of that
  date, both rejected wholesale with zero adoptions:
  `docs/2026-08-12_critique_gemini_spark.md` (the 07-25 CC program
  re-argued; PuLP premise false against this tree, four proposals already
  shipped at the paths named, one phantom file) and
  `docs/2026-08-12_critique_gemini_pro.md` (the 2026-08-01 Gemini critique
  regenerated; did not read the tree, again).
- Context engineering and loops: [The new rules of context engineering](https://claude.com/blog/the-new-rules-of-context-engineering-for-claude-5-generation-models), [Building verification loops with skills](https://claude.com/blog/building-verification-loops-in-claude-code-with-skills), [Getting started with loops](https://x.com/ClaudeDevs/article/2074208949205881033)
- Provider capabilities (for R10 framing): [Stokastic](https://www.stokastic.com/), [SaberSim contest sims](https://support.sabersim.com/en/articles/12079199-how-contest-sims-work), [RotoGrinders LineupHQ](https://rotogrinders.com/lineuphq)
- DraftKings: [late swap](https://help.draftkings.com/hc/en-us/articles/4405224380051-Late-Swap-Overview-US), [MLB rules](https://www.draftkings.com/help/rules/mlb)

