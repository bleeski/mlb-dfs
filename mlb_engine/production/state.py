"""Immutable run bundles with transactional, slate-scoped publication.

SQLite owns the current export bytes. The convenient safe CSV is a recoverable
mirror; it is never trusted without comparing its hash with the committed row.
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path


def digest(raw: bytes) -> str:
    return sha256(raw).hexdigest()


def json_bytes(value) -> bytes:
    return (
        json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n"
    ).encode()


def atomic_write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # A short sibling name also works under Windows' legacy path-length limit.
    temp = path.with_name("." + uuid.uuid4().hex[:16] + ".tmp")
    try:
        with temp.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
        if os.name != "nt":
            fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
    finally:
        if temp.exists():
            temp.unlink()


class StateStore:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.database = self.root / "state.sqlite3"
        with self.connection() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS runs("
                "run_id TEXT PRIMARY KEY, scope TEXT NOT NULL, "
                "manifest BLOB NOT NULL, manifest_hash TEXT NOT NULL, "
                "export BLOB NOT NULL, export_hash TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS current("
                "scope TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(run_id))"
            )

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.database, timeout=5, isolation_level=None)
        db.execute("PRAGMA foreign_keys=ON")
        # R338 step 7, XS fix (R109). The default DELETE journal mode creates a
        # `-journal` sibling per write transaction and UNLINKS it at commit, and
        # this mount grants create and truncate but not unlink, so every write
        # through this store would fail there. PERSIST keeps the same crash
        # safety -- the rollback journal is still written and fsynced -- and
        # zeroes its header at commit instead of deleting the file. WAL is the
        # other durable option and is rejected: it needs shared memory the mount
        # does not give, and it would change the single-writer semantics the
        # publication compare-and-update depends on.
        db.execute("PRAGMA journal_mode=PERSIST")
        db.execute("PRAGMA synchronous=FULL")
        try:
            yield db
        finally:
            db.close()

    def current(self, scope: str) -> str | None:
        with self.connection() as db:
            row = db.execute(
                "SELECT run_id FROM current WHERE scope=?", (scope,)
            ).fetchone()
        return row[0] if row else None

    def create_run(self, inputs: dict[str, bytes], metadata: dict) -> tuple[Path, dict]:
        run_id = uuid.uuid4().hex
        run = self.root / "runs" / run_id
        run.mkdir(parents=True, exist_ok=False)
        manifest = {
            "schema_version": 1,
            "run_id": run_id,
            "status": "building",
            "inputs": {},
            "artifacts": {},
            "metadata": metadata,
        }
        for index, (role, raw) in enumerate(sorted(inputs.items())):
            name = f"inputs/{index:03d}.bin"
            atomic_write(run / name, raw)
            manifest["inputs"][role] = {
                "path": name,
                "sha256": digest(raw),
                "bytes": len(raw),
            }
        atomic_write(run / "manifest.json", json_bytes(manifest))
        return run, manifest

    def artifact(self, run: Path, manifest: dict, name: str, raw: bytes):
        if Path(name).is_absolute() or ".." in Path(name).parts:
            raise ValueError("artifact path must be confined")
        target = run / name
        if target.exists():
            raise FileExistsError("immutable run artifact already exists")
        atomic_write(target, raw)
        manifest["artifacts"][name] = {
            "path": name,
            "sha256": digest(raw),
            "bytes": len(raw),
        }

    def save_manifest(self, run: Path, manifest: dict):
        atomic_write(run / "manifest.json", json_bytes(manifest))

    def verify_bundle(
        self, run_id: str, expected_manifest: bytes | None = None
    ) -> dict:
        if not len(run_id) == 32 or any(c not in "0123456789abcdef" for c in run_id):
            raise ValueError("invalid run identity")
        run = (self.root / "runs" / run_id).resolve(strict=True)
        raw = (run / "manifest.json").read_bytes()
        if expected_manifest is not None and raw != expected_manifest:
            raise ValueError("immutable run manifest changed")
        manifest = json.loads(raw)
        if not manifest.get("inputs"):
            raise ValueError("release has no frozen inputs")
        required = {
            "final/DKEntries.csv",
            "final/diagnostics.json",
            "final/assignments.json",
        }
        if not required <= set(manifest.get("artifacts", {})):
            raise ValueError("release lacks required final artifacts")
        if not {"salary", "entries", "evidence", "controls"} <= set(manifest["inputs"]):
            raise ValueError("release lacks its authoritative input tables")
        for group in ("inputs", "artifacts"):
            for record in manifest[group].values():
                rel = Path(record["path"])
                from pathlib import PureWindowsPath

                if (
                    rel.is_absolute()
                    or ".." in rel.parts
                    or PureWindowsPath(str(rel)).drive
                ):
                    raise ValueError("manifest path escapes the run")
                path = (run / rel).resolve(strict=True)
                if not path.is_relative_to(run) or not path.is_file():
                    raise ValueError("manifest artifact is outside the run")
                if digest(path.read_bytes()) != record["sha256"]:
                    raise ValueError("run artifact hash mismatch")
        diagnostics = json.loads((run / "final/diagnostics.json").read_bytes())
        if (
            diagnostics.get("export_sha256")
            != manifest["artifacts"]["final/DKEntries.csv"]["sha256"]
        ):
            raise ValueError("diagnostics/export binding differs")
        if (
            diagnostics.get("assignment_sha256")
            != manifest["artifacts"]["final/assignments.json"]["sha256"]
        ):
            raise ValueError("diagnostics/assignment binding differs")
        if any(
            diagnostics.get(k) is not True
            for k in (
                "FILE_VALID",
                "workflow_valid",
                "selection_certified",
                "allocation_certified",
            )
        ):
            raise ValueError("release certification failed")
        # Certificates are outputs, never caller assertions. Recompute legality
        # from the hash-checked input bytes on every publication/recovery.
        from datetime import datetime
        from .contracts import Controls, EvidenceBundle
        from .csvio import inspect_embedded_pool, parse_entries, parse_salary
        from .evidence import prepare
        from .referee import inspect_export

        frozen = {
            key: (run / record["path"]).read_bytes()
            for key, record in manifest["inputs"].items()
        }
        mode, players = parse_salary(frozen["salary"])
        template = parse_entries(frozen["entries"])
        if mode != template.mode:
            raise ValueError("release roster formats differ")
        inspect_embedded_pool(template, players)
        controls = Controls.model_validate_json(frozen["controls"])
        bundle = EvidenceBundle.model_validate_json(frozen["evidence"])
        expected_release = (
            "FIXTURE_DO_NOT_UPLOAD" if bundle.fixture else "MANUAL_REVIEW_REQUIRED"
        )
        if (
            diagnostics.get("MODEL_STATUS") != "PRIOR_ONLY"
            or diagnostics.get("economic_certification") is not False
            or diagnostics.get("RELEASE_DECISION") != expected_release
        ):
            raise ValueError("unsupported economic or release certification claim")
        for source in bundle.sources:
            if digest(frozen.get("source:" + source.source_id, b"")) != source.sha256:
                raise ValueError("release source provenance is missing or corrupt")
        when = datetime.fromisoformat(diagnostics["valid_as_of"])
        prepared = prepare(
            bundle, players, controls, when, manifest["metadata"]["fixture"]
        )
        final = (run / "final/DKEntries.csv").read_bytes()
        assignments = json.loads((run / "final/assignments.json").read_bytes())
        if assignments != {
            e.entry_id: list(e.roster) for e in parse_entries(final).entries
        }:
            raise ValueError("release assignments differ from the final CSV")
        validation = inspect_export(
            template,
            final,
            players,
            prepared,
            controls,
            when,
            set(manifest["metadata"]["mutable_entry_ids"]),
        )
        if validation["FILE_VALID"] is not True:
            raise ValueError(
                "release independently failed legality: "
                + "; ".join(validation["errors"])
            )
        return manifest

    def publish(
        self, scope: str, expected_parent: str | None, run: Path, manifest: dict
    ) -> Path:
        if any(c not in "0123456789abcdef" for c in scope) or len(scope) != 64:
            raise ValueError("invalid publication scope")
        self.save_manifest(run, manifest)
        self.verify_bundle(run.name)
        export = (run / "final/DKEntries.csv").read_bytes()
        payload = (run / "manifest.json").read_bytes()
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                if manifest["metadata"]["fixture"] is False:
                    from datetime import datetime, timezone

                    diagnostic = json.loads(
                        (run / "final/diagnostics.json").read_bytes()
                    )
                    now = datetime.now(timezone.utc)
                    if now < datetime.fromisoformat(
                        diagnostic["valid_as_of"]
                    ) or now >= datetime.fromisoformat(diagnostic["recheck_at"]):
                        raise ValueError(
                            "readiness boundary passed before publication; revalidate this snapshot"
                        )
                row = db.execute(
                    "SELECT run_id FROM current WHERE scope=?", (scope,)
                ).fetchone()
                current = row[0] if row else None
                if current != expected_parent:
                    raise RuntimeError(
                        "PARENT_CONFLICT: another run published first; rebase on its safe export"
                    )
                db.execute(
                    "INSERT INTO runs VALUES(?,?,?,?,?,?)",
                    (run.name, scope, payload, digest(payload), export, digest(export)),
                )
                db.execute(
                    "INSERT INTO current VALUES(?,?) ON CONFLICT(scope) DO UPDATE SET run_id=excluded.run_id",
                    (scope, run.name),
                )
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise
        return self.recover_safe(scope)

    def recover_safe(self, scope: str) -> Path:
        # Holding the transaction through mirror replacement prevents an older
        # recovery process from overwriting a newer committed export.
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                row = db.execute(
                    "SELECT r.run_id,r.manifest,r.manifest_hash,r.export,r.export_hash "
                    "FROM runs r JOIN current c ON r.run_id=c.run_id WHERE c.scope=?",
                    (scope,),
                ).fetchone()
                if not row:
                    raise ValueError("no committed safe export for this slate")
                if digest(row[1]) != row[2] or digest(row[3]) != row[4]:
                    raise ValueError("committed state hash mismatch")
                self.verify_bundle(row[0], row[1])
                safe = self.root / "safe" / scope / "latest_safe_export.csv"
                if not safe.exists() or digest(safe.read_bytes()) != row[4]:
                    atomic_write(safe, row[3])
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise
        return safe
