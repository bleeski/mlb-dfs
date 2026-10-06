#!/usr/bin/env python3
"""promote_run.py -- deliver a run's immutable final/DKEntries.csv, again (R129).

Manifest supersession was a one-way door. A session that builds five variants and
picks the third has, by the time it picks, marked the third superseded: every
later build supersedes the earlier ones on (contest_type, slate_tag), which is
correct bookkeeping, and ``preflight_upload.py`` then correctly hard-fails with
"manifest marks this file superseded by <path>; do not upload it". Both halves are
right. What was missing was a legal transition between two true states, so the
only ways out were ``--no-manifest``, which waives the cross-check on a file that
DOES have a record and therefore misrepresents it, or rebuilding, which on
2026-08-15 could not reproduce because the bank had grown underneath it (R130).

The effect was worse than one lost delivery: it PENALIZED exploring alternatives.
The more variants a session builds, the more certainly its best one is superseded.
Filed twice from opposite directions -- a better variant that could not be
delivered (2026-08-15 2138_2g) and an earlier certified run that could not be
restored (2026-08-14, R98(3)'s restore remainder) -- one missing operation.

This tool is that operation. It copies ``runs/<run_id>/final/DKEntries.csv``, which
is immutable by contract, and APPENDS an ordinary delivery row carrying
``re_promoted_from: <run_id>``. No waiver, no status outside the closed set, no
edit to any prior row beyond the supersession every delivery already performs. The
record after this runs is true: this file is current, the one it replaced is
superseded, and the row says where the bytes came from.

Two things it deliberately does NOT do. It does not certify: certification is a
property of the run, it is copied from the run's own manifest, and a run that was
never certified promotes as ``not_certified`` with a loud line rather than being
refused, because refusing here would put this tool back in the business of
process preventing a lineup. And it does not upload. Nothing in this repo does.

Default destination is RUN-SCOPED (``DKEntries_<tag>_<run8>.csv``) so the canonical
path is not the only place a certified file can live; ``--canonical`` overwrites
the canonical name when that is what you want.

Exit codes: 0 promoted, 2 refused, 3 IO error, 4 promoted with an UNVERIFIED
immutability bind (``--force-unbound``; R228). Four is never success: it means the
bytes were delivered and the run manifest could not say they are the bytes it
recorded.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

VERSION = "1.0"


def _load_run_manifest(run_dir: Path) -> Dict[str, Any]:
    path = run_dir / "manifest.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(_refuse(f"run manifest unreadable at {path}: {exc}"))
    if not isinstance(data, dict):
        raise SystemExit(_refuse(f"run manifest at {path} is not an object"))
    return data


def _refuse(message: str) -> int:
    print(f"REFUSED  {message}")
    return 2


def run_rows(run_id: str, outputs_root: Path) -> List[Tuple[str, Dict[str, Any]]]:
    """Every upload-manifest row naming this run, oldest first, each with its
    slate date. A row names the run; whether it describes THESE bytes is
    `find_prior_row`'s question (R473)."""
    from mlb_engine.entries.upload_manifest import read_manifest

    rows: List[Tuple[str, Dict[str, Any]]] = []
    if not outputs_root.is_dir():
        return rows
    for date_dir in sorted(outputs_root.iterdir()):
        if not date_dir.is_dir():
            continue
        manifest = read_manifest(date_dir.name)
        if manifest.get("corrupt"):
            print(f"WARN  {date_dir.name}: manifest unreadable, skipped while "
                  f"looking for run {run_id} ({manifest['corrupt']['error']})")
            continue
        for row in manifest.get("deliveries", []):
            if str(row.get("run_id") or "") == run_id:
                rows.append((date_dir.name, row))
    return rows


