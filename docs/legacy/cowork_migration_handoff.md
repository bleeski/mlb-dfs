> **RETIRED 2026-09-19 under R368, and moved here from `docs/`.** This file
> opened with a "Read order for the next session" and told it to run
> `pip install -r requirements.txt --break-system-packages` -- a command `.claude/settings.json` now DENIES, because the
> supported install is `python tools/env_probe.py --install --venv` against
> `requirements.lock` (R353). Its `.env` paragraph is false on the host that now
> runs most sessions: a cloud container is a fresh clone and `.env` is
> gitignored, so the key can only come from an environment variable
> (`docs/hosts.md`, Secrets). Its network section was measured on a Cowork
> device VM in July, and egress is now measured per session
> (`python tools/env_probe.py --egress`, R367).
>
> Kept unedited below as the record of the July 2026 migration. The current
> authorities are `CLAUDE.md`, `docs/hosts.md` and
> `skills/generate-lineups/SKILL.md`.

# MLB DFS — Cowork Migration Handoff

Last updated: 2026-07-17, later session. Supersedes the earlier 2026-07-17 end-of-session note on two points: network is now OPEN (was blocked), and a fresh sandbox needs `pip install` before the audit passes. Both are detailed below.

## Read order for the next session

1. CLAUDE.md, always, every session.
2. This file, in full.
3. mlb-cowork-migration-guide.html if Phase 1+ work needs the original 5-phase spec. It was uploaded to chat, not saved into the repo, so it will not be present in a new session unless Ben re-attaches it. (It carries the exact Phase 1 intake-wiring prompt that `tools/stage_slate.py` was built from.)

Nothing here overrides CLAUDE.md. Where the two conflict, CLAUDE.md wins.

## Sandbox prerequisite: install deps before trusting the audit

A fresh Cowork sandbox does NOT have the engine's dependencies installed, and pip installs do not persist between sessions. On a cold start `python tools/audit.py --run-tests --terse` reports `FAIL scipy.optimize.milp unavailable` — not a code regression, just a missing runtime. `scipy.optimize.milp` is the engine's only permitted solver (CLAUDE.md "Authority"), so the audit and the whole optimizer are dead until scipy is present.

First thing every session, before the session-start audit:

```
pip install -r requirements.txt --break-system-packages -q
```

That installs numpy, pandas, and scipy (the requirements floors). After it, `python tools/audit.py --run-tests --terse` prints `PASS v2.26.0 12 modules 119 tests` and `from scipy.optimize import milp` imports. Confirmed this session: scipy 1.15.3, numpy 2.2.6, pandas 2.3.3.

## Status: Phase 0 done and green (after the install above)

`tests/test_golden_replay.py` is the migration gate. It runs the real production front door (`run_slate`, `approve=False` then `approve=True`) against archived slate data, asserts all three certification gates, and asserts allocation diagnostics (entry-to-lineup assignments, exposure summary, SP-pair distribution) match a frozen baseline. It passes inside the 119-test suite once scipy is installed.

The gate is anchored on 2026-06-03, not the originally requested 2026-06-29. Do not re-litigate this:

