"""Human-readable data intake sheets; factual data entry never requires code."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from .contracts import EvidenceBundle, infer_shape
from .csvio import parse_entries, parse_salary
from .evidence import confined_source, read_bounded
from .state import atomic_write, digest, json_bytes


def write_table(path: Path, columns: list[str], rows: list[dict]):
    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=columns, lineterminator="\r\n")
    writer.writeheader()
    writer.writerows(rows)
    path.write_bytes(out.getvalue().encode("utf-8-sig"))


def create_intake(salary: Path, entries: Path, root: Path) -> dict:
    # Refuse to overwrite an earlier intake packet or raw platform downloads.
    salary_raw, entries_raw = read_bounded(salary), read_bounded(entries)
    mode, players = parse_salary(salary_raw)
    template = parse_entries(entries_raw)
    if mode != template.mode:
        raise ValueError("salary and entry formats disagree")
    root.mkdir(parents=True, exist_ok=False)
    (root / "DKSalaries.csv").write_bytes(salary_raw)
    (root / "DKEntries.csv").write_bytes(entries_raw)
    people = {p.person_id: p for p in players.values() if p.role != "CPT"}
    games = {}
    for p in people.values():
        away, home = p.game_id.split("|", 1)[0].split("@")
        games[p.game_id] = dict(
            game_id=p.game_id,
            event_id="",
            away=away,
            home=home,
            start=p.start.isoformat(),
            state="unknown",
            weather="unknown",
            source_id="",
            weather_source_id="",
        )
    write_table(
        root / "games.csv", list(next(iter(games.values()))), list(games.values())
    )
    rows = [
        dict(
            player_id=p.person_id,
            team=p.team,
            game_id=p.game_id,
            status="unknown",
            source_id="",
        )
        for p in people.values()
    ]
    write_table(root / "players.csv", list(rows[0]), rows)
    rows = [
        dict(
            player_id=p.person_id,
            mean="",
            stddev="",
            ownership="",
            captain_ownership="",
            source_id="",
            method="supplied_dk_points",
        )
        for p in people.values()
    ]
    write_table(root / "projections.csv", list(rows[0]), rows)
    write_table(
        root / "sources.csv",
        ["source_id", "uri", "tier", "observed_at", "expires_at", "artifact"],
        [],
    )
    write_table(
        root / "lineups.csv",
        ["game_id", "team", "ordered_ids", "confirmed", "source_id"],
        [],
    )
    contests = {}
    for e in template.entries:
        contests[e.contest_id] = {
            "contest_id": e.contest_id,
            "shape": infer_shape(e.name) or "",
        }
    write_table(root / "contests.csv", ["contest_id", "shape"], list(contests.values()))
    (root / "READ_ME.md").write_text(
        "# Slate intake\n\n"
        "Open the CSV tables in Excel or another spreadsheet editor. They contain facts, not programming. "
        "Player IDs, teams, game IDs and start times came directly from your salary file; keep them unchanged.\n\n"
        "1. Put saved source files beside these tables, or in a subfolder. In sources.csv enter a short source ID, "
        "its original URL, tier (1 official/league/weather/market; 2 quantitative model; 3 verified context), "
        "observed_at and expires_at with a timezone, and its relative filename. Never include credentials.\n"
        "2. In games.csv enter the provider event ID, state (scheduled/in_progress/final/postponed/cancelled/suspended), "
        "weather (clear/closed_roof/medium/high), and source IDs. Unknown blocks the build.\n"
        "3. In players.csv enter confirmed_starter, projected_starter, probable_pitcher, confirmed_out or bench, "
        "with its source ID. Pitchers require probable_pitcher or confirmed_starter. Unknown players are excluded.\n"
        "4. In projections.csv enter expected DraftKings points and the source ID for every eligible player. "
        "Standard deviations enable optional simulation. Ownership is a fraction from 0 to 1. "
        "Leave unavailable optional values blank; do not substitute fantasy-point averages.\n"
        "5. In contests.csv choose cash, small_gpp, large_gpp or wta using the actual contest. "
        "Payout-aware scoring additionally needs a complete prize curve and opponent field from a verified provider.\n"
        "6. Optionally fill lineups.csv: ordered_ids are nine canonical IDs separated by semicolons, "
        "confirmed is true or false, and source_id identifies the saved lineup evidence.\n\n"
        "Run `python tools/dfs.py freeze --input PATH_TO_THIS_FOLDER` from the project folder. "
        "Then use the run command in the project runbook. Missing data produces an explicit refusal. "
        "The supplied moments remain uncalibrated priors until independently validated.\n",
        encoding="utf-8",
    )
    return {
        "status": "intake_created",
        "input_folder": str(root.resolve()),
        "next_action": "Supply verified facts in the CSV sheets, then run freeze. No live data was fabricated.",
    }


def freeze_intake(root: Path) -> dict:
    def rows(name):
        raw = read_bounded(root / name)
        return list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))

    sources = rows("sources.csv")
    for s in sources:
        s["tier"] = int(s["tier"])
        s["sha256"] = digest(read_bounded(confined_source(root, s["artifact"])))
    games = rows("games.csv")
    by_game = {g["game_id"]: g for g in games}
    for side in rows("lineups.csv"):
        gid = side.pop("game_id")
        if gid not in by_game:
            raise ValueError("lineup refers to an unknown game")
        if side["confirmed"].lower() not in {"true", "false"}:
            raise ValueError("lineup confirmed must be true or false")
        side["confirmed"] = side["confirmed"].lower() == "true"
        side["ordered_ids"] = [
            x.strip() for x in side["ordered_ids"].split(";") if x.strip()
        ]
        by_game[gid].setdefault("lineups", []).append(side)
    projections = []
    for p in rows("projections.csv"):
        if not p["mean"].strip():
            continue  # prepare subsequently refuses any eligible player without a mean.
        for key in ("mean", "stddev", "ownership", "captain_ownership"):
            p[key] = float(p[key]) if p[key].strip() else None
        projections.append(p)
    data = {
        "schema_version": 1,
        "fixture": False,
        "sources": sources,
        "games": games,
        "players": rows("players.csv"),
        "projections": projections,
        "contests": rows("contests.csv"),
    }
    bundle = EvidenceBundle.model_validate_json(json.dumps(data, allow_nan=False))
    target = root / (
        "evidence_" + digest(bundle.model_dump_json().encode())[:16] + ".json"
    )
    raw = json_bytes(bundle.model_dump(mode="json"))
    if target.exists() and target.read_bytes() != raw:
        raise ValueError("frozen evidence filename collision")
    if not target.exists():
        atomic_write(target, raw)
    return {
        "status": "evidence_frozen",
        "evidence": str(target.resolve()),
        "next_action": "Run with DKSalaries.csv, DKEntries.csv and this evidence file. Freshness is checked at execution.",
    }
