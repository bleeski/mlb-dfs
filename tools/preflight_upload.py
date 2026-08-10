#!/usr/bin/env python3
"""preflight_upload.py -- the last check between a built file and DraftKings.

One fail-closed inspection of the artifact, run between "build finished" and
"Ben uploads." It inspects the file, not the process that made it, so it also
covers hand-built and ad-hoc exports that never entered the pipeline.

Design constraints, all deliberate:
  - two files and nothing else in the core invocation: --entries and --salary
  - no engine import, no solver, no network, no LLM; target under two seconds
  - every hard check is a fact about the file, decidable from disk
  - --force always exists, so this can never be the reason a slate is not
    entered. It exits 4, not 0: the operator is unblocked, the caller is told.

Deterministic file checks. Nothing here is a projection, an ROI figure, a win
rate, or a probability claim.

Hard checks (exit 2):
  1. header geometry matches a known roster contract, and every reserved row is
     either fully filled or fully blank at that width
  2. every rostered player carries a clean DK ``Status`` (IL/O/OUT/NA fail)
  3. every rostered ID exists in the salary file, and the entries file's own
     embedded player pool overlaps the salary file above --min-pool-overlap
  4. per-lineup DK legality (cap, slot eligibility, no duplicate person,
     Classic: 2+ games and at most 5 hitters per team and no hitter opposing a
     rostered SP; Showdown: both teams and a recomputed 1.5x captain salary)
  5. row accounting: at least one entry parsed, every Entry ID row parsed, all
     Entry IDs unique, and the row count matches --expect-entries or the manifest
     when either is given (truncation is self-consistent on its face; it is only
     detectable against an external statement of how many entries the file
     should hold). A file that parses to ZERO entries fails here: every other
     hard check iterates the parsed entries, so an empty parse used to run them
     all over nothing and print PASS (R51).

Resolved on their own when not passed, because a check that runs only when the
operator remembers a flag is a check that does not run at T-5:
  --manifest  outputs/<date>/upload_manifest.json, found next to the entries file.
              A delivered file with no manifest row, or one whose sha256 differs
              from the recorded one, is a HARD FAILURE (R3). --no-manifest is the
              explicit waiver, for a file that was never meant to have a record.
  --feed      the freshest lineups_feed.json for the slate date. A rostered
              player absent from his team's CONFIRMED lineup is a HARD FAILURE
              (R4); --feed-lenient restores the old warning. A team that has not
              posted stays soft. The feed's age is printed next to the verdict,
              so a stale all-clear is visibly stale.

Optional, never blocking on its own absence:
  --parent    diff contest assignment against the file this one refines
  --expect-sha256  hard-fail unless the file hashes to the given sha256 (full
              hex or a prefix of 12+ chars). The brief records
              delivered_sha256; this is the flag that pairs the upload with
              it at T-5 (R20a)

Advisory prints (never affect the exit code): exposure, lineup-overlap
histogram, duplicate-lineup groups, first lock.

Usage:
    python tools/preflight_upload.py --entries outputs/<date>/DKEntries.csv \\
        [--salary data/slates/<date>/DKSalaries.csv] [--manifest ...] [--feed ...]
        [--parent ...] [--json] [--force]

Exit codes:
  0  clean. Every hard check passed.
  2  hard failure. Do not upload without reading the failures.
  3  usage or IO error. The check did not run.
  4  acknowledged, not ready. --force was given and hard checks failed; the
     failures are printed, the file is not blocked, and the caller is told the
     truth. Exit 0 is the one signal automation trusts, so --force never returns
     it (R2). The design goal was that this tool can never be the reason a slate
     is not entered; that requires the OPERATOR to stay unblocked, not the
     caller to be misinformed.

This is a file check. It never uploads anything and never contacts DraftKings.
"""
from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
import re
import sys
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

VERSION = "1.1"

REPO_ROOT = Path(__file__).resolve().parent.parent

SALARY_CAP = 50000
CLASSIC_SLOTS: Tuple[str, ...] = ("P", "P", "C", "1B", "2B", "3B", "SS", "OF", "OF", "OF")
SHOWDOWN_SLOTS: Tuple[str, ...] = ("CPT", "UTIL", "UTIL", "UTIL", "UTIL", "UTIL")
ROSTER_START_COL = 4

# DK's Status vocabulary. IL/O/OUT/NA are shelved; DTD is playable-but-risky and
# warns rather than blocks, because a DTD scratch is a late-swap problem and a
# hard block here would stop a legal file from being entered.
OUT_STATUSES = frozenset({"IL", "O", "OUT", "NA", "IL10", "IL15", "IL60", "PUP", "SUSP"})
WARN_STATUSES = frozenset({"DTD", "GTD", "Q"})

# R85. DK writes the contest family into the contest name, and the roster
# contract into the header. Those are two independent statements about the same
# file and they can disagree -- a Showdown-geometry file carrying Classic
# Contest IDs passes every other check here, because nothing reads the name.
# Verified against every archived DKEntries and standings export in the repo:
# Showdown contest names carry the literal token, Classic names never do.
ARCHETYPES_CSV = REPO_ROOT / "data" / "reference" / "dk_contest_archetypes.csv"
SHOWDOWN_NAME_TOKENS = ("showdown", "captain mode")

# A verbatim copy of dk_entries_manager.ARCHETYPE_TYPE_PRECEDENCE, pinned equal
# by test. Preflight cannot import the engine, and resolving the same contest
# name to a different archetype than the engine did is this project's named
# no-op failure class (R79(d)), so the table is duplicated and the duplication
# is guarded rather than left to hold by luck.
ARCHETYPE_TYPE_PRECEDENCE = {
    "satellite": 100,
    "cash": 90,
    "wta": 80,
    "se_gpp": 50,
    "portfolio_gpp": 20,
    "unknown": 0,
}

# R34: mirrors ``mlb_engine.entries.upload_manifest.STATUS_VALUES`` on purpose,
# for the same reason parse_game_info_datetime is mirrored: this tool imports
# nothing from the engine so it still runs when the engine does not, which is
# exactly the state in which a pre-upload check matters most. The two are pinned
# in sync by a test, because a silently-diverged copy is worse than an import.
STATUS_VALUES = ("candidate", "upload_ready", "blocked", "acknowledged",
                 "superseded")

CLASSIC_MAX_HITTERS_PER_TEAM = 5
CLASSIC_MIN_GAMES = 2
CAPTAIN_MULTIPLIER = 1.5

_GAME_INFO_DT_RE = re.compile(
    r"(\d{2})/(\d{2})/(\d{4})\s+(\d{2}):(\d{2})(AM|PM)", re.IGNORECASE
)


# --------------------------------------------------------------------------
# small shared helpers
# --------------------------------------------------------------------------

def _cell(row: Sequence[str], i: int) -> str:
    return str(row[i]).strip() if 0 <= i < len(row) else ""


def _digits(value: Any) -> str:
    """DK writes player references as either a bare ID or 'Name (12345)'."""
    text = str(value or "")
    hits = re.findall(r"\d{4,}", text)
    return hits[-1] if hits else ""


def _int_or_none(value: Any) -> Optional[int]:
    try:
        return int(float(str(value).replace(",", "").replace("$", "").strip()))
    except (TypeError, ValueError):
        return None


