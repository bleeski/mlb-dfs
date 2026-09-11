"""Deterministic fictional fixtures. Never produce an uploadable live slate."""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from pathlib import Path

from .contracts import Controls
from .csvio import parse_entries, parse_salary
from .state import digest, json_bytes
from .workflow import run

AS_OF = datetime(2040, 7, 1, 21, tzinfo=timezone.utc)


def make_fixture(root: Path, mode: str = "CLASSIC", entry_count: int = 3) -> dict:
    root.mkdir(parents=True, exist_ok=False)
    teams = [("NYM", "ATL", "06:00PM"), ("BOS", "NYY", "07:00PM")]
    if mode == "SHOWDOWN":
        teams = teams[:1]
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(
        [
            "Position",
            "Name + ID",
            "Name",
            "ID",
            "Roster Position",
            "Salary",
            "Game Info",
            "TeamAbbrev",
            "AvgPointsPerGame",
        ]
    )
    serial = 1000
    positions = ["P", "C", "1B", "2B", "3B", "SS", "OF", "OF", "OF", "OF"]
    for away, home, start in teams:
        for team in (away, home):
            for index, position in enumerate(positions):
                serial += 1
                name = f"Fictional {team}, Player {index}"
                salary = 6500 if position == "P" else 3000 + index * 100
                for role in ("UTIL", "CPT") if mode == "SHOWDOWN" else (position,):
                    pid = str(serial + (10000 if role == "CPT" else 0))
                    writer.writerow(
                        [
                            position,
                            f"{name} ({pid})",
                            name,
                            pid,
                            role,
                            salary * 3 // 2 if role == "CPT" else salary,
                            f"{away}@{home} 07/01/2040 {start} ET",
                            team,
                            "999",
                        ]
                    )
    salary_raw = buffer.getvalue().encode("utf-8-sig")
    _, players = parse_salary(salary_raw)
    slots = (
        ("CPT", "UTIL", "UTIL", "UTIL", "UTIL", "UTIL")
        if mode == "SHOWDOWN"
        else ("P", "P", "C", "1B", "2B", "3B", "SS", "OF", "OF", "OF")
    )
    buf = io.StringIO(newline="")
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow(
        ["Entry ID", "Contest Name", "Contest ID", "Entry Fee", *slots, "Instructions"]
    )
    for i in range(entry_count):
        writer.writerow(
            [
                str(90000 + i),
                'Fictional "GPP", example',
                "80000",
                "$1.00",
                *([""] * len(slots)),
                "keep exactly",
            ]
        )
    writer.writerow(
        ["", "", "", "", *([""] * len(slots)), "Do not edit this embedded instruction"]
    )
    entries_raw = buf.getvalue().encode("utf-8-sig")
    source_raw = json_bytes(
        {
            "notice": "Fictional offline fixture; not real players, projections, or lineups."
        }
    )
    people = {p.person_id: p for p in players.values() if p.role != "CPT"}
    games = []
    for away, home, _ in teams:
        game_players = [p for p in people.values() if p.team in {away, home}]
        game = game_players[0]
        games.append(
            {
                "game_id": game.game_id,
                "event_id": "fixture_" + away + home,
                "away": away,
                "home": home,
                "start": game.start.isoformat(),
                "state": "scheduled",
                "weather": "clear",
                "source_id": "fixture",
                "weather_source_id": "fixture",
                "lineups": [
                    {
                        "team": t,
                        "ordered_ids": [
                            p.person_id
                            for p in game_players
                            if p.team == t and "P" not in p.positions
                        ],
                        "confirmed": True,
                        "source_id": "fixture",
                    }
                    for t in (away, home)
                ],
            }
        )
    bundle = {
        "schema_version": 1,
        "fixture": True,
        "sources": [
            {
                "source_id": "fixture",
                "uri": "fixture:fictional",
                "tier": 1,
                "observed_at": "2040-07-01T20:59:00+00:00",
                "expires_at": "2040-07-02T00:00:00+00:00",
                "artifact": "source.json",
                "sha256": digest(source_raw),
            }
        ],
        "games": games,
        "players": [
            {
                "player_id": p.person_id,
                "team": p.team,
                "game_id": p.game_id,
                "status": "probable_pitcher"
                if "P" in p.positions
                else "confirmed_starter",
                "source_id": "fixture",
            }
            for p in people.values()
        ],
        "projections": [
            {
                "player_id": p.person_id,
                "mean": 20.0 + int(p.person_id) % 7
                if "P" in p.positions
                else 6.0 + int(p.person_id) % 9,
                "stddev": 8.0,
                "ownership": 0.3
                if mode == "SHOWDOWN"
                else 0.5
                if "P" in p.positions
                else 8 / 36,
                "captain_ownership": 0.05 if mode == "SHOWDOWN" else None,
                "source_id": "fixture",
                "method": "supplied_dk_points",
            }
            for p in people.values()
        ],
        "contests": [{"contest_id": "80000", "shape": "large_gpp"}],
    }
    for name, raw in {
        "DKSalaries.csv": salary_raw,
        "DKEntries.csv": entries_raw,
        "source.json": source_raw,
        "evidence.json": json_bytes(bundle),
    }.items():
        (root / name).write_bytes(raw)
    return {
        "salary": root / "DKSalaries.csv",
        "entries": root / "DKEntries.csv",
        "evidence": root / "evidence.json",
        "output": root / "store",
    }


