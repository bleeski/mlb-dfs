#!/usr/bin/env python3
"""handedness_feed.py -- a cached bat-side / throw-hand reference, and the lineups
feed it stamps for a DK-covered slate.

R332. On a slate where DK's ``Starting`` column covers every side the build needs
no feed at all (R143, R404), and the cost is that DK ships no handedness: F4's
platoon half goes neutral and ``f4_handedness_unavailable`` names every side. The
fix BUILD found on 1835_5g (``f4_platoon_applied`` 0 -> 90 of 90) was a per-slate
scratch generator that died with the slate. This is that route made first-class.

Handedness is a stable attribute of a player, so it is cached in
``data/reference/handedness.csv`` and AGED PER PLAYER: every row carries its own
``stamped`` date and ``source``, the report says how old each row it used is, and
a row older than ``STALE_DAYS`` is named. Age here is provenance, not validity: a
bat side does not expire, a player the file has never seen is the real gap, and
that is named too. Nothing here refuses a build over age.

    python tools/handedness_feed.py seed --from-platoon [PATH]      # the reference's `bats`
    python tools/handedness_feed.py seed --stdin --as-of 2026-10-08 # operator-captured rows
    python tools/handedness_feed.py feed --salary DKSalaries.csv --date 2026-10-08 \\
        --out data/slates/2026-10-08/lineups_feed.json

``seed`` upserts rows into the CSV (``name,team,bats[,throws]`` on stdin: the
StatsAPI roster route R332 documents, ``batSide`` and ``pitchHand`` per person, is
the session's to run; the engine reads captured bytes). ``feed`` builds the feed
through ``live_data_adapters.dk_starting_only_feed`` (R404: the engine's own
game_date_utc, orders and declared probables, and its own refusal wording for a
slate DK does not fully cover), then stamps ``bat_side`` per hitter and ``hand``
per probable from the CSV. A player the CSV does not know stays BLANK and is
named; a blank is never guessed. The feed is what ``build_slate.py --lineups``
reads. R332 filed a paste; a feed can say "hand unknown" and a paste cannot
without dropping the hitter's line, which is why this emits the feed.

Exit 0 clean, 2 a refusal (an unreadable row, a bad capture, a slate DK does not
fully cover, an output that already exists), 3 on IO. Nothing here touches the
network, DraftKings or a stored credential, and the DK salary file stays
authoritative for names, teams and orders.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from mlb_engine.intake.slate_intake_manager import normalize_name  # noqa: E402
from mlb_engine.team_codes import to_dk_abbrev  # noqa: E402

DEFAULT_CSV = REPO / "data" / "reference" / "handedness.csv"
DEFAULT_PLATOON = REPO / "data" / "reference" / "fangraphs_platoon_lineups.json"
FIELDS = ("name", "team", "bats", "throws", "stamped", "source")
#: A hand read off a roster by the operator outranks one read off a projected lineup
#: page: a routine re-seed from the platoon reference never undoes a correction.
SOURCE_RANK = {"operator_capture": 2, "fangraphs_platoon": 1}
BATS = frozenset("LRS")
THROWS = frozenset("LR")
#: A row this many days past its own stamp is NAMED. A bat side is stable, so this
#: is a provenance line, never a gate.
STALE_DAYS = 400
FRESH_DAYS = 30


class HandednessError(ValueError):
    """A refusal, named: nothing is written and the message says why."""


def key_of(name: Any, team: Any) -> Tuple[str, str]:
    """(accent-folded name, DK team): the join every other intake module uses."""
    return normalize_name(name), to_dk_abbrev(str(team or "").strip().upper())


def _iso(value: Any, what: str) -> date:
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError as exc:
        raise HandednessError(f"{what} {value!r} is not an ISO date") from exc


# --------------------------------------------------------------------------- #
# The CSV
# --------------------------------------------------------------------------- #
def read_handedness(path: Path) -> Tuple[List[Dict[str, str]], Dict[str, Any]]:
    """``(rows, report)``. A missing file is an empty reference, not an error.

    A row that cannot be read is NAMED in ``report["rejected"]`` and left out of
    the rows; ``seed`` refuses to rewrite a file that has one, so a rewrite can
    never silently drop it.
    """
    report: Dict[str, Any] = {"path": str(path), "exists": path.exists(), "rejected": []}
    if not path.exists():
        return [], report
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:                      # a zero-byte file is an empty reference
            return [], report
        if tuple(reader.fieldnames or ()) != FIELDS:
            raise HandednessError(
                f"{path}: header {tuple(reader.fieldnames or ())} is not {FIELDS}")
        rows: List[Dict[str, str]] = []
        for number, raw in enumerate(reader, start=2):
            row = {f: str(raw.get(f) or "").strip() for f in FIELDS}
            problem = _row_problem(row)
            if problem:
                report["rejected"].append({"line": number, "name": row["name"],
                                           "reason": problem})
            else:
                rows.append(row)
    return rows, report


def _row_problem(row: Mapping[str, str]) -> Optional[str]:
    if not row["name"] or not row["team"]:
        return "name and team are required"
    if row["bats"] and row["bats"] not in BATS:
        return f"bats {row['bats']!r} is not L, R or S"
    if row["throws"] and row["throws"] not in THROWS:
        return f"throws {row['throws']!r} is not L or R"
    if not row["bats"] and not row["throws"]:
        return "a row carries a bat side or a throw hand"
    try:
        date.fromisoformat(row["stamped"])
    except ValueError:
        return f"stamped {row['stamped']!r} is not an ISO date"
    return None


def write_handedness(path: Path, rows: Iterable[Mapping[str, str]]) -> None:
    """Deterministic order, atomic replace: a crash never leaves a half file."""
    ordered = sorted((dict(r) for r in rows),
                     key=lambda r: (to_dk_abbrev(r["team"]), normalize_name(r["name"]), r["name"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
            writer.writeheader()
            for row in ordered:
                writer.writerow({f: row.get(f, "") for f in FIELDS})
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


# --------------------------------------------------------------------------- #
# Seeding
# --------------------------------------------------------------------------- #
def rows_from_platoon(platoon: Mapping[str, Any]) -> Tuple[List[Dict[str, str]], Dict[str, Any]]:
    """Every reference row's ``bats``, stamped with the reference's own collected date."""
    stamped = _iso(platoon.get("collected_date"), "the platoon reference's collected_date").isoformat()
    seen: Dict[Tuple[str, str], Dict[str, str]] = {}
    unreadable = 0
    for team in platoon.get("teams") or []:
        abbrev = to_dk_abbrev(team.get("abbrev"))
        for view in ("vs_RHP", "vs_LHP"):
            for rec in team.get(view) or []:
                bats = str(rec.get("bats") or "").strip().upper()
                name = str(rec.get("player") or "").strip()
                if not name or not abbrev:
                    continue
                if bats not in BATS:
                    unreadable += 1
                    continue
                seen[key_of(name, abbrev)] = {
                    "name": name, "team": abbrev, "bats": bats, "throws": "",
                    "stamped": stamped, "source": "fangraphs_platoon"}
    return ([seen[k] for k in sorted(seen)],
            {"rows": len(seen), "unreadable_bats": unreadable, "stamped": stamped})


def rows_from_capture(text: str, as_of: str) -> List[Dict[str, str]]:
    """``name,team,bats[,throws]`` lines. ANY bad line refuses the whole capture:
    a silent partial write is the thing a cache must not do."""
    stamped = _iso(as_of, "--as-of").isoformat()
    out: List[Dict[str, str]] = []
    bad: List[str] = []
    first = True
    for number, record in enumerate(csv.reader(io.StringIO(text)), start=1):
        if not record or not "".join(record).strip():
            continue
        cells = [c.strip() for c in record]
        header_candidate, first = first, False             # the first NON-BLANK line
        if header_candidate and [c.lower() for c in cells[:3]] == ["name", "team", "bats"]:
            continue
        if len(cells) < 3 or len(cells) > 4:
            bad.append(f"line {number}: expected name,team,bats[,throws], got {len(cells)} cells")
            continue
        row = {"name": cells[0], "team": to_dk_abbrev(cells[1]), "bats": cells[2].upper(),
               "throws": (cells[3].upper() if len(cells) == 4 else ""),
               "stamped": stamped, "source": "operator_capture"}
        problem = _row_problem(row)
        if problem:
            bad.append(f"line {number} ({cells[0]}): {problem}")
        else:
            out.append(row)
    if bad:
        raise HandednessError("capture refused, nothing written: " + "; ".join(bad))
    return out


def upsert(existing: Sequence[Mapping[str, str]],
           incoming: Sequence[Mapping[str, str]]) -> Tuple[List[Dict[str, str]], Dict[str, Any]]:
    """Merge by (folded name, team). The NEWER stamp wins the row; a field the
    incoming row lacks keeps its old value; a CHANGED hand is reported, never
    silent. The stamp is the row's last write."""
    merged = {key_of(r["name"], r["team"]): dict(r) for r in existing}
    added = refreshed = kept_newer = 0
    changed: List[Dict[str, str]] = []
    for row in sorted(incoming, key=lambda r: (r["stamped"], key_of(r["name"], r["team"]))):
        key = key_of(row["name"], row["team"])
        old = merged.get(key)
        if old is None:
            merged[key] = dict(row)
            added += 1
        elif (SOURCE_RANK.get(row["source"], 0), row["stamped"]) >= (
                SOURCE_RANK.get(old["source"], 0), old["stamped"]):
            new = dict(old)
            for field in ("bats", "throws"):
                if row[field]:
                    if old[field] and old[field] != row[field]:
                        changed.append({"name": old["name"], "team": old["team"],
                                        "field": field, "was": old[field], "now": row[field]})
                    new[field] = row[field]
            new["stamped"], new["source"] = row["stamped"], row["source"]
            merged[key] = new
            refreshed += 1
        else:
            kept_newer += 1
    rows = [merged[k] for k in sorted(merged)]
    return rows, {"added": added, "refreshed": refreshed, "kept_newer": kept_newer,
                  "changed_hands": changed, "total": len(rows)}


