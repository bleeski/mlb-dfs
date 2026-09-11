"""Authoritative salary ingestion and surgical, byte-preserving entry updates."""

from __future__ import annotations

import csv
import io
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from mlb_engine.optimize.roster_contracts import get_contract
from .contracts import Entry, Player

MAX_INPUT_BYTES = 32 * 1024 * 1024
OUT_STATUSES = frozenset(
    {"IL", "O", "OUT", "NA", "IL10", "IL15", "IL60", "PUP", "SUSP"}
)
ID_RE = re.compile(r"^(?:.*\()?([0-9]+)\)?$")
GAME_RE = re.compile(
    r"^([A-Z0-9]+)@([A-Z0-9]+)\s+(\d{2}/\d{2}/\d{4})\s+"
    r"(\d{1,2}:\d{2}(?:AM|PM))\s+ET$"
)


def player_id(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    if value.isascii() and value.isdecimal():
        return value
    match = re.fullmatch(r".+ \(([0-9]+)\)", value)
    if match:
        return match.group(1)
    raise ValueError("player cell must contain an exact numeric DraftKings ID")


def money_cents(value: str) -> int:
    try:
        amount = Decimal(value.strip().removeprefix("$").replace(",", ""))
        if (
            not amount.is_finite()
            or amount < 0
            or amount * 100 != (amount * 100).to_integral_value()
        ):
            raise ValueError("invalid monetary amount")
        return int(amount * 100)
    except InvalidOperation as exc:
        raise ValueError("invalid monetary amount") from exc


def game_identity(text: str, team: str) -> tuple[str, str, datetime]:
    match = GAME_RE.fullmatch(text.strip().upper())
    if not match:
        raise ValueError(
            "Game Info needs a complete dated Eastern-time start; TBD cannot establish lock state"
        )
    away, home, date, clock = match.groups()
    if team not in {away, home} or away == home:
        raise ValueError("salary team is inconsistent with its game")
    start = datetime.strptime(date + " " + clock, "%m/%d/%Y %I:%M%p").replace(
        tzinfo=ZoneInfo("America/New_York")
    )
    # UTC identity distinguishes the two legs of a doubleheader.
    from datetime import timezone

    start = start.astimezone(timezone.utc)
    return f"{away}@{home}|{start.isoformat()}", home if team == away else away, start


def parse_salary(raw: bytes) -> tuple[str, dict[str, Player]]:
    if len(raw) > MAX_INPUT_BYTES:
        raise ValueError("salary file exceeds the input size limit")
    reader = csv.DictReader(
        io.StringIO(raw.decode("utf-8-sig"), newline=""), strict=True
    )
    required = {
        "ID",
        "Name",
        "Position",
        "Roster Position",
        "Salary",
        "TeamAbbrev",
        "Game Info",
    }
    header = reader.fieldnames or []
    if required - set(header) or any(n > 1 for h, n in Counter(header).items() if h):
        raise ValueError(
            "salary schema is missing required columns or has duplicate columns"
        )
    records = [r for r in reader if any(r.values())]
    if not records:
        raise ValueError("salary table is empty")
    mode = (
        "SHOWDOWN"
        if any(r["Roster Position"] in {"CPT", "UTIL"} for r in records)
        else "CLASSIC"
    )
    players: dict[str, Player] = {}
    pairs: dict[tuple, dict[str, str]] = defaultdict(dict)
    for r in records:
        if None in r or any(r.get(k) is None for k in required):
            raise ValueError("malformed salary row")
        pid = r["ID"].strip()
        if not re.fullmatch(r"[0-9]+", pid) or pid in players:
            raise ValueError("blank, nonnumeric, or duplicate salary ID")
        if r.get("Name + ID") and player_id(r["Name + ID"]) != pid:
            raise ValueError("salary ID disagrees with Name + ID")
        if not re.fullmatch(r"[0-9]+", r["Salary"].strip()) or int(r["Salary"]) <= 0:
            raise ValueError("salary must be a positive integer")
        team, name = r["TeamAbbrev"].strip(), r["Name"].strip()
        if not name:
            raise ValueError("salary player name is empty")
        gid, opponent, start = game_identity(r["Game Info"], team)
        positions = tuple(r["Position"].strip().upper().split("/"))
        if not positions or set(positions) - {
            "P",
            "SP",
            "RP",
            "C",
            "1B",
            "2B",
            "3B",
            "SS",
            "OF",
        }:
            raise ValueError("unsupported biological player position")
        positions = tuple("P" if x in {"SP", "RP"} else x for x in positions)
        role = r["Roster Position"].strip()
        if mode == "SHOWDOWN":
            if role not in {"CPT", "UTIL"}:
                raise ValueError("mixed Classic and Showdown salary geometry")
            key = (name, team, gid, positions)
            if role in pairs[key]:
                raise ValueError("ambiguous Showdown physical-player pairing")
            pairs[key][role] = pid
        else:
            eligible = tuple(role.split("/"))
            if set(eligible) - {"P", "C", "1B", "2B", "3B", "SS", "OF"}:
                raise ValueError("unsupported Classic roster eligibility")
            positions = eligible
            role = "CLASSIC"
        status = r.get("Status", "").strip().upper()
        exclusion = r.get("Excluded", "").strip().lower()
        if exclusion not in {
            "",
            "true",
            "1",
            "yes",
            "y",
            "t",
            "false",
            "0",
            "no",
            "n",
            "f",
        }:
            raise ValueError("unrecognized exclusion flag")
        excluded = exclusion in {"true", "1", "yes", "y", "t"}
        players[pid] = Player(
            pid,
            pid,
            name,
            team,
            opponent,
            gid,
            positions,
            role,
            int(r["Salary"]),
            start,
            status in OUT_STATUSES,
            excluded,
        )
    if mode == "SHOWDOWN":
        from dataclasses import replace

        for pair in pairs.values():
            if set(pair) != {"CPT", "UTIL"}:
                raise ValueError("Showdown player lacks its CPT or UTIL salary row")
            a, b = players[pair["CPT"]], players[pair["UTIL"]]
            # An exclusion or official out applies to the physical player.
            for pid in pair.values():
                players[pid] = replace(
                    players[pid],
                    person_id=pair["UTIL"],
                    status_out=a.status_out or b.status_out,
                    excluded=a.excluded or b.excluded,
                )
        if len({p.game_id for p in players.values()}) != 1:
            raise ValueError("Showdown must contain exactly one game")
    return mode, players


def field_spans(raw: str) -> list[tuple[int, int]]:
    """Offsets of CSV fields, including their lexical quotes but not separators."""
    spans = []
    start = i = 0
    quoted = False
    while i < len(raw):
        c = raw[i]
        if c == '"':
            if quoted and i + 1 < len(raw) and raw[i + 1] == '"':
                i += 2
                continue
            if quoted or i == start:
                quoted = not quoted
        if not quoted and c in ",\r\n":
            spans.append((start, i))
            if c != ",":
                return spans
            start = i + 1
        i += 1
    spans.append((start, i))
    return spans


@dataclass(frozen=True)
class Template:
    mode: str
    bom: str
    rows: tuple[tuple[str, ...], ...]
    raw_records: tuple[str, ...]
    entries: tuple[Entry, ...]

    def render(
        self, assignments: dict[str, tuple[str, ...]], mutable_ids: set[str]
    ) -> bytes:
        known = {e.entry_id for e in self.entries}
        if set(assignments) - known or mutable_ids - known:
            raise ValueError("assignment or authorization contains an unknown Entry ID")
        records = list(self.raw_records)
        size = get_contract(self.mode).roster_size
        for entry in self.entries:
            roster = assignments.get(entry.entry_id, entry.roster)
            if len(roster) != size or not all(
                re.fullmatch(r"[0-9]+", p) for p in roster
            ):
                raise ValueError("blank or malformed reserved roster")
            if roster == entry.roster:
                continue
            if entry.entry_id not in mutable_ids:
                raise ValueError("unauthorized entry change")
            raw = records[entry.record_index]
            spans = field_spans(raw)
            if len(spans) != len(self.rows[entry.record_index]):
                raise ValueError("CSV lexical field count disagrees with parser")
            for index in reversed(range(size)):
                if roster[index] == entry.roster[index]:
                    continue
                start, end = spans[4 + index]
                raw = raw[:start] + roster[index] + raw[end:]
            records[entry.record_index] = raw
        return (self.bom + "".join(records)).encode("utf-8")


def parse_entries(raw: bytes) -> Template:
    if len(raw) > MAX_INPUT_BYTES:
        raise ValueError("entries file exceeds the input size limit")
    text = raw.decode("utf-8")
    bom = "\ufeff" if text.startswith("\ufeff") else ""
    text = text.removeprefix("\ufeff")
    physical = text.splitlines(keepends=True)
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    rows, records = [], []
    prior_line = 0
    for row in reader:
        rows.append(tuple(row))
        records.append("".join(physical[prior_line : reader.line_num]))
        prior_line = reader.line_num
    if not rows or list(rows[0][:4]) != [
        "Entry ID",
        "Contest Name",
        "Contest ID",
        "Entry Fee",
    ]:
        raise ValueError("invalid DKEntries header")
    mode = "SHOWDOWN" if rows[0][4:10] == get_contract("SHOWDOWN").slots else "CLASSIC"
    slots = get_contract(mode).slots
    if rows[0][4 : 4 + len(slots)] != slots:
        raise ValueError("unsupported entry roster geometry")
    entries, seen = [], set()
    for index, row in enumerate(rows[1:], 1):
        eid = row[0].strip() if row else ""
        cid = row[2].strip() if len(row) > 2 else ""
        # Embedded player tables can also contain numbers, but never in Entry ID
        # unless the first four entry identity columns are populated.
        if not eid or not re.fullmatch(r"[0-9]+", eid):
            if eid and re.fullmatch(r"[0-9]+", cid):
                raise ValueError("nonnumeric Entry ID on a reserved contest row")
            continue
        if not re.fullmatch(r"[0-9]+", cid) or len(row) < 4 + len(slots):
            raise ValueError(
                "malformed reserved entry identity or missing roster columns"
            )
        if eid in seen:
            raise ValueError("duplicate Entry ID")
        seen.add(eid)
        entries.append(
            Entry(
                eid,
                cid,
                row[1],
                money_cents(row[3]),
                index,
                tuple(player_id(c) for c in row[4 : 4 + len(slots)]),
            )
        )
    if not entries:
        raise ValueError("entries table contains no reserved Entry IDs")
    return Template(mode, bom, tuple(rows), tuple(records), tuple(entries))


def verify_template(
    before: Template, raw_after: bytes, mutable_ids: set[str]
) -> Template:
    after = parse_entries(raw_after)
    if (
        before.mode != after.mode
        or before.bom != after.bom
        or len(before.rows) != len(after.rows)
    ):
        raise ValueError("template geometry changed")
    if [e.entry_id for e in before.entries] != [e.entry_id for e in after.entries]:
        raise ValueError("entry identity or order changed")
    roster_by_id = {e.entry_id: e.roster for e in after.entries}
    # Render only permitted ID replacements into the original byte record.
    # Equality proves headers, instructions, fees, quoting and all other bytes.
    if before.render(roster_by_id, mutable_ids) != raw_after:
        raise ValueError("non-roster or unauthorized template bytes changed")
    return after


def inspect_embedded_pool(template: Template, players: dict[str, Player]) -> dict:
    """Cross-check DraftKings' independent draftgroup fingerprint, when present."""
    start = None
    for row in template.rows:
        for i, value in enumerate(row):
            if (
                i >= 4 + get_contract(template.mode).roster_size
                and value.strip().lower() == "position"
            ):
                start = i
                break
        if start is not None:
            break
    if start is None:
        return {
            "state": "UNAVAILABLE",
            "warning": "template has no embedded salary pool",
        }
    ids = set()
    for row in template.rows[1:]:
        if len(row) <= start + 1:
            continue
        value = row[start + 1].strip()
        if not value or value.lower() == "name + id":
            continue
        try:
            ids.add(player_id(value))
        except ValueError:
            continue
    if not ids:
        raise ValueError(
            "embedded salary pool header is present but no IDs can be verified"
        )
    overlap = len(ids & set(players)) / len(ids)
    if overlap < 0.95:
        raise ValueError(
            "embedded entries pool and salary file refer to different draftgroups"
        )
    return {"state": "PASS", "overlap": overlap, "embedded_ids": len(ids)}
