#!/usr/bin/env python
"""plan_status.py -- the linter for `docs/ROADMAP.md` (R385; replaces R366's generator).

`docs/ROADMAP.md` is the only surface that orders engineering work and carries
its status. `docs/backlog.md` is the R-entry register: the What/Why/Fix bodies.
R366 derived a one-screen `docs/PROGRESS.md` from the register's roadmap tables,
because the register was 1.1 MB and could not be read on a phone. Once the
queue moved into a file that small, a derived copy became a second surface for
no reason. So this no longer writes anything. It checks the one surface, and
the gate fails when that surface is incomplete or malformed.

What `--check` enforces, each rule because its absence has cost this repo:

  1. Exactly one `**NEXT:** Session NN` line, and it names a row whose status is
     Pending or In Progress.
  2. Every master-table row has 8 cells and a Status in the vocabulary
     {Pending, In Progress, Complete YYYY-MM-DD, Deferred}.
  3. Every OPEN register entry (a `### R<num>` heading above `# Board history`,
     outside `## Closed number stubs`, that does not say CLOSED) is named
     somewhere in ROADMAP.md. This is the
     single-source rule: an open item with no session block is a second backlog.
  4. Every non-Deferred row names at least one R-number, because commit
     subjects carry R-numbers (R301).
  5. Every Session ID in the Progress Ledger exists in the master table.

A Session ID is two or three digits. Two-digit IDs run out at 99, and a
three-digit row used to be invisible here: never parsed, so its status went
unlinted and `--print` skipped it, while `**NEXT:** Session 100` failed the gate
outright. Rows sort by number, not by text, so 100 follows 99.

    python tools/plan_status.py --check     # exit 2 on any lint failure
    python tools/plan_status.py --print     # one line per session, to stdout

Exit codes: 0 ok, 2 lint failure, 3 a file could not be read.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ROADMAP = Path("docs/ROADMAP.md")
REGISTER = Path("docs/backlog.md")

#: A Session ID is two or three digits (see the docstring). One width, used by
#: every reader below.
SESSION_ID = r"\d{2,3}"
ROW = re.compile(r"^\|\s*\*\*Session (" + SESSION_ID + r")\*\*\s*\|")
NEXT = re.compile(r"^\*\*NEXT:\*\*\s*Session (" + SESSION_ID + r")\b")
LEDGER_ID = re.compile(r"Session (" + SESSION_ID + r")$")
STATUS = re.compile(r"^(Pending|In Progress|Complete \d{4}-\d{2}-\d{2}|Deferred)$")
RNUM = re.compile(r"\bR\d{1,3}(?!\d)")
OPEN_HEADING = re.compile(r"^### (R\d{1,3})(?!\d)")
LEDGER_HEADING = "## Living Changelog and Progress Ledger"


def _by_number(item: tuple) -> int:
    """Sort key for ``(session_id, row)``: 100 after 99, never between 10 and 11."""
    return int(item[0])


def split_row(line: str) -> list[str]:
    """The cells of a markdown table row, splitting on unescaped pipes only."""
    parts = re.split(r"(?<!\\)\|", line.strip())
    if parts and not parts[0].strip():
        parts = parts[1:]
    if parts and not parts[-1].strip():
        parts = parts[:-1]
    return [p.strip() for p in parts]


def parse_roadmap(text: str) -> dict:
    rows: dict[str, dict] = {}
    nexts: list[str] = []
    ledger_ids: list[str] = []
    problems: list[str] = []
    in_ledger = False
    for number, line in enumerate(text.splitlines(), 1):
        if line.startswith("## "):
            in_ledger = line.strip() == LEDGER_HEADING
        m = NEXT.match(line)
        if m:
            nexts.append(m.group(1))
            continue
        if in_ledger and line.startswith("|"):
            cells = split_row(line)
            if len(cells) > 1:
                sid = LEDGER_ID.match(cells[1])
                if sid:
                    ledger_ids.append(sid.group(1))
            continue
        m = ROW.match(line)
        if not m:
            continue
        sid = m.group(1)
        cells = split_row(line)
        if sid in rows:
            problems.append(f"line {number}: Session {sid} appears twice in the master table")
        if len(cells) != 8:
            problems.append(f"line {number}: Session {sid} has {len(cells)} cells, not 8")
            continue
        rows[sid] = {"line": number, "packaging": cells[1], "scope": cells[2],
                     "status": cells[7]}
    return {"rows": rows, "nexts": nexts, "ledger": ledger_ids, "problems": problems}


def open_register_entries(text: str) -> list[str]:
    """R-numbers of open `### R` headings above `# Board history`, stubs excluded."""
    found: list[str] = []
    in_stubs = False
    for line in text.splitlines():
        if line.startswith("# Board history"):
            break
        if line.startswith("## "):
            in_stubs = line.startswith("## Closed number stubs")
        m = OPEN_HEADING.match(line)
        if m and not in_stubs and "CLOSED" not in line:
            found.append(m.group(1))
    return sorted(set(found), key=lambda r: int(r[1:]))


def lint(roadmap_text: str, register_text: str) -> list[str]:
    parsed = parse_roadmap(roadmap_text)
    rows = parsed["rows"]
    problems = list(parsed["problems"])

    if len(parsed["nexts"]) != 1:
        problems.append(f"expected exactly one `**NEXT:** Session NN` line, found {len(parsed['nexts'])}")
    else:
        sid = parsed["nexts"][0]
        if sid not in rows:
            problems.append(f"NEXT names Session {sid}, which is not in the master table")
        elif rows[sid]["status"] not in ("Pending", "In Progress"):
            problems.append(f"NEXT names Session {sid}, whose status is {rows[sid]['status']!r}")

    for sid, row in sorted(rows.items(), key=_by_number):
        if not STATUS.match(row["status"]):
            problems.append(f"Session {sid}: status {row['status']!r} is outside the vocabulary")
        if row["status"] != "Deferred" and not RNUM.search(row["scope"]):
            problems.append(f"Session {sid}: a non-Deferred row names no R-number")

    named = set(RNUM.findall(roadmap_text))
    for rnum in open_register_entries(register_text):
        if rnum not in named:
            problems.append(f"{rnum} is open in {REGISTER} and named nowhere in {ROADMAP}")

    for sid in parsed["ledger"]:
        if sid not in rows:
            problems.append(f"the Progress Ledger names Session {sid}, which is not in the master table")
    return problems


def summary(roadmap_text: str) -> str:
    parsed = parse_roadmap(roadmap_text)
    rows = parsed["rows"]
    done = sum(1 for r in rows.values() if r["status"].startswith("Complete"))
    lines = [f"NEXT: Session {parsed['nexts'][0] if parsed['nexts'] else '??'}",
             f"{done} of {len(rows)} sessions complete", ""]
    for sid, row in sorted(rows.items(), key=_by_number):
        lead = re.sub(r"<br>.*", "", row["scope"])
        lead = " ".join(lead.split())
        lead = lead if len(lead) <= 90 else lead[:89].rstrip() + "…"
        lines.append(f"Session {sid} | {row['status']:<20} | {lead}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="exit 2 on any lint failure")
    parser.add_argument("--print", dest="to_stdout", action="store_true",
                        help="print one line per session")
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    args = parser.parse_args(argv)
    try:
        roadmap_text = (args.root / ROADMAP).read_text(encoding="utf-8")
        register_text = (args.root / REGISTER).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"cannot read the roadmap or the register: {exc}", file=sys.stderr)
        return 3
    if args.to_stdout:
        sys.stdout.write(summary(roadmap_text))
        if not args.check:
            return 0
    problems = lint(roadmap_text, register_text)
    if problems:
        for p in problems:
            print(f"LINT  {p}", file=sys.stderr)
        return 2
    if args.check:
        print(f"{ROADMAP} is consistent with {REGISTER}")
    elif not args.to_stdout:
        sys.stdout.write(summary(roadmap_text))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
