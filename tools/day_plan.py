#!/usr/bin/env python3
"""tools/day_plan.py -- one plan for the day's draftgroups, in lock order (R499).

THE DEFECT THIS CLOSES. 93 MLB entries locked blank in seven start-time blocks,
each starting after a draftgroup that was filled the same day (four Turbo, two
Showdown, one Classic satellite; CHANGELOG 2026-10-11). Nothing listed a day's
draftgroups: one DKEntries file is one draftgroup (DKM's embedded-pool check),
the deadline belongs to one build (`mlb_engine/pipeline/deadline.py`), and
`stage_slate` refuses a second DKEntries file (R70, exit 4). A session that had
just delivered one file had nothing telling it another draftgroup locked next.

WHAT IT DOES. Reads every DKEntries file for the date -- staged in
`data/slates/<date>/`, attached to the chat (`stage_slate.ATTACHMENT_ROOTS`), or
named with `--entries` -- identified by its header, never its name. Each file's
first lock comes from its own embedded player pool (`Game Info`), so no salary
file is needed. One row per draftgroup, sorted by deadline (first lock minus
F-1's five minutes): reserved, blank, complete and open rows, and the delivery
state read from the tracked records in `data/deliveries/<date>/`. The next
action is a baseline into every draftgroup with open rows, in deadline order,
before enhancing any (R389's baseline-first, applied across the day).

A row is OPEN unless its lineup is complete in the DKEntries file or a
delivered file filled it, so a partial file still names the entries that would
lock blank. "Inside T-30" is the engine's reading: under 30 minutes to the
DEADLINE, not to the lock (`build_slate.py`, `deadline_t30`).

WHAT IT CANNOT SEE. A draftgroup Ben reserved and never handed over. The plan
says so on every run; `skills/generate-lineups/SKILL.md` asks for each file by
name, and R496's blank report is the after-the-fact detector.

Bookkeeping over files Ben downloaded and the records the builds wrote: no
DraftKings access, never a claim about the slate.

Usage:
  python tools/day_plan.py --date YYYY-MM-DD [--entries PATH ...] [--now ISO]
                           [--attachment-root DIR ...] [--json] [--root DIR]

  --entries  a DKEntries file somewhere the search does not look (repeatable).
  --attachment-root  search this directory instead of the host's attachment
             locations (repeatable; tests pass an empty one).
  --now      an aware ISO instant to plan at instead of the clock (replay, tests).
  --root     the repo tree to read (default: this file's repo).

Exit codes: 0 nothing to act on; 1 a draftgroup that has not locked is inside
T-30 with open rows (named on the ACT NOW line); 2 bad arguments.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
for _p in (REPO_ROOT, REPO_ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

#: `build_slate.py`'s `deadline_t30` reads `minutes_to_deadline < 30` (R386).
T30_MINUTES = 30
#: Best last: a draftgroup's state is the best any record of it reached.
STATE_ORDER = ("none", "refused", "baseline", "review-grade", "certified")
SEES_ONLY = ("sees only the DKEntries files handed over: ask Ben to name every "
             "draftgroup he holds reserved entries in today, and for each missing "
             "file by name")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _now_et(now: Optional[datetime]) -> datetime:
    from mlb_engine.repo_env import now_et
    return now_et(now or _utcnow())


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# One DKEntries file
# ---------------------------------------------------------------------------

def _pool_columns(rows: Sequence[Sequence[str]]) -> Optional[Tuple[int, int, int]]:
    """(row index of the pool's header, its `Game Info` column, its `ID` column).

    DK puts the embedded pool's header on the file's header row or on a later
    entry row; DKM's `detect_player_pool_start` finds the `Position` cell, and
    the two columns are read by their labels, not by an offset from it.
    """
    from mlb_engine.entries.dk_entries_manager import detect_player_pool_start
    for i, row in enumerate(rows):
        start = detect_player_pool_start(row)
        if start is None:
            continue
        labels = [str(c).strip().lower() for c in row]
        try:
            return i, labels.index("game info", start), labels.index("id", start)
        except ValueError:
            return None
    return None


def read_template(path: Path) -> Optional[Dict[str, Any]]:
    """A DKEntries file's draftgroup facts, or None when it is not one."""
    from mlb_engine.entries.dk_entries_manager import (
        detect_entries_geometry, parse_dk_entry_rows)
    from mlb_engine.intake.slate_intake_manager import parse_game_info_datetime
    from stage_slate import ENTRIES_HEADER_PREFIX

    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle)
        header = next(reader, [])
        if [c.strip() for c in header[:4]] != ENTRIES_HEADER_PREFIX:
            return None
        rows = [header, *reader]
    contract, slots = detect_entries_geometry(rows[0])
    entries = parse_dk_entry_rows(path)

    locks, games, pool_ids = [], set(), set()
    cols = _pool_columns(rows)
    if cols is not None:
        head, gi_col, id_col = cols
        for row in rows[head + 1:]:
            info = row[gi_col].strip() if gi_col < len(row) else ""
            pid = row[id_col].strip() if id_col < len(row) else ""
            # `slate_signature`'s game rule, row for row: AWAY@HOME off the
            # first token, else the token itself, so a 'Postponed' cell counts
            # there and here alike and the two tags stay equal.
            token = info.split(" ", 1)[0]
            gid = token.upper() if "@" in token else token
            if gid:
                games.add(gid)
            if pid:
                pool_ids.add(pid)
            when = parse_game_info_datetime(info)
            if when is not None:
                locks.append(when)
    first_lock = min(locks) if locks else None
    # The tag `build_slate.slate_signature` and EP `_slate_tag` compute from a
    # salary file, computed here from the template's own pool so a delivery or
    # refusal record of the same draftgroup carries the same string.
    tag = (f"{first_lock.strftime('%H%M')}_{len(games)}g" if first_lock
           else f"{len(games)}g")
    if contract == "SHOWDOWN":
        tag += "_sd"
    contests = sorted({(e.contest_id, e.contest_name) for e in entries})
    key = ("pool:" + hashlib.sha1(",".join(sorted(pool_ids)).encode()).hexdigest()[:12]
           if pool_ids else "contests:" + ",".join(c for c, _ in contests))
    width = len(slots)
    return {
        "path": path, "contract": contract, "slots": width, "tag": tag,
        "first_lock": first_lock, "key": key, "contests": contests,
        "rows": {e.entry_id: sum(1 for c in e.roster_cells if c) for e in entries},
    }


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def _candidates(root: Path, date: str, attachment_roots: Optional[Iterable[str]],
                named: Sequence[str]) -> List[Tuple[Path, str]]:
    import stage_slate

    found: List[Tuple[Path, str]] = [(Path(p), "named") for p in named]
    staged = root / "data" / "slates" / date
    if staged.is_dir():
        found += [(p, "staged") for p in sorted(staged.glob("*.csv")) if p.is_file()]
    roots = stage_slate.ATTACHMENT_ROOTS if attachment_roots is None else tuple(attachment_roots)
    for _root, paths in stage_slate.attachment_candidates(roots):
        found += [(p, "attached") for p in paths]
    return found


