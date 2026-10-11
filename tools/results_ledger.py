#!/usr/bin/env python3
"""results_ledger.py -- the DraftKings contest entry-history export, read per entry (R496).

Ben downloads the entry-history export by hand (one row per entry he ever
entered, every sport and contest type) and commits it as
`data/reference/draftkings-contest-entry-history_<last contest date>.csv`. This
tool reads those files and nothing on DraftKings.

    python tools/results_ledger.py ingest [EXPORT ...] [--out PATH]

`ingest` validates the 14 export columns by name, dedupes by `Entry_Key` across
every export it is given (identical rows merge; a row that disagrees refuses),
and writes `data/reference/dk_entry_results.csv`, one row per entry, every sport
kept: the 14 source columns verbatim plus the derived columns below, and a
`.meta.json` sidecar naming each source's sha256 and row count. With no EXPORT
it reads every committed export, sorted.

Per entry:
  finish_pctl    (Place - 1) / (Contest_Entries - 1): 0 is first, 1 is last,
                 and a uniform finisher averages 0.5 at every field size.
  place_over_n   the results review's Place / N, beside its own uniform
                 reference (N + 1) / (2N), which is 52.3 in a field of 25.
  top_decile     Place <= floor(0.1 N), against top_ref = floor(0.1 N) / N.
  bottom_decile  Place >= ceil(0.9 N), against bottom_ref = (N - ceil(0.9 N) + 1) / N.
                 Never a flat 10%: the share a uniform finisher lands in each
                 band depends on N.
  blank_class    zero-point entries only, from lineup evidence first:
                 zero_complete    the archived standings hold a complete lineup;
                 blank_no_lineup  the archived lineup is empty, or every entry of
                                  ours in the contest scored 0;
                 zero_unknown     otherwise.
  engine_record  MLB only: `present` when a delivery record names the Entry ID,
                 `absent` when none does, `pre_records` when the contest predates
                 the first delivery record (absence there says nothing). Which
                 record was entered is R497's question, not this column's.
  start_block    date, start time and game type: the export's stand-in for a
                 draftgroup, which it does not carry.

Labels: every figure is an observed outcome, never ROI, a win rate, a cash rate
or a probability; the uniform reference is arithmetic. Family and archetype are
inferred from the contest title (a labelled prior). Ticket face value is not
realized value. `data/reference/` is ARCHIVE's write set: a DEV session points
`--out` at a scratch path.

Exit codes: 0 ok, 2 refused input (a missing column, an unparsable cell, a
duplicate Entry_Key that disagrees), 3 IO (a missing file, no export found).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import sys
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

# Pinned before any import that hashes, like every entry point (CLAUDE.md
# determinism). Script only: importing this module never replaces the importer.
if (__name__ == "__main__" and os.environ.get("PYTHONHASHSEED") != "0"
        and sys.executable):
    try:
        os.execve(sys.executable, [sys.executable, *sys.argv],
                  {**os.environ, "PYTHONHASHSEED": "0"})
    except OSError:
        pass

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

EXPORT_COLUMNS: Tuple[str, ...] = (
    "Sport", "Game_Type", "Entry_Key", "Entry", "Contest_Key", "Contest_Date_EST",
    "Place", "Points", "Winnings_Non_Ticket", "Winnings_Ticket", "Contest_Entries",
    "Entry_Fee", "Prize_Pool", "Places_Paid",
)
MONEY_COLUMNS = ("Winnings_Non_Ticket", "Winnings_Ticket", "Entry_Fee", "Prize_Pool")
INT_COLUMNS = ("Entry_Key", "Contest_Key", "Place", "Contest_Entries", "Places_Paid")
EXPORT_GLOB = "draftkings-contest-entry-history_*.csv"
REFERENCE_DIR = Path("data") / "reference"
ARCHIVE_DIR = Path("data") / "archive"
RESULTS_NAME = "dk_entry_results.csv"
SIDECAR_SUFFIX = ".meta.json"
SCHEMA = "dk_entry_results/1"

# Upper bound of each field-size band, inclusive; anything larger is ">100K".
FIELD_BANDS: Tuple[Tuple[int, str], ...] = (
    (25, "<=25"), (100, "26-100"), (500, "101-500"), (2000, "501-2K"),
    (10000, "2K-10K"), (100000, "10K-100K"),
)
FIELD_BAND_OVER = ">100K"
BLANK_CLASSES = ("blank_no_lineup", "zero_unknown", "zero_complete")
# The archived standings row for a zero-point entry. `incomplete` is
# parse_lineup_string's not-complete: an empty Lineup cell, or a partial one
# (0 partial cells in the 610 archived files on 2026-10-11).
ARCHIVE_LINEUP_VALUES = ("complete", "incomplete", "absent", "no_standings", "unreadable")
TURBO_RE = re.compile(r"\bturbo\b", re.IGNORECASE)
MONEY_RE = re.compile(r"^-?\$?-?[\d,]*\.?\d+$")

DERIVED_COLUMNS: Tuple[str, ...] = (
    "fee", "cash", "ticket", "net", "slate", "start_block", "month", "field_band",
    "archetype", "family", "single_entry", "turbo", "finish_pctl", "place_over_n",
    "place_over_n_ref", "top_decile", "top_ref", "bottom_decile", "bottom_ref",
    "zero_points", "archive_lineup", "blank_class", "engine_record",
)
RESULTS_COLUMNS: Tuple[str, ...] = EXPORT_COLUMNS + DERIVED_COLUMNS

EXIT_OK, EXIT_REFUSED, EXIT_IO = 0, 2, 3

LABELS: Tuple[str, ...] = (
    "Observed outcomes from Ben's DraftKings entry-history export; review figures only.",
    "Uniform reference: what a finisher drawn uniformly from each contest's own field "
    "would show; arithmetic, not a forecast.",
    "Net = cash + ticket face - fees; ticket face is not realized value, and the "
    "promotional channel is unmeasured (Ben, 2026-07-29).",
    "Family and archetype are inferred from the contest title (a labelled prior).",
)


class Refused(Exception):
    """Input this tool will not read; the message names the cell or column."""


# ---------------------------------------------------------------------------
# Reading the export
# ---------------------------------------------------------------------------

def parse_money(cell: str) -> Decimal:
    """`$1,234.56` -> Decimal('1234.56'). Raises ValueError on anything else."""
    text = str(cell).strip()
    if not MONEY_RE.match(text):
        raise ValueError(text)
    negative = text.count("-") % 2 == 1
    try:
        value = Decimal(text.replace("$", "").replace(",", "").replace("-", ""))
    except InvalidOperation as exc:
        raise ValueError(text) from exc
    return -value if negative else value


def _validate_row(row: Mapping[str, str], where: str) -> None:
    key = row.get("Entry_Key", "")
    for col in INT_COLUMNS:
        if not str(row[col]).strip().isdigit():
            raise Refused(f"{where}: Entry_Key {key or '?'}: {col} is not a whole number: {row[col]!r}")
    for col in MONEY_COLUMNS:
        try:
            parse_money(row[col])
        except ValueError:
            raise Refused(f"{where}: Entry_Key {key}: {col} is not a dollar amount: {row[col]!r}") from None
    try:
        float(str(row["Points"]).strip())
    except ValueError:
        raise Refused(f"{where}: Entry_Key {key}: Points is not a number: {row['Points']!r}") from None
    if not re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}", str(row["Contest_Date_EST"]).strip()):
        raise Refused(f"{where}: Entry_Key {key}: Contest_Date_EST is not 'YYYY-MM-DD HH:MM': "
                      f"{row['Contest_Date_EST']!r}")


def read_export(path: Path) -> Dict[str, Any]:
    """One export: its rows (the 14 columns as strings), sha256 and extras.

    Columns are checked by NAME, so a reordered export still reads; a missing
    one refuses naming every column that is absent. Extra columns are ignored
    and named, because a new DK column is news, not an error.
    """
    raw = Path(path).read_bytes()
    text = raw.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text, newline=""))
    header = [str(h).strip() for h in (reader.fieldnames or [])]
    if not header:
        raise Refused(f"{path}: empty file, no header")
    missing = [c for c in EXPORT_COLUMNS if c not in header]
    if missing:
        raise Refused(f"{path}: missing column(s): {', '.join(missing)} "
                      f"(the entry-history export has {len(EXPORT_COLUMNS)}: {', '.join(EXPORT_COLUMNS)})")
    extras = sorted(h for h in header if h not in EXPORT_COLUMNS)
    rows: List[Dict[str, str]] = []
    for n, rec in enumerate(reader, start=2):
        row = {c: str(rec.get(c) if rec.get(c) is not None else "").strip() for c in EXPORT_COLUMNS}
        if not any(row.values()):
            continue
        _validate_row(row, f"{path}:{n}")
        rows.append(row)
    return {"path": Path(path), "sha256": hashlib.sha256(raw).hexdigest(),
            "rows": rows, "extras": extras}


def merge_exports(exports: Sequence[Mapping[str, Any]]) -> Tuple[Dict[str, Dict[str, str]], int]:
    """Dedupe by Entry_Key across (and within) exports.

    Identical rows merge silently and are counted; a row that disagrees with an
    earlier one for the same Entry_Key refuses, naming the key, the columns that
    differ and both files. An export is a DK statement of fact about a finished
    contest; two that disagree need a person, not a tiebreak.
    """
    merged: Dict[str, Dict[str, str]] = {}
    origin: Dict[str, str] = {}
    identical = 0
    for export in exports:
        for row in export["rows"]:
            key = row["Entry_Key"]
            prior = merged.get(key)
            if prior is None:
                merged[key] = row
                origin[key] = str(export["path"])
                continue
            differs = [c for c in EXPORT_COLUMNS if prior[c] != row[c]]
            if differs:
                detail = "; ".join(f"{c} {prior[c]!r} vs {row[c]!r}" for c in differs)
                raise Refused(f"Entry_Key {key} disagrees between {origin[key]} and "
                              f"{export['path']}: {detail}")
            identical += 1
    return merged, identical


# ---------------------------------------------------------------------------
# Per-entry arithmetic (shared by ingest and report)
# ---------------------------------------------------------------------------

def top_cut(n: int) -> int:
    """floor(0.1 n), in integers: the last top-decile place."""
    return int(n) // 10


def bottom_cut(n: int) -> int:
    """ceil(0.9 n), in integers: the first bottom-decile place."""
    return (9 * int(n) + 9) // 10


def uniform_reference(n: int) -> Dict[str, float]:
    """A uniform finisher's top- and bottom-decile share and place/N mean at field size n."""
    n = int(n)
    if n < 1:
        raise ValueError(f"field size must be positive, got {n}")
    return {
        "top_ref": top_cut(n) / n,
        "bottom_ref": (n - bottom_cut(n) + 1) / n,
        "place_over_n_ref": (n + 1) / (2 * n),
    }


