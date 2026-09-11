> **Status (2026-09-10, board adjudication of the thirteenth edition).** This package
> is R302's strangler at stage 0: offline-verified, isolated, NOT the build path and
> not canonical. Live slates are built through `skills/generate-lineups/SKILL.md`
> and `execution_pipeline.run_slate`, as CLAUDE.md's Authority section says. The
> "canonical" wording below is the author's and was not adopted; the package has
> no projection, ownership, field or archive source until R339 lands, and it is
> graded by R118 before it replaces anything (R302's start condition). Two known
> defects ride the stage-0 commit (R338): `dfs.py`'s environment guard fails on a
> POSIX venv, and `production/state.py` uses SQLite's DELETE journal, which the
> Cowork mount cannot unlink (R109).

# DraftKings MLB production runbook

The canonical command is `python tools/dfs.py`. It supports Classic and Showdown,
preserves Entry IDs and locked slots, and ends with a validated file for manual
review and upload. It never logs into DraftKings or submits an entry.

The engine is verified with fictional offline data. Real builds require a current,
verified local evidence snapshot. A live news/lineup connector and a calibrated
economic model are not configured. Do not treat a legal file, a prior simulation,
or a conditional payout estimate as proof of an edge.

## Start on Windows

Open a terminal in this project folder. Setup is already installed in this workspace.
For another computer with Python 3.11–3.13, run this once:

```powershell
python tools/bootstrap_engine.py
```

This installs pinned, free packages in this project's `.venv`. It leaves global
Python alone. Windows Python 3.13.7 is the verified runtime. The package lock is
portable, but another Python version or operating system needs its own acceptance
run before operational use. No API subscription is required.

Run the complete fictional demonstration:

```powershell
python tools/dfs.py demo
```

The command creates a new folder under `outputs`, builds three Classic entries,
tests an enhancement, reports its acceptance or rejection, then repairs a late
scratch with the first game locked. It checks that original inputs remain unchanged.
The result includes the safe CSV and `demo_result.json`. **Fixture files are never
for upload.** Repeating this command creates a separate demonstration folder.

Check the environment or run all automated acceptance checks:

```powershell
python tools/dfs.py doctor
python tools/verify_engine.py
```

The latter saves the full test log, individual pytest results, static checks,
format check, compilation results and a source fingerprint in a unique `.tmp`
folder. The older `tools/audit.py` gate remains useful for historical compatibility
tests; it does not cover the new pytest function suite. Use `verify_engine.py` for
the complete current tree.

## Supply a real slate without programming

Download DKSalaries and DKEntries manually from DraftKings. Keep the downloads.
Create a new intake folder; choose a name that does not already exist:

```powershell
python tools/dfs.py intake --salary "DKSalaries.csv" --entries "DKEntries.csv" --output "data/slates/my-slate/intake"
```

The command copies the raw downloads and creates CSV sheets that can be opened
in Excel. IDs, teams, game identities and start times are already filled from the
salary file. Read the generated `READ_ME.md`. Supply verified participation,
weather, projections, contest type and source timestamps. These are factual data
inputs, not programming. Save each source file beside the sheets; its hash is
computed automatically. Never put a credential file in an intake folder.

Expected points must be DraftKings points from a supplied quantitative model.
Optional standard deviations enable the simulation. Player ownership is a
fraction: `0.25` means 25%. Complete Classic ownership totals must sum to 2 pitcher
and 8 hitter slots; Showdown totals sum to 6 people and, when complete, 1 captain.
The engine does not manufacture means or uncertainty from fantasy-point averages.

Freeze the sheets:

```powershell
python tools/dfs.py freeze --input "data/slates/my-slate/intake"
```

Use the evidence filename printed by that command:

```powershell
python tools/dfs.py run --salary "data/slates/my-slate/intake/DKSalaries.csv" --entries "data/slates/my-slate/intake/DKEntries.csv" --evidence "data/slates/my-slate/intake/evidence_HASH.json" --output "outputs/production"
```

`HASH` above is a placeholder for the actual filename the freeze command prints.
A provider can instead supply a strict `EvidenceBundle` JSON and its hash-bound
source files directly. `python tools/dfs.py schemas` writes the exact schemas.
The provider interface refuses unavailable live access; it never substitutes a
fixture or older slate. A packet compiled from empty sheets cannot run.

Participation/game/lineup evidence has a default maximum age of 30 minutes,
weather 60 minutes, and projection evidence 24 hours. Each source's declared
expiry can make this shorter. Sources cannot be future dated. The next source-age,
expiry or game-lock boundary appears as `recheck_at`; recheck before upload.

## Portfolio controls and enhancements

`--baseline-only` skips enhancement while retaining every requested hard control.
The default baseline imposes platform legality and the Classic opposing-pitcher
policy. Exposure defaults are 100%, no salary floor and no cross-entry overlap
cap; the result reports actual concentration. This permits a legal small-entry
baseline without covertly rounding up an impossible fractional cap. Choose tighter
controls explicitly for a portfolio. Zero exposure really forbids a player class;
the engine does not silently convert it to one entry.

A controls file is optional; the generated `Controls.schema.json` describes all
fields. An analyst/provider can supply it, and the command uses it unchanged:

```powershell
python tools/dfs.py run --salary "DKSalaries.csv" --entries "DKEntries.csv" --evidence "evidence.json" --controls "controls.json"
```

The controls include salary floor, player/pitcher/captain exposure, primary-stack
exposure and minimum size, pitcher-pair repetition, team/game exposure, overlap,
a named stack and bring-back minimum, starter policy, freshness, solver budgets
and simulation settings. All caps count unchanged and locked entries too. Medium
weather limits game exposure to 25%; high weather and postponements prevent new
selections. With too few unaffected games, Classic correctly becomes infeasible.

Unknown contest titles permit a legal baseline but block enhancement until the
objective is identified. Cash, single-entry/small-field GPP, larger GPP, WTA and
satellite profiles use distinct objectives. Explicit contest evidence wins over
title inference. A complete prize curve and legal opponent field enable conditional
payout scoring, including ties, duplicates and competition between your entries.
Ticket prizes must be explicitly labeled face value and are never reported as cash.

Every enhancement is a new solve. It must improve both the ceiling and safety
criteria, with at least one strict improvement, on construction and separate
simulation draws. There are at most three iterations; a rejected proposal stops
the loop. These tests measure the supplied prior model, not real-world EV. Missing
moments, a timeout or a rejected proposal preserves the already verified baseline.

## Read the result

| Result field | Meaning |
|---|---|
| `FILE_VALID` | Exact exported bytes passed the independent legality referee at `valid_as_of`. |
| `workflow_valid` | The frozen-input workflow, evidence and final byte checks passed; the returned current value becomes false if recheck time has passed. |
| `selection_certified` | Selected lineups passed exact constraints; inspect solver status for optimality and search scope. |
| `allocation_certified` | Whole-entry assignment, caps, uniqueness, authorization and preservation passed. |
| `MODEL_STATUS=PRIOR_ONLY` | No calibrated economic advantage is certified. |
| `FIXTURE_DO_NOT_UPLOAD` | Fictional offline output. Never upload. |
| `MANUAL_REVIEW_REQUIRED` | Structurally valid live-input export requiring current evidence review and manual platform action. |
| `DO_NOT_UPLOAD` | A hard check failed, the source/lock boundary passed, or readiness is otherwise unverified. |

Artifacts are under `outputs/production/runs/RUN_ID/`. `inputs/` holds immutable
captured bytes; `final/` holds `DKEntries.csv`, assignments and diagnostics. The
manifest binds all hashes, source provenance, configuration and runtime identity.
The convenience copy is `outputs/production/safe/SCOPE/latest_safe_export.csv`.
Separate slate/entry scopes cannot overwrite one another's convenience file.

SQLite records the committed current run and export bytes in one transaction.
The safe CSV is an atomic, recoverable mirror. Never edit a run's files or the
database. A failed new build creates a unique failure record and leaves the prior
safe export available; availability does not imply its evidence is still current.

## Late swap and monitoring

First confirm manually that the intended parent is the lineup currently on the
platform. Supply its immutable `runs/RUN_ID/final/DKEntries.csv`, current evidence,
and each Entry ID the operator authorizes for changes. Keep the same output store:

```powershell
python tools/dfs.py late-swap --salary "DKSalaries.csv" --entries "outputs/production/runs/RUN_ID/final/DKEntries.csv" --parent "outputs/production/runs/RUN_ID/final/DKEntries.csv" --evidence "updated_evidence.json" --output "outputs/production" --entry-id 123456 --entry-id 123457
```

Replace RUN_ID and the sample Entry IDs with those printed for your actual run.
The parent must be the current committed export. Started/in-progress/final slots
stay fixed, including an already locked scratch that can no longer be repaired.
Unchanged unavailable locked players are prominently reported. Unlocked confirmed
outs, high-weather games and postponed games cannot enter a replacement lineup.
No new already-started player is allowed. Unknown lock times block the build.

A configured external provider can update the local evidence file and source
artifacts. Monitor those files with:

```powershell
python tools/dfs.py watch --salary "DKSalaries.csv" --evidence "current_evidence.json" --output "outputs/production" --scope SCOPE --entry-id 123456 --entry-id 123457
```

This is **local snapshot monitoring**, not verified live feed connectivity. It
checks every 30 seconds by default, stays quiet when unchanged and reruns only on
changed evidence or a readiness boundary. Each solve has a shared time budget and
a separate worker deadline. Repeated failures preserve the safe artifact. Stop
with Ctrl+C; `--cycles 1` makes a single scheduled check. The operator still uploads
each accepted change manually. A rebuilt file is not proof of a platform update.

## Recovery, updates and Unix use

Verify/recover the latest committed safe file using the actual scope:

```powershell
python tools/dfs.py verify --output "outputs/production" --scope SCOPE
python tools/dfs.py recover --output "outputs/production" --scope SCOPE
```

Recovery checks every hash and rederives legality from frozen inputs before
repairing the mirror. It reports whether a new freshness check is needed. A stale
parent, changed artifact, unconfined manifest path, empty certification or competing
publication cannot advance the current pointer.

On Unix use the same `python3 tools/bootstrap_engine.py`, then
`.venv/bin/python -B tools/dfs.py ...`. Run the full acceptance suite on that host;
Unix/WSL was not executed in this Windows validation. A cron entry can run a single
already-configured snapshot check; no schedule is installed by this overhaul:

```cron
* * * * * cd /absolute/project && .venv/bin/python -B tools/dfs.py watch --salary /absolute/inputs/DKSalaries.csv --evidence /absolute/inputs/current_evidence.json --output /absolute/project/outputs/production --scope SCOPE --entry-id ACTUAL_ENTRY_ID --cycles 1 >> /absolute/project/outputs/monitor.log 2>&1
```

For continuous use prefer one long-running watch process so its unchanged-input
token persists between polls. Use only verified provider files and correct Entry
IDs. No scheduling arrangement creates credentials or a data feed.

Before upgrades, preserve the complete output store and code revision/patch. To
recover an earlier output, inspect its immutable run, then start an explicit new
build from the actual platform state; do not hand-edit the current pointer or
copy stale bytes over the safe mirror. Older legacy commands are for historical
replays and retain documented limitations; they do not acquire this new workflow's
certification merely because they still run.
