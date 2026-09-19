"""Keep a bare `python -m unittest` from publishing into the operator's tree.

R369, 2026-09-19. Two invocations were already isolated and one was not. The
gate sets `MLB_DFS_ARTIFACT_ROOT` on every `--run-tests` run (`tools/audit.py`,
R338 repair 4) and `tests/conftest.py` sets it for pytest, but a developer
running `python -m unittest tests.test_core` got neither, so the front-door and
golden-replay tests published real manifests into `outputs/` on the real tree.
That was invisible for as long as `outputs/` was the only thing they wrote,
because it is gitignored. `data/deliveries/` is TRACKED, so the same tests
started leaving twenty committed-looking delivery records in `git status`.

Set here rather than in each suite because it has to be in place before
`mlb_engine.entries.upload_manifest` is imported, and importing any `tests.*`
module runs this file first. An `MLB_DFS_ARTIFACT_ROOT` already in the
environment is respected: the gate and conftest pin their own, and a session
debugging a published artifact may want to point at a real tree.

The directory is deliberately not cleaned up. It is small, it lives under the
system temp root, and a test run whose artifacts are deleted before anyone can
look at them is worse than one that leaves them.
"""
import os
import tempfile

if not os.environ.get("MLB_DFS_ARTIFACT_ROOT"):
    os.environ["MLB_DFS_ARTIFACT_ROOT"] = tempfile.mkdtemp(
        prefix="mlb_dfs_unittest_artifacts_")
