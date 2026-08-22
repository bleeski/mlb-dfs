# Showdown never merges confirmed batting order from --lineups; two downstream breaks

Raised by a BUILD session, slate 2026-08-22 tag `1335_1g_sd` (TOR @ NYY
Showdown, 19 entries across 7 contests). Create-only fragment; the owning
role merges and deletes it.

## 1. `melt_showdown_salary_csv` has no equivalent of R143's `merge_dk_starting_into_feed`

`Pool_Basis` and `Batting_Order` (`mlb_engine/optimize/showdown.py` ~line
160-209) are derived ONLY from the DK salary file's own `Starting` column.
On this slate DK had flagged both probable pitchers (`Dylan Cease` -> `P`,
`Ryan Weathers` -> `SP`) but left `Starting` blank for all 18 hitters, even
though mlb.com had a full confirmed 1-9 for both sides (Ben pasted it, and
`tools/lineups_from_paste.py` resolved all 18 names cleanly against this
draftgroup's IDs). Contrast with the 2026-08-19 ARI@BOS Showdown slate
(`2026-08-19_BUILD_showdown-feed-abbrev-and-ownership-pred.md`), where DK's
own file *did* carry 1-9 for both sides -- so this is DK-file-dependent, not
universal, and a build can't assume either shape.

Effect: `declared` in `melt_showdown_salary_csv` contained only the two
pitcher rows, so `basis` still read `declared_starters` (misleadingly) but
`Batting_Order.notna().sum()` was 0. `run_showdown`'s
`use_ladder = (basis == "declared_starters" and posted >= 18)`
(`skills/generate-lineups/scripts/build_slate.py` ~line 2226) evaluated
False despite a perfectly good `--lineups` feed sitting right there --
`showdown_handedness` reads that feed for `bat_side`/`pitcher_hand` only, it
never touches `Batting_Order` or `Pool_Basis`.

## 2. The `build_showdown_bank` fallback then hit a hard ceiling, not a slow build

Losing the ladder path routed to `sd.build_showdown_bank`, which returned
`{"status": "bank_short", "built": 11, "needed": 19}` identically across two
attempts (14s and then 18s `--max-seconds`, no change in `built`). That
smells structural rather than search-effort-bounded -- worth someone with
`build_showdown_bank` context checking whether it has its own version of
the ceiling `2026-08-19_BUILD_pitchhand-missing-and-bank-solve-ceiling.md`
describes for the joint MILP, since "grow the bank" (the standing autonomy
default remedy) did nothing here.

## Workaround used to ship this slate

Wrote a derived copy of the salary file,
`data/slates/2026-08-22/DKSalaries_tornyy_sd_confirmed.csv`: for each of the
18 hitters in the resolved `--lineups` feed, matched by (Name, TeamAbbrev)
against the ORIGINAL uploaded salary file, set the `Starting` field on both
that player's CPT and UTIL rows to his batting-order digit (1-9). Pitcher
rows and every non-confirmed/reserve row were left untouched -- no salary,
ID, or eligibility field was touched, only the one column DK would have
populated itself had it posted order into `Starting`. Rebuilt against that
file: `Pool_Basis=declared_starters`, `posted_hitters=18`, `use_ladder=True`,
thesis ladder solved clean (0 relaxations on all three portfolio controls).

Suggested fix: give Showdown a per-side merge analogous to R143 -- inside
`melt_showdown_salary_csv` or just before the `use_ladder` decision in
`run_showdown`, backfill `Batting_Order` for a side from `--lineups` when DK's
own `Starting` column leaves that side's hitters blank but the feed has a
confirmed 1-9. Ranking stays DK-first (only fill what DK left empty), same
as R143's per-side rule for Classic.

## 3. `preflight_upload.py`'s `--salary`/`--brief` auto-resolve assumes a `runs/` promotion Showdown never does

Showdown doesn't go through `run_slate`, so it never writes a `runs/<run_id>/`
directory or touches `runs/latest_valid_run.json`. Running
`preflight_upload.py --entries <delivered>` with no other flags on this
delivery auto-resolved `--salary` to `runs/latest_valid_run.json`'s target,
which was a DIFFERENT concurrent session's Classic run
(`runs/20260822T165256Z_0289fc17`, sandbox `relaxed-compassionate-goodall`,
promoted ~20 minutes before this build even started). Result: `FAIL embedded
player pool overlaps the salary file at 0.0%` and 26 "absent from salary
file" IDs -- a false failure on a genuinely clean file. Passing `--salary`
(the slate-dir salary snapshot) and `--feed` explicitly fixed it;
`--brief outputs/<date>/build_brief_showdown_<tag>.json` also had to be named
by hand since nothing pointed at it either. Worth teaching the auto-resolve
that a `showdown_module_version` delivery should look for its own staged
inputs in `data/slates/<date>/` rather than (or before) `runs/`.
