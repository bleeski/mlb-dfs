"""upload_manifest.py -- one file per slate date that answers "which file do I upload".

The upload is the only manual step in this project and it happens at T-5.
Filesystem ambiguity at that moment is the highest-consequence operator trap in
the system, and on 2026-07-25 it was live: ``outputs/2026-07-25/`` held seven
DKEntries files and ten briefs, three Showdown slates each recorded a
``delivered_path`` of ``.../DKEntries_showdown.csv`` so two briefs cited a file
holding another slate's lineups, two files carried identical contest names with
different rosters, and every recorded path was absolute against a session mount
that no longer exists. Nothing on disk answered the question.

``outputs/<date>/upload_manifest.json`` answers it. Every delivery path appends
one record; a later delivery that supersedes an earlier one says so in the
earlier record rather than overwriting the file. Paths are repo-relative,
because a path resolved against a dead sandbox mount is not a path.

Deterministic bookkeeping. Nothing here is a projection, an ROI figure, a win
rate, or a probability claim. A manifest record states what was written, not
whether it was any good.
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

VERSION = "1.1"

# R3(c). The closed set of record statuses. 'candidate' is what a build writes:
# the file exists and nothing has checked it yet. Only preflight moves a record
# to 'upload_ready', and only for the exact bytes it hashed.
STATUS_VALUES = ("candidate", "upload_ready", "blocked", "acknowledged", "superseded")


def _valid_status(status: object) -> str:
    """R34: the closed status set, actually closed.

    ``STATUS_VALUES`` was documentation only. Nothing validated against it, so
    the Showdown path recorded ``status='delivered'`` and it read as CURRENT
    everywhere that filters on ``!= 'superseded'`` -- including
    ``current_deliveries``, which answers "which file do I upload".

    Raises rather than coercing. Both callers already wrap ``record_delivery`` in
    a try/except that degrades to "MANIFEST NOT RECORDED", which default
    preflight then hard-fails, so an invalid status fails closed instead of
    entering the record as a status nobody can interpret.
    """
    text = str(status or "").strip()
    if text not in STATUS_VALUES:
        raise ValueError(
            f"status {text!r} is not one of {list(STATUS_VALUES)}; a status "
            f"outside the closed set reads as current everywhere that only "
            f"filters out 'superseded'")
    return text

MANIFEST_NAME = "upload_manifest.json"
REPO_ROOT = Path(__file__).resolve().parents[2]


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def repo_relative(path: str | Path) -> str:
    """Repo-relative when possible, so the record survives a new session mount."""
    resolved = Path(path)
    try:
        return str(resolved.resolve().relative_to(REPO_ROOT))
    except (ValueError, OSError):
        return str(resolved)


def manifest_path(date: str) -> Path:
    return REPO_ROOT / "outputs" / str(date) / MANIFEST_NAME


def read_manifest(date: str) -> Dict[str, Any]:
    path = manifest_path(date)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"version": VERSION, "date": str(date), "deliveries": []}
    if isinstance(data, list):  # tolerate a bare list written by an older caller
        return {"version": VERSION, "date": str(date), "deliveries": data}
    data.setdefault("deliveries", [])
    data.setdefault("date", str(date))
    return data


def _write(path: Path, payload: Mapping[str, Any]) -> None:
    """tmp + os.replace: a manifest is read at T-5 and must never be half-written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(payload, indent=1, sort_keys=False) + "\n",
                   encoding="utf-8")
    os.replace(tmp, path)


def record_delivery(
    *,
    date: str,
    delivered_file: str | Path,
    contest_type: str,
    slate_tag: str = "",
    contest_ids: Optional[Sequence[str]] = None,
    contest_names: Optional[Sequence[str]] = None,
    entries: Optional[int] = None,
    run_id: Optional[str] = None,
    status: str = "candidate",
    certification: str = "review_grade",
    projection_tier: str = "unknown",
    strategy_state: Optional[Mapping[str, Any]] = None,
    notes: str = "",
) -> Dict[str, Any]:
    """Append one delivery record and supersede any prior record for the same slate.

    Supersession is keyed on (contest_type, slate_tag), which is the identity of
    the thing being delivered. A second Classic build for the same draftgroup
    replaces the first; a Showdown build for a different game does not touch it.
    """
    path = Path(delivered_file)
    manifest = read_manifest(date)
    record = {
        "delivered_file": repo_relative(path),
        "sha256": sha256_file(path) if path.exists() else None,
        "contest_type": str(contest_type).lower(),
        "slate_tag": str(slate_tag or ""),
        "contest_ids": sorted({str(c) for c in (contest_ids or [])}),
        "contest_names": sorted({str(c) for c in (contest_names or [])}),
        "entries": int(entries) if entries is not None else None,
        "run_id": run_id,
        # R3(c). One of STATUS_VALUES. The build writes 'candidate'; preflight
        # stamps 'upload_ready', 'blocked' or 'acknowledged' onto the record for
        # the exact bytes it checked; a later delivery for the same slate marks
        # this one 'superseded'. "Which file do I upload, and did it pass" is now
        # one read of one file instead of a memory of what a terminal printed.
        "status": _valid_status(status),
        "certification": certification,
        # 'enriched' or 'proxy'. A portfolio built on proxy projections is a
        # different artifact from one built on the enrichment stack.
        "projection_tier": str(projection_tier or "unknown"),
        # {'state': 'clean'|'relaxed', 'counts': {...}}. A portfolio is not clean
        # because the gates passed; it is clean when nothing was relaxed.
        "strategy_state": dict(strategy_state or {"state": "unknown", "counts": {}}),
        "recorded_utc": datetime.now(timezone.utc).isoformat(),
        "notes": notes,
    }
    key = (record["contest_type"], record["slate_tag"])
    for prior in manifest["deliveries"]:
        if (prior.get("contest_type"), prior.get("slate_tag")) != key:
            continue
        if prior.get("status") == "superseded":
            continue
        if prior.get("sha256") and prior["sha256"] == record["sha256"]:
            # The same bytes recorded twice is one delivery, not two.
            prior.update(record)
            _write(manifest_path(date), manifest)
            return prior
        prior["status"] = "superseded"
        prior["superseded_by"] = record["delivered_file"]
        prior["superseded_utc"] = record["recorded_utc"]
    manifest["deliveries"].append(record)
    _write(manifest_path(date), manifest)
    return record


def current_deliveries(date: str) -> List[Dict[str, Any]]:
    """Records that are still the answer to "which file do I upload"."""
    return [r for r in read_manifest(date).get("deliveries", [])
            if r.get("status") != "superseded"]


def verify_manifest(date: str) -> Dict[str, Any]:
    """Do the recorded files still exist, and do they still hash the same.

    A manifest that has drifted from disk is worse than none, because it is the
    thing preflight cross-checks against.
    """
    problems: List[str] = []
    checked = 0
    for record in read_manifest(date).get("deliveries", []):
        if record.get("status") == "superseded":
            continue
        target = REPO_ROOT / str(record.get("delivered_file") or "")
        if not target.exists():
            problems.append(f"{record.get('delivered_file')}: recorded but missing")
            continue
        checked += 1
        if record.get("sha256") and sha256_file(target) != record["sha256"]:
            problems.append(
                f"{record.get('delivered_file')}: on-disk sha256 differs from the "
                f"recorded one; the file changed after it was delivered")
    return {"passed": not problems, "checked": checked, "problems": problems,
            "date": str(date)}
