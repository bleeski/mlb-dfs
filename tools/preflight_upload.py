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
  --brief     the build brief for this delivery, matched to these bytes by
              delivered_sha256 among the sibling build_brief*.json files. It is
              read for ONE field, declared_pitchers, so a legally rostered
              declared arm is acknowledged instead of failed (R114). Nothing
              else in the brief affects any verdict, and a brief that cannot be
              found costs one info line. --declare-pitcher ID=role passes the
              same fact by hand when there is no run to read.

Optional, never blocking on its own absence:
  --parent    diff contest assignment against the file this one refines
  --expect-sha256  hard-fail unless the file hashes to the given sha256 (full
              hex or a prefix of 12+ chars). The brief records
              delivered_sha256; this is the flag that pairs the upload with
              it at T-5 (R20a)

Advisory prints (never affect the exit code): exposure, lineup-overlap
histogram, first lock, and lineup duplication split by contest (R128) --
duplicates WITHIN a contest is the finding, duplicates ACROSS contests is
information, and the two count different objects and never sum to a total.

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

# R239(b)/R266, corrected 2026-08-29 in the same session R266 shipped. The
# per-contest captain bar is this NAMED control, mirrored from
# showdown.DEFAULT_MAX_CPT_PER_CONTEST and pinned equal by test.
#
# R266 originally derived the bar from the pct above, because the named control
# did not exist yet. Once it did, the two disagreed: at n=3 the engine
# deliberately builds to 2 while the pct reading warns above 1, so the checker
# would have flagged files the builder was specified to produce -- noise on the
# one surface whose job is to be believed at T-5, and this project's named
# two-implementations-of-one-rule failure arriving between the builder and the
# checker. Caught by a test written to compare them.
DEFAULT_MAX_CPT_PER_CONTEST = 2

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
# A posted MLB lineup is nine hitters. R46 round 2 subtracts the posted count
# from this to learn how many slots on a partially-posted side are still unknown,
# which is the only arithmetic that can make a projected fill provably wrong.
POSTED_LINEUP_SLOTS = 9
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


def slot_admits(row: Mapping[str, Any], slot: str) -> bool:
    """Does this salary row's ``Roster Position`` admit this DK column?

    R267(a)'s R233 enumeration. DK writes multi-position eligibility as a
    slash-joined token ("OF/1B"), and this repo derived that rule from the raw
    string at two places once `repair_entry.py` arrived: `check_legality`'s
    inline comprehension below, which is what a delivered file is CHECKED
    against, and the repair filter's own copy, which is what a replacement is
    CHOSEN by. Two definitions of the same rule, on the two sides of one
    write, is R167/R159's class exactly -- and the failure mode is specific
    rather than theoretical: the chooser drifting looser than the checker
    means a repair that picks a player the preflight then rejects, under a
    lock clock, which is the worst moment available to discover it. One owner,
    here, because this file is where the rule is enforced against money.
    """
    roles = {r.strip().upper()
             for r in str(row.get("Roster Position") or "").split("/")}
    return str(slot).strip().upper() in roles


def person_key(row: Mapping[str, Any]) -> str:
    """One human, whatever role their salary row is priced for.

    R234. A DK draftable id is a ROLE, not a person: a Showdown export lists
    everybody twice, a CPT row and a UTIL row carrying different ids and
    different salaries, so anything that counts ids counts one player as two.
    Name-plus-team is the identity that survives the split, and it is the one
    every duplication, exposure and captain-pricing check in this file needs.

    R233 enumeration. This expression was written out by hand at FOUR sites
    before R234 and the class had no fifth::

        $ grep -n "_norm_name(.*)}|" tools/preflight_upload.py
        717:  _showdown_legality, captain -> UTIL sibling lookup
        740:  check_legality, the salary_by_person index
        770:  check_legality, within-lineup duplicate-person identity
        1545: advisory, the person map behind duplicates and overlap

    All four now call this, as does ``advisory``'s exposure count, which is the
    site that had never had it at all.
    """
    return (f"{_norm_name(row.get('Name'))}|"
            f"{str(row.get('TeamAbbrev') or '').upper()}")


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


def salary_export_is_showdown(salary: Mapping[str, Mapping[str, str]]) -> bool:
    """DK prices a CPT row per player on a Showdown export, never on a Classic one."""
    for row in salary.values():
        roles = {r.strip().upper()
                 for r in str(row.get("Roster Position") or "").split("/")}
        if "CPT" in roles:
            return True
    return False


def resolve_salary_from_promoted_run(
    runs_root: Path,
    contest: Optional[str] = None,
    rostered: Optional[Iterable[str]] = None,
) -> Tuple[Optional[Path], str]:
    """(snapshot, refusal reason) for the promoted run, CHECKED against the file.

    The engine snapshots inputs per run; prefer that over the staged copy. The
    staged ``data/slates/<date>/`` copy is shared and date-keyed, so a later
    build for the same date overwrites it and orphans verification of what was
    actually delivered. The run snapshot cannot be clobbered that way.

    ``run_id`` resolves first because the recorded ``run_dir`` is an absolute
    path from the session that wrote it, and that mount is gone in every later
    session.

    R234. What this reads is a POINTER -- ``runs/latest_valid_run.json``, last
    writer wins -- and it used to hand back whatever that pointer named without
    ever looking at the file being verified. On a Showdown delivery that is not
    a race but the expected behaviour: ``build_slate.py`` promotes no run, so
    the pointer necessarily names some other build. Three field hits, all on
    clean delivered files at the last check before the money boundary:
    2026-08-20 ``1835_1g_sd`` and ``2010_1g_sd`` each resolved to a concurrent
    session's Classic run and exited 2 on ``27 rostered player ID(s) absent``;
    2026-08-24 ``texcws_sd`` reached back a whole day to
    ``20260823T200036Z_0fe4a983``. It misfires the other direction too, a
    Classic preflight taking a stale prior run, whenever the timing lines up.

    So the candidate is now checked on the two facts the caller already holds --
    contest geometry and the rostered ids -- and a mismatch REFUSES, naming what
    disagreed. Both are facts that would hard-fail one call later, so this
    weakens no check: it turns a confident wrong answer into "pass --salary",
    which costs one flag instead of a delivery.
    """
    pointer = runs_root / "latest_valid_run.json"
    try:
        data = json.loads(pointer.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, f"no readable run pointer at {pointer}"
    candidates = []
    run_id = str(data.get("run_id") or "").strip()
    if run_id:
        candidates.append(runs_root / run_id)
    recorded = str(data.get("run_dir") or "").strip()
    if recorded:
        candidates.append(Path(recorded))
    snap: Optional[Path] = None
    for base in candidates:
        try:
            probe = base / "inputs" / "DKSalaries.csv"
            if probe.exists():
                snap = probe
                break
        except OSError:
            continue
    if snap is None:
        return None, (f"the run pointer {pointer} names no run carrying "
                      f"inputs/DKSalaries.csv")
    try:
        salary = load_salary(snap)
    except (OSError, ValueError) as exc:
        return None, f"{snap} does not read as a salary file ({exc})"

    snap_contest = "showdown" if salary_export_is_showdown(salary) else "classic"
    if contest and snap_contest != contest:
        return None, (f"the promoted run's snapshot {snap} is a {snap_contest} "
                      f"export and these entries are {contest} geometry")
    missing = sorted({str(pid) for pid in (rostered or ()) if pid} - set(salary))
    if missing:
        return None, (f"the promoted run's snapshot {snap} is missing "
                      f"{len(missing)} of this file's rostered player ID(s) "
                      f"({missing[:5]}), so it is a different slate")
    return snap, ""


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


def parse_as_of(value: Any) -> datetime:
    """``--as-of`` -> aware datetime. Bare local times are read as ET.

    Accepts a full ISO timestamp (``2026-09-01T19:56:00-04:00``), an ISO
    timestamp with no offset, or ``HH:MM``/``HH:MM:SS`` alone, which takes
    today's date. A naive value is stamped Eastern, because every other clock in
    this file is: the salary file's ``Game Info`` carries ET and nothing else,
    and guessing UTC for a bare "19:56" would move the comparison four hours and
    silently pass exactly the file this check exists to stop.
    """
    text = str(value or "").strip()
    if not text:
        raise ValueError("--as-of given with no value")
    if re.fullmatch(r"\d{1,2}:\d{2}(:\d{2})?", text):
        today = datetime.now(tz=_eastern_tz(datetime.now().month, datetime.now().day))
        parts = [int(p) for p in text.split(":")]
        while len(parts) < 3:
            parts.append(0)
        stamped = today.replace(hour=parts[0], minute=parts[1], second=parts[2],
                                microsecond=0)
        return stamped
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(
            f"--as-of {text!r} is not an ISO timestamp or HH:MM: {exc}") from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=_eastern_tz(parsed.month, parsed.day))
    return parsed


