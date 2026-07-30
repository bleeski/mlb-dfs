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
        [--lineups data/slates/<date>/lineups_feed.json]  # auto-resolved
        [--locked-teams PIT,NYY]           # ADDS to the derived set, never shrinks it
        [--as-of 2026-07-25T18:40:00-04:00]  # wall clock used for the lock derivation
        [--json]

Exit 0 clean, 2 on any failure (matching preflight_upload), 3 on a usage or IO
error. This is a file check. It never uploads anything.

R29: the lock derivation is wall-clock, and re-derived on every invocation. It
used to be that ``--locked-teams``, when supplied, REPLACED the derivation. On
2026-07-29 a swap chain ran 7:23-8:02 PM ET against a list passed once at 7:23;
two more games locked underneath it, this tool passed the file, and DraftKings
rejected 7 of 16 entries. A verification tool that can go stale mid-use does
not verify. So the derivation always runs, ``--locked-teams`` is unioned in
rather than substituted, and a supplied list that omits a team the clock says
has started is reported as stale. The lineups feed is preferred over the salary
file's Game Info column because the feed knows a postponed game has not locked
and Game Info only knows when it was scheduled.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))
# The repo root too, so the lazy engine import in derive_locked_teams_from_feed
# resolves when this tool is run as a script. Without it the feed derivation
# fails as an ImportError and silently degrades to the Game Info fallback,
# which is the weaker source and cannot see a postponement.
sys.path.insert(1, str(Path(__file__).resolve().parents[1]))

