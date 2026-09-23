# CLAUDE.md - MLB DFS Engine (Ben's personal project)

A DraftKings MLB DFS lineup engine: a scipy MILP optimizer with intake, allocation, certification, late swap, and an archive-and-ledger loop that grades what won. Sessions build slates (BUILD), mine standings and keep the ledger (ARCHIVE), or change the engine (DEV). Ben uploads files and moves money by hand; nothing here does either. This file is the contract; procedures live where the table at the bottom says; history lives in `CHANGELOG.md` under its R-number, so `grep R157 CHANGELOG.md` is how you read the reasoning behind any rule below.

## Context wall
Personal project. Never mix in Blue Cypress, Elastik Teams, or Izzy context, files, or connectors. If a request seems work-related, stop and ask.

## Truthful labels (non-negotiable)
Every diagnostic, prior, screen, plan, and scan is a deterministic review proxy or a labeled prior. Never say ROI, profitability, win rate, cash rate, edge, or a probability. "Upload-ready" means a certified Classic export where `workflow_valid`, `selection_certified`, and `allocation_certified` all pass. Showdown ships review-grade: never certified, never upload-ready. Archived results are observed outcomes, not graded predictions.

## Authority
- `MLB_Classic.md` governs strategy and contracts; `ledger/MLB_Classic_Calibration_Ledger.md` is the memory.
- `mlb_engine/optimize/optimizer_v3.py` is the lineup source of truth; `scipy.optimize.milp` only.
- Production builds enter at `mlb_engine/pipeline/execution_pipeline.run_slate` and nowhere else. `mlb_engine/production/` is R302's stage-0 strangler: offline-verified, not the build path.
- `mlb_engine/contest_shapes.py` owns the contest-shape vocabulary; every producer validates against it at import.
- The DKSalaries CSV is authoritative for player IDs, salaries, teams, eligibility, and (`Starting` column) posted batting orders. Never correct it against real-world rosters.

## Hard walls
- DraftKings reads are MANUAL and the money-and-entry wall is absolute: no scripted DK access by any client, no uploads, entries, edits, deposits, withdrawals, or stored DK credentials. Ben downloads salaries, entries, and standings (into `data/standings/inbox/`, kept FLAT) himself; sessions may print export URLs and automate everything downstream.
- Never trim the legal player pool to fit a compute limit. A limit may reduce search effort (bank size, time budget), never the legal player set; a trim is invisible in the certified output. A blank `Excluded` cell keeps the player; `optimizer_v3.excluded_flags` / `read_excluded_cell` are the only readers (R289, R291).
- Never log, echo, or write API keys. `THE_ODDS_API_KEY` and `GH_PAT` stay in the environment or `REPO/.env`.
- Before any upload: `python tools/preflight_upload.py --entries <delivered.csv> --salary <salary.csv>`. Exit 0 clean, 2 hard failure, 3 IO error, 4 acknowledged (`--force` prints the failures and exits 4, never 0). This sentence is the pre-upload rule (R287, R305, R324).
- Determinism: every set reaching the solver is sorted first (`mlb_engine.determinism.stable_union`); entry points pin `PYTHONHASHSEED=0`; never `list(set(ids))`.
- Blank reserved entry rows block certification. Ceiling below Floor is a hard error. Ledger edits are in place; the archive is append-only; ownership and outcome counts are conditioned on contest archetype and field size, never pooled.
- Deliverables land in `outputs/<date>/`; `runs/<run_id>/final/DKEntries.csv` is immutable; refinements go through `run_late_swap` with `authorized_entry_ids`, never a rebuild. Every brief states the delivered file's sha256.

