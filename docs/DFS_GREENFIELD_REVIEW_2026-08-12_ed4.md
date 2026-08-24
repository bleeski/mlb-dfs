# Greenfield review, fourth edition: what survives the standing record

**Date:** 2026-08-12
**Reviewed at:** commit `329b8fa` (R110), working tree clean except 19 untracked archive/reference files
**Role:** none taken. No claim held, no repo file modified, no engine path executed that writes.
**Filename note:** the requested name `DFS_SYSTEM_GREENFIELD_SPEC.md` is occupied by the third edition, hard-linked to `docs/2026-08-12_critique_greenfield_spec.md`, which the adjudication protocol depends on keeping ("archived beside the prior editions, so the next regeneration can be diffed"). Overwriting it would destroy the diff base and violate the read-only mandate in the same stroke. This file takes a new name instead.

---

## 0. Lead finding: the requested deliverable is the wrong one, and the record says why

The brief asked for a zero-base greenfield critique assuming nothing built so far is correct. That document exists three times over. Every edition was adjudicated, and the pattern of the rulings is the most useful thing in this repo for anyone writing a fourth.

| Review | Date | Sections | Adopted |
|---|---|---|---|
| CC / red team | 2026-07-25 | — | corroboration only, zero new work |
| Greenfield spec ed. 1 | 2026-08-01 | — | 2 items filed (R41, R42) + 5 extensions |
| Gemini | 2026-08-01 | 9 | **0 of 9** |
| Greenfield spec ed. 2 | 2026-08-10 | 76 | 3 items, all of which "BUILD fragments predate the spec and carry the sharper evidence" |
| Greenfield spec ed. 3 | 2026-08-12 | 78 | **1 rider** (R41 `Pool_Basis`), 5 reviewer concessions, 2 new sections rejected |
| Gemini Spark + Pro | 2026-08-12 | — | **0, rejected wholesale** |

Marginal yield across roughly 160 findings in the last twelve days: one rider on an existing backlog item.

That is not the reviewers being lazy. Three specific mechanisms produce it, and all three are documented:

1. **The premise keeps being false.** PuLP has now been diagnosed or prescribed by external reviewers four times. `grep -ri pulp mlb_engine tools tests skills` matches nothing, and has matched nothing since the repo began. I re-ran it today; still nothing. `scipy.optimize.milp` is the pinned authority at `optimizer_v3.py:86`.
2. **Proposals arrive as greenfield for things that already exist at the paths the proposal names.** Ed. 3's count was four. Spark's Part 2 proposed `build_state_manager.py`, `bank_cache.py`, a deterministic preflight, and swap-from-bank, all four shipped.
3. **The rebuild program is gated on a decision, not on an argument.** R13 (scale or freeze the stakes) and R10 (satellite ownership prior) gate the sim/economics stack. Re-arguing the architecture does not move a gate whose input is graded slates.

**So this edition does not restate the rebuild program.** It contributes three things instead: runtime evidence no prior reviewer could produce, one structural finding about the objective function that the record documents only halfway, and a correction to the sequencing of the sim gate itself.

---

## 1. Runtime evidence: the first review to actually run the thing

Every prior critique was static-only. Ed. 3 says so in its own method section: NumPy, pandas, SciPy and `scipy.optimize.milp` were all unavailable on the reviewer's Windows 3.13 environment, so `tools/audit.py --run-tests --terse` stopped at the dependency gate after 79 tests. The 08-10 adjudication extracted the same concession under F-27.

This sandbox is Linux, Python 3.10.12, and the repo vendors scipy 1.15.3 in `.pylibs/`. The locked configuration ran.

### 1.1 The gate passes, at the pin, in one call

```
$ python3 tools/audit.py --run-tests --terse
PASS  v2.26.0  26 modules  883 tests
TOTAL WALL 74.82s
```

Per-suite, each in its own process, cold cache:

| Suite | Result | Pin | Wall |
|---|---|---|---|
| `test_core` | 582 passed, 27 subtests | 582 | 68.27s |
| `test_showdown` | 55 passed, 6 subtests | 55 | 4.81s |
| `test_upload_integrity` | 162 passed, 92 subtests | 162 | 11.72s |
| `test_golden_replay` | 9 passed, 2 subtests | 9 | 19.78s |
| `test_paste_lineups` | 75 passed, 14 subtests | 75 | 3.31s |
| **Total** | **883** | **883** | |

