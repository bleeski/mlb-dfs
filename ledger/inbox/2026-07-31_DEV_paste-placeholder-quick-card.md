# 2026-07-31 DEV fragment: Quick Card lines for R32 round 2

For ARCHIVE to merge into section 0 and then delete this file.

## 1. Quick Card item 1 is carrying a stale pin, and it is the number I was briefed with

Section 0 item 1 says the macro prints `PASS  v2.26.0  25 modules  546 tests`
and lists `tests.test_core` at 359. Neither is current and neither was current
when it was written for this session's brief. Measured 2026-07-31, all five
suites run individually and green:

| suite | count |
|---|---|
| `tests.test_core` | 375 |
| `tests.test_showdown` | 49 |
| `tests.test_upload_integrity` | 100 |
| `tests.test_golden_replay` | 9 |
| `tests.test_paste_lineups` | 56 |
| **total** | **589** |

`tools/audit.py` and `CLAUDE.md` both said 556 before this session and both are
now re-pinned to 589. The Quick Card was the only surface still on 546/359: it
missed R34's ten `PrimaryStackSizeFloorTests` and now this session's 33. Since
the Quick Card is the mandated session-start read, a stale count there is the
one that actually reaches a session.

Suggested replacement for the count clause: **589 (375 + 49 + 100 + 9 + 56)**.

This number moved twice within the session that wrote this fragment, 583 then
589, which is the argument for merging it promptly rather than sitting on it.

The sandbox caveat in that item is still accurate and worth keeping, with one
correction: `test_core` alone no longer reliably fits a 45s call either. Split it
by test class into roughly four groups, or accept that the single-suite run is
near the wall.

## 2. A new Quick Card line worth adding to the paste entry

Paste the mlb.com page AS IT COMES, including the games nobody has posted. An
unposted side renders `1. TBD` and an unannounced probable renders a bare `TBD`.
Both are POSITIONAL FACTS: they hold the empty slot so the block count matches
the header count and each lineup goes to the side that posted it. Trimming them
is what makes a half-posted game ambiguous, and the tool now refuses that game
rather than guessing at it.

Before 2026-07-31 it did guess, and it guessed wrong: the posted nine went to
`headers[0]`, the away side. On the 1910_6g slate that put CIN's nine on PIT and
SD's nine on SF. Nothing was uploaded, because all nine names then missed the
other team's roster and both sides ended `tbd`. That is a crosswalk accident,
not a designed safeguard.

## 3. One invariant candidate, ARCHIVE's call

Section 3 collects the parsing traps that have already cost something. This is
one, and it is the same trap as the paired-header trap already recorded there,
reached by a different route:

> A placeholder in a positional sequence is information and must occupy its
> slot. Dropping it does not produce a gap; it produces a SHIFT, and a shift in
> an away-then-home sequence is a wrong-team assignment that passes every gate.

It has now happened twice in the same module, once for lineup blocks and once
for probable pitchers, which is the argument for recording it as a trap rather
than as two fixes.
