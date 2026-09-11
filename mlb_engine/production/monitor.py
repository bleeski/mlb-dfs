"""Monitor an authorized local snapshot provider, with idempotent safe retries."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from .contracts import Controls
from .evidence import FileProvider, read_bounded
from .state import StateStore, digest, json_bytes
from .workflow import run


def tick(
    salary: Path,
    evidence: Path,
    output: Path,
    scope: str,
    authorized_entry_ids: set[str],
    previous_token: str | None = None,
    controls: Controls | None = None,
    *,
    fixture_mode=False,
    as_of=None,
    runner=run,
) -> tuple[str, dict]:
    store = StateStore(output)
    run_id = store.current(scope)
    if run_id is None:
        raise ValueError("monitor requires an existing verified parent and its scope")
    store.verify_bundle(run_id)
    parent = store.root / "runs" / run_id / "final/DKEntries.csv"
    diagnostics = json.loads((parent.parent / "diagnostics.json").read_bytes())
    raw, sources = FileProvider(evidence).read()
    now = as_of if fixture_mode else datetime.now(timezone.utc)
    recheck_due = now >= datetime.fromisoformat(diagnostics["recheck_at"])
    token = digest(
        json_bytes(
            {
                "salary": digest(read_bounded(salary)),
                "evidence": digest(raw),
                "sources": {k: digest(v) for k, v in sources.items()},
                "recheck_due": recheck_due,
                "parent_export": diagnostics["export_sha256"],
            }
        )
    )
    if token == previous_token:
        return token, {"status": "unchanged", "scope": scope}
    result = runner(
        salary,
        parent,
        evidence,
        output,
        controls=controls,
        parent=parent,
        authorized_entry_ids=authorized_entry_ids,
        fixture_mode=fixture_mode,
        as_of=as_of,
    )
    return token, result