Zero failures, zero skips, zero errors. Four `FutureWarning`s, all pandas dtype-assignment notices in `test_core.py` fixtures (for example `:6308`, assigning `"probably not"` into a bool column, which is the R-numbered Excluded-coercion test doing exactly what it should). No warning indicates a defect.

Every pin in `EXPECTED_SUITE_COUNTS` is accurate. The Quick Card's `883` is current. The R110 entry's caution that the single-line gate did not complete in its sandbox is a real observation about that sandbox, not about the gate.

### 1.2 The audit is I/O-bound, not compute-bound, and that retires an operating constraint

Re-running immediately, warm:

| Run | Cold | Warm | Delta |
|---|---|---|---|
| `test_core` alone | 68.27s | **32.35s** | −53% |
| Full `--run-tests --terse` | 74.82s | **66.56s** | −11% |

`test_core` halves on a warm cache. The cost is first-touch reads of test fixtures and module bytecode across the mount, not solver work or Python execution.

**Why this matters operationally.** The Quick Card carries an elaborate workaround built on the premise that the suite cannot fit a tool call: split `test_core` into class chunks (33 classes / 205 tests / ~20s, then classes 34-45 / 51 tests / ~23s, then `DeterminismTests` alone because it "exceeds 40s"), then four more suites, then `audit.py --terse`. That is eight calls, and the Card itself flags the chunk boundaries as stale by seven tests. My own memory of this project carries the same rule.

The measurement says the constraint is softer than the workaround assumes, and is a property of cache state rather than of the suite. The full gate ran in 74.82s against a ceiling near 178s, with better than 2x headroom, on the first try, cold.

**Spec — session-start warm-up, replacing the chunking ritual.** One cheap call that touches the working set, then the gate in a single call:

```bash
# call 1: warm the mount (~5-10s, no assertions, output discarded)
python3 -c "import mlb_engine.optimize.optimizer_v3, mlb_engine.pipeline.execution_pipeline" >/dev/null 2>&1
find tests/fixtures -type f -exec cat {} + >/dev/null 2>&1

# call 2: the gate, one line, one call
python3 tools/audit.py --run-tests --terse
```

Falsifiable and cheap to check: if call 2 exceeds the window on Ben's Windows mount, the chunk fallback stays and this finding is scoped to Linux containers only. It should be measured on the device mount before the Quick Card changes, because the Card's numbers were taken there and mine were not. That measurement is the whole cost of the item.

### 1.3 The `$HOME`-is-full wall reproduced, unprompted

Installing pytest failed:

```
ERROR: Could not install packages due to an OSError:
[Errno 28] No space left on device: '/sessions/.../.local'
```

This is the 2026-08-03 SD@ARI incident class, filed as R42(b) and deprioritized to Tier 6 on the grounds that R42(a) and `.pylibs` made it rare. It is rare for the engine, because scipy is vendored. It is not rare for anything else: I hit it on the first non-vendored package I asked for, on a container with 2.7 GB free on `/`, because the failure is a quota on `$HOME` and not a full disk.

The workaround that worked, in one line, no engine impact:

```bash
pip install <pkg> --target=/tmp/<name> --break-system-packages -q
export PYTHONPATH=/tmp/<name>:$PWD/.pylibs
```

**Recommendation:** leave R42(b) in Tier 6 (its impact really is bounded), but put the `--target=/tmp` line in `env_probe.py --install`'s failure message. That converts a dead-end error into a recovery, costs one string, and rides any session already touching the file. The Tier 6 bar is "name the measurement that changed its standing"; this is not that, so it should not be pulled as an item. It is a one-line rider.

### 1.4 R109's delete grant did not generalize, and the residue is now 18 files

The backlog records the R109 residue sweep as unblocked: the 2026-08-12 fifth session noted "the Cowork delete grant let `rm` clear a stale `.git/index.lock`."

It did not hold for me today:

```
$ rm -f .git/index.lock
rm: cannot remove '.git/index.lock': Operation not permitted
```

The documented `mv` remedy worked. So the grant was session-scoped or narrower than the note reads, and R109's sweep is still blocked in the general case. Worth correcting in place, because a session that trusts the note will try `rm` first and lose a call to it.

The residue it leaves is now visible:

```
$ ls .git/index.lock*    ->  18 files
.git/index.lock.bak, .stale, .stale2, .stale3,
.stale-20260810T221025Z ... .stale_20260812T220411Z
```

