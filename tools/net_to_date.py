#!/usr/bin/env python3
"""net_to_date.py -- one table answering "are we winning".

G4 exists because G7, the stakes decision, is the highest-value open item in the
backlog and is undecidable without this number. The engine is built to a standard
that suits four-figure exposure and has been running at single-digit dollars;
either scaling stakes or freezing the engine is defensible, and neither can be
chosen on vibes.

Reads ``ledger/own_results.json``, which ``field_miner`` appends to as contests
are archived, and prints a cumulative table. Every row is an observed outcome
from a completed contest. Nothing here is a graded prediction, an ROI model, a
win rate, an expected value, or a probability claim, and a positive net over a
small number of contests is not evidence of skill.

Usage:
    python tools/net_to_date.py [--since 2026-07-01] [--json]
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LEDGER = REPO / "ledger" / "own_results.json"


def load_records(path: Path = LEDGER) -> list[dict]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return list(payload.get("contests") or [])


def append_record(record: dict, path: Path = LEDGER) -> None:
    """Append one contest, keyed on contest id so a re-mine replaces rather than adds."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        payload = {
            "_label": "Ben's own observed results per archived contest. Observed "
                      "outcomes only; never a graded prediction, ROI model, win "
                      "rate, or probability claim.",
            "contests": [],
        }
    contests = [c for c in payload.get("contests", [])
                if str(c.get("contest_id")) != str(record.get("contest_id"))]
    contests.append(record)
    payload["contests"] = sorted(contests, key=lambda c: (str(c.get("slate_date") or ""),
                                                          str(c.get("contest_id") or "")))
    # R21: a fixed tmp name let two concurrent miners interleave into one tmp
    # file; a unique name keeps every stage-and-replace private to its writer.
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
    tmp.replace(path)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--since", help="ISO slate date; earlier contests are excluded")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    records = load_records()
    if args.since:
        records = [r for r in records if str(r.get("slate_date") or "") >= args.since]
    if not records:
        print("No own-results records yet. They are written as contests are archived:\n"
              "  python -m mlb_engine.field.field_miner --standings <csv> "
              "--auto-salary --contest-id <id> --slate-date <date> \\\n"
              "      --entry-fee <fee> --winnings <won> --emit-ledger\n"
              "Entry IDs are harvested from outputs/<date>/upload_manifest.json.")
        return 0

    by_date: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        by_date[str(record.get("slate_date") or "unknown")].append(record)

    graded = [r for r in records if r.get("net") is not None]
    fees = sum(float(r.get("fees_total") or 0.0) for r in graded)
    won = sum(float(r.get("winnings_total") or 0.0) for r in graded)
    entries = sum(int(r.get("matched") or 0) for r in records)

    payload = {
        "contests_archived": len(records),
        "contests_with_fee_and_winnings": len(graded),
        "entries": entries,
        "fees_total": round(fees, 2),
        "winnings_total": round(won, 2),
        "net_to_date": round(won - fees, 2),
        "labels": "observed outcomes from completed contests; never a graded "
                  "prediction, ROI model, win rate, or probability claim",
    }

    if args.json:
        print(json.dumps({"summary": payload, "by_date": by_date}, indent=1))
        return 0

    print(f"{'date':<12} {'contests':>8} {'entries':>8} {'fees':>9} {'won':>9} {'net':>9}")
    print("-" * 60)
    for date in sorted(by_date):
        rows = by_date[date]
        d_fees = sum(float(r.get("fees_total") or 0.0) for r in rows)
        d_won = sum(float(r.get("winnings_total") or 0.0) for r in rows)
        d_entries = sum(int(r.get("matched") or 0) for r in rows)
        print(f"{date:<12} {len(rows):>8} {d_entries:>8} "
              f"{d_fees:>9.2f} {d_won:>9.2f} {d_won - d_fees:>9.2f}")
    print("-" * 60)
    print(f"{'TOTAL':<12} {len(records):>8} {entries:>8} "
          f"{fees:>9.2f} {won:>9.2f} {won - fees:>9.2f}")
    ungraded = len(records) - len(graded)
    if ungraded:
        print(f"\n{ungraded} archived contest(s) carry no fee/winnings and are "
              f"excluded from the money columns. Pass --entry-fee and --winnings "
              f"at mining time to include them.")
    print("\nObserved outcomes from completed contests. Not a graded prediction, "
          "an ROI model, a win rate, or a probability claim. A positive net over "
          "a small number of contests is not evidence of skill.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