def pick_prior_row(rows: Sequence[Tuple[str, Dict[str, Any]]], run_id: str,
                   sha256: str) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """The newest of ``rows`` that is the delivery of ``sha256`` under this run,
    and its slate date; ``(None, None)`` when no row records the bytes.

    The row is where ``date``, ``contest_type`` and ``slate_tag`` come from, and
    both filings of R129 have one: the variant that got superseded inside a
    session was delivered first, and the earlier certified run being restored was
    delivered when it was built. A run with no row is a run that was never
    delivered, and then the operator has to say which slate it belongs to, because
    guessing the slate identity is how a file lands under another draftgroup.

    R473. The row must carry the run's BYTES as well as its id. A run id alone
    picked the LAST row naming the run, and on 1400_4g that was a hand-recorded
    variant (7fdaa380, `review_grade_uncertified`) under the certified run
    0efaf97e, so the re-promotion took the variant's label, lineage, tier and
    strategy state. Rows that name the run but record other bytes are not read
    for any of those, and not for the slate either: a row that describes other
    bytes may sit under another slate tag, and `run()` says out loud which rows
    it left unread. Several rows can match (re-promoting a superseded run appends
    one with the same bytes); the newest is the live label.
    """
    from mlb_engine.entries.delivery_record import names_run_bytes

    best: Tuple[Optional[str], Optional[Dict[str, Any]]] = (None, None)
    for date, row in rows:
        if names_run_bytes(row, run_id, sha256):
            best = (date, row)
    return best


def _describe_rows(rows: Sequence[Tuple[str, Dict[str, Any]]]) -> str:
    """One clause per row, enough to find it: slate date, tag, bytes, label."""
    return "; ".join(
        f"{d} {r.get('slate_tag') or '-'} sha256 "
        f"{str(r.get('sha256') or '')[:12] or 'none'} "
        f"{r.get('certification') or 'no label'}" for d, r in rows)


def find_prior_row(run_id: str, outputs_root: Path,
                   sha256: str) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """The newest upload-manifest row that is the delivery of ``sha256`` under
    this run, and its slate date: `run_rows` then `pick_prior_row`, whose
    docstring says why the bytes are part of the key (R473). `run()` calls the
    two directly because it also needs the rows that name the run and record
    other bytes."""
    return pick_prior_row(run_rows(run_id, outputs_root), run_id, sha256)


def prior_delivery_record(run_id: str, date: str,
                          sha256: str) -> Optional[Dict[str, Any]]:
    """The latest delivery record for this run's bytes on this date, or None
    (R377). R473: matched on run AND sha256, because a run id keys one record per
    slate tag and a variant under another tag shares it while carrying other
    controls and another market."""
    from mlb_engine.entries.delivery_record import records_for_run_bytes

    best: Optional[Dict[str, Any]] = None
    for record in records_for_run_bytes(date, run_id, sha256):
        if best is None or str(record.get("recorded_utc") or "") > str(
                best.get("recorded_utc") or ""):
            best = record
    return best


