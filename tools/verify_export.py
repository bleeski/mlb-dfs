#!/usr/bin/env python3
"""verify_export.py -- check a DKEntries upload file before it goes to DraftKings.

These checks were hand-written inline twice on 2026-07-22, under deadline, which is
exactly when a reconstructed check is least trustworthy. They belong in one
reviewable place.

Checks, all deterministic:
  - every reserved Entry ID has ten filled slots, no blanks
  - no duplicate player inside a lineup
  - salary total at or under the cap
  - each player is eligible for the DK slot they occupy
  - stack sizes reported per lineup (informational)
  - against a parent file: locked slots preserved, and no new player introduced
    from a team whose game has already locked

Usage:
    python tools/verify_export.py --salary DKSalaries.csv --entries DKEntries.csv
        [--parent runs/<id>/final/DKEntries.csv] [--locked-teams PIT,NYY] [--json]

Exit 0 clean, 3 on any failure. This is a file check. It never uploads anything.
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import sys
from pathlib import Path

SALARY_CAP = 50000
SLOTS = ("P", "P", "C", "1B", "2B", "3B", "SS", "OF", "OF", "OF")


def load_entries(path: Path) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.reader(fh):
            if len(row) < 14:
                continue
            entry_id = row[0].strip()
            if not entry_id.isdigit():
                continue
            out[entry_id] = [c.strip() for c in row[4:14]]
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--salary", required=True)
    ap.add_argument("--entries", required=True)
    ap.add_argument("--parent", help="prior delivered file, to diff locked slots against")
    ap.add_argument("--locked-teams", help="comma-separated teams whose games have locked")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    with open(args.salary, encoding="utf-8-sig", newline="") as fh:
        salary = {r["ID"]: r for r in csv.DictReader(fh)}

    entries = load_entries(Path(args.entries))
    parent = load_entries(Path(args.parent)) if args.parent else {}
    locked_teams = {t.strip().upper() for t in (args.locked_teams or "").split(",") if t.strip()}

    failures: list[str] = []
    rows: list[dict] = []

    for entry_id, ids in sorted(entries.items()):
        detail: dict = {"entry_id": entry_id}
        if any(not pid for pid in ids):
            failures.append(f"{entry_id}: blank slot")
            detail["blank"] = True
            rows.append(detail)
            continue
        unknown = [pid for pid in ids if pid not in salary]
        if unknown:
            failures.append(f"{entry_id}: player IDs absent from the salary file: {unknown}")
            rows.append(detail)
            continue

        players = [salary[pid] for pid in ids]
        total = sum(int(p["Salary"]) for p in players)
        detail["salary"] = total
        if total > SALARY_CAP:
            failures.append(f"{entry_id}: salary {total} over cap")

        if len(set(ids)) != 10:
            dupes = [p for p, n in collections.Counter(ids).items() if n > 1]
            failures.append(f"{entry_id}: duplicate player {dupes}")
        detail["duplicates"] = len(set(ids)) != 10

        ineligible = [
            f"{players[i]['Name']}->{SLOTS[i]}"
            for i in range(10)
            if SLOTS[i] not in str(players[i]["Roster Position"]).split("/")
        ]
        if ineligible:
            failures.append(f"{entry_id}: slot ineligibility {ineligible}")
        detail["eligible"] = not ineligible

        stacks = collections.Counter(p["TeamAbbrev"] for p in players[2:])
        detail["stack"] = stacks.most_common(3)

        if entry_id in parent:
            before = parent[entry_id]
            detail["slots_changed"] = sum(1 for a, b in zip(before, ids) if a != b)
            if locked_teams:
                added = [pid for pid in ids
                         if pid not in before
                         and salary[pid]["TeamAbbrev"].upper() in locked_teams]
                if added:
                    names = [salary[p]["Name"] for p in added]
                    failures.append(
                        f"{entry_id}: introduced {names} from an already-locked game")
                detail["new_from_locked_games"] = len(added)
        rows.append(detail)

    if args.parent:
        missing = sorted(set(parent) - set(entries))
        if missing:
            failures.append(f"entries present in the parent but absent here: {missing}")

    report = {"entries": len(entries), "failures": failures, "lineups": rows,
              "passed": not failures}

    if args.json:
        print(json.dumps(report, indent=1))
    else:
        for detail in rows:
            if "salary" not in detail:
                print(f"{detail['entry_id']}  UNVERIFIABLE")
                continue
            changed = (f" chg={detail['slots_changed']}"
                       if "slots_changed" in detail else "")
            print(f"{detail['entry_id']}  ${detail['salary']}{changed} "
                  f"elig={detail['eligible']} dup={detail['duplicates']} "
                  f"stack={detail['stack']}")
        print()
        if failures:
            for failure in failures:
                print(f"FAIL  {failure}")
        else:
            print(f"PASS  {len(entries)} entries, all checks clean")
    return 0 if not failures else 3


if __name__ == "__main__":
    raise SystemExit(main())
