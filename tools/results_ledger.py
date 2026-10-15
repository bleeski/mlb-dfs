#!/usr/bin/env python3
"""results_ledger.py -- the DraftKings contest entry-history export, read per entry (R496).

Ben downloads the entry-history export by hand (one row per entry he ever
entered, every sport and contest type) and commits it as
`data/reference/draftkings-contest-entry-history_<last contest date>.csv`. This
tool reads those files and nothing on DraftKings.

    python tools/results_ledger.py ingest [EXPORT ...] [--out PATH]
    python tools/results_ledger.py report [--sport MLB] [--results PATH] [--exclude-blanks] [--json]
    python tools/results_ledger.py resolve [--results PATH] [--out PATH] [--json]
    python tools/results_ledger.py attribute [--results PATH] [--resolution PATH] [--json]
                                             [--rank | --showdown]

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

`report` also cuts FIRST PLACE per contest (R504(c)): in how many contests did any
entry of ours take Place 1, against the uniform reference, the sum over contests of
our entries in the contest over N (a uniform draw from the field lands on one of
our m entries m times in N, so the reference is arithmetic). Cells are archetype x
field band and never pooled, each with its contests, entries and slates. First is
RANK 1 in every contest. A one-seat satellite's seat is rank 1, so the two coincide;
a seat in a multi-seat satellite (Places_Paid of 2 or more) is NOT counted as first,
so its cell also carries `multi_seat_contests` and, separately, how many of them
awarded a seat to one of ours (Place within Places_Paid). The seat read is its own
field and is never folded into first.

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

`attribute` (R498) asks which of our Classic constructions sit under our bottom-
and top-decile finishes. It reads our paid Classic entries whose standings
export (archive under any date, then the inbox) holds a complete lineup, and
every other complete lineup of the same contest as the field. Per lineup: the
field-relative ownership percentile (summed %Drafted, midrank / N) and its
third; the hitter stack (mined, else a team map) and its group; the primary
team and the share of the field's team-mapped lineups stacking it; dead slots (hitters at
exactly 0 FPTS). Per contest: posture (the build's default inference from the
title and fee), field-size band, month. Per resolved entry only (R497): hitter
roles, market, the primary team's implied total, contest shape. Every cell
holds our finish and decile excess against the uniform reference, the field's
in the same cell of the same contests on one paired slate draw, and our share
of entries against the field's share of lineups; a finding line prints only
when an interval excludes 0. It writes nothing.

`attribute --rank` (R500(a)) asks whether the lineup the engine put higher
finished higher: per contest's resolved entries from one build, the Spearman
correlation (midranks) between the engine's own order (Classic
`contest_fit_score`, Showdown `rank_in_build`) and DK's Place, signed so
agreement reads +1, with its median and spread across units; a unit of one
entry or no spread is skipped and counted. `attribute --showdown` (R500(b)) is
the same cells over our paid Showdown entries: the captain's role (the
resolved record's, else the vendored season tables, a labelled prior), the
captain's CPT% and flex% in the field (the entry block, not DK's table), the
team split, duplication (captain-aware), posture, field band, month and, per
resolved entry, the thesis.

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


def contest_first_place(population: Sequence[Mapping[str, str]]) -> List[Dict[str, Any]]:
    """R504(c). One record per contest of the population: did any entry of ours take Place 1?

    ``ref`` is the uniform reference, our entries in the contest over its field
    size N (capped at 1): the share of uniform draws from the field that land on
    one of our entries, which is all the reference claims. A multi-seat
    satellite (title-inferred satellite, `Places_Paid` of 2 or more) keeps its
    rank-1 read and gains a separate seat read, never folded into first.
    """
    by_contest: Dict[str, List[Mapping[str, str]]] = defaultdict(list)
    for r in population:
        by_contest[r["Contest_Key"]].append(r)
    out: List[Dict[str, Any]] = []
    for key in sorted(by_contest):
        members = by_contest[key]
        head = members[0]
        n = int(head["Contest_Entries"])
        places = [int(r["Place"]) for r in members]
        try:
            paid = int(head["Places_Paid"])
        except (TypeError, ValueError):
            paid = None
        multi = head["archetype"] == "satellite" and paid is not None and paid >= 2
        out.append({
            "contest": key, "slate": head["slate"], "archetype": head["archetype"],
            "field_band": head["field_band"], "entries": len(members), "field": n,
            "first": min(places) == 1, "ref": min(1.0, len(members) / n),
            "multi_seat": multi,
            "seat_won": bool(multi and min(places) <= paid),
        })
    return out


def first_place_cell(contests: Sequence[Mapping[str, Any]], seed: int = BOOTSTRAP_SEED,
                     draws: int = BOOTSTRAP_DRAWS) -> Dict[str, Any]:
    """One cell of the first-place cut, with a slate bootstrap on the excess.

    Same rule as `cell_stats`: slates sorted before sampling, a fresh generator
    per cell, and no interval under two slates (every draw would be the same
    slate, and a zero-width interval would read as certainty). One more here:
    none when no contest of the cell saw a first-place finish. A resample of zero
    finishes varies only through the reference, so the interval collapses on the
    estimate (-4.35 [-4.3, -4.3] on the 2026-10-09 exports) and says the cell is
    certain when it has no events to be uncertain about.
    """
    import numpy as np

    sums: Dict[str, List[float]] = {}
    for c in contests:
        vec = sums.setdefault(c["slate"], [0.0, 0.0, 0.0])
        vec[0] += 1
        vec[1] += 1.0 if c["first"] else 0.0
        vec[2] += float(c["ref"])
    keys = sorted(sums)
    A = np.array([sums[k] for k in keys], dtype=float).reshape(len(keys), 3)
    total = A.sum(axis=0)
    n = int(total[0])
    cell: Dict[str, Any] = {
        "contests": n, "entries": sum(int(c["entries"]) for c in contests),
        "slates": len(keys), "first_contests": int(total[1]),
        "first_ref": round(float(total[2]), 4),
        "first_share": round(100.0 * float(total[1]) / n, 4) if n else None,
        "first_ref_share": round(100.0 * float(total[2]) / n, 4) if n else None,
        "first_excess": round(100.0 * float(total[1] - total[2]) / n, 4) if n else None,
        "first_excess_interval": None,
        "multi_seat_contests": sum(1 for c in contests if c["multi_seat"]),
        "multi_seat_seat_won": sum(1 for c in contests if c["seat_won"]),
    }
    if len(keys) >= 2 and total[1] > 0:
        rng = np.random.default_rng(seed)
        S = A[rng.integers(0, len(keys), size=(draws, len(keys)))].sum(axis=1)
        cell["first_excess_interval"] = _interval((S[:, 1] - S[:, 2]) / S[:, 0])
    return cell


def build_first_place(population: Sequence[Mapping[str, str]], seed: int = BOOTSTRAP_SEED,
                      draws: int = BOOTSTRAP_DRAWS) -> Dict[str, Any]:
    """R504(c). Cells of archetype x field band over the population's contests."""
    cells: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for c in contest_first_place(population):
        cells[(c["archetype"], c["field_band"])].append(c)
    bands = [label for _, label in FIELD_BANDS] + [FIELD_BAND_OVER]

    def order(item: Tuple[Tuple[str, str], Any]) -> Tuple[Any, ...]:
        (archetype, band), _ = item
        return (archetype, bands.index(band) if band in bands else len(bands), band)

    return {
        "unit": "contest: did any entry of ours take Place 1",
        "conditioning": "archetype x field band, never pooled",
        "cells": {f"{a} | {b}": first_place_cell(members, seed, draws)
                  for (a, b), members in sorted(cells.items(), key=order)},
        "labels": [
            "Observed outcomes. First is Place 1 in every contest; a seat in a "
            "multi-seat satellite (Places_Paid of 2 or more) is not counted as first "
            "and is its own field.",
            "Uniform reference: our entries in the contest over its field size, summed; "
            "arithmetic, not a forecast.",
        ],
    }


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
        "first_place": build_first_place(population, seed, draws),
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