def _norm_name(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"\b(jr|sr|ii|iii|iv)\.?\b", "", text.lower())
    return re.sub(r"[^a-z]", "", text)


def _matchup(game_info: Any) -> str:
    text = str(game_info or "").strip()
    head = text.split(" ", 1)[0] if text else ""
    return head.upper() if "@" in head else ""


def _eastern_tz(month: int, day: int):
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("America/New_York")
    except Exception:
        edt = (3 < month < 11) or (month == 3 and day >= 15) or (month == 11 and day <= 1)
        return timezone(timedelta(hours=-4 if edt else -5))


def parse_game_info_datetime(game_info: Any) -> Optional[datetime]:
    """'AAA@BBB 07/08/2026 07:05PM ET' -> aware datetime, or None.

    Mirrors ``slate_intake_manager.parse_game_info_datetime`` on purpose. This
    tool imports nothing from the engine so it still runs when the engine does
    not, which is exactly the state in which a pre-upload check matters most.
    """
    m = _GAME_INFO_DT_RE.search(str(game_info or ""))
    if not m:
        return None
    mm, dd, yyyy, hh, mi, ap = m.groups()
    hour = int(hh) % 12 + (12 if ap.upper() == "PM" else 0)
    return datetime(int(yyyy), int(mm), int(dd), hour, int(mi),
                    tzinfo=_eastern_tz(int(mm), int(dd)))


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


# --------------------------------------------------------------------------
# geometry: read the contract off the header rather than assume one
# --------------------------------------------------------------------------

def detect_geometry(header: Sequence[str]) -> Tuple[str, Tuple[str, ...]]:
    """Return (contest_type, slots) or raise ValueError naming expected vs found.

    The defect this closes: the entries parser validated columns 0-3 only, which
    are identical in both geometries, so a Showdown file read at Classic width
    pulled DK's Instructions text into roster cells and defeated the blank-row
    guard. The slot labels are right there in the header; read them.
    """
    labels = [str(x).strip().upper() for x in header[ROSTER_START_COL:]]
    for contest, slots in (("classic", CLASSIC_SLOTS), ("showdown", SHOWDOWN_SLOTS)):
        width = len(slots)
        if [s.upper() for s in slots] == labels[:width]:
            return contest, slots
    found = ",".join(labels[:12]) or "<empty>"
    raise ValueError(
        "entries header roster window matches no roster contract; "
        f"expected '{','.join(CLASSIC_SLOTS)}' or '{','.join(SHOWDOWN_SLOTS)}' "
        f"at column {ROSTER_START_COL}, found '{found}'"
    )


def parse_embedded_pool(rows: Sequence[Sequence[str]]) -> set[str]:
    """DK's per-file fingerprint of the draftgroup, to the right of the entries.

    Unread until now. Its signal is blunt and strong: near-total overlap for the
    right salary/entries pairing, near-zero for a wrong-day pairing.
    """
    start = None
    for row in rows[:40]:
        for i, value in enumerate(row):
            if str(value).strip().lower() == "position" and i > ROSTER_START_COL:
                start = i
                break
        if start is not None:
            break
    if start is None:
        return set()
    out: set[str] = set()
    for row in rows:
        pid = _digits(_cell(row, start + 1)) or _digits(_cell(row, start + 3))
        if pid:
            out.add(pid)
    return out


# --------------------------------------------------------------------------
# loading
# --------------------------------------------------------------------------

class EntryRow:
    __slots__ = ("line_no", "entry_id", "contest_name", "contest_id", "entry_fee",
                 "cells", "raw")

    def __init__(self, line_no: int, raw: Sequence[str], width: int):
        self.line_no = line_no
        self.raw = list(raw)
        self.entry_id = _cell(raw, 0)
        self.contest_name = _cell(raw, 1)
        self.contest_id = _cell(raw, 2)
        self.entry_fee = _cell(raw, 3)
        end = ROSTER_START_COL + width
        self.cells = [_digits(_cell(raw, i)) if _cell(raw, i) else ""
                      for i in range(ROSTER_START_COL, end)]

    @property
    def filled(self) -> int:
        return sum(1 for c in self.cells if c)

    @property
    def is_blank(self) -> bool:
        return self.filled == 0


def load_entries(path: Path) -> Tuple[str, Tuple[str, ...], List[EntryRow], List[List[str]], int]:
    """Parse every reserved row at the detected width, dropping nothing silently.

    ``load_entries`` in verify_export.py skipped rows shorter than the expected
    width, so a truncated file printed PASS. Here a short row is still parsed
    (missing cells read blank) and the count of Entry-ID-bearing rows is
    returned separately, so row accounting can catch what parsing tolerates.

    R51: that separation only works if the two counters can actually disagree.
    They could not. Both were incremented inside the same
    ``if not entry_id.isdigit(): continue`` branch, so ``entry_id_rows`` was
    ``len(entries)`` by construction and hard check 5 was dead code. A row now
    counts as an Entry-ID row when it STATES an entry -- anything in the Entry ID
    cell, or a filled roster window -- whether or not the ID still parses as
    digits. That is what makes an Excel or pandas float round-trip
    ('4.71059E+09', '4710591235.0') visible as rows-lost instead of parsing to
    zero entries and printing PASS. Verified against three real DK exports
    (2026-07-25 classic, 2026-07-29 classic, the Showdown fixture): the embedded
    player pool sits to the RIGHT of the roster window, so its rows carry
    neither signal and the new counter matches the old one exactly on a healthy
    file.
    """
    with path.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.reader(fh))
    if not rows:
        raise ValueError(f"{path} is empty")
    header = rows[0]
    contest, slots = detect_geometry(header)
    width = len(slots)
    entries: List[EntryRow] = []
    entry_id_rows = 0
    for line_no, raw in enumerate(rows[1:], start=2):
        entry_id = _cell(raw, 0)
        row = EntryRow(line_no, raw, width)
        if entry_id or row.filled:
            entry_id_rows += 1
        if not entry_id.isdigit():
            continue
        entries.append(row)
    return contest, slots, entries, rows, entry_id_rows


