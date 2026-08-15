# The one-call audit macro fits or does not fit depending on machine load, not on a fixed ceiling

**Corrected before filing, by the thing itself.** This note was first written
after three clean macro runs, claiming the Quick Card's "does not fit" was
stale. The fourth run, forty minutes later on the same tree, was killed at
178s. The correction is in "What actually decides it" below; the three
successful runs are still real and are left as measured.

Filed by DEV, 2026-08-15, claim `engine_2026-08-15_r114`, while landing
R114+R67. Quick Card item 1 only; nothing else in the ledger is touched by this.

## What the Quick Card says

Item 1 carries a 2026-08-13 correction reading, in part:

> Measured the same session: the single-line `--run-tests` macro does NOT fit
> this sandbox's per-call ceiling — it was killed twice at ~178s and once at
> ~935s in the background with no output — so the per-suite fallback in this
> very line is the path that produced the evidence, suite by suite, each at its
> pin.

The 2026-08-14 audit repeated the finding independently (`.audit/AUDIT.md`,
Verification levels: "the one-call macro exceeds the ~178s sandbox ceiling").

## What happened here

Three clean runs this session, from the repo root with `TMPDIR=/tmp` and
`PYTHONPATH=.pylibs`:

```
$ time python tools/audit.py --run-tests --terse
PASS  v2.26.0  26 modules  928 tests   [changelog debt warning]
real    1m23.975s          # baseline, before any edit

PASS  v2.26.0  26 modules  941 tests
real    1m15.974s          # after the R114+R67 tests landed

PASS  v2.26.0  26 modules  942 tests
real    1m17.7s            # final, at the committed pins
```

Per-suite, same session, for comparison: test_core 621 in ~36-39s,
test_showdown 55 in ~5s, test_upload_integrity 168->182 in ~10-12s,
test_golden_replay 9 in ~18s, test_paste_lineups 75 in ~3s. The suites sum to
about 75s of work and the macro's wall time matches that, so there is no
per-call ceiling being hit at all here: total runtime is ~80s against a tool
timeout that can be set to 560s.

## What actually decides it: machine load, measured both ways in one session

The fourth macro run, same tree, same flags, was killed at 178s. Re-running
per-suite immediately after gave the answer:

```
tests.test_core              Ran 621 in 93.2s      (was ~36-39s earlier)
tests.test_showdown          Ran  55 in 10.4s      (was ~4.6s)
tests.test_upload_integrity  Ran 182 in 34.8s      (was ~10-12s)
tests.test_golden_replay     Ran   9 in 28.8s      (was ~18.1s)
tests.test_paste_lineups     Ran  75 in 10.0s      (was ~3.2s)
```

The same work got about 2.4x slower over roughly forty minutes on an unchanged
tree. At the early rate the macro is ~80s and fits comfortably; at the late
rate it is ~190s and dies just past the ~178s mark the 2026-08-13 session
reported. So the 2026-08-13 measurement was not wrong and this session's first
three runs were not wrong either — the two disagree because the box was
differently loaded, and the suite total sits close enough to the ceiling that
load decides the outcome.

Two consequences worth writing down:

1. **The macro is worth trying first and is not worth relying on.** It is one
   call, it derives the total itself, and it prints the per-suite state word
   (`grew` / `shortfall` / `skipped_in_place` / `absent`) that item 1 tells the
   reader to check. The per-suite fallback is five calls and is where a session
   hand-reads counts and can talk itself into moving a pin, which is the exact
   failure item 1 exists to prevent. Try the macro; fall back when it dies.
2. **A macro kill is not a test failure and must not be read as one.** It exits
   with no verdict at all. The distinction matters at session start, where the
   instruction is to block on a failing suite: a killed macro means "run it
   per-suite", never "the gate is red".

Suggested edit for ARCHIVE, Quick Card item 1 only: keep the 2026-08-13
correction as written history, and append that on 2026-08-15 the same macro
succeeded three times in 76-84s and was then killed at 178s on the same tree,
with per-suite timings 2.4x slower in the same window — so the fallback is
load-conditional rather than standing, and a kill is not a red gate.
`.audit/AUDIT.md`'s Verification-levels line carries the absolute version of
the claim and is `.audit/`-owned, not ledger-owned; whoever next writes there
may want the same note.

## Also worth a line, unrelated to the macro

Item 1's pin line reads `901 tests`. `EXPECTED_SUITE_COUNTS` summed to 928
before this session and 942 after it, so the line was stale by its own stated
rule (the dict wins) across R70 and now R114+R67. `tools/audit.py`'s own
`EXPECTED_TEST_COUNT` comment had drifted the same way, from 901 against a
dict of 928, and was corrected in this commit.
