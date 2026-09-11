"""extract_inbox_zips.py -- unzip DraftKings standings exports dropped in the inbox.

DraftKings exports full standings as a .zip containing a single standings CSV.
This pulls every CSV out of every .zip in data/standings/inbox/ so the downstream
field_miner loop sees plain CSVs. Idempotent (skips a member whose CSV already
exists unless --overwrite), leaves the .zip in place, and never deletes anything.
Extract-only; touches only the inbox folder.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import zipfile
import uuid
from pathlib import Path
from typing import List, Optional

DEFAULT_INBOX = "data/standings/inbox"
_DIGITS = re.compile(r"\d+")


def infer_contest_id(name: str) -> str:
    """DK names exports like contest-standings-<id>.zip/.csv; take the last digit run."""
    matches = _DIGITS.findall(Path(str(name)).stem)
    return matches[-1] if matches else ""


def extract_zip(zip_path: Path, dest: Optional[Path] = None, overwrite: bool = False) -> List[Path]:
    """Extract every .csv member of one zip into ``dest`` (flattened to basename)."""
    dest = Path(dest or Path(zip_path).parent)
    dest.mkdir(parents=True, exist_ok=True)
    dest = dest.resolve()
    out: List[Path] = []
    with zipfile.ZipFile(zip_path) as zf:
        members = [m for m in zf.infolist() if not m.is_dir() and m.filename.lower().endswith(".csv")]
        names = [m.filename.replace("\\", "/").rsplit("/", 1)[-1] for m in members]
        if len(names) != len(set(n.casefold() for n in names)):
            raise ValueError("ZIP contains colliding CSV basenames")
        if sum(m.file_size for m in members) > 512 * 1024 * 1024:
            raise ValueError("ZIP expands beyond the 512 MiB limit")
        for member, name in zip(members, names):
            if not name or ":" in name:
                raise ValueError("invalid CSV basename")
            target = (dest / name).resolve()
            if not target.is_relative_to(dest):
                raise ValueError("ZIP destination escapes inbox")
            with zf.open(member) as src:
                raw = src.read(min(member.file_size, 512 * 1024 * 1024) + 1)
            if len(raw) != member.file_size:
                raise ValueError("ZIP member size mismatch")
            if target.exists() and not overwrite:
                if target.read_bytes() != raw:
                    raise ValueError("existing CSV differs from ZIP; refusing silent collision")
                out.append(target)
                continue
            temp = dest / ("." + uuid.uuid4().hex[:12] + ".tmp")
            try:
                with temp.open("xb") as fh:
                    fh.write(raw)
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(temp, target)
            finally:
                if temp.exists():
                    temp.unlink()
            out.append(target)
    return out


def extract_inbox(inbox: str = DEFAULT_INBOX, overwrite: bool = False) -> List[dict]:
    inbox_dir = Path(inbox)
    results: List[dict] = []
    for zp in sorted(inbox_dir.glob("*.zip")):
        try:
            csvs = extract_zip(zp, inbox_dir, overwrite=overwrite)
        except (zipfile.BadZipFile, ValueError, OSError) as exc:
            results.append({"zip": zp.name, "error": str(exc)})
            continue
        for c in csvs:
            results.append({"zip": zp.name, "csv": c.name, "contest_id": infer_contest_id(c.name)})
    return results


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--inbox", default=DEFAULT_INBOX)
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args(argv)
    rows = extract_inbox(args.inbox, overwrite=args.overwrite)
    if not rows:
        print(f"no .zip files in {args.inbox}")
        return 0
    for r in rows:
        if r.get("error"):
            print(f"SKIP {r['zip']}: {r['error']}")
        else:
            print(f"extracted {r['csv']} (contest {r['contest_id'] or '?'}) from {r['zip']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
