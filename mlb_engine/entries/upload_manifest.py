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
REPO_ROOT = Path(os.environ.get("MLB_DFS_ARTIFACT_ROOT", Path(__file__).resolve().parents[2])).resolve()


class CorruptManifestError(RuntimeError):
    """A manifest file exists on disk and cannot be parsed (R36 F6m).

    Raised only from the write path, and only when the corrupt bytes could not be
    preserved. A caller that sees this has NOT had its delivery recorded, which is
    the fail-closed state ``deliver`` already handles: the file keeps its
    ``DO_NOT_UPLOAD_`` name and the error text says why.
    """

# R96(2). The name a delivery file wears until a manifest row exists for it.
# Fail-open bookkeeping was the whole defect: every delivery path wrapped
# ``record_delivery`` in a try/except so a certified build could never be broken
# by a manifest write, which is right, but the file then landed under its
# uploadable name with nothing on it saying the record was missing. Six paths
# reached that state (see R96's table). The fix is ordering, not another guard:
# write to a name nobody would upload, record, and only then promote the name. A
# crash, an exception, or an early return anywhere in between leaves the
# DO_NOT_UPLOAD_ name, which is self-labelling instead of merely failing preflight
# later. ``showdown.write_showdown_entries`` already used this pattern internally
# for truncated writes; this generalizes it to the manifest.
UNRECORDED_PREFIX = "DO_NOT_UPLOAD_"


def unrecorded_name(dest: str | Path) -> Path:
    """The provisional path a delivery is written to before it has a row."""
    dest = Path(dest)
    if dest.name.startswith(UNRECORDED_PREFIX):
        return dest
    return dest.with_name(f"{UNRECORDED_PREFIX}{dest.name}")


def is_unrecorded_name(path: str | Path) -> bool:
    """True for a file that is labelling itself as having no manifest row."""
    return Path(path).name.startswith(UNRECORDED_PREFIX)


# R388(d). The label a Classic export earns when every gate it failed is S or
# P and every V gate passed on its bytes: legal, NOT certified, never
# upload-ready. Its own label rather than bare `review_grade`, whose preflight
# reason is Showdown's (R388(e) set one label per cause).
UNCERTIFIED_LABEL = "review_grade_uncertified"
#: Labels whose file did NOT pass its own gates; every other label did.
GATES_FAILED_LABELS = frozenset({UNCERTIFIED_LABEL, "not_certified"})


def passed_its_gates(certification: Any) -> bool:
    """True for a row whose file passed its own gates: `certified`, or a
    review-grade label a deadline rung or an accepted downgrade set (R388(e)).
    An unknown label counts as passing, the direction that never lets an
    UNCERTIFIED file replace it."""
    return str(certification or "") not in GATES_FAILED_LABELS


def live_gates_passing_row(date: str, contest_type: str,
                           slate_tag: str = "") -> Optional[Dict[str, Any]]:
    """R388(d). The newest live row for this slate whose file passed its
    gates, or None. An UNCERTIFIED file is never mirrored over one: the live
    file stays the delivery, and refinements go through late swap."""
    key = (str(contest_type).lower(), str(slate_tag or ""))
    manifest = read_manifest(date)
    live = [row for row in manifest.get("deliveries") or []
            if (row.get("contest_type"), row.get("slate_tag")) == key
            and row.get("status") != "superseded"
            and passed_its_gates(row.get("certification"))]
    return dict(live[-1]) if live else None