def load_salary(path: Path) -> Dict[str, Dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        out: Dict[str, Dict[str, str]] = {}
        for row in reader:
            pid = _digits(row.get("ID") or row.get("Name + ID"))
            if pid:
                out[pid] = row
    if not out:
        raise ValueError(f"{path} yielded no salary rows with a parseable ID")
    return out


def resolve_salary_from_promoted_run(runs_root: Path) -> Optional[Path]:
    """The engine snapshots inputs per run; prefer that over the staged copy.

    The staged ``data/slates/<date>/`` copy is shared and date-keyed, so a later
    build for the same date overwrites it and orphans verification of what was
    actually delivered. The run snapshot cannot be clobbered that way.

    ``run_id`` resolves first because the recorded ``run_dir`` is an absolute
    path from the session that wrote it, and that mount is gone in every later
    session.
    """
    pointer = runs_root / "latest_valid_run.json"
    try:
        data = json.loads(pointer.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    candidates = []
    run_id = str(data.get("run_id") or "").strip()
    if run_id:
        candidates.append(runs_root / run_id)
    recorded = str(data.get("run_dir") or "").strip()
    if recorded:
        candidates.append(Path(recorded))
    for base in candidates:
        try:
            snap = base / "inputs" / "DKSalaries.csv"
            if snap.exists():
                return snap
        except OSError:
            continue
    return None


# --------------------------------------------------------------------------
# checks
# --------------------------------------------------------------------------

class Report:
    def __init__(self) -> None:
        self.failures: List[str] = []
        self.warnings: List[str] = []
        self.info: Dict[str, Any] = {}

    def fail(self, message: str) -> None:
        self.failures.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)


def verdict_exit_code(failures: Sequence[str], force: bool) -> int:
    """The one exit-code contract both file checkers answer to.

    R2 settled this on preflight: ``--force`` must never return the single signal
    automation trusts, so a forced run with hard failures present exits 4
    (acknowledged, not clean) rather than 0. R52 found ``verify_export`` had never
    adopted it -- it returned 2 only when ``--force`` was absent and otherwise
    fell through to ``return 0``, so the late-swap verification path read a forced
    run as clean and the two checkers disagreed on the only contract a caller can
    see. One function now, imported by both, because two implementations of one
    rule is this project's named no-op failure class.
    """
    if not failures:
        return 0
    return 4 if force else 2


def load_archetypes(path: Path = ARCHETYPES_CSV) -> List[Dict[str, str]]:
    """The pinned contest-pattern table, read directly.

    Preflight-native by contract: no network, no engine import. The engine has
    its own reader in dk_entries_manager for allocation; this is a second,
    smaller read of the same pinned CSV rather than an import, because
    preflight must run when the engine cannot (R79(d) names this duplication
    class; the constants cross-pin is the answer there, not an import here).

    A missing or unreadable file returns [] and the caller degrades to the
    geometry check alone. The archetype join is evidence, never the gate.
    """
    try:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            return [row for row in csv.DictReader(handle)
                    if str(row.get("pattern") or "").strip()]
    except (OSError, csv.Error, UnicodeDecodeError):
        return []


def match_archetype(contest_name: str,
                    archetypes: Sequence[Mapping[str, str]]) -> Optional[Mapping[str, str]]:
    """Type precedence, then max-entries, then pattern length, then name.

    The identical ranking dk_entries_manager.infer_contest_archetype uses, for
    the reason its comment gives: longest-pattern-wins misroutes real DK names,
    because "Satellite to $2 MLB Pocket Cup MEGA Qualifier" resolves on "Pocket
    Cup" and a satellite is not a GPP. Reproduced here on the archived names
    before this was written.
    """
    name = str(contest_name or "").casefold()
    matches = [row for row in archetypes
               if str(row.get("pattern") or "").strip()
               and str(row["pattern"]).strip().casefold() in name]
    if not matches:
        return None
    return max(matches, key=lambda row: (
        ARCHETYPE_TYPE_PRECEDENCE.get(
            str(row.get("inferred_type") or "").strip().lower(), 0),
        1 if str(row.get("inferred_max_entries") or "").strip() else 0,
        len(str(row.get("pattern") or "").strip()),
        str(row.get("pattern") or "").strip(),
    ))


def contest_type_from_name(contest_name: str) -> Optional[str]:
    """'showdown' | 'classic' | None, read off DK's own contest name.

    The archetypes CSV deliberately does NOT decide this. Its patterns are
    objective families (Jukebox, Satellite, Double Up) and every one of them
    ships in BOTH geometries -- 'MLB Showdown $20 Quarter Jukebox (CHC @ STL)'
    and 'MLB $30 Quarter Jukebox' are both real, both archived here. So the
    geometry discriminator is the name's own Showdown token and the archetype
    is the objective join that rides alongside it.

    Measured before it was allowed to fail anything, across all 871 entry rows
    in this repo's archived DKEntries exports, slate files and fixtures: 446
    classic-geometry rows, none carrying the token or a single-game "(A @ B)"
    suffix; 425 showdown-geometry rows, every one carrying the token. The
    separation is total in both directions, which is what makes the absence of
    the token evidence and not just silence. If DK ever ships a Showdown
    contest without it, this reads classic, the check fails, and `--force`
    (exit 4) is the operator's way past it -- preflight is never allowed to be
    the reason a slate is not entered.

    Only a blank name returns None, which never fails.
    """
    name = str(contest_name or "").casefold()
    if not name.strip():
        return None
    if any(token in name for token in SHOWDOWN_NAME_TOKENS):
        return "showdown"
    return "classic"


def check_contest_identity(contest: str, entries: Sequence[EntryRow], rep: Report,
                           archetypes: Optional[Sequence[Mapping[str, str]]] = None) -> None:
    """R85: the contest NAME and the header geometry must tell the same story.

    Today a Showdown-shaped file whose entries belong to Classic contests
    passes every hard check, because nothing reads the Contest Name column --
    the geometry check reads the header, the legality check reads the roster,
    and the manifest cross-check only fires when a manifest resolves. The name
    is DK's own statement of what the contest is, it sits in column 2 of every
    row, and it is free to read.

    Two hard failures, both money-boundary:
      1. every named contest disagrees with the geometry (the whole file is
         pointed at the wrong contest family);
      2. the names disagree with EACH OTHER (two draftgroups in one file,
         which no single upload can satisfy).

    Unrecognized archetypes are recorded, never failed on.
    """
    if not entries:
        return
    rows = load_archetypes() if archetypes is None else archetypes
    seen: Dict[str, List[EntryRow]] = collections.defaultdict(list)
    unmatched: List[str] = []
    objective_classes: set[str] = set()

    for entry in entries:
        implied = contest_type_from_name(entry.contest_name)
        if implied is not None:
            seen[implied].append(entry)
        arche = match_archetype(entry.contest_name, rows)
        if arche is None:
            if entry.contest_name and entry.contest_name not in unmatched:
                unmatched.append(entry.contest_name)
        else:
            klass = str(arche.get("objective_class") or "").strip()
            if klass:
                objective_classes.add(klass)

    rep.info["contest_identity"] = {
        "geometry": contest,
        "implied_by_name": sorted(seen),
        "objective_classes": sorted(objective_classes),
        "unmatched_contest_names": unmatched,
    }

    if len(seen) > 1:
        detail = "; ".join(
            f"{kind}: {seen[kind][0].contest_name!r} (entry "
            f"{seen[kind][0].entry_id}, {len(seen[kind])} row(s))"
            for kind in sorted(seen))
        rep.fail(f"the entries name BOTH contest families in one file, which no "
                 f"single upload can satisfy -- {detail}. Two draftgroups have "
                 f"been mixed; split them and re-run")
        return

    for kind, members in seen.items():
        if kind == contest:
            continue
        first = members[0]
        rep.fail(
            f"contest identity: the header geometry is {contest} but all "
            f"{len(members)} entries name {kind} contests, first "
            f"{first.contest_name!r} (entry {first.entry_id}, contest ID "
            f"{first.contest_id}). DK's contest name and DK's roster contract "
            f"disagree, so this file is pointed at the wrong contest family; "
            f"do not upload")

    if unmatched:
        rep.warn(f"{len(unmatched)} contest name(s) match no row in "
                 f"{ARCHETYPES_CSV.name}, so no archetype could be inferred "
                 f"for them: {unmatched[:3]}. Not a failure -- DK names change "
                 f"faster than the pinned table")


def check_row_shape(entries: Sequence[EntryRow], entry_id_rows: int, width: int,
                    rep: Report, expect_entries: Optional[int] = None) -> None:
    """Hard check 1 and 5: geometry per row, and row accounting."""
    # R51: every other hard check iterates `entries`. On an empty parse they all
    # ran over an empty list and the tool printed "all hard checks clean", exit 0,
    # verdict upload_ready -- a false PASS at the money boundary. A file with no
    # parseable entry is never uploadable, whatever else is true of it.
    if not entries:
        if entry_id_rows:
            rep.fail(f"no parseable entries: {entry_id_rows} row(s) state an entry "
                     f"but none carries a numeric Entry ID. An Excel or pandas "
                     f"round-trip reformats that column ('4.71059E+09', "
                     f"'4710591235.0'); re-export the file rather than repairing "
                     f"the cells by hand")
        else:
            rep.fail("no parseable entries: this file holds a header and no entry "
                     "rows at all. There is nothing to upload")
    if entry_id_rows != len(entries):
        rep.fail(f"row accounting: {entry_id_rows} Entry ID rows on disk, "
                 f"{len(entries)} parsed")
    if expect_entries is not None and len(entries) != expect_entries:
        rep.fail(f"row accounting: expected {expect_entries} reserved entries, "
                 f"file holds {len(entries)}; a short file is a truncated write")
    seen: Dict[str, int] = {}
    for e in entries:
        if e.entry_id in seen:
            rep.fail(f"duplicate Entry ID {e.entry_id} (lines {seen[e.entry_id]} "
                     f"and {e.line_no}); a duplicate silently overwrites the first")
        seen[e.entry_id] = e.line_no
        if not e.contest_id.isdigit():
            rep.fail(f"{e.entry_id}: Contest ID '{e.contest_id}' is not numeric")
        if 0 < e.filled < width:
            rep.fail(f"{e.entry_id} (line {e.line_no}): partially filled roster, "
                     f"{e.filled}/{width} slots; DK rejects the entry")
    blanks = [e.entry_id for e in entries if e.is_blank]
    rep.info["blank_reserved_rows"] = blanks
    if blanks:
        rep.fail(f"{len(blanks)} blank reserved row(s) block certification: "
                 f"{', '.join(blanks[:8])}{' ...' if len(blanks) > 8 else ''}")


def check_pool_membership(entries: Sequence[EntryRow], salary: Dict[str, Dict[str, str]],
                          pool: set[str], min_overlap: float, rep: Report) -> None:
    """Hard check 3: the file's players and DK's own draftgroup fingerprint."""
    rostered = {pid for e in entries for pid in e.cells if pid}
    unknown = sorted(rostered - set(salary))
    if unknown:
        rep.fail(f"{len(unknown)} rostered player ID(s) absent from the salary file "
                 f"(wrong slate or wrong file): {unknown[:10]}")
    if pool:
        overlap = len(pool & set(salary)) / len(pool)
        rep.info["embedded_pool_overlap"] = round(overlap, 4)
        rep.info["embedded_pool_size"] = len(pool)
        if overlap < min_overlap:
            rep.fail(f"entries file's embedded player pool overlaps the salary file "
                     f"at {overlap:.1%} ({len(pool & set(salary))}/{len(pool)}); "
                     f"below {min_overlap:.0%} means these two files are different "
                     f"draftgroups")
    else:
        rep.info["embedded_pool_overlap"] = None
        rep.warn("entries file carries no parseable embedded player pool; the "
                 "strongest available same-draftgroup check is unavailable")


def check_status(entries: Sequence[EntryRow], salary: Dict[str, Dict[str, str]],
                 rep: Report) -> None:
    """Hard check 2: no shelved player occupies a roster slot."""
    out_hits: List[str] = []
    warn_hits: List[str] = []
    for e in entries:
        for pid in e.cells:
            row = salary.get(pid)
            if not row:
                continue
            status = str(row.get("Status") or "").strip().upper()
            if not status:
                continue
            label = f"{row.get('Name', pid)} ({row.get('TeamAbbrev', '?')}, {status})"
            if status in OUT_STATUSES:
                out_hits.append(f"{e.entry_id}: {label}")
            elif status in WARN_STATUSES:
                warn_hits.append(f"{e.entry_id}: {label}")
    rep.info["status_out"] = sorted(set(out_hits))
    rep.info["status_watch"] = sorted(set(warn_hits))
    if out_hits:
        uniq = sorted(set(out_hits))
        rep.fail(f"{len(uniq)} roster slot(s) hold a shelved player: "
                 + "; ".join(uniq[:10]))
    for hit in sorted(set(warn_hits)):
        rep.warn(f"day-to-day player rostered: {hit}")


def _classic_legality(entry: EntryRow, players: Sequence[Dict[str, str]],
                      slots: Sequence[str], rep: Report) -> None:
    games = {_matchup(p.get("Game Info")) for p in players}
    games.discard("")
    if len(games) < CLASSIC_MIN_GAMES:
        rep.fail(f"{entry.entry_id}: {len(games)} game(s) represented; DK Classic "
                 f"requires at least {CLASSIC_MIN_GAMES}")
    hitters = players[2:]
    per_team = collections.Counter(str(p.get("TeamAbbrev") or "").upper() for p in hitters)
    over = [f"{t}={n}" for t, n in per_team.items() if n > CLASSIC_MAX_HITTERS_PER_TEAM]
    if over:
        rep.fail(f"{entry.entry_id}: more than {CLASSIC_MAX_HITTERS_PER_TEAM} hitters "
                 f"from one team ({', '.join(sorted(over))})")
    sp_opponents = set()
    for p in players[:2]:
        match = _matchup(p.get("Game Info"))
        team = str(p.get("TeamAbbrev") or "").upper()
        if "@" in match:
            away, home = match.split("@", 1)
            sp_opponents.add(home if team == away else away)
    clashes = sorted({
        f"{p.get('Name')} vs {str(p.get('TeamAbbrev') or '').upper()}-opposing SP"
        for p in hitters
        if str(p.get("TeamAbbrev") or "").upper() in sp_opponents
    })
    if clashes:
        rep.fail(f"{entry.entry_id}: hitter opposing a rostered SP ({'; '.join(clashes)})")


def _showdown_legality(entry: EntryRow, players: Sequence[Dict[str, str]],
                       salary_by_person: Dict[str, List[Dict[str, str]]],
                       rep: Report) -> None:
    teams = {str(p.get("TeamAbbrev") or "").upper() for p in players}
    teams.discard("")
    if len(teams) < 2:
        rep.fail(f"{entry.entry_id}: Showdown requires both teams; found "
                 f"{sorted(teams) or ['none']}")
    cpt = players[0]
    cpt_roles = {r.strip().upper() for r in str(cpt.get("Roster Position") or "").split("/")}
    if "CPT" not in cpt_roles:
        rep.fail(f"{entry.entry_id}: slot 1 holds {cpt.get('Name')} whose salary row "
                 f"is not a CPT row ({sorted(cpt_roles) or ['none']})")
    for p in players[1:]:
        roles = {r.strip().upper() for r in str(p.get("Roster Position") or "").split("/")}
        if "CPT" in roles and "UTIL" not in roles:
            rep.fail(f"{entry.entry_id}: {p.get('Name')} occupies a UTIL slot with a "
                     f"CPT-priced salary row; DK rejects two captains")
    # Recompute the captain price rather than trust the cell. DK prices the CPT
    # role row at 1.5x the same person's UTIL row; a hand-edited or mismatched
    # file shows up here and nowhere else.
    key = f"{_norm_name(cpt.get('Name'))}|{str(cpt.get('TeamAbbrev') or '').upper()}"
    siblings = salary_by_person.get(key, [])
    util_rows = [r for r in siblings
                 if "UTIL" in str(r.get("Roster Position") or "").upper()
                 and "CPT" not in str(r.get("Roster Position") or "").upper()]
    cpt_salary = _int_or_none(cpt.get("Salary"))
    util_salary = _int_or_none(util_rows[0].get("Salary")) if util_rows else None
    if cpt_salary is not None and util_salary:
        expected = round(util_salary * CAPTAIN_MULTIPLIER)
        if abs(cpt_salary - expected) > 1:
            rep.fail(f"{entry.entry_id}: captain {cpt.get('Name')} priced {cpt_salary}, "
                     f"recomputed {expected} from the UTIL row ({util_salary} x "
                     f"{CAPTAIN_MULTIPLIER})")
    elif util_rows:
        rep.warn(f"{entry.entry_id}: captain salary not recomputable "
                 f"(cpt={cpt.get('Salary')!r}, util={util_rows[0].get('Salary')!r})")


def check_legality(contest: str, slots: Sequence[str], entries: Sequence[EntryRow],
                   salary: Dict[str, Dict[str, str]], rep: Report) -> List[Dict[str, Any]]:
    """Hard check 4: the rules DK enforces, restated on the file."""
    salary_by_person: Dict[str, List[Dict[str, str]]] = collections.defaultdict(list)
    for row in salary.values():
        key = f"{_norm_name(row.get('Name'))}|{str(row.get('TeamAbbrev') or '').upper()}"
        salary_by_person[key].append(row)

    width = len(slots)
    details: List[Dict[str, Any]] = []
    for e in entries:
        detail: Dict[str, Any] = {"entry_id": e.entry_id, "contest_id": e.contest_id}
        if e.is_blank:
            detail["status"] = "blank"
            details.append(detail)
            continue
        players = [salary.get(pid) for pid in e.cells]
        if any(p is None for p in players):
            detail["status"] = "unverifiable"
            details.append(detail)
            continue
        players = [p for p in players if p is not None]

        salaries = [_int_or_none(p.get("Salary")) for p in players]
        if any(s is None for s in salaries):
            bad = [p.get("Name") for p, s in zip(players, salaries) if s is None]
            rep.fail(f"{e.entry_id}: unparseable salary for {bad}")
            detail["status"] = "unverifiable"
            details.append(detail)
            continue
        total = sum(s for s in salaries if s is not None)
        detail["salary"] = total
        if total > SALARY_CAP:
            rep.fail(f"{e.entry_id}: salary {total} over the {SALARY_CAP} cap")

        identity = [f"{_norm_name(p.get('Name'))}|{str(p.get('TeamAbbrev') or '').upper()}"
                    for p in players]
        if len(set(identity)) != width:
            dupes = sorted({p.get("Name") for p, k in zip(players, identity)
                            if identity.count(k) > 1})
            rep.fail(f"{e.entry_id}: the same person occupies two slots ({dupes})")
        detail["duplicate_person"] = len(set(identity)) != width

        ineligible = [
            f"{players[i].get('Name')}->{slots[i]}"
            for i in range(width)
            if slots[i].upper() not in
            {r.strip().upper() for r in str(players[i].get("Roster Position") or "").split("/")}
        ]
        if ineligible:
            rep.fail(f"{e.entry_id}: slot ineligibility {ineligible}")
        detail["slot_eligible"] = not ineligible

        hitters = players[1:] if contest == "showdown" else players[2:]
        detail["stack"] = collections.Counter(
            str(p.get("TeamAbbrev") or "").upper() for p in hitters).most_common(3)

        if contest == "classic":
            _classic_legality(e, players, slots, rep)
        else:
            _showdown_legality(e, players, salary_by_person, rep)
        detail["status"] = "checked"
        details.append(detail)
    return details


# --------------------------------------------------------------------------
# optional widenings
# --------------------------------------------------------------------------

def is_delivered_file(entries_path: Path) -> bool:
    """A file under outputs/ is a delivery; anything else is ad hoc.

    R3(b) hard-fails a DELIVERED file with no manifest row. The distinction
    matters because this tool deliberately also covers hand-built exports that
    never entered the pipeline, and those have no record to miss. outputs/ is
    the delivery location, so a file sitting there with nothing saying which
    delivery it is is exactly the ambiguity the manifest exists to kill.
    """
    try:
        entries_path.resolve().relative_to((REPO_ROOT / "outputs").resolve())
        return True
    except (ValueError, OSError):
        return False


def check_manifest(entries_path: Path, entries: Sequence[EntryRow],
                   manifest_path: Path, rep: Report, delivered: bool = False) -> None:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        # R35: an ABSENT manifest for a delivered file already hard-fails below,
        # so warning on a CORRUPT one had the provenance gate exactly backwards:
        # the weaker evidence state passed. Corruption is also the state in which
        # a later delivery can silently overwrite the history, so it blocks.
        if delivered:
            rep.fail(f"manifest at {manifest_path} is unreadable ({exc}); a "
                     f"delivered file whose provenance record cannot be read has "
                     f"no verifiable provenance, and a corrupt manifest is the "
                     f"one state in which the next delivery erases the history. "
                     f"Quarantine the file and re-record the delivery")
        else:
            rep.warn(f"manifest unreadable ({exc}); contest-assignment "
                     f"cross-check skipped")
        return
    records = manifest if isinstance(manifest, list) else manifest.get("deliveries", [])
    digest = sha256_of(entries_path)
    name = entries_path.name
    match = None
    for rec in records:
        if str(rec.get("sha256") or "") == digest:
            match = rec
            break
    if match is None:
        by_name = [r for r in records if Path(str(r.get("delivered_file") or "")).name == name]
        if by_name:
            rep.fail(f"manifest lists {name} with sha256 "
                     f"{by_name[-1].get('sha256')} but this file hashes {digest}; "
                     f"the file changed after it was recorded")
        else:
            message = (f"no manifest record for {name} (sha256 {digest[:12]}); "
                       f"this file was not produced by a recorded delivery path")
            rep.fail(message) if delivered else rep.warn(message)
        return
    rep.info["manifest_run_id"] = match.get("run_id")
    # R34: the verdict needs this. A file whose own record says it was not
    # certified must not be handed the 'upload_ready' label by a byte checker.
    rep.info["recorded_certification"] = match.get("certification")
    rep.info["recorded_status"] = match.get("status")
    # R34: the status vocabulary is closed and was never enforced, so the
    # Showdown path wrote 'delivered' and it read as current everywhere that
    # filters on '!= superseded'.
    recorded_status = str(match.get("status") or "").strip()
    if recorded_status and recorded_status not in STATUS_VALUES:
        rep.fail(f"manifest records status {recorded_status!r}, which is not one "
                 f"of {list(STATUS_VALUES)}; an unknown status reads as current "
                 f"everywhere that only filters out 'superseded'")
    recorded_entries = match.get("entries")
    if isinstance(recorded_entries, int) and recorded_entries != len(entries):
        rep.fail(f"manifest records {recorded_entries} entries, file holds "
                 f"{len(entries)}; a short file is a truncated write")
    if str(match.get("status") or "") == "superseded":
        rep.fail(f"manifest marks this file superseded by "
                 f"{match.get('superseded_by')}; do not upload it")
    recorded = {str(c) for c in (match.get("contest_ids") or [])}
    actual = {e.contest_id for e in entries}
    if recorded and recorded != actual:
        rep.fail(f"contest assignment differs from the manifest: recorded "
                 f"{sorted(recorded)}, file carries {sorted(actual)}")


def status_for_verdict(verdict: str) -> str:
    """R105. The manifest STATUS this preflight VERDICT implies. Two vocabularies.

    ``STATUS_VALUES`` is the manifest's closed record vocabulary, shared with
    ``mlb_engine.entries.upload_manifest``. The verdict vocabulary is this tool's
    own, and R34 grew it a fifth value -- ``review_ready`` -- without the
    manifest growing one. ``stamp_manifest_status`` wrote the verdict straight
    into ``status``, so every clean Showdown delivery stamped
    ``status: 'review_ready'`` and the NEXT read of that record hard-failed:
    "manifest records status 'review_ready', which is not one of [...]". Two
    writers of one field disagreeing on its allowed values is exactly the
    condition ``contest_shapes.py`` exists to prevent for shapes; the behavioral
    cost is worse than the bookkeeping one, because a red FAIL on every clean
    Showdown export trains the operator to ignore the FAIL that is someday real.

    A ``review_ready`` file is a CANDIDATE: mechanically clean, not certified,
    and preflight must not promote it past that. The verdict is not lost -- it is
    recorded beside the status under ``preflight.verdict``, where it belongs,
    because the verdict and the status are separate facts about the same bytes.
    """
    return {
        "upload_ready": "upload_ready",
        "review_ready": "candidate",
        "blocked": "blocked",
        "acknowledged": "acknowledged",
    }.get(str(verdict), "candidate")


def stamp_manifest_status(manifest_path: Path, entries_sha256: str,
                          status: str, failures: Sequence[str], rep: Report) -> None:
    """Write the preflight verdict onto the matching manifest record.

    R3(c). "Upload-ready", "blocked" and "acknowledged" lived only in the
    operator's memory of what the terminal said. They belong on the artifact
    record, because the record is what a later session, a scheduled task, or a
    late swap reads.

    R105. ``status`` here is a VERDICT, and it is mapped through
    ``status_for_verdict`` before it is written, because the two vocabularies are
    not the same set. The mapped value is asserted against ``STATUS_VALUES``
    before the write: a verdict this function cannot map is a bug in this
    function, and the honest response is to record the verdict and leave the
    status alone rather than write a value the next reader will hard-fail on.

    Deliberately narrow: it only ever updates a record whose sha256 already
    equals these bytes, it never creates one, and a write failure is a warning.
    No engine import; the manifest is plain JSON.
    """
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    records = payload if isinstance(payload, list) else payload.get("deliveries", [])
    target = next((r for r in records
                   if isinstance(r, dict) and r.get("sha256") == entries_sha256), None)
    if target is None:
        return
    record_status = status_for_verdict(status)
    if record_status in STATUS_VALUES:
        target["status"] = record_status
    else:  # pragma: no cover - structurally unreachable; the guard is the point
        rep.warn(f"preflight verdict {status!r} maps to {record_status!r}, which "
                 f"is outside the manifest vocabulary {list(STATUS_VALUES)}; the "
                 f"status was left unchanged and only the verdict recorded")
    target["preflight"] = {
        "version": VERSION,
        "verdict": status,
        "failures": list(failures),
        "checked_utc": datetime.now(timezone.utc).isoformat(),
    }
    try:
        # R21: the fixed tmp name here let two concurrent preflights
        # interleave into one tmp file and rename partial bytes over the
        # manifest; a unique name keeps each stamp private to its writer.
        tmp = manifest_path.with_name(
            f".{manifest_path.name}.preflight.{uuid.uuid4().hex}.tmp")
        tmp.write_text(json.dumps(payload, indent=1, sort_keys=False) + "\n",
                       encoding="utf-8")
        tmp.replace(manifest_path)
        # R105. The STATUS that landed on the record, not the verdict that
        # produced it: on a review-grade file those two differ, and reporting the
        # verdict here is what made the divergence invisible.
        rep.info["manifest_status_stamped"] = record_status
        rep.info["manifest_verdict_recorded"] = status
    except OSError as exc:
        rep.warn(f"manifest status not stamped ({exc}); the verdict is this "
                 f"output only")


def resolve_feed_for_slate(entries: Sequence[EntryRow],
                           salary: Dict[str, Dict[str, str]],
                           rep: Report) -> Optional[Path]:
    """Find the freshest lineups_feed*.json for this file's slate date.

    R4. The posted-lineup cross-check was the strongest thing this tool could
    say and it ran only when --feed was passed, which made the scratch-after-
    build window opt-in. The feed is already on disk for every slate the engine
    built; nothing has to be fetched to use it.
    """
    dates = set()
    for entry in entries:
        for pid in entry.cells:
            row = salary.get(pid)
            if not row:
                continue
            parsed = parse_game_info_datetime(row.get("Game Info"))
            if parsed is not None:
                dates.add(parsed.date().isoformat())
    if len(dates) != 1:
        if dates:
            rep.info["feed_autoresolve"] = (
                f"skipped: the file spans {len(dates)} slate dates {sorted(dates)}")
        return None
    slate_date = dates.pop()
    candidates = sorted((REPO_ROOT / "data" / "slates" / slate_date).glob("lineups_feed*.json"))
    if not candidates:
        rep.info["feed_autoresolve"] = f"no lineups_feed*.json under data/slates/{slate_date}"
        return None
    freshest = max(candidates, key=lambda p: p.stat().st_mtime)
    rep.info["feed_autoresolve"] = f"resolved {freshest.name} for {slate_date}"
    return freshest


def _feed_age_minutes(feed: Mapping[str, Any]) -> Optional[float]:
    stamp = str(feed.get("fetched_at") or "")
    if not stamp:
        return None
    try:
        fetched = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - fetched).total_seconds() / 60.0