def check_started_games(entries: Sequence[EntryRow],
                        salary: Dict[str, Dict[str, str]],
                        as_of: datetime, rep: Report) -> None:
    """Hard check: no roster slot holds a player whose game has already begun.

    R287, 2026-09-01. The defect this closes cost a slate and it is the worst
    kind, because the tool reported PASS. `outputs/2026-09-01/DKEntries_1940_9g.csv`
    (sha256 947e09856d0f...) held 151 roster slots drawn from DET@MIN, MIA@KC and
    MIL@CHC, all of which started at 19:40 ET. Preflight ran against it at ~19:56
    ET, PRINTED `first lock: 2026-09-01 19:40 ET`, and exited 0 with "all hard
    checks clean". A second file that night carried 78 such slots and also
    cleared every check. DK would have rejected both. The tool computed the first
    lock, displayed it, and never compared it -- or any other game's start -- to
    the clock.

    Three properties, each deliberate:

    - It reads the SALARY FILE only. `verify_export.py` has this rule already and
      it lives on the swap path behind `--parent`, so a freshly built post-lock
      file was checked by nobody; and its version needs a lineups feed, which is
      exactly what is missing at 19:56 on a slate that went sideways. `Game Info`
      is in the file the operator is already passing.
    - It HARD FAILS. A warning at the money boundary is a warning the clock will
      talk someone past. `--force` still exists and still exits 4.
    - `--as-of` exists for replay determinism. Absent, it is now(), because the
      question this check asks is about the moment of upload.

    A row whose `Game Info` does not parse is named in `started_unparsed` rather
    than passed or failed, on R237's rule: an unreadable start time is not
    evidence the game has not begun.
    """
    started: Dict[str, List[str]] = collections.defaultdict(list)
    unparsed: List[str] = []
    affected_entries: set[str] = set()
    slots = 0
    for e in entries:
        for pid in e.cells:
            if not pid:
                continue
            row = salary.get(pid)
            if not row:
                continue
            start = parse_game_info_datetime(row.get("Game Info"))
            if start is None:
                unparsed.append(f"{row.get('Name', pid)} ({pid})")
                continue
            if start <= as_of:
                slots += 1
                affected_entries.add(e.entry_id)
                game = _matchup(row.get("Game Info")) or "?"
                started[game].append(
                    f"{e.entry_id}: {row.get('Name', pid)} "
                    f"({row.get('TeamAbbrev', '?')})")
    rep.info["as_of_et"] = as_of.astimezone(
        _eastern_tz(as_of.month, as_of.day)).strftime("%Y-%m-%d %H:%M ET")
    rep.info["started_slots"] = slots
    rep.info["started_games"] = sorted(started)
    rep.info["started_entries"] = len(affected_entries)
    rep.info["started_unparsed"] = sorted(set(unparsed))
    if unparsed:
        rep.warn(f"{len(set(unparsed))} rostered player(s) have no parseable "
                 f"Game Info start time, so the started-game check could not "
                 f"read them: {sorted(set(unparsed))[:5]}")
    if slots:
        examples = []
        for game in sorted(started):
            hits = sorted(set(started[game]))
            examples.append(f"{game} ({len(hits)}): {'; '.join(hits[:3])}"
                            + (" ..." if len(hits) > 3 else ""))
        rep.fail(
            f"{slots} roster slot(s) across {len(affected_entries)} entr"
            f"{'y' if len(affected_entries) == 1 else 'ies'} hold a player whose "
            f"game has ALREADY STARTED as of {rep.info['as_of_et']}; DK rejects "
            f"these. Games: {', '.join(sorted(started))}. "
            + " | ".join(examples))


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
        # R288, 2026-09-01. WARN, not FAIL. DK does not prohibit this and the
        # evidence is DK's own scored output rather than a reading of its rules
        # page: across 22 archived slate dates, 19,072 of 102,201 fully-resolvable
        # DK Classic entries (18.7%) roster a hitter facing a rostered SP, and
        # contest-standings-192464310 (2026-07-19, 1,486 entries) has ranks 1, 2
        # AND 3 all holding Ryan McMahon (NYY) alongside Yamamoto (LAD) starting
        # against NYY. DK accepted, scored and paid those. The frequency is
        # slate-size dependent -- 62.5% of entries on that 2-game slate, 3.2% on
        # the 12-game 2026-08-11 slate -- which is the tell that on a small slate
        # the convention forbids most of the legal space.
        #
        # It is a DFS CONVENTION about negative correlation, and a good one by
        # default. Enforcing it here as a hard failure meant the only way to ship
        # the construction Ben asked for was --force, which reports the file as
        # having been pushed past a failing check. That is false about a legal
        # roster, and it teaches a session to normalise --force, which has to stay
        # frightening. The control lives in the optimizer as
        # `max_opposing_hitters_per_sp` (default 0, so today's behaviour is
        # the default); this line's job is to REPORT what the delivered file
        # actually did.
        #
        # Measured cost of the wall on 1940_9g: a hand builder carrying the same
        # convention as a hard rule had Gabriel Hughes at 54% exposure, which
        # banned every BAL bat from 20 of 37 lineups. BAL was the highest implied
        # team total on the slate (~5.9, in an 11.0-total game at Coors) and
        # finished with 2 roster slots out of 370. A pitcher-selection error
        # became a hitter-distribution error through a constraint nobody
        # re-examined.
        rep.warn(f"{entry.entry_id}: hitter opposing a rostered SP "
                 f"({len(clashes)}: {'; '.join(clashes)}) -- DK-LEGAL. This is the "
                 f"anti-correlation CONVENTION, not a DK rule; see "
                 f"max_opposing_hitters_per_sp")
        # The COUNT, so the portfolio-level fact is one line rather than N
        # warnings a reader under a clock has to add up.
        block = rep.info.setdefault(
            "opposing_hitters", {"entries": 0, "slots": 0, "by_entry": {}})
        block["entries"] += 1
        block["slots"] += len(clashes)
        block["by_entry"][entry.entry_id] = len(clashes)


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
    siblings = salary_by_person.get(person_key(cpt), [])
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
        salary_by_person[person_key(row)].append(row)

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

        identity = [person_key(p) for p in players]
        if len(set(identity)) != width:
            dupes = sorted({p.get("Name") for p, k in zip(players, identity)
                            if identity.count(k) > 1})
            rep.fail(f"{e.entry_id}: the same person occupies two slots ({dupes})")
        detail["duplicate_person"] = len(set(identity)) != width

        ineligible = [
            f"{players[i].get('Name')}->{slots[i]}"
            for i in range(width)
            if not slot_admits(players[i], slots[i])
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


def match_manifest_record(records: Sequence[Any], digest: str,
                          name: str) -> Optional[Dict[str, Any]]:
    """The manifest row that describes THESE bytes AT THIS PATH (R129).

    Both readers of the manifest in this file used to ask a narrower question --
    "the first row whose sha256 equals these bytes" -- and that was an adequate
    proxy only while one set of bytes had exactly one row. ``tools/promote_run.py``
    makes two rows for one sha256 ORDINARY: a run's original delivery, later
    superseded, and the re-promotion that brought the same bytes back. Two live
    defects fell out of first-wins the moment re-promotion existed, both observed
    on a copy of the real 2026-08-15 manifest:

    1. ``check_manifest`` read the OLD superseded row and reported a file that is
       current as superseded, which is the exact block R129 exists to make
       escapable, now firing on the escape.
    2. ``stamp_manifest_status`` wrote ``upload_ready`` onto that same old row --
       a SUPERSEDED record resurrected to the answer to "which file do I upload".
       That is the lost-supersession failure R36 F6m names, arriving through a
       different door than the concurrency one it was filed for.

    One matcher, used by both, so the two cannot drift: prefer rows that name this
    filename, then prefer a row that is not superseded, then take the newest,
    because rows are appended in order. With nothing live for this path the newest
    superseded row is the honest answer and the caller's block still fires.
    """
    same_bytes = [r for r in records
                  if isinstance(r, dict) and str(r.get("sha256") or "") == digest]
    same_path = [r for r in same_bytes
                 if Path(str(r.get("delivered_file") or "")).name == name]
    pool = same_path or same_bytes
    if not pool:
        return None
    live = [r for r in pool if str(r.get("status") or "") != "superseded"]
    return (live or pool)[-1]


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
    match = match_manifest_record(records, digest, name)
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
    # R275, 2026-08-31. Absence is not agreement. This guard and the contest_ids
    # guard below were each written `if <field> and <field> != <expected>`, so a
    # row that OMITS the field skipped the check instead of failing it, and a row
    # that never recorded the fact read exactly like a row that agrees. That is
    # not a hypothetical thin record: `record_delivery` makes both fields
    # optional and its own defaults produce exactly these values --
    # `entries` writes None and `contest_ids or []` writes an EMPTY LIST
    # (upload_manifest.py:275,273) -- so any `deliver(**record_kwargs)` caller
    # that omits either writes a row this checker reads as corroboration.
    # The type test is part of the same fact: a non-integer count cannot be
    # compared either, and `bool` is excluded because True is an int in Python
    # and would otherwise compare as 1.
    recorded_entries = match.get("entries")
    if isinstance(recorded_entries, bool) or not isinstance(recorded_entries, int):
        rep.fail(f"manifest records entries={recorded_entries!r}, which is not an "
                 f"integer count, so the truncation cross-check could not run; "
                 f"the file holds {len(entries)}. Re-record the delivery rather "
                 f"than uploading against a row too thin to corroborate it")
    elif recorded_entries != len(entries):
        rep.fail(f"manifest records {recorded_entries} entries, file holds "
                 f"{len(entries)}; a short file is a truncated write")
    if str(match.get("status") or "") == "superseded":
        # R129. The block is right and it stays. What it lacked was the way out:
        # it named only the path that beat this file, so an operator holding a
        # measurably better superseded variant had no legal move and reached for
        # --no-manifest, which waives the cross-check on a file that DOES have a
        # record. The run id is the operator's actual next move, so the message
        # carries it and the command that uses it.
        run_id = str(match.get("run_id") or "")
        remedy = (f" To deliver these bytes anyway, re-promote the run that made "
                  f"them: python tools/promote_run.py --run-id {run_id}"
                  if run_id else
                  " The record carries no run_id, so there is no run to re-promote "
                  "from; rebuild rather than waiving the manifest")
        rep.fail(f"manifest marks this file superseded by "
                 f"{match.get('superseded_by')}; do not upload it.{remedy}")
    # R275(a). See the note on the entries guard above: the empty case is the
    # writer's own default, not a legacy shape.
    recorded = {str(c) for c in (match.get("contest_ids") or [])}
    actual = {e.contest_id for e in entries}
    if not recorded:
        rep.fail(f"the manifest row for {name} records no contest_ids, so the "
                 f"contest-assignment cross-check could not run; the file "
                 f"assigns {sorted(actual)}. A row that never recorded which "
                 f"contests it was for is not evidence that it agrees. "
                 f"Re-record the delivery rather than uploading against it")
    elif recorded != actual:
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


def committed_manifest_status(manifest_path: Path, entries_sha256: str,
                              entries_name: str = "") -> Optional[str]:
    """Re-read the manifest from disk and return the status now on this file's row.

    R176 rider, 2026-08-30. The only way to know a stamp PERSISTED is to read it
    back: ``stamp_manifest_status`` can return early on an unreadable manifest or
    an unmatched row, and its write failure was a warning. None means "no row for
    these bytes", which is a different answer from a row carrying a status.
    """
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    records = payload if isinstance(payload, list) else payload.get("deliveries", [])
    target = match_manifest_record(records, str(entries_sha256), str(entries_name))
    if target is None:
        return None
    return str(target.get("status") or "")


def stamp_manifest_status(manifest_path: Path, entries_sha256: str,
                          status: str, failures: Sequence[str], rep: Report,
                          entries_name: str = "") -> Dict[str, Any]:
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

    R129. The row is resolved by ``match_manifest_record`` rather than by the
    first sha256 hit, and a ``superseded`` row keeps its status. ``entries_name``
    is what lets the matcher prefer the row for THIS path when one set of bytes
    has more than one row; omitted, it degrades to the old sha256-only pool, which
    is why every existing caller keeps working.

    Deliberately narrow: it only ever updates a record whose sha256 already
    equals these bytes, it never creates one, and a write failure is a warning.
    No engine import; the manifest is plain JSON.
    """
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"stamped": False, "status": None,
                "reason": f"manifest at {manifest_path} is unreadable ({exc})"}
    records = payload if isinstance(payload, list) else payload.get("deliveries", [])
    target = match_manifest_record(records, str(entries_sha256), str(entries_name))
    if target is None:
        return {"stamped": False, "status": None,
                "reason": f"no manifest record in {manifest_path} matches these bytes"}
    record_status = status_for_verdict(status)
    if str(target.get("status") or "") == "superseded":
        # R129. A supersession is a fact about this record's relationship to a
        # LATER delivery; a preflight verdict is a fact about bytes. Overwriting
        # the first with the second is how a superseded row came back as
        # 'upload_ready' and as 'blocked', and after either write the supersession
        # block can never fire for that file again. The verdict is not lost: it
        # lands under 'preflight' below, where the two facts sit side by side.
        rep.info["manifest_status_held_superseded"] = True
        rep.warn(f"this file's manifest record is superseded; the preflight "
                 f"verdict {status!r} was recorded on it but the status stays "
                 f"'superseded'. Re-promote its run to deliver these bytes")
    elif record_status in STATUS_VALUES:
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
        # The status the ROW now carries, which on a superseded row is
        # 'superseded' and not `record_status` -- that branch deliberately holds
        # the status and records the verdict beside it. Returning `record_status`
        # here would make the caller's read-back comparison fail on the one case
        # the code is getting right.
        return {"stamped": True, "status": str(target.get("status") or ""),
                "reason": ""}
    except OSError as exc:
        rep.warn(f"manifest status not stamped ({exc}); the verdict is this "
                 f"output only")
        return {"stamped": False, "status": None,
                "reason": f"the manifest write failed ({exc})"}


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


DEFAULT_DECLARED_ROLE = "declared_probable_sp"


def parse_declared_pitcher_args(values: Sequence[str]) -> Dict[str, str]:
    """``--declare-pitcher 43815489=viable_bulk_or_alt_sp`` -> {id: role}.

    Deliberately the same grammar as ``build_slate.py``'s flag of the same
    name, bare-id default included: the operator who declared an arm to the
    BUILD types the same thing here, and one flag spelled two ways in two tools
    is a defect waiting for a T-10.

    The role is kept verbatim and never validated against a vocabulary. The
    engine owns that list (``dk_entries_manager.ALLOWED_PITCHER_ROLES``) and
    this tool imports no engine module by design, so a copy here would be a
    second definition of one rule that can drift out of agreement with the
    first. What the role has to do is NAME itself in the warning, and any
    non-empty string does that.
    """
    out: Dict[str, str] = {}
    for raw in values or ():
        text = str(raw).strip()
        pid, _, role = text.partition("=")
        pid, role = _digits(pid), role.strip()
        if not pid:
            raise ValueError(
                f"--declare-pitcher wants a DK player ID, optionally ID=role, "
                f"got {raw!r}. Example: 43815489=viable_bulk_or_alt_sp. A bare "
                f"id means {DEFAULT_DECLARED_ROLE}, the same default the engine "
                f"and build_slate.py apply")
        out[pid] = role or DEFAULT_DECLARED_ROLE
    return out


def resolve_declared_pitchers(entries_path: Path, entries_sha256: str,
                              explicit: Optional[str], rep: Report,
                              ) -> Dict[str, str]:
    """Read ``declared_pitchers`` off the build brief for THESE bytes.

    R114. The build records the declaration; this gate never saw it. On
    2026-08-12 (2210_2g, run 20260813T005233Z_1b5d3a4a) Mason Black was
    rostered on a declaration, all three certification gates passed, and this
    tool exited 2 twelve times on "not in KC's confirmed lineup or probables".
    The only way through was --force, which is exit 4 on a failure the operator
    knew was spurious -- and a gate that hard-fails legal files teaches the
    operator to force past it.

    The brief is matched by ``delivered_sha256``, not by name or by mtime.
    ``outputs/2026-08-12/`` held eight briefs for four deliveries; the newest
    and the alphabetically first both belong to a DIFFERENT slate whose
    declarations are empty, so any resolution weaker than the hash silently
    reads the wrong slate's facts and this check goes quiet again.

    Several briefs may record one delivery (a rebuild that re-delivers the same
    bytes). Agreement is the normal case. Where they DISAGREE the intersection
    wins, because every id dropped here restores a hard failure and every id
    kept removes one: on a contradictory record the safe direction is the one
    that keeps the gate closed.
    """
    if explicit:
        briefs = [Path(explicit)]
        how = "given by --brief"
    else:
        briefs = sorted(entries_path.resolve().parent.glob("build_brief*.json"))
        how = "matched by delivered_sha256 among sibling build_brief*.json"
    matched: List[Tuple[Path, Dict[str, str]]] = []
    for path in briefs:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            if explicit:
                rep.warn(f"--brief {path} unreadable ({exc}); declared pitchers "
                         f"were not read and a declared arm will fail as absent")
            continue
        if not isinstance(data, dict):
            continue
        if not explicit:
            recorded = str(data.get("delivered_sha256") or "").strip().lower()
            if not recorded or recorded != entries_sha256:
                continue
        raw = data.get("declared_pitchers") or {}
        if not isinstance(raw, Mapping):
            continue
        matched.append((path, {_digits(k): str(v) for k, v in raw.items()
                               if _digits(k) and str(v).strip()}))
    if not matched:
        rep.info["declared_pitchers_source"] = f"none found ({how})"
        return {}
    resolved = dict(matched[0][1])
    for path, other in matched[1:]:
        if other != resolved:
            disagreement = sorted(
                set(resolved) ^ set(other)) or sorted(
                k for k in resolved if resolved.get(k) != other.get(k))
            rep.warn(
                f"{len(matched)} briefs record these bytes and they disagree on "
                f"declared_pitchers ({', '.join(disagreement[:6])}); only the "
                f"declarations ALL of them carry are acknowledged, so a "
                f"contradicted id still fails as absent. Briefs: "
                + ", ".join(p.name for p, _ in matched))
            resolved = {k: v for k, v in resolved.items() if other.get(k) == v}
    rep.info["declared_pitchers_source"] = (
        f"{matched[0][0].name} ({how})" if len(matched) == 1
        else f"{len(matched)} briefs, intersection ({how})")
    return resolved


def check_feed(entries: Sequence[EntryRow], salary: Dict[str, Dict[str, str]],
               feed_path: Path, strict: bool, rep: Report,
               declared_pitchers: Optional[Mapping[str, str]] = None) -> None:
    """A rostered player missing from his team's CONFIRMED lineup is a hard fail.

    R4. It was a warning unless --feed AND --feed-strict were both passed, so a
    3:55pm bench with a blank salary-file Status walked through the default
    check. That is the classic DFS zero and the evidence to catch it was already
    on disk. ``strict=False`` (--feed-lenient) restores the warning. A team that
    has not posted is untouched either way: TEAM_UNCONFIRMED is not evidence.

    R46 round 2, 2026-08-12. Three sides exist, not two, and each gets its own
    treatment:

    - CONFIRMED: a rostered player outside the posted nine is a hard fail. R4.
    - PARTIAL, meaning posted hitters under a non-confirmed status: the posted
      names ARE observed and are checked against. A miss is a projected fill,
      which is legal, so it is named with its exposure rather than failed; but
      an entry rostering more misses than the side has un-posted slots is
      arithmetically impossible and fails. A declared probable pitcher is a
      stated fact on a partial side too, so a different arm is a contradiction.
    - UNPOSTED: nothing to check against. Soft, per R46, and now named.

    The recurrence this fixes: R46 reported the blind spot as a team name and a
    slot count, which is a pointer to an analysis rather than a finding. On the
    1840_3g slate a bench catcher rode six of eighteen certified entries and the
    warning that covered him read "DET (32 slots)". Every case above now names
    the player and how many entries carry him, because that is the sentence that
    gets read at T-40.

    R114 + R67, 2026-08-15. Two ways a legally rostered ARM read as a
    contradiction, both of them the same mistake: treating a posted batting
    lineup as evidence about pitching.

    - R114, DECLARED. ``declared_pitchers`` is how the build rosters a second
      arm (``viable_bulk_or_alt_sp`` and the rest of the R104 vocabulary). The
      declaration reached the optimizer and the brief and stopped there, so
      this check re-derived "absent" from a feed that never had the fact. A
      declared arm is now an acknowledged WARN naming the role, never a FAIL.
      The acknowledgement is deliberately narrow: it applies to a
      pitcher-position row only. A declaration is a statement about an arm, and
      letting one silence a benched HITTER would hand the operator a flag that
      turns off R4 -- which is the zero this check exists to catch.
    - R67, BULLPEN GAME. ``confirmed_teams`` keyed off ``lineup_status`` alone,
      so a confirmed nine with a null ``probable_pitcher`` evidenced the arm
      too, and any pitcher rostered off DK's ``Starting`` column failed. A
      posted batting lineup evidences BATS. Those teams are now bats-only:
      their hitters are checked exactly as before and their arms are named
      soft.

    Both paths WARN rather than pass in silence, and both name their evidence
    class, because the two facts are not equally strong. A posted lineup is
    observed; a declaration is the operator's own statement. R114's live case
    had a hand-patched probable alongside the declaration, which made the
    check pass on operator-supplied input -- the right fact that night, and
    still not independent confirmation. The warning says which one it has.
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
    declared = {_digits(k): str(v) for k, v in (declared_pitchers or {}).items()
                if _digits(k) and str(v).strip()}
    rep.info["feed_declared_pitchers"] = dict(sorted(declared.items()))
    posted: Dict[str, set[str]] = {}
    posted_hitters: Dict[str, int] = {}
    declared_probable: Dict[str, str] = {}
    confirmed_teams: set[str] = set()
    confirmed_bats_only: set[str] = set()
    partial_teams: set[str] = set()
    for game in feed.get("games", []) or []:
        for side in ("away", "home"):
            block = game.get(side) or {}
            team = str(block.get("team_abbrev") or "").upper()
            if not team:
                continue
            lineup = block.get("lineup") or []
            names = {_norm_name(p.get("name")) for p in lineup}
            pp = (block.get("probable_pitcher") or {}).get("name")
            if pp:
                names.add(_norm_name(pp))
                declared_probable[team] = _norm_name(pp)
            posted.setdefault(team, set()).update(names)
            posted_hitters[team] = max(posted_hitters.get(team, 0), len(lineup))
            status = str(block.get("lineup_status") or "").lower()
            if status == "confirmed":
                confirmed_teams.add(team)
            elif 0 < len(lineup) < POSTED_LINEUP_SLOTS:
                # R46 round 2. A side with SOME posted hitters and a non-confirmed
                # status is a THIRD case, and collapsing it into the unposted
                # branch below is how 2026-08-12 happened: DET posted eight of
                # nine, the ninth was unrosterable on DK so the paste read
                # 'partial', and every DET slot skipped the check even though
                # eight observed names were sitting in `posted` one line up.
                #
                # The bound is `< 9` deliberately, and it is the whole distinction
                # R4 and R46 were protecting. A side listing all nine under a
                # non-confirmed status is most likely a PROJECTED nine, and a
                # projection is a labeled prior: a rostered player outside it is
                # contradicted by a guess, not by an observation, so hard-failing
                # there would block legal builds. Under nine is different. Those
                # names came from a real posting in progress, and the arithmetic
                # below only ever runs against observed slots.
                partial_teams.add(team)
    partial_teams -= confirmed_teams
    # R67. Computed from the whole feed rather than inside the block loop: a
    # doubleheader puts one team in two blocks, and a team is bats-only when NO
    # block for it named an arm, not when the last one happened not to.
    confirmed_bats_only = confirmed_teams - set(declared_probable)
    absent: List[str] = []
    unconfirmed: Dict[str, int] = {}
    projected: Dict[tuple, int] = {}
    overdrawn: List[str] = []
    acknowledged: Dict[tuple, int] = {}
    bats_only_arms: Dict[tuple, int] = {}
    misdeclared: Dict[tuple, int] = {}
    for e in entries:
        drawn: Dict[str, int] = {}
        for pid in e.cells:
            row = salary.get(pid)
            if not row:
                continue
            team = str(row.get("TeamAbbrev") or "").upper()
            name = str(row.get("Name") or "")
            if _norm_name(name) in posted.get(team, set()):
                continue                      # observed on the field, any status
            is_pitcher = str(row.get("Roster Position") or "").upper() == "P"
            role = declared.get(pid)
            if role and not is_pitcher:
                # A declaration names an ARM. Applying one to a hitter would
                # turn --declare-pitcher into an off switch for R4, so it is
                # reported and NOT applied; the normal checks below still run.
                misdeclared[(name, team, role)] = misdeclared.get(
                    (name, team, role), 0) + 1
                role = None
            if role:
                # R114. Declared, therefore legal, therefore not a contradiction
                # -- and still not observed, which is what the warning says.
                acknowledged[(name, team, role)] = acknowledged.get(
                    (name, team, role), 0) + 1
                continue
            if team in confirmed_teams:
                if is_pitcher and team in confirmed_bats_only:
                    # R67. The nine are posted and the arm is not among the
                    # facts they carry.
                    bats_only_arms[(name, team)] = bats_only_arms.get(
                        (name, team), 0) + 1
                    continue
                absent.append(f"{e.entry_id}: {name} ({team}) is not in "
                              f"{team}'s confirmed lineup or probables")
                continue
            # Not observed, and his team is not confirmed. R46 named the TEAM and
            # counted its slots; a team name and a slot count still leave the
            # reader to work out WHO, and on 2026-08-12 nobody did that at T-40.
            # Name the player and his exposure, every time, for both remaining
            # cases. It stays SOFT for the reason R46 gives: a genuinely unposted
            # team pre-lock is normal and R27 ships on warn by design.
            projected[(name, team)] = projected.get((name, team), 0) + 1
            if team in partial_teams:
                if str(row.get("Roster Position") or "").upper() == "P":
                    if team in declared_probable:
                        # The probable is a STATED fact even on a partial side,
                        # so a different arm is a contradiction, not an unknown.
                        absent.append(f"{e.entry_id}: {name} ({team}) is not "
                                      f"{team}'s declared probable pitcher")
                    # With no probable declared the arm is genuinely unknown. It
                    # is named in `projected` either way, and it never consumes a
                    # HITTER slot in the arithmetic below.
                    continue
                drawn[team] = drawn.get(team, 0) + 1
            else:
                unconfirmed[team] = unconfirmed.get(team, 0) + 1
        for team, n in sorted(drawn.items()):
            unknown = max(0, POSTED_LINEUP_SLOTS - posted_hitters.get(team, 0))
            if n > unknown:
                overdrawn.append(
                    f"{e.entry_id}: {n} {team} hitter(s) absent from a lineup that "
                    f"posted {posted_hitters.get(team, 0)} of {POSTED_LINEUP_SLOTS}, "
                    f"leaving only {unknown} slot(s) genuinely unknown")
    uniq = sorted(set(absent))
    total = len(entries)
    rep.info["feed_acknowledged_pitchers"] = {
        f"{name} ({team})": {"role": role, "entries": n, "evidence": "operator_declared"}
        for (name, team, role), n in sorted(acknowledged.items())}
    rep.info["feed_bats_only_arms"] = {
        f"{name} ({team})": n for (name, team), n in sorted(bats_only_arms.items())}
    if acknowledged:
        rep.warn(
            f"{len(acknowledged)} rostered pitcher(s) absent from the posted "
            f"lineup but DECLARED by the build, acknowledged rather than failed: "
            + "; ".join(f"{name} ({team}) in {n} of {total}, declared {role}"
                        for (name, team, role), n in
                        sorted(acknowledged.items(), key=lambda kv: (-kv[1], kv[0])))
            + ". Evidence: operator_declared. A declaration is the build's own "
              "statement of the role, not confirmation from the feed")
    if misdeclared:
        rep.warn(
            f"{len(misdeclared)} declared id(s) are not pitcher-position rows, so "
            f"the declaration was NOT applied and the posted-lineup check ran "
            f"normally: "
            + "; ".join(f"{name} ({team}) in {n} of {total}, declared {role}"
                        for (name, team, role), n in sorted(misdeclared.items()))
            + ". A declaration names an arm; it cannot clear a hitter")
    if bats_only_arms:
        rep.warn(
            f"{len(bats_only_arms)} rostered pitcher(s) on a team whose lineup is "
            f"confirmed but names no probable, so the posting evidences bats only: "
            + "; ".join(f"{name} ({team}) in {n} of {total}"
                        for (name, team), n in
                        sorted(bats_only_arms.items(), key=lambda kv: (-kv[1], kv[0])))
            + ". Evidence: posted_lineup, hitters only. A bullpen game posts nine "
              "bats and no starter, and this check cannot contradict an arm it "
              "has no fact about")
    rep.info["feed_absent"] = uniq
    rep.info["feed_unconfirmed_teams"] = dict(sorted(unconfirmed.items()))
    rep.info["feed_partial_teams"] = {t: posted_hitters.get(t, 0)
                                      for t in sorted(partial_teams)}
    rep.info["feed_projected_players"] = {
        f"{name} ({team})": n for (name, team), n in sorted(projected.items())}
    if projected:
        parts = []
        for (name, team), n in sorted(projected.items(), key=lambda kv: (-kv[1], kv[0])):
            where = (f"{team} posted {posted_hitters.get(team, 0)} of "
                     f"{POSTED_LINEUP_SLOTS}" if team in partial_teams
                     else f"{team} has not posted")
            parts.append(f"{name} ({team}) in {n} of {total}, {where}")
        rep.warn(f"{len(projected)} rostered player(s) absent from a posted lineup, "
                 f"each filling a projected slot: " + "; ".join(parts[:10]))
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
    if overdrawn:
        # Arithmetic, not judgment: more unknowns rostered than the posted lineup
        # leaves unknown cannot be right whatever the projection said.
        message = (f"{len(overdrawn)} entr{'ies' if len(overdrawn) != 1 else 'y'} "
                   f"roster more absent players than the posted lineup leaves "
                   f"unknown: " + "; ".join(sorted(set(overdrawn))[:10]))
        rep.fail(message) if strict else rep.warn(message)


# --------------------------------------------------------------------------
# advisory
# --------------------------------------------------------------------------

def partition_duplicate_lineups(rows: Iterable[Tuple[str, Any]]) -> Dict[str, int]:
    """Split lineup duplication into the finding and the information (R128).

    ``rows`` is one ``(contest_key, lineup_signature)`` pair per filled entry.
    The signature is whatever the caller keys a lineup on; this function only
    compares them, so the preflight's person-normalised frozenset and the
    brief's sorted player-ID tuple both work.

    Two duplications wear one word today and they are not the same fact.
    Duplication INSIDE one contest is waste: the entries pay twice into one
    prize pool for one outcome, and it is exactly what the allocator's
    ``no_duplicates_within_contest`` exists to prevent. Duplication ACROSS
    contests is free, often deliberate, and the allocator permits it by
    default under ``allow_cross_contest_reuse``. Reporting the union under a
    name that reads as a finding is what let a correct portfolio look broken
    at T-5 on 2026-08-15: nine groups printed, zero of them inside a contest,
    and the nine were seven lineups mirrored across two identical satellites.

    This is a SPLIT, not a filter. The across-contest number is retained and
    reported because it is the number that says whether a satellite bank is
    being reused deliberately; suppressing it would trade one blind spot for
    another.

    The two numbers do NOT sum to ``duplicate_lineup_groups`` and must never be
    presented as if they did. They count different objects. Within counts
    (contest, signature) pairs a contest holds more than once, so one signature
    duplicated in two different contests contributes 2. Across counts
    signatures appearing in more than one contest, so that same signature
    contributes 1. The flat count would call it 1 group. All three readings are
    correct about different questions, which is the whole reason one number
    could not answer the operator's.
    """
    by_contest: Dict[str, List[Any]] = collections.defaultdict(list)
    for contest_key, sig in rows:
        by_contest[contest_key].append(sig)
    within = 0
    contests_by_sig: Dict[Any, set] = collections.defaultdict(set)
    all_sigs: collections.Counter = collections.Counter()
    for contest_key, sigs in by_contest.items():
        counts = collections.Counter(sigs)
        within += sum(1 for c in counts.values() if c > 1)
        all_sigs.update(counts)
        for sig in counts:
            contests_by_sig[sig].add(contest_key)
    return {
        "distinct_lineups": len(all_sigs),
        "contests_in_file": len(by_contest),
        "duplicates_within_contest": within,
        "duplicates_across_contests": sum(
            1 for keys in contests_by_sig.values() if len(keys) > 1),
        # Retained deliberately. Nothing in tree reads it today (checked
        # 2026-08-16), but it is a published key in both this tool's --json and
        # verify_export's, and dropping a key from a JSON contract to save a
        # line is not a trade worth making. It is the flat, contest-blind count
        # the two numbers above supersede.
        "duplicate_lineup_groups": sum(1 for c in all_sigs.values() if c > 1),
    }


def per_contest_captain_cap(n: int,
                            max_cpt_per_contest: int = DEFAULT_MAX_CPT_PER_CONTEST
                            ) -> int:
    """How many times one captain may appear inside a contest of ``n`` entries.

    A mirror of ``showdown.per_contest_cap_count``, pinned equal by test:
    ``max(1, min(m, n - 1))``. Preflight cannot import the engine, and a checker
    applying a different bar than the builder built to is R79(d)'s no-op failure
    class landing on the money boundary, so the copy is guarded rather than left
    to agree by luck.

    The ``n - 1`` is the load-bearing part. A flat ``m`` permits a 2-entry contest
    to put BOTH entries on one captain (``min(2, 2) = 2``), which is the measured
    100% on contest 194553034, 2026-08-28 -- a cap written to stop that case
    passing it. ``n - 1`` guarantees at least two distinct captains in any
    multi-entry contest.
    """
    n = max(1, int(n))
    if n == 1:
        return 1
    return max(1, min(int(max_cpt_per_contest), n - 1))


def per_contest_captain_exposure(filled: Sequence[EntryRow],
                                 persons: Mapping[str, str],
                                 display: Mapping[str, Tuple[str, str]],
                                 max_cpt_per_contest: int = DEFAULT_MAX_CPT_PER_CONTEST,
                                 ) -> List[Dict[str, Any]]:
    """Count captains per CONTEST rather than per file (R266).

    This crosses the two checks ``advisory`` already held six lines apart and
    never crossed: ``top_captain_exposure`` counted captains across the WHOLE
    FILE, and R128's partition split entries by contest for lineup duplication
    only. Neither could see the 2026-08-29 finding on ``2215_1g_sd``, where a
    2-entry contest carried ONE captain across both entries (two entries bought,
    one outcome) and a 7-entry satellite carried 4 distinct captains across 7,
    while the portfolio counters read ``realized_max_pct 23.8`` under a 0.25 cap
    with ``cap_relaxed_slots 0`` -- every number true, none of them describing
    what was entered.

    R128's own words are the precedent unchanged: entries duplicated inside one
    contest "pay twice into one prize pool for one outcome". A shared captain is
    that same waste one slot down, and on a six-man roster carrying 1.5x it is
    the most expensive slot to duplicate.

    Contests holding one entry are omitted: a single entry cannot duplicate
    anything, and listing it would bury the finding in noise on a slate where
    most contests are single-entry.

    Returns one block per multi-entry contest, worst first, each carrying its own
    ``n``, ``cap``, ``distinct_captains``, full ``captain_counts``, and the
    ``over_cap`` rows that are the finding.
    """
    by_contest: Dict[str, List[EntryRow]] = collections.defaultdict(list)
    for e in filled:
        # Same key as R128, in the same order and for the same reason: the ID is
        # the key and the name is the fallback, because a hand-assembled file can
        # leave the ID blank while the name still separates the contests.
        by_contest[e.contest_id or e.contest_name or ""].append(e)

    blocks: List[Dict[str, Any]] = []
    for key, rows in by_contest.items():
        n = len(rows)
        if n < 2:
            continue
        counts: collections.Counter = collections.Counter()
        for e in rows:
            if e.cells and e.cells[0]:
                counts[persons.get(e.cells[0], e.cells[0])] += 1
        if not counts:
            continue
        cap = per_contest_captain_cap(n, max_cpt_per_contest)
        over = [
            {"player": display.get(k, (k, "?"))[0],
             "team": display.get(k, (k, "?"))[1],
             "n": c, "cap": cap, "pct": round(100.0 * c / n, 1)}
            for k, c in counts.most_common() if c > cap
        ]
        name = next((e.contest_name for e in rows if e.contest_name), "")
        blocks.append({
            "contest_id": rows[0].contest_id or "",
            "contest_name": name,
            "contest_key": key,
            "n": n,
            "cap": cap,
            "distinct_captains": len(counts),
            "captain_counts": [
                {"player": display.get(k, (k, "?"))[0], "n": c}
                for k, c in counts.most_common()
            ],
            "over_cap": over,
            "worst_pct": round(100.0 * counts.most_common(1)[0][1] / n, 1),
        })
    # Worst first: the contest whose most-repeated captain owns the largest share
    # is the one the operator has seconds to look at. Ties break on the contest
    # key so the ordering is deterministic, which the golden replay needs.
    blocks.sort(key=lambda b: (-b["worst_pct"], -b["n"], b["contest_key"]))
    return blocks


def check_contest_captain_diversity(adv: Mapping[str, Any], rep: Report,
                                    strict: bool = False) -> None:
    """Register the R266 finding as a WARNING, or as a failure under --strict.

    **WARN by default and this is deliberate.** A deliberate double-up is a
    legitimate play and CLAUDE.md reserves concentration to Ben, so this check
    must not block an upload on its own judgment. The hard failure lives behind
    ``--strict-contest-diversity`` and is not wired on anywhere.

    Why this belongs on the preflight rather than only in the brief: the preflight
    is the one surface that runs on every deliverable, with no engine import, no
    bank and no network, and it is already trusted at the money boundary. It also
    catches a HAND-PERMUTED file, which the brief cannot -- and R239 records two
    live deliveries that shipped by hand permutation of the delivered file.
    """
    for b in adv.get("per_contest_captains") or []:
        for row in b["over_cap"]:
            where = b["contest_id"] or b["contest_name"] or "unkeyed contest"
            msg = (f"contest {where}: captain {row['player']} in {row['n']} of "
                   f"{b['n']} entries ({row['pct']}%), above the per-contest cap "
                   f"of {row['cap']}. Entries sharing a captain inside one "
                   f"contest pay twice into one prize pool for one outcome; the "
                   f"portfolio captain cap cannot see this, because it counts "
                   f"against the entered total")
            rep.fail(msg) if strict else rep.warn(msg)


def advisory(contest: str, entries: Sequence[EntryRow],
             salary: Dict[str, Dict[str, str]],
             max_cpt_per_contest: int = DEFAULT_MAX_CPT_PER_CONTEST,
             ) -> Dict[str, Any]:
    filled = [e for e in entries if not e.is_blank]
    n = len(filled)
    out: Dict[str, Any] = {"entries": len(entries), "filled": n}
    if not n:
        return out
    persons = {pid: person_key(row) for pid, row in salary.items()}
    display: Dict[str, Tuple[str, str]] = {}
    for pid, row in salary.items():
        display.setdefault(persons[pid], (str(row.get("Name") or pid),
                                          str(row.get("TeamAbbrev") or "?")))

    def _top(counter: collections.Counter) -> List[Dict[str, Any]]:
        rows = []
        for key, c in counter.most_common(8):
            name, team = display.get(key, (key, "?"))
            rows.append({"player": name, "team": team,
                         "n": c, "pct": round(100.0 * c / n, 1)})
        return rows

    sets = [frozenset(persons.get(pid, pid) for pid in e.cells if pid) for e in filled]
    # R234/R192. This used to count draftable ids. On Classic that is the same
    # number, because there is no multiplier role; on Showdown it splits one
    # human across a CPT key and a UTIL key and neither half reaches the printed
    # five. On the 2026-08-19 LAD@COL delivery that hid the two MOST
    # concentrated players in the portfolio: Sasaki sat at 9 of 19, exactly the
    # solver's floor(0.5*19)=9 player cap, and did not appear at all. R153 set
    # that cap "counting the PLAYER and not the role" because correlated failure
    # across entries is the washout axis; this is the one line an operator reads
    # to check it, so it counts what the cap counts. It failed in both
    # directions -- every captained player under-reported, so a real breach
    # could read clean.
    counts = collections.Counter(key for s in sets for key in s)
    out["top_exposure"] = _top(counts)
    if contest == "showdown":
        # The captain cap (0.25) and the player cap (0.50) are separate controls
        # and an operator checking either against the brief had neither.
        out["top_captain_exposure"] = _top(collections.Counter(
            persons.get(e.cells[0], e.cells[0])
            for e in filled if e.cells and e.cells[0]))
        # R266. The same captains, counted against the contest that pays them
        # instead of against the file. The line above and R128's partition below
        # sat six lines apart and never crossed; this is the crossing.
        out["per_contest_captains"] = per_contest_captain_exposure(
            filled, persons, display, max_cpt_per_contest)
        out["max_cpt_per_contest"] = int(max_cpt_per_contest)
    # R128. The contest each entry belongs to is already in the row; the DK
    # template writes it beside the Entry ID, so the partition needs no new
    # input. Contest ID is the key and the name is the fallback, because a
    # hand-assembled file can leave the ID blank while the name still separates
    # the contests; when both are blank every entry lands in one bucket, which
    # degrades to exactly the old flat reading rather than to a wrong one.
    out.update(partition_duplicate_lineups(
        (e.contest_id or e.contest_name or "", sig) for e, sig in zip(filled, sets)))
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
        resolved, why = resolve_salary_from_promoted_run(
            REPO_ROOT / "runs", contest=contest,
            rostered={pid for e in entries for pid in e.cells if pid})
        if resolved is None:
            raise ValueError(
                f"no --salary given and the promoted run's snapshot was NOT "
                f"used: {why}. Pass --salary explicitly; checking these entries "
                f"against another slate's file answers a different question")
        salary_path = resolved
        rep.info["salary_source"] = "promoted run snapshot"
    rep.info["salary_file"] = str(salary_path)
    salary = load_salary(salary_path)

    check_contest_identity(contest, entries, rep)
    check_row_shape(entries, entry_id_rows, len(slots), rep, args.expect_entries)
    check_pool_membership(entries, salary, parse_embedded_pool(raw_rows),
                          args.min_pool_overlap, rep)
    check_status(entries, salary, rep)
    # R287. Before the legality walk, deliberately: a started game makes every
    # other verdict about that entry moot, and this is the one failure a reader
    # at T-0 must see first.
    check_started_games(entries, salary,
                        parse_as_of(getattr(args, "as_of", None))
                        if getattr(args, "as_of", None)
                        else datetime.now(timezone.utc),
                        rep)
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

    # R114. Hand-passed declarations win over the recorded ones: --declare-pitcher
    # exists for the file that never had a run, and an operator who passes it
    # against a file that does have one is stating something the brief does not.
    hand = parse_declared_pitcher_args(getattr(args, "declare_pitcher", None) or ())
    if hand:
        declared_pitchers = hand
        rep.info["declared_pitchers_source"] = "--declare-pitcher"
    else:
        declared_pitchers = resolve_declared_pitchers(
            entries_path, rep.info["entries_sha256"],
            getattr(args, "brief", None), rep)

    feed_path = Path(args.feed) if args.feed else resolve_feed_for_slate(entries, salary, rep)
    if feed_path is not None and feed_path.exists():
        check_feed(entries, salary, feed_path, not args.feed_lenient, rep,
                   declared_pitchers=declared_pitchers)
    elif feed_path is not None:
        rep.warn(f"feed {feed_path} does not exist; posted-lineup cross-check skipped")
    else:
        rep.warn("no lineups feed resolved; the posted-lineup cross-check did "
                 "not run and a benched starter would not be caught here")

    # R266. The advisory is computed BEFORE the report dict, not inside it,
    # because the diversity check registers into `rep` and `passed` is evaluated
    # at dict-construction time. Built inline, a --strict failure would land in
    # `rep.failures` after `passed` had already read it as True.
    adv = advisory(contest, entries, salary,
                   max_cpt_per_contest=getattr(args, "max_cpt_per_contest",
                                               DEFAULT_MAX_CPT_PER_CONTEST))
    check_contest_captain_diversity(
        adv, rep, strict=bool(getattr(args, "strict_contest_diversity", False)))

    report = {
        "tool": "preflight_upload", "version": VERSION,
        "passed": not rep.failures,
        "failures": rep.failures, "warnings": rep.warnings,
        "info": rep.info, "lineups": details,
        "advisory": adv,
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
    ap.add_argument("--brief", help="build brief holding declared_pitchers for "
                                    "this delivery; auto-matched by "
                                    "delivered_sha256 among sibling "
                                    "build_brief*.json files")
    ap.add_argument("--declare-pitcher", action="append", metavar="ID=ROLE",
                    help="state a declared arm by hand when there is no brief "
                         "to read, for example "
                         "43815489=viable_bulk_or_alt_sp. Repeatable. A "
                         "declared pitcher absent from the posted lineup is an "
                         "acknowledged warning, never a failure; an undeclared "
                         "one still fails")
    ap.add_argument("--expect-contest-type", choices=["classic", "showdown"],
                    help="fail if the file's geometry is not this")
    ap.add_argument("--expect-entries", type=int,
                    help="reserved-entry count this file must hold; catches truncation")
    ap.add_argument("--expect-sha256",
                    help="hard-fail unless the entries file hashes to this "
                         "sha256 (full hex, or a prefix of 12+ chars); pairs "
                         "the upload with the brief's delivered_sha256 (R20a)")
    ap.add_argument("--as-of", metavar="ISO|HH:MM",
                    help="the moment to judge 'has this game started' against; "
                         "defaults to now. A bare HH:MM is Eastern, because the "
                         "salary file's Game Info is. Exists for replay "
                         "determinism (R287)")
    ap.add_argument("--min-pool-overlap", type=float, default=0.95)
    # R266. Default WARN. A deliberate double-up is a legitimate play and
    # CLAUDE.md reserves concentration to Ben, so this must not block on its own
    # judgment; the strict flag exists so the decision is a flag flip rather than
    # a rebuild, and it is not wired on anywhere.
    ap.add_argument("--strict-contest-diversity", action="store_true",
                    help="turn the R266 per-contest captain finding into a hard "
                         "failure instead of a warning")
    ap.add_argument("--max-cpt-per-contest", type=int,
                    default=DEFAULT_MAX_CPT_PER_CONTEST,
                    help="per-contest captain bar the build used; the effective "
                         "bar is max(1, min(m, contest entries - 1)) "
                         f"(default {DEFAULT_MAX_CPT_PER_CONTEST})"),
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
        # R275(b), 2026-08-31. The guard was `if certification and certification
        # != "certified"`, so an ABSENT certification fell through to
        # `upload_ready` -- the one label CLAUDE.md reserves, awarded on missing
        # evidence rather than on evidence of certification. Absence now lands in
        # the same branch as a wrong value, because "no row said it was certified"
        # and "the row said it was review_grade" are the same fact for this label.
        # The two cases get DIFFERENT notes: a verdict note that quotes
        # `certification=''` reads like a checker bug, and the operator needs to
        # know whether the evidence disagreed or was never recorded.
        if certification != "certified":
            verdict = "review_ready"
            report["verdict_note"] = (
                f"every file-level check passed, but no manifest certification "
                f"was recorded for these bytes, so this is NOT upload_ready: "
                f"that label is reserved for a run where workflow_valid, "
                f"selection_certified and allocation_certified all passed, and a "
                f"row that records nothing is not evidence that they did. Check "
                f"the delivery was recorded by the build path (a --no-manifest "
                f"run reaches here by design)."
                if not certification else
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
        stamp = stamp_manifest_status(
            Path(manifest_file), report["info"]["entries_sha256"],
            verdict, report["failures"], rep,
            entries_name=Path(args.entries).name)
        # R176 rider (ed8 F-34), 2026-08-30. `code` is computed above, BEFORE this
        # write, and every way the stamp could fail was a warning: an unreadable
        # manifest and an unmatched row both returned in silence, and the write's
        # OSError only warned. So a shipping verdict could return 0 while never
        # being durably bound to the delivery -- and the manifest row is what the
        # next session, a late swap and this tool's own re-run all read. For a
        # verdict that exits zero, failed persistence is a hard failure.
        #
        # Read back rather than trust the write: that is the only evidence the
        # bytes landed, and this batch is about not asserting what nobody checked.
        if code == 0:
            committed = committed_manifest_status(
                Path(manifest_file), report["info"]["entries_sha256"],
                entries_name=Path(args.entries).name)
            if not stamp["stamped"] or committed != stamp["status"]:
                rep.fail(
                    f"verdict {verdict!r} was not durably recorded on the manifest "
                    f"({stamp['reason'] or 'the row on disk reads ' + repr(committed)}"
                    f"); a verdict that exits zero has to be bound to the delivery, "
                    f"because the row is what the next session and the late swap "
                    f"read. Fix the manifest and re-run rather than uploading on "
                    f"this output alone")
                verdict = "acknowledged" if args.force else "blocked"
                report["verdict"] = verdict
                code = verdict_exit_code(report["failures"], args.force)

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
        # R287. The first lock was already printed here and read as reassurance.
        # The clock it is being compared AGAINST is what was missing, so the two
        # numbers now sit on adjacent lines and the verdict is stated rather than
        # left to the reader's arithmetic.
        if info.get("as_of_et"):
            started = int(info.get("started_slots") or 0)
            verdict = (f"{started} slot(s) in {info.get('started_entries')} "
                       f"entr{'y' if info.get('started_entries') == 1 else 'ies'} "
                       f"ALREADY STARTED" if started else "none started")
            print(f"  as of: {info['as_of_et']}  [{verdict}]")
        if adv.get("top_exposure"):
            top = ", ".join(f"{x['player']} {x['pct']}%" for x in adv["top_exposure"][:5])
            print(f"  top exposure: {top}  (the PERSON, either role)")
        if adv.get("top_captain_exposure"):
            top = ", ".join(f"{x['player']} {x['pct']}%"
                            for x in adv["top_captain_exposure"][:5])
            print(f"  top CPT exposure: {top}")
        if adv.get("per_contest_captains"):
            # R266. Prints even when every contest is clean, on R128's own
            # reasoning: "zero repeats inside a contest" is the reassurance the
            # T-5 reader needs, and inferring it from silence is what nearly cost
            # a good portfolio on 2026-08-15.
            blocks = adv["per_contest_captains"]
            flagged = sum(1 for b in blocks if b["over_cap"])
            print(f"  CPT per contest ({len(blocks)} multi-entry contest"
                  f"{'s' if len(blocks) != 1 else ''}, "
                  f"{flagged} over cap):")
            for b in blocks[:6]:
                mark = "  <-- OVER CAP" if b["over_cap"] else ""
                repeats = ", ".join(f"{c['player']} x{c['n']}"
                                    for c in b["captain_counts"] if c["n"] > 1)
                print(f"    {b['contest_id'] or b['contest_name'] or '?'}: "
                      f"{b['distinct_captains']} distinct CPT across {b['n']} "
                      f"entries (cap {b['cap']}/CPT)"
                      + (f"; {repeats}" if repeats else "; no repeats") + mark)
        if adv.get("duplicate_lineup_groups"):
            # R128. Same trigger as before, so no file that prints nothing
            # today starts printing; what changed is that the operator is told
            # WHICH duplication this is. The within line prints even at zero,
            # because "zero inside a contest" is the reassurance the T-5 reader
            # needs and inferring it from silence is what nearly cost a good
            # portfolio on 2026-08-15.
            n_contests = adv.get("contests_in_file", 1)
            plural = "s" if n_contests != 1 else ""
            print(f"  duplicate lineups WITHIN a contest: "
                  f"{adv.get('duplicates_within_contest', 0)}"
                  f"  (the finding: one contest holding a lineup twice pays "
                  f"twice into one prize pool)")
            print(f"  same lineup in MORE THAN ONE contest: "
                  f"{adv.get('duplicates_across_contests', 0)} of "
                  f"{adv.get('distinct_lineups', 0)} distinct lineups, across "
                  f"{n_contests} contest{plural}  (information, not a finding: "
                  f"separate contests have separate prize pools, so reuse is "
                  f"free and often deliberate)")
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