def recorded_delivery_row(date: str, sha256: str) -> Optional[Dict[str, Any]]:
    """R268(a). The newest row for these exact bytes, any status, or None. A
    late swap reads its parent's label and failing gates here, because a
    downgrade label lives on the row, not in the run."""
    if not sha256:
        return None
    rows = [row for row in read_manifest(date).get("deliveries") or []
            if row.get("sha256") == sha256]
    return dict(rows[-1]) if rows else None


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
    """The manifest for ``date``, with CORRUPT distinguished from ABSENT (R36 F6m).

    This function used to answer both states with the same empty manifest. That
    erased the difference between "no delivery has ever been recorded here" and
    "the record exists and cannot be read", and the consequence was not merely a
    bad read: the next ``record_delivery`` wrote its one row over the top and
    every prior record's supersession history went with it. An obsolete file then
    sits at ``upload_ready`` as the apparent answer to "which file do I upload".

    An absent file still reads as empty, which is true. A file that EXISTS and
    does not parse reads as empty deliveries plus a ``corrupt`` block naming the
    path, the error and the byte count. Every existing reader goes on reading
    ``deliveries`` unchanged; a reader that cares about the difference now has it,
    and the write path refuses to overwrite bytes it could not preserve.
    """
    path = manifest_path(date)
    empty: Dict[str, Any] = {"version": VERSION, "date": str(date), "deliveries": []}
    try:
        raw = path.read_bytes()
    except OSError as exc:
        if path.exists():
            # Present but unreadable: still corrupt from every caller's point of
            # view, and the quarantine attempt below will fail loudly rather than
            # let a write destroy it.
            empty["corrupt"] = {"path": str(path), "error": f"{type(exc).__name__}: {exc}",
                                "bytes": None}
        return empty
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        empty["corrupt"] = {"path": str(path), "error": f"{type(exc).__name__}: {exc}",
                            "bytes": len(raw)}
        return empty
    if isinstance(data, list):  # tolerate a bare list written by an older caller
        return {"version": VERSION, "date": str(date), "deliveries": data}
    if not isinstance(data, dict):
        # Valid JSON, wrong shape. Nothing here can be read as deliveries and the
        # next write would replace it, so it is corrupt by the same argument.
        empty["corrupt"] = {"path": str(path),
                            "error": f"manifest is a {type(data).__name__}, not an object",
                            "bytes": len(raw)}
        return empty
    data.setdefault("deliveries", [])
    data.setdefault("date", str(date))
    return data


def quarantine_corrupt_manifest(date: str) -> str:
    """Copy an unreadable manifest aside before anything writes over it (R36 F6m).

    Create-only, UTC-stamped, and never a move: this mount grants create and
    truncate but not unlink (R109), and moving the file would be one more way to
    lose it. Returns the repo-relative quarantine path.

    Raises ``CorruptManifestError`` when the bytes cannot be read or the copy
    cannot be written, because at that point the only honest options are to leave
    the original alone and refuse. Losing a supersession history is the failure
    this whole function exists to prevent; refusing to record one delivery is
    recoverable and the caller self-labels it.
    """
    source = manifest_path(date)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = source.with_name(f"{source.stem}.corrupt.{stamp}.json")
    try:
        payload = source.read_bytes()
    except OSError as exc:
        raise CorruptManifestError(
            f"{source} is unreadable ({exc}) and its bytes could not be preserved; "
            f"nothing was written over it") from exc
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(f".{dest.name}.{uuid.uuid4().hex}.tmp")
        tmp.write_bytes(payload)
        os.replace(tmp, dest)
    except OSError as exc:
        raise CorruptManifestError(
            f"{source} is corrupt and could not be quarantined ({exc}); it was "
            f"left as it is rather than overwritten") from exc
    return repo_relative(dest)