- 2026-06-29's archive never had a salary CSV or DKEntries file, only mined JSONs and an ownership CSV. Nothing to replay.
- 2026-06-28 (`DKEntries_MLB_Classic_20260628_38lineups.csv`) has a real embedded player pool, confirming the fallback in `docs/cowork_archival_runbook.md` works. But every one of its 38 entries was already complete and submitted, so `run_initial_build` correctly refused all of them ("Entry ID X is already complete and immutable"). Right guardrail, wrong artifact type. The files are still on disk at `data/archive/2026-06-28/` (can't be deleted on this mount) but are dead weight, not inputs to anything.
- 2026-06-03 is a real, complete slate Ben supplied directly (salary CSV, DKEntries, contest standings), copied into `data/archive/2026-06-03/`. That's the live anchor. Baseline: `tests/golden/golden_replay_2026-06-03.json`.

Two test-only adaptations, not production changes:

- The test's own projection builder caps starting pitchers at the top 2 by salary per team before calling `run_slate`. `build_diverse_candidate_bank` enumerates every viable SP pair to guarantee coverage, which is O(n²) in distinct SP count — at full-field scale (40+ SPs) it blew past this sandbox's ~45-second single-call ceiling. Filtering SPs is a test fixture decision, not an engine change.
- The test calls `run_slate` with `requested_n=8` and a loosened `portfolio_controls_override` (`LOOSE_CONTROLS` in the test file). Both are documented, legitimate `run_slate` parameters, used here purely to keep runtime under the sandbox ceiling, not a change to production defaults.

Do not touch `tests/test_golden_replay.py` or `tests/golden/golden_replay_2026-06-03.json` casually. If a future engine change legitimately shifts the allocation, regenerate the baseline deliberately and say so, don't silently overwrite it.

## THE_ODDS_API_KEY: done

`.env` exists at the repo root with a real key (confirmed present a prior session, never printed to chat or logs — that's a hard CLAUDE.md rule, not just caution). `tools/fetch_slate_bundle.py` was edited to auto-load `.env` via a small stdlib-only loader (`_load_dotenv`), added because the script's own docstring requires it stay dependency-free. An explicit shell `export` still wins over the file if one is ever set. `requirements.txt` is unchanged, no python-dotenv added.

## Network is OPEN as of 2026-07-17 (this corrects the prior note)

The prior end-of-session note said all five engine data domains were blocked by the sandbox allowlist. That is no longer true. Re-tested this session: every domain the engine needs is reachable, no `X-Proxy-Error: blocked-by-allowlist` anywhere.

- statsapi.mlb.com → 200
- api.the-odds-api.com → 200
- baseballsavant.mlb.com → 200
- www.fangraphs.com → 200
- api.open-meteo.com → 400 (the origin server answering a bare no-params request — reachable, not a proxy block)

Confirmed against the live upstream, not just curl: `python tools/fetch_slate_bundle.py --date 2026-07-17 --skip-odds` pulled 15 games, 28/30 confirmed lineups, and 14 weather venues from statsapi.mlb.com and open-meteo with zero warnings. The allowlist that was blocking Phase 1 has been opened (Admin Settings → Capabilities, most likely). Re-test at the start of any session before trusting this, since it is an environment setting that could change again:

```
for host in statsapi.mlb.com api.the-odds-api.com api.open-meteo.com baseballsavant.mlb.com www.fangraphs.com; do
  echo "--- $host ---"
  curl -s -D - -o /dev/null --max-time 8 "https://$host" | grep -Ei "^HTTP|X-Proxy-Error"
done
```

## Git: still not possible from inside Cowork

No `.git` directory currently exists in the repo (`git status` returns "not a git repository", confirmed again this session). Earlier attempts at `git init` inside this sandbox corrupted `.git/config` and then failed to clean up (`rm -rf .git` hit "Operation not permitted" on every file), because the mounted workspace folder disallows delete/rename, which breaks git's lock-then-rename internals. Don't re-attempt `git init` from inside a Cowork session. Ben needs to run `git init` and the first commit himself, outside Cowork (regular terminal or Claude Code). `MANIFEST.md` documents the intended first commit message. Nothing this session is version-controlled yet, including the new `tools/stage_slate.py`.

## Phase 1: stage_slate.py built and verified (new this session)

`tools/stage_slate.py` exists and is the Phase 1 intake-wiring tool from the migration guide. Data source decision, made and acted on: the authoritative source is `tools/fetch_slate_bundle.py`, NOT the `mlb-lineups` / `mlb-game-odds` Cowork skills. Reasoning — the bundle already emits the exact shapes the engine's adapters consume unchanged (lineups feed shape for `build_status_map_from_lineups_feed`; the raw the-odds-api events payload for `parse_the_odds_api_totals`), covers weather too (the skills have no weather source), and hits the same upstream endpoints the skills would, so the skills offer no independent path, only a shape mismatch (`mlb-game-odds` returns pre-parsed per-book rows that `parse_the_odds_api_totals` does not accept).

What `stage_slate.py` does: given a date, it loads `slate_bundle.json`, the platoon JSON, the DKSalaries CSV, and the DKEntries CSV from `data/slates/<date>/` (CSVs content-sniffed, same discipline as the golden test), runs `build_slate_pool`, computes the deterministic F4 prior via `compute_f4_factors` over the pool's `team_by_player_id`/`opposing_probables`/`batter_hands` plus the Savant pitching frame, parses the odds packet, and assembles the exact `run_slate` kwargs (pool kwargs + `f4_by_player_id` + the Savant/FanGraphs enrichment CSV paths from `data/reference/`). CLI: `python tools/stage_slate.py --date <date> [--checkpoint] [--json] [--no-enrich]`. The odds packet is returned alongside the kwargs, not passed into `run_slate` — the current engine has no odds parameter (the odds gate is static; only the opt-in tail scanner consumes game environment).

Verification done this session (short of a live DK download, which only Ben can do): a lineups feed was reconstructed from the archived 2026-06-03 salary file's own names/teams, staged through the tool, and run through the real `run_slate(approve=False)`. Result on both the minimal and fully-enriched paths: `passed=True`, `status=plan_pending_approval`, no run directory created, pool of 40 (36 hitters + 4 arms across BAL/BOS/PHI/SD), F4 applied to all 36 hitters, odds packet parsed, Savant/FanGraphs enrichments applied with no zero-match raise. The remaining Phase 1 item (guide checkbox p1-live, "one real slate end to end") needs Ben to download a real same-date DKSalaries CSV and a blank DKEntries file into `data/slates/<date>/`, then run `fetch_slate_bundle.py` (with odds this time) into that folder and `stage_slate.py --checkpoint`.

## Phase 2: not started

`mcp__scheduled-tasks__list_scheduled_tasks` showed zero MLB DFS tasks last check (the only scheduled tasks belong to an unrelated golf project). Task A/B/C/D from the migration guide haven't been built.

## Environment bugs worth knowing before you rediscover them

- **Deps not preinstalled / don't persist**: see the "Sandbox prerequisite" section above. `pip install -r requirements.txt --break-system-packages` first, every session.
- **Bytecode cache**: this mount doesn't reliably update file mtimes, so Python's default timestamp-based `.pyc` invalidation can serve stale cached behavior after an edit. Force a hash-based recompile if a change doesn't seem to take: `python3 -c "import py_compile; py_compile.compile('path/to/file.py', doraise=True, invalidation_mode=py_compile.PycInvalidationMode.CHECKED_HASH)"`.
- **~180-second single-call ceiling on bash tool calls.** *(Corrected 2026-09-02, R271(b). This bullet read "~45-second" and "`timeout_ms` is capped at 45000; asking for more is rejected outright" from this document's writing until that date, and both halves are false: a request for 450000 ms is CAPPED rather than rejected and reports `Command timed out after 177999ms`, and calls of 150-165 s complete normally. The safe inner budget is 130 s and CLAUDE.md's `## Sandbox` section owns that number. The O(n²) note below was measured against the old figure and its conclusion is weaker than it reads.)* Backgrounded processes (`nohup`/`setsid`/`disown`) don't survive between bash tool calls either. Keep work inside a single call or shrink it to fit. Note `run_slate(approve=False)` does NOT build the candidate bank, so checkpoint-only staging is fast; the O(n²) SP-pair blowup only bites at `approve=True` on an unfiltered pool.
- **Write/Edit tool output on this mount has silently truncated or null-byte-filled content** on files under both the project folder and the outputs scratchpad, while the Read tool simultaneously showed the correct, complete content. Always verify anything nontrivial you just wrote with bash (`wc -l`, `python3 -m py_compile`, or `python3 -c "import ast; ast.parse(open(f).read())"`) immediately after writing it. `stage_slate.py` was written with Write this session and verified clean with py_compile + ast.parse. If a file gets bitten, rewrite it via `bash cat > file <<'EOF' ... EOF` heredoc instead.

## Next steps, in order

1. Ask Ben to run `git init` plus the first commit outside Cowork (see MANIFEST.md for the intended commit message), then commit `tools/stage_slate.py`. None of this session's work is version-controlled yet.
2. Close out Phase 1 with one real slate end to end (guide checkbox p1-live): Ben downloads a real DKSalaries CSV and a blank DKEntries file into `data/slates/<date>/`; run `fetch_slate_bundle.py` (with odds — ~3 credits) into that folder; run `stage_slate.py --date <date> --checkpoint`; review the checkpoint; `run_slate(approve=True)`; upload by hand; drop standings in the inbox that night.
3. Phase 2: stand up scheduled tasks for Task A/B/C/D per the migration guide.
4. Optional, needs Ben's explicit go-ahead first: run `field_miner --registry --emit-ledger` against `data/archive/2026-06-03/standings_191020573.csv` and follow the post-slate checklist in CLAUDE.md. This touches the ledger archive, so don't do it opportunistically.
5. Phases 3 (Showdown v3.0) and 4 (ownership model): not started, full detail is in the migration guide.
