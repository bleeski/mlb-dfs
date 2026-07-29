"""MLB Classic immutable run manager v1.4.

Creates hash-bound, immutable execution runs. A run may be written while in
``building`` state, but production artifacts are never overwritten after the run
is promoted. ``latest_valid_run.json`` is only a pointer; it is not an artifact.

v1.4 (R7): every manifest records the runtime environment (Python and engine
package versions, plus the sha256 of requirements.lock when present), so a
result can always be tied to the resolver state that produced it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Sequence

VERSION = "v1.4"
MANIFEST_NAME = "manifest.json"
LATEST_POINTER = "latest_valid_run.json"
RUN_SUBDIRS = ("inputs", "candidate", "final")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: Optional[datetime] = None) -> str:
    dt = value or _utc_now()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def _load_manifest(run_dir: str | Path) -> Dict[str, Any]:
    path = Path(run_dir) / MANIFEST_NAME
    if not path.exists():
        raise FileNotFoundError(f"run manifest not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _save_manifest(run_dir: str | Path, manifest: Dict[str, Any]) -> None:
    _atomic_write_json(Path(run_dir) / MANIFEST_NAME, manifest)


def _assert_mutable(manifest: Dict[str, Any]) -> None:
    if manifest.get("status") == "promoted":
        raise RuntimeError("promoted runs are immutable")


def runtime_environment(runs_root: str | Path) -> Dict[str, Any]:
    """Snapshot the runtime the run executes under (R7).

    Package versions come from live imports, because what imported is what
    ran; a dep that fails to import records None rather than raising, since
    ``validate_only`` work may legitimately run without the solver. The lock
    sha256 ties the manifest to the exact resolution set; ``runs/`` sits at
    the repo root, so the lock is looked up beside it and records None when
    absent rather than guessing.
    """
    import platform

    packages: Dict[str, Optional[str]] = {}
    for name in ("numpy", "pandas", "scipy"):
        try:
            packages[name] = str(getattr(__import__(name), "__version__", "unknown"))
        except ImportError:
            packages[name] = None
    lock = Path(runs_root).resolve().parent / "requirements.lock"
    return {
        "python": platform.python_version(),
        "packages": packages,
        "lock_file": lock.name if lock.exists() else None,
        "lock_sha256": sha256_file(lock) if lock.exists() else None,
    }


def create_run(
    runs_root: str | Path,
    mode: str,
    parent_run_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Create a unique immutable run directory and initial manifest."""
    if mode not in {"initial_build", "late_swap", "validate_only"}:
        raise ValueError("mode must be initial_build, late_swap, or validate_only")
    root = Path(runs_root)
    root.mkdir(parents=True, exist_ok=True)
    ts = (now or _utc_now()).astimezone(timezone.utc)
    run_id = f"{ts.strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:8]}"
    run_dir = root / run_id
    run_dir.mkdir()
    for subdir in RUN_SUBDIRS:
        (run_dir / subdir).mkdir()
    manifest: Dict[str, Any] = {
        "schema_version": 1,
        "run_manager_version": VERSION,
        "run_id": run_id,
        "mode": mode,
        "parent_run_id": parent_run_id,
        "created_utc": _iso(ts),
        "status": "building",
        "environment": runtime_environment(root),
        "metadata": metadata or {},
        "inputs": {},
        "artifacts": {},
        "certification": {
            "workflow_valid": False,
            "selection_certified": False,
            "allocation_certified": None,
        },
        "errors": [],
        "warnings": [],
    }
    _save_manifest(run_dir, manifest)
    return {"run_id": run_id, "run_dir": str(run_dir), "manifest": manifest}


