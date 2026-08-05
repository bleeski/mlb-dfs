#!/usr/bin/env python3
"""awaiting_standings.py -- the standings-pull gap, computed instead of hand-written (R43).

Three sessions (07-28, 08-02, 08-03) independently hand-wrote the same scan:
every Contest ID on a filled entry row in `outputs/*/DKEntries*.csv`, minus
whatever is already archived or sitting in the inbox, minus the contests
already known to be dead. The 08-03 pass also found the defect every earlier
pass shared: accepting any non-empty Contest ID picks up non-DK placeholder
values (`0`, `900`) from manual/test entry rows and emits a dead
`exportfullstandingscsv/0` link. Real DK contest IDs are 9 digits; this tool
filters to that instead of hardcoding the two junk values anyone has seen so
far, so the next one gets caught too.

This tool only reads local files and writes two report files. It never
fetches DraftKings -- the hard guardrail in CLAUDE.md is that standings pulls
are Ben's manual action, one click per contest while logged in. What this
tool is allowed to do, and does, is turn contest IDs that are already sitting
in Ben's own delivered files into the exact `exportfullstandingscsv/<id>` URL
so he does not have to hand-build it.

Inputs:
  outputs/*/DKEntries*.csv        -- entered contests (skips `_`-prefixed dirs,
                                      which are test/audit fixtures, e.g. the
                                      R3 leak in `outputs/_test_r3_*`)
  data/archive/*/mined_*.json     -- the archived set (one file per contest a
                                      mine succeeded on; more precise than
                                      globbing raw CSV filenames, which can
                                      exist without a completed mine)
  data/standings/inbox/*.csv|.zip -- already pulled, waiting to be mined
  data/standings/recorded_exceptions.json
                                   -- contests known dead or synthetic; see
                                      `mark-unrecoverable` / `mark-placeholder`
                                      below. Missing file means empty sets,
                                      not an error, so a fresh checkout still
                                      runs; the exclusion just starts thinner.

Outputs:
  data/standings/CONTESTS_AWAITING_STANDINGS.md  -- the pull list, oldest
      slate date first. Oldest first because the aging theory (ledger,
      2026-07-25) is that DK's export goes empty some days after a contest
      settles, so the oldest unpulled contests are the ones closest to that
      cliff, not the ones nearest 08-01's clean slate. (07-28 and 08-02's
      hand-written versions sorted newest-first while saying "pull oldest
      first" in the prose; this tool makes the order match the words.)
  data/standings/standings_pulls_<date>.html      -- the same list as a
      clickable checklist. Clicking a contest's export link also checks its
      box, so working through the list top to bottom needs one click per row,
      not two.

Usage:
    python tools/awaiting_standings.py scan
    python tools/awaiting_standings.py scan --check          # print, write nothing
    python tools/awaiting_standings.py scan --no-html
    python tools/awaiting_standings.py mark-unrecoverable 192345441 \\
        --reason "zero bytes on second pull, 2026-08-05"
    python tools/awaiting_standings.py mark-placeholder 199000001 \\
        --name "MLB $100K Relay Throw" --reason "synthetic entry ID, not a real contest"

Exit codes: 0 ok, 3 usage or IO error. `scan` always exits 0 once it can read
the inputs; there is nothing here to certify or block on.
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Real DraftKings contest IDs are 9 digits. Anything else on a filled entry
# row is a placeholder (manual/test rows use `0`, `900`, ...) rather than a
# contest DK will ever serve an export for.
CID_RE = re.compile(r"^\d{9}$")
MINED_JSON_RE = re.compile(r"^mined_(\d+)\.json$")
# R74(b): ANCHORED. `.search(r"(\d{9})")` matched the first 9 digits of any
# longer run, so an entry id or a timestamp in a filename could yield a real
# entered contest id and silently mark it pulled -- the one direction this
# tool exists to prevent. The lookarounds require the run to be exactly 9
# digits long.
INBOX_ID_RE = re.compile(r"(?<!\d)(\d{9})(?!\d)")


# The DK Classic roster headers, lowercased. A reserved row carries the contest
# columns and leaves these empty, which is what makes it reserved (R74c).
_ROSTER_HEADERS = frozenset({
    "p", "c", "1b", "2b", "3b", "ss", "of", "cpt", "util",
})


def _row_is_filled(
    row: list[str],
    entry_i: int | None,
    roster_i: list[int],
) -> bool:
    """True when this DKEntries row is an ENTERED entry rather than a reserved one.

    R74(c). Two independent signals, both required, because either alone is weak:
    a digit Entry ID (DK assigns one per reserved slot, so a blank here is a row
    the template made and nothing filled), and at least one roster cell carrying
    something. A file with no recognizable roster columns falls back to the Entry
    ID alone rather than rejecting every row, so an unexpected header shape
    degrades to the old behavior instead of emptying the pull list.
    """
    if entry_i is not None:
        value = row[entry_i].strip() if len(row) > entry_i else ""
        if not value.isdigit():
            return False
    if not roster_i:
        return entry_i is not None
    return any((row[i].strip() for i in roster_i if len(row) > i))


def _today(date_override: str | None = None) -> str:
    return date_override or datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


# --------------------------------------------------------------------------
# Scanning
# --------------------------------------------------------------------------

def scan_entered(outputs_dir: Path) -> tuple[dict[str, dict], dict[str, dict]]:
    """Every Contest ID on a filled entry row in outputs/*/DKEntries*.csv.

    Returns (entered, invalid): entered maps a 9-digit contest ID to
    {"date", "name"}; invalid maps a non-empty, non-9-digit Contest ID value
    to the same, so the caller can report what it filtered out instead of
    silently dropping it.
    """
    entered: dict[str, dict] = {}
    invalid: dict[str, dict] = {}
    if not outputs_dir.is_dir():
        return entered, invalid
    for date_dir in sorted(outputs_dir.iterdir()):
        if not date_dir.is_dir() or date_dir.name.startswith("_"):
            continue
        for csv_path in sorted(date_dir.glob("DKEntries*.csv")):
            try:
                with csv_path.open(encoding="utf-8-sig", errors="ignore", newline="") as fh:
                    reader = csv.reader(fh)
                    header = next(reader, None)
                    if not header:
                        continue
                    lowered = [h.strip().lower() for h in header]
                    if "contest id" not in lowered:
                        continue
                    cid_i = lowered.index("contest id")
                    name_i = lowered.index("contest name") if "contest name" in lowered else None
                    entry_i = (lowered.index("entry id")
                               if "entry id" in lowered else None)
                    # R74(c): the docstring says "every Contest ID on a FILLED
                    # entry row", and the loop read every row with a Contest ID
                    # cell -- including the blank reserved rows a DKEntries
                    # template carries, which enrolled never-entered contests
                    # into the pull list. A filled row has a digit Entry ID and
                    # at least one roster cell with something in it.
                    roster_i = [i for i, h in enumerate(lowered)
                                if h in _ROSTER_HEADERS]
                    for row in reader:
                        if len(row) <= cid_i:
                            continue
                        raw = row[cid_i].strip()
                        if not raw:
                            continue
                        if not _row_is_filled(row, entry_i, roster_i):
                            continue
                        name = row[name_i].strip() if name_i is not None and len(row) > name_i else ""
                        target = entered if CID_RE.match(raw) else invalid
                        target.setdefault(raw, {"date": date_dir.name, "name": name})
            except OSError:
                continue
    return entered, invalid


def archived_ids(data_dir: Path) -> set[str]:
    """Contest IDs with a completed mine, from data/archive/*/mined_<id>.json.

    Deliberately not a glob of raw standings CSV filenames: a CSV can land in
    the archive folder without a mine having actually finished (per the
    08-03 fragment on the inbox/archive tooling gap), and mined_*.json is the
    one artifact that only exists once the mine succeeded.
    """
    out: set[str] = set()
    archive_dir = data_dir / "archive"
    if not archive_dir.is_dir():
        return out
    for path in archive_dir.glob("*/mined_*.json"):
        m = MINED_JSON_RE.match(path.name)
        if m:
            out.add(m.group(1))
    return out


def inbox_ids(data_dir: Path) -> set[str]:
    """Contest IDs already sitting in data/standings/inbox/, pulled but not
    necessarily mined yet -- either way, not something to ask Ben to pull
    again."""
    out: set[str] = set()
    inbox_dir = data_dir / "standings" / "inbox"
    if not inbox_dir.is_dir():
        return out
    for path in inbox_dir.iterdir():
        if path.is_file() and path.suffix.lower() in (".csv", ".zip"):
            m = INBOX_ID_RE.search(path.stem)
            if m:
                out.add(m.group(1))
    return out


# --------------------------------------------------------------------------
# Exceptions: contests to exclude regardless of the file scan
# --------------------------------------------------------------------------

EXCEPTIONS_FILENAME = "recorded_exceptions.json"


def exceptions_path(data_dir: Path) -> Path:
    return data_dir / "standings" / EXCEPTIONS_FILENAME


def load_exceptions(data_dir: Path) -> dict:
    path = exceptions_path(data_dir)
    empty = {"unrecoverable": [], "placeholder": []}
    if not path.exists():
        print(f"note: {path} not found; unrecoverable/placeholder sets start empty", file=sys.stderr)
        return empty
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"warning: could not read {path}: {exc}; treating as empty", file=sys.stderr)
        return empty
    data.setdefault("unrecoverable", [])
    data.setdefault("placeholder", [])
    return data


def save_exceptions(data_dir: Path, data: dict) -> None:
    path = exceptions_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=False) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------
# Combine
# --------------------------------------------------------------------------

def compute_open(entered: dict[str, dict], have: set[str], exceptions: dict) -> dict[str, list[tuple[str, str]]]:
    excluded = set(have)
    excluded |= {e["contest_id"] for e in exceptions.get("unrecoverable", [])}
    excluded |= {e["contest_id"] for e in exceptions.get("placeholder", [])}
    by_date: dict[str, list[tuple[str, str]]] = {}
    for cid, meta in entered.items():
        if cid in excluded:
            continue
        by_date.setdefault(meta["date"], []).append((cid, meta["name"]))
    for date in by_date:
        by_date[date].sort()
    return by_date


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

def render_markdown(by_date: dict, archived_count: int, invalid: dict, exceptions: dict, today: str) -> str:
    total = sum(len(v) for v in by_date.values())
    dates_asc = sorted(by_date)  # oldest first -- see module docstring

    lines = [
        f"# Contests awaiting standings — regenerated {today}",
        "",
        "Scan: every 9-digit Contest ID on a filled entry row in `outputs/*/DKEntries*.csv`,",
        "minus the archived set (`data/archive/*/mined_*.json`), what's already sitting in",
        "`data/standings/inbox/`, and `data/standings/recorded_exceptions.json`. Generated by",
        "`python tools/awaiting_standings.py scan`; do not hand-maintain this list.",
        "",
        "Pull each while logged in to DraftKings, **check the file size is non-zero**, and",
        "drop it in `data/standings/inbox/`. A zero-byte export is a failed pull, not a",
        "pulled file. The inbox is flat; the miner reads Classic vs Showdown off the",
        "lineup cells and resolves the salary file itself (`--auto-salary`).",
        "",
        f"## Status as of {today}: {_plural(total, 'contest')} open across {_plural(len(dates_asc), 'slate date')}",
        "",
        "Prioritize oldest first. The 2026-07-25 ledger note found DK's export ages out",
        "some days after a contest settles, so the oldest rows below are the ones closest",
        "to going empty; the newest date has the most runway left.",
        "",
    ]
    for date in dates_asc:
        ids = by_date[date]
        lines.append(f"**{date}** ({_plural(len(ids), 'contest')}):")
        lines.append("")
        for cid, name in ids:
            url = f"https://www.draftkings.com/contest/exportfullstandingscsv/{cid}"
            lines.append(f"- [{name}]({url}) — `{cid}`")
        lines.append("")

    lines.append("## Not on this list — do not pull")
    lines.append("")
    lines.append(f"- **Archived** ({_plural(archived_count, 'contest')}) — already mined into `data/archive/`;")
    lines.append("  see the ledger's A-NNN entries for the per-contest mapping.")
    if invalid:
        lines.append("- **Non-DK IDs on filled entry rows** — filtered out because a real contest ID is")
        lines.append("  9 digits; these would otherwise emit a dead export URL:")
        for raw, meta in sorted(invalid.items()):
            label = f"`{raw}`"
            if meta.get("name"):
                label += f" (`{meta['name']}`, {meta['date']})"
            lines.append(f"  - {label}")
    placeholder = exceptions.get("placeholder", [])
    if placeholder:
        lines.append("- **Recorded placeholder** — synthetic IDs, not real DK contests:")
        for e in placeholder:
            lines.append(f"  - `{e['contest_id']}`" + (f" (`{e['name']}`)" if e.get("name") else "") + f" — {e['reason']}")
    unrecoverable = exceptions.get("unrecoverable", [])
    if unrecoverable:
        lines.append("- **Recorded unrecoverable** — landed at 0 bytes and stayed at 0 bytes on")
        lines.append("  re-pull; do not re-attempt:")
        for e in unrecoverable:
            lines.append(f"  - `{e['contest_id']}` — {e['reason']}")
    lines.append("")
    return "\n".join(lines)


_HTML_STYLE = """
  :root {
    --bg: #0f1115; --panel: #171a21; --border: #2a2e38;
    --text: #e6e8ec; --muted: #8b93a3; --accent: #4f8cff;
    --done-bg: #10241a; --done-text: #5fbd8a;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 32px 16px 80px;
    background: var(--bg); color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
  }
  .wrap { max-width: 780px; margin: 0 auto; }
  h1 { font-size: 20px; margin: 0 0 4px; }
  .sub { color: var(--muted); font-size: 14px; line-height: 1.5; margin: 0 0 24px; }
  .sub b { color: var(--text); }
  .sub code { background: var(--panel); padding: 1px 5px; border-radius: 4px; }
  .progress {
    position: sticky; top: 0; z-index: 5;
    background: var(--bg); padding: 8px 0 16px; font-size: 13px; color: var(--muted);
  }
  #progressBar { height: 6px; background: var(--border); border-radius: 3px; overflow: hidden; margin-top: 6px; }
  #progressFill { height: 100%; width: 0%; background: var(--accent); transition: width .15s; }
  section { margin-bottom: 28px; }
  h2 {
    font-size: 15px; border-bottom: 1px solid var(--border); padding-bottom: 6px;
    margin: 0 0 10px; display: flex; align-items: baseline; gap: 8px;
  }
  h2 .count { color: var(--muted); font-weight: normal; font-size: 13px; }
  ul.rows { list-style: none; margin: 0; padding: 0; }
  li.row {
    display: flex; align-items: center; gap: 10px;
    background: var(--panel); border: 1px solid var(--border);
    border-radius: 8px; padding: 9px 12px; margin-bottom: 6px;
    font-size: 13.5px;
  }
  li.row.done { background: var(--done-bg); border-color: #1d3b2a; }
  li.row.done .name { color: var(--done-text); text-decoration: line-through; }
  .chk input { width: 16px; height: 16px; cursor: pointer; }
  .name { flex: 1; min-width: 0; overflow-wrap: anywhere; }
  .cid { color: var(--muted); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; flex-shrink: 0; }
  a.pull {
    flex-shrink: 0; color: #fff; background: var(--accent); text-decoration: none;
    font-size: 12.5px; padding: 6px 10px; border-radius: 6px; white-space: nowrap;
  }
  a.pull:hover { background: #3d78e6; }
"""

_HTML_SCRIPT = """
  const total = __TOTAL__;
  function updateProgress() {
    const done = document.querySelectorAll('li.row.done').length;
    document.getElementById('progressLabel').textContent = done + ' / ' + total + ' pulled';
    document.getElementById('progressFill').style.width = (total ? (done / total * 100) : 0) + '%';
  }
  document.querySelectorAll('li.row').forEach(row => {
    const cb = row.querySelector('input[type=checkbox]');
    const link = row.querySelector('a.pull');
    function setDone(v) {
      cb.checked = v;
      row.classList.toggle('done', v);
      updateProgress();
    }
    cb.addEventListener('change', () => setDone(cb.checked));
    // Clicking the export link opens the download AND checks the box off --
    // one click per contest instead of two.
    link.addEventListener('click', () => setDone(true));
  });
"""


def render_html(by_date: dict, today: str) -> str:
    total = sum(len(v) for v in by_date.values())
    dates_asc = sorted(by_date)  # oldest first, matching the markdown priority order

    sections = []
    for date in dates_asc:
        ids = by_date[date]
        rows = []
        for cid, name in ids:
            url = f"https://www.draftkings.com/contest/exportfullstandingscsv/{cid}"
            rows.append(
                '      <li class="row">\n'
                '        <label class="chk"><input type="checkbox"></label>\n'
                f'        <span class="name">{html.escape(name)}</span>\n'
                f'        <span class="cid">{html.escape(cid)}</span>\n'
                f'        <a class="pull" href="{html.escape(url)}" target="_blank" rel="noopener">Open export ↗</a>\n'
                "      </li>"
            )
        sections.append(
            f'    <section>\n      <h2>{date} <span class="count">({_plural(len(ids), "contest")})</span></h2>\n'
            f'      <ul class="rows">\n{chr(10).join(rows)}\n      </ul>\n    </section>'
        )
    sections_html = "\n".join(sections)
    script = _HTML_SCRIPT.replace("__TOTAL__", str(total))

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Standings pulls needed — {today}</title>
<style>{_HTML_STYLE}</style>
</head>
<body>
<div class="wrap">
  <h1>Standings pulls needed</h1>
  <p class="sub">
    <b>{_plural(total, 'contest')}</b> across <b>{_plural(len(dates_asc), 'slate date')}</b>, generated {today}.
    Click <b>Open export</b> while logged into DraftKings; it opens the download and checks the row
    off for you. Confirm the download is non-zero bytes, then drop it in
    <code>data/standings/inbox/</code>. Oldest date first — DK's export is known to age out after
    a few days, so those are the most at risk.
  </p>
  <div class="progress">
    <span id="progressLabel">0 / {total} pulled</span>
    <div id="progressBar"><div id="progressFill"></div></div>
  </div>

{sections_html}

</div>
<script>{script}</script>
</body>
</html>
"""


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def cmd_scan(args: argparse.Namespace) -> int:
    root = Path(args.root)
    outputs_dir = root / args.outputs_dir
    data_dir = root / args.data_dir

    entered, invalid = scan_entered(outputs_dir)
    have = archived_ids(data_dir) | inbox_ids(data_dir)
    exceptions = load_exceptions(data_dir)
    by_date = compute_open(entered, have, exceptions)
    today = _today(args.date)
    total = sum(len(v) for v in by_date.values())

    md = render_markdown(by_date, len(archived_ids(data_dir)), invalid, exceptions, today)

    if args.check:
        print(md)
        print(f"\n[check] {_plural(total, 'contest')} open across {_plural(len(by_date), 'date')}; "
              f"nothing written", file=sys.stderr)
        return 0

    md_out = root / args.md_out
    md_out.parent.mkdir(parents=True, exist_ok=True)
    md_out.write_text(md, encoding="utf-8")
    print(f"wrote {md_out} ({_plural(total, 'contest')}, {_plural(len(by_date), 'date')})")

    if not args.no_html:
        html_out = root / (args.html_out or f"data/standings/standings_pulls_{today}.html")
        html_out.parent.mkdir(parents=True, exist_ok=True)
        html_out.write_text(render_html(by_date, today), encoding="utf-8")
        print(f"wrote {html_out}")

    return 0


def cmd_mark_unrecoverable(args: argparse.Namespace) -> int:
    data_dir = Path(args.root) / args.data_dir
    exc = load_exceptions(data_dir)
    if any(e["contest_id"] == args.contest_id for e in exc["unrecoverable"]):
        print(f"{args.contest_id} is already recorded unrecoverable")
        return 0
    exc["unrecoverable"].append({
        "contest_id": args.contest_id,
        "reason": args.reason,
        "recorded": _today(args.date),
    })
    save_exceptions(data_dir, exc)
    print(f"recorded {args.contest_id} as unrecoverable: {args.reason}")
    return 0


def cmd_mark_placeholder(args: argparse.Namespace) -> int:
    data_dir = Path(args.root) / args.data_dir
    exc = load_exceptions(data_dir)
    if any(e["contest_id"] == args.contest_id for e in exc["placeholder"]):
        print(f"{args.contest_id} is already recorded as a placeholder")
        return 0
    exc["placeholder"].append({
        "contest_id": args.contest_id,
        "name": args.name or "",
        "reason": args.reason,
    })
    save_exceptions(data_dir, exc)
    print(f"recorded {args.contest_id} as a placeholder: {args.reason}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path, default=REPO, help=argparse.SUPPRESS)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("scan", help="write the awaiting-standings markdown and HTML checklist")
    p.add_argument("--outputs-dir", default="outputs")
    p.add_argument("--data-dir", default="data")
    p.add_argument("--md-out", default="data/standings/CONTESTS_AWAITING_STANDINGS.md")
    p.add_argument("--html-out", default=None, help="default: data/standings/standings_pulls_<date>.html")
    p.add_argument("--no-html", action="store_true", help="write only the markdown")
    p.add_argument("--date", help="UTC date stamp; defaults to today")
    p.add_argument("--check", action="store_true", help="print the markdown, write nothing")

    p = sub.add_parser("mark-unrecoverable", help="record a contest as a dead pull, excluded from now on")
    p.add_argument("contest_id")
    p.add_argument("--reason", required=True)
    p.add_argument("--data-dir", default="data")
    p.add_argument("--date", help="UTC date stamp; defaults to today")

    p = sub.add_parser("mark-placeholder", help="record a synthetic/non-DK ID, excluded from now on")
    p.add_argument("contest_id")
    p.add_argument("--name", default="")
    p.add_argument("--reason", required=True)
    p.add_argument("--data-dir", default="data")

    args = ap.parse_args(argv)
    handler = {
        "scan": cmd_scan,
        "mark-unrecoverable": cmd_mark_unrecoverable,
        "mark-placeholder": cmd_mark_placeholder,
    }[args.cmd]
    try:
        return handler(args)
    except OSError as exc:
        print(f"ERROR  {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