def _first_span(cell: Mapping[str, Any]) -> str:
    """The first-place cell's interval, or the reason there is none."""
    if cell["first_excess_interval"]:
        return _span(cell["first_excess_interval"], signed=True)
    if cell["slates"] < 2:
        return "[no interval: under 2 slates]"
    return "[no interval: no first-place finish to resample]"


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
    first = report.get("first_place") or {}
    lines.append("")
    lines.append("-- first place by contest: did any entry of ours take Place 1? "
                 "(cells are archetype x field band, never pooled) --")
    for label in first.get("labels") or []:
        lines.append(f"  label:   {label}")
    if not first.get("cells"):
        lines.append("  none")
    for name, cell in (first.get("cells") or {}).items():
        lines.append(
            f"  {name:<28} contests {cell['contests']}  entries {cell['entries']}  "
            f"slates {cell['slates']}  first {cell['first_contests']} vs uniform "
            f"{_num(cell['first_ref'])}  ({_num(cell['first_excess'], '{:+.2f}')} points "
            f"per contest {_first_span(cell)})"
            + (f"  multi-seat {cell['multi_seat_contests']}, seat awarded "
               f"{cell['multi_seat_seat_won']}" if cell["multi_seat_contests"] else ""))
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
    code = side.get("exit_code") if isinstance(side, Mapping) else None
    return (isinstance(side, Mapping) and side.get("kind") == "preflight"
            and type(code) is int and code == 0 and bool(sha)
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

    named = sorted({str(entry.get("contest_id") or "").strip() for _, entry in cands}, key=_cid_order)
    if named != [str(row["Contest_Key"]).strip()]:
        # One Entry ID is one contest: a results row or a record naming another
        # would score a roster against the wrong draftgroup's points.
        return {**out, "status": "unscored",
                "detail": f"contest: the results row says {row['Contest_Key']}, the records say "
                          f"{', '.join(named)}; not scored"}
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
# attribute (R498): which of our choices sit under our finishes (Classic)
# ---------------------------------------------------------------------------

CLASSIC_GAME_TYPE = "Classic"
CLASSIC_HITTERS = 8
UNKNOWN, UNRECORDED, NONE_LABEL = "unknown", "unrecorded", "none"
LARGE_SECONDARY = ("4-4", "4-3-1", "4-2-2")
STACK_GROUPS = ("5", "4-4|4-3-1|4-2-2", "4-other", "3-or-less")
# The share of the field's team-mapped lineups whose primary stack is the
# team (a lineup with no primary in the denominator), upper bounds exclusive.
TEAM_SHARE_BANDS: Tuple[Tuple[float, str], ...] = ((0.05, "<5%"), (0.10, "5-10%"), (0.20, "10-20%"))
TEAM_SHARE_OVER = "20%+"
IMPLIED_BANDS: Tuple[Tuple[float, str], ...] = ((4.0, "<4.0"), (5.0, "4.0-4.99"))
IMPLIED_OVER = "5.0+"
ROLE_CONFIRMED, ROLE_PROJECTED = "confirmed_lineup", "platoon_projected"
# (axis, level). `lineup`: every lineup, ours and the field's, has a value;
# `contest`: the field shares the contest's value; `build`: ours only, read
# from the delivery record R497 resolved the entry to.
ATTRIBUTE_AXES: Tuple[Tuple[str, str], ...] = (
    ("chalk_third", "lineup"), ("max_stack", "lineup"), ("stack_group", "lineup"),
    ("stack_pattern", "lineup"), ("primary_team", "lineup"), ("team_field_share", "lineup"),
    ("dead_slots", "lineup"), ("posture", "contest"), ("field_band", "contest"),
    ("month", "contest"), ("hitter_roles", "build"), ("market", "build"),
    ("implied_total", "build"), ("contest_shape", "build"),
)
# Per-lineup columns the paired bootstrap sums, in this order.
_PAIR = ("n", "n_fp", "fp", "top", "top_ref", "bottom", "bottom_ref")
# A cell prints a finding about its own finishes only from this size up: a
# slate bootstrap over a handful of slates, or a cell of a few entries, gives an
# interval far narrower than what it measures. The share comparison is over the
# whole population and has no floor.
FINDING_MIN_N, FINDING_MIN_SLATES = 20, 5
ATTRIBUTE_LABELS: Tuple[str, ...] = (
    "Observed outcomes and review proxies: which constructions sat under our finishes, "
    "never why, never ROI, a win rate or a probability; nothing reads this back into a control.",
    "Ours: Place and N from the entry-history export. The field: every other complete lineup "
    "in the same contest, ranked by its standings export.",
    "Chalk: the lineup's summed %Drafted (DK's table, summed per player) as midrank / N among "
    "the contest's complete lineups; low under 1/3, high from 2/3.",
    "Stack: hitters per team, from the mined standings, else a team map (the record's players "
    "map, else a salary file).",
    "Dead slot: a hitter whose FPTS is exactly 0, which counts a hitter who did not play and "
    "one who went 0-for-4 alike.",
    "Posture: inferred today from the title and fee by the build's default rule "
    "(infer_contest_archetype, then normalize_posture); an operator --postures override is not visible.",
    "Build-time axes (hitter roles, market, implied total, contest shape) come only from the "
    "delivery record R497 resolved the entry to.",
    "A finding line prints only when its interval excludes 0; otherwise the cell reads "
    f"inside the reference. A cell under {FINDING_MIN_N} entries or {FINDING_MIN_SLATES} slates "
    "prints no finding about its finishes, and a decile band holding none or all of the cell's "
    "entries prints none about that band (its bootstrap has no spread).",
    "Dead slots are an outcome, not a choice: the axis is here for the R6 question, and its "
    "cells sort finishes by construction.",
    "The field is weighted by its lineups: a contest of 10,000 weighs 400 times one of 25 on the "
    "field side, whatever number of ours it holds; the pairing is by slate, not by weight.",
)


def chalk_percentiles(sums: Mapping[str, float]) -> Dict[str, Tuple[float, str]]:
    """{entry: (percentile, third)} of each lineup's summed %Drafted in its contest.

    The percentile is midrank / N: the average 1-based rank of the lineup's sum
    among the contest's complete lineups (ties share it), over N. The thirds
    are decided in integers (twice the midrank against N), so a lineup sitting
    exactly on 1/3 or 2/3 reads mid or high on every host.
    """
    from bisect import bisect_left, bisect_right

    values = sorted(sums.values())
    n = len(values)
    out: Dict[str, Tuple[float, str]] = {}
    for key, value in sums.items():
        lo, hi = bisect_left(values, value), bisect_right(values, value)
        twice = lo + hi + 1
        third = "low" if 3 * twice < 2 * n else "high" if 3 * twice >= 4 * n else "mid"
        out[key] = (twice / (2 * n), third)
    return out


def fpts_by_norm(player_table: Sequence[Mapping[str, Any]]) -> Dict[str, float]:
    """{name: FPTS} from one standings table; a name scored two ways is left out."""
    seen: Dict[str, set] = defaultdict(set)
    for row in player_table or []:
        if row.get("fpts") is not None:
            seen[str(row.get("player_norm") or "")].add(float(row["fpts"]))
    return {name: next(iter(v)) for name, v in sorted(seen.items()) if len(v) == 1}


def dead_slots(lineup: Sequence[Tuple[str, str]], fpts: Mapping[str, float]) -> int:
    """Hitter slots whose FPTS is exactly 0, from (slot, normalized name) pairs.
    A pitcher at 0 is not a dead slot, and a player the table does not score is
    not counted either way."""
    return sum(1 for slot, name in lineup if slot != "P" and fpts.get(name) == 0)


def stack_from_teams(lineup: Sequence[Tuple[str, str]], teams: Mapping[str, str]
                     ) -> Optional[Dict[str, Any]]:
    """Hitters per team, the pattern and the primary team, from (slot, normalized
    name) pairs and a {normalized name: team} map.

    None unless every hitter is mapped (a missing hitter could be on the stack
    team). The primary team is field_miner's rule (R422(a)): the largest hitter
    stack, at least PRIMARY_STACK_MIN_HITTERS and strictly larger than the
    next, else none.
    """
    from mlb_engine.field.field_miner import PRIMARY_STACK_MIN_HITTERS

    counts: Dict[str, int] = defaultdict(int)
    for slot, name in lineup:
        if slot == "P":
            continue
        team = teams.get(name)
        if not team:
            return None
        counts[team] += 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    if not ranked:
        return None
    top = ranked[0][1]
    unique = len(ranked) == 1 or ranked[1][1] < top
    return {"pattern": "-".join(str(c) for _, c in ranked), "max_stack": top,
            "primary_team": ranked[0][0] if top >= PRIMARY_STACK_MIN_HITTERS and unique else NONE_LABEL}


def stack_group(pattern: Optional[str], max_stack: Optional[int]) -> str:
    if pattern is None or max_stack is None:
        return UNKNOWN
    if max_stack >= 5:
        return "5"
    if pattern in LARGE_SECONDARY:
        return "4-4|4-3-1|4-2-2"
    return "4-other" if max_stack == 4 else "3-or-less"


def _band(value: float, bands: Sequence[Tuple[float, str]], over: str) -> str:
    for upper, label in bands:
        if value < upper:
            return label
    return over


def mined_stacks(root: Path, contest_id: str, contest_type: str = "classic",
                 size: int = CLASSIC_HITTERS) -> Dict[str, Tuple[str, int]]:
    """{entry: (stack_pattern, max_stack)} from the contest's mined standings.

    A contest mined twice (2026-07-18 and 07-19 hold 192464820) reads its typed
    `classic` file first, then the first by path: the 07-19 copy is one of four
    untyped files an older miner wrote. Entries mined without a salary file
    carry no pattern and are left out, and so is a pattern whose counts do not
    sum to the eight hitters: the miner writes one even when a hitter failed to
    join (none on disk on 2026-10-12; this is the only check the file allows).
    A Showdown contest (R500) reads its typed `showdown` file and the pattern
    over all six players, which is the team split.
    """
    files = sorted((Path(root) / ARCHIVE_DIR).glob(f"*/mined_{contest_id}.json"))
    loaded = []
    for path in files:
        try:
            loaded.append((path, json.loads(path.read_text(encoding="utf-8"))))
        except (OSError, ValueError):
            continue
    loaded.sort(key=lambda pd: (str(pd[1].get("contest_type") or "").lower() != contest_type, str(pd[0])))
    if not loaded:
        return {}
    out: Dict[str, Tuple[str, int]] = {}
    for entry in loaded[0][1].get("entries") or []:
        pattern = str(entry.get("stack_pattern") or "")
        counts = pattern.split("-")
        if (entry.get("max_stack") is not None and all(c.isdigit() for c in counts)
                and sum(int(c) for c in counts) == size):
            out[str(entry.get("entry_id"))] = (pattern, int(entry["max_stack"]))
    return out


def salary_teams(path: Path) -> Dict[str, str]:
    """{name: team} from a DK salary file; a name two players share maps nobody."""
    from mlb_engine.field.field_miner import load_salary_map

    smap = load_salary_map(str(path))
    clash = set((smap.get("__collisions__") or {}).get("names") or [])
    return {name: str(rec.get("team") or "") for name, rec in sorted(smap.items())
            if not name.startswith("__") and name not in clash and rec.get("team")}


class _TeamMaps:
    """One salary file per contest, found the way the archive and the records allow:
    the R497-resolved record's salary sha (`record_salary_candidates`), else the
    file `replay_slate.slate_groups` resolves for a folder holding the contest's
    typed classic mined file. `slate_groups` walks those files only, so a
    contest with no mined file gets no map from the archive."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self._groups: Dict[str, Dict[str, str]] = {}

    def _archive_lookup(self, folder: Path) -> Dict[str, str]:
        key = folder.as_posix()
        if key not in self._groups:
            from tools.replay_slate import slate_groups

            found: Dict[str, str] = {}
            try:
                groups = slate_groups(folder)["groups"]
            except Exception:  # noqa: BLE001 - a folder that will not group maps nobody
                groups = {}
            for path, mined in groups.items():
                for record in mined:
                    found[str(record.get("contest_id"))] = path
            self._groups[key] = found
        return self._groups[key]

    def for_contest(self, contest_id: str, record_dates: Sequence[str]) -> Tuple[Dict[str, str], str]:
        from mlb_engine.field.field_miner import record_salary_candidates

        for date in sorted(set(record_dates)):
            for path in record_salary_candidates(self.root, date, contest_id):
                return salary_teams(Path(path)), f"salary file via record: {_rel(Path(path), self.root)}"
        folders = sorted({p.parent for p in (self.root / ARCHIVE_DIR).glob(f"*/mined_{contest_id}.json")})
        for folder in folders:
            path = self._archive_lookup(folder).get(str(contest_id))
            if path:
                return salary_teams(Path(path)), f"salary file via slate_groups: {_rel(Path(path), self.root)}"
        return {}, ""


def title_postures(titles: Iterable[Tuple[str, Decimal]]) -> Dict[Tuple[str, Decimal], Tuple[str, bool]]:
    """{(title, fee): (posture, inferred)} by the build's default rule.

    `_resolve_contest_postures` infers the archetype from the title and fee and
    maps it with `normalize_posture` when the operator supplies none. `inferred`
    is the pipeline's `name_inference` source; False is its `unresolved`, where
    the posture comes from the entry cap alone or the large_gpp default.
    """
    from mlb_engine.entries import dk_entries_manager as dm
    from mlb_engine.pipeline.execution_pipeline import normalize_posture

    curated = dm.load_archetypes(dm.find_archetypes_csv())
    out: Dict[Tuple[str, Decimal], Tuple[str, bool]] = {}
    for title, fee in sorted(set(titles)):
        inferred = dm.infer_contest_archetype(title, float(fee), curated)
        out[(title, fee)] = (
            normalize_posture(inferred.get("inferred_type"), inferred.get("payout_shape_default"),
                              inferred.get("inferred_max_entries")),
            inferred.get("inferred_type") not in (None, "", "unknown"))
    return out


def resolved_builds(root: Path, resolution: Optional[Path]) -> Dict[str, Any]:
    """{entry: what its resolved delivery record says}, R497's `resolved` rows only."""
    from mlb_engine.entries.delivery_record import read_records

    if resolution is None:
        return {"builds": {}, "note": "no resolution file; every build-time axis reads unrecorded",
                "resolution_rows": 0, "resolved": 0}
    rows = read_resolution(resolution)
    records = {record_key(r.get("_path")): r for r in read_records(root=Path(root))
               if r.get("kind") == "delivery"}
    builds: Dict[str, Any] = {}
    missing = 0
    for eid, row in sorted(rows.items()):
        if row.get("status") != "resolved":
            continue
        record = records.get(str(row.get("record") or ""))
        entry = next((e for e in (record or {}).get("entries") or []
                      if str(e.get("entry_id") or "").strip() == eid and e.get("filled")), None)
        if entry is None:
            missing += 1
            continue
        extra = record.get("extra") if isinstance(record.get("extra"), Mapping) else {}
        builds[eid] = {
            "record": str(row["record"]), "date": str(record.get("date") or ""),
            "roster_ids": [str(p).strip() for p in entry.get("roster_ids") or []],
            "players": record.get("players") if isinstance(record.get("players"), Mapping) else {},
            "prediction": entry.get("prediction") if isinstance(entry.get("prediction"), Mapping) else None,
            "market": extra.get("market") if isinstance(extra.get("market"), Mapping) else None,
        }
    note = (f"{len(builds)} entries resolved to a record with their entry"
            + (f"; {missing} resolved rows name a record or entry not on disk" if missing else ""))
    return {"builds": builds, "note": note, "resolution_rows": len(rows), "resolved": len(builds)}


def _build_axes(build: Optional[Mapping[str, Any]], primary: str) -> Dict[str, str]:
    """The build-time axes of one entry from its resolved record, else unrecorded."""
    if not build:
        return {"hitter_roles": UNRECORDED, "market": UNRECORDED, "implied_total": UNRECORDED,
                "contest_shape": UNRECORDED}
    pred = build.get("prediction") or {}
    roles = pred.get("hitter_roles") if isinstance(pred.get("hitter_roles"), Mapping) else None
    if roles is None:
        hitter_roles = UNRECORDED
    else:
        projected = sum(1 for v in roles.values() if v == ROLE_PROJECTED)
        known = sum(1 for v in roles.values() if v in (ROLE_PROJECTED, ROLE_CONFIRMED))
        hitter_roles = ("no_known_role" if not known else "0" if projected == 0
                        else "1-2" if projected <= 2 else "3+")
    market = build.get("market")
    if market is None:
        applied: Optional[bool] = None
    else:
        # R494(b) writes `applied`; a record before it reads the writer's own rule.
        applied = bool(market["applied"]) if "applied" in market else bool(market.get("implied_total_by_team"))
    totals = (market or {}).get("implied_total_by_team") or {}
    if applied is None:
        implied = UNRECORDED
    elif not applied:
        implied = "not_applied"
    elif primary in (NONE_LABEL, UNKNOWN):
        implied = primary
    elif primary in totals:
        implied = _band(float(totals[primary]), IMPLIED_BANDS, IMPLIED_OVER)
    else:
        implied = UNRECORDED
    return {"hitter_roles": hitter_roles,
            "market": UNRECORDED if applied is None else ("applied" if applied else "not_applied"),
            "implied_total": implied,
            "contest_shape": str(pred.get("contest_shape") or UNRECORDED)}


def _record_teams(build: Optional[Mapping[str, Any]]) -> Dict[str, str]:
    """{name: team} for an entry's roster from its record's players map (R494)."""
    from mlb_engine.field.field_miner import normalize_name

    out: Dict[str, str] = {}
    for pid in (build or {}).get("roster_ids") or []:
        row = ((build or {}).get("players") or {}).get(pid)
        if isinstance(row, (list, tuple)) and len(row) > 1 and row[0] and row[1]:
            out[normalize_name(str(row[0]))] = str(row[1])
    return out


def _r6_hitters(build: Optional[Mapping[str, Any]], fpts: Mapping[str, float]) -> List[Tuple[str, int]]:
    """(role, dead) for each confirmed or projected hitter of a resolved entry."""
    from mlb_engine.field.field_miner import normalize_name

    pred = (build or {}).get("prediction") or {}
    roles = pred.get("hitter_roles") if isinstance(pred.get("hitter_roles"), Mapping) else {}
    out: List[Tuple[str, int]] = []
    for pid in (build or {}).get("roster_ids") or []:
        role = roles.get(pid)
        row = ((build or {}).get("players") or {}).get(pid)
        if role not in (ROLE_CONFIRMED, ROLE_PROJECTED) or not isinstance(row, (list, tuple)) or not row:
            continue
        points = fpts.get(normalize_name(str(row[0])))
        if points is not None:
            out.append((role, int(points == 0)))
    return out


def attribute_lineups(root: Path, results_rows: Sequence[Mapping[str, str]],
                      builds: Mapping[str, Any]) -> Dict[str, Any]:
    """Every lineup of every contest holding one of our Classic entries, ours and the field's.

    Ours are the paid MLB Classic entries the results file holds whose
    standings export (archive under any date, then the inbox) has a complete
    lineup for the Entry ID. Every other Entry_Key in the results file is ours
    too, so it never joins the field. A field lineup takes its slate and month
    from our results row for the contest, never the folder date.
    """
    from mlb_engine.field.field_miner import own_by_player_norm, normalize_name, parse_standings_export

    root = Path(root)
    ours_ids = {str(r["Entry_Key"]).strip() for r in results_rows}
    population = [r for r in results_rows if r["Sport"] == "MLB" and r["Game_Type"] == CLASSIC_GAME_TYPE
                  and Decimal(r["fee"]) > 0]
    by_contest: Dict[str, List[Mapping[str, str]]] = defaultdict(list)
    for r in population:
        by_contest[str(r["Contest_Key"]).strip()].append(r)
    postures = title_postures((r["Entry"], Decimal(r["fee"])) for r in population)
    teams = _TeamMaps(root)
    coverage: Dict[str, int] = {"population": len(population), "with_lineup": 0, "no_standings": 0,
                                "incomplete_lineup": 0, "absent_from_standings": 0,
                                "field_rank_unusable": 0}
    unreadable: List[str] = []
    not_classic: List[str] = []
    team_sources: Dict[str, str] = {}
    lineups: List[Dict[str, Any]] = []
    inferred_n = fell_through_n = 0
    for cid in sorted(by_contest, key=_cid_order):
        rows_c = sorted(by_contest[cid], key=lambda r: _cid_order(str(r["Entry_Key"])))
        parsed, used = None, None
        for path in standings_files(root, [cid]):
            try:
                candidate = parse_standings_export(str(path))
            except (ValueError, OSError, csv.Error, UnicodeDecodeError):
                unreadable.append(_rel(path, root))
                continue
            if candidate.get("contest_type") == "classic":
                parsed, used = candidate, path
                break
            not_classic.append(_rel(path, root))
        if parsed is None:
            coverage["no_standings"] += len(rows_c)
            continue
        anchor = rows_c[0]
        slate, month, n_field = anchor["slate"], anchor["month"], int(anchor["Contest_Entries"])
        posture, by_title = postures[(anchor["Entry"], Decimal(anchor["fee"]))]
        contest_axes = {"posture": posture, "field_band": anchor["field_band"], "month": month}
        mine = {str(r["Entry_Key"]).strip(): r for r in rows_c}
        complete = [e for e in parsed["entries"] if e["lineup_complete"]]
        by_entry = {e["entry_id"]: e for e in parsed["entries"]}
        for eid in sorted(mine, key=_cid_order):
            if eid not in by_entry:
                coverage["absent_from_standings"] += 1
            elif not by_entry[eid]["lineup_complete"]:
                coverage["incomplete_lineup"] += 1
        if not any(e["entry_id"] in mine for e in complete):
            continue
        own = own_by_player_norm(parsed["player_table"])
        fpts = fpts_by_norm(parsed["player_table"])
        norms = {e["entry_id"]: [(slot, normalize_name(name)) for slot, name in e["lineup"]]
                 for e in complete}
        # The percentile ranks every complete lineup, as the field saw them.
        # DK's shares carry two decimals, so a sum rounded to two is exact and
        # equal lineups tie (unrounded, 112.98 and 112.97999999999999 ranked apart).
        chalk = chalk_percentiles({eid: round(sum(own.get(n, 0.0) for _, n in lu), 2)
                                   for eid, lu in norms.items()})
        # Ours outside the population (a free entry) are neither ours here nor field.
        complete = [e for e in complete if e["entry_id"] in mine or e["entry_id"] not in ours_ids]
        mined = mined_stacks(root, cid)
        record_dates = [builds[e]["date"] for e in mine if e in builds]
        team_map, source = teams.for_contest(cid, record_dates)
        if source:
            team_sources[cid] = source
        stacks = {e["entry_id"]: stack_from_teams(norms[e["entry_id"]], team_map) if team_map else None
                  for e in complete}
        # The share of the field's team-mapped lineups whose primary stack is a
        # team (a lineup with no primary counts in the denominator). A field
        # lineup is measured without itself, as ours are, so the two sides sit
        # on one basis.
        field_primary = [stacks[e["entry_id"]]["primary_team"] for e in complete
                         if e["entry_id"] not in mine and stacks[e["entry_id"]] is not None]
        primary_counts: Dict[str, int] = defaultdict(int)
        for team in field_primary:
            primary_counts[team] += 1
        for e in complete:
            eid = e["entry_id"]
            ours = eid in mine
            build = builds.get(eid) if ours else None
            stack = stack_from_teams(norms[eid], _record_teams(build)) if build else None
            stack = stack or stacks[eid]
            pattern, max_stack = mined.get(eid, (None, None))
            if pattern is None and stack is not None:
                pattern, max_stack = stack["pattern"], stack["max_stack"]
            primary = stack["primary_team"] if stack is not None else UNKNOWN
            own_one = 0 if ours or stacks[eid] is None else 1
            others = len(field_primary) - own_one
            if primary in (UNKNOWN, NONE_LABEL):
                share = primary
            elif others <= 0:
                share = UNKNOWN
            else:
                share = _band((primary_counts[primary] - own_one) / others, TEAM_SHARE_BANDS, TEAM_SHARE_OVER)
            dead = dead_slots(norms[eid], fpts)
            if ours:
                nums = entry_numbers(int(mine[eid]["Place"]), int(mine[eid]["Contest_Entries"]))
            else:
                rank = str(e.get("rank") or "").strip()
                nums = (entry_numbers(int(rank), n_field)
                        if rank.isdigit() and 1 <= int(rank) <= n_field else None)
                if nums is None:
                    coverage["field_rank_unusable"] += 1
            axes = {
                "chalk_third": chalk[eid][1],
                "max_stack": UNKNOWN if max_stack is None else str(max_stack),
                "stack_group": stack_group(pattern, max_stack),
                "stack_pattern": pattern or UNKNOWN,
                "primary_team": primary, "team_field_share": share,
                "dead_slots": str(dead) if dead < 3 else "3+",
                **contest_axes,
                **(_build_axes(build, primary) if ours else {}),
            }
            lineups.append({"entry": eid, "contest": cid, "slate": slate, "month": month, "ours": ours,
                            "numbers": nums, "chalk_pctl": chalk[eid][0], "dead": dead, "axes": axes,
                            "r6": _r6_hitters(build, fpts) if ours else []})
        ours_here = sum(1 for e in complete if e["entry_id"] in mine)
        coverage["with_lineup"] += ours_here
        inferred_n += ours_here if by_title else 0
        fell_through_n += 0 if by_title else ours_here
    return {"lineups": lineups, "coverage": coverage, "standings_unreadable": sorted(set(unreadable)),
            "standings_not_classic": sorted(set(not_classic)),
            "team_sources": team_sources,
            "postures_inferred": {"name_inference": inferred_n, "unresolved": fell_through_n}}


def _draw(A: Any, seed: int, draws: int) -> Any:
    """Slate-bootstrap sums: `cell_stats`'s draw exactly (a fresh generator under
    the seed, `integers(0, k, (draws, k))` over the slates in sorted order)."""
    import numpy as np

    k = A.shape[0]
    return A[np.random.default_rng(seed).integers(0, k, size=(draws, k))].sum(axis=1)


def _slate_matrix(lineups: Sequence[Mapping[str, Any]], slates: Sequence[str]) -> Any:
    import numpy as np

    index = {s: i for i, s in enumerate(slates)}
    A = np.zeros((len(slates), len(_PAIR)), dtype=float)
    for lu in lineups:
        nums = lu["numbers"]
        fp = nums["finish_pctl"]
        row = A[index[lu["slate"]]]
        for i, v in enumerate((1, fp is not None, fp or 0.0, nums["top_decile"], nums["top_ref"],
                               nums["bottom_decile"], nums["bottom_ref"])):
            row[i] += float(v)
    return A


def paired_cell(ours: Sequence[Mapping[str, Any]], field: Optional[Sequence[Mapping[str, Any]]],
                seed: int = BOOTSTRAP_SEED, draws: int = BOOTSTRAP_DRAWS) -> Dict[str, Any]:
    """Our finish and decile excess against the uniform reference, and against the
    field in the same cell, on ONE slate draw.

    The slates are ours (sorted), so our marginals are `cell_stats`'s exactly;
    the field's lineups sit in our contests, so every one of them falls in one
    of those slates and each draw pairs the two. A field difference gets an
    interval only when every draw holds field lineups (the guard `cell_stats`
    puts on the finish). `field=None` is a build-time axis: no field side.
    """
    import numpy as np

    slates = sorted({lu["slate"] for lu in ours})
    col = {name: i for i, name in enumerate(_PAIR)}
    O = _slate_matrix(ours, slates)
    F = _slate_matrix(field, slates) if field is not None else None
    t, f = O.sum(axis=0), (F.sum(axis=0) if F is not None else None)

    def finish(v: Any) -> Any:
        return v[..., col["fp"]] / v[..., col["n_fp"]]

    def excess(v: Any, band: str) -> Any:
        return (v[..., col[band]] - v[..., col[f"{band}_ref"]]) / v[..., col["n"]]

    def pct(x: Any) -> Optional[float]:
        return None if x is None else round(100.0 * float(x), 4)

    out: Dict[str, Any] = {
        "n": int(t[col["n"]]), "slates": len(slates),
        "finish_pctl": pct(finish(t)) if t[col["n_fp"]] else None,
        "top_share": pct(t[col["top"]] / t[col["n"]]), "top_ref": pct(t[col["top_ref"]] / t[col["n"]]),
        "top_excess": pct(excess(t, "top")),
        "bottom_share": pct(t[col["bottom"]] / t[col["n"]]),
        "bottom_ref": pct(t[col["bottom_ref"]] / t[col["n"]]), "bottom_excess": pct(excess(t, "bottom")),
        "finish_pctl_interval": None, "top_excess_interval": None, "bottom_excess_interval": None,
        "field": None,
    }
    if f is not None:
        fn = int(f[col["n"]])
        out["field"] = {
            "n": fn,
            "finish_pctl": pct(finish(f)) if f[col["n_fp"]] else None,
            "top_excess": pct(excess(f, "top")) if fn else None,
            "bottom_excess": pct(excess(f, "bottom")) if fn else None,
            "finish_diff": (round(out["finish_pctl"] - pct(finish(f)), 4)
                            if fn and f[col["n_fp"]] and out["finish_pctl"] is not None else None),
            "top_diff": round(out["top_excess"] - pct(excess(f, "top")), 4) if fn else None,
            "bottom_diff": round(out["bottom_excess"] - pct(excess(f, "bottom")), 4) if fn else None,
            "finish_diff_interval": None, "top_diff_interval": None, "bottom_diff_interval": None,
        }
    if len(slates) < 2:
        return out
    S = _draw(O, seed, draws)
    if (S[:, col["n_fp"]] > 0).all():
        out["finish_pctl_interval"] = _interval(finish(S))
    out["top_excess_interval"] = _interval(excess(S, "top"))
    out["bottom_excess_interval"] = _interval(excess(S, "bottom"))
    G = _draw(F, seed, draws) if F is not None else None
    if G is not None and (G[:, col["n"]] > 0).all():
        side = out["field"]
        side["top_diff_interval"] = _interval(excess(S, "top") - excess(G, "top"))
        side["bottom_diff_interval"] = _interval(excess(S, "bottom") - excess(G, "bottom"))
        if (S[:, col["n_fp"]] > 0).all() and (G[:, col["n_fp"]] > 0).all():
            side["finish_diff_interval"] = _interval(finish(S) - finish(G))
    return out


def _ratio_diff(vectors: Mapping[str, Sequence[float]], slates: Sequence[str],
                seed: int, draws: int) -> Dict[str, Any]:
    """a/b minus c/d over slate sums, with the slate bootstrap; vectors are
    {slate: (a, b, c, d)}. No interval under two slates or where a draw has a
    zero denominator."""
    import numpy as np

    A = np.array([vectors[s] for s in slates], dtype=float).reshape(len(slates), 4)
    t = A.sum(axis=0)
    point = (float(t[0] / t[1]) if t[1] else None, float(t[2] / t[3]) if t[3] else None)
    out: Dict[str, Any] = {"ours": point[0], "field": point[1], "ours_den": int(t[1]),
                           "field_den": int(t[3]),
                           "diff": point[0] - point[1] if None not in point else None, "interval": None}
    if len(slates) >= 2 and None not in point:
        S = _draw(A, seed, draws)
        if (S[:, 1] > 0).all() and (S[:, 3] > 0).all():
            lo, hi = np.percentile(S[:, 0] / S[:, 1] - S[:, 2] / S[:, 3], list(INTERVAL_PCT))
            out["interval"] = [float(lo), float(hi)]
    return out


def _excludes_zero(interval: Optional[Sequence[float]]) -> bool:
    return bool(interval) and (interval[0] > 0 or interval[1] < 0)


def finding_lines(cell: Mapping[str, Any]) -> List[str]:
    """One line per comparison whose interval excludes 0, nothing else.

    About the cell's own finishes, only at FINDING_MIN_N entries and
    FINDING_MIN_SLATES slates, and never about a decile band holding none or
    all of the cell's entries: every draw then has the same share, so the
    interval is the reference's own spread, not the cell's. The share line is
    over the whole population and takes no floor.
    """
    lines: List[str] = []
    sized = cell["n"] >= FINDING_MIN_N and cell["slates"] >= FINDING_MIN_SLATES
    spread = {band: cell[f"{band}_share"] is not None and 0.0 < cell[f"{band}_share"] < 100.0
              for band in ("bottom", "top")}
    for band in ("bottom", "top"):
        if sized and spread[band] and _excludes_zero(cell[f"{band}_excess_interval"]):
            lines.append(f"{band}-decile share {cell[f'{band}_share']:.2f} against its uniform reference "
                         f"{cell[f'{band}_ref']:.2f}: {cell[f'{band}_excess']:+.2f} "
                         f"{_span(cell[f'{band}_excess_interval'], signed=True)}")
    field = cell.get("field") if sized else None
    if field:
        for band in ("bottom", "top"):
            if spread[band] and _excludes_zero(field[f"{band}_diff_interval"]):
                lines.append(f"{band}-decile excess {cell[f'{band}_excess']:+.2f} against the field's "
                             f"{field[f'{band}_excess']:+.2f} in this cell, same contests: "
                             f"{field[f'{band}_diff']:+.2f} {_span(field[f'{band}_diff_interval'], signed=True)}")
        if _excludes_zero(field["finish_diff_interval"]):
            lines.append(f"finish {cell['finish_pctl']:.2f} against the field's {field['finish_pctl']:.2f} "
                         f"in this cell, same contests: {field['finish_diff']:+.2f} "
                         f"{_span(field['finish_diff_interval'], signed=True)}")
    share = cell.get("share")
    if share and share.get("interval") and _excludes_zero(share["interval"]):
        lines.append(f"{100 * share['ours']:.1f}% of our {share['ours_den']} entries against "
                     f"{100 * share['field']:.1f}% of the field's {share['field_den']} lineups: "
                     f"{100 * share['diff']:+.1f} [{100 * share['interval'][0]:+.1f}, "
                     f"{100 * share['interval'][1]:+.1f}]")
    return lines


def _attribute_order(axis: str, value: str, counts: Mapping[str, int]) -> Tuple[Any, ...]:
    tail = value in (UNKNOWN, UNRECORDED, NONE_LABEL)
    fixed = {
        "chalk_third": ["low", "mid", "high"], "stack_group": list(STACK_GROUPS),
        "dead_slots": ["0", "1", "2", "3+"], "hitter_roles": ["0", "1-2", "3+"],
        "team_field_share": [label for _, label in TEAM_SHARE_BANDS] + [TEAM_SHARE_OVER],
        "implied_total": [label for _, label in IMPLIED_BANDS] + [IMPLIED_OVER],
        "field_band": [label for _, label in FIELD_BANDS] + [FIELD_BAND_OVER],
        "market": ["applied", "not_applied"],
        "captain_role": [ROLE_PITCHER, ROLE_HITTER], "team_split": list(TEAM_SPLITS),
        "captain_cpt_share": [label for _, label in CPT_SHARE_BANDS] + [CPT_SHARE_OVER],
        "captain_flex_share": [label for _, label in FLEX_SHARE_BANDS] + [FLEX_SHARE_OVER],
        "duplication": list(DUPLICATION_LABELS),
    }.get(axis)
    if fixed is not None:
        return (tail, fixed.index(value) if value in fixed else len(fixed), value)
    if axis == "max_stack":
        return (tail, -int(value) if value.isdigit() else 0, value)
    if axis in ("stack_pattern", "primary_team"):
        return (tail, -counts[value], value)
    return (tail, value)


def attribute_cells(lineups: Sequence[Mapping[str, Any]], seed: int = BOOTSTRAP_SEED,
                    draws: int = BOOTSTRAP_DRAWS,
                    axes: Sequence[Tuple[str, str]] = ATTRIBUTE_AXES) -> Dict[str, Any]:
    """Every axis's cells: ours against the uniform reference, against the field in
    the same cell of the same contests, and (lineup axes) our share of entries
    against the field's share of lineups over every contest we entered, each
    share over the lineups whose value is known. The chalk and dead-slot means
    are Classic's (R498); a Showdown lineup (R500) carries neither."""
    ours_all = [lu for lu in lineups if lu["ours"]]
    field_all = [lu for lu in lineups if not lu["ours"]]
    pop_slates = sorted({lu["slate"] for lu in ours_all})
    axes_out: Dict[str, Any] = {}
    for axis, level in axes:
        ours_by: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
        field_by: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
        for lu in ours_all:
            ours_by[lu["axes"][axis]].append(lu)
        if level != "build":
            for lu in field_all:
                field_by[lu["axes"][axis]].append(lu)
        known: Dict[str, List[float]] = {s: [0.0, 0.0] for s in pop_slates}
        if level == "lineup":
            for i, side in ((0, ours_all), (1, field_all)):
                for lu in side:
                    if lu["axes"][axis] not in (UNKNOWN, UNRECORDED):
                        known[lu["slate"]][i] += 1
        counts = {value: len(members) for value, members in ours_by.items()}
        cells: Dict[str, Any] = {}
        for value in sorted(counts, key=lambda v: _attribute_order(axis, v, counts)):
            ours = ours_by[value]
            contests = {lu["contest"] for lu in ours}
            field = (None if level == "build" else
                     [lu for lu in field_by.get(value, []) if lu["contest"] in contests
                      and lu["numbers"] is not None])
            cell = paired_cell(ours, field, seed, draws)
            if "chalk_pctl" in ours[0]:
                cell["chalk_pctl_mean"] = round(sum(lu["chalk_pctl"] for lu in ours) / len(ours), 4)
                cell["dead_mean"] = round(sum(lu["dead"] for lu in ours) / len(ours), 4)
            cell["share"] = None
            if level == "lineup" and value not in (UNKNOWN, UNRECORDED):
                vec = {s: [0.0, known[s][0], 0.0, known[s][1]] for s in pop_slates}
                for lu in ours:
                    vec[lu["slate"]][0] += 1
                for lu in field_by.get(value, []):
                    vec[lu["slate"]][2] += 1
                cell["share"] = _ratio_diff(vec, pop_slates, seed, draws)
            cell["findings"] = finding_lines(cell)
            cells[value] = cell
        axes_out[axis] = {"level": level, "cells": cells}
    return axes_out


def dead_slot_summary(lineups: Sequence[Mapping[str, Any]], seed: int = BOOTSTRAP_SEED,
                      draws: int = BOOTSTRAP_DRAWS) -> Dict[str, Any]:
    """Dead slots per lineup, ours against the field in the same contests, overall and by month."""
    out: Dict[str, Any] = {}
    months = sorted({lu["month"] for lu in lineups if lu["ours"]})
    for label in ["overall"] + months:
        subset = [lu for lu in lineups if label == "overall" or lu["month"] == label]
        slates = sorted({lu["slate"] for lu in subset if lu["ours"]})
        vec = {s: [0.0, 0.0, 0.0, 0.0] for s in slates}
        for lu in subset:
            if lu["slate"] in vec:
                i = 0 if lu["ours"] else 2
                vec[lu["slate"]][i] += lu["dead"]
                vec[lu["slate"]][i + 1] += 1
        out[label] = _ratio_diff(vec, slates, seed, draws)
    return out


def r6_summary(lineups: Sequence[Mapping[str, Any]], seed: int = BOOTSTRAP_SEED,
               draws: int = BOOTSTRAP_DRAWS) -> Dict[str, Any]:
    """Dead-slot rate of platoon_projected hitters minus confirmed_lineup hitters, in
    the contests where our resolved entries hold both (the results review's R6).

    `reading` is `finding` only for the D-row's question (projected above
    confirmed, the interval excluding 0, at FINDING_MIN_SLATES slates or more);
    an interval wholly below 0 reads `below`, never inside the reference.
    """
    by_contest: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    slate_of: Dict[str, str] = {}
    for lu in lineups:
        if not lu["ours"]:
            continue
        slate_of[lu["contest"]] = lu["slate"]
        for role, dead in lu["r6"]:
            by_contest[lu["contest"]][f"{role}_n"] += 1
            by_contest[lu["contest"]][f"{role}_dead"] += dead
    both = {c: v for c, v in by_contest.items()
            if v[f"{ROLE_CONFIRMED}_n"] and v[f"{ROLE_PROJECTED}_n"]}
    slates = sorted({slate_of[c] for c in both})
    vec = {s: [0.0, 0.0, 0.0, 0.0] for s in slates}
    for c, v in both.items():
        row = vec[slate_of[c]]
        row[0] += v[f"{ROLE_PROJECTED}_dead"]
        row[1] += v[f"{ROLE_PROJECTED}_n"]
        row[2] += v[f"{ROLE_CONFIRMED}_dead"]
        row[3] += v[f"{ROLE_CONFIRMED}_n"]
    got = _ratio_diff(vec, slates, seed, draws) if slates else {
        "ours": None, "field": None, "ours_den": 0, "field_den": 0, "diff": None, "interval": None}
    out = {"projected": got["ours"], "confirmed": got["field"], "projected_n": got["ours_den"],
           "confirmed_n": got["field_den"], "diff": got["diff"], "interval": got["interval"],
           "contests": len(both), "slates": len(slates)}
    if not both:
        out["reading"] = "not_measurable"
    elif len(slates) < FINDING_MIN_SLATES:
        out["reading"] = "under_floor"
    elif _excludes_zero(got["interval"]):
        out["reading"] = "finding" if got["interval"][0] > 0 else "below"
    else:
        out["reading"] = "inside"
    return out


def build_attribution(root: Path, results_rows: Sequence[Mapping[str, str]],
                      resolution: Optional[Path], seed: int = BOOTSTRAP_SEED,
                      draws: int = BOOTSTRAP_DRAWS) -> Dict[str, Any]:
    builds = resolved_builds(root, resolution)
    joined = attribute_lineups(root, results_rows, builds["builds"])
    lineups = joined["lineups"]
    ours = [lu for lu in lineups if lu["ours"]]
    overall = (paired_cell(ours, [lu for lu in lineups if not lu["ours"] and lu["numbers"] is not None],
                           seed, draws) if ours else None)
    if overall is not None:
        overall["chalk_pctl_mean"] = round(sum(lu["chalk_pctl"] for lu in ours) / len(ours), 4)
        overall["dead_mean"] = round(sum(lu["dead"] for lu in ours) / len(ours), 4)
        overall["share"] = None
        overall["findings"] = finding_lines(overall)
    return {
        "population": "paid MLB Classic entries (fee above 0) with a complete lineup in a standings export",
        "coverage": {**joined["coverage"], "field_lineups": len(lineups) - len(ours),
                     "contests": len({lu["contest"] for lu in ours}),
                     "slates": len({lu["slate"] for lu in ours}),
                     "team_mapped_contests": len(joined["team_sources"]),
                     "team_mapped_entries": sum(1 for lu in ours if lu["contest"] in joined["team_sources"]),
                     "standings_unreadable": joined["standings_unreadable"],
                     "standings_not_classic": joined["standings_not_classic"]},
        "postures_inferred": joined["postures_inferred"],
        "builds": {k: v for k, v in builds.items() if k != "builds"},
        "bootstrap": {"unit": "slate (sport, date, game type)", "draws": draws, "seed": seed,
                      "interval_pct": list(INTERVAL_PCT), "order": "slates sorted before sampling"},
        "labels": list(ATTRIBUTE_LABELS),
        "overall": overall,
        "axes": attribute_cells(lineups, seed, draws),
        "dead_slots": dead_slot_summary(lineups, seed, draws),
        "r6": r6_summary(lineups, seed, draws),
        "team_sources": joined["team_sources"],
    }


def _pct_span(interval: Optional[Sequence[float]]) -> str:
    return "[no interval]" if not interval else f"[{interval[0]:+.2f}, {interval[1]:+.2f}]"


def render_attribution(report: Mapping[str, Any], results: Path) -> str:
    cov = report["coverage"]
    boot = report["bootstrap"]
    lines = [f"results_ledger attribute  ({report['population']})", f"  results: {results}",
             f"  coverage: {cov['with_lineup']} of {cov['population']} entries with a lineup in "
             f"{cov['contests']} contests, {cov['slates']} slates; {cov['no_standings']} without a "
             f"standings export, {cov['absent_from_standings']} absent from theirs, "
             f"{cov['incomplete_lineup']} incomplete; field {cov['field_lineups']} lineups "
             f"({cov['field_rank_unusable']} without a usable rank)",
             f"  team map: {cov['team_mapped_entries']} of our entries in {cov['team_mapped_contests']} "
             "contests (primary team and its field share are unknown elsewhere)",
             f"  posture: {report['postures_inferred']['name_inference']} of our entries by "
             f"name_inference, {report['postures_inferred']['unresolved']} unresolved (the entry cap "
             "or the large_gpp default)",
             f"  build-time axes: {report['builds']['note']}",
             f"  intervals: 90%, {boot['unit']} bootstrap, {boot['draws']} draws, seed {boot['seed']}, "
             f"{boot['order']}; ours and the field paired on one draw per cell"]
    for label in report["labels"]:
        lines.append(f"  label:   {label}")
    lines.append("")
    lines.extend(render_attribution_cell("overall", report["overall"]))
    for axis, block in report["axes"].items():
        lines.append("")
        lines.append(f"== {axis} ({block['level']}) ==")
        for value, cell in block["cells"].items():
            lines.extend(render_attribution_cell(value, cell))
    return _render_summaries(report, lines)


def render_attribution_cell(value: str, cell: Mapping[str, Any]) -> List[str]:
    lines: List[str] = []
    means = (f"chalk {cell['chalk_pctl_mean']:.3f}  dead {cell['dead_mean']:.2f}  "
             if "chalk_pctl_mean" in cell else "")
    lines.append(
        f"  {value:<22} n {cell['n']}  slates {cell['slates']}  {means}finish {_num(cell['finish_pctl'])} "
        f"{_span(cell['finish_pctl_interval'])}  top {_num(cell['top_share'])} vs "
        f"{_num(cell['top_ref'])} ({_num(cell['top_excess'], '{:+.2f}')} "
        f"{_span(cell['top_excess_interval'], signed=True)})  bottom {_num(cell['bottom_share'])} vs "
        f"{_num(cell['bottom_ref'])} ({_num(cell['bottom_excess'], '{:+.2f}')} "
        f"{_span(cell['bottom_excess_interval'], signed=True)})")
    field = cell["field"]
    if field is None:
        lines.append(f"  {'':<22} field: n/a (a build-time axis)")
    else:
        lines.append(
            f"  {'':<22} field in this cell, same contests: n {field['n']}  finish "
            f"{_num(field['finish_pctl'])}  top {_num(field['top_excess'], '{:+.2f}')}  bottom "
            f"{_num(field['bottom_excess'], '{:+.2f}')}  ours minus field: bottom "
            f"{_num(field['bottom_diff'], '{:+.2f}')} {_span(field['bottom_diff_interval'], signed=True)}")
    share = cell["share"]
    if share:
        lines.append(f"  {'':<22} share: {100 * share['ours']:.1f}% of our {share['ours_den']} "
                     f"against {100 * (share['field'] or 0):.1f}% of the field's "
                     f"{share['field_den']} lineups")
    if cell["findings"]:
        lines.extend(f"  {'':<22} finding: {text}" for text in cell["findings"])
    if cell["slates"] < 2:
        lines.append(f"  {'':<22} no interval on its finishes: under 2 slates")
    elif cell["n"] < FINDING_MIN_N or cell["slates"] < FINDING_MIN_SLATES:
        lines.append(f"  {'':<22} under the finding floor ({FINDING_MIN_N} entries, "
                     f"{FINDING_MIN_SLATES} slates)")
    elif not cell["findings"]:
        lines.append(f"  {'':<22} inside the reference")
    return lines


def _render_summaries(report: Mapping[str, Any], lines: List[str]) -> str:
    lines.append("")
    lines.append("== dead slots per lineup, ours against the field in the same contests ==")
    for label, d in report["dead_slots"].items():
        lines.append(f"  {label:<10} ours {_num(d['ours'])} ({d['ours_den']})  field {_num(d['field'])} "
                     f"({d['field_den']})  difference {_num(d['diff'], '{:+.2f}')} {_pct_span(d['interval'])}")
    r6 = report["r6"]
    lines.append("")
    lines.append("== R6: dead-slot rate, platoon_projected hitters minus confirmed_lineup hitters ==")
    if r6["reading"] == "not_measurable":
        lines.append("  not measurable: n 0 (no resolved entry carries hitter roles in a contest holding both)")
    else:
        verdict = {"finding": "finding: projected above confirmed (the R6 D-row's question)",
                   "below": "the interval excludes 0 below it: projected under confirmed",
                   "under_floor": f"under the finding floor ({FINDING_MIN_SLATES} slates)",
                   "inside": "inside the reference"}[r6["reading"]]
        lines.append(f"  projected {_num(r6['projected'], '{:.3f}')} of {r6['projected_n']}  confirmed "
                     f"{_num(r6['confirmed'], '{:.3f}')} of {r6['confirmed_n']}  difference "
                     f"{_num(r6['diff'], '{:+.3f}')} {_pct_span(r6['interval'])}  ({r6['contests']} contests, "
                     f"{r6['slates']} slates)  {verdict}")
    return "\n".join(lines) + "\n"


def cmd_attribute(args: argparse.Namespace) -> int:
    root = Path(args.root)
    results = Path(args.results) if args.results else root / REFERENCE_DIR / RESULTS_NAME
    if not results.is_file():
        print(f"ERROR  no results file at {results}; run `python tools/results_ledger.py ingest` "
              "first (a DEV session adds --out <scratch path> and passes it here as --results)",
              file=sys.stderr)
        return EXIT_IO
    if args.resolution:
        resolution: Optional[Path] = Path(args.resolution)
        if not resolution.is_file():
            print(f"ERROR  no resolution file at {resolution}; run `python tools/results_ledger.py "
                  "resolve` first", file=sys.stderr)
            return EXIT_IO
    else:
        default = root / REFERENCE_DIR / RESOLUTION_NAME
        resolution = default if default.is_file() else None
    if args.rank:
        builds = resolved_builds(root, resolution)
        ranked = {"rank": rank_report(read_results(results), builds["builds"]),
                  "builds": {k: v for k, v in builds.items() if k != "builds"},
                  "labels": list(RANK_LABELS)}
        if args.json:
            print(json.dumps({**ranked, "results": str(results)}, indent=1, sort_keys=True))
        else:
            sys.stdout.write(render_rank(ranked, results))
        return EXIT_OK
    if args.showdown:
        report = build_showdown_attribution(root, read_results(results), resolution)
        if args.json:
            print(json.dumps({**report, "results": str(results)}, indent=1, sort_keys=True))
        elif not report["coverage"]["with_lineup"]:
            print(f"no paid MLB Showdown entry in {results} has a complete lineup in a standings export")
        else:
            sys.stdout.write(render_showdown_attribution(report, results))
        return EXIT_OK
    report = build_attribution(root, read_results(results), resolution)
    if args.json:
        print(json.dumps({**report, "results": str(results)}, indent=1, sort_keys=True))
    elif not report["coverage"]["with_lineup"]:
        print(f"no paid MLB Classic entry in {results} has a complete lineup in a standings export")
    else:
        sys.stdout.write(render_attribution(report, results))
    return EXIT_OK


# ---------------------------------------------------------------------------
# attribute --rank (R500(a)): the engine's own order against finish order
# ---------------------------------------------------------------------------

#: Per format, the prediction key a resolved entry carries and the sign that
#: makes "the engine put it higher" read high: R494's allocator score (higher
#: is better) and R495's rank in the build (1 is the build's best Base).
RANK_KEYS: Dict[str, Tuple[str, int]] = {"classic": ("contest_fit_score", 1),
                                         "showdown": ("rank_in_build", -1)}
RANK_GAME_TYPES = {CLASSIC_GAME_TYPE: "classic", SHOWDOWN_GAME_TYPE: "showdown"}
RANK_LABELS: Tuple[str, ...] = (
    "Spearman over midranks, per unit: +1 when the engine's own order of our entries equals "
    "their finish order (DK's Place, ties shared), -1 when it is reversed. A review proxy of "
    "the engine's ordering, never a probability, a win rate or an edge.",
    "Classic orders by R494's contest_fit_score (the allocator's score); Showdown by R495's "
    "rank_in_build (the build's Base with the captain at 1.5x, descending, ties by slot).",
    "A unit is one contest's entries from one build: a score orders only its own build's "
    "lineups, so a contest whose entries came from two builds (a rebuild, a late swap, the "
    "Showdown baseline beside its ladder) is cut into one unit per build. Classic keys the "
    "build by the prediction's run, Showdown by the record R497 resolved the entry to.",
    "Only entries R497 resolved to a delivery record whose entry carries the key, free entries "
    "included (the order is the engine's whatever the fee). A unit needs two of them, and one "
    "with no spread on either side has no correlation; both are counted.",
)


def rank_report(results_rows: Sequence[Mapping[str, str]], builds: Mapping[str, Any]) -> Dict[str, Any]:
    """Per format, per unit (a contest's resolved entries from one build), the
    Spearman correlation between the engine's own order and the finish order,
    and its median and spread across units; skipped units counted. The
    correlation is `replay_slate.spearman` (tie-averaged ranks, None under two
    pairs or with no spread on a side, 4 decimals), R384's projection grade's."""
    import numpy as np

    from tools.replay_slate import spearman

    units: Dict[str, Dict[Tuple[str, str], List[Tuple[float, int]]]] = {f: defaultdict(list) for f in RANK_KEYS}
    without_key = {f: 0 for f in RANK_KEYS}
    for row in results_rows:
        fmt = RANK_GAME_TYPES.get(row["Game_Type"]) if row["Sport"] == "MLB" else None
        build = builds.get(str(row["Entry_Key"]).strip())
        if fmt is None or build is None:
            continue
        key, sign = RANK_KEYS[fmt]
        pred = build.get("prediction") or {}
        value = pred.get(key)
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            without_key[fmt] += 1
            continue
        scale = str(pred.get("run_id") or "") if fmt == "classic" else ""
        units[fmt][(str(row["Contest_Key"]).strip(), scale or str(build.get("record") or ""))].append(
            (sign * float(value), int(row["Place"])))
    out: Dict[str, Any] = {}
    for fmt, by_unit in units.items():
        measured: List[Dict[str, Any]] = []
        one = one_entries = flat = 0
        for (cid, scale) in sorted(by_unit, key=lambda u: (_cid_order(u[0]), u[1])):
            pairs = by_unit[(cid, scale)]
            if len(pairs) < 2:
                one += 1
                one_entries += len(pairs)
                continue
            rho = spearman([p[0] for p in pairs], [-p[1] for p in pairs])
            if rho is None:
                flat += 1
                continue
            measured.append({"contest": cid, "build": scale, "n": len(pairs), "rho": rho})
        rhos = [u["rho"] for u in measured]
        cut = ([round(float(v), 6) for v in np.percentile(rhos, [25, 50, 75])] if rhos else [None] * 3)
        contests = defaultdict(set)
        for cid, scale in by_unit:
            contests[cid].add(scale)
        out[fmt] = {
            "key": RANK_KEYS[fmt][0], "units": len(measured), "entries": sum(u["n"] for u in measured),
            "contests": len({u["contest"] for u in measured}),
            "median": cut[1], "p25": cut[0], "p75": cut[2],
            "min": min(rhos) if rhos else None, "max": max(rhos) if rhos else None,
            "skipped_one_entry": {"units": one, "entries": one_entries}, "skipped_no_spread": flat,
            "contests_split_across_builds": sum(1 for s in contests.values() if len(s) > 1),
            "entries_without_key": without_key[fmt], "per_unit": measured,
        }
    return out


def render_rank(ranked: Mapping[str, Any], results: Path) -> str:
    lines = ["results_ledger attribute --rank  (the engine's own order of our entries against "
             "their finish order)", f"  results: {results}",
             f"  build-time source: {ranked['builds']['note']}"]
    lines += [f"  label:   {label}" for label in ranked["labels"]]
    for fmt, r in ranked["rank"].items():
        lines.append("")
        head = f"  {fmt:<9} {r['key']}: {r['units']} unit(s) in {r['contests']} contest(s), {r['entries']} entries"
        if r["units"]:
            lines.append(f"{head}: median {r['median']:+.3f}, p25 {r['p25']:+.3f}, p75 {r['p75']:+.3f}, "
                         f"range [{r['min']:+.3f}, {r['max']:+.3f}]")
        else:
            lines.append(f"{head}: not measurable (n 0)")
        lines.append(f"  {'':<9} skipped: {r['skipped_one_entry']['units']} unit(s) with one entry "
                     f"({r['skipped_one_entry']['entries']} entries), {r['skipped_no_spread']} with no "
                     f"spread; {r['contests_split_across_builds']} contest(s) split across builds; "
                     f"{r['entries_without_key']} resolved entries carry no {r['key']}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# attribute --showdown (R500(b)): the Showdown axis
# ---------------------------------------------------------------------------

SHOWDOWN_SIZE = 6
ROLE_PITCHER, ROLE_HITTER = "pitcher", "hitter"
TEAM_SPLITS = ("5-1", "4-2", "3-3")
# The captain's share of the field's complete lineups at CPT and at UTIL, upper
# bounds exclusive. Our 757 archived Showdown entries' captains sit at quartiles
# 3.2, 9.3 and 20.4% at CPT and 19.9, 26.9 and 34.6% at UTIL (2026-10-12).
CPT_SHARE_BANDS, CPT_SHARE_OVER = TEAM_SHARE_BANDS, TEAM_SHARE_OVER
FLEX_SHARE_BANDS: Tuple[Tuple[float, str], ...] = ((0.20, "<20%"), (0.30, "20-30%"), (0.40, "30-40%"))
FLEX_SHARE_OVER = "40%+"
DUPLICATION_LABELS = ("0", "1", "2+")
SEASON_PITCHING = REFERENCE_DIR / "statsapi_season_pitching.csv"
SEASON_BATTING = REFERENCE_DIR / "expected_stats_batting.csv"
SHOWDOWN_AXES: Tuple[Tuple[str, str], ...] = (
    ("captain_role", "lineup"), ("captain_cpt_share", "lineup"), ("captain_flex_share", "lineup"),
    ("team_split", "lineup"), ("duplication", "lineup"), ("posture", "contest"),
    ("field_band", "contest"), ("month", "contest"), ("thesis", "build"),
)
SHOWDOWN_LABELS: Tuple[str, ...] = (
    "Observed outcomes and review proxies: which Showdown constructions sat under our finishes, "
    "never why, never ROI, a win rate or a probability; nothing reads this back into a control.",
    ATTRIBUTE_LABELS[1],
    "Captain role: DK's position from the delivery record R497 resolved our entry to; otherwise, "
    "and for every field lineup, a labelled prior from the vendored season tables: pitcher when "
    "the name is only in statsapi_season_pitching.csv, hitter when only in "
    "expected_stats_batting.csv, unknown when in both (mostly a position player with a mop-up "
    "inning or a pitcher with a plate appearance; also a two-way player, or two people sharing a "
    "name) or in neither (a name the tables spell another way). It moves when ARCHIVE refreshes "
    "those tables.",
    "Captain CPT% and flex%: the captain's share of the field's complete lineups (ours never "
    "among them) at CPT and at UTIL, counted from the entry block, because DK's %Drafted table "
    "drops one of two equal slot rows (R341); a field lineup is measured without itself.",
    "Team split: players per team over all six (5-1, 4-2, 3-3), from the mined standings, else "
    "the resolved record's split.",
    "Duplication: the other complete lineups in the contest with the same captain and the same "
    "five, whoever entered them (field_miner.lineup_identity_groups, captain-aware).",
    "Thesis: the template the build dealt the entry (R495), only from a resolved delivery record.",
    ATTRIBUTE_LABELS[5],
    "The bootstrap's slate is R496's (sport, date, game type), so every single-game Showdown "
    "contest of one day is one slate.",
    ATTRIBUTE_LABELS[7],
    ATTRIBUTE_LABELS[9],
)


def season_roles(root: Path) -> Dict[str, Any]:
    """{name: pitcher|hitter} from the two vendored season tables, by normalized name.

    A name in both tables (mostly a position player with a mop-up inning or a
    pitcher with a plate appearance; also a two-way player, or two people
    sharing a name) or in neither is absent, so it reads unknown. Both tables are needed: with one,
    every name of the other kind would read unknown and the pitcher share of
    the known roles would be wrong, so a missing table classifies nobody.
    """
    from mlb_engine.field.field_miner import normalize_name

    names: Dict[str, set] = {}
    missing: List[str] = []
    for kind, rel, column in ((ROLE_PITCHER, SEASON_PITCHING, "Name"),
                              (ROLE_HITTER, SEASON_BATTING, "last_name, first_name")):
        found: set = set()
        try:
            with open(Path(root) / rel, "r", encoding="utf-8-sig", newline="") as fh:
                for row in csv.DictReader(fh):
                    name = str(row.get(column) or "")
                    if "," in name:
                        last, first = name.split(",", 1)
                        name = f"{first.strip()} {last.strip()}"
                    if normalize_name(name):
                        found.add(normalize_name(name))
        except (OSError, csv.Error, UnicodeDecodeError):
            missing.append(rel.as_posix())
        names[kind] = found
    if missing:
        return {"roles": {}, "both": 0, "note": f"no captain role from the tables: {', '.join(missing)} unreadable"}
    pitch, bat = names[ROLE_PITCHER], names[ROLE_HITTER]
    roles = {n: ROLE_PITCHER for n in pitch - bat}
    roles.update({n: ROLE_HITTER for n in bat - pitch})
    return {"roles": roles, "both": len(pitch & bat),
            "note": f"{len(pitch - bat)} pitchers and {len(bat - pitch)} hitters from "
                    f"{SEASON_PITCHING.name} and {SEASON_BATTING.name}; {len(pitch & bat)} names in both"}


def showdown_lineups(root: Path, results_rows: Sequence[Mapping[str, str]],
                     builds: Mapping[str, Any]) -> Dict[str, Any]:
    """Every lineup of every contest holding one of our Showdown entries, ours and the field's.

    `attribute_lineups`' population and field rules on Showdown: ours are the
    paid MLB Showdown entries whose standings export has a complete lineup for
    the Entry ID; every other Entry_Key in the results file is ours too and
    never joins the field; a field lineup takes its slate from our row.
    """
    from mlb_engine.field.field_miner import lineup_identity_groups, normalize_name, parse_standings_export

    root = Path(root)
    ours_ids = {str(r["Entry_Key"]).strip() for r in results_rows}
    population = [r for r in results_rows if r["Sport"] == "MLB" and r["Game_Type"] == SHOWDOWN_GAME_TYPE
                  and Decimal(r["fee"]) > 0]
    by_contest: Dict[str, List[Mapping[str, str]]] = defaultdict(list)
    for r in population:
        by_contest[str(r["Contest_Key"]).strip()].append(r)
    postures = title_postures((r["Entry"], Decimal(r["fee"])) for r in population)
    roles = season_roles(root)
    coverage: Dict[str, int] = {"population": len(population), "with_lineup": 0, "no_standings": 0,
                                "incomplete_lineup": 0, "absent_from_standings": 0,
                                "field_rank_unusable": 0}
    role_check = {"recorded": 0, "recorded_and_table": 0, "disagree": 0}
    unreadable: List[str] = []
    not_showdown: List[str] = []
    lineups: List[Dict[str, Any]] = []
    inferred_n = fell_through_n = 0
    for cid in sorted(by_contest, key=_cid_order):
        rows_c = sorted(by_contest[cid], key=lambda r: _cid_order(str(r["Entry_Key"])))
        parsed = None
        for path in standings_files(root, [cid]):
            try:
                candidate = parse_standings_export(str(path))
            except (ValueError, OSError, csv.Error, UnicodeDecodeError):
                unreadable.append(_rel(path, root))
                continue
            if candidate.get("contest_type") == "showdown":
                parsed = candidate
                break
            not_showdown.append(_rel(path, root))
        if parsed is None:
            coverage["no_standings"] += len(rows_c)
            continue
        anchor = rows_c[0]
        slate, month, n_field = anchor["slate"], anchor["month"], int(anchor["Contest_Entries"])
        posture, by_title = postures[(anchor["Entry"], Decimal(anchor["fee"]))]
        contest_axes = {"posture": posture, "field_band": anchor["field_band"], "month": month}
        mine = {str(r["Entry_Key"]).strip(): r for r in rows_c}
        everyone = [e for e in parsed["entries"] if e["lineup_complete"]]
        by_entry = {e["entry_id"]: e for e in parsed["entries"]}
        for eid in sorted(mine, key=_cid_order):
            if eid not in by_entry:
                coverage["absent_from_standings"] += 1
            elif not by_entry[eid]["lineup_complete"]:
                coverage["incomplete_lineup"] += 1
        if not any(e["entry_id"] in mine for e in everyone):
            continue
        # Duplication counts every complete lineup in the contest, whoever entered it.
        groups, _ = lineup_identity_groups(everyone, "showdown", strict=False)
        copies = {eid: len(ids) for ids in groups.values() for eid in ids}
        complete = [e for e in everyone if e["entry_id"] in mine or e["entry_id"] not in ours_ids]
        field = [e for e in complete if e["entry_id"] not in mine]
        cpt_counts: Dict[str, int] = defaultdict(int)
        util_counts: Dict[str, int] = defaultdict(int)
        for e in field:
            cpt_counts[str(e["captain_norm"])] += 1
            for name in {normalize_name(n) for slot, n in e["lineup"] if slot == "UTIL"}:
                util_counts[name] += 1
        mined = mined_stacks(root, cid, "showdown", SHOWDOWN_SIZE)
        for e in complete:
            eid = e["entry_id"]
            ours = eid in mine
            build = builds.get(eid) if ours else None
            pred = ((build or {}).get("prediction") or {}) if ours else {}
            captain = str(e["captain_norm"])
            others = len(field) - (0 if ours else 1)
            if others <= 0:
                cpt_share = flex_share = UNKNOWN
            else:
                # A field lineup leaves itself out; its own UTIL never holds its captain.
                cpt_share = _band((cpt_counts[captain] - (0 if ours else 1)) / others,
                                  CPT_SHARE_BANDS, CPT_SHARE_OVER)
                flex_share = _band(util_counts[captain] / others, FLEX_SHARE_BANDS, FLEX_SHARE_OVER)
            recorded = pred.get("captain_role") if pred.get("captain_role") in (ROLE_PITCHER, ROLE_HITTER) else None
            table = roles["roles"].get(captain, UNKNOWN)
            if recorded:
                role_check["recorded"] += 1
                if table != UNKNOWN:
                    role_check["recorded_and_table"] += 1
                    role_check["disagree"] += int(recorded != table)
            split = mined.get(eid, (None, None))[0]
            if split is None and pred.get("team_split") in TEAM_SPLITS:
                split = pred["team_split"]
            dup = copies[eid] - 1
            if ours:
                nums = entry_numbers(int(mine[eid]["Place"]), int(mine[eid]["Contest_Entries"]))
            else:
                rank = str(e.get("rank") or "").strip()
                nums = (entry_numbers(int(rank), n_field)
                        if rank.isdigit() and 1 <= int(rank) <= n_field else None)
                if nums is None:
                    coverage["field_rank_unusable"] += 1
            axes = {
                "captain_role": recorded or table,
                "captain_cpt_share": cpt_share, "captain_flex_share": flex_share,
                "team_split": split or UNKNOWN,
                "duplication": str(dup) if dup < 2 else "2+",
                **contest_axes,
                **({"thesis": str(pred.get("thesis") or UNRECORDED) if build else UNRECORDED} if ours else {}),
            }
            lineups.append({"entry": eid, "contest": cid, "slate": slate, "month": month, "ours": ours,
                            "numbers": nums, "axes": axes})
        ours_here = sum(1 for e in complete if e["entry_id"] in mine)
        coverage["with_lineup"] += ours_here
        inferred_n += ours_here if by_title else 0
        fell_through_n += 0 if by_title else ours_here
    return {"lineups": lineups, "coverage": coverage, "standings_unreadable": sorted(set(unreadable)),
            "standings_not_showdown": sorted(set(not_showdown)), "roles_note": roles["note"],
            "role_check": role_check,
            "postures_inferred": {"name_inference": inferred_n, "unresolved": fell_through_n}}


def build_showdown_attribution(root: Path, results_rows: Sequence[Mapping[str, str]],
                               resolution: Optional[Path], seed: int = BOOTSTRAP_SEED,
                               draws: int = BOOTSTRAP_DRAWS) -> Dict[str, Any]:
    builds = resolved_builds(root, resolution)
    joined = showdown_lineups(root, results_rows, builds["builds"])
    lineups = joined["lineups"]
    ours = [lu for lu in lineups if lu["ours"]]
    overall = (paired_cell(ours, [lu for lu in lineups if not lu["ours"] and lu["numbers"] is not None],
                           seed, draws) if ours else None)
    if overall is not None:
        overall["share"] = None
        overall["findings"] = finding_lines(overall)
    unknown = {side: sum(1 for lu in lineups if lu["ours"] == (side == "ours")
                         and lu["axes"]["captain_role"] == UNKNOWN) for side in ("ours", "field")}
    return {
        "population": "paid MLB Showdown entries (fee above 0) with a complete lineup in a standings export",
        "coverage": {**joined["coverage"], "field_lineups": len(lineups) - len(ours),
                     "contests": len({lu["contest"] for lu in ours}),
                     "slates": len({lu["slate"] for lu in ours}),
                     "standings_unreadable": joined["standings_unreadable"],
                     "standings_not_showdown": joined["standings_not_showdown"]},
        "postures_inferred": joined["postures_inferred"],
        "builds": {k: v for k, v in builds.items() if k != "builds"},
        "captain_role": {"tables": joined["roles_note"], "unknown": unknown, **joined["role_check"]},
        "bootstrap": {"unit": "slate (sport, date, game type)", "draws": draws, "seed": seed,
                      "interval_pct": list(INTERVAL_PCT), "order": "slates sorted before sampling"},
        "labels": list(SHOWDOWN_LABELS),
        "overall": overall,
        "axes": attribute_cells(lineups, seed, draws, axes=SHOWDOWN_AXES),
    }


def render_showdown_attribution(report: Mapping[str, Any], results: Path) -> str:
    cov = report["coverage"]
    boot = report["bootstrap"]
    role = report["captain_role"]
    lines = [f"results_ledger attribute --showdown  ({report['population']})", f"  results: {results}",
             f"  coverage: {cov['with_lineup']} of {cov['population']} entries with a lineup in "
             f"{cov['contests']} contests, {cov['slates']} slates; {cov['no_standings']} without a "
             f"standings export, {cov['absent_from_standings']} absent from theirs, "
             f"{cov['incomplete_lineup']} incomplete; field {cov['field_lineups']} lineups "
             f"({cov['field_rank_unusable']} without a usable rank)",
             f"  captain role: {role['tables']}; unknown on {role['unknown']['ours']} of ours and "
             f"{role['unknown']['field']} field lineups; {role['recorded']} of ours from a record, "
             f"{role['disagree']} of the {role['recorded_and_table']} the tables also name disagree",
             f"  posture: {report['postures_inferred']['name_inference']} of our entries by "
             f"name_inference, {report['postures_inferred']['unresolved']} unresolved (the entry cap "
             "or the large_gpp default)",
             f"  build-time axes: {report['builds']['note']}",
             f"  intervals: 90%, {boot['unit']} bootstrap, {boot['draws']} draws, seed {boot['seed']}, "
             f"{boot['order']}; ours and the field paired on one draw per cell"]
    lines += [f"  label:   {label}" for label in report["labels"]]
    lines.append("")
    lines.extend(render_attribution_cell("overall", report["overall"]))
    for axis, block in report["axes"].items():
        lines.append("")
        lines.append(f"== {axis} ({block['level']}) ==")
        for value, cell in block["cells"].items():
            lines.extend(render_attribution_cell(value, cell))
    return "\n".join(lines) + "\n"


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

    p = sub.add_parser("attribute", help="our finishes by construction against the field (R498, Classic; "
                                         "--showdown and --rank, R500)")
    p.add_argument("--results", default=None, help=f"default data/reference/{RESULTS_NAME}")
    p.add_argument("--resolution", default=None,
                   help=f"default data/reference/{RESOLUTION_NAME} when present (R497's resolve)")
    p.add_argument("--json", action="store_true", help="print every cell and summary as JSON")
    which = p.add_mutually_exclusive_group()
    which.add_argument("--rank", action="store_true",
                       help="only the engine's own order against finish order, per contest (R500(a))")
    which.add_argument("--showdown", action="store_true",
                       help="our Showdown finishes by captain, split, duplication and thesis (R500(b))")

    args = ap.parse_args(argv)
    handler = {"ingest": cmd_ingest, "report": cmd_report, "resolve": cmd_resolve,
               "attribute": cmd_attribute}[args.cmd]
    try:
        return handler(args)
    except Refused as exc:
        print(f"REFUSED  {exc}", file=sys.stderr)
        return EXIT_REFUSED
    except UnicodeDecodeError as exc:
        print(f"REFUSED  not UTF-8 at byte {exc.start}; re-run ingest rather than re-saving the file",
              file=sys.stderr)
        return EXIT_REFUSED
    except OSError as exc:
        print(f"ERROR  {exc}", file=sys.stderr)
        return EXIT_IO


if __name__ == "__main__":
    raise SystemExit(main())