def snapshot_run_inputs(
    run_dir: str | Path,
    paths: Iterable[str | Path],
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Copy inputs into the run and record hashes. Basenames must be unique."""
    run_path = Path(run_dir)
    manifest = _load_manifest(run_path)
    _assert_mutable(manifest)
    seen: set[str] = set()
    rows: Dict[str, Any] = {}
    for raw in paths:
        source = Path(raw)
        if not source.exists() or not source.is_file():
            raise FileNotFoundError(f"input file not found: {source}")
        name = source.name
        if name in seen:
            raise ValueError(f"duplicate input basename: {name}")
        seen.add(name)
        destination = run_path / "inputs" / name
        shutil.copy2(source, destination)
        rows[name] = {
            "source_path": str(source.resolve()),
            "relative_path": str(destination.relative_to(run_path)),
            "sha256": sha256_file(destination),
            "size_bytes": destination.stat().st_size,
        }
    manifest["inputs"].update(rows)
    if metadata:
        manifest.setdefault("input_metadata", {}).update(metadata)
    _save_manifest(run_path, manifest)
    return rows


def register_artifact(
    run_dir: str | Path,
    artifact_path: str | Path,
    role: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Register a file already located under the run directory."""
    run_path = Path(run_dir).resolve()
    path = Path(artifact_path).resolve()
    manifest = _load_manifest(run_path)
    _assert_mutable(manifest)
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(path)
    try:
        relative = path.relative_to(run_path)
    except ValueError as exc:
        raise ValueError("artifact must be inside run_dir") from exc
    record = {
        "role": role,
        "relative_path": str(relative),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
        "metadata": metadata or {},
    }
    manifest["artifacts"][str(relative)] = record
    _save_manifest(run_path, manifest)
    return record


ASSIGNABLE_RUN_STATUSES = {"building", "blocked", "diagnostic"}


def update_run_certification(
    run_dir: str | Path,
    certification: Dict[str, Any],
    errors: Optional[Sequence[str]] = None,
    warnings: Optional[Sequence[str]] = None,
    status: Optional[str] = None,
) -> Dict[str, Any]:
    """Update certification flags and optionally the run status.

    ``status`` may be one of ``building``, ``blocked``, or ``diagnostic``.
    ``promoted`` can only be set through :func:`promote_run`, which re-verifies
    every recorded hash first. Gate-blocked runs should be marked ``blocked``
    so a crashed run and a gate-blocked run are distinguishable in the manifest.
    """
    run_path = Path(run_dir)
    manifest = _load_manifest(run_path)
    _assert_mutable(manifest)
    manifest["certification"] = dict(certification)
    if errors is not None:
        manifest["errors"] = list(errors)
    if warnings is not None:
        manifest["warnings"] = list(warnings)
    if status is not None:
        if status not in ASSIGNABLE_RUN_STATUSES:
            raise ValueError(f"status must be one of {sorted(ASSIGNABLE_RUN_STATUSES)}")
        manifest["status"] = status
    _save_manifest(run_path, manifest)
    return manifest


def verify_run_bundle(run_dir: str | Path) -> Dict[str, Any]:
    """Verify all recorded input/artifact hashes and export-diagnostics binding."""
    run_path = Path(run_dir)
    manifest = _load_manifest(run_path)
    errors: list[str] = []
    checked = 0
    for section in ("inputs", "artifacts"):
        for name, record in manifest.get(section, {}).items():
            rel = record.get("relative_path") or name
            path = run_path / rel
            checked += 1
            if not path.exists():
                errors.append(f"missing {section[:-1]}: {rel}")
            elif sha256_file(path) != record.get("sha256"):
                errors.append(f"hash mismatch: {rel}")

    diagnostic_records = [
        r for r in manifest.get("artifacts", {}).values()
        if r.get("role") == "diagnostics"
    ]
    for record in diagnostic_records:
        path = run_path / record["relative_path"]
        try:
            diagnostic = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"invalid diagnostics JSON: {record['relative_path']}: {exc}")
            continue
        source_rel = diagnostic.get("diagnostic_source_file")
        source_hash = diagnostic.get("diagnostic_source_sha256")
        if not source_rel or not source_hash:
            # A blocked run has no export, so it has nothing to bind a hash to.
            # Reporting that as a verification failure made every correctly
            # blocked run read as tampered, which is the opposite of what the
            # check is for.
            if diagnostic.get("hash_binding_applicable") is False or \
                    diagnostic.get("status") == "blocked":
                continue
            errors.append("diagnostics missing export hash binding")
            continue
        source_path = run_path / source_rel
        if not source_path.exists():
            errors.append(f"diagnostic source missing: {source_rel}")
        elif sha256_file(source_path) != source_hash:
            errors.append("diagnostic source hash mismatch")

    cert = manifest.get("certification", {})
    if manifest.get("status") == "promoted" and not cert.get("workflow_valid"):
        errors.append("promoted run is not workflow_valid")
    return {
        "passed": not errors,
        "errors": errors,
        "checked_files": checked,
        "run_id": manifest.get("run_id"),
        "status": manifest.get("status"),
    }