def entry_numbers(place: int, n: int) -> Dict[str, Any]:
    """Finish percentile, place/N and decile membership for one entry."""
    place, n = int(place), int(n)
    ref = uniform_reference(n)
    return {
        "finish_pctl": (place - 1) / (n - 1) if n >= 2 else None,
        "place_over_n": place / n,
        "place_over_n_ref": ref["place_over_n_ref"],
        "top_decile": place <= top_cut(n),
        "top_ref": ref["top_ref"],
        "bottom_decile": place >= bottom_cut(n),
        "bottom_ref": ref["bottom_ref"],
    }


def field_band(n: int) -> str:
    for upper, label in FIELD_BANDS:
        if int(n) <= upper:
            return label
    return FIELD_BAND_OVER


def classify_zero(archive_lineup: str, all_ours_zero: bool) -> str:
    """The blank class of a zero-point entry, lineup evidence before the heuristic.

    1. A complete archived lineup that scored 0 is a lineup, not a blank.
    2. An archived row with no complete lineup is a blank on its own evidence,
       whatever our other entries in the contest scored.
    3. With no archived row, a contest where every entry of ours scored 0 is
       read as never filled (the 93 MLB blanks sit in whole start-time blocks).
    4. Anything else (a zero beside scoring siblings, no standings) is unknown.
    """
    if archive_lineup == "complete":
        return "zero_complete"
    if archive_lineup == "incomplete":
        return "blank_no_lineup"
    if all_ours_zero:
        return "blank_no_lineup"
    return "zero_unknown"


