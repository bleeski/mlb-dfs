"""DraftKings Entries Manager v1.6 for MLB Classic v2.16.0.

The exported DKEntries candidate is authoritative. Certification is derived from
that exact file after it is written and re-read; callers cannot assert export or
workflow validity. DraftKings duplicate roster headers are handled positionally.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
import csv
import json
import math
import os
import re
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from mlb_engine.intake.slate_intake_manager import SalaryPlayer, parse_dk_salary_csv

VERSION = "v1.6"
ENTRY_ID_COL = 0
CONTEST_NAME_COL = 1
CONTEST_ID_COL = 2
ENTRY_FEE_COL = 3
ROSTER_START_COL = 4
ROSTER_END_COL_EXCLUSIVE = 14
ROSTER_SLOTS = ["P1", "P2", "C", "1B", "2B", "3B", "SS", "OF1", "OF2", "OF3"]
ROSTER_POSITIONS = ["P", "P", "C", "1B", "2B", "3B", "SS", "OF", "OF", "OF"]
ALLOWED_PITCHER_ROLES = {"verified_starter", "declared_probable_sp", "viable_bulk_or_alt_sp"}

PRE_EXPORT_GATES = (
    "salary_gate_passed",
    "entry_grid_gate_passed",
    "lineup_gate_passed",
    "pitcher_audit_gate_passed",
    "weather_gate_passed",
    "odds_gate_passed",
    "projection_schema_gate_passed",
    "optimizer_gate_passed",
    "selection_certified",
)
POST_EXPORT_GATES = (
    "template_preservation_passed",
    "entry_reconciliation_passed",
    "roster_legality_passed",
    "portfolio_caps_passed",
    "locked_immutability_passed",
    "export_hash_binding_passed",
)
FORBIDDEN_CALLER_ASSERTIONS = {
    "workflow_valid", "dk_export_gate_passed", "post_export_gate_passed",
    "template_preservation_passed", "entry_reconciliation_passed",
    "roster_legality_passed", "portfolio_caps_passed",
    "locked_immutability_passed", "export_hash_binding_passed",
}

CONFIDENCE_VERIFIED = "verified"
CONFIDENCE_INFERRED_HIGH = "inferred_high"
CONFIDENCE_INFERRED_MEDIUM = "inferred_medium"
CONFIDENCE_INFERRED_LOW = "inferred_low"
CONFIDENCE_UNKNOWN = "unknown"


@dataclass(frozen=True)
class DKEntryRow:
    row_index: int
    entry_id: str
    contest_name: str
    contest_id: str
    entry_fee: float
    roster_ids: Tuple[str, ...]
    roster_cells: Tuple[str, ...]
    raw_row: Tuple[str, ...]

    @property
    def is_blank(self) -> bool:
        return not any(self.roster_ids)

    @property
    def is_complete(self) -> bool:
        return len(self.roster_ids) == 10 and all(self.roster_ids)

    @property
    def lineup_signature(self) -> str:
        return "|".join(sorted(self.roster_ids)) if self.is_complete else ""

    @property
    def slot_assignments(self) -> Dict[str, str]:
        return {slot: pid for slot, pid in zip(ROSTER_SLOTS, self.roster_cells) if pid}


@dataclass(frozen=True)
class ContestArchetype:
    pattern: str
    inferred_buy_in: Optional[float]
    inferred_type: str
    inferred_max_entries: Optional[int]
    payout_shape_default: str
    confidence: str
    notes: str = ""


@dataclass
class ContestGridSummary:
    contest_id: str
    contest_name: str
    entry_fee: float
    reserved_entries: int = 0
    blank_entries: int = 0
    completed_entries: int = 0
    entry_ids: List[str] = field(default_factory=list)
    inferred_type: str = "unknown"
    inferred_max_entries: Optional[int] = None
    payout_shape_default: str = "unknown"
    confidence: str = CONFIDENCE_UNKNOWN
    decision_critical_gaps: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


def _gate_bool(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key in ("passed", "selection_certified", "allocation_certified"):
            if key in value:
                return _gate_bool(value[key])
        return False
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "pass", "passed", "certified"}
    return bool(value)


def validate_upload_ready_gates(gates: Optional[Dict[str, Any]], allocation_required: Optional[bool] = None) -> Dict[str, Any]:
    """Validate caller-supplied *pre-export* facts only.

    Post-export facts and ``workflow_valid`` are always derived by this module.
    """
    values = dict(gates or {})
    forbidden = sorted(k for k in FORBIDDEN_CALLER_ASSERTIONS if k in values)
    missing = [name for name in PRE_EXPORT_GATES if name not in values]
    failed = [name for name in PRE_EXPORT_GATES if name in values and not _gate_bool(values[name])]
    if allocation_required is None:
        allocation_required = bool(values.get("allocation_required")) or values.get("allocation_certified") is not None or bool(values.get("allocation_method"))
    if allocation_required:
        if "allocation_certified" not in values:
            missing.append("allocation_certified")
        elif not _gate_bool(values.get("allocation_certified")):
            failed.append("allocation_certified")
        method = str(values.get("allocation_method") or "").strip().lower()
        if not method:
            missing.append("allocation_method")
        elif method not in {"scipy_milp_joint", "scipy_milp_joint_select_assign", "scipy_milp_entry_level"}:
            failed.append("allocation_method")
    if forbidden:
        failed.extend(f"caller_assertion:{x}" for x in forbidden)
    missing = sorted(set(missing))
    failed = sorted(set(failed))
    errors = [f"Missing pre-export gate: {x}" for x in missing]
    errors += [f"Failed pre-export gate: {x}" for x in failed]
    return {
        "passed": not missing and not failed,
        "required_pre_export_gates": list(PRE_EXPORT_GATES),
        "missing_gates": missing,
        "failed_gates": failed,
        "forbidden_caller_assertions": forbidden,
        "gate_values": values,
        "errors": errors,
        "selection_certified": _gate_bool(values.get("selection_certified")),
        "allocation_certified": _gate_bool(values.get("allocation_certified")) if allocation_required else None,
        "allocation_method": values.get("allocation_method") if allocation_required else None,
        "summary": "Pre-export gates passed" if not errors else "Pre-export gates failed",
    }


def normalize_player_id(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    match = re.search(r"\((\d{5,})\)", text)
    if match:
        return match.group(1)
    numbers = re.findall(r"\d{5,}", text)
    if numbers:
        return numbers[-1]
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def parse_money(value: Any) -> float:
    text = re.sub(r"[^0-9.\-]", "", str(value or "").replace(",", ""))
    try:
        return float(text) if text not in {"", "-"} else 0.0
    except ValueError:
        return 0.0


def _safe_get(row: Sequence[str], index: int) -> str:
    return str(row[index]).strip() if 0 <= index < len(row) else ""


def read_csv_rows(path: str | Path) -> Tuple[List[str], List[List[str]]]:
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.reader(handle))
    if not rows:
        return [], []
    return rows[0], rows[1:]


def parse_dk_entry_rows(path: str | Path) -> List[DKEntryRow]:
    """Parse reserved rows positionally; never use ``DictReader`` for rosters."""
    header, data = read_csv_rows(path)
    if not header or [x.strip() for x in header[:4]] != ["Entry ID", "Contest Name", "Contest ID", "Entry Fee"]:
        raise ValueError("DKEntries header must start with Entry ID, Contest Name, Contest ID, Entry Fee")
    output: List[DKEntryRow] = []
    for offset, row in enumerate(data, start=2):
        entry_id = _safe_get(row, ENTRY_ID_COL)
        contest_id = _safe_get(row, CONTEST_ID_COL)
        if not entry_id or not contest_id or not re.fullmatch(r"\d+", entry_id) or not re.fullmatch(r"\d+", contest_id):
            continue
        cells = tuple(normalize_player_id(_safe_get(row, i)) for i in range(ROSTER_START_COL, ROSTER_END_COL_EXCLUSIVE))
        ids = tuple(pid for pid in cells if pid)
        output.append(DKEntryRow(
            row_index=offset,
            entry_id=entry_id,
            contest_name=_safe_get(row, CONTEST_NAME_COL),
            contest_id=contest_id,
            entry_fee=parse_money(_safe_get(row, ENTRY_FEE_COL)),
            roster_ids=ids,
            roster_cells=cells,
            raw_row=tuple(row),
        ))
    return output


def detect_player_pool_start(header: Sequence[str]) -> Optional[int]:
    for i, value in enumerate(header):
        if str(value).strip().lower() == "position" and i >= ROSTER_END_COL_EXCLUSIVE:
            return i
    return None


def parse_embedded_player_pool(path: str | Path) -> Dict[str, Dict[str, str]]:
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.reader(handle))
    if not rows:
        return {}
    start = detect_player_pool_start(rows[0])
    if start is None:
        # DK often puts embedded-pool headers on the first entry row.
        for row in rows[1:]:
            start = detect_player_pool_start(row)
            if start is not None:
                break
    if start is None:
        return {}
    output: Dict[str, Dict[str, str]] = {}
    for row in rows[1:]:
        name_id = _safe_get(row, start + 1)
        pid = normalize_player_id(name_id or _safe_get(row, start + 3))
        if not pid:
            continue
        output[pid] = {
            "position": _safe_get(row, start),
            "name_id": name_id,
            "name": _safe_get(row, start + 2),
            "id": pid,
        }
    return output


def load_salary_player_ids(path: str | Path) -> set[str]:
    return {p.player_id for p in parse_dk_salary_csv(str(path))}


DEFAULT_ARCHETYPES = [
    ContestArchetype("Daily Dollar", 1.0, "se_gpp", 1, "single_entry_gpp", CONFIDENCE_INFERRED_MEDIUM),
    ContestArchetype("Single Entry", None, "se_gpp", 1, "single_entry_gpp", CONFIDENCE_INFERRED_HIGH),
    ContestArchetype("Satellite", None, "satellite", None, "ticket_satellite", CONFIDENCE_INFERRED_HIGH),
    ContestArchetype("WTA", None, "wta", None, "winner_take_all", CONFIDENCE_INFERRED_HIGH),
    ContestArchetype("20-Max", None, "portfolio_gpp", 20, "portfolio_gpp", CONFIDENCE_INFERRED_HIGH),
    ContestArchetype("150-Max", None, "portfolio_gpp", 150, "mme_top_heavy", CONFIDENCE_INFERRED_HIGH),
]


def load_archetypes(path: Optional[str] = None) -> List[ContestArchetype]:
    if not path or not Path(path).exists():
        return list(DEFAULT_ARCHETYPES)
    output: List[ContestArchetype] = []
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            output.append(ContestArchetype(
                pattern=str(row.get("pattern") or ""),
                inferred_buy_in=parse_money(row.get("inferred_buy_in")) or None,
                inferred_type=str(row.get("inferred_type") or "unknown"),
                inferred_max_entries=int(float(row["inferred_max_entries"])) if row.get("inferred_max_entries") else None,
                payout_shape_default=str(row.get("payout_shape_default") or "unknown"),
                confidence=str(row.get("confidence") or CONFIDENCE_UNKNOWN),
                notes=str(row.get("notes") or ""),
            ))
    return output


def infer_ticket_value_from_title(contest_name: str) -> Optional[float]:
    matches = re.findall(r"\$(\d+(?:\.\d+)?)", str(contest_name or ""))
    return max((float(x) for x in matches), default=None)


def infer_contest_archetype(contest_name: str, entry_fee: Optional[float] = None, archetypes: Optional[Sequence[ContestArchetype]] = None) -> Dict[str, Any]:
    name = str(contest_name or "")
    matches = [a for a in (archetypes or DEFAULT_ARCHETYPES) if a.pattern.lower() in name.lower()]
    selected = max(matches, key=lambda a: len(a.pattern), default=None)
    if selected is None:
        return {"inferred_type": "unknown", "inferred_max_entries": None, "payout_shape_default": "unknown", "confidence": CONFIDENCE_UNKNOWN, "decision_critical_gaps": ["contest_type"]}
    gaps: List[str] = []
    if selected.inferred_type == "satellite":
        gaps = ["ticket_count", "ticket_value"]
    return {
        "inferred_type": selected.inferred_type,
        "inferred_max_entries": selected.inferred_max_entries,
        "payout_shape_default": selected.payout_shape_default,
        "confidence": selected.confidence,
        "inferred_buy_in": selected.inferred_buy_in if selected.inferred_buy_in is not None else entry_fee,
        "decision_critical_gaps": gaps,
    }


def summarize_reserved_contests(entries_path: str, archetypes_path: Optional[str] = None) -> Dict[str, Any]:
    rows = parse_dk_entry_rows(entries_path)
    archetypes = load_archetypes(archetypes_path)
    grouped: Dict[Tuple[str, str], ContestGridSummary] = {}
    for row in rows:
        key = (row.contest_id, row.contest_name)
        if key not in grouped:
            meta = infer_contest_archetype(row.contest_name, row.entry_fee, archetypes)
            grouped[key] = ContestGridSummary(
                contest_id=row.contest_id, contest_name=row.contest_name, entry_fee=row.entry_fee,
                inferred_type=meta["inferred_type"], inferred_max_entries=meta["inferred_max_entries"],
                payout_shape_default=meta["payout_shape_default"], confidence=meta["confidence"],
                decision_critical_gaps=list(meta["decision_critical_gaps"]),
            )
        rec = grouped[key]
        rec.reserved_entries += 1
        rec.blank_entries += int(row.is_blank)
        rec.completed_entries += int(row.is_complete)
        rec.entry_ids.append(row.entry_id)
    contests = [x.to_dict() for x in grouped.values()]
    return {
        "mode": "reserved_entry_execution",
        "entry_count": len(rows),
        "blank_entry_count": sum(r.is_blank for r in rows),
        "completed_entry_count": sum(r.is_complete for r in rows),
        "contests": sorted(contests, key=lambda x: (x["contest_name"], x["contest_id"])),
        "player_pool_count": len(parse_embedded_player_pool(entries_path)),
        "warnings": reserved_entry_grid_warnings(contests),
    }


def reserved_entry_grid_warnings(contest_summaries: Sequence[Dict[str, Any]]) -> List[str]:
    output = []
    for row in contest_summaries:
        if row.get("decision_critical_gaps"):
            output.append(f"{row.get('contest_name')}: missing {', '.join(row['decision_critical_gaps'])}")
        if row.get("blank_entries"):
            output.append(f"{row.get('contest_name')}: {row['blank_entries']} blank reserved entries")
    return output


def _lineup_from_assignment(assignment: Mapping[str, Any]) -> List[str]:
    if assignment.get("roster_slot_ids") is not None:
        raw = assignment["roster_slot_ids"]
        if isinstance(raw, Mapping):
            values = [raw.get(slot, "") for slot in ROSTER_SLOTS]
        else:
            values = list(raw)
    elif assignment.get("lineup_ids") is not None:
        values = list(assignment["lineup_ids"])
    elif assignment.get("roster_ids") is not None:
        values = list(assignment["roster_ids"])
    else:
        values = [assignment.get(slot, "") for slot in ROSTER_SLOTS]
    ids = [normalize_player_id(x) for x in values]
    if len(ids) != 10 or not all(ids):
        raise ValueError(f"assignment must contain ten ordered Player_IDs: {assignment}")
    return ids


def write_candidate_from_template(
    template_path: str | Path,
    assignments: Sequence[Mapping[str, Any]],
    candidate_path: str | Path,
    preserve_completed: bool = True,
) -> Dict[str, Any]:
    """Write a candidate without overwriting the source template."""
    source = Path(template_path).resolve()
    target = Path(candidate_path).resolve()
    if source == target:
        raise ValueError("candidate_path must differ from template_path")
    with source.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.reader(handle))
    parsed = parse_dk_entry_rows(source)
    by_entry = {r.entry_id: r for r in parsed}
    used: set[str] = set()
    errors: List[str] = []
    logs: List[Dict[str, Any]] = []
    for assignment in assignments:
        entry_id = str(assignment.get("entry_id") or "").strip()
        if not entry_id or entry_id not in by_entry:
            errors.append(f"assignment Entry ID not found: {entry_id or assignment}")
            continue
        if entry_id in used:
            errors.append(f"duplicate assignment for Entry ID {entry_id}")
            continue
        row = by_entry[entry_id]
        if preserve_completed and row.is_complete:
            intended = _lineup_from_assignment(assignment)
            if tuple(intended) != row.roster_cells:
                errors.append(f"Entry ID {entry_id} is already complete and immutable")
            continue
        try:
            lineup = _lineup_from_assignment(assignment)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        raw_index = row.row_index - 1
        while len(rows[raw_index]) < ROSTER_END_COL_EXCLUSIVE:
            rows[raw_index].append("")
        rows[raw_index][ROSTER_START_COL:ROSTER_END_COL_EXCLUSIVE] = lineup
        used.add(entry_id)
        logs.append({
            "entry_id": entry_id, "contest_id": row.contest_id, "row_number": row.row_index,
            "lineup_signature": "|".join(sorted(lineup)), "ordered_roster": lineup,
        })
    if errors:
        return {"passed": False, "errors": errors, "candidate_path": None, "assignment_log": logs}
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    with tmp.open("w", newline="", encoding="utf-8") as handle:
        csv.writer(handle).writerows(rows)
    os.replace(tmp, target)
    return {"passed": True, "errors": [], "candidate_path": str(target), "assignment_log": logs}


def validate_template_preservation(source_path: str | Path, candidate_path: str | Path, mutable_entry_ids: Optional[Iterable[str]] = None) -> Dict[str, Any]:
    mutable = {str(x) for x in (mutable_entry_ids or [])}
    with Path(source_path).open(newline="", encoding="utf-8-sig") as handle:
        source_rows = list(csv.reader(handle))
    with Path(candidate_path).open(newline="", encoding="utf-8-sig") as handle:
        candidate_rows = list(csv.reader(handle))
    errors: List[str] = []
    if len(source_rows) != len(candidate_rows):
        errors.append("row count changed")
        return {"passed": False, "errors": errors}
    source_entries = {r.row_index: r for r in parse_dk_entry_rows(source_path)}
    for i, (source, candidate) in enumerate(zip(source_rows, candidate_rows), start=1):
        width = max(len(source), len(candidate))
        s = source + [""] * (width - len(source))
        c = candidate + [""] * (width - len(candidate))
        for col in list(range(0, ROSTER_START_COL)) + list(range(ROSTER_END_COL_EXCLUSIVE, width)):
            if s[col] != c[col]:
                errors.append(f"non-roster cell changed at row {i}, column {col + 1}")
        source_entry = source_entries.get(i)
        if source_entry and source_entry.is_complete and source_entry.entry_id not in mutable:
            if s[ROSTER_START_COL:ROSTER_END_COL_EXCLUSIVE] != c[ROSTER_START_COL:ROSTER_END_COL_EXCLUSIVE]:
                errors.append(f"completed Entry ID {source_entry.entry_id} changed")
    return {"passed": not errors, "errors": errors, "summary": "Template preserved" if not errors else "Template preservation failed"}


def reconcile_entries_against_assignments(intended_assignments: Sequence[Mapping[str, Any]], actual_path: str | Path) -> Dict[str, Any]:
    """Reconcile exact Entry IDs and ordered ten-slot rosters."""
    intended: Dict[str, Tuple[str, ...]] = {}
    errors: List[str] = []
    for row in intended_assignments:
        entry_id = str(row.get("entry_id") or "")
        if not entry_id:
            errors.append("intended assignment missing Entry ID")
            continue
        if entry_id in intended:
            errors.append(f"duplicate intended Entry ID {entry_id}")
            continue
        intended[entry_id] = tuple(_lineup_from_assignment(row))
    actual_rows = {r.entry_id: r for r in parse_dk_entry_rows(actual_path)}
    rows = []
    for entry_id, roster in intended.items():
        actual = actual_rows.get(entry_id)
        if actual is None:
            errors.append(f"missing actual Entry ID {entry_id}")
            continue
        matched = actual.roster_cells == roster
        rows.append({"entry_id": entry_id, "contest_id": actual.contest_id, "matched": matched})
        if not matched:
            errors.append(f"Entry ID {entry_id} ordered roster mismatch")
    extra_populated = [r.entry_id for r in actual_rows.values() if r.is_complete and r.entry_id not in intended]
    return {
        "passed": not errors,
        "errors": errors,
        "rows": rows,
        "extra_populated_entry_ids": extra_populated,
        "summary": "Exact Entry ID reconciliation passed" if not errors else "Exact Entry ID reconciliation failed",
    }


def _cap_count(total: int, pct: Optional[float]) -> Optional[int]:
    """Resolve a percentage cap to a count. ``pct <= 0`` means "not set".

    Semantics are aligned with ``contest_allocator._cap_count`` so the solved
    model and the post-export validator can never disagree on a cap value.
    """
    if pct is None:
        return None
    value = float(pct)
    if value <= 0:
        return None
    return max(1, int(math.floor(total * min(1.0, value) + 1e-9)))


def _game_cap_count(total: int, pct: float) -> int:
    """Game-exposure caps are explicit per-game intent: ``pct <= 0`` means zero."""
    return max(0, int(math.floor(total * min(1.0, max(0.0, float(pct))) + 1e-9)))


def _primary_stack(roster: Sequence[str], players: Mapping[str, SalaryPlayer]) -> str:
    counts = Counter(players[pid].team for pid in roster if pid in players and "P" not in players[pid].positions)
    if not counts:
        return ""
    best = max(counts.values())
    return sorted(team for team, count in counts.items() if count == best)[0]


def validate_dk_entries_file(
    path: str | Path,
    salary_csv_path: Optional[str | Path] = None,
    salary_player_ids: Optional[Iterable[str]] = None,
    confirmed_hitter_ids: Optional[Iterable[str]] = None,
    pitcher_roles: Optional[Mapping[str, str]] = None,
    excluded_player_ids: Optional[Iterable[str]] = None,
    locked_slot_assignments: Optional[Mapping[str, Mapping[str, str]]] = None,
    portfolio_controls: Optional[Mapping[str, Any]] = None,
    require_all_reserved_filled: bool = True,
    confirmed_teams: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Validate legality and portfolio controls from the exact exported CSV.

    ``confirmed_teams`` makes the confirmed-hitter check per-team: hitters on a
    confirmed team must appear in ``confirmed_hitter_ids``; hitters on teams not
    listed (TBD lineups) pass. When None, the legacy global-set check applies.
    """
    entries = parse_dk_entry_rows(path)
    controls = dict(portfolio_controls or {})
    players: Dict[str, SalaryPlayer] = {}
    if salary_csv_path:
        players = {p.player_id: p for p in parse_dk_salary_csv(str(salary_csv_path))}
    allowed_ids = set(players) if players else {normalize_player_id(x) for x in (salary_player_ids or [])}
    confirmed = {normalize_player_id(x) for x in (confirmed_hitter_ids or [])}
    confirmed_team_set = {str(t).strip().upper() for t in confirmed_teams} if confirmed_teams is not None else None
    excluded = {normalize_player_id(x) for x in (excluded_player_ids or [])}
    roles = {normalize_player_id(k): str(v) for k, v in (pitcher_roles or {}).items()}
    locked = {str(k): {str(slot): normalize_player_id(pid) for slot, pid in v.items()} for k, v in (locked_slot_assignments or {}).items()}
    errors: List[str] = []
    warnings: List[str] = []
    blank_entries: List[str] = []
    invalid_ids: List[Dict[str, Any]] = []
    legal_rosters: List[Tuple[DKEntryRow, Tuple[str, ...]]] = []
    by_contest_sig: Dict[str, Counter] = defaultdict(Counter)

    for entry in entries:
        if not entry.is_complete:
            blank_entries.append(entry.entry_id)
            if require_all_reserved_filled:
                errors.append(f"Entry ID {entry.entry_id}: reserved row is blank or incomplete")
            continue
        roster = entry.roster_cells
        if len(set(roster)) != 10:
            errors.append(f"Entry ID {entry.entry_id}: duplicate Player_ID")
        missing = [pid for pid in roster if allowed_ids and pid not in allowed_ids]
        if missing:
            invalid_ids.append({"entry_id": entry.entry_id, "ids": missing})
            errors.append(f"Entry ID {entry.entry_id}: invalid Player_ID(s) {missing}")
            continue
        if excluded.intersection(roster):
            errors.append(f"Entry ID {entry.entry_id}: excluded player rostered")
        for slot, required_pos, pid in zip(ROSTER_SLOTS, ROSTER_POSITIONS, roster):
            player = players.get(pid)
            if player and required_pos not in player.positions:
                errors.append(f"Entry ID {entry.entry_id}: {pid} not eligible for {slot}")
        if players:
            salary = sum(players[pid].salary for pid in roster)
            if salary > 50000 + 1e-6:
                errors.append(f"Entry ID {entry.entry_id}: salary {salary:.0f} exceeds 50000")
            pitcher_ids = roster[:2]
            if any("P" not in players[pid].positions for pid in pitcher_ids):
                errors.append(f"Entry ID {entry.entry_id}: first two slots must be pitchers")
            hitter_teams = Counter(players[pid].team for pid in roster[2:])
            if hitter_teams and max(hitter_teams.values()) > 5:
                errors.append(f"Entry ID {entry.entry_id}: more than five hitters from one team")
            games = {players[pid].game_id for pid in roster if players[pid].game_id}
            if len(games) < 2:
                errors.append(f"Entry ID {entry.entry_id}: fewer than two games represented")
            for spid in pitcher_ids:
                opponent = players[spid].opponent
                if any(players[hid].team == opponent for hid in roster[2:]):
                    errors.append(f"Entry ID {entry.entry_id}: hitter against rostered opposing pitcher {spid}")
            if confirmed:
                for pid in roster[2:]:
                    hitter_team = players[pid].team if pid in players else ""
                    team_requires_confirmation = (
                        confirmed_team_set is None or hitter_team in confirmed_team_set
                    )
                    if team_requires_confirmation and pid not in confirmed:
                        errors.append(f"Entry ID {entry.entry_id}: unconfirmed hitter {pid}")
            if roles:
                for pid in pitcher_ids:
                    if roles.get(pid) not in ALLOWED_PITCHER_ROLES:
                        errors.append(f"Entry ID {entry.entry_id}: ineligible pitcher role for {pid}")
        for slot, pid in locked.get(entry.entry_id, {}).items():
            if slot not in ROSTER_SLOTS:
                errors.append(f"Entry ID {entry.entry_id}: unknown locked slot {slot}")
            elif roster[ROSTER_SLOTS.index(slot)] != pid:
                errors.append(f"Entry ID {entry.entry_id}: locked slot {slot} changed")
        by_contest_sig[entry.contest_id][entry.lineup_signature] += 1
        legal_rosters.append((entry, roster))

    duplicate_same_contest = []
    for contest_id, counter in by_contest_sig.items():
        for signature, count in counter.items():
            if signature and count > 1:
                duplicate_same_contest.append({"contest_id": contest_id, "signature": signature, "count": count})
                errors.append(f"Contest {contest_id}: duplicate roster appears {count} times")

    total = len(legal_rosters)
    player_counts = Counter(pid for _, roster in legal_rosters for pid in roster)
    pitcher_counts = Counter(pid for _, roster in legal_rosters for pid in roster[:2])
    stack_counts = Counter(_primary_stack(roster, players) for _, roster in legal_rosters) if players else Counter()
    pair_counts = Counter(tuple(sorted(roster[:2])) for _, roster in legal_rosters)
    portfolio_errors: List[str] = []
    player_cap = _cap_count(total, controls.get("max_player_exposure_pct"))
    pitcher_cap = _cap_count(total, controls.get("max_pitcher_exposure_pct"))
    stack_cap = _cap_count(total, controls.get("max_primary_stack_exposure_pct"))
    pair_cap = controls.get("max_sp_pair_repetition")
    max_overlap = controls.get("max_shared_players")
    if player_cap:
        portfolio_errors += [f"player {pid} count {count}>{player_cap}" for pid, count in player_counts.items() if count > player_cap]
    if pitcher_cap:
        portfolio_errors += [f"pitcher {pid} count {count}>{pitcher_cap}" for pid, count in pitcher_counts.items() if count > pitcher_cap]
    if stack_cap:
        portfolio_errors += [f"primary stack {team} count {count}>{stack_cap}" for team, count in stack_counts.items() if team and count > stack_cap]
    if pair_cap is not None:
        portfolio_errors += [f"SP pair {'/'.join(pair)} count {count}>{int(pair_cap)}" for pair, count in pair_counts.items() if count > int(pair_cap)]
    overlap_violations = []
    game_caps = dict(controls.get("max_game_exposure_pct_by_game") or {})
    if game_caps and players:
        game_counts: Counter = Counter()
        for _, roster in legal_rosters:
            games_in = {players[pid].game_id for pid in roster if pid in players and players[pid].game_id}
            for gid in games_in:
                game_counts[gid] += 1
        for gid, pct in game_caps.items():
            cap = _game_cap_count(total, pct)
            count = game_counts.get(str(gid), 0)
            if count > cap:
                portfolio_errors.append(f"game {gid} exposure {count}>{cap}")
    if max_overlap is not None:
        for i, (entry_a, roster_a) in enumerate(legal_rosters):
            for entry_b, roster_b in legal_rosters[i + 1:]:
                if entry_a.lineup_signature == entry_b.lineup_signature:
                    continue  # approved cross-contest reuse of the same candidate
                shared = len(set(roster_a) & set(roster_b))
                if shared > int(max_overlap):
                    overlap_violations.append({"entry_a": entry_a.entry_id, "entry_b": entry_b.entry_id, "shared": shared})
                    portfolio_errors.append(f"entries {entry_a.entry_id}/{entry_b.entry_id} share {shared}>{max_overlap}")
    errors.extend(portfolio_errors)
    if blank_entries and not require_all_reserved_filled:
        warnings.append(f"{len(blank_entries)} blank/incomplete reserved entries")

    roster_legality_errors = [e for e in errors if not e.startswith(("player ", "pitcher ", "primary stack ", "SP pair ", "entries ", "game "))]
    return {
        "passed": not errors,
        "errors": errors,
        "warnings": warnings,
        "entry_count": len(entries),
        "complete_entry_count": total,
        "blank_entries": blank_entries,
        "invalid_ids": invalid_ids,
        "duplicate_same_contest": duplicate_same_contest,
        "roster_legality_passed": not roster_legality_errors,
        "portfolio_caps_passed": not portfolio_errors,
        "locked_immutability_passed": not any("locked slot" in e for e in errors),
        "exposures": {
            "player_counts": dict(player_counts), "pitcher_counts": dict(pitcher_counts),
            "primary_stack_counts": dict(stack_counts),
            "sp_pair_counts": {"/".join(k): v for k, v in pair_counts.items()},
            "total_lineups": total,
        },
        "overlap_violations": overlap_violations,
        "resolved_caps": {
            "max_player_count": player_cap, "max_pitcher_count": pitcher_cap,
            "max_primary_stack_count": stack_cap, "max_sp_pair_repetition": pair_cap,
            "max_shared_players": max_overlap,
            "max_game_exposure_pct_by_game": game_caps or None,
        },
        "summary": "DKEntries validation passed" if not errors else f"DKEntries validation failed with {len(errors)} error(s)",
    }