def entries_facts(path: Path) -> Dict[str, Any]:
    """Contest ids, names and the entry count, counted off the delivered bytes.

    Never off the run's plan. The count preflight cross-checks has to be a fact
    about these bytes; that is what catches a truncated write.
    """
    from mlb_engine.entries.dk_entries_manager import parse_dk_entry_rows

    rows = parse_dk_entry_rows(path)
    return {
        "entries": len(rows),
        "contest_ids": sorted({str(r.contest_id) for r in rows}),
        "contest_names": sorted({str(r.contest_name or "") for r in rows}),
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Re-promote a run's immutable final/DKEntries.csv with a truthful manifest row.")
    p.add_argument("--run-id", required=True,
                   help="run id under runs/, e.g. 20260815T213800Z_ab12cd34")
    # One anchor, not three. runs/ and outputs/ are both derived from it, and it
    # rebinds upload_manifest.REPO_ROOT so the manifest is written under the same
    # tree the destination is in. Separate --runs-root/--outputs-root flags would
    # have moved the file and left the manifest behind in the real repo, which is
    # the class of split-truth this manifest exists to prevent.
    p.add_argument("--repo-root", default=str(REPO_ROOT),
                   help="tree holding runs/ and outputs/; testing and recovery only")
    p.add_argument("--date", default="",
                   help="slate date; required only when no manifest row names this run")
    p.add_argument("--tag", default=None,
                   help="slate tag; defaults to the tag on this run's prior row")
    p.add_argument("--dest", default="",
                   help="explicit destination path; overrides --canonical")
    p.add_argument("--canonical", action="store_true",
                   help="deliver onto the canonical DKEntries_<tag>.csv instead of a "
                        "run-scoped name")
    p.add_argument("--notes", default="")
    p.add_argument("--force-unbound", action="store_true",
                   help="promote even though the run manifest records no sha256 for "
                        "final/DKEntries.csv; the unverified bind is written onto the "
                        "manifest row and the exit code is 4, never 0 (R228)")
    p.add_argument("--dry-run", action="store_true",
                   help="print what would be written and touch nothing")
    p.add_argument("--json", action="store_true")
    return p


def run(args: argparse.Namespace) -> int:
    from mlb_engine.entries import upload_manifest as um
    from mlb_engine.entries.delivery_record import names_run_bytes
    from mlb_engine.entries.upload_manifest import (
        CorruptManifestError, deliver, repo_relative, sha256_file)

    root = Path(args.repo_root).resolve()
    if root != um.REPO_ROOT:
        um.REPO_ROOT = root
    runs_root, outputs_root = root / "runs", root / "outputs"

    run_id = str(args.run_id).strip()
    run_dir = runs_root / run_id
    source = run_dir / "final" / "DKEntries.csv"
    if not source.is_file():
        return _refuse(f"no final export at {source}; a run that never reached "
                       f"final/ has nothing to promote")

    run_manifest = _load_run_manifest(run_dir)
    cert = run_manifest.get("certification") or {}
    workflow_valid = bool(cert.get("workflow_valid"))
    certification = "certified" if workflow_valid else "not_certified"

    # The run's own manifest binds its bytes. A final/ export whose hash no longer
    # matches the run record is not immutable any more, and promoting it would
    # launder that.
    #
    # R228, 2026-08-30. THREE states, not two. A hash mismatch refused loudly; an
    # ABSENT artifacts row, or a row carrying no sha256, promoted with no check and
    # no message, because `if recorded_sha and ...` reads missing evidence as a
    # passing check. That is the same laundering the comment above forbids, with the
    # evidence missing instead of contradicted -- the R177/F16 fail-open class at the
    # one boundary CLAUDE.md calls immutable. The re-promotion path is where it bites:
    # a run manifest written by an older code path, or truncated by a killed writer,
    # promoted clean. Absence is now its own refusal, and the acknowledgment that
    # overrides it never returns 0.
    recorded = ((run_manifest.get("artifacts") or {}).get("final/DKEntries.csv") or {})
    recorded_sha = str(recorded.get("sha256") or "")
    actual_sha = sha256_file(source)
    if recorded_sha and recorded_sha != actual_sha:
        return _refuse(f"{source} hashes {actual_sha[:12]} but the run manifest "
                       f"records {recorded_sha[:12]}; the run's final export changed "
                       f"after it was written and is no longer the artifact it claims "
                       f"to be")
    unbound = not recorded_sha
    if unbound and not args.force_unbound:
        return _refuse(
            f"the run manifest at {run_dir / 'manifest.json'} records no sha256 for "
            f"final/DKEntries.csv, so nothing in the run binds the bytes being "
            f"promoted (they hash {actual_sha[:12]}). This is missing evidence, not "
            f"a check that passed: the immutability of runs/<id>/final/ is the whole "
            f"basis of this operation and here it is unverifiable. Rebuild the run, "
            f"or acknowledge with --force-unbound, which promotes, records the "
            f"unverified bind on the row, and exits 4 rather than 0")

    # R473. The row is the one that records THESE bytes under this run, never the
    # last row naming the run: a variant recorded under the run's id describes
    # other bytes, and its label, lineage, tier and strategy state are theirs.
    # Every read of `prior_row` below moves with this choice; nothing reads a row
    # that names the run and records other bytes.
    named = run_rows(run_id, outputs_root)
    prior_date, prior_row = pick_prior_row(named, run_id, actual_sha)
    unread = [(d, r) for d, r in named if not names_run_bytes(r, run_id, actual_sha)]
    date = str(args.date or prior_date or "").strip()
    if not date:
        if unread:
            return _refuse(
                f"no manifest row records these bytes (sha256 {actual_sha[:12]}) "
                f"under run {run_id}; {len(unread)} row(s) name the run but record "
                f"other bytes ({_describe_rows(unread)}). A row that describes other "
                f"bytes is not read for the slate, the label, the lineage or the "
                f"tier. Pass --date <slate date> --tag <slate tag> to say which slate "
                f"these entries belong to")
        return _refuse(f"no manifest row names run {run_id} and no --date was given; "
                       f"pass --date <slate date> --tag <slate tag> to say which slate "
                       f"these entries belong to")
    if unread:
        print(f"WARN  {len(unread)} manifest row(s) name run {run_id} but record "
              f"other bytes ({_describe_rows(unread)}); none of them lends its "
              f"label, lineage, tier or strategy state to this promotion")
    tag = args.tag if args.tag is not None else str((prior_row or {}).get("slate_tag") or "")
    contest_type = str((prior_row or {}).get("contest_type") or "classic")
    # R388(e), R377. A re-promotion restores bytes an earlier delivery already
    # recorded, and that delivery knew two things runs/<id>/manifest.json does
    # not: a review-grade label (a deadline rung, an accepted downgrade) and the
    # controls the build solved under. Re-deriving `certified` from
    # workflow_valid would upgrade the label; passing nothing empties the record.
    prior_cert = str((prior_row or {}).get("certification") or "")
    if workflow_valid and prior_cert.startswith("review_grade"):
        certification = prior_cert
    # R389(b). With no row left (outputs/ lost, another host), the run's own
    # metadata still names a governed or baseline label (`run_slate` writes
    # `certification_label` there, R268(a)), and a re-promotion never upgrades
    # it to `certified`. The row's lineage, else the run's, rides along, so a
    # re-promoted baseline supersedes baselines and never the enhanced file.
    run_meta = run_manifest.get("metadata") or {}
    meta_label = str(run_meta.get("certification_label") or "")
    if workflow_valid and certification == "certified" and \
            meta_label.startswith("review_grade"):
        certification = meta_label
    lineage = str((prior_row or {}).get("lineage")
                  or run_meta.get("delivery_lineage") or "")
    prior_record = prior_delivery_record(run_id, date, actual_sha) or {}

    facts = entries_facts(source)
    out_dir = outputs_root / date
    if args.canonical and lineage:
        # R389(b). `--canonical` is the enhanced file's name: writing a
        # baseline there would overwrite a file Ben may hold while its row
        # stays live under the old sha. A baseline re-promotes under its
        # run-scoped name.
        return _refuse(f"run {run_id} is a {lineage} delivery; --canonical would "
                       f"write it over the enhanced file's name. Re-promote it "
                       f"without --canonical (run-scoped name) or name a --dest")
    if args.dest:
        dest = Path(args.dest)
    elif args.canonical:
        dest = out_dir / (f"DKEntries_{tag}.csv" if tag else "DKEntries.csv")
    else:
        short = run_id.split("_")[-1][:8] or run_id[:8]
        stem = f"DKEntries_{tag}_{short}" if tag else f"DKEntries_{short}"
        dest = out_dir / f"{stem}.csv"

    plan = {
        "run_id": run_id, "date": date, "slate_tag": tag,
        "contest_type": contest_type, "certification": certification,
        "source": repo_relative(source), "dest": repo_relative(dest),
        "sha256": actual_sha, "entries": facts["entries"],
        "contest_ids": facts["contest_ids"],
        "prior_row_status": (prior_row or {}).get("status"),
        "immutability_bind": "unverified" if unbound else "verified",
    }

    # The row has to carry the fact, not just the console. A promotion whose bind
    # nothing verified is a different artifact from one whose bind held, and the
    # manifest is what preflight and the next session read.
    notes = str(args.notes or "")
    if unbound:
        unbound_note = (
            "R228: promoted with --force-unbound; the run manifest recorded no "
            "sha256 for final/DKEntries.csv, so the immutability bind on these "
            "bytes was NOT verified")
        notes = f"{notes}; {unbound_note}" if notes else unbound_note
        print(f"WARN  the run manifest records no sha256 for final/DKEntries.csv; "
              f"the immutability bind is UNVERIFIED and --force-unbound was given. "
              f"The manifest row will say so and the exit code is 4, not 0")

    if not workflow_valid:
        print(f"WARN  run {run_id} is NOT certified (workflow_valid false); it will "
              f"be recorded as not_certified and it is not upload-ready")
    if args.dry_run:
        print(json.dumps(plan, indent=1) if args.json else
              "\n".join(f"  {k}: {v}" for k, v in plan.items()))
        print("DRY RUN  nothing written")
        # A dry run reports what the real run would do, exit code included. Handing
        # back 0 here while the promotion itself would hand back 4 is the same
        # misreport this item exists to close, one command earlier.
        return 4 if unbound else 0

    def _write(provisional: Path) -> None:
        provisional.write_bytes(source.read_bytes())

    prior_extra = prior_record.get("extra") or {}
    try:
        result = deliver(
            date=date, dest=dest, write=_write,
            salary_csv=(run_dir / "inputs" / "DKSalaries.csv"),
            contest_type=contest_type, slate_tag=tag,
            contest_ids=facts["contest_ids"], contest_names=facts["contest_names"],
            entries=facts["entries"], run_id=run_id,
            # 'candidate' and not 'current': the closed status set has no
            # 'current', and a row preflight has not checked yet is exactly what
            # 'candidate' means. Preflight stamps 'upload_ready' on these bytes.
            status="candidate", certification=certification,
            projection_tier=str((prior_row or {}).get("projection_tier") or "unknown"),
            strategy_state=((prior_row or {}).get("strategy_state") or
                            {"state": "unknown", "counts": {}}),
            re_promoted_from=run_id,
            notes=notes,
            controls=prior_record.get("controls") or None,
            relaxations=prior_record.get("relaxations") or None,
            # R422(a). The market the run was ranked by, or a re-promotion
            # rewrites the tracked record without it.
            market=prior_extra.get("market") or None,
            # R434. The named stack's request and what seated, for the same reason.
            **({"stack_sleeve": prior_extra["stack_sleeve"]}
               if prior_extra.get("stack_sleeve") else {}),
            **({"lineage": lineage} if lineage else {}),
        )
    except CorruptManifestError as exc:
        return _refuse(str(exc))
    except OSError as exc:
        print(f"IO ERROR  {exc}")
        return 3

    plan["delivered_path"] = result.get("path")
    plan["recorded"] = result.get("recorded")
    plan["error"] = result.get("error")
    if args.json:
        print(json.dumps(plan, indent=1))
    if result.get("error"):
        return _refuse(result["error"])
    if not args.json:
        print(f"promote_run v{VERSION}  run {run_id} -> {result['path']}")
        print(f"  {facts['entries']} entries across {len(facts['contest_ids'])} "
              f"contest(s)  sha256={actual_sha[:12]}  {certification}")
        if prior_row is not None:
            print(f"  prior row for this run was '{prior_row.get('status')}'; a new "
                  f"row is appended and whatever was current is now superseded")
        print(f"  NEXT: python tools/preflight_upload.py --entries {result['path']} "
              f"--salary <salary.csv>")
    return 4 if unbound else 0


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except SystemExit as exc:  # _load_run_manifest raises with its own code
        return int(exc.code or 2)
    except OSError as exc:
        print(f"IO ERROR  {exc}")
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
