"""delivery_record.py -- the tracked record of a build, so an outcome can find it (R369).

THE DEFECT THIS CLOSES. `runs/` and `outputs/` are gitignored (`.gitignore:1-2`)
and a cloud container is reclaimed when the session ends. Three archive-side
links read only those trees:

  * entered contests, from `outputs/*/DKEntries*.csv`
    (`tools/awaiting_standings.py`, `scan_entered`)
  * Ben's Entry IDs, from `outputs/<date>/upload_manifest.json` AND the delivered
    file it names (`field_miner.harvest_own_entry_ids`, which calls
    `parse_dk_entry_rows` on that file)
  * the salary file a build used, via `runs/<run_id>/inputs/`
    (`field_miner.manifest_salary_candidates`)

So on the host that now runs most sessions, every build vanishes: the 2026-09-17
and 2026-09-18 cloud builds left hand-written fragments and nothing
machine-readable, and their delivered sha256 exists in no file in this repo. No
standings export can ever be joined back to them. That is not a reporting gap,
it is the whole archive-and-ledger loop going dark on the default host.

WHAT THIS IS. One small tracked JSON per delivery, written from inside
`upload_manifest.record_delivery` -- the one choke point every delivery tool
already calls -- carrying what the ephemeral trees hold and the archive needs:
the manifest row, the parsed entry rows, the input fingerprints, code identity,
the controls actually in force, and the host. Roughly 10-30 KB. The repo already
tracks contest IDs, Entry IDs and standings, so this adds a kind of fact it
holds rather than a new kind.

WHAT IT IS NOT. Not a second manifest: `outputs/<date>/upload_manifest.json`
stays the delivery authority for the session that wrote it, and this is its
durable projection. Not a place for bulky artifacts: no candidate banks, no
projections, no briefs. Not a secret store -- see `_SECRET_HINTS` below.

NEVER RAISES. This is bookkeeping running beside a certified build, the same
contract `stage_salary_for_delivery` already keeps. A record that cannot be
written must never be the reason a delivery fails; it reports and returns None.
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence

from mlb_engine.entries import upload_manifest as _upload_manifest
from mlb_engine.entries.upload_manifest import repo_relative, sha256_file

SCHEMA_VERSION = 1
DELIVERIES_DIR = "data/deliveries"


def _artifact_root() -> Path:
    """Where this delivery's artifacts live, read at CALL time.

    `upload_manifest.REPO_ROOT` honours ``MLB_DFS_ARTIFACT_ROOT``, which is how
    the gate (`tools/audit.py`, R338 repair 4) and `tests/conftest.py` keep a
    test run from publishing into the operator's own tree. Binding the value at
    import -- `from ... import REPO_ROOT`, which this module did first -- takes a
    COPY, so `conftest`'s in-process patch of that name never reached here and
    the suite wrote real records into a tracked directory. Read the attribute.
    """
    return _upload_manifest.REPO_ROOT


def _code_root() -> Path:
    """Where the CODE lives, which is a different question from the one above.

    Under an isolated artifact root the artifact tree is a temp directory with
    no git in it, and `git rev-parse HEAD` there answers nothing. The sha this
    module records is the sha of the engine that built the portfolio, so it is
    read from this file's own location and never from the artifact root.
    """
    return Path(__file__).resolve().parents[2]

#: Substrings that mark an environment variable as a secret. Nothing from the
#: environment is copied into a record, so this is belt and braces: the writer
#: scans its own output and refuses to write a record containing any of these
#: values. CLAUDE.md's wall is "never log, echo, or write API keys", and a
#: tracked file is the worst possible place to break it.
_SECRET_HINTS = ("KEY", "TOKEN", "SECRET", "PAT", "PASSWORD")


def deliveries_dir(root: Optional[Path] = None) -> Path:
    return (Path(root) if root is not None else _artifact_root()) / DELIVERIES_DIR


def _posix(path: str | Path) -> str:
    """A repo-relative path with forward slashes, on every host.

    `upload_manifest.repo_relative` returns `str(Path.relative_to(...))`, which
    is backslash-separated on Ben's Windows machine. A record written there and
    read in a Linux container would otherwise carry a path that resolves to a
    single filename containing backslashes.
    """
    return str(repo_relative(path)).replace("\\", "/")


def record_name(slate_tag: str, run_id: Optional[str]) -> str:
    tag = "".join(c if (c.isalnum() or c in "-_") else "_"
                  for c in str(slate_tag or "untagged"))
    return f"{tag}_{run_id or 'norun'}.json"


def code_identity() -> Dict[str, Any]:
    """What this build was built BY, which no live run record carries.

    `build_state_manager.runtime_environment` records the interpreter and the
    package versions -- the runtime -- and nothing records the code. The only
    `code_sha256` in the tree is in `mlb_engine/production/`, which is off the
    build path. Without this a replay cannot tell which engine produced a
    portfolio, so a grade cannot be attributed to a version.

    The dirty flag matters more than the sha: a delivery built from an
    uncommitted tree is not reproducible from any commit, and saying so is the
    difference between evidence and a guess.
    """
    out: Dict[str, Any] = {"git_sha": None, "git_dirty": None}
    try:
        code_root = _code_root()
        sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(code_root),
                             capture_output=True, text=True, timeout=15)
        if sha.returncode == 0:
            out["git_sha"] = sha.stdout.strip() or None
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=str(code_root),
                               capture_output=True, text=True, timeout=15)
        if dirty.returncode == 0:
            out["git_dirty"] = bool(dirty.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    # `optimizer_v3` carries no VERSION constant and is deliberately not given
    # one here: the lineup source of truth is not the place for a bookkeeping
    # field, and the git sha already identifies it exactly.
    for label, module, attr in (
        ("execution_pipeline", "mlb_engine.pipeline.execution_pipeline", "VERSION"),
        ("contest_allocator", "mlb_engine.allocate.contest_allocator", "VERSION"),
    ):
        try:
            mod = __import__(module, fromlist=[attr])
            out[label] = getattr(mod, attr, None)
        except Exception:  # noqa: BLE001 - identity is best-effort, never fatal
            out[label] = None
    return out


def host_identity() -> Dict[str, Any]:
    try:
        from mlb_engine.repo_env import host_profile
        profile = dict(host_profile())
        return {k: profile.get(k) for k in
                ("host", "call_budget_s", "declared_ceiling_s")}
    except Exception:  # noqa: BLE001
        return {}


def run_inputs(run_id: Optional[str], root: Optional[Path] = None) -> Dict[str, Any]:
    """The run's own input fingerprints, copied out of an ephemeral tree.

    `runs/<run_id>/manifest.json` already hashes what the build consumed. It is
    gitignored, so it dies with the container; this carries the hashes forward.
    Known limitation, recorded rather than papered over: R83's open rider says
    `snapshot_run_inputs` runs AFTER the originals are consumed, so these hashes
    prove the copied file rather than the causal input set.
    """
    if not run_id:
        return {}
    base = (Path(root) if root is not None else _artifact_root()) / "runs" / str(run_id)
    try:
        manifest = json.loads((base / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    inputs = {}
    for name, entry in (manifest.get("inputs") or {}).items():
        if isinstance(entry, Mapping):
            inputs[name] = {"sha256": entry.get("sha256"),
                            "size_bytes": entry.get("size_bytes"),
                            "source_path": str(entry.get("source_path") or "").replace("\\", "/")}
    return {"inputs": inputs,
            "environment": (manifest.get("environment") or {}),
            "certification": (manifest.get("certification") or {})}


def entry_rows(delivered_file: str | Path) -> list:
    """Entry ID, Contest ID and the roster, parsed from the delivered bytes.

    `field_miner.harvest_own_entry_ids` needs the FILE, not just the manifest
    row: it calls `parse_dk_entry_rows` on it to learn which Entry IDs were
    entered where. The file lives under `outputs/` and does not survive the
    container, so the rows ride here.

    `parse_dk_entry_rows` returns `DKEntryRow` DATACLASSES, not mappings. The
    first cut of this function filtered on `isinstance(row, Mapping)` and
    therefore dropped all eighteen rows of the fixture in silence, which is the
    failure this record exists to prevent, one layer in. Read the attributes.
    """
    try:
        from mlb_engine.entries.dk_entries_manager import parse_dk_entry_rows
        rows = parse_dk_entry_rows(str(delivered_file))
    except Exception:  # noqa: BLE001
        return []
    out = []
    for row in rows or []:
        entry_id = str(getattr(row, "entry_id", "") or "").strip()
        if not entry_id:
            continue
        roster = tuple(getattr(row, "roster_ids", ()) or ())
        out.append({
            "entry_id": entry_id,
            "contest_id": str(getattr(row, "contest_id", "") or "").strip(),
            "contest_name": str(getattr(row, "contest_name", "") or "").strip(),
            "entry_fee": getattr(row, "entry_fee", None),
            "roster_ids": [str(pid) for pid in roster],
            # A reserved row that was never filled is a FACT about the delivery
            # (CLAUDE.md: blank reserved rows block certification), so it is
            # recorded rather than dropped.
            "filled": bool(roster),
        })
    return out


def _carries_a_secret(text: str) -> Optional[str]:
    """The NAME of an environment secret whose value appears in ``text``.

    Names only, never the value: this function's own return is printed.
    """
    for name, value in os.environ.items():
        value = (value or "").strip()
        if len(value) < 8:
            continue  # too short to be a key, and prone to false positives
        if any(hint in name.upper() for hint in _SECRET_HINTS) and value in text:
            return name
    return None


def write_delivery_record(*, date: str, manifest_row: Mapping[str, Any],
                          run_id: Optional[str] = None,
                          controls: Optional[Mapping[str, Any]] = None,
                          relaxations: Optional[Mapping[str, Any]] = None,
                          egress: str = "",
                          root: Optional[Path] = None,
                          extra: Optional[Mapping[str, Any]] = None
                          ) -> Optional[Path]:
    """Write one delivery record. Returns its path, or None. Never raises."""
    try:
        base = deliveries_dir(root) / str(date)
        resolved_run = run_id or manifest_row.get("run_id")
        delivered = (Path(root) if root is not None else _artifact_root()) / str(
            manifest_row.get("delivered_file") or "")
        record = {
            "schema_version": SCHEMA_VERSION,
            "kind": "delivery",
            "date": str(date),
            "recorded_utc": datetime.now(timezone.utc).isoformat(),
            "manifest_row": {k: v for k, v in manifest_row.items()},
            "entries": entry_rows(delivered) if delivered.exists() else [],
            "run": run_inputs(resolved_run, root=root),
            "code": code_identity(),
            "host": host_identity(),
            "controls": dict(controls or {}),
            "relaxations": dict(relaxations or {}),
            "egress": str(egress or ""),
            "labels": ("deterministic review proxies and labeled priors only; "
                       "never ROI, win rate, cash rate, or probability"),
        }
        if extra:
            record["extra"] = dict(extra)
        record["manifest_row"]["delivered_file"] = _posix(
            manifest_row.get("delivered_file") or "")
        return _write(base,
                      record_name(str(manifest_row.get("slate_tag") or ""),
                                  resolved_run),
                      record)
    except Exception as exc:  # noqa: BLE001 - bookkeeping never fails a delivery
        print(f"delivery_record: not written ({type(exc).__name__}: {exc})")
        return None


def write_refusal_record(*, date: str, slate_tag: str, exit_code: int,
                         refusal: Optional[Mapping[str, Any]] = None,
                         root: Optional[Path] = None) -> Optional[Path]:
    """Record a build that produced no file. Never raises.

    A refusal is evidence too: "no delivery on this slate" and "no session ran"
    look identical in an archive that only records deliveries, and the first is
    a thing to learn from. Keyed by timestamp rather than run_id because most
    refusals happen BEFORE `create_run` mints one -- twelve of the thirteen
    refusal returns in `build_slate.py` are `return N, {}`.
    """
    try:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        record = {
            "schema_version": SCHEMA_VERSION,
            "kind": "refusal",
            "date": str(date),
            "recorded_utc": datetime.now(timezone.utc).isoformat(),
            "slate_tag": str(slate_tag or ""),
            "exit_code": int(exit_code),
            "refusal": dict(refusal or {}),
            "code": code_identity(),
            "host": host_identity(),
            "labels": ("a refusal is an observed build outcome, never a claim "
                       "about the slate"),
        }
        tag = record_name(str(slate_tag or ""), None).removesuffix("_norun.json")
        return _write(deliveries_dir(root) / str(date), f"{tag}_{stamp}.json", record)
    except Exception as exc:  # noqa: BLE001
        print(f"delivery_record: refusal not written ({type(exc).__name__}: {exc})")
        return None


def _write(base: Path, name: str, record: Mapping[str, Any]) -> Optional[Path]:
    text = json.dumps(record, indent=1, sort_keys=True, default=str)
    leaked = _carries_a_secret(text)
    if leaked:
        print(f"delivery_record: REFUSED to write, the record would contain the "
              f"value of {leaked}; nothing was written")
        return None
    base.mkdir(parents=True, exist_ok=True)
    target = base / name
    if target.exists() and target.read_text(encoding="utf-8") == text:
        return target  # idempotent: the same build recorded twice is one record
    target.write_text(text, encoding="utf-8")
    return target


def read_records(root: Optional[Path] = None, date: Optional[str] = None) -> list:
    """Every record, or one date's. Unreadable files are skipped, never fatal."""
    base = deliveries_dir(root)
    if not base.is_dir():
        return []
    dates = [base / str(date)] if date else sorted(
        p for p in base.iterdir() if p.is_dir())
    out = []
    for folder in dates:
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.json")):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(record, dict):
                record["_path"] = _posix(path)
                out.append(record)
    return out
