#!/usr/bin/env python
"""plan_status.py -- the roadmap's status, DERIVED from the board (R366).

`docs/backlog.md` is 1.1 MB and the roadmap tables inside it are the queue every
session works from. Nothing could read that queue cheaply: a session wanting to
know what is open either grepped for anchors or paid to load a file it is told
never to read whole (`.claude/rules/board.md`), and from a phone on github.com
it is unopenable.

So this writes `docs/PROGRESS.md`: one screen, one line per Session ID, status
taken from the board itself.

It is GENERATED, never hand-maintained, and that is the whole point. This repo
has eighteen ledger fragments unmerged since 2026-08-13 and a Quick Card pin
about twelve moves stale, both because a second surface needed a second write
that somebody had to remember. A derived file cannot drift: `--check` exits 2
when the file on disk disagrees with what the board says, `tests/test_core.py`
runs that check, and the gate fails rather than the file quietly lying.

Status is read, not stored. A row is DONE when its scope cell carries
`DONE <date>`, which is the form `.claude/rules/board.md` already requires of a
completed item ("the roadmap row says DONE with the date and the gate line").
A Session ID spanning several batch rows is DONE only when every one of its rows
is.

    python tools/plan_status.py              # rewrite docs/PROGRESS.md
    python tools/plan_status.py --check      # exit 2 if it is out of date
    python tools/plan_status.py --print      # write nothing, print to stdout

Exit codes: 0 ok, 2 out of date (`--check`), 3 the board could not be read.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BOARD = Path("docs/backlog.md")
PROGRESS = Path("docs/PROGRESS.md")

# A roadmap row. Cell 1 is the Session ID, cell 3 the scope. Both the `## Execution
# roadmap` heading's NEXT pointer and these rows are written by hand in every
# landing, so this parser reads what the board already has rather than asking a
# session to maintain a second format.
ROW = re.compile(r"^\|\s*\*\*(CC-[A-Z]?\d+)\*\*")
PHASE = re.compile(r"^### (Phase [^\n]*)$")
ROADMAP_HEADING = re.compile(r"^## Execution roadmap[^\n]*$")
DONE = re.compile(r"\bDONE\b\s+(\d{4}-\d{2}-\d{2})")
# The scope cell opens with the item's own bolded title; that is the short name.
LEAD = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)


def split_row(line: str) -> list[str]:
    """The cells of a markdown table row, without the leading/trailing pipes.

    Split on unescaped pipes only. Scope cells carry inline code containing `|`
    rarely but names like `a|b` would otherwise shift every later cell, and a
    silently shifted cell is how a status column starts reading the wrong thing.
    """
    parts = re.split(r"(?<!\\)\|", line.strip())
    if parts and not parts[0].strip():
        parts = parts[1:]
    if parts and not parts[-1].strip():
        parts = parts[:-1]
    return [p.strip() for p in parts]


def short_name(scope: str, limit: int = 96) -> str:
    """The item's own bolded lead, trimmed to one line."""
    match = LEAD.search(scope)
    text = (match.group(1) if match else scope).strip()
    text = " ".join(text.split())
    text = re.sub(r"\s*\bDONE\b\s+\d{4}-\d{2}-\d{2}\.?", "", text).strip(" .-")
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def parse_board(text: str) -> tuple[str, list[dict]]:
    """``(next_pointer, rows)`` from the board's roadmap tables."""
    pointer = ""
    phase = ""
    rows: list[dict] = []
    for line in text.splitlines():
        if not pointer and ROADMAP_HEADING.match(line):
            _, _, tail = line.partition("NEXT:")
            pointer = tail.strip() or "(the roadmap heading names no NEXT)"
            continue
        phase_match = PHASE.match(line)
        if phase_match:
            phase = phase_match.group(1).strip()
            continue
        if not ROW.match(line):
            continue
        cells = split_row(line)
        if len(cells) < 3:
            continue
        session = ROW.match(line).group(1)
        done = DONE.search(cells[2])
        rows.append({
            "session": session,
            "phase": phase,
            "name": short_name(cells[2]),
            "done": done.group(1) if done else "",
            "impact": cells[5] if len(cells) > 5 else "",
        })
    return pointer or "(no `## Execution roadmap ... NEXT:` heading found)", rows


def collapse(rows: list[dict]) -> list[dict]:
    """One entry per Session ID. A batch is DONE only when every row of it is."""
    order: list[str] = []
    by_id: dict[str, dict] = {}
    for row in rows:
        sid = row["session"]
        if sid not in by_id:
            by_id[sid] = {**row, "batches": 0, "done_batches": 0, "names": []}
            order.append(sid)
        entry = by_id[sid]
        entry["batches"] += 1
        entry["names"].append(row["name"])
        if row["done"]:
            entry["done_batches"] += 1
            entry["done"] = max(entry["done"], row["done"])
        else:
            entry["done"] = entry["done"] if entry["done_batches"] else ""
    out = []
    for sid in order:
        entry = by_id[sid]
        complete = entry["done_batches"] == entry["batches"]
        out.append({
            "session": sid,
            "phase": entry["phase"],
            "status": f"DONE {entry['done']}" if complete and entry["done"] else (
                f"part {entry['done_batches']}/{entry['batches']}"
                if entry["done_batches"] else "open"),
            "name": entry["names"][0] if entry["batches"] == 1 else
                    f"{entry['names'][0]} (+{entry['batches'] - 1} more)",
            "impact": entry["impact"],
        })
    return out


def render(pointer: str, rows: list[dict]) -> str:
    done = sum(1 for r in rows if r["status"].startswith("DONE"))
    lines = [
        "# Roadmap status",
        "",
        "**Generated by `python tools/plan_status.py` from `docs/backlog.md`. Do not",
        "hand-edit: `--check` runs in the gate and fails when this file and the board",
        "disagree.** The board is the source of truth; this is the one-screen view of it,",
        "because the board itself is 1.1 MB and cannot be read on a phone.",
        "",
        f"**NEXT:** {pointer}",
        "",
        f"{done} of {len(rows)} sessions done.",
        "",
    ]
    phase = None
    for row in rows:
        if row["phase"] != phase:
            phase = row["phase"]
            lines += ["", f"### {phase}" if phase else "### (ungrouped)", "",
                      "| Session | Status | Item |", "| :--- | :--- | :--- |"]
        lines.append(f"| **{row['session']}** | {row['status']} | {row['name']} |")
    lines.append("")
    return "\n".join(lines)


def build(root: Path) -> str:
    board = root / BOARD
    try:
        text = board.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise SystemExit(f"cannot read {BOARD}: {exc}")
    pointer, rows = parse_board(text)
    return render(pointer, collapse(rows))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="exit 2 if docs/PROGRESS.md is out of date")
    parser.add_argument("--print", dest="to_stdout", action="store_true",
                        help="print the generated file instead of writing it")
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    args = parser.parse_args(argv)

    try:
        wanted = build(args.root)
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        return 3

    target = args.root / PROGRESS
    if args.to_stdout:
        sys.stdout.write(wanted)
        return 0
    if args.check:
        current = target.read_text(encoding="utf-8") if target.exists() else ""
        if current == wanted:
            print(f"{PROGRESS} is current")
            return 0
        print(f"{PROGRESS} is out of date; run `python tools/plan_status.py`",
              file=sys.stderr)
        return 2
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(wanted, encoding="utf-8")
    print(f"wrote {PROGRESS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
