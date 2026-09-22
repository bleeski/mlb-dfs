# Late swap and repair ignore DK's posted 1-9 when no feed file exists

BUILD, 2026-09-22, slate 1905_10g, 19:04 ET. TB@NYY had just locked. Ben's
third DKSalaries pull (sha256 72342b4f92bc) carried a complete `Starting` 1-9
for all 20 sides. Every data host was egress-blocked, so no
`lineups_feed.json` existed. Five delivered slots were benched: Brett Baty
(NYM) in 3 entries and Alan Roden (MIN) in 2.

## 1. `late_swap.py` exits 4 on a missing feed file

`late_swap.py --salary <third pull> --entry-ids <5 ids>` exited 4 with
`missing input: data/slates/2026-09-22/lineups_feed.json` before doing
anything. CLAUDE.md ranks a complete DK `Starting` 1-9 ABOVE any feed (R143),
and `build_slate_pool` merges it through `merge_dk_starting_into_feed`. The
swap door should accept "no feed, DK covers every side" the way
`build_slate.py` does (`dk_order_coverage`, "no paste and no API call were
needed"), not demand a file for a fact the salary CSV already holds.

## 2. `repair_entry.py` counts every candidate `not_confirmed` without `--feed`

With the same salary file, `repair_entry.py --dead 44222929 --dead 44222933
--mode repair --dry-run` returned NO LEGAL REPLACEMENT for all five entries.
Every otherwise-legal candidate landed in `not_confirmed` (23 to 63 per slot).
The tool also printed `lock: no feed supplied; no team treated as locked` one
minute after TB@NYY started. `preflight_upload.py` on the same file already
synthesizes the feed ("synthesized from the salary file's Starting column").
The repair tool should take confirmation from the same synthesized feed, and
its lock derivation should fall back to the salary file's Game Info the way
`verify_export.py` does ("lock clock ... via salary Game Info").

## 3. Two run-less deliveries on one slate share one record file

`record_name(slate_tag, None)` yields `<tag>_norun.json`. The 18:23 repair
(sha256 bb9637e3b547) and the 19:05 hand late swap (sha256 a65077667789) both
wrote `data/deliveries/2026-09-22/1905_10g_norun.json`, so the second
overwrote the first in the working tree. The earlier record survives only
because it was already committed (7d34869). Fix: key run-less records on
UTC or on the sha256 prefix, the way refusal records are keyed.

## What was delivered

A hand repair under R272. Each replacement was the top build-`Base` legal
candidate: slot-eligible, in its team's posted 1-9, active, a 21:40+ ET game,
within freed salary, and not facing a rostered SP. Baty -> Ryan Kreidler
(44222927) x3, Roden -> Victor Bericoto (44222910) x1, and Roden -> Taylor
Trammell (44222914) x1. No other slot moved. `verify_export --parent` exit 0.
`preflight_upload` exit 2 without `--parent` (34 unchanged TB@NYY slots read
as started) and exit 0 with `--parent`.