def _write(path: Path, payload: Mapping[str, Any]) -> None:
    """tmp + os.replace: a manifest is read at T-5 and must never be half-written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(payload, indent=1, sort_keys=False) + "\n",
                   encoding="utf-8")
    os.replace(tmp, path)


def _mirror_to_delivery_record(date: str, record: Mapping[str, Any],
                               controls: Optional[Mapping[str, Any]],
                               relaxations: Optional[Mapping[str, Any]],
                               egress: str,
                               entries_source: Optional[Path] = None) -> None:
    """Project this delivery into the TRACKED record (R369).

    Written from here rather than from the three delivery tools because this is
    the one function all three already call -- `build_slate.py`, `late_swap.py`
    and the re-promotion path in this module. Three writers would be three
    places to forget.

    The manifest under `outputs/` remains the authority for the session that
    wrote it. This is its durable projection, and it exists because `outputs/`
    is gitignored and a cloud container is reclaimed at session end, so without
    it no build run there can ever be joined to its standings.

    Never raises and never blocks: the record is bookkeeping, the delivery is
    the deliverable.

    R387. ``entries_source`` is the file the row's sha256 was taken from. Inside
    ``deliver`` that is the provisional file, which is not promoted onto the
    row's ``delivered_file`` until after this returns, so reading the rosters
    from ``delivered_file`` read nothing on a first build and the previous
    build's lineups on a rebuild.
    """
    try:
        from mlb_engine.entries.delivery_record import write_delivery_record
        write_delivery_record(date=date, manifest_row=record,
                              run_id=record.get("run_id"), controls=controls,
                              relaxations=relaxations, egress=egress,
                              entries_source=entries_source)
    except Exception as exc:  # noqa: BLE001
        print(f"delivery_record: mirror skipped ({type(exc).__name__}: {exc})")


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
    hash_source: Optional[str | Path] = None,
    re_promoted_from: Optional[str] = None,
    controls: Optional[Mapping[str, Any]] = None,
    relaxations: Optional[Mapping[str, Any]] = None,
    egress: str = "",
    failing_gates: Optional[Sequence[str]] = None,
    refinement: bool = False,
) -> Dict[str, Any]:
    """Append one delivery record and supersede any prior record for the same slate.

    Supersession is keyed on (contest_type, slate_tag), which is the identity of
    the thing being delivered. A second Classic build for the same draftgroup
    replaces the first; a Showdown build for a different game does not touch it.

    R96(2). ``hash_source`` lets the row name the path the file is ABOUT to wear
    while the hash is taken from the provisional file that holds those bytes now.
    The record has to name the upload path, and the file cannot wear the upload
    path until the record exists, so one of the two has to be told where to look.
    A rename preserves bytes, so the hash is the same either way.

    R129. ``re_promoted_from`` names the run whose immutable ``final/`` produced
    these bytes when the row is a re-promotion rather than a fresh build. It is a
    recorded fact, not a waiver: the row is an ordinary appended delivery and it
    supersedes the current one the same way any other delivery does.

    R36 F6m. A manifest that exists and cannot be parsed is QUARANTINED before
    this function writes, and the fresh manifest says where the old bytes went.
    Raises ``CorruptManifestError`` when the quarantine fails, which the delivery
    path already degrades to "MANIFEST NOT RECORDED" with the file keeping its
    ``DO_NOT_UPLOAD_`` name.
    """
    path = Path(delivered_file)
    source = Path(hash_source) if hash_source is not None else path
    manifest = read_manifest(date)
    corrupt = manifest.pop("corrupt", None)
    if corrupt:
        quarantined = quarantine_corrupt_manifest(date)
        manifest["recovered_from_corrupt"] = {
            "quarantined_to": quarantined,
            "error": corrupt.get("error"),
            "bytes": corrupt.get("bytes"),
            "recovered_utc": datetime.now(timezone.utc).isoformat(),
            "note": ("the prior manifest could not be parsed; its bytes are at "
                     "quarantined_to and NO prior delivery record survives in this "
                     "file. Records below start from this delivery."),
        }
    record = {
        "delivered_file": repo_relative(path),
        "sha256": sha256_file(source) if source.exists() else None,
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
    if re_promoted_from:
        record["re_promoted_from"] = str(re_promoted_from)
    if failing_gates:
        # R388(d). The gates an UNCERTIFIED file failed, so preflight's note
        # and the delivery record can name them.
        record["failing_gates"] = sorted({str(g) for g in failing_gates})
    key = (record["contest_type"], record["slate_tag"])
    if record["certification"] == UNCERTIFIED_LABEL and not refinement:
        # R388(d), the backstop behind the mirror's own check: a BUILD that
        # failed its gates never supersedes, or merges into, one that passed
        # them. `deliver` catches this, so the file keeps its DO_NOT_UPLOAD_
        # name and the error says why. A late swap (``refinement``) is exempt:
        # it refines the file Ben entered, which may be an UNCERTIFIED one a
        # later certified build superseded, and its row is that entry's.
        passing = [p for p in manifest["deliveries"]
                   if (p.get("contest_type"), p.get("slate_tag")) == key
                   and p.get("status") != "superseded"
                   and passed_its_gates(p.get("certification"))]
        if passing:
            raise ValueError(
                f"refusing to record an {UNCERTIFIED_LABEL} delivery over the "
                f"live {passing[-1].get('certification')!r} row "
                f"{passing[-1].get('delivered_file')} for slate {key[1]!r}; that "
                f"file stays the delivery")
    for prior in manifest["deliveries"]:
        if (prior.get("contest_type"), prior.get("slate_tag")) != key:
            continue
        if prior.get("status") == "superseded":
            continue
        if prior.get("sha256") and prior["sha256"] == record["sha256"]:
            # The same bytes recorded twice is one delivery, not two.
            prior.update(record)
            # R388(d). `failing_gates` is set only on an UNCERTIFIED row, so a
            # later label for the same bytes must not inherit it.
            if "failing_gates" not in record:
                prior.pop("failing_gates", None)
            _write(manifest_path(date), manifest)
            _mirror_to_delivery_record(date, prior, controls, relaxations, egress,
                                       entries_source=source)
            return prior
        prior["status"] = "superseded"
        prior["superseded_by"] = record["delivered_file"]
        prior["superseded_utc"] = record["recorded_utc"]
    manifest["deliveries"].append(record)
    _write(manifest_path(date), manifest)
    _mirror_to_delivery_record(date, record, controls, relaxations, egress,
                               entries_source=source)
    return record


def stage_salary_for_delivery(date: str, salary_csv: str | Path,
                              slate_tag: str = "") -> Optional[str]:
    """Copy the delivery's salary export to ``data/slates/<date>/`` (R96(4)).

    This is what makes the contest MINEABLE and what R49's manifest-first
    resolution reads. Without it a recovered delivery is permanently
    ``standings_only``: `field_miner` globs ``data/slates/<date>/DKSalaries*.csv``
    and a delivered ``DKEntries_*.csv`` is not a salary source, so the evidence is
    degraded in a way no re-mine can undo. `build_slate.py` already staged; the
    engine mirror and the late-swap path did not, which is why the 2026-08-06
    1910_4g contests can never be mined.

    Tagged rather than bare, because DK runs several draftgroups a date and a bare
    ``DKSalaries.csv`` from one draftgroup silently answers for another. Returns
    the staged path, or None when there was nothing to stage. Never raises: this
    is bookkeeping and it runs beside a certified build.
    """
    try:
        source = Path(salary_csv)
        if not source.is_file():
            return None
        dest_dir = REPO_ROOT / "data" / "slates" / str(date)
        dest_dir.mkdir(parents=True, exist_ok=True)
        tag = str(slate_tag or "").strip().lstrip("_")
        dest = dest_dir / (f"DKSalaries_{tag}.csv" if tag else "DKSalaries.csv")
        payload = source.read_bytes()
        if dest.exists() and dest.read_bytes() == payload:
            return str(dest)
        tmp = dest.with_name(f".{dest.name}.{uuid.uuid4().hex}.tmp")
        tmp.write_bytes(payload)
        os.replace(tmp, dest)
        return str(dest)
    except Exception:  # noqa: BLE001 - staging must never fail a delivery
        return None


def deliver(*, date: str, dest: str | Path, write, salary_csv: Optional[str | Path] = None,
            **record_kwargs) -> Dict[str, Any]:
    """The one front door for a delivery file under ``outputs/<date>/`` (R96(2)).

    Ordering, in three steps that cannot be reordered without reopening R96:

    1. ``write(provisional)`` puts the bytes at ``DO_NOT_UPLOAD_<name>``.
    2. ``record_delivery`` writes the row, naming ``dest`` and hashing the
       provisional file.
    3. Only on a written row is the file promoted onto ``dest``.

    Every way this can go wrong leaves the file at the DO_NOT_UPLOAD_ name: a
    raising writer, a raising recorder, a crash between the two, or a caller that
    returns early before calling this at all. That is the property R96 asks for --
    a delivery file has a manifest row or it has a self-labelling name, never
    neither.

    ``write`` takes the provisional path and returns anything; a falsy return is
    not treated as failure, only an exception is, because the Showdown writer
    returns a report dict its caller inspects.

    Returns ``{"path", "recorded", "record", "staged_salary", "error"}``. ``path``
    is where the file actually is, which is what a caller should print and record
    in a brief. Never raises.
    """
    dest = Path(dest)
    provisional = unrecorded_name(dest)
    out: Dict[str, Any] = {"path": str(provisional), "recorded": False,
                           "record": None, "staged_salary": None, "error": ""}
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        out["write_report"] = write(provisional)
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"delivery write failed: {exc}"
        return out
    if not provisional.exists():
        out["error"] = ("the writer returned without producing "
                        f"{provisional.name}; nothing was delivered")
        return out
    try:
        out["record"] = record_delivery(date=date, delivered_file=dest,
                                        hash_source=provisional, **record_kwargs)
        out["recorded"] = True
    except Exception as exc:  # noqa: BLE001 - the file keeps the DO_NOT_UPLOAD_ name
        out["error"] = (f"MANIFEST NOT RECORDED: {exc}. {provisional.name} holds "
                        f"the lineups and is deliberately named so nobody uploads "
                        f"it; it was NOT promoted to {dest.name}")
        return out
    if salary_csv is not None:
        out["staged_salary"] = stage_salary_for_delivery(
            date, salary_csv, str(record_kwargs.get("slate_tag") or ""))
    try:
        os.replace(provisional, dest)
        out["path"] = str(dest)
    except OSError as exc:
        # The row exists and names dest, which does not exist yet. verify_manifest
        # reports exactly this as "recorded but missing", and the bytes are still
        # on disk under a name nobody uploads. Fail loud, lose nothing.
        out["error"] = (f"recorded but not promoted: {exc}; the row names "
                        f"{dest.name} and the bytes are at {provisional.name}")
    return out


def rename_recorded_delivery(date: str, old_path: str | Path,
                             new_path: str | Path) -> bool:
    """Point any row for ``old_path`` at ``new_path`` (R96, P6).

    ``build_slate.preserve_prior_slate`` moves a previous draftgroup's delivered
    file aside so a new build cannot overwrite it. That rename ORPHANED the row:
    the manifest went on naming a path that no longer existed while the renamed
    file sat there with no row, which is R96's state arrived at from the far side.
    Ben's call, 2026-08-11: the row follows the rename rather than the rename being
    refused, because refusing would block a BUILD mid-slate over bookkeeping and
    that inverts the fail-open-but-loud posture the delivery path already takes.

    The sha256 is untouched: a rename does not change bytes, and rehashing here
    would mask a file that changed underneath. Returns whether a row moved.
    """
    old_rel, new_rel = repo_relative(old_path), repo_relative(new_path)
    manifest = read_manifest(date)
    moved = False
    for record in manifest.get("deliveries", []):
        if record.get("delivered_file") != old_rel:
            continue
        record["delivered_file"] = new_rel
        record["renamed_from"] = old_rel
        record["renamed_utc"] = datetime.now(timezone.utc).isoformat()
        moved = True
    if moved:
        _write(manifest_path(date), manifest)
    return moved


def unrecorded_deliveries(date: str, root: Optional[Path] = None) -> List[str]:
    """DKEntries files under ``outputs/<date>/`` that no manifest row names (R96(3)).

    The reverse check. ARCHIVE is where an unrecorded delivery costs something --
    own-entry harvest fails silently and the slate can only ever be
    ``standings_only`` -- and it discovered this by hand five times across three
    months. Repo-relative, sorted, so the output is deterministic.

    A ``DO_NOT_UPLOAD_``-named file is NOT reported: that file is already saying
    what it is, and the whole point of R96(2) is that saying so is sufficient.
    Files in ``_``-prefixed directories are skipped for the same reason
    ``awaiting_standings`` skips them -- those are scratch, not deliveries.

    A date with NO manifest file at all reports nothing, deliberately. The manifest
    did not exist before 2026-07-25 and there are eleven such dates on disk; listing
    every file on them would put 20-odd permanent entries in a report whose whole
    value is that it is normally empty, and this project has already learned twice
    what happens to a warning the operator is trained to scroll past (R31's STALE
    line, R3(a)'s silent manifest print). An absent manifest is a different fact
    from a manifest that omits a file, and the caller reports it separately.
    """
    base = Path(root) if root is not None else REPO_ROOT
    date_dir = base / "outputs" / str(date)
    if not date_dir.is_dir():
        return []
    if not (date_dir / MANIFEST_NAME).is_file():
        return []
    recorded = {str(r.get("delivered_file") or "")
                for r in read_manifest(date).get("deliveries", [])}
    out: List[str] = []
    for path in sorted(date_dir.glob("DKEntries*.csv")):
        if is_unrecorded_name(path) or path.name.startswith("_"):
            continue
        rel = repo_relative(path)
        if rel not in recorded:
            out.append(rel)
    return out


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
    unverifiable: List[str] = []
    checked = 0
    manifest = read_manifest(date)
    if manifest.get("corrupt"):
        # R36 F6m. This used to return passed=True with checked=0, which reads as
        # "nothing recorded, nothing wrong" on the one file preflight cross-checks
        # against. An unreadable record is the worst state, not the empty one.
        return {"passed": False, "checked": 0, "date": str(date), "unverifiable": [],
                "problems": [f"{manifest['corrupt']['path']}: manifest is unreadable "
                             f"({manifest['corrupt']['error']}); no delivery on this "
                             f"date has verifiable provenance until it is quarantined "
                             f"and re-recorded"]}
    for record in manifest.get("deliveries", []):
        if record.get("status") == "superseded":
            continue
        target = REPO_ROOT / str(record.get("delivered_file") or "")
        if not target.exists():
            problems.append(f"{record.get('delivered_file')}: recorded but missing")
            continue
        # R228's class, second site. `checked += 1` ran before the guard, so a row
        # carrying no sha256 was counted as verified by a function whose whole
        # subject is "do they still hash the same". Absence gets its own list; it
        # does not join `problems`, because a row that never recorded a hash is a
        # thin record and not a drifted file, and conflating the two would trade
        # one false label for another.
        if not record.get("sha256"):
            unverifiable.append(
                f"{record.get('delivered_file')}: row records no sha256, so nothing "
                f"here can say whether the file changed after it was delivered")
            continue
        checked += 1
        if sha256_file(target) != record["sha256"]:
            problems.append(
                f"{record.get('delivered_file')}: on-disk sha256 differs from the "
                f"recorded one; the file changed after it was delivered")
    return {"passed": not problems, "checked": checked, "problems": problems,
            "unverifiable": unverifiable, "date": str(date)}
