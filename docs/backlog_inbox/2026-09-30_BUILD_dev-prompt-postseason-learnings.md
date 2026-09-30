# DEV session prompt: postseason 1400_4g learnings (BUILD, 2026-09-30)

Paste into a DEV session after `/dev-session`.

Context: BUILD session 2026-09-29 (slate 1400_4g, postseason Wild Card G1, 4 staggered games, 9 entries across
Opener 196052739 and Pocket 195970831). 0 of 9 cashed. Read these first, in full:
- ledger/inbox/2026-09-30_BUILD_1400_4g_postseason_opener_retro.md (outcomes, counterfactuals, chalk-core proposal)
- docs/backlog_inbox/2026-09-29_BUILD_late-swap-drops-declared-arms.md
- docs/backlog_inbox/2026-09-29_BUILD_po-token-on-named-starter.md
- data/deliveries/2026-09-29/*.json (refusal and delivery records)
Merge the backlog fragments into docs/backlog.md as register entries (next free R-numbers) and put them on
docs/ROADMAP.md, then implement in this order. Each item: failing test first, then fix, CHANGELOG entry in the
same commit, suite pins updated only for `grew`. Run dfs-premise on each entry before building it.

1. late_swap.py carries declared pitchers (the blocker).
   tools/late_swap.py has no --declare-pitcher, so intake drops declared PLR/bulk arms. Entries with a locked
   declared arm got "+0 targeted candidates" and the joint MILP went infeasible for every entry (3 refusals at
   16:03 ET). Add --declare-pitcher (same grammar as build_slate.py's parse_declared_pitchers) and DEFAULT it
   to the parent run's brief `declared_pitchers`, resolving the parent the way R268(a) inherits controls. Test:
   a parent with a declared arm locked in one entry swaps the other entries and certifies.

2. Chalk-core seat per contest (Ben's rule, 2026-09-30).
   Every Classic contest with >=2 entries seats at least one lineup on the projection's consensus SP pair
   (top two arms by projection among rostered-legal SPs), differentiated through its bats. New control,
   e.g. `min_consensus_pair_entries_per_contest`: default 1 on large_gpp / wta_satellite / small_gpp / mme,
   0 on single_entry and cash; typed through the units gate; recorded in the brief's exposure block.
   It must survive max_pitcher_exposure_pct, max_sp_pair_repetition and the distinct-pair behavior (floor those
   caps up to admit the seat, named in feasibility.checks, never silently). Sleeves: seat it in `projection`.
   late_swap: never remove the last consensus-pair entry in a contest (refuse, name the entry, allow
   --accept-downgrade to override). On 1400_4g the Opener had zero Sale+Schlittler entries.

3. Bulk/opener arm workload.
   Declared viable_bulk_or_alt_sp arms are projected off season APPG (Imai's included starter games). Four P slots
   on PLR arms scored 0. Scale a declared bulk arm's Base/Ceiling by an expected-IP factor (default well under a
   starter's; a named constant with a comment citing this slate), overridable per arm via
   --declare-pitcher ID=role:ip=N. The brief lists each declared arm with the factor applied.

4. Guard on overriding DK's PO tag.
   --declare-pitcher on an arm whose DK Starting is PO must carry an evidence note
   (--declare-pitcher ID=declared_probable_sp:evidence="..."). Without one, refuse at exit 4 (cli_value_invalid),
   naming the arm and suggesting the K-prop check. Luzardo was PO, and the override was wrong (K line 2.5).

5. Standings reader for late-swap decisions.
   New tools/standings_read.py reads DK contest-standings CSVs/zips for our entry IDs (from data/deliveries).
   Per entry it prints rank, points, TimeRemaining and open slots. Per contest it prints #1, #10, #100 and the
   cash line (from data/reference/dk_contest_paid_places.json or a --paid-places arg), %Drafted of started
   players, and the hidden-slot inference: for leaders whose only hidden slot is P, the max-salary arm their
   remaining cap allows. Add a per-entry verdict column (`live_for_target`, `cash_viable` or `out`) using
   remaining-slot ceilings from the parent run's projections.csv. Rule the tool prints and late_swap enforces:
   a swap that LOWERS an entry's projection is refused unless that entry is `live_for_target` (override with
   --accept-downgrade). On 1400_4g two hand swaps (Schlittler->Tolle, Rice->Rutschman) turned two cashing
   entries into non-cashing ones.

6. Manifest bookkeeping bugs found live.
   a. tools/promote_run.py inherited `review_grade_uncertified` from a later manifest row sharing the run_id
      when re-promoting a certified run. Take certification from the run's own record (runs/<id>/manifest.json),
      not the latest manifest row.
   b. upload_manifest.record_delivery with refinement=True and the parent's run_id overwrote the parent's
      data/deliveries/<date>/<tag>_<run_id>.json mirror (the certified record). Key the mirror so a refinement
      writes its own file (e.g. suffix the sha256 prefix) and never rewrites the parent's.

7. odds_from_paste.py: WARN when a book label is not a known sportsbook key (e.g. `websearch_src1`), and record
   `book_attributed: false` in the packet so the brief can show F1 came from unattributed prices.

Constraints: CLAUDE.md is binding. No scripted DK access. Truthful labels (no ROI, win rate or probability).
Determinism (stable_union, PYTHONHASHSEED=0). Never trim the legal pool: items 2 and 3 are controls and
projections, not exclusions. The gate must print PASS with nothing appended before /land and /ship.