def check_parent(entries: Sequence[EntryRow], parent_path: Path, rep: Report) -> None:
    try:
        _, _, parent_entries, _, _ = load_entries(parent_path)
    except (OSError, ValueError) as exc:
        rep.warn(f"parent unreadable ({exc}); contest-assignment diff skipped")
        return
    parent_by_id = {e.entry_id: e for e in parent_entries}
    missing = sorted(set(parent_by_id) - {e.entry_id for e in entries})
    if missing:
        rep.fail(f"entries present in the parent but absent here: {missing[:10]}")
    for e in entries:
        p = parent_by_id.get(e.entry_id)
        if p and p.contest_id != e.contest_id:
            rep.fail(f"{e.entry_id}: contest reassigned from {p.contest_id} "
                     f"({p.contest_name}) to {e.contest_id} ({e.contest_name})")


FEED_STALE_MINUTES = 90


def check_feed(entries: Sequence[EntryRow], salary: Dict[str, Dict[str, str]],
               feed_path: Path, strict: bool, rep: Report) -> None:
    """A rostered player missing from his team's CONFIRMED lineup is a hard fail.

    R4. It was a warning unless --feed AND --feed-strict were both passed, so a
    3:55pm bench with a blank salary-file Status walked through the default
    check. That is the classic DFS zero and the evidence to catch it was already
    on disk. ``strict=False`` (--feed-lenient) restores the warning. A team that
    has not posted is untouched either way: TEAM_UNCONFIRMED is not evidence.
    """
    try:
        feed = json.loads(feed_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        rep.warn(f"feed unreadable ({exc}); posted-lineup cross-check skipped")
        return
    age = _feed_age_minutes(feed)
    if age is not None:
        rep.info["feed_age_minutes"] = round(age, 1)
        if age > FEED_STALE_MINUTES:
            rep.warn(f"lineups feed is {age / 60:.1f}h old (fetched "
                     f"{feed.get('fetched_at')}); a confirmed-lineup all-clear "
                     f"from it is that old too")
    rep.info["feed_file"] = str(feed_path)
    posted: Dict[str, set[str]] = {}
    confirmed_teams: set[str] = set()
    for game in feed.get("games", []) or []:
        for side in ("away", "home"):
            block = game.get(side) or {}
            team = str(block.get("team_abbrev") or "").upper()
            if not team:
                continue
            names = {_norm_name(p.get("name")) for p in (block.get("lineup") or [])}
            pp = (block.get("probable_pitcher") or {}).get("name")
            if pp:
                names.add(_norm_name(pp))
            posted.setdefault(team, set()).update(names)
            if str(block.get("lineup_status") or "").lower() == "confirmed":
                confirmed_teams.add(team)
    absent: List[str] = []
    unconfirmed: Dict[str, int] = {}
    for e in entries:
        for pid in e.cells:
            row = salary.get(pid)
            if not row:
                continue
            team = str(row.get("TeamAbbrev") or "").upper()
            if team not in confirmed_teams:
                # R46: this branch was pure silence, and that silence is the
                # 2026-08-03 incident. ARI had not posted at build time, so the
                # feed said tbd, so every ARI slot skipped this check without a
                # word -- and a platoon-projected bench player (Tyler Locklear)
                # rode two certified entries to the edge of upload. Nothing on
                # disk could have caught it at that minute; what was missing is
                # the statement that the check did not cover those slots. It
                # stays SOFT: a genuinely unposted team pre-lock is normal, R27
                # ships on warn by design, and hard-failing here would block
                # legal builds. It is now loud, and it names what to re-check.
                unconfirmed[team] = unconfirmed.get(team, 0) + 1
                continue
            if _norm_name(row.get("Name")) not in posted.get(team, set()):
                absent.append(f"{e.entry_id}: {row.get('Name')} ({team}) is not in "
                              f"{team}'s confirmed lineup or probables")
    uniq = sorted(set(absent))
    rep.info["feed_absent"] = uniq
    rep.info["feed_unconfirmed_teams"] = dict(sorted(unconfirmed.items()))
    if unconfirmed:
        rep.warn(f"{len(unconfirmed)} rostered team(s) have no confirmed lineup in "
                 f"this feed, so their slots were NOT cross-checked: "
                 + ", ".join(f"{t} ({n} slot{'s' if n > 1 else ''})"
                             for t, n in sorted(unconfirmed.items()))
                 + ". Re-paste and re-run this check once they post; a "
                   "platoon-projected bench player is invisible until then")
    if uniq:
        message = (f"{len(uniq)} rostered player(s) absent from a confirmed posted "
                   f"lineup: " + "; ".join(uniq[:10]))
        rep.fail(message) if strict else rep.warn(message)


# --------------------------------------------------------------------------
# advisory
# --------------------------------------------------------------------------

def advisory(contest: str, entries: Sequence[EntryRow],
             salary: Dict[str, Dict[str, str]]) -> Dict[str, Any]:
    filled = [e for e in entries if not e.is_blank]
    n = len(filled)
    out: Dict[str, Any] = {"entries": len(entries), "filled": n}
    if not n:
        return out
    counts = collections.Counter(pid for e in filled for pid in e.cells if pid)
    out["top_exposure"] = [
        {"player": salary.get(pid, {}).get("Name", pid),
         "team": salary.get(pid, {}).get("TeamAbbrev", "?"),
         "n": c, "pct": round(100.0 * c / n, 1)}
        for pid, c in counts.most_common(8)
    ]
    persons = {}
    for pid, row in salary.items():
        persons[pid] = f"{_norm_name(row.get('Name'))}|{str(row.get('TeamAbbrev') or '').upper()}"
    sets = [frozenset(persons.get(pid, pid) for pid in e.cells if pid) for e in filled]
    dupe_groups = [ids for ids, c in collections.Counter(sets).items() if c > 1]
    out["duplicate_lineup_groups"] = len(dupe_groups)
    if n > 1:
        overlaps = collections.Counter()
        for i in range(n):
            for j in range(i + 1, n):
                overlaps[len(sets[i] & sets[j])] += 1
        out["overlap_histogram"] = dict(sorted(overlaps.items()))
    locks = [parse_game_info_datetime(salary[pid].get("Game Info"))
             for e in filled for pid in e.cells if pid in salary]
    locks = [t for t in locks if t]
    if locks:
        out["first_lock_et"] = min(locks).strftime("%Y-%m-%d %H:%M ET")
    return out


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def run(args: argparse.Namespace) -> Tuple[Report, Dict[str, Any]]:
    rep = Report()
    entries_path = Path(args.entries)
    contest, slots, entries, raw_rows, entry_id_rows = load_entries(entries_path)
    rep.info["contest_type"] = contest
    rep.info["roster_width"] = len(slots)
    rep.info["entries_file"] = str(entries_path)
    rep.info["entries_sha256"] = sha256_of(entries_path)

    if getattr(args, "expect_sha256", None):
        # R20a. The brief records delivered_sha256; this pairs the file Ben
        # actually selects at upload with the one the session reported. A
        # prefix under 12 chars is refused rather than matched, because a
        # check that can pass by accident is not a check.
        expected = str(args.expect_sha256).strip().lower()
        if len(expected) < 12 or any(c not in "0123456789abcdef" for c in expected):
            raise ValueError(
                "--expect-sha256 needs at least 12 hex characters; a shorter "
                "prefix is too easy to match by accident")
        actual = rep.info["entries_sha256"]
        if actual == expected or actual.startswith(expected):
            rep.info["expect_sha256"] = "matched"
        else:
            rep.fail(f"these bytes hash {actual[:12]} but --expect-sha256 says "
                     f"{expected[:12]}; the file about to be uploaded is not "
                     f"the one the brief reported. Do not upload without "
                     f"resolving which delivery this is")

    if args.expect_contest_type and args.expect_contest_type.lower() != contest:
        rep.fail(f"declared contest type '{args.expect_contest_type}' but the file's "
                 f"header geometry is {contest}")

    if args.salary:
        salary_path = Path(args.salary)
    else:
        resolved = resolve_salary_from_promoted_run(REPO_ROOT / "runs")
        if resolved is None:
            raise ValueError(
                "no --salary given and no salary snapshot found under the promoted "
                "run's inputs/; pass --salary explicitly")
        salary_path = resolved
        rep.info["salary_source"] = "promoted run snapshot"
    rep.info["salary_file"] = str(salary_path)
    salary = load_salary(salary_path)

    check_contest_identity(contest, entries, rep)
    check_row_shape(entries, entry_id_rows, len(slots), rep, args.expect_entries)
    check_pool_membership(entries, salary, parse_embedded_pool(raw_rows),
                          args.min_pool_overlap, rep)
    check_status(entries, salary, rep)
    details = check_legality(contest, slots, entries, salary, rep)

    manifest = Path(args.manifest) if args.manifest else None
    if manifest is None:
        # The manifest sits next to the delivered file. Finding it without being
        # told is the difference between a cross-check that runs at T-5 and one
        # that runs when the operator remembers a flag.
        sibling = entries_path.resolve().parent / "upload_manifest.json"
        if sibling.exists():
            manifest = sibling
            rep.info["manifest_source"] = "found next to the entries file"
    delivered = is_delivered_file(entries_path)
    rep.info["delivered_file"] = delivered
    if args.no_manifest:
        rep.info["manifest_source"] = "waived by --no-manifest"
        rep.warn("manifest cross-check waived by --no-manifest; nothing on disk "
                 "states this file is the one to upload")
    elif manifest is not None:
        rep.info["manifest_file"] = str(manifest)
        check_manifest(entries_path, entries, manifest, rep, delivered=delivered)
    elif delivered:
        # R3(b). The manifest generation path is fail-open by design, so a
        # certified file can land in outputs/ with no record and nothing says
        # so. Failing closed HERE closes that hole without ever letting
        # bookkeeping break a build.
        rep.fail(f"no upload manifest for this delivered file: nothing at "
                 f"{entries_path.resolve().parent / 'upload_manifest.json'} states "
                 f"which delivery these bytes are. Re-run the build, or pass "
                 f"--no-manifest to waive it deliberately")
    if args.parent:
        check_parent(entries, Path(args.parent), rep)

    feed_path = Path(args.feed) if args.feed else resolve_feed_for_slate(entries, salary, rep)
    if feed_path is not None and feed_path.exists():
        check_feed(entries, salary, feed_path, not args.feed_lenient, rep)
    elif feed_path is not None:
        rep.warn(f"feed {feed_path} does not exist; posted-lineup cross-check skipped")
    else:
        rep.warn("no lineups feed resolved; the posted-lineup cross-check did "
                 "not run and a benched starter would not be caught here")

    report = {
        "tool": "preflight_upload", "version": VERSION,
        "passed": not rep.failures,
        "failures": rep.failures, "warnings": rep.warnings,
        "info": rep.info, "lineups": details,
        "advisory": advisory(contest, entries, salary),
    }
    return rep, report


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--entries", required=True, help="the file about to be uploaded")
    ap.add_argument("--salary", help="DKSalaries.csv; defaults to the promoted run's snapshot")
    ap.add_argument("--manifest", help="outputs/<date>/upload_manifest.json")
    ap.add_argument("--no-manifest", action="store_true",
                    help="waive the manifest cross-check for a file that was "
                         "never recorded as a delivery")
    ap.add_argument("--parent", help="the delivered file this one refines")
    ap.add_argument("--feed", help="lineups_feed.json; auto-resolved for the slate date")
    ap.add_argument("--feed-lenient", action="store_true",
                    help="demote posted-lineup absences from failure to warning")
    ap.add_argument("--feed-strict", action="store_true",
                    help=argparse.SUPPRESS)  # R4: strict is the default; kept so
                    # an existing invocation or script does not die on the flag.
    ap.add_argument("--expect-contest-type", choices=["classic", "showdown"],
                    help="fail if the file's geometry is not this")
    ap.add_argument("--expect-entries", type=int,
                    help="reserved-entry count this file must hold; catches truncation")
    ap.add_argument("--expect-sha256",
                    help="hard-fail unless the entries file hashes to this "
                         "sha256 (full hex, or a prefix of 12+ chars); pairs "
                         "the upload with the brief's delivered_sha256 (R20a)")
    ap.add_argument("--min-pool-overlap", type=float, default=0.95)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="print failures and exit 4 (acknowledged, not clean); "
                         "for when the clock beats the fix")
    args = ap.parse_args(argv)

    try:
        rep, report = run(args)
    except (OSError, ValueError) as exc:
        print(f"ERROR  {exc}", file=sys.stderr)
        return 3

    # R34: 'upload_ready' is reserved for a certified export (CLAUDE.md), and this
    # tool checks bytes, not certification. It never read the manifest's
    # `certification` field, so a review-grade Showdown file that is mechanically
    # clean was stamped 'upload_ready' over `certification: review_grade`. That
    # already happened twice on 2026-07-29. Passing every byte-level check is not
    # certification and must not be labelled as it.
    certification = str(report["info"].get("recorded_certification") or "").strip()
    # R52: the exit code comes from the shared contract; only the LABEL is local.
    code = verdict_exit_code(report["failures"], args.force)
    if not report["failures"]:
        if certification and certification != "certified":
            verdict = "review_ready"
            report["verdict_note"] = (
                f"every file-level check passed, but the manifest records "
                f"certification={certification!r}, so this is NOT upload_ready: "
                f"that label is reserved for a run where workflow_valid, "
                f"selection_certified and allocation_certified all passed. "
                f"Showdown ships review-grade by design.")
        else:
            verdict = "upload_ready"
    elif args.force:
        verdict = "acknowledged"
    else:
        verdict = "blocked"
    report["verdict"] = verdict
    manifest_file = report["info"].get("manifest_file")
    if manifest_file:
        stamp_manifest_status(Path(manifest_file), report["info"]["entries_sha256"],
                              verdict, report["failures"], rep)

    if args.json:
        print(json.dumps(report, indent=1, default=str))
    else:
        info = report["info"]
        print(f"preflight_upload v{VERSION}  {info['contest_type']} "
              f"{report['advisory']['entries']} entries  "
              f"sha256={info['entries_sha256'][:12]}")
        print(f"  salary: {info['salary_file']}"
              + (f"  [{info['salary_source']}]" if info.get("salary_source") else ""))
        overlap = info.get("embedded_pool_overlap")
        if overlap is not None:
            print(f"  embedded pool overlap: {overlap:.1%} of {info['embedded_pool_size']}")
        adv = report["advisory"]
        if adv.get("first_lock_et"):
            print(f"  first lock: {adv['first_lock_et']}")
        if adv.get("top_exposure"):
            top = ", ".join(f"{x['player']} {x['pct']}%" for x in adv["top_exposure"][:5])
            print(f"  top exposure: {top}")
        if adv.get("duplicate_lineup_groups"):
            print(f"  duplicate lineup groups: {adv['duplicate_lineup_groups']}")
        if adv.get("overlap_histogram"):
            print(f"  lineup overlap histogram: {adv['overlap_histogram']}")
        if info.get("feed_file"):
            age = info.get("feed_age_minutes")
            age_text = (f"{age / 60:.1f}h old" if isinstance(age, (int, float))
                        else "age unknown")
            print(f"  feed: {Path(info['feed_file']).name} ({age_text})")
        print()
        for w in report["warnings"]:
            print(f"WARN  {w}")
        for f in report["failures"]:
            print(f"FAIL  {f}")
        if not report["failures"]:
            print(f"PASS  {adv['entries']} {info['contest_type']} entries, "
                  f"all hard checks clean")
        elif args.force:
            print(f"\nACKNOWLEDGED  {len(report['failures'])} hard failure(s) "
                  f"overridden by --force; this file is not blocked and it is not "
                  f"clean. Exit 4.")

    return code


if __name__ == "__main__":
    raise SystemExit(main())
