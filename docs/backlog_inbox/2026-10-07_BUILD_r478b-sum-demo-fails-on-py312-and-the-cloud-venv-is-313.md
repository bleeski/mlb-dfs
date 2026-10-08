# 2026-10-07 BUILD: rider for R478(b): the `sum()` demonstration fails DETERMINISTICALLY on Python 3.12+, and this cloud container's `.venv` is 3.13

**Observed.** `ReplaySlateTests.test_settle_scores_requires_integer_hundredths_so_ties_are_exact` (`tests/test_core.py` ~L37423) fails with `AssertionError: 155.6 == 155.6` on this container's `.venv` (Python 3.13.16) and passes under a Python 3.11.17 venv built from the same `requirements.lock` (2242 run, 4 skipped, OK). CI pins `python-version: '3.11'`, so CI stays green.

**Mechanism.** R478(b) files this assertion as one that "does not hold reliably". It is version-dependent: since Python 3.12, `sum()` of floats uses compensated (Neumaier) summation, so the two term orders the test sums agree on 3.12 and later and differ on 3.11. `env_probe.SUPPORTED_CP_TAGS` is `("cp310", "cp311", "cp313")`, so a cp313 session venv is a supported state, and on it `python tools/audit.py --run-tests --terse` (CLAUDE.md session start step 2) prints FAIL for a reason unrelated to the tree.

**Candidate (for R478(b), not a new item).** Demonstrate the hazard with an explicit left fold (`functools.reduce(operator.add, xs, 0.0)`) instead of `sum()`, which keeps 3.11 semantics on every version, or drop the incidental demonstration and keep the integer-refusal assertion that does the work. Verify on cp311 and cp313.

Nothing here is a lift, an edge, an ROI or a win rate.
