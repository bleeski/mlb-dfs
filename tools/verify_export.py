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

  - the locked-set derivation itself: which teams have started, and which games
    a lineups source affirmatively reports postponed
  - per-entry slot-change counts

R324: the parent-transition rule is NOT one of them any more. It was implemented
here (`check_parent_slots`: did a CHANGED slot introduce or rewrite a started
player) and again in `preflight_upload` (`check_started_games`: does ANY slot
hold one), and the two disagreed on exactly the file this tool exists for. A
swap after the first game's first pitch retains started players in its frozen
slots, which is legal and which this tool passed, while preflight -- the tool
CLAUDE.md names as THE pre-upload rule -- exited 2 on the same bytes. The rule
now lives once, in `preflight_upload.check_parent_transition`, stated as a
transition: an unchanged slot passes whatever its lock state, a CHANGED slot
needs both its old and its new player known-not-locked, an unreadable clock
refuses a change, a postponed game is exempt (R314), and an initial build is the
all-empty parent -- which collapses to R287's blanket rule, salary file only, no
lineups source and no parent needed. Both tools call it and neither implements
any part of it.

The parent is resolved from the manifest's supersession chain when --parent is
omitted, and the manifest is found next to the entries file when --manifest is
omitted (R72(ii)). Both were opt-in, and the two checks above are exactly the
ones that ran only if the operator remembered the flag at T-5.

Everything else (row accounting, duplicate Entry IDs, header geometry, blank and
partially-filled rows, DK Status, embedded-pool overlap, cap, slot eligibility,
duplicate persons, two-game minimum, five-hitters-per-team, hitter-versus-
rostered-SP, Showdown both-teams and recomputed captain price, and the
confirmed-lineup contradiction check) comes from preflight and is reported the
same way.

R46: that last one was missing here until 2026-08-04, which is the wrong tool to
be missing it -- a file this tool verifies is by definition one changed close to
lock. On 2026-08-03 a bench player seated off a 35-day-stale platoon projection
(ARI had not posted at build time) rode two certified entries to the edge of
upload; preflight held the check but read a feed that still said tbd, and this
tool had no such check at all. The feed it already resolves for the lock
derivation is the same input the check needs.

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
        [--parent runs/<id>/final/DKEntries.csv]   # auto-resolved from the manifest
        [--manifest outputs/<date>/upload_manifest.json]  # found beside --entries
        [--lineups data/slates/<date>/lineups_feed.json]  # auto-resolved
        [--feed-lenient]                   # confirmed-lineup contradiction warns
        [--locked-teams PIT,NYY]           # ADDS to the derived set, never shrinks it
        [--as-of 2026-07-25T18:40:00-04:00]  # wall clock used for the lock derivation
                                             # (or 18:40; a stamp with no offset
                                             #  is ET, per preflight's parse_as_of)
        [--json]

Exit 0 clean, 2 on any failure, 3 on a usage or IO error, 4 acknowledged
(--force printed the failures and did not block). The codes and the rule behind
them are preflight_upload's, imported rather than restated: --force never returns
0, because exit 0 is the one signal automation trusts (R2, extended here by R52 --
this tool used to fall through to `return 0` on a forced run and read as clean).
This is a file check. It never uploads anything.

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
# The repo root too. This was added for the lazy engine import in
# derive_locked_teams_from_feed, which moved to preflight_upload under R324 and
# resolves the root itself now; the insert stays because the reason still holds
# for anything else run from here as a script, and because losing it degrades
# that derivation to the Game Info fallback in SILENCE -- the weaker source,
# which cannot see a postponement.
sys.path.insert(1, str(Path(__file__).resolve().parents[1]))

from preflight_upload import (  # noqa: E402
    EntryRow, Report, advisory, check_feed, check_legality, check_manifest,
    check_parent_transition, check_pool_membership, check_row_shape, check_status,
    derive_locked_teams_from_feed, load_entries, load_salary, parse_as_of,
    parse_declared_pitcher_args, parse_embedded_pool, parse_game_info_datetime,
    resolve_declared_pitchers, resolve_feed_for_slate, resolve_feed_source,
    resolve_salary_from_promoted_run, sha256_of, verdict_exit_code,
)

# R324. `derive_locked_teams_from_feed` moved into `preflight_upload` with the
# shared helper, because R314's postponed exemption needs its `not_locked` half
# in BOTH referees and two readers of "which games are postponed" is this
# project's named no-op failure class. It is imported above rather than
# re-implemented, so `verify_export.derive_locked_teams_from_feed` still
# resolves for `repair_entry`, which imports it from here.

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