def execute_demo(root: Path) -> dict:
    paths = make_fixture(root)
    hashes = {k: digest(v.read_bytes()) for k, v in paths.items() if k != "output"}
    controls = Controls(total_seconds=60.0, simulations=512, max_candidates_per_entry=4)
    baseline = run(**paths, controls=controls, fixture_mode=True, as_of=AS_OF)
    if baseline["status"] != "validated_export":
        return {"status": "failed", "baseline": baseline}
    _, players = parse_salary(paths["salary"].read_bytes())
    parent = root / "parent.csv"
    parent.write_bytes(Path(baseline["safe_export"]).read_bytes())
    entries = parse_entries(parent.read_bytes()).entries
    # Scratch a selected late-game outfielder; the early game is already locked.
    scratch = next(
        pid
        for e in entries
        for pid in e.roster
        if players[pid].team in {"BOS", "NYY"} and "OF" in players[pid].positions
    )
    updated = json.loads(paths["evidence"].read_bytes())
    updated["sources"][0]["observed_at"] = "2040-07-01T22:29:00+00:00"
    next(p for p in updated["players"] if p["player_id"] == scratch)["status"] = (
        "confirmed_out"
    )
    # A reported scratch removes confirmation pending a fresh complete batting order.
    for game in updated["games"]:
        for side in game["lineups"]:
            if scratch in side["ordered_ids"]:
                side["ordered_ids"].remove(scratch)
                side["confirmed"] = False
    scratch_path = root / "scratch_evidence.json"
    scratch_path.write_bytes(json_bytes(updated))
    late = run(
        paths["salary"],
        parent,
        scratch_path,
        paths["output"],
        controls=controls.model_copy(update={"enhance": False}),
        authorized_entry_ids={e.entry_id for e in entries},
        parent=parent,
        fixture_mode=True,
        as_of=datetime(2040, 7, 1, 22, 30, tzinfo=timezone.utc),
    )
    unchanged = hashes == {k: digest(paths[k].read_bytes()) for k in hashes}
    result = {
        "status": "verified"
        if late["status"] == "validated_export" and unchanged
        else "failed",
        "label": "OFFLINE_FIXTURE_DO_NOT_UPLOAD",
        "baseline": baseline,
        "late_swap": late,
        "scratch_id": scratch,
        "raw_inputs_unchanged": unchanged,
    }
    (root / "demo_result.json").write_bytes(json_bytes(result))
    return result