Two of them show the naming drift the remedy invites: `.stale-20260810T221217ZF` has a trailing character, and two carry nanosecond-suffixed timestamps from a different date format. Harmless individually, and none of it is in the DEV write set, but it is the accumulating cost of a workaround with no cleanup path.

Also worth knowing: the lock regenerates on **every** `git status` on this mount, because git creates it to refresh the index and cannot unlink it. So the file being present is not evidence that a session died mid-write, and a session that treats a present lock as a stale-lock incident will chase nothing. Only a lock whose timestamp predates the current session means anything.

---

## 2. The finding that survives: the objective function is scale-invariant, and only half of that is on the record

This is the one place where I think the record is genuinely incomplete rather than merely re-argued. I verified it three ways because the R36 method demands it, and because the half that IS documented is documented well enough that claiming novelty for the whole thing would be exactly the reviewer failure this board keeps rejecting.

### 2.1 What the repo already says

`MLB_Classic.md:199`, verbatim:

> "Uniform Floor/Ceiling multipliers (0.58/1.42) made ceiling-maximization rank-identical to mean-maximization, so the GPP ceiling objective carried no player-specific variance information."

Correct, known, and **already fixed for the ceiling path**. The v2.24.0 `Ceiling_Multiplier` work (xISO percentile for hitters, K-rate for pitchers, clipped 1.25-1.60) exists precisely to break that degeneracy. The same line closes: "Floors stay uniform on purpose; the GPP objective consumes Ceiling."

So the ceiling half is not a finding. It is a solved problem with a dated decision.

### 2.2 What follows from it and is not stated anywhere I could find

`build_projections` at `projection_builder.py:103`:

```python
frame["Floor"] = resolved * float(floor_multiplier)   # 0.58, unconditional
```

There is no per-row floor path. `Ceiling` has one; `Floor` does not, by the stated design decision. And the objective at `optimizer_v3.py:714-723` is linear in the chosen column:

```python
value_col = 'Ceiling' if target == 'ceiling' else 'Floor'
...
df['_obj'] = df[value_col]
```

`Floor` is therefore a positive scalar multiple of `Base_Projection` for every player, on every slate, permanently. The argmax of a linear objective is invariant under positive scaling. **So `target='floor'` is not floor-optimized selection. It is exactly points-maximization, always, with no exception and no slate on which it differs.**

The documented reasoning stops at the GPP path, where the conclusion was "consume Ceiling, and enrich it." The corollary on the cash path was never drawn: cash builds are not trading upside for safety, they are ranking on mean and relabeling it.

### 2.3 Empirical confirmation

Read-only, in `/tmp`, `build_single_lineup` called directly on synthetic 4-team pools, no penalties, no suppression, 25 seeds:

```
FLAT multipliers (no enrichment): ceiling-target == floor-target in 25/25 slates
WITH per-row Ceiling enrichment:  identical in 4/25; mean overlap 6.28/10, min 2
floor-target == raw Base_Projection-target: True
ratio ceiling_obj/floor_obj = 2.448276   (1.42/0.58 = 2.448276)
```

The objective ratio matching 1.42/0.58 to six figures is the scalar-multiple property, measured rather than asserted.

Two conclusions, of different strength:

- **Structural, always true:** floor-target selection == mean-maximization. Not a sample result; it is algebra, and the 25/25 and the exact ratio confirm the implementation matches the algebra.
- **Measured, first time:** enrichment is the *only* thing separating a GPP build from a cash build. With it, the two disagree on 4 of 10 roster slots on average. Without it, they are the same lineup.

### 2.4 Why this changes what `signal_applied` means

`SKILL.md:153-156` tells a session that `enrichment.signal_applied == False` means "a materially weaker portfolio, and Ben should be told plainly rather than handed a certified file that looks identical to a good one." That instruction is right and it now has a precise mechanism: when enrichment is absent, the GPP portfolio and the cash portfolio are **the same object**, and the contest-posture machinery above them is selecting between identical candidate sets.

"Materially weaker" undersells it. The honest statement is "undifferentiated": the build has no contest-type signal at all, and `ceiling_weight: 1.00 / floor_weight: 0.00` in `CONTEST_SHAPE_PROFILE_WEIGHTS` is describing a distinction that does not exist on that slate.

### 2.5 Two limits on this finding, stated rather than buried