# ---------------------------------------------------------------------------
# Evidence outside the export: archived standings, delivery records, titles
# ---------------------------------------------------------------------------

def _rel(path: Path, root: Path) -> str:
    try:
        return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return Path(path).as_posix()


def archive_lineups(root: Path, entries_by_contest: Mapping[str, Sequence[str]]
                    ) -> Tuple[Dict[str, str], List[str], List[str]]:
    """Archived lineup state for each named Entry ID, from the raw standings CSVs.

    Only the raw `contest-standings-<cid>.csv` can tell an empty lineup from an
    absent entry: the mined JSON keeps complete lineups only. A contest can be
    filed under another date folder (after midnight ET), so every date is
    searched. Returns ({entry_id: state}, files read, files unreadable).
    """
    from mlb_engine.field.field_miner import parse_standings_export

    state: Dict[str, str] = {}
    read: List[str] = []
    unreadable: List[str] = []
    archive = Path(root) / ARCHIVE_DIR
    for cid in sorted(entries_by_contest, key=int):
        wanted = sorted(set(entries_by_contest[cid]))
        files = sorted(archive.glob(f"*/contest-standings-{cid}.csv")) if archive.is_dir() else []
        if not files:
            state.update({e: "no_standings" for e in wanted})
            continue
        found: Dict[str, bool] = {}
        any_read = False
        for path in files:
            try:
                parsed = parse_standings_export(str(path))
            except (ValueError, OSError, csv.Error):
                unreadable.append(_rel(path, root))
                continue
            any_read = True
            read.append(_rel(path, root))
            for entry in parsed["entries"]:
                eid = entry["entry_id"]
                if eid in wanted:
                    found[eid] = found.get(eid, False) or bool(entry["lineup_complete"])
        for eid in wanted:
            if eid in found:
                state[eid] = "complete" if found[eid] else "incomplete"
            else:
                state[eid] = "absent" if any_read else "unreadable"
    return state, read, unreadable


