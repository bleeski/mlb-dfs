# DEV fragment, 2026-10-10: a gate test pins Python's float `sum()` order-dependence, which 3.12 removed

**Found by** Session 129 (R319 + R429), measuring the baseline: on a clean `705650b` in a Claude Code cloud container (Python 3.13.16), `python tools/audit.py --run-tests --terse` printed `FAIL  test suite FAILED in tests.test_core (ran 3558); do not build`. CI pins Python 3.11 (`.github/workflows`), so the `gate` check is green and the local gate is not.

**What.** `tests.test_core.ReplaySlateTests.test_settle_scores_requires_integer_hundredths_so_ties_are_exact` (`tests/test_core.py:37938`) asserts `sum([16.0, 2.0, 7.0, 4.0, 18.0, 16.0, 18.7, 28.0, 29.9, 16.0]) != sum([16.0, 29.9, 28.0, 18.7, 16.0, 18.0, 4.0, 7.0, 2.0, 16.0])` to show float tie scores depend on summation order. Python 3.12 made `sum()` of floats compensated, so on 3.12 and later the two agree (`155.6 == 155.6`) and the assertion fails. The code under test is not wrong; the test measures the interpreter.

**Verify.** `python -c "print(sum([16.0, 2.0, 7.0, 4.0, 18.0, 16.0, 18.7, 28.0, 29.9, 16.0]) == sum([16.0, 29.9, 28.0, 18.7, 16.0, 18.0, 4.0, 7.0, 2.0, 16.0]))"` prints `True` on 3.13.16.

**Fix.** Accumulate with an explicit left fold (`functools.reduce(operator.add, xs)`), which is order-dependent on every Python, or pin a pair whose order-dependence survives compensated summation. Separately, `docs/hosts.md` records the cloud container's gate as passing in 4m45s (measured 2026-09-23); the container's Python has since moved past the CI pin, so either hold the container to 3.11 or add the interpreter to the `host_profile` facts, or every cloud DEV session starts on a red local gate and reads it as the tree's.

**Why it matters.** CLAUDE.md says a failing suite blocks. A session that cannot tell a host failure from a tree failure either stops on a false red or learns to ignore the line.
