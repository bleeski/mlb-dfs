"""Independent final-byte legality, authorization and whole-portfolio checks."""

from __future__ import annotations

from collections import Counter
from datetime import datetime

from mlb_engine.optimize.roster_contracts import get_contract
from .contracts import Controls, Player
from .csvio import Template, verify_template
from .evidence import Prepared
from .optimizer import count_cap, signature


def inspect_export(
    template: Template,
    raw: bytes,
    players: dict[str, Player],
    prepared: Prepared,
    controls: Controls,
    now: datetime,
    mutable_ids: set[str],
) -> dict:
    after = verify_template(template, raw, mutable_ids)
    old_entries = {e.entry_id: e for e in template.entries}
    errors, warnings = [], list(prepared.warnings)
    pc, pitchers, captains, teams, games = (Counter() for _ in range(5))
    primary_counts, pair_counts = Counter(), Counter()
    signatures, sets, salary_by_entry = {}, {}, {}
    game_state = {g.game_id: g.state for g in prepared.bundle.games}
    slots = get_contract(after.mode).slots
    for entry in after.entries:
        old = old_entries[entry.entry_id]
        if entry.contest_id != old.contest_id or entry.fee_cents != old.fee_cents:
            errors.append("entry contest or fee changed")
        roster = entry.roster
        if (
            not all(roster)
            or len(roster) != len(slots)
            or any(pid not in players for pid in roster)
        ):
            errors.append(
                f"{entry.entry_id}: incomplete roster or ID outside salary pool"
            )
            continue
        selected = [players[x] for x in roster]
        people = {p.person_id for p in selected}
        if len(people) != len(slots):
            errors.append(f"{entry.entry_id}: duplicate physical player")
        salary = sum(p.salary for p in selected)
        salary_by_entry[entry.entry_id] = salary
        if salary > 50000 or salary < controls.salary_floor:
            errors.append(f"{entry.entry_id}: salary constraint")
        for s, (slot, p) in enumerate(zip(slots, selected)):
            if p.role != slot if after.mode == "SHOWDOWN" else slot not in p.positions:
                errors.append(f"{entry.entry_id}: positional violation at slot {s}")
            locked = now >= p.start or game_state[p.game_id] in {"in_progress", "final"}
            old_pid = old.roster[s]
            if old_pid and old_pid in players:
                op = players[old_pid]
                old_locked = now >= op.start or game_state[op.game_id] in {
                    "in_progress",
                    "final",
                }
                if old_locked and p.player_id != old_pid:
                    errors.append(f"{entry.entry_id}: locked slot changed")
            if locked and old_pid != p.player_id:
                errors.append(f"{entry.entry_id}: new locked player")
            if p.player_id not in prepared.eligible:
                if locked and old_pid == p.player_id:
                    warnings.append(
                        f"immutable unavailable player carried forward: {p.person_id}"
                    )
                else:
                    errors.append(f"{entry.entry_id}: unavailable player {p.person_id}")
        ht = Counter(p.team for p in selected if "P" not in p.positions)
        stack_counts = Counter(
            p.team
            for p in selected
            if after.mode == "SHOWDOWN" or "P" not in p.positions
        )
        primary = (
            min(stack_counts, key=lambda t: (-stack_counts[t], t))
            if stack_counts
            else ""
        )
        primary_counts[primary] += 1
        if stack_counts.get(primary, 0) < controls.primary_stack_min_size:
            errors.append(f"{entry.entry_id}: primary stack minimum")
        if after.mode == "CLASSIC":
            pair_counts[tuple(sorted(roster[:2]))] += 1
        if after.mode == "CLASSIC":
            if sum("P" in p.positions for p in selected) != 2:
                errors.append(f"{entry.entry_id}: must contain exactly two pitchers")
            if (
                len({p.game_id for p in selected}) < 2
                or max(ht.values(), default=0) > 5
            ):
                errors.append(f"{entry.entry_id}: Classic game/team rule")
        elif len({p.team for p in selected}) != 2:
            errors.append(f"{entry.entry_id}: Showdown must represent both teams")
        allowance = controls.max_opposing_hitters_per_sp
        if allowance is None:
            allowance = 0 if after.mode == "CLASSIC" else len(slots)
        for p in selected:
            if "P" in p.positions:
                facing = sum(
                    "P" not in h.positions
                    and h.team == p.opponent
                    and h.game_id == p.game_id
                    for h in selected
                )
                if facing > allowance:
                    errors.append(f"{entry.entry_id}: opposing-pitcher policy")
        if controls.stack_team:
            stack = Counter(
                p.team
                for p in selected
                if after.mode == "SHOWDOWN" or "P" not in p.positions
            )
            if (
                not controls.stack_min
                <= stack[controls.stack_team]
                <= controls.stack_max
            ):
                errors.append(f"{entry.entry_id}: requested stack size")
            opponent = next(
                p.opponent for p in players.values() if p.team == controls.stack_team
            )
            if stack[opponent] < controls.bringback_min:
                errors.append(f"{entry.entry_id}: bring-back minimum")
        sig = signature(roster, after.mode)
        key = (entry.contest_id, sig)
        if key in signatures:
            errors.append(f"{entry.entry_id}: same-contest duplicate lineup")
        signatures[key] = entry.entry_id
        sets[entry.entry_id] = people
        pc.update(people)
        pitchers.update({p.person_id for p in selected if "P" in p.positions})
        if after.mode == "SHOWDOWN":
            captains.update([selected[0].person_id])
        teams.update({p.team for p in selected})
        games.update({p.game_id for p in selected})
    n = len(after.entries)
    for label, counter, fraction in (
        ("player", pc, controls.max_player_exposure),
        ("pitcher", pitchers, controls.max_pitcher_exposure),
        ("captain", captains, controls.max_captain_exposure),
        ("primary_stack", primary_counts, controls.max_primary_stack_exposure),
    ):
        cap = count_cap(fraction, n)
        errors.extend(
            f"{label} exposure {k}: {v}>{cap}" for k, v in counter.items() if v > cap
        )
    if controls.max_sp_pair_repetition is not None:
        errors.extend(
            f"SP pair exposure {k}: {v}>{controls.max_sp_pair_repetition}"
            for k, v in pair_counts.items()
            if v > controls.max_sp_pair_repetition
        )
    for label, counter, limits in (
        ("team", teams, controls.max_team_exposure),
        ("game", games, prepared.game_caps),
    ):
        for key, fraction in limits.items():
            if counter[key] > count_cap(fraction, n):
                errors.append(f"{label} exposure {key}")
    max_shared = 0
    for i, (eid, people) in enumerate(sets.items()):
        for other_id in list(sets)[i + 1 :]:
            overlap = len(people & sets[other_id])
            max_shared = max(max_shared, overlap)
            if (
                controls.max_shared_players is not None
                and overlap > controls.max_shared_players
            ):
                errors.append(f"overlap: {eid}/{other_id} share {overlap}")
    if pc and max(pc.values()) == n and n > 1:
        warnings.append("at least one player is present in every entry")
    return {
        "FILE_VALID": not errors,
        "errors": sorted(set(errors)),
        "warnings": sorted(set(warnings)),
        "entry_count": n,
        "salary_by_entry": salary_by_entry,
        "max_shared_players": max_shared,
        "player_counts": dict(sorted(pc.items())),
        "pitcher_counts": dict(sorted(pitchers.items())),
        "captain_counts": dict(sorted(captains.items())),
        "team_counts": dict(sorted(teams.items())),
        "game_counts": dict(sorted(games.items())),
        "raw_template_preserved": True,
        "primary_stack_counts": dict(sorted(primary_counts.items())),
        "sp_pair_counts": {"/".join(k): v for k, v in sorted(pair_counts.items())},
    }