# R305. The lock derivation above needs a FILE (it reads per-game status for a
# postponement, which only a fetched feed carries). The posted-lineup check needs
# EVIDENCE, and on a DK-covered slate the best evidence is the salary file's own
# Starting column, which is not a file at all. Two resolvers, one for each
# question, rather than one Path serving both and being wrong for one of them.


def resolve_locked_teams(
    supplied: Optional[str],
    salary: Dict[str, Dict[str, str]],
    salary_path: Path,
    feed_path: Optional[Path],
    now: Optional[datetime],
    rep: Report,
) -> tuple[set[str], str, str, set[str]]:
    """The locked set, its note, which source produced it, and ``not_locked``.

    A supplied ``--locked-teams`` is a union, never a substitution. Anything the
    clock says has started stays locked whether the operator remembered it or
    not; that asymmetry is the whole fix, because the failure mode is always a
    list that is missing a team, never one with a team too many.

    R314. ``not_locked`` -- the teams in games a lineups source affirmatively
    reports postponed, cancelled or suspended -- was computed here, subtracted,
    and thrown away, so the one fact that distinguishes a postponed game from a
    game in progress never reached the started-game rule. It is RETURNED now and
    passed to the shared helper as its exemption set. Subtracting it from the
    locked set is not enough on its own: the helper re-reads each player's own
    Game Info clock, and a postponed game's scheduled start has passed, so
    without the affirmative fact the player reads LOCKED again.

    An operator who names a team in ``--locked-teams`` OUTRANKS the exemption
    for that team, which keeps R29's asymmetry intact in both directions: the
    flag may add a lock, and nothing derived may take one the operator asserted
    away.
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
    # R314. Empty means "no such observation", which is NOT the same fact as
    # "no game is postponed" (R237). Only a lineups source can carry it, so with
    # no feed it stays empty and the salary clock decides alone, exactly as
    # before this value existed.
    not_locked_teams: set[str] = set()
    if feed_path is not None:
        from_feed = derive_locked_teams_from_feed(feed_path, salary_path, now)
        if from_feed is None:
            rep.warn(f"lineups feed at {feed_path} was unusable (unreadable, no "
                     f"games, or the engine is not importable); locked teams "
                     f"come from the salary Game Info column alone, which cannot "
                     f"see a postponement")
        else:
            feed_locked, feed_note, not_locked = from_feed
            not_locked_teams = set(not_locked)
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
        return derived, note, source, set(not_locked_teams)

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
    return (operator | derived, f"{source} + operator", source,
            set(not_locked_teams) - operator)


def resolve_parent_from_manifest(entries_path: Path, manifest_path: Optional[Path],
                                 rep: Report) -> Optional[Path]:
    """The delivery this file refines, read off the manifest's supersession chain.

    R72(ii). The locked-game membership check ran only ``if args.parent`` -- so on
    a refinement verified without that flag, nothing re-checked whether a changed
    entry introduced a player from a game that had already started. (R324 closed
    the remaining half of that: with no parent at all, the shared helper now runs
    the initial-build case rather than nothing.) This tool already refuses to let
    its two most
    consequential inputs be opt-in (``--locked-teams`` is unioned rather than
    substituted per R29, and the feed auto-resolves) for one reason, stated in the
    module header: a check that runs only when the operator remembers a flag is a
    check that does not run at T-5. The parent was the last opt-in input.

    The chain is structured, not parsed from prose: the superseded record names
    its successor in ``superseded_by``, so the parent of THIS file is the record
    that points at it. (The child's own ``notes`` string also mentions a parent
    run path, but a notes field is not a contract and is not read here.) An
    explicit ``--parent`` always wins; this only fills the gap.
    """
    if manifest_path is None:
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None                      # check_manifest reports unreadable records
    records = manifest if isinstance(manifest, list) else manifest.get("deliveries", [])
    name = entries_path.name
    for rec in records:
        successor = str(rec.get("superseded_by") or "").strip()
        if not successor or Path(successor).name != name:
            continue
        for candidate in (REPO_ROOT / str(rec.get("delivered_file") or ""),
                          REPO_ROOT / "runs" / str(rec.get("run_id") or "")
                          / "final" / "DKEntries.csv"):
            if candidate.exists():
                rep.info["parent_source"] = (
                    f"manifest supersession chain ({name} supersedes "
                    f"{Path(str(rec.get('delivered_file') or '')).name})")
                return candidate
        rep.warn(f"the manifest says this file supersedes "
                 f"{rec.get('delivered_file')}, but that file is not on disk and "
                 f"neither is the run snapshot for {rec.get('run_id')}; "
                 f"locked-slot preservation is unverified")
        return None
    return None


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--entries", required=True)
    ap.add_argument("--salary", help="defaults to the promoted run's inputs snapshot")
    ap.add_argument("--parent", help="prior delivered file, to diff against; "
                                     "auto-resolved from the manifest's "
                                     "supersession chain when omitted")
    ap.add_argument("--manifest", help="outputs/<date>/upload_manifest.json; "
                                       "found next to the entries file when omitted")
    ap.add_argument("--feed-lenient", action="store_true",
                    help="a rostered player absent from a confirmed posted lineup "
                         "warns instead of failing (R4/R46 default is to fail)")
    ap.add_argument("--expect-entries", type=int)
    ap.add_argument("--expect-contest-type", choices=["classic", "showdown"])
    ap.add_argument("--brief", help="build brief holding declared_pitchers for "
                                    "this delivery; auto-matched by "
                                    "delivered_sha256 among sibling "
                                    "build_brief*.json files")
    ap.add_argument("--declare-pitcher", action="append", metavar="ID=ROLE",
                    help="state a declared arm by hand when there is no brief "
                         "to read, for example "
                         "43815489=viable_bulk_or_alt_sp. Repeatable. A "
                         "declared pitcher absent from the posted lineup is an "
                         "acknowledged warning, never a failure; an undeclared "
                         "one still fails")
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
                    help="print failures and exit 4 (acknowledged, not clean); "
                         "never exits 0 with failures present")
    args = ap.parse_args(argv)

    rep = Report()
    try:
        entries_path = Path(args.entries)
        # Parsed HERE rather than at the point of use: a malformed ID=ROLE is a
        # usage error and the exit-code contract says usage errors are 3, which
        # only this block returns.
        hand_declared = parse_declared_pitcher_args(args.declare_pitcher or ())
        contest, slots, entries, raw_rows, entry_id_rows = load_entries(entries_path)

        if args.salary:
            salary_path = Path(args.salary)
        else:
            # R234. The SECOND site of the same unvalidated auto-resolve. R191
            # named only preflight_upload; the class had two members and this
            # one is the weaker checker on exactly the files it exists for
            # (R175), so it would have inherited the wrong-slate answer in
            # silence after the sibling was fixed.
            resolved, why = resolve_salary_from_promoted_run(
                REPO_ROOT / "runs", contest=contest,
                rostered={pid for e in entries for pid in e.cells if pid})
            if resolved is None:
                raise ValueError(
                    f"no --salary given and the promoted run's snapshot was NOT "
                    f"used: {why}. Pass --salary explicitly; checking these "
                    f"entries against another slate's file answers a different "
                    f"question")
            salary_path = resolved
            rep.info["salary_source"] = "promoted run snapshot"
        salary = load_salary(salary_path)

        # R292(c). One reader for --as-of, and it is preflight's, imported like
        # every other shared rule in this file. This block read a naive stamp as
        # UTC while preflight read the same characters as ET: a bare `19:40`
        # became 15:40 ET here, so every game that started between 16:05 and
        # 19:40 read as still open and the introduced-from-a-started-game check
        # went quiet on exactly the files this tool exists for. Game Info carries
        # ET and nothing else, so ET is the right reading; and `parse_as_of` also
        # accepts a bare `HH:MM`, which this block raised on.
        now = parse_as_of(args.as_of) if args.as_of else None
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

    # The manifest sits next to the delivered file; preflight already finds it
    # without being told and this tool required the flag. Same reason as the
    # parent below: an opt-in input is not an input at T-5.
    manifest_path = Path(args.manifest) if args.manifest else None
    if manifest_path is None:
        sibling = entries_path.resolve().parent / "upload_manifest.json"
        if sibling.exists():
            manifest_path = sibling
            rep.info["manifest_source"] = "found next to the entries file"
    rep.info["manifest_file"] = str(manifest_path) if manifest_path else None

    # Everything preflight checks, checked identically here.
    check_row_shape(entries, entry_id_rows, len(slots), rep, args.expect_entries)
    check_pool_membership(entries, salary, parse_embedded_pool(raw_rows),
                          args.min_pool_overlap, rep)
    check_status(entries, salary, rep)
    details = check_legality(contest, slots, entries, salary, rep)
    if manifest_path is not None:
        check_manifest(entries_path, entries, manifest_path, rep)

    locked, lock_note, lock_source, not_locked = resolve_locked_teams(
        args.locked_teams, salary, salary_path, feed_path, now, rep)
    rep.info["locked_teams"] = sorted(locked)
    rep.info["not_locked_teams"] = sorted(not_locked)
    rep.info["lock_note"] = lock_note
    rep.info["lock_source"] = lock_source
    lock_clock = now or datetime.now(timezone.utc)
    rep.info["lock_as_of"] = lock_clock.isoformat()
    rep.info["lineups_feed"] = str(feed_path) if feed_path else None
    if lock_source == "none":
        rep.warn("no lineups feed and no parsable Game Info: lock state is "
                 "underivable, so a slot touching a started game cannot be "
                 "detected. Pass --lineups.")

    # R46: the confirmed-lineup contradiction check, imported rather than
    # reimplemented. It existed in preflight only, so a swap verified with this
    # tool -- the tool whose whole subject is a file changed close to lock -- never
    # cross-checked a seated player against a team's posted lineup. Same feed this
    # tool already resolves for the lock derivation.
    #
    # R114: the declarations ride along for the same reason. This tool verifies
    # late-swap output, and a swap inherits the build's declared arms; reading
    # them in preflight only would have left the two checkers disagreeing on one
    # file, which is the failure class R52 already found here once.
    if hand_declared:
        declared_pitchers = hand_declared
        rep.info["declared_pitchers_source"] = "--declare-pitcher"
    else:
        declared_pitchers = resolve_declared_pitchers(
            entries_path, rep.info["entries_sha256"], args.brief, rep)
    # R305. This tool and preflight_upload resolved the SAME wrong feed for the
    # same file on 2026-09-04 because both already called one function; the
    # typed compatibility join and the DK-Starting preference land in that same
    # function so the two referees cannot drift back apart.
    feed_source = resolve_feed_source(entries, salary, salary_path,
                                      args.lineups, rep)
    if feed_source is None:
        rep.warn("no lineups feed resolved; the posted-lineup cross-check did "
                 "not run. " + str(rep.info.get("feed_autoresolve") or ""))
    elif not isinstance(feed_source, (str, Path)):
        check_feed(entries, salary, feed_source, not args.feed_lenient, rep,
                   declared_pitchers=declared_pitchers)
    elif Path(feed_source).exists():
        check_feed(entries, salary, feed_source, not args.feed_lenient, rep,
                   declared_pitchers=declared_pitchers)
    else:
        rep.warn(f"feed {feed_source} does not exist; posted-lineup cross-check "
                 f"skipped")

    parent_path = Path(args.parent) if args.parent else None
    if parent_path is None:
        parent_path = resolve_parent_from_manifest(entries_path, manifest_path, rep)
    rep.info["parent_file"] = str(parent_path) if parent_path else None

    parent_entries: Optional[Sequence[EntryRow]] = None
    if parent_path is not None:
        try:
            _, _, loaded_parent, _, _ = load_entries(parent_path)
        except (OSError, ValueError) as exc:
            rep.fail(f"parent unreadable ({exc}); this file cannot be verified as a swap")
        else:
            parent_entries = loaded_parent or None

    # R324. ONE call, both cases, and the branch that used to choose between two
    # rules is gone.
    #
    # It used to read: with a parent, `check_parent_slots` asked the sharper
    # question (did a CHANGED slot introduce or rewrite a started player); with
    # none, R287's blanket rule ran instead, because started players sitting in
    # UNCHANGED slots are the normal, legal content of a late-swap file and a
    # blanket refusal would fail every legal swap after first pitch. Both halves
    # were right and the pair was the defect: `preflight_upload` ran the blanket
    # rule UNCONDITIONALLY, including with `--parent`, so the two referees
    # disagreed on exactly the file this tool exists for, and CLAUDE.md's
    # "before any upload, run the preflight" left the operator `--force`.
    #
    # The transition helper states both halves as one rule -- an initial build is
    # the all-empty parent, where every filled slot is a placement and a
    # placement refuses a locked player -- so there is nothing left to keep in
    # agreement. R314's exemption and F19's unknown-clock refusal live in the
    # same function for the same reason: three rules on one input.
    parent_detail = check_parent_transition(
        entries, parent_entries, salary, lock_clock, rep,
        exempt_teams=not_locked, locked_teams=locked)
    if parent_entries is None and locked:
        rep.warn(f"{len(locked)} team(s) have already started and no --parent "
                 f"was given or resolvable from the manifest; locked-slot "
                 f"preservation is unverified (every started slot is a hard "
                 f"failure above, so a passing file has none to preserve)")

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
            print(f"\nACKNOWLEDGED  {len(rep.failures)} failure(s) overridden by "
                  f"--force; this file is not blocked and it is not clean. Exit 4.")

    return verdict_exit_code(rep.failures, args.force)


if __name__ == "__main__":
    raise SystemExit(main())
