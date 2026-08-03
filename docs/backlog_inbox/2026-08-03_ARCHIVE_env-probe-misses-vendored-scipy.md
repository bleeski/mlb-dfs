# Fragment: env_probe and audit call the environment cold while a working scipy sits in .pylibs

Session: ARCHIVE, 2026-08-03. For: DEV. Adjacent to R42.

`python tools/audit.py --terse` printed:

    FAIL  dependencies: missing ['scipy']; run: python tools/env_probe.py --install;  scipy.optimize.milp unavailable

and `python tools/env_probe.py` agreed ("env cold: missing ['scipy']; milp unavailable"). Both are
wrong. `.pylibs/` in the repo root holds scipy 1.15.3 with its `.libs`, and

    export PYTHONPATH=$PWD/.pylibs

makes `from scipy.optimize import milp` import immediately. The whole suite and every mine in this
session ran that way. No install, no network, no disk.

The defect is that the probe reads only the interpreter's default path. `.pylibs` and `.wheels` are
the persistence design working exactly as intended and the tool cannot see them, so it reports the
one state that sends the next session into a pip install it does not need. In a sandbox where
`--install` can die on ENOSPC (R42), being told to install when a working copy is already on disk is
the expensive version of the wrong answer.

Suggested fix: `env_probe` checks `.pylibs` before declaring anything missing, and either reports
"vendored at .pylibs, export PYTHONPATH=$PWD/.pylibs" or adds the path itself. `audit.py` should
report the same thing rather than a bare FAIL. Done when a session with a populated `.pylibs` and an
empty site-packages gets one line naming the env var instead of an install command.

Ordering note: this is smaller than R42 and independent of it. R42 is about failing gracefully when
an install genuinely must happen; this is about not starting one that does not.