## Autonomy (Ben, 2026-08-16 and 2026-09-22; R157, R272, R288, R386)
Use your judgment to override, relax, and constrain without asking, then poke holes in the result. Ask only for a fact only Ben has. A progress report is not a stop: when the next step needs nothing from Ben, take it and put the status note in the same message. Delegated:
- Grow the bank, always: search effort, not strategy, and the first remedy for every refusal against an unexhausted job list.
- Apply a feasibility remedy the engine named in `STRUCTURAL_FEASIBILITY_CHECKS`, to the named value.
- Override a pool blocker you classified benign AND assert `lineup_gate_passed` on the same evidence; both or neither (R133).
- Choose postures, stack plans, the frontier position, and `--max-opposing-hitters-per-sp` (a convention, not a DK rule; R288). Record the value and reason in the brief.
- Loosen the three exposure caps to rescue a proven-infeasible joint MILP whose error names no single binding control (R157): sanity-check at 1.0, re-derive a target from that slate's structural floors, never ship 1.0, record before and after.
- Repair is not strategy (R272): replacing a scratched, absent, or IL player is a REPAIR. Pick among legal replacements by the build's projection (`tools/repair_entry.py`), take the minimum-loss collateral downgrade, and ship a hand-corrected file labeled review-grade when `verify_export.py` and `preflight_upload.py` both exit 0. On an authorized repair, `late_swap.py --accept-downgrade` is the session's call too; the file ships review-grade (R386).
- Ship the file. Blank entries are the MAXIMUM washout: refuse only an ILLEGAL file (started game, blown cap, slot violation), never a poorly shaped one. State the concentration and let Ben decide (1940_9g, 2026-09-01).

**Delivery first (Ben, 2026-09-22; R386).** A legal file before the deadline outranks optional research, simulation, and quality gates. Every check is V (validity), S (strategy), or P (process), defined in `MLB_Classic.md` §2: split a Mixed check into its facts, and treat one you cannot place as V. Under deadline, meaning inside T-30, the session relaxes S failures and records P failures, and either way ships the file review-grade rather than removing it. V is a wall at every clock. Ben's facts (`docs/ROADMAP.md`): F-1 upload takes 5 minutes, so the deadline is first lock minus 5; F-2 DK takes a partial file only with unresolved rows removed, not blank; F-3 never one lineup twice in a contest, an S control that never relaxes; F-4 every build is deadline-aware.