def verify_inputs_unmoved(run_dir: str | Path) -> Dict[str, Any]:
    """R20(b): the staged sources this run read still hash what intake recorded.

    :func:`verify_run_bundle` checks the snapshots inside the run, which
    nothing outside the run can touch. The exposure is the staged working
    copies the build actually reads (``data/slates/<date>/...``): on
    2026-07-23 a Showdown stage clobbered an in-flight Classic build's staged
    inputs and certification could not see it. This check can: at promotion
    the sources must still match the intake hashes, or the run was built on a
    world that moved underneath it. Meaningful only within the building
    session, because ``source_path`` is absolute against that session's
    mount, and promotion is exactly where that holds.
    """
    manifest = _load_manifest(run_dir)
    moved: list[str] = []
    missing: list[str] = []
    checked = 0
    for name, record in manifest.get("inputs", {}).items():
        source = Path(str(record.get("source_path") or ""))
        try:
            exists = source.exists() and source.is_file()
        except OSError:
            exists = False
        if not exists:
            missing.append(name)
            continue
        checked += 1
        if sha256_file(source) != record.get("sha256"):
            moved.append(name)
    errors = [f"inputs moved underneath the run: {name}" for name in sorted(moved)]
    errors += [f"input source vanished underneath the run: {name}"
               for name in sorted(missing)]
    return {"passed": not errors, "errors": errors, "checked": checked,
            "moved": sorted(moved), "missing_sources": sorted(missing)}


_POINTER_UNCHECKED = object()


def read_pointer_sha256(runs_root: str | Path) -> Optional[str]:
    """Current sha256 of the latest-run pointer file, or None when absent.

    R20(c): capture this the moment a run is created, hand it back to
    :func:`promote_run` as ``expected_pointer_sha256``, and a promotion that
    would silently overwrite another session's promotion becomes a loud
    refusal instead of a lost update.
    """
    pointer = Path(runs_root) / LATEST_POINTER
    try:
        return sha256_file(pointer) if pointer.exists() else None
    except OSError:
        return None


