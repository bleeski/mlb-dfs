#!/usr/bin/env python3
"""verify_export.py -- check a DKEntries upload file, with a parent to diff against.

These checks were hand-written inline twice on 2026-07-22, under deadline, which is
exactly when a reconstructed check is least trustworthy. They belong in one
reviewable place.

That place is now ``tools/preflight_upload.py``. Everything both tools check is
implemented there once and imported here, because two implementations of one rule
is this project's named no-op failure class: they diverge, and the weaker one
reports success. What lives here is only what is specific to verifying a file
against the file it refines:

  - locked-slot preservation against a parent export
  - no player introduced from a game that has already started, with the locked
    set derived from the salary file's Game Info rather than a hand-passed flag
  - per-entry slot-change counts

Everything else (row accounting, duplicate Entry IDs, header geometry, blank and
partially-filled rows, DK Status, embedded-pool overlap, cap, slot eligibility,
duplicate persons, two-game minimum, five-hitters-per-team, hitter-versus-
rostered-SP, Showdown both-teams and recomputed captain price) comes from
preflight and is reported the same way.

What this tool used to do wrong, and no longer does: it skipped every row shorter
than the expected width, so a truncated file printed PASS with two of sixteen rows
silently dropped; duplicate Entry IDs overwrote each other in a dict; Contest Name
and Contest ID were never read, so a wrong-contest assignment was invisible; three
Classic legality rules the engine enforces were absent; stack sizes were reported
without being asserted; ``int(p["Salary"])`` crashed on a blank cell; and the
locked-teams check was a no-op unless the operator remembered a flag.

Usage:
    python tools/verify_export.py --entries DKEntries.csv
        [--salary DKSalaries.csv]          # defaults to the promoted run snapshot
        [--parent runs/<id>/final/DKEntries.csv]
        [--manifest outputs/<date>/upload_manifest.json]
        [--locked-teams PIT,NYY]           # overrides the Game Info derivation
        [--now 2026-07-25T18:40:00-04:00]  # for testing the lock derivation
        [--json]

Exit 0 clean, 2 on any failure (matching preflight_upload), 3 on a usage or IO
error. This is a file check. It never uploads anything.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

from preflight_upload import (  # noqa: E402
    EntryRow, Report, advisory, check_legality, check_manifest,
    check_pool_membership, check_row_shape, check_status, load_entries,
    load_salary, parse_embedded_pool, parse_game_info_datetime,
    resolve_salary_from_promoted_run, sha256_of,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def derive_locked_teams(
    salary: Dict[str, Dict[str, str]],
    now: Optional[datetime] = None,
) -> tuple[set[str], Optional[str]]:
    """Teams whose game has already started, read from the salary file's clock.

    The old ``--locked-teams`` flag made the most consequential check in this
    tool opt-in, at the moment the operator is least likely to remember it. DK's
    Game Info column already carries the start time; derive from it and let the
    flag override rather than enable.
    """
    now_dt = now or datetime.now(timezone.utc)
    locked: set[str] = set()
    first_open: Optional[datetime] = None
    for row in salary.values():
        team = str(row.get("TeamAbbrev") or "").strip().upper()
        start = parse_game_info_datetime(row.get("Game Info"))
        if not team or start is None:
            continue
        if start <= now_dt:
            locked.add(team)
        elif first_open is None or start < first_open:
            first_open = start
    note = (f"next lock {first_open.strftime('%Y-%m-%d %H:%M ET')}"
            if first_open else "every game on this slate has started")
    return locked, note


def check_parent_slots(
    entries: Sequence[EntryRow],
    parent: Sequence[EntryRow],
    salary: Dict[str, Dict[str, str]],
    locked_teams: set[str],
    rep: Report,
) -> Dict[str, Dict[str, object]]:
    """Contest identity, slot churn, and no new player from a started game."""
    parent_by_id = {e.entry_id: e for e in parent}
    detail: Dict[str, Dict[str, object]] = {}

    missing = sorted(set(parent_by_id) - {e.entry_id for e in entries})
    if missing:
        rep.fail(f"entries present in the parent but absent here: {missing[:10]}")

    for e in entries:
        p = parent_by_id.get(e.entry_id)
        if p is None:
            rep.warn(f"{e.entry_id}: no matching entry in the parent; this row is new")
            continue
        row: Dict[str, object] = {}
        # Contest identity. A swap that moves an entry to a different contest has
        # changed the objective the lineup was built for, and the only prior
        # signal for it was a slot-change count.
        if p.contest_id != e.contest_id:
            rep.fail(f"{e.entry_id}: contest reassigned from {p.contest_id} "
                     f"({p.contest_name}) to {e.contest_id} ({e.contest_name})")
        if p.contest_name != e.contest_name and p.contest_id == e.contest_id:
            rep.warn(f"{e.entry_id}: contest {e.contest_id} name changed from "
                     f"{p.contest_name!r} to {e.contest_name!r}")
        changed = sum(1 for a, b in zip(p.cells, e.cells) if a != b)
        row["slots_changed"] = changed

        before = set(p.cells)
        added = [pid for pid in e.cells
                 if pid and pid not in before
                 and str(salary.get(pid, {}).get("TeamAbbrev") or "").upper() in locked_teams]
        row["new_from_locked_games"] = len(added)
        if added:
            names = [f"{salary[pid].get('Name')} ({salary[pid].get('TeamAbbrev')})"
                     for pid in added if pid in salary]
            rep.fail(f"{e.entry_id}: introduced {names} from an already-started game")

        # A slot that changed but whose player was already locked is a rewrite of
        # a frozen slot, which DK rejects and which the swap contract forbids.
        relocked = [a for a, b in zip(p.cells, e.cells)
                    if a and a != b
                    and str(salary.get(a, {}).get("TeamAbbrev") or "").upper() in locked_teams]
        if relocked:
            names = [salary.get(pid, {}).get("Name", pid) for pid in relocked]
            rep.fail(f"{e.entry_id}: replaced {names}, whose game has already started")
        detail[e.entry_id] = row
    return detail


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--entries", required=True)
    ap.add_argument("--salary", help="defaults to the promoted run's inputs snapshot")
    ap.add_argument("--parent", help="prior delivered file, to diff against")
    ap.add_argument("--manifest", help="outputs/<date>/upload_manifest.json")
    ap.add_argument("--expect-entries", type=int)
    ap.add_argument("--expect-contest-type", choices=["classic", "showdown"])
    ap.add_argument("--locked-teams",
                    help="override the Game Info derivation; comma-separated")
    ap.add_argument("--now", help="ISO timestamp used to decide which games have started")
    ap.add_argument("--min-pool-overlap", type=float, default=0.95)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="print failures and exit 0")
    args = ap.parse_args(argv)

    rep = Report()
    try:
        entries_path = Path(args.entries)
        contest, slots, entries, raw_rows, entry_id_rows = load_entries(entries_path)

        if args.salary:
            salary_path = Path(args.salary)
        else:
            resolved = resolve_salary_from_promoted_run(REPO_ROOT / "runs")
            if resolved is None:
                raise ValueError(
                    "no --salary given and no snapshot under the promoted run's "
                    "inputs/; pass --salary explicitly")
            salary_path = resolved
            rep.info["salary_source"] = "promoted run snapshot"
        salary = load_salary(salary_path)

        now = None
        if args.now:
            now = datetime.fromisoformat(args.now)
            if now.tzinfo is None:
                now = now.replace(tzinfo=timezone.utc)
    except (OSError, ValueError) as exc:
        print(f"ERROR  {exc}", file=sys.stderr)
        return 3

    rep.info["contest_type"] = contest
    rep.info["entries_file"] = str(entries_path)
    rep.info["salary_file"] = str(salary_path)
    rep.info["entries_sha256"] = sha256_of(entries_path)

    if args.expect_contest_type and args.expect_contest_type != contest:
        rep.fail(f"declared contest type '{args.expect_contest_type}' but the "
                 f"file's header geometry is {contest}")

    # Everything preflight checks, checked identically here.
    check_row_shape(entries, entry_id_rows, len(slots), rep, args.expect_entries)
    check_pool_membership(entries, salary, parse_embedded_pool(raw_rows),
                          args.min_pool_overlap, rep)
    check_status(entries, salary, rep)
    details = check_legality(contest, slots, entries, salary, rep)
    if args.manifest:
        check_manifest(entries_path, entries, Path(args.manifest), rep)

    if args.locked_teams is not None:
        locked = {t.strip().upper() for t in args.locked_teams.split(",") if t.strip()}
        lock_note = "operator-supplied"
    else:
        locked, lock_note = derive_locked_teams(salary, now)
    rep.info["locked_teams"] = sorted(locked)
    rep.info["lock_note"] = lock_note

    parent_detail: Dict[str, Dict[str, object]] = {}
    if args.parent:
        try:
            _, _, parent_entries, _, _ = load_entries(Path(args.parent))
        except (OSError, ValueError) as exc:
            rep.fail(f"parent unreadable ({exc}); this file cannot be verified as a swap")
            parent_entries = []
        if parent_entries:
            parent_detail = check_parent_slots(entries, parent_entries, salary,
                                               locked, rep)
    elif locked:
        rep.warn(f"{len(locked)} team(s) have already started and no --parent was "
                 f"given; locked-slot preservation is unverified")

    for d in details:
        d.update(parent_detail.get(str(d.get("entry_id")), {}))

    report = {
        "tool": "verify_export", "passed": not rep.failures,
        "contest_type": contest, "entries": len(entries),
        "failures": rep.failures, "warnings": rep.warnings,
        "info": rep.info, "lineups": details,
        "advisory": advisory(contest, entries, salary),
    }

    if args.json:
        print(json.dumps(report, indent=1, default=str))
    else:
        print(f"verify_export  {contest} {len(entries)} entries  "
              f"sha256={rep.info['entries_sha256'][:12]}")
        print(f"  salary: {salary_path}"
              + (f"  [{rep.info['salary_source']}]" if rep.info.get("salary_source") else ""))
        print(f"  locked teams ({lock_note}): "
              + (", ".join(sorted(locked)) if locked else "none"))
        for d in details:
            if d.get("status") != "checked":
                print(f"{d['entry_id']}  {str(d.get('status', '?')).upper()}")
                continue
            changed = f" chg={d['slots_changed']}" if "slots_changed" in d else ""
            print(f"{d['entry_id']}  ${d.get('salary')}{changed} "
                  f"elig={d.get('slot_eligible')} dup={d.get('duplicate_person')} "
                  f"stack={d.get('stack')}")
        print()
        for w in rep.warnings:
            print(f"WARN  {w}")
        for f in rep.failures:
            print(f"FAIL  {f}")
        if not rep.failures:
            print(f"PASS  {len(entries)} {contest} entries, all checks clean")
        elif args.force:
            print(f"\nFORCED  {len(rep.failures)} failure(s) overridden by --force")

    if rep.failures and not args.force:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