def templates_for(root: Path, date: str, *, attachment_roots: Optional[Iterable[str]] = None,
                  named: Sequence[str] = ()) -> Tuple[List[Dict[str, Any]], List[str]]:
    """The date's DKEntries templates, one per distinct file, and what was skipped.

    A template belongs to the date when its first lock falls on it in ET. One
    with no readable lock is kept only when it was staged under the date or
    named on the command line, since nothing else ties it to the day.
    """
    seen: Dict[str, Dict[str, Any]] = {}
    reached: set = set()
    notes: List[str] = []
    for path, origin in _candidates(root, date, attachment_roots, named):
        try:
            real = path.resolve()
            if real in reached:  # the attachment roots nest: one file, one source
                continue
            reached.add(real)
            template = read_template(path)
            digest = _sha256(path) if template is not None else ""
        except (OSError, ValueError, csv.Error, UnicodeDecodeError) as exc:
            if origin == "named":
                notes.append(f"{path}: unreadable as a DKEntries file ({exc})")
            continue
        if template is None:
            if origin == "named":
                notes.append(f"{path}: not a DKEntries file (header)")
            continue
        if digest in seen:
            seen[digest]["sources"].append(f"{origin} {path.name}")
            continue
        lock = template["first_lock"]
        if lock is not None and lock.date().isoformat() != date:
            if origin == "named":
                notes.append(f"{path}: first lock {lock:%Y-%m-%d %H:%M} ET is not on "
                             f"{date}; left out")
            continue
        if lock is None and origin == "attached":
            continue
        template["sources"] = [f"{origin} {path.name}"]
        seen[digest] = template
    return list(seen.values()), notes