# --------------------------------------------------------------------------- #
# The feed
# --------------------------------------------------------------------------- #
def build_feed(salary_csv: Path, rows: Sequence[Mapping[str, str]], slate_date: str,
               as_of: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """``(feed, report)``; raises HandednessError when DK's own file cannot supply the slate."""
    from mlb_engine.intake.live_data_adapters import dk_starting_only_feed

    feed, note = dk_starting_only_feed(salary_csv, slate_date)
    if feed is None:
        raise HandednessError(f"no feed: {note}")
    index = {key_of(r["name"], r["team"]): r for r in rows}
    today = _iso(as_of, "--as-of")
    sides: List[Dict[str, Any]] = []
    ages: List[Tuple[int, str, str]] = []
    for game in feed.get("games") or []:
        for key in ("away", "home"):
            block = game.get(key) or {}
            team = to_dk_abbrev(block.get("team_abbrev"))
            if not team or not block.get("lineup"):
                continue
            blank_hitters: List[str] = []
            stamped = 0
            for hitter in block["lineup"]:
                row = index.get(key_of(hitter.get("name"), team))
                if row and row["bats"]:
                    hitter["bat_side"] = row["bats"]
                    stamped += 1
                    ages.append(((today - date.fromisoformat(row["stamped"])).days,
                                 str(hitter.get("name")), team))
                else:
                    blank_hitters.append(str(hitter.get("name")))
            probable = block.get("probable_pitcher") or {}
            hand = None
            if probable.get("name"):
                row = index.get(key_of(probable["name"], team))
                if row and row["throws"]:
                    probable["hand"] = hand = row["throws"]
                    ages.append(((today - date.fromisoformat(row["stamped"])).days,
                                 str(probable["name"]), team))
            sides.append({
                "team": team, "hitters": len(block["lineup"]), "with_bat_side": stamped,
                "blank_hitters": blank_hitters,
                "probable": {"name": probable.get("name"), "hand": hand}
                if probable else None})
    stale = sorted((a, n, t) for a, n, t in ages if a > STALE_DAYS)
    report = {
        "note": note, "sides": sorted(sides, key=lambda s: s["team"]),
        "hitters": sum(s["hitters"] for s in sides),
        "with_bat_side": sum(s["with_bat_side"] for s in sides),
        "blank_probables": sorted(s["team"] for s in sides
                                  if s["probable"] and not s["probable"]["hand"]),
        "age_days": {"fresh_le_%d" % FRESH_DAYS: sum(1 for a, _n, _t in ages if a <= FRESH_DAYS),
                     "aged": sum(1 for a, _n, _t in ages if FRESH_DAYS < a <= STALE_DAYS),
                     "stale_gt_%d" % STALE_DAYS: [
                         {"name": n, "team": t, "days": a} for a, n, t in stale]},
        "label": "bat side and throw hand per player from a cached reference; a blank "
                 "keeps F4's platoon term at 1.0 and is named, never guessed",
    }
    return feed, report


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _print_report(report: Mapping[str, Any]) -> None:
    print(f"feed: {report['note']}", file=sys.stderr)
    print(f"bat sides: {report['with_bat_side']} of {report['hitters']} hitters stamped",
          file=sys.stderr)
    for side in report["sides"]:
        if side["blank_hitters"]:
            print(f"  {side['team']}: no bat side for {', '.join(side['blank_hitters'])}",
                  file=sys.stderr)
    if report["blank_probables"]:
        print(f"  no throw hand for the probable of {', '.join(report['blank_probables'])}"
              " (F4's platoon term stays 1.0 against them)", file=sys.stderr)
    for rec in report["age_days"][f"stale_gt_{STALE_DAYS}"]:
        print(f"  WARN {rec['name']} ({rec['team']}): stamp is {rec['days']} days old", file=sys.stderr)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    seed = sub.add_parser("seed", help="upsert rows into the handedness CSV")
    seed.add_argument("--csv", default=str(DEFAULT_CSV))
    seed.add_argument("--from-platoon", nargs="?", const=str(DEFAULT_PLATOON), default=None,
                      help="ingest the platoon reference's `bats` (its own collected_date stamps them)")
    seed.add_argument("--stdin", action="store_true",
                      help="ingest name,team,bats[,throws] lines from stdin, stamped --as-of")
    seed.add_argument("--as-of", help="ISO date stamping stdin rows")
    seed.add_argument("--json", action="store_true")
    feed_p = sub.add_parser("feed", help="a lineups feed from DK's Starting column, hands stamped")
    feed_p.add_argument("--salary", required=True)
    feed_p.add_argument("--date", required=True, help="the slate date (ISO)")
    feed_p.add_argument("--out", required=True, help="where to write the feed; never overwrites")
    feed_p.add_argument("--csv", default=str(DEFAULT_CSV))
    feed_p.add_argument("--as-of", help="ISO date the row ages are measured against (default: --date)")
    feed_p.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    try:
        if args.cmd == "seed":
            return _seed(args)
        return _feed(args)
    except HandednessError as exc:
        print(f"REFUSED  {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"ERROR  {exc}", file=sys.stderr)
        return 3


def _seed(args: argparse.Namespace) -> int:
    if not args.from_platoon and not args.stdin:
        raise HandednessError("seed needs --from-platoon and/or --stdin")
    if args.stdin and not args.as_of:
        raise HandednessError("--stdin rows need --as-of: the stamp is the row's age")
    path = Path(args.csv)
    existing, read_report = read_handedness(path)
    if read_report["rejected"]:
        raise HandednessError(
            f"{path} has {len(read_report['rejected'])} unreadable row(s) a rewrite would "
            f"drop: {read_report['rejected'][:5]}; fix them first")
    incoming: List[Dict[str, str]] = []
    report: Dict[str, Any] = {"csv": str(path)}
    if args.from_platoon:
        try:
            platoon = json.loads(Path(args.from_platoon).read_text(encoding="utf-8"))
        except ValueError as exc:
            raise HandednessError(f"{args.from_platoon} is not readable JSON: {exc}") from exc
        rows, report["platoon"] = rows_from_platoon(platoon)
        incoming += rows
    if args.stdin:
        incoming += rows_from_capture(sys.stdin.read(), args.as_of)
    merged, report["merge"] = upsert(existing, incoming)
    write_handedness(path, merged)
    if args.json:
        print(json.dumps(report, indent=1, default=str))
    else:
        m = report["merge"]
        print(f"handedness: {m['total']} rows ({m['added']} added, {m['refreshed']} refreshed, "
              f"{m['kept_newer']} kept newer); {len(m['changed_hands'])} changed hand(s)")
        for c in m["changed_hands"]:
            print(f"  CHANGED {c['name']} ({c['team']}) {c['field']}: {c['was']} -> {c['now']}")
    return 0


def _feed(args: argparse.Namespace) -> int:
    out = Path(args.out)
    if out.exists():
        raise HandednessError(f"{out} already exists; this never overwrites a feed")
    slate_date = _iso(args.date, "--date").isoformat()
    rows, read_report = read_handedness(Path(args.csv))
    for rec in read_report["rejected"]:
        print(f"  skipped row at line {rec['line']} ({rec['name']}): {rec['reason']}", file=sys.stderr)
    feed, report = build_feed(Path(args.salary), rows, slate_date, args.as_of or slate_date)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(feed, indent=1), encoding="utf-8")
    report["out"] = str(out)
    report["csv"] = {"path": read_report["path"], "exists": read_report["exists"],
                     "rows": len(rows), "rejected": read_report["rejected"]}
    if args.json:
        print(json.dumps(report, indent=1, default=str))
    else:
        _print_report(report)
        print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
