# 2026-10-13 DEV (Session 171, R503): on Classic, a feed probable silently outranks the arm DK's `Starting` column flags SP

**Observed.** `merge_dk_starting_into_feed`'s `_attach_probable` (`mlb_engine/intake/live_data_adapters.py`, in the merge) writes DK's declared arm into a side only `if probables.get(team) and not side.get("probable_pitcher")`. When the feed already names a different probable, the merged side keeps the feed's. `build_status_map_from_lineups_feed` then crosswalks that one name into `probable_pitcher_ids`, and `build_slate_pool` takes those ids as the side's pitchers (`probable_ids = list(status["probable_pitcher_ids"])`, then "Pitchers: probables plus explicit declarations"). DK's SP-flagged arm is therefore not in the Classic pool at all, and the pool report does not name him.

**Reproduced at 152c10d.** The vendored `data/archive/2026-06-03/DKSalaries_2026-06-03.csv` was given a `Starting` column with `SP` on BAL's Shane Baz (43206008). A feed for the same game named Dean Kremer (43206009) as BAL's probable.
- `build_slate_pool` gives `pitcher_roles` = `{'43206009': 'declared_probable_sp'}` for BAL; Baz is absent.
- `json.dumps(pool_report)` contains neither "Shane Baz" nor "43206008".

The script was a scratchpad file (`classic_probable.py`), not kept in the repo. It is about 40 lines: the archive file plus one `Starting` cell, a one-game feed dated to the salary file's start, and `build_slate_pool(..., stale_platoon_policy="warn")`. The same precedence was seen on the merge alone, on the Showdown fixture's UTIL rows: DK flags Taj Bradley, the feed names Joe Ryan, and the merged probable and the status map's id are both Ryan's.

**Why it matters.** CLAUDE.md's build contract says disagreements between lineup sources are NAMED in the pool report and never silently resolved. Here one is resolved silently, in the feed's favour.

Since R503(b) (Session 171), the Showdown melt resolves the same disagreement the other way: DK's arm stays the declaration, and the feed's probable is named in `feed_orders.arm_disagreements`. The two doors now disagree about which source wins on the arm.

Unchecked: whether `skills/generate-lineups/scripts/build_slate.py`'s pitcher audit (`slate_intake_manager.audit_pitcher_pool`, a review gate) flags the dropped arm at the script door.

**Why filed, not fixed.** R503 is the Showdown feed lift. Which source wins on a Classic probable is a precedence rule (R143 ranks sources for batting ORDERS; `dk_declared_probables` and the merge set the arm rule), and the build contract names it Ben's to state. The fix touches the Classic front door.

**Candidate item.** First a decision for Ben: does DK's `Starting=SP` outrank a feed probable on Classic, as it now does on Showdown? Either way, the disagreement gets named in the pool report, beside `dk_order_report.disagreements`.
- If DK wins: `_attach_probable` (or the status map) prefers DK's declared arm, and the feed's arm leaves the pool unless declared.
- If the feed wins: keep today's behaviour, name it, and decide whether the Showdown melt should follow.

Test: the reproduction above, as a `test_core` class. Effort S; it touches the Classic pool path, so `GOLD` is checked, though the golden slate carries no `Starting` column.

Nothing here is a lift, an edge, an ROI or a win rate.
