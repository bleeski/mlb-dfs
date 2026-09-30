# Miner truth landed (R341, R225, R226, R227): what an ARCHIVE re-mine backfills

DEV, 2026-09-30 ET. For ARCHIVE. The miner's code changed; nothing under `data/archive/`
or `data/standings/` was touched. The full reasoning is the CHANGELOG entry
"R341 + R225 + R226 + R227(a)" (roadmap Session 42).

**What the mine writes from now on.**
- `rostered_by_norm`: percent of COMPLETE lineups rostering each player, counted over the entries. DK's column is no longer what ownership means: DK drops one of a player's two slot rows when the slots tie, leaving exactly half (309 of 309 short rows in the 610 standings). `pct_rostered` sits beside `pct_drafted` on `top_owned`, `captain_table` and `winner_captain`.
- `diagnostics.dk_understated_players`, `dk_overstated_max_pts`, `ownership_parse_suspect`, `rostered_denominator`, `rostered_entries_excluded`. Runbook step 7 now reads: DK below the recompute is expected; DK ABOVE it by more than 0.1 point is a structural gate (exit 3, nothing written; 0.01 is the largest excess over the 614 archived files). `ownership_recompute_ok False` alone no longer blocks archiving (it reads False on 120 of 614 contests with a correct parse).
- `meta.winner_state` (`OBSERVED`, `TIED`, `UNKNOWN_NO_RANK_ONE`) and `meta.winner_rank1_rows`. No stored number moves (610 standings: 563 OBSERVED, 47 TIED, 0 differ from the old pick).
- `construction.primary_stack_team_share` on a mine with a salary join.

**What only a re-mine (or a read-time recompute) backfills.**
1. The 91 Showdown JSONs mined 2026-07-17 to 08-06 (version 0.5-review) carry no `captain_norm`. Their stored `duplication` block is person-set, which overstates. All 91 have a standings CSV in the archive; re-mining them stores captain-aware counts.
2. The stored `duplication` blocks of 83 pre-R338 files are captain-blind: 22 captain-bearing JSONs (derivable from `entries[]`) and 61 of the 91 above (need the CSV). Ledger 3.17's Showdown duplication rows (27.2% median duplicated, winner duplicated 40%, own 27 of 109) carry R225's caveat until the recount lands.
3. `rostered_by_norm` is derivable on read (`field_miner.rostered_by_player_norm(entries)`); a re-mine only stores it. `primary_stack_team_share` is NOT derivable from the archive (`primary_stack_team` is in 0 of 614 archived entries, `player_table` has no team): it needs a re-mine with a salary file.

**Ledger prose that still carries the old reading** (ARCHIVE edits in place): section 3.7's "ownership recompute within 1.5 points of `%Drafted`; if it fails the parse is wrong" (the runbook no longer says it); the ownership and winner-captain medians in 3.17 and 3.18 (`tools/qa_portfolio.py:634-641,969` quote them as prose constants) were computed on DK's column and move when re-derived on `rostered_by_norm`.

**Follow-ups for ARCHIVE.** (1) `tools/rebuild_registry.py` after the re-mine: `data/reference/field_opponent_registry.json` holds 610 folded contests whose `dup_entries` were computed on the person set for every Showdown contest, and new fold-ins are captain-aware, so the registry mixes two bases until it is rebuilt. (2) `ownership_grade_archive` grades from before 2026-09-30 were scored against DK's column on DK's all-entries denominator; new grades use the entry block over complete lineups, so they are not comparable: re-run, do not splice. (3) A malformed `field_opponent_registry.json` now refuses the fold-in (NOTICE, the mine continues) and is left in place; `contest_library.load_registry` alone quarantines (`*.corrupt-*`, gitignored).

**Hygiene found.** `mined_192464820.json` is archived twice (2026-07-18 at 0.5-review, 2026-07-19 at 0.4-review; the CSV is under 07-19 only). Four mined JSONs carry no `contest_type` (0.3/0.4-review Classic).