def promote_run(
    run_dir: str | Path,
    latest_pointer_path: Optional[str | Path] = None,
    *,
    expected_pointer_sha256: Any = _POINTER_UNCHECKED,
) -> Dict[str, Any]:
    """Promote a validated run and atomically update the latest-run pointer.

    ``expected_pointer_sha256`` is the compare half of a compare-and-swap
    (R20c): pass what :func:`read_pointer_sha256` returned when this run was
    created (None when no pointer existed yet). A pointer that has since
    changed means another session promoted while this run was building; the
    promotion is refused without mutating the run, which stays ``building``
    and remains valid. Omitting the argument keeps the old unconditional
    write, which is the manual-recovery path after review.
    """
    run_path = Path(run_dir)
    manifest = _load_manifest(run_path)
    _assert_mutable(manifest)
    pointer = Path(latest_pointer_path) if latest_pointer_path else run_path.parent / LATEST_POINTER
    if expected_pointer_sha256 is not _POINTER_UNCHECKED:
        try:
            current = sha256_file(pointer) if pointer.exists() else None
        except OSError:
            current = None
        if current != expected_pointer_sha256:
            return {
                "passed": False,
                "run_id": manifest.get("run_id"),
                "pointer_conflict": True,
                "errors": [
                    "promotion refused: the latest-run pointer changed while "
                    "this run was building, so another session promoted a run "
                    "in the meantime. This run is untouched and stays "
                    "'building'; re-read the pointer and decide which "
                    "portfolio is the delivery, or promote manually (without "
                    "expected_pointer_sha256) after review"],
            }
    cert = manifest.get("certification", {})
    errors: list[str] = []
    if not cert.get("workflow_valid"):
        errors.append("workflow_valid is false")
    if not cert.get("selection_certified"):
        errors.append("selection_certified is false")
    allocation = cert.get("allocation_certified")
    if allocation is False:
        errors.append("allocation_certified is false")
    verification = verify_run_bundle(run_path)
    errors.extend(verification["errors"])
    # R20(b): the snapshots verified above live inside the run where nothing
    # else can touch them; the staged sources the build actually read are
    # not so protected. A source that no longer hashes what intake recorded
    # means the world moved underneath this run, and the certified claim
    # must not ship.
    sources = verify_inputs_unmoved(run_path)
    errors.extend(sources["errors"])
    if errors:
        manifest["status"] = "blocked"
        manifest["errors"] = sorted(set(manifest.get("errors", []) + errors))
        _save_manifest(run_path, manifest)
        return {"passed": False, "errors": errors, "run_id": manifest["run_id"]}

    manifest["status"] = "promoted"
    manifest["promoted_utc"] = _iso()
    _save_manifest(run_path, manifest)
    _atomic_write_json(pointer, {
        "run_id": manifest["run_id"],
        # Relative to the pointer's own directory, which is runs_root. A pointer
        # that only knows an absolute path from a dead session mount is a pointer
        # to nothing; this one resolves under any mount, and run_id resolves it
        # even if the file is moved.
        "run_dir_rel": run_path.resolve().name,
        "runs_root_rel": str(pointer.parent.resolve().name),
        # Kept for readers written against the old shape. Never resolved first.
        "run_dir": str(run_path.resolve()),
        "manifest_sha256": sha256_file(run_path / MANIFEST_NAME),
        "promoted_utc": manifest["promoted_utc"],
    })
    return {"passed": True, "errors": [], "run_id": manifest["run_id"], "run_dir": str(run_path)}


def _resolve_pointer_run_dir(runs_root: Path, data: Dict[str, Any]) -> Optional[Path]:
    """Locate the promoted run from the pointer, run_id first.

    ``run_dir`` is an absolute path recorded by the session that promoted the
    run. Every Cowork session gets a new mount, so in any later session that
    path is not merely absent, it belongs to a directory tree the process cannot
    stat: the bare ``.exists()`` raised PermissionError rather than returning
    False, and ``tools/late_swap.py`` died at entry. The deadline-critical tool
    must not depend on the birth session's filesystem.

    ``runs_root`` plus ``run_id`` is the same run under whatever mount is
    current, so it is tried first and the recorded path is only a fallback.
    """
    candidates = []
    relative = str(data.get("run_dir_rel") or "").strip()
    if relative:
        candidates.append(runs_root / relative)
    run_id = str(data.get("run_id") or "").strip()
    if run_id:
        candidates.append(runs_root / run_id)
    recorded = str(data.get("run_dir") or "").strip()
    if recorded:
        candidates.append(Path(recorded))
    for candidate in candidates:
        try:
            if candidate.exists():
                return candidate
        except OSError:
            # A dead session mount. Not an error, just not this one.
            continue
    return None


