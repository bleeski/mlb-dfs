> **RETIRED 2026-09-19 under R368**, moved here from the repo root. It
> describes the July 2026 Cowork migration seed: a v2.26.0 tree pinned at 119
> tests, told to be opened "in Cowork". Both facts are two migrations old. Kept
> unedited as the record of that restructure.

# MANIFEST - Cowork Migration Seed (restructured)

Seeded 2026-07-16 from the claude.ai project at engine v2.26.0. Unlike
the flat seed, this zip has the Phase 0 package restructure EXECUTED and
VERIFIED. Layout v3.0.0-pre, engine behavior unchanged, every module
VERSION constant intact.

Verification run against this exact tree before zipping:
`python tools/audit.py --run-tests --terse` ->
PASS  v2.26.0  12 modules  119 tests
plus field_miner --selftest PASS and posture_allocator --selftest PASS
under their new `python -m` invocations.

Getting started: unzip, `git init`, commit as
"v3.0.0-pre: package restructure, checksum manifest retired", open the
folder in Cowork. Phase 0's remaining item is the golden replay test
(see Still open, below), then Phase 1 per the migration guide.

Excluded from the old project: ownership_rows_20260629.csv, the
pre-grain-fix A-001 export (112 rows, pos_ledger column).
ownership_rows_2026-06-29.csv (132 rows, drafted_positions) is canonical
per ledger 3.7 and is included in the archive.

## What the restructure did

1. Moved 15 engine modules into mlb_engine/ subpackages and rewrote 64
   cross-module import lines to package-qualified form. No function
   bodies changed.
2. Moved test_core.py to tests/test_core.py with the same import
   rewrite. The suite stays one file; splitting per module is optional
   cleanup, not a gate.
3. Moved all 8 CSVs to data/reference/ and patched the three
   root-relative path surfaces: the park-factor and weather paths in
   two tests, the --venues default in tools/fetch_slate_bundle.py, and
   posture_allocator's archetypes-CSV search order (data/reference
   first, then cwd, then beside the module).
4. Ported project_audit.py to tools/audit.py: kept version-coherence,
   CSV schema, venue-factor join, compile-all, scipy.milp, and the
   full-suite run pinned to 119 tests. Retired the SHA-256 checksum
   manifest, the manifest txt, and the 26-file cap. Git history is
   provenance now. The retired originals live in docs/legacy/.

## Layout

| Path | Contents |
| --- | --- |
| CLAUDE.md | standing instructions (new; session-start macro updated) |
| MLB_Classic.md | strategy authority |
| requirements.txt | dependency floors (upper bounds still open per backlog B-4) |
| mlb_engine/intake/ | slate_intake_manager v1.7, live_data_adapters v1.2, platoon_order_adapter v1.0 |
| mlb_engine/projections/ | projection_builder v1.4, xwoba_base_correction v1.2 |
| mlb_engine/optimize/ | optimizer_v3 v3.18, tail_candidate_scanner v1.0; roster_contracts lands here in Phase 3 |
| mlb_engine/allocate/ | contest_allocator v1.10, posture_allocator v0.1-review |
| mlb_engine/entries/ | dk_entries_manager v1.6 |
| mlb_engine/swap/ | late_swap_manager v1.3 |
| mlb_engine/pipeline/ | execution_pipeline v1.9, build_state_manager v1.3 |
| mlb_engine/field/ | field_miner v0.3-review, ownership_prior v0.1-prior |
| tools/ | fetch_slate_bundle.py (--venues default updated), audit.py v3.0; stage_slate.py lands here in Phase 1 |
| tests/ | test_core.py (119 tests), fixtures/, golden/ |
| data/reference/ | 5 structural CSVs + both Savant CSVs + statsapi_season_pitching.csv (R278: was fangraphs_season_pitching.csv, a manual export; all three rate files are fetched now) |
| data/archive/2026-06-29/ | 3 mined JSONs + canonical ownership CSV (A-001) |
| data/slates/, data/standings/inbox/, data/odds_history/, data/order_history/ | scaffold for the per-slate loop and Tasks A/B |
| ledger/ | calibration ledger + field_opponent_registry.json |
| docs/ | integration contract, backlog, archival runbook |
| docs/legacy/ | v2.26.0 system prompt, manifest txt, checksums json (all retired) |
| runs/, outputs/ | gitignored working directories |

## Invocation changes to know

| Old | New |
| --- | --- |
| python project_audit.py --run-tests --terse | python tools/audit.py --run-tests --terse |
| expected macro output: PASS v2.26.0 24 files 119 tests | PASS  v2.26.0  12 modules  119 tests |
| python test_core.py | python -m unittest tests.test_core |
| python field_miner.py ... | python -m mlb_engine.field.field_miner ... |
| python posture_allocator.py ... | python -m mlb_engine.allocate.posture_allocator ... |
| python fetch_slate_bundle.py | python tools/fetch_slate_bundle.py |
| import optimizer_v3 | from mlb_engine.optimize import optimizer_v3 |

Run everything from the repo root so data/reference/ paths and package
imports resolve.

## Still open (deliberately)

1. tests/test_golden_replay.py. The guide's golden prompt needs the
   2026-06-29 DKSalaries CSV and DKEntries file, which live in your
   local Cowork archive tree, not in the old claude.ai project. Copy
   them into data/archive/2026-06-29/ and run the prompt; the first run
   freezes the baseline into tests/golden/.
2. tools/stage_slate.py (Phase 1 wiring prompt).
3. mlb_engine/optimize/roster_contracts.py (Phase 3 Showdown).
4. expected_stats_batting.csv ships with the old too-high PA threshold;
   the first Task C run re-pulls at minimum PA 25.
5. Optional: split tests/test_core.py per module; pin requirements
   upper bounds (backlog B-4).