def delivery_presence(root: Path) -> Tuple[set, Optional[str], int]:
    """Entry IDs named by any delivery record, the earliest record date, the record count."""
    from mlb_engine.entries.delivery_record import read_records

    ids: set = set()
    dates: List[str] = []
    count = 0
    for record in read_records(root=Path(root)):
        if record.get("kind") != "delivery":
            continue
        count += 1
        if record.get("date"):
            dates.append(str(record["date"]))
        for entry in record.get("entries") or []:
            if entry.get("entry_id") not in (None, ""):
                ids.add(str(entry["entry_id"]).strip())
    return ids, (min(dates) if dates else None), count


def title_archetypes(titles: Iterable[Tuple[str, Decimal]]) -> Dict[Tuple[str, Decimal], Dict[str, Any]]:
    """Archetype per (contest title, fee), from the engine's curated title inference."""
    from mlb_engine.entries import dk_entries_manager as dm

    curated = dm.load_archetypes(dm.find_archetypes_csv())
    out: Dict[Tuple[str, Decimal], Dict[str, Any]] = {}
    for title, fee in sorted(set(titles)):
        inferred = dm.infer_contest_archetype(title, float(fee), curated)
        archetype = str(inferred.get("inferred_type") or "unknown")
        out[(title, fee)] = {
            "archetype": archetype,
            # The results review's rollup: satellites, cash, and every other
            # contest as GPP (its 1,435-entry MLB cell).
            "family": archetype if archetype in ("satellite", "cash") else "gpp",
            "single_entry": inferred.get("inferred_max_entries") == 1,
        }
    return out