Ben's, not the session's: outside a deadline, an exposure or stack change as a STRATEGY preference with no dead player behind it, or leaving an S or P gate failing; at any clock, a V failure, anything needing `--force`, any reduction of the legal pool, a name-crosswalk failure (under 5 of 9 hitters matched; R133 refuses it by name), and truthful labels. `tools/autobuild.py` is this policy as code, still pre-R386 (its S and P stops under deadline are the session's to clear), and records every decision in `outputs/<date>/autobuild_decisions.json`; reach for it first, and a V stop it reports is a real question.

**The dual objective.** Large wins and no total washout are one frontier: concentration wins a winner-take-all ticket and loses every entry at once. `tools/qa_portfolio.py` reports both ends as review proxies; the washout axis binds at the PORTFOLIO level.

## Build contract
1. `live_data_adapters.build_slate_pool` is the intake front door: the confirmed nine per posted side, the platoon-projected nine per TBD side, feed probables plus declared pitchers; every other salary row is absent. Lineup sources rank PER SIDE: a complete DK `Starting` 1-9, then an operator paste, then an API pull (R143, R32); once a game is underway its boxscore outranks all three (R270). Disagreements are NAMED in the pool report, never silently resolved.
2. The platoon reference ages against the SLATE: past 7 days with a TBD side filled from it blocks at the engine default and warns in `build_slate.py` and `late_swap.py` (R27).
3. Every build is reviewed before it certifies: `run_slate(approve=False)` at the engine door, the script's own pool report at `build_slate.py` (R63). Never approve a slate whose pool report you have not read. On a refusal, read `feasibility.checks` where `passed=False` before `errors[]`.
4. Steps, flags, the supervised path, and Showdown mechanics: `skills/generate-lineups/SKILL.md` and its `references/`.

## Roles, claims, and git
- Roles. BUILD, one slate: `runs/`, `outputs/<date>/`, `data/slates/<date>/`, `data/deliveries/`, its bank cache. ARCHIVE: `ledger/`, `data/archive/`, `data/standings/`, `data/reference/`, `data/deliveries/`, outside live build windows. DEV: `mlb_engine/`, `tools/`, `tests/`, `docs/`, `skills/`, `.claude/`, `.github/`, `CHANGELOG.md`, `MLB_Classic.md`, `MANIFEST.md`, `.gitignore`, `.gitattributes`, `requirements*`, this file. Building lineups is always permitted; ledger, inbox, engine, and contract surfaces need their role.
- Claims are live state in `claims/` (gitignored): `python tools/claim.py take <resource> --role <ROLE> --scope "..."`, `check`, `release <resource>`, `dirt --role <ROLE>`. Engine, ledger, and inbox are mutexes: a held claim stops you (read `owner.json`; never delete or take over another session's). The mutex is NOMINAL: a scoped `engine_<slug>` blocks nobody, so glob `claims/engine*` before writing and commit early (R31(d)). Slate claims are beacons (`--beacon`); never edit engine paths while one is lit, because builds re-import modules between steps. **In a cloud container the claim is CONTAINER-LOCAL and invisible to everyone else, so the pushed branch is the real mutex** — one session, one branch, one PR; `claim.py` says so on that host (R359).
- Git: `git add` by explicit path, never `-A` or `.`, and pass the same paths to `git commit`, because a pathless commit sweeps every session's staged files. While any claim you do not own is live: no checkout, reset, stash, restore, or clean. Foreign dirt inside your write set blocks and names the owner; elsewhere it is reported and left alone. Commit subjects are at most 100 characters and carry the R-numbers; the body carries the rest (R301).
- Shipping is the session's, end to end: branch, commit, push, open the PR, merge it once the `gate` check is green (Ben, 2026-09-17; R350, R353). Never commit to `main` directly and never force-push, because a force-push discards commits that may not be yours. A red gate is work, not a thing to merge past or to re-run hoping; `/ship` is this as a checklist.
- A DEV change is not shipped until CHANGELOG.md carries its entry, in the same commit, and "change" means the whole write set (docs, skills, this file): one entry per shipped change keyed to its R-number, newest first. A completed item's register entry MIGRATES from `docs/backlog.md` into the changelog and its `docs/ROADMAP.md` row reads Complete, in the completing commit. `audit.changelog_debt` warns at the next session start; the discipline is yours. An entry claiming a rule now lives in one place carries the grep that enumerates the class, with its hit list (R233).
- One writer per contended file: only ARCHIVE edits the ledger; only DEV edits the roadmap, the register and this file. Everyone else drops a fragment in `ledger/inbox/` or `docs/backlog_inbox/` (`<date>_<ROLE>_<slug>.md`, create-only); the owner merges and retires consumed fragments.
- Scratch goes in `tools/_scratch_<tag>/` (gitignored at any depth), never a bare file in `tools/`; sweep it when the slate closes.

## Session start
DEV in Claude Code: `/dev-session` runs this. Every role, every host:
1. `python tools/claim.py dirt --role <ROLE>`, then `git status --short` and `git log --format="%h %<(96,trunc)%s" -12`. Subjects carry the R-numbers; before touching an area a subject names, read that CHANGELOG entry. In Claude Code the SessionStart hook prints all of this.
2. `python tools/audit.py --run-tests --terse` must print `PASS  <version>  <N> modules  <N> tests` with nothing appended. The count is a PER-SUITE pin (`EXPECTED_SUITE_COUNTS` in `tools/audit.py`): `grew` is a stale pin; `shortfall`, `skipped_in_place`, and `absent` are lost coverage, never a reason to lower a pin. Bracketed warnings describe the HOST, not the tree (R348). A failing suite blocks. The audit fetches before measuring (`GH_PAT`; R146, R147) and names what stopped a fetch.
3. `python tools/solver_probe.py --date <date>` before any build. Exit 3 means the bank does not fit THIS HOST's call budget (`repo_env.call_budget_s()`, which the probe prints with its source): pass `time_budget_s` and accept a partial bank, or slice with `mlb_engine.optimize.bank_cache`. A BUILD session inside T-30 skips steps 2 and 3 (T-schedule).
4. Ledger Quick Card: `ledger/MLB_Classic_Calibration_Ledger.md` section 0 plus headers. The full read is post-slate work.

Never repair audit or test infrastructure during a live slate; if version or inventory checks fail while the suite passes, build and flag it.

## Hosts
Three hosts run this repo and `docs/hosts.md` is the table: how each is reached, call budget, whether `rm` works, where DK files arrive, how the deliverable leaves. **Ask `repo_env.host_profile()` for any number a program needs** (R349); do not restate one here.
- **A Claude Code cloud container is the default**, and runs DEV, BUILD or ARCHIVE. It is EPHEMERAL: everything uncommitted dies with the session and `outputs/`/`runs/` are gitignored, so push before you stop and hand the deliverable into the conversation (R354). `.claude/` carries the settings, hooks, path-scoped rules and the `/dev-session`, `/land` and `/ship` skills. The full gate runs in one call here (~230s measured 2026-09-19).
- **Claude Code on Ben's Windows machine runs DEV** (Ben, 2026-09-15). PowerShell, so prefer `python` entry points over bash idioms. Host facts go in `CLAUDE.local.md` (gitignored), never here.
- **Cowork is legacy**, kept because the mount still exists: no `rm` (`mv` into `_to_delete/`), and a lock CLASS to sweep before every git write (R109). Read `docs/cowork_sandbox.md` before the first bash call there.

## Sandbox
The per-call budget belongs to the HOST and is resolved by `repo_env.call_budget_s()`: ~630s in a cloud container, 130s on Cowork, and 130s for a host that states nothing — R271's number, now one profile's value rather than every caller's default. Do not re-derive it per call and never hardcode it (R349, R358). `docs/cowork_sandbox.md` is the legacy procedure.

## Showdown
Review-grade only; `run_slate` and `run_late_swap` do not apply. Three controls are enforced in the solver against the REALIZED set and relaxed only in the order overlap, player exposure, captain lock, thesis, each relaxation counted in the brief (R153): `max_shared_players` 4 of 6, `max_cpt_exposure_pct` 0.25, `max_player_exposure_pct` 0.50. Counts are `floor(pct * entries)`, clamped to 1 when `pct * n < 1`. A portfolio is clean when the relaxation counts are zero, not when the gates pass. Override all three through `--controls-override`.

## T-schedule (BUILD)
A ladder with actions, rewritten 2026-09-01 after a 23-minute window shipped nothing and made delivery-first 2026-09-22 (R386). T-30: skip the gate and the solver probe; they measure engineering health, not the file. T-20: skip every optional step. T-15: open every binding control AT ONCE, not stepwise (five careful steps cost more than one crude, reversible one). T-10: the best legal file is the deliverable; approve on posture defaults and auto-floors. T-6: hand-build if the engine has not produced a file, run the preflight, label it review-grade with its sha256. T-5: present the file with zero narration. Read the clock from the clock: print `TZ=America/New_York date` in the same call as every build, before every clock figure you state, and entering and leaving any phase that runs no build call (R318).

## Where things live
| Need | Read |
|---|---|
| What to build next | `docs/ROADMAP.md`, its **NEXT** line (the only queue); entry bodies in `docs/backlog.md` by `### R<num>` |
| What changed and why | `CHANGELOG.md`, newest first, by R-number |
| A DEV session, start to landing | `.claude/skills/dev-session/SKILL.md`, then `.claude/skills/land/SKILL.md` |
| Per-slate build, late swap, Showdown | `skills/generate-lineups/SKILL.md` and `references/` |
| Adversarial review of a portfolio | `python tools/qa_portfolio.py` (a report, never a gate) |
| Post-slate archival | `docs/cowork_archival_runbook.md` |
| Disk, container, GitHub sync; git locks | `docs/cowork_sync_protocol.md`, wrapping `python tools/sync_check.py` |
| Standings still to pull | `python tools/awaiting_standings.py scan` |
| Any tool's flags | `python tools/<tool>.py --help` |

## Compaction
When compacting, preserve: the role and the claim held, the R-numbers in flight and their files, the last gate line, and any instruction Ben gave this session. Keep them in `claims/<claim>/TASKS.md` as you go; the PreCompact hook re-injects it.

## Editing this file
Stay under 200 lines. A rule earns a line here only if removing it would cause a mistake in most sessions. A dated incident goes in the CHANGELOG entry it cites and leaves its R-number here. A procedure goes in a skill or `docs/`. A host fact goes in `CLAUDE.local.md`. A rule for one part of the tree goes in `.claude/rules/`. Scheduled tasks: none exist; ask Ben before creating one.
