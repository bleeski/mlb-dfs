#!/usr/bin/env python3
"""results_ledger.py -- the DraftKings contest entry-history export, read per entry (R496).

Ben downloads the entry-history export by hand (one row per entry he ever
entered, every sport and contest type) and commits it as
`data/reference/draftkings-contest-entry-history_<last contest date>.csv`. This
tool reads those files and nothing on DraftKings.

    python tools/results_ledger.py ingest [EXPORT ...] [--out PATH]
    python tools/results_ledger.py report [--sport MLB] [--results PATH] [--exclude-blanks] [--json]
    python tools/results_ledger.py resolve [--results PATH] [--out PATH] [--json]

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

`resolve` (R497) answers which delivery record each entry was entered from,
since most entry IDs sit in several records (baseline, rebuild, repair, late
swap) and the upload is manual. Every candidate record's roster is scored in
integer thousandths from the player points of any standings export of the
entry's draftgroup (a Showdown captain at 1.5x its UTIL row) and matched to the
entry's Points, rounded half-up to hundredths as DK's export rounds them:
  resolved      one record's roster scores the Points (`by: points`), or the
                matching records are one file recorded twice (`same_bytes`),
                or only one of them cleared preflight (`preflight_sidecar`)
  tied          matching records nothing above tells apart
  unmatched     every roster scored and none matches (a hand edit, a swap
                outside the records)
  unscored      a roster names a player no export of the draftgroup lists,
                one scored two ways, or a contest type the export contradicts
  no_standings  no export of any contest of the draftgroup
  no_crosswalk  no players map, salary file or DKEntries file names an ID
It writes `data/reference/dk_entry_resolution.csv` (`--out` for DEV) and a
`.meta.json`, and `tools/outcome_review.py` grades only resolved records.

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
import math
import os
import re
import sys
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
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
# One optional leading minus, an optional dollar sign, digits with well-placed
# thousands commas, at most two decimals: `$1,234.56`, `-$0.25`, `5`.
MONEY_RE = re.compile(r"^-?\$?(\d{1,3}(,\d{3})+|\d+)(\.\d{1,2})?$")

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
    try:
        value = Decimal(text.replace("$", "").replace(",", "").replace("-", ""))
    except InvalidOperation as exc:
        raise ValueError(text) from exc
    return -value if text.startswith("-") else value


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
        points = float(str(row["Points"]).strip())
    except ValueError:
        points = math.nan
    if not math.isfinite(points):
        raise Refused(f"{where}: Entry_Key {key}: Points is not a number: {row['Points']!r}")
    place, n = int(row["Place"]), int(row["Contest_Entries"])
    if n < 1 or not 1 <= place <= n:
        raise Refused(f"{where}: Entry_Key {key}: Place {place} is not a finish in a field of "
                      f"Contest_Entries {n}")
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
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise Refused(f"{path}: not UTF-8 at byte {exc.start} ({raw[exc.start:exc.start + 1]!r}); "
                      "re-download the export rather than re-saving it") from None
    reader = csv.DictReader(io.StringIO(text, newline=""))
    header = [str(h).strip() for h in (reader.fieldnames or [])]
    if not header:
        raise Refused(f"{path}: empty file, no header")
    # Read by the stripped names too, so a padded header cell is the column it names.
    reader.fieldnames = header
    missing = [c for c in EXPORT_COLUMNS if c not in header]
    if missing:
        raise Refused(f"{path}: missing column(s): {', '.join(missing)} "
                      f"(the entry-history export has {len(EXPORT_COLUMNS)}: {', '.join(EXPORT_COLUMNS)})")
    extras = sorted(h for h in header if h not in EXPORT_COLUMNS)
    rows: List[Dict[str, str]] = []
    lines: List[int] = []
    for n, rec in enumerate(reader, start=2):
        row = {c: str(rec.get(c) if rec.get(c) is not None else "").strip() for c in EXPORT_COLUMNS}
        if not any(row.values()):
            continue
        _validate_row(row, f"{path}:{n}")
        rows.append(row)
        lines.append(n)
    if not rows:
        raise Refused(f"{path}: a header and no entry rows; refusing to write an empty ledger")
    return {"path": Path(path), "sha256": hashlib.sha256(raw).hexdigest(),
            "rows": rows, "lines": lines, "extras": extras}


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
        for row, line in zip(export["rows"], export.get("lines") or [None] * len(export["rows"])):
            key = row["Entry_Key"]
            where = f"{export['path']}:{line}" if line else str(export["path"])
            prior = merged.get(key)
            if prior is None:
                merged[key] = row
                origin[key] = where
                continue
            # Cell text, not parsed values: a formatting change DK makes is a
            # disagreement a person reads, never one this tool decides.
            differs = [c for c in EXPORT_COLUMNS if prior[c] != row[c]]
            if differs:
                detail = "; ".join(f"{c} {prior[c]!r} vs {row[c]!r}" for c in differs)
                raise Refused(f"Entry_Key {key} disagrees between {origin[key]} and {where}: {detail}")
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
        # The same file named twice is one source.
        paths = list(dict.fromkeys(Path(p).resolve() for p in args.exports))
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
    print(f"        standings read for zero-point contests: {len(derived['standings_read'])}"
          f" ({len(derived['standings_unreadable'])} unreadable); "
          f"delivery records: {derived['delivery_records']} (earliest "
          f"{derived['earliest_delivery_record'] or 'none'})")
    return EXIT_OK


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------

# (cut name, results column). Overall comes first; the blank table per start
# block is printed after the cuts.
CUTS: Tuple[Tuple[str, str], ...] = (
    ("format", "Game_Type"), ("family", "family"), ("archetype", "archetype"),
    ("single_entry", "single_entry"), ("turbo", "turbo"), ("field_band", "field_band"),
    ("month", "month"), ("engine_record", "engine_record"),
)
# What the results review called "without blanks": the zero_complete entry is a
# lineup that scored 0 and stays.
BLANKS_EXCLUDED = ("blank_no_lineup", "zero_unknown")
BOOTSTRAP_DRAWS = 2000
BOOTSTRAP_SEED = 0
INTERVAL_PCT = (5.0, 95.0)
# Per-slate sums the bootstrap resamples, in this column order.
_SUMS = ("n", "n_fp", "fp", "pon", "pon_ref", "top", "top_ref", "bottom", "bottom_ref", "net")
CELL_KEYS = (
    "n", "slates", "fees", "cash", "ticket_face", "net", "net_interval",
    "place_over_n", "place_over_n_ref", "finish_pctl", "finish_pctl_interval",
    "top_share", "top_ref", "top_excess", "top_excess_interval",
    "bottom_share", "bottom_ref", "bottom_excess", "bottom_excess_interval", "blanks",
)


def read_results(path: Path) -> List[Dict[str, str]]:
    with open(path, "r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        missing = [c for c in RESULTS_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise Refused(f"{path}: not a {SCHEMA} file (missing {', '.join(missing)}); "
                          "re-run `python tools/results_ledger.py ingest`")
        return list(reader)


def report_population(rows: Iterable[Mapping[str, str]], sport: str, exclude_blanks: bool
                      ) -> List[Mapping[str, str]]:
    """Paid entries outside Best Ball for one sport, optionally without the blanks."""
    out = []
    for r in rows:
        if r["Sport"] != sport or r["Game_Type"] == "Best Ball" or Decimal(r["fee"]) <= 0:
            continue
        if exclude_blanks and r["blank_class"] in BLANKS_EXCLUDED:
            continue
        out.append(r)
    return out


def _interval(values: Any) -> List[float]:
    import numpy as np
    lo, hi = np.percentile(values, list(INTERVAL_PCT))
    return [round(100.0 * float(lo), 4), round(100.0 * float(hi), 4)]


def cell_stats(rows: Sequence[Mapping[str, str]], seed: int = BOOTSTRAP_SEED,
               draws: int = BOOTSTRAP_DRAWS) -> Dict[str, Any]:
    """One cell's money, finish and decile figures with slate-bootstrap intervals.

    A slate is sport, date and game type. Slates are sorted before sampling and
    each cell draws from a fresh generator under the seed, so a cell's interval
    depends on its rows only, never on file order or on the cells before it.
    One index draw serves every statistic in the cell. A cell with fewer than
    two slates gets no interval: every draw would be the same slate, and a
    zero-width interval would read as certainty.
    """
    import numpy as np

    sums: Dict[str, List[float]] = {}
    fees = cash = ticket = net = Decimal(0)
    blanks: Dict[str, int] = {c: 0 for c in BLANK_CLASSES}
    for r in rows:
        nums = entry_numbers(int(r["Place"]), int(r["Contest_Entries"]))
        fp = nums["finish_pctl"]
        entry_net = Decimal(r["net"])
        vec = sums.setdefault(r["slate"], [0.0] * len(_SUMS))
        for i, v in enumerate((1, fp is not None, fp or 0.0, nums["place_over_n"],
                               nums["place_over_n_ref"], nums["top_decile"], nums["top_ref"],
                               nums["bottom_decile"], nums["bottom_ref"], float(entry_net))):
            vec[i] += float(v)
        fees += Decimal(r["fee"])
        cash += Decimal(r["cash"])
        ticket += Decimal(r["ticket"])
        net += entry_net
        if r["blank_class"]:
            blanks[r["blank_class"]] += 1
    keys = sorted(sums)
    col = {name: i for i, name in enumerate(_SUMS)}
    A = np.array([sums[k] for k in keys], dtype=float).reshape(len(keys), len(_SUMS))
    t = A.sum(axis=0)

    def pct(num: str, den: str, total: Any = t) -> Optional[float]:
        return round(100.0 * float(total[col[num]] / total[col[den]]), 4) if total[col[den]] else None

    def excess(share: str, ref: str) -> Optional[float]:
        return round(100.0 * float((t[col[share]] - t[col[ref]]) / t[col["n"]]), 4) if t[col["n"]] else None

    cell: Dict[str, Any] = {
        "n": int(t[col["n"]]) if len(keys) else 0, "slates": len(keys),
        "fees": float(fees), "cash": float(cash), "ticket_face": float(ticket), "net": float(net),
        "net_interval": None,
        "place_over_n": pct("pon", "n"), "place_over_n_ref": pct("pon_ref", "n"),
        "finish_pctl": pct("fp", "n_fp"), "finish_pctl_interval": None,
        "top_share": pct("top", "n"), "top_ref": pct("top_ref", "n"),
        "top_excess": excess("top", "top_ref"), "top_excess_interval": None,
        "bottom_share": pct("bottom", "n"), "bottom_ref": pct("bottom_ref", "n"),
        "bottom_excess": excess("bottom", "bottom_ref"), "bottom_excess_interval": None,
        "blanks": blanks,
    }
    if len(keys) >= 2:
        rng = np.random.default_rng(seed)
        S = A[rng.integers(0, len(keys), size=(draws, len(keys)))].sum(axis=1)
        n = S[:, col["n"]]
        if (S[:, col["n_fp"]] > 0).all():
            cell["finish_pctl_interval"] = _interval(S[:, col["fp"]] / S[:, col["n_fp"]])
        cell["top_excess_interval"] = _interval((S[:, col["top"]] - S[:, col["top_ref"]]) / n)
        cell["bottom_excess_interval"] = _interval((S[:, col["bottom"]] - S[:, col["bottom_ref"]]) / n)
        lo, hi = _interval(S[:, col["net"]] / 100.0)
        cell["net_interval"] = [round(lo, 2), round(hi, 2)]
    return cell


def _cut_order(cut: str, value: str) -> Tuple[Any, ...]:
    if cut == "field_band":
        labels = [label for _, label in FIELD_BANDS] + [FIELD_BAND_OVER]
        return (labels.index(value) if value in labels else len(labels), value)
    return (value,)


def blank_blocks(rows: Sequence[Mapping[str, str]]) -> List[Dict[str, Any]]:
    """Zero-point entries per start block (the export's stand-in for a draftgroup)."""
    by_block: Dict[str, List[Mapping[str, str]]] = defaultdict(list)
    for r in rows:
        by_block[r["start_block"]].append(r)
    out = []
    for block in sorted(by_block):
        members = by_block[block]
        zeros = [r for r in members if r["zero_points"] == "1"]
        if not zeros:
            continue
        contests: Dict[str, List[Mapping[str, str]]] = defaultdict(list)
        for r in members:
            contests[r["Contest_Key"]].append(r)
        out.append({
            "start_block": block,
            "entries": len(members),
            "contests": len(contests),
            "all_zero_contests": sum(1 for c in contests.values()
                                     if all(r["zero_points"] == "1" for r in c)),
            "zero_points": len(zeros),
            "blanks": {c: sum(1 for r in zeros if r["blank_class"] == c) for c in BLANK_CLASSES},
        })
    return out


def build_report(rows: Sequence[Mapping[str, str]], sport: str, exclude_blanks: bool,
                 seed: int = BOOTSTRAP_SEED, draws: int = BOOTSTRAP_DRAWS) -> Dict[str, Any]:
    population = report_population(rows, sport, exclude_blanks)
    cuts: Dict[str, Dict[str, Any]] = {}
    for cut, column in CUTS:
        groups: Dict[str, List[Mapping[str, str]]] = defaultdict(list)
        for r in population:
            groups[r[column]].append(r)
        cuts[cut] = {value: cell_stats(groups[value], seed, draws)
                     for value in sorted(groups, key=lambda v: _cut_order(cut, v))}
    return {
        "sport": sport,
        "population": "paid entries (fee above 0) outside Best Ball"
                      + (", without blank_no_lineup and zero_unknown" if exclude_blanks else ""),
        "exclude_blanks": exclude_blanks,
        "bootstrap": {"unit": "slate (sport, date, game type)", "draws": draws, "seed": seed,
                      "interval_pct": list(INTERVAL_PCT), "order": "slates sorted before sampling"},
        "labels": list(LABELS) + [
            "Engine-record presence: a delivery record names the Entry ID; which record was "
            "entered is R497's to resolve."],
        "overall": cell_stats(population, seed, draws),
        "cuts": cuts,
        "blank_blocks": blank_blocks(population),
    }


def _money(value: float) -> str:
    return f"-${abs(value):,.2f}" if value < 0 else f"${value:,.2f}"


def _span(interval: Optional[Sequence[float]], signed: bool = False, money: bool = False) -> str:
    if not interval:
        return "[no interval: under 2 slates]"
    if money:
        return f"[{_money(interval[0])}, {_money(interval[1])}]"
    fmt = "{:+.1f}" if signed else "{:.1f}"
    return f"[{fmt.format(interval[0])}, {fmt.format(interval[1])}]"


def _num(value: Optional[float], fmt: str = "{:.2f}") -> str:
    return "n/a" if value is None else fmt.format(value)


def render_cell(label: str, cell: Mapping[str, Any]) -> List[str]:
    blanks = cell["blanks"]
    return [
        f"  {label:<24} n {cell['n']}  slates {cell['slates']}  fees {_money(cell['fees'])}  "
        f"cash {_money(cell['cash'])}  ticket face {_money(cell['ticket_face'])}  "
        f"net {_money(cell['net'])} {_span(cell['net_interval'], money=True)}",
        f"  {'':<24} place/N {_num(cell['place_over_n'])} (ref {_num(cell['place_over_n_ref'])})  "
        f"finish {_num(cell['finish_pctl'])} {_span(cell['finish_pctl_interval'])}  "
        f"top {_num(cell['top_share'])} vs {_num(cell['top_ref'])} "
        f"({_num(cell['top_excess'], '{:+.2f}')} {_span(cell['top_excess_interval'], signed=True)})  "
        f"bottom {_num(cell['bottom_share'])} vs {_num(cell['bottom_ref'])} "
        f"({_num(cell['bottom_excess'], '{:+.2f}')} {_span(cell['bottom_excess_interval'], signed=True)})  "
        f"blanks " + ", ".join(f"{c} {blanks.get(c, 0)}" for c in BLANK_CLASSES),
    ]


def render_report(report: Mapping[str, Any], results: Path, meta: Optional[Mapping[str, Any]]) -> str:
    boot = report["bootstrap"]
    lines = [f"results_ledger report  {report['sport']}  ({report['population']})",
             f"  results: {results}"]
    if meta:
        for src in meta.get("sources", []):
            lines.append(f"  source:  {src['path']}  sha256 {src['sha256'][:12]}  {src['rows']} rows")
    else:
        lines.append("  source:  sidecar missing; re-run ingest to record the exports read")
    lines.append(f"  intervals: 90%, {boot['unit']} bootstrap, {boot['draws']} draws, seed "
                 f"{boot['seed']}, {boot['order']}")
    lines.append("  finish = (Place - 1) / (N - 1), uniform reference 50; top and bottom are "
                 "decile shares against each entry's own uniform reference, in percent")
    for label in report["labels"]:
        lines.append(f"  label:   {label}")
    lines.append("")
    lines.extend(render_cell("overall", report["overall"]))
    for cut, cells in report["cuts"].items():
        lines.append("")
        lines.append(f"== {cut} ==")
        for value, cell in cells.items():
            shown = {"1": "yes", "0": "no"}.get(value, value) if cut in ("single_entry", "turbo") else value
            lines.extend(render_cell(shown or "(none)", cell))
    lines.append("")
    lines.append("== zero-point entries by start block (date, start, game type; the export carries no draftgroup) ==")
    if not report["blank_blocks"]:
        lines.append("  none")
    for block in report["blank_blocks"]:
        lines.append(
            f"  {block['start_block']:<40} {block['zero_points']} of {block['entries']} entries, "
            f"{block['all_zero_contests']} of {block['contests']} contests all zero: "
            + ", ".join(f"{c} {block['blanks'][c]}" for c in BLANK_CLASSES))
    return "\n".join(lines) + "\n"


def cmd_report(args: argparse.Namespace) -> int:
    root = Path(args.root)
    results = Path(args.results) if args.results else root / REFERENCE_DIR / RESULTS_NAME
    if not results.is_file():
        print(f"ERROR  no results file at {results}; run `python tools/results_ledger.py ingest` "
              "first (a DEV session adds --out <scratch path> and passes it here as --results)",
              file=sys.stderr)
        return EXIT_IO
    rows = read_results(results)
    meta = None
    side = sidecar_path(results)
    if side.is_file():
        try:
            meta = json.loads(side.read_text(encoding="utf-8"))
        except ValueError:
            print(f"note   {side} is not JSON; the sources it names are not shown", file=sys.stderr)
    report = build_report(rows, args.sport, args.exclude_blanks)
    if args.json:
        payload = {**report, "results": str(results),
                   "sources": (meta or {}).get("sources", [])}
        print(json.dumps(payload, indent=1, sort_keys=True))
    elif not report["overall"]["n"]:
        print(f"no paid {args.sport} entries outside Best Ball in {results}")
    else:
        sys.stdout.write(render_report(report, results, meta))
    return EXIT_OK


# ---------------------------------------------------------------------------
# resolve (R497): which delivery record each entry was entered from
# ---------------------------------------------------------------------------

RESOLUTION_NAME = "dk_entry_resolution.csv"
RESOLUTION_SCHEMA = "dk_entry_resolution/1"
RESOLUTION_COLUMNS: Tuple[str, ...] = (
    "Entry_Key", "Contest_Key", "date", "draftgroup", "status", "record", "by",
    "candidates", "rosters", "matched", "points", "standings", "detail",
)
RESOLVE_STATUSES = ("resolved", "tied", "unmatched", "unscored", "no_standings", "no_crosswalk")
DELIVERIES_DIR = Path("data") / "deliveries"
INBOX_DIR = Path("data") / "standings" / "inbox"
SHOWDOWN_GAME_TYPE = "Showdown Captain Mode"
# DK's two rosters: Classic 2P/C/1B/2B/3B/SS/3OF, Showdown 1 CPT + 5 UTIL.
ROSTER_SIZE = {"classic": 10, "showdown": 6}
RESOLVE_LABEL = (
    "Which delivery record an entry was entered from: the record whose roster, scored "
    "from DK's own player points, equals the entry's Points. A match is arithmetic on "
    "observed outcomes; it grades nothing.")


def record_key(path: Any) -> str:
    """`data/deliveries/<date>/<file>`: a record's name on every host.

    `read_records` hands back a repo-relative path where it can and an absolute
    one under any other root, so the last two parts are the identity.
    """
    p = Path(str(path).replace("\\", "/"))
    return f"{DELIVERIES_DIR.as_posix()}/{p.parent.name}/{p.name}"


def draftgroups(records: Sequence[Mapping[str, Any]]) -> Dict[str, str]:
    """{contest id: draftgroup key}. No file in the tree carries DK's draftgroup ID.

    A DKEntries file, and so a delivery record, holds one draftgroup, so
    contests that share a record share a draftgroup; the key is the group's
    lowest contest ID. On the records since 2026-09-19 this gives 30 groups for
    159 contests, the same 30 that (date, slate tag, contest type) gives.
    """
    parent: Dict[str, str] = {}

    def find(x: str) -> str:
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for record in records:
        cids = sorted({str(e.get("contest_id") or "").strip() for e in record.get("entries") or []
                       if e.get("filled") and str(e.get("contest_id") or "").strip()}, key=_cid_order)
        for cid in cids:
            find(cid)
        for a, b in zip(cids, cids[1:]):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[max(ra, rb, key=_cid_order)] = min(ra, rb, key=_cid_order)
    return {cid: find(cid) for cid in sorted(parent, key=_cid_order)}


def _cid_order(cid: str) -> Tuple[int, int, str]:
    return (0, int(cid), cid) if str(cid).isdigit() else (1, 0, str(cid))


def standings_files(root: Path, contest_ids: Iterable[str]) -> List[Path]:
    """Every standings export of these contests: the archive under any date (a
    contest after midnight ET is filed under the next one) and the inbox, the
    places `outcome_review.standings_candidates` searches. The inbox match is
    anchored, so a longer digit run never answers for a contest (R74(b))."""
    root = Path(root)
    out: List[Path] = []
    archive = root / ARCHIVE_DIR
    inbox = root / INBOX_DIR
    inbox_files = sorted(inbox.glob("*.csv")) if inbox.is_dir() else []
    for cid in sorted(set(contest_ids), key=_cid_order):
        if archive.is_dir():
            out.extend(sorted(archive.glob(f"*/contest-standings-{cid}.csv")))
        pattern = re.compile(rf"(?<!\d){re.escape(cid)}(?!\d)")
        out.extend(p for p in inbox_files if pattern.search(p.stem))
    return sorted(set(out))


def player_points(root: Path, paths: Sequence[Path]
                  ) -> Tuple[Dict[str, int], set, List[str], List[str]]:
    """Merged realized points in integer hundredths, one draftgroup's exports.

    Player FPTS do not differ across contests of one draftgroup, but each
    export lists only the players drafted in that contest, so the tables are
    merged. A name two exports score differently (a pull before a stat
    correction), or one table scores two ways (two people, one name), is
    ambiguous and scores nothing. `fpts_cents_by_norm` drops CPT rows: a
    Showdown captain is scored off its UTIL row, never the rounded CPT value.
    Returns (points, ambiguous names, files read, files unreadable).
    """
    from mlb_engine.field.field_miner import parse_standings_export
    from tools.replay_slate import ambiguous_norms, fpts_cents_by_norm

    cents: Dict[str, int] = {}
    ambiguous: set = set()
    read: List[str] = []
    unreadable: List[str] = []
    for path in sorted(paths):
        try:
            table = parse_standings_export(str(path))["player_table"]
        except (ValueError, OSError, csv.Error, UnicodeDecodeError):
            unreadable.append(_rel(path, root))
            continue
        read.append(_rel(path, root))
        ambiguous |= set(ambiguous_norms(table))
        for norm, value in fpts_cents_by_norm(table).items():
            if cents.setdefault(norm, value) != value:
                ambiguous.add(norm)
    return cents, ambiguous, read, unreadable


def _sha256_file(path: Path) -> Optional[str]:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def crosswalk(root: Path, records: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """One draftgroup's DK player ID -> normalized name, from every source left.

    A record carries IDs and a standings export carries names. The sources, in
    the order R497 names them: each record's `players` map (R494, R495); the
    slate's salary file, found by the sha256 the record names
    (`field_miner.record_salary_candidates`); the DKEntries file the record
    names, when it is still on disk with the bytes the record hashed (its
    embedded player pool). DK IDs are per draftgroup, so the union is safe; an
    ID two sources name differently names nobody. `slots` keeps each ID's
    roster position where a source says it (CPT or UTIL on Showdown).
    """
    from mlb_engine.entries.delivery_record import _players_from_salary
    from mlb_engine.entries.dk_entries_manager import parse_embedded_player_pool
    from mlb_engine.field.field_miner import normalize_name, record_salary_candidates

    names: Dict[str, set] = defaultdict(set)
    slots: Dict[str, str] = {}
    sources: List[str] = []
    errors: List[str] = []

    def add(pid: Any, name: Any, slot: Any = "") -> None:
        pid, norm = str(pid).strip(), normalize_name(str(name or ""))
        if pid and norm:
            names[pid].add(norm)
            if str(slot or "").strip():
                slots.setdefault(pid, str(slot).strip().upper())

    for record in records:
        players = record.get("players")
        if isinstance(players, Mapping) and players:
            sources.append(f"players map: {record_key(record.get('_path'))}")
            for pid, row in players.items():
                if isinstance(row, (list, tuple)) and row:
                    add(pid, row[0], row[2] if len(row) > 2 else "")
    salary_files: List[str] = []
    for record in records:
        cids = sorted({str(e.get("contest_id") or "") for e in record.get("entries") or []
                       if e.get("contest_id")}, key=_cid_order)
        try:
            found = record_salary_candidates(Path(root), str(record.get("date") or ""),
                                             cids[0] if cids else "")
        except Exception as exc:  # noqa: BLE001 - a source that fails is named, never fatal
            errors.append(f"salary lookup: {type(exc).__name__}: {exc}")
            found = []
        salary_files.extend(p for p in found if p not in salary_files)
    for path in sorted(salary_files):
        try:
            for pid, row in _players_from_salary(Path(path)).items():
                add(pid, row[0], row[2])
            sources.append(f"salary file: {_rel(Path(path), root)}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{_rel(Path(path), root)}: {type(exc).__name__}: {exc}")
    templates: List[Path] = []
    for record in records:
        binding = record.get("entries_binding") or {}
        row = record.get("manifest_row") or {}
        for rel, sha in ((binding.get("source"), binding.get("source_sha256")),
                         (row.get("delivered_file"), row.get("sha256"))):
            if not rel or not sha:
                continue
            path = Path(str(rel))
            path = path if path.is_absolute() else Path(root) / path
            if path.is_file() and path not in templates and _sha256_file(path) == str(sha).lower():
                templates.append(path)
    for path in templates:
        try:
            for pid, row in parse_embedded_player_pool(path).items():
                add(pid, row.get("name"))
            sources.append(f"DKEntries pool: {_rel(path, root)}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{_rel(path, root)}: {type(exc).__name__}: {exc}")
    named = {pid: next(iter(n)) for pid, n in names.items() if len(n) == 1}
    conflicts = sorted(pid for pid, n in names.items() if len(n) > 1)
    return {"names": named, "conflicts": conflicts, "slots": slots,
            "sources": sources, "errors": errors}


def points_match(milli: int, points: Any) -> bool:
    """A roster's score in thousandths against the export's Points.

    The export rounds a Showdown total half-up to hundredths (46.025 reads
    46.03): of our 742 scorable archived Showdown entries 552 match exactly and
    190 more only after that rounding, while half-even reaches 661 and
    truncation 552. A Classic total is whole hundredths, so the rounding is a
    no-op there (791 of 791).
    """
    try:
        target = Decimal(str(points).strip())
    except InvalidOperation:
        return False
    return (Decimal(int(milli)) / 1000).quantize(Decimal("0.01"), ROUND_HALF_UP) == target


def score_roster(roster: Sequence[str], fmt: str, xwalk: Mapping[str, Any],
                 cents: Mapping[str, int], ambiguous: set) -> Dict[str, Any]:
    """{milli} or {status, why}: one roster scored in integer thousandths.

    Showdown: the first cell is the captain (DK's CPT-first template order,
    confirmed on every R495 record) at 15x its UTIL row's hundredths, each UTIL
    at 10x; Classic: 10x each. Integers only, so two identical rosters always
    tie (`replay_slate`'s rule).
    """
    names = xwalk["names"]
    conflicted = [pid for pid in roster if pid in xwalk["conflicts"]]
    unnamed = [pid for pid in roster if pid not in names and pid not in conflicted]
    if unnamed:
        return {"status": "no_crosswalk", "ids": unnamed,
                "why": f"no source names {len(unnamed)} id(s): {', '.join(unnamed[:4])}"}
    if conflicted:
        return {"status": "unscored",
                "why": f"id(s) its sources name two ways: {', '.join(conflicted[:4])}"}
    if len(roster) != ROSTER_SIZE[fmt]:
        return {"status": "unscored", "why": f"a {fmt} roster of {len(roster)} cells"}
    if fmt == "showdown" and xwalk["slots"].get(roster[0], "CPT") != "CPT":
        return {"status": "unscored",
                "why": f"captain cell {roster[0]} is a {xwalk['slots'][roster[0]]} id, not CPT"}
    norms = [names[pid] for pid in roster]
    absent = [n for n in norms if n not in cents]
    clash = [n for n in norms if n in ambiguous]
    if absent or clash:
        return {"status": "unscored", "absent": absent, "ambiguous": clash,
                "why": "; ".join(part for part in (
                    f"in no export's player table: {', '.join(absent)}" if absent else "",
                    f"scored two ways: {', '.join(clash)}" if clash else "") if part)}
    weights = [15] + [10] * (len(norms) - 1) if fmt == "showdown" else [10] * len(norms)
    return {"milli": sum(w * cents[n] for w, n in zip(weights, norms))}


def preflight_cleared(root: Path, record: Mapping[str, Any]) -> bool:
    """R494(c)'s sidecar says preflight exited 0 on this record's own bytes."""
    key = Path(record_key(record.get("_path")))
    path = Path(root) / key.parent / f"{key.stem}.preflight.json"
    try:
        side = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    sha = str((record.get("manifest_row") or {}).get("sha256") or "").strip().lower()
    return (isinstance(side, Mapping) and side.get("kind") == "preflight"
            and side.get("exit_code") == 0 and bool(sha)
            and str(side.get("entries_sha256") or "").strip().lower() == sha)


def _bytes_key(record: Mapping[str, Any]) -> str:
    sha = str((record.get("manifest_row") or {}).get("sha256") or "").strip().lower()
    return sha or record_key(record.get("_path"))


def _same_bytes_pick(records: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    """One file recorded twice: the record with no `lineage`, then the lowest path."""
    return sorted(records, key=lambda r: (bool((r.get("manifest_row") or {}).get("lineage")),
                                          record_key(r.get("_path"))))[0]


def decide(entry_id: str, row: Mapping[str, str], cands: Sequence[Tuple[Mapping[str, Any], Mapping[str, Any]]],
           xwalk: Mapping[str, Any], points: Mapping[str, Any], root: Path) -> Dict[str, str]:
    """One entry's resolution. `cands` are (record, entry) pairs, sorted by record."""
    keys = [record_key(rec.get("_path")) for rec, _ in cands]
    fmt = "showdown" if row["Game_Type"] == SHOWDOWN_GAME_TYPE else "classic"
    rosters: Dict[Tuple[str, ...], List[Mapping[str, Any]]] = {}
    for rec, entry in cands:
        rosters.setdefault(tuple(str(p).strip() for p in entry.get("roster_ids") or []), []).append(rec)
    out = {"status": "", "record": "", "by": "", "candidates": str(len(cands)),
           "rosters": str(len(rosters)), "matched": "", "points": row["Points"],
           "standings": str(len(points["read"])), "detail": ""}

    said = sorted({str((rec.get("manifest_row") or {}).get("contest_type") or "").lower()
                   for rec, _ in cands} & set(ROSTER_SIZE))
    if said and said != [fmt]:
        return {**out, "status": "unscored",
                "detail": f"contest type: the record says {'/'.join(said)}, the export's "
                          f"Game_Type says {row['Game_Type']!r}; not scored"}
    scored = {roster: score_roster(roster, fmt, xwalk, points["cents"], points["ambiguous"])
              for roster in rosters}
    unnamed = sorted({pid for s in scored.values() for pid in s.get("ids", [])})
    if unnamed:
        return {**out, "status": "no_crosswalk",
                "detail": f"no players map, salary file or DKEntries file names {len(unnamed)} "
                          f"id(s): {', '.join(unnamed[:6])}"}
    if not points["read"]:
        return {**out, "status": "no_standings",
                "detail": "no readable standings export for any contest of draftgroup "
                          f"{points['draftgroup']}"}
    bad = [s for s in scored.values() if "milli" not in s]
    if bad:
        return {**out, "status": "unscored", "detail": "; ".join(sorted({s["why"] for s in bad}))}
    hits = [roster for roster, s in scored.items() if points_match(s["milli"], row["Points"])]
    if not hits:
        shown = ", ".join(f"{Decimal(s['milli']) / 1000:.3f}" for s in scored.values())
        return {**out, "status": "unmatched",
                "detail": f"no candidate scores {row['Points']} (scores {shown}): a hand edit "
                          "or a swap outside the records"}
    tie = sorted((rec for roster in hits for rec in rosters[roster]),
                 key=lambda r: record_key(r.get("_path")))
    out["matched"] = "|".join(record_key(r.get("_path")) for r in tie)
    by_bytes: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for rec in tie:
        by_bytes[_bytes_key(rec)].append(rec)
    if len(by_bytes) == 1:
        group = next(iter(by_bytes.values()))
        if len(group) == 1:
            return {**out, "status": "resolved", "record": out["matched"], "by": "points"}
        return {**out, "status": "resolved", "by": "same_bytes",
                "record": record_key(_same_bytes_pick(group).get("_path")),
                "detail": f"{len(group)} records of one file score {row['Points']}"}
    cleared = [g for g in by_bytes.values() if any(preflight_cleared(root, r) for r in g)]
    if len(cleared) == 1:
        return {**out, "status": "resolved", "by": "preflight_sidecar",
                "record": record_key(_same_bytes_pick(cleared[0]).get("_path")),
                "detail": f"{len(tie)} records score {row['Points']}; one file cleared preflight"}
    return {**out, "status": "tied",
            "detail": f"{len(tie)} records score {row['Points']} ("
                      + ", ".join(f"{record_key(r.get('_path'))}"
                                  f"{' preflight-cleared' if preflight_cleared(root, r) else ''}"
                                  for r in tie) + ")"}


def resolve_entries(root: Path, results_rows: Sequence[Mapping[str, str]]) -> Dict[str, Any]:
    """Every filled entry of every delivery record, resolved to the record entered.

    Driven from the records (record -> entry -> its results row), so a record
    written after the last ingest is still read and a results row nobody
    recorded is never asked about.
    """
    from mlb_engine.entries.delivery_record import read_records

    root = Path(root)
    records = sorted((r for r in read_records(root=root) if r.get("kind") == "delivery"),
                     key=lambda r: record_key(r.get("_path")))
    group_of = draftgroups(records)
    results = {str(r["Entry_Key"]).strip(): r for r in results_rows}
    cands: Dict[str, List[Tuple[Mapping[str, Any], Mapping[str, Any]]]] = defaultdict(list)
    for record in records:
        for entry in record.get("entries") or []:
            eid = str(entry.get("entry_id") or "").strip()
            if entry.get("filled") and eid and str(entry.get("contest_id") or "").strip():
                cands[eid].append((record, entry))
    no_result = sorted((e for e in cands if e not in results), key=_cid_order)
    members: Dict[str, List[str]] = defaultdict(list)
    for eid in sorted(cands, key=_cid_order):
        if eid in results:
            members[group_of[str(cands[eid][0][1]["contest_id"]).strip()]].append(eid)

    rows: List[Dict[str, str]] = []
    groups: List[Dict[str, Any]] = []
    read_all: List[str] = []
    unreadable_all: List[str] = []
    for group in sorted(members, key=_cid_order):
        contests = sorted((c for c, g in group_of.items() if g == group), key=_cid_order)
        in_group = [r for r in records if any(str(e.get("contest_id") or "").strip() in contests
                                              for e in r.get("entries") or [] if e.get("filled"))]
        xwalk = crosswalk(root, in_group)
        cents, ambiguous, read, unreadable = player_points(root, standings_files(root, contests))
        points = {"cents": cents, "ambiguous": ambiguous, "read": read, "draftgroup": group}
        read_all += read
        unreadable_all += unreadable
        counts: Dict[str, int] = defaultdict(int)
        unnamed: set = set()
        absent: set = set()
        for eid in members[group]:
            row = results[eid]
            decided = decide(eid, row, cands[eid], xwalk, points, root)
            counts[decided["status"]] += 1
            for rec, entry in cands[eid]:
                roster = [str(p).strip() for p in entry.get("roster_ids") or []]
                unnamed |= {p for p in roster if p not in xwalk["names"]}
                absent |= {xwalk["names"][p] for p in roster
                           if p in xwalk["names"] and xwalk["names"][p] not in cents}
            rows.append({"Entry_Key": eid, "Contest_Key": str(row["Contest_Key"]),
                         "date": str(cands[eid][0][0].get("date") or ""),
                         "draftgroup": group, **decided})
        dates = sorted({str(r.get("date") or "") for r in in_group})
        groups.append({"draftgroup": group, "date": dates[-1] if dates else "",
                       "contests": len(contests), "entries": len(members[group]),
                       "statuses": dict(sorted(counts.items())), "standings_read": len(read),
                       "standings_unreadable": len(unreadable), "ids_unnamed": len(unnamed),
                       "players_absent": len(absent), "crosswalk_sources": len(xwalk["sources"]),
                       "crosswalk_errors": xwalk["errors"]})
    rows.sort(key=lambda r: (r["date"], _cid_order(r["Contest_Key"]), _cid_order(r["Entry_Key"])))
    statuses = {s: sum(1 for r in rows if r["status"] == s) for s in RESOLVE_STATUSES}
    by = {b: sum(1 for r in rows if r["by"] == b) for b in ("points", "same_bytes", "preflight_sidecar")}
    groups.sort(key=lambda g: (g["date"], _cid_order(g["draftgroup"])), reverse=True)
    return {"rows": rows, "draftgroups": groups, "statuses": statuses, "resolved_by": by,
            "records": len(records), "entries_without_result": len(no_result),
            "standings_read": sorted(set(read_all)), "standings_unreadable": sorted(set(unreadable_all))}


def write_resolution(path: Path, rows: Sequence[Mapping[str, str]]) -> None:
    lines: List[str] = []

    class _Sink:
        def write(self, s: str) -> None:
            lines.append(s)

    writer = csv.DictWriter(_Sink(), fieldnames=list(RESOLUTION_COLUMNS), lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({c: row.get(c, "") for c in RESOLUTION_COLUMNS})
    _atomic_write(Path(path), "".join(lines))


def read_resolution(path: Path) -> Dict[str, Dict[str, str]]:
    """{Entry_Key: row} from a resolution file; refuses a file of another shape."""
    with open(path, "r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        missing = [c for c in RESOLUTION_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise Refused(f"{path}: not a {RESOLUTION_SCHEMA} file (missing {', '.join(missing)}); "
                          "re-run `python tools/results_ledger.py resolve`")
        return {row["Entry_Key"]: row for row in reader}


def cmd_resolve(args: argparse.Namespace) -> int:
    root = Path(args.root)
    results = Path(args.results) if args.results else root / REFERENCE_DIR / RESULTS_NAME
    if not results.is_file():
        print(f"ERROR  no results file at {results}; run `python tools/results_ledger.py ingest` "
              "first (a DEV session adds --out <scratch path> and passes it here as --results)",
              file=sys.stderr)
        return EXIT_IO
    resolved = resolve_entries(root, read_results(results))
    out = Path(args.out) if args.out else root / REFERENCE_DIR / RESOLUTION_NAME
    write_resolution(out, resolved["rows"])
    meta = {
        "schema": RESOLUTION_SCHEMA,
        "tool": "tools/results_ledger.py resolve (R497)",
        "results": {"path": _rel(results, root), "sha256": _sha256_file(results)},
        "delivery_records": resolved["records"],
        "entries": len(resolved["rows"]),
        "entries_without_result": resolved["entries_without_result"],
        "statuses": resolved["statuses"],
        "resolved_by": resolved["resolved_by"],
        "draftgroups": resolved["draftgroups"],
        "standings_read": resolved["standings_read"],
        "standings_unreadable": resolved["standings_unreadable"],
        "labels": [RESOLVE_LABEL] + list(LABELS[:1]),
    }
    _atomic_write(sidecar_path(out), json.dumps(meta, indent=1, sort_keys=True) + "\n")
    if args.json:
        print(json.dumps({**meta, "rows": resolved["rows"], "out": str(out)}, indent=1, sort_keys=True))
        return EXIT_OK
    print(f"resolve  {len(resolved['rows'])} recorded entries with a result, "
          f"{resolved['entries_without_result']} without one, from {resolved['records']} "
          f"delivery records  -> {out}")
    print("         " + ", ".join(f"{s} {n}" for s, n in resolved["statuses"].items())
          + "  (resolved by " + ", ".join(f"{b} {n}" for b, n in resolved["resolved_by"].items()) + ")")
    print("  per draftgroup, newest first (key = lowest contest ID):")
    for g in resolved["draftgroups"]:
        print(f"  {g['date']}  dg {g['draftgroup']:<10} {g['contests']} contest(s), "
              f"{g['entries']} entr{'y' if g['entries'] == 1 else 'ies'}: "
              + ", ".join(f"{s} {n}" for s, n in g["statuses"].items())
              + f"  | exports read {g['standings_read']}, ids no source names "
              f"{g['ids_unnamed']}, players in no export {g['players_absent']}")
    print(f"  label:   {RESOLVE_LABEL}")
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

    p = sub.add_parser("report", help="money, finish, deciles and blanks by cut, with intervals")
    p.add_argument("--sport", default="MLB", help="Sport column value (default MLB)")
    p.add_argument("--results", default=None, help=f"default data/reference/{RESULTS_NAME}")
    p.add_argument("--exclude-blanks", action="store_true",
                   help="drop blank_no_lineup and zero_unknown entries from every cell")
    p.add_argument("--json", action="store_true", help="print the report as JSON")

    p = sub.add_parser("resolve", help="tie each recorded entry to the delivery record entered (R497)")
    p.add_argument("--results", default=None, help=f"default data/reference/{RESULTS_NAME}")
    p.add_argument("--out", default=None,
                   help=f"default data/reference/{RESOLUTION_NAME} (ARCHIVE's write set)")
    p.add_argument("--json", action="store_true", help="print every row and the summary as JSON")

    args = ap.parse_args(argv)
    handler = {"ingest": cmd_ingest, "report": cmd_report, "resolve": cmd_resolve}[args.cmd]
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
