#!/usr/bin/env python3
"""preflight_upload.py -- the last check between a built file and DraftKings.

One fail-closed inspection of the artifact, run between "build finished" and
"Ben uploads." It inspects the file, not the process that made it, so it also
covers hand-built and ad-hoc exports that never entered the pipeline.

Design constraints, all deliberate:
  - two files and nothing else in the core invocation: --entries and --salary
  - no engine import, no solver, no network, no LLM; target under two seconds
  - every hard check is a fact about the file, decidable from disk
  - --force always exists, so this can never be the reason a slate is not entered

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
  5. row accounting: every Entry ID row parsed, all Entry IDs unique, and the
     row count matches --expect-entries or the manifest when either is given
     (truncation is self-consistent on its face; it is only detectable against
     an external statement of how many entries the file should hold)

Optional, never blocking on their own absence:
  --manifest  cross-check contest IDs and sha256 against outputs/<date>/upload_manifest.json
  --feed      flag rostered players absent from their team's posted lineup
  --parent    diff contest assignment against the file this one refines

Advisory prints (never affect the exit code): exposure, lineup-overlap
histogram, duplicate-lineup groups, first lock.

Usage:
    python tools/preflight_upload.py --entries outputs/<date>/DKEntries.csv \\
        [--salary data/slates/<date>/DKSalaries.csv] [--manifest ...] [--feed ...]
        [--parent ...] [--json] [--force]

Exit 0 clean (or --force), 2 on any hard failure, 3 on a usage or IO error.
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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

VERSION = "1.0"

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
        if not entry_id.isdigit():
            continue
        entry_id_rows += 1
        entries.append(EntryRow(line_no, raw, width))
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


def check_row_shape(entries: Sequence[EntryRow], entry_id_rows: int, width: int,
                    rep: Report, expect_entries: Optional[int] = None) -> None:
    """Hard check 1 and 5: geometry per row, and row accounting."""
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

def check_manifest(entries_path: Path, entries: Sequence[EntryRow],
                   manifest_path: Path, rep: Report) -> None:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        rep.warn(f"manifest unreadable ({exc}); contest-assignment cross-check skipped")
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
            rep.warn(f"no manifest record for {name} (sha256 {digest[:12]}); "
                     f"this file was not produced by a recorded delivery path")
        return
    rep.info["manifest_run_id"] = match.get("run_id")
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


def check_feed(entries: Sequence[EntryRow], salary: Dict[str, Dict[str, str]],
               feed_path: Path, strict: bool, rep: Report) -> None:
    """Name-joined, so it warns by default; --feed-strict promotes it to a block."""
    try:
        feed = json.loads(feed_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        rep.warn(f"feed unreadable ({exc}); posted-lineup cross-check skipped")
        return
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
    for e in entries:
        for pid in e.cells:
            row = salary.get(pid)
            if not row:
                continue
            team = str(row.get("TeamAbbrev") or "").upper()
            if team not in confirmed_teams:
                continue
            if _norm_name(row.get("Name")) not in posted.get(team, set()):
                absent.append(f"{e.entry_id}: {row.get('Name')} ({team}) is not in "
                              f"{team}'s confirmed lineup or probables")
    uniq = sorted(set(absent))
    rep.info["feed_absent"] = uniq
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

    check_row_shape(entries, entry_id_rows, len(slots), rep, args.expect_entries)
    check_pool_membership(entries, salary, parse_embedded_pool(raw_rows),
                          args.min_pool_overlap, rep)
    check_status(entries, salary, rep)
    details = check_legality(contest, slots, entries, salary, rep)

    if args.manifest:
        check_manifest(entries_path, entries, Path(args.manifest), rep)
    if args.parent:
        check_parent(entries, Path(args.parent), rep)
    if args.feed:
        check_feed(entries, salary, Path(args.feed), args.feed_strict, rep)

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
    ap.add_argument("--parent", help="the delivered file this one refines")
    ap.add_argument("--feed", help="lineups_feed.json")
    ap.add_argument("--feed-strict", action="store_true",
                    help="promote posted-lineup absences from warning to failure")
    ap.add_argument("--expect-contest-type", choices=["classic", "showdown"],
                    help="fail if the file's geometry is not this")
    ap.add_argument("--expect-entries", type=int,
                    help="reserved-entry count this file must hold; catches truncation")
    ap.add_argument("--min-pool-overlap", type=float, default=0.95)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="print failures and exit 0; for when the clock beats the fix")
    args = ap.parse_args(argv)

    try:
        rep, report = run(args)
    except (OSError, ValueError) as exc:
        print(f"ERROR  {exc}", file=sys.stderr)
        return 3

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
        print()
        for w in report["warnings"]:
            print(f"WARN  {w}")
        for f in report["failures"]:
            print(f"FAIL  {f}")
        if not report["failures"]:
            print(f"PASS  {adv['entries']} {info['contest_type']} entries, "
                  f"all hard checks clean")
        elif args.force:
            print(f"\nFORCED  {len(report['failures'])} hard failure(s) overridden "
                  f"by --force; this file is being uploaded against the check")

    if report["failures"] and not args.force:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