- **Portfolio builds break exact invariance.** `build_multi_lineup` applies DU penalties, and `_obj = value_col - penalty` is affine, not scalar. A fixed penalty is 2.45x more powerful against a Floor-scaled objective than a Ceiling-scaled one (0.58 vs 1.42), so diversity penalties bite harder in cash mode by an accident of scale rather than by decision. I did not measure whether that is material at shipped penalty magnitudes. It is a hypothesis with a named mechanism, not a finding.
- **The suppression tiebreaker** (weight 0.0003, lineup cap 0.75) also breaks exact ties, and is documented in-code as a tiebreaker. It does not affect the argument.

### 2.6 Spec

Smallest honest fix, no gate change, no strategy change, recording only:

```python
# projection_builder.build_projections, beside the Ceiling_Multiplier block
frame["Floor_Basis"] = "uniform_0.58_of_base"   # or "per_row" if a floor path ever ships
```

and surface in the brief, next to `enrichment.signal_applied`:

```json
"objective_differentiation": {
  "floor_basis": "uniform",
  "ceiling_basis": "per_row_enriched" | "uniform",
  "cash_and_gpp_selection_identical": true | false
}
```

When both bases are uniform, `cash_and_gpp_selection_identical` is `true` and the session says so. That is one boolean the operator cannot currently derive from any field in the brief, and it is the difference between a portfolio with contest-type signal and one without.

The strategy question (should Floor get a per-row basis, from playing-time and role variance rather than power) belongs in `MLB_Classic.md` and is not a pool-membership or recording fix. Filing it as work now would repeat the mistake R60's entry names: shipping a strategy change inside a plumbing item.

---

## 3. Sequencing correction: the sim gate as written will not open onto a working sim

This is the one place I would push back on the board's own ordering rather than on a reviewer.

The do-not-build list gates the Monte Carlo / field-ROI / play-by-play stack on two conditions: **R13 scales the stakes AND R10's ownership is calibrated.** That gate has been defended four times and the defense is sound as far as it goes: do not fund an EV core before the stakes make it rational.

