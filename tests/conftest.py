"""Keep historical default publication paths away from operator artifacts."""

import hashlib
import json
import os
from pathlib import Path

import pytest


def _operator_hashes(root):
    result = {}
    for folder in ("data", "outputs", "runs", "_slate_in", "tests/fixtures"):
        for path in (root / folder).rglob("*"):
            if path.is_file() and path.suffix.lower() in {".csv", ".json", ".tsv"}:
                result[path.relative_to(root).as_posix()] = hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
    return result


@pytest.fixture(scope="session", autouse=True)
def isolate_historical_publication(tmp_path_factory):
    """Redirect defaults in-process and in children; explicit fixture roots still win."""
    from mlb_engine.entries import upload_manifest

    root = Path(__file__).resolve().parents[1]
    before = _operator_hashes(root)
    isolated = tmp_path_factory.mktemp("historical_artifacts")
    previous_root = upload_manifest.REPO_ROOT
    previous_env = os.environ.get("MLB_DFS_ARTIFACT_ROOT")
    upload_manifest.REPO_ROOT = isolated
    os.environ["MLB_DFS_ARTIFACT_ROOT"] = str(isolated)
    try:
        yield
    finally:
        upload_manifest.REPO_ROOT = previous_root
        if previous_env is None:
            os.environ.pop("MLB_DFS_ARTIFACT_ROOT", None)
        else:
            os.environ["MLB_DFS_ARTIFACT_ROOT"] = previous_env
        after = _operator_hashes(root)
        changed = [p for p, sha in before.items() if after.get(p) != sha]
        report = {
            "checked_files": len(before),
            "changed": changed,
            "passed": not changed,
        }
        (isolated.parent / "operator_preservation.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
        assert not changed, f"Tests changed operator artifacts: {changed}"
