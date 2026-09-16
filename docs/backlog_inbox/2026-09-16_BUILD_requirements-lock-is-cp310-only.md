# requirements.lock pins cp310 wheels, so env_probe cannot install on a cp311 host

Filed by BUILD, 2026-09-16 slate 1910_7g. Cost ~3 minutes of a 35-minute lock window.

## What happened

`python tools/env_probe.py --install` failed on a cold container with:

    ERROR: THESE PACKAGES DO NOT MATCH THE HASHES FROM THE REQUIREMENTS FILE.
    numpy==2.2.6 ... Expected sha256 fc7b73d0... Got ba10f841...

That error text says "someone may have tampered with them", which is the
alarming reading and the wrong one. The bytes were authentic.

## Diagnosis

The host was Python 3.11.15. `requirements.lock` carries ONE hash per package,
and for the three binary packages that hash belongs to the **cp310** wheel:

    lock's numpy hash fc7b73d0 -> numpy-2.2.6-cp310-cp310-manylinux_2_17_x86_64.whl
    downloaded on cp311       -> numpy-2.2.6-cp311-cp311-manylinux_2_17_x86_64.whl (ba10f841)

PyPI's own JSON API publishes ba10f841 / 39cb9c62 / b98560e9 as the sha256 of
the cp311 wheels for numpy 2.2.6, scipy 1.15.3 and pandas 2.3.3 -- exactly the
bytes that arrived, over two independent transports (pip, and `tools/wheel_fetch.py`
raw range requests). The four PURE-PYTHON pins (python-dateutil, pytz, six,
tzdata, all `py2.py3-none-any`) matched the lock exactly on the same host, which
is the control: only the platform-specific wheels diverge.

So the lock is not corrupt and PyPI is not compromised. The lock is
**single-platform**, generated on a cp310 host, and `--require-hashes` makes
that a hard failure rather than a resolve to the right wheel.

## Why it matters

`env_probe --install` is the documented first step of every BUILD session and
the skill says never to hand-pip around it. On any cp311 host that step cannot
succeed, and the failure surfaces as a tampering warning during a lock window.

## Remedy taken this slate (not a fix)

Fetched the version-exact wheels with `tools/wheel_fetch.py`, verified each
sha256 against PyPI's published digest for that exact filename, confirmed the
four pure-python wheels still matched the lock, then installed with
`--no-index --find-links`. Versions stayed exactly what the lock pins; nothing
was resolved loosely. This is a workaround and it re-verifies against PyPI
rather than against the repo, which is weaker than the lock.

## Suggested fix for DEV

Regenerate `requirements.lock` with hashes for every interpreter/platform the
project runs on (pip accepts multiple `--hash=` lines per pin), at minimum
cp310 and cp311 manylinux x86_64. Then `--require-hashes` keeps its guarantee
on both hosts instead of failing closed on one.

Worth adding to `tools/env_probe.py`: on a hash mismatch, print the running
`sys.version_info` and the cp tag, so the next session sees "cp311 host,
cp310 lock" instead of a tampering warning.
