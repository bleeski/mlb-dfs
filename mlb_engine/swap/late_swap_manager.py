"""MLB Classic late-swap manager v1.3.

Builds exact entry-level lock contracts. ``validate_only`` may identify forced
changes but never inherits selection/allocation certification. ``reoptimize``
produces requirements for the entry-level joint SciPy MILP.

v1.3 fail-closed changes:
- A roster player missing from ``status_by_player_id`` is never treated as
  swappable. The default policy raises; ``treat_as_locked`` freezes the slot.
- ``build_entry_requirements`` accepts ``authorized_entry_ids`` and only emits
  requirements for authorized entries; unknown authorized IDs raise.
- Fully locked entries are excluded from the joint solve instead of demanding
  an exact-replica candidate; the export gates byte-protect them.
- ``load_latest_valid_parent_run`` re-verifies every recorded parent hash via
  ``verify_run_bundle`` before the parent can anchor a late swap.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from mlb_engine.pipeline.build_state_manager import get_latest_promoted_run, verify_run_bundle
from mlb_engine.entries.dk_entries_manager import ROSTER_SLOTS, parse_dk_entry_rows

VERSION = "v1.4"
CONFIRMED_STARTER = "Confirmed_Starter"
PROJECTED_STARTER = "Projected_Starter"
BENCH_RISK = "Bench_Risk"
CONFIRMED_OUT = "Confirmed_Out"
UNKNOWN = "Unknown"
SAFE_UNLOCKED_STATUSES = {CONFIRMED_STARTER, PROJECTED_STARTER}
TBD_STATUSES = {PROJECTED_STARTER, BENCH_RISK, UNKNOWN}
BLOCK_STATUSES = {CONFIRMED_OUT}
LATE_SWAP_MODES = {"reoptimize", "validate_only"}
MISSING_STATUS_POLICIES = {"error", "treat_as_locked"}


@dataclass(frozen=True)
class GameLock:
    game_id: str
    away_team: str
    home_team: str
    start_time: datetime
    venue: str = ""
    roof: str = "unknown"
    lineup_status: str = "TBD"
    lock_cohort: Optional[int] = None

    def normalized_start(self) -> datetime:
        value = self.start_time
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class PlayerLineupStatus:
    player_id: str
    name: str
    team: str
    game_id: str
    lock_time: datetime
    status: str
    batting_order: Optional[int] = None
    positions: Tuple[str, ...] = tuple()
    salary: Optional[float] = None
    risk_tag: str = ""

    def is_locked(self, as_of: datetime) -> bool:
        lock = self.lock_time if self.lock_time.tzinfo else self.lock_time.replace(tzinfo=timezone.utc)
        current = as_of if as_of.tzinfo else as_of.replace(tzinfo=timezone.utc)
        return current.astimezone(timezone.utc) >= lock.astimezone(timezone.utc)

    def is_tbd(self) -> bool:
        return self.status in TBD_STATUSES


@dataclass
class LockedLineupState:
    contest_id: str
    entry_id: str
    lineup_id: str
    player_ids: List[str]
    locked_player_ids: List[str]
    unlocked_player_ids: List[str]
    locked_slot_assignments: Dict[str, str] = field(default_factory=dict)
    unlocked_slots: List[str] = field(default_factory=list)
    salary_used: float = 0.0
    salary_cap: float = 50000.0

    @property
    def salary_remaining(self) -> float:
        return max(0.0, self.salary_cap - self.salary_used)


def build_lock_cohorts(games: Sequence[GameLock]) -> List[GameLock]:
    sorted_games = sorted(games, key=lambda game: (game.normalized_start(), game.game_id))
    cohort_by_time: Dict[datetime, int] = {}
    output = []
    for game in sorted_games:
        ts = game.normalized_start()
        if ts not in cohort_by_time:
            cohort_by_time[ts] = len(cohort_by_time) + 1
        output.append(GameLock(
            game.game_id, game.away_team, game.home_team, game.start_time,
            game.venue, game.roof, game.lineup_status, cohort_by_time[ts],
        ))
    return output


def players_by_lock_state(players: Sequence[PlayerLineupStatus], as_of: datetime) -> Dict[str, List[PlayerLineupStatus]]:
    return {
        "locked": [p for p in players if p.is_locked(as_of)],
        "unlocked": [p for p in players if not p.is_locked(as_of)],
    }


def validate_tbd_policy(players: Sequence[PlayerLineupStatus], as_of: datetime, contest_late_swap: bool, max_tbd_hitters_per_lineup: int = 3) -> Dict[str, Any]:
    errors, warnings, tbd = [], [], []
    for player in players:
        if player.status in BLOCK_STATUSES:
            errors.append(f"{player.player_id} {player.name}: confirmed out")
        elif player.is_tbd():
            if player.is_locked(as_of):
                errors.append(f"{player.player_id} {player.name}: TBD at/after lock")
            elif not contest_late_swap:
                errors.append(f"{player.player_id} {player.name}: TBD in non-late-swap contest")
            else:
                tbd.append(player.player_id)
                warnings.append(f"{player.player_id} {player.name}: pivot required")
    if len(tbd) > max_tbd_hitters_per_lineup:
        errors.append(f"TBD count {len(tbd)} exceeds {max_tbd_hitters_per_lineup}")
    return {"passed": not errors, "errors": errors, "warnings": warnings, "tbd_unlocked_player_ids": tbd}


def _eligible_for_pivot(original: PlayerLineupStatus, candidate: PlayerLineupStatus, salary_buffer: float) -> bool:
    if candidate.status in BLOCK_STATUSES or candidate.is_tbd() or candidate.player_id == original.player_id:
        return False
    if original.salary is not None and candidate.salary is not None and candidate.salary > original.salary + salary_buffer:
        return False
    if original.positions and candidate.positions and not set(original.positions).intersection(candidate.positions):
        return False
    return True


def pivot_requirements_for_tbd_players(lineup_players: Sequence[PlayerLineupStatus], full_player_pool: Sequence[PlayerLineupStatus], as_of: datetime, salary_buffer: float = 500.0, min_pivots: int = 2) -> Dict[str, Any]:
    rows, errors = [], []
    pool = [p for p in full_player_pool if not p.is_locked(as_of)]
    for player in lineup_players:
        if not player.is_tbd() or player.is_locked(as_of):
            continue
        options = [candidate for candidate in pool if _eligible_for_pivot(player, candidate, salary_buffer)]
        options.sort(key=lambda candidate: (candidate.batting_order or 99, -(candidate.salary or 0)))
        passed = len(options) >= min_pivots
        rows.append({"player_id": player.player_id, "pivot_count": len(options), "primary_pivots": [x.player_id for x in options[:3]], "passed": passed})
        if not passed:
            errors.append(f"{player.player_id}: only {len(options)} pivot(s)")
    return {"passed": not errors, "rows": rows, "errors": errors}


def freeze_lineup_state(
    contest_id: str,
    entry_id: str,
    lineup_id: str,
    lineup_player_ids: Sequence[str],
    status_by_player_id: Mapping[str, PlayerLineupStatus],
    as_of: datetime,
    salary_used: float = 0.0,
    salary_cap: float = 50000.0,
    roster_slots: Optional[Sequence[str]] = None,
    missing_status_policy: str = "error",
) -> LockedLineupState:
    """Freeze lock state for one roster. Unknown lock state never unlocks a slot.

    ``missing_status_policy='error'`` (default) raises when any populated roster
    Player_ID is absent from ``status_by_player_id``. ``'treat_as_locked'``
    freezes those slots instead. There is intentionally no fail-open option.
    """
    if missing_status_policy not in MISSING_STATUS_POLICIES:
        raise ValueError(f"missing_status_policy must be one of {sorted(MISSING_STATUS_POLICIES)}")
    slots = list(roster_slots or ROSTER_SLOTS)
    if len(slots) != len(lineup_player_ids):
        raise ValueError("roster_slots and lineup_player_ids lengths differ")
    missing = sorted({str(pid) for pid in lineup_player_ids if str(pid or "").strip() and str(pid) not in status_by_player_id})
    if missing and missing_status_policy == "error":
        raise ValueError(
            f"lock state unknown for Player_ID(s) {missing}; supply a complete "
            "status_by_player_id (see live_data_adapters.build_status_map_from_lineups_feed) "
            "or pass missing_status_policy='treat_as_locked'"
        )
    locked_players, unlocked_players, locked_slots, unlocked_slots = [], [], {}, []
    for slot, pid in zip(slots, lineup_player_ids):
        pid_text = str(pid or "").strip()
        if not pid_text:
            unlocked_slots.append(str(slot))
            continue
        player = status_by_player_id.get(pid_text)
        if player is None:
            # treat_as_locked: unknown lock state freezes the exact slot.
            locked_players.append(pid_text); locked_slots[str(slot)] = pid_text
        elif player.is_locked(as_of):
            locked_players.append(pid_text); locked_slots[str(slot)] = pid_text
        else:
            unlocked_players.append(pid_text); unlocked_slots.append(str(slot))
    return LockedLineupState(
        contest_id=str(contest_id), entry_id=str(entry_id), lineup_id=str(lineup_id),
        player_ids=[str(x) for x in lineup_player_ids], locked_player_ids=locked_players,
        unlocked_player_ids=unlocked_players, locked_slot_assignments=locked_slots,
        unlocked_slots=unlocked_slots, salary_used=float(salary_used), salary_cap=float(salary_cap),
    )


def build_locked_slot_map(
    entry_roster: Sequence[str],
    status_by_player_id: Mapping[str, PlayerLineupStatus],
    as_of: datetime,
    missing_status_policy: str = "error",
) -> Dict[str, str]:
    state = freeze_lineup_state(
        "", "", "", entry_roster, status_by_player_id, as_of,
        missing_status_policy=missing_status_policy,
    )
    return state.locked_slot_assignments


def partial_rebuild_constraints(state: LockedLineupState) -> Dict[str, Any]:
    return {
        "contest_id": state.contest_id,
        "entry_id": state.entry_id,
        "lineup_id": state.lineup_id,
        "locked_player_ids": list(state.locked_player_ids),
        "locked_slot_assignments": dict(state.locked_slot_assignments),
        "unlocked_player_ids": list(state.unlocked_player_ids),
        "unlocked_slots": list(state.unlocked_slots),
        "salary_cap": state.salary_cap,
        "salary_used_current": state.salary_used,
        "salary_remaining_current": state.salary_remaining,
        "rule": "locked_player_ids and locked_slot_assignments are immutable; optimize only unlocked roster slots",
    }


def load_latest_valid_parent_run(runs_root: str | Path) -> Dict[str, Any]:
    """Load the latest promoted run and re-verify every recorded hash.

    The pointer alone only proves the manifest is intact. A tampered final
    export under a promoted manifest must not anchor a late swap, so the full
    bundle (inputs, artifacts, diagnostics binding) is re-verified here.
    """
    latest = get_latest_promoted_run(runs_root)
    if latest is None:
        raise FileNotFoundError("no promoted parent run found")
    verification = verify_run_bundle(latest["run_dir"])
    if not verification["passed"]:
        raise RuntimeError(
            f"promoted parent run {latest['manifest'].get('run_id')} failed integrity "
            f"verification: {verification['errors']}"
        )
    latest["verification"] = verification
    return latest


def build_entry_requirements(
    entries_path: str | Path,
    status_by_player_id: Mapping[str, PlayerLineupStatus],
    as_of: datetime,
    contest_shapes: Optional[Mapping[str, str]] = None,
    mode: str = "reoptimize",
    authorized_entry_ids: Optional[Iterable[str]] = None,
    missing_status_policy: str = "error",
) -> List[Dict[str, Any]]:
    """Build entry-level lock contracts for the joint MILP.

    ``authorized_entry_ids`` restricts the swap to exactly those Entry IDs; all
    other reserved entries are excluded from the requirements and therefore
    byte-protected by the template-preservation and delta gates. None means
    every reserved Entry ID is authorized (explicitly all, not silently all).
    Authorized IDs not present in the DKEntries file raise.

    Entries whose ten slots are all locked are skipped: nothing is mutable, so
    forcing an exact-replica candidate into the solve would block the whole
    swap. Skipped fully locked entries remain protected by the export gates.
    """
    if mode not in LATE_SWAP_MODES:
        raise ValueError(f"mode must be one of {sorted(LATE_SWAP_MODES)}")
    authorized = {str(x).strip() for x in authorized_entry_ids} if authorized_entry_ids is not None else None
    if authorized is not None and not authorized:
        raise ValueError("authorized_entry_ids was provided but empty; nothing to swap")
    requirements = []
    seen_entry_ids: set[str] = set()
    locked_teams = sorted({player.team for player in status_by_player_id.values() if player.is_locked(as_of)})
    player_team_by_id = {str(pid): player.team for pid, player in status_by_player_id.items()}
    for entry in parse_dk_entry_rows(entries_path):
        seen_entry_ids.add(entry.entry_id)
        if authorized is not None and entry.entry_id not in authorized:
            continue
        locked_slots = (
            build_locked_slot_map(
                entry.roster_cells, status_by_player_id, as_of,
                missing_status_policy=missing_status_policy,
            )
            if entry.is_complete else {}
        )
        if entry.is_complete and len(locked_slots) == len(ROSTER_SLOTS):
            continue  # fully locked: nothing mutable; export gates byte-protect it
        requirements.append({
            "entry_id": entry.entry_id,
            "contest_id": entry.contest_id,
            "contest_name": entry.contest_name,
            "contest_shape": (contest_shapes or {}).get(entry.contest_id, "large_wta"),
            "locked_slot_assignments": locked_slots,
            "locked_player_ids": list(locked_slots.values()),
            "excluded_new_teams": locked_teams,
            "player_team_by_id": player_team_by_id,
            "late_swap_mode": mode,
        })
    if authorized is not None:
        unknown = sorted(authorized - seen_entry_ids)
        if unknown:
            raise ValueError(f"authorized Entry IDs not present in DKEntries file: {unknown}")
    return requirements


def validate_locked_immutability(source_path: str | Path, candidate_path: str | Path, locked_slot_assignments: Mapping[str, Mapping[str, str]]) -> Dict[str, Any]:
    actual = {row.entry_id: row for row in parse_dk_entry_rows(candidate_path)}
    errors = []
    for entry_id, slots in locked_slot_assignments.items():
        row = actual.get(str(entry_id))
        if row is None:
            errors.append(f"missing Entry ID {entry_id}")
            continue
        for slot, pid in slots.items():
            if slot not in ROSTER_SLOTS or row.roster_cells[ROSTER_SLOTS.index(slot)] != str(pid):
                errors.append(f"Entry ID {entry_id}: locked slot {slot} changed")
    return {"passed": not errors, "errors": errors}


def validate_late_swap_delta(source_path: str | Path, candidate_path: str | Path, mutable_entry_ids: Optional[Iterable[str]] = None) -> Dict[str, Any]:
    """Diff a swapped file against its parent and reject unauthorized changes.

    ``mutable_entry_ids=None`` means unrestricted: no authorization was
    expressed, so every change is allowed. An explicitly EMPTY collection means
    nothing is mutable, and any roster change is an error.

    Those two used to be the same thing (F16). ``{str(x) for x in (ids or [])}``
    collapsed None and [] to the same empty set and the guard then read
    ``if mutable and ...``, so an empty authorized set fell through to "anything
    may change" on the one path that runs closest to lock. The empty case is
    reachable from ``execute_portfolio``, which passes the entry_ids of the
    requirements it built and builds none when every reserved entry is fully
    locked. ``validate_template_preservation`` already fails closed on the same
    input; these two now agree.
    """
    mutable = None if mutable_entry_ids is None else {str(x) for x in mutable_entry_ids}
    before = {row.entry_id: row for row in parse_dk_entry_rows(source_path)}
    after = {row.entry_id: row for row in parse_dk_entry_rows(candidate_path)}
    errors, changed = [], []
    for entry_id, old in before.items():
        new = after.get(entry_id)
        if new is None:
            errors.append(f"Entry ID {entry_id} missing after late swap")
        elif old.roster_cells != new.roster_cells:
            changed.append(entry_id)
            if mutable is not None and entry_id not in mutable:
                errors.append(f"Entry ID {entry_id} changed without permission")
    return {"passed": not errors, "errors": errors, "changed_entry_ids": changed,
            "authorization": "unrestricted" if mutable is None
                             else f"{len(mutable)} authorized Entry ID(s)"}


def late_swap_certification(mode: str, optimization_result: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    if mode not in LATE_SWAP_MODES:
        raise ValueError(f"mode must be one of {sorted(LATE_SWAP_MODES)}")
    # R176(c), 2026-08-30. Both branches used to return
    # `forced_swap_validation_passed: True`, written unconditionally, for a
    # validation that does not exist anywhere in this tree. A certification key
    # whose value is a literal is not evidence, and it is worse than an absent key
    # because a later reader can treat it as one. It was harmless only because
    # nothing read it, which is a property of today's callers rather than of the
    # record. Deleted rather than renamed: there is no validation to name.
    if mode == "validate_only":
        return {
            "late_swap_optimization_performed": False,
            "selection_certified": False,
            "allocation_certified": False,
        }
    result = dict(optimization_result or {})
    passed = bool(result.get("passed")) and bool(result.get("selection_certified")) and bool(result.get("allocation_certified"))
    return {
        "late_swap_optimization_performed": True,
        "selection_certified": passed,
        "allocation_certified": passed,
    }


def cohort_refresh_plan(games: Sequence[GameLock], as_of: datetime) -> Dict[str, Any]:
    current = as_of if as_of.tzinfo else as_of.replace(tzinfo=timezone.utc)
    locked, upcoming = [], []
    for game in build_lock_cohorts(games):
        row = {"game_id": game.game_id, "start_time_utc": game.normalized_start().isoformat(), "lock_cohort": game.lock_cohort, "lineup_status": game.lineup_status}
        (locked if current.astimezone(timezone.utc) >= game.normalized_start() else upcoming).append(row)
    next_cohort = min((row["lock_cohort"] for row in upcoming), default=None)
    return {"locked_games": locked, "upcoming_games": upcoming, "next_lock_cohort": next_cohort}