def get_latest_promoted_run(runs_root: str | Path) -> Optional[Dict[str, Any]]:
    runs_root = Path(runs_root)
    pointer = runs_root / LATEST_POINTER
    try:
        if not pointer.exists():
            return None
        data = json.loads(pointer.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    run_dir = _resolve_pointer_run_dir(runs_root, data)
    if run_dir is None:
        return None
    try:
        manifest = _load_manifest(run_dir)
        if manifest.get("status") != "promoted":
            return None
        if sha256_file(run_dir / MANIFEST_NAME) != data.get("manifest_sha256"):
            return None
    except (OSError, ValueError):
        return None
    return {"run_dir": str(run_dir), "manifest": manifest, "pointer": data}


# Backward-compatible input snapshot helpers.
def snapshot_inputs(paths: Iterable[str], metadata: Optional[Dict] = None) -> Dict:
    files = {}
    for raw in paths:
        path = Path(raw)
        if not path.exists():
            files[str(path)] = {"exists": False}
            continue
        stat = path.stat()
        files[str(path)] = {
            "exists": True,
            "sha256": sha256_file(path),
            "size_bytes": int(stat.st_size),
            "modified_utc": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        }
    return {"version": VERSION, "created_utc": _iso(), "files": files, "metadata": metadata or {}}


def compare_states(previous: Optional[Dict], current: Dict) -> Dict:
    previous_files = (previous or {}).get("files", {})
    current_files = current.get("files", {})
    changed, unchanged, added, removed = [], [], [], []
    for path, info in current_files.items():
        if path not in previous_files:
            added.append(path)
        elif info.get("sha256") != previous_files[path].get("sha256") or info.get("exists") != previous_files[path].get("exists"):
            changed.append(path)
        else:
            unchanged.append(path)
    for path in previous_files:
        if path not in current_files:
            removed.append(path)
    return {
        "changed": changed, "unchanged": unchanged, "added": added, "removed": removed,
        "requires_upstream_rebuild": bool(changed or added or removed),
        "note": "Final optimizer/export validation must run even when upstream inputs are unchanged.",
    }


def update_build_state(state_path: str, input_paths: Iterable[str], metadata: Optional[Dict] = None) -> Dict:
    path = Path(state_path)
    previous = json.loads(path.read_text()) if path.exists() else None
    current = snapshot_inputs(input_paths, metadata=metadata)
    current["diff_from_previous"] = compare_states(previous, current)
    _atomic_write_json(path, current)
    return current


def slate_context_refresh_plan(packet: Dict, now_iso: Optional[str] = None) -> Dict:
    now = datetime.fromisoformat(now_iso.replace("Z", "+00:00")) if now_iso else _utc_now()
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    def age_minutes(value: Any) -> Optional[float]:
        if not value:
            return None
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0.0, (now - dt.astimezone(timezone.utc)).total_seconds() / 60.0)

    refresh_odds, refresh_roof, refresh_weather, reuse_weather = [], [], [], []
    for game in packet.get("games", []):
        gid = str(game.get("game_id") or "")
        odds = game.get("odds") or {}
        weather = game.get("weather") or {}
        if age_minutes(odds.get("fetched_at")) is None or age_minutes(odds.get("fetched_at")) > 180:
            refresh_odds.append(gid)
        if game.get("roof_status_required"):
            refresh_roof.append(gid)
        risk = {str(weather.get("delay_risk") or "").lower(), str(weather.get("postponement_risk") or "").lower()}
        weather_age = age_minutes(weather.get("fetched_at"))
        if game.get("weather_required") and (risk & {"medium", "high"} or weather_age is None or weather_age > 120):
            refresh_weather.append(gid)
        elif game.get("weather_required"):
            reuse_weather.append(gid)
    return {
        "refresh_odds_games": sorted(set(refresh_odds)),
        "refresh_roof_games": sorted(set(refresh_roof)),
        "refresh_weather_games": sorted(set(refresh_weather)),
        "reuse_cached_weather_games": sorted(set(reuse_weather)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="MLB Classic immutable run manager")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create")
    create.add_argument("--runs-root", required=True)
    create.add_argument("--mode", required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("run_dir")
    args = parser.parse_args()
    if args.command == "create":
        print(json.dumps(create_run(args.runs_root, args.mode), indent=2, sort_keys=True))
    else:
        result = verify_run_bundle(args.run_dir)
        print(json.dumps(result, indent=2, sort_keys=True))
        raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