# ---------------------------------------------------------------------------
# Delivery state
# ---------------------------------------------------------------------------

def record_state(record: Mapping[str, Any]) -> str:
    row = record.get("manifest_row") or {}
    cert = str(row.get("certification") or "")
    if cert == "certified":
        return "certified"
    if row.get("lineage") == "baseline" or cert == "review_grade_baseline":
        return "baseline"
    return "review-grade"


def _merge(templates: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """One draftgroup per embedded pool; a row's best copy wins."""
    groups: Dict[str, Dict[str, Any]] = {}
    for t in sorted(templates, key=lambda t: (t["key"], str(t["path"]))):
        g = groups.setdefault(t["key"], {
            "key": t["key"], "contract": t["contract"], "slots": t["slots"],
            "tag": t["tag"], "first_lock": t["first_lock"], "contests": set(),
            "rows": {}, "sources": []})
        g["contests"].update(t["contests"])
        g["sources"] += t["sources"]
        for entry_id, filled in t["rows"].items():
            g["rows"][entry_id] = max(filled, g["rows"].get(entry_id, 0))
    return list(groups.values())


def build_plan(root: Path, date: str, now: Optional[datetime] = None, *,
               attachment_roots: Optional[Iterable[str]] = None,
               named: Sequence[str] = ()) -> Dict[str, Any]:
    from mlb_engine.entries.delivery_record import read_records
    from mlb_engine.intake.slate_intake_manager import DELIVERY_BUFFER_MINUTES

    now = _now_et(now)
    templates, notes = templates_for(root, date, attachment_roots=attachment_roots,
                                     named=named)
    groups = _merge(templates)
    records = read_records(root, date)
    deliveries = [r for r in records if r.get("kind") == "delivery"]
    refused_tags = {str(r.get("slate_tag") or "") for r in records
                    if r.get("kind") == "refusal"} - {""}
    matched: set = set()

    out = []
    for g in groups:
        ids = set(g["rows"])
        states, filled = {"none"}, set()
        for i, rec in enumerate(deliveries):
            rows = [e for e in rec.get("entries") or []
                    if isinstance(e, dict) and str(e.get("entry_id")) in ids]
            if not rows:
                continue
            matched.add(i)
            states.add(record_state(rec))
            # One completeness rule for the template and the record: every slot
            # of the format holds an id. The record's own `filled` is any id.
            filled |= {str(e["entry_id"]) for e in rows
                       if sum(1 for x in e.get("roster_ids") or [] if str(x).strip()) == g["slots"]}
        if g["tag"] in refused_tags:
            states.add("refused")
        state = max(states, key=STATE_ORDER.index)
        complete = sum(1 for n in g["rows"].values() if n == g["slots"])
        blank = sum(1 for n in g["rows"].values() if n == 0)
        open_ids = sorted(e for e, n in g["rows"].items() if n != g["slots"] and e not in filled)
        lock = g["first_lock"]
        deadline = lock - timedelta(minutes=DELIVERY_BUFFER_MINUTES) if lock else None
        # In UTC: two datetimes sharing one zone object subtract and compare as
        # wall clocks, which is an hour off across the DST change.
        utc_now = now.astimezone(timezone.utc)
        to_deadline = ((deadline.astimezone(timezone.utc) - utc_now).total_seconds() / 60.0
                       if deadline else None)
        locked = bool(lock and utc_now >= lock.astimezone(timezone.utc))
        inside = bool(lock and not locked and to_deadline < T30_MINUTES)
        if lock is None:
            clock = "lock unknown"
        elif locked:
            clock = "LOCKED"
        elif to_deadline >= 0:
            clock = f"T-{int(to_deadline)} to deadline"
        else:
            clock = f"T+{math.ceil(-to_deadline)} past deadline"
        contests = sorted(g["contests"])
        out.append({
            "tag": g["tag"], "format": g["contract"].title(), "key": g["key"],
            "first_lock": lock.isoformat() if lock else None,
            "deadline": deadline.isoformat() if deadline else None,
            "lock_et": lock.strftime("%H:%M") if lock else None,
            "deadline_et": deadline.strftime("%H:%M") if deadline else None,
            "minutes_to_deadline": round(to_deadline, 1) if to_deadline is not None else None,
            "clock": clock, "locked": locked, "inside_t30": inside,
            "reserved": len(g["rows"]), "blank": blank, "complete": complete,
            "partial": len(g["rows"]) - blank - complete, "open": len(open_ids),
            "open_entry_ids": open_ids,
            "fill": "complete" if not open_ids else f"open {len(open_ids)}",
            "state": state,
            "contests": [{"contest_id": c, "contest_name": n} for c, n in contests],
            "sources": g["sources"],
            "act_now": inside and bool(open_ids),
        })
    out.sort(key=lambda r: (r["deadline"] is None, r["deadline"] or "", r["tag"], r["key"]))

    ahead = [r for r in out if r["open"] and not r["locked"]]
    if ahead:
        text = ", then ".join(
            f"{r['tag']} (deadline {r['deadline_et'] or 'unknown'} ET, {r['open']} open)"
            for r in ahead)
        next_action = f"baseline into {text}, in deadline order, before enhancing any"
        short_next = "baseline " + ", then ".join(r["tag"] for r in ahead)
    elif out:
        unlocked = [r for r in out if not r["locked"]]
        locked_open = [r for r in out if r["open"] and r["locked"]]
        parts = []
        if unlocked:
            parts.append("every draftgroup on hand that has not locked has a lineup for "
                         "every reserved row; enhance in deadline order")
        if locked_open:
            parts.append("nothing left to act on in " + ", ".join(
                f"{r['tag']} ({r['open']} rows locked without a lineup)" for r in locked_open))
        elif not unlocked:
            parts.append("every draftgroup on hand has locked")
        next_action = "; ".join(parts)
        short_next = "enhance in deadline order" if unlocked else "nothing left to act on"
    else:
        next_action = (f"no DKEntries file staged or attached for {date}; ask Ben for "
                       f"every reserved draftgroup's file by name")
        short_next = "ask Ben for every reserved draftgroup's file by name"

    elsewhere: Dict[str, set] = {}
    for i, rec in enumerate(deliveries):
        if i not in matched:
            tag = str((rec.get("manifest_row") or {}).get("slate_tag") or "untagged")
            elsewhere.setdefault(tag, set()).add(record_state(rec))
    for tag in sorted(refused_tags - {r["tag"] for r in out}):
        elsewhere.setdefault(tag, set()).add("refused")
    return {
        "date": date, "now_et": now.strftime("%Y-%m-%d %H:%M"),
        "draftgroups": out, "next": next_action, "short_next": short_next,
        "act_now": [r for r in out if r["act_now"]],
        "recorded_without_template": {
            t: max(s, key=STATE_ORDER.index) for t, s in sorted(elsewhere.items())},
        "notes": notes,
        "labels": "bookkeeping over the files handed over and the delivery records; "
                  "never DraftKings access, never a claim about the slate",
    }


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def _act_line(plan: Mapping[str, Any]) -> str:
    return "ACT NOW: " + "; ".join(
        f"{r['tag']} {r['open']} open, deadline {r['deadline_et']} ET ({r['clock']})"
        for r in plan["act_now"])


def render(plan: Mapping[str, Any]) -> str:
    lines = [f"day plan {plan['date']} (now {plan['now_et'][11:]} ET; T counts to the "
             f"deadline, first lock minus 5): {len(plan['draftgroups'])} draftgroup(s)"]
    if plan["act_now"]:
        lines.append(_act_line(plan))
    for r in plan["draftgroups"]:
        first = r["contests"][0]["contest_name"] if r["contests"] else "?"
        more = len(r["contests"]) - 1
        lines.append(
            f"  {r['deadline_et'] or '--:--'} ET  {r['tag']:<12} {r['format']:<8} "
            f"lock {r['lock_et'] or '--:--'}  {r['clock']:<20} reserved {r['reserved']:>3}  "
            f"blank {r['blank']:>3}  complete {r['complete']:>3}  {r['fill']:<9} "
            f"state {r['state']:<12} {first}" + (f" (+{more} contests)" if more > 0 else ""))
    lines.append(f"next: {plan['next']}")
    if plan["recorded_without_template"]:
        lines.append("recorded on this date with no DKEntries file on hand: " + ", ".join(
            f"{t} ({s})" for t, s in plan["recorded_without_template"].items()))
    lines += [f"note: {n}" for n in plan["notes"]]
    lines.append(f"this plan {SEES_ONLY}")
    return "\n".join(lines)


def exit_code(plan: Mapping[str, Any]) -> int:
    return 1 if plan["act_now"] else 0


def hook_line(root: Optional[Path] = None, *, now: Optional[datetime] = None,
              attachment_roots: Optional[Iterable[str]] = None,
              build_claim: bool = False) -> Optional[str]:
    """The SessionStart line: printed when a BUILD claim is held or a DKEntries
    file for today is on hand, so a DEV session with neither sees nothing new.
    Never raises."""
    try:
        root = Path(root) if root is not None else REPO_ROOT
        now = _now_et(now)  # one clock reading for the date and the plan
        date = now.date().isoformat()
        plan = build_plan(root, date, now, attachment_roots=attachment_roots)
        if not plan["draftgroups"] and not build_claim:
            return None
        if not plan["draftgroups"]:
            return (f"day plan {date}: no DKEntries file staged or attached; {SEES_ONLY}; "
                    f"python tools/day_plan.py --date {date}")
        rows = ", ".join(f"{r['tag']} {r['fill']} {r['state']} {r['clock']}"
                         for r in plan["draftgroups"])
        act = f"{_act_line(plan)}; " if plan["act_now"] else ""
        return (f"day plan {date}: {act}{rows}; next: {plan['short_next']}; "
                f"python tools/day_plan.py --date {date}")
    except Exception as exc:  # noqa: BLE001 - a hook line must never take the briefing down
        return f"day plan: not measured ({type(exc).__name__})"


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--date", help="slate date YYYY-MM-DD (default: today in ET)")
    parser.add_argument("--entries", action="append", default=[],
                        help="a DKEntries file the search does not reach (repeatable)")
    parser.add_argument("--attachment-root", action="append", default=None,
                        help="search this directory instead of the host's attachment "
                             "locations (repeatable)")
    parser.add_argument("--now", help="an aware ISO instant to plan at (replay, tests)")
    parser.add_argument("--root", default=str(REPO_ROOT), help="the repo tree to read")
    parser.add_argument("--json", action="store_true", help="print the plan as JSON")
    args = parser.parse_args(argv)
    try:
        now = datetime.fromisoformat(args.now) if args.now else None
        now_et = _now_et(now)
        date = args.date or now_et.date().isoformat()
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError as exc:
        print(f"day_plan: {exc}", file=sys.stderr)
        return 2
    plan = build_plan(Path(args.root), date, now_et, named=args.entries,
                      attachment_roots=args.attachment_root)
    code = exit_code(plan)
    if args.json:
        print(json.dumps(dict(plan, exit_code=code), indent=1, sort_keys=True))
    else:
        print(render(plan))
    return code


if __name__ == "__main__":
    sys.exit(main())