def derive_workflow_certification(pre_export: Dict[str, Any], post_export: Dict[str, Any], allocation_required: bool) -> Dict[str, Any]:
    post_values = {
        "template_preservation_passed": bool(post_export.get("template_preservation_passed")),
        "entry_reconciliation_passed": bool(post_export.get("entry_reconciliation_passed")),
        "roster_legality_passed": bool(post_export.get("roster_legality_passed")),
        "portfolio_caps_passed": bool(post_export.get("portfolio_caps_passed")),
        "locked_immutability_passed": bool(post_export.get("locked_immutability_passed")),
        "export_hash_binding_passed": bool(post_export.get("export_hash_binding_passed")),
    }
    failed_post = [k for k, v in post_values.items() if not v]
    allocation = pre_export.get("allocation_certified") if allocation_required else None
    workflow_valid = bool(pre_export.get("passed")) and not failed_post and (allocation is not False)
    return {
        "workflow_valid": workflow_valid,
        "selection_certified": bool(pre_export.get("selection_certified")) and workflow_valid,
        "allocation_certified": bool(allocation) and workflow_valid if allocation_required else None,
        "pre_export_passed": bool(pre_export.get("passed")),
        "post_export_gates": post_values,
        "failed_post_export_gates": failed_post,
    }


def populate_dk_entries_template(
    template_path: str,
    assignments: Sequence[Dict[str, Any]],
    output_path: str,
    salary_player_ids: Optional[Iterable[str]] = None,
    workflow_gates: Optional[Dict[str, Any]] = None,
    *,
    salary_csv_path: Optional[str] = None,
    confirmed_hitter_ids: Optional[Iterable[str]] = None,
    pitcher_roles: Optional[Mapping[str, str]] = None,
    excluded_player_ids: Optional[Iterable[str]] = None,
    locked_slot_assignments: Optional[Mapping[str, Mapping[str, str]]] = None,
    portfolio_controls: Optional[Mapping[str, Any]] = None,
    allocation_required: Optional[bool] = None,
) -> Dict[str, Any]:
    """Compatibility wrapper: write, re-read, validate, and promote atomically.

    For hash-bound production runs use :mod:`execution_pipeline`; this wrapper
    cannot satisfy ``export_hash_binding_passed`` on its own and therefore does
    not claim full project workflow validity.
    """
    pre = validate_upload_ready_gates(workflow_gates, allocation_required=allocation_required)
    if Path(output_path).exists():
        return {
            "passed": False,
            "errors": [
                f"output_path already exists: {output_path}; this compatibility wrapper "
                "never overwrites or deletes an existing export. Use execution_pipeline "
                "for run-scoped, hash-bound production output."
            ],
            "output_path": None, "workflow_valid": False,
        }
    diagnostic = str(Path(output_path).with_name("DO_NOT_UPLOAD_" + Path(output_path).name))
    write = write_candidate_from_template(template_path, assignments, diagnostic)
    if not write["passed"]:
        return {**write, "workflow_gate": pre, "output_path": None}
    validation = validate_dk_entries_file(
        diagnostic, salary_csv_path=salary_csv_path, salary_player_ids=salary_player_ids,
        confirmed_hitter_ids=confirmed_hitter_ids, pitcher_roles=pitcher_roles,
        excluded_player_ids=excluded_player_ids, locked_slot_assignments=locked_slot_assignments,
        portfolio_controls=portfolio_controls,
    )
    template = validate_template_preservation(template_path, diagnostic)
    reconciliation = reconcile_entries_against_assignments(assignments, diagnostic)
    if not pre["passed"] or not validation["passed"] or not template["passed"] or not reconciliation["passed"]:
        return {
            "passed": False, "errors": pre["errors"] + validation["errors"] + template["errors"] + reconciliation["errors"],
            "output_path": None, "diagnostic_output_path": diagnostic, "validation": validation,
            "template_preservation": template, "reconciliation": reconciliation, "workflow_gate": pre,
            "workflow_valid": False,
        }
    os.replace(diagnostic, output_path)
    return {
        "passed": True, "errors": [], "output_path": output_path, "diagnostic_output_path": None,
        "validation": validation, "template_preservation": template, "reconciliation": reconciliation,
        "workflow_gate": pre, "workflow_valid": False,
        "summary": "Export legal but full hash-bound workflow certification requires execution_pipeline.py",
    }


def write_reserved_contest_summary(summary: Dict[str, Any], path: str) -> str:
    Path(path).write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    return path