# ---------------------------------------------------------------------------
# ingest
# ---------------------------------------------------------------------------

def _fmt_money(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01'))}"


def _fmt_float(value: Optional[float]) -> str:
    return "" if value is None else f"{value:.6f}"


def derive_rows(merged: Mapping[str, Mapping[str, str]], root: Path) -> Dict[str, Any]:
    """Every entry with its derived columns, plus the evidence the sidecar names."""
    rows = sorted(merged.values(), key=lambda r: (r["Contest_Date_EST"], int(r["Contest_Key"]),
                                                  int(r["Entry_Key"])))
    points_by_contest: Dict[str, List[float]] = defaultdict(list)
    for r in rows:
        points_by_contest[r["Contest_Key"]].append(float(r["Points"]))
    zero_by_contest: Dict[str, List[str]] = defaultdict(list)
    for r in rows:
        if float(r["Points"]) == 0:
            zero_by_contest[r["Contest_Key"]].append(r["Entry_Key"])
    lineups, standings_read, standings_unreadable = archive_lineups(root, zero_by_contest)
    record_ids, earliest_record, record_count = delivery_presence(root)
    archetypes = title_archetypes((r["Entry"], parse_money(r["Entry_Fee"])) for r in rows)

    out: List[Dict[str, str]] = []
    for r in rows:
        fee = parse_money(r["Entry_Fee"])
        cash = parse_money(r["Winnings_Non_Ticket"])
        ticket = parse_money(r["Winnings_Ticket"])
        date = r["Contest_Date_EST"][:10]
        nums = entry_numbers(int(r["Place"]), int(r["Contest_Entries"]))
        title = archetypes[(r["Entry"], fee)]
        zero = float(r["Points"]) == 0
        lineup = lineups.get(r["Entry_Key"], "") if zero else ""
        blank = classify_zero(lineup, not any(points_by_contest[r["Contest_Key"]])) if zero else ""
        if r["Sport"] != "MLB":
            engine = ""
        elif r["Entry_Key"] in record_ids:
            engine = "present"
        elif earliest_record is None or date < earliest_record:
            engine = "pre_records"
        else:
            engine = "absent"
        derived = {
            "fee": _fmt_money(fee), "cash": _fmt_money(cash), "ticket": _fmt_money(ticket),
            "net": _fmt_money(cash + ticket - fee),
            "slate": f"{r['Sport']}|{date}|{r['Game_Type']}",
            "start_block": f"{r['Contest_Date_EST'][:16]}|{r['Game_Type']}",
            "month": date[:7],
            "field_band": field_band(int(r["Contest_Entries"])),
            "archetype": title["archetype"], "family": title["family"],
            "single_entry": "1" if title["single_entry"] else "0",
            "turbo": "1" if TURBO_RE.search(r["Entry"]) else "0",
            "finish_pctl": _fmt_float(nums["finish_pctl"]),
            "place_over_n": _fmt_float(nums["place_over_n"]),
            "place_over_n_ref": _fmt_float(nums["place_over_n_ref"]),
            "top_decile": "1" if nums["top_decile"] else "0",
            "top_ref": _fmt_float(nums["top_ref"]),
            "bottom_decile": "1" if nums["bottom_decile"] else "0",
            "bottom_ref": _fmt_float(nums["bottom_ref"]),
            "zero_points": "1" if zero else "0",
            "archive_lineup": lineup, "blank_class": blank, "engine_record": engine,
        }
        out.append({**{c: r[c] for c in EXPORT_COLUMNS}, **derived})
    return {"rows": out, "standings_read": sorted(set(standings_read)),
            "standings_unreadable": sorted(set(standings_unreadable)),
            "delivery_records": record_count, "earliest_delivery_record": earliest_record}


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp{os.getpid()}")
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    os.replace(tmp, path)


def write_results(path: Path, rows: Sequence[Mapping[str, str]]) -> None:
    lines: List[str] = []

    class _Sink:
        def write(self, s: str) -> None:
            lines.append(s)

    writer = csv.DictWriter(_Sink(), fieldnames=list(RESULTS_COLUMNS), lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    _atomic_write(Path(path), "".join(lines))


def sidecar_path(results: Path) -> Path:
    results = Path(results)
    return results.with_name(results.stem + SIDECAR_SUFFIX)


def cmd_ingest(args: argparse.Namespace) -> int:
    root = Path(args.root)
    if args.exports:
        paths = [Path(p) for p in args.exports]
    else:
        paths = sorted((root / REFERENCE_DIR).glob(EXPORT_GLOB))
        if not paths:
            print(f"ERROR  no export matches {(REFERENCE_DIR / EXPORT_GLOB).as_posix()} under {root}; "
                  "Ben downloads the entry-history export from DraftKings by hand", file=sys.stderr)
            return EXIT_IO
    exports = [read_export(p) for p in paths]
    for export in exports:
        if export["extras"]:
            print(f"note   {export['path']}: ignoring column(s) not in the export contract: "
                  f"{', '.join(export['extras'])}")
    merged, identical = merge_exports(exports)
    derived = derive_rows(merged, root)
    out = Path(args.out) if args.out else root / REFERENCE_DIR / RESULTS_NAME
    write_results(out, derived["rows"])
    sports: Dict[str, int] = defaultdict(int)
    blanks: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for row in derived["rows"]:
        sports[row["Sport"]] += 1
        if row["blank_class"]:
            blanks[row["Sport"]][row["blank_class"]] += 1
    meta = {
        "schema": SCHEMA,
        "tool": "tools/results_ledger.py ingest (R496)",
        "sources": sorted(({"path": _rel(e["path"], root), "sha256": e["sha256"], "rows": len(e["rows"])}
                           for e in exports), key=lambda s: (s["path"], s["sha256"])),
        "rows_out": len(derived["rows"]),
        "identical_rows_merged": identical,
        "sports": dict(sorted(sports.items())),
        "blank_classes": {s: dict(sorted(c.items())) for s, c in sorted(blanks.items())},
        "standings_read": derived["standings_read"],
        "standings_unreadable": derived["standings_unreadable"],
        "delivery_records": derived["delivery_records"],
        "earliest_delivery_record": derived["earliest_delivery_record"],
        "labels": list(LABELS),
    }
    _atomic_write(sidecar_path(out), json.dumps(meta, indent=1, sort_keys=True) + "\n")
    print(f"ingest  {len(derived['rows'])} entries from {len(exports)} export(s), "
          f"{identical} identical row(s) merged  -> {out}")
    for sport, counts in sorted(blanks.items()):
        print(f"        {sport} zero-point entries: "
              + ", ".join(f"{c} {counts.get(c, 0)}" for c in BLANK_CLASSES))
    print(f"        standings read for zero-point contests: {len(derived['standings_read'])}; "
          f"delivery records: {derived['delivery_records']} (earliest "
          f"{derived['earliest_delivery_record'] or 'none'})")
    return EXIT_OK


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path, default=REPO, help=argparse.SUPPRESS)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("ingest", help="validate, dedupe and derive; write dk_entry_results.csv")
    p.add_argument("exports", nargs="*",
                   help=f"export CSVs; default every data/reference/{EXPORT_GLOB}")
    p.add_argument("--out", default=None,
                   help=f"default data/reference/{RESULTS_NAME} (ARCHIVE's write set)")

    args = ap.parse_args(argv)
    handler = {"ingest": cmd_ingest}[args.cmd]
    try:
        return handler(args)
    except Refused as exc:
        print(f"REFUSED  {exc}", file=sys.stderr)
        return EXIT_REFUSED
    except OSError as exc:
        print(f"ERROR  {exc}", file=sys.stderr)
        return EXIT_IO


if __name__ == "__main__":
    raise SystemExit(main())
