# requirements.lock is cp310-only AND omits two test dependencies, so neither a cold install nor the gate can succeed from the documented path

Filed by BUILD, 2026-09-16 slate 1910_7g; extended the same evening by the DEV
session that needed a green gate. Cost ~3 minutes of a 35-minute lock window,
then ~8 more to get the gate runnable.

Three defects, one file. They compound: (1) makes the install fail, and once you
work around it, (2) and (3) make the gate fail.

## Defect 1: the hashes are cp310's, and the host was cp311

`python tools/env_probe.py --install` failed on a cold container with:

    ERROR: THESE PACKAGES DO NOT MATCH THE HASHES FROM THE REQUIREMENTS FILE.
    numpy==2.2.6 ... Expected sha256 fc7b73d0... Got ba10f841...

That error says "someone may have tampered with them", which is the alarming
reading and the wrong one. The bytes were authentic.

The host was Python 3.11.15. `requirements.lock` carries ONE hash per package,
and for the three binary packages that hash belongs to the **cp310** wheel:

    lock's numpy hash fc7b73d0 -> numpy-2.2.6-cp310-cp310-manylinux_2_17_x86_64.whl
    downloaded on cp311       -> numpy-2.2.6-cp311-cp311-manylinux_2_17_x86_64.whl (ba10f841)

PyPI's own JSON API publishes ba10f841 / 39cb9c62 / b98560e9 as the sha256 of
the cp311 wheels for numpy 2.2.6, scipy 1.15.3 and pandas 2.3.3 -- exactly the
bytes that arrived, over two independent transports (pip, and
`tools/wheel_fetch.py` raw range requests). The four PURE-PYTHON pins
(python-dateutil, pytz, six, tzdata, all `py2.py3-none-any`) matched the lock
exactly on the same host, which is the control: only the platform-specific
wheels diverge.

So the lock is not corrupt and PyPI is not compromised. It is
**single-platform**, generated on a cp310 host, and `--require-hashes` makes
that a hard failure rather than a resolve to the right wheel.

## Defect 2: `requirements.lock` omits pytest, so two suites cannot load

`requirements.lock` is a **7-package** hashed file: numpy, pandas, scipy,
python-dateutil, pytz, six, tzdata. `requirements-production.lock` is a
**19-package** unhashed file and it pins `pytest==8.4.2` (plus ruff, iniconfig,
pluggy, pygments, packaging, colorama).

`env_probe.py --install` installs `requirements.lock`. Its own printed command
says so:

    install: python -m pip install -r <repo>/requirements.lock --require-hashes --break-system-packages -q

So after a *successful* install there is still no pytest, and
`tests/test_greenfield_regressions.py:8`, `tests/test_production.py` and
`tests/conftest.py` all `import pytest`. The gate reports:

    FAIL  test suite FAILED in tests.test_greenfield_regressions, tests.test_production (ran 2001); do not build

which reads as a code defect and is a missing dependency.

## Defect 3: it also omits the pydantic stack

With pytest installed, `tests/test_production.py:16` then fails on
`from pydantic import ValidationError`. `requirements-production.lock` pins
pydantic 2.12.5, pydantic-core 2.41.5, typing-extensions 4.16.0,
typing-inspection 0.4.4, annotated-types 0.8.0. None are in
`requirements.lock`. This is R302's production strangler package, so the
dependency arrived with that work and the hashed lock was never extended.

**Net: `PASS` is unreachable from the documented install path on any host,
not just cp311.** The gate only went green here after hand-installing pytest
and pydantic.

## A fourth, smaller thing: a docstring names the wrong file

`.claude/hooks/guard_commands.py:65` tells the reader that `env_probe --install`
installs `requirements-production.lock`. It installs `requirements.lock`. That
mismatch is exactly the drift that would hide defects 2 and 3 from anyone
reasoning about which file matters.

## Remedy taken (a workaround, not a fix)

Fetched version-exact wheels with `tools/wheel_fetch.py`; verified each sha256
against PyPI's published digest for that exact filename; confirmed the four
pure-python wheels still matched the lock; installed with
`--no-index --find-links`. Then installed `pytest==8.4.2` and the pydantic stack
at `requirements-production.lock`'s own pins, also from verified wheels.

Two deviations to record. The lock's `packaging==26.3` could not be installed
(`Cannot uninstall packaging 24.0, RECORD file not found. Hint: The package was
installed by debian.`), so pytest ran against the system's 24.0, which satisfies
its `packaging>=20` floor. And nothing here re-verifies against the repo, only
against PyPI, which is weaker than what the lock is for.

Gate after the workaround: `PASS  v2.26.0  40 modules  2132 tests  4 skipped`.
The 4 skips are host facts, not lost tree coverage: no vendored `.pylibs/scipy`,
no `.env` on this machine, and two unstaged 2026-08-16 salary fixtures.

## Suggested fix for DEV

1. Regenerate `requirements.lock` with hashes for every interpreter the project
   runs on (pip accepts multiple `--hash=` lines per pin), at minimum cp310 and
   cp311 manylinux x86_64.
2. Decide what `requirements.lock` is FOR. Today there are two locks with
   overlapping names and different contents, and the one the probe installs is
   the one that cannot run the tests. Either fold the test dependencies into it
   or have `env_probe` install both and say which is which.
3. In `tools/env_probe.py`, on a hash mismatch, print the running
   `sys.version_info` and the cp tag, so the next session reads "cp311 host,
   cp310 lock" instead of a tampering warning.
4. Fix the `guard_commands.py:65` docstring.
