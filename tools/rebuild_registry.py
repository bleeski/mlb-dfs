#!/usr/bin/env python3
"""rebuild_registry.py -- rebuild the opponent registry from the archive, deterministically.

The registry had forked into two diverging copies:
``ledger/field_opponent_registry.json`` (534 users, newest 2026-07-19) and
``data/reference/field_opponent_registry.json`` (1986 users, newest 2026-07-24),
with 230 shared users disagreeing and neither a superset of the other. It forked
because ``--registry`` was a bare cwd-relative argument with no default, so
whichever directory the miner happened to run from got the write.

Merging two diverged copies is guesswork. Rebuilding from source is not: every
input is a standings CSV already on disk under ``data/archive/``, the mine is
deterministic, and the result is reproducible by running this again. That is the
whole argument for rebuilding rather than reconciling.

Usage:
    python tools/rebuild_registry.py [--dry-run] [--out <path>]

Writes ``data/reference/field_opponent_registry.json``, the one path
``field_miner.default_registry_path()`` resolves. Prints what it read and what
it produced. Deterministic bookkeeping; observed field behaviour, never a
prediction.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from mlb_engine.field.field_miner import (  # noqa: E402
    default_registry_path, default_salary_candidates, load_salary_map,
    mine_contest, parse_standings_export, resolve_salary_file,
    structural_exit_code, update_registry,
)


def contest_id_from_name(path: Path) -> str:
    stem = path.stem
    return stem.split("contest-standings-")[-1] if "contest-standings-" in stem else stem


def slate_date_from_path(path: Path) -> str:
    """data/archive/<date>/contest-standings-<id>.csv"""
    parent = path.parent.name
    return parent if len(parent) == 10 and parent[4] == "-" else ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--archive", default=str(REPO / "data" / "archive"))
    ap.add_argument("--out", default=None,
                    help="defaults to field_miner.default_registry_path()")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-seconds", type=float, default=None,
                    help="stop after this many seconds and exit 10 with progress "
                         "kept, so the rebuild can finish across several runs. "
                         "Salary resolution scores every candidate on disk "
                         "against every contest, so a full rebuild is minutes; "
                         "the Cowork sandbox caps a single call at 45s.")
    ap.add_argument("--restart", action="store_true",
                    help="discard staged progress and rebuild from zero")
    args = ap.parse_args()

    out = Path(args.out or default_registry_path())
    sources = sorted(Path(args.archive).rglob("contest-standings-*.csv"))
    if not sources:
        print(f"no standings CSVs under {args.archive}", file=sys.stderr)
        return 3

    staged = out.with_name(f".{out.name}.rebuild")
    if args.restart and staged.exists():
        staged.unlink()

    # Resume where the last run stopped. update_registry already refuses to
    # double-count a contest it has folded in, so the staged file is a complete
    # and correct record of the slice done so far, not a partial one.
    done = set()
    if staged.exists():
        done = set(json.loads(staged.read_text(encoding="utf-8"))
                   .get("contests_mined", []))
        print(f"resuming: {len(done)} contests already folded in")

    started = time.monotonic()
    mined_ok, skipped, remaining = 0, [], []
    for path in sources:
        cid = contest_id_from_name(path)
        if cid in done:
            continue
        if args.max_seconds and time.monotonic() - started > args.max_seconds:
            remaining.append(path.name)
            continue
        try:
            standings = parse_standings_export(str(path))
        except Exception as exc:  # noqa: BLE001 - one bad file must not kill the rebuild
            skipped.append((path.name, f"unreadable: {exc}"))
            continue
        resolved = resolve_salary_file(standings, default_salary_candidates(REPO))
        salary_map = None
        if resolved.get("path"):
            try:
                salary_map = load_salary_map(resolved["path"])
            except Exception:  # noqa: BLE001
                salary_map = None
        mined = mine_contest(standings, salary_map, contest_id=cid,
                             slate_date=slate_date_from_path(path))
        diagnostics = mined.get("diagnostics") or {}
        if not diagnostics.get("parse_structural_ok", True):
            # The same gate the miner enforces. A rebuild that folds in a mine
            # the miner itself would refuse to archive is not a rebuild, it is a
            # second way to poison the same file.
            skipped.append((path.name,
                            f"exit {structural_exit_code(diagnostics)}: "
                            f"{diagnostics.get('verification_note', '')[:90]}"))
            continue
        update_registry(str(staged), mined)
        mined_ok += 1

    payload = json.loads(staged.read_text(encoding="utf-8")) if staged.exists() else {}
    users = payload.get("users", {})
    print(f"read     {len(sources)} standings CSVs under {args.archive}")
    print(f"mined    {mined_ok}")
    print(f"skipped  {len(skipped)}")
    for name, why in skipped:
        print(f"         {name}: {why}")
    print(f"users    {len(users)}")
    print(f"contests {len(payload.get('contests_mined', []))}")

    if remaining:
        print(f"\n{len(remaining)} contests still to mine; progress is kept in "
              f"{staged.name}. Run the same command again to continue.")
        return 10

    if args.dry_run:
        print(f"\ndry run: nothing written; the staged rebuild is at {staged}")
        return 0

    for old in (out, REPO / "ledger" / "field_opponent_registry.json"):
        if old.exists() and old.resolve() != staged.resolve():
            prior = json.loads(old.read_text(encoding="utf-8"))
            print(f"replacing {old} ({len(prior.get('users', {}))} users)")
    staged.replace(out)
    print(f"\nwrote {out} with {len(users)} users from {mined_ok} contests")
    print("Delete ledger/field_opponent_registry.json by hand once you have "
          "confirmed this file; the miner no longer writes there.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