from preflight_upload import (  # noqa: E402
    EntryRow, Report, advisory, check_legality, check_manifest,
    check_pool_membership, check_row_shape, check_status, load_entries,
    load_salary, parse_embedded_pool, parse_game_info_datetime,
    resolve_feed_for_slate, resolve_salary_from_promoted_run, sha256_of,
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

    This is the fallback source. It cannot tell a postponed game from a game in
    progress, because the salary CSV only records when the game was scheduled.
    """
    now_dt = now or datetime.now(timezone.utc)
    locked: set[str] = set()
    first_open: Optional[datetime] = None
    parsed_any = False
    for row in salary.values():
        team = str(row.get("TeamAbbrev") or "").strip().upper()
        start = parse_game_info_datetime(row.get("Game Info"))
        if not team or start is None:
            continue
        parsed_any = True
        if start <= now_dt:
            locked.add(team)
        elif first_open is None or start < first_open:
            first_open = start
    if not parsed_any:
        # An empty note is the signal the caller uses to say lock state is
        # underivable. "every game has started" against an empty locked set is a
        # self-contradiction, and it used to print exactly that.
        return set(), ""
    note = (f"next lock {first_open.strftime('%Y-%m-%d %H:%M ET')}"
            if first_open else "every game on this slate has started")
    return locked, note


def resolve_lineups_feed(
    explicit: Optional[str],
    salary_path: Path,
    entries: Sequence[EntryRow],
    salary: Dict[str, Dict[str, str]],
    rep: Report,
) -> Optional[Path]:
    """Where the lineups feed for this slate lives, or None.

    An explicit path wins. Otherwise a feed staged beside the salary file is
    preferred, because that pairing is what a build actually wrote. Failing
    that, the slate-date resolution is preflight's ``resolve_feed_for_slate``,
    imported rather than restated: it already picks the freshest feed for the
    date and already refuses when a file spans two slate dates, and two
    implementations of one rule is this project's named no-op failure class.
    """
    if explicit:
        return Path(explicit)
    sibling = salary_path.parent / "lineups_feed.json"
    if sibling.exists():
        rep.info["feed_autoresolve"] = f"staged beside the salary file: {sibling.name}"
        return sibling
    return resolve_feed_for_slate(entries, salary, rep)


def derive_locked_teams_from_feed(
    feed_path: Path,
    salary_path: Path,
    now: Optional[datetime] = None,
) -> Optional[tuple[set[str], str, set[str]]]:
    """(locked, note, not_locked) from the feed's clock, or None if unusable.

    This is the same source ``late_swap.py`` uses internally
    (``build_status_map_from_lineups_feed`` + a wall clock), so the tool that
    performs a swap and the tool that verifies it now read lock state off one
    fact rather than two.

    ``not_locked`` is the teams in games the feed reports postponed, cancelled or
    suspended. Their scheduled start has passed but no lineup in them is frozen,
    so treating them as locked would block a legal swap. It is returned
    separately rather than just omitted, because the caller unions this result
    with the salary file's clock and needs to know which absences are an
    affirmative "not locked" and which are merely games this feed does not cover.

    The engine import is lazy and its failure is not fatal, because this tool
    must still run when the engine does not.
    """
    try:
        from mlb_engine.intake.live_data_adapters import (  # noqa: E402
            build_status_map_from_lineups_feed,
        )
    except ImportError:
        return None
    try:
        feed = json.loads(feed_path.read_text(encoding="utf-8"))
        status = build_status_map_from_lineups_feed(feed, str(salary_path))
    except (OSError, ValueError, KeyError, TypeError):
        return None

    now_dt = now or datetime.now(timezone.utc)
    excluded = set(status.get("excluded_game_ids") or [])
    locked: set[str] = set()
    not_locked: set[str] = set()
    first_open: Optional[datetime] = None
    for game_id, lock_iso in (status.get("lock_time_by_game_id") or {}).items():
        teams = {t for t in str(game_id).split("@") if t}
        if game_id in excluded:
            not_locked |= teams
            continue
        try:
            lock_time = datetime.fromisoformat(str(lock_iso))
        except ValueError:
            continue
        if lock_time.tzinfo is None:
            lock_time = lock_time.replace(tzinfo=timezone.utc)
        if lock_time <= now_dt:
            locked |= teams
        elif first_open is None or lock_time < first_open:
            first_open = lock_time
    if not status.get("lock_time_by_game_id"):
        return None
    note = (f"next lock {first_open.astimezone(timezone.utc).strftime('%H:%M UTC')}"
            if first_open else "every game the feed covers has started")
    if excluded:
        note += f"; not locked (postponed/suspended): {', '.join(sorted(excluded))}"
    return locked, note, not_locked


def resolve_locked_teams(
    supplied: Optional[str],
    salary: Dict[str, Dict[str, str]],
    salary_path: Path,
    feed_path: Optional[Path],
    now: Optional[datetime],
    rep: Report,
) -> tuple[set[str], str, str]:
    """The locked set, its note, and which source produced it.

    A supplied ``--locked-teams`` is a union, never a substitution. Anything the
    clock says has started stays locked whether the operator remembered it or
    not; that asymmetry is the whole fix, because the failure mode is always a
    list that is missing a team, never one with a team too many.
    """
    # The salary file is the coverage floor: it lists every player on the slate,
    # so its Game Info column can always answer "has this team's game started".
    # The feed is more accurate but not guaranteed to be complete -- a
    # single-game Showdown feed can land at the same shared name a Classic slate
    # reads, and one for the wrong date parses cleanly. So the two are UNIONED,
    # and the only thing the feed is allowed to REMOVE is a game it explicitly
    # reports postponed, cancelled or suspended, which is the one fact Game Info
    # cannot carry. A source that can only add, plus one that can only subtract
    # on an affirmative signal, is the same asymmetry --locked-teams gets below,
    # for the same reason: the failure that ships a bad file is always a locked
    # team missing from the set.
    from_clock, clock_note = derive_locked_teams(salary, now)
    derived = set(from_clock)
    note = clock_note or ""
    source = "salary Game Info"
    if feed_path is not None:
        from_feed = derive_locked_teams_from_feed(feed_path, salary_path, now)
        if from_feed is None:
            rep.warn(f"lineups feed at {feed_path} was unusable (unreadable, no "
                     f"games, or the engine is not importable); locked teams "
                     f"come from the salary Game Info column alone, which cannot "
                     f"see a postponement")
        else:
            feed_locked, feed_note, not_locked = from_feed
            missing = sorted(derived - feed_locked - not_locked)
            derived |= feed_locked
            derived -= not_locked
            source = f"lineups feed {feed_path.name} + salary Game Info"
            note = feed_note
            if missing:
                rep.warn(f"the lineups feed does not cover {missing}, whose "
                         f"scheduled start has passed per the salary file; they "
                         f"stay locked. A feed that covers fewer games than the "
                         f"salary file is the wrong feed for this slate (a "
                         f"single-game Showdown feed at the shared name, or the "
                         f"wrong date)")
    if not derived and not str(note).strip():
        rep.warn("no lineups feed and no parsable Game Info: lock state is "
                 "underivable, so a slot touching a started game cannot be "
                 "detected. Pass --lineups.")
        source = "none"

    if supplied is None:
        return derived, note, source

    operator = {t.strip().upper() for t in supplied.split(",") if t.strip()}
    stale = sorted(derived - operator)
    if stale:
        rep.warn(f"STALE --locked-teams: {sorted(operator)} omits {stale}, whose "
                 f"game the {source} says has already started. The derived set "
                 f"is used anyway; a hand-passed list goes stale while a swap "
                 f"chain runs, which is how 7 of 16 entries were rejected on "
                 f"2026-07-29")
    extra = sorted(operator - derived)
    if extra:
        rep.info["locked_teams_operator_only"] = extra
    return operator | derived, f"{source} + operator", source


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
    ap.add_argument("--lineups",
                    help="lineups feed JSON; auto-resolved from the salary file's "
                         "directory or data/slates/<date>/ when omitted")
    ap.add_argument("--locked-teams",
                    help="teams to treat as locked IN ADDITION to the wall-clock "
                         "derivation; comma-separated. It cannot shrink the "
                         "derived set, because a hand-passed list goes stale")
    ap.add_argument("--as-of", dest="as_of",
                    help="ISO timestamp used to decide which games have started; "
                         "defaults to now")
    ap.add_argument("--now", dest="as_of",
                    help="deprecated alias for --as-of")
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
        if args.as_of:
            now = datetime.fromisoformat(args.as_of)
            if now.tzinfo is None:
                now = now.replace(tzinfo=timezone.utc)
        feed_path = resolve_lineups_feed(
            args.lineups, salary_path, entries, salary, rep)
        if args.lineups and not feed_path.exists():
            raise ValueError(f"--lineups {feed_path} does not exist")
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

    locked, lock_note, lock_source = resolve_locked_teams(
        args.locked_teams, salary, salary_path, feed_path, now, rep)
    rep.info["locked_teams"] = sorted(locked)
    rep.info["lock_note"] = lock_note
    rep.info["lock_source"] = lock_source
    rep.info["lock_as_of"] = (now or datetime.now(timezone.utc)).isoformat()
    rep.info["lineups_feed"] = str(feed_path) if feed_path else None
    if lock_source == "none":
        rep.warn("no lineups feed and no parsable Game Info: lock state is "
                 "underivable, so a slot touching a started game cannot be "
                 "detected. Pass --lineups.")

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
        print(f"  lock clock: as of {rep.info['lock_as_of']} via {lock_source}")
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
