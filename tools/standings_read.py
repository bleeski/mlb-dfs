#!/usr/bin/env python3
"""standings_read.py -- read a live DraftKings standings export for the late-swap decision (R472).

READ-ONLY and never fetching. Ben downloads the standings export himself (into
``data/standings/inbox/``, kept flat); this takes explicit file paths, reads them
in memory, and writes nothing: no fetch, no move, no delete, no extraction to disk.

What it prints, per contest: the field size, the points at the target rank (#1 by
default) and at #10 and #100, the cash line (``--paid-places``, else the post-slate
reference files, else UNKNOWN), the %Drafted of players whose games have started,
and, for each leader whose only open slot is a pitcher, the arm that open slot could
still add (named when the cell names him, otherwise the max-salary unstarted arm the
leader's remaining cap allows). Per entry of ours: rank, points, TimeRemaining (raw),
open slots, remaining-slot ceiling, and a verdict.

Verdicts (review proxies, never a prediction):
  live_for_target  points + the projected Ceiling of every UNSTARTED slot reaches the
                   target rank's points (current, plus the inferred open-pitcher
                   ceiling where one could be inferred)
  cash_viable      not live, but reaches the cash line
  out              reaches neither
  unknown          anything missing, ambiguous, mismatched or unparseable, with the
                   reason named. Unknown is never exempt from anything.

LABELS. Ceiling is a model prior from the parent frame, not a maximum; standings are
observed. Nothing here is a win rate, cash rate, ROI, edge or probability.
Rule (Ben, 2026-09-30 retro): never lower a cash_viable entry's projection for leverage.

UNVERIFIED FORMAT. 0 of the 516,804 archived standings rows carry a nonzero
TimeRemaining, so the LIVE format (its unit, and how a hidden or open slot appears in a
Lineup cell) has never been seen. Every test fixture is SYNTHETIC. The tool therefore
prints TimeRemaining raw, refuses by name a TimeRemaining that is not blank or a plain
non-negative number, uses it in NO verdict, reads a partial Lineup cell structurally
(the ten-slot contract minus what parsed), and refuses a leader whose name the salary
file cannot resolve. It does not guess.

Two doors. ``tools/late_swap.py --standings`` calls ``swap_context`` and
``partition_downgrades``; this file's own ``main`` is the standalone reader.

    python tools/standings_read.py --date 2026-10-05 --salary <DKSalaries.csv> \
        --standings data/standings/inbox/contest-standings-<id>.zip \
        [--paid-places 2200 | <id>=2200,...] [--run-id <run> | --projections <csv>] \
        [--target-rank 1] [--leaders 10] [--as-of 2026-10-05T23:30:00Z]
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import io
import json
import math
import os
import re
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

# Pinned before any import, like every entry point (CLAUDE.md determinism). Script
# only: importing this module never replaces the importer's process.
if (__name__ == "__main__" and os.environ.get("PYTHONHASHSEED") != "0"
        and sys.executable):
    try:
        os.execve(sys.executable, [sys.executable, *sys.argv],
                  {**os.environ, "PYTHONHASHSEED": "0"})
    except OSError:
        pass

REPO = Path(__file__).resolve().parents[1]
TOOLS_DIR = Path(__file__).resolve().parent
for _p in (str(REPO), str(TOOLS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from mlb_engine import contest_shapes  # noqa: E402
from mlb_engine.field import field_miner as fm  # noqa: E402

SALARY_CAP = fm.SALARY_CAP
# The ten Classic slots in DKEntries order (P1 P2 C 1B 2B 3B SS OF1 OF2 OF3).
SLOT_TYPES: Tuple[str, ...] = ("P", "P", "C", "1B", "2B", "3B", "SS", "OF", "OF", "OF")

LIVE_FOR_TARGET = "live_for_target"
CASH_VIABLE = "cash_viable"
OUT = "out"
UNKNOWN = "unknown"
VERDICTS = (LIVE_FOR_TARGET, CASH_VIABLE, OUT, UNKNOWN)

# An entry is exempt from the downgrade refusal only in a contest ranked for first
# place or for a top-heavy finish. A `cash` or `ticket_line` entry's target is the cut
# line, so "live for first" is not its question and its verdict never exempts it.
EXEMPT_OBJECTIVE_CLASSES = frozenset({"gpp", "wta"})

def objective_class(shape: str) -> str:
    """The objective class (`cash`, `gpp`, `wta`, `ticket_line`) of a contest shape."""
    return contest_shapes.OBJECTIVE_CLASS_BY_SHAPE.get(str(shape or "").strip().lower(), "")


MAX_ZIP_BYTES = 512 * 1024 * 1024        # extract_inbox_zips' own cap
STALE_FILE_WARN_MINUTES = 15
DEFAULT_LEADERS = 10
DRAFTED_TOP = 8

REVIEW_LABEL = (
    "review proxy, not a prediction: 'reaches' means the entry's current points plus "
    "the projected Ceiling of every slot whose game has not started would meet the "
    "target rank's points (current, plus the inferred open-pitcher ceiling where one "
    "could be inferred). Ceiling is a model prior from the parent frame, not a "
    "maximum; standings are observed. Never a win rate, cash rate, ROI, edge or "
    "probability.")
RULE_LINE = ("rule (Ben, 2026-09-30 retro): never lower a cash_viable entry's "
             "projection for leverage.")
UNVERIFIED_LINE = (
    "format note: the live TimeRemaining and hidden-slot format are UNVERIFIED "
    "(0 of 516,804 archived rows are nonzero); TimeRemaining is printed raw and "
    "feeds no verdict.")

_TIME_REMAINING = re.compile(r"^\d+(?:\.\d+)?$")


class StandingsFormatError(ValueError):
    """A standings file (or flag value) this tool will not read, named."""


class FrameUnavailable(Exception):
    """No projection frame could be read for the ceilings; verdicts are unknown."""


# ---------------------------------------------------------------------------
# reading the export
# ---------------------------------------------------------------------------

def infer_contest_id(*names: str) -> str:
    """A DK export's contest id from its name(s) (``contest-standings-<id>.zip``).

    The last run of SIX OR MORE digits in the first name that has one (a DK contest id
    is nine; a browser's duplicate suffix, ``... (1).csv``, is not), else the last digit
    run of the first name that has any, which is `extract_inbox_zips`' own rule. The
    caller still verifies the answer by entry membership where it can."""
    for name in names:
        long_runs = re.findall(r"\d{6,}", Path(str(name)).stem)
        if long_runs:
            return long_runs[-1]
    for name in names:
        runs = re.findall(r"\d+", Path(str(name)).stem)
        if runs:
            return runs[-1]
    return ""


def read_standings(path, contest_id: Optional[str] = None, *,
                   allow_unknown_id: bool = False) -> Dict[str, Any]:
    """Read one standings CSV or zip, in memory. Raises ``FileNotFoundError`` for a
    path that is not a file and ``StandingsFormatError`` (named) for everything the
    tool will not read. The zip is never extracted to the inbox.

    ``allow_unknown_id`` lets a file whose name carries no digits through with
    ``contest_id == ""``, for a caller that identifies the contest by entry
    membership (`swap_context`)."""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"missing input: {p} is not a file (the tool takes "
                                f"explicit paths: no directory, no glob, no fetch)")
    suffix = p.suffix.lower()
    if suffix not in (".csv", ".zip"):
        raise StandingsFormatError(
            f"{p.name}: a standings export is a .csv or a .zip, not {suffix or 'a file with no extension'}")
    size = p.stat().st_size
    if size > MAX_ZIP_BYTES:
        raise StandingsFormatError(f"{p.name}: {size} bytes is above the "
                                   f"{MAX_ZIP_BYTES}-byte cap")
    raw = p.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    member_name = ""
    if suffix == ".zip":
        try:
            zf = zipfile.ZipFile(io.BytesIO(raw))
        except zipfile.BadZipFile as exc:
            raise StandingsFormatError(f"{p.name}: not a readable zip ({exc})") from exc
        members = [m for m in zf.infolist()
                   if not m.is_dir() and m.filename.lower().endswith(".csv")]
        if len(members) != 1:
            raise StandingsFormatError(
                f"{p.name}: holds {len(members)} CSV member(s); a DK export zip holds "
                f"exactly one standings CSV")
        member = members[0]
        if member.file_size > MAX_ZIP_BYTES:
            raise StandingsFormatError(f"{p.name}: the CSV member expands beyond "
                                       f"{MAX_ZIP_BYTES} bytes")
        data = zf.read(member)
        if len(data) != member.file_size:
            raise StandingsFormatError(f"{p.name}: the CSV member's size does not "
                                       f"match its header (a corrupt zip)")
        member_name = Path(member.filename.replace("\\", "/")).name
    else:
        data = raw
    cid = (str(contest_id or "").strip()
           or infer_contest_id(*([p.name, member_name] if member_name else [p.name])))
    if not cid and not allow_unknown_id:
        raise StandingsFormatError(
            f"{p.name}: no contest id in the file name (DK names an export "
            f"contest-standings-<id>.csv or .zip); rename it, or pass --contest-id to "
            f"tools/standings_read.py")
    if suffix == ".csv":
        parsed = _parse(str(p), p.name)
    else:
        with tempfile.TemporaryDirectory(prefix="standings_read_") as tmp:
            target = Path(tmp) / "standings.csv"
            target.write_bytes(data)
            parsed = _parse(str(target), p.name)
    if parsed["contest_type"] != "classic":
        raise StandingsFormatError(
            f"{p.name}: a {parsed['contest_type']} export; this reader is Classic only "
            f"(Showdown ships review-grade and has no late swap)")
    entries = parsed["entries"]
    for position, entry in enumerate(entries, start=1):
        cell = entry.get("time_remaining", "")
        if cell != "" and not _TIME_REMAINING.match(cell):
            raise StandingsFormatError(
                f"{p.name}: TimeRemaining {cell!r} (entry {entry['entry_id']}, entry "
                f"row {position}) is not blank or a plain non-negative number. The "
                f"live format is unverified (0 of 516,804 archived rows are nonzero), "
                f"so this tool will not guess what it means")
    by_entry: Dict[str, List[Dict[str, Any]]] = {}
    for entry in entries:
        by_entry.setdefault(str(entry["entry_id"]), []).append(entry)
    age = max(0.0, (dt.datetime.now(dt.timezone.utc).timestamp() - p.stat().st_mtime) / 60.0)
    return {
        "path": str(p), "name": p.name, "sha256": sha, "contest_id": cid,
        "contest_type": parsed["contest_type"], "entries": entries,
        "player_table": parsed["player_table"], "entries_by_id": by_entry,
        "age_minutes": age,
    }


def _parse(path: str, label: str) -> Dict[str, Any]:
    try:
        return fm.parse_standings_export(path, with_time_remaining=True)
    except ValueError as exc:
        raise StandingsFormatError(f"{label}: {exc}") from exc


def _sorted_points(entries: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Entries with parseable Points, by points descending, ties by the export's rank
    then entry id, so 'the rank-k row' is one definition."""
    def _rank(entry):
        try:
            return int(str(entry.get("rank") or "").strip())
        except ValueError:
            return 10 ** 9
    return sorted((dict(e) for e in entries if e.get("points") is not None),
                  key=lambda e: (-float(e["points"]), _rank(e), str(e["entry_id"])))


def points_at_rank(entries: Sequence[Mapping[str, Any]], k: int) -> Optional[float]:
    """The k-th highest Points in the file, ties kept; None when the field is shorter."""
    ordered = _sorted_points(entries)
    if k < 1 or k > len(ordered):
        return None
    return float(ordered[k - 1]["points"])


# ---------------------------------------------------------------------------
# paid places and the cash line
# ---------------------------------------------------------------------------

def parse_paid_places(value: Optional[str]) -> Dict[str, int]:
    """``N`` (one standings file) or ``<contest_id>=N,...`` -> {contest id or "*": N}."""
    out: Dict[str, int] = {}
    for item in str(value or "").split(","):
        item = item.strip()
        if not item:
            continue
        key, sep, number = item.partition("=")
        if not sep:
            key, number = "*", item
        try:
            places = int(number.strip())
        except ValueError:
            raise StandingsFormatError(
                f"--paid-places {item!r} is not <contest_id>=<integer> or an integer"
            ) from None
        if places < 1:
            raise StandingsFormatError(
                f"--paid-places {item!r}: paid places must be a positive integer")
        key = key.strip() or "*"
        if key in out:
            raise StandingsFormatError(
                f"--paid-places names {'the bare number' if key == '*' else 'contest ' + key} "
                f"twice")
        out[key] = places
    return out


def check_paid_places_scope(given: Mapping[str, int], n_files: int) -> None:
    """A bare ``N`` is one contest's number: with several standings files it would put
    the same cash line on every one, so it is refused by name."""
    if "*" in given and n_files != 1:
        raise StandingsFormatError(
            f"a bare --paid-places {given['*']} applies to exactly one --standings file "
            f"(got {n_files}); write <contest_id>=N,<contest_id>=N")


def resolve_paid_places(contest_id: str, given: Mapping[str, int],
                        root: Path) -> Tuple[Optional[int], str]:
    """(paid_places, source). The operator's number first; then the post-slate
    reference lookup `outcome_review.resolve_paid_places`, which answers only a
    contest already in the two reference files; else (None, why)."""
    if contest_id in given:
        return int(given[contest_id]), "--paid-places"
    if "*" in given:
        return int(given["*"]), "--paid-places"
    try:
        import outcome_review  # noqa: PLC0415 - a sibling tool, loaded on the one path that reads it
        places, source_file, note = outcome_review.resolve_paid_places(Path(root), contest_id)
    except Exception as exc:  # noqa: BLE001 - an unreadable reference is "unknown", with the reason
        return None, f"reference lookup failed ({type(exc).__name__}: {exc})"
    if places is not None:
        return int(places), source_file
    return None, f"unknown: not in the reference files ({note}); pass --paid-places"


# ---------------------------------------------------------------------------
# the slate: names, salaries, positions, lock state
# ---------------------------------------------------------------------------

class Slate:
    """Salary records plus the swap's own lock clock.

    ``status_by_player_id`` is the late-swap status map (``PlayerLineupStatus``):
    ``is_open`` is exactly its ``is_locked`` negated at ``as_of``, the definition the
    swap's V gates use. A player the map does not hold is LOCKED by absence (the
    ``treat_as_locked`` rule); ``is_open`` returns None for him so the report can name
    him.
    """

    def __init__(self, players: Mapping[str, Any], status_by_player_id: Mapping[str, Any],
                 as_of: dt.datetime):
        if as_of.tzinfo is None:
            raise StandingsFormatError("the lock clock needs a timezone-aware instant")
        self.players = {str(pid): rec for pid, rec in players.items()}
        self.status = {str(pid): st for pid, st in status_by_player_id.items()}
        self.as_of = as_of
        self.by_norm: Dict[str, List[str]] = {}
        for pid in sorted(self.players):
            self.by_norm.setdefault(fm.normalize_name(self.players[pid].name), []).append(pid)

    def is_open(self, pid: str) -> Optional[bool]:
        status = self.status.get(str(pid))
        if status is None:
            return None
        return not status.is_locked(self.as_of)

    def name(self, pid: str) -> str:
        rec = self.players.get(str(pid))
        return rec.name if rec is not None else ""

    def salary(self, pid: str) -> Optional[float]:
        rec = self.players.get(str(pid))
        return float(rec.salary) if rec is not None else None

    def is_pitcher(self, pid: str) -> bool:
        rec = self.players.get(str(pid))
        return rec is not None and "P" in tuple(rec.positions or ())


# ---------------------------------------------------------------------------
# ceilings: the parent run's frame, one hop
# ---------------------------------------------------------------------------

def _ceiling_value(cell: Any) -> Optional[float]:
    try:
        value = float(cell)
    except (TypeError, ValueError):
        return None
    if math.isnan(value) or math.isinf(value) or value < 0:
        return None
    return value


def load_frame(path) -> Dict[str, Optional[float]]:
    """{Player_ID: Ceiling or None} from a projections CSV (None: NaN, negative, blank)."""
    p = Path(path)
    try:
        with p.open(encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            fields = set(reader.fieldnames or [])
            if not {"Player_ID", "Ceiling"} <= fields:
                raise FrameUnavailable(f"{p} has no Player_ID and Ceiling columns")
            return {str(row["Player_ID"]).strip(): _ceiling_value(row.get("Ceiling"))
                    for row in reader if str(row.get("Player_ID") or "").strip()}
    except (OSError, ValueError, csv.Error) as exc:
        raise FrameUnavailable(f"{p} cannot be read ({type(exc).__name__}: {exc})") from exc


def frame_from_dataframe(frame) -> Dict[str, Optional[float]]:
    """The in-hand swap frame as the same {Player_ID: Ceiling} mapping."""
    return {str(pid): _ceiling_value(ceiling)
            for pid, ceiling in zip(frame["Player_ID"], frame["Ceiling"])}


def frame_for_run(runs_root, run_id: str) -> Tuple[Dict[str, Optional[float]], Dict[str, str]]:
    """ONE hop: ``runs/<id>/final/projections.csv`` and the run's manifest ``mode``.

    A run whose mode is ``late_swap`` wrote the swap's UNENRICHED frame (R428), so its
    ceilings are APPG-derived; the info says so. Multi-hop to the root build is not
    walked (Session 115 makes swap frames reuse the parent's enrichment)."""
    run_dir = Path(runs_root) / str(run_id)
    path = run_dir / "final" / "projections.csv"
    if not path.is_file():
        raise FrameUnavailable(f"no {path} on this host (runs/ is gitignored: the frame "
                               f"exists only where the run was built)")
    mode = ""
    try:
        mode = str(json.loads((run_dir / "manifest.json").read_text(encoding="utf-8")).get("mode") or "")
    except (OSError, ValueError):
        pass
    info = {"run_id": str(run_id), "mode": mode, "path": str(path),
            "note": ("unenriched swap frame: its ceilings are APPG-derived (R428)"
                     if mode == "late_swap" else "")}
    return load_frame(path), info


class Ceilings:
    """Frames in priority order; each lookup names which one answered."""

    def __init__(self, frames: Sequence[Tuple[str, Mapping[str, Optional[float]]]]):
        self.frames = list(frames)

    def get(self, pid: str) -> Tuple[Optional[float], str]:
        for label, frame in self.frames:
            if str(pid) in frame and frame[str(pid)] is not None:
                return float(frame[str(pid)]), label
        return None, ""


# ---------------------------------------------------------------------------
# an entry's reach and its verdict
# ---------------------------------------------------------------------------

def reach_for_roster(roster_ids: Sequence[str], points: float, slate: Slate,
                     ceilings: Ceilings) -> Dict[str, Any]:
    """points + the Ceiling of every slot whose player has not started.

    Started players add nothing (their points so far are in ``points``): an
    under-count. A player absent from the status map is locked and named."""
    open_slots: List[str] = []
    absent: List[str] = []
    problems: List[str] = []
    sources: Dict[str, int] = {}
    remaining = 0.0
    for index, pid in enumerate(roster_ids):
        state = slate.is_open(pid)
        if state is None:
            absent.append(str(pid))
            continue
        if not state:
            continue
        open_slots.append(SLOT_TYPES[index] if index < len(SLOT_TYPES) else "?")
        value, label = ceilings.get(pid)
        if value is None:
            problems.append(f"no usable Ceiling for open-slot player {pid} "
                            f"({slate.name(pid) or 'name unknown'})")
            continue
        remaining += value
        sources[label] = sources.get(label, 0) + 1
    return {"open_slots": open_slots, "locked_by_absence": absent, "problems": problems,
            "remaining_ceiling": remaining, "reach": float(points) + remaining,
            "ceiling_source": sources}


def _names_match(row: Mapping[str, Any], roster_ids: Sequence[str], slate: Slate) -> Optional[str]:
    """None when the standings Lineup is exactly this roster, else the reason."""
    if not row.get("lineup_complete"):
        return "the standings Lineup cell for this entry is partial"
    names = [slate.name(pid) for pid in roster_ids]
    if any(not n for n in names):
        return "a roster player is not in the salary file"
    expected = tuple(sorted(fm.normalize_name(n) for n in names))
    if tuple(row.get("players_norm") or ()) != expected:
        return ("the standings Lineup differs from the roster being refined (edited "
                "since, or another contest's export)")
    return None


def entry_verdict(seat: Mapping[str, Any], standing: Mapping[str, Any], slate: Slate,
                  ceilings: Ceilings, target: Mapping[str, Any],
                  cash: Mapping[str, Any]) -> Dict[str, Any]:
    """One entry's record; the verdict is the first of the four that its inputs allow."""
    entry_id = str(seat["entry_id"])
    out: Dict[str, Any] = {
        "entry_id": entry_id, "contest_id": str(seat.get("contest_id") or ""),
        "verdict": UNKNOWN, "reasons": [], "rank": None, "points": None,
        "time_remaining": None, "open_slots": [], "locked_by_absence": [],
        "remaining_ceiling": None, "reach": None, "target_points": target.get("T"),
        "cash_line": cash.get("line"), "ceiling_source": {},
    }
    reasons: List[str] = out["reasons"]
    roster = seat.get("roster_ids")
    if not roster or len(roster) != len(SLOT_TYPES):
        reasons.append(seat.get("problem") or "the roster is not ten players")
        return out
    rows = standing["entries_by_id"].get(entry_id, [])
    if not rows:
        reasons.append(f"entry {entry_id} is not in {standing['name']}")
        return out
    if len(rows) > 1:
        reasons.append(f"entry {entry_id} appears {len(rows)} times in {standing['name']}")
        return out
    row = rows[0]
    out["rank"] = row.get("rank")
    out["points"] = row.get("points")
    out["time_remaining"] = row.get("time_remaining")
    if row.get("points") is None:
        reasons.append("the entry's Points cell is not a number")
    mismatch = _names_match(row, roster, slate)
    if mismatch:
        reasons.append(mismatch)
    if reasons:
        return out
    reach = reach_for_roster(roster, float(row["points"]), slate, ceilings)
    out["open_slots"] = reach["open_slots"]
    out["locked_by_absence"] = reach["locked_by_absence"]
    out["remaining_ceiling"] = reach["remaining_ceiling"]
    out["reach"] = reach["reach"]
    out["ceiling_source"] = reach["ceiling_source"]
    reasons.extend(reach["problems"])
    if target.get("T") is None:
        reasons.append(target.get("why") or "the target rank's points are unknown")
    if reasons:
        return out
    # An entry at or above the target is "live" against itself and trivially: it is
    # defending, not chasing, and `partition_downgrades` never exempts it.
    p_k = target.get("p_k")
    out["at_or_above_target"] = float(row["points"]) >= float(p_k if p_k is not None else target["T"])
    if out["reach"] >= float(target["T"]):
        out["verdict"] = LIVE_FOR_TARGET
    elif cash.get("line") is None:
        reasons.append("cash line unknown (" + str(cash.get("source") or "no paid places")
                       + "); not live for the target, so cash_viable and out cannot be told apart")
    elif out["reach"] >= float(cash["line"]):
        out["verdict"] = CASH_VIABLE
    else:
        out["verdict"] = OUT
    return out


# ---------------------------------------------------------------------------
# leaders: the hidden-pitcher inference, and %Drafted of started players
# ---------------------------------------------------------------------------

def _lineup_pids(lineup: Sequence[Tuple[str, str]], slate: Slate
                 ) -> Tuple[List[Tuple[str, str]], Optional[str]]:
    """[(slot, pid)] for a parsed Lineup cell, or (partial, reason) when a name does
    not resolve to exactly one salary row."""
    resolved: List[Tuple[str, str]] = []
    for slot, name in lineup:
        pids = slate.by_norm.get(fm.normalize_name(name), [])
        if len(pids) != 1:
            why = "is not in the salary file" if not pids else "is ambiguous in the salary file"
            return resolved, f"{name!r} {why}"
        resolved.append((slot, pids[0]))
    return resolved, None


def hidden_pitcher_inference(row: Mapping[str, Any], slate: Slate,
                             ceilings: Ceilings) -> Dict[str, Any]:
    """What a leader's open slot could still add, when that slot is the one pitcher.

    Open slots are the unstarted players the Lineup cell names plus the slots a partial
    cell leaves out (the ten-slot contract minus what parsed). Exactly one open slot,
    and it is P: NAMED (the cell holds him) or HIDDEN (the cell does not), in which
    case the arm is the max-salary unstarted pitcher his remaining cap allows (ties by
    higher Ceiling, then the lower Player_ID). Anything else is not inferred, with the
    reason. A review proxy: Ceiling is a model prior."""
    base = {"entry_id": str(row["entry_id"]), "rank": row.get("rank"),
            "points": row.get("points"), "status": "not_inferred", "reason": "",
            "arm": None, "A": None}
    resolved, problem = _lineup_pids(row.get("lineup") or [], slate)
    if problem:
        base["reason"] = f"leader skipped: {problem}"
        return base
    expected = dict(fm.EXPECTED_SLOT_COUNTS)
    for slot, _ in resolved:
        expected[slot] = expected.get(slot, 0) - 1
    if any(count < 0 for count in expected.values()):
        base["reason"] = "leader skipped: the Lineup cell holds more slots of a type than the contract"
        return base
    hidden = [slot for slot, count in sorted(expected.items()) for _ in range(count)]
    open_named = [(slot, pid) for slot, pid in resolved if slate.is_open(pid)]
    open_types = [slot for slot, _ in open_named] + hidden
    if not open_types:
        base.update(status="no_open_slots", A=0.0, reason="no unstarted slot")
        return base
    if open_types != ["P"]:
        base["reason"] = f"open slots {open_types}: only a lone open pitcher is inferred"
        return base
    if open_named:
        pid = open_named[0][1]
        value, label = ceilings.get(pid)
        if value is None:
            base["reason"] = f"named open pitcher {slate.name(pid)} has no usable Ceiling"
            return base
        base.update(status="named", A=value,
                    arm={"player_id": pid, "name": slate.name(pid),
                         "salary": slate.salary(pid), "ceiling": value, "source": label})
        return base
    held = {pid for _, pid in resolved}
    cap_left = SALARY_CAP - sum(slate.salary(pid) or 0.0 for pid in held)
    candidates = []
    for pid in sorted(slate.players):
        if pid in held or not slate.is_pitcher(pid) or slate.is_open(pid) is not True:
            continue
        salary = slate.salary(pid)
        value, label = ceilings.get(pid)
        if salary is None or salary > cap_left or value is None:
            continue
        candidates.append((salary, value, pid, label))
    if not candidates:
        base["reason"] = f"hidden pitcher slot, ${cap_left:,.0f} left: no unstarted arm with a Ceiling fits"
        return base
    salary, value, pid, label = sorted(
        candidates, key=lambda c: (-c[0], -c[1], int(c[2]) if c[2].isdigit() else 0, c[2]))[0]
    base.update(status="inferred", A=value, cap_left=cap_left,
                arm={"player_id": pid, "name": slate.name(pid), "salary": salary,
                     "ceiling": value, "source": label},
                reason=f"hidden pitcher slot; max-salary unstarted arm ${cap_left:,.0f} allows")
    return base


def started_drafted(standing: Mapping[str, Any], slate: Slate, top: int = DRAFTED_TOP
                    ) -> Dict[str, Any]:
    """The field's %Drafted for players whose games have started, highest first."""
    table = fm.own_by_player_norm(standing["player_table"])
    rows: List[Tuple[float, str]] = []
    ambiguous = unmatched = 0
    for norm, pct in sorted(table.items()):
        pids = slate.by_norm.get(norm, [])
        if not pids:
            unmatched += 1
            continue
        if len(pids) > 1:
            ambiguous += 1
            continue
        if slate.is_open(pids[0]) is False:
            rows.append((float(pct), slate.name(pids[0])))
    rows.sort(key=lambda r: (-r[0], r[1]))
    return {"players": [{"name": n, "pct_drafted": p} for p, n in rows[:top]],
            "ambiguous_names": ambiguous, "unmatched_names": unmatched}


# ---------------------------------------------------------------------------
# the contest block and the whole report
# ---------------------------------------------------------------------------

def contest_block(standing: Mapping[str, Any], slate: Slate, ceilings: Ceilings,
                  target_rank: int, paid_places: Optional[int], paid_source: str,
                  leaders_n: int) -> Dict[str, Any]:
    ordered = _sorted_points(standing["entries"])
    target_row = ordered[target_rank - 1] if 1 <= target_rank <= len(ordered) else None
    target: Dict[str, Any] = {"rank": target_rank, "p_k": None, "A": None, "T": None,
                              "why": f"the field has {len(ordered)} scored row(s), fewer than "
                                     f"target rank {target_rank}", "inference": None}
    if target_row is not None:
        inference = hidden_pitcher_inference(target_row, slate, ceilings)
        p_k = float(target_row["points"])
        arm = inference["A"] if inference["status"] in ("named", "inferred") else 0.0
        target.update(p_k=p_k, A=inference["A"] if arm else None, T=p_k + float(arm or 0.0),
                      why="", inference=inference, entry_id=str(target_row["entry_id"]))
    cash: Dict[str, Any] = {"paid_places": paid_places, "source": paid_source, "line": None}
    if paid_places is not None:
        if paid_places > len(ordered):
            cash["source"] = (f"paid places {paid_places} is above the {len(ordered)} scored "
                              f"row(s) in the file ({paid_source})")
        else:
            cash["line"] = float(ordered[paid_places - 1]["points"])
    return {
        "contest_id": standing["contest_id"], "file": standing["name"],
        "contest_id_source": standing.get("contest_id_source", "file name"),
        "sha256": standing["sha256"], "age_minutes": standing["age_minutes"],
        "field_size": len(standing["entries"]), "scored_rows": len(ordered),
        "points_at": {str(k): (float(ordered[k - 1]["points"]) if k <= len(ordered) else None)
                      for k in (1, 10, 100)},
        "target": target, "cash": cash,
        "leaders": [hidden_pitcher_inference(row, slate, ceilings)
                    for row in ordered[:max(0, leaders_n)]],
        "started_drafted": started_drafted(standing, slate),
    }


def build_report(*, standings: Mapping[str, Mapping[str, Any]], seats: Sequence[Mapping[str, Any]],
                 slate: Slate, ceilings: Ceilings, target_rank: int,
                 paid_places: Mapping[str, int], leaders_n: int, root: Path,
                 frame_note: str = "") -> Dict[str, Any]:
    contests: Dict[str, Any] = {}
    verdicts: Dict[str, Any] = {}
    for cid in sorted(standings):
        places, source = resolve_paid_places(cid, paid_places, root)
        contests[cid] = contest_block(standings[cid], slate, ceilings, target_rank,
                                      places, source, leaders_n)
    for seat in seats:
        cid = str(seat.get("contest_id") or "")
        if cid not in standings:
            verdicts[str(seat["entry_id"])] = {
                "entry_id": str(seat["entry_id"]), "contest_id": cid, "verdict": UNKNOWN,
                "reasons": [f"no standings file was given for contest {cid or '?'}"],
                "points": None, "reach": None, "target_points": None}
            continue
        block = contests[cid]
        verdicts[str(seat["entry_id"])] = entry_verdict(
            seat, standings[cid], slate, ceilings, block["target"], block["cash"])
    return {"contests": contests, "verdicts": verdicts, "label": REVIEW_LABEL,
            "rule": RULE_LINE, "frame": frame_note, "target_rank": target_rank,
            # What `partition_downgrades` re-reads for the CHOSEN lineup; never printed
            # or recorded (`render` and `metadata_for_run` pick their own fields).
            "slate": slate, "ceilings": ceilings,
            "standings_files": {cid: {"name": s["name"], "sha256": s["sha256"],
                                      "contest_id_source": s.get("contest_id_source", "file name")}
                                for cid, s in standings.items()}}


def _num(value: Optional[float]) -> str:
    return "n/a" if value is None else f"{float(value):.2f}"


def render(report: Mapping[str, Any]) -> List[str]:
    lines = [f"standings read (R472) -- {REVIEW_LABEL}", RULE_LINE, UNVERIFIED_LINE]
    if report.get("frame"):
        lines.append(f"ceiling frame: {report['frame']}")
    for cid, block in sorted(report["contests"].items()):
        at = block["points_at"]
        target = block["target"]
        lines.append(
            f"contest {cid} ({block['file']}, sha256 {block['sha256'][:12]}, "
            f"{block['age_minutes']:.0f} min old by mtime): field {block['field_size']}, "
            f"#1 {_num(at['1'])}, #10 {_num(at['10'])}, #100 {_num(at['100'])}"
            + ("" if block["contest_id_source"] == "file name"
               else f" [contest id from {block['contest_id_source']}]"))
        if block["age_minutes"] > STALE_FILE_WARN_MINUTES:
            lines.append(f"  WARN the file is older than {STALE_FILE_WARN_MINUTES} minutes by "
                         f"mtime: points may have moved (an understated total can only "
                         f"remove an exemption)")
        if target["T"] is None:
            lines.append(f"  target rank {target['rank']}: unknown ({target['why']})")
        else:
            arm = f" + inferred open-pitcher ceiling {_num(target['A'])}" if target.get("A") else ""
            lines.append(f"  target rank {target['rank']}: {_num(target['p_k'])}{arm} -> "
                         f"T {_num(target['T'])} (entry {target.get('entry_id')})")
        cash = block["cash"]
        if cash["line"] is None:
            lines.append(f"  cash line: unknown ({cash['source']})")
        else:
            lines.append(f"  cash line: {_num(cash['line'])} = rank {cash['paid_places']} "
                         f"(paid places from {cash['source']})")
        for leader in block["leaders"]:
            tail = ""
            if leader["arm"]:
                arm = leader["arm"]
                tail = (f" arm {arm['name']} ${arm['salary']:,.0f} ceiling {_num(arm['ceiling'])}"
                        f" -> {_num(float(leader['points']) + arm['ceiling'])}")
            lines.append(f"  leader #{leader['rank']} entry {leader['entry_id']} "
                         f"{_num(leader['points'])}: {leader['status']}"
                         + (f" ({leader['reason']})" if leader["reason"] else "") + tail)
        drafted = block["started_drafted"]
        if drafted["players"]:
            lines.append("  %Drafted of started players: " + ", ".join(
                f"{p['name']} {p['pct_drafted']:.1f}%" for p in drafted["players"])
                + (f" [{drafted['ambiguous_names']} ambiguous, {drafted['unmatched_names']} "
                   f"unmatched name(s) skipped]" if drafted["ambiguous_names"]
                   or drafted["unmatched_names"] else ""))
        else:
            lines.append("  %Drafted of started players: none started or none matched")
    lines.append("entries:")
    for entry_id, v in sorted(report["verdicts"].items()):
        if v["verdict"] == UNKNOWN:
            lines.append(f"  {entry_id} [{v.get('contest_id')}] unknown: "
                         + "; ".join(v["reasons"]))
            continue
        lines.append(
            f"  {entry_id} [{v['contest_id']}] rank {v['rank']} points {_num(v['points'])} "
            f"time_remaining {v['time_remaining']!r} open {','.join(v['open_slots']) or 'none'} "
            f"remaining ceiling {_num(v['remaining_ceiling'])} reach {_num(v['reach'])} "
            f"vs T {_num(v['target_points'])} / cash line {_num(v['cash_line'])} -> {v['verdict']}"
            + (" (at or above the target: never exempt from a downgrade refusal)"
               if v.get("at_or_above_target") else "")
            + (f" (locked by absence from the status map: {', '.join(v['locked_by_absence'])})"
               if v["locked_by_absence"] else ""))
    return lines


# ---------------------------------------------------------------------------
# the late-swap door
# ---------------------------------------------------------------------------

def swap_context(*, standings_paths: Sequence[str], paid_places: Optional[str],
                 target_rank: int, seats: Sequence[Mapping[str, Any]], slate: Slate,
                 parent_frame: Optional[Tuple[Mapping[str, Optional[float]], Mapping[str, str]]],
                 swap_frame: Mapping[str, Optional[float]], root: Path,
                 leaders_n: int = DEFAULT_LEADERS) -> Dict[str, Any]:
    """Everything ``late_swap`` needs, or ``StandingsFormatError`` (named) when the
    standings cannot be used, which the caller turns into 'no entry is exempt'.

    ``seats`` are the parent file's authorized entries (entry id, contest id, ten
    Player_IDs in slot order). ``parent_frame`` is the one-hop parent run's frame (None
    when no run matches this file's bytes); the in-hand swap frame supplies only the
    players the parent never carried."""
    given = parse_paid_places(paid_places)
    check_paid_places_scope(given, len(standings_paths))
    seat_contest = {str(s["entry_id"]): str(s.get("contest_id") or "") for s in seats}
    ours = set(seat_contest.values()) - {""}
    standings: Dict[str, Dict[str, Any]] = {}
    for path in standings_paths:
        item = read_standings(path, allow_unknown_id=True)
        if item["contest_id"] not in ours:
            # The name's id matches no contest of ours (a browser's duplicate suffix, a
            # renamed file): the join is by EntryId, so take the one contest whose
            # entries the file holds, and say so.
            held = {seat_contest[e] for e in item["entries_by_id"] if e in seat_contest} - {""}
            if len(held) == 1:
                item["contest_id_source"] = (f"entry membership (the file name's id "
                                             f"{item['contest_id'] or 'none'!r} matches no contest "
                                             f"of ours)")
                item["contest_id"] = next(iter(held))
        if not item["contest_id"]:
            raise StandingsFormatError(
                f"{item['name']}: no contest id in the file name and no entry of ours in it")
        if item["contest_id"] in standings:
            raise StandingsFormatError(
                f"two standings files for contest {item['contest_id']}: "
                f"{standings[item['contest_id']]['name']} and {item['name']}")
        standings[item["contest_id"]] = item
    frames: List[Tuple[str, Mapping[str, Optional[float]]]] = []
    note = ""
    if parent_frame is not None:
        frames.append(("parent", parent_frame[0]))
        info = parent_frame[1]
        note = (f"parent run {info.get('run_id')} (mode {info.get('mode') or 'unknown'})"
                + (f"; {info['note']}" if info.get("note") else ""))
    else:
        note = "no parent run matches this file's bytes; the in-hand swap frame is the only source"
    frames.append(("swap_frame", swap_frame))
    report = build_report(standings=standings, seats=seats, slate=slate,
                          ceilings=Ceilings(frames), target_rank=target_rank,
                          paid_places=given, leaders_n=leaders_n, root=root, frame_note=note)
    return report


def metadata_for_run(report: Mapping[str, Any]) -> Dict[str, Any]:
    """What the swap run's manifest records about the standings it read."""
    return {
        "label": "review proxy; observed standings; never a probability",
        "target_rank": report["target_rank"], "frame": report["frame"],
        "files": report["standings_files"],
        "verdicts": {eid: {k: v.get(k) for k in ("verdict", "points", "reach", "target_points",
                                                  "cash_line", "reasons")}
                     for eid, v in sorted(report["verdicts"].items())},
    }


def _entry_token(line: str) -> str:
    return str(line).split(" ", 1)[0]


def partition_downgrades(downgraded: Sequence[str], report: Mapping[str, Any],
                         class_by_entry: Mapping[str, str],
                         after_rosters: Mapping[str, Sequence[str]]
                         ) -> Tuple[List[str], List[str], Dict[str, Dict[str, Any]]]:
    """Split the F16 downgrade lines into (refusable, exempt, detail).

    A line is exempt only when its entry's incumbent verdict is live_for_target, the
    entry is BEHIND the target (an entry at or above it is defending a lead, not
    chasing, and is trivially live against itself), its contest's objective class is
    gpp or wta, AND the chosen lineup's own reach still meets the target (a swap must
    not kill the liveness it was exempted for). A line whose first token is not an
    entry id in the verdict table fails closed. The refusal is S; every V check ran
    before this is reached."""
    verdicts = report["verdicts"]
    slate = report["slate"]
    ceilings = report["ceilings"]
    refusable: List[str] = []
    exempt: List[str] = []
    detail: Dict[str, Dict[str, Any]] = {}
    for line in downgraded:
        entry_id = _entry_token(line)
        v = verdicts.get(entry_id)
        if (v is None or v["verdict"] != LIVE_FOR_TARGET
                or class_by_entry.get(entry_id) not in EXEMPT_OBJECTIVE_CLASSES
                or v.get("target_points") is None or v.get("points") is None
                or v.get("at_or_above_target") is not False):
            refusable.append(line)
            continue
        chosen = after_rosters.get(entry_id) or []
        if len(chosen) != len(SLOT_TYPES):
            refusable.append(line)
            continue
        after = reach_for_roster(chosen, float(v["points"]), slate, ceilings)
        if after["problems"] or after["reach"] < float(v["target_points"]):
            refusable.append(line)
            continue
        exempt.append(line)
        detail[entry_id] = {"verdict": v["verdict"], "points": v["points"],
                            "reach": v["reach"], "chosen_reach": after["reach"],
                            "target_points": v["target_points"],
                            "objective_class": class_by_entry.get(entry_id)}
    return refusable, exempt, detail


# ---------------------------------------------------------------------------
# the standalone door
# ---------------------------------------------------------------------------

def roster_from_lineup(lineup: Sequence[Tuple[str, str]], slate: Slate
                       ) -> Tuple[Optional[List[str]], str]:
    """Ten Player_IDs in slot order from a complete Lineup cell, or (None, why)."""
    resolved, problem = _lineup_pids(lineup, slate)
    if problem:
        return None, f"cannot build the roster: {problem}"
    by_slot: Dict[str, List[str]] = {}
    for slot, pid in resolved:
        by_slot.setdefault(slot, []).append(pid)
    roster: List[str] = []
    for slot in SLOT_TYPES:
        queue = by_slot.get(slot) or []
        if not queue:
            return None, f"the Lineup cell is partial (no {slot})"
        roster.append(queue.pop(0))
    return roster, ""


def delivery_run_ids(root: Path, date: str, contest_id: str) -> List[str]:
    """The distinct run ids of the contest's non-superseded delivery records (the same
    filter as ``field_miner.harvest_own_entry_ids``; a parity test pins them)."""
    from mlb_engine.entries.delivery_record import read_records  # noqa: PLC0415
    found = set()
    for record in read_records(root=Path(root), date=str(date)):
        if record.get("kind") != "delivery":
            continue
        row = record.get("manifest_row") or {}
        if row.get("status") == "superseded":
            continue
        if contest_id and contest_id not in {str(c) for c in (row.get("contest_ids") or [])}:
            continue
        if row.get("run_id"):
            found.add(str(row["run_id"]))
    return sorted(found)


def standalone_seats(standing: Mapping[str, Any], own_ids: Sequence[str], slate: Slate,
                     contest_id: str) -> List[Dict[str, Any]]:
    seats = []
    for entry_id in own_ids:
        rows = standing["entries_by_id"].get(str(entry_id), [])
        seat: Dict[str, Any] = {"entry_id": str(entry_id), "contest_id": contest_id,
                                "roster_ids": None, "problem": ""}
        if len(rows) == 1:
            seat["roster_ids"], seat["problem"] = roster_from_lineup(rows[0]["lineup"], slate)
        elif not rows:
            seat["problem"] = f"entry {entry_id} is not in {standing['name']}"
        else:
            seat["problem"] = f"entry {entry_id} appears {len(rows)} times in {standing['name']}"
        seats.append(seat)
    return seats


def _parse_as_of(value: Optional[str]) -> dt.datetime:
    if not value:
        return dt.datetime.now(dt.timezone.utc)
    try:
        parsed = dt.datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise StandingsFormatError(f"--as-of {value!r} is not an ISO instant ({exc})") from exc
    if parsed.tzinfo is None:
        raise StandingsFormatError(f"--as-of {value!r} needs a timezone (end it with Z)")
    return parsed.astimezone(dt.timezone.utc)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description=(__doc__ or "").split("\n\n")[0] +
        " READ-ONLY: takes explicit paths, writes nothing. " + UNVERIFIED_LINE +
        " Every test fixture is SYNTHETIC.")
    ap.add_argument("--date", required=True, help="slate date, YYYY-MM-DD (the delivery records' key)")
    ap.add_argument("--standings", action="append", required=True, metavar="CSV_OR_ZIP",
                    help="a DK standings export, by explicit path; repeat for several contests")
    ap.add_argument("--salary", required=True, help="the slate's DKSalaries.csv (names, salaries, positions, lock times)")
    ap.add_argument("--lineups", help="a lineups feed JSON; without it DK's own Starting column "
                                      "supplies the lock times (late_swap's R404 rule)")
    ap.add_argument("--projections", help="a projections CSV with Player_ID and Ceiling")
    ap.add_argument("--run-id", dest="run_id", help="runs/<id>/final/projections.csv is the frame")
    ap.add_argument("--paid-places", dest="paid_places",
                    help="the contest page's paid places: N (one file) or <contest_id>=N,...")
    ap.add_argument("--target-rank", dest="target_rank", type=int, default=1,
                    help="the rank whose points define 'live for the target' (default 1)")
    ap.add_argument("--leaders", type=int, default=DEFAULT_LEADERS,
                    help="how many top rows get the open-pitcher inference block")
    ap.add_argument("--as-of", dest="as_of", help="the lock clock, an ISO instant (default now)")
    ap.add_argument("--contest-id", dest="contest_id",
                    help="the contest id when the single standings file's name carries none")
    ap.add_argument("--root", default=str(REPO), help=argparse.SUPPRESS)
    return ap


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root)
    try:
        if args.target_rank < 1:
            raise StandingsFormatError("--target-rank must be a positive integer")
        if args.contest_id and len(args.standings) != 1:
            raise StandingsFormatError("--contest-id applies to exactly one --standings file")
        given = parse_paid_places(args.paid_places)
        check_paid_places_scope(given, len(args.standings))
        as_of = _parse_as_of(args.as_of)
        standings: Dict[str, Dict[str, Any]] = {}
        for path in args.standings:
            item = read_standings(path, args.contest_id)
            if item["contest_id"] in standings:
                raise StandingsFormatError(f"two standings files for contest {item['contest_id']}")
            standings[item["contest_id"]] = item
    except (StandingsFormatError, FileNotFoundError) as exc:
        print(f"standings_read refused: {exc}", file=sys.stderr)
        return 4
    salary = Path(args.salary)
    if not salary.is_file():
        print(f"standings_read refused: missing input: {salary}", file=sys.stderr)
        return 4
    from mlb_engine.intake.live_data_adapters import (  # noqa: PLC0415
        build_status_map_from_lineups_feed, dk_starting_only_feed)
    from mlb_engine.intake.slate_intake_manager import parse_dk_salary_csv  # noqa: PLC0415
    if args.lineups:
        try:
            feed = json.loads(Path(args.lineups).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"standings_read refused: {args.lineups} cannot be read ({exc})", file=sys.stderr)
            return 4
    else:
        feed, why = dk_starting_only_feed(salary, args.date)
        if feed is None:
            print(f"standings_read refused: no lock times can be derived: {why}. Pass "
                  f"--lineups at a feed.", file=sys.stderr)
            return 4
    try:
        status = build_status_map_from_lineups_feed(feed, str(salary))
        slate = Slate({p.player_id: p for p in parse_dk_salary_csv(str(salary))},
                      status["status_by_player_id"], as_of)
    except Exception as exc:  # noqa: BLE001 - a refusal with the reason, not a traceback
        print(f"standings_read refused: the salary file and feed give no usable lock "
              f"state ({type(exc).__name__}: {exc})", file=sys.stderr)
        return 4
    runs_root = root / "runs"
    frames: List[Tuple[str, Mapping[str, Optional[float]]]] = []
    frame_note = ""
    try:
        if args.projections:
            frames.append(("projections", load_frame(args.projections)))
            frame_note = f"--projections {args.projections}"
        else:
            run_id = args.run_id
            if not run_id:
                ids = sorted({r for cid in standings
                              for r in delivery_run_ids(root, args.date, cid)})
                if len(ids) == 1:
                    run_id = ids[0]
                else:
                    raise FrameUnavailable(
                        "the delivery records name no run id (pass --run-id or --projections)"
                        if not ids else
                        f"the delivery records name {len(ids)} run ids ({', '.join(ids)}) and "
                        f"cannot say which file was uploaded (pass --run-id or --projections)")
            frame, info = frame_for_run(runs_root, run_id)
            frames.append(("parent", frame))
            frame_note = (f"run {info['run_id']} (mode {info['mode'] or 'unknown'})"
                          + (f"; {info['note']}" if info["note"] else ""))
    except FrameUnavailable as exc:
        frame_note = f"UNAVAILABLE: {exc}; every verdict is unknown"
    from mlb_engine.field.field_miner import harvest_own_entry_ids  # noqa: PLC0415
    seats: List[Dict[str, Any]] = []
    for cid, standing in sorted(standings.items()):
        own = harvest_own_entry_ids(args.date, cid, root=root)
        if not own:
            # harvest_own_entry_ids returns [] both for "none entered" and for "the
            # evidence did not survive" (a fresh container, R369): say which it can't tell.
            print(f"WARN no delivery record or outputs/ manifest on this host names an "
                  f"entry of ours in contest {cid}; nothing to judge there (that is not "
                  f"evidence that none was entered)")
        seats.extend(standalone_seats(standing, own, slate, cid))
    report = build_report(standings=standings, seats=seats, slate=slate,
                          ceilings=Ceilings(frames), target_rank=args.target_rank,
                          paid_places=given, leaders_n=args.leaders, root=root,
                          frame_note=frame_note)
    for line in render(report):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