But look at what the retired simulator actually specified. `MLB_Classic.md:570`, inside §16, which carries its retirement banner at line 563 (I checked, because claiming these modules are phantoms is the exact error that got ed. 2's F-05 rejected):

> "sigma = (Ceiling − Floor) / (2 × 1.2816), placing Floor and Ceiling at p10/p90 of the unclipped marginal"

Substitute the uniform multipliers:

```
sigma = Base x (1.42 - 0.58) / 2.5632 = Base x 0.3277
CV    = sigma / mu = 0.3277,  identical for every player
```

Every player had the same coefficient of variation. The simulator's marginals carried no player-specific variance information, for precisely the reason `MLB_Classic.md:199` identifies about the ceiling objective. The recorded retirement reason is "below the comparable-slate threshold it fell back to a static tail and added no signal." The static tail was not a volume artifact. **It was structural: sigma was a constant multiple of mu, so the sim could not rank anything the point estimate did not already rank.**

Post-v2.24.0 that improves but does not resolve. With `Ceiling_Multiplier` in [1.25, 1.60], CV lands in [0.261, 0.398]. Real, and driven entirely by xISO percentile, which is a power measure. Nothing in that range comes from playing-time risk, blowout/pinch-hit risk, bullpen-game risk, or pitcher workload, which is where most of the variance a DFS sim needs actually lives.

**The correction.** R13 and R10 are the right gates for *funding*. They are not sufficient *preconditions*. Neither produces per-player variance: R13 is a stakes decision, R10 is a field model. If both clear tomorrow and the sim ladder reopens, it reopens onto the same degenerate marginals that retired `slate_sim.py`, and the second retirement would be recorded as another volume problem.

The missing precondition is a per-player variance basis, which is a projection-layer input, not a simulation component. It is adjacent to Finding 15 (replace APPG with an event-rate foundation), correctly parked as the largest project on any version of the list.

**Recommendation, and it is cheap:** add one clause to the do-not-build entry. Not new work, not an R-number, one sentence so the gate does not mislead the session that eventually opens it:

> Sim ladder additionally requires a per-player variance basis. Uniform Floor and enriched-Ceiling marginals give CV in [0.26, 0.40] driven by power alone; `slate_sim.py`'s static tail was a consequence of CV being constant, not of slate volume. Reopening the ladder without a variance basis reproduces the v2.20.0 retirement.

That sentence costs nothing, blocks nothing, and prevents the board from spending its largest build on an input that cannot support it.

---

## 4. Autonomy: three hard walls, and the rest is prose

Mapping every human touchpoint in the slate loop against whether it is actually forced:

| Class | Count | Items |
|---|---|---|
| Hard DraftKings ToS wall | 3 | salary/entries download, upload, standings export |
| Hard data availability | 1 | retractable-roof open/closed, in no forecast feed |
| Judgment the design reserves for Ben | ~9 | naming the slate, declaring an arm on a bullpen game, postures by ID, ship-on-failing-preflight, sha256 check, late-swap authorization |
| Unautomated, no stated reason | ~4 | role assignment, the paste, PowerShell invocation |

The zero-touch target in the brief is unreachable and should stay unreachable: DK's terms prohibit automated interaction and automated entry, ed. 3 documented this with citations, and both Gemini critiques were rejected wholesale for proposing 60-second DK polling and headless auto-upload. That is settled and I am not reopening it.

What is worth saying plainly is a structural observation about the rest:

**Every "Ben decides" gate in this repo is enforced by a sentence in a markdown file, not by code.** `--force`, `--ignore-pool-blockers`, `--assume-gates`, `--declare-pitcher`, `--controls-override`, and omitting `--entry-ids` are all flags a session can pass unilaterally. `run_slate(approve=True)` is a default-False Python kwarg with no approval record; nothing verifies a human saw the checkpoint, and the docstring's "the checkpoint the operator approves" describes an intent the code does not enforce. `build_slate.py` skips the plan leg entirely and deliberately, for the stated and correct reason that it would solve the same MILP twice.

The only code-enforced human wall in the entire system is the **absence of any DraftKings write path**. That single absence is doing all the work, and it is doing it well.

I am not proposing to fix this. An approval-record mechanism is the "promote-command ceremony" already on the do-not-build list, the threat model here is operator error rather than an adversary, and the sha256-in-brief plus preflight already binds the delivered file. The observation is worth having on the record because it correctly locates where the safety actually lives: not in the gates, which a session can talk its way past, but in the fact that nothing in this repo can reach DraftKings.

If one thing were hardened, it should be the cheapest: `--assume-gates`, `--force` and `--ignore-pool-blockers` already record themselves in `diagnostics.json`. Make the *brief* carry them in the same line as the certification verdict, so an overridden gate cannot be read as a clean one at T-5 when nobody is reading `diagnostics.json`. That is R36 F3m, already Tier 1 item 6, already elevated. It is the right item and it is already correctly placed.

---

## 5. Context economics

Session-start reads, measured:

| File | Lines | Chars | Approx tokens |
|---|---|---|---|
| `CLAUDE.md` | 301 | 18,936 | ~4,700 |
| `MLB_Classic.md` | 594 | 47,532 | ~11,900 |
| `skills/generate-lineups/SKILL.md` | 712 | 37,820 | ~9,500 |
| `docs/2026-07-27_backlog_v2.md` | 1,479 | 166,104 | ~41,500 |
| `CHANGELOG.md` | 4,729 | 402,608 | ~100,700 |
| `ledger/…Calibration_Ledger.md` | 5,412 | 534,867 | ~133,700 |

The four mandated session-start items (CLAUDE.md, the audit, solver probe, Quick Card section 0) are well-behaved. CLAUDE.md at 4.7k tokens is dense and load-bearing; the "<25-line CLAUDE.md" absolutism is correctly on the do-not-build list and I am not reviving it.

The problem is not the always-loaded set. It is that **three files grow without bound and two of them are read by a live build.** The Quick Card is nominally "section 0" but is one continuous item-1 paragraph that now runs past 900 words and contains four dated self-corrections, two stale-chunk-boundary warnings, and a retired instruction that another line tells you is retired. It is the single most-read paragraph in the project and it is the hardest one to read.

**Spec, and this is the highest ratio of benefit to lift in this document.** The Quick Card's item 1 has one job: tell a session what command to run and what output means PASS. Everything else in it is history. Split it:

```markdown
## 0. Quick Card
1. Gate: `python tools/audit.py --run-tests --terse` -> `PASS  v2.26.0  26 modules  883 tests`
   Source of truth is EXPECTED_SUITE_COUNTS in tools/audit.py; when this line and
   that dict disagree, the dict wins. Read the state word: only `grew` is a stale
   pin; `shortfall`, `skipped_in_place`, `absent` are LOST COVERAGE.
   Per-suite pins: core 582, showdown 55, upload_integrity 162, golden_replay 9,
   paste_lineups 75. Sandbox fallback and correction history: section 0a.
```

Move every correction, every superseded instruction, and the chunking fallback to a `0a` the session reads only when the gate misbehaves. This is progressive disclosure applied to the one paragraph where the cost is paid every session. It is ARCHIVE's file and an S-lift edit.

`CHANGELOG.md` at 100k tokens and the ledger at 134k are append-only by design and that design is correct; neither is a full-read at session start. No action, and I flag them only so the numbers are on the record.

---

## 6. What I do not recommend, so the fifth edition can skip it

Recorded in the board's own vocabulary, with grounds, to reduce the cost of the next pass:

| Not recommended | Grounds |
|---|---|
| Any `dfs_vnext` parallel package or phased rebuild | Rejected 08-01, 08-10, 08-12. Gated on R13, which is a decision awaiting graded slates, not an argument awaiting a better document. |
| PuLP, CP-SAT, or any solver migration | `scipy.optimize.milp` is pinned authority. Zero PuLP in tree, re-verified today. No measured solver problem exists; the 2026-08-03 incidents were installation failures that never reached a solver. |
| SQLite/WAL run-state authority, persisted FSM, signed manifests, fencing-token leases | Threat model is operator error, not adversaries. sha256-in-brief plus preflight binds the file. F-35's remedy rejected on standing grounds 08-12. |
| Any DraftKings automation, polling, or auto-upload | Absolute wall. Both Gemini critiques died here. |
| Deleting or restructuring the CSV archive | It is the append-only calibration substrate R10 and R13 both read. |
| Monte Carlo / field-ROI stack now | Gated, correctly. But see §3: the gate as written is necessary and not sufficient. |
| Module extraction argued from file line counts | `optimizer_v3.py` at 4,215 lines is large and the tests hold it. Extraction for its own sake rejected 08-04. |
| A fifth greenfield document | This file's §0 is the argument. The next review-shaped document should be written when the backlog is substantially landed, per the standing rule. |

---

## 7. What I would actually do next

In order, and only two of these are new:

1. **Ship nothing from this document that competes with Tier 1.** R69, R70, and the false-signal batch are correctly ahead of everything here. Five builds since 08-01 burned on the false-signal family; nothing in this review has that evidence behind it.
2. **Add the objective-differentiation boolean** (§2.6). Recording only, no gate change, rides any session touching `projection_builder.py` or the brief assembler. XS.
3. **Add the variance-basis clause to the sim gate** (§3). One sentence in the do-not-build list. Costs nothing, prevents the largest build on the board from opening onto a known-degenerate input. XS, and it is the item I would most want landed even if nothing else here is.
4. **Split the Quick Card** (§5). ARCHIVE's file, S-lift, paid back every session.
5. **Measure the warm-cache gate on the device mount** (§1.2) before changing the Card's fallback. If it holds there, eight calls become two.
6. **Put the `--target=/tmp` recovery line in `env_probe --install`'s error path** (§1.3). One string, rides anything.

Items 2 and 3 are the substantive contributions. Items 1, 4, 5, 6 are hygiene with measured backing.

---

## Appendix: reproduction

```bash
cd <repo>
export PYTHONPATH=$PWD/.pylibs:$PWD
export PYTHONHASHSEED=0

# §1.1 the gate
python3 tools/audit.py --run-tests --terse

# §1.1 per-suite
for s in test_core test_showdown test_upload_integrity test_golden_replay test_paste_lineups; do
  /usr/bin/time -f "WALL %es" python3 -m pytest tests/$s.py -q --no-header -p no:cacheprovider
done

# §1.2 warm delta: run test_core twice, compare wall

# §1.3 pytest, given the $HOME quota
pip install pytest --target=/tmp/pytest_lib --break-system-packages -q
export PYTHONPATH=/tmp/pytest_lib:$PWD/.pylibs:$PWD

# §2.3 argmax invariance: build_single_lineup on synthetic 4-team pools,
# target='ceiling' vs 'floor', 25 seeds, apply_suppression=False, no penalties.
# Required frame columns beyond the documented contract: Team, Opponent, Game_ID.
```

**Environment:** Linux, Python 3.10.12, scipy 1.15.3 / numpy 2.2.6 / pandas 2.3.3 from vendored `.pylibs`, pytest 9.1.1 installed to `/tmp`. Matches the repo lock. All timings are single-run on one container and should be re-measured on the device mount before any operating rule changes.

**Write scope of this review:** this file only. No repo file was modified, no claim was taken, no engine path that writes was executed.
